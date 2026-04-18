"""
app.py — JARVIS menu bar application.

Entry point: run with `.venv/bin/python app.py` from the menubar/ directory,
or via the launchd agent installed by setup.sh.

Architecture:
  - @rumps.timer(10)  → _health_tick: runs health checks on the main thread
    every 10 s and updates menu items.
  - @rumps.timer(300) → _inactivity_tick: checks idle timers every 5 minutes.
  - All shared state (_loaded, _health) is protected with a threading.Lock.
  - UI writes always happen on the main thread (rumps timer callbacks).
    Background threads (toggle, quick-chat) use AppHelper.callAfter for UI.
"""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

# Ensure sibling modules (services, health, memory, chat, inactivity) are importable
# regardless of the working directory the process was started from.
sys.path.insert(0, str(Path(__file__).parent))

import chat
import health as hlth
import inactivity as inact
import memory as mem
import rumps
import services as svc
from PyObjCTools import AppHelper

# ── osascript dialog helpers ─────────────────────────────────────────────────
# These run osascript as a child process, completely outside the app's run
# loop.  That makes them safe to call from background threads with no risk of
# deadlocking against NSStatusBar's event-tracking run-loop mode.


def _osa_safe(text: str) -> str:
    """Sanitise text for embedding in an AppleScript double-quoted string."""
    return text.replace("\\", "/").replace('"', "'").replace("\n", "  ").replace("\r", "")


def _osa_alert(message: str, title: str = "JARVIS") -> None:
    """Show a simple OK-only alert.  Blocks the calling thread until dismissed."""
    script = (
        f'display dialog "{_osa_safe(message)}" '
        f'with title "{_osa_safe(title)}" '
        'buttons {"OK"} default button "OK"'
    )
    subprocess.run(["osascript", "-e", script], capture_output=True)


def _osa_confirm(
    message: str,
    title: str = "JARVIS",
    ok: str = "OK",
    cancel: str = "Cancel",
) -> bool:
    """Two-button dialog.  Returns True if the user clicked *ok*."""
    script = (
        f'display dialog "{_osa_safe(message)}" '
        f'with title "{_osa_safe(title)}" '
        f'buttons {{"{cancel}", "{ok}"}} default button "{ok}"'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.returncode == 0 and f"button returned:{ok}" in result.stdout


def _osa_input(prompt: str, title: str = "JARVIS") -> str | None:
    """Input dialog.  Returns the entered text, or None if the user cancelled."""
    script = (
        f'display dialog "{_osa_safe(prompt)}" '
        'default answer "" '
        f'with title "{_osa_safe(title)}" '
        'buttons {"Cancel", "Send"} default button "Send"'
    )
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    for part in result.stdout.strip().split(", "):
        if part.startswith("text returned:"):
            return part[len("text returned:") :]
    return None


# ── Constants ─────────────────────────────────────────────────────────────────

STATUS_RUNNING = "●"  # loaded + healthy
STATUS_LOADING = "◐"  # loaded but health check failing (starting / crashed)
STATUS_STOPPED = "○"  # not loaded

ICON_OK = "🧃"
ICON_WARN = "⚠️"
ICON_IDLE = "○"

CONFIG_PATH = Path.home() / ".jarvis" / "menubar_config.json"
LOCK_PATH = Path("/tmp/jarvis-menubar.lock")

# Module-level reference keeps the lock fd open (and flock held) for the
# lifetime of the process.  Released automatically on process exit/crash.
_LOCK_FILE: object = None


def _acquire_single_instance_lock() -> bool:
    """Return True if this is the only running instance, False otherwise."""
    global _LOCK_FILE  # noqa: PLW0603
    try:
        _LOCK_FILE = LOCK_PATH.open("w")
        fcntl.flock(_LOCK_FILE.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        _LOCK_FILE.write(str(os.getpid()))
        _LOCK_FILE.flush()
        return True
    except OSError:
        return False


DEFAULT_CONFIG: dict = {
    "inactivity_timeout_minutes": 30,
    "health_check_interval_seconds": 10,
    "memory_warning_threshold_gb": 20,
    "chat_model": "qwen3.5:9b",
    "ollama_keep_alive": "10m",
}

# Services for which we track inactivity and auto-unload.
INACTIVITY_SERVICES = {"com.whisper.server", "com.kokoro.server"}


# ── Config ────────────────────────────────────────────────────────────────────


def load_config() -> dict:
    """Load config from ~/.jarvis/menubar_config.json, writing defaults if absent."""
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open() as f:
                on_disk = json.load(f)
            # Merge so newly added keys always have defaults.
            return {**DEFAULT_CONFIG, **on_disk}
        except json.JSONDecodeError, OSError:
            pass
    # First run — write defaults.
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2)
    return dict(DEFAULT_CONFIG)


# ── App ───────────────────────────────────────────────────────────────────────


class JarvisApp(rumps.App):
    def __init__(self) -> None:
        super().__init__(name="JARVIS", title=ICON_IDLE, quit_button=None)
        self._config = load_config()
        self._lock = threading.Lock()

        # Per-service health and loaded state (keyed by service.plist label).
        self._loaded: dict[str, bool] = {s.plist: False for s in svc.SERVICES}
        self._health: dict[str, bool] = {s.plist: False for s in svc.SERVICES}

        # MenuItem references so we can update titles without rebuilding the menu.
        self._service_items: dict[str, rumps.MenuItem] = {}

        # Inactivity watchers for Whisper + Kokoro.
        timeout = self._config["inactivity_timeout_minutes"]
        self._watchers: dict[str, inact.InactivityWatcher] = {
            s.plist: inact.InactivityWatcher(s, timeout)
            for s in svc.SERVICES
            if s.plist in INACTIVITY_SERVICES
        }

        self._build_menu()

        # Run an initial health refresh via a one-shot timer so the app finishes
        # initialising on the main thread before any UI writes happen.
        rumps.Timer(self._initial_refresh, 0.1).start()

    # ── Menu construction ─────────────────────────────────────────────────────

    def _build_menu(self) -> None:
        items: list = []

        for service in svc.SERVICES:
            mi = rumps.MenuItem(
                f"{STATUS_STOPPED} {service.name}",
                callback=self._make_toggle_cb(service),
            )
            self._service_items[service.plist] = mi
            items.append(mi)

        items.append(rumps.separator)

        # Informational (no-op callback keeps them visually consistent).
        self._mem_item = rumps.MenuItem("Memory: — / — GB used")
        self._mem_item.set_callback(None)
        self._ollama_item = rumps.MenuItem("Ollama: —")
        self._ollama_item.set_callback(None)
        items += [self._mem_item, self._ollama_item, rumps.separator]

        items += [
            rumps.MenuItem("Quick Chat", callback=self._quick_chat),
            rumps.MenuItem("Open Dashboard", callback=self._open_dashboard),
            rumps.separator,
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]

        self.menu = items

    # ── Toggle callback factory ───────────────────────────────────────────────

    def _make_toggle_cb(self, service: svc.Service):
        """Return a closure that toggles the given service."""

        def _toggle(_sender):
            self._on_toggle(service)

        return _toggle

    def _on_toggle(self, service: svc.Service) -> None:
        # Spawn a thread immediately so the menu callback returns at once and
        # NSMenu can fully dismiss.  All blocking work (launchctl, osascript)
        # happens off the main thread.
        threading.Thread(target=self._run_toggle, args=(service,), daemon=True).start()

    def _run_toggle(self, service: svc.Service) -> None:
        if not svc.plist_exists(service):
            _osa_alert(f"{service.name} is not installed on this system.")
            return
        with self._lock:
            currently_loaded = self._loaded.get(service.plist, False)
        AppHelper.callAfter(lambda: setattr(self, "title", "🟡"))
        if currently_loaded:
            svc.unload_service(service)
        else:
            svc.load_service(service)
        self._refresh_one(service)
        AppHelper.callAfter(self._update_icon)

    def _initial_refresh(self, sender) -> None:
        sender.stop()
        self._do_health_refresh()

    # ── Health timer (every 10 s) ─────────────────────────────────────────────

    @rumps.timer(10)
    def _health_tick(self, _sender) -> None:
        self._do_health_refresh()

    def _do_health_refresh(self) -> None:
        """Check all services, update state, and refresh menu labels."""
        for service in svc.SERVICES:
            self._refresh_one(service)
        self._update_memory()
        self._update_icon()

    def _refresh_one(self, service: svc.Service) -> None:
        loaded = svc.is_loaded(service)
        healthy = hlth.check_health(service) if loaded else False

        with self._lock:
            self._loaded[service.plist] = loaded
            self._health[service.plist] = healthy

        # Update inactivity watcher if applicable.
        watcher = self._watchers.get(service.plist)
        if watcher is not None and healthy:
            watcher.record_activity()

        self._update_service_item(service, loaded, healthy)

    def _update_service_item(self, service: svc.Service, loaded: bool, healthy: bool) -> None:
        if not loaded:
            prefix = STATUS_STOPPED
        elif healthy:
            prefix = STATUS_RUNNING
        else:
            prefix = STATUS_LOADING
        item = self._service_items.get(service.plist)
        if item is not None:
            item.title = f"{prefix} {service.name}"

    # ── Inactivity timer (every 5 min) ────────────────────────────────────────

    @rumps.timer(300)
    def _inactivity_tick(self, _sender) -> None:
        self._do_inactivity_check()

    def _do_inactivity_check(self) -> None:
        for plist_label, watcher in self._watchers.items():
            with self._lock:
                if not self._loaded.get(plist_label, False):
                    continue
            if watcher.check_and_unload():
                service = svc.SERVICES_BY_PLIST[plist_label]
                rumps.notification(
                    title="JARVIS",
                    subtitle="Service auto-unloaded",
                    message=(
                        f"{service.name} was idle for "
                        f"{self._config['inactivity_timeout_minutes']} minutes "
                        "and has been stopped."
                    ),
                )
                # Sync state after unload.
                self._refresh_one(service)
                self._update_icon()

    # ── Memory / Ollama display ───────────────────────────────────────────────

    def _update_memory(self) -> None:
        used_gb, total_gb = mem.get_system_memory_gb()
        threshold = self._config["memory_warning_threshold_gb"]
        self._mem_item.title = mem.format_memory_line(used_gb, total_gb, threshold)

        models = mem.get_ollama_loaded_models()
        self._ollama_item.title = mem.format_ollama_line(models)

    # ── Icon update ───────────────────────────────────────────────────────────

    def _update_icon(self) -> None:
        with self._lock:
            loaded_plists = [p for p, v in self._loaded.items() if v]
        if not loaded_plists:
            self.title = ICON_IDLE
        elif all(self._health.get(p, False) for p in loaded_plists):
            self.title = ICON_OK
        else:
            self.title = ICON_WARN

    # ── Quick Chat ────────────────────────────────────────────────────────────

    def _quick_chat(self, _sender) -> None:
        threading.Thread(target=self._run_quick_chat, daemon=True).start()

    def _run_quick_chat(self) -> None:
        prompt = _osa_input("Ask JARVIS:")
        if not prompt or not prompt.strip():
            return
        AppHelper.callAfter(lambda: setattr(self, "title", "🤔"))
        answer = chat.query_ollama(prompt.strip(), self._config["chat_model"])
        AppHelper.callAfter(self._update_icon)
        _osa_alert(answer)

    # ── Open Dashboard ────────────────────────────────────────────────────────

    def _open_dashboard(self, _sender) -> None:
        threading.Thread(target=self._run_open_dashboard, daemon=True).start()

    def _run_open_dashboard(self) -> None:
        with self._lock:
            webui_healthy = self._health.get("com.openwebui", False)
            webui_loaded = self._loaded.get("com.openwebui", False)

        if not webui_loaded:
            if not svc.plist_exists(svc.SERVICES_BY_PLIST["com.openwebui"]):
                _osa_alert("Open WebUI is not installed. Run menubar/setup.sh to install it.")
                return
            if not _osa_confirm("Open WebUI is not running. Start it now?", ok="Start"):
                return
            svc.load_service(svc.SERVICES_BY_PLIST["com.openwebui"])
            _osa_alert(
                "Open WebUI is starting. It may take 30-60 s on the first run. "
                "Opening the dashboard now — refresh if it doesn't load immediately."
            )
        elif not webui_healthy:
            if not _osa_confirm(
                "Open WebUI is starting up — the page may not load yet.",
                ok="Open anyway",
                cancel="Wait",
            ):
                return

        subprocess.run(["open", "http://127.0.0.1:3000"], check=False)


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    if not _acquire_single_instance_lock():
        # Another instance is already running — exit silently.
        sys.exit(0)
    JarvisApp().run()


if __name__ == "__main__":
    main()

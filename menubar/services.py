"""
services.py — launchd service definitions and control functions.

Each JARVIS service is represented as a Service dataclass. Control is via
launchctl load/unload. The Ollama service uses its Homebrew-managed plist
(homebrew.mxcl.ollama) rather than a custom one.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# ── Constants ─────────────────────────────────────────────────────────────────

LAUNCH_AGENTS_DIR = Path.home() / "Library" / "LaunchAgents"


# ── Service dataclass ─────────────────────────────────────────────────────────


@dataclass
class Service:
    name: str
    plist: str  # launchd label, e.g. "com.whisper.server"
    plist_path: str  # absolute path to the .plist file
    health_url: str  # HTTP URL to GET for liveness; "" → use process_name check
    memory_mb: int  # approximate RAM in MB; 0 = dynamic (Ollama reads from /api/ps)
    process_name: str = field(default="")  # psutil process name when health_url is empty


def _agent_plist(label: str) -> str:
    return str(LAUNCH_AGENTS_DIR / f"{label}.plist")


# ── Service registry ──────────────────────────────────────────────────────────

SERVICES: list[Service] = [
    Service(
        name="STT — Whisper Server",
        plist="com.whisper.server",
        plist_path=_agent_plist("com.whisper.server"),
        health_url="http://127.0.0.1:2022/inference",
        memory_mb=1500,
    ),
    Service(
        name="STT — Dictation Hotkey",
        plist="com.whisper.dictate",
        plist_path=_agent_plist("com.whisper.dictate"),
        health_url="",
        memory_mb=80,
        process_name="jarvis-dictate",
    ),
    Service(
        name="TTS — Kokoro",
        plist="com.kokoro.server",
        plist_path=_agent_plist("com.kokoro.server"),
        health_url="http://127.0.0.1:8880/health",
        memory_mb=300,
    ),
    Service(
        # Managed by Homebrew; plist label differs from the jarvis convention.
        name="LLM — Ollama",
        plist="homebrew.mxcl.ollama",
        plist_path=_agent_plist("homebrew.mxcl.ollama"),
        health_url="http://127.0.0.1:11434/api/tags",
        memory_mb=0,  # dynamic — read live from /api/ps in memory.py
    ),
    Service(
        name="Open WebUI",
        plist="com.openwebui",
        plist_path=_agent_plist("com.openwebui"),
        health_url="http://127.0.0.1:3000",
        memory_mb=300,
    ),
]

# Lookup by plist label for O(1) access elsewhere.
SERVICES_BY_PLIST: dict[str, Service] = {s.plist: s for s in SERVICES}


# ── launchd control ───────────────────────────────────────────────────────────


def plist_exists(service: Service) -> bool:
    """Return True if the plist file is present (service is installable)."""
    return Path(service.plist_path).exists()


def load_service(service: Service) -> bool:
    """
    Start a launchd agent.

    Strategy:
      1. If the plist is not yet registered with launchd, run
         `launchctl load -w <plist>` to register AND start it.
      2. If it is already registered (but stopped), `launchctl load` would
         fail silently.  Use `launchctl kickstart` instead, which starts an
         already-registered service unconditionally.

    Returns True if the process appears to have started; False otherwise.
    """
    if not plist_exists(service):
        return False

    uid = os.getuid()
    domain_target = f"gui/{uid}/{service.plist}"

    # Try kickstart first — works whether or not the plist is registered.
    # -k = kill any existing instance first (safe no-op if not running).
    result = subprocess.run(
        ["launchctl", "kickstart", "-k", domain_target],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True

    # kickstart fails if the service isn't registered yet → load it first.
    subprocess.run(
        ["launchctl", "load", "-w", service.plist_path],
        capture_output=True,
        text=True,
    )
    # Now kick it.
    result = subprocess.run(
        ["launchctl", "kickstart", "-k", domain_target],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def unload_service(service: Service) -> bool:
    """
    Stop a launchd agent and prevent it auto-restarting.

    Uses `launchctl kill SIGTERM` to stop the running process, then
    `launchctl unload -w` to remove the Disabled=false flag so it won't
    restart at next login.

    Returns True on success; False if the plist is missing or launchctl fails.
    """
    if not plist_exists(service):
        return False
    uid = os.getuid()
    domain_target = f"gui/{uid}/{service.plist}"
    # Stop the running process (ignore errors — may already be stopped).
    subprocess.run(
        ["launchctl", "kill", "SIGTERM", domain_target],
        capture_output=True,
        text=True,
    )
    # Mark disabled so it won't auto-start at next login.
    result = subprocess.run(
        ["launchctl", "unload", "-w", service.plist_path],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def is_loaded(service: Service) -> bool:
    """
    Return True if launchd has this service registered AND the process is
    actually running (PID column is not '-' in `launchctl list` output).

    `launchctl list` prints tab-separated lines: PID\\tLAST_EXIT\\tLABEL.
    A running process has a numeric PID; a registered-but-stopped job has '-'.
    Using `launchctl list <label>` (with a label) returns 0 even for stopped
    jobs, so we use the plain `launchctl list` and search for our label.
    """
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2].strip() == service.plist:
            pid = parts[0].strip()
            return pid != "-"
    return False

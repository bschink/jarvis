#!/usr/bin/env python3
"""
System-wide "read this to me" hotkey daemon for JARVIS.
Press Ctrl+Shift+F5 to speak whatever text is selected in any app.
Press Ctrl+Shift+F5 again while speaking to stop playback immediately.

Flow: hotkey → Cmd+C → read clipboard → restore clipboard → speak via tts-router.py
"""

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time

from pynput import keyboard

sys.path.insert(0, os.path.dirname(__file__))
from jarvis_config import (
    HEARTBEAT_INTERVAL_S,
)
from jarvis_config import (
    NARRATE_COPY_DELAY as COPY_DELAY,
)
from jarvis_config import (
    NARRATE_TTS_PYTHON as TTS_PYTHON,
)
from jarvis_config import (
    NARRATE_TTS_SCRIPT as TTS_SCRIPT,
)
from jarvis_log import log

_SVC = "tts-narrate"


def _start_heartbeat() -> None:
    import time
    from pathlib import Path

    path = Path(f"/tmp/jarvis-{_SVC}.heartbeat")
    while True:
        path.write_text(str(time.time()))
        time.sleep(HEARTBEAT_INTERVAL_S)


threading.Thread(target=_start_heartbeat, daemon=True).start()

# Toggle combo: Ctrl+Shift+F5
HOTKEY = {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.f5}

# ── State ─────────────────────────────────────────────────────────────────────

current_keys = set()
_speaking = threading.Event()  # set = currently speaking, clear = idle
triggered = False  # hotkey was pressed, waiting for release to fire
tts_proc = None  # current TTS subprocess (Popen handle)

# ── Clipboard helpers ─────────────────────────────────────────────────────────


def clipboard_read() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout


def clipboard_write(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True)


def copy_selection() -> str:
    """Simulate Cmd+C, wait, return clipboard contents."""
    subprocess.run(
        ["osascript", "-e", 'tell application "System Events" to keystroke "c" using command down']
    )
    time.sleep(COPY_DELAY)
    return clipboard_read()


# ── TTS ───────────────────────────────────────────────────────────────────────


def speak(text: str) -> None:
    global tts_proc
    proc = subprocess.Popen(
        [TTS_PYTHON, TTS_SCRIPT, "--long", text],
        start_new_session=True,
    )
    tts_proc = proc
    try:
        proc.wait(timeout=300)  # 5 min hard ceiling; Qwen3-TTS is slow but not infinite
    except subprocess.TimeoutExpired:
        log(_SVC, "ERROR", "TTS timed out — killing process")
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception as e:
        log(_SVC, "ERROR", f"TTS error: {e}")
    finally:
        tts_proc = None
        _speaking.clear()


def stop_speaking() -> None:
    global tts_proc
    proc = tts_proc
    if proc is not None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        log(_SVC, "INFO", "playback stopped")


# ── Hotkey handler ────────────────────────────────────────────────────────────


def _hotkey_complete(current_keys: set, hotkey: set) -> bool:
    """Return True iff current_keys exactly equals the hotkey combo. Pure function."""
    return current_keys == hotkey


def on_press(key: keyboard.Key) -> None:
    global triggered
    current_keys.add(key)
    if current_keys == HOTKEY:
        triggered = True


def on_release(key: keyboard.Key) -> None:
    global triggered
    current_keys.discard(key)
    if not triggered:
        return
    # Fire once all hotkey keys are released (modifiers no longer held)
    if any(k in current_keys for k in HOTKEY):
        return
    triggered = False

    if _speaking.is_set():
        stop_speaking()
        return

    saved = clipboard_read()
    text = copy_selection()
    clipboard_write(saved)

    text = text.strip()
    if not text:
        log(_SVC, "WARN", "hotkey pressed but no text selected")
        return

    max_chars = 100_000
    if len(text) > max_chars:
        log(_SVC, "WARN", f"clipboard too large ({len(text)} chars), truncating to {max_chars}")
        text = text[:max_chars]

    log(_SVC, "INFO", f"narrating {len(text)} chars")
    _speaking.set()
    threading.Thread(target=speak, args=(text,), daemon=True).start()


# ── Main ──────────────────────────────────────────────────────────────────────


def _sigterm_handler(signum: int, frame: object) -> None:
    log(_SVC, "INFO", "SIGTERM received — shutting down")
    stop_speaking()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _sigterm_handler)

log(_SVC, "INFO", "ready — select text and press Ctrl+Shift+F5")

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()

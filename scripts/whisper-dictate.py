#!/usr/bin/env python3
"""
Toggle dictation for macOS using whisper-stream for real-time streaming.
Press Ctrl+F5 to start streaming, press again to stop.
Transcription is typed progressively into whatever app is currently focused.
"""

import os
import queue
import re
import subprocess
import sys
import threading

from pynput import keyboard

sys.path.insert(0, os.path.dirname(__file__))
from jarvis_config import (
    HEARTBEAT_INTERVAL_S,
    WHISPER_STREAM_KEEP_MS,
    WHISPER_STREAM_LENGTH_MS,
    WHISPER_STREAM_STEP_MS,
    WHISPER_STREAM_VAD_THRESHOLD,
)
from jarvis_config import (
    STT_LANGUAGE as LANGUAGE,
)
from jarvis_config import (
    STT_MODEL_PATH as MODEL_PATH,
)
from jarvis_log import log

_SVC = "whisper-dictate"


def _start_heartbeat() -> None:
    """Write a timestamp to /tmp/jarvis-<svc>.heartbeat every HEARTBEAT_INTERVAL_S seconds."""
    import time
    from pathlib import Path

    path = Path(f"/tmp/jarvis-{_SVC}.heartbeat")
    while True:
        path.write_text(str(time.time()))
        time.sleep(HEARTBEAT_INTERVAL_S)


threading.Thread(target=_start_heartbeat, daemon=True).start()

# Toggle combo: Ctrl+F5. macOS intercepts bare F5 at the system level;
# a modifier combo bypasses that. Change to taste.
HOTKEY = {keyboard.Key.ctrl, keyboard.Key.f5}

# ── State ─────────────────────────────────────────────────────────────────────

whisper_proc = None  # subprocess.Popen handle
reader_thread = None  # stdout-reading daemon thread
current_keys = set()
triggered = False  # hotkey was pressed, waiting for full release before firing
_type_queue: queue.Queue = queue.Queue()  # decouples stdout reader from osascript calls

# ── Streaming ─────────────────────────────────────────────────────────────────

_TIMESTAMP_RE = re.compile(r"\[[\d:.]+ --> [\d:.]+\]\s*")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Common whisper hallucinations during silence — language-agnostic short phrases
_HALLUCINATIONS = {
    "Thank you.",
    "Thank you!",
    "Thanks for watching.",
    "Thanks for watching!",
    "Thank you for watching.",
    "Thank you so much.",
    "Please subscribe.",
    "Okay.",
    "Okay!",
    "OK.",
    "Amen.",
    "Bye.",
    "Bye!",
    "...",
    ". . .",
    ".",
}


def clean_whisper_line(raw: str) -> str:
    """Strip ANSI codes, carriage-return rewrites, and timestamp prefixes. Pure function."""
    line = _ANSI_RE.sub("", raw)
    line = line.split("\r")[-1]
    return _TIMESTAMP_RE.sub("", line).strip()


def is_hallucination(text: str) -> bool:
    """Return True if text is a known Whisper hallucination or noise fragment. Pure function."""
    return text in _HALLUCINATIONS or len(text) <= 2


def _typer_worker():
    """Drain _type_queue and call type_text sequentially in a dedicated thread.

    Keeping typing out of _read_stdout means the stdout pipe is always drained
    promptly — osascript latency (~50–200 ms per call) can no longer back up the
    64 KB kernel pipe buffer and stall whisper-stream mid-session.
    """
    while True:
        text = _type_queue.get()
        if text is None:  # sentinel — stop the worker
            break
        type_text(text)


def _read_stdout(proc):
    first_chunk = True

    for raw in proc.stdout:
        text = clean_whisper_line(raw.decode("utf-8", errors="replace"))

        # skip status messages like [Start speaking], [BLANK_AUDIO], etc.
        if not text or text.startswith("["):
            continue
        if is_hallucination(text):
            log(_SVC, "DEBUG", f"filtered: '{text}'")
            continue

        out = (" " if not first_chunk else "") + text
        first_chunk = False
        log(_SVC, "INFO", f"transcribed: '{out}'")
        _type_queue.put(out)  # hand off; don't block the reader


def start_streaming():
    global whisper_proc, reader_thread
    cmd = [
        "/opt/homebrew/bin/whisper-stream",
        "--model",
        MODEL_PATH,
        "--language",
        LANGUAGE,
        "--step",
        str(WHISPER_STREAM_STEP_MS),
        "--length",
        str(WHISPER_STREAM_LENGTH_MS),
        "--keep",
        str(WHISPER_STREAM_KEEP_MS),
        "--vad-thold",
        str(WHISPER_STREAM_VAD_THRESHOLD),
    ]
    whisper_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    threading.Thread(target=_typer_worker, daemon=True).start()
    reader_thread = threading.Thread(target=_read_stdout, args=(whisper_proc,), daemon=True)
    reader_thread.start()
    log(_SVC, "INFO", "streaming started")


def stop_streaming():
    global whisper_proc, reader_thread
    if whisper_proc is not None:
        whisper_proc.terminate()
        try:
            whisper_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            whisper_proc.kill()
            whisper_proc.wait()
        whisper_proc = None
    reader_thread = None
    log(_SVC, "INFO", "streaming stopped")


# ── Typing ────────────────────────────────────────────────────────────────────


def type_text(text):
    """Type text into the currently focused app via osascript."""
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    subprocess.run(
        ["osascript", "-e", f'tell application "System Events" to keystroke "{escaped}"']
    )


# ── Hotkey Listener ───────────────────────────────────────────────────────────


def on_press(key):
    global triggered
    current_keys.add(key)
    if current_keys == HOTKEY and not triggered:
        triggered = True


def on_release(key):
    global triggered
    current_keys.discard(key)
    if not triggered:
        return
    # fire once all hotkey keys are fully released
    if any(k in current_keys for k in HOTKEY):
        return
    triggered = False
    if whisper_proc is None:
        start_streaming()
    else:
        threading.Thread(target=stop_streaming, daemon=True).start()


# ── Main ──────────────────────────────────────────────────────────────────────

log(_SVC, "INFO", "ready — press Ctrl+F5 to start streaming")

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()

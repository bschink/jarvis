#!/usr/bin/env python3
"""
Toggle dictation for macOS using whisper-stream for real-time streaming.
Press Ctrl+F5 to start streaming, press again to stop.
Transcription is typed progressively into whatever app is currently focused.
"""

import os
import re
import signal
import subprocess
import threading
from pynput import keyboard

# ── Configuration ─────────────────────────────────────────────────────────────

MODEL_PATH = os.path.expanduser("~/.cache/whisper/ggml-large-v3-turbo.bin")
LANGUAGE = "auto"
WHISPER_STREAM_STEP_MS   = 2000   # process a new chunk every 2s
WHISPER_STREAM_LENGTH_MS = 10000  # context window per chunk (longer = fewer mid-sentence cuts)
WHISPER_STREAM_KEEP_MS   = 0      # no overlap — re-processing causes non-deterministic duplicates

# Toggle combo: Ctrl+F5. macOS intercepts bare F5 at the system level;
# a modifier combo bypasses that. Change to taste.
HOTKEY = {keyboard.Key.ctrl, keyboard.Key.f5}

# ── State ─────────────────────────────────────────────────────────────────────

whisper_proc  = None   # subprocess.Popen handle
reader_thread = None   # stdout-reading daemon thread
current_keys  = set()

# ── Streaming ─────────────────────────────────────────────────────────────────

_TIMESTAMP_RE  = re.compile(r'\[[\d:.]+ --> [\d:.]+\]\s*')
_ANSI_RE       = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')

# Common whisper hallucinations during silence — language-agnostic short phrases
_HALLUCINATIONS = {
    "Thank you.", "Thank you!", "Thanks for watching.", "Thanks for watching!",
    "Thank you for watching.", "Thank you so much.", "Please subscribe.",
    "Okay.", "Okay!", "OK.", "Amen.", "Bye.", "Bye!",
    "...", ". . .", ".",
}

def _read_stdout(proc):
    first_chunk = True

    for raw in proc.stdout:
        line = raw.decode('utf-8', errors='replace')
        line = _ANSI_RE.sub('', line)
        # whisper-stream uses \r to rewrite lines in-place; take the final state
        line = line.split('\r')[-1]
        text = _TIMESTAMP_RE.sub('', line).strip()

        # skip status messages like [Start speaking], [BLANK_AUDIO], etc.
        if not text or text.startswith('['):
            continue
        # skip known hallucinations and single-character noise
        if text in _HALLUCINATIONS or len(text) <= 2:
            print(f"🚫 Filtered: '{text}'")
            continue

        out = (' ' if not first_chunk else '') + text
        first_chunk = False
        print(f"✅ '{out}'")
        type_text(out)

def start_streaming():
    global whisper_proc, reader_thread
    cmd = [
        "/opt/homebrew/bin/whisper-stream",
        "--model",    MODEL_PATH,
        "--language", LANGUAGE,
        "--step",     str(WHISPER_STREAM_STEP_MS),
        "--length",   str(WHISPER_STREAM_LENGTH_MS),
        "--keep",     str(WHISPER_STREAM_KEEP_MS),
    ]
    whisper_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
    )
    reader_thread = threading.Thread(target=_read_stdout, args=(whisper_proc,), daemon=True)
    reader_thread.start()
    print("🎙  Streaming...")

def stop_streaming():
    global whisper_proc, reader_thread
    if whisper_proc is not None:
        whisper_proc.terminate()
        whisper_proc.wait(timeout=3)
        whisper_proc = None
    reader_thread = None
    print("⏹  Stopped.")

# ── Typing ────────────────────────────────────────────────────────────────────

def type_text(text):
    """Type text into the currently focused app via osascript."""
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    subprocess.run([
        "osascript", "-e",
        f'tell application "System Events" to keystroke "{escaped}"'
    ])

# ── Hotkey Listener ───────────────────────────────────────────────────────────

def on_press(key):
    current_keys.add(key)
    if HOTKEY.issubset(current_keys):
        if whisper_proc is None:
            start_streaming()
        else:
            threading.Thread(target=stop_streaming, daemon=True).start()

def on_release(key):
    current_keys.discard(key)

# ── Main ──────────────────────────────────────────────────────────────────────

print("🟢 Whisper dictation ready (streaming mode).")
print("   Press Ctrl+F5 to start streaming, press again to stop.")
print("   Edit HOTKEY in the script to change the key.\n")

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()

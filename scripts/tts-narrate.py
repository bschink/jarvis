#!/usr/bin/env python3
"""
System-wide "read this to me" hotkey daemon for JARVIS.
Press Ctrl+Shift+F5 to speak whatever text is selected in any app.

Flow: hotkey → Cmd+C → read clipboard → restore clipboard → speak via tts-router.py
"""

import os
import subprocess
import threading
import time

from pynput import keyboard

# ── Configuration ─────────────────────────────────────────────────────────────

HOTKEY     = {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.f5}
TTS_PYTHON = os.path.expanduser("~/.venv/tts-speak/bin/python")
TTS_SCRIPT = os.path.expanduser("~/scripts/tts-router.py")
COPY_DELAY = 0.15   # seconds to wait after Cmd+C before reading clipboard

# ── State ─────────────────────────────────────────────────────────────────────

current_keys = set()
busy = False
triggered = False   # hotkey was pressed, waiting for release to fire

# ── Clipboard helpers ─────────────────────────────────────────────────────────

def clipboard_read() -> str:
    return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout

def clipboard_write(text: str) -> None:
    subprocess.run(["pbcopy"], input=text, text=True)

def copy_selection() -> str:
    """Simulate Cmd+C, wait, return clipboard contents."""
    subprocess.run([
        "osascript", "-e",
        'tell application "System Events" to keystroke "c" using command down'
    ])
    time.sleep(COPY_DELAY)
    return clipboard_read()

# ── TTS ───────────────────────────────────────────────────────────────────────

def speak(text: str) -> None:
    global busy
    try:
        subprocess.run([TTS_PYTHON, TTS_SCRIPT, "--long", text])
    except Exception as e:
        print(f"❌ TTS error: {e}")
    finally:
        busy = False

# ── Hotkey handler ────────────────────────────────────────────────────────────

def on_press(key):
    global triggered
    current_keys.add(key)
    if current_keys == HOTKEY and not busy:
        triggered = True

def on_release(key):
    global busy, triggered
    current_keys.discard(key)
    if not triggered:
        return
    # Fire once all hotkey keys are released (modifiers no longer held)
    if any(k in current_keys for k in HOTKEY):
        return
    triggered = False

    if busy:
        print("⏳ Already speaking, ignoring.")
        return

    saved = clipboard_read()
    text = copy_selection()
    clipboard_write(saved)

    text = text.strip()
    if not text:
        print("⚠️  No text selected.")
        return

    print(f"🔊 Narrating ({len(text)} chars)...")
    busy = True
    threading.Thread(target=speak, args=(text,), daemon=True).start()

# ── Main ──────────────────────────────────────────────────────────────────────

print("🟢 JARVIS narrate ready.")
print("   Select text anywhere, then press Ctrl+Shift+F5 to hear it.")
print("   Edit HOTKEY in the script to change the key.\n")

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()

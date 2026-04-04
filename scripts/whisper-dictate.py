#!/usr/bin/env python3
"""
Toggle dictation for macOS.
Press Ctrl+F5 to start recording, press again to transcribe.
Transcription is typed into whatever app is currently focused.
"""

import threading
import tempfile
import subprocess
import requests
import sounddevice as sd
import soundfile as sf
import numpy as np
from pynput import keyboard

# ── Configuration ─────────────────────────────────────────────────────────────

SAMPLE_RATE = 16000          # Hz — Whisper expects 16kHz
WHISPER_URL = "http://127.0.0.1:2022/inference"
LANGUAGE = "auto"            # "auto", "en", or "de"

# Toggle combo: Ctrl+F5. macOS intercepts bare F5 at the system level;
# a modifier combo bypasses that. Change to taste.
HOTKEY = {keyboard.Key.ctrl, keyboard.Key.f5}

# ── State ─────────────────────────────────────────────────────────────────────

recording = False
audio_frames = []
current_keys = set()
stream = None

# ── Audio ─────────────────────────────────────────────────────────────────────

def start_recording():
    global recording, audio_frames, stream
    recording = True
    audio_frames = []
    stream = sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32',
        callback=audio_callback,
    )
    stream.start()
    print("🎙  Recording...")

def stop_and_transcribe():
    global recording, stream
    recording = False
    if stream is not None:
        stream.stop()
        stream.close()
        stream = None
    print("⏳ Transcribing...")

    if not audio_frames:
        return

    audio = np.concatenate(audio_frames, axis=0)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        sf.write(f.name, audio, SAMPLE_RATE)
        tmp_path = f.name

    try:
        with open(tmp_path, "rb") as audio_file:
            response = requests.post(
                WHISPER_URL,
                files={"file": ("audio.wav", audio_file, "audio/wav")},
                data={"language": LANGUAGE},
                timeout=30
            )
        result = response.json()
        text = result.get("text", "").strip()
        if text:
            print(f"✅ '{text}'")
            type_text(text)
        else:
            print("⚠️  No transcription returned")
    except requests.exceptions.ConnectionError:
        print("❌ Could not reach whisper-server. Is it running on port 2022?")
    except Exception as e:
        print(f"❌ Error: {e}")

def audio_callback(indata, frames, time, status):
    if recording:
        audio_frames.append(indata.copy())

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
    if current_keys == HOTKEY:
        if not recording:
            start_recording()
        else:
            threading.Thread(target=stop_and_transcribe, daemon=True).start()

def on_release(key):
    current_keys.discard(key)

# ── Main ──────────────────────────────────────────────────────────────────────

print("🟢 Whisper dictation ready.")
print("   Press Ctrl+F5 to start recording, press again to transcribe.")
print("   Edit HOTKEY in the script to change the key.\n")

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
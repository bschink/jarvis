#!/usr/bin/env python3
"""
Text-to-speech router for JARVIS.
Short text (< THRESHOLD chars) → Kokoro-ONNX (real-time, HTTP on port 8880).
Long text (>= THRESHOLD chars) → Qwen3-TTS via mlx-audio (quality, in-process).
Usage:
  tts-speak.py "text to speak"           # auto-route by length
  tts-speak.py --fast "text"             # force Kokoro
  tts-speak.py --long "text"             # force Qwen3-TTS
"""

import argparse
import io
import sys

import requests
import sounddevice as sd
import soundfile as sf

# ── Configuration ─────────────────────────────────────────────────────────────

THRESHOLD      = 200                                     # chars — below: Kokoro, at or above: Qwen3-TTS
KOKORO_URL     = "http://127.0.0.1:8880/v1/audio/speech"
KOKORO_VOICE   = "af_heart"                                # see Customisation in docs/tts-setup.md
QWEN3_MODEL    = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"
QWEN3_SR       = 24000                                   # Hz — Qwen3-TTS output sample rate

# ── Kokoro (fast path) ────────────────────────────────────────────────────────

def speak_kokoro(text: str) -> None:
    print(f"🔊 Kokoro ({len(text)} chars)...")
    try:
        resp = requests.post(
            KOKORO_URL,
            json={"model": "kokoro", "input": text, "voice": KOKORO_VOICE},
            timeout=10,
        )
        resp.raise_for_status()
        data, sr = sf.read(io.BytesIO(resp.content))
        sd.play(data, sr)
        sd.wait()
        print("✅ Done")
    except requests.exceptions.ConnectionError:
        print("❌ Kokoro server not reachable on port 8880. Is it running?")
        print("   Check: launchctl list | grep kokoro")
        print("   Logs:  tail /tmp/kokoro-server.err")
    except Exception as e:
        print(f"❌ Error: {e}")

# ── Qwen3-TTS (quality path) ──────────────────────────────────────────────────

def speak_qwen3(text: str) -> None:
    print(f"🔊 Qwen3-TTS ({len(text)} chars) — loading model...")
    try:
        # Lazy import: mlx-audio is only needed on the quality path
        from mlx_audio.tts.utils import load_model  # type: ignore
        model = load_model(QWEN3_MODEL)
        print("⏳ Generating audio...")
        audio = model.generate(text)
        print("✅ Playing...")
        sd.play(audio, QWEN3_SR)
        sd.wait()
        print("✅ Done")
    except ImportError:
        print("❌ mlx-audio not installed.")
        print("   Run: uv pip install --python ~/.venv/mlx-audio mlx-audio")
    except Exception as e:
        print(f"❌ Error: {e}")

# ── Router ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="JARVIS TTS router — speaks text via Kokoro or Qwen3-TTS."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fast", metavar="TEXT", help="force Kokoro (real-time)")
    group.add_argument("--long", metavar="TEXT", help="force Qwen3-TTS (quality)")
    parser.add_argument("text", nargs="?", default=None, help="text to speak (auto-routed)")
    args = parser.parse_args()

    if args.fast:
        speak_kokoro(args.fast)
    elif args.long:
        speak_qwen3(args.long)
    elif args.text:
        if len(args.text) < THRESHOLD:
            speak_kokoro(args.text)
        else:
            speak_qwen3(args.text)
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Text-to-speech router for JARVIS.
Short text (< THRESHOLD chars) → Kokoro-ONNX (real-time, HTTP on port 8880).
Long text (>= THRESHOLD chars) → Qwen3-TTS via mlx-audio (quality, in-process).
Usage:
  tts-router.py "text to speak"           # auto-route by length
  tts-router.py --fast "text"             # force Kokoro
  tts-router.py --long "text"             # force Qwen3-TTS
"""

import argparse
import io
import os

import requests
import sounddevice as sd
import soundfile as sf
from mlx_audio.tts.audio_player import AudioPlayer
from mlx_audio.tts.utils import load_model

# ── Configuration ─────────────────────────────────────────────────────────────

THRESHOLD      = 200                                     # chars — below: Kokoro, at or above: Qwen3-TTS
KOKORO_URL     = "http://127.0.0.1:8880/v1/audio/speech"
KOKORO_VOICE   = "af_heart"                                # see Customisation in docs/tts-setup.md
QWEN3_LOCAL_PATH = os.path.expanduser(
    "~/.cache/huggingface/hub/"
    "models--mlx-community--Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit/snapshots/main"
)
QWEN3_MODE     = "voicedesign"                           # "customvoice" or "voicedesign"
QWEN3_VOICE    = "vivian"                                # customvoice only: serena, vivian, ryan, aiden, eric, dylan, sohee
QWEN3_INSTRUCT = "A young woman, warm and slightly husky, calm and intimate, natural conversational rhythm, expressive"  # voicedesign only
QWEN3_GENDER   = "female"                                # "male" or "female"
QWEN3_TEMP     = 0                                       # 0 = deterministic
QWEN3_TOP_K    = 1
QWEN3_CFG      = 1.0
QWEN3_SR       = 24000                                   # Hz — Qwen3-TTS output sample rate

# ── Qwen3-TTS lazy model loader ───────────────────────────────────────────────

_qwen3_model = None

def _get_qwen3_model():
    global _qwen3_model
    if _qwen3_model is None:
        print("⏳ Loading Qwen3-TTS model...")
        _qwen3_model = load_model(QWEN3_LOCAL_PATH)
        print("✅ Model loaded.")
    return _qwen3_model

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
    print(f"🔊 Qwen3-TTS ({len(text)} chars) — streaming by paragraph...")
    try:
        model = _get_qwen3_model()
        player = AudioPlayer(sample_rate=QWEN3_SR)
        kwargs = {"instruct": QWEN3_INSTRUCT} if QWEN3_MODE == "voicedesign" else {"voice": QWEN3_VOICE}
        for result in model.generate(
            text,
            temperature=QWEN3_TEMP,
            top_k=QWEN3_TOP_K,
            cfg_scale=QWEN3_CFG,
            split_pattern="\n\n",
            stream=True,
            **kwargs,
        ):
            player.queue_audio(result.audio)
        player.wait_for_drain()
        print("✅ Done")
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
        raise SystemExit(1)

if __name__ == "__main__":
    main()

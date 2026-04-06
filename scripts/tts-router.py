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
import sys

import requests
import sounddevice as sd
import soundfile as sf
from mlx_audio.tts.audio_player import AudioPlayer
from mlx_audio.tts.utils import load_model

sys.path.insert(0, os.path.dirname(__file__))
from jarvis_config import (
    KOKORO_DEFAULT_VOICE as KOKORO_VOICE,
)
from jarvis_config import (
    KOKORO_URL,
    QWEN3_CFG,
    QWEN3_INSTRUCT,
    QWEN3_LOCAL_PATH,
    QWEN3_MODE,
    QWEN3_SR,
    QWEN3_TEMP,
    QWEN3_TOP_K,
    QWEN3_VOICE,
)
from jarvis_config import (
    ROUTING_THRESHOLD as THRESHOLD,
)

# ── Qwen3-TTS lazy model loader ───────────────────────────────────────────────

_qwen3_model = None


def _get_qwen3_model():
    global _qwen3_model
    if _qwen3_model is None:
        if not os.path.isdir(QWEN3_LOCAL_PATH):
            raise FileNotFoundError(
                f"Qwen3-TTS model not found: {QWEN3_LOCAL_PATH}\n"
                "Download via mlx-audio — see docs/tts-setup.md Part 4."
            )
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
        kwargs = (
            {"instruct": QWEN3_INSTRUCT} if QWEN3_MODE == "voicedesign" else {"voice": QWEN3_VOICE}
        )
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


def _choose_backend(
    text: str,
    force_fast: bool = False,
    force_long: bool = False,
    threshold: int = THRESHOLD,
) -> str:
    """Return 'kokoro' or 'qwen3'. Pure function — no I/O."""
    if force_fast:
        return "kokoro"
    if force_long:
        return "qwen3"
    return "kokoro" if len(text) < threshold else "qwen3"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JARVIS TTS router — speaks text via Kokoro or Qwen3-TTS."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--fast", metavar="TEXT", help="force Kokoro (real-time)")
    group.add_argument("--long", metavar="TEXT", help="force Qwen3-TTS (quality)")
    parser.add_argument("text", nargs="?", default=None, help="text to speak (auto-routed)")
    args = parser.parse_args()

    text = args.fast or args.long or args.text
    if text is None:
        parser.print_help()
        raise SystemExit(1)

    backend = _choose_backend(text, force_fast=bool(args.fast), force_long=bool(args.long))
    if backend == "kokoro":
        speak_kokoro(text)
    else:
        speak_qwen3(text)


if __name__ == "__main__":
    main()

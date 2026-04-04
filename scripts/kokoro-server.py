#!/usr/bin/env python3
"""
Kokoro-ONNX HTTP server for JARVIS.
Wraps the kokoro-onnx library in a FastAPI app that exposes an
OpenAI-compatible /v1/audio/speech endpoint on 127.0.0.1:8880.

Managed by launchd (com.kokoro.server) — do not run multiple instances.
"""

import io
import os

import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from kokoro_onnx import Kokoro
from pydantic import BaseModel

# ── Configuration ─────────────────────────────────────────────────────────────

HOST         = "127.0.0.1"
PORT         = 8880
MODEL_PATH   = os.path.expanduser("~/.cache/kokoro/kokoro-v1.0.onnx")
VOICES_PATH  = os.path.expanduser("~/.cache/kokoro/voices-v1.0.bin")
DEFAULT_VOICE = "af_heart"
DEFAULT_SPEED = 1.0

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="kokoro-server")
kokoro: Kokoro | None = None


@app.on_event("startup")
def startup() -> None:
    global kokoro
    for path in (MODEL_PATH, VOICES_PATH):
        if not os.path.exists(path):
            raise RuntimeError(
                f"Model file not found: {path}\n"
                "Download from hexgrad/Kokoro-82M on HuggingFace — see docs/tts-setup.md Part 1."
            )
    print(f"🔊 Loading Kokoro model from {MODEL_PATH} ...")
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    print(f"✅ Kokoro server ready on {HOST}:{PORT}")


class SpeechRequest(BaseModel):
    model: str = "kokoro"
    input: str
    voice: str = DEFAULT_VOICE
    speed: float = DEFAULT_SPEED


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest) -> Response:
    if kokoro is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    try:
        samples, sample_rate = kokoro.create(
            req.input, voice=req.voice, speed=req.speed, lang="en-us"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return Response(content=buf.getvalue(), media_type="audio/wav")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")

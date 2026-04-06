#!/usr/bin/env python3
"""
Kokoro-ONNX HTTP server for JARVIS.
Wraps the kokoro-onnx library in a FastAPI app that exposes an
OpenAI-compatible /v1/audio/speech endpoint on 127.0.0.1:8880.

Managed by launchd (com.kokoro.server) — do not run multiple instances.
"""

import io
import os
import sys
from contextlib import asynccontextmanager

import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from kokoro_onnx import Kokoro
from pydantic import BaseModel

sys.path.insert(0, os.path.dirname(__file__))
from jarvis_config import (
    KOKORO_DEFAULT_LANG as DEFAULT_LANG,
)
from jarvis_config import (
    KOKORO_DEFAULT_SPEED as DEFAULT_SPEED,
)
from jarvis_config import (
    KOKORO_DEFAULT_VOICE as DEFAULT_VOICE,
)
from jarvis_config import (
    KOKORO_HOST as HOST,
)
from jarvis_config import (
    KOKORO_MODEL_PATH as MODEL_PATH,
)
from jarvis_config import (
    KOKORO_PORT as PORT,
)
from jarvis_config import (
    KOKORO_VOICES_PATH as VOICES_PATH,
)
from jarvis_log import log

_SVC = "kokoro-server"

# ── App ───────────────────────────────────────────────────────────────────────

kokoro: Kokoro | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global kokoro
    for path in (MODEL_PATH, VOICES_PATH):
        if not os.path.exists(path):
            raise RuntimeError(
                f"Model file not found: {path}\n"
                "Download from hexgrad/Kokoro-82M on HuggingFace — see docs/tts-setup.md Part 1."
            )
    log(_SVC, "INFO", f"loading model from {MODEL_PATH}")
    kokoro = Kokoro(MODEL_PATH, VOICES_PATH)
    log(_SVC, "INFO", f"ready on {HOST}:{PORT}")
    yield


app = FastAPI(title="kokoro-server", lifespan=lifespan)


class SpeechRequest(BaseModel):
    model: str = "kokoro"
    input: str
    voice: str = DEFAULT_VOICE
    speed: float = DEFAULT_SPEED
    lang: str = DEFAULT_LANG


@app.post("/v1/audio/speech")
def speech(req: SpeechRequest) -> Response:
    if kokoro is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    try:
        samples, sample_rate = kokoro.create(
            req.input, voice=req.voice, speed=req.speed, lang=req.lang
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    buf = io.BytesIO()
    sf.write(buf, samples, sample_rate, format="WAV")
    return Response(content=buf.getvalue(), media_type="audio/wav")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")

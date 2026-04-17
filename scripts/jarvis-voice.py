#!/usr/bin/env python3
"""
JARVIS voice conversation loop.

Press Option+F5 to start listening. Speak. JARVIS responds via Kokoro TTS.
Press Option+F5 again while JARVIS is speaking to barge in — playback stops
and a new listening session starts immediately.

Architecture:
  STT: whisper-stream subprocess → stdout reader thread → echo gate → silence timer
  LLM: LLMClient.stream_sentences() — yields sentences as they arrive
  TTS: tts-router.py --fast subprocess per sentence (Kokoro, <1 s latency)

Echo gate: _tts_active Event is set while TTS subprocess runs. Any whisper
output received while it's set is discarded, preventing speaker audio from
being fed back into the microphone.
"""

import contextlib
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from pynput import keyboard

sys.path.insert(0, os.path.dirname(__file__))
from jarvis_config import (
    HEARTBEAT_INTERVAL_S,
    SILENCE_GAP_S,
    STT_LANGUAGE,
    STT_MODEL_PATH,
    VOICE_TTS_PYTHON,
    VOICE_TTS_SCRIPT,
    WHISPER_STREAM_KEEP_MS,
    WHISPER_STREAM_LENGTH_MS,
    WHISPER_STREAM_STEP_MS,
    WHISPER_STREAM_VAD_THRESHOLD,
)
from jarvis_log import clean_whisper_line, is_hallucination, log
from llm_client import LLMClient

_SVC = "jarvis-voice"
HOTKEY = {keyboard.Key.alt, keyboard.Key.f5}

# ── State ─────────────────────────────────────────────────────────────────────

_tts_active = threading.Event()  # set while TTS subprocess is running
_cancelled = threading.Event()  # set on barge-in; cleared when new LLM response starts
_whisper_proc: subprocess.Popen | None = None
_tts_proc: subprocess.Popen | None = None
_utterance_buffer: list[str] = []
_buffer_lock = threading.Lock()
_silence_timer: threading.Timer | None = None
_current_keys: set = set()
_triggered = False
_llm = LLMClient()

# ── TTS ───────────────────────────────────────────────────────────────────────


def _speak_sentence(sentence: str) -> None:
    """Speak one sentence via Kokoro (blocking). Sets/clears _tts_active."""
    global _tts_proc
    _tts_active.set()
    proc = subprocess.Popen(
        [VOICE_TTS_PYTHON, VOICE_TTS_SCRIPT, "--fast", sentence],
        start_new_session=True,
    )
    _tts_proc = proc
    try:
        proc.wait()
    finally:
        _tts_proc = None
        _tts_active.clear()


def _llm_and_speak(utterance: str) -> None:
    """Run LLM sentence streaming + per-sentence TTS in a background thread."""
    _cancelled.clear()
    log(_SVC, "INFO", f"querying LLM: '{utterance[:60]}{'...' if len(utterance) > 60 else ''}'")
    try:
        for sentence in _llm.stream_sentences(utterance):
            if _cancelled.is_set():
                log(_SVC, "INFO", "barge-in: discarding remaining TTS sentences")
                break
            _speak_sentence(sentence)
    except Exception as e:
        log(_SVC, "ERROR", f"LLM/TTS error: {e}")


# ── STT ───────────────────────────────────────────────────────────────────────


def _on_utterance_complete() -> None:
    """Called by silence timer when no new whisper output for SILENCE_GAP_S seconds."""
    with _buffer_lock:
        utterance = " ".join(_utterance_buffer).strip()
        _utterance_buffer.clear()
    if not utterance:
        return
    log(_SVC, "INFO", f"utterance: '{utterance}'")
    threading.Thread(target=_llm_and_speak, args=(utterance,), daemon=True).start()


def _reset_silence_timer() -> None:
    global _silence_timer
    if _silence_timer is not None:
        _silence_timer.cancel()
    _silence_timer = threading.Timer(SILENCE_GAP_S, _on_utterance_complete)
    _silence_timer.daemon = True
    _silence_timer.start()


def _read_stdout(proc: subprocess.Popen) -> None:
    for raw in proc.stdout:  # type: ignore[union-attr]
        if _tts_active.is_set():
            continue  # echo gate: discard while speaker is playing
        text = clean_whisper_line(raw.decode("utf-8", errors="replace"))
        if not text or text.startswith("["):
            continue
        if is_hallucination(text):
            log(_SVC, "DEBUG", f"filtered: '{text}'")
            continue
        log(_SVC, "INFO", f"heard: '{text}'")
        with _buffer_lock:
            _utterance_buffer.append(text)
        _reset_silence_timer()


# ── Control ───────────────────────────────────────────────────────────────────


def start_streaming() -> None:
    global _whisper_proc
    cmd = [
        "/opt/homebrew/bin/whisper-stream",
        "--model",
        STT_MODEL_PATH,
        "--language",
        STT_LANGUAGE,
        "--step",
        str(WHISPER_STREAM_STEP_MS),
        "--length",
        str(WHISPER_STREAM_LENGTH_MS),
        "--keep",
        str(WHISPER_STREAM_KEEP_MS),
        "--vad-thold",
        str(WHISPER_STREAM_VAD_THRESHOLD),
    ]
    _whisper_proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
    )
    threading.Thread(target=_read_stdout, args=(_whisper_proc,), daemon=True).start()
    log(_SVC, "INFO", "listening...")


def stop_all() -> None:
    """Stop STT, cancel any in-flight LLM response, and kill TTS. Does not restart."""
    global _whisper_proc, _silence_timer
    _cancelled.set()
    if _silence_timer is not None:
        _silence_timer.cancel()
        _silence_timer = None
    if _whisper_proc is not None:
        _whisper_proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            _whisper_proc.wait(timeout=3)
        _whisper_proc = None
    proc = _tts_proc
    if proc is not None:
        with contextlib.suppress(ProcessLookupError, OSError):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    _tts_active.clear()
    with _buffer_lock:
        _utterance_buffer.clear()
    log(_SVC, "INFO", "stopped")


# ── Hotkey listener ───────────────────────────────────────────────────────────


def on_press(key: keyboard.Key) -> None:
    global _triggered
    _current_keys.add(key)
    if _current_keys == HOTKEY and not _triggered:
        _triggered = True


def on_release(key: keyboard.Key) -> None:
    global _triggered
    _current_keys.discard(key)
    if not _triggered:
        return
    if any(k in _current_keys for k in HOTKEY):
        return
    _triggered = False

    if _whisper_proc is not None or _tts_active.is_set():
        # Something is active — stop everything
        threading.Thread(target=stop_all, daemon=True).start()
    else:
        # Idle — start listening
        start_streaming()


# ── Heartbeat ─────────────────────────────────────────────────────────────────


def _heartbeat_writer() -> None:
    path = Path(f"/tmp/jarvis-{_SVC}.heartbeat")
    while True:
        path.write_text(str(time.time()))
        time.sleep(HEARTBEAT_INTERVAL_S)


# ── Main ──────────────────────────────────────────────────────────────────────


def _sigterm_handler(signum: int, frame: object) -> None:
    log(_SVC, "INFO", "SIGTERM received — shutting down")
    stop_all()
    raise SystemExit(0)


signal.signal(signal.SIGTERM, _sigterm_handler)

threading.Thread(target=_heartbeat_writer, daemon=True).start()

log(_SVC, "INFO", "pre-warming LLM...")
_llm.prewarm()
log(_SVC, "INFO", "ready — press Option+F5 to speak, press again to stop")

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()

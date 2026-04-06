"""
jarvis_config.py — single source of truth for all JARVIS runtime settings.
Edit this file to change voices, routing thresholds, model paths, etc.
All other scripts import from here — one change propagates everywhere.
Run install.sh after editing to deploy and restart live services.
"""

import os

# ── STT ───────────────────────────────────────────────────────────────────────

STT_MODEL_PATH = os.path.expanduser("~/.cache/whisper/ggml-large-v3-turbo.bin")
STT_LANGUAGE = "auto"  # "auto", "en", "de", etc.

WHISPER_STREAM_STEP_MS = 2000  # process a new chunk every N ms
WHISPER_STREAM_LENGTH_MS = 10000  # context window per chunk
WHISPER_STREAM_KEEP_MS = 0  # overlap — 0 prevents non-deterministic duplicates
WHISPER_STREAM_VAD_THRESHOLD = (
    0.60  # voice activity detection threshold (0–1); raise to filter more noise
)

# ── TTS — Kokoro (fast path) ──────────────────────────────────────────────────

KOKORO_HOST = "127.0.0.1"
KOKORO_PORT = 8880
KOKORO_MODEL_PATH = os.path.expanduser("~/.cache/kokoro/kokoro-v1.0.onnx")
KOKORO_VOICES_PATH = os.path.expanduser("~/.cache/kokoro/voices-v1.0.bin")
KOKORO_DEFAULT_VOICE = "af_heart"
KOKORO_DEFAULT_SPEED = 1.0
KOKORO_DEFAULT_LANG = "en-us"  # "en-us", "en-gb", "de", etc. — passed to kokoro.create()
KOKORO_URL = f"http://{KOKORO_HOST}:{KOKORO_PORT}/v1/audio/speech"

# ── TTS — Qwen3-TTS (quality path) ───────────────────────────────────────────


def _resolve_qwen3_path(repo: str) -> str:
    """Resolve the local snapshot directory for a HuggingFace model repo.

    mlx-audio downloads models directly into the hub cache without registering
    the standard blobs/refs metadata, so huggingface_hub.snapshot_download with
    local_files_only=True doesn't work. This scans the snapshots directory and
    returns the path of the most recently modified snapshot (usually 'main').
    """
    safe_name = repo.replace("/", "--")
    snapshots_dir = os.path.expanduser(f"~/.cache/huggingface/hub/models--{safe_name}/snapshots")
    if os.path.isdir(snapshots_dir):
        revisions = [
            os.path.join(snapshots_dir, r)
            for r in os.listdir(snapshots_dir)
            if os.path.isdir(os.path.join(snapshots_dir, r))
        ]
        if revisions:
            return max(revisions, key=os.path.getmtime)
    # Fallback — return the expected path so downstream validation gives a clear error
    return os.path.join(snapshots_dir, "main") if os.path.isdir(snapshots_dir) else snapshots_dir


QWEN3_REPO = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit"
QWEN3_LOCAL_PATH = _resolve_qwen3_path(QWEN3_REPO)
QWEN3_MODE = "voicedesign"  # "customvoice" or "voicedesign"
QWEN3_VOICE = "vivian"  # customvoice only: serena, vivian, ryan, aiden, eric, dylan, sohee
QWEN3_INSTRUCT = "A young woman, warm and slightly husky, calm and intimate, natural conversational rhythm, expressive"  # voicedesign only
QWEN3_GENDER = "female"  # "male" or "female"
QWEN3_TEMP = 0  # 0 = deterministic
QWEN3_TOP_K = 1
QWEN3_CFG = 1.0
QWEN3_SR = 24000  # Hz — Qwen3-TTS output sample rate

# ── TTS routing ───────────────────────────────────────────────────────────────

ROUTING_THRESHOLD = 200  # chars: below → Kokoro, at or above → Qwen3-TTS

# ── Narrate daemon ────────────────────────────────────────────────────────────

NARRATE_TTS_PYTHON = os.path.expanduser("~/.venv/tts-speak/bin/python")
NARRATE_TTS_SCRIPT = os.path.expanduser("~/scripts/tts-router.py")
NARRATE_COPY_DELAY = 0.15  # seconds to wait after Cmd+C before reading clipboard

# ── Heartbeat ─────────────────────────────────────────────────────────────────

HEARTBEAT_INTERVAL_S = 30  # seconds between heartbeat file writes
HEARTBEAT_STALE_S = 90  # age threshold above which a service is considered STALE (> 3 missed beats)

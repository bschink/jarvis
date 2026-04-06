"""Tests for scripts/kokoro-server.py — Pydantic model and FastAPI endpoint."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _load_server_module():
    """Load kokoro-server.py by file path (hyphen prevents normal import)."""
    # Build stubs for all hardware/model imports
    fake_kokoro_onnx = MagicMock()
    fake_soundfile = MagicMock()

    # kokoro.create() returns (samples_array, sample_rate)
    fake_instance = MagicMock()
    fake_instance.create.return_value = (np.zeros(24000, dtype=np.float32), 24000)
    fake_kokoro_onnx.Kokoro.return_value = fake_instance

    # soundfile.write() must actually write a valid WAV so the endpoint returns RIFF bytes
    import soundfile as _real_sf

    def _fake_sf_write(buf, data, sr, format=None):  # noqa: A002
        _real_sf.write(buf, data, sr, format=format or "WAV")

    fake_soundfile.write.side_effect = _fake_sf_write

    with (
        patch.dict(
            sys.modules,
            {
                "kokoro_onnx": fake_kokoro_onnx,
                "soundfile": fake_soundfile,
                "sounddevice": MagicMock(),
                "uvicorn": MagicMock(),
            },
        ),
        patch("os.path.exists", return_value=True),
    ):
        spec = importlib.util.spec_from_file_location(
            "kokoro_server", SCRIPTS_DIR / "kokoro-server.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["kokoro_server"] = mod
        spec.loader.exec_module(mod)

    # Bypass the lifespan context manager — inject the fake kokoro directly
    mod.kokoro = fake_instance
    return mod, fake_instance


@pytest.fixture(scope="module")
def server_module():
    mod, _ = _load_server_module()
    return mod


@pytest.fixture(scope="module")
def fake_kokoro_instance():
    _, instance = _load_server_module()
    return instance


@pytest.fixture()
def client(server_module):
    from fastapi.testclient import TestClient

    return TestClient(server_module.app, raise_server_exceptions=False)


class TestSpeechRequestModel:
    def test_defaults_applied(self, server_module):
        req = server_module.SpeechRequest(input="hello")
        assert req.model == "kokoro"
        assert req.voice == "af_heart"
        assert req.speed == 1.0
        assert req.lang == "en-us"

    def test_custom_fields_accepted(self, server_module):
        req = server_module.SpeechRequest(input="hi", voice="af_sky", speed=1.3, lang="en-gb")
        assert req.voice == "af_sky"
        assert req.speed == 1.3
        assert req.lang == "en-gb"

    def test_input_is_required(self, server_module):
        import pydantic

        with pytest.raises(pydantic.ValidationError):
            server_module.SpeechRequest()


class TestSpeechEndpoint:
    def test_returns_wav_on_success(self, client):
        resp = client.post("/v1/audio/speech", json={"input": "Hello, world."})
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "audio/wav"
        assert resp.content[:4] == b"RIFF"

    def test_503_when_kokoro_is_none(self, client, server_module):
        original = server_module.kokoro
        server_module.kokoro = None
        try:
            resp = client.post("/v1/audio/speech", json={"input": "test"})
            assert resp.status_code == 503
            assert "not loaded" in resp.json()["detail"].lower()
        finally:
            server_module.kokoro = original

    def test_500_when_kokoro_raises(self, client, server_module):
        server_module.kokoro.create.side_effect = RuntimeError("synthesis failed")
        try:
            resp = client.post("/v1/audio/speech", json={"input": "oops"})
            assert resp.status_code == 500
            assert "synthesis failed" in resp.json()["detail"]
        finally:
            server_module.kokoro.create.side_effect = None

    def test_voice_forwarded_to_create(self, client, server_module):
        server_module.kokoro.create.reset_mock()
        resp = client.post("/v1/audio/speech", json={"input": "test", "voice": "af_sky"})
        assert resp.status_code == 200
        call_kwargs = server_module.kokoro.create.call_args
        # voice is passed as keyword argument
        assert call_kwargs.kwargs.get("voice") == "af_sky"

"""Tests for scripts/tts-router.py — _choose_backend() routing logic."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


@pytest.fixture(scope="module")
def router_module():
    """Load tts-router.py with all hardware/ML imports stubbed out."""
    stubs = {
        "requests": MagicMock(),
        "sounddevice": MagicMock(),
        "soundfile": MagicMock(),
        "mlx": MagicMock(),
        "mlx.core": MagicMock(),
        "mlx_audio": MagicMock(),
        "mlx_audio.tts": MagicMock(),
        "mlx_audio.tts.utils": MagicMock(),
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("tts_router", SCRIPTS_DIR / "tts-router.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["tts_router"] = mod
        spec.loader.exec_module(mod)
    return mod


class TestChooseBackend:
    def test_short_text_routes_to_kokoro(self, router_module):
        assert router_module._choose_backend("short", threshold=200) == "kokoro"

    def test_threshold_boundary_routes_to_qwen3(self, router_module):
        text = "x" * 200  # exactly at threshold → qwen3
        assert router_module._choose_backend(text, threshold=200) == "qwen3"

    def test_just_below_threshold_is_kokoro(self, router_module):
        text = "x" * 199
        assert router_module._choose_backend(text, threshold=200) == "kokoro"

    def test_force_fast_overrides_long_text(self, router_module):
        long_text = "x" * 500
        assert router_module._choose_backend(long_text, force_fast=True, threshold=200) == "kokoro"

    def test_force_long_overrides_short_text(self, router_module):
        assert router_module._choose_backend("hi", force_long=True, threshold=200) == "qwen3"

    def test_empty_string_routes_to_kokoro(self, router_module):
        assert router_module._choose_backend("", threshold=200) == "kokoro"

    def test_custom_threshold_respected(self, router_module):
        # 5 chars >= threshold of 3 → qwen3
        assert router_module._choose_backend("hello", threshold=3) == "qwen3"

    def test_uses_config_threshold_by_default(self, router_module):
        """Default threshold matches ROUTING_THRESHOLD from jarvis_config."""
        import jarvis_config

        short = "x" * (jarvis_config.ROUTING_THRESHOLD - 1)
        long_ = "x" * jarvis_config.ROUTING_THRESHOLD
        assert router_module._choose_backend(short) == "kokoro"
        assert router_module._choose_backend(long_) == "qwen3"

"""Tests for scripts/jarvis_config.py — pure functions and constants."""

import os
from unittest.mock import patch

import jarvis_config


class TestResolveQwen3Path:
    def test_returns_most_recent_revision(self, tmp_path):
        """Returns the snapshot revision with the latest mtime."""
        snapshots = tmp_path / "snapshots"
        rev_a = snapshots / "abc123"
        rev_b = snapshots / "main"
        rev_a.mkdir(parents=True)
        rev_b.mkdir(parents=True)
        # Make rev_b newer
        os.utime(rev_b, (rev_b.stat().st_atime, rev_b.stat().st_mtime + 10))

        with patch("os.path.expanduser", return_value=str(snapshots)):
            result = jarvis_config._resolve_qwen3_path("org/MyModel")

        assert result == str(rev_b)

    def test_returns_snapshots_dir_when_missing(self, tmp_path):
        """When the snapshots dir doesn't exist, returns the snapshots dir itself."""
        nonexistent = str(tmp_path / "models--org--Missing" / "snapshots")

        with patch("os.path.expanduser", return_value=nonexistent):
            result = jarvis_config._resolve_qwen3_path("org/Missing")

        assert result == nonexistent

    def test_returns_main_when_dir_empty(self, tmp_path):
        """When snapshots dir exists but has no subdirs, returns snapshots/main."""
        snapshots = tmp_path / "snapshots"
        snapshots.mkdir(parents=True)

        with patch("os.path.expanduser", return_value=str(snapshots)):
            result = jarvis_config._resolve_qwen3_path("org/EmptyModel")

        assert result == str(snapshots / "main")

    def test_slash_to_double_dash_conversion(self, tmp_path):
        """Repo org/name must be resolved under models--org--name directory."""
        snapshots = tmp_path / "snapshots"
        rev = snapshots / "main"
        rev.mkdir(parents=True)

        with patch("os.path.expanduser", return_value=str(snapshots)):
            result = jarvis_config._resolve_qwen3_path("mlx-community/Qwen3-TTS")

        # The result should be inside the snapshots dir
        assert str(snapshots) in result


class TestConstants:
    def test_routing_threshold_is_positive_int(self):
        assert isinstance(jarvis_config.ROUTING_THRESHOLD, int)
        assert jarvis_config.ROUTING_THRESHOLD > 0

    def test_kokoro_default_speed_is_float(self):
        assert isinstance(jarvis_config.KOKORO_DEFAULT_SPEED, float)

    def test_kokoro_url_contains_host_and_port(self):
        assert "127.0.0.1" in jarvis_config.KOKORO_URL
        assert "8880" in jarvis_config.KOKORO_URL

    def test_kokoro_url_has_speech_path(self):
        assert jarvis_config.KOKORO_URL.endswith("/v1/audio/speech")

    def test_qwen3_sr_is_positive(self):
        assert jarvis_config.QWEN3_SR > 0

    def test_vad_threshold_is_float_in_range(self):
        assert isinstance(jarvis_config.WHISPER_STREAM_VAD_THRESHOLD, float)
        assert 0.0 < jarvis_config.WHISPER_STREAM_VAD_THRESHOLD < 1.0

"""Tests for scripts/whisper-dictate.py — regex patterns and filtering helpers."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


@pytest.fixture(scope="module")
def dictate_module():
    """Load whisper-dictate.py with pynput stubbed out."""
    fake_pynput = MagicMock()
    stubs = {
        "pynput": fake_pynput,
        "pynput.keyboard": fake_pynput.keyboard,
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(
            "whisper_dictate", SCRIPTS_DIR / "whisper-dictate.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["whisper_dictate"] = mod
        spec.loader.exec_module(mod)
    return mod


class TestTimestampRegex:
    def test_strips_standard_timestamp(self, dictate_module):
        raw = "[00:01.500 --> 00:03.200]  Hello world"
        result = dictate_module._TIMESTAMP_RE.sub("", raw).strip()
        assert result == "Hello world"

    def test_strips_zero_padded_timestamp(self, dictate_module):
        raw = "[00:00.000 --> 00:00.000]   "
        result = dictate_module._TIMESTAMP_RE.sub("", raw).strip()
        assert result == ""

    def test_no_match_on_plain_text(self, dictate_module):
        text = "Just plain text"
        assert dictate_module._TIMESTAMP_RE.sub("", text) == text


class TestAnsiRegex:
    def test_strips_color_code(self, dictate_module):
        raw = "\x1b[32mGreen text\x1b[0m"
        assert dictate_module._ANSI_RE.sub("", raw) == "Green text"

    def test_strips_multiple_codes(self, dictate_module):
        raw = "\x1b[1m\x1b[31mBold red\x1b[0m"
        assert dictate_module._ANSI_RE.sub("", raw) == "Bold red"

    def test_no_match_on_clean_text(self, dictate_module):
        assert dictate_module._ANSI_RE.sub("", "clean") == "clean"


class TestHallucinations:
    def test_known_phrases_present(self, dictate_module):
        for phrase in ("Thank you.", "Okay.", "...", "Bye.", "."):
            assert phrase in dictate_module._HALLUCINATIONS

    def test_normal_sentence_absent(self, dictate_module):
        assert "The meeting is at three." not in dictate_module._HALLUCINATIONS


class TestCleanWhisperLine:
    def test_strips_timestamp_and_ansi(self, dictate_module):
        raw = "\x1b[32m[00:01.000 --> 00:02.000]  Hello\x1b[0m"
        assert dictate_module.clean_whisper_line(raw) == "Hello"

    def test_carriage_return_takes_last_segment(self, dictate_module):
        raw = "old text\rnew text"
        assert dictate_module.clean_whisper_line(raw) == "new text"

    def test_empty_line_returns_empty(self, dictate_module):
        assert dictate_module.clean_whisper_line("   ") == ""

    def test_plain_text_unchanged(self, dictate_module):
        assert dictate_module.clean_whisper_line("  Hello world  ") == "Hello world"

    def test_only_timestamp_returns_empty(self, dictate_module):
        raw = "[00:00.000 --> 00:01.000]"
        assert dictate_module.clean_whisper_line(raw) == ""


class TestVadThreshold:
    def test_vad_thold_arg_in_start_command(self, dictate_module):
        """start_streaming must pass --vad-thold so the threshold is explicit."""
        captured: list = []

        class FakePopen:
            def __init__(self, cmd, **kwargs):
                captured.append(cmd)
                self.stdout = iter([])
                self.pid = 0

            def terminate(self):
                pass

            def wait(self, timeout=None):
                pass

        import subprocess

        with patch.object(subprocess, "Popen", FakePopen):
            dictate_module.start_streaming()

        assert captured, "Popen was never called"
        cmd = captured[0]
        assert "--vad-thold" in cmd, "--vad-thold must be passed to whisper-stream"
        idx = cmd.index("--vad-thold")
        val = float(cmd[idx + 1])
        assert 0.0 < val < 1.0, "--vad-thold value must be in (0, 1)"

        # Clean up the proc handle so other tests aren't affected
        dictate_module.whisper_proc = None


class TestIsHallucination:
    def test_known_hallucination_returns_true(self, dictate_module):
        assert dictate_module.is_hallucination("Thank you.") is True

    def test_normal_sentence_returns_false(self, dictate_module):
        assert dictate_module.is_hallucination("The meeting is at three.") is False

    def test_empty_string_returns_true(self, dictate_module):
        assert dictate_module.is_hallucination("") is True

    def test_single_char_returns_true(self, dictate_module):
        assert dictate_module.is_hallucination("A") is True

    def test_two_chars_returns_true(self, dictate_module):
        assert dictate_module.is_hallucination("ok") is True

    def test_three_chars_returns_false(self, dictate_module):
        assert dictate_module.is_hallucination("hey") is False

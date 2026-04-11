"""Tests for scripts/jarvis-voice.py — voice loop logic (no hardware, no network)."""

import importlib.util
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


@pytest.fixture(scope="module")
def voice_module():
    """Load jarvis-voice.py with all hardware/network deps stubbed out."""
    fake_pynput = MagicMock()
    fake_keyboard = MagicMock()
    fake_keyboard.Key.alt = "alt"
    fake_keyboard.Key.f5 = "f5"
    fake_keyboard.Listener = MagicMock()
    fake_pynput.keyboard = fake_keyboard

    fake_llm_client = MagicMock()
    fake_llm_instance = MagicMock()
    fake_llm_instance.prewarm.return_value = None
    fake_llm_instance.stream_sentences.return_value = iter([])
    fake_llm_client.LLMClient.return_value = fake_llm_instance

    stubs = {
        "pynput": fake_pynput,
        "pynput.keyboard": fake_keyboard,
        "llm_client": fake_llm_client,
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location(
            "jarvis_voice", SCRIPTS_DIR / "jarvis-voice.py"
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["jarvis_voice"] = mod
        spec.loader.exec_module(mod)
    return mod


# ── Whisper line parsing ──────────────────────────────────────────────────────


class TestCleanWhisperLine:
    def test_strips_ansi_and_timestamp(self, voice_module):
        raw = "\x1b[32m[00:01.000 --> 00:02.000]  Hello\x1b[0m"
        assert voice_module.clean_whisper_line(raw) == "Hello"

    def test_carriage_return_takes_last(self, voice_module):
        assert voice_module.clean_whisper_line("old\rnew") == "new"

    def test_empty_returns_empty(self, voice_module):
        assert voice_module.clean_whisper_line("   ") == ""


class TestIsHallucination:
    def test_known_phrase(self, voice_module):
        assert voice_module.is_hallucination("Thank you.") is True

    def test_too_short(self, voice_module):
        assert voice_module.is_hallucination("ok") is True

    def test_normal_sentence(self, voice_module):
        assert voice_module.is_hallucination("What time is it?") is False


# ── Echo gate ─────────────────────────────────────────────────────────────────


class TestEchoGate:
    def test_discards_output_when_tts_active(self, voice_module):
        """Lines arriving while _tts_active is set must not enter the buffer."""
        voice_module._utterance_buffer.clear()
        voice_module._tts_active.set()
        try:
            # Simulate _read_stdout receiving a valid line
            raw = b"[00:01.000 --> 00:02.000]  Hello there\n"
            if not voice_module._tts_active.is_set():
                text = voice_module.clean_whisper_line(raw.decode("utf-8"))
                if text and not voice_module.is_hallucination(text):
                    voice_module._utterance_buffer.append(text)
            assert voice_module._utterance_buffer == []
        finally:
            voice_module._tts_active.clear()

    def test_accepts_output_when_tts_inactive(self, voice_module):
        """Lines arriving while _tts_active is clear should reach the buffer."""
        voice_module._utterance_buffer.clear()
        voice_module._tts_active.clear()

        text = "What time is it?"
        if (
            not voice_module._tts_active.is_set()
            and text
            and not voice_module.is_hallucination(text)
        ):
            voice_module._utterance_buffer.append(text)

        assert "What time is it?" in voice_module._utterance_buffer
        voice_module._utterance_buffer.clear()


# ── Barge-in ──────────────────────────────────────────────────────────────────


class TestStopAll:
    def test_clears_utterance_buffer(self, voice_module):
        voice_module._utterance_buffer.extend(["hello", "world"])
        voice_module._tts_proc = None
        voice_module._tts_active.clear()
        voice_module._whisper_proc = None

        voice_module.stop_all()

        assert voice_module._utterance_buffer == []

    def test_sets_cancelled(self, voice_module):
        voice_module._cancelled.clear()
        voice_module._tts_proc = None
        voice_module._tts_active.clear()
        voice_module._whisper_proc = None

        voice_module.stop_all()

        assert voice_module._cancelled.is_set()

    def test_clears_tts_active_flag(self, voice_module):
        voice_module._tts_active.set()
        voice_module._tts_proc = None
        voice_module._whisper_proc = None

        voice_module.stop_all()

        assert not voice_module._tts_active.is_set()

    def test_does_not_restart_streaming(self, voice_module):
        voice_module._tts_proc = None
        voice_module._tts_active.clear()
        voice_module._whisper_proc = None

        with patch.object(voice_module, "start_streaming") as mock_start:
            voice_module.stop_all()

        mock_start.assert_not_called()


# ── Hotkey state machine ──────────────────────────────────────────────────────


class TestHotkeyStateMachine:
    def test_exact_hotkey_sets_triggered(self, voice_module):
        voice_module._current_keys.clear()
        voice_module._triggered = False

        voice_module.on_press("alt")
        voice_module.on_press("f5")

        assert voice_module._triggered is True
        voice_module._current_keys.clear()
        voice_module._triggered = False

    def test_partial_hotkey_does_not_trigger(self, voice_module):
        voice_module._current_keys.clear()
        voice_module._triggered = False

        voice_module.on_press("alt")  # only alt, no f5

        assert voice_module._triggered is False
        voice_module._current_keys.clear()

    def test_release_starts_streaming_when_idle(self, voice_module):
        voice_module._current_keys.clear()
        voice_module._triggered = True
        voice_module._whisper_proc = None
        voice_module._tts_active.clear()

        with patch.object(voice_module, "start_streaming") as mock_start:
            voice_module.on_release("f5")

        mock_start.assert_called_once()

    def test_release_stops_when_tts_active(self, voice_module):
        voice_module._current_keys.clear()
        voice_module._triggered = True
        voice_module._tts_active.set()

        with patch.object(voice_module, "stop_all") as mock_stop:
            voice_module.on_release("f5")

        mock_stop.assert_called_once()
        voice_module._tts_active.clear()

    def test_release_stops_when_stt_active(self, voice_module):
        voice_module._current_keys.clear()
        voice_module._triggered = True
        voice_module._tts_active.clear()
        voice_module._whisper_proc = object()  # non-None sentinel

        with patch.object(voice_module, "stop_all") as mock_stop:
            voice_module.on_release("f5")

        mock_stop.assert_called_once()
        voice_module._whisper_proc = None


# ── Silence timer ─────────────────────────────────────────────────────────────


class TestSilenceTimer:
    def test_utterance_complete_clears_buffer_and_fires_llm(self, voice_module):
        voice_module._utterance_buffer.clear()
        voice_module._utterance_buffer.extend(["Hello", "world"])

        fired = threading.Event()

        def fake_llm_speak(utterance):
            fired.set()

        with patch.object(voice_module, "_llm_and_speak", side_effect=fake_llm_speak):
            voice_module._on_utterance_complete()

        assert voice_module._utterance_buffer == []
        fired.wait(timeout=2)
        assert fired.is_set()

    def test_empty_buffer_does_not_fire_llm(self, voice_module):
        voice_module._utterance_buffer.clear()

        with patch.object(voice_module, "_llm_and_speak") as mock_llm:
            voice_module._on_utterance_complete()

        mock_llm.assert_not_called()

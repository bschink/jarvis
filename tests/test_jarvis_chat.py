"""Tests for scripts/jarvis-chat.py — CLI chat loop, no network."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


@pytest.fixture(scope="module")
def chat_module():
    """Load jarvis-chat.py with llm_client stubbed out."""
    fake_llm_client = MagicMock()
    fake_client_instance = MagicMock()
    fake_llm_client.LLMClient.return_value = fake_client_instance
    fake_client_instance.stream.return_value = iter(["Hello ", "there."])

    stubs = {
        "requests": MagicMock(),
        "llm_client": fake_llm_client,
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("jarvis_chat", SCRIPTS_DIR / "jarvis-chat.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["jarvis_chat"] = mod
        spec.loader.exec_module(mod)
    return mod


class TestMain:
    def test_quit_command_exits(self, chat_module, capsys):
        """main() exits cleanly when user types 'quit'."""
        with patch("builtins.input", side_effect=["quit"]):
            chat_module.main()
        out = capsys.readouterr().out
        assert "Goodbye" in out

    def test_exit_command_exits(self, chat_module, capsys):
        with patch("builtins.input", side_effect=["exit"]):
            chat_module.main()
        out = capsys.readouterr().out
        assert "Goodbye" in out

    def test_eof_exits_gracefully(self, chat_module, capsys):
        with patch("builtins.input", side_effect=EOFError):
            chat_module.main()
        out = capsys.readouterr().out
        assert "Goodbye" in out

    def test_keyboard_interrupt_exits_gracefully(self, chat_module, capsys):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            chat_module.main()
        out = capsys.readouterr().out
        assert "Goodbye" in out

    def test_empty_input_is_skipped(self, chat_module):
        """Empty lines don't trigger LLM calls."""
        mock_client = MagicMock()
        mock_client.stream.return_value = iter([])
        chat_module.LLMClient = MagicMock(return_value=mock_client)
        with patch("builtins.input", side_effect=["", "quit"]):
            chat_module.main()
        mock_client.stream.assert_not_called()

    def test_streams_tokens_to_stdout(self, chat_module, capsys):
        mock_client = MagicMock()
        mock_client.stream.return_value = iter(["Hi ", "there."])
        mock_client.prewarm.return_value = None
        chat_module.LLMClient = MagicMock(return_value=mock_client)
        with patch("builtins.input", side_effect=["hello", "quit"]):
            chat_module.main()
        out = capsys.readouterr().out
        assert "Hi " in out
        assert "there." in out

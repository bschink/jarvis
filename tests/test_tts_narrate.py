"""Tests for scripts/tts-narrate.py — _hotkey_complete() pure helper."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


@pytest.fixture(scope="module")
def narrate_module():
    """Load tts-narrate.py with pynput and subprocess stubbed out.

    Both narrate and whisper-dictate run `with keyboard.Listener(...) as l: l.join()`
    at module level. MagicMock supports context managers and join() by default,
    so patching pynput before exec_module() is sufficient.
    """
    fake_pynput = MagicMock()
    stubs = {
        "pynput": fake_pynput,
        "pynput.keyboard": fake_pynput.keyboard,
    }
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("tts_narrate", SCRIPTS_DIR / "tts-narrate.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["tts_narrate"] = mod
        spec.loader.exec_module(mod)
    return mod


class TestHotkeyComplete:
    def test_exact_match_returns_true(self, narrate_module):
        hotkey = {"ctrl", "shift", "f5"}
        assert narrate_module._hotkey_complete({"ctrl", "shift", "f5"}, hotkey) is True

    def test_superset_returns_false(self, narrate_module):
        """Narrate uses exact equality (==), not subset — extra keys must disqualify."""
        hotkey = {"ctrl", "shift", "f5"}
        assert narrate_module._hotkey_complete({"ctrl", "shift", "f5", "extra"}, hotkey) is False

    def test_subset_returns_false(self, narrate_module):
        hotkey = {"ctrl", "shift", "f5"}
        assert narrate_module._hotkey_complete({"ctrl", "shift"}, hotkey) is False

    def test_empty_current_returns_false(self, narrate_module):
        hotkey = {"ctrl", "shift", "f5"}
        assert narrate_module._hotkey_complete(set(), hotkey) is False

    def test_single_key_hotkey_matches(self, narrate_module):
        assert narrate_module._hotkey_complete({"f5"}, {"f5"}) is True

    def test_single_key_hotkey_no_match(self, narrate_module):
        assert narrate_module._hotkey_complete({"ctrl"}, {"f5"}) is False

    def test_empty_hotkey_matches_empty_current(self, narrate_module):
        """Degenerate case: empty hotkey is trivially satisfied by empty keys."""
        assert narrate_module._hotkey_complete(set(), set()) is True

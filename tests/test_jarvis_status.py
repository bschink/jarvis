"""Tests for scripts/jarvis-status.py — service health monitor."""

import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


@pytest.fixture(scope="module")
def status_module():
    spec = importlib.util.spec_from_file_location("jarvis_status", SCRIPTS_DIR / "jarvis-status.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["jarvis_status"] = mod
    spec.loader.exec_module(mod)
    return mod


class TestServiceStatus:
    def test_down_when_file_missing(self, status_module, tmp_path):
        with patch.object(Path, "exists", return_value=False):
            result = status_module.service_status("missing-service")
        assert result == "DOWN"

    def test_up_when_heartbeat_is_fresh(self, status_module, tmp_path):
        hb_file = tmp_path / "jarvis-test-svc.heartbeat"
        hb_file.write_text(str(time.time()))

        original_init = Path.__init__

        def patched_path(self, *args, **kwargs):
            original_init(self, *args, **kwargs)

        with patch("jarvis_status.Path") as MockPath:
            mock_p = MagicMock()
            mock_p.exists.return_value = True
            mock_p.read_text.return_value = str(time.time())
            MockPath.return_value = mock_p
            result = status_module.service_status("test-svc")
        assert result == "UP"

    def test_stale_when_heartbeat_is_old(self, status_module, tmp_path):
        old_ts = str(time.time() - 999)  # 999s ago — well past HEARTBEAT_STALE_S (90)

        with patch("jarvis_status.Path") as MockPath:
            mock_p = MagicMock()
            mock_p.exists.return_value = True
            mock_p.read_text.return_value = old_ts
            MockPath.return_value = mock_p
            result = status_module.service_status("old-svc")
        assert result == "STALE"

    def test_down_when_file_contains_garbage(self, status_module):
        with patch("jarvis_status.Path") as MockPath:
            mock_p = MagicMock()
            mock_p.exists.return_value = True
            mock_p.read_text.return_value = "not-a-timestamp"
            MockPath.return_value = mock_p
            result = status_module.service_status("bad-svc")
        assert result == "DOWN"

    def test_down_when_read_raises_oserror(self, status_module):
        with patch("jarvis_status.Path") as MockPath:
            mock_p = MagicMock()
            mock_p.exists.return_value = True
            mock_p.read_text.side_effect = OSError("permission denied")
            MockPath.return_value = mock_p
            result = status_module.service_status("unreadable-svc")
        assert result == "DOWN"

    def test_services_list_is_nonempty(self, status_module):
        assert len(status_module.SERVICES) >= 3

    def test_all_listed_services_are_strings(self, status_module):
        assert all(isinstance(s, str) for s in status_module.SERVICES)

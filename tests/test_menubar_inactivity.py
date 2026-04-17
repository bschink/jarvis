"""Tests for menubar/inactivity.py — InactivityWatcher logic."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import services as svc
from inactivity import InactivityWatcher

_SERVICE = svc.SERVICES_BY_PLIST["com.whisper.server"]


def test_initial_state_not_idle():
    watcher = InactivityWatcher(_SERVICE, timeout_minutes=30)
    assert watcher.idle_minutes() < 1


def test_record_activity_resets_timer():
    watcher = InactivityWatcher(_SERVICE, timeout_minutes=30)
    # Fake an old last_active timestamp.
    watcher.last_active = datetime.now() - timedelta(minutes=20)
    watcher.record_activity()
    assert watcher.idle_minutes() < 1


def test_check_and_unload_not_yet_idle():
    watcher = InactivityWatcher(_SERVICE, timeout_minutes=30)
    watcher.last_active = datetime.now() - timedelta(minutes=10)
    with patch("inactivity.unload_service") as mock_unload:
        result = watcher.check_and_unload()
    assert result is False
    mock_unload.assert_not_called()


def test_check_and_unload_idle_triggers():
    watcher = InactivityWatcher(_SERVICE, timeout_minutes=30)
    watcher.last_active = datetime.now() - timedelta(minutes=31)
    with patch("inactivity.unload_service", return_value=True) as mock_unload:
        result = watcher.check_and_unload()
    assert result is True
    mock_unload.assert_called_once_with(_SERVICE)


def test_check_and_unload_exactly_at_timeout():
    """Exactly at timeout_minutes should trigger (>=)."""
    watcher = InactivityWatcher(_SERVICE, timeout_minutes=30)
    watcher.last_active = datetime.now() - timedelta(minutes=30, seconds=1)
    with patch("inactivity.unload_service", return_value=True):
        assert watcher.check_and_unload() is True


def test_timeout_is_configurable():
    watcher = InactivityWatcher(_SERVICE, timeout_minutes=5)
    watcher.last_active = datetime.now() - timedelta(minutes=6)
    with patch("inactivity.unload_service", return_value=True) as mock_unload:
        watcher.check_and_unload()
    mock_unload.assert_called_once()


def test_idle_minutes_calculation():
    watcher = InactivityWatcher(_SERVICE, timeout_minutes=30)
    watcher.last_active = datetime.now() - timedelta(minutes=15)
    assert 14.9 < watcher.idle_minutes() < 15.1

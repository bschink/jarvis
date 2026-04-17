"""Tests for menubar/services.py — pure logic only, no launchctl calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import services as svc

# ── is_loaded parsing ─────────────────────────────────────────────────────────


def _make_list_output(*entries: tuple[str, str]) -> str:
    """Build fake `launchctl list` output.  Each entry is (pid, label)."""
    lines = ["PID\tStatus\tLabel"]
    for pid, label in entries:
        lines.append(f"{pid}\t0\t{label}")
    return "\n".join(lines)


def test_is_loaded_running_process():
    """A numeric PID means the process is running → True."""
    output = _make_list_output(("1234", "com.whisper.server"))
    service = svc.SERVICES_BY_PLIST["com.whisper.server"]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=output)
        assert svc.is_loaded(service) is True


def test_is_loaded_registered_but_stopped():
    """PID column '-' means registered but not running → False."""
    output = _make_list_output(("-", "com.whisper.server"))
    service = svc.SERVICES_BY_PLIST["com.whisper.server"]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=output)
        assert svc.is_loaded(service) is False


def test_is_loaded_not_in_list():
    """Label absent from output → False."""
    output = _make_list_output(("999", "com.something.else"))
    service = svc.SERVICES_BY_PLIST["com.kokoro.server"]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=output)
        assert svc.is_loaded(service) is False


def test_is_loaded_launchctl_fails():
    """Non-zero exit code → False."""
    service = svc.SERVICES_BY_PLIST["com.whisper.server"]
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="")
        assert svc.is_loaded(service) is False


# ── plist_exists ──────────────────────────────────────────────────────────────


def test_plist_exists_true(tmp_path):
    plist_file = tmp_path / "com.test.plist"
    plist_file.touch()
    service = svc.Service(
        name="Test",
        plist="com.test",
        plist_path=str(plist_file),
        health_url="",
        memory_mb=0,
    )
    assert svc.plist_exists(service) is True


def test_plist_exists_false(tmp_path):
    service = svc.Service(
        name="Test",
        plist="com.test",
        plist_path=str(tmp_path / "missing.plist"),
        health_url="",
        memory_mb=0,
    )
    assert svc.plist_exists(service) is False


# ── SERVICES registry ─────────────────────────────────────────────────────────


def test_services_by_plist_covers_all():
    """Every service in SERVICES is reachable via SERVICES_BY_PLIST."""
    for service in svc.SERVICES:
        assert svc.SERVICES_BY_PLIST[service.plist] is service


def test_services_have_names():
    for service in svc.SERVICES:
        assert service.name, f"Service {service.plist} has an empty name"


def test_ollama_service_has_zero_memory():
    """Ollama memory is dynamic; the static field should be 0 (sentinel)."""
    ollama = svc.SERVICES_BY_PLIST["homebrew.mxcl.ollama"]
    assert ollama.memory_mb == 0


def test_process_name_for_dictation():
    """Dictation hotkey has a process name for psutil-based health check."""
    dictate = svc.SERVICES_BY_PLIST["com.whisper.dictate"]
    assert dictate.process_name != ""
    assert dictate.health_url == ""

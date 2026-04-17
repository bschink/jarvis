"""Tests for menubar/health.py — HTTP and process-based health checks."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import health
import services as svc

_WHISPER = svc.SERVICES_BY_PLIST["com.whisper.server"]
_KOKORO = svc.SERVICES_BY_PLIST["com.kokoro.server"]
_DICTATE = svc.SERVICES_BY_PLIST["com.whisper.dictate"]


# ── HTTP health check ─────────────────────────────────────────────────────────


def _http_client(status_code: int | None = 200, raises: Exception | None = None):
    mock_client = MagicMock()
    if raises is not None:
        mock_client.get.side_effect = raises
    else:
        mock_client.get.return_value = MagicMock(status_code=status_code)
    ctx = MagicMock()
    ctx.__enter__ = lambda s: mock_client
    ctx.__exit__ = MagicMock(return_value=False)
    return patch("httpx.Client", return_value=ctx)


def test_check_health_http_200():
    with _http_client(200):
        assert health.check_health(_WHISPER) is True


def test_check_health_http_405():
    """405 still counts as healthy (server is up, just rejected GET)."""
    with _http_client(405):
        assert health.check_health(_WHISPER) is True


def test_check_health_http_connection_refused():
    import httpx

    with _http_client(raises=httpx.ConnectError("refused")):
        assert health.check_health(_WHISPER) is False


def test_check_health_http_timeout():
    import httpx

    with _http_client(raises=httpx.TimeoutException("timeout")):
        assert health.check_health(_KOKORO) is False


# ── Process-based health check ────────────────────────────────────────────────


def _fake_proc(name: str):
    p = MagicMock()
    p.info = {"name": name}
    return p


def test_check_health_process_found():
    procs = [_fake_proc("jarvis-dictate")]
    with patch("psutil.process_iter", return_value=procs):
        assert health.check_health(_DICTATE) is True


def test_check_health_process_not_found():
    procs = [_fake_proc("python3"), _fake_proc("bash")]
    with patch("psutil.process_iter", return_value=procs):
        assert health.check_health(_DICTATE) is False


def test_check_health_process_no_such_process():
    import psutil

    class _DeadProc:
        @property
        def info(self):
            raise psutil.NoSuchProcess(pid=1)

    with patch("psutil.process_iter", return_value=[_DeadProc()]):
        # Should not raise — just returns False.
        result = health.check_health(_DICTATE)
    assert result is False


def test_check_health_no_process_name():
    """Service with empty process_name and empty health_url → False."""
    service = svc.Service(
        name="Bare",
        plist="com.bare",
        plist_path="/nonexistent",
        health_url="",
        memory_mb=0,
        process_name="",
    )
    assert health.check_health(service) is False

"""
health.py — HTTP and process-based health checks for JARVIS services.

A service is "healthy" if it is reachable and responding, regardless of HTTP
status code. We treat any response (including 4xx/5xx) as "up" because:
  - whisper-server's /inference only accepts POST; GET returns 405 but the
    server is clearly running.
  - The important distinction is "connection refused / timeout" (down) vs
    "got an HTTP response" (up).

Services without a health_url (e.g. Dictation Hotkey) are checked via psutil
process name lookup instead.
"""

from __future__ import annotations

import httpx
import psutil
from services import Service


def check_health(service: Service) -> bool:
    """
    Return True if the service is reachable/running.

    For services with a health_url: HTTP GET with a 2-second timeout.
    Any HTTP response counts as healthy; only connection errors / timeouts
    return False.

    For services without a health_url: scan running processes for
    service.process_name.
    """
    if not service.health_url:
        return _check_process(service.process_name)
    return _check_http(service.health_url)


def _check_http(url: str) -> bool:
    """Return True if url responds to a GET request within 2 seconds."""
    try:
        with httpx.Client(timeout=2.0) as client:
            client.get(url)
        return True
    except Exception:
        return False


def _check_process(process_name: str) -> bool:
    """Return True if a process with the given name is currently running."""
    if not process_name:
        return False
    for proc in psutil.process_iter(["name"]):
        try:
            if proc.info["name"] == process_name:
                return True
        except psutil.NoSuchProcess, psutil.AccessDenied:
            continue
    return False

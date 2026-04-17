"""
inactivity.py — auto-unload timer for idle JARVIS services.

Strategy (per plan):
  - Ollama: rely on its native OLLAMA_KEEP_ALIVE env-var (set via launchd plist
    by generate_plists.py). No watcher needed — Ollama manages model ejection.
  - Whisper Server & Kokoro: maintain a last_active timestamp that is bumped
    every time a health check returns True. If idle for longer than the
    configured timeout, unload the service and show a macOS notification.

"Active" is defined as: the service responded to its health check. This is a
coarse signal (alive ≠ in use) but it's reliable and requires no log-parsing.
If you later want a stricter definition, parse the service log file instead.
"""

from __future__ import annotations

from datetime import datetime

from services import Service, unload_service


class InactivityWatcher:
    """Track idle time for a single service and unload it when idle too long."""

    def __init__(self, service: Service, timeout_minutes: int) -> None:
        self.service = service
        self.timeout_minutes = timeout_minutes
        self.last_active: datetime = datetime.now()

    def record_activity(self) -> None:
        """Call each time the service is confirmed healthy (health check passed)."""
        self.last_active = datetime.now()

    def idle_minutes(self) -> float:
        """Seconds since last recorded activity, expressed in minutes."""
        return (datetime.now() - self.last_active).total_seconds() / 60

    def check_and_unload(self) -> bool:
        """
        Unload the service if it has been idle for longer than timeout_minutes.

        Returns True if the service was unloaded, False otherwise.
        The caller (app.py) is responsible for showing the notification so that
        rumps.notification() is always called from the right context.
        """
        if self.idle_minutes() >= self.timeout_minutes:
            return unload_service(self.service)
        return False

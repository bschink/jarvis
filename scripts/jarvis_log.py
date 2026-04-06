"""
jarvis_log.py — structured log helper for JARVIS daemons.

All daemons write to stdout, which launchd captures to /tmp/<label>.log.
Using a consistent format makes multi-service tailing and grepping easier.

Format: ISO-8601 timestamp | service | level | message
Example: 2026-04-06T12:00:00 | whisper-dictate | INFO | Streaming started
"""

import time


def log(service: str, level: str, message: str) -> None:
    """Print a structured log line to stdout (captured by launchd)."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"{ts} | {service} | {level} | {message}", flush=True)

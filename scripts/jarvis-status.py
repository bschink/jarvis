#!/usr/bin/env python3
"""
JARVIS service health monitor.

Reads /tmp/jarvis-<service>.heartbeat files written by each daemon.
Each file contains a Unix timestamp updated every HEARTBEAT_INTERVAL_S seconds.

Status:
  UP    — heartbeat file exists and age < HEARTBEAT_STALE_S
  STALE — heartbeat file exists but age >= HEARTBEAT_STALE_S (daemon may have hung)
  DOWN  — heartbeat file absent (daemon not running or never started)

Usage: uv run python ~/scripts/jarvis-status.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from jarvis_config import HEARTBEAT_STALE_S

SERVICES = [
    "whisper-dictate",
    "kokoro-server",
    "tts-narrate",
]


def service_status(name: str) -> str:
    path = Path(f"/tmp/jarvis-{name}.heartbeat")
    if not path.exists():
        return "DOWN"
    try:
        age = time.time() - float(path.read_text())
        return "UP" if age < HEARTBEAT_STALE_S else "STALE"
    except ValueError, OSError:
        return "DOWN"


def main() -> None:
    col_w = max(len(s) for s in SERVICES) + 2
    for svc in SERVICES:
        status = service_status(svc)
        indicator = {"UP": "●", "STALE": "◐", "DOWN": "○"}.get(status, "?")
        print(f"{indicator}  {svc:<{col_w}} {status}")


if __name__ == "__main__":
    main()

"""
jarvis_log.py — structured log helper for JARVIS daemons.

All daemons write to stdout, which launchd captures to /tmp/<label>.log.
Using a consistent format makes multi-service tailing and grepping easier.

Format: ISO-8601 timestamp | service | level | message
Example: 2026-04-06T12:00:00 | whisper-dictate | INFO | Streaming started
"""

import re
import time


def log(service: str, level: str, message: str) -> None:
    """Print a structured log line to stdout (captured by launchd)."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"{ts} | {service} | {level} | {message}", flush=True)


# ── Whisper output cleaning ──────────────────────────────────────────────────

_TIMESTAMP_RE = re.compile(r"\[[\d:.]+ --> [\d:.]+\]\s*")
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")

# Common whisper hallucinations during silence — language-agnostic short phrases
HALLUCINATIONS = {
    "Thank you.",
    "Thank you!",
    "Thanks for watching.",
    "Thanks for watching!",
    "Thank you for watching.",
    "Thank you so much.",
    "Please subscribe.",
    "Okay.",
    "Okay!",
    "OK.",
    "Amen.",
    "Bye.",
    "Bye!",
    "...",
    ". . .",
    ".",
}


def clean_whisper_line(raw: str) -> str:
    """Strip ANSI codes, carriage-return rewrites, and timestamp prefixes."""
    line = _ANSI_RE.sub("", raw)
    line = line.split("\r")[-1]
    return _TIMESTAMP_RE.sub("", line).strip()


def is_hallucination(text: str) -> bool:
    """Return True if text is a known Whisper hallucination or noise fragment."""
    return text in HALLUCINATIONS or len(text) <= 2

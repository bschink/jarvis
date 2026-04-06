"""Tests for scripts/jarvis_log.py — structured log format."""

import re

import jarvis_log


class TestLogFormat:
    def test_output_has_four_pipe_separated_fields(self, capsys):
        jarvis_log.log("whisper-dictate", "INFO", "test message")
        out = capsys.readouterr().out.strip()
        parts = out.split(" | ")
        assert len(parts) == 4, f"Expected 4 fields, got {len(parts)}: {out!r}"

    def test_timestamp_field_is_iso_format(self, capsys):
        jarvis_log.log("kokoro-server", "INFO", "ready")
        out = capsys.readouterr().out.strip()
        ts = out.split(" | ")[0]
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", ts), f"Bad timestamp: {ts!r}"

    def test_service_field_is_preserved(self, capsys):
        jarvis_log.log("my-service", "WARN", "something happened")
        out = capsys.readouterr().out.strip()
        assert out.split(" | ")[1] == "my-service"

    def test_level_field_is_preserved(self, capsys):
        jarvis_log.log("svc", "ERROR", "boom")
        out = capsys.readouterr().out.strip()
        assert out.split(" | ")[2] == "ERROR"

    def test_message_field_is_preserved(self, capsys):
        jarvis_log.log("svc", "INFO", "hello world")
        out = capsys.readouterr().out.strip()
        assert out.split(" | ")[3] == "hello world"

    def test_output_ends_with_newline(self, capsys):
        jarvis_log.log("svc", "INFO", "msg")
        raw = capsys.readouterr().out
        assert raw.endswith("\n")

    def test_message_with_pipe_character(self, capsys):
        """A pipe in the message itself should not break the format — it lands in field 4."""
        jarvis_log.log("svc", "INFO", "a | b")
        out = capsys.readouterr().out.strip()
        parts = out.split(" | ")
        # There will be 5 parts but field [3:] joined should reconstruct the message
        assert " | ".join(parts[3:]) == "a | b"

"""Tests for menubar/chat.py — query_ollama with mocked HTTP."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import chat


def _mock_response(text: str, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = {"response": text}
    mock.text = text
    return mock


def _patch_client(response: MagicMock):
    """Context-manager helper that patches httpx.Client with a given response."""
    mock_client = MagicMock()
    mock_client.post.return_value = response
    ctx = MagicMock()
    ctx.__enter__ = lambda s: mock_client
    ctx.__exit__ = MagicMock(return_value=False)
    return patch("httpx.Client", return_value=ctx), mock_client


# ── Happy path ────────────────────────────────────────────────────────────────


def test_query_ollama_returns_text():
    patcher, mock_client = _patch_client(_mock_response("Hello, I am JARVIS."))
    with patcher:
        result = chat.query_ollama("Hi", "qwen3.5:9b")
    assert result == "Hello, I am JARVIS."


def test_query_ollama_sends_correct_payload():
    patcher, mock_client = _patch_client(_mock_response("ok"))
    with patcher:
        chat.query_ollama("test prompt", "qwen3.5:9b")
    call_kwargs = mock_client.post.call_args
    payload = call_kwargs[1]["json"] if call_kwargs[1] else call_kwargs[0][1]
    assert payload["model"] == "qwen3.5:9b"
    assert payload["prompt"] == "test prompt"
    assert payload["stream"] is False


# ── Truncation ────────────────────────────────────────────────────────────────


def test_query_ollama_truncates_long_response():
    long_text = "x" * 900
    patcher, _ = _patch_client(_mock_response(long_text))
    with patcher:
        result = chat.query_ollama("q", "qwen3.5:9b")
    assert len(result) < 900
    assert "truncated" in result.lower()


def test_query_ollama_no_truncation_under_limit():
    short_text = "y" * 799
    patcher, _ = _patch_client(_mock_response(short_text))
    with patcher:
        result = chat.query_ollama("q", "qwen3.5:9b")
    assert result == short_text


# ── Error handling ────────────────────────────────────────────────────────────


def test_query_ollama_connect_error():
    import httpx

    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.ConnectError("refused")
    ctx = MagicMock()
    ctx.__enter__ = lambda s: mock_client
    ctx.__exit__ = MagicMock(return_value=False)
    with patch("httpx.Client", return_value=ctx):
        result = chat.query_ollama("hi", "qwen3.5:9b")
    assert "not running" in result.lower()


def test_query_ollama_timeout():
    import httpx

    mock_client = MagicMock()
    mock_client.post.side_effect = httpx.TimeoutException("timed out")
    ctx = MagicMock()
    ctx.__enter__ = lambda s: mock_client
    ctx.__exit__ = MagicMock(return_value=False)
    with patch("httpx.Client", return_value=ctx):
        result = chat.query_ollama("hi", "qwen3.5:9b")
    assert "timed out" in result.lower()


def test_query_ollama_bad_status():
    patcher, _ = _patch_client(_mock_response("Internal Server Error", status_code=500))
    with patcher:
        result = chat.query_ollama("hi", "qwen3.5:9b")
    assert "500" in result


def test_query_ollama_empty_response():
    patcher, _ = _patch_client(_mock_response(""))
    with patcher:
        result = chat.query_ollama("hi", "qwen3.5:9b")
    assert "no response" in result.lower()

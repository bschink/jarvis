"""Tests for menubar/memory.py — format functions and mocked Ollama calls."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import memory as mem

# ── format_memory_line ────────────────────────────────────────────────────────


def test_format_memory_line_normal():
    result = mem.format_memory_line(10.5, 24.0, 20.0)
    assert result == "Memory: 10.5 GB / 24 GB used"
    assert "⚠️" not in result


def test_format_memory_line_warning():
    result = mem.format_memory_line(21.0, 24.0, 20.0)
    assert result.startswith("⚠️")
    assert "21.0 GB" in result


def test_format_memory_line_at_threshold():
    """Exactly at threshold triggers warning (>=)."""
    result = mem.format_memory_line(20.0, 24.0, 20.0)
    assert result.startswith("⚠️")


# ── format_ollama_line ────────────────────────────────────────────────────────


def test_format_ollama_line_empty():
    assert mem.format_ollama_line([]) == "Ollama: no model loaded"


def test_format_ollama_line_single():
    models = [{"name": "qwen3.5:9b", "size_mb": 8704.0}]  # ~8.5 GB
    result = mem.format_ollama_line(models)
    assert "qwen3.5:9b" in result
    assert "8.5 GB" in result


def test_format_ollama_line_multiple():
    models = [
        {"name": "qwen3.5:9b", "size_mb": 8192.0},
        {"name": "qwen3:0.6b", "size_mb": 512.0},
    ]
    result = mem.format_ollama_line(models)
    assert "qwen3.5:9b" in result
    assert "qwen3:0.6b" in result


# ── get_ollama_loaded_models ──────────────────────────────────────────────────


def _mock_response(data: dict, status_code: int = 200) -> MagicMock:
    mock = MagicMock()
    mock.status_code = status_code
    mock.json.return_value = data
    return mock


def test_get_ollama_loaded_models_success():
    payload = {
        "models": [
            {"name": "qwen3.5:9b", "size_vram": 9_000_000_000, "size": 10_000_000_000},
        ]
    }
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = lambda s: mock_client
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response(payload)
        result = mem.get_ollama_loaded_models()

    assert len(result) == 1
    assert result[0]["name"] == "qwen3.5:9b"
    # size_vram preferred
    assert abs(result[0]["size_mb"] - 9_000_000_000 / 1_048_576) < 1


def test_get_ollama_loaded_models_no_models():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = lambda s: mock_client
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response({"models": []})
        result = mem.get_ollama_loaded_models()

    assert result == []


def test_get_ollama_loaded_models_ollama_down():
    import httpx

    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = lambda s: mock_client
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("refused")
        result = mem.get_ollama_loaded_models()

    assert result == []


def test_get_ollama_loaded_models_bad_status():
    with patch("httpx.Client") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value.__enter__ = lambda s: mock_client
        mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = _mock_response({}, status_code=503)
        result = mem.get_ollama_loaded_models()

    assert result == []


def test_get_ollama_loaded_mb_sums():
    models = [
        {"name": "a", "size_mb": 500.0},
        {"name": "b", "size_mb": 300.0},
    ]
    with patch.object(mem, "get_ollama_loaded_models", return_value=models):
        assert mem.get_ollama_loaded_mb() == 800


# ── get_system_memory_gb ──────────────────────────────────────────────────────


def test_get_system_memory_gb_returns_floats():
    used, total = mem.get_system_memory_gb()
    assert total > 0
    assert 0 < used <= total

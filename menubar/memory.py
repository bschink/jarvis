"""
memory.py — system memory pressure and Ollama loaded-model tracking.

Two separate data sources:
  1. psutil.virtual_memory()  — total system RAM usage
  2. GET /api/ps              — currently loaded Ollama models with live sizes

Using the live /api/ps size for Ollama (instead of a static MB estimate) means
the memory display stays accurate when the user switches to a different model.
"""

from __future__ import annotations

import httpx
import psutil

_OLLAMA_PS_URL = "http://127.0.0.1:11434/api/ps"


# ── System memory ─────────────────────────────────────────────────────────────


def get_system_memory_gb() -> tuple[float, float]:
    """Return (used_gb, total_gb) for system RAM."""
    mem = psutil.virtual_memory()
    gb = 1_073_741_824  # 1 GiB
    return mem.used / gb, mem.total / gb


# ── Ollama model tracking ─────────────────────────────────────────────────────


def get_ollama_loaded_models() -> list[dict]:
    """
    Return a list of currently loaded Ollama models fetched from /api/ps.
    Each entry has:
      - name     : str   (e.g. "qwen3:14b")
      - size_mb  : float (VRAM/RAM used by this model in MB)

    Returns [] when Ollama is not running or has no models loaded.
    """
    try:
        with httpx.Client(timeout=2.0) as client:
            response = client.get(_OLLAMA_PS_URL)
        if response.status_code != 200:
            return []
        data = response.json()
        models: list[dict] = []
        for m in data.get("models", []):
            # Prefer size_vram (GPU/ANE allocated); fall back to total size.
            size_bytes: int = m.get("size_vram") or m.get("size") or 0
            models.append(
                {
                    "name": m.get("name", "unknown"),
                    "size_mb": size_bytes / 1_048_576,  # bytes → MiB
                }
            )
        return models
    except Exception:
        return []


def get_ollama_loaded_mb() -> int:
    """
    Return total MiB consumed by all currently loaded Ollama models.
    Used in the aggregate memory calculation shown in the menu bar.
    Returns 0 if Ollama is unreachable or no models are loaded.
    """
    return int(sum(m["size_mb"] for m in get_ollama_loaded_models()))


# ── Formatted display strings ─────────────────────────────────────────────────


def format_memory_line(used_gb: float, total_gb: float, threshold_gb: float) -> str:
    """Return the memory menu item label, with a warning prefix when over threshold."""
    warning = "⚠️ " if used_gb >= threshold_gb else ""
    return f"{warning}Memory: {used_gb:.1f} GB / {total_gb:.0f} GB used"


def format_ollama_line(models: list[dict]) -> str:
    """Return the Ollama model menu item label."""
    if not models:
        return "Ollama: no model loaded"
    parts = [f"{m['name']} ({m['size_mb'] / 1024:.1f} GB)" for m in models]
    return "Ollama: " + ", ".join(parts)

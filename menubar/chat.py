"""
chat.py — one-shot Ollama query for the Quick Chat popover.

Intentionally minimal: no streaming, no conversation history, 60-second timeout.
For anything conversational the user should open the full Open WebUI dashboard.

The model is passed in from app.py (read from menubar_config.json) so swapping
to a newly released model requires only a config edit, no code change.
"""

from __future__ import annotations

import httpx

_GENERATE_URL = "http://127.0.0.1:11434/api/generate"
_MAX_RESPONSE_CHARS = 800
_TRUNCATION_SUFFIX = "\n\n[…truncated — Open Dashboard for full response]"


def query_ollama(prompt: str, model: str) -> str:
    """
    Send a non-streaming prompt to Ollama and return the response text.

    Args:
        prompt: The user's question.
        model:  Ollama model tag to use (e.g. "qwen3:14b").  Read from config
                in app.py so no code change is needed when switching models.

    Returns:
        The model's response, truncated to _MAX_RESPONSE_CHARS if longer.
        A human-readable error string if Ollama is unreachable or fails.
    """
    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                _GENERATE_URL,
                json={"model": model, "prompt": prompt, "stream": False},
            )
    except httpx.ConnectError:
        return "LLM is not running. Start it from the menu first."
    except httpx.TimeoutException:
        return "Request timed out after 60 seconds."
    except Exception as exc:
        return f"Unexpected error: {exc}"

    if response.status_code != 200:
        return f"Ollama returned HTTP {response.status_code}: {response.text[:200]}"

    text: str = str(response.json().get("response", "")).strip()
    if not text:
        return "(No response received)"

    if len(text) > _MAX_RESPONSE_CHARS:
        text = text[:_MAX_RESPONSE_CHARS] + _TRUNCATION_SUFFIX

    return text

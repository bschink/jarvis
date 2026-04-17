"""
llm_client.py — reusable Ollama chat client for JARVIS.

Provides:
  LLMClient           — manages conversation state and streaming
  split_sentences()   — sentence boundary splitter (no external deps)

Design decisions:
  - Uses /api/chat endpoint (native multi-turn history)
  - Streams tokens via requests; yields strings as they arrive
  - Rolling 5-turn verbatim memory window (deque, maxlen=10 messages)
  - Episodic summary: evicted turns are compressed to a 1-sentence running summary
  - Persistent user facts at ~/.jarvis/facts.json
  - System prompt explicitly forbids markdown/bullets/code blocks
  - stream_sentences() buffers tokens to sentence boundaries before yielding
  - prewarm() fires a 1-token dummy call to load the model into GPU memory
"""

import json
import os
import re
import sys
import threading
import time
from collections import deque
from collections.abc import Generator
from pathlib import Path

import requests

sys.path.insert(0, os.path.dirname(__file__))
from jarvis_config import (
    LLM_BASE_URL,
    LLM_CONTEXT_LENGTH,
    LLM_MODEL,
    LLM_TEMPERATURE,
)
from jarvis_log import log

_SVC = "llm-client"
_FACTS_PATH = Path("~/.jarvis/facts.json").expanduser()
_MEMORY_TURNS = 5  # number of verbatim user/assistant turn pairs to keep

SYSTEM_PROMPT = """\
You are JARVIS, a personal AI assistant running entirely on-device on a MacBook Pro. \
You are direct, concise, and helpful. \
Speak in plain prose only — never use markdown, bullet points, numbered lists, \
headers, code blocks, asterisks, or backticks. \
Do not open with "Certainly!", "Of course!", or "Great question!". \
Get straight to the point. \
Keep answers short (1-3 sentences) unless the user explicitly asks for more depth.\
"""

_SENT_END = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    """Split text on sentence-ending punctuation. Returns non-empty stripped parts."""
    parts = _SENT_END.split(text.strip())
    return [p.strip() for p in parts if p.strip()]


class LLMClient:
    """Stateful Ollama chat client with rolling memory and sentence streaming."""

    def __init__(
        self,
        model: str = LLM_MODEL,
        base_url: str = LLM_BASE_URL,
        temperature: float = LLM_TEMPERATURE,
        context_length: int = LLM_CONTEXT_LENGTH,
        system_prompt: str = SYSTEM_PROMPT,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.context_length = context_length
        self.system_prompt = system_prompt
        self._session = requests.Session()
        self._recent: deque[dict[str, str]] = deque(maxlen=_MEMORY_TURNS * 2)
        self._summary: str = ""
        self._facts: dict[str, str] = self._load_facts()
        self._summary_lock = threading.Lock()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load_facts(self) -> dict[str, str]:
        if _FACTS_PATH.exists():
            try:
                data = json.loads(_FACTS_PATH.read_text())
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except (json.JSONDecodeError, OSError) as e:
                log(_SVC, "WARN", f"failed to load facts: {e}")
        return {}

    def save_facts(self) -> None:
        _FACTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _FACTS_PATH.write_text(json.dumps(self._facts, indent=2))

    def set_fact(self, key: str, value: str) -> None:
        self._facts[key] = value
        self.save_facts()

    def forget_fact(self, key: str) -> None:
        self._facts.pop(key, None)
        self.save_facts()

    # ── History ───────────────────────────────────────────────────────────────

    def _build_messages(self, user_text: str) -> list[dict[str, str]]:
        facts_block = ""
        if self._facts:
            facts_block = "\n\nKnown facts about the user:\n" + "\n".join(
                f"- {k}: {v}" for k, v in self._facts.items()
            )
        summary_block = (
            f"\n\nEarlier conversation summary:\n{self._summary}" if self._summary else ""
        )
        system = self.system_prompt + facts_block + summary_block
        messages: list[dict[str, str]] = [{"role": "system", "content": system}]
        messages.extend(self._recent)
        messages.append({"role": "user", "content": user_text})
        return messages

    def _maybe_summarize(self, evicted_user: str, evicted_assistant: str) -> None:
        """Compress an evicted turn into the running summary (non-fatal, best-effort)."""
        prompt = (
            f"Summarize this exchange in one sentence for context memory.\n"
            f"User: {evicted_user}\nAssistant: {evicted_assistant}\n"
            f"Existing summary (extend or replace): {self._summary}"
        )
        try:
            resp = self._session.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": 60, "temperature": 0},
                },
                timeout=15,
            )
            with self._summary_lock:
                self._summary = resp.json().get("response", self._summary).strip()
        except Exception as e:
            log(_SVC, "WARN", f"summary generation failed (non-fatal): {e}")

    def _record_turn(self, user_text: str, assistant_text: str) -> None:
        if len(self._recent) == self._recent.maxlen:
            evicted_user = self._recent[0]["content"]
            evicted_asst = self._recent[1]["content"]
            threading.Thread(
                target=self._maybe_summarize,
                args=(evicted_user, evicted_asst),
                daemon=True,
            ).start()
        self._recent.append({"role": "user", "content": user_text})
        self._recent.append({"role": "assistant", "content": assistant_text})

    # ── Core API ──────────────────────────────────────────────────────────────

    _MAX_RETRIES = 2
    _RETRY_DELAY_S = 1.0

    def stream(self, user_text: str) -> Generator[str]:
        """Yield token strings as they arrive. Records the completed turn on finish.

        Retries up to _MAX_RETRIES times on ConnectionError (Ollama may be restarting).
        """
        messages = self._build_messages(user_text)
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "think": False,  # disable chain-of-thought — voice needs direct answers
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.context_length,
            },
        }
        full: list[str] = []
        last_err: Exception | None = None
        for attempt in range(1 + self._MAX_RETRIES):
            try:
                with self._session.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    stream=True,
                    timeout=60,
                ) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        data = json.loads(line)
                        token = data.get("message", {}).get("content", "")
                        if token:
                            full.append(token)
                            yield token
                        if data.get("done"):
                            break
                last_err = None
                break  # success
            except requests.exceptions.ConnectionError as e:
                last_err = e
                if attempt < self._MAX_RETRIES:
                    log(
                        _SVC,
                        "WARN",
                        f"Ollama connection failed (attempt {attempt + 1}), retrying...",
                    )
                    time.sleep(self._RETRY_DELAY_S)
                    continue
            except Exception as e:
                log(_SVC, "ERROR", f"stream error: {e}")
                return
        if last_err is not None:
            log(_SVC, "ERROR", f"cannot reach Ollama on {self.base_url} — is it running?")
            return
        self._record_turn(user_text, "".join(full))

    def ask(self, user_text: str) -> str:
        """Blocking variant — returns the full response string."""
        return "".join(self.stream(user_text))

    def stream_sentences(self, user_text: str) -> Generator[str]:
        """Yield complete sentences as they become available from the token stream."""
        buffer = ""
        for token in self.stream(user_text):
            buffer += token
            parts = _SENT_END.split(buffer)
            for sentence in parts[:-1]:
                if sentence.strip():
                    yield sentence.strip()
            buffer = parts[-1]
        if buffer.strip():
            yield buffer.strip()

    def prewarm(self) -> None:
        """Send a 1-token dummy request to load the model into GPU memory."""
        log(_SVC, "INFO", f"pre-warming {self.model}...")
        try:
            self._session.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": "hi",
                    "stream": False,
                    "options": {"num_predict": 1},
                },
                timeout=60,
            )
            log(_SVC, "INFO", "model warm")
        except Exception as e:
            log(_SVC, "WARN", f"pre-warm failed (will be slow on first query): {e}")

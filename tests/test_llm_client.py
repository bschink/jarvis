"""Tests for scripts/llm_client.py — all network-free via requests stub."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _make_ndjson_response(tokens: list[str]) -> MagicMock:
    """Build a mock requests response that streams NDJSON token lines."""
    lines = [json.dumps({"message": {"content": t}, "done": False}).encode() for t in tokens]
    lines.append(json.dumps({"message": {"content": ""}, "done": True}).encode())
    mock_resp = MagicMock()
    mock_resp.iter_lines.return_value = iter(lines)
    mock_resp.raise_for_status.return_value = None
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


@pytest.fixture(scope="module")
def llm_module():
    """Load llm_client.py with requests stubbed out."""
    fake_requests = MagicMock()
    fake_session = MagicMock()
    fake_requests.Session.return_value = fake_session
    fake_requests.exceptions.ConnectionError = ConnectionError

    stubs = {"requests": fake_requests}
    with patch.dict(sys.modules, stubs):
        spec = importlib.util.spec_from_file_location("llm_client", SCRIPTS_DIR / "llm_client.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["llm_client"] = mod
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def client(llm_module):
    """Fresh LLMClient with a mocked requests session for each test."""
    fake_session = MagicMock()
    fake_session.post.return_value.__enter__ = lambda s: _make_ndjson_response(["Hello."])
    fake_session.post.return_value.__exit__ = MagicMock(return_value=False)

    c = llm_module.LLMClient()
    c._session = fake_session
    return c


# ── System prompt ─────────────────────────────────────────────────────────────


class TestSystemPrompt:
    def test_forbids_markdown(self, llm_module):
        assert "markdown" in llm_module.SYSTEM_PROMPT.lower()

    def test_forbids_bullet_points(self, llm_module):
        assert "bullet" in llm_module.SYSTEM_PROMPT.lower()

    def test_forbids_code_blocks(self, llm_module):
        assert "code block" in llm_module.SYSTEM_PROMPT.lower()

    def test_is_nonempty(self, llm_module):
        assert len(llm_module.SYSTEM_PROMPT) > 50


# ── split_sentences ───────────────────────────────────────────────────────────


class TestSplitSentences:
    def test_splits_on_period(self, llm_module):
        result = llm_module.split_sentences("Hello world. How are you?")
        assert result == ["Hello world.", "How are you?"]

    def test_splits_on_exclamation(self, llm_module):
        result = llm_module.split_sentences("Great! Now try again.")
        assert result == ["Great!", "Now try again."]

    def test_single_sentence_returns_list_of_one(self, llm_module):
        result = llm_module.split_sentences("Just one sentence.")
        assert result == ["Just one sentence."]

    def test_empty_string_returns_empty(self, llm_module):
        assert llm_module.split_sentences("") == []

    def test_strips_whitespace(self, llm_module):
        result = llm_module.split_sentences("  Hello.  World.  ")
        assert result == ["Hello.", "World."]


# ── Message building ──────────────────────────────────────────────────────────


class TestBuildMessages:
    def test_starts_with_system_role(self, client):
        msgs = client._build_messages("hi")
        assert msgs[0]["role"] == "system"

    def test_ends_with_user_message(self, client):
        msgs = client._build_messages("tell me something")
        assert msgs[-1] == {"role": "user", "content": "tell me something"}

    def test_includes_recent_history(self, client):
        client._recent.append({"role": "user", "content": "ping"})
        client._recent.append({"role": "assistant", "content": "pong"})
        msgs = client._build_messages("next")
        roles = [m["role"] for m in msgs]
        assert "user" in roles[1:-1] or "assistant" in roles[1:-1]

    def test_injects_facts_into_system(self, client):
        client._facts = {"name": "Bene"}
        msgs = client._build_messages("hi")
        assert "Bene" in msgs[0]["content"]

    def test_injects_summary_into_system(self, client):
        client._summary = "We discussed the weather."
        msgs = client._build_messages("hi")
        assert "weather" in msgs[0]["content"]

    def test_no_facts_no_facts_block(self, client):
        client._facts = {}
        msgs = client._build_messages("hi")
        assert "Known facts" not in msgs[0]["content"]


# ── Streaming ─────────────────────────────────────────────────────────────────


class TestStream:
    def test_yields_tokens_in_order(self, client):
        mock_resp = _make_ndjson_response(["Hello", ", ", "world", "."])
        client._session.post.return_value = mock_resp

        tokens = list(client.stream("hi"))
        assert tokens == ["Hello", ", ", "world", "."]

    def test_ask_returns_concatenated_string(self, client):
        mock_resp = _make_ndjson_response(["Paris", " is", " the capital."])
        client._session.post.return_value = mock_resp

        result = client.ask("Capital of France?")
        assert result == "Paris is the capital."

    def test_stream_records_turn(self, client):
        mock_resp = _make_ndjson_response(["Done."])
        client._session.post.return_value = mock_resp
        before = len(client._recent)

        list(client.stream("test"))
        assert len(client._recent) == before + 2  # user + assistant

    def test_connection_error_yields_nothing(self, client):
        client._session.post.side_effect = ConnectionError("refused")
        tokens = list(client.stream("hi"))
        assert tokens == []
        client._session.post.side_effect = None  # reset

    def test_stream_sentences_yields_on_boundary(self, client):
        # Feed tokens that form two sentences
        chars = list("Hello world. How are you?")
        mock_resp = _make_ndjson_response(chars)
        client._session.post.return_value = mock_resp

        sentences = list(client.stream_sentences("test"))
        assert "Hello world." in sentences
        assert any("How are you?" in s for s in sentences)

    def test_stream_sentences_yields_trailing_fragment(self, client):
        mock_resp = _make_ndjson_response(["No period here"])
        client._session.post.return_value = mock_resp

        sentences = list(client.stream_sentences("test"))
        assert sentences == ["No period here"]


# ── Memory ────────────────────────────────────────────────────────────────────


class TestMemory:
    def test_deque_truncates_at_cap(self, llm_module):
        c = llm_module.LLMClient()
        c._session = MagicMock()
        cap = c._recent.maxlen
        for i in range(cap + 4):
            c._recent.append({"role": "user", "content": f"msg {i}"})
        assert len(c._recent) == cap

    def test_record_turn_appends_two_messages(self, client):
        before = len(client._recent)
        client._record_turn("u", "a")
        assert len(client._recent) == before + 2

    def test_set_fact_updates_facts(self, client, llm_module, tmp_path, monkeypatch):
        monkeypatch.setattr(llm_module, "_FACTS_PATH", tmp_path / "facts.json")
        client.set_fact("city", "Berlin")
        assert client._facts.get("city") == "Berlin"

    def test_forget_fact_removes_key(self, client, llm_module, tmp_path, monkeypatch):
        client._facts["lang"] = "Python"
        monkeypatch.setattr(llm_module, "_FACTS_PATH", tmp_path / "facts.json")
        client.forget_fact("lang")
        assert "lang" not in client._facts


# ── Pre-warm ──────────────────────────────────────────────────────────────────


class TestPrewarm:
    def test_prewarm_calls_generate_endpoint(self, client):
        client._session.post.side_effect = None
        client._session.post.return_value = MagicMock(
            json=lambda: {"response": ""}, raise_for_status=lambda: None
        )
        client.prewarm()
        call_url = client._session.post.call_args[0][0]
        assert "/api/generate" in call_url

    def test_prewarm_survives_connection_error(self, client):
        client._session.post.side_effect = ConnectionError("refused")
        client.prewarm()  # must not raise
        client._session.post.side_effect = None


# ── Facts persistence ─────────────────────────────────────────────────────────


class TestFactsPersistence:
    def test_load_facts_returns_empty_on_missing_file(self, llm_module, tmp_path, monkeypatch):
        monkeypatch.setattr(llm_module, "_FACTS_PATH", tmp_path / "nonexistent.json")
        c = llm_module.LLMClient()
        assert c._facts == {}

    def test_load_facts_returns_empty_on_corrupt_json(self, llm_module, tmp_path, monkeypatch):
        bad = tmp_path / "facts.json"
        bad.write_text("not json {{{")
        monkeypatch.setattr(llm_module, "_FACTS_PATH", bad)
        c = llm_module.LLMClient()
        assert c._facts == {}

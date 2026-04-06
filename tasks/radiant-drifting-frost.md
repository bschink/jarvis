# JARVIS — Full Implementation Plan

## Context

JARVIS is a 100% local personal AI assistant (STT → LLM → TTS pipeline) running on an M5 Pro MacBook.
STT (whisper.cpp push-to-talk) and TTS (Kokoro + Qwen3-TTS dual-engine router, read-aloud daemon) are complete
and production-ready, with 60 passing tests and a working pre-commit pipeline (ruff + mypy + pytest).

The immediate blocker is a mypy version mismatch between `pyproject.toml` (mypy 1.20) and
`.pre-commit-config.yaml` (mirrors-mypy pinned at v1.19.1) — this causes "unused type: ignore" errors
in 4 test files and fails every commit. After fixing that, the remaining work is: LLM layer,
voice conversation loop, quality hardening, and MCP integration.

---

## Phase Order

| Phase | What | Why this order |
|-------|------|----------------|
| **0** | Fix mypy version mismatch | Unblocks all future commits |
| **1** | Quality hardening (existing code) | Improves current STT/TTS before adding more complexity |
| **2** | LLM layer (Ollama + llm_client.py) | Unblocks the voice loop |
| **3** | Voice conversation loop | Wires all layers together |
| **4** | MCP integration | Final expansion, sandbox-first |

---

## Phase 0 — Fix mypy version mismatch (unblocks all future commits)

**Root cause:** Two mypy installs diverge on `warn_unused_ignores`: `uv run mypy` uses 1.20,
pre-commit uses 1.19.1. Their opinion on which `# type: ignore` comments are "unused" differs.

**Files to modify:**
- `.pre-commit-config.yaml`
- `pyproject.toml`

### Steps

**0.1** In `.pre-commit-config.yaml`, bump the `mirrors-mypy` rev:
```yaml
- repo: https://github.com/pre-commit/mirrors-mypy
  rev: v1.20.0   # was v1.19.1
```
Also add `numpy` to `additional_dependencies` (used in kokoro test):
```yaml
additional_dependencies: [types-requests, pydantic, fastapi, numpy]
```

**0.2** In `pyproject.toml`, tighten the mypy floor:
```toml
"mypy>=1.20",
```

### Verify
```bash
uv run pre-commit run --all-files
git commit -m "chore: align mypy versions"   # must succeed
```

---

## Phase 1 — LLM Layer (Ollama + Qwen3 14B)

### Steps

**1.1 Install Ollama and pull model**
```bash
brew install ollama
ollama pull qwen3:14b-q4_K_M        # ~9GB download
brew services start ollama           # installs launchd plist automatically
```
Verify: `curl -s http://localhost:11434/api/tags | python3 -m json.tool`

**1.2 Add LLM config to `scripts/jarvis_config.py`**

Add at the bottom:
```python
# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_HOST = "127.0.0.1"
LLM_PORT = 11434
LLM_MODEL = "qwen3:14b-q4_K_M"
LLM_BASE_URL = f"http://{LLM_HOST}:{LLM_PORT}"
LLM_CONTEXT_LENGTH = 8192   # 8k is plenty for voice; 14B supports 32k
LLM_TEMPERATURE = 0.7

# ── Voice Loop ────────────────────────────────────────────────────────────────
VOICE_TTS_PYTHON = os.path.expanduser("~/.venv/tts-speak/bin/python")
VOICE_TTS_SCRIPT = os.path.expanduser("~/scripts/tts-router.py")
SILENCE_GAP_S = 1.8   # seconds of no whisper output = end of utterance

# ── Heartbeat ─────────────────────────────────────────────────────────────────
HEARTBEAT_INTERVAL_S = 30
HEARTBEAT_STALE_S = 90   # > 3 missed beats = STALE
```

**1.3 Create `scripts/llm_client.py`**

Reusable Ollama chat client. Key design points:
- Uses `/api/chat` endpoint (native conversation history support)
- Streams tokens via `requests` with `stream=True`
- Rolling `_MEMORY_TURNS = 5` verbatim turn window (deque with maxlen=10)
- Episodic summary: when a turn is evicted from the deque, a 1-sentence summary
  is generated via a low-token background call and appended to `self._summary`
- Persistent facts file at `~/.jarvis/facts.json`
- System prompt explicitly forbids markdown, bullets, code blocks, lists
- `stream_sentences()` generator: buffers tokens until sentence boundary, then yields complete sentences
- `prewarm()` method: sends a 1-token dummy request to load model into GPU memory

```python
SYSTEM_PROMPT = """\
You are JARVIS, a personal AI assistant running entirely on-device. \
You are direct, concise, and helpful. \
Speak in plain prose only. \
Never use markdown, bullet points, numbered lists, headers, code blocks, or asterisks. \
Never open with "Certainly!" or "Of course!". Get straight to the point. \
Keep answers short unless the user explicitly asks for depth.\
"""
```

`stream_sentences()` implementation:
```python
_SENT_END = re.compile(r'(?<=[.!?])\s+')

def stream_sentences(self, user_text: str) -> Generator[str, None, None]:
    buffer = ""
    for token in self.stream(user_text):
        buffer += token
        parts = _SENT_END.split(buffer)
        for s in parts[:-1]:
            if s.strip():
                yield s.strip()
        buffer = parts[-1]
    if buffer.strip():
        yield buffer.strip()
```

**1.4 Create `scripts/jarvis-chat.py`**

Simple CLI loop: pre-warms model, then `input("You: ")` → `client.stream()` → print tokens as they arrive. Exits on `quit`/EOF.

**1.5 Write `tests/test_llm_client.py`**

All tests are network-free. Stub `requests` via `patch.dict(sys.modules)`.

Test cases:
1. `test_system_prompt_forbids_markdown` — SYSTEM_PROMPT contains "Never use markdown"
2. `test_build_messages_starts_with_system_role`
3. `test_build_messages_includes_recent_history`
4. `test_build_messages_injects_facts`
5. `test_build_messages_injects_summary`
6. `test_stream_yields_tokens_in_order` — mock NDJSON response
7. `test_ask_returns_concatenated_string`
8. `test_record_turn_appends_to_deque`
9. `test_memory_window_truncates_at_cap` — fill beyond maxlen, assert len stays at cap
10. `test_prewarm_survives_connection_error` — mock raises `ConnectionError`, assert no raise
11. `test_load_facts_returns_empty_on_missing_file`
12. `test_load_facts_returns_empty_on_corrupt_json`
13. `test_stream_sentences_yields_on_boundary` — feed char-by-char tokens of "Hello. World.", assert yields `["Hello.", "World."]`
14. `test_set_fact_persists_to_file`
15. `test_episodic_summary_called_on_eviction` — fill deque to cap, verify `_maybe_summarize` called

**1.6 Write `docs/llm-setup.md`**

Sections: prerequisites, install Ollama, pull model, start daemon, verify, CLI chat test, model
selection rationale (14B Q4_K_M on 24GB leaves ~10GB free), troubleshooting.

**1.7 Update `install.sh`**

Add `llm_client.py` and `jarvis-chat.py` to `SCRIPTS` array. No new launchd plist — Ollama managed by `brew services`.

### Verify Phase 1
```bash
curl -s http://localhost:11434/api/tags | python3 -m json.tool   # model listed
uv run python ~/scripts/jarvis-chat.py                            # no markdown in response
uv run pytest tests/test_llm_client.py -v                         # all pass
uv run pre-commit run --all-files                                  # green
```

---

## Phase 2 — Voice Conversation Loop

### Architecture

```
Ctrl+F5 pressed (while idle)
      │
      ▼
whisper-stream subprocess  →  stdout reader thread
      │  hallucination filter + echo gate (_tts_active flag)
      │  silence timer resets on each new phrase (1.8s gap = end of utterance)
      ▼
utterance complete  →  LLMClient.stream_sentences()
      │
      │  one sentence at a time
      ▼
tts-router.py subprocess --fast (Kokoro, <1s latency)
      │  _tts_active set while subprocess running
      │
Ctrl+F5 pressed (while TTS active) = BARGE-IN
      →  SIGTERM tts subprocess group
      →  _tts_active.clear()
      →  restart STT immediately
```

**Echo gate:** `_tts_active` threading.Event — any whisper output while set is discarded.
This prevents speaker audio from being fed back into the microphone and hallucinated.

### Steps

**2.1 Create `scripts/jarvis-voice.py`**

Key implementation details:

```python
# Silence detection via threading.Timer (cleaner than polling)
def _reset_silence_timer() -> None:
    global _silence_timer
    if _silence_timer:
        _silence_timer.cancel()
    _silence_timer = threading.Timer(SILENCE_GAP_S, _on_utterance_complete)
    _silence_timer.daemon = True
    _silence_timer.start()

# Echo gate in stdout reader
def _read_stdout(proc: subprocess.Popen[bytes]) -> None:
    for raw in proc.stdout:
        if _tts_active.is_set():
            continue   # discard while TTS is playing
        text = clean_whisper_line(raw.decode("utf-8", errors="replace"))
        if not text or text.startswith("[") or is_hallucination(text):
            continue
        _utterance_buffer.append(text)
        _reset_silence_timer()

# Barge-in: kill TTS subprocess group, clear flag, restart STT
def barge_in() -> None:
    proc = _tts_proc
    if proc is not None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    _tts_active.clear()
    _utterance_buffer.clear()
    start_streaming()

# LLM + per-sentence TTS in background thread
def _llm_and_speak(utterance: str) -> None:
    for sentence in _llm_client.stream_sentences(utterance):
        if _tts_active.is_set():
            break   # barge-in interrupted
        _speak_sentence(sentence)   # blocks until sentence finishes

def _speak_sentence(sentence: str) -> None:
    global _tts_proc
    _tts_active.set()
    proc = subprocess.Popen(
        [VOICE_TTS_PYTHON, VOICE_TTS_SCRIPT, "--fast", sentence],
        start_new_session=True,
    )
    _tts_proc = proc
    try:
        proc.wait()
    finally:
        _tts_proc = None
        _tts_active.clear()
```

Hotkey state machine: same `_current_keys` set + `_triggered` bool pattern as `whisper-dictate.py`.
Ctrl+F5 behavior:
- Idle → start STT
- Streaming → stop STT
- TTS playing → barge-in

`whisper_dictate` pure functions (`clean_whisper_line`, `is_hallucination`, `_TIMESTAMP_RE`,
`_ANSI_RE`, `_HALLUCINATIONS`) are duplicated verbatim into `jarvis-voice.py`. Both are standalone
daemon scripts with separate venvs — duplication is acceptable here; a future `stt_utils.py`
refactor can consolidate them.

**2.2 Create venv and named binary**
```bash
uv venv ~/.venv/jarvis-voice
uv pip install --python ~/.venv/jarvis-voice pynput requests

# Named binary (follow stt-setup.md Part 5 exactly)
ln -s ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/lib/libpython3.14.dylib \
  ~/.venv/jarvis-voice/lib/libpython3.14.dylib
cp ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14 \
  ~/.venv/jarvis-voice/bin/jarvis-voice
codesign --sign - ~/.venv/jarvis-voice/bin/jarvis-voice
```

**2.3 Create `launchd/com.jarvis.voice.plist`**
```xml
<key>Label</key><string>com.jarvis.voice</string>
<key>ThrottleInterval</key><integer>30</integer>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
```
Paths use `YOURUSERNAME` placeholder (substituted by `install.sh`).

**2.4 Grant macOS permissions**
```
System Settings → Privacy & Security → Microphone → add jarvis-voice binary
System Settings → Privacy & Security → Accessibility → add jarvis-voice binary
```

**2.5 Write `tests/test_jarvis_voice.py`**

Stubs: `pynput`, `pynput.keyboard`, `requests`, `llm_client`.

Test cases:
1. `test_clean_whisper_line_strips_ansi_and_timestamp`
2. `test_is_hallucination_short_string`
3. `test_echo_gate_discards_when_tts_active` — set `_tts_active`, run reader logic, assert buffer empty
4. `test_barge_in_clears_utterance_buffer`
5. `test_hotkey_triggers_on_exact_combo`
6. `test_hotkey_ignores_subset_combo`
7. `test_llm_and_speak_breaks_on_barge_in` — mock `_tts_active` mid-iteration

**2.6 Update `install.sh`**

Add `jarvis-voice.py` to `SCRIPTS`, `com.jarvis.voice` to `PLISTS` and `SERVICES`.

### Verify Phase 2
```bash
launchctl list | grep jarvis.voice         # running, no error code
tail -f /tmp/jarvis-voice.log              # shows "Voice loop ready"
# Press Ctrl+F5, say "What's the capital of France?"
# Expected: plain prose TTS response within ~4-6s
# Check /tmp/jarvis-voice.log for echo gate: no utterance lines during playback
uv run pytest tests/test_jarvis_voice.py -v
uv run pre-commit run --all-files
```

---

## Phase 3 — Quality Hardening

Each sub-step is independent and can be done in any order.

### 3A — Confidence-based hallucination filter

**Files to modify:** `scripts/whisper-dictate.py`, `scripts/jarvis-voice.py`

First verify the flag is available:
```bash
whisper-stream --help 2>&1 | grep -i confidence
```

If available, add alongside the existing static list (belt-and-suspenders):
```python
_CONFIDENCE_RE = re.compile(r"\[p=(\d+\.\d+)\]")   # whisper-stream confidence format
CONFIDENCE_THRESHOLD = 0.6

def extract_confidence(line: str) -> float:
    m = _CONFIDENCE_RE.search(line)
    return float(m.group(1)) if m else 1.0
```

Filter low-confidence lines in `_read_stdout` before the hallucination check.
Static `_HALLUCINATIONS` set remains as backup.

Add to `tests/test_whisper_dictate.py`:
- `test_extract_confidence_parses_score`
- `test_extract_confidence_returns_1_on_missing`
- `test_is_low_confidence_filters_below_threshold`

### 3B — Health monitor

**File to create:** `scripts/jarvis-status.py`

Add heartbeat writer thread to each daemon (`whisper-dictate.py`, `kokoro-server.py`, `tts-narrate.py`, `jarvis-voice.py`):
```python
def _heartbeat_writer(service_name: str) -> None:
    path = Path(f"/tmp/jarvis-{service_name}.heartbeat")
    while True:
        path.write_text(str(time.time()))
        time.sleep(HEARTBEAT_INTERVAL_S)
```

`jarvis-status.py` reads all heartbeat files:
```
UP    = file exists and age < HEARTBEAT_STALE_S
STALE = file exists but age >= HEARTBEAT_STALE_S
DOWN  = file missing
```

Output:
```
whisper-dictate           UP
kokoro-server             UP
tts-narrate               UP
jarvis-voice              UP
```

Tests in `tests/test_jarvis_status.py`: `test_status_down`, `test_status_up`, `test_status_stale`.

### 3C — Unified structured log format

**File to create:** `scripts/jarvis_log.py`
```python
import time, sys

def log(service: str, level: str, message: str) -> None:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"{ts} | {service} | {level} | {message}", flush=True)
```

Replace `print(f"...")` calls in all daemons with `log("service-name", "INFO", "...")`.
Output captured by existing launchd log files — no config change needed.

Test in `tests/test_jarvis_log.py`: verify `|`-delimited output format.

### Verify Phase 3
```bash
uv run python ~/scripts/jarvis-status.py   # all UP
tail /tmp/jarvis-voice.log                 # structured format
uv run pytest -v                           # all tests pass
uv run pre-commit run --all-files
```

---

## Phase 4 — MCP Integration

### Prerequisites (must be confirmed before starting)
```bash
tmutil status | grep Running   # Time Machine must be active with a completed backup
ls ~/jarvis-sandbox/           # sandbox directory must exist
```

### Steps

**4.1 Audit the MCP filesystem server source**

Read source before installing:
`https://github.com/modelcontextprotocol/servers/tree/main/src/filesystem`

Confirm: path allow-list is enforced in TypeScript, symlinks outside root are rejected.

**4.2 Install and test the server standalone**
```bash
npx -y @modelcontextprotocol/server-filesystem ~/jarvis-sandbox/
```

**4.3 Configure Claude Desktop**

File to modify: `~/Library/Application Support/Claude/claude_desktop_config.json`
```json
{
  "mcpServers": {
    "jarvis-sandbox-fs": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/benediktschink/jarvis-sandbox"
      ]
    }
  }
}
```

**4.4 Write `docs/mcp-setup.md`**

Sections: prerequisites (Time Machine, Node.js), why sandbox-first, install, configure, verify,
path traversal check, write access caveat, expanding scope conditions.

**Write access caveat:** The standard `@modelcontextprotocol/server-filesystem` exposes write tools.
These must NOT be used until Phase 4 is validated. A proper read-only fork is required before
expanding scope beyond `~/jarvis-sandbox/`. Do not rely on prompting to prevent writes — this
violates JARVIS security rule #2.

### Verify Phase 4
```bash
# In Claude Desktop: "List files in my sandbox"
# Expected: shows ~/jarvis-sandbox/ contents only

# Path traversal check (in Claude Desktop):
# "Read ../Documents/test.txt"
# Expected: access denied

# Confirm no accidental writes occurred
ls -la ~/jarvis-sandbox/    # only files you explicitly created
```

---

## Critical Files Summary

| File | Phase | Action |
|------|-------|--------|
| `.pre-commit-config.yaml` | 0 | bump mirrors-mypy to v1.20.0 |
| `pyproject.toml` | 0 | tighten mypy floor to >=1.20 |
| `scripts/jarvis_config.py` | 1 | add LLM + voice loop config |
| `scripts/llm_client.py` | 1 | create — reusable Ollama client |
| `scripts/jarvis-chat.py` | 1 | create — CLI chat loop |
| `tests/test_llm_client.py` | 1 | create — 15 tests, network-free |
| `docs/llm-setup.md` | 1 | create — setup guide |
| `install.sh` | 1,2 | add new scripts + voice plist |
| `scripts/jarvis-voice.py` | 2 | create — voice conversation loop |
| `launchd/com.jarvis.voice.plist` | 2 | create — launchd service |
| `tests/test_jarvis_voice.py` | 2 | create — 7 tests |
| `scripts/whisper-dictate.py` | 3A | add confidence filter |
| `scripts/jarvis-voice.py` | 3A | add confidence filter |
| `scripts/jarvis_log.py` | 3C | create — structured log helper |
| `scripts/jarvis-status.py` | 3B | create — health monitor |
| All daemons | 3B,3C | add heartbeat + structured logging |
| `~/Library/.../claude_desktop_config.json` | 4 | add MCP server entry |
| `docs/mcp-setup.md` | 4 | create — MCP setup guide |

## Port Inventory

| Port | Service |
|------|---------|
| 2022 | whisper-server (existing) |
| 8880 | kokoro-server (existing) |
| 11434 | Ollama (Phase 1) |

No new ports added through Phase 4.

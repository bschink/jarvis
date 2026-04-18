# LLM Setup — Ollama + Qwen3.5 9B

Local language model for JARVIS. Qwen3.5 9B Q4_K_M runs at ~25–35 tok/s on M5 Pro,
leaves ~15 GB of the 24 GB unified memory free for the OS and TTS models, and supports
up to 128k context (JARVIS uses 32k by default).

---

## Prerequisites

- Homebrew installed
- macOS 26.4, M5 Pro (or any Apple Silicon with ≥ 16 GB RAM)
- `brew` in PATH

---

## Part 1 — Install Ollama

```bash
brew install ollama
```

Verify:

```bash
ollama --version
# ollama version 0.20.x or newer
```

---

## Part 2 — Pull the model

```bash
ollama pull qwen3.5:9b
```

This downloads ~6.6 GB to `~/.ollama/models/`. Takes 5–10 minutes depending on connection.

Verify the model is listed:

```bash
ollama list
# NAME            ID              SIZE    MODIFIED
# qwen3.5:9b      ...             6.6 GB  ...
```

---

## Part 3 — Start the Ollama daemon

```bash
brew services start ollama
```

This installs a launchd plist at `~/Library/LaunchAgents/homebrew.mxcl.ollama.plist` and
starts Ollama on `127.0.0.1:11434` now and on every login.

Verify:

```bash
curl -s http://localhost:11434/api/tags | python3 -m json.tool
# Should list qwen3:14b under "models"
```

---

## Part 4 — Test via CLI chat

```bash
uv run python ~/scripts/jarvis-chat.py
```

Expected output:

```
2026-...-...T... | llm-client | INFO | pre-warming qwen3.5:9b...
2026-...-...T... | llm-client | INFO | model warm

You: What is the capital of France?
JARVIS: Paris is the capital of France.

You: quit
[JARVIS] Goodbye.
```

The first query after a cold start takes ~6–8 s while the model loads into GPU memory.
Subsequent queries in the same session start responding in ~1 s.

---

## Part 5 — Verify no markdown in responses

Qwen3 defaults to markdown-heavy output. The JARVIS system prompt overrides this.
Quick check:

```bash
uv run python ~/scripts/jarvis-chat.py
You: Give me three tips for staying healthy.
# Expected: plain prose, no bullet points or asterisks
```

---

## Key configuration

All LLM settings live in `scripts/jarvis_config.py`:

| Variable | Default | Notes |
|---|---|---|
| `LLM_MODEL` | `qwen3.5:9b` | Change to `qwen3.5:4b` for faster/smaller |
| `LLM_TEMPERATURE` | `0.7` | Lower = more deterministic |
| `LLM_CONTEXT_LENGTH` | `32768` | Tokens of context per request (model supports 128k) |
| `LLM_BASE_URL` | `http://127.0.0.1:11434` | Must match `OLLAMA_HOST` env var if changed |

Run `./install.sh` after editing config to deploy changes.

---

## Troubleshooting

**`curl` to port 11434 returns nothing:**
```bash
brew services restart ollama
launchctl list | grep ollama
tail -f ~/Library/Logs/Homebrew/ollama/ollama.log
```

**Model not found error:**
```bash
ollama list          # check it's listed
ollama pull qwen3.5:9b   # re-pull if missing
```

**Slow first response (>10 s):**
Normal on first query — model is loading into memory. The `prewarm()` call in
`jarvis-chat.py` and `jarvis-voice.py` handles this automatically at daemon startup.

**Ollama uses wrong host/port:**
Set `OLLAMA_HOST=127.0.0.1:11434` in launchd environment or update `LLM_BASE_URL`
in `jarvis_config.py`.

**Out of memory errors:**
Qwen3.5 9B Q4_K_M needs ~6.6 GB. If Kokoro and Qwen3-TTS are also loaded:
- Kokoro-ONNX: ~500 MB
- Qwen3-TTS 1.7B (6-bit): ~1.5 GB
- Qwen3.5 9B Q4_K_M: ~6.6 GB
- Total: ~8.6 GB — well within 24 GB unified memory

If you see OOM errors, stop non-essential services first:
```bash
launchctl stop com.kokoro.server
```

# JARVIS

Personal AI assistant running 100% local on an M5 Pro MacBook. No cloud, no API keys, no ongoing costs.

**Pipeline:** Voice → STT → LLM → TTS → Response

| Layer | Tech | Status |
| --- | --- | --- |
| STT | whisper.cpp large-v3-turbo + Core ML | ✅ Done |
| LLM | Qwen3 14B Q4_K_M via Ollama | ✅ Done |
| TTS (fast) | Kokoro-ONNX | ✅ Done |
| TTS (quality) | Qwen3-TTS 1.7B via mlx-audio | ✅ Done |
| TTS routing + narrate | tts-router.py + tts-narrate.py | ✅ Done |
| Orchestration | MCP + Claude Desktop | 🔲 Planned |

## Hotkeys

| Hotkey | Action |
| --- | --- |
| `Ctrl+F5` | Push-to-talk dictation — press to start recording, press again to stop and transcribe |
| `Ctrl+Shift+F5` | Narrate selection — reads whatever text is selected in any app via TTS |
| `Option+F5` | Voice conversation loop — speak to JARVIS, press again while it's speaking to barge in |

## Ports

| Service | Address |
| --- | --- |
| whisper-server | `127.0.0.1:2022` |
| Kokoro-ONNX | `127.0.0.1:8880` |
| Ollama | `127.0.0.1:11434` |

## Repo

```text
jarvis/
├── install.sh                        ← deploy scripts + restart live services
├── scripts/
│   ├── jarvis_config.py              ← single source of truth for all settings
│   ├── whisper-dictate.py            ← Ctrl+F5 push-to-talk dictation daemon
│   ├── kokoro-server.py              ← Kokoro-ONNX HTTP server (port 8880)
│   ├── tts-router.py                 ← routes text to Kokoro or Qwen3-TTS by length
│   └── tts-narrate.py                ← Ctrl+Shift+F5 "read this" daemon
├── launchd/
│   ├── com.whisper.server.plist      ← auto-start whisper-server
│   ├── com.whisper.dictate.plist     ← auto-start dictation daemon
│   ├── com.kokoro.server.plist       ← auto-start Kokoro server
│   └── com.tts.narrate.plist         ← auto-start narrate daemon
├── docs/
│   ├── stt-setup.md                  ← whisper.cpp + hotkey setup guide
│   └── tts-setup.md                  ← Kokoro + Qwen3-TTS setup guide
└── jarvis-sandbox/                   ← isolated workspace for agent experiments
```

## Development

### Fresh clone setup

```bash
# 1. Install Homebrew system tools (whisper.cpp, Ollama) — see docs/ for details
# 2. Install Python dev dependencies
uv sync --group dev

# 3. Install git hooks (run once)
uv run pre-commit install
```

### Day-to-day

```bash
uv run pytest                      # run tests (no hardware required — all mocked)
uv run pre-commit run --all-files  # lint, type-check, test without committing
```

Pre-commit runs automatically on every `git commit`: ruff (lint + format), mypy, pytest.

## Security model

- Read-only data access first; write access behind explicit confirmation gates
- All filesystem agent access scoped to `jarvis-sandbox/` only
- No natural language safety guards — permissions enforced at the system level

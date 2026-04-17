# JARVIS

A voice-first AI assistant that runs entirely on a MacBook Pro M5 Pro (24 GB).
Speech-to-text, a 14B language model, and two text-to-speech engines all run locally —
no cloud services, no API keys, nothing leaves the machine.

You talk to it with a hotkey, it thinks with Qwen3, and it answers out loud through Kokoro.
A macOS menu bar app manages the five backing services and shows live health / memory stats.

## Stack

| Layer | Tech | Notes |
| --- | --- | --- |
| STT | whisper.cpp large-v3-turbo + Core ML | ~6× faster than large-v3 on Apple Silicon |
| LLM | Qwen3 14B Q4_K_M via Ollama | 8k context, streaming sentence output |
| TTS (fast) | Kokoro-ONNX on port 8880 | Real-time, used for conversation |
| TTS (quality) | Qwen3-TTS 1.7B via mlx-audio | Slower, used for long-form "read this" |
| TTS routing | tts-router.py | < 200 chars → Kokoro, ≥ 200 chars → Qwen3-TTS |
| Menu bar | rumps + launchd | Service control, health checks, quick chat, memory monitor |
| Web UI | Open WebUI on port 3000 | Optional browser chat interface |

## Hotkeys

| Hotkey | Action |
| --- | --- |
| `Ctrl+F5` | Push-to-talk dictation — types transcribed text into the focused app |
| `Ctrl+Shift+F5` | Narrate selection — reads highlighted text aloud via TTS |
| `Option+F5` | Voice conversation — speak to JARVIS, press again to barge in |

## Services & ports

| Service | Address | Managed by |
| --- | --- | --- |
| whisper-server (STT) | `127.0.0.1:2022` | launchd |
| Kokoro-ONNX (TTS) | `127.0.0.1:8880` | launchd |
| Ollama (LLM) | `127.0.0.1:11434` | Homebrew services |
| Open WebUI | `127.0.0.1:3000` | launchd |

## Menu bar app

The menu bar app (🧃 icon) provides:

- **Service toggles** — start/stop any service with one click; uses `launchctl kickstart` under the hood
- **Health monitoring** — HTTP and process-based checks every 10 s, icon changes to ⚠️ on failure
- **Memory tracking** — system RAM usage + per-model VRAM from Ollama `/api/ps`
- **Quick Chat** — one-shot LLM query via osascript dialog (no browser needed)
- **Open WebUI** — opens the browser chat interface
- **Inactivity auto-unload** — idle Whisper and Kokoro services are unloaded after 30 min to free RAM
- **Single-instance lock** — prevents duplicate menu bar icons via `fcntl.flock`

## Repo layout

```text
jarvis/
├── install.sh                        ← deploy scripts + plists, restart services
├── scripts/
│   ├── jarvis_config.py              ← single source of truth for all settings
│   ├── jarvis_log.py                 ← structured logging (ISO-8601 | svc | level | msg)
│   ├── llm_client.py                 ← Ollama chat client (streaming, memory, facts)
│   ├── jarvis-chat.py                ← CLI chat REPL
│   ├── jarvis-voice.py               ← Option+F5 voice conversation loop
│   ├── jarvis-status.py              ← heartbeat-based health monitor CLI
│   ├── whisper-dictate.py            ← Ctrl+F5 push-to-talk dictation daemon
│   ├── kokoro-server.py              ← Kokoro-ONNX HTTP server (port 8880)
│   ├── tts-router.py                 ← routes text to Kokoro or Qwen3-TTS
│   └── tts-narrate.py                ← Ctrl+Shift+F5 "read this" daemon
├── menubar/
│   ├── app.py                        ← rumps menu bar application
│   ├── services.py                   ← service registry and launchctl control
│   ├── health.py                     ← HTTP + psutil health checks
│   ├── chat.py                       ← one-shot Ollama query for Quick Chat
│   ├── memory.py                     ← RAM + Ollama model memory tracking
│   ├── inactivity.py                 ← idle service auto-unload
│   ├── generate_plists.py            ← template plist files with real paths
│   └── setup.sh                      ← menubar app setup
├── launchd/
│   ├── com.whisper.server.plist      ← whisper-server auto-start
│   ├── com.whisper.dictate.plist     ← dictation daemon
│   ├── com.kokoro.server.plist       ← Kokoro TTS server
│   ├── com.tts.narrate.plist         ← narrate daemon
│   ├── com.jarvis.voice.plist        ← voice conversation loop
│   ├── com.jarvis.menubar.plist      ← menu bar app
│   └── com.openwebui.plist           ← Open WebUI
├── tests/                            ← 171 tests, all hardware-free (mocked)
├── docs/
│   ├── stt-setup.md                  ← whisper.cpp + Core ML + hotkey
│   ├── tts-setup.md                  ← Kokoro + Qwen3-TTS
│   ├── llm-setup.md                  ← Ollama + Qwen3 14B
│   ├── voice-setup.md                ← voice conversation loop
│   └── menubar-setup.md              ← menu bar app
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
uv run pytest                      # 171 tests, no hardware required
uv run pre-commit run --all-files  # ruff + mypy + pytest without committing
```

Pre-commit runs automatically on every `git commit`: ruff (lint + format), mypy, pytest.

## Security model

- Read-only data access first; write access behind explicit confirmation gates
- All filesystem agent access scoped to `jarvis-sandbox/` only
- No natural language safety guards — permissions enforced at the system level
- Services listen on `127.0.0.1` only — nothing exposed to the network

# JARVIS — Claude Project Instructions

## Project Overview

Personal AI assistant system for Bene, running entirely local, open source, and free on a MacBook Pro M5 Pro (14", 24GB RAM). Inspired by Iron Man's JARVIS/EDITH. No cloud dependencies, no ongoing costs, full data privacy.

**Stack:** whisper.cpp (STT) → Qwen3 14B via Ollama (LLM) → Kokoro-ONNX / Qwen3-TTS (TTS) → MCP + Claude Desktop (orchestration)

## Core Principles

- **100% local** — no API keys, no cloud, no ongoing costs. Never suggest cloud/paid alternatives unless explicitly asked.
- **Open source only** — MIT, Apache 2.0, or equivalent permissive licenses. Flag any dependency that isn't.
- **Security-first** — read-only access to real data first; write access only behind explicit confirmation gates. System-level permission enforcement, never rely on natural language safety instructions to the model.
- **Incremental trust** — sandbox before real data. Test on dummy data for weeks before connecting anything real.
- **Apple Silicon optimised** — prefer Core ML, MLX, and Metal-accelerated paths. This is an M5 Pro with 24GB unified memory.

## Development Setup

- **OS:** macOS 26.4
- **Shell:** use `zsh` conventions; launchd for persistent background services (not cron, not systemd)
- **Python:** use `uv run python` (not pip, not conda)
- **Package management:** Homebrew for system tools, uv for Python dependencies
- **Key ports in use:**
  - `127.0.0.1:2022` — whisper-server (STT)
  - `127.0.0.1:8880` — Kokoro-ONNX (TTS)
  - `127.0.0.1:11434` — Ollama (LLM)

## Repo Structure

```
jarvis/
├── README.md
├── docs/
│   ├── stt-setup.md          ← whisper.cpp + Core ML + hotkey (done)
│   ├── tts-setup.md          ← Qwen3-TTS + Kokoro-ONNX (planned)
│   ├── llm-setup.md          ← Ollama + Qwen3 14B (planned)
│   └── mcp-setup.md          ← Claude Desktop + MCP servers (planned)
├── scripts/
│   └── whisper-dictate.py    ← system-wide push-to-talk dictation (done)
├── launchd/
│   ├── com.whisper.server.plist
│   └── com.whisper.dictate.plist
└── jarvis-sandbox/           ← the ONLY folder any agent gets filesystem access to
```

## Workflow

### Planning & Execution Rules

1. **Plan before touching anything** — for any non-trivial task (new component, config change, script), write out the approach before writing code. Confirm before proceeding.
2. **One component at a time** — JARVIS is layered (STT → LLM → TTS → orchestration). Do not jump layers. Get each layer stable before wiring to the next.
3. **Verify before marking done** — test the actual running service, not just "the code looks right". Check the port, send a real request, confirm the output.
4. **Sandbox first, always** — any agent or MCP feature must be proven in `~/jarvis-sandbox/` before touching real data. No exceptions.
5. **Autonomous bug fixing** — when given a log, error, or failing service, just diagnose and fix it. No back-and-forth asking for obvious context.

### Task Management

1. Write plan to `tasks/todo.md` with checkable items before starting
2. Mark items complete as you go
3. Add a brief summary of what changed and why after each step
4. Capture any gotchas or lessons in `tasks/lessons.md`

### Documentation Standard

Every new component gets a `docs/<component>-setup.md` that covers:
- Prerequisites and install steps
- Exact commands to start/stop the service
- How to verify it's working (what to run, what to expect)
- launchd plist if the service should auto-start
- Known issues and workarounds

## Security Rules (non-negotiable)

These are hard constraints, not preferences. Never suggest patterns that violate them.

1. **Read before write** — connect any data source in read-only mode first, observe for an extended period, add write access deliberately and explicitly.
2. **No natural language safety guards** — do not rely on prompting the model to "be careful". The Summer Yue incident (OpenClaw bulk-deleted 200+ emails when a safety instruction was dropped during context compression) is the canonical reference. Permissions must be enforced at the system/API level.
3. **Hard confirmation gates** — any destructive action (delete, send, modify) must require an explicit out-of-band confirmation step, not just a "yes" in the same chat.
4. **Sandboxed filesystem** — all filesystem MCP access scoped to `~/jarvis-sandbox/` only. Never suggest widening this scope casually.
5. **No skill/plugin marketplaces** — treat community MCP servers and plugins like untrusted npm packages. Read source before installing anything. Do not suggest ClawHub or equivalent registries.
6. **Time Machine prerequisite** — before any agent experiment that touches real data, Time Machine must be confirmed running.

## Component Status

| Component | Status | Notes |
|---|---|---|
| STT (whisper.cpp + hotkey) | 🔲 Planned | `docs/stt-setup.md` written, not yet implemented |
| TTS — Kokoro-ONNX | 🔲 Planned | Real-time, conversational replies |
| TTS — Qwen3-TTS (MLX) | 🔲 Planned | Quality, longer content, voice cloning |
| Local LLM (Ollama + Qwen3 14B) | 🔲 Planned | `docs/llm-setup.md` |
| MCP + Claude Desktop | 🔲 Planned | Read-only MCP first |
| Voice conversation loop | 🔲 Planned | STT → LLM → TTS pipeline |
| OpenClaw integration | ⏸ Deferred | Security concerns; revisit after MCP layer stable |
| n8n orchestration | ⏸ Deferred | After MCP layer stable |

## Key Technology Decisions (don't relitigate without good reason)

- **STT:** whisper.cpp large-v3-turbo + Core ML encoder (not large-v3 — 6× faster, negligible accuracy loss on clean mic audio)
- **LLM:** Qwen3 14B Q4_K_M via Ollama (not MLX-LM — ecosystem integration wins over 20–30% speed gain for now)
- **TTS fast:** Kokoro-ONNX on `127.0.0.1:8880` (real-time, conversational)
- **TTS quality:** Qwen3-TTS 1.7B via mlx-audio (not real-time, batch/reading use)
- **TTS routing:** < ~200 chars or voice loop → Kokoro; > ~200 chars or "read this" → Qwen3-TTS
- **Orchestration start:** MCP + Claude Desktop (not OpenClaw — security, not n8n — premature)

## References

- whisper.cpp: https://github.com/ggml-org/whisper.cpp
- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS
- mlx-audio: https://github.com/Blaizzy/mlx-audio
- kokoro-onnx: https://github.com/thewh1teagle/kokoro-onnx
- Ollama: https://ollama.com
- MCP spec: https://modelcontextprotocol.io
- OpenClaw (deferred): https://github.com/openclaw/openclaw

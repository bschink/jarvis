# JARVIS

Personal AI assistant running 100% local on an M5 Pro MacBook. No cloud, no API keys, no ongoing costs.

**Pipeline:** Voice → STT → LLM → TTS → Response

| Layer | Tech | Status |
| --- | --- | --- |
| STT | whisper.cpp large-v3-turbo + Core ML | Planned |
| LLM | Qwen3 14B Q4_K_M via Ollama | Planned |
| TTS (fast) | Kokoro-ONNX | Planned |
| TTS (quality) | Qwen3-TTS 1.7B via mlx-audio | Planned |
| Orchestration | MCP + Claude Desktop | Planned |

## Ports

| Service | Address |
| --- | --- |
| whisper-server | `127.0.0.1:2022` |
| Kokoro-ONNX | `127.0.0.1:8880` |
| Ollama | `127.0.0.1:11434` |

## Repo

```text
jarvis/
├── docs/          # setup guides per component
├── scripts/       # push-to-talk dictation, helpers
├── launchd/       # plist files for auto-start services
└── jarvis-sandbox/ # isolated workspace for agent experiments
```

## Security model

- Read-only data access first; write access behind explicit confirmation gates
- All filesystem agent access scoped to `jarvis-sandbox/` only
- No natural language safety guards — permissions enforced at the system level

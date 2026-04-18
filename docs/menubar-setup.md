# JARVIS Menu Bar App — Setup Guide

A macOS menu bar app (`rumps`) that acts as the control layer for the JARVIS
stack. Toggle services on/off, monitor memory pressure, run quick one-shot LLM
queries, and auto-unload idle services — all from the menu bar.

---

## Prerequisites

- macOS (Apple Silicon)
- The rest of the JARVIS stack set up (see `stt-setup.md`, `tts-setup.md`, `llm-setup.md`)
- `uv` installed (`brew install uv`)
- Ollama installed via Homebrew (`brew install ollama`)

---

## Install (first time)

```bash
cd /path/to/jarvis
bash menubar/setup.sh
```

This will:

1. Install Python dependencies into the repo's shared `.venv` (adds `rumps`, `httpx`, `psutil`)
2. Install Open WebUI via `uv tool install open-webui --python 3.12` (skipped if already installed; pinned to 3.12 because `pyarrow` has no pre-built wheel for Python 3.14)
3. Generate `~/Library/LaunchAgents/com.jarvis.menubar.plist` and `com.openwebui.plist` with real paths substituted
4. Patch `OLLAMA_KEEP_ALIVE=10m` into the Homebrew Ollama plist (if not already set)
5. Load the menu bar agent via `launchctl`

The 🧃 icon should appear in your menu bar within a few seconds.

---

## Running manually (without launchd)

```bash
cd /path/to/jarvis
uv run python menubar/app.py
```

---

## Menu structure

```text
🧃 (or ⚠️ / ○ depending on health)
├── ● STT — Whisper Server       ← click to toggle
├── ● STT — Dictation Hotkey
├── ○ TTS — Kokoro
├── ● LLM — Ollama
├── ○ Open WebUI
├── ─────────────────────────────
├── Memory: 9.1 GB / 24 GB used
├── Ollama: qwen3.5:9b (6.6 GB)
├── ─────────────────────────────
├── Quick Chat…
├── Open Dashboard
├── ─────────────────────────────
└── Quit JARVIS
```

**Status indicators:**

- `●` = loaded + health check passing
- `◐` = loaded but health check failing (starting up or crashed)
- `○` = not loaded

**Bar icon:**

- `🧃` = all loaded services healthy
- `⚠️` = at least one loaded service unhealthy
- `○` = no services loaded

---

## Configuration

Edit `~/.jarvis/menubar_config.json` (created with defaults on first run):

```json
{
  "inactivity_timeout_minutes": 30,
  "health_check_interval_seconds": 10,
  "memory_warning_threshold_gb": 20,
  "chat_model": "qwen3.5:9b",
  "ollama_keep_alive": "10m"
}
```

| Key | Effect |
| --- | --- |
| `inactivity_timeout_minutes` | Whisper + Kokoro are auto-unloaded after this many idle minutes |
| `health_check_interval_seconds` | How often health checks run (default 10 s) |
| `memory_warning_threshold_gb` | Show ⚠️ on the memory item when system RAM exceeds this |
| `chat_model` | Ollama model tag for the Quick Chat popover. **Change this to swap models — no code edit needed.** |
| `ollama_keep_alive` | Injected into the Ollama launchd plist by `generate_plists.py`. After changing, re-run `uv run python menubar/generate_plists.py` and reload Ollama. |

After editing `ollama_keep_alive`, re-run `generate_plists.py` and reload Ollama:

```bash
uv run python menubar/generate_plists.py
launchctl unload ~/Library/LaunchAgents/homebrew.mxcl.ollama.plist
launchctl load -w ~/Library/LaunchAgents/homebrew.mxcl.ollama.plist
```

---

## Swapping the LLM model

1. Pull the new model: `ollama pull <new-model-tag>`
2. Edit `~/.jarvis/menubar_config.json` → set `"chat_model": "<new-model-tag>"`
3. Restart the menu bar app (Quit from menu, then `launchctl load -w ~/Library/LaunchAgents/com.jarvis.menubar.plist`)

No code changes needed anywhere.

---

## Open WebUI

Open WebUI is installed as a `uv` tool and managed via launchd. It is **not**
started automatically at login — start it from the "Open Dashboard" menu item
or manually:

```bash
launchctl load -w ~/Library/LaunchAgents/com.openwebui.plist
```

Logs: `/tmp/openwebui.log` / `/tmp/openwebui.err`

---

## Auto-unload on inactivity

Whisper Server and Kokoro are automatically unloaded when they have not
responded to a health check for longer than `inactivity_timeout_minutes`. A
macOS notification is shown when this happens.

Ollama manages its own model-unload lifecycle via `OLLAMA_KEEP_ALIVE`. The
process itself stays running; only the loaded model is ejected after the
keepalive timeout. To check the current state: **Ollama: qwen3:14b (8.5 GB)**
vs **Ollama: no model loaded** in the menu.

---

## Logs and debugging

| Service | Logs |
| --- | --- |
| Menu bar app | `/tmp/jarvis-menubar.log` / `/tmp/jarvis-menubar.err` |
| Open WebUI | `/tmp/openwebui.log` / `/tmp/openwebui.err` |
| Ollama | `/opt/homebrew/var/log/ollama.log` |
| Whisper Server | `/tmp/whisper-server.log` |
| Kokoro | `/tmp/kokoro-server.log` |

To tail the menu bar app log:

```bash
tail -f /tmp/jarvis-menubar.err
```

---

## Uninstall

```bash
launchctl unload ~/Library/LaunchAgents/com.jarvis.menubar.plist
launchctl unload ~/Library/LaunchAgents/com.openwebui.plist
rm ~/Library/LaunchAgents/com.jarvis.menubar.plist
rm ~/Library/LaunchAgents/com.openwebui.plist
```

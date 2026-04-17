# JARVIS Menu Bar App — Implementation Plan

This document is an implementation brief for Claude Code. Build everything described here inside the existing `jarvis/` repo. Use `uv` for all Python dependency management. Do not use Docker for the menu bar app itself.

---

## Overview

A lightweight macOS menu bar app (`rumps`) that acts as the control layer for the JARVIS stack. It starts/stops each service independently, monitors memory pressure, shows live health status, provides a quick chat popover, and auto-unloads idle services. Open WebUI runs alongside it as the full chat dashboard.

---

## Repo Structure Changes

Add the following to the existing repo:

```
jarvis/
├── menubar/
│   ├── app.py                  ← main entry point
│   ├── services.py             ← launchd start/stop/status logic
│   ├── health.py               ← HTTP health checks for each service
│   ├── memory.py               ← memory pressure + ollama model tracking
│   ├── inactivity.py           ← auto-unload timer logic
│   └── chat.py                 ← quick chat popover (rumps.Window)
├── launchd/
│   ├── com.whisper.server.plist       ← already exists
│   ├── com.whisper.dictate.plist      ← already exists
│   ├── com.jarvis.menubar.plist       ← NEW: auto-start the menu bar app
│   └── com.openwebui.plist            ← NEW: auto-start Open WebUI
└── docs/
    └── menubar-setup.md        ← NEW: setup guide
```

---

## Dependencies

Add to `menubar/` as a `uv` project:

```toml
# menubar/pyproject.toml
[project]
name = "jarvis-menubar"
requires-python = ">=3.11"
dependencies = [
    "rumps>=0.4.0",           # macOS menu bar framework, MIT
    "httpx>=0.27.0",          # async HTTP for health checks + Ollama API
    "psutil>=6.0.0",          # system memory stats
]
```

Install: `cd menubar && uv sync`

---

## Feature 1: Toggle Controls

**File:** `menubar/services.py`

Define each JARVIS service as a dataclass:

```python
@dataclass
class Service:
    name: str           # display name, e.g. "STT (Whisper)"
    plist: str          # launchd plist label, e.g. "com.whisper.server"
    plist_path: str     # full path to .plist file
    health_url: str     # URL to ping for liveness check
    memory_mb: int      # approximate RAM footprint when loaded
```

Services to define:

| Name | Plist label | Health URL | Approx RAM |
|---|---|---|---|
| STT — Whisper Server | `com.whisper.server` | `http://127.0.0.1:2022/inference` | 1500 MB |
| STT — Dictation Hotkey | `com.whisper.dictate` | n/a (process check) | 80 MB |
| TTS — Kokoro | `com.kokoro.server` | `http://127.0.0.1:8880/health` | 300 MB |
| LLM — Ollama | `com.ollama.server` | `http://127.0.0.1:11434/api/tags` | dynamic (read from `/api/ps`) |
| Open WebUI | `com.openwebui` | `http://127.0.0.1:3000` | 300 MB |

Implement two functions:

```python
def load_service(plist_label: str) -> bool:
    # runs: launchctl load ~/Library/LaunchAgents/<plist_label>.plist
    # returns True on success

def unload_service(plist_label: str) -> bool:
    # runs: launchctl unload ~/Library/LaunchAgents/<plist_label>.plist
    # returns True on success
```

In `app.py`, each service gets a menu item with a checkmark that reflects its current loaded state. Clicking it toggles load/unload. The checkmark updates after the toggle.

Menu structure:

```
🧃 JARVIS                          ← menu bar icon (changes to 🟡 during loading)
├── ● STT — Whisper Server         ← ● green = running, ○ grey = stopped
├── ● STT — Dictation Hotkey
├── ○ TTS — Kokoro
├── ● LLM — Ollama
├── ○ Open WebUI
├── ─────────────────
├── Memory: 10.2 GB / 24 GB used
├── Ollama loaded: qwen3:14b (8.5 GB)
├── ─────────────────
├── Quick Chat...
├── Open Dashboard                 ← opens localhost:3000 in browser
├── ─────────────────
└── Quit JARVIS
```

---

## Feature 2: Status Indicators

**File:** `menubar/health.py`

Each service gets a live health check, not just a check of whether the launchd agent is loaded. A loaded agent that crashed will show as failed.

```python
async def check_health(service: Service) -> bool:
    # For services with a health_url: HTTP GET, timeout=2s, return True if 200
    # For services without (dictation hotkey): check if process name is in psutil.process_iter()
    # Return False on any exception
```

Run health checks on a background timer every **10 seconds**.

Update the menu bar icon based on aggregate status:
- All enabled services healthy → `🧃`
- Any enabled service unhealthy → `⚠️`
- All services stopped → `○` (grey circle using Unicode)

Update each menu item prefix:
- `●` (green via unicode or emoji) = launchd loaded AND health check passing
- `◐` = launchd loaded but health check failing (crashed/starting up)
- `○` = not loaded

---

## Feature 3: Memory Pressure Indicator

**File:** `menubar/memory.py`

Two data points to display:

**1. System memory:**
```python
import psutil
mem = psutil.virtual_memory()
# display: "Memory: X.X GB / 24 GB"
# colour warning threshold: >20 GB used → show ⚠️ next to memory item
```

**2. Ollama loaded models:**
```python
# GET http://127.0.0.1:11434/api/ps
# Returns currently loaded models with their size
# Display: "Ollama: qwen3:14b (8.5 GB)" or "Ollama: no model loaded"
# If multiple models loaded somehow, list each

async def get_ollama_loaded_mb() -> int:
    # Sum the size_vram (or size) field for all loaded models in /api/ps response
    # Returns 0 if Ollama is not running or no models are loaded
    # Used in the aggregate memory display instead of the static memory_mb on the Ollama Service
```

Both update every 10 seconds alongside the health checks.

Add a menu item that is **not clickable** (just informational) showing combined memory state. If total RAM > 20GB, prefix with ⚠️.

Note: The Ollama `Service.memory_mb` field is used for the other services (STT, TTS) where RAM footprint is fixed. For Ollama, always use the live `/api/ps` size — it changes with the loaded model.

---

## Feature 4: Quick Chat Popover

**File:** `menubar/chat.py`

Use `rumps.Window` to show a simple input dialog:

```python
@rumps.clicked("Quick Chat...")
def quick_chat(self, _):
    response = rumps.Window(
        message="Ask JARVIS:",
        title="JARVIS",
        default_text="",
        ok="Send",
        cancel="Cancel",
        dimensions=(400, 80)
    ).run()

    if response.clicked and response.text.strip():
        answer = query_ollama(response.text.strip())
        rumps.alert(title="JARVIS", message=answer, ok="Done")
```

Implement `query_ollama(prompt: str, model: str) -> str`:

- `model` is passed in from `app.py`, which reads `chat_model` from `menubar_config.json`
- POST to `http://127.0.0.1:11434/api/generate`
- `stream: false`
- Timeout: 60s
- If Ollama is not running, return `"LLM is not running. Start it from the menu first."`
- If response exceeds 800 chars, truncate and append `"\n\n[...truncated. Open Dashboard for full response]"`

This is intentionally minimal. The popover is for quick one-off queries. For anything conversational, the user should use Open WebUI.

---

## Feature 5: Open WebUI

**Do not use Docker.** Install Open WebUI as a Python package via `uv`:

```bash
uv tool install open-webui
```

It runs as: `open-webui serve --port 3000`

Create `launchd/com.openwebui.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.openwebui</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/USERNAME/.local/bin/open-webui</string>
        <string>serve</string>
        <string>--port</string>
        <string>3000</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>OLLAMA_BASE_URL</key>
        <string>http://127.0.0.1:11434</string>
        <key>WEBUI_AUTH</key>
        <string>false</string>
    </dict>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/openwebui.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/openwebui.err</string>
</dict>
</plist>
```

Note: Replace `USERNAME` with the actual macOS username. Claude Code should detect this via `os.getenv("USER")` when generating the plist.

The "Open Dashboard" menu item runs:
```python
import subprocess
subprocess.run(["open", "http://127.0.0.1:3000"])
```

If Open WebUI is not running (health check failing), show a `rumps.alert` offering to start it first.

---

## Feature 6: Auto-Unload on Inactivity

**File:** `menubar/inactivity.py`

Track the last request timestamp for each service by tailing their log files or by wrapping the health check with a last-seen timestamp. Simpler approach: maintain a dict `last_active: dict[str, datetime]` that updates every time a health check returns 200 (meaning the service is being used or at minimum alive and responding).

Actually use a more reliable signal: check each service's log file for recent writes. For Ollama specifically, `GET /api/ps` shows currently loaded models — if a model is loaded but no generate requests have come in, Ollama will auto-eject it after its own keepalive timeout. Set Ollama's keepalive explicitly:

```python
# When starting Ollama via launchd, set env var:
# OLLAMA_KEEP_ALIVE=10m
# This is Ollama's built-in idle unload — use it rather than reimplementing it
```

For **whisper-server and Kokoro**, implement a proper inactivity timer:

```python
INACTIVITY_TIMEOUT_MINUTES = 30

class InactivityWatcher:
    def __init__(self, service: Service):
        self.service = service
        self.last_active = datetime.now()
        self._timer = None

    def record_activity(self):
        self.last_active = datetime.now()

    def check(self):
        idle_minutes = (datetime.now() - self.last_active).seconds / 60
        if idle_minutes > INACTIVITY_TIMEOUT_MINUTES:
            unload_service(self.service.plist_label)
            # show a brief notification via rumps.notification()
```

Hook `record_activity()` into the health check loop: if a service was previously responding and still is, it's considered active. If you want a stricter definition of "active" (actual requests, not just alive), parse the service logs instead — but start with the simpler version.

Use `rumps.Timer` to run the inactivity check every 5 minutes.

The timeout should be **user-configurable** via a simple JSON config file at `~/.jarvis/menubar_config.json`:

```json
{
  "inactivity_timeout_minutes": 30,
  "health_check_interval_seconds": 10,
  "memory_warning_threshold_gb": 20,
  "chat_model": "qwen3:14b",
  "ollama_keep_alive": "10m"
}
```

`chat_model` controls which Ollama model the Quick Chat popover uses — change this when a new model drops, no code edit required. `ollama_keep_alive` is substituted into the Ollama launchd plist by `generate_plists.py` (see Setup Script below).

Load this on startup. If the file doesn't exist, write defaults.

---

## Feature 7: Menu Bar App Auto-Start (launchd)

Create `launchd/com.jarvis.menubar.plist` so the menu bar app launches at login:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jarvis.menubar</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/jarvis/menubar/.venv/bin/python</string>
        <string>/path/to/jarvis/menubar/app.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/jarvis-menubar.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/jarvis-menubar.err</string>
</dict>
</plist>
```

Note: Claude Code should substitute actual absolute paths here, not relative ones.

---

## Setup Script

Create `menubar/setup.sh`:

```bash
#!/bin/bash
set -e

echo "Setting up JARVIS menu bar app..."

# 1. Install Python deps
cd "$(dirname "$0")"
uv sync

# 2. Install Open WebUI
uv tool install open-webui

# 3. Generate plists with correct paths and install them
python generate_plists.py  # generates all plists with real paths substituted

# 4. Load the menu bar agent
launchctl load ~/Library/LaunchAgents/com.jarvis.menubar.plist

echo "Done. JARVIS menu bar app is now running."
```

Create `menubar/generate_plists.py` that reads plist templates from `launchd/`, substitutes `USERNAME`, absolute paths, and values from `menubar_config.json` (including `ollama_keep_alive` into the Ollama plist's `OLLAMA_KEEP_ALIVE` env var), then copies them to `~/Library/LaunchAgents/`.

---

## Implementation Order

Build in this sequence — each step is independently testable:

1. `services.py` — launchd load/unload, verify with existing whisper plist
2. `health.py` — HTTP health checks, print results to stdout first
3. `app.py` (skeleton) — menu bar appears with toggle items, no status yet
4. Wire health checks into menu item labels
5. `memory.py` — add memory menu item
6. `chat.py` — add quick chat popover
7. Open WebUI plist + "Open Dashboard" menu item
8. `inactivity.py` — auto-unload timers
9. `generate_plists.py` + `setup.sh`
10. `docs/menubar-setup.md`

---

## Constraints

- No cloud dependencies, no API keys
- All Python, managed with `uv`
- `rumps` only — no PyObjC, no native Swift/Obj-C unless absolutely unavoidable
- Must not crash if a service is not installed (gracefully mark as unavailable)
- Must not load any service automatically on startup — user controls what runs
- Config file at `~/.jarvis/menubar_config.json` — never hardcode timeouts

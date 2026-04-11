# Voice Conversation Loop Setup

Wires all three layers together: Option+F5 starts listening via whisper-stream, speech is
transcribed and sent to Qwen3 14B, and JARVIS responds sentence-by-sentence via Kokoro TTS.
Press Option+F5 again at any point — while listening or while JARVIS is speaking — to stop everything.

---

## Prerequisites

- STT layer working — see `docs/stt-setup.md`
- LLM layer working — see `docs/llm-setup.md`
- TTS layer working — see `docs/tts-setup.md`
- `uv` installed
- All JARVIS scripts deployed to `~/scripts/` (run `./install.sh` from the repo root)

---

## Part 1 — Create the venv

```bash
uv venv ~/.venv/jarvis-voice
uv pip install --python ~/.venv/jarvis-voice pynput requests
```

Verify:

```bash
~/.venv/jarvis-voice/bin/python -c "import pynput, requests; print('ok')"
# ok
```

---

## Part 2 — Named binary (required for launchd)

macOS resolves symlinks before setting the process name, so a real binary copy is needed.
Without this, the process appears as `python3.14` in Activity Monitor and macOS may refuse
Accessibility and Microphone permissions.

```bash
# Symlink libpython into the venv (avoids copying the 60 MB dylib)
ln -s ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/lib/libpython3.14.dylib \
  ~/.venv/jarvis-voice/lib/libpython3.14.dylib

# Copy the interpreter binary under the service name
cp ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14 \
  ~/.venv/jarvis-voice/bin/jarvis-voice

# Adhoc-sign the copy (macOS will block unsigned binaries from using the mic)
codesign --sign - ~/.venv/jarvis-voice/bin/jarvis-voice
```

Verify the name shows correctly:

```bash
~/.venv/jarvis-voice/bin/jarvis-voice --version
# Python 3.14.x
```

---

## Part 3 — Grant macOS permissions

The `jarvis-voice` binary needs two permissions that macOS will prompt for on first use,
but it is cleaner to grant them in advance so the daemon doesn't silently fail.

1. **Microphone** — `System Settings → Privacy & Security → Microphone`
   Add `~/.venv/jarvis-voice/bin/jarvis-voice`

2. **Accessibility** (required by pynput to read global hotkeys)
   `System Settings → Privacy & Security → Accessibility`
   Add `~/.venv/jarvis-voice/bin/jarvis-voice`

If the binary is replaced (e.g. after a Python upgrade), remove and re-add it in both panels.

---

## Part 4 — Deploy and load the launchd service

From the repo root:

```bash
./install.sh
launchctl load ~/Library/LaunchAgents/com.jarvis.voice.plist
```

`install.sh` substitutes your username into the plist and copies all scripts to `~/scripts/`.

Verify it loaded:

```bash
launchctl list | grep jarvis.voice
# should show a PID (non-zero first column) and exit code 0
```

---

## Part 5 — Verify it's working

```bash
tail -f /tmp/jarvis-voice.log
```

Expected startup output:

```
2026-04-08T12:00:00 | jarvis-voice | INFO | pre-warming LLM...
2026-04-08T12:00:03 | jarvis-voice | INFO | ready — press Option+F5 to speak, press again to stop
```

Then press **Option+F5**, say something, and release. Expected log sequence:

```
... | INFO | listening...
... | INFO | heard: 'What's the capital of France?'
... | INFO | utterance: 'What's the capital of France?'
... | INFO | querying LLM: 'What's the capital of France?'
... | INFO | stopped listening
```

You should hear a spoken response within 3–6 seconds.

---

## How the echo gate works

While JARVIS is speaking, `_tts_active` is set. Any whisper output that arrives during
this window is discarded before it reaches the utterance buffer — preventing the microphone
from picking up the speaker audio and hallucinating a second query.

---

## Stopping

Press **Option+F5** at any point to stop everything immediately:

- Any in-flight LLM sentence stream is cancelled
- The TTS subprocess group receives SIGTERM
- STT is terminated and the utterance buffer is flushed
- The daemon returns to idle — press Option+F5 again to start a new conversation

---

## Stop / start manually

```bash
# Stop
launchctl unload ~/Library/LaunchAgents/com.jarvis.voice.plist

# Start
launchctl load ~/Library/LaunchAgents/com.jarvis.voice.plist

# Restart (after install.sh)
launchctl kickstart -k "gui/$(id -u)/com.jarvis.voice"
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| No log output at all | plist not loaded or binary path wrong | Check `launchctl list \| grep jarvis.voice`; re-run `install.sh` |
| `[Errno 13] Permission denied` on mic | Microphone permission missing | Re-add binary in System Settings → Microphone |
| Hotkey does nothing | Accessibility permission missing | Re-add binary in System Settings → Accessibility |
| JARVIS responds but you hear nothing | TTS not running | Check `launchctl list \| grep kokoro`; see `docs/tts-setup.md` |
| Responses contain markdown/bullet points | LLM ignoring system prompt | Ensure Ollama model is `qwen3:14b-q4_K_M`, not a fine-tune |
| Echo feedback loop | Echo gate not firing | Check log for `filtered:` lines during TTS playback |

---

## Known issues

- **Binary must be re-signed after Python upgrades.** If `uv` updates the Python interpreter,
  repeat the `cp` + `codesign` steps in Part 2 and re-add the binary to both permission panels.
- **whisper-stream must already be running.** `jarvis-voice.py` spawns `whisper-stream` as a
  subprocess; it does not depend on the `com.whisper.server` service (that serves the HTTP API
  for dictation). Both can run simultaneously.

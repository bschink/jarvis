# System-Wide STT on macOS (Whisper + Metal GPU + Global Hotkey)

Local, offline, push-to-talk dictation that works in any app. Hold a hotkey, speak, release — text is typed wherever your cursor is. No cloud, no API keys.

**Stack:** whisper.cpp · Metal (Apple GPU) · Python · launchd
**Languages:** English + German (auto-detected)
**Hardware:** Apple Silicon Mac (M1–M5)

---

## Prerequisites

- macOS 14 (Sonoma) or newer
- Homebrew installed
- uv (`brew install uv`)
- Xcode Command Line Tools: `xcode-select --install`

---

## Part 1: Install whisper.cpp

```bash
brew install whisper-cpp
```

Download the large-v3-turbo model (~1.6GB, fast with near-large quality):

```bash
mkdir -p ~/.cache/whisper
curl -L -o ~/.cache/whisper/ggml-large-v3-turbo.bin \
  "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3-turbo.bin"
```

Model is saved to `~/.cache/whisper/ggml-large-v3-turbo.bin`.

Test it:

```bash
whisper-cli \
  --model ~/.cache/whisper/ggml-large-v3-turbo.bin \
  --language auto \
  /path/to/any/audio.wav
```

> **Model size tradeoffs**
>
> | Model | Size | Speed | Quality |
> | ------- | ------ | ------- | --------- |
> | `base` | 142MB | Very fast | OK for commands |
> | `small` | 488MB | Fast | Good |
> | `medium` | ~1.5GB | Fast | Very good |
> | `large-v3-turbo` | 1.6GB | Much faster than large-v3 | Near-large-v3 quality |
> | `large-v3` | ~3GB | Comfortable on M-series | Best |

---

## Part 2: GPU Acceleration

The Homebrew build of whisper-cpp uses **Metal (Apple GPU)** automatically — no configuration needed. whisper-server loads the Metal backend on startup and runs inference on the GPU.

> **Note on Core ML / Neural Engine:** The Homebrew bottle is not compiled with Core ML support (`--use-coreml` is not a recognized flag). Metal GPU acceleration is comparably fast on Apple Silicon and requires no setup.

---

## Part 3: Run the Whisper HTTP Server

whisper.cpp includes a built-in HTTP server with an OpenAI-compatible API.

```bash
whisper-server \
  --model ~/.cache/whisper/ggml-large-v3-turbo.bin \
  --language auto \
  --port 2022 \
  --host 127.0.0.1
```

Test it's working:

```bash
curl http://localhost:2022/inference \
  -F file="@/path/to/audio.wav" \
  -F language="auto"
```

You should get back JSON with a `text` field containing the transcription.

---

## Part 4: Auto-start Server at Login (launchd)

The plist is in the repo at `launchd/com.whisper.server.plist`. Copy it to the LaunchAgents folder and substitute your username:

```bash
sed "s/YOURUSERNAME/$(whoami)/g" \
  $(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/launchd/com.whisper.server.plist \
  > ~/Library/LaunchAgents/com.whisper.server.plist
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.whisper.server.plist
```

Verify it's running:

```bash
launchctl list | grep whisper
```

---

## Part 5: The Dictation Script

Create a dedicated virtual environment and install dependencies:

```bash
uv venv ~/.venv/whisper-dictate
uv pip install --python ~/.venv/whisper-dictate \
  pynput sounddevice soundfile requests numpy
```

Create a named binary so macOS shows **jarvis-dictate** in System Settings and the menu bar instead of python3:

```bash
# Symlink the dylib so the copied binary can find it
ln -s ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/lib/libpython3.14.dylib \
  ~/.venv/whisper-dictate/lib/libpython3.14.dylib

# Copy the real binary and adhoc-sign it
cp ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14 \
  ~/.venv/whisper-dictate/bin/jarvis-dictate
codesign --sign - ~/.venv/whisper-dictate/bin/jarvis-dictate
```

> **Why not a symlink?** macOS resolves symlinks before setting the process name, so a symlink to python3 always shows as python3. A real binary copy with an adhoc signature is required. The dylib symlink makes the rpath (`@executable_path/../lib`) resolve correctly without needing to relink the binary.

Copy the script from the repo and make it executable:

```bash
mkdir -p ~/scripts
cp "$(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/scripts/whisper-dictate.py" ~/scripts/whisper-dictate.py
chmod +x ~/scripts/whisper-dictate.py
```

---

## Part 6: Grant macOS Permissions

The script needs two permissions. Both are requested automatically on first run, but you can add them manually:

**Microphone access:**
System Settings → Privacy & Security → Microphone → enable `~/.venv/whisper-dictate/bin/jarvis-dictate`

**Accessibility access** (required for typing into other apps):
System Settings → Privacy & Security → Accessibility → enable `~/.venv/whisper-dictate/bin/jarvis-dictate`

> You need to add the venv Python binary specifically, not Terminal, because launchd invokes it directly.

---

## Part 7: Auto-start Dictation Script at Login (launchd)

The plist is in the repo at `launchd/com.whisper.dictate.plist`. Copy it to the LaunchAgents folder and substitute your username:

```bash
sed "s/YOURUSERNAME/$(whoami)/g" \
  $(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/launchd/com.whisper.dictate.plist \
  > ~/Library/LaunchAgents/com.whisper.dictate.plist
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.whisper.dictate.plist
```

---

## Verifying Everything Works

```bash
# Check both services are running (exit code 0 = running)
launchctl list | grep whisper

# Check startup logs (use -f only if you want to stream live output)
tail /tmp/whisper-server.log
tail /tmp/whisper-dictate.log

# Force-restart a service (kills and relaunches immediately)
launchctl kickstart -k gui/$(id -u)/com.whisper.server
launchctl kickstart -k gui/$(id -u)/com.whisper.dictate
```

Expected behavior after full setup:

1. Press **Ctrl+F5** in any app to start recording
2. Speak (English or German, auto-detected)
3. Press **Ctrl+F5** again to stop
4. Wait ~1–2 seconds
5. Text appears at your cursor

---

## Customisation

### Change the hotkey

Edit `HOTKEY` in `whisper-dictate.py`. Examples:

```python
# Option+Space
HOTKEY = {keyboard.Key.alt, keyboard.KeyCode.from_char(' ')}

# F5
HOTKEY = {keyboard.Key.f5}

# Ctrl+Alt+D
HOTKEY = {keyboard.Key.ctrl, keyboard.Key.alt, keyboard.KeyCode.from_char('d')}
```

### Force a specific language (faster, slightly more accurate)

Change `LANGUAGE = "auto"` to `"en"` or `"de"` in the script.

### Use a smaller/faster model

Replace `large-v3-turbo` with `medium` or `small` in the model path and plist.

### Toggle mode instead of push-to-talk

Replace the `on_press` / `on_release` functions with a toggle:

```python
def on_press(key):
    current_keys.add(key)
    if all(k in current_keys for k in HOTKEY):
        if not recording:
            start_recording()
        else:
            threading.Thread(target=stop_and_transcribe, daemon=True).start()

def on_release(key):
    current_keys.discard(key)
```

---

## Troubleshooting

**"Could not reach whisper-server"**
The server isn't running. Check: `launchctl list | grep whisper` and `tail /tmp/whisper-server.err`

**Text doesn't appear in apps**
Accessibility permission is missing. System Settings → Privacy & Security → Accessibility → add Terminal.

**Slow transcription**
Metal GPU should be active by default. Run `whisper-server` from a valid directory (not a deleted folder) and check that it logs `loaded MTL backend` on startup.

**Wrong language detected**
Set `LANGUAGE = "de"` or `"en"` explicitly instead of `"auto"`.

**`pynput` hotkey not triggering**
On macOS 14+, Input Monitoring permission may be required in addition to Accessibility. Check System Settings → Privacy & Security → Input Monitoring.

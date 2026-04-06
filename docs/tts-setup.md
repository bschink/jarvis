# Dual-Engine TTS on macOS (Kokoro-ONNX + Qwen3-TTS + Routing)

Local, offline text-to-speech with two engines: Kokoro for real-time conversational replies, Qwen3-TTS for longer, higher-quality audio. A single router script picks the right engine automatically.

**Stack:** Kokoro-ONNX · mlx-audio · Qwen3-TTS · Python · launchd
**Routing:** < 200 chars or voice loop → Kokoro · ≥ 200 chars or "read this" → Qwen3-TTS
**Hardware:** Apple Silicon Mac (M1–M5)

---

## Prerequisites

- macOS 14 (Sonoma) or newer
- Homebrew installed
- uv (`brew install uv`)
- ~4 GB free disk space (Qwen3-TTS model download, one-time)

---

## Part 1: Install Kokoro-ONNX

Create a dedicated virtual environment and install dependencies:

```bash
uv venv ~/.venv/kokoro
uv pip install --python ~/.venv/kokoro \
  kokoro-onnx fastapi uvicorn soundfile
```

Create a named binary so macOS shows **jarvis-kokoro** in Activity Monitor instead of python3:

```bash
# Symlink the dylib so the copied binary can find it
ln -s ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/lib/libpython3.14.dylib \
  ~/.venv/kokoro/lib/libpython3.14.dylib

# Copy the real binary and adhoc-sign it
cp ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14 \
  ~/.venv/kokoro/bin/jarvis-kokoro
codesign --sign - ~/.venv/kokoro/bin/jarvis-kokoro
```

> **Why not a symlink?** macOS resolves symlinks before setting the process name. See `docs/stt-setup.md` Part 5 for the full explanation.

Download the model files (~310 MB, one-time) from HuggingFace (`hexgrad/Kokoro-82M`):

```bash
mkdir -p ~/.cache/kokoro
# Download the model files
curl -L -o ~/.cache/kokoro/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o ~/.cache/kokoro/voices-v1.0.bin https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
```

Verify the library loads correctly:

```bash
~/.venv/kokoro/bin/python -c "from kokoro_onnx import Kokoro; print('OK')"
```

You should see `OK`.

---

## Part 2: Run the Kokoro HTTP Server

Copy the server script and run it:

```bash
mkdir -p ~/scripts
cp "$(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/scripts/kokoro-server.py" ~/scripts/kokoro-server.py
~/.venv/kokoro/bin/python ~/scripts/kokoro-server.py
```

The server logs `✅ Kokoro server ready on 127.0.0.1:8880` when listening.

Test it's working (save as WAV and play back):

```bash
curl http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "kokoro", "input": "Hello, I am JARVIS.", "voice": "af_heart"}' \
  --output /tmp/test-kokoro.wav && afplay /tmp/test-kokoro.wav
```

You should hear the sentence spoken. Response time should be under 1 second for short text.

> **Available voices:** Dozens of voices are included in the v1.0 release (e.g., `af_bella`, `af_sky`, `am_michael`, `bf_emma`, `bm_george`, `ef_dora`, `ff_siwis`, `jf_alpha`, etc.) spanning multiple languages and American/British English accents.
> See the full list in the [Kokoro VOICES.md](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md).

---

## Part 3: Auto-start Kokoro at Login (launchd)

The plist is in the repo at `launchd/com.kokoro.server.plist`. Copy it to the LaunchAgents folder and substitute your username:

```bash
sed "s/YOURUSERNAME/$(whoami)/g" \
  $(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/launchd/com.kokoro.server.plist \
  > ~/Library/LaunchAgents/com.kokoro.server.plist
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.kokoro.server.plist
```

Verify it's running:

```bash
launchctl list | grep kokoro
```

Check logs if it fails to start:

```bash
tail /tmp/kokoro-server.err
```

---

## Part 4: Install mlx-audio + Qwen3-TTS

Create a dedicated virtual environment and install mlx-audio (pulls in MLX automatically — Apple Silicon native):

```bash
uv venv ~/.venv/mlx-audio
uv pip install --python ~/.venv/mlx-audio mlx-audio
```

Two model variants are available. Download whichever you prefer (or both):

### Option A — CustomVoice (~1.1 GB, pick from preset voices)

```bash
DEST_CV="$HOME/.cache/huggingface/hub/models--mlx-community--Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit/snapshots/main"
mkdir -p "$DEST_CV/speech_tokenizer"
BASE="https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit/resolve/main"
for f in config.json generation_config.json merges.txt model.safetensors model.safetensors.index.json preprocessor_config.json tokenizer_config.json vocab.json; do
  curl -L --progress-bar "$BASE/$f" -o "$DEST_CV/$f"
done
for f in config.json configuration.json model.safetensors preprocessor_config.json; do
  curl -L --progress-bar "$BASE/speech_tokenizer/$f" -o "$DEST_CV/speech_tokenizer/$f"
done
curl -L --progress-bar "https://huggingface.co/Qwen/Qwen2.5-0.5B/resolve/main/tokenizer.json" -o "$DEST_CV/tokenizer.json"
```

Test (pass `--voice` with a preset name):

```bash
~/.venv/mlx-audio/bin/python -m mlx_audio.tts.generate \
  --model "$DEST_CV" \
  --text "This is a longer passage to test the quality TTS engine." \
  --voice "vivian" \
  --output /tmp/test-cv && afplay /tmp/test-cv/audio_000.wav
```

> **Available voices:** `serena`, `vivian`, `uncle_fu`, `ryan`, `aiden`, `ono_anna`, `sohee`, `eric`, `dylan`

### Option B — VoiceDesign (~1.4 GB, describe the voice in natural language)

```bash
DEST_VD="$HOME/.cache/huggingface/hub/models--mlx-community--Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit/snapshots/main"
mkdir -p "$DEST_VD/speech_tokenizer"
BASE="https://huggingface.co/mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit/resolve/main"
for f in config.json generation_config.json merges.txt model.safetensors model.safetensors.index.json preprocessor_config.json tokenizer_config.json vocab.json; do
  curl -L --progress-bar "$BASE/$f" -o "$DEST_VD/$f"
done
for f in config.json configuration.json model.safetensors preprocessor_config.json; do
  curl -L --progress-bar "$BASE/speech_tokenizer/$f" -o "$DEST_VD/speech_tokenizer/$f"
done
curl -L --progress-bar "https://huggingface.co/Qwen/Qwen2.5-0.5B/resolve/main/tokenizer.json" -o "$DEST_VD/tokenizer.json"
```

Test (pass `--instruct` with a free-form voice description):

```bash
~/.venv/mlx-audio/bin/python -m mlx_audio.tts.generate \
  --model "$DEST_VD" \
  --text "JARVIS online. All systems nominal." \
  --instruct "A calm, deep British male voice with a slight authoritative tone" \
  --output /tmp/test-vd && afplay /tmp/test-vd/audio_000.wav
```

> **Output path quirk:** mlx-audio treats `--output` as a directory prefix. The actual file is always `{output}/audio_000.wav`.

Generation takes 10–40 seconds. Subsequent runs are faster (model weights stay in memory/cache).

> **Model naming convention:** Models follow `mlx-community/Qwen3-TTS-12Hz-{size}-{variant}-{quant}`. The `12Hz` refers to the internal codec frame rate, not audio output sample rate (which remains 24 kHz).

---

## Part 5: The TTS Speak Script

Install the speak script's dependencies into a venv. The script routes between Kokoro (via HTTP) and Qwen3-TTS (in-process via mlx-audio), so it only needs the shared audio + HTTP libs plus mlx-audio:

```bash
uv venv ~/.venv/tts-speak
uv pip install --python ~/.venv/tts-speak \
  requests sounddevice soundfile mlx-audio
```

Copy the scripts from the repo and make them executable:

```bash
mkdir -p ~/scripts
cp "$(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/scripts/tts-router.py" ~/scripts/tts-router.py
cp "$(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/scripts/kokoro-server.py" ~/scripts/kokoro-server.py
chmod +x ~/scripts/tts-router.py ~/scripts/kokoro-server.py
```

Test it:

```bash
# Auto-route: short text → Kokoro
~/.venv/tts-speak/bin/python ~/scripts/tts-router.py "Hello, how can I help?"

# Auto-route: long text → Qwen3-TTS
~/.venv/tts-speak/bin/python ~/scripts/tts-router.py \
  "This is a longer passage that exceeds the two hundred character threshold and will be routed to Qwen3-TTS for higher quality synthesis. And this is just some extra text to make sure we go over the threshold. Testing, one, two, three."

# Force a specific engine
~/.venv/tts-speak/bin/python ~/scripts/tts-router.py --fast "Quick reply."
~/.venv/tts-speak/bin/python ~/scripts/tts-router.py --long "Short but high quality."
```

---

## Part 6: Routing Logic

The router (`tts-router.py`) picks an engine based on text length unless overridden:

| Condition | Engine | Latency | Use case |
| --- | --- | --- | --- |
| `< 200 chars` (default) | Kokoro-ONNX | < 1s | Conversational replies, voice loop |
| `≥ 200 chars` (default) | Qwen3-TTS | 10–40s | Reading articles, long responses |
| `--fast` flag | Kokoro-ONNX | < 1s | Force fast regardless of length |
| `--long` flag | Qwen3-TTS | 10–40s | Force quality regardless of length |

The threshold and voice defaults live at the top of `tts-router.py` as `THRESHOLD` and `KOKORO_VOICE` — see Customisation below.

---

## Part 7: Narrate Daemon (System-wide "Read This to Me")

`tts-narrate.py` is a persistent hotkey daemon — the TTS mirror of `whisper-dictate.py`. Select any text in any app, press `Ctrl+Shift+F5`, and JARVIS reads it aloud. Press `Ctrl+Shift+F5` again while audio is playing to stop immediately.

### Install dependencies

```bash
uv venv ~/.venv/tts-narrate
uv pip install --python ~/.venv/tts-narrate pynput
```

### Create the named binary

macOS resolves symlinks before setting the process name. Copy and sign the binary so it appears as `jarvis-narrate` in Activity Monitor:

```bash
ln -s ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/lib/libpython3.14.dylib \
  ~/.venv/tts-narrate/lib/libpython3.14.dylib
cp ~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14 \
  ~/.venv/tts-narrate/bin/jarvis-narrate
codesign --sign - ~/.venv/tts-narrate/bin/jarvis-narrate
```

### Grant Accessibility permission

`pynput` requires Accessibility access to listen for global hotkeys. `osascript` requires it to simulate `Cmd+C`.

Open **System Settings → Privacy & Security → Accessibility** and add `jarvis-narrate` (or the Terminal app if running manually first).

### Copy the script

```bash
cp "$(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/scripts/tts-narrate.py" ~/scripts/tts-narrate.py
chmod +x ~/scripts/tts-narrate.py
```

### Install the launchd service

```bash
sed "s/YOURUSERNAME/$(whoami)/g" \
  $(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/launchd/com.tts.narrate.plist \
  > ~/Library/LaunchAgents/com.tts.narrate.plist
launchctl load ~/Library/LaunchAgents/com.tts.narrate.plist
```

### Verify

```bash
# Service is running (exit code 0)
launchctl list | grep tts.narrate

# Process shows as jarvis-narrate
ps aux | grep jarvis-narrate

# End-to-end: select some text in any app, press Ctrl+Shift+F5
# Audio should play

# Check logs if silent
tail /tmp/tts-narrate.err
tail /tmp/tts-narrate.log
```

### Force-restart

```bash
launchctl kickstart -k gui/$(id -u)/com.tts.narrate
```

---

## Verifying Everything Works

```bash
# Check Kokoro server is running (exit code 0 = running)
launchctl list | grep kokoro

# Check Kokoro startup logs
tail /tmp/kokoro-server.log
tail /tmp/kokoro-server.err

# End-to-end Kokoro test
curl http://127.0.0.1:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"model": "kokoro", "input": "JARVIS online.", "voice": "af_sky"}' \
  --output /tmp/test-kokoro.wav && afplay /tmp/test-kokoro.wav

# End-to-end Qwen3-TTS test
DEST="$HOME/.cache/huggingface/hub/models--mlx-community--Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit/snapshots/main"
~/.venv/mlx-audio/bin/python -m mlx_audio.tts.generate \
  --model "$DEST" \
  --text "Qwen3-TTS is working correctly." \
  --voice "ryan" \
  --output /tmp/test-qwen3 && afplay /tmp/test-qwen3/audio_000.wav

# Router script (auto-route)
~/.venv/tts-speak/bin/python ~/scripts/tts-router.py "Both engines are ready."

# Force-restart Kokoro server
launchctl kickstart -k gui/$(id -u)/com.kokoro.server
```

Expected behaviour:

1. `launchctl list | grep kokoro` returns a line with exit code `0` and the label `com.kokoro.server`
2. Kokoro curl test plays audio in under a second
3. Qwen3-TTS test plays after 10–40s on first run, faster on subsequent runs
4. Router script auto-selects the correct engine based on text length

---

## Customisation

### Change the Kokoro voice

Edit `KOKORO_VOICE` in `tts-router.py`:

```python
KOKORO_VOICE = "bm_george"   # British male
KOKORO_VOICE = "af_bella"    # American female
KOKORO_VOICE = "am_michael"  # American male
```

### Change the routing threshold

Edit `THRESHOLD` in `tts-router.py`:

```python
THRESHOLD = 150   # route to Qwen3-TTS sooner
THRESHOLD = 400   # keep more text on Kokoro
```

### Force a specific language (Kokoro)

Kokoro serves English voices only. For multilingual output, Qwen3-TTS supports multiple languages natively — use `--long` to force it regardless of text length.

### Switch between CustomVoice and VoiceDesign

Edit `QWEN3_LOCAL_PATH`, `QWEN3_MODE`, `QWEN3_VOICE`, and `QWEN3_INSTRUCT` at the top of `tts-router.py`:

**CustomVoice** — pick from a preset list of voices:

```python
QWEN3_LOCAL_PATH = os.path.expanduser(
    "~/.cache/huggingface/hub/"
    "models--mlx-community--Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit/snapshots/main"
)
QWEN3_MODE    = "customvoice"
QWEN3_VOICE   = "vivian"   # serena, vivian, uncle_fu, ryan, aiden, ono_anna, sohee, eric, dylan
```

**VoiceDesign** — describe the voice in natural language:

```python
QWEN3_LOCAL_PATH = os.path.expanduser(
    "~/.cache/huggingface/hub/"
    "models--mlx-community--Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit/snapshots/main"
)
QWEN3_MODE     = "voicedesign"
QWEN3_INSTRUCT = "A calm, deep British male voice with a slight authoritative tone"
```

---

## Troubleshooting

**"Kokoro server not reachable on port 8880"**
The server isn't running. Check: `launchctl list | grep kokoro` and `tail /tmp/kokoro-server.err`.
If the plist isn't loaded: re-run the `sed + launchctl load` commands from Part 3.

**"Model file not found" on server start**
The ONNX model files haven't been downloaded yet. Follow the download step in Part 1 to place `kokoro-v1.0.onnx` and `voices-v1.0.bin` in `~/.cache/kokoro/`.

**Qwen3-TTS: "No module named mlx_audio"**
mlx-audio isn't installed in the right venv. The router script must be run with `~/.venv/tts-speak/bin/python`, not the system Python.

**Qwen3-TTS generate command hangs with no output**
The auto-download from HuggingFace hangs silently on some networks. Download model files manually with curl as shown in Part 4. Also ensure you pass the local filesystem path (not the repo name) via `--model "$DEST"`.

**Qwen3-TTS: "CustomVoice model requires 'voice'"**
The CustomVoice variant requires a `--voice` flag. Pass one of: `serena`, `vivian`, `uncle_fu`, `ryan`, `aiden`, `ono_anna`, `sohee`, `eric`, `dylan`.

**Qwen3-TTS: "VoiceDesign model requires 'instruct'"**
The VoiceDesign variant uses `--instruct` (not `--voice`) with a free-form description e.g. `"A calm, deep British male voice"`.

**Qwen3-TTS: "Tokenizer not loaded"**
The `tokenizer.json` file is missing from the mlx-community repo. Download it from Qwen2.5-0.5B as shown in the Part 4 download script — the tokenizer is identical.

**Qwen3-TTS output file not found after generate**
mlx-audio treats `--output` as a directory prefix. The actual file is `{output}/audio_000.wav`, not `{output}` directly.

**No audio output (sounddevice)**
macOS audio output does not require explicit permission like Microphone access. If silent: check System Settings → Sound → Output device is set correctly, and that the Python process isn't sandboxed.

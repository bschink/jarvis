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

Test the CLI (first run downloads the model — ~1.1 GB at 8-bit, one-time):

```bash
~/.venv/mlx-audio/bin/python -m mlx_audio.tts.generate \
  --model mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit \
  --text "This is a longer passage to test the quality TTS engine." \
  --output /tmp/test-qwen3.wav && afplay /tmp/test-qwen3.wav
```

Generation takes 10–40 seconds depending on text length. Subsequent runs are faster (model is cached in `~/.cache/huggingface/`).

> **Model naming convention:** Models follow `mlx-community/Qwen3-TTS-12Hz-{size}-{variant}-{quant}`. The `12Hz` refers to the internal codec frame rate, not audio output sample rate (which remains 24 kHz). Available variants: `Base` (core voice), `CustomVoice` (style control), `VoiceDesign` (voice from text description).

> **Note on Qwen3-TTS Python API:** The `tts-speak.py` script uses `from mlx_audio.tts.utils import load_model`. If this import fails after install, verify with `~/.venv/mlx-audio/bin/python -c "from mlx_audio.tts import utils; help(utils)"` and update `tts-speak.py` accordingly.

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
cp "$(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/scripts/tts-speak.py" ~/scripts/tts-speak.py
cp "$(git -C ~/Documents/VSCode/jarvis rev-parse --show-toplevel)/scripts/kokoro-server.py" ~/scripts/kokoro-server.py
chmod +x ~/scripts/tts-speak.py ~/scripts/kokoro-server.py
```

Test it:

```bash
# Auto-route: short text → Kokoro
~/.venv/tts-speak/bin/python ~/scripts/tts-speak.py "Hello, how can I help?"

# Auto-route: long text → Qwen3-TTS
~/.venv/tts-speak/bin/python ~/scripts/tts-speak.py \
  "This is a longer passage that exceeds the two hundred character threshold and will be routed to Qwen3-TTS for higher quality synthesis."

# Force a specific engine
~/.venv/tts-speak/bin/python ~/scripts/tts-speak.py --fast "Quick reply."
~/.venv/tts-speak/bin/python ~/scripts/tts-speak.py --long "Short but high quality."
```

---

## Part 6: Routing Logic

The router (`tts-speak.py`) picks an engine based on text length unless overridden:

| Condition | Engine | Latency | Use case |
|---|---|---|---|
| `< 200 chars` (default) | Kokoro-ONNX | < 1s | Conversational replies, voice loop |
| `≥ 200 chars` (default) | Qwen3-TTS | 10–40s | Reading articles, long responses |
| `--fast` flag | Kokoro-ONNX | < 1s | Force fast regardless of length |
| `--long` flag | Qwen3-TTS | 10–40s | Force quality regardless of length |

The threshold and voice defaults live at the top of `tts-speak.py` as `THRESHOLD` and `KOKORO_VOICE` — see Customisation below.

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
~/.venv/mlx-audio/bin/python -m mlx_audio.tts.generate \
  --model mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit \
  --text "Qwen3-TTS is working correctly." \
  --output /tmp/test-qwen3.wav && afplay /tmp/test-qwen3.wav

# Router script (auto-route)
~/.venv/tts-speak/bin/python ~/scripts/tts-speak.py "Both engines are ready."

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

Edit `KOKORO_VOICE` in `tts-speak.py`:

```python
KOKORO_VOICE = "bm_george"   # British male
KOKORO_VOICE = "af_bella"    # American female
KOKORO_VOICE = "am_michael"  # American male
```

### Change the routing threshold

Edit `THRESHOLD` in `tts-speak.py`:

```python
THRESHOLD = 150   # route to Qwen3-TTS sooner
THRESHOLD = 400   # keep more text on Kokoro
```

### Force a specific language (Kokoro)

Kokoro serves English voices only. For multilingual output, Qwen3-TTS supports multiple languages natively — use `--long` to force it regardless of text length.

### Use a different Qwen3-TTS model size or variant

Change `QWEN3_MODEL` in `tts-speak.py`:

```python
# Smaller / faster (~400 MB)
QWEN3_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit"
QWEN3_MODEL = "mlx-community/Qwen3-TTS-12Hz-0.6B-Base-bf16"

# Default — quality + style control (~1.1 GB)
QWEN3_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-CustomVoice-8bit"

# Voice design: describe a voice in natural language (~1.4 GB)
QWEN3_MODEL = "mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-6bit"
```

---

## Troubleshooting

**"Kokoro server not reachable on port 8880"**  
The server isn't running. Check: `launchctl list | grep kokoro` and `tail /tmp/kokoro-server.err`.  
If the plist isn't loaded: re-run the `sed + launchctl load` commands from Part 3.

**"Model file not found" on server start**  
The ONNX model files haven't been downloaded yet. Follow the download step in Part 1 to place `kokoro-v1.0.onnx` and `voices-v1.0.bin` in `~/.cache/kokoro/`.

**Qwen3-TTS: "No module named mlx_audio"**  
mlx-audio isn't installed in the right venv. The speak script must be run with `~/.venv/tts-speak/bin/python`, not the system Python.

**Qwen3-TTS is very slow on first run**  
Normal — the model (~1.1 GB) is being downloaded to `~/.cache/huggingface/`. Subsequent runs use the cached model and are significantly faster.

**`mlx_audio.tts.utils.load_model` import fails**  
The mlx-audio API is evolving. Check the installed version: `~/.venv/tts-speak/bin/python -c "import mlx_audio; print(mlx_audio.__version__)"` and compare to the mlx-audio changelog for the current import path.

**No audio output (sounddevice)**  
macOS audio output does not require explicit permission like Microphone access. If silent: check System Settings → Sound → Output device is set correctly, and that the Python process isn't sandboxed.

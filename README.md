# WhisperDictate

Local voice input for macOS — hold a hotkey, speak, release. Text appears at your cursor.

Two ASR backends: [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (Apple Silicon optimized) and [FunASR Paraformer](https://github.com/modelscope/FunASR) (fast Chinese-English). Switch between them from the right-click menu, no restart needed.

[中文教程 / Chinese Guide](README_CN.md)

## Features

- **100% Local & Private** — no cloud, no API keys, audio never leaves your Mac
- **Free** — no subscription, no limits
- **Two ASR Backends** — Whisper (best English) or Paraformer (fastest Chinese-English mix)
- **Animated Waveform** — live audio visualization during recording, shimmer during transcription
- **Hold-to-Talk** — Ctrl+Option to record, release to transcribe and auto-paste
- **Chinese-English Code-Switching** — speak mixed languages in one sentence
- **Smart Post-Processing** — removes hallucinations, repetitions, and filler words
- **Keyword Hints** — custom terms improve recognition of names and domain jargon
- **Window Detection** — auto-pastes if same window, shows Copy button if you switched
- **Right-Click Menu** — switch ASR backend, microphone, edit keywords, view logs
- **Transcription History** — JSONL with 7-day retention
- **Memory Management** — auto-cleanup and restart when memory gets high

## Requirements

- **macOS 13+** (Ventura or later)
- **Apple Silicon** (M1 / M2 / M3 / M4)
- **Python 3.10+**
- **~1.5 GB** disk for Whisper model (downloaded on first run)
- **~300 MB** additional for Paraformer model (optional, downloaded on first use)

## Installation

### 1. Clone

```bash
git clone https://github.com/jerryshimax/whisper-dictate.git
cd whisper-dictate
```

### 2. Create environment & install

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 3. Build the macOS app

```bash
.venv/bin/python setup_whisper_app.py
```

Creates `~/Applications/WhisperDictate.app`.

### 4. macOS permissions

1. **System Settings → Keyboard → "Press 🌐 key to"** → **Do Nothing**
2. **System Settings → Privacy & Security → Accessibility** → Add WhisperDictate.app
3. **System Settings → Privacy & Security → Microphone** → Allow WhisperDictate.app
4. (Optional) **System Settings → General → Login Items** → Add for auto-start

### 5. Launch

```bash
open ~/Applications/WhisperDictate.app
```

First launch downloads the model (~1.5 GB). A small floating bar appears at the bottom of your screen when ready.

## Usage

### Voice Input

1. **Hold Ctrl+Option** — bar expands with animated waveform
2. **Speak** — any language, or mix Chinese and English freely
3. **Release** — waveform shimmers while transcribing (~1-3s)
4. Text auto-pastes at your cursor

If you switch windows while recording, a Copy button appears instead of auto-pasting.

### Switching ASR Backend

Right-click the floating bar → **ASR Backend**:

| Backend | Best For | Speed | Model Size |
|---------|----------|-------|------------|
| **Whisper (MLX)** | English, rare words, accents | ~1-3s | 1.5 GB |
| **Paraformer (FunASR)** | Chinese, Chinese-English mix | ~0.5-1s | 300 MB |

The new backend loads in the background — the bar shows a loading state, then you're good.

### Keywords

Edit `~/.config/whisper/keywords.txt` to improve recognition of specific terms:

```
NVIDIA, Tesla, S&P 500, Bitcoin, your terms here
```

Changes apply on the next transcription, no restart needed.

### Right-Click Menu

- **Edit Keywords** — open keyword file
- **Open History** — view past transcriptions
- **Open Log** — debug log
- **Input Device** — switch microphone
- **ASR Backend** — switch between Whisper and Paraformer
- **Quit**

### CLI Control

```bash
./whisper_ctl.sh status    # Process info + memory
./whisper_ctl.sh log       # Tail the log
./whisper_ctl.sh mic       # List / switch microphones
./whisper_ctl.sh restart   # Restart the app
./whisper_ctl.sh quit      # Stop the app
```

## Configuration

| File | Purpose |
|------|---------|
| `~/.config/whisper/keywords.txt` | Keyword hints (comma-separated) |
| `~/.config/whisper/config.json` | Settings (input device, etc.) |
| `~/.config/whisper/history.jsonl` | Transcription history (7-day retention) |
| `~/.config/whisper/app.log` | Application log (5 MB rotation) |

All config files are created with owner-only permissions (0600).

## Acknowledgments

UI inspired by **[Typeless](https://typeless.so/)**.

Built on:
- [OpenAI Whisper](https://github.com/openai/whisper) — speech recognition model
- [MLX](https://github.com/ml-explore/mlx) — Apple Silicon ML framework
- [FunASR](https://github.com/modelscope/FunASR) — Alibaba DAMO speech recognition
- [PyObjC](https://github.com/ronaldoussoren/pyobjc) — Python ↔ Cocoa bridge
- [sounddevice](https://github.com/spatialaudio/python-sounddevice) / [PortAudio](http://www.portaudio.com/)
- [NumPy](https://numpy.org/)

## License

MIT

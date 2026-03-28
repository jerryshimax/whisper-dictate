# WhisperDictate

Local voice input for macOS — hold or tap a hotkey, speak, text appears at your cursor. 100% local, no cloud, no subscription.

Built on [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (Apple Silicon optimized) with LLM-powered punctuation polishing.

[中文教程 / Chinese Guide](README_CN.md)

## Features

- **100% Local & Private** — no cloud, no API keys, audio never leaves your Mac
- **Free & Open Source** — no subscription, no limits
- **Two Input Modes**:
  - **Hold-to-Talk** — hold Ctrl+Option, speak, release to transcribe
  - **Tap-to-Toggle** — quick tap to start, tap again to stop (hands-free)
- **LLM Punctuation Polish** — local Qwen2.5-0.5B fixes capitalization, periods, commas (~0.15s)
- **Brain Vault Keywords** — auto-scans your Obsidian vault for people names, companies, and domain terms to improve recognition
- **Animated Waveform** — live audio visualization during recording, shimmer during transcription
- **Sound Alerts** — Tink on start, Ping on done — no need to watch the screen
- **Chinese-English Code-Switching** — speak mixed languages in one sentence
- **Smart Post-Processing** — removes hallucinations, repetitions, filler words, and merges fragmented commas
- **Custom Keywords** — manual keyword hints for domain-specific terms
- **Window Detection** — auto-pastes if same window, shows Copy button if you switched
- **Right-Click Menu** — switch microphone, edit keywords, view logs
- **Transcription History** — JSONL with 7-day retention
- **Memory Management** — auto-cleanup and restart when memory gets high

## Requirements

- **macOS 13+** (Ventura or later)
- **Apple Silicon** (M1 / M2 / M3 / M4)
- **Python 3.10+**
- **~1.5 GB** disk for Whisper model (downloaded on first run)
- **~400 MB** for LLM punctuation model (downloaded on first run)

## Installation

### Option A: Run from Source (recommended for development)

```bash
# 1. Clone
git clone https://github.com/jerryshimax/whisper-dictate.git
cd whisper-dictate

# 2. Create virtual environment & install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Grant macOS permissions (see below)

# 4. Run
python -m whisper_dictate
```

### Option B: Build macOS .app

```bash
# After cloning and installing dependencies:
bash build_dmg.sh
```

This creates `~/Applications/WhisperDictate.app` — double-click to launch. No Python needed after build.

### macOS Permissions

These are required for the app to work:

1. **System Settings > Privacy & Security > Accessibility** — add WhisperDictate (or Terminal if running from source)
2. **System Settings > Privacy & Security > Microphone** — allow WhisperDictate (or Terminal)
3. (Optional) **System Settings > General > Login Items** — add for auto-start

### First Launch

First launch downloads the Whisper model (~1.5 GB) and LLM model (~400 MB). A small floating bar appears at the bottom of your screen. When it shows `○`, you're ready to go.

## Usage

### Hold-to-Talk (default)

1. **Hold Ctrl+Option** — bar expands with animated waveform, Tink sound plays
2. **Speak** — any language, or mix Chinese and English
3. **Release** — waveform shimmers while transcribing, Ping when done
4. Text auto-pastes at your cursor

### Tap-to-Toggle (hands-free)

1. **Quick tap Ctrl+Option** (< 0.6s) — recording starts, you hear Tink twice
2. **Speak** — as long as you want, hands-free
3. **Tap Ctrl+Option again** — stops recording, transcribes, Ping when done

### Keywords

Edit `~/.config/whisper/keywords.txt` to add domain-specific terms:

```
# Natural sentences work best — Whisper follows style, not instructions
Synergis Capital tracks ARR and valuation multiples for Series A deals.
NVIDIA, Tesla, S&P 500, Bitcoin, your custom terms here.
```

If you have an Obsidian vault at `~/Work/[00] Brain/`, WhisperDictate auto-scans it for people names, company names, and Chinese terms on startup.

### Right-Click Menu

Right-click the floating bar:
- **Edit Keywords** — open keyword file
- **Open History** — view past transcriptions
- **Open Log** — debug log
- **Input Device** — switch microphone
- **Quit**

### CLI

```bash
# Run from source
pkill -f whisper_dictate
cd ~/Ship/dictation && source .venv/bin/activate && python -m whisper_dictate &

# Or run the app
open ~/Applications/WhisperDictate.app
```

## Configuration

| File | Purpose |
|------|---------|
| `~/.config/whisper/keywords.txt` | Keyword hints for Whisper |
| `~/.config/whisper/config.json` | Settings (input device, model) |
| `~/.config/whisper/history.jsonl` | Transcription history (7-day retention) |
| `~/.config/whisper/app.log` | Application log (5 MB rotation) |

All config files are created with owner-only permissions (0600).

## Architecture

```
whisper_dictate/
├── app.py              # AppDelegate, main event loop
├── asr.py              # Whisper MLX backend
├── llm_polish.py       # Qwen2.5-0.5B punctuation fixer
├── brain_keywords.py   # Obsidian vault keyword scanner
├── postprocessor.py    # Regex text cleaning pipeline
├── config.py           # Constants and config management
├── audio.py            # Audio device and silence trimming
├── clipboard.py        # Paste and clipboard restore
├── history.py          # JSONL history and keyword mining
├── event_tap.py        # CGEventTap hotkey detection
├── macos.py            # Window detection, memory management
├── logging_setup.py    # Rotating file logger
└── ui/
    ├── indicator.py    # Floating NSPanel bar
    ├── waveform.py     # CALayer animated waveform
    └── context_menu.py # Right-click menu
```

## Built With

- [OpenAI Whisper](https://github.com/openai/whisper) — speech recognition model
- [MLX](https://github.com/ml-explore/mlx) — Apple Silicon ML framework
- [MLX-LM](https://github.com/ml-explore/mlx-examples/tree/main/llms) — local LLM inference
- [PyObjC](https://github.com/ronaldoussoren/pyobjc) — Python-Cocoa bridge
- [sounddevice](https://github.com/spatialaudio/python-sounddevice) / [PortAudio](http://www.portaudio.com/)

## License

MIT

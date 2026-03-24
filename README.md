# WhisperDictate

Local voice input for macOS — hold FN, speak, release. Powered by [MLX Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) on Apple Silicon.

[中文介绍 / Chinese README](README_CN.md)

<p align="center">
  <code>◦ ──────────────</code> → <code>♪ ───│──────</code> → <code>✎ ┄┄┄┄┄┄</code> → <code>✓ ──────────────</code>
</p>

## Features

- **100% Local & Private** — runs entirely on-device, no cloud API, no data leaves your Mac
- **Free** — no subscription, no usage limits
- **FN Hold-to-Talk** — hold the FN key to record, release to transcribe and auto-paste
- **Minimal UI** — 170×20px floating bar at the bottom of the screen, zero screen takeover
- **Multilingual** — Chinese, English, and mixed-language support via Whisper large-v3-turbo
- **Smart Post-Processing** — 8-step regex pipeline removes Whisper hallucinations, repetitions, and filler words
- **Keyword Hints** — custom keyword list improves recognition of names, tickers, and domain terms
- **Auto-Paste with Window Detection** — pastes directly if you stay in the same window; shows "Copy" button if you switched
- **Right-Click Menu** — right-click the floating bar to edit keywords, open logs, switch microphone, or quit
- **Transcription History** — JSONL history with 7-day auto-cleanup
- **Memory Management** — periodic cache cleanup + auto-restart when memory exceeds threshold

## Why WhisperDictate?

There are great voice input tools out there — macOS Dictation, Typeless, WeChat voice input all work well. WhisperDictate fills a specific niche:

- **Free & local** — no subscription, no cloud, your audio never leaves your Mac
- **Just input, not an assistant** — some tools try to auto-complete or answer your questions; WhisperDictate only transcribes what you say, nothing more
- **Open source & hackable** — ~500 lines of Python, easy to customize
- **Chinese-English mixed input** — keyword hints correct domain-specific terms that other tools often get wrong

| | WhisperDictate | macOS Dictation | Typeless | WeChat Voice |
|---|---|---|---|---|
| Privacy | Local only | Cloud (Apple) | Cloud or local | Cloud (Tencent) |
| Cost | Free | Free | $8-15/mo | Free |
| Speed | ~2-3s | Fast | Fast | Fast |
| Post-processing | Regex dedup | None | AI-powered (best) | Good |
| AI features | None (by design) | None | Auto-complete, Q&A | None |
| History | 7-day JSONL | None | Yes | None |
| Open source | Yes | No | No | No |

## Requirements

- **macOS 13+** (Ventura or later)
- **Apple Silicon** (M1 / M2 / M3 / M4)
- **Python 3.10+** (conda recommended)
- **~1.5 GB** disk space for the Whisper model (downloaded on first run)

## Installation

### 1. Set up Python environment

```bash
conda create -n voice python=3.10 -y
conda activate voice
pip install -r requirements.txt
```

Or without conda:
```bash
pip3 install -r requirements.txt
```

### 2. Build the macOS app

```bash
python setup_whisper_app.py
```

This creates `~/Applications/WhisperDictate.app`.

If your Python is not in a conda `voice` env, set `WHISPER_PYTHON`:
```bash
WHISPER_PYTHON=/path/to/python3 python setup_whisper_app.py
```

### 3. Configure macOS permissions

1. **System Settings → Keyboard → "Press 🌐 key to"** → **Do Nothing**
2. **System Settings → Privacy & Security → Accessibility** → Add WhisperDictate.app
3. **System Settings → Privacy & Security → Microphone** → Allow WhisperDictate.app
4. (Optional) **System Settings → General → Login Items** → Add WhisperDictate.app for auto-start

### 4. Launch

```bash
open ~/Applications/WhisperDictate.app
```

The first launch downloads the Whisper model (~1.5 GB). The floating bar shows `· ┄┄┄...` during loading, then `◦ ──────────────` when ready.

## Usage

### Voice Input

1. **Hold FN** — the bar shows `♪` with a live audio meter
2. **Speak** — in any language
3. **Release FN** — the bar shows `✎` while transcribing (typically 2-3 seconds)
4. Text is auto-pasted into the current cursor position

If you switch windows during recording, the bar shows `✓ Ready to Copy` with a Copy button instead of auto-pasting.

### Right-Click Menu

Right-click the floating bar to access:
- **Edit Keywords** — open the keyword hint file
- **Open History** — view transcription history
- **Open Log** — view the app log
- **Input Device** — switch microphone
- **Quit** — exit the app

### Keywords

Edit `~/.config/whisper/keywords.txt` to add domain-specific terms (comma-separated). Whisper uses these as hints to improve recognition:

```
NVIDIA, Tesla, S&P 500, Bitcoin, your custom terms here
```

Changes are picked up automatically on the next transcription.

### CLI Control (optional)

```bash
./whisper_ctl.sh status    # Show process info + memory usage
./whisper_ctl.sh log       # Tail the app log
./whisper_ctl.sh mic       # List / switch input devices
./whisper_ctl.sh restart   # Restart the app
./whisper_ctl.sh quit      # Stop the app
```

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│              WhisperDictate.app (~/Applications/)             │
├──────────────────────────────────────────────────────────────┤
│  CGEventTap        sounddevice        mlx_whisper            │
│  (FN key monitor)  (microphone)       (MLX transcription)    │
│         │                │                   │               │
│         ▼                ▼                   ▼               │
│  FN press → record → FN release → transcribe → post-process │
│                                                    │         │
│  postprocess() — 8-step regex engine:              │         │
│    hallucination removal → block dedup →            │         │
│    clause dedup → tail dedup → filler removal →     │         │
│    tail noise filter → whitespace cleanup           │         │
│                                                    │         │
│  Auto-paste (same window) or Copy prompt            │         │
│                                                              │
│  UI: NSPanel floating bar (170×20) + right-click menu        │
│  Memory: 2h gc + auto-restart at threshold                   │
└──────────────────────────────────────────────────────────────┘
```

## Configuration Files

| File | Purpose |
|------|---------|
| `~/.config/whisper/keywords.txt` | Keyword hints for Whisper (comma-separated) |
| `~/.config/whisper/config.json` | Settings (e.g., `{"input_device": "MacBook Air Microphone"}`) |
| `~/.config/whisper/history.jsonl` | Transcription history (auto-generated, 7-day retention) |
| `~/.config/whisper/app.log` | Application log |

## Acknowledgments

UI inspired by **[Typeless](https://typeless.so/)** — the floating indicator bar design was learned from their excellent product.

Built on top of these open-source projects:

- **[OpenAI Whisper](https://github.com/openai/whisper)** — the original speech recognition model
- **[MLX](https://github.com/ml-explore/mlx)** by Apple — machine learning framework for Apple Silicon
- **[mlx-whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper)** — MLX-optimized Whisper inference
- **[PyObjC](https://github.com/ronaldoussoren/pyobjc)** — Python ↔ Objective-C bridge (Cocoa, Quartz)
- **[sounddevice](https://github.com/spatialaudio/python-sounddevice)** / [PortAudio](http://www.portaudio.com/) — cross-platform audio I/O
- **[SoundFile](https://github.com/bastibe/python-soundfile)** / [libsndfile](https://github.com/libsndfile/libsndfile) — audio file reading/writing
- **[NumPy](https://numpy.org/)** — array processing

## License

MIT

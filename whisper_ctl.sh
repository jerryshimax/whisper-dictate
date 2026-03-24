#!/bin/bash
# whisper_ctl.sh — WhisperDictate CLI control

# Auto-detect Python: $WHISPER_PYTHON > conda voice > system
_find_python() {
  if [ -n "$WHISPER_PYTHON" ] && [ -x "$WHISPER_PYTHON" ]; then
    echo "$WHISPER_PYTHON"; return
  fi
  for p in ~/miniconda3/envs/voice/bin/python3 ~/anaconda3/envs/voice/bin/python3; do
    [ -x "$p" ] && echo "$p" && return
  done
  echo "python3"
}
PYTHON=$(_find_python)

case "${1:-help}" in
  log)
    tail -f ~/.config/whisper/app.log
    ;;
  keywords)
    open ~/.config/whisper/keywords.txt
    ;;
  history)
    open -a TextEdit ~/.config/whisper/history.jsonl
    ;;
  mic)
    if [ -n "$2" ]; then
      printf '{"input_device": "%s"}\n' "$2" > ~/.config/whisper/config.json
      echo "Input device set to: $2 (takes effect next recording)"
    else
      echo "Current:"
      cat ~/.config/whisper/config.json 2>/dev/null || echo '  (default system mic)'
      echo ""
      echo "Available input devices:"
      "$PYTHON" -c "
import sounddevice as sd
for d in sd.query_devices():
    if d['max_input_channels'] > 0:
        marker = ' <-' if d['index'] == sd.default.device[0] else ''
        print(f\"  {d['name']}{marker}\")
" 2>/dev/null
      echo ""
      echo "Set with: whisper_ctl mic \"device name\""
    fi
    ;;
  status)
    pid=$(pgrep -f "whisper_dictate.py" 2>/dev/null)
    if [ -n "$pid" ]; then
      rss=$(ps -o rss= -p "$pid" | awk '{printf "%.0f", $1/1024}')
      etime=$(ps -o etime= -p "$pid" | xargs)
      echo "Running  PID=$pid  RSS=${rss}MB  uptime=$etime"
    else
      echo "Not running."
    fi
    ;;
  quit)
    pkill -f "whisper_dictate.py" && echo "Stopped." || echo "Not running."
    ;;
  restart)
    pkill -f "whisper_dictate.py" 2>/dev/null
    sleep 1
    open ~/Applications/WhisperDictate.app
    echo "Restarted."
    ;;
  *)
    echo "whisper_ctl — WhisperDictate CLI control"
    echo ""
    echo "  log        Tail app log"
    echo "  keywords   Open keywords file"
    echo "  history    Open transcription history"
    echo "  mic        Show/set input device"
    echo "  status     Show process info + memory"
    echo "  quit       Stop WhisperDictate"
    echo "  restart    Stop + relaunch"
    ;;
esac

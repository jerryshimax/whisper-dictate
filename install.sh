#!/usr/bin/env bash
set -euo pipefail

# ── colors ─────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

info()  { printf "${CYAN}[info]${NC}  %s\n" "$*"; }
ok()    { printf "${GREEN}[ok]${NC}    %s\n" "$*"; }
warn()  { printf "${YELLOW}[warn]${NC}  %s\n" "$*"; }
fail()  { printf "${RED}[fail]${NC}  %s\n" "$*"; exit 1; }

# ── pre-checks ─────────────────────────────────────────────
info "Checking environment..."

[[ "$(uname)" == "Darwin" ]] || fail "This script requires macOS."

ARCH="$(uname -m)"
if [[ "$ARCH" == "arm64" ]]; then
    ok "Apple Silicon detected ($ARCH)"
else
    warn "Not Apple Silicon ($ARCH) — MLX Whisper may not work. Proceeding anyway."
fi

# ── find Python ────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"

find_python() {
    # 1. WHISPER_PYTHON env var
    if [[ -n "${WHISPER_PYTHON:-}" ]] && "$WHISPER_PYTHON" --version &>/dev/null; then
        echo "$WHISPER_PYTHON"
        return
    fi
    # 2. Existing .venv
    if [[ -x "$VENV_DIR/bin/python3" ]]; then
        echo "$VENV_DIR/bin/python3"
        return
    fi
    # 3. python3 on PATH
    if command -v python3 &>/dev/null; then
        echo "python3"
        return
    fi
    fail "No Python 3 found. Set WHISPER_PYTHON or install python3."
}

PYTHON="$(find_python)"
PY_VERSION="$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="${PY_VERSION%%.*}"
PY_MINOR="${PY_VERSION##*.}"

if (( PY_MAJOR < 3 || (PY_MAJOR == 3 && PY_MINOR < 10) )); then
    fail "Python 3.10+ required, found $PY_VERSION"
fi
ok "Python $PY_VERSION ($PYTHON)"

# ── create venv if needed ──────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    info "Creating virtual environment at $VENV_DIR ..."
    "$PYTHON" -m venv "$VENV_DIR"
    ok "Virtual environment created"
fi

# Activate venv
source "$VENV_DIR/bin/activate"
ok "Virtual environment activated"

# ── install dependencies ───────────────────────────────────
info "Installing dependencies from requirements.txt ..."
pip install --upgrade pip -q
pip install -r "$SCRIPT_DIR/requirements.txt" -q
ok "Dependencies installed"

# ── verify core imports ────────────────────────────────────
info "Verifying core imports..."
python3 -c "
import sounddevice, soundfile, numpy
import objc
from AppKit import NSApplication
print('Core imports OK')
" || fail "Core import verification failed. Check requirements."
ok "All core imports work"

# ── verify package compiles ────────────────────────────────
info "Checking package syntax..."
python3 -c "
import py_compile, pathlib, sys
pkg = pathlib.Path('$SCRIPT_DIR/whisper_dictate')
errors = []
for f in sorted(pkg.rglob('*.py')):
    try:
        py_compile.compile(str(f), doraise=True)
    except py_compile.PyCompileError as e:
        errors.append(str(e))
if errors:
    for e in errors:
        print(e, file=sys.stderr)
    sys.exit(1)
print(f'All {len(list(pkg.rglob(\"*.py\")))} modules compile OK')
"
ok "Package syntax valid"

# ── build .app bundle ──────────────────────────────────────
info "Building WhisperDictate.app ..."
python3 "$SCRIPT_DIR/setup_whisper_app.py"
ok "App bundle ready at ~/Applications/WhisperDictate.app"

# ── permission instructions ────────────────────────────────
echo ""
printf "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
printf "${YELLOW}  Required macOS permissions:${NC}\n"
printf "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
echo "  1. System Settings > Keyboard > 'Press 🌐 key to' → 'Do Nothing'"
echo "  2. System Settings > Privacy > Accessibility → allow WhisperDictate.app"
echo "  3. System Settings > Privacy > Microphone → allow WhisperDictate.app"
echo ""

# ── offer to launch ────────────────────────────────────────
read -rp "Launch WhisperDictate now? [Y/n] " answer
answer="${answer:-Y}"
if [[ "$answer" =~ ^[Yy]$ ]]; then
    open ~/Applications/WhisperDictate.app
    ok "Launched!"
else
    info "Run later with: open ~/Applications/WhisperDictate.app"
fi

#!/usr/bin/env bash
set -euo pipefail

# ── build_dmg.sh — Build self-contained WhisperDictate.dmg ──
#
# Bundles Python venv + source code into .app, wraps in .dmg.
# Output: dist/WhisperDictate-{version}-arm64.dmg

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION="3.0.0"
APP_NAME="WhisperDictate"
DIST_DIR="$SCRIPT_DIR/dist"
APP_DIR="$DIST_DIR/$APP_NAME.app"
CONTENTS="$APP_DIR/Contents"
MACOS_DIR="$CONTENTS/MacOS"
RESOURCES="$CONTENTS/Resources"
VENV_SRC="$SCRIPT_DIR/.venv"
DMG_NAME="$APP_NAME-$VERSION-arm64"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[1;34m'
NC='\033[0m'

log()  { printf "${BLUE}==>${NC} %s\n" "$*"; }
ok()   { printf "${GREEN}✓${NC}  %s\n" "$*"; }
fail() { printf "${RED}✗${NC}  %s\n" "$*" >&2; exit 1; }

# ── Preflight checks ──
[[ "$(uname)" == "Darwin" ]] || fail "macOS required"
[[ "$(uname -m)" == "arm64" ]] || fail "Apple Silicon required"
[[ -d "$VENV_SRC" ]] || fail "No .venv found. Run ./install.sh first."
[[ -f "$SCRIPT_DIR/whisper_dictate.py" ]] || fail "whisper_dictate.py not found"
[[ -d "$SCRIPT_DIR/whisper_dictate" ]] || fail "whisper_dictate/ package not found"

# ── Clean previous build ──
log "Cleaning previous build..."
rm -rf "$DIST_DIR"
mkdir -p "$MACOS_DIR" "$RESOURCES"

# ── Copy source code ──
log "Copying source code..."
mkdir -p "$RESOURCES/app"
cp "$SCRIPT_DIR/whisper_dictate.py" "$RESOURCES/app/"
cp -R "$SCRIPT_DIR/whisper_dictate" "$RESOURCES/app/whisper_dictate"
# Strip __pycache__ from source
find "$RESOURCES/app" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
ok "Source code copied"

# ── Copy venv ──
log "Copying Python venv (this takes a moment)..."
cp -R "$VENV_SRC" "$RESOURCES/venv"

# Strip unnecessary files to reduce size
log "Stripping venv..."
find "$RESOURCES/venv" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
find "$RESOURCES/venv" -name "*.pyc" -delete 2>/dev/null || true
find "$RESOURCES/venv" -name "*.pyo" -delete 2>/dev/null || true
# Strip pip/setuptools/wheel caches
rm -rf "$RESOURCES/venv/lib/"*/site-packages/pip 2>/dev/null || true
rm -rf "$RESOURCES/venv/lib/"*/site-packages/setuptools 2>/dev/null || true
rm -rf "$RESOURCES/venv/lib/"*/site-packages/wheel 2>/dev/null || true
rm -rf "$RESOURCES/venv/lib/"*/site-packages/pip-*.dist-info 2>/dev/null || true
rm -rf "$RESOURCES/venv/lib/"*/site-packages/setuptools-*.dist-info 2>/dev/null || true
rm -rf "$RESOURCES/venv/lib/"*/site-packages/wheel-*.dist-info 2>/dev/null || true
ok "Venv copied and stripped"

# ── Fix venv for relocation ──
log "Fixing venv for relocation..."
# Update pyvenv.cfg to not require original path
PYVENV_CFG="$RESOURCES/venv/pyvenv.cfg"
if [[ -f "$PYVENV_CFG" ]]; then
    # Remove the home line that points to system Python
    # The launcher script will set paths explicitly
    sed -i '' 's|^home = .*|home = .|' "$PYVENV_CFG"
fi
ok "Venv paths fixed"

# ── Write launcher script ──
log "Writing launcher script..."
cat > "$MACOS_DIR/$APP_NAME" << 'LAUNCHER'
#!/bin/bash
# WhisperDictate launcher — uses bundled Python venv

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RESOURCES="$APP_DIR/Resources"
VENV="$RESOURCES/venv"
APP_CODE="$RESOURCES/app"
PYTHON="$VENV/bin/python3"
LOG_FILE="$HOME/.config/whisper/app.log"

# Ensure config directory exists
mkdir -p "$HOME/.config/whisper"

# Set PATH to include venv bin and homebrew (for codesign etc)
export PATH="$VENV/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

# Point Python at the bundled venv's site-packages
export PYTHONPATH="$APP_CODE"

# Launch the app
exec "$PYTHON" -u "$APP_CODE/whisper_dictate.py" >> "$LOG_FILE" 2>&1
LAUNCHER

chmod +x "$MACOS_DIR/$APP_NAME"
ok "Launcher script written"

# ── Write Info.plist ──
log "Writing Info.plist..."
cat > "$CONTENTS/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>$APP_NAME</string>
    <key>CFBundleDisplayName</key>
    <string>Whisper Dictate</string>
    <key>CFBundleIdentifier</key>
    <string>com.jerryshi.whisper-dictate</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundleExecutable</key>
    <string>$APP_NAME</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSMicrophoneUsageDescription</key>
    <string>Whisper Dictate needs microphone access for voice input.</string>
    <key>LSMinimumSystemVersion</key>
    <string>13.0</string>
</dict>
</plist>
PLIST
ok "Info.plist written"

# ── Codesign ──
log "Signing app bundle (ad-hoc)..."
codesign -s "-" --force --deep "$APP_DIR"
ok "App signed"

# ── Report .app size ──
APP_SIZE=$(du -sh "$APP_DIR" | cut -f1)
log "App bundle size: $APP_SIZE"

# ── Create DMG ──
log "Creating DMG..."
DMG_PATH="$DIST_DIR/$DMG_NAME.dmg"

# Create a temporary DMG with read-write, then convert to compressed read-only
TEMP_DMG="$DIST_DIR/temp_$DMG_NAME.dmg"
hdiutil create -volname "$APP_NAME" \
    -srcfolder "$APP_DIR" \
    -ov -format UDZO \
    -imagekey zlib-level=6 \
    "$DMG_PATH"

ok "DMG created"

# ── Report ──
DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
echo ""
printf "${GREEN}========================================${NC}\n"
printf "${GREEN}  Build complete!${NC}\n"
printf "${GREEN}========================================${NC}\n"
echo ""
echo "  DMG:  $DMG_PATH"
echo "  Size: $DMG_SIZE"
echo ""
echo "  To install: open the DMG, drag WhisperDictate to Applications."
echo "  First launch: right-click → Open (Gatekeeper bypass)."
echo "  Grant: Accessibility + Microphone permissions in System Settings."
echo ""

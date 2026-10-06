#!/usr/bin/env bash
# One-shot setup for a fresh machine: installs Python 3.10+ and FFmpeg,
# creates .venv, installs sportscode-extract, checks FFmpeg codecs and runs
# the test suite. Safe to re-run.
#
#   ./setup.sh              full setup
#   ./setup.sh --skip-tests skip pytest at the end
#
# Supports macOS (Homebrew) and Debian/Ubuntu (apt). Written for bash 3.2.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

RUN_TESTS=1
for arg in "$@"; do
    case "$arg" in
        --skip-tests) RUN_TESTS=0 ;;
        -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
        *) echo "Unknown option: $arg" >&2; exit 1 ;;
    esac
done

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
ok()   { printf '\033[1;32m  ✓ %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- System packages -------------------------------------------------------

load_brew() {
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -x "$b" ]; then eval "$("$b" shellenv)"; return 0; fi
    done
    command -v brew >/dev/null 2>&1
}

install_macos() {
    step "Checking Xcode Command Line Tools"
    if ! xcode-select -p >/dev/null 2>&1; then
        xcode-select --install || true
        die "Finish the Command Line Tools installer window, then re-run ./setup.sh"
    fi
    ok "Command Line Tools present"

    step "Checking Homebrew"
    if ! load_brew; then
        echo "  Installing Homebrew (you may be asked for your password)..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        load_brew || die "Homebrew installed but brew not found; open a new terminal and re-run"
    fi
    ok "Homebrew $(brew --version | head -1 | awk '{print $2}')"

    step "Installing Python 3.12 and FFmpeg via Homebrew"
    brew install python@3.12
    # Core Homebrew ffmpeg is built without freetype, so it lacks the drawtext
    # filter used by --render-titles. The homebrew-ffmpeg tap includes it.
    if brew list --formula --full-name | grep -qx ffmpeg; then
        echo "  Replacing core Homebrew ffmpeg (no drawtext) with homebrew-ffmpeg/ffmpeg..."
        brew uninstall --ignore-dependencies ffmpeg
    fi
    brew tap homebrew-ffmpeg/ffmpeg
    echo "  Installing homebrew-ffmpeg/ffmpeg (may build from source; can take a while)..."
    brew install homebrew-ffmpeg/ffmpeg/ffmpeg
    ok "Homebrew packages installed"
}

install_linux() {
    command -v apt-get >/dev/null 2>&1 || die "Only apt-based Linux is automated. Install Python 3.10+ and FFmpeg (libx264, aac) manually, then re-run."
    step "Installing Python and FFmpeg via apt (sudo required)"
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip ffmpeg
    ok "apt packages installed"
}

case "$(uname -s)" in
    Darwin) install_macos ;;
    Linux)  install_linux ;;
    *)      die "Unsupported OS: $(uname -s)" ;;
esac

# --- Python environment ----------------------------------------------------

py_ok() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; }

step "Locating Python 3.10+"
PYTHON=""
for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1 && py_ok "$candidate"; then
        PYTHON="$(command -v "$candidate")"; break
    fi
done
[ -n "$PYTHON" ] || die "No Python 3.10+ found on PATH"
ok "$PYTHON ($("$PYTHON" --version 2>&1))"

step "Creating virtual environment (.venv)"
if [ -x .venv/bin/python ] && py_ok .venv/bin/python; then
    ok "Reusing existing .venv"
else
    rm -rf .venv
    "$PYTHON" -m venv .venv
    ok "Created .venv"
fi

step "Installing sportscode-extract"
mkdir -p .tmp local_exports
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e '.[test]'
ok "$(.venv/bin/sportscode-extract --help >/dev/null && echo 'sportscode-extract command installed')"

# --- macOS app launcher ----------------------------------------------------

make_app() {
    step "Creating Sportscode Extract.app"
    local app="$ROOT/Sportscode Extract.app" icon="$ROOT/src/sportscode_extract/static/icon.png"
    local iconset="$ROOT/.tmp/icon.iconset" size
    rm -rf "$app" "$iconset"
    # An AppleScript applet, not a bare shell-script bundle: recent macOS refuses to
    # launch those (error -10810). The applet starts the server in the background and quits.
    osacompile -o "$app" \
        -e "set root to \"$ROOT\"" \
        -e 'do shell script "nohup " & quoted form of (root & "/run.sh") & " gui >> " & quoted form of (root & "/.tmp/gui.log") & " 2>&1 &"'
    mkdir -p "$iconset"
    for size in 16 32 128 256 512; do
        sips -z "$size" "$size" "$icon" --out "$iconset/icon_${size}x${size}.png" >/dev/null
        sips -z $((size * 2)) $((size * 2)) "$icon" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
    done
    iconutil -c icns "$iconset" -o "$app/Contents/Resources/applet.icns"
    # Drop the asset catalog so macOS uses applet.icns (the photo) instead of the default icon.
    rm -f "$app/Contents/Resources/Assets.car"
    plutil -remove CFBundleIconName "$app/Contents/Info.plist" 2>/dev/null || true
    plutil -replace CFBundleIdentifier -string local.sportscode-extract "$app/Contents/Info.plist"
    codesign --force --deep --sign - "$app" 2>/dev/null
    touch "$app"  # refresh Finder's icon cache
    ok "Double-click 'Sportscode Extract.app' to open the front end"
}
[ "$(uname -s)" = Darwin ] && make_app

# --- FFmpeg capability check -----------------------------------------------

step "Verifying FFmpeg codecs"
command -v ffmpeg  >/dev/null 2>&1 || die "ffmpeg not on PATH"
command -v ffprobe >/dev/null 2>&1 || die "ffprobe not on PATH"
ENCODERS="$(ffmpeg -hide_banner -encoders 2>/dev/null)"
DECODERS="$(ffmpeg -hide_banner -decoders 2>/dev/null)"
echo "$ENCODERS" | grep -qw libx264 || die "ffmpeg lacks libx264 encoder"
echo "$ENCODERS" | grep -qE ' aac '  || die "ffmpeg lacks AAC encoder"
echo "$DECODERS" | grep -qw hevc    || die "ffmpeg lacks HEVC decoder"
ffmpeg -hide_banner -filters 2>/dev/null | grep -qw drawtext \
    || die "ffmpeg lacks the drawtext filter (needs libfreetype) — $(command -v ffmpeg)"
ok "$(ffmpeg -version | head -1) — libx264, aac, hevc, drawtext OK"

# --- Tests -----------------------------------------------------------------

if [ "$RUN_TESTS" = 1 ]; then
    step "Running test suite"
    .venv/bin/python -m pytest -q --basetemp=.tmp/pytest || die "Tests failed — see output above"
    ok "Tests passed"
fi

chmod +x "$ROOT/run.sh"
step "Setup complete"
cat <<EOF
  Open the front end (or double-click 'Sportscode Extract.app' on macOS):
      ./run.sh gui

  Run in the terminal (prompts for the playlist):
      ./run.sh

  Or call the CLI directly:
      ./run.sh inspect  '/path/One.SCPlaylist'
      ./run.sh extract  '/path/One.SCPlaylist' --output ./local_exports/One
      ./run.sh validate ./local_exports/One
EOF

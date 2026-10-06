#!/usr/bin/env bash
# Run sportscode-extract from the project's .venv (created by ./setup.sh).
#
#   ./run.sh gui                   opens the web front end in your browser
#   ./run.sh                       interactive: asks for a playlist, extracts, validates
#   ./run.sh <subcommand> [args]   passes everything to the CLI (inspect/extract/validate)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLI="$ROOT/.venv/bin/sportscode-extract"
[ -x "$CLI" ] || { echo "Not set up yet — run ./setup.sh first." >&2; exit 1; }

# Make Homebrew's ffmpeg/ffprobe visible even if the shell profile wasn't updated.
for b in /opt/homebrew/bin /usr/local/bin; do
    case ":$PATH:" in *":$b:"*) ;; *) [ -d "$b" ] && PATH="$b:$PATH" ;; esac
done
export PATH

if [ "${1:-}" = gui ]; then
    shift
    exec "$ROOT/.venv/bin/python" -m sportscode_extract.gui --exports "$ROOT/local_exports" "$@"
fi
if [ $# -gt 0 ]; then
    exec "$CLI" "$@"
fi

# --- Interactive mode ------------------------------------------------------

echo "Drag a .SCPlaylist package into this window (or type its path), then press Enter:"
# No -r: lets the shell unescape drag-and-drop paths like My\ Playlist.SCPlaylist
read -p "> " PLAYLIST
PLAYLIST="${PLAYLIST%"${PLAYLIST##*[![:space:]]}"}"   # trim trailing whitespace
PLAYLIST="${PLAYLIST#\'}"; PLAYLIST="${PLAYLIST%\'}"  # strip surrounding quotes
PLAYLIST="${PLAYLIST#\"}"; PLAYLIST="${PLAYLIST%\"}"
[ -d "$PLAYLIST" ] || { echo "Not found: $PLAYLIST" >&2; exit 1; }

echo "Target application: [1] Angles (default)  [2] Catapult Focus"
read -r -p "> " CHOICE
TARGET=angles; [ "$CHOICE" = 2 ] && TARGET=focus

NAME="$(basename "$PLAYLIST" .SCPlaylist)"
OUTPUT="$ROOT/local_exports/$NAME"
EXTRA=""
if [ -e "$OUTPUT" ]; then
    read -r -p "$OUTPUT already exists. Overwrite? [y/N] " YN
    case "$YN" in [yY]*) EXTRA="--force" ;; *) echo "Aborted."; exit 1 ;; esac
fi

set +e
"$CLI" extract "$PLAYLIST" --output "$OUTPUT" --target "$TARGET" $EXTRA
STATUS=$?
set -e
[ "$STATUS" = 1 ] && { echo "Extraction failed." >&2; exit 1; }

"$CLI" validate "$OUTPUT"
echo
echo "Export written to: $OUTPUT"
[ "$(uname -s)" = Darwin ] && open "$OUTPUT"
exit "$STATUS"

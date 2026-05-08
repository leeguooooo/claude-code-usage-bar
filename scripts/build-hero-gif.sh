#!/usr/bin/env bash
# Re-build docs/images/hero.gif from scripts/hero.tape.
# Trims ~3.5s of vhs setup leakage and re-quantizes the palette.
#
# Deps: vhs (brew), ffmpeg (brew).

set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
TAPE="$ROOT/scripts/hero.tape"
OUT="$ROOT/docs/images/hero.gif"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

command -v vhs >/dev/null    || { echo "missing: vhs (brew install vhs)" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "missing: ffmpeg (brew install ffmpeg)" >&2; exit 1; }

echo "[1/2] vhs render..."
vhs "$TAPE"   # writes to $OUT per the tape's `Output` directive

echo "[2/2] ffmpeg trim + re-quantize..."
ffmpeg -y -loglevel warning \
  -ss 3.5 -i "$OUT" \
  -vf "fps=15,split[a][b];[a]palettegen=stats_mode=full[p];[b][p]paletteuse=dither=bayer:bayer_scale=5" \
  -f gif "$TMP/hero.gif"

mv "$TMP/hero.gif" "$OUT"

dur=$(ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$OUT")
size=$(ls -lh "$OUT" | awk '{print $5}')
echo "wrote $OUT  (${dur}s, $size)"

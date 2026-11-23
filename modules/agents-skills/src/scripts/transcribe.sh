#!/usr/bin/env bash
# transcribe.sh <source> [language] [output_prefix]
#   source   a local audio or video file, or a URL (YouTube, Vimeo, most e-learning platforms through yt-dlp)
#   language ISO code (en, fr, ...) or "auto" (default)
#   prefix   base name of the output files (default: derived from the source)
# Output: <OUT_DIR>/<prefix>.txt (plain text) and <prefix>.vtt (with timecodes); prints both paths.
#
# Needs: ffmpeg, whisper-cli (whisper.cpp), yt-dlp for URLs, and a whisper model file.
#   WHISPER_MODEL   path to the ggml model (default ~/.local/share/whisper-cpp/ggml-large-v3-turbo-q5_0.bin)
#   TRANSCRIBE_OUT  output folder (default ~/transcriptions)
set -euo pipefail

MODEL="${WHISPER_MODEL:-$HOME/.local/share/whisper-cpp/ggml-large-v3-turbo-q5_0.bin}"
OUT_DIR="${TRANSCRIBE_OUT:-$HOME/transcriptions}"

die() { printf 'transcribe: %s\n' "$1" >&2; exit 1; }

[ $# -ge 1 ] || die "usage: transcribe.sh <file|url> [language] [prefix]"
SRC="$1"
LANGUAGE="${2:-auto}"

for bin in ffmpeg whisper-cli; do
  command -v "$bin" >/dev/null 2>&1 || die "$bin not found in PATH"
done
[ -f "$MODEL" ] || die "whisper model missing: $MODEL (set WHISPER_MODEL)"

mkdir -p "$OUT_DIR"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [[ "$SRC" =~ ^https?:// ]]; then
  command -v yt-dlp >/dev/null 2>&1 || die "yt-dlp not found, required for a URL"
  DEFAULT_PREFIX="$(yt-dlp --print "%(title)s" --no-warnings "$SRC" 2>/dev/null | head -1)"
  [ -n "$DEFAULT_PREFIX" ] || DEFAULT_PREFIX="video"
  yt-dlp -f "bestaudio/best" --no-playlist -o "$TMP/media.%(ext)s" "$SRC" \
    || die "download failed (protected video? cookies needed?)"
  MEDIA="$(find "$TMP" -maxdepth 1 -name 'media.*' | head -1)"
  [ -n "$MEDIA" ] || die "nothing was downloaded"
else
  [ -f "$SRC" ] || die "file not found: $SRC"
  MEDIA="$SRC"
  DEFAULT_PREFIX="$(basename "${SRC%.*}")"
fi

PREFIX="${3:-$DEFAULT_PREFIX}"
PREFIX="$(printf '%s' "$PREFIX" | tr -cs '[:alnum:]._-' '_' | cut -c1-80)"

ffmpeg -nostdin -loglevel error -y -i "$MEDIA" -vn -ac 1 -ar 16000 -c:a pcm_s16le "$TMP/audio.wav" \
  || die "audio extraction failed"

whisper-cli -m "$MODEL" -f "$TMP/audio.wav" -l "$LANGUAGE" -otxt -ovtt -np \
  -of "$OUT_DIR/$PREFIX" >/dev/null 2>&1 \
  || die "transcription failed"

[ -s "$OUT_DIR/$PREFIX.txt" ] || die "transcript is empty"
printf '%s\n' "$OUT_DIR/$PREFIX.txt" "$OUT_DIR/$PREFIX.vtt"

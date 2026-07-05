#!/usr/bin/env bash
# streamer/run-record.sh — Stream Phase 6-B: 60秒ローカル録画モード
#
# entrypoint.sh が Xvfb + Chromium を起動済みの前提で、DISPLAY 上の画面を
# ffmpeg (x11grab) で RECORD_SECONDS 秒だけ録画し、OUTPUT_FILE に MP4 を書き出す。
# YouTube へは一切送信しない (完全ローカル)。
set -euo pipefail

AUDIO_BITRATE="${AUDIO_BITRATE:-128k}"

mkdir -p "$(dirname "${OUTPUT_FILE}")"

echo "[run-record] recording ${RECORD_SECONDS}s @ ${STREAM_WIDTH}x${STREAM_HEIGHT} ${STREAM_FPS}fps -> ${OUTPUT_FILE}"

ffmpeg \
  -y \
  -f x11grab \
  -draw_mouse 0 \
  -video_size "${STREAM_WIDTH}x${STREAM_HEIGHT}" \
  -framerate "${STREAM_FPS}" \
  -i "${DISPLAY}.0" \
  -f lavfi \
  -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
  -t "${RECORD_SECONDS}" \
  -c:v libx264 \
  -preset veryfast \
  -pix_fmt yuv420p \
  -b:v "${VIDEO_BITRATE}" \
  -maxrate "${VIDEO_BITRATE}" \
  -bufsize "7000k" \
  -c:a aac \
  -b:a "${AUDIO_BITRATE}" \
  "${OUTPUT_FILE}"

echo "[run-record] done: ${OUTPUT_FILE}"
ls -lh "${OUTPUT_FILE}" || true

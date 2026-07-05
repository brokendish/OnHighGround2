#!/usr/bin/env bash
# streamer/run-youtube.sh — Stream Phase 6-C: YouTube RTMPS 限定公開送信 (PoC)
#
# 既定では実送信を行わない (dry-run)。YOUTUBE_CONFIRM=1 を明示的に設定した場合のみ
# 実際に ffmpeg で配信を開始する。Stream Key はログに出さない (出す場合は必ずマスクする)。
# PoCとして安全側に倒すため、STREAM_DURATION_SEC (既定300秒) で送信時間を必ず区切る
# (無制限配信を避ける — Phase 6-C の FAIL条件「YouTubeへ意図せず無制限配信される」対応)。
set -euo pipefail

: "${YOUTUBE_RTMP_URL:?YOUTUBE_RTMP_URL is required (see .env.stream.example)}"
: "${YOUTUBE_STREAM_KEY:?YOUTUBE_STREAM_KEY is required (see .env.stream.example)}"

AUDIO_BITRATE="${AUDIO_BITRATE:-128k}"
# 安全側: 未指定なら 300 秒 (5分) に制限する。無制限にしたい場合のみ明示的に 0 を指定する。
STREAM_DURATION_SEC="${STREAM_DURATION_SEC:-300}"

DEST_URL="${YOUTUBE_RTMP_URL}/${YOUTUBE_STREAM_KEY}"
MASKED_URL="${YOUTUBE_RTMP_URL}/****"

# ffmpeg 自体の stderr にも接続先URL(キー入り)が出るため、必ずマスクして表示する。
mask_key() {
  sed -u "s#${YOUTUBE_STREAM_KEY}#****#g"
}

# -t 0 または未設定(空文字)は「無制限」を意味するため、その場合だけ -t を付けない。
DURATION_ARGS=()
DURATION_DESC="unlimited (!)"
if [[ -n "${STREAM_DURATION_SEC}" && "${STREAM_DURATION_SEC}" != "0" ]]; then
  DURATION_ARGS=(-t "${STREAM_DURATION_SEC}")
  DURATION_DESC="${STREAM_DURATION_SEC}s"
fi

echo "[run-youtube] target: ${MASKED_URL}"
echo "[run-youtube] video: ${STREAM_WIDTH}x${STREAM_HEIGHT}@${STREAM_FPS}fps bitrate=${VIDEO_BITRATE} audio=${AUDIO_BITRATE} duration=${DURATION_DESC}"

if [[ "${YOUTUBE_CONFIRM:-0}" != "1" ]]; then
  cat <<EOF
[run-youtube] dry-run mode (YOUTUBE_CONFIRM is not "1"). No stream will be started.

The following ffmpeg command would run (destination masked):

  ffmpeg -y \\
    -f x11grab -draw_mouse 0 -video_size ${STREAM_WIDTH}x${STREAM_HEIGHT} -framerate ${STREAM_FPS} -i \${DISPLAY}.0 \\
    -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=44100 \\
    -c:v libx264 -preset veryfast -pix_fmt yuv420p -tune zerolatency \\
    -b:v ${VIDEO_BITRATE} -maxrate ${VIDEO_BITRATE} -bufsize 7000k \\
    -g $(( STREAM_FPS * 2 )) \\
    -c:a aac -b:a ${AUDIO_BITRATE} -ar 44100 \\
    ${DURATION_ARGS[@]+"${DURATION_ARGS[@]}"} \\
    -f flv ${MASKED_URL}

  (duration: ${DURATION_DESC})

To actually start streaming, re-run with YOUTUBE_CONFIRM=1.
This is a PoC scaffold — verify Stream Key / privacy settings (限定公開) on YouTube's side first.
EOF
  exit 0
fi

if [[ "${DURATION_DESC}" == "unlimited (!)" ]]; then
  echo "[run-youtube] WARNING: STREAM_DURATION_SEC=0 — streaming with NO time limit." >&2
fi
echo "[run-youtube] YOUTUBE_CONFIRM=1 — starting live stream to ${MASKED_URL} (duration=${DURATION_DESC})"

set +e
ffmpeg \
  -y \
  -f x11grab \
  -draw_mouse 0 \
  -video_size "${STREAM_WIDTH}x${STREAM_HEIGHT}" \
  -framerate "${STREAM_FPS}" \
  -i "${DISPLAY}.0" \
  -f lavfi \
  -i "anullsrc=channel_layout=stereo:sample_rate=44100" \
  -c:v libx264 \
  -preset veryfast \
  -pix_fmt yuv420p \
  -tune zerolatency \
  -b:v "${VIDEO_BITRATE}" \
  -maxrate "${VIDEO_BITRATE}" \
  -bufsize "7000k" \
  -g $(( STREAM_FPS * 2 )) \
  -c:a aac \
  -b:a "${AUDIO_BITRATE}" \
  -ar 44100 \
  ${DURATION_ARGS[@]+"${DURATION_ARGS[@]}"} \
  -f flv \
  "${DEST_URL}" 2>&1 | mask_key
STATUS="${PIPESTATUS[0]}"
set -e

echo "[run-youtube] ffmpeg exited with status ${STATUS}"
exit "${STATUS}"

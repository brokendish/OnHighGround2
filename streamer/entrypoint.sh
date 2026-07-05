#!/usr/bin/env bash
# streamer/entrypoint.sh — Stream Phase 6-B
#
# mode を受け取り、Xvfb + Chromium を起動してから record/youtube 処理へ渡す。
# 使い方:
#   docker compose --profile streamer run --rm streamer record
#   docker compose --profile streamer run --rm streamer youtube
#   docker compose --profile streamer run --rm streamer shell
set -euo pipefail

MODE="${1:-record}"

XVFB_PID=""
CHROMIUM_PID=""

cleanup() {
  if [[ -n "${CHROMIUM_PID}" ]] && kill -0 "${CHROMIUM_PID}" 2>/dev/null; then
    echo "[entrypoint] stopping chromium (pid ${CHROMIUM_PID})"
    kill "${CHROMIUM_PID}" 2>/dev/null || true
  fi
  if [[ -n "${XVFB_PID}" ]] && kill -0 "${XVFB_PID}" 2>/dev/null; then
    echo "[entrypoint] stopping Xvfb (pid ${XVFB_PID})"
    kill "${XVFB_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# frontend コンテナがまだ起動しきっていない場合に備えて軽くポーリングする
# (無ければ警告だけ出してそのまま進める — chromium 側のリトライに任せる)。
wait_for_frontend() {
  local base_url="${STREAM_URL%%\?*}"
  local tries=0
  local max_tries=30
  echo "[entrypoint] waiting for ${base_url} ..."
  until curl -fsS -o /dev/null "${base_url}" 2>/dev/null; do
    tries=$((tries + 1))
    if [[ "${tries}" -ge "${max_tries}" ]]; then
      echo "[entrypoint] WARNING: ${base_url} not reachable after ${tries}s, proceeding anyway" >&2
      return 0
    fi
    sleep 1
  done
  echo "[entrypoint] frontend reachable after ${tries}s"
}

start_xvfb() {
  echo "[entrypoint] starting Xvfb on ${DISPLAY} (${STREAM_WIDTH}x${STREAM_HEIGHT})"
  Xvfb "${DISPLAY}" -screen 0 "${STREAM_WIDTH}x${STREAM_HEIGHT}x24" -nolisten tcp &
  XVFB_PID=$!
  sleep 1
}

start_chromium() {
  echo "[entrypoint] starting chromium -> ${STREAM_URL}"
  chromium \
    --no-sandbox \
    --disable-dev-shm-usage \
    --disable-gpu \
    --autoplay-policy=no-user-gesture-required \
    --window-size="${STREAM_WIDTH},${STREAM_HEIGHT}" \
    --window-position=0,0 \
    --start-fullscreen \
    --kiosk \
    --user-data-dir=/tmp/chromium-profile \
    --no-first-run \
    --disable-infobars \
    --lang=ja \
    --disable-features=Translate,TranslateUI \
    --disable-translate \
    --disable-notifications \
    --disable-session-crashed-bubble \
    --overscroll-history-navigation=0 \
    "${STREAM_URL}" \
    >/tmp/chromium.log 2>&1 &
  CHROMIUM_PID=$!
  echo "[entrypoint] chromium pid=${CHROMIUM_PID}, waiting ${CHROMIUM_WAIT_SECONDS}s for page load"
  sleep "${CHROMIUM_WAIT_SECONDS}"
  if ! kill -0 "${CHROMIUM_PID}" 2>/dev/null; then
    echo "[entrypoint] ERROR: chromium exited early. Log:" >&2
    cat /tmp/chromium.log >&2 || true
    exit 1
  fi
}

case "${MODE}" in
  record)
    wait_for_frontend
    start_xvfb
    start_chromium
    /usr/local/bin/run-record.sh
    ;;
  youtube)
    wait_for_frontend
    start_xvfb
    start_chromium
    /usr/local/bin/run-youtube.sh
    ;;
  shell)
    exec bash
    ;;
  *)
    echo "[entrypoint] unknown mode: ${MODE} (expected: record|youtube|shell)" >&2
    exit 1
    ;;
esac

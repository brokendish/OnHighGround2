#!/usr/bin/env bash
set -u

# ============================================================
# OnHighGround2 /live/stream VPS Stream Controller
# whiptail menu for streamer container
# ============================================================

APP_DIR="${APP_DIR:-$HOME/Development/GitHub/OnHighGround2}"
ENV_FILE="${ENV_FILE:-$APP_DIR/.env.stream}"
CONTAINER_NAME="${CONTAINER_NAME:-ohg2-streamer}"
COMPOSE_CMD="${COMPOSE_CMD:-docker compose}"
STREAMER_SERVICE="${STREAMER_SERVICE:-streamer}"

WT_HEIGHT=22
WT_WIDTH=82
WT_MENU_HEIGHT=14

cd "$APP_DIR" || {
  echo "ERROR: APP_DIR not found: $APP_DIR"
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: command not found: $1"
    exit 1
  }
}

need_cmd docker
need_cmd whiptail

info_box() {
  whiptail --title "$1" --msgbox "$2" "$WT_HEIGHT" "$WT_WIDTH"
}

yesno() {
  whiptail --title "$1" --yesno "$2" "$WT_HEIGHT" "$WT_WIDTH"
}

is_running() {
  docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"
}

is_exists() {
  docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"
}

mask_secret_text() {
  sed -E \
    -e 's/(YOUTUBE_STREAM_KEY=).*/\1****/g' \
    -e 's/(.*STREAM_KEY.*=).*/\1****/g' \
    -e 's#(rtmp://[^/]+/live2/)[^[:space:]]+#\1****#g' \
    -e 's#(live2/)[^[:space:]]+#\1****#g'
}

mask_env_preview() {
  if [[ ! -f "$ENV_FILE" ]]; then
    echo "ENV file not found: $ENV_FILE"
    return
  fi
  mask_secret_text < "$ENV_FILE"
}

load_env_safe() {
  if [[ -f "$ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE"
    set +a
  fi
}

format_duration() {
  local sec="${1:-}"
  if [[ -z "$sec" ]]; then
    echo "Use .env.stream default"
    return
  fi
  local h=$((sec / 3600))
  local m=$(((sec % 3600) / 60))
  local s=$((sec % 60))
  if (( h > 0 )); then
    printf "%dh %02dm %02ds (%ss)" "$h" "$m" "$s" "$sec"
  elif (( m > 0 )); then
    printf "%dm %02ds (%ss)" "$m" "$s" "$sec"
  else
    printf "%ss" "$sec"
  fi
}

choose_duration_sec() {
  local choice
  choice=$(whiptail --title "Stream Duration" \
    --menu "Select stream duration. This overrides STREAM_DURATION_SEC only for this launch." 22 78 11 \
    "env"  "Use .env.stream STREAM_DURATION_SEC" \
    "5m"   "5 minutes" \
    "15m"  "15 minutes" \
    "30m"  "30 minutes" \
    "1h"   "1 hour" \
    "3h"   "3 hours" \
    "5h"   "5 hours" \
    "min"  "Manual input: minutes" \
    "hour" "Manual input: hours" \
    "sec"  "Manual input: seconds" \
    3>&1 1>&2 2>&3) || return 1

  case "$choice" in
    env)  echo "" ;;
    5m)   echo 300 ;;
    15m)  echo 900 ;;
    30m)  echo 1800 ;;
    1h)   echo 3600 ;;
    3h)   echo 10800 ;;
    5h)   echo 18000 ;;
    min)
      local minutes
      minutes=$(whiptail --title "Duration minutes" \
        --inputbox "Enter stream duration in minutes. Example: 90" 10 65 \
        3>&1 1>&2 2>&3) || return 1
      if [[ ! "$minutes" =~ ^[0-9]+$ ]] || (( minutes <= 0 )); then
        info_box "Invalid input" "Please enter a positive integer."
        return 1
      fi
      echo $((minutes * 60))
      ;;
    hour)
      local hours
      hours=$(whiptail --title "Duration hours" \
        --inputbox "Enter stream duration in hours. Example: 5" 10 65 \
        3>&1 1>&2 2>&3) || return 1
      if [[ ! "$hours" =~ ^[0-9]+$ ]] || (( hours <= 0 )); then
        info_box "Invalid input" "Please enter a positive integer."
        return 1
      fi
      echo $((hours * 3600))
      ;;
    sec)
      local seconds
      seconds=$(whiptail --title "Duration seconds" \
        --inputbox "Enter stream duration in seconds. Example: 300" 10 65 \
        3>&1 1>&2 2>&3) || return 1
      if [[ ! "$seconds" =~ ^[0-9]+$ ]] || (( seconds <= 0 )); then
        info_box "Invalid input" "Please enter a positive integer."
        return 1
      fi
      echo "$seconds"
      ;;
  esac
}

show_status() {
  local status stats env_preview default_duration
  load_env_safe
  default_duration="${STREAM_DURATION_SEC:-unset}"

  if is_running; then
    status="RUNNING"
    stats="$(docker stats --no-stream "$CONTAINER_NAME" 2>/dev/null || true)"
  elif is_exists; then
    status="STOPPED container exists"
    stats="$(docker ps -a --filter "name=$CONTAINER_NAME" --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}')"
  else
    status="NOT RUNNING"
    stats="No streamer container found."
  fi

  env_preview="$(mask_env_preview)"

  whiptail --title "Streamer Status" --scrolltext --msgbox \
"Status: $status

App dir:
$APP_DIR

Env file:
$ENV_FILE

Container:
$CONTAINER_NAME

Default STREAM_DURATION_SEC:
$default_duration

Default duration:
$(format_duration "${STREAM_DURATION_SEC:-}")

Docker:
$($COMPOSE_CMD version 2>/dev/null | head -n 1)

--- docker stats / ps ---
$stats

--- .env.stream preview ---
$env_preview
" 36 110
}

validate_env() {
  local msg=""
  local ok=1

  if [[ ! -f "$ENV_FILE" ]]; then
    info_box "ENV check" ".env.stream not found:

$ENV_FILE"
    return
  fi

  load_env_safe

  [[ -n "${YOUTUBE_RTMP_URL:-}" ]] || { msg+="YOUTUBE_RTMP_URL is empty\n"; ok=0; }
  [[ -n "${YOUTUBE_STREAM_KEY:-}" ]] || { msg+="YOUTUBE_STREAM_KEY is empty\n"; ok=0; }
  [[ -n "${STREAM_URL:-}" ]] || { msg+="STREAM_URL is empty\n"; ok=0; }
  [[ -n "${STREAM_WIDTH:-}" ]] || { msg+="STREAM_WIDTH is empty\n"; ok=0; }
  [[ -n "${STREAM_HEIGHT:-}" ]] || { msg+="STREAM_HEIGHT is empty\n"; ok=0; }
  [[ -n "${STREAM_FPS:-}" ]] || { msg+="STREAM_FPS is empty\n"; ok=0; }
  [[ -n "${VIDEO_BITRATE:-}" ]] || { msg+="VIDEO_BITRATE is empty\n"; ok=0; }
  [[ -n "${AUDIO_BITRATE:-}" ]] || { msg+="AUDIO_BITRATE is empty\n"; ok=0; }
  [[ -n "${STREAM_DURATION_SEC:-}" ]] || { msg+="STREAM_DURATION_SEC is empty\n"; ok=0; }

  if [[ -n "${STREAM_DURATION_SEC:-}" ]] && ! [[ "$STREAM_DURATION_SEC" =~ ^[0-9]+$ ]]; then
    msg+="STREAM_DURATION_SEC is not numeric\n"
    ok=0
  fi

  if [[ "$ok" -eq 1 ]]; then
    msg="ENV looks OK.

Default duration:
$(format_duration "$STREAM_DURATION_SEC")

$(mask_env_preview)"
  else
    msg="ENV has issues:

$msg

$(mask_env_preview)"
  fi

  whiptail --title "ENV Check" --scrolltext --msgbox "$msg" 34 110
}

start_stream() {
  if [[ ! -f "$ENV_FILE" ]]; then
    info_box "ERROR" ".env.stream not found:

$ENV_FILE"
    return
  fi

  if is_running; then
    info_box "Already running" "Streamer is already running:

$CONTAINER_NAME"
    return
  fi

  if is_exists; then
    if yesno "Existing container" "Stopped container exists:

$CONTAINER_NAME

Remove it before starting?"; then
      docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || {
        info_box "ERROR" "Failed to remove existing container: $CONTAINER_NAME"
        return
      }
    else
      return
    fi
  fi

  local duration_sec
  duration_sec="$(choose_duration_sec)" || return
  local duration_label
  duration_label="$(format_duration "$duration_sec")"
  local env_preview
  env_preview="$(mask_env_preview)"

  if ! yesno "Start YouTube Stream" \
"Start YouTube streaming?

Container:
$CONTAINER_NAME

Duration:
$duration_label

Command:
$COMPOSE_CMD --profile streamer run -d --rm --name $CONTAINER_NAME -e YOUTUBE_CONFIRM=1 [-e STREAM_DURATION_SEC=...] $STREAMER_SERVICE youtube

Env preview:
$env_preview

Stream key is masked. Continue?"; then
    return
  fi

  local log_file="/tmp/ohg2-streamer-start.log"
  local rc

  if [[ -n "$duration_sec" ]]; then
    $COMPOSE_CMD --profile streamer run -d --rm \
      --name "$CONTAINER_NAME" \
      -e YOUTUBE_CONFIRM=1 \
      -e STREAM_DURATION_SEC="$duration_sec" \
      "$STREAMER_SERVICE" youtube >"$log_file" 2>&1
    rc=$?
  else
    $COMPOSE_CMD --profile streamer run -d --rm \
      --name "$CONTAINER_NAME" \
      -e YOUTUBE_CONFIRM=1 \
      "$STREAMER_SERVICE" youtube >"$log_file" 2>&1
    rc=$?
  fi

  if [[ $rc -ne 0 ]]; then
    info_box "Start failed" "Failed to start streamer.

Exit code: $rc

Log:
$(cat "$log_file")"
    return
  fi

  sleep 2

  info_box "Started" "Streamer started.

Container:
$CONTAINER_NAME

Duration:
$duration_label

Next:
- Check logs
- Check YouTube Studio
- Check docker stats"
}

start_stream_unlimited() {
  if [[ ! -f "$ENV_FILE" ]]; then
    info_box "ERROR" ".env.stream not found:

$ENV_FILE"
    return
  fi

  if is_running; then
    info_box "Already running" "Streamer is already running:

$CONTAINER_NAME"
    return
  fi

  if is_exists; then
    if yesno "Existing container" "Stopped container exists:

$CONTAINER_NAME

Remove it before starting?"; then
      docker rm "$CONTAINER_NAME" >/dev/null 2>&1 || {
        info_box "ERROR" "Failed to remove existing container: $CONTAINER_NAME"
        return
      }
    else
      return
    fi
  fi

  local env_preview
  env_preview="$(mask_env_preview)"

  if ! yesno "Start YouTube Stream Unlimited" \
"Start YouTube streaming with no duration limit?

Container:
$CONTAINER_NAME

Duration:
Unlimited / manual stop

Stop:
- Menu: Stop Stream
- CLI: docker stop $CONTAINER_NAME
- Emergency: docker rm -f $CONTAINER_NAME

Command:
$COMPOSE_CMD --profile streamer run -d --rm --name $CONTAINER_NAME -e YOUTUBE_CONFIRM=1 -e STREAM_DURATION_SEC= $STREAMER_SERVICE youtube

Env preview:
$env_preview

Stream key is masked. Continue?"; then
    return
  fi

  local log_file="/tmp/ohg2-streamer-start-unlimited.log"
  local rc

  $COMPOSE_CMD --profile streamer run -d --rm \
    --name "$CONTAINER_NAME" \
    -e YOUTUBE_CONFIRM=1 \
    -e STREAM_DURATION_SEC=0 \
    "$STREAMER_SERVICE" youtube >"$log_file" 2>&1
  rc=$?

  if [[ $rc -ne 0 ]]; then
    info_box "Start failed" "Failed to start streamer.

Exit code: $rc

Log:
$(cat "$log_file")"
    return
  fi

  sleep 2

  info_box "Started" "Streamer started.

Container:
$CONTAINER_NAME

Duration:
Unlimited / manual stop

Next:
- Check logs
- Check YouTube Studio
- Check docker stats
- Stop manually when finished"
}

stop_stream() {
  if ! is_running; then
    info_box "Not running" "Streamer is not running."
    return
  fi

  if ! yesno "Stop Stream" "Stop streamer container?

$CONTAINER_NAME"; then
    return
  fi

  local log_file="/tmp/ohg2-streamer-stop.log"
  docker stop "$CONTAINER_NAME" >"$log_file" 2>&1
  local rc=$?

  if [[ $rc -ne 0 ]]; then
    info_box "Stop failed" "Failed to stop streamer.

Exit code: $rc

Log:
$(cat "$log_file")"
    return
  fi

  info_box "Stopped" "Streamer stopped:

$CONTAINER_NAME"
}

kill_stream() {
  if ! is_exists; then
    info_box "Not found" "No streamer container found."
    return
  fi

  if ! yesno "Emergency Stop" "Force remove streamer container?

docker rm -f $CONTAINER_NAME

Use only when normal stop fails."; then
    return
  fi

  local log_file="/tmp/ohg2-streamer-kill.log"
  docker rm -f "$CONTAINER_NAME" >"$log_file" 2>&1
  local rc=$?

  if [[ $rc -ne 0 ]]; then
    info_box "Emergency stop failed" "Failed to force remove streamer.

Exit code: $rc

Log:
$(cat "$log_file")"
    return
  fi

  info_box "Emergency stopped" "Streamer force removed:

$CONTAINER_NAME"
}

show_logs() {
  if ! is_exists; then
    info_box "No logs" "No streamer container found."
    return
  fi

  local logfile
  logfile="$(mktemp /tmp/ohg2-streamer-logs.XXXXXX)"

  docker logs --tail=160 "$CONTAINER_NAME" 2>&1 \
    | mask_secret_text \
    > "$logfile"

  whiptail --title "Streamer Logs tail=160" --scrolltext --textbox "$logfile" 34 120
  rm -f "$logfile"
}

follow_logs_hint() {
  info_box "Follow logs" "Run this in another terminal:

docker logs -f $CONTAINER_NAME

Stream key should remain masked by streamer scripts."
}

show_stats() {
  local tempfile
  tempfile="$(mktemp /tmp/ohg2-docker-stats.XXXXXX)"

  {
    echo "docker stats --no-stream"
    echo
    docker stats --no-stream 2>&1
    echo
    echo "docker ps"
    echo
    docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  } > "$tempfile"

  whiptail --title "Docker Stats" --scrolltext --textbox "$tempfile" 34 120
  rm -f "$tempfile"
}

record_test() {
  if [[ ! -f "$ENV_FILE" ]]; then
    info_box "ERROR" ".env.stream not found:

$ENV_FILE"
    return
  fi

  if is_running; then
    info_box "Streamer running" "Streamer is already running. Stop it before record test."
    return
  fi

  if ! yesno "Record Test" "Run local record test?

This should not publish to YouTube.
It uses streamer record command."; then
    return
  fi

  local logfile
  logfile="$(mktemp /tmp/ohg2-streamer-record.XXXXXX)"

  $COMPOSE_CMD --profile streamer run --rm "$STREAMER_SERVICE" record > "$logfile" 2>&1
  local rc=$?

  mask_secret_text < "$logfile" > "${logfile}.masked"
  whiptail --title "Record Test Result rc=$rc" --scrolltext --textbox "${logfile}.masked" 34 120
  rm -f "$logfile" "${logfile}.masked"
}

show_manual() {
  local manual
  manual="$(mktemp /tmp/ohg2-stream-menu-manual.XXXXXX)"

  cat > "$manual" <<'MANUAL'
OnHighGround2 /live/stream Stream Controller

Basic usage:
  1. Validate .env.stream
  2. Start YouTube Stream
  3. Select duration, or use Unlimited / manual stop
  4. Check logs
  5. Check YouTube Studio / YouTube watch page
  6. Stop Stream if needed

Recommended .env.stream:
  YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2
  YOUTUBE_STREAM_KEY=your_key_here
  STREAM_URL=http://frontend/live/stream?chrome=off
  STREAM_WIDTH=1280
  STREAM_HEIGHT=720
  STREAM_FPS=30
  VIDEO_BITRATE=3500k
  AUDIO_BITRATE=128k
  STREAM_DURATION_SEC=300

Notes:
  - .env.stream must not be committed to git.
  - Stream key must never appear in logs.
  - The script starts the streamer as:
      docker compose --profile streamer run -d --rm --name ohg2-streamer ...
  - This continues running even if SSH disconnects.
  - Stop with:
      docker stop ohg2-streamer
  - Emergency stop:
      docker rm -f ohg2-streamer

Duration:
  - The menu can override STREAM_DURATION_SEC only for this launch.
  - Unlimited / manual stop starts with STREAM_DURATION_SEC empty for this launch.
  - .env.stream is not rewritten.
  - 5 hours = 18000 seconds.
  - Stop unlimited streaming manually from the menu or with docker stop ohg2-streamer.

Checks during streaming:
  - docker logs -f ohg2-streamer
  - watch -n 2 'docker stats --no-stream'
  - YouTube Studio stream health
  - YouTube watch page
MANUAL

  whiptail --title "Manual" --scrolltext --textbox "$manual" 34 110
  rm -f "$manual"
}

main_menu() {
  while true; do
    local running_label
    if is_running; then
      running_label="RUNNING"
    else
      running_label="STOPPED"
    fi

    local choice
    choice=$(whiptail --title "OnHighGround2 Stream Controller [$running_label]" \
      --menu "Choose action" "$WT_HEIGHT" "$WT_WIDTH" "$WT_MENU_HEIGHT" \
      "1" "Status" \
      "2" "Start YouTube Stream (duration menu)" \
      "3" "Start YouTube Stream (unlimited / manual stop)" \
      "4" "Stop Stream" \
      "5" "Emergency Stop rm -f" \
      "6" "Show Logs tail" \
      "7" "Follow Logs command" \
      "8" "Docker Stats" \
      "9" "Record Test" \
      "10" "Validate .env.stream" \
      "11" "Manual" \
      "12" "Exit" \
      3>&1 1>&2 2>&3)

    local rc=$?
    [[ $rc -ne 0 ]] && exit 0

    case "$choice" in
      1) show_status ;;
      2) start_stream ;;
      3) start_stream_unlimited ;;
      4) stop_stream ;;
      5) kill_stream ;;
      6) show_logs ;;
      7) follow_logs_hint ;;
      8) show_stats ;;
      9) record_test ;;
      10) validate_env ;;
      11) show_manual ;;
      12) exit 0 ;;
    esac
  done
}

main_menu

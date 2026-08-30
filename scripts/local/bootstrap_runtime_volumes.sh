#!/usr/bin/env bash
#
# bootstrap_runtime_volumes.sh — local runtime profile（macOS Docker Desktop 向け）の
# named volume を backend-public（UID/GID 10001:10001）が使える状態に初期化する。
#
# 背景:
#   local runtime profile（docker-compose.override.yml、docker-compose.override.example.yml
#   から作成）は /data_runtime を host bind mount から named volume へ切り替える。
#   Docker が新規作成する named volume の root は root:root 0755 のため、
#   /data_runtime/logs・/data_runtime/cache 専用 child named volume へは
#   backend-public（UID 10001）が書き込めない。runtime-init（root, one-shot）は
#   .staging / versions / .publish.lock だけを扱い logs/cache には関与しないため、
#   この helper が opt-in の前処理として ownership と nested mountpoint を用意する。
#
# この helper がやること（idempotent・非破壊）:
#   1. 対象 named volume（data-runtime / logs / cache）を docker volume create（既存なら no-op）
#   2. 共有 runtime volume 内へ nested mountpoint を mkdir -p
#      （logs, cache, backend, frontend, frontend/tiles, および config/martin-local.yaml が
#       参照する frontend/tiles/<region>/<hazard> の全ディレクトリ）
#   3. logs / cache child volume の root を 10001:10001 / mode 0750 に設定
#
# この helper がやらないこと:
#   - .publish.lock / .staging / versions の作成（runtime-init の責務。奪わない）
#   - chown -R / chmod -R / rm 等の再帰・破壊操作
#   - owner Compose の起動、production への接続・変更
#
# 使い方:
#   scripts/local/bootstrap_runtime_volumes.sh [--dry-run] [COMPOSE_FILE ...]
#
#   既定の COMPOSE_FILE: docker-compose.yml docker-compose.override.yml
#   COMPOSE_PROJECT_NAME / -p は docker compose と同じく環境変数で渡す:
#     COMPOSE_PROJECT_NAME=onhighground2-qual scripts/local/bootstrap_runtime_volumes.sh \
#       docker-compose.yml docker-compose.override.example.yml
#
# 環境変数:
#   OHG2_BOOTSTRAP_IMAGE  helper コンテナの image（既定: Compose で pin 済みの nginx alpine）
#   OHG2_PUBLIC_UID / OHG2_PUBLIC_GID  既定 10001 / 10001

set -euo pipefail

PUBLIC_UID="${OHG2_PUBLIC_UID:-10001}"
PUBLIC_GID="${OHG2_PUBLIC_GID:-10001}"
CHILD_VOLUME_MODE="0750"
# Compose の frontend / martin と同一の pin 済み image を既定にする（追加の image 依存を作らない）。
BOOTSTRAP_IMAGE="${OHG2_BOOTSTRAP_IMAGE:-nginx:1.28.0-alpine@sha256:30f1c0d78e0ad60901648be663a710bdadf19e4c10ac6782c235200619158284}"

DRY_RUN=0
COMPOSE_FILES=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) sed -n '2,45p' "$0"; exit 0 ;;
    --) shift; break ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) COMPOSE_FILES+=("$1"); shift ;;
  esac
done
if [ "${#COMPOSE_FILES[@]}" -eq 0 ]; then
  COMPOSE_FILES=(docker-compose.yml docker-compose.override.yml)
fi

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

MARTIN_LOCAL_CONFIG="config/martin-local.yaml"

log() { printf '[bootstrap] %s\n' "$*"; }

command -v docker >/dev/null 2>&1 || { echo "[bootstrap] FATAL: docker が見つからない" >&2; exit 1; }
for f in "${COMPOSE_FILES[@]}"; do
  [ -f "$f" ] || { echo "[bootstrap] FATAL: compose file がない: $f" >&2; exit 1; }
done
[ -f "$MARTIN_LOCAL_CONFIG" ] || { echo "[bootstrap] FATAL: $MARTIN_LOCAL_CONFIG がない" >&2; exit 1; }

COMPOSE_ARGS=()
for f in "${COMPOSE_FILES[@]}"; do COMPOSE_ARGS+=(-f "$f"); done

# ── 1. 対象 named volume 名を解決する（docker compose が付与する project prefix を含む実名） ──
log "compose files: ${COMPOSE_FILES[*]}   project: ${COMPOSE_PROJECT_NAME:-<dir default>}"
CONFIG_JSON="$(docker compose "${COMPOSE_ARGS[@]}" config --format json)"

resolve_volume() {
  # $1 = docker-compose volumes: の key 名。解決後の実 volume 名を返す。
  printf '%s' "$CONFIG_JSON" | python3 -c '
import sys, json
key = sys.argv[1]
cfg = json.load(sys.stdin)
vols = cfg.get("volumes") or {}
v = vols.get(key)
if not v or not v.get("name"):
    sys.stderr.write(
        "[bootstrap] FATAL: volume '%s' が merged compose config に無い。\n"
        "  local runtime profile（override.example.yml の B ブロック）が有効か確認する:\n"
        "    cp docker-compose.override.example.yml docker-compose.override.yml\n" % key
    )
    sys.exit(1)
print(v["name"])
' "$1"
}

DATA_RUNTIME_VOL="$(resolve_volume data-runtime)"
LOGS_VOL="$(resolve_volume data-runtime-logs)"
CACHE_VOL="$(resolve_volume data-runtime-cache)"
log "data-runtime volume : $DATA_RUNTIME_VOL"
log "logs volume         : $LOGS_VOL"
log "cache volume        : $CACHE_VOL"

for v in "$DATA_RUNTIME_VOL" "$LOGS_VOL" "$CACHE_VOL"; do
  if docker volume inspect "$v" >/dev/null 2>&1; then
    log "volume exists: $v"
  elif [ "$DRY_RUN" -eq 1 ]; then
    log "[dry-run] would create volume: $v"
  else
    docker volume create "$v" >/dev/null && log "volume created: $v"
  fi
done

# ── 2. nested mountpoint 一覧を組み立てる ─────────────────────────────────────
# 共有 runtime volume 内に必ず存在させる相対パス。
NESTED_DIRS=(logs cache backend frontend frontend/tiles)
# Martin local config が参照する tile ディレクトリを config から抽出（drift 防止）。
while IFS= read -r p; do
  rel="${p#/data_runtime/}"
  [ -n "$rel" ] && NESTED_DIRS+=("$rel")
done < <(grep -oE '/data_runtime/frontend/tiles/[A-Za-z0-9_/-]+' "$MARTIN_LOCAL_CONFIG" | sort -u)

log "nested mountpoints (${#NESTED_DIRS[@]}): ${NESTED_DIRS[*]}"

# ── 3. helper コンテナ（root）で mkdir + chown/chmod を実行 ───────────────────
MKDIR_LIST=""
for d in "${NESTED_DIRS[@]}"; do MKDIR_LIST="$MKDIR_LIST /data_runtime/$d"; done

# logs/cache child volume の root（コンテナ内 /vol_logs, /vol_cache）と、
# 共有 volume 内の logs/cache mountpoint stub の両方を 10001:10001 / 0750 にする。
CONTAINER_SCRIPT="set -eu
mkdir -p${MKDIR_LIST}
chown ${PUBLIC_UID}:${PUBLIC_GID} /vol_logs /vol_cache /data_runtime/logs /data_runtime/cache
chmod ${CHILD_VOLUME_MODE} /vol_logs /vol_cache /data_runtime/logs /data_runtime/cache
echo '--- verify ---'
for p in /vol_logs /vol_cache; do
  own=\$(stat -c '%u:%g' \"\$p\"); mod=\$(stat -c '%a' \"\$p\")
  echo \"\$p owner=\$own mode=\$mod\"
  [ \"\$own\" = '${PUBLIC_UID}:${PUBLIC_GID}' ] || { echo \"FATAL: \$p owner != ${PUBLIC_UID}:${PUBLIC_GID}\" >&2; exit 1; }
done
# runtime-init 責務の path を作らないことを自己確認（作っていたら異常）
for p in /data_runtime/.publish.lock /data_runtime/.staging /data_runtime/versions; do
  [ ! -e \"\$p\" ] || echo \"note: \$p already exists (runtime-init が既に実行済み。helper は触れていない)\"
done
echo '--- ok ---'"

DOCKER_RUN="docker run --rm --network none \
  --entrypoint sh \
  -v '$DATA_RUNTIME_VOL':/data_runtime \
  -v '$LOGS_VOL':/vol_logs \
  -v '$CACHE_VOL':/vol_cache \
  '$BOOTSTRAP_IMAGE' -c \"\$CONTAINER_SCRIPT\""

if [ "$DRY_RUN" -eq 1 ]; then
  printf '[bootstrap][dry-run] helper container script:\n%s\n' "$CONTAINER_SCRIPT"
  printf '[bootstrap][dry-run] %s\n' "$DOCKER_RUN"
else
  eval "$DOCKER_RUN"
fi

log "done. 次に: docker compose ${COMPOSE_ARGS[*]} up -d"

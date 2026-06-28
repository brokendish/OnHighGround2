#!/usr/bin/env bash
# build_railway_pmtiles.sh — 全国鉄道路線 PMTiles 生成スクリプト
#
# 依存ツール（要インストール）:
#   osmium-tool  : brew install osmium-tool / apt install osmium-tool
#   tippecanoe   : brew install tippecanoe  / apt install tippecanoe (v2.47+)
#   tile-join    : tippecanoe に同梱
#   python3      : フィーチャーフィルタリング用
#
# 入力:
#   $1  : Japan OSM PBF ファイルパス
#          例: data/japan-latest.osm.pbf
#          取得: https://download.geofabrik.de/asia/japan-latest.osm.pbf
#   $2  : 出力ディレクトリ（省略時 frontend/layers/railways）
#
# 出力:
#   ${出力ディレクトリ}/railways_japan.pmtiles
#
# 使用例:
#   bash scripts/tile_build/build_railway_pmtiles.sh data/japan-latest.osm.pbf

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

INPUT_PBF="${1:-${PROJECT_ROOT}/data/japan-latest.osm.pbf}"
OUTPUT_DIR="${2:-${PROJECT_ROOT}/frontend/layers/railways}"
SCRATCH_DIR="$(mktemp -d)"

trap 'rm -rf "${SCRATCH_DIR}"' EXIT

log() { echo "[$(date '+%H:%M:%S')] $*"; }

if [[ ! -f "${INPUT_PBF}" ]]; then
    echo "ERROR: OSM PBF が見つかりません: ${INPUT_PBF}"
    echo ""
    echo "Japan OSM PBF のダウンロード:"
    echo "  curl -L -o data/japan-latest.osm.pbf \\"
    echo "    https://download.geofabrik.de/asia/japan-latest.osm.pbf"
    exit 1
fi

for cmd in osmium tippecanoe tile-join python3; do
    if ! command -v "${cmd}" &>/dev/null; then
        echo "ERROR: ${cmd} が見つかりません"
        case "${cmd}" in
            osmium)   echo "  brew install osmium-tool  / apt install osmium-tool" ;;
            tippecanoe|tile-join) echo "  brew install tippecanoe  / apt install tippecanoe" ;;
        esac
        exit 1
    fi
done

mkdir -p "${OUTPUT_DIR}"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: 路線フィーチャー抽出 (OSM PBF → railways.osm.pbf)
# ─────────────────────────────────────────────────────────────────────────────
log "[1/6] OSM PBF から鉄道路線フィーチャーを抽出中..."
osmium tags-filter "${INPUT_PBF}" \
    "w/railway=rail,subway,light_rail,tram,monorail,narrow_gauge" \
    -o "${SCRATCH_DIR}/railways.osm.pbf" \
    --overwrite

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: 駅フィーチャー抽出 (OSM PBF → stations.osm.pbf)
# ─────────────────────────────────────────────────────────────────────────────
log "[2/6] 駅フィーチャーを抽出中..."
osmium tags-filter "${INPUT_PBF}" \
    "n/railway=station,halt" \
    -o "${SCRATCH_DIR}/stations.osm.pbf" \
    --overwrite

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3: GeoJSON 変換
# ─────────────────────────────────────────────────────────────────────────────
log "[3/6] GeoJSON に変換中..."
osmium export "${SCRATCH_DIR}/railways.osm.pbf" \
    --geometry-types=linestring \
    --attributes=type,id,version,timestamp \
    -f geojson \
    -o "${SCRATCH_DIR}/railways_raw.geojson" \
    --overwrite

osmium export "${SCRATCH_DIR}/stations.osm.pbf" \
    --geometry-types=point \
    --attributes=type,id \
    -f geojson \
    -o "${SCRATCH_DIR}/stations_raw.geojson" \
    --overwrite

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4: フィルタリング（貨物専用・側線・車庫線・工業線を除外）
# ─────────────────────────────────────────────────────────────────────────────
log "[4/6] 不要フィーチャーをフィルタリング中..."

export SCRATCH_DIR_PY="${SCRATCH_DIR}"
python3 - << 'PYTHON'
import json, sys, os

EXCLUDE_SERVICE = {'yard', 'siding', 'spur', 'crossover'}
EXCLUDE_USAGE   = {'industrial'}
EXCLUDE_RAILWAY = {'platform', 'station', 'abandoned', 'disused', 'construction', 'razed'}
KEEP_RAILWAY_ATTRS = {'railway', 'name', 'name:ja', 'name:en', 'ref', 'service', 'usage', 'operator'}
KEEP_STATION_ATTRS = {'railway', 'name', 'name:ja', 'name:en', 'station', 'operator'}

scratch = os.environ.get('SCRATCH_DIR_PY', '/tmp')

def filter_geojson(in_path, out_path, exclude_fn, attr_keys):
    with open(in_path) as f:
        fc = json.load(f)
    kept = []
    for feat in fc.get('features', []):
        props = feat.get('properties') or {}
        if exclude_fn(props):
            continue
        feat['properties'] = {k: v for k, v in props.items() if k in attr_keys}
        kept.append(feat)
    with open(out_path, 'w') as f:
        json.dump({'type': 'FeatureCollection', 'features': kept}, f)
    print(f'  {os.path.basename(in_path)}: {len(fc.get("features", []))} → {len(kept)} features')

def exclude_railway(props):
    if props.get('service', '') in EXCLUDE_SERVICE: return True
    if props.get('usage', '') in EXCLUDE_USAGE: return True
    if props.get('railway', '') in EXCLUDE_RAILWAY: return True
    if not (props.get('name', '') or '').strip(): return True
    return False

def exclude_station(props):
    return not (props.get('name', '') or '').strip()

filter_geojson(f'{scratch}/railways_raw.geojson',  f'{scratch}/railways_filtered.geojson',
               exclude_railway, KEEP_RAILWAY_ATTRS)
filter_geojson(f'{scratch}/stations_raw.geojson', f'{scratch}/stations_filtered.geojson',
               exclude_station, KEEP_STATION_ATTRS)
PYTHON

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5: tippecanoe で個別 PMTiles を生成
# ─────────────────────────────────────────────────────────────────────────────
log "[5/6] tippecanoe で PMTiles を生成中..."

# 路線レイヤー: zoom 5〜14
# - Z5: 日本全体俯瞰用（新幹線・主要幹線が見える程度）
# - Z14: 拡大時の詳細表示
tippecanoe \
    -o "${SCRATCH_DIR}/railways.pmtiles" \
    -Z 5 -z 14 \
    --layer=railways \
    --name="Japan Railways" \
    --description="Japan railway lines from OSM (rail/subway/light_rail/tram/monorail)" \
    --simplification=5 \
    --coalesce-smallest-as-needed \
    --detect-shared-borders \
    --force \
    "${SCRATCH_DIR}/railways_filtered.geojson"

# 駅レイヤー: zoom 9〜14（低ズームでは非表示）
# --drop-rate=1: ズーム別の通常 thinning を止め、z13 でも全駅を保持する
# --no-feature-limit: タイル内フィーチャー数上限による間引きを防ぐ
# --no-tile-size-limit: タイルサイズ超過による間引きを防ぐ
tippecanoe \
    -o "${SCRATCH_DIR}/stations.pmtiles" \
    -Z 9 -z 14 \
    --drop-rate=1 \
    --no-feature-limit \
    --no-tile-size-limit \
    --layer=stations \
    --name="Japan Stations" \
    --description="Japan railway stations from OSM" \
    --force \
    "${SCRATCH_DIR}/stations_filtered.geojson"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6: tile-join でマージ
# ─────────────────────────────────────────────────────────────────────────────
log "[6/6] 路線+駅 PMTiles をマージ中..."
tile-join \
    -o "${OUTPUT_DIR}/railways_japan.pmtiles" \
    --force \
    --no-tile-size-limit \
    "${SCRATCH_DIR}/railways.pmtiles" \
    "${SCRATCH_DIR}/stations.pmtiles"

SIZE=$(du -sh "${OUTPUT_DIR}/railways_japan.pmtiles" | cut -f1)
log "完了: ${OUTPUT_DIR}/railways_japan.pmtiles (${SIZE})"
log ""
log "メタデータ確認 (pmtiles inspect):"
if command -v pmtiles &>/dev/null; then
    pmtiles show "${OUTPUT_DIR}/railways_japan.pmtiles" 2>/dev/null || true
fi

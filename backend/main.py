"""
避難ナビゲーションAPI
標高データを使用して避難目的地を検索し、ルート情報を提供
"""
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import logging
import sys
import os
from pathlib import Path
import csv
import json

import math

from elevation_service import ElevationService
from hazard_service import HazardService, derive_hazard_safe
from geometry_utils import calc_reachable_safe_area, SHAPELY_AVAILABLE
from hazard_engine import HazardEngine
from app.api.hazards import router as hazards_router
from app.api.admin import router as admin_router
from app.api.admin_config import router as admin_config_router
from app.api.admin_datasets import router as admin_datasets_router
from app.api.admin_datasets import jobs_router as admin_jobs_router
from app.api.admin_upload import router as admin_upload_router
from app.api.layer_types_api import router as layer_types_router
from app.api.earthquakes import router as earthquakes_router
from app.api.earthquakes_recent import router as earthquakes_recent_router
from app.api.earthquakes_stream import router as earthquakes_stream_router
from app.api.earthquakes_stream import dev_router as earthquakes_dev_router
from app.api.weather import router as weather_router
from app.api.tsunami import router as tsunami_router
from app.api.astro import router as astro_router
from app.api.tide import router as tide_router
from app.api.navigation import router as navigation_router
from app.services.earthquake_realtime_service import get_realtime_service
from app.services.job_manager import get_job_manager
from app.services.admin_log_service import write_app_log
from app.services.reverse_geocode_service import get_reverse_geocode_service
from app.services.route_risk_scoring import calc_route_risk_score
from app.services.shelter_service import (
    HAZARD_COLUMN_MAP,
    REGION_PATH_MAP,
    _region_from_path,
    parse_float,
    load_emergency_shelters_from_csv,
    load_emergency_shelters_from_geojson,
    load_emergency_shelters,
    get_shelter_registry,
)

# 設定ファイル読み込み
BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "app.properties"


def load_properties(config_path: Path) -> dict:
    """Java .properties 形式の設定ファイルを読み込む"""
    properties = {}

    if not config_path.exists():
        return properties

    with config_path.open("r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            properties[key.strip()] = value.strip()

    return properties


def parse_bool(value: str, default: bool) -> bool:
    """文字列設定値をboolへ変換"""
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in ("true", "1", "yes", "on"):
        return True
    if normalized in ("false", "0", "no", "off"):
        return False
    return default


def parse_csv(value: str, default: List[str]) -> List[str]:
    """カンマ区切り設定値を配列へ変換"""
    if value is None:
        return default

    items = [item.strip() for item in value.split(",") if item.strip()]
    return items if items else default


raw_config_path = Path(os.getenv("APP_PROPERTIES_FILE", str(DEFAULT_CONFIG_PATH)))
if not raw_config_path.is_absolute():
    raw_config_path = BASE_DIR / raw_config_path
CONFIG_PATH = raw_config_path.resolve()
APP_CONFIG = load_properties(CONFIG_PATH)

LOG_LEVEL = APP_CONFIG.get("log.level", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

logger.info("OnHighGround2 backend starting")
logger.info("LOG_LEVEL=%s  config=%s", LOG_LEVEL, CONFIG_PATH)
logger.info("runtime path=%s", (BASE_DIR.parent / "data_runtime").resolve())
logger.info("fallback path=%s  (data_lake)", (BASE_DIR.parent / "data_lake").resolve())
if SHAPELY_AVAILABLE:
    logger.info("RSA: shapely/pyproj available — RSA calculation enabled")
else:
    logger.warning("RSA: shapely/pyproj not available — RSA calculation disabled")


def resolve_existing_path(path_value: str, legacy_candidates: List[Path], label: str = "") -> Path:
    """正本候補を優先しつつ、移行期間は legacy をフォールバックにする。

    採用パスは INFO（runtime / primary）または WARNING（fallback）でログに出す。
    """
    _label = label or "data path"
    path = Path(path_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    resolved = path.resolve()
    if resolved.exists():
        if "data_runtime" in str(resolved):
            logger.info("%s loaded from runtime: %s", _label, resolved)
        elif "data_lake" in str(resolved):
            logger.warning("%s fallback to data_lake: %s", _label, resolved)
        else:
            logger.warning("%s fallback to legacy: %s", _label, resolved)
        return resolved

    for candidate in legacy_candidates:
        legacy_path = candidate.resolve()
        if legacy_path.exists():
            if "data_lake" in str(legacy_path):
                logger.warning("%s fallback to data_lake: %s", _label, legacy_path)
            else:
                logger.warning("%s fallback to legacy: %s", _label, legacy_path)
            return legacy_path

    logger.warning("%s: no valid path found, using (may not exist): %s", _label, resolved)
    return resolved


def meters_to_lat_degrees(meters: float) -> float:
    """メートルを緯度方向のおおよその度数へ変換"""
    return meters / 111_320.0

# FastAPIアプリケーション初期化
app = FastAPI(
    title="避難ナビゲーションAPI",
    description="津波・高潮・洪水からの避難経路を提供するAPI",
    version="1.0.0"
)

# CORS設定（フロントエンドからのアクセスを許可）
CORS_ALLOW_ORIGINS = parse_csv(APP_CONFIG.get("cors.allow_origins"), ["*"])
CORS_ALLOW_METHODS = parse_csv(APP_CONFIG.get("cors.allow_methods"), ["*"])
CORS_ALLOW_HEADERS = parse_csv(APP_CONFIG.get("cors.allow_headers"), ["*"])
CORS_ALLOW_CREDENTIALS = parse_bool(
    APP_CONFIG.get("cors.allow_credentials"),
    True
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=CORS_ALLOW_HEADERS,
)
app.include_router(hazards_router)
app.include_router(admin_router)
app.include_router(admin_config_router)
app.include_router(admin_datasets_router)
app.include_router(admin_jobs_router)
app.include_router(admin_upload_router)
app.include_router(layer_types_router)
app.include_router(earthquakes_router)
app.include_router(earthquakes_recent_router)
app.include_router(earthquakes_stream_router)
app.include_router(earthquakes_dev_router)
app.include_router(weather_router)
app.include_router(tsunami_router)
app.include_router(astro_router)
app.include_router(tide_router)
app.include_router(navigation_router)


@app.on_event("startup")
async def _startup():
    """起動時: ジョブリセット + 地震リアルタイムサービス起動。"""
    try:
        write_app_log("backend startup")
    except Exception:
        pass
    get_job_manager().cleanup_stale_running()
    try:
        get_realtime_service().start()
    except Exception as exc:
        logger.error("EarthquakeRealtimeService start failed (non-fatal): %s", exc)


@app.on_event("shutdown")
async def _shutdown():
    """シャットダウン時のログ。ExitCode:0 の原因追跡用。"""
    import signal as _signal
    import sys as _sys

    # 現在処理中のシグナルを best-effort で取得（Python 3.8+ では signal.SIGTERM 等を参照できる）
    frame = _sys._getframe(1) if hasattr(_sys, "_getframe") else None
    frame_info = f"{frame.f_code.co_filename}:{frame.f_lineno}" if frame else "unknown"

    logger.warning(
        "backend shutdown initiated"
        " — this log appears on normal SIGTERM/SIGINT as well as unexpected exits."
        " If a job was running, check boot_state.json for restart details."
        " caller_frame=%s",
        frame_info,
    )
    logger.warning(
        "shutdown: pid=%d  python=%s",
        os.getpid(),
        _sys.version.split()[0],
    )
    try:
        await get_realtime_service().stop()
    except Exception as exc:
        logger.warning("EarthquakeRealtimeService stop failed: %s", exc)
    try:
        write_app_log("backend shutdown", level="WARNING")
    except Exception:
        pass

# 標高サービスの初期化
# [Phase 1] data_runtime/backend/elevation/ を優先参照。
# data_runtime にデータが無い場合は data_lake/validated/ → legacy へフォールバック。
# deploy_to_runtime.sh を実行することで data_runtime が整備される。
dem_path_value = APP_CONFIG.get("dem.path", "../data_runtime/backend/elevation/elevation.tif")
dem_path = resolve_existing_path(
    dem_path_value,
    legacy_candidates=[
        BASE_DIR.parent / "data_lake" / "validated" / "tokyo" / "dem" / "elevation.tif",
        BASE_DIR.parent / "data" / "elevation.tif",
        BASE_DIR / "elevation.tif",
    ],
    label="DEM",
)
DEM_PATH = str(dem_path)
elevation_service = ElevationService(DEM_PATH)


def parse_shelter_paths(path_config: Optional[str]) -> List[Path]:
    """避難場所データの設定値をPath配列へ変換。

    [Phase 2] 参照優先順位:
      1. data_runtime/backend/shelters/  (runtime 優先)
      2. data_lake/validated/tokyo/shelter  (data_lake fallback)
      3. 国土地理院避難所データ  (legacy fallback)
    """
    runtime_path = BASE_DIR.parent / "data_runtime" / "backend" / "shelters"
    default_path = BASE_DIR.parent / "data_lake" / "validated" / "tokyo" / "shelter"
    legacy_default_path = BASE_DIR.parent / "国土地理院避難所データ" / "東京" / "13000_2" / "13000_2.csv"

    if not path_config:
        # config 未指定時は runtime → data_lake → legacy の順で探す
        runtime_files = list(runtime_path.rglob("*.geojson")) + list(runtime_path.rglob("*.csv")) if runtime_path.exists() else []
        if runtime_files:
            logger.info("Shelter loaded from runtime: %s", runtime_path)
            return [runtime_path]
        if default_path.exists():
            logger.warning("Shelter fallback to data_lake: %s", default_path)
            return [default_path]
        logger.warning("Shelter fallback to legacy: %s", legacy_default_path)
        return [legacy_default_path]

    result: List[Path] = []
    for raw_item in path_config.split(","):
        item = raw_item.strip()
        if not item:
            continue
        path = Path(item)
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()

        if path.exists():
            if "data_runtime" in str(path):
                logger.info("Shelter loaded from runtime: %s", path)
            elif "data_lake" in str(path):
                logger.warning("Shelter fallback to data_lake: %s", path)
            else:
                logger.warning("Shelter fallback to legacy: %s", path)
            result.append(path)
            continue

        # 指定パスが見つからない場合の fallback
        if "data_runtime" in str(path) and default_path.exists():
            logger.warning("Shelter: runtime path not found (%s) — fallback to data_lake: %s", path, default_path)
            result.append(default_path)
            continue
        if "data_lake" in str(path) and legacy_default_path.exists():
            logger.warning("Shelter fallback to legacy: %s", legacy_default_path)
            result.append(legacy_default_path)
            continue

        result.append(path)

    if result:
        return result
    runtime_files = list(runtime_path.rglob("*.geojson")) + list(runtime_path.rglob("*.csv")) if runtime_path.exists() else []
    if runtime_files:
        return [runtime_path]
    return [default_path] if default_path.exists() else [legacy_default_path]


# 起動時にキャッシュをウォームアップ（初回リクエスト遅延を防ぐ）
_shelter_registry = get_shelter_registry()
logger.info("ShelterRegistry initialized — warming up cache")
_initial_shelters = _shelter_registry.get_shelters()
logger.info("Shelter data sources (initial): %d shelters loaded", len(_initial_shelters))
del _initial_shelters  # 参照を解放（registry が保持するため不要）

# ハザードサービスの初期化
try:
    FLOOD_PROXIMITY_BUFFER_M = float(
        APP_CONFIG.get("hazard.flood.proximity_buffer_m", "25")
    )
except (TypeError, ValueError):
    FLOOD_PROXIMITY_BUFFER_M = 25.0

hazard_service = HazardService(
    flood_proximity_buffer_deg=meters_to_lat_degrees(FLOOD_PROXIMITY_BUFFER_M)
)

FLOOD_ENABLED = parse_bool(APP_CONFIG.get("hazard.flood.enabled", "false"), False)
if FLOOD_ENABLED:
    # [Phase 2] data_runtime/backend/hazard/flood/ 内の全 *.geojsonl を順次ロード。
    # 複数地域ファイル（tokyo_flood_check.geojsonl / kanagawa_flood_check.geojsonl 等）を
    # 自動認識する。ファイルが存在しない場合は data_lake/normalized/ へフォールバック。
    _flood_runtime_dir = BASE_DIR.parent / "data_runtime" / "backend" / "hazard" / "flood"
    _flood_geojsonl_files: list[Path] = []
    if _flood_runtime_dir.is_dir():
        _flood_geojsonl_files = sorted(_flood_runtime_dir.glob("*.geojsonl"))

    if _flood_geojsonl_files:
        for _f in _flood_geojsonl_files:
            logger.info("Flood check loaded from runtime: %s", _f)
            hazard_service.load_geojsonl("flood", _f, bbox_only=True)
    else:
        # フォールバック: 設定ファイル指定の単一パス（backward compat）
        _flood_check_path_value = APP_CONFIG.get(
            "hazard.flood.check_path",
            "../data_runtime/backend/hazard/flood/tokyo_flood_check.geojsonl",
        )
        _flood_check_path = resolve_existing_path(
            _flood_check_path_value,
            legacy_candidates=[
                BASE_DIR.parent / "data_lake" / "normalized" / "tokyo" / "flood" / "tokyo_flood_check.geojsonl",
            ],
            label="Flood",
        )
        hazard_service.load_geojsonl("flood", _flood_check_path, bbox_only=True)
else:
    logger.info("洪水ハザード判定は無効（hazard.flood.enabled=false）")

# storm_surge: 高潮浸水想定区域
# [Phase 2] data_runtime/backend/hazard/storm_surge/ 内の全 *.geojson を順次ロード。
# 複数地域ファイル（tokyo_storm_surge.geojson / kanagawa_storm_surge.geojson 等）を自動認識。
# ファイルが存在しない場合は data_lake/normalized/ へフォールバック（東京のみ）。
_storm_surge_runtime_dir = BASE_DIR.parent / "data_runtime" / "backend" / "hazard" / "storm_surge"
_storm_surge_geojson_files: list[Path] = []
if _storm_surge_runtime_dir.is_dir():
    _storm_surge_geojson_files = sorted(_storm_surge_runtime_dir.glob("*.geojson"))

if _storm_surge_geojson_files:
    for _f in _storm_surge_geojson_files:
        logger.info("StormSurge loaded from runtime: %s", _f)
        hazard_service.load("storm_surge", _f, bbox_only=True)
else:
    # フォールバック: 設定ファイル指定の単一パス（backward compat）
    _storm_surge_path_value = APP_CONFIG.get(
        "hazard.storm_surge.path",
        "../data_runtime/backend/hazard/storm_surge/tokyo_storm_surge.geojson",
    )
    _storm_surge_path = resolve_existing_path(
        _storm_surge_path_value,
        legacy_candidates=[
            BASE_DIR.parent / "data_lake" / "normalized" / "tokyo" / "storm_surge" / "tokyo_storm_surge.geojson",
        ],
        label="StormSurge",
    )
    hazard_service.load("storm_surge", _storm_surge_path, bbox_only=True)

# tsunami: targets 設定に従ってファイルを個別ロード
# デフォルト: tokyo のみ（東京版 v1 標準モード）
# 広域モード: hazard.tsunami.targets=tokyo,kanagawa,chiba
#
# [Phase 1] 参照優先順位:
#   1. data_runtime/backend/hazard/tsunami/  (runtime 優先)
#   2. data_lake/validated/tokyo/tsunami/    (validated 正本)
#   3. data_lake/normalized/tokyo/tsunami/   (normalized フォールバック)
_tsunami_dir_value = APP_CONFIG.get(
    "hazard.tsunami.dir",
    "../data_lake/normalized/tokyo/tsunami",
)
_tsunami_dir = Path(_tsunami_dir_value)
if not _tsunami_dir.is_absolute():
    _tsunami_dir = (BASE_DIR / _tsunami_dir).resolve()

_tsunami_runtime_dir = BASE_DIR.parent / "data_runtime" / "backend" / "hazard" / "tsunami"
_tsunami_validated_dir = BASE_DIR.parent / "data_lake" / "validated" / "tokyo" / "tsunami"
_tsunami_targets = parse_csv(APP_CONFIG.get("hazard.tsunami.targets", "tokyo"), ["tokyo"])

logger.info("Loading tsunami hazard targets: %s", ", ".join(_tsunami_targets))

for _target in _tsunami_targets:
    _filename = f"tsunami_{_target}.geojson"
    _runtime_path = _tsunami_runtime_dir / _filename
    _validated_path = _tsunami_validated_dir / _filename
    _normalized_path = _tsunami_dir / _filename
    if _runtime_path.exists():
        logger.info("Tsunami loaded from runtime: %s", _runtime_path)
        hazard_service.load("tsunami", _runtime_path, bbox_only=True)
    elif _validated_path.exists():
        logger.warning("Tsunami fallback to data_lake: %s", _validated_path)
        hazard_service.load("tsunami", _validated_path, bbox_only=True)
    elif _normalized_path.exists():
        logger.warning("Tsunami fallback to data_lake: %s", _normalized_path)
        hazard_service.load("tsunami", _normalized_path, bbox_only=True)
    else:
        logger.warning(
            "Tsunami file not found for target '%s': checked runtime=%s, validated=%s, normalized=%s — skipped",
            _target, _runtime_path, _validated_path, _normalized_path,
        )

# 設定上期待する tsunami targets を hazard_service に登録する（degraded 検出用）。
# 欠落ターゲットがある場合、assess_candidate() が tsunami を "unknown" に倒す。
hazard_service.set_expected_tsunami_sources(_tsunami_targets)
_missing = hazard_service.get_missing_tsunami_sources()
if _missing:
    logger.warning(
        "DEGRADED: tsunami coverage incomplete — missing sources: %s "
        "→ tsunami will be assessed as 'unknown' for all candidates",
        _missing,
    )
else:
    logger.info("Tsunami coverage OK: all configured targets loaded: %s", _tsunami_targets)

# inland_flood: 内水氾濫想定
# [Phase 4] data_runtime/backend/hazard/inland_flood/ 内の全 *.geojson を順次ロード。
# 複数地域ファイルを自動認識。未整備の場合は data_lake/normalized/ → data/hazard/ へフォールバック。
INLAND_FLOOD_ENABLED = parse_bool(APP_CONFIG.get("hazard.inland_flood.enabled", "true"), True)
if INLAND_FLOOD_ENABLED:
    _inland_flood_runtime_dir = BASE_DIR.parent / "data_runtime" / "backend" / "hazard" / "inland_flood"
    _inland_flood_geojson_files: list[Path] = []
    if _inland_flood_runtime_dir.is_dir():
        # rglob でサブディレクトリ（{region}/）内のファイルも含めてスキャン
        _inland_flood_geojson_files = sorted(_inland_flood_runtime_dir.rglob("*.geojson"))

    if _inland_flood_geojson_files:
        for _f in _inland_flood_geojson_files:
            logger.info("InlandFlood loaded from runtime: %s", _f)
            hazard_service.load("inland_flood", _f)
    else:
        # フォールバック: 設定ファイル指定の単一パス（backward compat）
        _inland_flood_path_value = APP_CONFIG.get(
            "hazard.inland_flood.path",
            "../data_runtime/backend/hazard/inland_flood/inland_flood_sample.geojson",
        )
        _inland_flood_path = resolve_existing_path(
            _inland_flood_path_value,
            legacy_candidates=[
                BASE_DIR.parent / "data_lake" / "normalized" / "tokyo" / "inland_flood" / "inland_flood_sample.geojson",
                BASE_DIR.parent / "data" / "hazard" / "inland_flood_sample.geojson",
            ],
            label="InlandFlood",
        )
        if _inland_flood_path.exists():
            hazard_service.load("inland_flood", _inland_flood_path)
        else:
            logger.info("内水氾濫データが見つかりません（スキップ）: %s", _inland_flood_path)
else:
    logger.info("内水氾濫ハザード判定は無効（hazard.inland_flood.enabled=false）")

# landslide: 土砂災害警戒区域
# [Phase 5] data_runtime/backend/hazard/landslide/ 内の全 *.geojson を順次ロード。
# 複数地域ファイルを自動認識。未整備の場合は data_lake/normalized/ → data/hazard/ へフォールバック。
# 正規化: python scripts/normalize/normalize_landslide.py
LANDSLIDE_ENABLED = parse_bool(APP_CONFIG.get("hazard.landslide.enabled", "true"), True)
if LANDSLIDE_ENABLED:
    _landslide_runtime_dir = BASE_DIR.parent / "data_runtime" / "backend" / "hazard" / "landslide"
    _landslide_geojson_files: list[Path] = []
    if _landslide_runtime_dir.is_dir():
        # rglob でサブディレクトリ（{region}/）内のファイルも含めてスキャン
        _landslide_geojson_files = sorted(_landslide_runtime_dir.rglob("*.geojson"))

    if _landslide_geojson_files:
        for _f in _landslide_geojson_files:
            logger.info("Landslide loaded from runtime: %s", _f)
            hazard_service.load("landslide", _f, bbox_only=True)
    else:
        # フォールバック: 設定ファイル指定の単一パス（backward compat）
        _landslide_path_value = APP_CONFIG.get(
            "hazard.landslide.path",
            "../data_runtime/backend/hazard/landslide/tokyo_landslide_A33.geojson",
        )
        _landslide_path = resolve_existing_path(
            _landslide_path_value,
            legacy_candidates=[
                BASE_DIR.parent / "data_lake" / "normalized" / "tokyo" / "landslide" / "tokyo_landslide_A33.geojson",
                BASE_DIR.parent / "data" / "hazard" / "landslide_sample.geojson",
            ],
            label="Landslide",
        )
        if _landslide_path.exists():
            hazard_service.load("landslide", _landslide_path, bbox_only=True)
        else:
            logger.info("土砂災害データが見つかりません（スキップ）: %s", _landslide_path)
else:
    logger.info("土砂災害ハザード判定は無効（hazard.landslide.enabled=false）")

# ── 低地・排水困難エリア ─────────────────────────────────────────────────────
# 地形的リスク（補助ハザード）。is_danger には影響しない（SUPPLEMENTARY_HAZARD_TYPES 参照）。
_lowland_enabled = parse_bool(APP_CONFIG.get("hazard.lowland_poor_drainage.enabled"), True)
if _lowland_enabled:
    _lowland_runtime_dir = BASE_DIR.parent / "data_runtime" / "backend" / "hazard" / "lowland_poor_drainage"
    _lowland_geojson_files: list = []
    if _lowland_runtime_dir.is_dir():
        _lowland_geojson_files = sorted(_lowland_runtime_dir.rglob("*.geojson"))

    if _lowland_geojson_files:
        for _f in _lowland_geojson_files:
            logger.info("LowlandPoorDrainage loaded from runtime: %s", _f)
            hazard_service.load("lowland_poor_drainage", _f, bbox_only=True)
    else:
        for _region in ("tokyo", "kanagawa"):
            _validated_dir = BASE_DIR.parent / "data_lake" / "validated" / _region / "lowland_poor_drainage"
            _lowland_files = sorted(_validated_dir.glob("*.geojson")) if _validated_dir.is_dir() else []
            if _lowland_files:
                _lowland_path = _lowland_files[0]
                logger.info("LowlandPoorDrainage loaded from validated (%s): %s", _region, _lowland_path)
                hazard_service.load("lowland_poor_drainage", _lowland_path, bbox_only=True)
            else:
                logger.info("低地データが見つかりません（スキップ）: %s", _validated_dir)

    from app.services.hazard_runtime_service import set_hazard_service as _set_hs
    _set_hs(hazard_service)
    logger.info("hazard_runtime_service: HazardService 登録完了")
else:
    logger.info("低地・排水困難エリア判定は無効（hazard.lowland_poor_drainage.enabled=false）")

# APIサーバー設定
API_HOST = APP_CONFIG.get("api.host", "0.0.0.0")
try:
    API_PORT = int(APP_CONFIG.get("api.port", "8000"))
except ValueError:
    API_PORT = 8000
API_RELOAD = parse_bool(APP_CONFIG.get("api.reload"), False)
API_LOG_LEVEL = APP_CONFIG.get("api.log_level", "info").lower()


# リクエスト/レスポンスモデル
class CurrentLocation(BaseModel):
    """現在地情報"""
    lat: float = Field(..., description="緯度", ge=-90, le=90)
    lon: float = Field(..., description="経度", ge=-180, le=180)


class EvacuationRequest(BaseModel):
    """避難目的地検索リクエスト"""
    lat: float = Field(..., description="現在地の緯度", ge=-90, le=90)
    lon: float = Field(..., description="現在地の経度", ge=-180, le=180)
    transport_mode: str = Field(
        default="walking", 
        description="移動手段 (walking/driving)"
    )
    max_distance: float = Field(
        default=2000.0, 
        description="最大移動距離（メートル）",
        gt=0,
        le=10000
    )
    min_elevation_gain: float = Field(
        default=10.0,
        description="最低必要標高差（メートル）",
        gt=0
    )


class EvacuationDestination(BaseModel):
    """避難目的地"""
    name: str
    type: str
    lat: float
    lon: float
    elevation: float
    elevation_gain: float
    distance: float
    estimated_time_minutes: float
    safety_score: float
    hazard_safe: Optional[bool]           # null = データ未ロードで判定不能
    hazard_assessment: Optional[Dict[str, str]] = None  # {"flood": "inside"|"outside"|"unknown"}


class HazardStatus(BaseModel):
    """現在地のハザード状況"""
    is_danger: bool
    hazards: List[str]


class RecommendedDestination(BaseModel):
    """推奨避難先（destinations[0] に reason を付与）"""
    name: str
    type: str
    lat: float
    lon: float
    elevation: float
    elevation_gain: float
    distance: float
    estimated_time_minutes: float
    safety_score: float
    hazard_safe: Optional[bool]           # null = データ未ロードで判定不能
    hazard_assessment: Optional[Dict[str, str]] = None
    reason: str


class RouteRiskRequest(BaseModel):
    """ルート危険度評価リクエスト"""
    coordinates: List[List[float]] = Field(
        ...,
        description="ルート座標列 [[lat, lon], ...] (2点以上)"
    )
    sample_count: int = Field(default=40, ge=5, le=100, description="サンプリング点数")


class ElevationProfileRequest(BaseModel):
    """標高プロファイル取得リクエスト"""
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    num_points: int = Field(default=50, ge=10, le=200)


class ReverseGeocodeResponse(BaseModel):
    address: Optional[str] = None
    postcode: Optional[str] = None
    source: str
    lat: float
    lon: float


# ------------------------------------------------------------------
# 避難目的地検索ヘルパー
# ------------------------------------------------------------------

def _calc_estimated_time(distance: float, transport_mode: str) -> float:
    """移動距離と手段から所要時間（分）を計算"""
    time_factor = 1.0 if transport_mode == "driving" else 1.5
    return (distance / 1000.0) * time_factor * 15


# hazard_safe ごとのスコア減点値
# 基礎スコア上限 100pt: False は確実に True 候補より下位、None は中間に置く
HAZARD_UNSAFE_PENALTY = 100.0    # hazard_safe=False: 危険確定
HAZARD_UNKNOWN_PENALTY = 20.0    # hazard_safe=None:  未判定（やや不利）

# 危険区域内候補（hazard_safe=False）を候補一覧から完全除外するかどうか
# false（デフォルト）: 大幅減点して残す（全候補が危険な場合の fallback を確保）
# true: 除外（安全性を最優先。全候補が危険な場合のみ fallback として残す）
EXCLUDE_UNSAFE_CANDIDATES: bool = parse_bool(
    APP_CONFIG.get("evacuation.exclude_unsafe_candidates"), False
)

# ── Time Margin 設定 ──────────────────────────────────────────────────
# Time Margin = 津波到達時間(TTI) - 避難所到達時間(ET)
# v1 対象: tsunami のみ。flood は今後。
ENABLE_TIME_MARGIN: bool = parse_bool(
    APP_CONFIG.get("evacuation.enable_time_margin"), True
)
try:
    TSUNAMI_SPEED_KMH: float = float(APP_CONFIG.get("evacuation.tsunami_speed_kmh", "30"))
except (TypeError, ValueError):
    TSUNAMI_SPEED_KMH = 30.0

# ── Reachable Safe Area (RSA) 設定 ──────────────────────────────────────────
ENABLE_RSA: bool = parse_bool(
    APP_CONFIG.get("evacuation.enable_reachable_safe_area"), True
)
try:
    WALKING_SPEED_MPS: float = float(APP_CONFIG.get("evacuation.walking_speed_mps", "1.3"))
except (TypeError, ValueError):
    WALKING_SPEED_MPS = 1.3

logger.info("RSA: enabled=%s walking_speed=%.1fm/s", ENABLE_RSA, WALKING_SPEED_MPS)

# ── Hazard Engine 初期化 ─────────────────────────────────────────────────────
hazard_engine = HazardEngine(
    hazard_service=hazard_service,
    enable_time_margin=ENABLE_TIME_MARGIN,
    tsunami_speed_kmh=TSUNAMI_SPEED_KMH,
)

# Time Margin スコア補正値（既存の hazard_safe 補正に加算）
TIME_MARGIN_SAFE_BONUS    =  20.0   # margin >= 5 min: 余裕あり → ボーナス
TIME_MARGIN_TIGHT_BONUS   =   0.0   # 0 <= margin < 5 min: ギリギリ → 中立
TIME_MARGIN_DANGER_PENALTY=  80.0   # margin < 0 min: 間に合わない → 大幅減点
TIME_MARGIN_UNKNOWN_PENALTY=  10.0  # TTI 算定不能 → 軽微減点


def _calc_rsa(user_lat: float, user_lon: float, tti_minutes: float) -> dict:
    """
    Reachable Safe Area を計算する。

    Args:
        user_lat: ユーザー緯度
        user_lon: ユーザー経度
        tti_minutes: 津波到達時間（分）— 到達可能半径の計算に使用

    Returns:
        {
            "enabled": bool,
            "radius_m": float,
            "time_to_impact_minutes": float,
            "walking_speed_mps": float,
            "area_m2": float,
            "exists": bool,
            "geometry": dict | None
        }
    """
    radius_m = WALKING_SPEED_MPS * tti_minutes * 60.0
    result = calc_reachable_safe_area(
        user_lat=user_lat,
        user_lon=user_lon,
        radius_m=radius_m,
        hazard_polygon_store=hazard_engine.get_polygon_store(),
    )
    logger.info(
        "RSA generated: radius_m=%.0f area_m2=%.0f exists=%s",
        result["radius_m"], result["area_m2"] or 0, result["exists"],
    )
    return {
        "enabled": True,
        "computed": True,
        "status": "computed",
        "reason": None,
        "radius_m": result["radius_m"],
        "time_to_impact_minutes": round(tti_minutes, 1),
        "walking_speed_mps": WALKING_SPEED_MPS,
        "area_m2": result["area_m2"],
        "exists": result["exists"],
        "geometry": result.get("geometry"),
    }


def _classify_time_margin(time_margin: Optional[float]) -> str:
    """time_margin_minutes から time_margin_status を決定する。"""
    if time_margin is None:
        return "unknown"
    if time_margin >= 5.0:
        return "safe"
    if time_margin >= 0.0:
        return "tight"
    return "danger"


def _time_margin_score_bonus(status: str) -> float:
    """time_margin_status からスコア補正値を返す（正 = ボーナス、負 = ペナルティ）。"""
    if status == "safe":
        return TIME_MARGIN_SAFE_BONUS
    if status == "tight":
        return TIME_MARGIN_TIGHT_BONUS
    if status == "danger":
        return -TIME_MARGIN_DANGER_PENALTY
    return -TIME_MARGIN_UNKNOWN_PENALTY  # "unknown"


def _calc_severity_penalty(assessment: Dict[str, Any]) -> float:
    """
    inland_flood / landslide の severity レベルに基づく追加ペナルティ。

    hazard_safe=False による既存ペナルティに加算し、
    同じ「危険区域内」でも重症度によってスコアを差別化する。

    level penalties:
        critical → -50pt
        danger   → -20pt
        caution / safe → 0pt
    """
    penalty = 0.0
    for v in assessment.values():
        if not isinstance(v, dict):
            continue
        if v.get("status") != "inside":
            continue
        level = v.get("level", "")
        if level == "critical":
            penalty += 50.0
        elif level == "danger":
            penalty += 20.0
    return penalty


def _calc_safety_score(
    elevation_gain: float,
    distance: float,
    max_distance: float,
    hazard_safe: Optional[bool],
    time_margin_status: str = "unknown",
    severity_penalty: float = 0.0,
) -> float:
    """
    安全性スコア計算 (基礎 0-100、hazard_safe + time_margin + severity に応じて補正)。

    - elevation_score:    標高差が 30m 以上で満点 50pt
    - distance_score:     距離が短いほど高スコア、max_distance で 0pt
    - hazard penalty:
        True  → 0pt    (安全確定)
        None  → -20pt  (未判定)
        False → -100pt (危険確定、安全候補を必ず上位にする)
    - time_margin bonus:
        safe    → +20pt  (余裕あり)
        tight   →   0pt  (ギリギリ・中立)
        danger  → -80pt  (間に合わない)
        unknown → -10pt  (算定不能・軽微減点)
    - severity_penalty:  inland_flood / landslide の危険度による追加減点
        critical → -50pt
        danger   → -20pt
    """
    elevation_score = min(elevation_gain / 30.0 * 50, 50)
    # distance_score は固定基準距離で正規化する。
    # max_distance を使うと、スライダーを広げるたびに既存候補のスコアが変わり
    # 単調増加性（results(2km) ⊆ results(3km)）が崩れるため固定値を使用する。
    _DIST_SCORE_REF = 5000.0  # スライダー最大10kmの中間値（固定）
    distance_score = max(50 - (distance / _DIST_SCORE_REF * 50), 0)
    base_score = elevation_score + distance_score
    if hazard_safe is True:
        penalty = 0.0
    elif hazard_safe is False:
        penalty = HAZARD_UNSAFE_PENALTY
    else:
        penalty = HAZARD_UNKNOWN_PENALTY
    time_bonus = _time_margin_score_bonus(time_margin_status)
    return base_score - penalty - severity_penalty + time_bonus


def _select_recommended(candidates: List[Dict[str, Any]]) -> tuple:
    """
    推奨候補を選定する。

    優先順位:
      1. hazard_safe=True  (安全確定) → safety_score 最大
      2. hazard_safe=None  (未判定)   → safety_score 最大  ← True が 0件の場合
      3. hazard_safe=False (危険確定) → safety_score 最大  ← True/None が 0件の場合

    Returns:
        (recommended_candidate, selected_tier: str, safe_count: int)
        selected_tier: "safe" | "unknown" | "unsafe"
    """
    safe_candidates = [c for c in candidates if c["hazard_safe"] is True]
    if safe_candidates:
        best = max(safe_candidates, key=lambda x: x["safety_score"])
        return best, "safe", len(safe_candidates)

    unknown_candidates = [c for c in candidates if c["hazard_safe"] is None]
    if unknown_candidates:
        best = max(unknown_candidates, key=lambda x: x["safety_score"])
        return best, "unknown", 0

    best = max(candidates, key=lambda x: x["safety_score"])
    return best, "unsafe", 0


def _build_reason(
    dest: dict,
    selected_tier: str,
    time_margin_status: str = "unknown",
) -> str:
    """
    推奨理由の文字列を組み立てる。

    selected_tier:
      "safe"    → ハザード判定上安全な候補から選定
      "unknown" → 安全候補ゼロのため未判定候補から選定
      "unsafe"  → 安全・未判定ともにゼロのため危険区域内候補から選定（fallback）

    time_margin_status:
      "safe"    → 津波到達まで余裕あり
      "tight"   → ギリギリ間に合う可能性、迅速な行動が必要
      "danger"  → 現在の移動時間では間に合わない可能性
      "unknown" → TTI 算定不能（津波ポリゴン外 or データなし）
    """
    gain = dest["elevation_gain"]
    dist = dest["distance"]

    # Time margin の付記文（status ごと）
    time_notes = {
        "safe":    "津波到達までの余裕時間が十分ある",
        "tight":   "到達は可能だが余裕時間は限定的、迅速な避難が必要",
        "danger":  "現在の移動時間では津波到達に間に合わない可能性がある",
    }
    time_note = time_notes.get(time_margin_status)  # "unknown" → None

    if selected_tier == "safe":
        parts = ["危険区域外で、ハザード判定上安全な候補"]
        if gain >= 10:
            parts.append(f"現在地より{gain:.0f}m高い")
        if dist <= 1000:
            parts.append("徒歩10分圏内")
        parts.append("標高差と到達性のバランスが最も良い地点")
        if time_note:
            parts.append(time_note)
        return "、".join(parts)

    if selected_tier == "unknown":
        parts = [
            "ハザード判定で安全な候補が見つからなかった",
            "安全性は未判定だが到達可能性と標高差が最も良い候補",
        ]
        if gain >= 10:
            parts.append(f"現在地より{gain:.0f}m高い")
        parts.append("利用可能なハザードデータでは判定不能のため注意が必要")
        if time_note:
            parts.append(time_note)
        return "、".join(parts)

    # selected_tier == "unsafe"
    base = (
        "安全候補・未判定候補が見つからなかった。"
        f"危険区域内を含む候補の中で標高差（現在地より{gain:.0f}m高い）と"
        "到達性を基準に選択した（十分な注意が必要）"
    )
    if time_note:
        base += f"。{time_note}"
    return base


def search_shelter_destinations(
    current_lat: float,
    current_lon: float,
    current_elevation: float,
    shelters: List[Dict[str, Any]],
    elev_service: ElevationService,
    haz_service: HazardService,
    min_elevation_gain: float,
    max_distance: float,
    transport_mode: str,
    tti_minutes: Optional[float] = None,
    active_hazards: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    避難所ベースで避難候補を検索する。

    各避難所に対して:
    - 距離フィルタ
    - DEM から標高取得・標高差フィルタ
    - 安全性スコア算出（hazard_safe + time_margin 補正）
    - ハザード安全判定
    - ハザード適合ボーナス（shelter.hazard_types が active_hazards と合致する場合）

    Args:
        tti_minutes: 現在地の津波到達時間（分）。None = 算定不能。
        active_hazards: 現在地で発生中のハザードキー一覧（例: ["tsunami"]）。
                        shelter.hazard_types と照合してスコアを加算する。

    Returns:
        安全性スコア降順で最大15件
    """
    # 粗フィルタ用マージン（max_distance の 1.2倍）
    lat_per_meter = 1.0 / 111000.0
    lon_per_meter = 1.0 / (111000.0 * math.cos(math.radians(current_lat)))
    lat_margin = max_distance * lat_per_meter * 1.2
    lon_margin = max_distance * lon_per_meter * 1.2

    candidates: List[Dict[str, Any]] = []

    for shelter in shelters:
        slat = shelter["lat"]
        slon = shelter["lon"]

        # バウンディングボックスによる粗フィルタ（高速）
        if not (
            current_lat - lat_margin <= slat <= current_lat + lat_margin
            and current_lon - lon_margin <= slon <= current_lon + lon_margin
        ):
            continue

        distance = elev_service.calculate_distance(current_lat, current_lon, slat, slon)
        if distance > max_distance:
            continue

        shelter_elevation = elev_service.get_elevation_interpolated(slat, slon)
        if shelter_elevation is None:
            continue

        elevation_gain = shelter_elevation - current_elevation
        if elevation_gain < min_elevation_gain:
            continue

        hazard_assessment = haz_service.assess_candidate(slat, slon)
        hazard_safe = derive_hazard_safe(hazard_assessment)

        et_minutes = _calc_estimated_time(distance, transport_mode)
        tm_minutes = (tti_minutes - et_minutes) if tti_minutes is not None else None
        tm_status = _classify_time_margin(tm_minutes)

        severity_penalty = _calc_severity_penalty(hazard_assessment)
        safety_score = _calc_safety_score(
            elevation_gain, distance, max_distance, hazard_safe, tm_status, severity_penalty
        )

        # ハザード適合ボーナス: shelter.hazard_types が active_hazards と合致する場合 +10
        shelter_hazard_types = shelter.get("hazard_types") or []
        if active_hazards and shelter_hazard_types:
            if any(h in shelter_hazard_types for h in active_hazards):
                safety_score += 10.0

        # 最初の3件をデバッグログに出力（判定が動いているか確認用）
        if len(candidates) < 3:
            logger.info(
                "Candidate[%d] lat=%.5f lon=%.5f assessment=%s hazard_safe=%s "
                "tm_status=%s tm_min=%s score=%.1f",
                len(candidates), slat, slon, hazard_assessment, hazard_safe,
                tm_status, f"{tm_minutes:.1f}" if tm_minutes is not None else "None",
                safety_score,
            )

        candidates.append({
            "name": shelter["name"],
            "type": "emergency_shelter",
            "category": shelter.get("category", "evacuation_site"),
            "hazard_types": shelter.get("hazard_types") or [],
            "lat": slat,
            "lon": slon,
            "elevation": shelter_elevation,
            "elevation_gain": elevation_gain,
            "distance": distance,
            "estimated_time_minutes": et_minutes,
            "safety_score": safety_score,
            "hazard_safe": hazard_safe,
            "hazard_assessment": hazard_assessment,
            "time_to_impact_minutes": round(tti_minutes, 1) if tti_minutes is not None else None,
            "evacuation_time_minutes": round(et_minutes, 1),
            "time_margin_minutes": round(tm_minutes, 1) if tm_minutes is not None else None,
            "time_margin_status": tm_status,
        })

    # 危険区域内候補除外モード（EXCLUDE_UNSAFE_CANDIDATES=true 時）
    # 全候補が危険でゼロになる場合は fallback として除外せずに返す
    if EXCLUDE_UNSAFE_CANDIDATES:
        filtered = [c for c in candidates if c["hazard_safe"] is not False]
        if filtered:
            candidates = filtered
        else:
            logger.info(
                "exclude_unsafe_candidates: すべての候補が危険区域内のため fallback として全件返す"
            )

    candidates.sort(key=lambda x: x["safety_score"], reverse=True)
    return candidates[:15]


def search_grid_destinations(
    current_lat: float,
    current_lon: float,
    current_elevation: float,
    elev_service: ElevationService,
    haz_service: HazardService,
    min_elevation_gain: float,
    max_distance: float,
    transport_mode: str,
    tti_minutes: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """
    グリッド探索ベースで避難候補を検索（避難所データがない場合のフォールバック）。

    候補に名称はないため type = "safe_high_ground_candidate" を付与する。
    """
    raw = elev_service.find_evacuation_destinations(
        current_lat=current_lat,
        current_lon=current_lon,
        min_elevation_gain=min_elevation_gain,
        max_distance=max_distance,
        transport_mode=transport_mode,
    )

    results: List[Dict[str, Any]] = []
    for d in raw:
        hazard_assessment = haz_service.assess_candidate(d["lat"], d["lon"])
        hazard_safe = derive_hazard_safe(hazard_assessment)

        et_minutes = d["estimated_time_minutes"]
        tm_minutes = (tti_minutes - et_minutes) if tti_minutes is not None else None
        tm_status = _classify_time_margin(tm_minutes)

        severity_penalty = _calc_severity_penalty(hazard_assessment)
        safety_score = _calc_safety_score(
            d["elevation_gain"], d["distance"], max_distance, hazard_safe, tm_status, severity_penalty
        )
        results.append({
            "name": "高台候補地点",
            "type": "safe_high_ground_candidate",
            "lat": d["lat"],
            "lon": d["lon"],
            "elevation": d["elevation"],
            "elevation_gain": d["elevation_gain"],
            "distance": d["distance"],
            "estimated_time_minutes": et_minutes,
            "safety_score": safety_score,
            "hazard_safe": hazard_safe,
            "hazard_assessment": hazard_assessment,
            "time_to_impact_minutes": round(tti_minutes, 1) if tti_minutes is not None else None,
            "evacuation_time_minutes": round(et_minutes, 1),
            "time_margin_minutes": round(tm_minutes, 1) if tm_minutes is not None else None,
            "time_margin_status": tm_status,
        })
    # 危険区域内候補除外モード（EXCLUDE_UNSAFE_CANDIDATES=true 時）
    if EXCLUDE_UNSAFE_CANDIDATES:
        filtered = [r for r in results if r["hazard_safe"] is not False]
        if filtered:
            results = filtered
        else:
            logger.info(
                "exclude_unsafe_candidates (grid): すべての候補が危険区域内のため fallback として全件返す"
            )

    results.sort(key=lambda x: x["safety_score"], reverse=True)
    return results


# エンドポイント
@app.get("/")
async def root():
    """APIルート"""
    return {
        "message": "避難ナビゲーションAPI",
        "version": "1.0.0",
        "endpoints": {
            "health": "/health",
            "elevation": "/api/elevation",
            "evacuation": "/api/evacuation",
            "profile": "/api/elevation-profile",
            "emergency_shelters": "/api/emergency-shelters"
        }
    }


@app.get("/health")
async def health_check():
    """ヘルスチェック"""
    dem_loaded = elevation_service.dataset is not None
    loaded_hazards = hazard_service.loaded_hazard_types()
    hazard_info = {
        ht: hazard_service.polygon_count(ht)
        for ht in loaded_hazards
    }
    hazard_sources = {
        ht: hazard_service.loaded_sources(ht)
        for ht in loaded_hazards
    }
    missing_tsunami = hazard_service.get_missing_tsunami_sources()
    is_degraded = not dem_loaded or bool(missing_tsunami)
    return {
        "status": "degraded" if is_degraded else "healthy",
        "dem_loaded": dem_loaded,
        "dem_path": str(elevation_service.dem_path),
        "hazard_loaded": loaded_hazards,
        "hazard_polygon_counts": hazard_info,
        "hazard_sources": hazard_sources,
        "tsunami_coverage": {
            "configured_targets": hazard_service._expected_tsunami_sources,
            "loaded_sources": hazard_service.loaded_sources("tsunami"),
            "missing_sources": missing_tsunami,
            "full_coverage": not bool(missing_tsunami),
        },
        "shelters_loaded": len(get_shelter_registry().get_shelters()),
    }


@app.get("/api/elevation")
async def get_elevation(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180)
):
    """
    指定座標の標高を取得
    
    Args:
        lat: 緯度
        lon: 経度
        
    Returns:
        標高情報
    """
    try:
        if not elevation_service.is_loaded():
            raise HTTPException(
                status_code=503,
                detail=(
                    "DEM is not loaded. Canonical source is "
                    "data_lake/validated/tokyo/dem/elevation.tif"
                ),
            )

        if not elevation_service.contains(lat, lon):
            raise HTTPException(
                status_code=400,
                detail="指定座標は DEM の対象範囲外です",
            )

        elevation = elevation_service.get_elevation_interpolated(lat, lon)

        if elevation is None:
            raise HTTPException(
                status_code=400,
                detail="指定座標の標高データを取得できませんでした"
            )

        return {
            "lat": lat,
            "lon": lon,
            "elevation": round(elevation, 2),
            "unit": "m"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("標高取得エラー")
        raise HTTPException(status_code=500, detail="標高取得中に内部エラーが発生しました")


@app.get("/api/hazard-check")
async def hazard_check(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
):
    """
    指定座標のハザード判定を返す（軽量・即時応答）。

    避難先検索 (/api/evacuation) を行わずにハザードエリア判定だけを取得したい
    場合（手動現在地選択など）に使用する。

    Returns:
        {
            "lat": float,
            "lon": float,
            "is_danger": bool,
            "hazards": list[str],
            "hazard_assessment": dict[str, str]
        }
    """
    try:
        logger.info("hazard-check: lat=%.5f lon=%.5f", lat, lon)
        point_eval = hazard_engine.evaluate_point(lat, lon)
        return {
            "lat": lat,
            "lon": lon,
            "is_danger": point_eval["is_danger"],
            "hazards": point_eval["hazards"],
            "hazard_assessment": point_eval["hazard_assessment"],
        }
    except Exception as e:
        logger.exception("ハザード判定エラー")
        raise HTTPException(status_code=500, detail="ハザード判定中に内部エラーが発生しました")


@app.get("/api/reverse-geocode", response_model=ReverseGeocodeResponse)
async def reverse_geocode(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
):
    try:
        result = get_reverse_geocode_service().reverse_geocode(lat, lon)
        return ReverseGeocodeResponse(**result)
    except Exception as exc:
        logger.warning("reverse geocode endpoint failed: %s", exc)
        return ReverseGeocodeResponse(
            address=None,
            postcode=None,
            source="unknown",
            lat=lat,
            lon=lon,
        )


@app.post("/api/evacuation")
async def find_evacuation_destinations(request: EvacuationRequest):
    """
    避難目的地を検索（hazard_status・recommended 付き強化版）

    Args:
        request: 避難目的地検索リクエスト

    Returns:
        hazard_status / recommended / destinations / search_parameters
    """
    try:
        logger.info(
            "evacuation request: lat=%.5f lon=%.5f mode=%s max_distance=%.0f",
            request.lat, request.lon, request.transport_mode, request.max_distance,
        )
        # 現在地の標高を確認
        current_elevation = elevation_service.get_elevation_interpolated(
            request.lat, request.lon
        )

        if current_elevation is None:
            raise HTTPException(
                status_code=404,
                detail="現在地の標高データが見つかりません",
            )

        # DEM NoData センチネル値の防御チェック（elevation_service 側で弾けなかった場合の二重ガード）
        if current_elevation <= -9999.0:
            logger.warning(
                "evacuation: NoData sentinel leaked through elevation_service: lat=%.5f lon=%.5f elev=%.1f",
                request.lat, request.lon, current_elevation,
            )
            raise HTTPException(
                status_code=422,
                detail="現在地の標高データが無効です（NoData）。別の地点を選択してください。",
            )

        # 現在地のハザード判定（HazardEngine 経由）
        point_eval = hazard_engine.evaluate_point(request.lat, request.lon)
        hazard_status = {
            "is_danger": point_eval["is_danger"],
            "hazards": point_eval["hazards"],
            "assessment": point_eval["hazard_assessment"],  # severity 付き詳細（frontend 表示用）
        }

        # Time Margin: 現在地の TTI を構造化形式で取得（候補全件で共有）
        tti_detail = hazard_engine.get_time_to_impact_detail(request.lat, request.lon)
        tti_minutes = tti_detail["minutes"]  # 後方互換：search_* 関数に渡す用

        if tti_detail["computed"]:
            logger.info(
                "TTI computed: lat=%.5f lon=%.5f tti=%.1f min (tsunami speed=%.0f km/h reason=%s)",
                request.lat, request.lon, tti_minutes, TSUNAMI_SPEED_KMH, tti_detail["reason"],
            )
        else:
            logger.debug(
                "TTI: not computed (supported=%s reason=%s)",
                tti_detail["supported"], tti_detail["reason"],
            )

        # Reachable Safe Area: TTI が computed の場合のみ算出
        if not ENABLE_RSA:
            logger.info("RSA disabled: ENABLE_RSA=False")
            rsa_result = {
                "enabled": False,
                "computed": False,
                "status": "disabled",
                "reason": "rsa_disabled",
                "radius_m": None,
                "time_to_impact_minutes": round(tti_minutes, 1) if tti_minutes is not None else None,
                "walking_speed_mps": WALKING_SPEED_MPS,
                "area_m2": None,
                "exists": None,
                "geometry": None,
            }
        elif not tti_detail["computed"]:
            _rsa_skip_reason = tti_detail["reason"] or "tti_not_computed"
            logger.info("RSA skipped: TTI not computed (reason=%s)", _rsa_skip_reason)
            rsa_result = {
                "enabled": True,
                "computed": False,
                "status": "skipped",
                "reason": _rsa_skip_reason,
                "radius_m": None,
                "time_to_impact_minutes": None,
                "walking_speed_mps": WALKING_SPEED_MPS,
                "area_m2": None,
                "exists": None,
                "geometry": None,
            }
        else:
            rsa_result = _calc_rsa(request.lat, request.lon, tti_minutes)

        # 避難候補を検索
        # 避難所データがあれば shelter ベース、なければグリッドフォールバック
        _shelters = get_shelter_registry().get_shelters()
        if _shelters:
            raw_destinations = search_shelter_destinations(
                current_lat=request.lat,
                current_lon=request.lon,
                current_elevation=current_elevation,
                shelters=_shelters,
                elev_service=elevation_service,
                haz_service=hazard_service,
                min_elevation_gain=request.min_elevation_gain,
                max_distance=request.max_distance,
                transport_mode=request.transport_mode,
                tti_minutes=tti_minutes,
                active_hazards=hazard_status.get("hazards") or [],
            )
        else:
            raw_destinations = search_grid_destinations(
                current_lat=request.lat,
                current_lon=request.lon,
                current_elevation=current_elevation,
                elev_service=elevation_service,
                haz_service=hazard_service,
                min_elevation_gain=request.min_elevation_gain,
                max_distance=request.max_distance,
                transport_mode=request.transport_mode,
                tti_minutes=tti_minutes,
            )

        # レスポンス整形
        destinations = [
            {
                "name": d["name"],
                "type": d["type"],
                "lat": d["lat"],
                "lon": d["lon"],
                "elevation": round(d["elevation"], 2),
                "elevation_gain": round(d["elevation_gain"], 2),
                "distance": round(d["distance"], 2),
                "estimated_time_minutes": round(d["estimated_time_minutes"], 1),
                "safety_score": round(d["safety_score"], 1),
                "hazard_safe": d["hazard_safe"],
                "hazard_assessment": d.get("hazard_assessment", {}),
                # Time Margin フィールド（津波ポリゴン外 / データなし の場合は null）
                "time_to_impact_minutes": d.get("time_to_impact_minutes"),
                "evacuation_time_minutes": d.get("evacuation_time_minutes"),
                "time_margin_minutes": d.get("time_margin_minutes"),
                "time_margin_status": d.get("time_margin_status", "unknown"),
            }
            for d in raw_destinations
        ]

        if not destinations:
            return {
                "current_location": {
                    "lat": request.lat,
                    "lon": request.lon,
                    "elevation": round(current_elevation, 2),
                },
                "hazard_status": hazard_status,
                "time_to_impact": {
                    "supported": tti_detail["supported"],
                    "computed": tti_detail["computed"],
                    "minutes": round(tti_minutes, 1) if tti_minutes is not None else None,
                    "reason": tti_detail["reason"],
                },
                "recommended": None,
                "reachable_safe_area": rsa_result,
                "destinations": [],
                "search_parameters": {
                    "transport_mode": request.transport_mode,
                    "max_distance": request.max_distance,
                    "min_elevation_gain": request.min_elevation_gain,
                },
                "message": "指定条件で避難目的地が見つかりませんでした",
            }

        # 推奨候補を選定（hazard_safe=True > None > False の優先順位）
        best_raw, selected_tier, safe_count = _select_recommended(raw_destinations)
        best_tm_status = best_raw.get("time_margin_status", "unknown")
        # destinations はスコア降順（hazard + time_margin 補正済み）のまま返す
        recommended = {
            "name": best_raw["name"],
            "type": best_raw["type"],
            "lat": best_raw["lat"],
            "lon": best_raw["lon"],
            "elevation": round(best_raw["elevation"], 2),
            "elevation_gain": round(best_raw["elevation_gain"], 2),
            "distance": round(best_raw["distance"], 2),
            "estimated_time_minutes": round(best_raw["estimated_time_minutes"], 1),
            "safety_score": round(best_raw["safety_score"], 1),
            "hazard_safe": best_raw["hazard_safe"],
            "hazard_assessment": best_raw.get("hazard_assessment", {}),
            "time_to_impact_minutes": best_raw.get("time_to_impact_minutes"),
            "evacuation_time_minutes": best_raw.get("evacuation_time_minutes"),
            "time_margin_minutes": best_raw.get("time_margin_minutes"),
            "time_margin_status": best_tm_status,
            "reason": _build_reason(best_raw, selected_tier, best_tm_status),
        }

        logger.info(
            "evacuation result: candidates=%d selected=1 tier=%s",
            len(destinations), selected_tier,
        )
        return {
            "current_location": {
                "lat": request.lat,
                "lon": request.lon,
                "elevation": round(current_elevation, 2),
            },
            "hazard_status": hazard_status,
            "time_to_impact": {
                "supported": tti_detail["supported"],
                "computed": tti_detail["computed"],
                "minutes": round(tti_minutes, 1) if tti_minutes is not None else None,
                "reason": tti_detail["reason"],
            },
            "recommended": recommended,
            "reachable_safe_area": rsa_result,
            "recommendation_meta": {
                "selected_tier": selected_tier,        # "safe" | "unknown" | "unsafe"
                "safe_candidates_found": safe_count,
                "total_candidates_found": len(raw_destinations),
                "exclude_unsafe_candidates": EXCLUDE_UNSAFE_CANDIDATES,
            },
            "destinations": destinations,
            "search_parameters": {
                "transport_mode": request.transport_mode,
                "max_distance": request.max_distance,
                "min_elevation_gain": request.min_elevation_gain,
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("避難目的地検索エラー")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/route-risk")
async def assess_route_risk(request: RouteRiskRequest):
    """
    ルート危険度評価

    ルート座標列を受け取り、ハザードゾーンとの重複率（exposure_ratio）を算出して
    安全度スコアとリスクサマリーを返す。

    Args:
        request.coordinates: [[lat, lon], ...] (2点以上)
        request.sample_count: サンプリング点数（デフォルト40）

    Returns:
        {
            "safety_score": float,       # 0–100
            "risk_level": str,           # "safe" | "caution" | "danger"
            "risk_summary": {
                "total_penalty": float,
                "hazards": [...],
                "notes": [...],
            },
            "sampled_points": [
                {"lat": float, "lon": float, "hazards": {"flood": "inside" | "outside" | "unknown", ...}},
                ...
            ]
        }
    """
    try:
        coords = request.coordinates
        if len(coords) < 2:
            raise HTTPException(status_code=400, detail="座標が2点以上必要です")

        # サンプリング: ルート全体から均等に sample_count 点を取得
        total = len(coords)
        sample_count = min(request.sample_count, total)
        step = max(1, total // sample_count)
        sampled = coords[::step]
        # 末尾点が抜けた場合は補完
        last = coords[-1]
        if sampled[-1] is not last and sampled[-1] != last:
            sampled = sampled + [last]

        # ハザード通過率を計算（per-point データも収集）
        inside_counts: Dict[str, int] = {}
        sampled_points = []
        valid_samples = 0
        for coord in sampled:
            if len(coord) < 2:
                continue
            lat, lon = float(coord[0]), float(coord[1])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            valid_samples += 1
            assessment = hazard_service.assess_candidate(lat, lon)
            point_hazards: Dict[str, str] = {}
            for hazard_type, value in assessment.items():
                if isinstance(value, str):
                    status = value
                elif isinstance(value, dict):
                    status = value.get("status", "unknown")
                else:
                    status = "unknown"
                point_hazards[hazard_type] = status
                if status == "inside":
                    inside_counts[hazard_type] = inside_counts.get(hazard_type, 0) + 1
            sampled_points.append({"lat": lat, "lon": lon, "hazards": point_hazards})

        if valid_samples == 0:
            result = calc_route_risk_score({})
            result["sampled_points"] = []
            return result

        exposure_by_hazard = {k: v / valid_samples for k, v in inside_counts.items()}
        result = calc_route_risk_score(exposure_by_hazard)
        result["sampled_points"] = sampled_points
        logger.debug(
            "route-risk: samples=%d score=%.1f level=%s",
            valid_samples, result["safety_score"], result["risk_level"],
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ルート危険度評価エラー")
        raise HTTPException(status_code=500, detail="ルート危険度評価中に内部エラーが発生しました")


@app.post("/api/elevation-profile")
async def get_elevation_profile(request: ElevationProfileRequest):
    """
    2点間の標高プロファイルを取得
    
    Args:
        request: 標高プロファイル取得リクエスト
        
    Returns:
        標高プロファイルデータ
    """
    try:
        profile = elevation_service.get_elevation_profile(
            start_lat=request.start_lat,
            start_lon=request.start_lon,
            end_lat=request.end_lat,
            end_lon=request.end_lon,
            num_points=request.num_points
        )
        
        if not profile:
            raise HTTPException(
                status_code=404,
                detail="標高プロファイルを取得できませんでした"
            )
        
        return {
            "profile": [
                {
                    "distance": round(p["distance"], 2),
                    "elevation": round(p["elevation"], 2),
                    "lat": p["lat"],
                    "lon": p["lon"]
                }
                for p in profile
            ],
            "total_distance": round(profile[-1]["distance"], 2),
            "elevation_gain": round(
                profile[-1]["elevation"] - profile[0]["elevation"], 2
            )
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("標高プロファイル取得エラー")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats")
async def get_statistics():
    """
    システム統計情報
    """
    if elevation_service.dataset is None:
        raise HTTPException(
            status_code=503,
            detail="標高データが読み込まれていません"
        )
    
    bounds = elevation_service.dataset.bounds
    
    return {
        "coverage_area": {
            "west": bounds.left,
            "south": bounds.bottom,
            "east": bounds.right,
            "north": bounds.top
        },
        "resolution": {
            "width": elevation_service.dataset.width,
            "height": elevation_service.dataset.height
        },
        "crs": str(elevation_service.dataset.crs)
    }


@app.get("/api/emergency-shelters")
async def get_emergency_shelters(
    south: Optional[float] = Query(default=None, ge=-90, le=90),
    west: Optional[float] = Query(default=None, ge=-180, le=180),
    north: Optional[float] = Query(default=None, ge=-90, le=90),
    east: Optional[float] = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=5000, ge=1, le=20000)
):
    """
    指定緊急避難場所を取得

    bbox（south/west/north/east）指定時は範囲内データのみ返却
    """
    _shelters = get_shelter_registry().get_shelters()
    if not _shelters:
        return {
            "count": 0,
            "data": [],
            "message": "避難場所データが読み込まれていません。evacuation.sites.path を確認してください。"
        }

    has_bbox = all(v is not None for v in (south, west, north, east))
    if has_bbox and (south > north or west > east):
        raise HTTPException(status_code=400, detail="bboxの指定が不正です")

    if has_bbox:
        filtered = [
            s for s in _shelters
            if south <= s["lat"] <= north and west <= s["lon"] <= east
        ]
    else:
        filtered = _shelters

    data = filtered[:limit]

    return {
        "count": len(data),
        "total_count": len(filtered),
        "data": data
    }


if __name__ == "__main__":
    import uvicorn

    logger.info(
        "uvicorn config: host=%s port=%s reload=%s log_level=%s",
        API_HOST, API_PORT, API_RELOAD, API_LOG_LEVEL,
    )
    if API_RELOAD:
        logger.warning(
            "api.reload=true: uvicorn が data_lake/ 内のファイル書き換えで再起動する場合があります。"
            " admin ingest/normalize/deploy を実行する環境では api.reload=false を推奨します。"
        )

    uvicorn_kwargs: dict = dict(
        host=API_HOST,
        port=API_PORT,
        reload=API_RELOAD,
        log_level=API_LOG_LEVEL,
    )

    if API_RELOAD:
        # reload=true の場合、監視対象をアプリソースのみに限定する。
        # data_lake/, data_runtime/ の書き換えによる意図しない再起動を防ぐ。
        _backend_dir = Path(__file__).resolve().parent
        uvicorn_kwargs["reload_dirs"] = [str(_backend_dir / "app")]
        uvicorn_kwargs["reload_excludes"] = [
            "**/data_lake/**",
            "**/data_runtime/**",
            "**/*.json",
            "**/*.log",
            "**/*.geojson",
            "**/*.geojsonl",
            "**/*.tmp.*",
            "**/*.mbtiles",
            "**/*.tif",
            "**/*.pbf",
        ]
        logger.info(
            "reload_dirs=%s  reload_excludes=%s",
            uvicorn_kwargs["reload_dirs"],
            uvicorn_kwargs["reload_excludes"],
        )

    uvicorn.run("main:app", **uvicorn_kwargs)

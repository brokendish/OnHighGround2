"""
避難ナビゲーションAPI — public entrypoint (Phase 2-B.1)

これは public trust boundary 専用の FastAPI エントリポイントである。
admin / admin_config / admin_datasets / admin_upload / simulation /
layer_types（/api/admin プレフィクスの管理用マッピングAPI）の各routerは
物理的にimportしない。Docker操作を行うモジュール（app.services.pipeline_service、
app.services.job_manager）もimportしない。

管理機能・operator機能は backend/app_operator.py が別途提供する
（tasks/public-release/github_public_audit_phase2a_remediation_plan.md 第5.1節）。
"""
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import contextlib
import logging
import sys
import os
from pathlib import Path
import csv
import json

import math

from elevation_service import ElevationService
from hazard_service import (
    HazardService,
    derive_hazard_safe,
    compute_hazard_coverage_status,
    compute_aggregate_status,
    compute_hazard_safe_from_aggregate,
    HAZARD_DETECTED,
    NO_HAZARD_RECORD,
    SOURCE_UNAVAILABLE,
)
from hazard_definitions import HAZARD_DEFINITIONS
from geometry_utils import calc_reachable_safe_area, SHAPELY_AVAILABLE
from hazard_engine import HazardEngine
from app.api.hazards import router as hazards_router
from app.api.earthquakes import router as earthquakes_router
from app.api.earthquakes_recent import router as earthquakes_recent_router
from app.api.earthquakes_stream import router as earthquakes_stream_router
from app.api.weather import router as weather_router
from app.api.tsunami import router as tsunami_router
from app.api.astro import router as astro_router
from app.api.tide import router as tide_router
from app.api.navigation import router as navigation_router
from app.api.live_summary import router as live_summary_router
from app.api.live_tide import router as live_tide_router
from app.api.live_sun_moon import router as live_sun_moon_router
from app.api.live_storm_surge import router as live_storm_surge_router
from app.api.live_rain_timeline import router as live_rain_timeline_router
from app.api.live_train import router as live_train_router
from app.api.live_road_traffic import router as live_road_traffic_router
from app.api.live_earthquakes import router as live_earthquakes_router
from app.api.live_weather_jma import router as live_weather_jma_router
from app.api.jartic_traffic import router as jartic_traffic_router
from app.services.earthquake_realtime_service import get_realtime_service
from app.services.admin_log_service import write_app_log
from app.services.reverse_geocode_service import get_reverse_geocode_service
from app.services.route_risk_scoring import calc_route_risk_score, calc_kikikuru_adjustment, _risk_level as _route_risk_level
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
from app_config_properties import (
    CorsConfigError,
    load_properties,
    load_raw_property_value,
    parse_bool,
    parse_csv,
    parse_cors_origins,
    resolve_config_path,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = BASE_DIR / "app.properties"

# CODEX P2B5-CX-003（第18ラウンド）対応: 設定file読み込み・default解決の
# 実装本体は backend/app_config_properties.py（consumerとpublish-time
# validatorの単一情報源）へ集約した。この行以降のCONFIG_PATH/APP_CONFIG
# 解決結果は従来と完全に同一（挙動変更なし、実装の集約のみ）。
CONFIG_PATH = resolve_config_path(BASE_DIR)
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

def _dev_docs_enabled() -> bool:
    """FastAPI docs（docs_url/redoc_url/openapi_url）をdevelopment限定で
    有効化するための二重条件（Phase 2-C 第3.2節、Round 12D-B改訂）。

    production/public既定profile（docker-compose.ymlのbackend-public/
    backend-operator）はこれらの環境変数を一切設定しないため、本関数は
    常にFalseを返し、docsはproduction既定で無効のままになる。

    Round 12D-A OWNER決定（NEW-ADV-001）: 値の比較はbyte-exact一致のみとし、
    `.strip()`・`.lower()`・`.casefold()`・truthy変換のいずれも行わない。
    認める値は完全一致の literal `"true"` だけであり、未設定・空・空白・
    "1"・"yes"・"True"・"TRUE"・" true"・"true "はすべて無効側とする
    （前後空白・大文字小文字の正規化を一切行わない）。両方の環境変数が
    同時にこの厳密一致を満たさない限り有効にならない。
    """
    dev_mode = os.environ.get("OHG2_DEV_MODE", "")
    dev_docs = os.environ.get("OHG2_DEV_DOCS_ENABLED", "")
    return dev_mode == "true" and dev_docs == "true"


# Phase 2-C 第3.1節: production/public既定ではFastAPI生成docs
# （/docs, /docs/oauth2-redirect, /redoc, /openapi.json）をpublic route
# tableへ一切登録しない（docs_url/redoc_url/openapi_url=None）。
# `_dev_docs_enabled()`の二重条件を両方満たす場合だけ有効化する
# （development限定、admin/simulation/operator routeが増えるわけではない）。
_DOCS_ENABLED = _dev_docs_enabled()

# FastAPIアプリケーション初期化
app = FastAPI(
    title="避難ナビゲーションAPI",
    description="津波・高潮・洪水からの避難経路を提供するAPI",
    version="1.0.0",
    docs_url="/docs" if _DOCS_ENABLED else None,
    redoc_url="/redoc" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
)
if _DOCS_ENABLED:
    logger.warning(
        "OHG2_DEV_MODE=true かつ OHG2_DEV_DOCS_ENABLED=true — "
        "public entrypointでFastAPI docs(/docs,/redoc,/openapi.json)を有効化した。"
        "productionでは絶対にこれらの環境変数を設定しないこと。"
    )

# CORS設定（Phase 2-C 第6節: exact-origin allowlist、fail-closed）。
# 未設定/空は空allowlist（same-originのみ、`*`へfallbackしない）。
# 値が存在し1件でも不正な場合は起動時fail-closed（CorsConfigErrorがそのまま
# 伝播してprocessが終了する。他の起動時設定検証と同一方針）。
#
# CODEX第1ラウンドP2C-CX-002対応: `APP_CONFIG.get(...)`（`load_properties()`
# が生成、全値に`.strip()`済み）を使うと、前後空白を含むorigin値が
# fail-closed検証へ到達する前に暗黙補正されてしまう。originだけは
# `load_raw_property_value()`でfile内の生の値（前後空白を含む）を
# 直接読み、`parse_cors_origins()`の空白拒否ロジックを実配線で機能させる。
CORS_ALLOW_ORIGINS = parse_cors_origins(load_raw_property_value(CONFIG_PATH, "cors.allow_origins"))
CORS_ALLOW_METHODS = parse_csv(APP_CONFIG.get("cors.allow_methods"), ["GET", "POST", "OPTIONS"])
CORS_ALLOW_HEADERS = parse_csv(APP_CONFIG.get("cors.allow_headers"), ["Content-Type"])
CORS_ALLOW_CREDENTIALS = parse_bool(
    APP_CONFIG.get("cors.allow_credentials"),
    False
)
if "*" in CORS_ALLOW_METHODS:
    raise CorsConfigError("cors.allow_methods: ワイルドカード '*' は許可しない")
if "*" in CORS_ALLOW_HEADERS:
    raise CorsConfigError("cors.allow_headers: ワイルドカード '*' は許可しない")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=CORS_ALLOW_METHODS,
    allow_headers=CORS_ALLOW_HEADERS,
)
# public entrypointが登録するrouterはこれで全てである。
# admin / admin_config / admin_datasets / admin_upload / simulation / layer_types
# （/api/admin プレフィクスの管理用マッピングAPI）はここに追加しないこと。
# 追加が必要な管理機能は backend/app_operator.py 側へ実装する。
# 開発用の地震publish routerもpublic trust boundaryには登録しない。
# DEV_EARTHQUAKE_PUBLISH の値によってpublic routeが出現することはない。
PUBLIC_ROUTERS = [
    hazards_router,
    earthquakes_router,
    earthquakes_recent_router,
    earthquakes_stream_router,
    weather_router,
    tsunami_router,
    astro_router,
    tide_router,
    navigation_router,
    live_summary_router,
    live_tide_router,
    live_sun_moon_router,
    live_storm_surge_router,
    live_rain_timeline_router,
    live_train_router,
    live_road_traffic_router,
    live_earthquakes_router,
    live_weather_jma_router,
    jartic_traffic_router,
]
for _router in PUBLIC_ROUTERS:
    app.include_router(_router)


@app.on_event("startup")
async def _startup():
    """起動時: 地震リアルタイムサービス起動。

    ジョブ状態のstale cleanup（app.services.job_manager 経由、docker inspect を
    内部で実行する）はoperator専用の関心事であり、backend/app_operator.py 側で
    実施する（Docker操作をpublic import graphへ持ち込まないため）。
    """
    try:
        write_app_log("backend startup")
    except Exception:
        pass
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

# CODEX P2B5-CX-004（第7ラウンド）対応: 以下のhazard type別起動時ローダーは
# 従来data_runtime/backend/hazard/<type>を直接globしており、atomic publish/
# lease機構（Phase 2-B.5）が導入済みの環境でもGCの削除保護（lease）を
# 一切受けずに読んでいた（独立検証: 「app_public.pyの起動時hazard direct
# reader群もflat pathのまま」と指摘）。lease機構が利用可能な場合は、
# 全hazard type読み込みを単一leaseで保護されたfixed version root配下から
# 行うことで、起動時読み込み中にGCが対象versionを削除しないことを保証する。
#
# 読み込みは起動時一度きりであり、新versionの反映には再起動が必要
# （restart-required consumer）。ShelterRegistryのようなper-requestホット
# リロードは、hazard_serviceが空間indexを保持する重い初期化を伴うため
# 本ラウンドのscopeとしない（既知の限界として開示する）。
#
# is_available()==Falseの場合（atomic publish機構が未導入の環境）は、
# 従来通りflat pathへfallackする。is_available()==Trueにもかかわらず
# lease取得が失敗する場合は「導入済みだが破損」を意味し、
# ShelterRegistry（shelter_service.py）と同じ方針でlegacyへ静かに
# fallbackせず、起動そのものをfail-closedで停止させる。
_hazard_lease_stack = contextlib.ExitStack()
try:
    from app.services import runtime_version_access as _hazard_rva
    from app.services.runtime_atomic import RuntimeAtomicError as _HazardRuntimeAtomicError
    from app.services.runtime_lease import leased_version_root as _hazard_leased_version_root

    # `is_available()`（coordination.lock存在）は「leases infra自体は一度
    # runtime-initで初期化された」ことしか示さず、「操作者が一度でも
    # publish()を実行し`current`を作った」こととは別事象である。`current`が
    # 一切存在しない（symlinkはおろかpathすら無い）のは、runtime-init直後で
    # まだ一度もpublishされていない正常な起動直後状態であり、これを
    # corruptionとして扱ってfail-closedにすると、初回デプロイ直後
    # （最初のpublish前）に本processが必ずcrashする。`current`が「存在するが
    # 不正」な場合は、以下のfail-closed方針（legacyへfallbackせず起動停止）
    # を従来どおり適用する（shelter_service.py::_try_load_from_atomic_publish()
    # と同一方針）。
    _hazard_current_link = _hazard_rva.DATA_RUNTIME_ROOT / "current"
    _hazard_never_published = not _hazard_current_link.exists() and not _hazard_current_link.is_symlink()
    if _hazard_rva.is_available() and not _hazard_never_published:
        _hazard_coordinator = _hazard_rva.get_coordinator()
        try:
            _hazard_version_root = _hazard_lease_stack.enter_context(
                _hazard_leased_version_root(
                    _hazard_coordinator, _hazard_rva.DATA_RUNTIME_ROOT, "hazard-service-startup-load"
                )
            )
        except _HazardRuntimeAtomicError as exc:
            raise RuntimeError(
                f"hazard_service起動時lease取得に失敗（atomic publish状態が破損の疑い、"
                f"legacyへfallbackしない）: {exc}"
            ) from exc
        _HAZARD_BACKEND_ROOT = _hazard_version_root / "backend" / "hazard"
        # CODEX P2B5-CX-004（第7ラウンド）対応: このflagがTrueの間は、
        # 個々のhazard typeがleaseされたversion内に存在しないというだけの
        # 理由でdata_lake/legacyへ型別fallbackしてはいけない。それを許すと、
        # 同一process内でflood=leased current version・storm_surge=unleased
        # data_lakeのように、hazard typeごとに異なるsnapshotが混在しうる
        # （独立検証で実証された「partial atomic snapshot時のsnapshot混在」）。
        # atomic lease機構が有効な環境では、対象typeがそのversionに存在
        # しない場合は「そのversionにはそのtypeのdataがない」として
        # スキップするだけにし、lease外の別sourceへは一切読みに行かない。
        _HAZARD_USING_ATOMIC_LEASE = True
        logger.info(
            "HazardService: 起動時読み込みをatomic publish leaseで保護（version=%s）",
            _hazard_version_root.name,
        )
    else:
        _HAZARD_BACKEND_ROOT = BASE_DIR.parent / "data_runtime" / "backend" / "hazard"
        _HAZARD_USING_ATOMIC_LEASE = False
        logger.info("HazardService: atomic publish機構未導入 — flat pathから読み込み")
except ImportError:
    _HAZARD_BACKEND_ROOT = BASE_DIR.parent / "data_runtime" / "backend" / "hazard"
    _HAZARD_USING_ATOMIC_LEASE = False

FLOOD_ENABLED = parse_bool(APP_CONFIG.get("hazard.flood.enabled", "false"), False)
if FLOOD_ENABLED:
    # HAZARD-ENGINE-VERSIONED-LAYOUT-MISMATCH / HAZARD-ENGINE-LARGE-DATASET-
    # MEMORY-BLOCKER対応: data_runtime/backend/hazard/flood/{region}/ 配下
    # （Dual Storage Remediation Phase C1で確立した正式current layout）の
    # 全 *.geojson を ijson streaming loader（load_geojson_streaming、
    # HazardService内部でfeatureを1件ずつ処理・破棄する）で順次ロードする。
    # 旧実装は直下（region配下ではない）の *.geojsonl のみをglob対象として
    # おり、layout不一致・拡張子不一致の両方でflood versioned artifact
    # （実測524MB/325MB）を発見できず、実ナビゲーション判定からflood自体が
    # 完全に欠落していた（is_available()時はdata_lakeへもfallbackしない
    # ため、silent omissionとなっていた）。
    _flood_runtime_dir = _HAZARD_BACKEND_ROOT / "flood"
    _flood_geojson_files: list[Path] = []
    if _flood_runtime_dir.is_dir():
        _flood_geojson_files = sorted(_flood_runtime_dir.rglob("*.geojson"))

    if _flood_geojson_files:
        for _f in _flood_geojson_files:
            logger.info("Flood loaded from runtime (streaming): %s", _f)
            hazard_service.load_geojson_streaming("flood", _f, bbox_only=True)
    elif _HAZARD_USING_ATOMIC_LEASE:
        # CX-004（第7ラウンド）対応: leaseされたversionにfloodがないだけで
        # data_lakeへは読みに行かない（snapshot混在防止）。
        logger.info("Flood: 現行versionにdataなし（snapshot混在防止のためskip、data_lakeへはfallbackしない）")
    else:
        # HAZARD-LEGACY-FLAT-FALLBACK-CONTRACT対応: is_available()==False
        # （runtime-init未実行、atomic lease機構未導入）は、docker-compose.yml
        # のbackend-public::depends_on（runtime-init: service_completed_
        # successfully）により、現在の正式deployment modelでは到達しない
        # 状態である（docs/installation.md参照）。旧hardcoded legacy flat
        # basenameの読み込みはmigration residueであり、unsupported
        # deployment modelとして明示的にskip
        # する（既存のcurrent-missing skip semanticsと同じ思想）。
        logger.info(
            "Flood: atomic runtime lease機構が未導入（unsupported deployment "
            "model）のためskip（legacy flat fallbackは廃止済み）"
        )
else:
    logger.info("洪水ハザード判定は無効（hazard.flood.enabled=false）")

# storm_surge: 高潮浸水想定区域
# HAZARD-ENGINE-VERSIONED-LAYOUT-MISMATCH / HAZARD-ENGINE-LARGE-DATASET-
# MEMORY-BLOCKER対応: data_runtime/backend/hazard/storm_surge/{region}/
# 配下（正式current layout）の全 *.geojson を、region配下も含めて
# 再帰的に列挙し、ijson streaming loader（load_geojson_streaming）で
# 順次ロードする。旧実装は直下（非再帰）globのみで、region配下
# サブディレクトリのartifactを発見できていなかった（実測54MB/82MB、
# floodと同様にswap thrashリスクがあるためstreaming化する）。
_storm_surge_runtime_dir = _HAZARD_BACKEND_ROOT / "storm_surge"
_storm_surge_geojson_files: list[Path] = []
if _storm_surge_runtime_dir.is_dir():
    _storm_surge_geojson_files = sorted(_storm_surge_runtime_dir.rglob("*.geojson"))

if _storm_surge_geojson_files:
    for _f in _storm_surge_geojson_files:
        logger.info("StormSurge loaded from runtime (streaming): %s", _f)
        hazard_service.load_geojson_streaming("storm_surge", _f, bbox_only=True)
elif _HAZARD_USING_ATOMIC_LEASE:
    logger.info("StormSurge: 現行versionにdataなし（snapshot混在防止のためskip、data_lakeへはfallbackしない）")
else:
    # HAZARD-LEGACY-FLAT-FALLBACK-CONTRACT対応: is_available()==Falseは
    # 現在の正式deployment modelでは到達しない状態（flood節の注記参照）。
    # 旧hardcoded legacy flat basename読み込みはunsupported deployment
    # modelとして明示的にskipする。
    logger.info(
        "StormSurge: atomic runtime lease機構が未導入（unsupported "
        "deployment model）のためskip（legacy flat fallbackは廃止済み）"
    )

# tsunami: targets 設定に従ってファイルを個別ロード
# デフォルト: tokyo のみ（東京版 v1 標準モード）
# 広域モード: hazard.tsunami.targets=tokyo,kanagawa,chiba
#
# 参照優先順位:
#   1. data_runtime/backend/hazard/tsunami/  (runtime 優先)
#   2. data_lake/validated/tokyo/tsunami/    (validated 正本、durable authoritative
#      source。HAZARD-LEGACY-FLAT-FALLBACK-CONTRACT対応: is_available()==Falseに
#      限定されたhardcoded flat basename fallbackとは別contractであり本remediation
#      のscope外——data_lake/validatedはLEGACY-HAZARD-RUNTIME-ARTIFACT-CLEANUP
#      の削除候補にも含まれない）
#
# HAZARD-LEGACY-FLAT-FALLBACK-CONTRACT対応: 旧legacy設定キー
# （デフォルトはdata_lake/normalizedだが、app.propertiesではflat runtime dir
# を指すよう上書きされていた＝実質的にhardcoded legacy flat basename
# fallbackだった）と、それに基づくnormalizedフォールバック階層は撤去。
# tsunami_{target}.geojson という命名規則自体はcurrent/versioned側でも
# 使われるため維持する。
_tsunami_runtime_dir = _HAZARD_BACKEND_ROOT / "tsunami"
_tsunami_validated_dir = BASE_DIR.parent / "data_lake" / "validated" / "tokyo" / "tsunami"
_tsunami_targets = parse_csv(APP_CONFIG.get("hazard.tsunami.targets", "tokyo"), ["tokyo"])

logger.info("Loading tsunami hazard targets: %s", ", ".join(_tsunami_targets))

for _target in _tsunami_targets:
    _filename = f"tsunami_{_target}.geojson"
    _runtime_path = _tsunami_runtime_dir / _filename
    _validated_path = _tsunami_validated_dir / _filename
    if _runtime_path.exists():
        logger.info("Tsunami loaded from runtime: %s", _runtime_path)
        hazard_service.load_geojson_streaming("tsunami", _runtime_path, bbox_only=True)
    elif _HAZARD_USING_ATOMIC_LEASE:
        # CX-004（第7ラウンド）対応: leaseされたversionにこのtargetがない
        # だけでdata_lakeへは読みに行かない（snapshot混在防止）。
        logger.info(
            "Tsunami: target '%s' は現行versionにdataなし（snapshot混在防止のためskip、data_lakeへはfallbackしない）",
            _target,
        )
    elif _validated_path.exists():
        logger.warning("Tsunami fallback to data_lake: %s", _validated_path)
        hazard_service.load_geojson_streaming("tsunami", _validated_path, bbox_only=True)
    else:
        logger.warning(
            "Tsunami file not found for target '%s': checked runtime=%s, validated=%s — skipped "
            "(unsupported deployment modelではlegacy flat fallbackは廃止済み)",
            _target, _runtime_path, _validated_path,
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
    _inland_flood_runtime_dir = _HAZARD_BACKEND_ROOT / "inland_flood"
    _inland_flood_geojson_files: list[Path] = []
    if _inland_flood_runtime_dir.is_dir():
        # rglob でサブディレクトリ（{region}/）内のファイルも含めてスキャン
        _inland_flood_geojson_files = sorted(_inland_flood_runtime_dir.rglob("*.geojson"))

    if _inland_flood_geojson_files:
        for _f in _inland_flood_geojson_files:
            logger.info("InlandFlood loaded from runtime: %s", _f)
            hazard_service.load("inland_flood", _f)
    elif _HAZARD_USING_ATOMIC_LEASE:
        logger.info("InlandFlood: 現行versionにdataなし（snapshot混在防止のためskip、data_lakeへはfallbackしない）")
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
    _landslide_runtime_dir = _HAZARD_BACKEND_ROOT / "landslide"
    _landslide_geojson_files: list[Path] = []
    if _landslide_runtime_dir.is_dir():
        # rglob でサブディレクトリ（{region}/）内のファイルも含めてスキャン
        _landslide_geojson_files = sorted(_landslide_runtime_dir.rglob("*.geojson"))

    if _landslide_geojson_files:
        for _f in _landslide_geojson_files:
            logger.info("Landslide loaded from runtime: %s", _f)
            hazard_service.load_geojson_streaming("landslide", _f, bbox_only=True)
    elif _HAZARD_USING_ATOMIC_LEASE:
        logger.info("Landslide: 現行versionにdataなし（snapshot混在防止のためskip、data_lakeへはfallbackしない）")
    else:
        # HAZARD-LEGACY-FLAT-FALLBACK-CONTRACT対応: is_available()==Falseは
        # 現在の正式deployment modelでは到達しない状態（flood節の注記参照）。
        # 旧hardcoded legacy flat basename読み込みはunsupported deployment
        # modelとして明示的にskipする。
        logger.info(
            "Landslide: atomic runtime lease機構が未導入（unsupported "
            "deployment model）のためskip（legacy flat fallbackは廃止済み）"
        )
else:
    logger.info("土砂災害ハザード判定は無効（hazard.landslide.enabled=false）")

# ── 低地・排水困難エリア ─────────────────────────────────────────────────────
# 地形的リスク（補助ハザード）。is_danger には影響しない（SUPPLEMENTARY_HAZARD_TYPES 参照）。
_lowland_enabled = parse_bool(APP_CONFIG.get("hazard.lowland_poor_drainage.enabled"), True)
if _lowland_enabled:
    _lowland_runtime_dir = _HAZARD_BACKEND_ROOT / "lowland_poor_drainage"
    _lowland_geojson_files: list = []
    if _lowland_runtime_dir.is_dir():
        _lowland_geojson_files = sorted(_lowland_runtime_dir.rglob("*.geojson"))

    if _lowland_geojson_files:
        for _f in _lowland_geojson_files:
            logger.info("LowlandPoorDrainage loaded from runtime: %s", _f)
            hazard_service.load_geojson_streaming("lowland_poor_drainage", _f, bbox_only=True)
    elif _HAZARD_USING_ATOMIC_LEASE:
        # CX-004（第7ラウンド）対応: snapshot混在防止のためdata_lakeへは
        # fallbackしない。lowland_poor_drainageはdeploy_to_runtime.shが
        # backend/hazard配下へ配備しない補助layerであるため、atomic lease
        # 有効時は常にこの経路になる（is_dangerには影響しないsupplementary
        # hazardのため許容する。第21節で開示）。
        logger.info("LowlandPoorDrainage: 現行versionにdataなし（snapshot混在防止のためskip、data_lakeへはfallbackしない）")
    else:
        for _region in ("tokyo", "kanagawa"):
            _validated_dir = BASE_DIR.parent / "data_lake" / "validated" / _region / "lowland_poor_drainage"
            _lowland_files = sorted(_validated_dir.glob("*.geojson")) if _validated_dir.is_dir() else []
            if _lowland_files:
                _lowland_path = _lowland_files[0]
                logger.info("LowlandPoorDrainage loaded from validated (%s): %s", _region, _lowland_path)
                hazard_service.load_geojson_streaming("lowland_poor_drainage", _lowland_path, bbox_only=True)
            else:
                logger.info("低地データが見つかりません（スキップ）: %s", _validated_dir)

    from app.services.hazard_runtime_service import set_hazard_service as _set_hs
    _set_hs(hazard_service)
    logger.info("hazard_runtime_service: HazardService 登録完了")
else:
    logger.info("低地・排水困難エリア判定は無効（hazard.lowland_poor_drainage.enabled=false）")

# CODEX P2B5-CX-004（第7ラウンド）対応: 全hazard type起動時読み込みが
# 完了したので、保持していたleaseを解放する（取得していた場合のみ、
# is_available()==Falseだった環境ではExitStackは空で close() は no-op）。
_hazard_lease_stack.close()

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


class KikikuruRouteInput(BaseModel):
    """キキクルルート要約（フロントエンドからの補正入力）Phase 3-B"""
    status: Optional[str] = None  # "ok" | "unavailable" | "loading" | "off"
    inund:  Optional[str] = None  # "none" | "caution" | "danger" | "unavailable"
    flood:  Optional[str] = None
    land:   Optional[str] = None


class RouteRiskRequest(BaseModel):
    """ルート危険度評価リクエスト"""
    coordinates: List[List[float]] = Field(
        ...,
        description="ルート座標列 [[lat, lon], ...] (2点以上)"
    )
    sample_count: int = Field(default=40, ge=5, le=100, description="サンプリング点数")
    kikikuru: Optional[KikikuruRouteInput] = Field(
        default=None,
        description="キキクル補正入力（Phase 3-B）。省略時は補正なし"
    )


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


# Round 12D-B1（hazard_definitions.py frozen SHA復元）: get_all_hazard_type_names()
# ヘルパーは追加せず、NEW-ADV-005 frozen contractのauthoritative object
# (HAZARD_DEFINITIONS) から直接導出する（別途複製・独立管理しない）。
ALL_HAZARD_TYPE_NAMES = [d.name for d in HAZARD_DEFINITIONS]

# aggregate_status ごとのスコア減点値
# 基礎スコア上限 100pt: HAZARD_DETECTED は確実に NO_HAZARD_RECORD 候補より下位、
# SOURCE_UNAVAILABLE は中間に置く
HAZARD_UNSAFE_PENALTY = 100.0    # aggregate_status=HAZARD_DETECTED: 危険確定
HAZARD_UNKNOWN_PENALTY = 20.0    # aggregate_status=SOURCE_UNAVAILABLE: 未判定（やや不利）

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
    aggregate_status: str,
    time_margin_status: str = "unknown",
    severity_penalty: float = 0.0,
) -> float:
    """
    安全性スコア計算 (基礎 0-100、aggregate_status + time_margin + severity に応じて補正)。

    - elevation_score:    標高差が 30m 以上で満点 50pt
    - distance_score:     距離が短いほど高スコア、max_distance で 0pt
    - hazard penalty（Round 12D-B、aggregate_status 基準）:
        NO_HAZARD_RECORD   → 0pt    (該当ハザード記録なし)
        SOURCE_UNAVAILABLE → -20pt  (未判定)
        HAZARD_DETECTED    → -100pt (ハザード検出、この候補を必ず下位にする)
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
    if aggregate_status == NO_HAZARD_RECORD:
        penalty = 0.0
    elif aggregate_status == HAZARD_DETECTED:
        penalty = HAZARD_UNSAFE_PENALTY
    else:
        penalty = HAZARD_UNKNOWN_PENALTY
    time_bonus = _time_margin_score_bonus(time_margin_status)
    return base_score - penalty - severity_penalty + time_bonus


def _select_recommended(candidates: List[Dict[str, Any]]) -> tuple:
    """
    推奨候補を選定する（Round 12D-B、NEW-ADV-003 selected_tier Option A）。

    優先順位（選定アルゴリズム自体はRound 12D-A以前から不変。ラベル文字列のみ
    hazard_coverage_statusと同一語彙へ変更）:
      1. aggregate_status=NO_HAZARD_RECORD   (該当ハザード記録なし) → safety_score 最大
      2. aggregate_status=SOURCE_UNAVAILABLE (情報確認不可)         → safety_score 最大  ← 1が0件の場合
      3. aggregate_status=HAZARD_DETECTED    (ハザード検出)         → safety_score 最大  ← 1/2が0件の場合

    Returns:
        (recommended_candidate, selected_tier: str, no_hazard_record_count: int)
        selected_tier: "HAZARD_DETECTED" | "NO_HAZARD_RECORD" | "SOURCE_UNAVAILABLE"
    """
    no_hazard_record_candidates = [c for c in candidates if c["aggregate_status"] == NO_HAZARD_RECORD]
    if no_hazard_record_candidates:
        best = max(no_hazard_record_candidates, key=lambda x: x["safety_score"])
        return best, NO_HAZARD_RECORD, len(no_hazard_record_candidates)

    source_unavailable_candidates = [c for c in candidates if c["aggregate_status"] == SOURCE_UNAVAILABLE]
    if source_unavailable_candidates:
        best = max(source_unavailable_candidates, key=lambda x: x["safety_score"])
        return best, SOURCE_UNAVAILABLE, 0

    best = max(candidates, key=lambda x: x["safety_score"])
    return best, HAZARD_DETECTED, 0


def _build_reason(
    dest: dict,
    selected_tier: str,
    time_margin_status: str = "unknown",
) -> str:
    """
    推奨理由の文字列を組み立てる（Round 12D-B、NEW-ADV-003 frontend_consumer_display_contract）。

    selected_tier:
      "NO_HAZARD_RECORD"   → 該当ハザード記録なしの候補から選定（安全確認ではない）
      "SOURCE_UNAVAILABLE" → NO_HAZARD_RECORD候補ゼロのためハザード情報確認不可の候補から選定
      "HAZARD_DETECTED"    → 両方ゼロのためハザード検出候補から選定（fallback）

    禁止語（frontend_consumer_display_contract）: 安全・安全候補・危険区域外・
    safe・confirmed safe・safety confirmed 及びこれらと同義の肯定的安全表現を
    本文言へ含めない。

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

    if selected_tier == NO_HAZARD_RECORD:
        parts = ["該当ハザード記録なし（危険がないことを示すものではありません）の候補"]
        if gain >= 10:
            parts.append(f"現在地より{gain:.0f}m高い")
        if dist <= 1000:
            parts.append("徒歩10分圏内")
        parts.append("標高差と到達性のバランスが最も良い地点")
        if time_note:
            parts.append(time_note)
        return "、".join(parts)

    if selected_tier == SOURCE_UNAVAILABLE:
        parts = [
            "該当ハザード記録なしの候補が見つからなかった",
            "ハザード情報を確認できません。到達可能性と標高差が最も良い候補",
        ]
        if gain >= 10:
            parts.append(f"現在地より{gain:.0f}m高い")
        parts.append("利用可能なハザードデータでは判定不能のため注意が必要")
        if time_note:
            parts.append(time_note)
        return "、".join(parts)

    # selected_tier == HAZARD_DETECTED
    base = (
        "該当ハザード記録なしの候補・ハザード情報確認不可の候補のいずれも見つからなかった。"
        f"ハザード検出区域内を含む候補の中で標高差（現在地より{gain:.0f}m高い）と"
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
        hazard_coverage_status = compute_hazard_coverage_status(hazard_assessment, ALL_HAZARD_TYPE_NAMES)
        aggregate_status = compute_aggregate_status(hazard_coverage_status)
        hazard_safe = compute_hazard_safe_from_aggregate(aggregate_status)

        et_minutes = _calc_estimated_time(distance, transport_mode)
        tm_minutes = (tti_minutes - et_minutes) if tti_minutes is not None else None
        tm_status = _classify_time_margin(tm_minutes)

        severity_penalty = _calc_severity_penalty(hazard_assessment)
        safety_score = _calc_safety_score(
            elevation_gain, distance, max_distance, aggregate_status, tm_status, severity_penalty
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
            "hazard_coverage_status": hazard_coverage_status,
            "aggregate_status": aggregate_status,
            "time_to_impact_minutes": round(tti_minutes, 1) if tti_minutes is not None else None,
            "evacuation_time_minutes": round(et_minutes, 1),
            "time_margin_minutes": round(tm_minutes, 1) if tm_minutes is not None else None,
            "time_margin_status": tm_status,
        })

    # 危険区域内候補除外モード（EXCLUDE_UNSAFE_CANDIDATES=true 時）
    # 全候補が危険でゼロになる場合は fallback として除外せずに返す
    if EXCLUDE_UNSAFE_CANDIDATES:
        filtered = [c for c in candidates if c["aggregate_status"] != HAZARD_DETECTED]
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
        hazard_coverage_status = compute_hazard_coverage_status(hazard_assessment, ALL_HAZARD_TYPE_NAMES)
        aggregate_status = compute_aggregate_status(hazard_coverage_status)
        hazard_safe = compute_hazard_safe_from_aggregate(aggregate_status)

        et_minutes = d["estimated_time_minutes"]
        tm_minutes = (tti_minutes - et_minutes) if tti_minutes is not None else None
        tm_status = _classify_time_margin(tm_minutes)

        severity_penalty = _calc_severity_penalty(hazard_assessment)
        safety_score = _calc_safety_score(
            d["elevation_gain"], d["distance"], max_distance, aggregate_status, tm_status, severity_penalty
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
            "hazard_coverage_status": hazard_coverage_status,
            "aggregate_status": aggregate_status,
            "time_to_impact_minutes": round(tti_minutes, 1) if tti_minutes is not None else None,
            "evacuation_time_minutes": round(et_minutes, 1),
            "time_margin_minutes": round(tm_minutes, 1) if tm_minutes is not None else None,
            "time_margin_status": tm_status,
        })
    # 危険区域内候補除外モード（EXCLUDE_UNSAFE_CANDIDATES=true 時）
    if EXCLUDE_UNSAFE_CANDIDATES:
        filtered = [r for r in results if r["aggregate_status"] != HAZARD_DETECTED]
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


@app.api_route("/health", methods=["GET", "HEAD"])
async def health_check(request: Request):
    """公開ヘルスチェック（Phase 2-C 第5節: 固定1-key schema）。

    top-level keyは厳密に`status`だけとし、値は`"ok"`または`"degraded"`の
    2値に限定する（任意文字列は返さない）。degraded判定ロジック
    （DEM未ロード or tsunami coverage欠落）自体は従来と同一のまま維持し、
    HTTP status（両状態とも200）も変更しない——変更するのはbodyの形だけである。
    role/service/version/hostname/dataset内訳/内部dependency一覧等は
    一切返さない（これらは従来 `/health` が返していたが、operator専用の
    診断経路が別途必要ならoperator側で新設すべきであり、本節のscope外）。

    HEAD（GET/HEAD単一routeとして登録、`@app.get`+`@app.head`の2 route分離では
    "GET,HEAD /health" 1本ではなく"GET /health"と"HEAD /health"の2本に
    分裂してしまうため単一route化した）はGETと矛盾しない200＋同じheadersを
    bodyなしで返す。status値の算出結果自体はbodyがないため観測されない。
    """
    dem_loaded = elevation_service.dataset is not None
    missing_tsunami = hazard_service.get_missing_tsunami_sources()
    is_degraded = not dem_loaded or bool(missing_tsunami)
    headers = {"Cache-Control": "no-store"}
    if request.method == "HEAD":
        return Response(status_code=200, media_type="application/json", headers=headers)
    return JSONResponse(
        content={"status": "degraded" if is_degraded else "ok"},
        headers=headers,
    )


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
                "hazard_coverage_status": d.get("hazard_coverage_status", {}),
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

        # 推奨候補を選定（NO_HAZARD_RECORD > SOURCE_UNAVAILABLE > HAZARD_DETECTED の優先順位）
        best_raw, selected_tier, no_hazard_record_count = _select_recommended(raw_destinations)
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
            "hazard_coverage_status": best_raw.get("hazard_coverage_status", {}),
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
                "selected_tier": selected_tier,        # "HAZARD_DETECTED" | "NO_HAZARD_RECORD" | "SOURCE_UNAVAILABLE"
                "safe_candidates_found": no_hazard_record_count,  # NO_HAZARD_RECORD tier count（Round 12D-B以前の"safe"名称を保持、意味はNO_HAZARD_RECORD件数）
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
            hazard_coverage_status = compute_hazard_coverage_status(assessment, ALL_HAZARD_TYPE_NAMES)
            sampled_points.append({
                "lat": lat, "lon": lon,
                "hazards": point_hazards,
                "hazard_coverage_status": hazard_coverage_status,
            })

        if valid_samples == 0:
            result = calc_route_risk_score({})
            result["kikikuru_adjustment"] = calc_kikikuru_adjustment(None, {})
            result["sampled_points"] = []
            return result

        exposure_by_hazard = {k: v / valid_samples for k, v in inside_counts.items()}
        result = calc_route_risk_score(exposure_by_hazard)

        # キキクル補正 (Phase 3-B)
        kikikuru_data = request.kikikuru.model_dump() if request.kikikuru else None
        kikikuru_adj  = calc_kikikuru_adjustment(kikikuru_data, exposure_by_hazard)
        if kikikuru_adj["enabled"] and kikikuru_adj["penalty"] > 0:
            adjusted_score = max(0.0, result["safety_score"] - kikikuru_adj["penalty"])
            new_level = _route_risk_level(adjusted_score)
            # キキクル単独では danger にしない（max_level == "caution"）
            if kikikuru_adj["max_level"] == "caution" and new_level == "danger":
                new_level = "caution"
            result["safety_score"] = round(adjusted_score, 1)
            result["risk_level"]   = new_level

        if kikikuru_adj["enabled"] and kikikuru_adj.get("summary"):
            notes = result.setdefault("risk_summary", {}).setdefault("notes", [])
            if kikikuru_adj["penalty"] > 0:
                notes.append(
                    f"キキクル補正（リアルタイム）: -{kikikuru_adj['penalty']:.1f}点 / "
                    + " / ".join(kikikuru_adj["summary"])
                )
            else:
                notes.append(" / ".join(kikikuru_adj["summary"]))

        result["kikikuru_adjustment"] = kikikuru_adj
        result["sampled_points"] = sampled_points
        logger.debug(
            "route-risk: samples=%d score=%.1f level=%s kkk_penalty=%.1f",
            valid_samples, result["safety_score"], result["risk_level"],
            kikikuru_adj["penalty"],
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
            "message": "避難場所データが読み込まれていません。active_mappings / dataset registry の shelter 設定を確認してください。"
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

    uvicorn.run("app_public:app", **uvicorn_kwargs)

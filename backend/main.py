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
import os
from pathlib import Path
import csv
import json

import math

from elevation_service import ElevationService
from hazard_service import HazardService, derive_hazard_safe
from geometry_utils import calc_reachable_safe_area

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
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))
logger = logging.getLogger(__name__)


def resolve_existing_path(path_value: str, legacy_candidates: List[Path]) -> Path:
    """正本候補を優先しつつ、移行期間は legacy をフォールバックにする"""
    path = Path(path_value)
    if not path.is_absolute():
        path = BASE_DIR / path
    resolved = path.resolve()
    if resolved.exists():
        return resolved

    for candidate in legacy_candidates:
        legacy_path = candidate.resolve()
        if legacy_path.exists():
            logger.warning(
                "Canonical data_lake path not found. Falling back to legacy path: %s",
                legacy_path,
            )
            return legacy_path

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

# 標高サービスの初期化
dem_path_value = APP_CONFIG.get("dem.path", "../data_lake/validated/tokyo/dem/elevation.tif")
dem_path = resolve_existing_path(
    dem_path_value,
    legacy_candidates=[BASE_DIR.parent / "data" / "elevation.tif", BASE_DIR / "elevation.tif"],
)
DEM_PATH = str(dem_path)
elevation_service = ElevationService(DEM_PATH)


def parse_float(value: Any) -> Optional[float]:
    """文字列/数値をfloatに変換（失敗時はNone）"""
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_shelter_paths(path_config: Optional[str]) -> List[Path]:
    """避難場所データの設定値をPath配列へ変換"""
    default_path = BASE_DIR.parent / "data_lake" / "validated" / "tokyo" / "shelter"
    legacy_default_path = BASE_DIR.parent / "国土地理院避難所データ" / "東京" / "13000_2" / "13000_2.csv"
    if not path_config:
        if default_path.exists():
            return [default_path]
        # TODO: data_lake/validated/tokyo/shelter への移行完了後に legacy fallback を削除する。
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
            result.append(path)
            continue

        if path == default_path and legacy_default_path.exists():
            logger.warning(
                "Canonical shelter path not found. Falling back to legacy path: %s",
                legacy_default_path,
            )
            result.append(legacy_default_path)
            continue

        result.append(path)

    return result if result else ([default_path] if default_path.exists() else [legacy_default_path])


def load_emergency_shelters_from_csv(csv_path: Path, shelters: List[Dict[str, Any]], seen: set) -> None:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = (
                row.get("施設・場所名")
                or row.get("name")
                or row.get("名称")
                or row.get("施設名")
                or ""
            ).strip()
            address = (row.get("住所") or row.get("address") or "").strip()
            lat = parse_float(row.get("緯度") or row.get("lat"))
            lon = parse_float(row.get("経度") or row.get("lon"))

            if lat is None or lon is None:
                continue

            designation = (row.get("designation") or "指定緊急避難場所").strip()
            if designation and designation not in ("指定緊急避難場所", "緊急避難場所"):
                continue

            key = (name, round(lat, 7), round(lon, 7), designation)
            if key in seen:
                continue
            seen.add(key)

            shelters.append({
                "name": name or "名称未設定",
                "address": address,
                "lat": lat,
                "lon": lon,
                "designation": designation or "指定緊急避難場所",
                "source_file": str(csv_path.relative_to(BASE_DIR.parent)) if csv_path.is_relative_to(BASE_DIR.parent) else str(csv_path)
            })


def load_emergency_shelters_from_geojson(geojson_path: Path, shelters: List[Dict[str, Any]], seen: set) -> None:
    with geojson_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if data.get("type") != "FeatureCollection":
        logger.warning("GeoJSON shelter source is not a FeatureCollection: %s", geojson_path)
        return

    for feature in data.get("features", []):
        properties = feature.get("properties", {}) or {}
        geometry = feature.get("geometry", {}) or {}
        coordinates = geometry.get("coordinates")
        if geometry.get("type") != "Point" or not isinstance(coordinates, list) or len(coordinates) < 2:
            continue

        lon = parse_float(coordinates[0])
        lat = parse_float(coordinates[1])
        if lat is None or lon is None:
            continue

        name = (
            properties.get("施設・場所名")
            or properties.get("name")
            or properties.get("名称")
            or properties.get("施設名")
            or "名称未設定"
        ).strip()
        address = (
            properties.get("住所")
            or properties.get("address")
            or properties.get("所在地")
            or ""
        ).strip()
        designation = (
            properties.get("designation")
            or properties.get("指定区分")
            or "指定緊急避難場所"
        ).strip()

        if designation and designation not in ("指定緊急避難場所", "緊急避難場所"):
            continue

        key = (name, round(lat, 7), round(lon, 7), designation)
        if key in seen:
            continue
        seen.add(key)

        shelters.append({
            "name": name,
            "address": address,
            "lat": lat,
            "lon": lon,
            "designation": designation or "指定緊急避難場所",
            "source_file": str(geojson_path.relative_to(BASE_DIR.parent)) if geojson_path.is_relative_to(BASE_DIR.parent) else str(geojson_path)
        })


def load_emergency_shelters(paths: List[Path]) -> List[Dict[str, Any]]:
    """指定された CSV / GeoJSON 群から指定緊急避難場所を読み込む"""
    shelters: List[Dict[str, Any]] = []
    seen = set()

    for path in paths:
        if path.is_dir():
            data_paths = sorted(list(path.rglob("*.geojson")) + list(path.rglob("*.csv")))
        else:
            data_paths = [path]

        for data_path in data_paths:
            if not data_path.exists():
                logger.warning(f"避難場所データが見つかりません: {data_path}")
                continue

            try:
                if data_path.suffix.lower() == ".csv":
                    load_emergency_shelters_from_csv(data_path, shelters, seen)
                elif data_path.suffix.lower() == ".geojson":
                    load_emergency_shelters_from_geojson(data_path, shelters, seen)
            except Exception as e:
                logger.error(f"避難場所データの読み込みに失敗しました: {data_path} error={e}")

    logger.info(f"避難場所データ読み込み件数: {len(shelters)}")
    return shelters


SHELTER_CSV_PATHS = parse_shelter_paths(APP_CONFIG.get("evacuation.sites.path"))
EMERGENCY_SHELTERS = load_emergency_shelters(SHELTER_CSV_PATHS)

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
    _flood_check_path_value = APP_CONFIG.get(
        "hazard.flood.check_path",
        "../data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl",
    )
    _flood_check_path = resolve_existing_path(_flood_check_path_value, legacy_candidates=[])
    hazard_service.load_geojsonl("flood", _flood_check_path)
else:
    logger.info("洪水ハザード判定は無効（hazard.flood.enabled=false）")

# storm_surge: 高潮浸水想定区域（東京都）
_storm_surge_path_value = APP_CONFIG.get(
    "hazard.storm_surge.path",
    "../data_lake/normalized/tokyo/storm_surge/tokyo_storm_surge.geojson",
)
_storm_surge_path = resolve_existing_path(_storm_surge_path_value, legacy_candidates=[])
hazard_service.load("storm_surge", _storm_surge_path)

# tsunami: targets 設定に従ってファイルを個別ロード
# デフォルト: tokyo のみ（東京版 v1 標準モード）
# 広域モード: hazard.tsunami.targets=tokyo,kanagawa,chiba
_tsunami_dir_value = APP_CONFIG.get(
    "hazard.tsunami.dir",
    "../data_lake/normalized/tokyo/tsunami",
)
_tsunami_dir = Path(_tsunami_dir_value)
if not _tsunami_dir.is_absolute():
    _tsunami_dir = (BASE_DIR / _tsunami_dir).resolve()

_tsunami_validated_dir = BASE_DIR.parent / "data_lake" / "validated" / "tokyo" / "tsunami"
_tsunami_targets = parse_csv(APP_CONFIG.get("hazard.tsunami.targets", "tokyo"), ["tokyo"])

logger.info("Loading tsunami hazard targets: %s", ", ".join(_tsunami_targets))

for _target in _tsunami_targets:
    _filename = f"tsunami_{_target}.geojson"
    # validated を優先、なければ normalized にフォールバック
    _validated_path = _tsunami_validated_dir / _filename
    _normalized_path = _tsunami_dir / _filename
    if _validated_path.exists():
        logger.info("Tsunami source (validated): %s", _filename)
        hazard_service.load("tsunami", _validated_path)
    elif _normalized_path.exists():
        logger.info("Tsunami source (normalized): %s", _filename)
        hazard_service.load("tsunami", _normalized_path)
    else:
        logger.warning(
            "Tsunami file not found for target '%s': checked %s and %s — skipped",
            _target, _validated_path, _normalized_path,
        )

# APIサーバー設定
API_HOST = APP_CONFIG.get("api.host", "0.0.0.0")
try:
    API_PORT = int(APP_CONFIG.get("api.port", "8000"))
except ValueError:
    API_PORT = 8000
API_RELOAD = parse_bool(APP_CONFIG.get("api.reload"), True)
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


class ElevationProfileRequest(BaseModel):
    """標高プロファイル取得リクエスト"""
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    num_points: int = Field(default=50, ge=10, le=200)


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
        hazard_polygon_store=hazard_service.get_polygon_store(),
    )
    return {
        "enabled": True,
        "radius_m": result["radius_m"],
        "time_to_impact_minutes": round(tti_minutes, 1),
        "walking_speed_mps": WALKING_SPEED_MPS,
        "area_m2": result["area_m2"],
        "exists": result["exists"],
        "geometry": result.get("geometry"),
    }


def _calc_tti_minutes(lat: float, lon: float) -> Optional[float]:
    """
    現在地の津波到達時間（分）を近似計算する。

    計算方法（v1 案A）:
      現在地が入っている津波ポリゴンの重心を「危険源」とみなし、
      そこまでの距離を津波速度で割って TTI（分）を算出する。
      ポリゴン外縁に近いほど TTI は長く（余裕あり）、
      重心に近いほど TTI は短い（余裕なし）。

    現在地が津波ポリゴン外、またはデータ未ロード / ENABLE_TIME_MARGIN=false の場合は None。
    """
    if not ENABLE_TIME_MARGIN:
        return None
    dist_m = hazard_service.get_tsunami_centroid_distance_m(lat, lon)
    if dist_m is None:
        return None
    speed_m_per_min = TSUNAMI_SPEED_KMH * 1000.0 / 60.0
    return dist_m / speed_m_per_min


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


def _calc_safety_score(
    elevation_gain: float,
    distance: float,
    max_distance: float,
    hazard_safe: Optional[bool],
    time_margin_status: str = "unknown",
) -> float:
    """
    安全性スコア計算 (基礎 0-100、hazard_safe + time_margin に応じて補正)。

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
    """
    elevation_score = min(elevation_gain / 30.0 * 50, 50)
    distance_score = max(50 - (distance / max_distance * 50), 0)
    base_score = elevation_score + distance_score
    if hazard_safe is True:
        penalty = 0.0
    elif hazard_safe is False:
        penalty = HAZARD_UNSAFE_PENALTY
    else:
        penalty = HAZARD_UNKNOWN_PENALTY
    time_bonus = _time_margin_score_bonus(time_margin_status)
    return base_score - penalty + time_bonus


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
) -> List[Dict[str, Any]]:
    """
    避難所ベースで避難候補を検索する。

    各避難所に対して:
    - 距離フィルタ
    - DEM から標高取得・標高差フィルタ
    - 安全性スコア算出（hazard_safe + time_margin 補正）
    - ハザード安全判定

    Args:
        tti_minutes: 現在地の津波到達時間（分）。None = 算定不能。

    Returns:
        安全性スコア降順で最大10件
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

        safety_score = _calc_safety_score(
            elevation_gain, distance, max_distance, hazard_safe, tm_status
        )

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
    return candidates[:10]


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

        safety_score = _calc_safety_score(
            d["elevation_gain"], d["distance"], max_distance, hazard_safe, tm_status
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
    return {
        "status": "healthy" if dem_loaded else "degraded",
        "dem_loaded": dem_loaded,
        "dem_path": str(elevation_service.dem_path),
        "hazard_loaded": loaded_hazards,
        "hazard_polygon_counts": hazard_info,
        "hazard_sources": hazard_sources,
        "shelters_loaded": len(EMERGENCY_SHELTERS),
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
        logger.error(f"標高取得エラー: {e}")
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
        hazard_status = hazard_service.check_hazards(lat, lon)
        hazard_assessment = hazard_service.assess_candidate(lat, lon)
        return {
            "lat": lat,
            "lon": lon,
            "is_danger": hazard_status["is_danger"],
            "hazards": hazard_status["hazards"],
            "hazard_assessment": hazard_assessment,
        }
    except Exception as e:
        logger.error(f"ハザード判定エラー: {e}")
        raise HTTPException(status_code=500, detail="ハザード判定中に内部エラーが発生しました")


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
        # 現在地の標高を確認
        current_elevation = elevation_service.get_elevation_interpolated(
            request.lat, request.lon
        )

        if current_elevation is None:
            raise HTTPException(
                status_code=404,
                detail="現在地の標高データが見つかりません",
            )

        # 現在地のハザード判定
        hazard_status = hazard_service.check_hazards(request.lat, request.lon)

        # Time Margin: 現在地の津波到達時間を一度だけ計算（候補全件で共有）
        tti_minutes = _calc_tti_minutes(request.lat, request.lon)
        if tti_minutes is not None:
            logger.info(
                "TTI computed: lat=%.5f lon=%.5f tti=%.1f min (tsunami speed=%.0f km/h)",
                request.lat, request.lon, tti_minutes, TSUNAMI_SPEED_KMH,
            )
        else:
            logger.debug("TTI: not in tsunami polygon or data not loaded — time margin disabled")

        # Reachable Safe Area: TTI がある場合のみ算出
        if ENABLE_RSA and tti_minutes is not None:
            rsa_result = _calc_rsa(request.lat, request.lon, tti_minutes)
        else:
            rsa_result = {
                "enabled": ENABLE_RSA,
                "radius_m": None,
                "time_to_impact_minutes": round(tti_minutes, 1) if tti_minutes is not None else None,
                "walking_speed_mps": WALKING_SPEED_MPS,
                "area_m2": None,
                "exists": None,
                "geometry": None,
            }

        # 避難候補を検索
        # 避難所データがあれば shelter ベース、なければグリッドフォールバック
        if EMERGENCY_SHELTERS:
            raw_destinations = search_shelter_destinations(
                current_lat=request.lat,
                current_lon=request.lon,
                current_elevation=current_elevation,
                shelters=EMERGENCY_SHELTERS,
                elev_service=elevation_service,
                haz_service=hazard_service,
                min_elevation_gain=request.min_elevation_gain,
                max_distance=request.max_distance,
                transport_mode=request.transport_mode,
                tti_minutes=tti_minutes,
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

        return {
            "current_location": {
                "lat": request.lat,
                "lon": request.lon,
                "elevation": round(current_elevation, 2),
            },
            "hazard_status": hazard_status,
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
        logger.error(f"避難目的地検索エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


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
        logger.error(f"標高プロファイル取得エラー: {e}")
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
    if not EMERGENCY_SHELTERS:
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
            s for s in EMERGENCY_SHELTERS
            if south <= s["lat"] <= north and west <= s["lon"] <= east
        ]
    else:
        filtered = EMERGENCY_SHELTERS

    data = filtered[:limit]

    return {
        "count": len(data),
        "total_count": len(filtered),
        "data": data
    }


if __name__ == "__main__":
    import uvicorn
    
    # 開発サーバーの起動
    uvicorn.run(
        "main:app",
        host=API_HOST,
        port=API_PORT,
        reload=API_RELOAD,
        log_level=API_LOG_LEVEL
    )

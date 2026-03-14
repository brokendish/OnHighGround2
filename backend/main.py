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

from elevation_service import ElevationService

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
    """避難場所CSVの設定値をPath配列へ変換"""
    default_path = BASE_DIR.parent / "国土地理院避難所データ" / "東京" / "13000_2" / "13000_2.csv"
    if not path_config:
        return [default_path]

    result: List[Path] = []
    for raw_item in path_config.split(","):
        item = raw_item.strip()
        if not item:
            continue
        path = Path(item)
        if not path.is_absolute():
            path = (BASE_DIR / path).resolve()
        result.append(path)

    return result if result else [default_path]


def load_emergency_shelters(paths: List[Path]) -> List[Dict[str, Any]]:
    """指定されたCSV群から指定緊急避難場所を読み込む"""
    shelters: List[Dict[str, Any]] = []
    seen = set()

    for path in paths:
        if path.is_dir():
            csv_paths = sorted(path.rglob("*.csv"))
        else:
            csv_paths = [path]

        for csv_path in csv_paths:
            if not csv_path.exists():
                logger.warning(f"避難場所CSVが見つかりません: {csv_path}")
                continue

            try:
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

                        # 変換済みCSVは指定区分を参照、国土地理院の元CSVは本データ種別として採用
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
            except Exception as e:
                logger.error(f"避難場所CSVの読み込みに失敗しました: {csv_path} error={e}")

    logger.info(f"避難場所データ読み込み件数: {len(shelters)}")
    return shelters


SHELTER_CSV_PATHS = parse_shelter_paths(APP_CONFIG.get("evacuation.sites.path"))
EMERGENCY_SHELTERS = load_emergency_shelters(SHELTER_CSV_PATHS)

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
    lat: float
    lon: float
    elevation: float
    elevation_gain: float
    distance: float
    estimated_time_minutes: float
    safety_score: float


class ElevationProfileRequest(BaseModel):
    """標高プロファイル取得リクエスト"""
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float
    num_points: int = Field(default=50, ge=10, le=200)


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
    return {
        "status": "healthy" if dem_loaded else "degraded",
        "dem_loaded": dem_loaded,
        "dem_path": str(elevation_service.dem_path)
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
        elevation = elevation_service.get_elevation_interpolated(lat, lon)
        
        if elevation is None:
            raise HTTPException(
                status_code=404,
                detail="指定座標の標高データが見つかりません"
            )
        
        return {
            "lat": lat,
            "lon": lon,
            "elevation": round(elevation, 2),
            "unit": "meters"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"標高取得エラー: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/evacuation")
async def find_evacuation_destinations(request: EvacuationRequest):
    """
    避難目的地を検索
    
    Args:
        request: 避難目的地検索リクエスト
        
    Returns:
        避難目的地候補のリスト
    """
    try:
        # 現在地の標高を確認
        current_elevation = elevation_service.get_elevation_interpolated(
            request.lat, request.lon
        )
        
        if current_elevation is None:
            raise HTTPException(
                status_code=404,
                detail="現在地の標高データが見つかりません"
            )
        
        # 避難目的地を検索
        destinations = elevation_service.find_evacuation_destinations(
            current_lat=request.lat,
            current_lon=request.lon,
            min_elevation_gain=request.min_elevation_gain,
            max_distance=request.max_distance,
            transport_mode=request.transport_mode
        )
        
        if not destinations:
            return {
                "current_location": {
                    "lat": request.lat,
                    "lon": request.lon,
                    "elevation": round(current_elevation, 2)
                },
                "destinations": [],
                "message": "指定条件で避難目的地が見つかりませんでした"
            }
        
        return {
            "current_location": {
                "lat": request.lat,
                "lon": request.lon,
                "elevation": round(current_elevation, 2)
            },
            "destinations": [
                {
                    "lat": d["lat"],
                    "lon": d["lon"],
                    "elevation": round(d["elevation"], 2),
                    "elevation_gain": round(d["elevation_gain"], 2),
                    "distance": round(d["distance"], 2),
                    "estimated_time_minutes": round(d["estimated_time_minutes"], 1),
                    "safety_score": round(d["safety_score"], 1)
                }
                for d in destinations
            ],
            "search_parameters": {
                "transport_mode": request.transport_mode,
                "max_distance": request.max_distance,
                "min_elevation_gain": request.min_elevation_gain
            }
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

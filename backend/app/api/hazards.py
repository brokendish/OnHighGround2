import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException

from app.services.hazard_dataset_service import HazardDatasetService


router = APIRouter(prefix="/api/hazards", tags=["hazards"])
hazard_dataset_service = HazardDatasetService()

# ── inland_flood 直接配信 ─────────────────────────────────────────────────
# registry を経由せず data_runtime → data_lake の優先順でファイルを探す。
# registry が整備されたら HazardDatasetService に移行してよい。
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/

# ── 検索ディレクトリ定義 ──────────────────────────────────────────────────────
# normalized/ を正規参照先とし、legacy sample はフォールバック。
_INLAND_FLOOD_SEARCH_DIRS = [
    _BACKEND_DIR.parent / "data_runtime" / "backend" / "hazard" / "inland_flood",
    _BACKEND_DIR.parent / "data_lake" / "normalized" / "tokyo" / "inland_flood",
    _BACKEND_DIR.parent / "data" / "hazard",
]
_LANDSLIDE_SEARCH_DIRS = [
    _BACKEND_DIR.parent / "data_runtime" / "backend" / "hazard" / "landslide",
    _BACKEND_DIR.parent / "data_lake" / "normalized" / "tokyo" / "landslide",
    _BACKEND_DIR.parent / "data" / "hazard",
]


def _find_hazard_file(search_dirs: list[Path], name_hint: str) -> Optional[Path]:
    """search_dirs を順に検索し、最初に見つかった *.geojson を返す。
    name_hint はログ用（実際の検索には使わない）。
    """
    for dir_path in search_dirs:
        if dir_path.is_dir():
            for f in sorted(dir_path.glob("*.geojson")):
                return f
    return None


@router.get("/inland_flood/tokyo")
async def get_inland_flood_tokyo():
    """内水氾濫 GeoJSON を返す（data_runtime → data_lake の優先順）。"""
    path = _find_hazard_file(_INLAND_FLOOD_SEARCH_DIRS, "inland_flood")
    if path is None:
        raise HTTPException(status_code=404, detail="inland_flood データが見つかりません")
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/landslide/tokyo")
async def get_landslide_tokyo():
    """土砂災害警戒区域 GeoJSON を返す（data_runtime → data_lake の優先順）。"""
    path = _find_hazard_file(_LANDSLIDE_SEARCH_DIRS, "landslide")
    if path is None:
        raise HTTPException(status_code=404, detail="landslide データが見つかりません")
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/active")
async def list_active_hazard_datasets():
    try:
        return hazard_dataset_service.list_active_hazard_datasets()
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{hazard_type}/{region_code}/meta")
async def get_active_hazard_meta(hazard_type: str, region_code: str):
    try:
        return hazard_dataset_service.get_active_hazard_meta(hazard_type, region_code)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{hazard_type}/{region_code}")
async def get_active_hazard_geojson(hazard_type: str, region_code: str):
    try:
        return hazard_dataset_service.get_active_hazard_geojson(hazard_type, region_code)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.services.hazard_dataset_service import HazardDatasetService


router = APIRouter(prefix="/api/hazards", tags=["hazards"])
hazard_dataset_service = HazardDatasetService()

# ── inland_flood / landslide 直接配信 ────────────────────────────────────────
# registry を経由せず data_runtime → data_lake の優先順でファイルを探す。
# registry が整備されたら HazardDatasetService に移行してよい。
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent  # backend/


def _find_hazard_file_for_region(hazard_type: str, region: str) -> Optional[Path]:
    """region / hazard_type に対応する GeoJSON ファイルを優先順で検索して返す。

    探索順序:
      1. data_runtime/backend/hazard/{type}/           ← flat runtime: {region}_*.geojson / {region}-*.geojson
         (tokyo のみ: prefix なしの単一ファイルも許容)
      2. data_runtime/backend/hazard/{type}/{region}/  ← per-region runtime subdir (将来構成・fallback)
      3. data_lake/normalized/{region}/{type}/
      4. data/hazard/                                  ← legacy (tokyo のみ)
    """
    root = _BACKEND_DIR.parent

    # 1. flat runtime dir — region-prefixed files を優先
    #    アンダースコア ({region}_*.geojson) とハイフン ({region}-*.geojson) 両方を探索する
    flat_runtime = root / "data_runtime" / "backend" / "hazard" / hazard_type
    if flat_runtime.is_dir():
        prefixed = sorted(
            list(flat_runtime.glob(f"{region}_*.geojson"))
            + list(flat_runtime.glob(f"{region}-*.geojson"))
        )
        if prefixed:
            # 最大サイズ（実データ）を優先して返す
            return max(prefixed, key=lambda p: p.stat().st_size)
        # backward compat: tokyo の場合は prefix なし単一ファイルも許容
        if region == "tokyo":
            any_files = sorted(flat_runtime.glob("*.geojson"))
            if any_files:
                return any_files[0]

    # 2. per-region runtime subdir (将来構成・fallback)
    per_region_runtime = root / "data_runtime" / "backend" / "hazard" / hazard_type / region
    if per_region_runtime.is_dir():
        for f in sorted(per_region_runtime.glob("*.geojson")):
            return f

    # 3. data_lake normalized
    normalized = root / "data_lake" / "normalized" / region / hazard_type
    if normalized.is_dir():
        for f in sorted(normalized.glob("*.geojson")):
            return f

    # 4. legacy fallback (tokyo のみ)
    if region == "tokyo":
        legacy = root / "data" / "hazard"
        if legacy.is_dir():
            for f in sorted(legacy.glob("*.geojson")):
                return f

    return None


@router.get("/inland_flood/{region}")
async def get_inland_flood(region: str):
    """内水氾濫 GeoJSON を返す（data_runtime → data_lake の優先順）。
    FileResponse でストリーミング配信するため json.load() によるメモリ全展開は行わない。
    """
    path = _find_hazard_file_for_region("inland_flood", region)
    if path is None:
        raise HTTPException(status_code=404, detail=f"inland_flood データが見つかりません: region={region}")
    return FileResponse(path, media_type="application/geo+json")


@router.get("/landslide/{region}")
async def get_landslide(region: str):
    """土砂災害警戒区域 GeoJSON を返す（data_runtime → data_lake の優先順）。
    FileResponse でストリーミング配信するため json.load() によるメモリ全展開は行わない。
    """
    path = _find_hazard_file_for_region("landslide", region)
    if path is None:
        raise HTTPException(status_code=404, detail=f"landslide データが見つかりません: region={region}")
    return FileResponse(path, media_type="application/geo+json")


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

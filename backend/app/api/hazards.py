import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from app.services.hazard_dataset_service import HazardDatasetService
from app.services import runtime_version_access


import logging

router = APIRouter(prefix="/api/hazards", tags=["hazards"])
hazard_dataset_service = HazardDatasetService()
logger = logging.getLogger(__name__)

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


async def _runtime_stream_or_none(hazard_type: str, region: str, request_kind: str):
    """Phase 2-B.5 atomic publish/leaseが利用可能な環境では、data_runtime直下を
    直接globせず current version root配下をlease保護下でstreamingする。
    未初期化環境（lease機構未適用のcompose等）・対象regionのfileがそもそも
    存在しない場合だけNoneを返し、呼び出し側が従来のdata_runtime直接参照
    （legacy fallback）を試みられるようにする（第8節）。

    CODEX P2B5-CX-004対応: 以前はここで`except Exception`により任意の
    lease機構failure（acquire失敗、file破損等）を握り潰してlegacy参照へ
    fallbackしていた。これはatomic treeが壊れている状態を検知不能にする
    fail-open挙動である。is_available()がTrueのままstream_versioned_glob()
    が例外を送出する場合は、それをそのまま呼び出し元（FastAPI）へ伝播させ、
    500として扱う（fail-closed）。「該当region/typeのfileがそもそも存在
    しない」という正常系のNoneはstream_versioned_glob()内部で判定済み。
    """
    if not runtime_version_access.is_available():
        return None
    return await runtime_version_access.stream_versioned_glob(
        f"backend/hazard/{hazard_type}",
        [f"{region}_*.geojson", f"{region}-*.geojson"],
        f"http-hazard-{hazard_type}",
    )


@router.get("/inland_flood/{region}")
async def get_inland_flood(region: str):
    """内水氾濫 GeoJSON を返す（lease保護されたdata_runtime current → data_lake の優先順）。
    StreamingResponse/FileResponse でストリーミング配信するため json.load() によるメモリ全展開は行わない。
    """
    stream = await _runtime_stream_or_none("inland_flood", region, "http-hazard-inland_flood")
    if stream is not None:
        return StreamingResponse(stream, media_type="application/geo+json")
    path = _find_hazard_file_for_region("inland_flood", region)
    if path is None:
        raise HTTPException(status_code=404, detail=f"inland_flood データが見つかりません: region={region}")
    return FileResponse(path, media_type="application/geo+json")


@router.get("/landslide/{region}")
async def get_landslide(region: str):
    """土砂災害警戒区域 GeoJSON を返す（lease保護されたdata_runtime current → data_lake の優先順）。
    StreamingResponse/FileResponse でストリーミング配信するため json.load() によるメモリ全展開は行わない。
    """
    stream = await _runtime_stream_or_none("landslide", region, "http-hazard-landslide")
    if stream is not None:
        return StreamingResponse(stream, media_type="application/geo+json")
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

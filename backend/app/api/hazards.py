import json
import sqlite3
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

# ── Martin tileset ID / source-layer 解決 ────────────────────────────────────
# tileset_id_alignment修復: 過去、frontendは「registryのdataset_id
# （例 TOKYO-RIVER-001）をlowercase+"_"変換したもの」または個々にhardcodeした
# 文字列（例 tokyo_river_001, tokyo_surge_001, *_001）をMartinのtileset IDと
# 仮定していた。しかしdataset_id（データ管理上の識別子）とtileset_id（配信
# artifactの実名、deploy_to_runtime.shがdata_lake/tiles/配下のmbtiles
# filenameをそのまま使う）は本来別概念であり、tile成果物の世代交代
# （例 tokyo_river_001.mbtiles → tokyo_flood_max.mbtiles）にdataset_id側が
# 追随しないと即座に不一致を起こす。この関数はMartinが実際にscanするflat
# mirror（data_runtime/frontend/tiles/<region>/<hazard_type>/）を都度
# globし、「今Martinが実際に配信できるtileset」を正本として返す。dataset_id
# 側やfrontend側のhardcode文字列を書き換え続ける代わりに、publishのたびに
# 自動的に追随させる。
_TILE_ROOT = _BACKEND_DIR.parent / "data_runtime" / "frontend" / "tiles"


def _find_tileset_for_region(hazard_type: str, region: str) -> Optional[dict]:
    """`data_runtime/frontend/tiles/<region>/<hazard_type>/*.mbtiles` から
    実際に配信可能な1件を選び、Martin source ID（filename stem）と、
    mbtiles自身のmetadataテーブルに記録されたvector layer名（tippecanoeの
    `--layer`指定、Martinのvector_layers.idと同一）を返す。該当なしはNone。
    複数fileがある場合は最大サイズを選ぶ（hazards.pyの他のfile選択と同じ規約）。
    """
    tile_dir = _TILE_ROOT / region / hazard_type
    if not tile_dir.is_dir():
        return None
    candidates = sorted(tile_dir.glob("*.mbtiles"))
    if not candidates:
        return None
    chosen = max(candidates, key=lambda p: p.stat().st_size)

    source_layer: Optional[str] = None
    try:
        conn = sqlite3.connect(f"file:{chosen.resolve()}?mode=ro", uri=True)
        try:
            row = conn.execute("SELECT value FROM metadata WHERE name = 'json'").fetchone()
            if row:
                layers = json.loads(row[0]).get("vector_layers") or []
                if layers and isinstance(layers[0], dict):
                    source_layer = layers[0].get("id")
        finally:
            conn.close()
    except (sqlite3.DatabaseError, OSError, json.JSONDecodeError):
        source_layer = None

    return {"tileset_id": chosen.stem, "source_layer": source_layer}


def _find_hazard_file_for_region(hazard_type: str, region: str) -> Optional[Path]:
    """region / hazard_type に対応する GeoJSON ファイルを優先順で検索して返す。

    探索順序:
      1. registry-driven一意解決（HazardDatasetService._resolve_active_dataset()
         と同一ロジック: active_mappings → dataset_definitions →
         DatasetState.current_runtime_path）
      2. data_runtime/backend/hazard/{type}/{region}/  ← per-region runtime subdir (将来構成・fallback)
      3. data_lake/normalized/{region}/{type}/
      4. data/hazard/                                  ← legacy (tokyo のみ)

    HAZARD-FLAT-FALLBACK-LEGACY-SIZE-SELECTION-RISK対応: 従来の1.は
    flat runtime dir配下を{region}_*.geojson / {region}-*.geojsonでglobし
    「最大サイズ」を選んでいた。この方式は、旧世代（legacy）artifactが
    たまたま現行artifactより大きい場合に誤って選択してしまう構造的
    リスクを持つ（実機確認: landslide/tokyo_landslide_A33.geojson(legacy,
    30,860,419 bytes) が landslide/tokyo-landslide-001.geojson(現行,
    28,760,177 bytes)より大きい）。同じactive datasetを別ルールで二重に
    解決しないよう、HazardDatasetServiceが既に持つ
    「active_mappings→registry→DatasetState.current_runtime_path」という
    一意解決ロジックをそのまま再利用する（新規service統合はしない、
    既存privateメソッドの呼び出しのみ）。これで解決できない場合
    （registry未整備・active dataset未登録等、真にactiveなdatasetが
    存在しない場合）のみ、旧来のdirectory scanへ縮退する。
    """
    try:
        _, _, _, active_path = hazard_dataset_service._resolve_active_dataset(hazard_type, region)
        if active_path.is_file():
            return active_path
    except (KeyError, FileNotFoundError):
        pass

    root = _BACKEND_DIR.parent

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


# Residual Finding Remediation 04（PUBLIC-ERROR-DETAIL-LEAK）: OSError/ValueError
# はfilesystem path・errno文字列を内包する場合があり（例:
# "[Errno 13] Permission denied: '/data_runtime/...'"）、str(exc)をそのまま
# public responseへ返すと内部runtime layoutが未認証clientへ露出する。
# 404（FileNotFoundError/KeyError、"dataset未登録"等のdomain error）は
# dataset_id/hazard_type/regionという不透明な識別子のみを含み、filesystem
# pathを含まないため既存のstr(exc)契約を維持する。500側のみ、この定型
# messageへ差し替え、実例外はlogger.exception()でserver-side診断用に残す。
_HAZARD_INTERNAL_ERROR_DETAIL = "Hazard data is temporarily unavailable"


@router.get("/active")
async def list_active_hazard_datasets():
    try:
        return hazard_dataset_service.list_active_hazard_datasets()
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        logger.exception("active hazard dataset list error")
        raise HTTPException(status_code=500, detail=_HAZARD_INTERNAL_ERROR_DETAIL) from exc


@router.get("/{hazard_type}/{region_code}/meta")
async def get_active_hazard_meta(hazard_type: str, region_code: str):
    try:
        meta = hazard_dataset_service.get_active_hazard_meta(hazard_type, region_code)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        logger.exception("hazard meta error: hazard_type=%s region_code=%s", hazard_type, region_code)
        raise HTTPException(status_code=500, detail=_HAZARD_INTERNAL_ERROR_DETAIL) from exc
    # tileset_id_alignment修復: dataset_id（registry識別子）とは独立に、
    # Martinが今実際に配信できるtileset ID/source-layerを解決して追加する。
    # 該当tileが存在しない場合は両方null（frontendはこれをapiUrl fallback、
    # またはfallbackが無いlayerではdisabled判定に使う）。
    #
    # HAZARD-META-EXCEPTION-HARDENING-GAP修復: _find_tileset_for_region()は
    # `data_runtime/frontend/tiles/`配下をtraverse/glob/statし、選ばれた
    # mbtilesをSQLiteでopenするfilesystem+sqlite処理であり、この呼び出しは
    # 従来ここ（上のtry/exceptの外）にあったため、PermissionError/OSError/
    # sqlite3.Error等がapplication-levelで一切処理されず、FastAPI/
    # Starletteのdefault 500 handlerへ素通りしていた
    # （HAZARD-META-TILESET-READ-PERMISSION-GAPの実障害時、frontend
    # ディレクトリのgroup driftによりまさにこの経路でPermissionErrorが
    # 発生していた。debug=falseによりraw leakは実証されなかったが、
    # 安全性がframework既定動作依存になっていた）。tileset lookup周辺
    # だけに絞った局所的except Exceptionで明示的に安全化する
    # （route全体は囲まない。tileset不存在自体は例外ではなくNone戻り値
    # のため、既存のnullable semanticsはこのtry/exceptの影響を受けない）。
    try:
        tileset = _find_tileset_for_region(hazard_type, region_code)
    except Exception as exc:
        logger.exception(
            "hazard tileset lookup error: hazard_type=%s region_code=%s operation=tileset_lookup",
            hazard_type, region_code,
        )
        raise HTTPException(status_code=500, detail=_HAZARD_INTERNAL_ERROR_DETAIL) from exc
    meta["tileset_id"] = tileset["tileset_id"] if tileset else None
    meta["tileset_source_layer"] = tileset["source_layer"] if tileset else None
    return meta


@router.get("/{hazard_type}/{region_code}")
async def get_active_hazard_geojson(hazard_type: str, region_code: str):
    try:
        return hazard_dataset_service.get_active_hazard_geojson(hazard_type, region_code)
    except (FileNotFoundError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        logger.exception("hazard geojson error: hazard_type=%s region_code=%s", hazard_type, region_code)
        raise HTTPException(status_code=500, detail=_HAZARD_INTERNAL_ERROR_DETAIL) from exc

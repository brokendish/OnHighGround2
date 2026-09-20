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

    HAZARD-META-TILESET-REGION-SELECTION-GAP対応（Phase B、region-prefix
    filter）: tsunamiはTokyo/Kanagawa(×2)/Chiba全てのMBTilesが物理的に
    同一directory（`tile_dir = tokyo/tsunami/`）へ同居しており、
    従来はdirectory scopingのみに頼っていたため、`region="tokyo"`の
    問い合わせに対して同居する最大サイズのChiba tilesetを誤って返す
    実バグがあった（実機確認: `chiba_tsunami_A40-18_12.mbtiles`
    34,267,136 bytes が `tokyo_tsunami_A40-23_13.mbtiles` 7,716,864 bytes
    より大きいため誤選択）。glob直後にfilenameのregion接頭辞
    （`{region}_`/`{region}-`）でfilterしてから、既存の最大サイズ
    selectorを適用する。`not_tokyo_xxx.mbtiles`のような偽陽性
    （substring anywhere一致）を避けるため、`startswith()`による
    厳密な接頭辞一致のみを判定基準とする。

    他5 hazard type（flood/storm_surge/pseudo_inland_flood/
    lowland_poor_drainage/inland_flood）は、region毎に専用directoryへ
    正しく分離済み（Phase A実機inventoryで確認）で、かつ全MBTilesが
    既にregion接頭辞命名に従っているため、このfilterは既存の選択結果を
    一切変更しない（無害な拡張）。

    Kanagawaのtsunami（`kanagawa/tsunami/`directory自体が存在しない）や
    Chiba（backend active dataset未登録、`get_active_hazard_meta()`の
    registry checkがこの関数へ到達する前に404を返す）は、今回のfilter
    追加では解決しない——directory自体が無ければ従来通りNoneのまま
    （HAZARD-META-MULTI-TILESET-CONTRACT-GAPとして別途deferred）。
    """
    tile_dir = _TILE_ROOT / region / hazard_type
    if not tile_dir.is_dir():
        return None
    all_candidates = sorted(tile_dir.glob("*.mbtiles"))
    candidates = [
        p for p in all_candidates
        if p.stem == region or p.stem.startswith(f"{region}_") or p.stem.startswith(f"{region}-")
    ]
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
    except (sqlite3.DatabaseError, OSError, json.JSONDecodeError) as exc:
        # RUNTIME-MBTILES-GROUP-CONTRACT: 従来は握り潰しており、mbtilesが
        # backend-publicから読めない（group/mode契約違反）場合にも無音で
        # source_layer=Noneになっていた（実機でstorm_surge/flood/tsunamiの
        # tileset_source_layerがnullになった原因の特定を著しく難しくした）。
        # 返り値仕様（source_layer=None）は変えず、server-side logにだけ残す
        # （HTTP responseへは出さないためpathは漏れない）。
        logger.warning(
            "hazard tileset metadata unreadable: hazard_type=%s region=%s tileset=%s error=%s: %s",
            hazard_type, region, chosen.name, type(exc).__name__, exc,
        )
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

    TSUNAMI-FALLBACK-STREAMING Phase B1対応: `region`指定によるregion-
    subdirectory primary解決（inland_flood/landslide/storm_surgeが使う
    `{type}/{region}/{file}`layout）は、tsunamiには一致しない。tsunamiは
    `HazardDatasetService._resolve_current_hazard_file()`の既存docstringに
    明記されている通り、region直下フラット命名かつregion**接尾辞**
    （`tsunami_{region}.geojson`、他typeのregion**接頭辞**とは逆）を使う
    （VPS実機`find`で実際に確認済み: `tsunami_tokyo.geojson`/
    `tsunami_kanagawa.geojson`、region subdirectory無し）。このため
    `stream_versioned_glob()`のlegacy direct-child glob（region-subdirectory
    が一致しない場合のfallback）へ渡すpatternsに接尾辞形
    （`*_{region}.geojson`）を追加し、`_resolve_current_hazard_file()`が
    既に使っている3パターン構成と一致させる。tsunami以外のtype（接尾辞
    命名を使わない）にとっては、region-subdirectory側で先に解決が完了する
    ため、この追加patternが実際にglobされることはない（無害な拡張）。
    """
    if not runtime_version_access.is_available():
        return None
    return await runtime_version_access.stream_versioned_glob(
        f"backend/hazard/{hazard_type}",
        [f"{region}_*.geojson", f"{region}-*.geojson", f"*_{region}.geojson"],
        f"http-hazard-{hazard_type}",
        region=region,
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


@router.get("/storm_surge/{region}")
async def get_storm_surge(region: str):
    """高潮浸水想定 GeoJSON を返す（lease保護されたdata_runtime current → data_lake の優先順）。

    STORM-SURGE-FALLBACK-STREAMING Phase B1（RUNTIME-VERSION-STREAM-REGION-
    LAYOUT-GAP修正で正しく機能するようになったcurrent/versioned優先の
    streaming helperをstorm_surgeへ適用）: 従来はcatch-all route
    （get_active_hazard_geojson）経由で`json.load()`によるfull memory
    展開＋FastAPI JSONResponseの再シリアライズが発生していた
    （tokyo≈54MB/kanagawa≈82MB、LARGE-HAZARD-GEOJSON-SWAP-THRASH対応で
    flood同様の懸念が指摘されていた）。inland_flood/landslideと同一の
    streaming pattern（StreamingResponse/FileResponse）をこのroute専用に
    適用し、json.load()を一切発生させない。

    content-type: 既存のstorm_surge public contractからの変化を最小化する
    ため`application/json`を使う（catch-all route時代のFastAPI default
    JSONResponseと同じ）。inland_flood/landslideが使う
    `application/geo+json`はここでは踏襲しない（両者は独立した既存
    precedentであり、本routeが新たに`application/geo+json`へ揃える理由は
    ない——OWNER Gate参照）。
    """
    stream = await _runtime_stream_or_none("storm_surge", region, "http-hazard-storm_surge")
    if stream is not None:
        return StreamingResponse(stream, media_type="application/json")
    path = _find_hazard_file_for_region("storm_surge", region)
    if path is None:
        raise HTTPException(status_code=404, detail=f"storm_surge データが見つかりません: region={region}")
    return FileResponse(path, media_type="application/json")


@router.get("/tsunami/{region}")
async def get_tsunami(region: str):
    """津波浸水想定 GeoJSON を返す（lease保護されたdata_runtime current → data_lake の優先順）。

    TSUNAMI-FALLBACK-STREAMING Phase B1（storm_surgeで確立済みのpatternを
    横展開）: 従来はcatch-all route（get_active_hazard_geojson）経由で
    `json.load()`によるfull memory展開＋FastAPI JSONResponseの再
    シリアライズが発生していた。frontendは既にtile-first
    （`useStaticVectorTiles`）でこのrouteをtile失敗時のfallbackとしてのみ
    呼ぶため、normal pathには影響しないが、fallback時のmemory安全性は
    storm_surge同様の懸念があった。inland_flood/landslide/storm_surgeと
    同一のstreaming pattern（StreamingResponse/FileResponse）を適用する。

    region layoutの違い: tsunamiのcurrent/versioned artifactは
    region-subdirectoryではなく`tsunami_{region}.geojson`という
    region接尾辞のflat命名（`_runtime_stream_or_none()`のdocstring・
    `HazardDatasetService._resolve_current_hazard_file()`のdocstring
    参照）。`_runtime_stream_or_none()`のlegacy glob patternsに接尾辞形を
    追加済みのため、`stream_versioned_glob()`の呼び出し自体は他typeと
    完全に同一で対応できる。

    Chiba: backend側にactive datasetが未登録（frontend tileのみ存在）の
    ため、versioned/flatとも一致せず既存の404 semanticsをそのまま維持する
    （Chiba用artifactを新設・代替探索しない）。

    content-type: storm_surgeと同一方針で`application/json`を維持する
    （既存catch-all contractからの変化を最小化）。
    """
    stream = await _runtime_stream_or_none("tsunami", region, "http-hazard-tsunami")
    if stream is not None:
        return StreamingResponse(stream, media_type="application/json")
    path = _find_hazard_file_for_region("tsunami", region)
    if path is None:
        raise HTTPException(status_code=404, detail=f"tsunami データが見つかりません: region={region}")
    return FileResponse(path, media_type="application/json")


# Residual Finding Remediation 04（PUBLIC-ERROR-DETAIL-LEAK）: OSError/ValueError
# はfilesystem path・errno文字列を内包する場合があり（例:
# "[Errno 13] Permission denied: '/data_runtime/...'"）、str(exc)をそのまま
# public responseへ返すと内部runtime layoutが未認証clientへ露出する。
# 404（FileNotFoundError/KeyError、"dataset未登録"等のdomain error）は
# dataset_id/hazard_type/regionという不透明な識別子のみを含み、filesystem
# pathを含まないため既存のstr(exc)契約を維持する。500側のみ、この定型
# messageへ差し替え、実例外はlogger.exception()でserver-side診断用に残す。
_HAZARD_INTERNAL_ERROR_DETAIL = "Hazard data is temporarily unavailable"

# LARGE-HAZARD-GEOJSON-SWAP-THRASH対応: 一部hazard typeのcurrent active
# artifactは数百MB規模（例: flood/tokyo ≈500MB）に達し、catch-all route
# （下記 get_active_hazard_geojson）がjson.load()でfull memory展開した上で
# FastAPIのJSONResponseが再度シリアライズするため、severeなmemory/swap
# thrashを引き起こした実績がある（OWNER Phase A investigation）。
# Phase B1（OWNER承認2026-09-07、スコープ最小: flood typeのみ）として、
# 対象typeはfileへ一切触れず（json.load()を発生させず）413を返す。
# 他type（storm_surge/tsunami/pseudo_inland_flood/lowland_poor_drainage）は
# 今回のスコープ外（KEEP FOR NOW/FOLLOW-UP、別途OWNER判断）。
_HAZARD_LARGE_RESPONSE_LIMITED_TYPES = frozenset({"flood"})
_HAZARD_LARGE_RESPONSE_DETAIL = (
    "Full GeoJSON response for this hazard type is not available due to its size. "
    "Use /api/hazards/{hazard_type}/{region_code}/meta for tileset information."
)

# LARGE-HAZARD-FULL-BODY-POLICY Phase B1（OWNER承認2026-09-07、HYBRID_POLICY）:
# pseudo_inland_flood/lowland_poor_drainageは、上記floodとは**異なる理由**で
# public full-body responseを提供しない——サイズが理由ではなく（lowlandは
# 約25MB、floodの~500MBとは無関係）、frontendがこのroute自体を一切呼ばない
# （apiUrl未設定、tile-onlyで運用）ことと、tile infrastructureが両regionとも
# 完備していることによるdelivery-policy上の判断（外部公開downloadとしての
# 用途も未確認）。floodと理由が異なるため、HTTP status・detail文言とも
# 413/_HAZARD_LARGE_RESPONSE_DETAILを機械的に流用しない。
#
# HTTP status選定（422 Unprocessable Entity）:
#   - 404不採用: 対象datasetは実在する（存在しないdatasetは引き続き404）。
#   - 413不採用: sizeが理由ではない（機械的な流用はfloodの理由と意味的に
#     矛盾する）。
#   - 403不採用: 認証/認可が理由ではない。
#   - 409不採用: リソースの一時的な状態競合ではなく、恒久的なdelivery
#     policyである。
#   422は「requestは理解できる（syntax・対象resourceとも正当）が、この形
#   （full-body representation）では提供しない」という意味を、標準status
#   code群の中で最も適切に表す。
_HAZARD_POLICY_REJECTED_TYPES = frozenset({
    "pseudo_inland_flood",
    "lowland_poor_drainage",
})
_HAZARD_POLICY_REJECTED_DETAIL = (
    "Full GeoJSON response is not available for this hazard type. "
    "Use /api/hazards/{hazard_type}/{region_code}/meta for tileset information."
)


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
    """全7 hazard type（`HazardDatasetService.HAZARD_LAYER_TYPES`）は、
    上記のreject分岐（flood/pseudo_inland_flood/lowland_poor_drainage）
    または本routeより前に登録済みの専用streaming route
    （inland_flood/landslide/storm_surge/tsunami）のいずれかへ既に
    吸収されている（`tests/test_hazard_public_catchall_dead_path.py::
    test_reject_and_dedicated_route_types_cover_all_known_hazard_types`
    で静的に固定）。したがってこの関数本体へ実際に到達する
    `hazard_type`は、常に「未対応/未登録」である。

    HAZARD-PUBLIC-CATCHALL-JSONLOAD-DEAD-PATH対応: 従来はここで
    `hazard_dataset_service.get_active_hazard_geojson()`
    （`json.load()`によるfull memory展開を伴う）を呼び出していたが、
    上記の理由によりこの呼び出しがfile読み込みまで到達することは
    構造的にあり得なかった（`HAZARD_LAYER_TYPES`に無いhazard_typeは
    サービス側の`if hazard_type not in self.HAZARD_LAYER_TYPES`
    ガードで即座にKeyErrorになり、`json.load()`前段で必ず止まる）。
    この呼び出し自体を除去し、明示的な404を返すことで、
    「HAZARD_LAYER_TYPESに将来型を追加したが専用route/reject分岐の
    追加を忘れた」場合でも、危険なfull-body loadへ暗黙にfallbackせず
    fail-closedになるようにする（本remediation系列で一貫して採用して
    きた設計方針）。`HazardDatasetService.get_active_hazard_geojson()`
    自体は他の実consumer（`HazardDatasetService`の直接単体テスト群、
    current/versioned優先解決contractの検証）があるため削除しない。

    既存の「Unsupported hazard_type」404 contract（`KeyError`の
    `str()`表現——前後の引用符を含む——をそのまま`detail`へ使う挙動）は、
    呼び出し元を変えずに再現し、後方互換を維持する。
    """
    if hazard_type in _HAZARD_LARGE_RESPONSE_LIMITED_TYPES or hazard_type in _HAZARD_POLICY_REJECTED_TYPES:
        # public full-body拒否対象（理由はtype毎に異なる——上記コメント参照）:
        # active datasetの存在確認のみ行い（404判定のため）、file内容も
        # Pathそのものも一切受け取らない（json.load()を発生させず、
        # lease-protected pathをこのroute層より外へ公開しない）。
        try:
            hazard_dataset_service.has_active_hazard_dataset(hazard_type, region_code)
        except (FileNotFoundError, KeyError) as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            logger.exception("hazard geojson error: hazard_type=%s region_code=%s", hazard_type, region_code)
            raise HTTPException(status_code=500, detail=_HAZARD_INTERNAL_ERROR_DETAIL) from exc

        if hazard_type in _HAZARD_LARGE_RESPONSE_LIMITED_TYPES:
            raise HTTPException(status_code=413, detail=_HAZARD_LARGE_RESPONSE_DETAIL)
        raise HTTPException(status_code=422, detail=_HAZARD_POLICY_REJECTED_DETAIL)

    raise HTTPException(status_code=404, detail=str(KeyError(f"Unsupported hazard_type: {hazard_type}")))

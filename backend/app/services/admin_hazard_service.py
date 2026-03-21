"""
admin_hazard_service.py — ハザードレイヤー管理情報の集約サービス

【Single Source of Truth】
  _LAYER_DEFINITIONS がハザードレイヤーの正式な定義源。
  admin API はここから情報を組み立てて返す。

  frontend 側（hazards.js）はこの API の JSON を描画するだけでよく、
  レイヤー定義を別途 layers = [...] のような形で持ってはいけない。
  新しいレイヤーを追加・変更するときは _LAYER_DEFINITIONS だけを編集すること。

提供する情報:
- レイヤー定義（固定）
- runtime 実態（MBTiles ファイル存在確認）
- Martin catalog チェック
"""
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import URLError
from urllib.request import urlopen

logger = logging.getLogger(__name__)

# プロジェクトルート（backend/app/services/ から 3 階層上）
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_ROOT = _BACKEND_DIR.parent

# ── レイヤー定義（Single Source of Truth） ─────────────────────────────────
# tileset_id   : Martin に登録された MBTiles のセット ID
# api_url      : タイル不在時の API fallback URL
# severity     : 危険度（浸水深ランク / zone_type）による色分け表示の有無
# source_path  : normalized GeoJSON の位置（プロジェクトルートからの相対パス）
# runtime_tiles_path : data_runtime 上の MBTiles パス
_LAYER_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "flood_tokyo_max": {
        "name": "洪水浸水想定（想定最大規模）",
        "type": "polygon",
        "region": "tokyo",
        "tileset_id": "tokyo_flood_max",
        "api_url": "/api/hazards/flood/tokyo",
        "severity": True,
        "notes": (
            "drop-densest-as-needed applied. "
            "coalesce not applicable (convergence failure at 660K features)."
        ),
        "source_path": "data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson",
        "runtime_tiles_path": "data_runtime/frontend/tiles/tokyo/flood/tokyo_flood_max.mbtiles",
        "docs": [
            "QUICKSTART.md",
            "docs/hazard_layers.md",
            "docs/architecture/layer_strategy.md",
        ],
    },
    "storm_surge_tokyo": {
        "name": "高潮浸水想定（東京都）",
        "type": "polygon",
        "region": "tokyo",
        "tileset_id": "tokyo_storm_surge",
        "api_url": "/api/hazards/storm_surge/tokyo",
        "severity": True,
        "notes": (
            "drop-densest-as-needed + coalesce-densest-as-needed "
            "+ detect-shared-borders applied."
        ),
        "source_path": "data_lake/normalized/tokyo/storm_surge/tokyo_storm_surge.geojson",
        "runtime_tiles_path": "data_runtime/frontend/tiles/tokyo/storm_surge/tokyo_storm_surge.mbtiles",
        "docs": [
            "docs/hazard_layers.md",
            "docs/architecture/layer_strategy.md",
        ],
    },
    "tsunami_tokyo": {
        "name": "津波浸水想定（東京都）",
        "type": "polygon",
        "region": "tokyo",
        "tileset_id": "tokyo_tsunami_A40-23_13",
        "api_url": "/api/hazards/tsunami/tokyo",
        "severity": False,
        "notes": "Multi-region support: kanagawa, chiba via hazard.tsunami.targets.",
        "source_path": "data_lake/normalized/tokyo/tsunami/tokyo_tsunami_A40-23_13.geojson",
        "runtime_tiles_path": (
            "data_runtime/frontend/tiles/tokyo/tsunami/tokyo_tsunami_A40-23_13.mbtiles"
        ),
        "docs": ["docs/hazard_layers.md"],
    },
    "inland_flood_tokyo": {
        "name": "内水氾濫（東京都）",
        "type": "polygon",
        "region": "tokyo",
        "tileset_id": None,
        "api_url": None,
        "severity": True,
        "notes": "タイル化未実装。GeoJSON via /layers/ のみ (sample data).",
        "source_path": "data_lake/normalized/tokyo/inland_flood/inland_flood_sample.geojson",
        "runtime_tiles_path": None,
        "docs": [
            "docs/hazard_layers.md",
            "docs/architecture/hazard_capability_matrix.md",
        ],
    },
    "landslide_tokyo": {
        "name": "土砂災害（東京都）",
        "type": "polygon",
        "region": "tokyo",
        "tileset_id": None,
        "api_url": "/api/hazards/landslide/tokyo",
        "severity": True,
        "notes": "zone_type based severity. タイル化未実装 (sample data).",
        "source_path": "data_lake/normalized/tokyo/landslide/landslide_sample.geojson",
        "runtime_tiles_path": None,
        "docs": [
            "docs/hazard_layers.md",
            "docs/architecture/hazard_capability_matrix.md",
        ],
    },
}


def _fetch_catalog(martin_url: str) -> Optional[List[str]]:
    """Martin /catalog から tileset ID リストを取得。失敗時は None を返す。"""
    try:
        url = martin_url.rstrip("/") + "/catalog"
        with urlopen(url, timeout=2) as resp:
            data = json.loads(resp.read())
        # Martin catalog 形式: {"tiles": {"tileset_id": {...}, ...}}
        return list(data.get("tiles", {}).keys())
    except (URLError, json.JSONDecodeError, OSError) as exc:
        logger.warning("Martin catalog fetch failed (%s): %s", martin_url, exc)
        return None


def _main_delivery(defn: Dict[str, Any]) -> str:
    if defn.get("tileset_id"):
        return "vector_tile"
    if defn.get("api_url"):
        return "api"
    if defn.get("source_path"):
        return "geojson"
    return "none"


def _runtime_state(defn: Dict[str, Any], catalog_ids: Optional[List[str]]) -> str:
    tileset_id = defn.get("tileset_id")
    if tileset_id:
        if catalog_ids is None:
            # catalog 到達不可 — ファイル存在で代替判定
            rt = defn.get("runtime_tiles_path")
            return "ok" if (rt and (_ROOT / rt).exists()) else "tiles_missing"
        return "ok" if tileset_id in catalog_ids else "tiles_missing"
    if defn.get("api_url"):
        return "api_only"
    src = defn.get("source_path")
    if src and (_ROOT / src).exists():
        return "api_only"
    return "not_configured"


def _status(defn: Dict[str, Any], rt_state: str) -> str:
    src = defn.get("source_path")
    source_exists = bool(src and (_ROOT / src).exists())
    if rt_state == "ok":
        return "active"
    if rt_state == "tiles_missing":
        return "warning"   # tiles missing; may or may not have API fallback
    if rt_state == "api_only":
        return "active" if source_exists else "planned"
    if rt_state == "not_configured":
        return "planned"
    return "error"


def _build_summary_row(
    layer_key: str,
    defn: Dict[str, Any],
    catalog_ids: Optional[List[str]],
) -> Dict[str, Any]:
    rt_state = _runtime_state(defn, catalog_ids)
    tileset_id = defn.get("tileset_id")
    catalog_present: Optional[bool] = None
    if tileset_id is not None:
        # catalog_ids が None = Martin 到達不可 → 不明（None のまま）
        # catalog_ids が取得済み → tileset の有無を返す
        if catalog_ids is not None:
            catalog_present = tileset_id in catalog_ids
    return {
        "layer_key": layer_key,
        "name": defn["name"],
        "type": defn["type"],
        "status": _status(defn, rt_state),
        "main_delivery": _main_delivery(defn),
        "fallback": bool(tileset_id and defn.get("api_url")),
        "severity": defn.get("severity", False),
        "tileset_id": tileset_id,
        "api_url": defn.get("api_url"),
        "runtime_state": rt_state,
        "catalog_present": catalog_present,
        "notes": defn.get("notes"),
        "updated_at": None,
    }


class AdminHazardService:
    def __init__(self, martin_url: str = "http://martin:3000") -> None:
        self.martin_url = martin_url

    def _catalog(self) -> tuple[Optional[List[str]], bool]:
        result = _fetch_catalog(self.martin_url)
        return result, result is not None

    def list_layers(self) -> Dict[str, Any]:
        catalog_ids, _ = self._catalog()
        layers = [
            _build_summary_row(k, v, catalog_ids)
            for k, v in _LAYER_DEFINITIONS.items()
        ]
        return {"layers": layers}

    def get_layer(self, layer_key: str) -> Dict[str, Any]:
        defn = _LAYER_DEFINITIONS.get(layer_key)
        if defn is None:
            raise KeyError(f"Layer not found: {layer_key!r}")
        catalog_ids, _ = self._catalog()
        row = _build_summary_row(layer_key, defn, catalog_ids)
        # 詳細パネル用追加フィールド
        row["region"] = defn.get("region")
        row["source_path"] = defn.get("source_path")
        row["runtime_tiles_path"] = defn.get("runtime_tiles_path")
        row["notes"] = [s.strip() for s in (defn.get("notes") or "").split(".") if s.strip()]
        row["docs"] = defn.get("docs", [])
        return row

    def get_runtime_summary(self) -> Dict[str, Any]:
        catalog_ids, catalog_ok = self._catalog()
        rows = [
            _build_summary_row(k, v, catalog_ids)
            for k, v in _LAYER_DEFINITIONS.items()
        ]
        return {
            "catalog_ok": catalog_ok,
            "tilesets": catalog_ids or [],
            "vector_tile_layers": sum(1 for r in rows if r["main_delivery"] == "vector_tile"),
            "fallback_capable_layers": sum(1 for r in rows if r["fallback"]),
            "active_layers": sum(1 for r in rows if r["status"] == "active"),
            "planned_layers": sum(1 for r in rows if r["status"] == "planned"),
        }

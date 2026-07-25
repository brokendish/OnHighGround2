"""
jartic_traffic_service.py — JARTIC 交通量観測点サービス

GET /api/jartic/traffic
  - APIキー不要（JARTIC交通量APIはオープンデータとして公開）
  - WFS 2.0.0 GetFeature で観測点の点データを取得
  - 正規化して最新スナップショットのみキャッシュ（DBなし・履歴なし）

環境変数:
  JARTIC_TRAFFIC_BASE_URL - APIベースURL（デフォルト: https://api.jartic-open-traffic.org/geoserver）
  JARTIC_TRAFFIC_USE_MOCK - "true" のときモックデータを返す（テスト用）

キャッシュ:
  TTL 300秒（5分）。メモリキャッシュ + ファイルスナップショット。
  ファイル: data_runtime/backend/jartic/latest_traffic.json
  マニフェスト: data_runtime/backend/jartic/manifest.json

交通量カテゴリ判定:
  /live 側 (app.services.live_road_traffic_service.classify_volume) をそのまま
  流用する。通常画面独自の閾値は新設しない（Phase 7-B.3）。
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

from app.models.live_road_traffic import SEVERITY, STATUS_LABEL
from app.services.live_road_traffic_service import classify_volume

logger = logging.getLogger(__name__)

_JST       = timezone(timedelta(hours=9))
_CACHE_TTL = 300.0  # 秒（5分）
_SOURCE    = "JARTIC / 国土交通省交通量API"

_cache:    Optional[Dict[str, Any]] = None
_cache_at: float = 0.0

_SNAPSHOT_PATH = Path("data_runtime/backend/jartic/latest_traffic.json")
_MANIFEST_PATH = Path("data_runtime/backend/jartic/manifest.json")


# ── 設定 ──────────────────────────────────────────────────────────────────────

def _base_url() -> str:
    return os.getenv("JARTIC_TRAFFIC_BASE_URL", "https://api.jartic-open-traffic.org/geoserver")


def _use_mock() -> bool:
    return os.getenv("JARTIC_TRAFFIC_USE_MOCK", "").lower() == "true"


# ── モックデータ ───────────────────────────────────────────────────────────────

def _mock_items() -> List[Dict[str, Any]]:
    now = datetime.now(_JST).isoformat()
    items = [
        {
            "code": "M001", "lat": 35.6812, "lon": 139.7671,
            "up": 320, "down": 280, "total": 600,
            "small": 520, "large": 80,
            "observed_at": now, "unit": "5min", "type": "常設",
        },
        {
            "code": "M002", "lat": 35.6503, "lon": 139.6941,
            "up": 0, "down": 0, "total": 0,
            "small": 0, "large": 0,
            "observed_at": now, "unit": "5min", "type": "常設",
        },
        {
            "code": "M003", "lat": 35.7281, "lon": 139.8601,
            "up": None, "down": None, "total": None,
            "small": None, "large": None,
            "observed_at": now, "unit": None, "type": None,
        },
        {
            "code": "M004", "lat": 35.6997, "lon": 139.7738,
            "up": 40, "down": 12, "total": 52,
            "small": 45, "large": 7,
            "observed_at": now, "unit": "5min", "type": "常設",
        },
    ]
    for item in items:
        status_up   = classify_volume(item["up"], None)
        status_down = classify_volume(item["down"], None)
        status = status_up if SEVERITY[status_up] >= SEVERITY[status_down] else status_down
        item["status"]            = status
        item["status_label"]      = STATUS_LABEL[status]
        item["status_up"]         = status_up
        item["status_up_label"]   = STATUS_LABEL[status_up]
        item["status_down"]       = status_down
        item["status_down_label"] = STATUS_LABEL[status_down]
    return items


# ── WFS URL 構築 ──────────────────────────────────────────────────────────────

_DEFAULT_BBOX = "128.0,30.0,148.0,46.0"  # 日本全域おおよそ


def _build_wfs_url(base_url: str, bbox_str: str = _DEFAULT_BBOX) -> str:
    """JARTIC WFS GetFeature URL を構築する（APIキーなし）。"""
    from urllib.parse import urlencode

    now = datetime.now(_JST)
    lag = now - timedelta(minutes=25)
    lag = lag.replace(second=0, microsecond=0, minute=(lag.minute // 5) * 5)
    time_code = lag.strftime("%Y%m%d%H%M")

    parts = [float(x) for x in bbox_str.split(",")]
    min_lng, min_lat, max_lng, max_lat = parts

    cql = (
        f'時間コード={time_code} AND '
        f'BBOX(ジオメトリ,{min_lng},{min_lat},{max_lng},{max_lat},\'EPSG:4326\')'
    )
    qs = urlencode({
        "service":      "WFS",
        "version":      "2.0.0",
        "request":      "GetFeature",
        "typeNames":    "t_travospublic_measure_5m",
        "srsName":      "EPSG:4326",
        "outputFormat": "application/json",
        "exceptions":   "application/json",
        "cql_filter":   cql,
    })
    return f"{base_url}?{qs}"


def _observed_at(date_int: int, time_hhmm: int) -> str:
    try:
        dt = datetime.strptime(f"{date_int}{str(time_hhmm).zfill(4)}", "%Y%m%d%H%M")
        return dt.replace(tzinfo=_JST).isoformat()
    except Exception:
        return datetime.now(_JST).isoformat()


# ── フィーチャー正規化 ─────────────────────────────────────────────────────────

def normalize_feature(feature: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    JARTIC WFS GeoJSON Feature 1件 → 観測点 1件（上り・下り を統合）。

    座標なし / 観測点コードなし は None を返す。
    交通量が欠測の場合は None（0台は有効値として保持）。
    """
    props = feature.get("properties", {})
    geom  = feature.get("geometry", {})
    coords = geom.get("coordinates", [])
    if not coords:
        return None
    try:
        lng = float(coords[0][0])
        lat = float(coords[0][1])
    except (IndexError, TypeError, ValueError):
        return None

    code = props.get("常時観測点コード")
    if code is None:
        return None

    observed_at = _observed_at(
        int(props.get("観測年月日", 0)),
        int(props.get("時間帯", 0)),
    )

    def _sum_dir(prefix: str) -> Optional[int]:
        """上り/下り の小型+大型+判別不能の合計。欠測フラグが "1" のときは None。"""
        if props.get(f"{prefix}・欠測") == "1":
            return None
        small = props.get(f"{prefix}・小型交通量")
        large = props.get(f"{prefix}・大型交通量")
        unkn  = props.get(f"{prefix}・車種判別不能交通量")
        if small is None and large is None:
            return None
        return sum(v for v in [small, large, unkn] if v is not None)

    def _sum_type(key: str) -> Optional[int]:
        """上り+下りの指定車種合計。どちらも欠測なら None。"""
        up_miss = props.get("上り・欠測") == "1"
        dn_miss = props.get("下り・欠測") == "1"
        u = props.get(f"上り・{key}") if not up_miss else None
        d = props.get(f"下り・{key}") if not dn_miss else None
        if u is None and d is None:
            return None
        return sum(v for v in [u, d] if v is not None)

    up   = _sum_dir("上り")
    down = _sum_dir("下り")

    if up is not None and down is not None:
        total: Optional[int] = up + down
    else:
        total = None

    small = _sum_type("小型交通量")
    large = _sum_type("大型交通量")

    # unit / type の判定（API仕様上取れる場合のみ）
    unit: Optional[str] = "5min"  # typeNames が 5m なので固定
    obs_type: Optional[str] = None
    road_type = str(props.get("道路種別", ""))
    if road_type == "1":
        obs_type = "高速"
    elif road_type == "3":
        obs_type = "一般国道"

    # 交通量カテゴリ（/live と同一の classify_volume を使用。上り・下りそれぞれ判定し、
    # マーカー色は severity が高い方（悪化側）を採用する。同点時は上りを優先）
    status_up   = classify_volume(up, None)
    status_down = classify_volume(down, None)
    status = status_up if SEVERITY[status_up] >= SEVERITY[status_down] else status_down

    return {
        "code":             str(code),
        "lat":              lat,
        "lon":              lng,
        "up":               up,
        "down":             down,
        "total":            total,
        "small":            small,
        "large":            large,
        "observed_at":      observed_at,
        "unit":             unit,
        "type":             obs_type,
        "status":           status,
        "status_label":     STATUS_LABEL[status],
        "status_up":        status_up,
        "status_up_label":  STATUS_LABEL[status_up],
        "status_down":      status_down,
        "status_down_label": STATUS_LABEL[status_down],
    }


# ── 生データ取得 ──────────────────────────────────────────────────────────────

def _fetch_raw(base_url: str, bbox_str: str = _DEFAULT_BBOX) -> List[Dict[str, Any]]:
    """APIキーなしで JARTIC WFS から GeoJSON Feature リストを取得する。"""
    url = _build_wfs_url(base_url, bbox_str)
    headers = {"User-Agent": "OnHighGround2/jartic-traffic-observation-layer"}
    req = Request(url, headers=headers)
    with urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode())
    return data.get("features", [])


# ── スナップショット保存 ───────────────────────────────────────────────────────

def _save_snapshot(payload: Dict[str, Any]) -> None:
    try:
        _SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SNAPSHOT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        manifest = {
            "status": payload.get("status"),
            "source": payload.get("source", _SOURCE),
            "updated_at": payload.get("updated_at"),
            "saved_at": datetime.now(_JST).isoformat(),
            "item_count": len(payload.get("items", [])) if isinstance(payload.get("items"), list) else 0,
            "snapshot": str(_SNAPSHOT_PATH),
        }
        _MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    except Exception as exc:
        logger.warning("jartic traffic: snapshot save failed: %s", exc)


# ── BBOX フィルター ───────────────────────────────────────────────────────────

def _filter_bbox(
    items: List[Dict[str, Any]],
    bbox_str: Optional[str],
) -> List[Dict[str, Any]]:
    """bbox="min_lng,min_lat,max_lng,max_lat" に従って items を絞る。"""
    if not bbox_str:
        return items
    try:
        parts = [float(x) for x in bbox_str.split(",")]
        if len(parts) != 4:
            return items
        min_lng, min_lat, max_lng, max_lat = parts
        return [
            it for it in items
            if min_lat <= it["lat"] <= max_lat and min_lng <= it["lon"] <= max_lng
        ]
    except (ValueError, KeyError):
        return items


# ── 内部取得 ──────────────────────────────────────────────────────────────────

async def _fetch_all_items() -> List[Dict[str, Any]]:
    import asyncio

    if _use_mock():
        logger.info("jartic traffic: mock mode")
        return _mock_items()

    base_url = _base_url()
    raw_features: List[Dict[str, Any]] = await asyncio.to_thread(
        _fetch_raw, base_url, _DEFAULT_BBOX
    )

    items: List[Dict[str, Any]] = []
    for feature in raw_features:
        item = normalize_feature(feature)
        if item is not None:
            items.append(item)

    logger.info("jartic traffic: fetched %d items", len(items))
    return items


# ── 公開API ───────────────────────────────────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(_JST).isoformat()


def _monotonic() -> float:
    return time.monotonic()


async def get_traffic_observations(
    bbox: Optional[str] = None,
) -> Dict[str, Any]:
    """
    交通量観測点データを返す。

    - APIキー不要（取得失敗時のみ unavailable）
    - 最新スナップショットのみ保持（DB・履歴なし）
    - bbox="min_lng,min_lat,max_lng,max_lat" で絞り込み可能
    """
    global _cache, _cache_at

    now = _monotonic()

    # キャッシュヒット
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        items = _filter_bbox(_cache["items"], bbox)
        return {
            "status":     _cache["status"],
            "source":     _SOURCE,
            "updated_at": _cache["updated_at"],
            "items":      items,
        }

    # 新規取得
    try:
        items_all = await _fetch_all_items()
        updated_at = _now_jst()
        payload: Dict[str, Any] = {
            "status":     "ok",
            "source":     _SOURCE,
            "updated_at": updated_at,
            "items":      items_all,
        }
        _cache    = payload
        _cache_at = now
        _save_snapshot(payload)
        logger.info("jartic traffic: ok items=%d", len(items_all))
        return {
            "status":     "ok",
            "source":     _SOURCE,
            "updated_at": updated_at,
            "items":      _filter_bbox(items_all, bbox),
        }

    except URLError as exc:
        logger.warning("jartic traffic: 取得失敗 (URLError): %s", exc)
    except Exception as exc:
        logger.warning("jartic traffic: 取得失敗: %s", exc)

    # unavailable（キャッシュなし）
    logger.warning("jartic traffic: unavailable")
    return {
        "status":     "unavailable",
        "source":     _SOURCE,
        "updated_at": None,
        "items":      [],
        "message":    "交通量観測点データを取得できません",
    }

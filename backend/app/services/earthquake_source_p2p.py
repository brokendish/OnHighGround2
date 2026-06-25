"""
earthquake_source_p2p.py — P2P地震情報 v2 API データ取得・正規化
"""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_P2P_URL = "https://api.p2pquake.net/v2/history?codes=551&limit=300"
_JST = timezone(timedelta(hours=9))

_SCALE_MAP: Dict[int, str] = {
    -1: "不明",
    10: "1",
    20: "2",
    30: "3",
    40: "4",
    45: "5弱",
    50: "5強",
    55: "6弱",
    60: "6強",
    70: "7",
}

_TSUNAMI_MAP: Dict[str, str] = {
    "None": "なし",
    "Unknown": "調査中",
    "Checking": "確認中",
    "NonEffective": "若干の海面変動あり",
    "Watch": "津波注意報",
    "Warning": "津波警報",
}


def _parse_time(time_str: Optional[str]) -> Optional[str]:
    """P2P 時刻文字列 "YYYY/MM/DD HH:MM:SS[.xxx]" → ISO 8601 文字列 (JST)"""
    if not time_str:
        return None
    try:
        dt = datetime.strptime(time_str.strip()[:19], "%Y/%m/%d %H:%M:%S")
        return dt.replace(tzinfo=_JST).isoformat()
    except ValueError:
        logger.debug("Cannot parse time: %s", time_str)
        return None


def _valid_coordinate(value: Any) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    # P2P は座標不明時に -200 を返す
    if value <= -180:
        return None
    return float(value)


def _normalize(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """P2P API レスポンス 1 件を正規化モデルへ変換する。"""
    eq = raw.get("earthquake") or {}
    hypo = eq.get("hypocenter") or {}

    occurred_at = _parse_time(eq.get("time"))
    if occurred_at is None:
        return None

    lat = _valid_coordinate(hypo.get("latitude"))
    lng = _valid_coordinate(hypo.get("longitude"))

    magnitude = hypo.get("magnitude", -1)
    depth_km = hypo.get("depth", -1)
    max_scale = eq.get("maxScale", -1)
    tsunami_code = eq.get("domesticTsunami", "None")

    raw_points = raw.get("points") or []
    points = [
        {
            "pref":   str(p.get("pref", "")),
            "addr":   str(p.get("addr", "")),
            "isArea": bool(p.get("isArea", True)),
            "scale":  int(p.get("scale", -1)),
        }
        for p in raw_points
        if isinstance(p, dict) and isinstance(p.get("scale"), (int, float)) and int(p.get("scale", -1)) > 0
    ]

    return {
        "event_id": str(raw.get("id", "")),
        "occurred_at": occurred_at,
        "epicenter_name": hypo.get("name") or "不明",
        "lat": lat,
        "lng": lng,
        "depth_km": depth_km if isinstance(depth_km, (int, float)) and depth_km > 0 else None,
        "magnitude": magnitude if isinstance(magnitude, (int, float)) and magnitude > 0 else None,
        "max_intensity": _SCALE_MAP.get(max_scale, "不明"),
        "tsunami_info": _TSUNAMI_MAP.get(tsunami_code, tsunami_code),
        "source": "p2pquake",
        "points": points,
    }


def _fetch_raw() -> List[Dict[str, Any]]:
    req = urllib.request.Request(
        _P2P_URL,
        headers={
            "Accept": "application/json",
            "User-Agent": "OnHighGround2/1.0 (+https://github.com/brokendish/OnHighGround2)",
        },
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


async def fetch_earthquakes() -> List[Dict[str, Any]]:
    """P2P 地震情報 API から最新 100 件を取得し正規化して返す。"""
    try:
        raw_list = await asyncio.to_thread(_fetch_raw)
    except Exception as exc:
        logger.warning("P2P 地震情報取得失敗: %s", exc)
        return []
    if not isinstance(raw_list, list):
        logger.warning("P2P 地震情報レスポンス形式不正: %s", type(raw_list).__name__)
        return []

    result = []
    for raw in raw_list:
        item = _normalize(raw)
        if item is not None:
            result.append(item)
    return result

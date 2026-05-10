"""
潮汐推算サービス。
調和定数（振幅・位相遅れ）から外部APIなしで潮位を計算する。

計算式:
  h(t) = Z0 + Σ[Ai * cos(σi * t + V0i − Gi)]
  t    = J2000 (2000-01-01 12:00 UTC) からの経過時間 [時間]
  V0i  = J2000 時点での潮汐分潮平衡引数 [度]
  Gi   = 各地点のグリニッジ位相遅れ [度]（調和定数表の G 値）
  σi   = 分潮角速度 [度/時間]

データ出典: 海上保安庁 潮汐推算 (参考値)
"""
import json
import math
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

# J2000 基準エポック (2000-01-01 12:00:00 UTC)
_J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

# 分潮角速度 [度/時間] と J2000 時点での平衡引数 V0 [度]
# V0 は以下の天文引数から算出:
#   h = 280.46646°  (太陽平均黄経)
#   s = 218.31664°  (月平均黄経)
#   p = 83.35324°   (近地点平均黄経)
#   T = 180°        (J2000 正午の時角換算)
_CONSTITUENTS = {
    "M2": {"speed": 28.9841042, "v0": 124.3},
    "S2": {"speed": 30.0000000, "v0":   0.0},
    "N2": {"speed": 28.4397295, "v0": 349.3},
    "K1": {"speed": 15.0410686, "v0": 190.5},
    "O1": {"speed": 13.9430356, "v0": 293.8},
    "M4": {"speed": 57.9682084, "v0": 248.6},
}

_STATIONS: list = []
_CACHE: dict = {}        # { station_id: { "data": ..., "expires_at": datetime } }
_CACHE_TTL = timedelta(minutes=60)


def _load_stations() -> None:
    global _STATIONS
    path = Path(__file__).resolve().parent.parent / "data" / "tide_stations.json"
    try:
        with path.open(encoding="utf-8") as f:
            _STATIONS = json.load(f)
        logger.info("tide: loaded %d stations from %s", len(_STATIONS), path)
    except Exception as e:
        logger.error("tide: failed to load stations: %s", e)
        _STATIONS = []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_station(lat: float, lon: float) -> Optional[dict]:
    if not _STATIONS:
        return None
    best = min(_STATIONS, key=lambda s: _haversine_km(lat, lon, s["lat"], s["lon"]))
    return best


def _tide_height(t: datetime, constituents: list, z0: float) -> float:
    """時刻 t における潮位 [m] を計算する。"""
    t_utc = t.astimezone(timezone.utc)
    t_hours = (t_utc - _J2000).total_seconds() / 3600.0
    h = z0
    for c in constituents:
        info = _CONSTITUENTS.get(c["name"])
        if not info:
            continue
        phi = (info["speed"] * t_hours + info["v0"] - c["phase_G"]) % 360
        h += c["amplitude"] * math.cos(math.radians(phi))
    return h


def _find_next_events(station: dict, t_start: datetime, n: int = 4) -> list:
    """t_start 以降の高潮・低潮イベントを n 件返す。5分刻みでスキャン。"""
    constituents = station["constituents"]
    z0 = station.get("z0", 0.0)
    step = timedelta(minutes=5)
    events = []

    t = t_start
    h_prev = _tide_height(t, constituents, z0)
    t += step
    h_curr = _tide_height(t, constituents, z0)

    while len(events) < n and t < t_start + timedelta(hours=60):
        t_next = t + step
        h_next = _tide_height(t_next, constituents, z0)

        if h_prev < h_curr and h_curr >= h_next:
            events.append({"type": "high", "time": t, "height": round(h_curr, 2)})
        elif h_prev > h_curr and h_curr <= h_next:
            events.append({"type": "low",  "time": t, "height": round(h_curr, 2)})

        h_prev = h_curr
        h_curr = h_next
        t = t_next

    return events


def _format_jst(dt: datetime) -> str:
    return dt.astimezone(JST).isoformat()


def get_tide_info(lat: float, lon: float) -> Optional[dict]:
    """
    現在地から最寄り地点の潮汐情報を返す。
    キャッシュ TTL 60分。
    """
    if not _STATIONS:
        _load_stations()

    station = _nearest_station(lat, lon)
    if not station:
        return None

    sid = station["id"]
    now = datetime.now(JST)

    # キャッシュチェック
    cached = _CACHE.get(sid)
    if cached and cached["expires_at"] > now:
        result = dict(cached["data"])
        result["station"] = dict(result["station"])
        result["station"]["distance_km"] = round(
            _haversine_km(lat, lon, station["lat"], station["lon"]), 1
        )
        return result

    events = _find_next_events(station, now)

    next_high = next((e for e in events if e["type"] == "high"), None)
    next_low  = next((e for e in events if e["type"] == "low"),  None)

    result = {
        "station": {
            "id":   station["id"],
            "name": station["name"],
            "distance_km": round(_haversine_km(lat, lon, station["lat"], station["lon"]), 1),
        },
        "next_high_tide": {
            "time": _format_jst(next_high["time"]),
            "remaining_minutes": int((next_high["time"] - now).total_seconds() / 60),
        } if next_high else None,
        "next_low_tide": {
            "time": _format_jst(next_low["time"]),
        } if next_low else None,
        "source": "harmonic",
    }

    _CACHE[sid] = {
        "data": result,
        "expires_at": now + _CACHE_TTL,
    }

    return result

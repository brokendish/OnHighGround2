"""
tide_service.py — 潮汐情報サービス（気象庁潮位表 runtime JSONL 参照）

deploy 済みの JSONL (data_runtime/backend/tide/jma/{year}/) を読み込み、
現在地から最寄観測地点の潮位情報を返す。

データが存在しない場合は available=False を返し、
アプリ本体・防災判断には影響させない。
"""
import json
import logging
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_RUNTIME_BASE = _PROJECT_ROOT / "data_runtime" / "backend" / "tide" / "jma"
_STATION_MASTER = _PROJECT_ROOT / "data_lake" / "registry" / "station_master.json"
_LEGACY_STATION_MASTER = _PROJECT_ROOT / "data_lake" / "registry" / "tide_station_master.json"

_stations: list[dict] = []
_hourly_index: dict[str, list[dict]] = {}   # station_code → sorted hourly records
_extremes_index: dict[str, list[dict]] = {} # station_code → sorted extremes records
_loaded_year: Optional[str] = None


# ── ロード ────────────────────────────────────────────────────────────────────

def _load_stations() -> list[dict]:
    station_master = _STATION_MASTER if _STATION_MASTER.exists() else _LEGACY_STATION_MASTER
    if not station_master.exists():
        logger.warning("tide: station_master not found: %s", _STATION_MASTER)
        return []
    with station_master.open(encoding="utf-8") as f:
        return json.load(f)


def _resolve_runtime_dir() -> Optional[Path]:
    """runtime ディレクトリを返す。JSONL が直置きされている場合はそのまま返す。"""
    if not _RUNTIME_BASE.exists():
        return None
    # JSONL が直接置かれている（年非依存レイアウト）
    if any(_RUNTIME_BASE.glob("tide_hourly_*.jsonl")):
        return _RUNTIME_BASE
    return None


def _load_runtime() -> None:
    global _stations, _hourly_index, _extremes_index, _loaded_year

    _stations = _load_stations()

    runtime_dir = _resolve_runtime_dir()
    if runtime_dir is None:
        logger.warning("tide: no runtime dir found under %s", _RUNTIME_BASE)
        return

    hourly_files = sorted(runtime_dir.glob("tide_hourly_*.jsonl"))

    # 年はファイル名から取得: tide_hourly_2026.jsonl → "2026"
    year = hourly_files[0].stem.split("_")[-1] if hourly_files else "unknown"
    extremes_files = sorted(runtime_dir.glob("tide_extremes_*.jsonl"))

    if not hourly_files:
        logger.warning("tide: no hourly JSONL found in %s", runtime_dir)
        return

    hourly_map: dict[str, list[dict]] = {}
    for path in hourly_files:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                code = rec.get("station", "")
                hourly_map.setdefault(code, []).append(rec)

    extremes_map: dict[str, list[dict]] = {}
    for path in extremes_files:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                code = rec.get("station", "")
                extremes_map.setdefault(code, []).append(rec)

    _hourly_index = {k: sorted(v, key=lambda r: r["datetime"]) for k, v in hourly_map.items()}
    _extremes_index = {k: sorted(v, key=lambda r: r["date"]) for k, v in extremes_map.items()}
    _loaded_year = year

    logger.info(
        "tide runtime loaded year=%s stations=%d",
        year, len(_hourly_index),
    )


def _ensure_loaded() -> None:
    if not _hourly_index:
        _load_runtime()


# ── 地理計算 ─────────────────────────────────────────────────────────────────

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _nearest_station(lat: float, lon: float) -> Optional[dict]:
    """station_master から最寄地点を返す（データが存在する地点のみ）。"""
    candidates = [s for s in _stations if s["station_code"] in _hourly_index]
    if not candidates:
        return None
    return min(candidates, key=lambda s: _haversine_km(lat, lon, s["lat"], s["lon"]))


# ── 潮位取得 ─────────────────────────────────────────────────────────────────

def _get_current_tide_cm(code: str, now: datetime) -> Optional[int]:
    hourly = _hourly_index.get(code, [])
    now_str = now.isoformat()[:16]  # "YYYY-MM-DDTHH:MM"
    for rec in hourly:
        if rec["datetime"][:16] == now_str:
            return rec.get("tide_cm")
    # 直前時刻にフォールバック
    now_hour = now.replace(minute=0, second=0, microsecond=0).isoformat()[:16]
    for rec in hourly:
        if rec["datetime"][:16] == now_hour:
            return rec.get("tide_cm")
    return None


def _get_next_extreme(
    code: str,
    now: datetime,
    extreme_type: str,
) -> Optional[dict]:
    """now 以降の次の満潮 ('high') または干潮 ('low') を返す。"""
    extremes = _extremes_index.get(code, [])
    now_iso = now.isoformat()

    for day_rec in extremes:
        day_str = day_rec.get("date", "")
        if day_str < now_iso[:10]:
            continue
        tides = day_rec.get("high_tides" if extreme_type == "high" else "low_tides", [])
        for t in tides:
            if t.get("time", "") > now_iso:
                remaining = int(
                    (datetime.fromisoformat(t["time"]) - now).total_seconds() / 60
                )
                return {
                    "time": t["time"],
                    "tide_cm": t.get("tide_cm"),
                    "remaining_minutes": max(0, remaining),
                }
    return None


# ── 公開 API ─────────────────────────────────────────────────────────────────

def get_tide_info(lat: float, lon: float) -> Optional[dict]:
    """
    現在地から最寄り地点の潮汐情報を返す。

    runtime JSONL が存在しない場合は available=False。
    """
    _ensure_loaded()

    if not _stations:
        logger.warning("tide: no stations loaded")
        return {"available": False, "source": "jma"}

    station = _nearest_station(lat, lon)
    if station is None:
        logger.warning("missing tide station lat=%s lon=%s", lat, lon)
        return {"available": False, "source": "jma"}

    now = datetime.now(JST)
    code = station["station_code"]
    dist_km = round(_haversine_km(lat, lon, station["lat"], station["lon"]), 1)

    current_tide_cm = _get_current_tide_cm(code, now)
    next_high = _get_next_extreme(code, now, "high")
    next_low = _get_next_extreme(code, now, "low")

    if current_tide_cm is None and next_high is None and next_low is None:
        return {"available": False, "source": "jma"}

    logger.info(
        "nearest tide station resolved station=%s name=%s dist_km=%s",
        code, station.get("station_name") or station.get("name"), dist_km,
    )

    return {
        "available": True,
        "station": {
            "id":          code,
            "name":        station.get("station_name") or station.get("name", code),
            "distance_km": dist_km,
        },
        "current_tide_cm": current_tide_cm,
        "next_high_tide":  next_high,
        "next_low_tide":   next_low,
        "source": "jma",
        "year":   _loaded_year,
    }


def reload() -> None:
    """runtime キャッシュを再ロードする（deploy 後ホットリロード用）。"""
    global _hourly_index, _extremes_index, _loaded_year
    _hourly_index = {}
    _extremes_index = {}
    _loaded_year = None
    _load_runtime()

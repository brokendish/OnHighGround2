"""
気象庁アメダスAPIクライアント。

エンドポイント:
  - 観測点テーブル: /const/amedastable.json（24h キャッシュ）
  - 最新時刻:      /data/latest_time.txt（60s キャッシュ）
  - 全観測点一括:  /data/map/{timestamp_utc}.json（60s キャッシュ）

タイムスタンプ:
  latest_time.txt は JST で返す（例: 2026-04-29T19:00:00+09:00）。
  map エンドポイントの URL は UTC 形式（例: 20260429100000）を使う。
"""
import math
import time
import logging
import urllib.request
import json
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

_JMA_BASE = "https://www.jma.go.jp/bosai/amedas"
_TABLE_URL = f"{_JMA_BASE}/const/amedastable.json"
_LATEST_TIME_URL = f"{_JMA_BASE}/data/latest_time.txt"
_MAP_URL = f"{_JMA_BASE}/data/map/{{timestamp}}.json"

_STATION_TABLE_CACHE: Optional[dict] = None
_STATION_TABLE_FETCHED_AT: float = 0.0
_STATION_TABLE_TTL = 86400.0  # 24h

_LATEST_TIME_CACHE: Optional[str] = None   # UTC timestamp string e.g. "20260429100000"
_LATEST_TIME_FETCHED_AT: float = 0.0
_LATEST_TIME_TTL = 60.0

_MAP_CACHE: Optional[dict] = None
_MAP_TIMESTAMP: Optional[str] = None
_MAP_FETCHED_AT: float = 0.0
_MAP_TTL = 60.0

_JST = timezone(timedelta(hours=9))


def _http_get(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OnHighGround2/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _jst_to_utc_str(jst_str: str) -> Optional[str]:
    """
    JST ISO8601 文字列を UTC の YYYYMMDDHHmmss 文字列に変換する。

    例: '2026-04-29T19:00:00+09:00' → '20260429100000'
    """
    try:
        dt = datetime.fromisoformat(jst_str.strip())
        dt_utc = dt.astimezone(timezone.utc)
        return dt_utc.strftime("%Y%m%d%H%M%S")
    except Exception as exc:
        logger.warning("jst_to_utc_str failed for '%s': %s", jst_str, exc)
        return None


def _dms_to_decimal(dms) -> float:
    """[度, 分] または数値を十進度に変換する。"""
    if isinstance(dms, (list, tuple)) and len(dms) >= 2:
        return dms[0] + dms[1] / 60.0
    return float(dms)


def fetch_station_table() -> dict:
    """観測点テーブルを返す（dict: station_id → {lat_dec, lon_dec, name}）。"""
    global _STATION_TABLE_CACHE, _STATION_TABLE_FETCHED_AT
    now = time.monotonic()
    if _STATION_TABLE_CACHE and now - _STATION_TABLE_FETCHED_AT < _STATION_TABLE_TTL:
        logger.debug("amedas station table: cache hit (%d stations)", len(_STATION_TABLE_CACHE))
        return _STATION_TABLE_CACHE

    try:
        raw = _http_get(_TABLE_URL)
        raw_table = json.loads(raw)
        table = {}
        for sid, info in raw_table.items():
            try:
                table[sid] = {
                    "station_id": sid,
                    "station_name": info.get("kjName") or info.get("enName") or sid,
                    "lat": _dms_to_decimal(info.get("lat", 0)),
                    "lon": _dms_to_decimal(info.get("lon", 0)),
                }
            except Exception:
                continue
        _STATION_TABLE_CACHE = table
        _STATION_TABLE_FETCHED_AT = now
        logger.info("amedas station table: cache miss — loaded %d stations", len(table))
        return table
    except Exception as exc:
        logger.warning("amedas station table fetch failed: %s", exc)
        return _STATION_TABLE_CACHE or {}


def fetch_latest_time_utc() -> Optional[str]:
    """最新データの UTC タイムスタンプ文字列を返す（例: '20260429100000'）。"""
    global _LATEST_TIME_CACHE, _LATEST_TIME_FETCHED_AT
    now = time.monotonic()
    if _LATEST_TIME_CACHE and now - _LATEST_TIME_FETCHED_AT < _LATEST_TIME_TTL:
        return _LATEST_TIME_CACHE

    try:
        raw = _http_get(_LATEST_TIME_URL)
        jst_str = raw.decode().strip()
        ts_utc = _jst_to_utc_str(jst_str)
        if ts_utc:
            _LATEST_TIME_CACHE = ts_utc
            _LATEST_TIME_FETCHED_AT = now
            logger.debug("amedas latest_time: JST=%s → UTC=%s", jst_str, ts_utc)
        return _LATEST_TIME_CACHE
    except Exception as exc:
        logger.warning("amedas latest_time fetch failed: %s", exc)
        return _LATEST_TIME_CACHE


def fetch_map_data() -> Optional[dict]:
    """全観測点の最新観測データを返す（dict: station_id → obs）。"""
    global _MAP_CACHE, _MAP_TIMESTAMP, _MAP_FETCHED_AT
    now = time.monotonic()
    if _MAP_CACHE and now - _MAP_FETCHED_AT < _MAP_TTL:
        age_s = now - _MAP_FETCHED_AT
        logger.debug("amedas map: cache hit ts=%s age=%.0fs stations=%d", _MAP_TIMESTAMP, age_s, len(_MAP_CACHE))
        return _MAP_CACHE

    ts = fetch_latest_time_utc()
    if not ts:
        return _MAP_CACHE

    url = _MAP_URL.format(timestamp=ts)
    try:
        raw = _http_get(url)
        data = json.loads(raw)
        _MAP_CACHE = data
        _MAP_TIMESTAMP = ts
        _MAP_FETCHED_AT = now
        logger.info("amedas map: cache miss — loaded %d stations ts=%s", len(data), ts)
        return data
    except Exception as exc:
        logger.warning("amedas map fetch failed ts=%s: %s", ts, exc)
        return _MAP_CACHE


def extract_value(obs: dict, key: str) -> Optional[float]:
    """観測データから値を取り出す（[value, quality] 形式）。"""
    v = obs.get(key)
    if isinstance(v, (list, tuple)) and len(v) >= 1:
        try:
            val = float(v[0])
            return None if math.isnan(val) else val
        except (TypeError, ValueError):
            return None
    return None

"""
live_weather_jma_service.py — 全国気象ミニテロップ（Open-Meteo Forecast）サービス

Open-Meteo `/v1/forecast` から都道府県代表地点（北海道は複数地点）の天気概況を取得し、
UI向けに正規化して返す。JMA警報・キキクルとは独立した補助情報。

Phase 8-A.1 で `/v1/jma` から `/v1/forecast` に切り替えた。`/v1/jma` (JMAモデル単体)
は precipitation_probability を常に null で返す仕様上の制約があり、降水確率の数値強調
(70%以上)が機能しなかったため、precipitation_probability を提供する `/v1/forecast`
(複数モデルのブレンド、日本域はJMAモデルを含む)に変更した。

キャッシュ:
  通常キャッシュ 20分。取得失敗時は stale cache を最大2時間まで使用する。
  2時間を超えたら更新停止 (unavailable) 扱いとする。

frontend は本サービス経由の backend API のみを利用し、Open-Meteo を直接叩かない。

利用箇所（Phase 8-A）:
  Phase 8-A の元仕様書は "/live 画面の右パネル上部" と記載していたが、実際に
  鉄道情報/潮位・水位カードの積み重ね構成・ページ送りテロップが存在するのは
  /live/stream (frontend/live/stream.html, frontend/js/live-stream/) 側だった
  ため、frontend 実装は /live/stream にのみ組み込んでいる（本 backend API は
  /live 側から呼び出しても問題ない共通資源）。
  /live 本体（frontend/index.html 相当ではなく frontend/live.html）への追加要否は
  tasks/stream/ の Phase 8-A 実装記録を参照のこと。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_JST = timezone(timedelta(hours=9))

_CACHE_TTL = 20 * 60.0        # 秒: 通常キャッシュ
_STALE_MAX_AGE = 2 * 60 * 60.0  # 秒: stale cache として使える上限

_OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
_SOURCE_LABEL = "Open-Meteo Forecast"
_HOURLY_FIELDS = "weather_code,temperature_2m,relative_humidity_2m,precipitation_probability"
_CHUNK_SIZE = 15
_HTTP_TIMEOUT = 15

_POINTS_PATH = Path(__file__).resolve().parents[1] / "data" / "weather_points_jma.json"
_points_cache: Optional[List[Dict[str, Any]]] = None

_cache: Optional[Dict[str, Any]] = None   # {"items": [...], "forecast_time": str}
_cache_at: float = 0.0                    # monotonic time of last successful fetch


# ── 地点マスタ ─────────────────────────────────────────────────────────────────

def _load_points() -> List[Dict[str, Any]]:
    global _points_cache
    if _points_cache is not None:
        return _points_cache
    with _POINTS_PATH.open(encoding="utf-8") as f:
        points = json.load(f)
    points.sort(key=lambda p: p["display_order"])
    _points_cache = points
    return points


# ── 天気コード正規化 ────────────────────────────────────────────────────────────

_WEATHER_CATEGORY: Dict[str, str] = {
    "sunny":   "晴",
    "cloudy":  "曇",
    "rain":    "雨",
    "snow":    "雪",
    "thunder": "雷",
    "fog":     "霧",
    "unknown": "不明",
}


def normalize_weather_code(code: Optional[int]) -> Tuple[str, str]:
    """Open-Meteo weather_code → (category, label) に正規化する。"""
    if code is None:
        return "unknown", _WEATHER_CATEGORY["unknown"]
    try:
        c = int(code)
    except (TypeError, ValueError):
        return "unknown", _WEATHER_CATEGORY["unknown"]

    if c in (0, 1, 2):
        category = "sunny"
    elif c == 3:
        category = "cloudy"
    elif c in (45, 48):
        category = "fog"
    elif c in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
        category = "rain"
    elif c in (71, 73, 75, 77, 85, 86):
        category = "snow"
    elif c in (95, 96, 99):
        category = "thunder"
    else:
        category = "unknown"
    return category, _WEATHER_CATEGORY[category]


# ── 数値強調フラグ ─────────────────────────────────────────────────────────────

def compute_flags(
    temperature_c: Optional[float],
    humidity_percent: Optional[float],
    precipitation_probability_percent: Optional[float],
) -> Dict[str, bool]:
    return {
        "precipitation_high": precipitation_probability_percent is not None
            and precipitation_probability_percent >= 70,
        "temperature_hot":  temperature_c is not None and temperature_c >= 35,
        "temperature_cold": temperature_c is not None and temperature_c <= 0,
        "humidity_high":    humidity_percent is not None and humidity_percent >= 85,
    }


# ── 時刻ヘルパー ───────────────────────────────────────────────────────────────

def _now_jst() -> datetime:
    return datetime.now(_JST)


def _now_jst_iso() -> str:
    return _now_jst().isoformat()


def _target_hour() -> datetime:
    return _now_jst().replace(minute=0, second=0, microsecond=0)


def _select_hour_index(times: List[str], target: datetime) -> Optional[int]:
    """hourly.time (JST naive ISO文字列) から target に最も近い index を返す。"""
    if not times:
        return None
    best_idx: Optional[int] = None
    best_diff: Optional[float] = None
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_JST)
        except ValueError:
            continue
        diff = abs((dt - target).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best_idx = i
    return best_idx


def _format_forecast_time(raw: str) -> str:
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_JST)
        return dt.isoformat()
    except ValueError:
        return raw


# ── Open-Meteo 取得 ────────────────────────────────────────────────────────────

def _fetch_chunk(points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """同期的に Open-Meteo /v1/forecast を1チャンク分取得する（asyncio.to_thread経由で呼ぶ）。"""
    lat_str = ",".join(str(p["lat"]) for p in points)
    lon_str = ",".join(str(p["lon"]) for p in points)
    url = (
        f"{_OPEN_METEO_URL}?latitude={lat_str}&longitude={lon_str}"
        f"&hourly={_HOURLY_FIELDS}&timezone=Asia%2FTokyo&forecast_days=1"
    )
    req = Request(url, headers={"User-Agent": "OnHighGround2/live-weather-jma"})
    with urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode())
    if isinstance(payload, dict):
        payload = [payload]
    return payload


def _build_item(
    point: Dict[str, Any],
    forecast: Dict[str, Any],
    target: datetime,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    hourly = forecast.get("hourly") or {}
    times = hourly.get("time") or []
    idx = _select_hour_index(times, target)
    if idx is None:
        return None, None

    def _at(field: str) -> Any:
        values = hourly.get(field) or []
        return values[idx] if idx < len(values) else None

    weather_code = _at("weather_code")
    temperature_c = _at("temperature_2m")
    humidity_percent = _at("relative_humidity_2m")
    precipitation_probability_percent = _at("precipitation_probability")

    category, label = normalize_weather_code(weather_code)
    flags = compute_flags(temperature_c, humidity_percent, precipitation_probability_percent)

    item = {
        "id": point["id"],
        "pref_code": point["pref_code"],
        "pref_name": point["pref_name"],
        "point_name": point["point_name"],
        "display_order": point["display_order"],
        "weather_code": weather_code,
        "weather_category": category,
        "weather_label": label,
        "temperature_c": temperature_c,
        "humidity_percent": humidity_percent,
        "precipitation_probability_percent": precipitation_probability_percent,
        "flags": flags,
    }
    return item, times[idx]


async def _fetch_all_points() -> Tuple[List[Dict[str, Any]], str]:
    points = _load_points()
    target = _target_hour()
    chunks = [points[i:i + _CHUNK_SIZE] for i in range(0, len(points), _CHUNK_SIZE)]

    items: List[Dict[str, Any]] = []
    forecast_time_raw: Optional[str] = None

    for chunk in chunks:
        payload = await asyncio.to_thread(_fetch_chunk, chunk)
        if len(payload) != len(chunk):
            raise ValueError(
                f"Open-Meteo response length mismatch: expected={len(chunk)} got={len(payload)}"
            )
        for point, forecast in zip(chunk, payload):
            item, ft = _build_item(point, forecast, target)
            if item is None:
                continue
            items.append(item)
            if forecast_time_raw is None:
                forecast_time_raw = ft

    if not items or forecast_time_raw is None:
        raise ValueError("Open-Meteo: no items parsed from response")

    items.sort(key=lambda it: it["display_order"])
    logger.info("live weather jma: items=%d", len(items))
    return items, _format_forecast_time(forecast_time_raw)


# ── 公開 API ──────────────────────────────────────────────────────────────────

def _monotonic() -> float:
    return time.monotonic()


def _envelope(cache_status: str) -> Dict[str, Any]:
    cache = _cache or {"items": [], "forecast_time": None}
    return {
        "status":        "ok" if cache_status != "unavailable" else "unavailable",
        "source":        _SOURCE_LABEL,
        "forecast_time": cache.get("forecast_time"),
        "fetched_at":    cache.get("fetched_at"),
        "cache_status":  cache_status,
        "items":         cache.get("items", []),
    }


async def get_weather_summary() -> Dict[str, Any]:
    """
    全国気象ミニテロップ用サマリーを返す。

    Returns:
        {
            "status": "ok" | "unavailable",
            "source": "Open-Meteo Forecast",
            "forecast_time": str | None,
            "fetched_at": str | None,
            "cache_status": "fresh" | "stale" | "unavailable",
            "items": [...],
        }
    """
    global _cache, _cache_at

    now = _monotonic()

    # キャッシュが新鮮ならそのまま返す
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        return _envelope("fresh")

    # 新規取得を試みる
    try:
        items, forecast_time = await _fetch_all_points()
        _cache = {
            "items":         items,
            "forecast_time": forecast_time,
            "fetched_at":    _now_jst_iso(),
        }
        _cache_at = now
        return _envelope("fresh")
    except URLError as exc:
        logger.warning("live weather jma: Open-Meteo取得失敗 (URLError): %s", exc)
    except Exception as exc:
        logger.warning("live weather jma: Open-Meteo取得失敗: %s", exc)

    # 取得失敗時: stale cache / unavailable
    if _cache is not None:
        age = now - _cache_at
        if age <= _STALE_MAX_AGE:
            logger.info("live weather jma: stale cache 使用 (age=%.0fs)", age)
            return _envelope("stale")
        logger.warning("live weather jma: stale cache 期限切れ → unavailable (age=%.0fs)", age)
        return _envelope("unavailable")

    logger.warning("live weather jma: unavailable (no cache)")
    return {
        "status":        "unavailable",
        "source":        _SOURCE_LABEL,
        "forecast_time": None,
        "fetched_at":    None,
        "cache_status":  "unavailable",
        "items":         [],
    }

"""
JMA 降水ナウキャストタイルサービス（Phase2B / Phase2C拡張）

targetTimes JSON を取得して basetime/validtime 一覧を解決し、
Leaflet 用タイル URL テンプレートを返す。

タイル URL 形式:
  https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png

将来 XRAIN に差し替える場合は、このファイルの定数と _build_tile_url() を変更するだけでよい。

Phase1.5 追加:
  get_precip_intensity_at(lat, lon, tile_url_template) — PNG タイルのピクセル色から降水強度を返す
"""
import io
import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Optional
import urllib.request

logger = logging.getLogger(__name__)

_TARGET_TIMES_N1_URL = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
)
_TARGET_TIMES_N2_URL = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N2.json"
)
_TARGET_TIMES_URL = _TARGET_TIMES_N1_URL  # get_rain_tile_latest 互換エイリアス
_CACHE_TTL = 120.0  # 秒

# 生エントリキャッシュ（N1: 過去観測 / N2: 予測）
_entries_cache:    Optional[tuple[list, float]] = None  # N1
_n2_entries_cache: Optional[tuple[list, float]] = None  # N2


def _http_get(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OnHighGround2/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _build_tile_url(basetime: str, validtime: str) -> str:
    return (
        "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
        + basetime
        + "/none/"
        + validtime
        + "/surf/hrpns/{z}/{x}/{y}.png"
    )


def _parse_jma_dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def _fetch_entries() -> list:
    """N1（過去観測）を取得・キャッシュして返す。"""
    global _entries_cache
    now = time.monotonic()

    if _entries_cache is not None:
        entries, fetched_at = _entries_cache
        if now - fetched_at < _CACHE_TTL:
            return entries

    raw = _http_get(_TARGET_TIMES_N1_URL)
    entries = json.loads(raw)
    if not isinstance(entries, list):
        raise ValueError("Unexpected targetTimes_N1 format")

    _entries_cache = (entries, now)
    return entries


def _fetch_n2_entries() -> list:
    """N2（+5〜+60分予測）を取得・キャッシュして返す。失敗時は空リスト。"""
    global _n2_entries_cache
    now = time.monotonic()

    if _n2_entries_cache is not None:
        entries, fetched_at = _n2_entries_cache
        if now - fetched_at < _CACHE_TTL:
            return entries

    raw = _http_get(_TARGET_TIMES_N2_URL)
    entries = json.loads(raw)
    if not isinstance(entries, list):
        raise ValueError("Unexpected targetTimes_N2 format")

    _n2_entries_cache = (entries, now)
    return entries


def get_rain_tile_latest() -> Optional[dict]:
    """
    JMA 降水ナウキャストの最新タイル情報を返す（120s キャッシュ）。

    Returns:
        {
            source:            "jma_nowcast",
            basetime:          "20250430120000",
            validtime:         "20250430120000",
            tile_url_template: "https://.../{z}/{x}/{y}.png",
            updated_at:        "2025-04-30T12:00:00+00:00",
            ttl_seconds:       120,
        }
        or None on unrecoverable error
    """
    try:
        entries = _fetch_entries()

        if not entries:
            logger.warning("jma rain tile: empty targetTimes response")
            return None

        latest = entries[-1]
        basetime  = str(latest.get("basetime", ""))
        validtime = str(latest.get("validtime", basetime))

        if not basetime:
            logger.warning("jma rain tile: missing basetime in response")
            return None

        data = {
            "source":            "jma_nowcast",
            "basetime":          basetime,
            "validtime":         validtime,
            "tile_url_template": _build_tile_url(basetime, validtime),
            "updated_at":        datetime.now(timezone.utc).isoformat(),
            "ttl_seconds":       int(_CACHE_TTL),
        }
        logger.info(
            "jma rain tile: basetime=%s validtime=%s",
            basetime, validtime,
        )
        return data

    except Exception as exc:
        logger.warning("jma rain tile fetch failed: %s", exc)
        # 旧キャッシュがあれば stale で返す
        if _entries_cache:
            entries, _ = _entries_cache
            if entries:
                latest = entries[-1]
                basetime  = str(latest.get("basetime", ""))
                validtime = str(latest.get("validtime", basetime))
                if basetime:
                    logger.info("jma rain tile: serving stale cache after error")
                    return {
                        "source":            "jma_nowcast",
                        "basetime":          basetime,
                        "validtime":         validtime,
                        "tile_url_template": _build_tile_url(basetime, validtime),
                        "updated_at":        datetime.now(timezone.utc).isoformat(),
                        "ttl_seconds":       int(_CACHE_TTL),
                    }
        return None


def get_rain_tile_times() -> Optional[dict]:
    """
    過去 60 分（N1）＋ 予測 60 分（N2）の統合タイル一覧を返す。

    - N1: basetime==validtime の観測専用データ。最大 13 件（直近 60 分）を使用。
    - N2: basetime!=validtime の予測データ（+5〜+60 分）。N2 取得失敗時は過去のみ。
    - offset_minutes: 0=最新観測、負=過去、正=予測

    Returns:
        {
            source:   "jma_nowcast",
            basetime: "20260430054000",   # N1 最新観測の basetime
            times: [
                {validtime: "...", offset_minutes: -60, tile_url_template: "..."},
                ...
                {validtime: "...", offset_minutes:   0, tile_url_template: "..."},
                {validtime: "...", offset_minutes:  +5, tile_url_template: "..."},
                ...
                {validtime: "...", offset_minutes: +60, tile_url_template: "..."},
            ],
            ttl_seconds: 120,
        }
        or None on error
    """
    try:
        # ── N1: 過去観測 ─────────────────────────────────────────────────────
        n1_entries = _fetch_entries()
        if not n1_entries:
            logger.warning("jma rain tile times: empty N1 response")
            return None

        n1_sorted   = sorted(n1_entries, key=lambda e: str(e.get("validtime", "")))
        n1_selected = n1_sorted[-13:]   # 最大 13 件（直近 60 分）

        latest_n1        = n1_selected[-1]
        latest_basetime  = str(latest_n1.get("basetime", ""))
        latest_vt_str    = str(latest_n1.get("validtime", latest_basetime))

        try:
            reference_dt = _parse_jma_dt(latest_vt_str)  # offset=0 の基準
        except ValueError:
            logger.warning("jma rain tile times: invalid N1 latest validtime %s", latest_vt_str)
            return None

        times: list[dict] = []

        for e in n1_selected:
            vt = str(e.get("validtime", ""))
            bt = str(e.get("basetime",  vt))
            try:
                offset_min = int((_parse_jma_dt(vt) - reference_dt).total_seconds() / 60)
            except ValueError:
                continue
            times.append({
                "validtime":         vt,
                "offset_minutes":    offset_min,
                "tile_url_template": _build_tile_url(bt, vt),
            })

        # ── N2: 予測（取得失敗時は過去データのみで継続） ─────────────────────
        try:
            n2_entries = _fetch_n2_entries()
        except Exception as exc:
            logger.warning("jma rain tile N2 fetch failed (forecast unavailable): %s", exc)
            n2_entries = []

        for e in n2_entries:
            vt = str(e.get("validtime", ""))
            bt = str(e.get("basetime",  ""))
            try:
                offset_min = int((_parse_jma_dt(vt) - reference_dt).total_seconds() / 60)
            except ValueError:
                continue
            if 0 < offset_min <= 70:   # 0 超〜70 分以内（N2 は +5〜+60 が通常）
                times.append({
                    "validtime":         vt,
                    "offset_minutes":    offset_min,
                    "tile_url_template": _build_tile_url(bt, vt),
                })

        # ── 昇順ソート・重複除去 ─────────────────────────────────────────────
        seen: set[int] = set()
        unique_times: list[dict] = []
        for t in sorted(times, key=lambda x: x["offset_minutes"]):
            off = t["offset_minutes"]
            if off not in seen:
                seen.add(off)
                unique_times.append(t)

        if not unique_times:
            return None

        min_off = unique_times[0]["offset_minutes"]
        max_off = unique_times[-1]["offset_minutes"]
        logger.info(
            "jma rain tile times: ref=%s total=%d range=%d..%d min (n2=%d)",
            latest_vt_str, len(unique_times), min_off, max_off, len(n2_entries),
        )
        return {
            "source":      "jma_nowcast",
            "basetime":    latest_basetime,
            "times":       unique_times,
            "ttl_seconds": int(_CACHE_TTL),
        }

    except Exception as exc:
        logger.warning("jma rain tile times fetch failed: %s", exc)
        return None


# ── Phase1.5: PNG タイルピクセル解析 ────────────────────────────────────────

_TILE_SIZE_PX = 256
_NOWCAST_DEFAULT_ZOOM = 8   # JMA hrpns は偶数ズームのみ有効（4, 6, 8, 10）
_PNG_TILE_TTL = 120.0       # 秒（targetTimes キャッシュと合わせる）
_PNG_CACHE_MAX = 200        # エントリ上限（超えたら最古を削除）

# PNG タイル byte キャッシュ: url → (bytes, monotonic)
_png_tile_cache: dict[str, tuple[bytes, float]] = {}

# JMA hrpns 降水ナウキャスト 色 → 降水強度マッピング（近似値 / 要実環境校正）
# (R, G, B, intensity, rain_class)  rain_class は大きいほど強い
_JMA_RAIN_COLOR_TABLE: list[tuple[int, int, int, str, int]] = [
    (160, 210, 255, "weak",     1),   # ~0.5-1 mm/h   薄水色
    ( 33, 140, 255, "weak",     2),   # ~1-5 mm/h     水色
    (  0,  65, 255, "moderate", 3),   # ~5-10 mm/h    青
    (  0, 200, 200, "moderate", 4),   # ~10-20 mm/h   シアン
    (  0, 200,   0, "strong",   5),   # ~20-30 mm/h   緑
    (255, 215,   0, "strong",   6),   # ~30-50 mm/h   黄
    (255, 140,   0, "severe",   7),   # ~50-80 mm/h   橙
    (255,   0,   0, "severe",   8),   # ~80-120 mm/h  赤
    (180,   0, 180, "severe",   9),   # ~120+ mm/h    紫
]
_COLOR_DIST_THRESHOLD_SQ = 50 ** 2   # Euclidean距離^2 の許容上限

_INTENSITY_LABEL: dict[str, str] = {
    "none":     "降水なし",
    "weak":     "弱い雨",
    "moderate": "雨",
    "strong":   "強い雨",
    "severe":   "非常に激しい雨",
    "unknown":  "判定不能",
}


def _lat_lon_to_tile_pixel(lat: float, lon: float, zoom: int) -> tuple[int, int, int, int]:
    """WebMercator lat/lon → (tile_x, tile_y, pixel_x, pixel_y)"""
    n = 2 ** zoom
    x_frac = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y_frac = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    tile_x = int(x_frac)
    tile_y = int(y_frac)
    px = min(int((x_frac - tile_x) * _TILE_SIZE_PX), _TILE_SIZE_PX - 1)
    py = min(int((y_frac - tile_y) * _TILE_SIZE_PX), _TILE_SIZE_PX - 1)
    return tile_x, tile_y, px, py


def _fetch_tile_png(url: str) -> Optional[bytes]:
    """PNG タイルを取得してキャッシュ。失敗時は None。"""
    now = time.monotonic()

    if url in _png_tile_cache:
        data, fetched_at = _png_tile_cache[url]
        if now - fetched_at < _PNG_TILE_TTL:
            return data

    if len(_png_tile_cache) >= _PNG_CACHE_MAX:
        oldest = min(_png_tile_cache, key=lambda k: _png_tile_cache[k][1])
        del _png_tile_cache[oldest]

    try:
        raw = _http_get(url, timeout=8)
        _png_tile_cache[url] = (raw, now)
        return raw
    except Exception as exc:
        logger.debug("png tile fetch failed %s: %s", url, exc)
        return None


def _rgba_to_intensity(r: int, g: int, b: int, a: int) -> tuple[str, int]:
    """RGBA 値を (intensity, rain_class) に変換する。"""
    if a < 50:
        return "none", 0
    if r > 230 and g > 230 and b > 230:   # 白系背景
        return "none", 0

    best_intensity = "unknown"
    best_class = -1
    best_dist_sq = float("inf")
    for tr, tg, tb, intensity, rain_class in _JMA_RAIN_COLOR_TABLE:
        d = (r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2
        if d < best_dist_sq:
            best_dist_sq = d
            best_intensity = intensity
            best_class = rain_class

    if best_dist_sq > _COLOR_DIST_THRESHOLD_SQ:
        return "unknown", -1
    return best_intensity, best_class


def _sample_max_intensity(
    pixels: any,
    px: int,
    py: int,
    radius: int,
    width: int,
    height: int,
) -> tuple[str, int]:
    """
    (px, py) を中心に (2*radius+1)^2 画素の最大強度を返す。

    判定優先度:
      1. recognized rain がある → 最大 rain_class の intensity
      2. rain なし + unknown opaque がある → "unknown"
      3. rain なし + unknown なし → "none"
      4. 画素なし（範囲外のみ） → "unknown"

    rain_class=-1 (unknown opaque) を none に倒さないことが重要。
    防災用途では「知らない色 = 安全」とみなさない。
    """
    recognized_rain_found = False
    unknown_opaque_found = False
    recognized_none_found = False
    best_rain_intensity = "none"
    best_rain_class = 0
    pixels_sampled = 0

    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            x = max(0, min(width - 1, px + dx))
            y = max(0, min(height - 1, py + dy))
            rgba = pixels[x, y]   # Pillow の load() は (col, row) = (x, y)
            r, g, b = rgba[0], rgba[1], rgba[2]
            a = rgba[3] if len(rgba) > 3 else 255
            intensity, rain_class = _rgba_to_intensity(r, g, b, a)
            pixels_sampled += 1

            if rain_class >= 1:
                recognized_rain_found = True
                if rain_class > best_rain_class:
                    best_rain_class = rain_class
                    best_rain_intensity = intensity
            elif rain_class == -1:
                unknown_opaque_found = True
            else:
                recognized_none_found = True

    if pixels_sampled == 0:
        return "unknown", -1
    if recognized_rain_found:
        return best_rain_intensity, best_rain_class
    if unknown_opaque_found:
        return "unknown", -1
    return "none", 0


def get_precip_intensity_at(
    lat: float,
    lon: float,
    tile_url_template: str,
    zoom: int = _NOWCAST_DEFAULT_ZOOM,
    sample_radius_px: int = 2,
) -> dict:
    """
    lat/lon 地点の降水強度を PNG タイル解析で返す。

    タイル URL テンプレートは get_rain_tile_times() の times[] 各エントリの
    tile_url_template を渡す。{z}/{x}/{y} を実座標に置換して取得する。

    JMA hrpns は偶数ズームのみ有効。奇数 zoom が渡された場合は 1 下げる。

    Returns:
        {
            "intensity": "none" | "weak" | "moderate" | "strong" | "severe" | "unknown",
            "label":     str,
            "rain_class": int,   # 0=なし, 1-9=強さ, -1=不明
            "source":    str,
        }
    """
    try:
        from PIL import Image
    except ImportError:
        logger.error("Pillow not installed — cannot analyze rain tile pixels")
        return {"intensity": "unknown", "label": _INTENSITY_LABEL["unknown"], "rain_class": -1, "source": "no_pillow"}

    try:
        # JMA hrpns は偶数ズームのみ
        if zoom % 2 != 0:
            zoom = max(zoom - 1, 4)

        tile_x, tile_y, px, py = _lat_lon_to_tile_pixel(lat, lon, zoom)
        url = (
            tile_url_template
            .replace("{z}", str(zoom))
            .replace("{x}", str(tile_x))
            .replace("{y}", str(tile_y))
        )

        raw = _fetch_tile_png(url)
        if raw is None:
            return {"intensity": "unknown", "label": _INTENSITY_LABEL["unknown"], "rain_class": -1, "source": "fetch_failed"}

        img = Image.open(io.BytesIO(raw)).convert("RGBA")
        width, height = img.size
        pixels = img.load()

        intensity, rain_class = _sample_max_intensity(pixels, px, py, sample_radius_px, width, height)
        return {
            "intensity": intensity,
            "label":     _INTENSITY_LABEL.get(intensity, "判定不能"),
            "rain_class": rain_class,
            "source":    "jma_nowcast_tile",
        }

    except Exception as exc:
        logger.warning("get_precip_intensity_at failed lat=%s lon=%s: %s", lat, lon, exc)
        return {"intensity": "unknown", "label": _INTENSITY_LABEL["unknown"], "rain_class": -1, "source": "error"}


def fetch_precip_intensities(
    lat: float,
    lon: float,
    time_entries: list[dict],
    max_workers: int = 4,
    max_forecast_min: int = 30,
) -> dict[int, dict]:
    """
    time_entries（get_rain_tile_times() の times[]）から
    offset_minutes <= max_forecast_min の各タイムステップの降水強度を
    ThreadPoolExecutor で並列取得して返す。

    Returns: {offset_minutes: intensity_dict, ...}
    """
    targets = [
        t for t in time_entries
        if t.get("offset_minutes", 0) <= max_forecast_min
    ]

    results: dict[int, dict] = {}

    def _fetch(entry: dict) -> tuple[int, dict]:
        off = entry["offset_minutes"]
        result = get_precip_intensity_at(lat, lon, entry["tile_url_template"])
        return off, result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch, t): t["offset_minutes"] for t in targets}
        for future in as_completed(futures, timeout=15):
            try:
                off, result = future.result()
                results[off] = result
            except Exception as exc:
                off = futures[future]
                logger.warning("fetch_precip_intensities: offset=%d failed: %s", off, exc)
                results[off] = {"intensity": "unknown", "label": _INTENSITY_LABEL["unknown"], "rain_class": -1, "source": "error"}

    return results

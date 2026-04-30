"""
JMA 降水ナウキャストタイルサービス（Phase2B / Phase2C拡張）

targetTimes JSON を取得して basetime/validtime 一覧を解決し、
Leaflet 用タイル URL テンプレートを返す。

タイル URL 形式:
  https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png

将来 XRAIN に差し替える場合は、このファイルの定数と _build_tile_url() を変更するだけでよい。
"""
import json
import logging
import time
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

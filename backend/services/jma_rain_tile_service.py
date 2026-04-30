"""
JMA 降水ナウキャストタイルサービス（Phase2B）

targetTimes JSON を取得して最新の basetime/validtime を解決し、
Leaflet 用タイル URL テンプレートを返す。

タイル URL 形式:
  https://www.jma.go.jp/bosai/jmatile/data/nowc/{basetime}/none/{validtime}/surf/hrpns/{z}/{x}/{y}.png

将来 XRAIN に差し替える場合は、このファイルの定数と _build_tile_url() を変更するだけでよい。
"""
import json
import logging
import time
import urllib.request
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_TARGET_TIMES_URL = (
    "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
)
_CACHE_TTL = 120.0  # 秒

_cache: Optional[tuple[dict, float]] = None  # (data, monotonic_fetched_at)


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
    global _cache
    now = time.monotonic()

    if _cache is not None:
        data, fetched_at = _cache
        if now - fetched_at < _CACHE_TTL:
            logger.info(
                "jma rain tile: cache hit basetime=%s validtime=%s",
                data.get("basetime"), data.get("validtime"),
            )
            return data

    try:
        raw = _http_get(_TARGET_TIMES_URL)
        entries = json.loads(raw)

        if not isinstance(entries, list) or not entries:
            logger.warning("jma rain tile: empty or invalid targetTimes response")
            return _cache[0] if _cache else None

        # 配列の末尾 = 最新エントリ（最も新しい basetime/validtime）
        latest = entries[-1]
        basetime  = str(latest.get("basetime", ""))
        validtime = str(latest.get("validtime", basetime))

        if not basetime:
            logger.warning("jma rain tile: missing basetime in response")
            return _cache[0] if _cache else None

        data = {
            "source":            "jma_nowcast",
            "basetime":          basetime,
            "validtime":         validtime,
            "tile_url_template": _build_tile_url(basetime, validtime),
            "updated_at":        datetime.now(timezone.utc).isoformat(),
            "ttl_seconds":       int(_CACHE_TTL),
        }
        _cache = (data, now)
        logger.info(
            "jma rain tile: cache miss — fetched basetime=%s validtime=%s",
            basetime, validtime,
        )
        return data

    except Exception as exc:
        logger.warning("jma rain tile fetch failed: %s", exc)
        if _cache:
            data, _ = _cache
            logger.info("jma rain tile: serving stale cache after error")
            return data
        return None

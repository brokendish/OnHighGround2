"""
live_storm_surge_service.py — /live 高潮警報・注意報 集計サービス

JMA 気象警報 API（都道府県別）から高潮関連警報を全国集計する。
沿岸都道府県のみを対象とし、非同期で並列取得する。

ログ:
  live storm surge summary: areas=X
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from app.services.jma_weather_adapter import (
    fetch_warnings_for_pref,
    _PREF_CENTROIDS,       # noqa: WPS450
    STORM_SURGE_CODES,     # 高潮コードの単一参照源。独自定義禁止。
    STORM_SURGE_CODE_META, # code → {severity, label}
)

logger = logging.getLogger(__name__)

# storm_surge における重大度順序
_LEVEL_ORDER: Dict[str, int] = {
    "emergency": 0,
    "warning": 1,
    "advisory": 2,
}

# 同一 severity 内の代表選択順位（小さいほど優先）。severity contract は変えず、
# 高潮代表の選択にだけ使う。JMA 2026 体系の警戒レベル順:
#   38 高潮特別警報(L5) > 48 レベル４高潮危険警報(L4) > 08 高潮警報(L3) > 19 高潮注意報(L2)
# 08 と 48 はどちらも warning のため、この順位がないと代表が入力順依存になる。
_STORM_SURGE_CODE_PRIORITY: Dict[str, int] = {
    "38": 0,
    "48": 1,
    "08": 2,
    "19": 3,
}

# 沿岸都道府県コード（高潮が発生しうる都道府県のみ取得）
_COASTAL_PREF_CODES: List[str] = [
    "010000",  # 北海道
    "020000",  # 青森県
    "030000",  # 岩手県
    "040000",  # 宮城県
    "050000",  # 秋田県
    "060000",  # 山形県
    "070000",  # 福島県
    "080000",  # 茨城県
    "120000",  # 千葉県
    "130000",  # 東京都
    "140000",  # 神奈川県
    "150000",  # 新潟県
    "160000",  # 富山県
    "170000",  # 石川県
    "180000",  # 福井県
    "220000",  # 静岡県
    "230000",  # 愛知県
    "240000",  # 三重県
    "270000",  # 大阪府
    "280000",  # 兵庫県
    "300000",  # 和歌山県
    "310000",  # 鳥取県
    "320000",  # 島根県
    "330000",  # 岡山県
    "340000",  # 広島県
    "350000",  # 山口県
    "360000",  # 徳島県
    "370000",  # 香川県
    "380000",  # 愛媛県
    "390000",  # 高知県
    "400000",  # 福岡県
    "410000",  # 佐賀県
    "420000",  # 長崎県
    "430000",  # 熊本県
    "440000",  # 大分県
    "450000",  # 宮崎県
    "460000",  # 鹿児島県
    "470000",  # 沖縄県
]

_CACHE_TTL = 120.0  # 秒

_cache: Optional[Dict[str, Any]] = None
_cache_at: float = 0.0


def _monotonic() -> float:
    return time.monotonic()


def _pref_info(pref_code: str) -> tuple[str, Optional[float], Optional[float]]:
    """pref_code から (都道府県名, lat, lon) を返す。"""
    info = _PREF_CENTROIDS.get(pref_code)
    if info:
        name, lat, lon = info  # (name, lat, lon) タプル形式
        return name, lat, lon
    return pref_code, None, None


async def _fetch_pref_storm_surge(pref_code: str) -> List[Dict[str, Any]]:
    """1都道府県の高潮警報・注意報を取得して返す。

    戻り値は都道府県単位で最大1件。最上位レベルの警報を代表として返し、
    全対象区域（市区町村・一次細分区域）を affected_areas に収録する。
    """
    pref_name, lat, lon = _pref_info(pref_code)
    try:
        items = await asyncio.to_thread(fetch_warnings_for_pref, pref_code, pref_name)
    except Exception as exc:
        logger.debug("live_storm_surge: fetch failed pref=%s: %s", pref_code, exc)
        return []

    # storm_surge 関連の全アイテムを収集し、最上位レベルを決定する
    affected: List[Dict[str, Any]] = []
    best_code: Optional[str] = None
    best_key = (999, 999)
    for item in items:
        raw_code = item.raw_code
        if raw_code not in STORM_SURGE_CODES:
            continue
        meta = STORM_SURGE_CODE_META[raw_code]
        level = meta["severity"]
        # severity 優先 → 同一 severity は高潮コード priority で決定（入力順非依存）
        key = (_LEVEL_ORDER.get(level, 9), _STORM_SURGE_CODE_PRIORITY.get(raw_code, 99))
        if key < best_key:
            best_key = key
            best_code = raw_code
        affected.append({
            "area_name": item.area_name or pref_name,
            "area_code": item.area_code or "",
            "kind":      meta["label"],
            "level":     level,
        })

    if best_code is None:
        return []

    best_meta = STORM_SURGE_CODE_META[best_code]
    return [{
        "pref_code":      pref_code,
        "pref_name":      pref_name,
        "area_name":      pref_name,
        "kind":           best_meta["label"],
        "level":          best_meta["severity"],
        "lat":            lat,
        "lng":            lon,
        "affected_areas": affected,
    }]


async def _fetch_all_storm_surge() -> List[Dict[str, Any]]:
    """全沿岸都道府県の高潮情報を並列取得してまとめる。"""
    tasks = [_fetch_pref_storm_surge(code) for code in _COASTAL_PREF_CODES]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    areas: List[Dict[str, Any]] = []
    for r in results:
        if isinstance(r, list):
            areas.extend(r)
    areas.sort(key=lambda a: _LEVEL_ORDER.get(a["level"], 9))
    return areas


async def build_live_storm_surge_summary() -> Dict[str, Any]:
    """
    全国高潮警報・注意報サマリーを返す。

    Returns:
        {
            "status": "ok" | "offline",
            "evaluated": True,
            "summary": {"active": bool, "warning_area_count": int},
            "areas": [...],
        }
    """
    global _cache, _cache_at

    now = _monotonic()
    if _cache is not None and (now - _cache_at) < _CACHE_TTL:
        return dict(_cache)

    try:
        areas = await _fetch_all_storm_surge()
        active = len(areas) > 0
        w_count = sum(1 for a in areas if a["level"] in {"emergency", "warning"})

        logger.info("live storm surge summary: areas=%d", len(areas))

        result: Dict[str, Any] = {
            "status":    "ok",
            "evaluated": True,
            "summary":   {"active": active, "warning_area_count": w_count},
            "areas":     _build_danger_areas(areas),
        }
        _cache = result
        _cache_at = now
        return dict(result)

    except Exception as exc:
        logger.warning("live_storm_surge: 集計失敗: %s", exc)
        return {
            "status":    "offline",
            "evaluated": False,
            "summary":   {"active": None, "warning_area_count": None},
            "areas":     [],
        }


def _build_danger_areas(areas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for i, a in enumerate(areas):
        result.append({
            "id":             f"storm_surge-{i}",
            "label":          a["pref_name"],
            "detail":         a["kind"],
            "level":          "danger" if a["level"] in {"emergency", "warning"} else "warning",
            "type":           "storm_surge",
            "source":         "jma",
            "lat":            a.get("lat"),
            "lng":            a.get("lng"),
            "pref_code":      a.get("pref_code", ""),
            "affected_areas": a.get("affected_areas", []),
        })
    return result

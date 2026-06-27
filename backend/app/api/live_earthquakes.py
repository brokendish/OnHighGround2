"""
live_earthquakes.py — /live 地震履歴 API

GET /api/live/earthquakes/history?days=3

P2P 地震情報を一次ソースとし、取得失敗・空の場合は JMA 地震情報にフォールバックする。
JMA クライアントは 60 秒キャッシュ付きで、大地震後の P2P 過負荷時にも安定して動作する。
各地震に isImportant / importantReasons / municipalityIntensityAvailable を付与する。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query

from app.services.earthquake_service import get_recent_earthquakes
from services.jma_quake_client import fetch_recent_earthquakes

router = APIRouter(prefix="/api/live/earthquakes", tags=["live-earthquakes"])
logger = logging.getLogger(__name__)

# 震度文字列 → ランク値（重要地震判定に使用）
_INTENSITY_RANK: Dict[str, int] = {
    "1": 10, "2": 20, "3": 30, "4": 40,
    "5弱": 45, "5強": 50, "6弱": 55, "6強": 60, "7": 70,
}


def _annotate_item(item: Dict[str, Any], source: str) -> Dict[str, Any]:
    """isImportant / importantReasons / municipalityIntensityAvailable を付与する。"""
    item = dict(item)
    reasons: List[str] = []

    mag = item.get("magnitude")
    try:
        mag_float = float(mag) if mag is not None else None
    except (TypeError, ValueError):
        mag_float = None
    if mag_float is not None:
        item["magnitude"] = mag_float
        if mag_float >= 5.0:
            reasons.append("magnitude_ge_5")

    max_int = str(item.get("max_intensity") or "")
    if _INTENSITY_RANK.get(max_int, 0) >= 45:
        reasons.append("intensity_ge_5weak")

    item["isImportant"] = bool(reasons)
    item["importantReasons"] = reasons
    item["municipalityIntensityAvailable"] = (source == "p2p")
    return item


def _jma_compat(event: Dict[str, Any]) -> Dict[str, Any]:
    """JMA 正規化イベントに既存 UI 互換フィールドを付与する。"""
    e = dict(event)
    # occurred_at: origin_time を優先
    e.setdefault("occurred_at", e.get("origin_time") or e.get("report_time"))
    # epicenter_name: hypocenter_name のエイリアス
    e.setdefault("epicenter_name", e.get("hypocenter_name") or "不明")
    # lng: lon のエイリアス（既存 UI は lng を参照）
    if e.get("lng") is None:
        e["lng"] = e.get("lon")
    # tsunami_info: domestic_tsunami のエイリアス
    e.setdefault("tsunami_info", e.get("domestic_tsunami") or "不明")
    e["source"] = "jma"
    return e


async def _jma_fallback(days: int) -> List[Dict[str, Any]]:
    """JMA から直近地震を取得し、days 日以内にフィルタして返す。"""
    try:
        jma_items = await fetch_recent_earthquakes(limit=30)
    except Exception as exc:
        logger.warning("live/earthquakes/history JMA fallback failed: %s", exc)
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result: List[Dict[str, Any]] = []
    for raw in jma_items:
        compat = _jma_compat(raw)
        occurred_at: Optional[str] = compat.get("occurred_at")
        if not occurred_at:
            continue
        try:
            dt = datetime.fromisoformat(occurred_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                result.append(compat)
        except ValueError:
            pass

    logger.info("live/earthquakes/history JMA fallback: days=%d count=%d", days, len(result))
    return result


@router.get("/history")
async def get_earthquake_history(
    days: int = Query(default=3, ge=1, le=7),
) -> Dict[str, Any]:
    """
    過去 N 日間の地震情報を返す（/live 地震履歴表示用）。
    デフォルト 3 日間。最大 7 日間。

    一次ソース: P2P 地震情報（取得失敗・空の場合は JMA にフォールバック）
    """
    source = "p2p"
    try:
        items = await get_recent_earthquakes(days=days)
    except Exception as exc:
        logger.warning("live/earthquakes/history P2P failed, falling back to JMA: %s", exc)
        items = []

    if not items:
        logger.info("live/earthquakes/history P2P empty, falling back to JMA")
        items = await _jma_fallback(days=days)
        source = "jma"

    annotated = [_annotate_item(it, source) for it in items]

    now = datetime.now(timezone.utc)
    logger.info("live/earthquakes/history: days=%d count=%d source=%s", days, len(annotated), source)
    return {
        "days": days,
        "source": source,
        "fallback": source != "p2p",
        "municipalityIntensityAvailable": source == "p2p",
        "updated_at": now.isoformat(),
        "count": len(annotated),
        "items": annotated,
    }

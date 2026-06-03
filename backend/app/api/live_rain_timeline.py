"""
live_rain_timeline.py — 雨雲予測タイムライン API (Phase 5-B)

/api/weather/rain/tile/times の全タイム一覧から
offset_minutes >= 0（現在〜+60分）の予測ステップのみを返す。
危険地域集計・キキクル判定には影響しない。
"""
import logging
from fastapi import APIRouter, HTTPException
from services.jma_rain_tile_service import get_rain_tile_times

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/live/rain/timeline")
async def get_live_rain_timeline():
    """
    雨雲予測タイムライン（現在〜+60分）を返す。

    times[]: offset_minutes >= 0 のエントリのみ（現在観測 + 予測）
    offset_minutes=0 が最新観測、正値が予測（+5〜+60 分）。
    """
    try:
        data = get_rain_tile_times()
        if data is None:
            raise HTTPException(
                status_code=503,
                detail={"error": "rain_timeline_unavailable", "message": "雨雲タイムライン情報を取得できませんでした"},
            )
        forecast_times = [
            t for t in data.get("times", [])
            if t.get("offset_minutes", -1) >= 0
        ]
        logger.info("live rain timeline: frames=%d", len(forecast_times))
        return {
            "source":      data.get("source", "jma_nowcast"),
            "basetime":    data.get("basetime", ""),
            "times":       forecast_times,
            "ttl_seconds": data.get("ttl_seconds", 120),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("live rain timeline endpoint error: %s", exc)
        raise HTTPException(status_code=500, detail={"error": "internal_error"})

"""
tide API — 現在地から最寄り地点の満潮・干潮情報を返す。
"""
import logging
from fastapi import APIRouter, Query

from app.services.tide_service import get_tide_info

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/api/tide/current")
async def get_tide_current(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
):
    try:
        data = get_tide_info(lat, lon)
    except Exception as e:
        logger.warning("tide lookup failed lat=%s lon=%s: %s", lat, lon, e)
        data = None

    if data is None:
        data = {"available": False, "source": "jma"}

    return {"lat": lat, "lon": lon, **data}

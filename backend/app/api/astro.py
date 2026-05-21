"""
天体情報API — 現在地の日の出・日の入り・月の出・月の入り・月齢を返す。
外部API不要。Astralライブラリのみで計算。
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from astral import Observer
from astral.sun import sun
from astral.moon import moonrise, moonset, phase as moon_phase

logger = logging.getLogger(__name__)

router = APIRouter()

JST = timezone(timedelta(hours=9))


def _moon_label(phase: float) -> str:
    if phase <= 1.5 or phase >= 26.5:
        return "新月"
    if 6.0 <= phase <= 8.5:
        return "上弦寄り"
    if 12.5 <= phase <= 15.5:
        return "満月"
    if 20.0 <= phase <= 22.5:
        return "下弦寄り"
    return "通常"


def _night_visibility(label: str) -> str:
    if label == "新月":
        return "真っ暗"
    if label == "満月":
        return "視界良い"
    return "通常"


def _iso_or_none(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _safe_moonrise(observer: Observer, target_date, tzinfo) -> Optional[datetime]:
    """月の出時刻を返す。その日に月が昇らない場合（astral ValueError）は None。"""
    try:
        return moonrise(observer, date=target_date, tzinfo=tzinfo)
    except ValueError:
        return None


def _safe_moonset(observer: Observer, target_date, tzinfo) -> Optional[datetime]:
    """月の入時刻を返す。その日に月が沈まない場合（astral ValueError）は None。"""
    try:
        return moonset(observer, date=target_date, tzinfo=tzinfo)
    except ValueError:
        return None


@router.get("/api/astro/current")
async def get_astro_current(
    lat: float = Query(..., description="緯度", ge=-90, le=90),
    lon: float = Query(..., description="経度", ge=-180, le=180),
    date: Optional[str] = Query(None, description="日付 YYYY-MM-DD (省略=今日JST)"),
):
    try:
        observer = Observer(latitude=lat, longitude=lon)
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(status_code=400, detail="日付形式が不正です (YYYY-MM-DD)")
        else:
            target_date = datetime.now(JST).date()
        s = sun(observer, date=target_date, tzinfo=JST)
        mr = _safe_moonrise(observer, target_date, JST)
        ms = _safe_moonset(observer, target_date, JST)
        phase = moon_phase(target_date)
        label = _moon_label(phase)
        return {
            "lat": lat,
            "lon": lon,
            "date": target_date.isoformat(),
            "timezone": "Asia/Tokyo",
            "sunrise": s["sunrise"].isoformat(),
            "sunset": s["sunset"].isoformat(),
            "moonrise": _iso_or_none(mr),
            "moonset": _iso_or_none(ms),
            "moon_phase": round(phase, 1),
            "moon_label": label,
            "night_visibility": _night_visibility(label),
            "source": "astral",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("astro calc failed lat=%s lon=%s date=%s: %s", lat, lon, date, e)
        raise HTTPException(status_code=500, detail="天体情報の計算に失敗しました")

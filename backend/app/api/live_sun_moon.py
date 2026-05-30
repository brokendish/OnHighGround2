"""
live_sun_moon.py — /live 日月情報 API

GET /api/live/sun-moon

東京固定座標で日の出・日の入り・月の出・月の入り・月齢を返す。
天文計算は既存 astral ライブラリを再利用。新規計算ロジックなし。
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter
from astral import Observer
from astral.sun import sun
from astral.moon import moonrise, moonset, phase as moon_phase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/live", tags=["live-sun-moon"])

_JST = timezone(timedelta(hours=9))

# 基準地点: 東京（将来的な地点切替に備えて定数化）
_TOKYO_LAT = 35.6895
_TOKYO_LON = 139.6917


def _hhmm(dt: Optional[datetime]) -> Optional[str]:
    """datetime → 'HH:MM' (JST) 文字列。None は None のまま返す。"""
    if dt is None:
        return None
    jst = dt.astimezone(_JST)
    return jst.strftime("%H:%M")


def _moon_phase_label(phase: float) -> str:
    """月齢値 (0〜29.5) から月相名を返す（文字列ロジックのみ）。"""
    if phase <= 1.5 or phase >= 27.5:
        return "新月"
    if phase < 6.5:
        return "三日月"
    if phase < 9.5:
        return "上弦"
    if phase < 13.5:
        return "十三夜"
    if phase < 16.5:
        return "満月"
    if phase < 20.5:
        return "十六夜"
    if phase < 24.0:
        return "下弦"
    return "有明月"


def _safe_moonrise(observer: Observer, date, tzinfo) -> Optional[datetime]:
    try:
        return moonrise(observer, date=date, tzinfo=tzinfo)
    except ValueError:
        return None


def _safe_moonset(observer: Observer, date, tzinfo) -> Optional[datetime]:
    try:
        return moonset(observer, date=date, tzinfo=tzinfo)
    except ValueError:
        return None


@router.get("/sun-moon")
async def live_sun_moon():
    """東京基準の日月情報を返す。"""
    try:
        observer = Observer(latitude=_TOKYO_LAT, longitude=_TOKYO_LON)
        today = datetime.now(_JST).date()

        s   = sun(observer, date=today, tzinfo=_JST)
        mr  = _safe_moonrise(observer, today, _JST)
        ms  = _safe_moonset(observer, today, _JST)
        ph  = moon_phase(today)

        return {
            "location":        "東京",
            "date":            today.isoformat(),
            "sunrise":         _hhmm(s["sunrise"]),
            "sunset":          _hhmm(s["sunset"]),
            "moonrise":        _hhmm(mr),
            "moonset":         _hhmm(ms),
            "moon_phase":      round(ph, 1),
            "moon_phase_name": _moon_phase_label(ph),
        }
    except Exception as exc:
        logger.warning("live sun moon failed: %s", exc)
        return {
            "location":        "東京",
            "date":            None,
            "sunrise":         None,
            "sunset":          None,
            "moonrise":        None,
            "moonset":         None,
            "moon_phase":      None,
            "moon_phase_name": None,
        }

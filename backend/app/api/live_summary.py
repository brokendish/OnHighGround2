"""
live_summary.py — /live サマリー API

GET /api/live/summary
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from app.services.live_summary_service import build_live_summary

router = APIRouter(prefix="/api/live", tags=["live"])


@router.get("/summary")
async def get_live_summary() -> Dict[str, Any]:
    """
    全国危険度サマリーを返す。

    各カテゴリに evaluated フラグを持ち、
    タイル表示のみのソース（rain / kikikuru）は evaluated=false で
    危険度の断定を防ぐ。
    """
    return await build_live_summary()

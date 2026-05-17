"""
navigation.py — ナビゲーション API (Phase3-A)

重要:
  - ルート比較提示のみ。自動 reroute は行わない。
  - OSRM weighting 非改変。
  - unknown を none に倒さない。
"""
import logging
from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from app.services.route_comparison_service import get_route_comparison

logger = logging.getLogger(__name__)
router = APIRouter()


class _RouteCompareRequest(BaseModel):
    origin:      list[float]  # [lon, lat]
    destination: list[float]  # [lon, lat]

    @field_validator("origin", "destination")
    @classmethod
    def validate_lonlat(cls, v: list[float]) -> list[float]:
        if len(v) < 2:
            raise ValueError("origin/destination must have at least 2 elements [lon, lat]")
        lon, lat = float(v[0]), float(v[1])
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise ValueError(f"invalid lon={lon} lat={lat}")
        return [lon, lat]


@router.post("/api/navigation/route/compare")
async def compare_routes(body: _RouteCompareRequest):
    """
    ルート比較 × 気象＋ハザード統合リスク (Phase3-A)。

    OSRM alternatives を取得し、各ルートを
    降水強度 × ハザードゾーン通過率 で評価してランク付けする。

    request:
      origin:      [lon, lat]
      destination: [lon, lat]

    response:
      status:                   ok | unavailable
      recommended_route_index:  推奨ルートのインデックス (0-based)
      routes[]:
        index          — ルートインデックス
        distance_m     — ルート距離（メートル）
        duration_s     — 推定所要時間（秒）
        risk_level     — none | advisory | warning | emergency | unknown
        safety_score   — 0–100（高いほど安全）
        risk_summary   — [str] リスク説明テキスト（最大3件）
        hazards        — {flood, lowland, landslide, ...} (bool|null)
        weather        — {forecast_max_intensity}

    重要: このAPIは比較情報の提供のみ。自動 reroute は行わない。
    """
    try:
        return get_route_comparison(body.origin, body.destination)
    except Exception as exc:
        logger.exception("route compare endpoint error: %s", exc)
        return {
            "status":                  "unavailable",
            "recommended_route_index": 0,
            "routes":                  [],
            "updated_at":              None,
        }

"""
TTI (Time to Impact) サービス

ハザードごとの到達時間計算を統一インターフェースで提供する。

- compute_tti(hazard_name, lat, lon) → TTI 結果 dict
- 対応ハザードは hazard_definitions の has_time_to_impact=True のもの
- 現在対応: tsunami（重心距離近似 v1）
- flood / storm_surge: supported=False を返す
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hazard_service import HazardService

logger = logging.getLogger(__name__)

# TTI 結果 dict のキー定義（ドキュメント）
#
# {
#     "supported": bool       — このハザードが TTI 計算に対応しているか
#     "computed":  bool       — 実際に TTI が算出されたか
#     "minutes":   float|None — 到達時間（分）。computed=False の場合は None
#     "reason":    str|None   — computed=True 時は算出方法、False 時は理由
# }
#
# reason 一覧:
#   "distance_based_estimation" — 重心距離近似（tsunami v1）
#   "not_supported"             — このハザードは TTI 未対応
#   "not_in_hazard_zone"        — 該当ハザードのポリゴン外（またはデータなし）
#   "time_margin_disabled"      — enable_time_margin=False により無効化


class TTIService:
    """
    各ハザードの TTI（Time to Impact: 到達時間）を計算するサービス。

    HazardEngine から呼び出される。HazardService（ポリゴン判定）は
    コンストラクタで受け取り、内部で保持する。

    Usage:
        service = TTIService(
            hazard_service=hazard_service,
            tsunami_speed_kmh=30.0,
            enable_time_margin=True,
        )
        result = service.compute_tti("tsunami", lat, lon)
        # → {"supported": True, "computed": True, "minutes": 12.3, "reason": "distance_based_estimation"}
    """

    def __init__(
        self,
        hazard_service: "HazardService",
        tsunami_speed_kmh: float = 30.0,
        enable_time_margin: bool = True,
    ) -> None:
        self._service = hazard_service
        self._tsunami_speed_kmh = tsunami_speed_kmh
        self._enable_time_margin = enable_time_margin

    def compute_tti(self, hazard_name: str, lat: float, lon: float) -> dict:
        """
        指定ハザードの TTI を計算する。

        Args:
            hazard_name: ハザード識別子（例: "tsunami", "flood"）
            lat: 緯度
            lon: 経度

        Returns:
            {
                "supported": bool,
                "computed": bool,
                "minutes": float | None,
                "reason": str | None,
            }
        """
        if not self._enable_time_margin:
            return {
                "supported": hazard_name == "tsunami",
                "computed": False,
                "minutes": None,
                "reason": "time_margin_disabled",
            }

        if hazard_name == "tsunami":
            return self._compute_tsunami(lat, lon)

        # flood / storm_surge など未対応ハザード
        return {
            "supported": False,
            "computed": False,
            "minutes": None,
            "reason": "not_supported",
        }

    # ──────────────────────────────────────────────────────────────────────
    # ハザード別プライベートメソッド
    # ──────────────────────────────────────────────────────────────────────

    def _compute_tsunami(self, lat: float, lon: float) -> dict:
        """
        tsunami の TTI を重心距離近似で計算する（v1）。

        現在地が津波浸水ポリゴン内にある場合、そのポリゴン重心までの
        距離と津波速度から到達時間を概算する。

        精度: 低め。将来的に津波伝播シミュレーション結果への置き換えを検討。
        """
        dist_m = self._service.get_tsunami_centroid_distance_m(lat, lon)
        if dist_m is None:
            return {
                "supported": True,
                "computed": False,
                "minutes": None,
                "reason": "not_in_hazard_zone",
            }

        speed_m_per_min = self._tsunami_speed_kmh * 1000.0 / 60.0
        minutes = dist_m / speed_m_per_min

        logger.debug(
            "TTIService tsunami: dist_m=%.0f speed_kmh=%.0f minutes=%.1f",
            dist_m, self._tsunami_speed_kmh, minutes,
        )
        return {
            "supported": True,
            "computed": True,
            "minutes": minutes,
            "reason": "distance_based_estimation",
        }

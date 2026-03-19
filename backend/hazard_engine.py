"""
Hazard Engine: ハザード評価の共通インターフェース

HazardService (低レベル: データ保持・ポリゴン判定) をラップし、
評価・TTI・RSA 連携の責務を一元化する。

main.py は HazardEngine を通じてハザード評価を行う。
HazardService の詳細（どのハザードが何の形式か）を main.py が知る必要はない。

設計方針:
  - HazardService: ポリゴン保持・点判定の低レベルサービス（変更なし）
  - HazardEngine: 評価オーケストレーション（TTI/RSA 連携を含む）
  - hazard_definitions: ハザードの性質・対応状況の定義（コード外の知識）
"""

import logging
from typing import Dict, List, Optional

from hazard_service import HazardService, HazardResult, derive_hazard_safe
from hazard_definitions import (
    get_definition,
    get_backend_enabled_definitions,
    get_rsa_supporting_definitions,
    get_tti_supporting_definitions,
)

logger = logging.getLogger(__name__)


class HazardEngine:
    """
    ハザード評価の共通エンジン。

    HazardService が保持するポリゴンデータを使い、
    点に対する評価・TTI 計算・RSA 連携判断などを提供する。

    Usage:
        engine = HazardEngine(hazard_service, enable_time_margin=True, tsunami_speed_kmh=30.0)

        # 現在地判定
        point = engine.evaluate_point(lat, lon)
        # -> {"is_danger": True, "hazards": ["flood"], "hazard_assessment": {"flood": "inside"}}

        # 候補地評価
        dest = engine.evaluate_destination(lat, lon)
        # -> {"hazard_assessment": {"flood": "outside"}, "hazard_safe": True}

        # TTI
        tti = engine.get_time_to_impact(lat, lon)
        # -> 45.2  or None
    """

    def __init__(
        self,
        hazard_service: HazardService,
        enable_time_margin: bool = True,
        tsunami_speed_kmh: float = 30.0,
    ) -> None:
        self._service = hazard_service
        self._enable_time_margin = enable_time_margin
        self._tsunami_speed_kmh = tsunami_speed_kmh

        loaded = self._service.loaded_hazard_types()
        logger.info(
            "HazardEngine initialized: loaded_hazards=%s time_margin=%s tsunami_speed=%.0fkm/h",
            loaded,
            enable_time_margin,
            tsunami_speed_kmh,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # 有効ハザード情報
    # ──────────────────────────────────────────────────────────────────────────

    def get_loaded_hazards(self) -> List[str]:
        """実際にデータがロードされているハザード種別一覧。"""
        return self._service.loaded_hazard_types()

    def get_rsa_supporting_hazards(self) -> List[str]:
        """RSA をサポートするハザード名一覧（定義ベース）。"""
        return [d.name for d in get_rsa_supporting_definitions()]

    def get_tti_supporting_hazards(self) -> List[str]:
        """TTI をサポートするハザード名一覧（定義ベース）。"""
        return [d.name for d in get_tti_supporting_definitions()]

    # ──────────────────────────────────────────────────────────────────────────
    # ポイント評価
    # ──────────────────────────────────────────────────────────────────────────

    def evaluate_point(self, lat: float, lon: float) -> Dict:
        """
        現在地のハザード判定を返す。

        /api/hazard-check や /api/evacuation の現在地判定に使用する。

        Returns:
            {
                "is_danger": bool,
                "hazards": List[str],             # 危険判定されたハザード名リスト
                "hazard_assessment": Dict[str, str],  # {"flood": "outside", ...}
            }
        """
        basic = self._service.check_hazards(lat, lon)
        assessment = self._service.assess_candidate(lat, lon)
        return {
            "is_danger": basic["is_danger"],
            "hazards": basic["hazards"],
            "hazard_assessment": assessment,
        }

    def evaluate_destination(self, lat: float, lon: float) -> Dict:
        """
        候補地のハザード評価を返す。

        避難先候補の安全性評価に使用する。

        Returns:
            {
                "hazard_assessment": Dict[str, str],  # {"flood": "outside", ...}
                "hazard_safe": bool | None,
            }
        """
        assessment = self._service.assess_candidate(lat, lon)
        hazard_safe = derive_hazard_safe(assessment)
        return {
            "hazard_assessment": assessment,
            "hazard_safe": hazard_safe,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # TTI (Time to Impact)
    # ──────────────────────────────────────────────────────────────────────────

    def get_time_to_impact(self, lat: float, lon: float) -> Optional[float]:
        """
        現在地の到達時間 (minutes) を返す。

        対応ハザード: tsunami（v1: 重心距離近似）
        flood / storm_surge は現在未対応 (has_time_to_impact=False)。

        Returns:
            float: TTI (分)。ポリゴン外 / 時間マージン無効 / 未ロードの場合は None。
        """
        if not self._enable_time_margin:
            return None
        dist_m = self._service.get_tsunami_centroid_distance_m(lat, lon)
        if dist_m is None:
            return None
        speed_m_per_min = self._tsunami_speed_kmh * 1000.0 / 60.0
        return dist_m / speed_m_per_min

    def get_tti_status_for_hazard(self, hazard_name: str) -> str:
        """
        ハザード定義から TTI 対応状況を文字列で返す。

        Returns:
            "supported" | "unsupported" | "unknown"
        """
        defn = get_definition(hazard_name)
        if defn is None:
            return "unknown"
        return "supported" if defn.has_time_to_impact else "unsupported"

    # ──────────────────────────────────────────────────────────────────────────
    # 内部共通評価サマリー
    # ──────────────────────────────────────────────────────────────────────────

    def build_assessment_summary(
        self,
        lat: float,
        lon: float,
        tti_minutes: Optional[float] = None,
    ) -> Dict[str, Dict]:
        """
        点に対する全ハザード評価を統一形式で返す（内部利用向け）。

        外向け API レスポンスとは独立した内部共通形式。
        将来の評価ロジック拡張（重み付け・複合判定など）の基盤として使用する。

        Returns:
            {
                "flood": {
                    "status": "inside" | "outside" | "unknown",
                    "safe": bool,
                    "time_to_impact_minutes": float | None,
                    "tti_status": "supported" | "unsupported" | "unknown" | "computed",
                },
                ...
            }
        """
        assessment = self._service.assess_candidate(lat, lon)
        summary: Dict[str, Dict] = {}

        for hazard_name, status in assessment.items():
            defn = get_definition(hazard_name)
            has_tti = defn.has_time_to_impact if defn else False

            tti_val: Optional[float] = None
            tti_stat: str
            if not has_tti:
                tti_stat = "unsupported"
            elif tti_minutes is not None:
                tti_val = tti_minutes
                tti_stat = "computed"
            else:
                tti_stat = "unknown"

            summary[hazard_name] = {
                "status": status,
                "safe": status == "outside",
                "time_to_impact_minutes": tti_val,
                "tti_status": tti_stat,
            }

        return summary

    # ──────────────────────────────────────────────────────────────────────────
    # 低レベル HazardService へのアクセサ
    # ──────────────────────────────────────────────────────────────────────────

    def get_polygon_store(self) -> Dict:
        """RSA 計算のために内部ポリゴンストアを返す。"""
        return self._service.get_polygon_store()

    def polygon_count(self, hazard_type: str) -> int:
        """指定ハザードのポリゴン数を返す (health check 用)。"""
        return self._service.polygon_count(hazard_type)

    def loaded_sources(self, hazard_type: str) -> List[str]:
        """指定ハザードのロード済みファイルステム一覧 (health check 用)。"""
        return self._service.loaded_sources(hazard_type)

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
from services.tti_service import TTIService

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
        self._tti_service = TTIService(
            hazard_service=hazard_service,
            tsunami_speed_kmh=tsunami_speed_kmh,
            enable_time_margin=enable_time_margin,
        )

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

    def get_time_to_impact_detail(self, lat: float, lon: float) -> Dict:
        """
        現在地の TTI を構造化形式で返す。

        TTI に対応するハザード（現在は tsunami のみ）で計算を試み、
        最初に computed=True となった結果を返す。
        すべて未対応 / 未計算の場合は最後のハザードの結果を返す。

        Returns:
            {
                "supported": bool,
                "computed": bool,
                "minutes": float | None,
                "reason": str | None,   # "distance_based_estimation" | "not_in_hazard_zone" | ...
            }
        """
        tti_defs = get_tti_supporting_definitions()
        if not tti_defs:
            return {
                "supported": False,
                "computed": False,
                "minutes": None,
                "reason": "not_supported",
            }

        # TTI 対応ハザードを順に試みる（現在は tsunami のみ）
        last_result: Dict = {
            "supported": False,
            "computed": False,
            "minutes": None,
            "reason": "not_supported",
        }
        for defn in tti_defs:
            result = self._tti_service.compute_tti(defn.name, lat, lon)
            last_result = result
            if result["computed"]:
                return result

        return last_result

    def get_time_to_impact(self, lat: float, lon: float) -> Optional[float]:
        """
        現在地の到達時間 (minutes) を返す。後方互換インターフェース。

        Returns:
            float: TTI (分)。computed=False の場合は None。
        """
        detail = self.get_time_to_impact_detail(lat, lon)
        return detail["minutes"] if detail["computed"] else None

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
        capability-based 設計に基づき、各ハザードの TTI を TTIService 経由で計算する。

        Returns:
            {
                "flood": {
                    "status": "inside" | "outside" | "unknown",
                    "safe": bool,
                    "tti": {
                        "supported": bool,
                        "computed": bool,
                        "minutes": float | None,
                        "reason": str | None,
                    },
                },
                ...
            }
        """
        assessment = self._service.assess_candidate(lat, lon)
        summary: Dict[str, Dict] = {}

        for hazard_name, raw_value in assessment.items():
            defn = get_definition(hazard_name)
            has_tti = defn.capabilities["time_to_impact"] if defn else False

            # 文字列（既存ハザード）と dict（severity 付きハザード）の両方を扱う
            if isinstance(raw_value, dict):
                status_str = raw_value.get("status", "unknown")
            else:
                status_str = raw_value

            if has_tti:
                tti_detail = self._tti_service.compute_tti(hazard_name, lat, lon)
            else:
                tti_detail = {
                    "supported": False,
                    "computed": False,
                    "minutes": None,
                    "reason": "not_supported",
                }

            summary[hazard_name] = {
                "status": raw_value,  # inland_flood/landslide は dict ごと格納
                "safe": status_str == "outside",
                "tti": tti_detail,
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

"""
ハザード定義モジュール

各ハザード種別の性質・対応状況を一元管理する。

新しいハザードを追加する際は HAZARD_DEFINITIONS リストに定義を追加するだけでよい。
ハザード固有の知識をコード内に散在させず、ここに集約する。
"""

from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class HazardDefinition:
    """ハザード種別の定義。"""

    name: str
    """識別子 (e.g. "flood")。コード内のキーとして使用。"""

    display_name: str
    """表示名 (e.g. "洪水浸水想定")。ログ・ドキュメント向け。"""

    backend_enabled: bool
    """backend でポリゴン判定を行うか。app.properties の設定で無効化できる場合がある。"""

    frontend_enabled: bool
    """frontend でレイヤー表示を行うか（frontend 側の実装状況を示す）。"""

    has_polygon_check: bool
    """inside/outside ポリゴン判定が実装されているか。"""

    has_time_to_impact: bool
    """TTI（到達時間）計算が実装されているか。"""

    supports_rsa: bool
    """このハザードが RSA（到達可能安全エリア）計算に関与するか。"""

    source_type: str
    """データ形式: "geojsonl" | "geojson" | "geojson_dir"。"""

    evaluation_mode: str
    """評価方式: "inside_outside" | "none"。"""

    notes: str = ""
    """補足メモ。"""

    enabled: bool = True
    """ハザードが全体として有効かどうか（backend + frontend 両方が有効な場合に True）。"""

    @property
    def capabilities(self) -> Dict[str, bool]:
        """ハザードの能力マップ（capability-based 設計のエントリポイント）。

        キー:
            polygon_check  — inside/outside ポリゴン判定が実装されているか
            time_to_impact — TTI（到達時間）計算が実装されているか
            rsa_support    — RSA（到達可能安全エリア）計算に関与するか
        """
        return {
            "polygon_check": self.has_polygon_check,
            "time_to_impact": self.has_time_to_impact,
            "rsa_support": self.supports_rsa,
        }


# ──────────────────────────────────────────────────────────────────────────────
# ハザード定義一覧
# ──────────────────────────────────────────────────────────────────────────────
HAZARD_DEFINITIONS: List[HazardDefinition] = [
    # ── 実装済みハザード ────────────────────────────────────────────────────────

    HazardDefinition(
        name="flood",
        display_name="洪水浸水想定",
        backend_enabled=True,
        frontend_enabled=True,
        has_polygon_check=True,
        has_time_to_impact=False,  # TTI 未実装（Phase 3.x 以降の課題）
        supports_rsa=False,        # RSA は現在 tsunami のみ
        source_type="geojsonl",
        evaluation_mode="inside_outside",
        notes="bbox_only モードで読み込み（大容量データ対策）。hazard.flood.enabled で制御。",
    ),

    HazardDefinition(
        name="storm_surge",
        display_name="高潮浸水想定",
        backend_enabled=True,
        frontend_enabled=True,
        has_polygon_check=True,
        has_time_to_impact=False,  # TTI 未実装
        supports_rsa=False,
        source_type="geojson",
        evaluation_mode="inside_outside",
    ),

    HazardDefinition(
        name="tsunami",
        display_name="津波浸水想定",
        backend_enabled=True,
        frontend_enabled=True,
        has_polygon_check=True,
        has_time_to_impact=True,   # TTI v1 実装済み（重心距離近似）
        supports_rsa=True,         # RSA は tsunami TTI を使用
        source_type="geojson_dir",
        evaluation_mode="inside_outside",
        notes="複数都県ファイル対応（tokyo/kanagawa/chiba）。TTI は重心距離近似 (v1 案A)。",
    ),

    # ── Phase 4 追加ハザード ─────────────────────────────────────────────────

    HazardDefinition(
        name="inland_flood",
        display_name="内水氾濫",
        backend_enabled=True,
        frontend_enabled=True,
        has_polygon_check=True,
        has_time_to_impact=False,  # TTI は Phase 4.1 以降
        supports_rsa=False,
        source_type="geojson",
        evaluation_mode="inside_outside",
        notes="Phase 4 追加。サンプルデータで動作確認。TTI/RSA は将来拡張。",
        enabled=True,
    ),

    HazardDefinition(
        name="landslide",
        display_name="土砂災害",
        backend_enabled=True,
        frontend_enabled=True,
        has_polygon_check=True,
        has_time_to_impact=False,  # TTI は Phase 4.1 以降
        supports_rsa=False,
        source_type="geojson",
        evaluation_mode="inside_outside",
        notes="Phase 4 追加。警戒区域・特別警戒区域を保持。TTI/RSA は将来拡張。",
        enabled=True,
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# ヘルパー関数
# ──────────────────────────────────────────────────────────────────────────────

def get_definition(name: str) -> Optional[HazardDefinition]:
    """ハザード名から定義を返す。見つからなければ None。"""
    for d in HAZARD_DEFINITIONS:
        if d.name == name:
            return d
    return None


def get_backend_enabled_definitions() -> List[HazardDefinition]:
    """backend 判定が有効なハザード定義一覧。"""
    return [d for d in HAZARD_DEFINITIONS if d.backend_enabled]


def get_rsa_supporting_definitions() -> List[HazardDefinition]:
    """RSA をサポートするハザード定義一覧。"""
    return [d for d in HAZARD_DEFINITIONS if d.supports_rsa]


def get_tti_supporting_definitions() -> List[HazardDefinition]:
    """TTI をサポートするハザード定義一覧。"""
    return [d for d in HAZARD_DEFINITIONS if d.has_time_to_impact]

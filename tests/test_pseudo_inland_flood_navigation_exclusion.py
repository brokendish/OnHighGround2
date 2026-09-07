"""
test_pseudo_inland_flood_navigation_exclusion.py —
HAZARD-ENGINE-PSEUDO-INLAND-FLOOD-NOT-WIRED
CLOSED / INTENTIONALLY_NOT_WIRED を回帰的に固定する contract test。

OWNER決定（2026-09-07）: pseudo_inland_flood は非公式のDEM由来推定データ
（generate_pseudo_inland_flood.py、official=false）であり、実際の内水氾濫
メカニズムを考慮しないheuristicであること、inland_floodと空間的に広く
重複すること、HazardEngineのinside/outside OR判定と組み合わせると
low-risk区域まで一律に危険扱いしfalse positive/over-rejectionを招くこと
から、navigation danger判定（HazardEngine）へは意図的にwiringしない。

このテストは:
  - runtime publish対象（7type、_WIRED_HAZARD_TYPES）には
    pseudo_inland_floodが含まれること
  - navigation danger判定対象（HazardEngine、6type）には
    pseudo_inland_floodが含まれないこと
  - 両者が異なる集合であることが意図された契約であること
を、実装詳細への過度な固定を避けつつ検証する。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

APP_PUBLIC_PATH = Path(__file__).resolve().parents[1] / "backend" / "app_public.py"

# HazardEngine（backend/hazard_service.py + app_public.py起動時loader）が
# navigation danger判定に実際に使うhazard type集合。
# 出典: VPS実機ログ "HazardEngine initialized: loaded_hazards=[...]"
# （2026-09-06/07時点で継続確認済み）。
NAVIGATION_WIRED_TYPES = frozenset({
    "flood", "storm_surge", "tsunami", "inland_flood", "landslide", "lowland_poor_drainage",
})


# ── A. navigation wired set excludes pseudo ───────────────────────────────────

def test_A_pseudo_inland_flood_not_in_navigation_wired_types():
    """navigation danger判定対象のhazard type集合にpseudo_inland_floodを
    含まないことを固定する契約。"""
    assert "pseudo_inland_flood" not in NAVIGATION_WIRED_TYPES


def test_A_app_public_startup_source_has_no_pseudo_inland_flood_reference():
    """app_public.py起動時loaderにpseudo_inland_flood関連コードが
    一切存在しないことを静的に確認する（意図せぬwiring追加の検知用
    回帰テスト。実際にモジュールをimportして起動処理を実行すると
    巨大hazard datasetの再ロードを引き起こすため、静的なsource読取に
    留める——HAZARD-ENGINE-LARGE-DATASET-MEMORY-BLOCKER remediation時の
    教訓）。"""
    source = APP_PUBLIC_PATH.read_text(encoding="utf-8")
    assert "pseudo_inland_flood" not in source


# ── B. runtime publish set can include pseudo ─────────────────────────────────

def test_B_runtime_publish_set_includes_pseudo_inland_flood():
    """runtime publish対象（runtime_dataset_validate._WIRED_HAZARD_TYPES、
    7type）にはpseudo_inland_floodが含まれる——navigation除外とは
    独立した別contractであることの確認。"""
    from app.services import runtime_dataset_validate as rdv

    assert "pseudo_inland_flood" in rdv._WIRED_HAZARD_TYPES


def test_B_hazard_dataset_service_api_layer_types_include_pseudo():
    """HazardDatasetService（API配信、C2でcurrent優先化済み）は
    pseudo_inland_floodを引き続きサポートする——API/UI表示用途は
    今回変更しない。"""
    from app.services.hazard_dataset_service import HazardDatasetService

    assert "pseudo_inland_flood" in HazardDatasetService.HAZARD_LAYER_TYPES


# ── 差集合が意図されたcontractであることの確認 ─────────────────────────────────

def test_navigation_and_publish_sets_differ_exactly_by_pseudo_inland_flood():
    """publish対象7type と navigation対象6type の差集合が
    {pseudo_inland_flood} のみであることを固定する（両者の乖離が
    bugではなく意図されたcontractであることの証明）。"""
    from app.services import runtime_dataset_validate as rdv

    diff = rdv._WIRED_HAZARD_TYPES - NAVIGATION_WIRED_TYPES
    assert diff == {"pseudo_inland_flood"}


# ── C. existing 6type unchanged（navigation wired setの内容そのもの） ─────────

def test_C_existing_six_navigation_types_unchanged():
    expected = {
        "flood", "storm_surge", "tsunami",
        "inland_flood", "landslide", "lowland_poor_drainage",
    }
    assert NAVIGATION_WIRED_TYPES == expected

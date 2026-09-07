"""
test_hazard_legacy_flat_fallback_removed.py —
HAZARD-LEGACY-FLAT-FALLBACK-CONTRACT Phase B 回帰テスト。

OWNER決定（2026-09-07, Candidate B APPROVED）: `app_public.py` 起動時の
flood/storm_surge/tsunami/landslide ローダーが持っていた
「is_available()==False（atomic runtime lease機構が未導入）の場合にのみ
hardcoded legacy flat basename を読む」フォールバックを撤去し、
unsupported deployment modelとしてskip/fail-closedにする。

このテストは、`backend/app_public.py` を直接importせず（起動時に
数百MBのhazard datasetを再ロードしてしまうため——
HAZARD-ENGINE-LARGE-DATASET-MEMORY-BLOCKER remediation時の教訓）、
静的なsource text解析のみで以下を確認する:
  - 対象4 hazard type（flood, storm_surge, tsunami, landslide）の
    起動時ローダーから、legacy flat basename読み込み（`hazard_service.load*`
    呼び出し）が「is_availableでない」分岐から消えていること
  - 各typeの「現行runtimeから発見できた場合」のロード経路自体は無傷であること
  - `_HAZARD_USING_ATOMIC_LEASE` skip分岐（既存のcurrent-missing skip
    semantics）も無傷であること
  - scope外の inland_flood / lowland_poor_drainage の legacy fallbackは
    一切変更されていないこと
  - Section 10: 旧hardcoded legacy filename / config keyの文字列が
    `app_public.py` / `app.properties` から完全に消えていること
    （ただし tsunami_{target}.geojson という命名規則自体は現行/versioned
    側でも使われるため維持されていること）
  - tsunami の data_lake/validated フォールバック階層（durable authoritative
    source、flat legacy artifactとは別contract）は維持されていること
"""
from __future__ import annotations

from pathlib import Path

APP_PUBLIC_PATH = Path(__file__).resolve().parents[1] / "backend" / "app_public.py"
APP_PROPERTIES_PATH = Path(__file__).resolve().parents[1] / "backend" / "app.properties"

_SOURCE = APP_PUBLIC_PATH.read_text(encoding="utf-8")
_PROPERTIES = APP_PROPERTIES_PATH.read_text(encoding="utf-8")

_MARKERS = {
    "flood": ('FLOOD_ENABLED = parse_bool(APP_CONFIG.get("hazard.flood.enabled"', "# storm_surge: 高潮浸水想定区域"),
    "storm_surge": ("# storm_surge: 高潮浸水想定区域", "# tsunami: targets 設定に従ってファイルを個別ロード"),
    "tsunami": ("# tsunami: targets 設定に従ってファイルを個別ロード", "# inland_flood: 内水氾濫想定"),
    "inland_flood": ("# inland_flood: 内水氾濫想定", "# landslide: 土砂災害警戒区域"),
    "landslide": ("# landslide: 土砂災害警戒区域", "# ── 低地・排水困難エリア"),
}

_LEGACY_KEYS = [
    "hazard.flood.check_path",
    "hazard.storm_surge.path",
    "hazard.tsunami.dir",
    "hazard.landslide.path",
]

_LEGACY_FILENAMES = [
    "tokyo_flood_check.geojsonl",
    "tokyo_storm_surge.geojson",
    "tokyo_landslide_A33.geojson",
]


def _block(hazard_type: str) -> str:
    start_marker, end_marker = _MARKERS[hazard_type]
    start = _SOURCE.index(start_marker)
    end = _SOURCE.index(end_marker, start)
    return _SOURCE[start:end]


# ── Section 10: legacy key/filename literal absence ───────────────────────────

def test_section10_legacy_keys_absent_from_app_public():
    for key in _LEGACY_KEYS:
        assert key not in _SOURCE, f"legacy key {key!r} must be fully removed from app_public.py"


def test_section10_legacy_keys_absent_from_app_properties():
    for key in _LEGACY_KEYS:
        assert key not in _PROPERTIES, f"legacy key {key!r} must be fully removed from app.properties"


def test_section10_legacy_filenames_absent_from_app_public():
    for name in _LEGACY_FILENAMES:
        assert name not in _SOURCE, f"legacy filename {name!r} must be fully removed from app_public.py"


def test_section10_legacy_filenames_absent_from_app_properties():
    for name in _LEGACY_FILENAMES:
        assert name not in _PROPERTIES, f"legacy filename {name!r} must be fully removed from app.properties"


def test_section10_tsunami_target_naming_pattern_preserved():
    """tsunami_{target}.geojson という命名規則自体は current/versioned 側でも
    使われるため、legacy filename除去の巻き添えで消えていないことを確認する。"""
    assert 'f"tsunami_{_target}.geojson"' in _SOURCE


# ── F: flood/storm_surge/landslide share the same removed-fallback contract ──

def test_F_flood_storm_surge_landslide_share_same_contract():
    for hazard_type in ("flood", "storm_surge", "landslide"):
        block = _block(hazard_type)
        # legacy単一パスfallback用のkeyがブロック内に残っていないこと
        # （=legacy hardcoded flat basename読み込みの消滅）。
        for key in _LEGACY_KEYS:
            assert key not in block, f"{hazard_type}: legacy key {key!r} must be removed from this block"
        # skip/fail-closedのログ文言が残っていること
        assert "unsupported" in block.lower() or "未導入" in block, (
            f"{hazard_type}: expected an explicit skip/fail-closed log for atomic-lease-unavailable case"
        )


# ── A: current/versioned discovery path (runtime dir scan) is unchanged ──────

def test_A_flood_storm_surge_landslide_runtime_discovery_unchanged():
    for hazard_type in ("flood", "storm_surge", "landslide"):
        block = _block(hazard_type)
        assert "_HAZARD_BACKEND_ROOT /" in block
        assert ".rglob(\"*.geojson" in block
        assert "hazard_service.load" in block  # still called in the "found" branch


# ── B: atomic-lease-active-but-missing skip semantics unchanged ──────────────

def test_B_atomic_lease_missing_skip_semantics_unchanged():
    for hazard_type in ("flood", "storm_surge", "landslide"):
        block = _block(hazard_type)
        assert "elif _HAZARD_USING_ATOMIC_LEASE:" in block
        assert "snapshot混在防止" in block


# ── C/D/E: legacy flat file is no longer read regardless of size/existence ───

def test_C_flood_storm_surge_landslide_final_else_has_no_load_call():
    """is_available()==False（最終else）分岐からは、legacy flat fileの
    存在・サイズに関わらず、いかなる hazard_service.load* 呼び出しも
    行われないことを確認する（読まれる前に静的にコードが存在しないため、
    ファイルの中身に関する動的検証は不要——これはsource-level contractの
    確認である）。"""
    for hazard_type in ("flood", "storm_surge", "landslide"):
        block = _block(hazard_type)
        # 末尾の else: 節を抽出（atomic-lease elifの後）
        lease_idx = block.index("elif _HAZARD_USING_ATOMIC_LEASE:")
        else_idx = block.index("\n    else:", lease_idx) if "\n    else:" in block[lease_idx:] else block.index("\nelse:", lease_idx)
        tail = block[else_idx:]
        # 次のトップレベル文（else節の終わり）までを見る簡易上限として
        # hazard_service.load呼び出しが全く無いことを確認
        assert "hazard_service.load" not in tail, f"{hazard_type}: final else must not call hazard_service.load*"
        assert "resolve_existing_path" not in tail, f"{hazard_type}: final else must not call resolve_existing_path"


# ── Tsunami-specific: validated fallback kept, normalized/legacy-dir removed ─

def test_tsunami_validated_fallback_tier_preserved():
    block = _block("tsunami")
    assert "_tsunami_validated_dir" in block
    assert "data_lake" in block and "validated" in block


def test_tsunami_normalized_legacy_dir_tier_removed():
    block = _block("tsunami")
    assert "_tsunami_dir" not in block  # legacy hazard.tsunami.dir-driven variable removed
    assert "_normalized_path" not in block


def test_tsunami_runtime_and_lease_skip_semantics_unchanged():
    block = _block("tsunami")
    assert "_tsunami_runtime_dir" in block
    assert "elif _HAZARD_USING_ATOMIC_LEASE:" in block
    assert "snapshot混在防止" in block


# ── Scope guard: inland_flood / lowland_poor_drainage untouched ──────────────

def test_inland_flood_legacy_fallback_untouched():
    """OWNER Phase B instructionのscope外——inland_floodの既存legacy
    fallbackパターン（hazard.inland_flood.path、resolve_existing_path）は
    本remediationで一切変更してはならない。"""
    block = _block("inland_flood")
    assert "hazard.inland_flood.path" in block
    assert "resolve_existing_path" in block
    assert "inland_flood_sample.geojson" in block


def test_lowland_poor_drainage_section_still_present_and_unrelated():
    assert "lowland_poor_drainage" in _SOURCE
    # low_land sectionはこのremediationの4 legacy keyのいずれも参照しない
    lowland_start = _SOURCE.index("# ── 低地・排水困難エリア")
    lowland_block = _SOURCE[lowland_start: lowland_start + 3000]
    for key in _LEGACY_KEYS:
        assert key not in lowland_block


# ── G/H: existing hazard-type-set regressions (imported safely, no side effects) ─

def test_G_hazard_engine_six_type_navigation_set_unchanged():
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
    from app.services import runtime_dataset_validate as rdv

    navigation_wired_types = frozenset({
        "flood", "storm_surge", "tsunami", "inland_flood", "landslide", "lowland_poor_drainage",
    })
    assert rdv._WIRED_HAZARD_TYPES - navigation_wired_types == {"pseudo_inland_flood"}


def test_H_pseudo_inland_flood_still_not_referenced_in_app_public():
    assert "pseudo_inland_flood" not in _SOURCE

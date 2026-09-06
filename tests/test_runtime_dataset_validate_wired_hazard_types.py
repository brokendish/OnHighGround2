"""
test_runtime_dataset_validate_wired_hazard_types.py — Dual Storage
Remediation Phase C1 atomic-publish blocker fix.

runtime_dataset_validate.py の `_WIRED_HAZARD_TYPES`（参照整合性guard、
CODEX P2B5-CX-003第6ラウンド）に `pseudo_inland_flood` を追加した変更を
検証する。このguardは「consumerに配線されていないorphan hazard typeを
publishしない」ためのものであり、pseudo_inland_flood はHazardDatasetService
（backend/app/services/hazard_dataset_service.py）に既にconsumerとして
配線済み・registry登録済み・Tokyo-only support contract確立済みのため、
正式対応typeとしてallowlistへ追加した——unknown typeを許可する一般化では
ない。

検証観点（OWNER指示 Section 4 A〜F）:
  A. pseudo_inland_flood/tokyo が存在 → PASS
  B. pseudo_inland_flood/kanagawa 不在（unsupported region） → PASS
     （directory自体が無いだけであり、エラーにはならない）
  C. unknown hazard type → 従来どおりFAIL（一般化していないことの証明）
  D. 既存6type（wired）は引き続きPASS（regressionなし）
  E. 7type全部が揃ったstaging treeがPASS
  F. orphan/unwired type guard自体は維持されている（Cと同一だが明示）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import runtime_dataset_validate as rdv  # noqa: E402
from app.services.runtime_atomic import RuntimeAtomicError  # noqa: E402


def _feature(props: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [139.0, 35.0]},
        "properties": props,
    }


def _write_feature_collection(path: Path, count: int, props_fn=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    features = [_feature(props_fn(i) if props_fn else {}) for i in range(count)]
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}),
        encoding="utf-8",
    )


def _landslide_props(i: int) -> dict:
    return {
        "hazard_type": "landslide", "landslide_type": "debris_flow", "zone_type": "special",
        "severity_level": "1", "zone_name": f"zone-{i}", "pref_code": "13", "source": "test",
    }


def _flood_props(i: int) -> dict:
    return {"flood_rank": 3}


def _storm_surge_props(i: int) -> dict:
    return {"storm_surge_rank": 3}


def _inland_flood_props(i: int) -> dict:
    return {
        "depth_rank": 3, "depth_min_m": 1.0, "depth_label": "x",
        "zone_name": f"zone-{i}", "city_code": "13101",
    }


def _lowland_props(i: int) -> dict:
    return {
        "dataset": "d", "source": "s", "risk": "r", "risk_score": 3,
        "region": "tokyo", "elevation_m": 1.0, "depth_below_tide_m": 1.0,
    }


def _tsunami_props(i: int) -> dict:
    return {"A40_001": "x", "A40_002": "y", "A40_003": "z"}


def _no_tsunami_requirement():
    """tsunami consumer設定への依存を切り離す（configured targets=空集合、
    tsunami directory自体も作らないため exact-match が自動的に成立する）。"""
    return patch.object(rdv, "_resolve_configured_tsunami_targets", return_value=(frozenset(), None))


# ── A. pseudo_inland_flood/tokyo が存在 → PASS ────────────────────────────────

def test_A_pseudo_inland_flood_tokyo_present_passes(tmp_path):
    staging = tmp_path / "staging"
    (staging / "backend").mkdir(parents=True)
    target = staging / "backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson"
    _write_feature_collection(target, 1)

    with _no_tsunami_requirement():
        manifest, feature_counts = rdv.validate_and_manifest_staging(staging, previous_version_path=None)

    assert "backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson" in manifest
    assert feature_counts["backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson"] == 1


# ── B. pseudo_inland_flood/kanagawa 不在（unsupported region） → PASS ─────────

def test_B_pseudo_inland_flood_kanagawa_absent_still_passes(tmp_path):
    staging = tmp_path / "staging"
    target = staging / "backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson"
    _write_feature_collection(target, 1)
    kanagawa_dir = staging / "backend" / "hazard" / "pseudo_inland_flood" / "kanagawa"
    assert not kanagawa_dir.exists()  # 意図的に作らない

    with _no_tsunami_requirement():
        manifest, _ = rdv.validate_and_manifest_staging(staging, previous_version_path=None)

    assert not kanagawa_dir.exists()  # validatorが強制生成しないこと
    assert "backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson" in manifest


# ── C. unknown hazard type → 従来どおりFAIL ────────────────────────────────────

def test_C_unknown_hazard_type_still_rejected(tmp_path):
    staging = tmp_path / "staging"
    target = staging / "backend/hazard/totally_unknown_hazard_type/tokyo/x.geojson"
    _write_feature_collection(target, 1)

    with _no_tsunami_requirement():
        with pytest.raises(RuntimeAtomicError, match="参照整合性違反.*配線されていないhazard type"):
            rdv.validate_and_manifest_staging(staging, previous_version_path=None)


# ── D. 既存6type（wired）は引き続きPASS（regressionなし） ─────────────────────

@pytest.mark.parametrize(
    "layer_type,min_count,props_fn",
    [
        ("flood", 100, _flood_props),
        ("storm_surge", 100, _storm_surge_props),
        ("landslide", 100, _landslide_props),
        ("inland_flood", 50, _inland_flood_props),
        ("lowland_poor_drainage", 50, _lowland_props),
    ],
)
def test_D_existing_wired_type_regression(tmp_path, layer_type, min_count, props_fn):
    staging = tmp_path / "staging"
    target = staging / f"backend/hazard/{layer_type}/tokyo/x.geojson"
    _write_feature_collection(target, min_count, props_fn=props_fn)

    with _no_tsunami_requirement():
        manifest, feature_counts = rdv.validate_and_manifest_staging(staging, previous_version_path=None)

    rel = f"backend/hazard/{layer_type}/tokyo/x.geojson"
    assert rel in manifest
    assert feature_counts[rel] == min_count


def test_D_existing_tsunami_type_regression(tmp_path):
    staging = tmp_path / "staging"
    target = staging / "backend/hazard/tsunami/tsunami_tokyo.geojson"
    _write_feature_collection(target, 100, props_fn=_tsunami_props)

    with patch.object(rdv, "_resolve_configured_tsunami_targets", return_value=(frozenset({"tokyo"}), None)):
        manifest, feature_counts = rdv.validate_and_manifest_staging(staging, previous_version_path=None)

    assert "backend/hazard/tsunami/tsunami_tokyo.geojson" in manifest


# ── E. 7type全部が揃ったstaging treeがPASS ────────────────────────────────────

def test_E_full_7type_staging_tree_passes(tmp_path):
    staging = tmp_path / "staging"
    _write_feature_collection(staging / "backend/hazard/flood/tokyo/x.geojson", 100, _flood_props)
    _write_feature_collection(staging / "backend/hazard/storm_surge/tokyo/x.geojson", 100, _storm_surge_props)
    _write_feature_collection(staging / "backend/hazard/landslide/tokyo/x.geojson", 100, _landslide_props)
    _write_feature_collection(staging / "backend/hazard/inland_flood/tokyo/x.geojson", 50, _inland_flood_props)
    _write_feature_collection(staging / "backend/hazard/lowland_poor_drainage/tokyo/x.geojson", 50, _lowland_props)
    _write_feature_collection(staging / "backend/hazard/tsunami/tsunami_tokyo.geojson", 100, _tsunami_props)
    _write_feature_collection(
        staging / "backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson", 1
    )
    # pseudo_inland_flood/kanagawa は意図的に作らない（unsupported region）

    with patch.object(rdv, "_resolve_configured_tsunami_targets", return_value=(frozenset({"tokyo"}), None)):
        manifest, feature_counts = rdv.validate_and_manifest_staging(staging, previous_version_path=None)

    expected_files = {
        "backend/hazard/flood/tokyo/x.geojson",
        "backend/hazard/storm_surge/tokyo/x.geojson",
        "backend/hazard/landslide/tokyo/x.geojson",
        "backend/hazard/inland_flood/tokyo/x.geojson",
        "backend/hazard/lowland_poor_drainage/tokyo/x.geojson",
        "backend/hazard/tsunami/tsunami_tokyo.geojson",
        "backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson",
    }
    assert expected_files <= set(manifest.keys())
    assert not (staging / "backend" / "hazard" / "pseudo_inland_flood" / "kanagawa").exists()


# ── F. orphan/unwired type guard自体は維持されている（Cと相補的な明示テスト） ──

def test_F_wired_hazard_types_is_exactly_the_7_authorized_types():
    assert rdv._WIRED_HAZARD_TYPES == frozenset(
        {
            "flood",
            "storm_surge",
            "tsunami",
            "inland_flood",
            "landslide",
            "lowland_poor_drainage",
            "pseudo_inland_flood",
        }
    )


def test_F_guard_still_rejects_a_second_unknown_type_alongside_valid_ones(tmp_path):
    """既知typeと同居していても、unknown typeが1つ混ざればguardは拒否する
    （allowlist追加が一般化ではなく個別追加であることの証明）。"""
    staging = tmp_path / "staging"
    _write_feature_collection(
        staging / "backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson", 1
    )
    _write_feature_collection(staging / "backend/hazard/another_future_type/tokyo/x.geojson", 1)

    with _no_tsunami_requirement():
        with pytest.raises(RuntimeAtomicError, match="参照整合性違反.*配線されていないhazard type"):
            rdv.validate_and_manifest_staging(staging, previous_version_path=None)

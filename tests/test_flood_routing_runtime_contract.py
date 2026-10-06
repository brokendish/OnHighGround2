"""
runtime publish（runtime_dataset_validate.validate_and_manifest_staging / activate_version.py）の
flood routing 契約と初回 migration のテスト。

runtime contract:
  - backend/hazard/flood/<region>/ には *.routing.geojson のみ許可
  - canonical *.geojson 混入 / canonical + routing 二重配置 / legacy *_flood_check.geojsonl /
    flood 直下 file / routing 0 件 / 空 routing（件数 floor 未満）は reject
  - 他 hazard type（storm_surge 等の *.geojson）は従来どおり許可

migration:
  - flag なし: legacy flood path → routing path の移行は path 消失 guard で reject
  - flag + OWNER 承認参照あり: 前 version に legacy がある初回のみ許可、manifest に記録
  - 2 回目（前 version が既に routing）・初回 publish・承認参照なしは flag 自体を reject
  - flag は legacy flood 以外の消失を許可しない
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import runtime_dataset_validate as rdv  # noqa: E402
from app.services.runtime_atomic import RuntimeAtomicError  # noqa: E402

FLOOD_CANONICAL = "backend/hazard/flood/tokyo/tokyo-river-001.geojson"
FLOOD_ROUTING = "backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson"
SURGE = "backend/hazard/storm_surge/tokyo/tokyo-surge-001.geojson"


def _write_fc(path: Path, count: int, props: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    feats = [{"type": "Feature", "properties": props,
              "geometry": {"type": "Polygon", "coordinates": [[[139.0, 35.0], [139.1, 35.0], [139.1, 35.1],
                                                               [139.0, 35.1], [139.0, 35.0]]]}}
             for _ in range(count)]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")


def _staging(root: Path, files: dict) -> Path:
    for rel, count in files.items():
        props = {"storm_surge_rank": 2} if "storm_surge" in rel else {"flood_rank": 3}
        _write_fc(root / rel, count, props)
    (root / "backend").mkdir(parents=True, exist_ok=True)
    return root


def _validate(staging: Path, previous=None, **kw):
    with patch.object(rdv, "_resolve_configured_tsunami_targets", return_value=(frozenset(), None)):
        return rdv.validate_and_manifest_staging(staging, previous, **kw)


def _published_version(root: Path, files: dict) -> Path:
    """manifest 付きの前 version を作る（件数 guard の比較対象）。"""
    v = _staging(root, files)
    manifest, counts = _validate(v)
    rdv.write_manifest(v, manifest, 0o640, counts)
    return v


# ── runtime contract ────────────────────────────────────────────────────────────

def test_routing_only_passes_with_other_hazards(tmp_path):
    manifest, counts = _validate(_staging(tmp_path / "s", {FLOOD_ROUTING: 120, SURGE: 120}))
    assert counts[FLOOD_ROUTING] == 120
    assert counts[SURGE] == 120  # 他 hazard type は *.geojson のまま影響なし


def test_canonical_in_runtime_rejected(tmp_path):
    with pytest.raises(RuntimeAtomicError, match="routing artifact 以外"):
        _validate(_staging(tmp_path / "s", {FLOOD_CANONICAL: 120}))


def test_canonical_and_routing_double_placement_rejected(tmp_path):
    with pytest.raises(RuntimeAtomicError, match="二重ロード防止"):
        _validate(_staging(tmp_path / "s", {FLOOD_ROUTING: 120, FLOOD_CANONICAL: 120}))


def test_legacy_flood_check_geojsonl_rejected(tmp_path):
    s = _staging(tmp_path / "s", {FLOOD_ROUTING: 120})
    legacy = s / "backend/hazard/flood/tokyo/tokyo_flood_check.geojsonl"
    legacy.write_text(json.dumps({"type": "Feature", "properties": {"flood_rank": 1},
                                  "geometry": {"type": "Point", "coordinates": [139, 35]}}) + "\n")
    with pytest.raises(RuntimeAtomicError, match="routing artifact 以外"):
        _validate(s)


def test_flat_file_directly_under_flood_rejected(tmp_path):
    s = _staging(tmp_path / "s", {FLOOD_ROUTING: 120, "backend/hazard/flood/tokyo-river-001.routing.geojson": 120})
    with pytest.raises(RuntimeAtomicError, match="直下に file"):
        _validate(s)


def test_empty_flood_region_rejected(tmp_path):
    s = _staging(tmp_path / "s", {SURGE: 120})
    (s / "backend/hazard/flood/tokyo").mkdir(parents=True)
    with pytest.raises(RuntimeAtomicError, match="routing artifact が 0 件"):
        _validate(s)


def test_empty_flood_dir_rejected(tmp_path):
    s = _staging(tmp_path / "s", {SURGE: 120})
    (s / "backend/hazard/flood").mkdir(parents=True)
    with pytest.raises(RuntimeAtomicError, match="空"):
        _validate(s)


def test_empty_routing_artifact_rejected(tmp_path):
    with pytest.raises(RuntimeAtomicError, match="dataset固有件数違反"):
        _validate(_staging(tmp_path / "s", {FLOOD_ROUTING: 0}))


# ── migration ───────────────────────────────────────────────────────────────────

@pytest.fixture
def legacy_prev(tmp_path):
    """routing 分離前の前 version（canonical を flood/{region}/ に置いていた）。
    旧版は新契約の layout 検証を通らないため、layout 検証を外して作る。"""
    with patch.object(rdv, "_validate_flood_runtime_layout", lambda _s: None):
        return _published_version(tmp_path / "v_old", {FLOOD_CANONICAL: 925, SURGE: 120})


def test_migration_without_flag_rejected(tmp_path, legacy_prev):
    s = _staging(tmp_path / "s", {FLOOD_ROUTING: 800, SURGE: 120})
    with pytest.raises(RuntimeAtomicError, match="消失.*--allow-flood-routing-migration"):
        _validate(s, legacy_prev)


def test_migration_with_flag_allowed_and_recorded(tmp_path, legacy_prev):
    s = _staging(tmp_path / "s", {FLOOD_ROUTING: 800, SURGE: 120})
    records: list = []
    manifest, counts = _validate(s, legacy_prev, allow_flood_routing_migration=True,
                                 owner_approval_ref="OWNER-2026-10-05", migration_records=records)
    assert FLOOD_ROUTING in manifest and FLOOD_CANONICAL not in manifest
    assert records == [{
        "type": "flood_routing_migration",
        "owner_approval_ref": "OWNER-2026-10-05",
        "previous_version": legacy_prev.name,
        "legacy_to_routing": {FLOOD_CANONICAL: [FLOOD_ROUTING]},
    }]
    rdv.write_manifest(s, manifest, 0o640, counts, migrations=records)
    written = json.loads((s / rdv.MANIFEST_BASENAME).read_text(encoding="utf-8"))
    assert written["migrations"] == records


def test_migration_flag_rejected_second_time(tmp_path, legacy_prev):
    s1 = _staging(tmp_path / "v_migrated", {FLOOD_ROUTING: 800, SURGE: 120})
    manifest, counts = _validate(s1, legacy_prev, allow_flood_routing_migration=True,
                                 owner_approval_ref="OWNER-1")
    rdv.write_manifest(s1, manifest, 0o640, counts)
    s2 = _staging(tmp_path / "s2", {FLOOD_ROUTING: 800, SURGE: 120})
    with pytest.raises(RuntimeAtomicError, match="初回 migration 専用.*legacy flood file が無い"):
        _validate(s2, s1, allow_flood_routing_migration=True, owner_approval_ref="OWNER-2")
    # flag なしの通常 publish は従来どおり通る
    _validate(s2, s1)


def test_migration_flag_rejected_on_initial_publish(tmp_path):
    s = _staging(tmp_path / "s", {FLOOD_ROUTING: 800})
    with pytest.raises(RuntimeAtomicError, match="前 version が無い"):
        _validate(s, None, allow_flood_routing_migration=True, owner_approval_ref="OWNER-1")


@pytest.mark.parametrize("ref", [None, "", "   "])
def test_migration_flag_requires_owner_approval(tmp_path, legacy_prev, ref):
    s = _staging(tmp_path / "s", {FLOOD_ROUTING: 800, SURGE: 120})
    with pytest.raises(RuntimeAtomicError, match="OWNER 承認参照"):
        _validate(s, legacy_prev, allow_flood_routing_migration=True, owner_approval_ref=ref)


def test_migration_flag_does_not_exempt_other_datasets(tmp_path, legacy_prev):
    s = _staging(tmp_path / "s", {FLOOD_ROUTING: 800})  # storm_surge も消失
    with pytest.raises(RuntimeAtomicError, match="消失.*storm_surge"):
        _validate(s, legacy_prev, allow_flood_routing_migration=True, owner_approval_ref="OWNER-1")


def test_migration_requires_routing_in_same_region(tmp_path, legacy_prev):
    s = _staging(tmp_path / "s", {"backend/hazard/flood/kanagawa/kanagawa-river-001.routing.geojson": 800,
                                  SURGE: 120})
    with pytest.raises(RuntimeAtomicError, match="対応する routing artifact が staging に無い"):
        _validate(s, legacy_prev, allow_flood_routing_migration=True, owner_approval_ref="OWNER-1")


def test_normal_count_guard_still_applies_to_routing(tmp_path):
    prev = _published_version(tmp_path / "v1", {FLOOD_ROUTING: 800, SURGE: 120})
    s = _staging(tmp_path / "s", {FLOOD_ROUTING: 300, SURGE: 120})
    with pytest.raises(RuntimeAtomicError, match="壊滅的に減少"):
        _validate(s, prev)


# ── activate_version.py CLI ─────────────────────────────────────────────────────

def _load_activate():
    spec = importlib.util.spec_from_file_location(
        "activate_version", ROOT / "scripts" / "publish" / "activate_version.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("argv", [
    ["--allow-flood-routing-migration"],                                   # 承認参照なし
    ["--allow-flood-routing-migration", "--owner-approval-ref", "  "],     # 空の承認参照
    ["--owner-approval-ref", "OWNER-1"],                                   # flag なしの承認参照
    ["--allow-flood-routing-migration", "--owner-approval-ref", "X", "--rollback", "v"],
])
def test_activate_cli_rejects_invalid_migration_args(tmp_path, argv, capsys):
    mod = _load_activate()
    full = ["activate_version.py", "--data-runtime-root", str(tmp_path), "--version-id", "v",
            "--skip-identity-check", *argv]
    with patch.object(sys, "argv", full):
        assert mod.main() == 1
    assert "FAIL" in capsys.readouterr().err


def test_atomic_wrapper_requires_approval_ref_value():
    src = (ROOT / "scripts" / "publish" / "deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    assert "--allow-flood-routing-migration)" in src
    assert "OWNER 承認の参照文字列が必須" in src
    assert '--allow-flood-routing-migration --owner-approval-ref "${FLOOD_MIGRATION_APPROVAL_REF}"' in src

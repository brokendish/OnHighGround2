"""
flood canonical / routing artifact 分離契約（backend/app/services/flood_routing_contract.py）のテスト。

  - routing / meta パスは canonical パスから一意に導かれる（validated → derived）
  - canonical sha256 と meta の source sha256 が不一致 → reject
  - routing artifact / meta 欠落 → reject
  - routing 実体と meta の routing sha256 が不一致 → reject
  - dataset_id 不一致・feature_count 0 → reject
  - HazardEngine の探索は *.routing.geojson のみ（canonical / legacy は ignored）
  - builder script と契約モジュールの定数が一致（τ 既定 0.85 を含む）
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import flood_routing_contract as frc  # noqa: E402


def _load_builder():
    spec = importlib.util.spec_from_file_location(
        "build_flood_routing_artifact", ROOT / "scripts" / "derive" / "build_flood_routing_artifact.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_valid_pair(tmp_path: Path, dataset_id: str = "TOKYO-RIVER-001"):
    canonical = tmp_path / "data_lake" / "validated" / "tokyo" / "flood" / "tokyo-river-001.geojson"
    canonical.parent.mkdir(parents=True)
    canonical.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
    routing, meta_path = frc.routing_paths_for_canonical(canonical)
    routing.parent.mkdir(parents=True)
    routing.write_text('{"type":"FeatureCollection","features":[{"x":1}]}\n', encoding="utf-8")
    meta = {
        "contract": frc.CONTRACT_VERSION,
        "dataset_id": dataset_id,
        "source_canonical_path": str(canonical),
        "source_canonical_sha256": frc.sha256_file(canonical),
        "routing_artifact_sha256": frc.sha256_file(routing),
        "builder_name": frc.BUILDER_NAME,
        "builder_version": "1.0.0",
        "tau": 0.85,
        "min_split_size": 0.0002,
        "feature_count": 1,
        "generated_at": "2026-10-05T00:00:00Z",
    }
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return canonical, routing, meta_path, meta


def test_routing_paths_derived_from_canonical():
    routing, meta = frc.routing_paths_for_canonical(
        Path("/data_lake/validated/tokyo/flood/tokyo-river-001.geojson")
    )
    assert routing == Path("/data_lake/derived/tokyo/flood/tokyo-river-001.routing.geojson")
    assert meta == Path("/data_lake/derived/tokyo/flood/tokyo-river-001.routing.meta.json")


@pytest.mark.parametrize("bad", [
    "/data_lake/normalized/tokyo/flood/x.geojson",          # validated 要素なし
    "/data_lake/validated/tokyo/flood/x.routing.geojson",   # routing を canonical 扱い
    "/data_lake/validated/tokyo/flood/x.geojsonl",
])
def test_routing_paths_reject_non_canonical(bad):
    with pytest.raises(frc.FloodRoutingContractError):
        frc.routing_paths_for_canonical(Path(bad))


def test_verify_accepts_consistent_pair(tmp_path):
    canonical, routing, _, meta = _make_valid_pair(tmp_path)
    path, got = frc.verify_routing_for_canonical(canonical, "TOKYO-RIVER-001")
    assert path == routing
    assert got["source_canonical_sha256"] == meta["source_canonical_sha256"]


def test_canonical_sha_mismatch_rejected(tmp_path):
    canonical, *_ = _make_valid_pair(tmp_path)
    canonical.write_text('{"type":"FeatureCollection","features":[{"changed":true}]}\n', encoding="utf-8")
    with pytest.raises(frc.FloodRoutingContractError, match="canonical sha256"):
        frc.verify_routing_for_canonical(canonical, "TOKYO-RIVER-001")


def test_routing_missing_rejected(tmp_path):
    canonical, routing, *_ = _make_valid_pair(tmp_path)
    routing.unlink()
    with pytest.raises(frc.FloodRoutingContractError, match="routing artifact が存在しません"):
        frc.verify_routing_for_canonical(canonical, "TOKYO-RIVER-001")


def test_meta_missing_rejected(tmp_path):
    canonical, _, meta_path, _ = _make_valid_pair(tmp_path)
    meta_path.unlink()
    with pytest.raises(frc.FloodRoutingContractError, match="meta が存在しません"):
        frc.verify_routing_for_canonical(canonical, "TOKYO-RIVER-001")


def test_routing_tampered_rejected(tmp_path):
    canonical, routing, *_ = _make_valid_pair(tmp_path)
    routing.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
    with pytest.raises(frc.FloodRoutingContractError, match="routing artifact sha256"):
        frc.verify_routing_for_canonical(canonical, "TOKYO-RIVER-001")


def test_dataset_id_mismatch_rejected(tmp_path):
    canonical, *_ = _make_valid_pair(tmp_path, dataset_id="KANAGAWA-RIVER-001")
    with pytest.raises(frc.FloodRoutingContractError, match="dataset_id"):
        frc.verify_routing_for_canonical(canonical, "TOKYO-RIVER-001")


@pytest.mark.parametrize("field,value", [
    ("feature_count", 0), ("contract", "flood_routing/v0"), ("builder_name", "other"), ("tau", "0.85"),
])
def test_invalid_meta_rejected(tmp_path, field, value):
    canonical, _, meta_path, meta = _make_valid_pair(tmp_path)
    meta[field] = value
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(frc.FloodRoutingContractError):
        frc.verify_routing_for_canonical(canonical, "TOKYO-RIVER-001")


def test_discover_loads_only_routing_artifacts(tmp_path):
    flood = tmp_path / "backend" / "hazard" / "flood"
    routing = flood / "tokyo" / "tokyo-river-001.routing.geojson"
    canonical = flood / "tokyo" / "tokyo-river-001.geojson"
    legacy = flood / "tokyo_flood_check.geojsonl"
    backup = flood / "tokyo" / "tokyo-river-001.routing.backup.geojson"
    for p in (routing, canonical, legacy, backup):
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    found, ignored = frc.discover_flood_routing_files(flood)
    assert found == [routing]
    assert set(ignored) == {canonical, legacy, backup}


def test_discover_missing_dir_is_empty(tmp_path):
    assert frc.discover_flood_routing_files(tmp_path / "nope") == ([], [])


def test_app_public_flood_loader_uses_routing_discovery():
    """app_public は副作用が重いため import せず、flood loader が routing 探索関数を使い
    canonical の rglob('*.geojson') を使っていないことをソースで固定する。"""
    src = (ROOT / "backend" / "app_public.py").read_text(encoding="utf-8")
    block = src[src.index("FLOOD_ENABLED = parse_bool"): src.index("# storm_surge: 高潮浸水想定区域")]
    assert "discover_flood_routing_files(_HAZARD_BACKEND_ROOT / \"flood\")" in block
    assert 'rglob("*.geojson")' not in block


def test_builder_constants_match_contract():
    b = _load_builder()
    assert b.ROUTING_SUFFIX == frc.ROUTING_SUFFIX
    assert b.META_SUFFIX == frc.META_SUFFIX
    assert b.CONTRACT_VERSION == frc.CONTRACT_VERSION
    assert b.BUILDER_NAME == frc.BUILDER_NAME
    assert b.DEFAULT_TAU == frc.DEFAULT_TAU == 0.85

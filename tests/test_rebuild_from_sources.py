"""
LOCAL-ENVIRONMENT-RECONCILIATION（2026-10-12）:

  - deploy_to_runtime_atomic.sh --rebuild-from-sources: current を種にせず registry / data_lake の正式な成果物
    だけで version を組み立てる（source から作られなくなった旧 artifact を current から外す）。region は自動、
    表示必須の tile・tsunami target の runtime が揃わなければ activate しない。
  - TOKYO-PSEUDO-INLAND-FLOOD-001 は toolchain（GDAL の版）で生成結果が変わるため、本番と同じ toolchain で
    生成する scripts/derive/generate_pseudo_inland_flood_pinned.sh を使う。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services.dataset_definition_service import get_definition_service  # noqa: E402

spec = importlib.util.spec_from_file_location("rebuild_from_sources", ROOT / "scripts/publish/rebuild_from_sources.py")
rfs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rfs)
WRAPPER = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
DEFS = get_definition_service().list_all()


def _touch(root: Path, rel: str, data=b"x"):
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)


def _required_rels():
    from app.services import data_ops_service as dos
    return [dos.tile_rel(d) for d in DEFS if d.layer_type and dos.tile_requirement(d) == "required"]


# ── region ────────────────────────────────────────────────────────────────────

def test_rebuild_regions_cover_mappings_targets_and_tile_contracts():
    mappings = [{"layer_type": "flood", "region": "tokyo"}, {"layer_type": "tide", "region": "japan"}]
    regions = rfs.rebuild_regions(mappings, DEFS, ["tokyo", "kanagawa", "chiba"])
    assert regions == ["chiba", "kanagawa", "tokyo"]  # tide:japan は hazard publish 対象外
    assert "chiba" in rfs.rebuild_regions([], DEFS, [])  # CHIBA は tile 契約（chiba/tsunami）だけでも入る


def test_rebuild_regions_reject_invalid_names():
    with pytest.raises(ValueError):
        rfs.rebuild_regions([{"layer_type": "flood", "region": "../x"}], [], [])


# ── staging の確認 ────────────────────────────────────────────────────────────────

def _staging(tmp_path, skip=()):
    s = tmp_path / "staging"
    for rel in _required_rels() + [f"backend/hazard/tsunami/tsunami_{t}.geojson" for t in ("tokyo", "kanagawa", "chiba")]:
        if rel not in skip:
            _touch(s, rel)
    return s


def test_complete_staging_passes_and_lists_dropped(tmp_path):
    s = _staging(tmp_path)
    cur = tmp_path / "current"
    _touch(cur, "backend/hazard/storm_surge/tokyo_storm_surge.geojson")  # source から作られない旧 artifact
    _touch(cur, "provenance/X.json")
    (cur / "_manifest.json").write_text(json.dumps({"files": {
        "backend/hazard/storm_surge/tokyo_storm_surge.geojson": "a", "provenance/X.json": "b",
        "backend/hazard/tsunami/tsunami_tokyo.geojson": "c"}}))
    res = rfs.check_staging(s, cur, DEFS, ["tokyo", "kanagawa", "chiba"])
    assert res["missing"] == []
    assert res["dropped"] == ["backend/hazard/storm_surge/tokyo_storm_surge.geojson"]  # provenance は対象外


@pytest.mark.parametrize("skip", ["required tile", "tsunami target"])
def test_missing_required_artifact_blocks(tmp_path, skip):
    rel = _required_rels()[0] if skip == "required tile" else "backend/hazard/tsunami/tsunami_chiba.geojson"
    res = rfs.check_staging(_staging(tmp_path, skip=(rel,)), None, DEFS, ["tokyo", "kanagawa", "chiba"])
    assert any(rel in m for m in res["missing"])


# ── wrapper ──────────────────────────────────────────────────────────────────

def test_wrapper_rebuild_mode_contract():
    assert "--rebuild-from-sources) REBUILD_FROM_SOURCES=1; shift ;;" in WRAPPER
    seed = WRAPPER[WRAPPER.index('if [[ -L "${CURRENT_LINK}" ]]; then'):WRAPPER.index('log_step "seed staging from current"')]
    assert seed.index('if [[ "${REBUILD_FROM_SOURCES}" == "1" ]]; then') < seed.index('cp -a --reflink=auto')
    i_regions = WRAPPER.index("rebuild_from_sources.py\" --regions")
    i_deploy = WRAPPER.index('for _region in "${REGIONS[@]}"; do\n    log_info "--- region')
    i_check = WRAPPER.index("rebuild_from_sources.py\" --check-staging")
    i_activate = WRAPPER.index('activate_version.py"')
    assert i_regions < i_deploy < i_check < i_activate  # 確認してから activate する
    assert 'REBUILD_FROM_SOURCES=0' in WRAPPER  # 既定は従来どおり current を種にする


# ── PSEUDO の toolchain ───────────────────────────────────────────────────────────

def test_pseudo_generation_uses_production_toolchain():
    sh = (ROOT / "scripts/derive/generate_pseudo_inland_flood_pinned.sh").read_text(encoding="utf-8")
    assert "--platform linux/amd64" in sh and 'EXPECTED_GDAL="3.9.3"' in sh
    assert "rasterio==1.4.3" in sh and "numpy==1.26.4" in sh
    d = get_definition_service().get("TOKYO-PSEUDO-INLAND-FLOOD-001")
    assert any("generate_pseudo_inland_flood_pinned.sh" in n for n in d.ingest_notes)
    assert any("fffc6041" in n for n in d.ingest_notes)


def test_local_pseudo_canonical_matches_registered_generator_output():
    """DEM-RUNTIME-REPAIR（2026-10-12）以降、canonical は標準配置の DEM から作った b2b37817…（registry の
    generator.output_sha256）。旧 fffc6041… は配置の誤った DEM 由来で置き換え済み。"""
    p = ROOT / "data_lake/validated/tokyo/pseudo_inland_flood/pseudo_inland_flood.geojson"
    if not p.is_file():
        pytest.skip("canonical が無い環境（data_lake は gitignore）")
    import hashlib
    d = get_definition_service().get("TOKYO-PSEUDO-INLAND-FLOOD-001")
    assert d.generator["output_sha256"].startswith("b2b378177a7f945f")
    assert hashlib.sha256(p.read_bytes()).hexdigest() == d.generator["output_sha256"]

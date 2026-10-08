"""
coverage 受入の明示例外（allow-empty mesh）。KANAGAWA-RIVER-001 の 5338 は神奈川県域に掛かるが、
公式 2025 原本に県内の浸水想定区域 feature が無い（geometry intersection で 0 件を確認）。

  - 境界内 feature >= 1 → PASS
  - 0 件 + 明示 allow-empty → PASS_WITH_EXCEPTION（理由付き。単純 PASS と区別）
  - 0 件 + 明示なし → FAIL（0 件だから自動で例外にしない）
  - 例外指定メッシュに feature が出現したら通常 PASS
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "validate"))
sys.path.insert(0, str(ROOT / "backend"))

import check_flood_region_coverage as cov  # noqa: E402

MESHES = ["5238", "5239", "5338", "5339"]
SCRIPT = ROOT / "scripts/validate/check_flood_region_coverage.py"
# 神奈川県域の概略（テスト用の単純矩形境界。5338 の県内部分は 138.92〜139.0 の帯）
BOUNDARY = [[138.92, 35.13], [139.84, 35.13], [139.84, 35.67], [138.92, 35.67], [138.92, 35.13]]
CITY = cov.PRESETS["kanagawa"]
POINT_IN = {"5238": (35.30, 138.95), "5239": (35.30, 139.30), "5338": (35.45, 138.95), "5339": (35.50, 139.60)}


def _feat(lat, lon, d=0.001):
    return {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[
        [lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}}


def _world(tmp_path, meshes_with_features):
    feats = [_feat(lat, lon) for lat, lon in CITY.values()]  # 6 地点を満たす
    feats += [_feat(*POINT_IN[m]) for m in meshes_with_features]
    # 6 地点の feature 自体が 5239 / 5339 に入るので、5239 / 5339 を 0 件にしたいケースはそれも除く
    keep = []
    for f in feats:
        lon, lat = f["geometry"]["coordinates"][0][0]
        if cov.mesh1(lat + 0.0005, lon + 0.0005) in meshes_with_features or f in [
                _feat(*POINT_IN[m]) for m in meshes_with_features]:
            keep.append(f)
    gj = tmp_path / "f.geojson"
    gj.write_text(json.dumps({"type": "FeatureCollection", "features": keep}))
    bnd = tmp_path / "b.geojson"
    bnd.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [BOUNDARY]}}]}))
    return gj, bnd


def _acc(tmp_path, with_features, allow=None):
    gj, bnd = _world(tmp_path, with_features)
    return cov.check(gj, bnd, CITY, 3.0, MESHES, allow)["acceptance"]


def test_01_allow_empty_5338_is_pass_with_exception(tmp_path):
    acc = _acc(tmp_path, ["5238", "5239", "5339"], ["5338"])
    assert acc["pass"] is True and acc["exceptions"] == ["5338"]
    r = acc["mesh_results"]["5338"]
    assert r["status"] == "PASS_WITH_EXCEPTION" and r["inside_boundary_features"] == 0 and r["reason"]
    assert {m: acc["mesh_results"][m]["status"] for m in ("5238", "5239", "5339")} == {
        "5238": "PASS", "5239": "PASS", "5339": "PASS"}


def test_02_without_allow_empty_fails(tmp_path):
    acc = _acc(tmp_path, ["5238", "5239", "5339"])
    assert acc["pass"] is False and acc["failed_meshes"] == ["5338"]
    assert acc["mesh_results"]["5338"]["status"] == "FAIL"


@pytest.mark.parametrize("zero", ["5238", "5239", "5339"])
def test_03_05_other_zero_meshes_fail_even_with_5338_exception(tmp_path, zero):
    acc = _acc(tmp_path, [m for m in ["5238", "5239", "5339"] if m != zero], ["5338"])
    assert acc["pass"] is False and zero in acc["failed_meshes"]


def test_06_feature_appearing_in_exception_mesh_is_normal_pass(tmp_path):
    acc = _acc(tmp_path, MESHES, ["5338"])
    assert acc["mesh_results"]["5338"]["status"] == "PASS" and acc["exceptions"] == [] and acc["pass"]


def test_07_no_auto_exception(tmp_path):
    acc = _acc(tmp_path, ["5238", "5239", "5339"], None)
    assert acc["allow_empty_meshes"] == [] and acc["exceptions"] == []


def test_08_six_locations_still_required(tmp_path):
    gj, bnd = _world(tmp_path, MESHES)
    data = json.loads(gj.read_text())
    data["features"] = [_feat(*POINT_IN[m]) for m in MESHES]  # 地点近傍の feature を除く
    gj.write_text(json.dumps(data))
    acc = cov.check(gj, bnd, CITY, 3.0, MESHES, ["5338"])["acceptance"]
    assert acc["pass"] is False and acc["points_without_coverage"]


def test_cli_exit_codes_and_argument_guards(tmp_path):
    gj, bnd = _world(tmp_path, ["5238", "5239", "5339"])
    base = [sys.executable, str(SCRIPT), "--geojson", str(gj), "--boundary", str(bnd), "--preset", "kanagawa"]
    ok = subprocess.run(base + ["--require-meshes", ",".join(MESHES), "--allow-empty-meshes", "5338"],
                        capture_output=True, text=True)
    assert ok.returncode == 0 and json.loads(ok.stdout)["acceptance"]["mesh_results"]["5338"]["status"] == "PASS_WITH_EXCEPTION"
    ng = subprocess.run(base + ["--require-meshes", ",".join(MESHES)], capture_output=True, text=True)
    assert ng.returncode == 1
    # 必須に含まれないメッシュを例外にできない・definition と CLI の併用不可
    bad = subprocess.run(base + ["--require-meshes", "5239", "--allow-empty-meshes", "5338"], capture_output=True, text=True)
    assert bad.returncode == 2
    both = subprocess.run(base + ["--from-definition", "KANAGAWA-RIVER-001", "--require-meshes", "5239"],
                          capture_output=True, text=True)
    assert both.returncode == 2
    via_def = subprocess.run(base + ["--from-definition", "KANAGAWA-RIVER-001"], capture_output=True, text=True)
    acc = json.loads(via_def.stdout)["acceptance"]
    assert via_def.returncode == 0 and acc["allow_empty_meshes"] == ["5338"] and acc["exceptions"] == ["5338"]


def test_definition_registers_only_5338_and_data_ops_shows_exception(tmp_path):
    from app.models.admin_dataset import DatasetState
    from app.services import data_ops_service as dos
    from app.services import dataset_runtime_reconcile as drr
    from app.services.dataset_definition_service import get_definition_service
    ds = get_definition_service()
    k = ds.get("KANAGAWA-RIVER-001")
    assert k.coverage_required_meshes == MESHES and k.coverage_allow_empty_meshes == ["5338"] and k.coverage_notes
    assert not any(d.coverage_allow_empty_meshes for d in ds.list_all() if d.dataset_id != "KANAGAWA-RIVER-001")
    view = drr.RuntimeView(root=tmp_path, version_id="V", files={})
    tr = dos.transform_section(k, DatasetState(dataset_id=k.dataset_id), view,
                               drr.reconcile_dataset(k, DatasetState(dataset_id=k.dataset_id), view,
                                                     drr.SourceShaCache(tmp_path / "c.json"), False), False)
    assert tr["coverage_policy"]["exceptions"] == ["5338: OFFICIAL SOURCE CONTAINS NO KANAGAWA FEATURES"]
    js = (ROOT / "operator/frontend-admin/data-ops.js").read_text(encoding="utf-8")
    assert '"COVERAGE EXCEPTION"' in js
    t = ds.get("TOKYO-RIVER-001")
    assert t.coverage_allow_empty_meshes == [] and t.required_source_count == 4  # 10. TOKYO 影響なし

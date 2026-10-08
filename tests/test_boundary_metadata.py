"""
行政区域境界（N03）normalizer の provenance metadata を dataset 定義から付与する。

以前は normalize_boundary.py が東京固定値（TOKYO-BOUNDARY-001 / 13）を setdefault しており、
KANAGAWA-BOUNDARY-001 にも東京の metadata が付いていた。geometry と N03 属性は変えない。
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
SCRIPT = ROOT / "scripts/normalize/normalize_boundary.py"

from app.models.admin_dataset import DatasetState  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402


def _fc(code_prefix, n=3, extra=None):
    feats = []
    for i in range(n):
        props = {"N03_001": "神奈川県" if code_prefix == "14" else "東京都", "N03_004": f"市{i}",
                 "N03_007": f"{code_prefix}{100 + i:03d}"}
        props.update(extra or {})
        feats.append({"type": "Feature", "properties": props, "geometry": {
            "type": "Polygon", "coordinates": [[[139.0 + i, 35.0], [139.1 + i, 35.0], [139.1 + i, 35.1], [139.0 + i, 35.0]]]}})
    return {"type": "FeatureCollection", "features": feats}


def _run(tmp_path, data, dataset_id, region_code):
    src = tmp_path / "in.geojson"
    src.write_text(json.dumps(data, ensure_ascii=False))
    out = tmp_path / "out.geojson"
    r = subprocess.run([sys.executable, str(SCRIPT), "--input", str(src), "--output", str(out),
                        "--dataset-id", dataset_id, "--region-code", region_code], capture_output=True, text=True)
    return r, (json.loads(out.read_text()) if out.exists() else None)


@pytest.mark.parametrize("dataset_id,code", [("TOKYO-BOUNDARY-001", "13"), ("KANAGAWA-BOUNDARY-001", "14")])
def test_01_04_metadata_from_arguments(tmp_path, dataset_id, code):
    r, out = _run(tmp_path, _fc(code), dataset_id, code)
    assert r.returncode == 0, r.stderr
    assert {(f["properties"]["source_dataset"], f["properties"]["normalized_region_code"]) for f in out["features"]} \
        == {(dataset_id, code)}


def test_05_09_geometry_and_n03_unchanged_only_metadata_rewritten(tmp_path):
    """入力に旧 metadata（東京固定値）が残っていても上書きし、geometry / N03 属性は変えない。"""
    src = _fc("14", extra={"source_dataset": "TOKYO-BOUNDARY-001", "normalized_region_code": "13"})
    r, out = _run(tmp_path, src, "KANAGAWA-BOUNDARY-001", "14")
    assert r.returncode == 0, r.stderr
    assert len(out["features"]) == len(src["features"])
    for a, b in zip(src["features"], out["features"]):
        assert a["geometry"] == b["geometry"]
        assert {k: v for k, v in a["properties"].items() if k.startswith("N03_")} == \
            {k: v for k, v in b["properties"].items() if k.startswith("N03_")}
        changed = {k for k in set(a["properties"]) | set(b["properties"]) if a["properties"].get(k) != b["properties"].get(k)}
        assert changed <= {"source_dataset", "normalized_region_code", "feature_index"}
        assert b["properties"]["source_dataset"] == "KANAGAWA-BOUNDARY-001"


def test_region_mismatch_is_rejected(tmp_path):
    r, out = _run(tmp_path, _fc("13"), "KANAGAWA-BOUNDARY-001", "14")
    assert r.returncode == 1 and "N03_007" in r.stderr and out is None


def test_arguments_are_required(tmp_path):
    src = tmp_path / "in.geojson"
    src.write_text(json.dumps(_fc("14")))
    r = subprocess.run([sys.executable, str(SCRIPT), "--input", str(src), "--output", str(tmp_path / "o.geojson")],
                       capture_output=True, text=True)
    assert r.returncode == 2  # --dataset-id / --region-code 必須（地域固定値の既定を持たない）
    r = subprocess.run([sys.executable, str(SCRIPT), "--input", str(src), "--output", str(tmp_path / "o.geojson"),
                        "--dataset-id", "X", "--region-code", "kanagawa"], capture_output=True, text=True)
    assert r.returncode == 2
    src_text = SCRIPT.read_text(encoding="utf-8")
    assert 'DATASET_ID = "' not in src_text and 'REGION_CODE = "' not in src_text  # 地域固定の定数を持たない


@pytest.mark.parametrize("dataset_id,code", [("TOKYO-BOUNDARY-001", "13"), ("KANAGAWA-BOUNDARY-001", "14")])
def test_pipeline_passes_dataset_and_region(tmp_path, monkeypatch, dataset_id, code):
    from app.services import pipeline_service as ps
    defn = get_definition_service().get(dataset_id)
    assert defn.expected_source_region_code == code
    raw = tmp_path / "raw.zip"
    raw.write_bytes(b"x")
    seen = {}

    async def fake(cmd, job, jm, **kw):
        seen["cmd"] = cmd
        return 0
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    state = DatasetState(dataset_id=dataset_id, current_raw_path=str(raw))
    with patch.object(ps, "_run_subprocess", side_effect=fake):
        asyncio.run(ps._do_normalize(Mock(job_id="j"), defn, state, Mock(), Mock()))
    cmd = seen["cmd"]
    assert cmd[cmd.index("--dataset-id") + 1] == dataset_id and cmd[cmd.index("--region-code") + 1] == code


def test_10_data_ops_metadata_consistency(tmp_path):
    from app.services import data_ops_service as dos
    k = get_definition_service().get("KANAGAWA-BOUNDARY-001")
    bad = tmp_path / "bad.geojson"
    bad.write_text(json.dumps(_fc("14", extra={"source_dataset": "TOKYO-BOUNDARY-001", "normalized_region_code": "13"})))
    md = dos._canonical_metadata(k, str(bad))
    assert md["consistent"] is False and len(md["mismatches"]) == 2
    good = tmp_path / "good.geojson"
    good.write_text(json.dumps(_fc("14", extra={"source_dataset": "KANAGAWA-BOUNDARY-001", "normalized_region_code": "14"})))
    assert dos._canonical_metadata(k, str(good))["consistent"] is True
    plain = tmp_path / "plain.geojson"
    plain.write_text(json.dumps(_fc("14")))
    assert dos._canonical_metadata(k, str(plain)) is None  # metadata を持たない dataset は照合しない


def test_11_12_tokyo_and_flood_regression():
    ds = get_definition_service()
    assert ds.get("TOKYO-BOUNDARY-001").expected_source_region_code == "13"
    assert ds.get("KANAGAWA-RIVER-001").expected_source_region_code == "14"
    assert ds.get("TOKYO-RIVER-001").source_region_code_regex == r"^A31a-\d+_(\d{2})_"
    from app.services import provenance_validity as pv
    from app.services.acquisition_history import SourceFile
    assert pv.extract_region_codes(ds.get("KANAGAWA-BOUNDARY-001"), [SourceFile(name="N03-20250101_14_GML.zip")]) == \
        [("N03-20250101_14_GML.zip", "14")]

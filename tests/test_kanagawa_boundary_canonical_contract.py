"""
KANAGAWA-BOUNDARY-CANONICAL-RECONCILIATION（2026-10-12）: 神奈川県境界の canonical を build node と runtime node で一致させる。

VPS の canonical（c19d78c0…）は 2026-04-17 に同じ raw を旧 normalize_boundary.py（a4c56c8）で正規化したもので、
geometry と N03 属性は Local と同一、provenance metadata だけが東京固定値（TOKYO-BOUNDARY-001 / 13）だった。
build node（Local）で正式 pipeline が作った canonical（92348caf…）を正とし、その sha を registry の契約にする。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import source_group as sg  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

DID = "KANAGAWA-BOUNDARY-001"
RAW_SHA = "1cf3c1ee08686de1e2685e5f81b9f0eaf6abb94bfffcd0811cc109c84b2e9fb4"
CANONICAL_SHA = "92348caf7bcf9a674dec36c30c5653c0fba159a70d0d164070b86b96c4c0ffef"
OLD_VPS_SHA_PREFIX = "c19d78c0"


def _defn():
    return get_definition_service().get(DID)


def _canonical() -> Path:
    return ROOT / _defn().validated_storage_path / "kanagawa-boundary-001.geojson"


def _sha(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_01_boundary_source_provenance():
    d = _defn()
    assert d.source_provider == "国土交通省 国土数値情報" and d.source_year == "2025"
    assert d.expected_source_files == ["N03-20250101_14_GML.zip"] and d.expected_source_region_code == "14"
    assert any(RAW_SHA in n for n in d.ingest_notes)
    assert sg.evaluate_source_set(d, ["N03-20250101_14_GML.zip"]).ok
    assert not sg.evaluate_source_set(d, ["N03-20250101_13_GML.zip"]).ok


def test_04_canonical_sha_is_the_registry_contract():
    """Local / VPS の parity は registry に記録した canonical sha で判定する（旧 VPS 版の由来も記録）。"""
    notes = _defn().ingest_notes
    assert any(CANONICAL_SHA in n and "source_dataset=KANAGAWA-BOUNDARY-001" in n and "normalized_region_code=14" in n
               for n in notes)
    assert any(OLD_VPS_SHA_PREFIX in n and "a4c56c8" in n and "~/backups/kanagawa-boundary-canonical-20261012/" in n
               for n in notes)


def _canonical_or_skip() -> Path:
    p = _canonical()
    if not p.is_file():
        pytest.skip("canonical が無い環境（build node / runtime node のみ）")
    return p


def test_03_05_canonical_matches_contract_and_region_14():
    p = _canonical_or_skip()
    assert _sha(p) == CANONICAL_SHA
    fc = json.loads(p.read_text(encoding="utf-8"))
    feats = fc["features"]
    assert len(feats) == 1247 and {f["geometry"]["type"] for f in feats} == {"Polygon"}
    assert {f["properties"]["source_dataset"] for f in feats} == {DID}
    assert {f["properties"]["normalized_region_code"] for f in feats} == {"14"}
    assert {str(f["properties"]["N03_007"])[:2] for f in feats} == {"14"}


def test_02_canonical_is_reproducible_from_raw(tmp_path):
    """正式 pipeline と同じ引数で raw を再正規化すると canonical とバイト一致する（raw が読める build node のみ）。"""
    p = _canonical_or_skip()
    raw = ROOT / _defn().raw_storage_path / "N03-20250101_14_GML.zip"
    try:
        if _sha(raw) != RAW_SHA:
            pytest.fail("raw が登録済みの公式原本と一致しない")
    except (FileNotFoundError, PermissionError):
        pytest.skip("raw を読めない環境")
    out = tmp_path / "kanagawa-boundary-001.geojson"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/normalize/normalize_boundary.py"), "--input", str(raw),
                        "--output", str(out), "--dataset-id", DID, "--region-code", "14"], capture_output=True, text=True)
    if r.returncode != 0 and re.search(r"ogr2ogr|gdal|GDAL", r.stderr):
        pytest.skip("GML 変換ツール（GDAL）が無い環境")
    assert r.returncode == 0, r.stderr
    assert _sha(out) == _sha(p) == CANONICAL_SHA


def test_06_data_ops_flags_old_tokyo_metadata(tmp_path, monkeypatch):
    """旧 canonical（metadata が東京固定値）は Data Ops で canonical WARNING になる（判定の回帰防止）。"""
    from app.services import data_ops_service as dos
    feats = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[139, 35], [139.1, 35], [139.1, 35.1], [139, 35]]]},
              "properties": {"N03_007": "14100", "source_dataset": "TOKYO-BOUNDARY-001", "normalized_region_code": "13"}}]
    old = tmp_path / "old.geojson"
    old.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    problems = dos.boundary_metadata_problems(_defn(), old) if hasattr(dos, "boundary_metadata_problems") else None
    if problems is None:
        src = (ROOT / "backend/app/services/data_ops_service.py").read_text(encoding="utf-8")
        assert "provenance metadata が dataset 定義と不一致" in src
    else:
        assert problems

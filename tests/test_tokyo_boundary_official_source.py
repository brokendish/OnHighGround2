"""
TOKYO-BOUNDARY-OFFICIAL-SOURCE（2026-10-12）: 東京都境界の公式 source identity を事実で確定する。

  公式 zip   N03-20250101_13_GML.zip（国土数値情報 N03、令和7年1月1日時点）sha256 e73a70ca…
  VPS raw    公式 zip と同一
  旧 Local raw sha256 ad84fb5f… = 公式 zip の 8 member を N03-20250101_13_GML/ 配下へ入れ直して zip し直したもの
             （member の内容は全件バイト一致・梱包だけの差）→ data_lake/_backup/tokyo_boundary_repacked_raw_20261012/
  canonical  sha256 0de2359f…（6,904 feature）。公式 zip・旧 raw のどちらから正規化してもバイト一致、Local / VPS も同じ
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetState, NormalizeStatus, ValidationStatus  # noqa: E402
from app.services import acquisition_migration as am  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import source_group as sg  # noqa: E402
from app.services import source_identity as si  # noqa: E402
from app.services.acquisition_history import (  # noqa: E402
    AcquisitionMethod, AcquisitionRecord, AcquisitionStore, AcquisitionValidity, SourceFile)
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

DID = "TOKYO-BOUNDARY-001"
ZIP = "N03-20250101_13_GML.zip"
OFFICIAL_SHA = "e73a70ca903c5a37daba66158ee5de7c48bb7cd7d45f31f7fa4a178c9456702f"
REPACKED_SHA = "ad84fb5fb23b743c6868ef631069503e67228a00824583634eecb106fc6d63cc"
CANONICAL_SHA = "0de2359f25d3982046fa7cb4b5b3ee42f887cc20bdb6ddaa51212ecef4a35572"
OFFICIAL_MEMBERS = ["KS-META-N03-20250101_13.xml", "N03-20250101_13.cpg", "N03-20250101_13.dbf",
                    "N03-20250101_13.geojson", "N03-20250101_13.prj", "N03-20250101_13.shp",
                    "N03-20250101_13.shx", "N03-20250101_13.xml"]


def _d():
    return get_definition_service().get(DID)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _raw() -> Path:
    return ROOT / _d().raw_storage_path / ZIP


def _canonical() -> Path:
    return ROOT / _d().validated_storage_path / "tokyo-boundary-001.geojson"


def _readable(p: Path) -> bool:
    try:
        p.open("rb").close()
        return True
    except OSError:
        return False


# ── 1-4. 公式 source identity ──────────────────────────────────────────────────

def test_01_official_source_identity_registered():
    d = _d()
    assert d.source_provider == "国土交通省 国土数値情報" and d.source_year == "2025" and d.source_version is None
    assert d.source_url == "https://nlftp.mlit.go.jp/ksj/gml/data/N03/N03-2025/" + ZIP
    assert d.official_source_url == "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-N03-2025.html"
    assert d.expected_source_files == [ZIP] and d.source_file_patterns == [ZIP]
    assert d.expected_source_sha256 == {ZIP: OFFICIAL_SHA} and d.expected_source_sha256_basis == "official_zip"
    assert d.expected_source_region_code == "13" and sg.definition_problems(d) == []
    assert sg.evaluate_source_set(d, [ZIP]).ok and not sg.evaluate_source_set(d, ["N03-20250101_14_GML.zip"]).ok
    assert any("3.2.1" not in n and "version は「不明」" in n for n in d.ingest_notes)  # GML 形式の版を版としない


def test_02_official_sha_matches_and_repacked_does_not():
    d = _d()
    assert si.verify(d, [SourceFile(name=ZIP, sha256=OFFICIAL_SHA)]).status == si.EXPECTED_SOURCE_MATCH
    assert si.verify(d, [SourceFile(name=ZIP, sha256=REPACKED_SHA)]).status == si.SOURCE_MISMATCH  # 名前は同じ


def test_02b_03_local_raw_is_the_official_zip_with_official_members():
    raw = _raw()
    if not _readable(raw):
        pytest.skip("raw が無い / 読めない環境")
    assert _sha(raw) == OFFICIAL_SHA
    assert sorted(zipfile.ZipFile(raw).namelist()) == OFFICIAL_MEMBERS  # subdirectory に入れ直した梱包ではない


def test_04_canonical_is_region_13():
    p = _canonical()
    if not p.is_file():
        pytest.skip("canonical が無い環境")
    feats = json.loads(p.read_text(encoding="utf-8"))["features"]
    assert len(feats) == 6904
    assert {f["properties"]["source_dataset"] for f in feats} == {DID}
    assert {f["properties"]["normalized_region_code"] for f in feats} == {"13"}
    assert {str(f["properties"]["N03_007"])[:2] for f in feats if f["properties"].get("N03_007")} == {"13"}
    assert any(CANONICAL_SHA in n and "6,904" in n for n in _d().ingest_notes)


# ── 5-7. canonical の再現と差分検出 ───────────────────────────────────────────────

def test_05_canonical_reproducible_from_official_raw(tmp_path):
    raw, canon = _raw(), _canonical()
    if not (_readable(raw) and canon.is_file()):
        pytest.skip("raw / canonical が無い環境")
    out = tmp_path / "c.geojson"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/normalize/normalize_boundary.py"), "--input", str(raw),
                        "--output", str(out), "--dataset-id", DID, "--region-code", "13"], capture_output=True, text=True)
    if r.returncode != 0 and "gdal" in r.stderr.lower():
        pytest.skip("GML 変換ツール（GDAL）が無い環境")
    assert r.returncode == 0, r.stderr
    assert _sha(out) == _sha(canon) == CANONICAL_SHA


def test_06_geometry_change_is_detected_by_sha_contract(tmp_path):
    canon = _canonical()
    if not canon.is_file():
        pytest.skip("canonical が無い環境")
    fc = json.loads(canon.read_text(encoding="utf-8"))
    fc["features"] = fc["features"][1:]  # feature を 1 件削除
    changed = tmp_path / "c.geojson"
    changed.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")
    assert _sha(changed) != CANONICAL_SHA


def test_07_metadata_mismatch_is_detected(tmp_path):
    feats = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[139, 35], [139.1, 35], [139.1, 35.1], [139, 35]]]},
              "properties": {"N03_007": "13101", "source_dataset": "KANAGAWA-BOUNDARY-001", "normalized_region_code": "14"}}]
    p = tmp_path / "x.geojson"
    p.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    meta = dos._canonical_metadata(_d(), str(p))
    assert meta["consistent"] is False and len(meta["mismatches"]) == 2


# ── 8-10. Data Ops・取得履歴・旧 source ────────────────────────────────────────────

def _rec(sha):
    return AcquisitionRecord(dataset_id=DID, acquisition_method=AcquisitionMethod.manual_import, active=True,
                             validity=AcquisitionValidity.valid, source_files=[SourceFile(name=ZIP, sha256=sha)])


def test_08_data_ops_ok_only_for_official_record(tmp_path):
    store = AcquisitionStore(tmp_path / "ok")
    store.add(_rec(OFFICIAL_SHA))
    acq = dos.acquisition_section(_d(), store, None, None)
    assert acq["status"] == dos.OK and acq["source_identity"]["status"] == si.EXPECTED_SOURCE_MATCH
    old = AcquisitionStore(tmp_path / "old")
    old.add(_rec(REPACKED_SHA))  # 旧 Local raw（再梱包）を記録した履歴は valid と書かれていても MISMATCH
    acq_old = dos.acquisition_section(_d(), old, None, None)
    assert acq_old["status"] == dos.ERROR and acq_old["source_identity"]["status"] == si.SOURCE_MISMATCH


def test_09_10_backfill_does_not_write_repacked_raw(tmp_path):
    raw = tmp_path / "raw" / ZIP
    raw.parent.mkdir(parents=True)
    with zipfile.ZipFile(raw, "w") as zf:  # 公式 member を subdirectory へ入れ直した梱包（sha は公式と異なる）
        for m in OFFICIAL_MEMBERS:
            zf.writestr(f"N03-20250101_13_GML/{m}", m)
    admin = tmp_path / "admin"
    (admin / "history").mkdir(parents=True)
    (admin / "jobs").mkdir()
    (admin / "history" / f"{DID}.jsonl").write_text(json.dumps({"operation_type": "ingest", "result": "success",
        "source_file_name": ZIP, "job_id": "j1", "executed_at": "2026-04-06T15:10:59"}) + "\n", encoding="utf-8")
    (admin / "jobs" / "j1.json").write_text(json.dumps({"job_type": "ingest_upload"}), encoding="utf-8")

    class DS:
        def list_all(self):
            return [_d()]
    store = AcquisitionStore(tmp_path / "acq")
    state = DatasetState(dataset_id=DID, current_raw_path=str(raw), normalize_status=NormalizeStatus.success,
                         validation_status=ValidationStatus.passed)
    out = am.migrate_all(DS(), ss=lambda did: state, store=store, admin_dir=admin)
    assert out[0]["action"] == "not_written" and out[0]["source_identity"]["status"] == si.SOURCE_MISMATCH
    assert store.list(DID) == []


def test_10_old_raw_is_kept_as_backup_record():
    notes = " ".join(_d().ingest_notes)
    assert REPACKED_SHA in notes and "data_lake/_backup/tokyo_boundary_repacked_raw_20261012/" in notes
    assert "梱包だけの差" in notes


# ── 11-12. 隔離 ───────────────────────────────────────────────────────────────

def test_11_12_no_real_admin_writes(tmp_path):
    real = ROOT / "data_lake/admin/acquisitions"
    before = {p.name: p.stat().st_mtime_ns for p in real.glob("*.json")} if real.is_dir() else {}
    test_09_10_backfill_does_not_write_repacked_raw(tmp_path / "a")
    test_08_data_ops_ok_only_for_official_record(tmp_path / "b")
    after = {p.name: p.stat().st_mtime_ns for p in real.glob("*.json")} if real.is_dir() else {}
    assert before == after

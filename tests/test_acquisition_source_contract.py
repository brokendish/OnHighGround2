"""
ACQUISITION-SOURCE-CONTRACT（2026-10-12）: 取得履歴の validity=valid は「registry が期待する原本と sha256 まで一致」だけ。

旧来は地域コード・原本の共有・取得方法しか見ず、VPS の KANAGAWA-RIVER-001 raw（2024 年版 bundle
A31a-24_14_*）も valid になった。source_identity.verify が原本名の集合と sha256 を registry
（expected_source_files / expected_source_sha256）と照合し、EXPECTED_SOURCE_MATCH 以外は valid にしない。
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetState, NormalizeStatus, ValidationStatus  # noqa: E402
from app.services import acquisition_migration as am  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import provenance_validity as pv  # noqa: E402
from app.services import runtime_provenance as rp  # noqa: E402
from app.services import source_group as sg  # noqa: E402
from app.services import source_identity as si  # noqa: E402
from app.services.acquisition_history import (  # noqa: E402
    AcquisitionMethod, AcquisitionRecord, AcquisitionStatus, AcquisitionStore, AcquisitionValidity, SourceFile)
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

VPS_KANAGAWA_RIVER_2024 = ["A31a-24_14_10_GML.zip", "A31a-24_14_20_GML.zip", "A31b-24_10_5339_GML.zip"]
WRONG = "0" * 64


def _d(did):
    return get_definition_service().get(did)


def _files(defn, override=None):
    """registry が期待する原本の事実（名前・sha256）。override で一部の sha を差し替える。"""
    out = []
    for name in defn.expected_source_files:
        out.append(SourceFile(name=name, size=1, sha256=(override or {}).get(name, defn.expected_source_sha256.get(name))))
    return out


def _rec(defn, files, method=AcquisitionMethod.upload, **kw):
    return AcquisitionRecord(dataset_id=defn.dataset_id, acquisition_method=method, source_files=files, **kw)


# ── 1-6. 判定ルール ─────────────────────────────────────────────────────────────

def test_01_exact_sha_match_is_verified():
    d = _d("KANAGAWA-SURGE-001")
    assert si.verify(d, _files(d)).status == si.EXPECTED_SOURCE_MATCH
    assert pv.assess(d, _rec(d, _files(d)))[0] == AcquisitionValidity.valid


@pytest.mark.parametrize("did", ["KANAGAWA-SURGE-001", "TOKYO-RIVER-001"])
def test_02_03_same_filename_different_sha_is_mismatch(did):
    d = _d(did)
    first = d.expected_source_files[0]
    files = _files(d, {first: WRONG})
    res = si.verify(d, files)
    assert res.status == si.SOURCE_MISMATCH and first in res.reasons[0]
    validity, _, flags = pv.assess(d, _rec(d, files))
    assert validity == AcquisitionValidity.provenance_mismatch and flags == [pv.SOURCE_MISMATCH]


def test_04_readable_names_without_sha_is_not_verified():
    d = _d("KANAGAWA-SURGE-001")
    files = [SourceFile(name=n) for n in d.expected_source_files]  # 読めて名前は合うが sha が無い
    assert si.verify(d, files).status == si.SOURCE_READABLE
    validity, _, flags = pv.assess(d, _rec(d, files))
    assert validity == AcquisitionValidity.unknown and flags == [pv.IDENTITY_UNVERIFIED]


def test_05_processed_and_active_alone_is_not_verified():
    """normalize / validation が成功（processed・active）していても、原本が違えば valid にしない。"""
    d = _d("TOKYO-URBAN-001")
    rec = _rec(d, _files(d, {d.expected_source_files[0]: WRONG}), status=AcquisitionStatus.processed, active=True)
    assert pv.assess(d, rec)[0] == AcquisitionValidity.provenance_mismatch


def test_06_without_registered_sha_or_identity():
    d = _d("KANAGAWA-SURGE-001").model_copy(update={"expected_source_sha256": {}, "expected_source_sha256_basis": None})
    assert si.verify(d, _files(_d("KANAGAWA-SURGE-001"))).status == si.SOURCE_READABLE
    unknown = _d("TOKYO-BOUNDARY-001")  # 出典未確定の dataset に expected source を作らない
    assert not unknown.expected_source_files and not unknown.expected_source_sha256
    res = si.verify(unknown, [SourceFile(name="N03-20250101_13_GML.zip", sha256="a" * 64)])
    assert res.status == si.SOURCE_UNKNOWN
    assert pv.assess(unknown, _rec(unknown, [SourceFile(name="x.zip", sha256="a" * 64)]))[2] == [pv.SOURCE_UNKNOWN]


def test_filename_alone_or_provider_alone_never_verifies():
    d = _d("KANAGAWA-LANDSLIDE-001")
    assert d.source_provider  # provider が一致していても
    assert si.verify(d, [SourceFile(name=d.expected_source_files[0], sha256=WRONG)]).status == si.SOURCE_MISMATCH


# ── 7-12. 現行 source と旧 source ──────────────────────────────────────────────────

def _registered():
    return [d for d in get_definition_service().list_all() if d.expected_source_sha256]


@pytest.mark.parametrize("did", [d.dataset_id for d in _registered()])
def test_07_current_registered_sources_match(did):
    d = _d(did)
    assert sg.definition_problems(d) == []
    assert d.expected_source_sha256_basis in ("official_zip", "verified_raw", "build_node_acquisition")
    assert si.verify(d, _files(d)).verified


def test_registered_identity_basis_is_explicit():
    by_basis = {}
    for d in _registered():
        by_basis.setdefault(d.expected_source_sha256_basis, set()).add(d.dataset_id)
    assert by_basis["build_node_acquisition"] == {"TOKYO-RIVER-001", "KANAGAWA-RIVER-001"}
    assert {"TOKYO-SHELTER-001", "TOKYO-EVAC-001", "KANAGAWA-SHELTER-001", "KANAGAWA-EVAC-001"} == by_basis["verified_raw"]
    assert {"CHIBA-TSUNAMI-001", "KANAGAWA-BOUNDARY-001", "TOKYO-TSUNAMI-001"} <= by_basis["official_zip"]


def test_08_09_kanagawa_river_2024_bundle_is_mismatch_although_region_matches():
    d = _d("KANAGAWA-RIVER-001")
    files = [SourceFile(name=n, size=1, sha256="b" * 64) for n in VPS_KANAGAWA_RIVER_2024]
    assert pv.extract_region_codes(d, files) and all(c == "14" for _, c in pv.extract_region_codes(d, files))
    res = si.verify(d, files)
    assert res.status == si.SOURCE_MISMATCH and "A31a-24_14_10_GML.zip" in " ".join(res.reasons)
    validity, _, flags = pv.assess(d, _rec(d, files))
    assert validity == AcquisitionValidity.provenance_mismatch and flags == [pv.SOURCE_MISMATCH]  # 旧実装: valid


@pytest.mark.parametrize("did", ["TOKYO-RIVER-001", "KANAGAWA-BOUNDARY-001", "CHIBA-TSUNAMI-001", "TOKYO-TSUNAMI-001"])
def test_10_11_12_current_fixtures(did):
    d = _d(did)
    rec = pv.apply(d, _rec(d, _files(d)))
    assert rec.validity == AcquisitionValidity.valid
    ident = rec.source_identity
    assert ident["status"] == si.EXPECTED_SOURCE_MATCH and ident["expected_sha256"] == ident["actual_sha256"]
    assert ident["validator_version"] == si.VALIDATOR_VERSION and ident["validated_at"] and ident["node"]
    assert ident["basis"] == d.expected_source_sha256_basis


# ── 13. 履歴の復元（migration）は一致したときだけ書く ─────────────────────────────────

def _bundle(tmp_path, did, members):
    raw = tmp_path / "raw" / f"{did}_bundle_test0001.zip"
    raw.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(raw, "w") as zf:
        for m in members:
            zf.writestr(m, b"legacy " + m.encode())
    return raw


class _DS:
    def __init__(self, *defns):
        self._d = list(defns)

    def list_all(self):
        return self._d


def _state(did, raw):
    return DatasetState(dataset_id=did, current_raw_path=str(raw), normalize_status=NormalizeStatus.success,
                        validation_status=ValidationStatus.passed)


def test_13_migration_does_not_write_legacy_raw(tmp_path):
    d = _d("KANAGAWA-RIVER-001")
    raw = _bundle(tmp_path, d.dataset_id, VPS_KANAGAWA_RIVER_2024)
    store = AcquisitionStore(tmp_path / "acq")
    out = am.migrate_all(_DS(d), ss=lambda did: _state(did, raw), store=store, admin_dir=tmp_path / "admin")
    assert out[0]["action"] == "not_written" and out[0]["validity"] == "provenance_mismatch"
    assert out[0]["source_identity"]["status"] == si.SOURCE_MISMATCH
    assert store.list(d.dataset_id) == []


def test_13b_migration_writes_only_matching_raw(tmp_path):
    d = _d("KANAGAWA-BOUNDARY-001")
    raw = ROOT / "data_lake/raw/kanagawa/boundary/N03-20250101_14_GML.zip"
    try:
        raw.open("rb").close()
    except OSError:
        pytest.skip("raw が無い / 読めない環境")
    admin = tmp_path / "admin"
    (admin / "history").mkdir(parents=True)
    (admin / "jobs").mkdir()
    (admin / "history" / f"{d.dataset_id}.jsonl").write_text(json.dumps(
        {"operation_type": "ingest", "result": "success", "source_file_name": raw.name, "job_id": "job-1",
         "executed_at": "2026-04-17T15:19:17"}) + "\n", encoding="utf-8")
    (admin / "jobs" / "job-1.json").write_text(json.dumps({"job_type": "ingest_upload"}), encoding="utf-8")
    store = AcquisitionStore(tmp_path / "acq")
    out = am.migrate_all(_DS(d), ss=lambda did: _state(did, raw), store=store, admin_dir=admin)
    assert out[0]["action"] == "migrated" and out[0]["source_identity"]["status"] == si.EXPECTED_SOURCE_MATCH
    assert store.list(d.dataset_id)[0].validity == AcquisitionValidity.valid
    # 取得方法の記録が無ければ（legacy_unknown）原本が一致していても書かない
    store2 = AcquisitionStore(tmp_path / "acq2")
    out2 = am.migrate_all(_DS(d), ss=lambda did: _state(did, raw), store=store2, admin_dir=tmp_path / "empty")
    assert out2[0]["action"] == "not_written" and store2.list(d.dataset_id) == []


def test_13c_migration_dry_run_never_writes(tmp_path):
    d = _d("KANAGAWA-RIVER-001")
    raw = _bundle(tmp_path, d.dataset_id, VPS_KANAGAWA_RIVER_2024)
    store = AcquisitionStore(tmp_path / "acq")
    out = am.migrate_all(_DS(d), ss=lambda did: _state(did, raw), store=store, dry_run=True, admin_dir=tmp_path / "a")
    assert out[0]["action"] == "dry_run" and store.list(d.dataset_id) == []


# ── 14. 既存履歴の再分類（一括で書き換えず、record ごとに再検証）─────────────────────────

def test_14_reverify_reclassifies_legacy_valid_record(tmp_path):
    d = _d("KANAGAWA-RIVER-001")
    store = AcquisitionStore(tmp_path / "acq")
    legacy = _rec(d, [SourceFile(name=n, size=1, sha256="c" * 64) for n in VPS_KANAGAWA_RIVER_2024],
                  validity=AcquisitionValidity.valid, active=True)  # 旧判定で valid と記録された
    current = _rec(_d("TOKYO-RIVER-001"), _files(_d("TOKYO-RIVER-001")), validity=AcquisitionValidity.valid, active=True)
    store.add(legacy)
    store.add(current)
    ds = _DS(d, _d("TOKYO-RIVER-001"))
    dry = {r["dataset_id"]: r for r in am.reverify_all(ds, store)}
    assert dry["KANAGAWA-RIVER-001"]["action"] == "reclassify" and dry["KANAGAWA-RIVER-001"]["new_validity"] == "provenance_mismatch"
    assert dry["TOKYO-RIVER-001"]["action"] == "unchanged"
    assert store.list(d.dataset_id)[0].validity == AcquisitionValidity.valid  # dry-run は書かない
    am.reverify_all(ds, store, apply=True)
    after = store.list(d.dataset_id)[0]
    assert after.validity == AcquisitionValidity.provenance_mismatch and after.source_identity["status"] == si.SOURCE_MISMATCH
    assert [f.name for f in after.source_files] == VPS_KANAGAWA_RIVER_2024 and after.active  # 事実・active は不変
    assert any("reverified" in n for n in after.notes)
    assert store.list("TOKYO-RIVER-001")[0].source_identity["status"] == si.EXPECTED_SOURCE_MATCH


# ── 15-16. runtime node: raw が在ることは取得を意味しない／Data Ops ───────────────────────

def _rt(defn, files):
    return {"status": rp.VERIFIED, "record": {"build_node": "build", "source": {
        "validity": "valid", "source_files": [{"name": f.name, "sha256": f.sha256} for f in files],
        "bundle": {"name": f"{defn.dataset_id}_bundle_current.zip"}}}}


def test_15_runtime_node_with_legacy_raw(tmp_path):
    d = _d("KANAGAWA-RIVER-001")
    raw = _bundle(tmp_path, d.dataset_id, VPS_KANAGAWA_RIVER_2024)
    acq = dos.acquisition_section(d, AcquisitionStore(tmp_path / "acq"), _state(d.dataset_id, raw), _rt(d, _files(d)))
    assert acq["acquisition_history"] == "NOT PRESENT ON THIS NODE"  # この node で取得したのではない
    assert acq["source_identity"]["status"] == si.EXPECTED_SOURCE_MATCH and acq["status"] == dos.OK
    assert acq["raw_cache"]["status"] == "STALE"
    assert acq["raw_cache"]["identity"]["status"] == si.SOURCE_MISMATCH and acq["raw_cache"]["identity"]["hashed"] is False
    labels = [l["label"] for l in dos.integrity_labels(acq, {"status": rp.VERIFIED}, {}, d)]
    assert "LEGACY_SOURCE_PRESENT" in labels and dos.LABEL_SEVERITY["LEGACY_SOURCE_PRESENT"] == "INFO"


def test_16_runtime_record_with_wrong_source_is_mismatch_even_if_verified(tmp_path):
    """runtime provenance が VERIFIED でも、record の原本が registry と違えば source は MISMATCH（上位で隠さない）。"""
    d = _d("KANAGAWA-RIVER-001")
    old = [SourceFile(name=n, sha256="d" * 64) for n in VPS_KANAGAWA_RIVER_2024]
    acq = dos.acquisition_section(d, AcquisitionStore(tmp_path / "acq"), None, _rt(d, old))
    assert acq["validity"] == "provenance_mismatch" and acq["status"] == dos.ERROR
    labels = [l["label"] for l in dos.integrity_labels(acq, {"status": rp.VERIFIED}, {}, d)]
    assert "SOURCE_IDENTITY_MISMATCH" in labels and dos.LABEL_SEVERITY["SOURCE_IDENTITY_MISMATCH"] == dos.ERROR


def test_16b_unverified_identity_is_warning_label(tmp_path):
    d = _d("KANAGAWA-SURGE-001")
    store = AcquisitionStore(tmp_path / "acq")
    store.add(_rec(d, [SourceFile(name=n) for n in d.expected_source_files], validity=AcquisitionValidity.valid, active=True))
    acq = dos.acquisition_section(d, store, None, None)
    assert acq["validity"] == "unknown" and acq["status"] == dos.WARNING  # 保存済みの valid を信用しない
    labels = [l["label"] for l in dos.integrity_labels(acq, {"status": rp.VERIFIED}, {}, d)]
    assert "SOURCE_IDENTITY_UNVERIFIED" in labels


# ── 17-18. 隔離 ───────────────────────────────────────────────────────────────

def test_17_18_tests_never_write_real_admin(tmp_path):
    real = ROOT / "data_lake/admin/acquisitions"
    before = {p.name: p.stat().st_mtime_ns for p in real.glob("*.json")} if real.is_dir() else {}
    test_13_migration_does_not_write_legacy_raw(tmp_path / "a")
    test_14_reverify_reclassifies_legacy_valid_record(tmp_path / "b")
    after = {p.name: p.stat().st_mtime_ns for p in real.glob("*.json")} if real.is_dir() else {}
    assert before == after


def test_16c_ui_shows_identity_status_as_text():
    js = (ROOT / "operator/frontend-admin/data-ops.js").read_text(encoding="utf-8")
    for label in ("SOURCE VERIFIED", "SOURCE READABLE / IDENTITY UNVERIFIED", "SOURCE MISMATCH", "SOURCE UNKNOWN",
                  "LEGACY SOURCE PRESENT", '["Source identity"', "build_node_acquisition"):
        assert label in js, label
    assert "innerHTML" not in js


def test_reverify_cli_defaults_to_dry_run(monkeypatch, capsys):
    import importlib.util
    spec = importlib.util.spec_from_file_location("rv", ROOT / "scripts/publish/reverify_acquisition_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    seen = {}
    monkeypatch.setattr(am, "reverify_all", lambda **kw: seen.update(kw) or [])
    monkeypatch.setattr(sys, "argv", ["x", "--dataset", "KANAGAWA-RIVER-001"])
    assert mod.main() == 0 and seen == {"apply": False, "dataset_ids": ["KANAGAWA-RIVER-001"]}

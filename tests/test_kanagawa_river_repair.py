"""
KANAGAWA-RIVER-001 2025 年版 正式修復（OWNER 承認済み 10 原本）。

  - 正式 10 原本 set: 10/10 のみ取込可。9 件・11 件・東京 A31a 混入は UI / API / pipeline で拒否
  - outer bundle（KANAGAWA-RIVER-001_2025_bundle.zip）を chunk upload。内部 10 原本の名前・size・sha256 を記録
  - 新取得は ACTIVE / VALID、旧誤取得（A31a-25_13_*）は削除せず INACTIVE / PROVENANCE_MISMATCH で残す
  - 現 raw の地域照合で REGION_MISMATCH が解除される
  - coverage checker は不合格で exit 1
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetState, Job, JobStatus, JobType  # noqa: E402
from app.services import acquisition_history as ah  # noqa: E402
from app.services import acquisition_migration as am  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import pipeline_service as ps  # noqa: E402
from app.services import provenance_validity as pv  # noqa: E402
from app.services import source_group as sg  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

MESHES = ["5238", "5239", "5338", "5339"]
OFFICIAL = ["A31a-25_14_10_GML.zip", "A31a-25_14_20_GML.zip"] + [
    f"A31b-25_{c}_{m}_GML.zip" for m in MESHES for c in ("10", "20")]
WRONG = ["A31a-25_13_10_GML.zip", "A31a-25_13_20_GML.zip"]


def _k():
    return get_definition_service().get("KANAGAWA-RIVER-001")


def _bundle(path: Path, names) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for n in names:
            zf.writestr(n, f"bytes-of-{n}")
    return path


def test_01_official_set_registered_and_passes():
    d = _k()
    assert sorted(d.expected_source_files) == sorted(OFFICIAL) and d.required_source_count == 10
    assert sg.definition_problems(d) == []
    ev = sg.evaluate_source_set(d, OFFICIAL)
    assert ev.ok and ev.selected_count == 10 and not ev.missing_patterns
    assert ev.confirm_message.startswith("10 ファイルを 1 セットとして canonical を再生成します")


@pytest.mark.parametrize("names,code", [
    (OFFICIAL[:-1], sg.SOURCE_SET_INCOMPLETE),                      # 2. 9/10
    (OFFICIAL + ["A31b-25_10_5240_GML.zip"], sg.SOURCE_SET_UNEXPECTED),  # 3. 11 件目
    (OFFICIAL + ["A31a-24_14_10_GML.zip"], sg.SOURCE_SET_DUPLICATE),  # 年度違い重複
    ([n.replace("_14_", "_13_") for n in OFFICIAL], sg.SOURCE_SET_INCOMPLETE),  # 4. 東京 A31a
    (OFFICIAL + WRONG, sg.SOURCE_SET_UNEXPECTED),                   # 4. 東京 A31a 混入
    (WRONG, sg.SOURCE_SET_INCOMPLETE),                               # 現在の誤 bundle
])
def test_02_04_rejected_sets(names, code):
    ev = sg.evaluate_source_set(_k(), names)
    assert not ev.ok
    assert code == ev.error_code or code in [sg.SOURCE_SET_UNEXPECTED, sg.SOURCE_SET_INCOMPLETE]


@pytest.mark.parametrize("names,ok", [(OFFICIAL, True), (OFFICIAL[:-1], False), (OFFICIAL + ["x_GML.zip"], False),
                                      (OFFICIAL[2:] + WRONG, False)])
def test_chunk_upload_bundle_start_and_finish(tmp_path, names, ok):
    """推奨 outer bundle 名は start で bundle 候補として受理、finish で内部を判定（10/10 のみ）。"""
    from app.api import admin_upload as up
    d = _k()
    ds = Mock()
    ds.get.return_value = d
    start = sg.upload_start_evaluation(d, "KANAGAWA-RIVER-001_2025_bundle.zip")
    assert start.ok and start.bundle_name == "KANAGAWA-RIVER-001_2025_bundle.zip"
    part = _bundle(tmp_path / "u.part", names)
    up._sessions["kr"] = {"upload_id": "kr", "filename": "KANAGAWA-RIVER-001_2025_bundle.zip",
                          "tmp_path": str(part), "dataset_id": d.dataset_id}
    jm = Mock()
    jm.has_running_job.return_value = False
    jm.create.return_value = Mock(job_id="job-k")
    run = Mock(return_value=None)
    with patch.object(up, "get_definition_service", return_value=ds), \
         patch.object(up, "get_state_service", return_value=Mock()), \
         patch.object(up, "get_job_manager", return_value=jm), \
         patch.object(up.pipeline_service, "run_ingest_upload", run):
        if ok:
            asyncio.run(up.upload_finish(up.FinishRequest(upload_id="kr", dataset_id=d.dataset_id,
                                                          total_size=part.stat().st_size), Mock(), principal=Mock()))
            jm.create.assert_called_once()
            final = Path(run.call_args.args[5])
            assert final.name == "KANAGAWA-RIVER-001_2025_bundle.zip"
            final.unlink()
        else:
            with pytest.raises(HTTPException) as e:
                asyncio.run(up.upload_finish(up.FinishRequest(upload_id="kr", dataset_id=d.dataset_id,
                                                              total_size=part.stat().st_size), Mock(), principal=Mock()))
            assert e.value.status_code == 422
            jm.create.assert_not_called()
    up._sessions.pop("kr", None)


def test_05_source_region_14_passes(tmp_path):
    raw = _bundle(tmp_path / "KANAGAWA-RIVER-001_2025_bundle.zip", OFFICIAL)
    v, reason, flags = pv.assess_raw_region(_k(), raw)
    assert v == ah.AcquisitionValidity.valid and flags == []


def _ingest(tmp_path, monkeypatch, store, names, post_ok=True):
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(ps, "get_acquisition_store", lambda: store)
    tmp = _bundle(tmp_path / "upload" / "KANAGAWA-RIVER-001_2025_bundle.zip", names)
    job = Job(job_id="job-new", dataset_id="KANAGAWA-RIVER-001", job_type=JobType.ingest_upload)
    state = DatasetState(dataset_id="KANAGAWA-RIVER-001")

    async def fake_post(job, *a, **k):
        job.status = JobStatus.success if post_ok else JobStatus.failed

    with patch.object(ps, "_run_post_ingest_pipeline", side_effect=fake_post):
        asyncio.run(ps.run_ingest_upload(job, _k(), state, Mock(log=lambda *a: None, update=lambda j, **kw: [setattr(j, k, v) for k, v in kw.items() if v is not None]),
                                         Mock(), tmp, acquisition={"method": "upload", "original_files": [tmp.name]}))
    return job, state


def _old_wrong_record(tmp_path):
    raw = _bundle(tmp_path / "raw_old" / "KANAGAWA-RIVER-001_bundle_t61diorv.zip", WRONG)
    admin = tmp_path / "admin"
    (admin / "history").mkdir(parents=True)
    (admin / "jobs").mkdir()
    (admin / "history" / "KANAGAWA-RIVER-001.jsonl").write_text(json.dumps({
        "operation_type": "ingest", "result": "success", "source_file_name": raw.name, "job_id": "c631",
        "executed_at": "2026-10-05T15:16:38.516818"}) + "\n")
    (admin / "jobs" / "c631.json").write_text(json.dumps({"job_type": "ingest_upload"}))
    rec = am.build_migrated_record(_k(), DatasetState(dataset_id="KANAGAWA-RIVER-001", current_raw_path=str(raw),
                                                      normalize_status="success", validation_status="pass"),
                                   admin_dir=admin)
    return pv.apply(_k(), rec, [])


def test_old_wrong_bundle_members_still_recorded_under_new_patterns(tmp_path):
    """正式 patterns（_14_ のみ）登録後でも、旧誤 bundle の A31a-25_13_* を記録から落とさない。"""
    rec = _old_wrong_record(tmp_path)
    assert [f.name for f in rec.source_files] == WRONG and rec.bundle.name == "KANAGAWA-RIVER-001_bundle_t61diorv.zip"
    assert rec.validity == ah.AcquisitionValidity.provenance_mismatch and rec.active


def test_11_12_13_new_acquisition_valid_old_kept_inactive_mismatch(tmp_path, monkeypatch):
    store = ah.AcquisitionStore(tmp_path / "acq")
    store.add(_old_wrong_record(tmp_path))
    job, state = _ingest(tmp_path, monkeypatch, store, OFFICIAL)
    assert job.status == JobStatus.success and state.current_raw_path.endswith("KANAGAWA-RIVER-001_2025_bundle.zip")
    recs = store.list("KANAGAWA-RIVER-001")
    assert len(recs) == 2  # 旧履歴を削除しない
    new = next(r for r in recs if r.ingest_job_id == "job-new")
    old = next(r for r in recs if r.ingest_job_id == "c631")
    assert new.active and new.validity == ah.AcquisitionValidity.valid and new.validity_flags == []
    assert sorted(f.name for f in new.source_files) == sorted(OFFICIAL) and new.bundle.name == "KANAGAWA-RIVER-001_2025_bundle.zip"
    for f in new.source_files:
        assert f.sha256 == hashlib.sha256(f"bytes-of-{f.name}".encode()).hexdigest() and f.size
    assert not old.active and old.validity == ah.AcquisitionValidity.provenance_mismatch  # INACTIVE / MISMATCH で保持
    # 13. Data Ops: 現 raw 照合でも REGION_MISMATCH 解除
    acq = dos.acquisition_section(_k(), store, state)
    assert acq["validity"] == "valid" and "REGION_MISMATCH" not in acq["validity_flags"]
    assert len(acq["active"]["source_files"]) == 10


def test_failed_pipeline_keeps_old_active(tmp_path, monkeypatch):
    store = ah.AcquisitionStore(tmp_path / "acq")
    store.add(_old_wrong_record(tmp_path))
    _ingest(tmp_path, monkeypatch, store, OFFICIAL, post_ok=False)
    active = store.active("KANAGAWA-RIVER-001")
    assert active.ingest_job_id == "c631"  # canonical 生成失敗なら新取得を active にしない


def test_partial_bundle_never_reaches_raw(tmp_path, monkeypatch):
    store = ah.AcquisitionStore(tmp_path / "acq")
    job, state = _ingest(tmp_path, monkeypatch, store, OFFICIAL[:-1])
    assert job.status == JobStatus.failed and job.error_code == sg.SOURCE_SET_INCOMPLETE
    assert state.current_raw_path is None and store.list("KANAGAWA-RIVER-001") == []
    assert not (tmp_path / "data_lake/raw/kanagawa/flood").exists() or \
        not list((tmp_path / "data_lake/raw/kanagawa/flood").glob("*"))


def test_08_coverage_failure_exits_1(tmp_path):
    feat = {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[
        [139.70, 35.53], [139.701, 35.53], [139.701, 35.531], [139.70, 35.531], [139.70, 35.53]]]}}
    gj = tmp_path / "f.geojson"
    gj.write_text(json.dumps({"type": "FeatureCollection", "features": [feat]}))
    bnd = tmp_path / "b.geojson"
    bnd.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[[138.92, 35.13], [139.84, 35.13], [139.84, 35.67],
                                                          [138.92, 35.67], [138.92, 35.13]]]}}]}))
    r = subprocess.run([sys.executable, str(ROOT / "scripts/validate/check_flood_region_coverage.py"),
                        "--geojson", str(gj), "--boundary", str(bnd), "--preset", "kanagawa",
                        "--require-meshes", ",".join(MESHES)], capture_output=True, text=True)
    assert r.returncode == 1 and json.loads(r.stdout)["acceptance"]["pass"] is False


def test_16_tokyo_river_regression():
    t = get_definition_service().get("TOKYO-RIVER-001")
    assert t.required_source_count == 4 and t.expected_source_region_code == "13"
    assert sg.evaluate_source_set(t, t.expected_source_files).ok
    # 東京と A31b 5339 を共有しても KANAGAWA 正式取得は A31a コード 14 で地域確認済み → suspect にしない
    peer = ah.AcquisitionRecord(dataset_id="TOKYO-RIVER-001", acquisition_method="upload", active=True,
                                source_files=[ah.SourceFile(name=n, sha256=n) for n in t.expected_source_files])
    rec = ah.AcquisitionRecord(dataset_id="KANAGAWA-RIVER-001", acquisition_method="upload",
                               source_files=[ah.SourceFile(name=n, sha256=n) for n in OFFICIAL])
    assert pv.assess(_k(), rec, [peer])[0] == ah.AcquisitionValidity.valid

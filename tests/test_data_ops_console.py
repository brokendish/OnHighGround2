"""
Data Operations Console（取得 → 変換 → 公開 → 稼働 → 整合性）。

  - source_group: all_required 等の原本構成判定（UI / API / pipeline の唯一の判定源）
  - acquisition_history: 取得事実（原本名・size・sha256・bundle 内原本・URL）の複数世代保存（atomic write）
  - data_ops_service: definition + acquisition + reconcile + routing meta + manifest + MBTiles の集約
  - API guard: upload / chunk upload / source-set check、pipeline guard: raw 保存前・normalize 前
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import sqlite3
import sys
import threading
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import (  # noqa: E402
    DatasetDefinition, DatasetState, DeployStatus, Job, JobStatus, JobType, NormalizeStatus, StorageStatus,
    ValidationStatus,
)
from app.services import acquisition_history as ah  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from app.services import pipeline_service as ps  # noqa: E402
from app.services import source_group as sg  # noqa: E402
from app.services.flood_routing_contract import BUILDER_NAME, CONTRACT_VERSION  # noqa: E402

A31 = ["A31a-25_13_10_GML.zip", "A31a-25_13_20_GML.zip", "A31b-25_10_5339_GML.zip", "A31b-25_20_5339_GML.zip"]
PATTERNS = ["A31a-*_13_10_GML.zip", "A31a-*_13_20_GML.zip", "A31b-*_10_5339_GML.zip", "A31b-*_20_5339_GML.zip"]
V1 = "20261006T000000Z-00000001"
PROPS = {"hazard.flood.enabled": "true", "hazard.tsunami.targets": "tokyo,kanagawa"}


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _defn(layer_type="flood", dataset_id="TOKYO-RIVER-001", region="tokyo", **kw):
    base = dict(
        dataset_id=dataset_id, region=region, category=layer_type or "osm", display_name="t", description="t",
        hint_text="t", impact_scope="t", accepted_input_modes=["upload", "fetch_url"],
        accepted_extensions=[".zip", ".geojson"], max_browser_upload_mb=200, requires_normalize=True,
        requires_validation=True, requires_deploy=True, requires_osrm_rebuild=False,
        raw_storage_path=f"data_lake/raw/{region}/{layer_type}", validated_storage_path=f"data_lake/validated/{region}/{layer_type}",
        normalized_storage_path=f"data_lake/normalized/{region}/{layer_type}",
        runtime_path=f"data_runtime/backend/hazard/{layer_type}", deploy_mode="copy_file", layer_type=layer_type,
        transformer_name="normalize_river_flood", validator_name="validate_geometry",
    )
    base.update(kw)
    return DatasetDefinition(**base)


def _river(**kw):
    return _defn(source_provider="国土交通省 国土数値情報", source_dataset_name="洪水浸水想定区域 A31a/A31b",
                 source_group_mode="all_required", ingest_mode="single_batch", required_source_count=4,
                 source_file_patterns=PATTERNS, ingest_replaces_canonical=True,
                 ingest_notes=["4ファイルを同一取込処理で投入すること"], requires_tile_build=True, **kw)


def _zip(path: Path, members: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return path


class FakeJM:
    def __init__(self):
        self.logs = []

    def update(self, job, **kw):
        for k, v in kw.items():
            if v is not None:
                setattr(job, k, v)
        return job

    def log(self, job, msg):
        self.logs.append(msg)


def _job(jt=JobType.ingest_upload):
    return Job(job_id="job-1", dataset_id="TOKYO-RIVER-001", job_type=jt, actor_id="op:test")


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = ah.AcquisitionStore(tmp_path / "acquisitions")
    monkeypatch.setattr(ah, "_default_store", s)
    monkeypatch.setattr(ps, "get_acquisition_store", lambda: s)
    return s


# ── 1-4, 17. source_group / pipeline の原本構成 guard ──────────────────────────

def test_01_single_dataset_upload_unconstrained():
    """source_group_mode 未定義の dataset は従来どおり（推測で制約を足さない）。"""
    d = _defn("landslide", "TOKYO-LANDSLIDE-001")
    ev = sg.evaluate_source_set(d, ["anything.zip"])
    assert ev.ok and not ev.enforced
    single = _defn("landslide", "X-001", source_group_mode="single")
    assert sg.evaluate_source_set(single, ["a.zip"]).ok
    assert sg.evaluate_source_set(single, ["a.zip", "b.zip"]).error_code == sg.SOURCE_SET_TOO_MANY


def test_02_all_required_missing_is_rejected():
    ev = sg.evaluate_source_set(_river(), A31[:3])
    assert not ev.ok and ev.error_code == sg.SOURCE_SET_INCOMPLETE
    assert ev.missing_patterns == ["A31b-*_20_5339_GML.zip"]
    assert ev.selected_count == 3 and ev.required_count == 4
    assert "3 / 4" in ev.blocking_reasons[0]


def test_03_all_required_complete_set_ok():
    ev = sg.evaluate_source_set(_river(), A31)
    assert ev.ok and not ev.missing_patterns and not ev.unexpected_files
    assert ev.confirm_message.startswith("4 ファイルを 1 セットとして canonical を再生成します")
    # 年度違い（命名は glob で吸収）も可
    assert sg.evaluate_source_set(_river(), [n.replace("-25_", "-26_") for n in A31]).ok


def test_03b_duplicates_and_unexpected_rejected():
    dup = sg.evaluate_source_set(_river(), A31 + ["A31a-24_13_10_GML.zip"])
    assert not dup.ok and dup.error_code == sg.SOURCE_SET_DUPLICATE
    unexpected = sg.evaluate_source_set(_river(), A31 + ["readme.txt"])
    assert not unexpected.ok and unexpected.unexpected_files == ["readme.txt"]


def test_04_sequential_individual_uploads_never_replace_canonical(tmp_path, monkeypatch, store):
    """4 原本を 1 つずつ投入しても、API（start）・pipeline の両方で拒否され canonical は不変。"""
    from app.api import admin_upload as up
    defn = _river()
    canonical = tmp_path / "data_lake/validated/tokyo/flood/tokyo-river-001.geojson"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"CANONICAL")
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    ds = Mock()
    ds.get.return_value = defn
    for name in A31:
        with patch.object(up, "get_definition_service", return_value=ds), pytest.raises(HTTPException) as e:
            asyncio.run(up.upload_start(up.StartRequest(filename=name, size=10, dataset_id=defn.dataset_id)))
        assert e.value.status_code == 422 and e.value.detail["error_code"] == sg.SOURCE_SET_INCOMPLETE
        # API を迂回して pipeline を直接呼んでも raw 保存前に拒否
        tmp = tmp_path / "uploads" / name
        tmp.parent.mkdir(exist_ok=True)
        tmp.write_bytes(b"PK-part")
        job, jm, ss = _job(), FakeJM(), Mock()
        state = DatasetState(dataset_id=defn.dataset_id, current_validated_path=str(canonical))
        with patch.object(ps, "_run_post_ingest_pipeline") as post:
            asyncio.run(ps.run_ingest_upload(job, defn, state, jm, ss, tmp))
        post.assert_not_called()
        ss.save.assert_not_called()
        assert job.status == JobStatus.failed and job.error_code == sg.SOURCE_SET_INCOMPLETE
        assert not tmp.exists() and not (tmp_path / defn.raw_storage_path / name).exists()
    assert canonical.read_bytes() == b"CANONICAL"
    assert store.list(defn.dataset_id) == []


def test_17_pipeline_rejects_partial_raw_before_normalize(tmp_path):
    """normalize 直前の guard: current_raw_path が部分 bundle なら canonical を再生成しない。"""
    defn = _river()
    raw = _zip(tmp_path / "TOKYO-RIVER-001_bundle_x.zip", {n: b"x" for n in A31[:2]})
    state = DatasetState(dataset_id=defn.dataset_id, current_raw_path=str(raw), storage_status=StorageStatus.stored)
    job, jm = _job(), FakeJM()
    with patch.object(ps, "_do_normalize") as norm:
        asyncio.run(ps._run_post_ingest_pipeline(job, defn, state, jm, Mock()))
    norm.assert_not_called()
    assert job.error_code == sg.SOURCE_SET_INCOMPLETE
    # 完全な bundle は通過
    raw_ok = _zip(tmp_path / "TOKYO-RIVER-001_bundle_ok.zip", {n: b"x" for n in A31})
    assert sg.evaluate_stored_file(defn, raw_ok).ok


# ── 5-7, 9, 10. 取込時の原本記録 ────────────────────────────────────────────────

def _run_upload(tmp_path, monkeypatch, store, defn, tmp_file, acquisition, post_ok=True):
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    job, jm, ss = _job(), FakeJM(), Mock()
    state = DatasetState(dataset_id=defn.dataset_id)

    async def fake_post(job, *a, **k):
        if not post_ok:
            job.status, job.error_code = JobStatus.failed, "NORMALIZE_FAILED"
        else:
            job.status = JobStatus.success

    with patch.object(ps, "_run_post_ingest_pipeline", side_effect=fake_post):
        asyncio.run(ps.run_ingest_upload(job, defn, state, jm, ss, tmp_file, acquisition=acquisition))
    return job, state


def test_05_06_07_bundle_records_original_names_sizes_sha(tmp_path, monkeypatch, store):
    defn = _river()
    members = {n: f"content-{n}".encode() for n in A31}
    bundle = _zip(tmp_path / "up" / "TOKYO-RIVER-001_bundle_ab12.zip", members)
    job, state = _run_upload(tmp_path, monkeypatch, store, defn, bundle,
                             {"method": "upload", "original_files": list(members)})
    assert job.status == JobStatus.success and state.current_raw_path.endswith("TOKYO-RIVER-001_bundle_ab12.zip")
    rec = store.active(defn.dataset_id)
    assert rec.acquisition_method == ah.AcquisitionMethod.upload and rec.ingest_job_id == "job-1"
    assert sorted(f.name for f in rec.source_files) == sorted(A31)  # bundle 名だけにしない
    for f in rec.source_files:
        assert f.sha256 == _sha(members[f.name]) and f.size == len(members[f.name])
        assert f.container == "TOKYO-RIVER-001_bundle_ab12.zip"
    assert rec.bundle.name == "TOKYO-RIVER-001_bundle_ab12.zip" and rec.bundle.sha256 == _sha(bundle.read_bytes())
    assert rec.actor_id == "op:test" and rec.status == ah.AcquisitionStatus.processed


def test_05b_single_source_file_recorded_as_itself(tmp_path, monkeypatch, store):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    f = tmp_path / "up" / "A33-23_13_GML.zip"
    _zip(f, {"inner.xml": b"<x/>"})
    _run_upload(tmp_path, monkeypatch, store, defn, f, {"method": "upload", "original_files": [f.name]})
    rec = store.active(defn.dataset_id)
    assert [x.name for x in rec.source_files] == ["A33-23_13_GML.zip"] and rec.bundle is None
    assert rec.source_files[0].sha256 == _sha((tmp_path / defn.raw_storage_path / f.name).read_bytes())


def test_08_url_fetch_records_actual_url(tmp_path, monkeypatch, store):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001", official_source_url="https://example.org/page")
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    url = "https://example.org/files/A33-23_13_GML.zip"

    async def fake_curl(cmd, job, jm, **kw):
        Path(cmd[cmd.index("-o") + 1]).write_bytes(b"ZIPDATA")
        return 0

    async def fake_post(job, *a, **k):
        job.status = JobStatus.success

    job, jm = _job(JobType.ingest_fetch_url), FakeJM()
    with patch.object(ps, "_run_subprocess", side_effect=fake_curl), \
         patch.object(ps, "_run_post_ingest_pipeline", side_effect=fake_post):
        asyncio.run(ps.run_ingest_fetch_url(job, defn, DatasetState(dataset_id=defn.dataset_id), jm, Mock(), url))
    rec = store.active(defn.dataset_id)
    assert rec.acquisition_method == ah.AcquisitionMethod.url
    assert rec.source_url == url and rec.source_url != defn.official_source_url  # 定義 URL と実取得 URL を分離
    assert rec.source_files[0].sha256 == _sha(b"ZIPDATA")


def test_09_10_history_generations_and_active(tmp_path, monkeypatch, store):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    f1 = tmp_path / "up" / "a1.geojson"
    f1.parent.mkdir(parents=True)
    f1.write_bytes(b"1")
    _run_upload(tmp_path, monkeypatch, store, defn, f1, {"method": "upload"})
    first = store.active(defn.dataset_id)
    f2 = tmp_path / "up" / "a2.geojson"
    f2.write_bytes(b"2")
    _run_upload(tmp_path, monkeypatch, store, defn, f2, {"method": "upload"})
    f3 = tmp_path / "up" / "a3.geojson"
    f3.write_bytes(b"3")
    _run_upload(tmp_path, monkeypatch, store, defn, f3, {"method": "upload"}, post_ok=False)
    recs = store.list(defn.dataset_id)
    assert len(recs) == 3
    active = [r for r in recs if r.active]
    assert len(active) == 1 and active[0].source_files[0].name == "a2.geojson"  # 失敗した取得は active にしない
    assert next(r for r in recs if r.acquisition_id == first.acquisition_id).active is False
    assert next(r for r in recs if r.source_files[0].name == "a3.geojson").status == ah.AcquisitionStatus.failed


# ── 26, 30. atomic write / path traversal ───────────────────────────────────────

def test_26_atomic_write_and_concurrent_adds(tmp_path):
    s = ah.AcquisitionStore(tmp_path / "acq")
    threads = [threading.Thread(target=lambda i=i: s.add(ah.AcquisitionRecord(
        dataset_id="DS-001", acquisition_method="upload", notes=[str(i)]))) for i in range(12)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(s.list("DS-001")) == 12
    assert not [p for p in (tmp_path / "acq").iterdir() if ".tmp-" in p.name]
    before = (tmp_path / "acq" / "DS-001.json").read_bytes()
    with patch.object(ah.json, "dump", side_effect=OSError("disk full")), pytest.raises(OSError):
        s.add(ah.AcquisitionRecord(dataset_id="DS-001", acquisition_method="upload"))
    assert (tmp_path / "acq" / "DS-001.json").read_bytes() == before  # 途中失敗で既存履歴を壊さない
    assert not [p for p in (tmp_path / "acq").iterdir() if ".tmp-" in p.name]


def test_30_path_traversal_rejected(tmp_path):
    s = ah.AcquisitionStore(tmp_path / "acq")
    for bad in ("../x", "a/b", "", ".hidden", "x" * 200):
        with pytest.raises(ValueError):
            s.list(bad)
    # クライアント供給名のディレクトリ成分は判定に使わない
    ev = sg.evaluate_source_set(_river(), [f"../../etc/{n}" for n in A31])
    assert ev.ok and ev.selected_files == A31
    from app.api import admin_data_ops as api
    with patch.object(api, "get_definition_service") as gds:
        res = asyncio.run(api.list_acquisitions("../../etc/passwd"))
    gds.return_value.get.assert_not_called()
    assert res.status_code == 404
    assert dos.routing_validation_from_logs(["../../etc/passwd"], "x", 1) is None


# ── 16. UI（source-set/check）と API reject の一致 ─────────────────────────────

@pytest.mark.parametrize("names", [A31[:3], A31, A31 + ["x.txt"], [A31[0]], ["TOKYO-RIVER-001_bundle.zip"], []])
def test_16_ui_check_matches_api_reject(tmp_path, names):
    """UI が表示・disabled 判定に使う source-set/check と、upload API の拒否が同じ結論になる。"""
    from app.api import admin_data_ops as dapi
    from app.api import admin_datasets as api
    defn = _river()
    ds = Mock()
    ds.get.return_value = defn
    with patch.object(dapi, "get_definition_service", return_value=ds):
        ui = asyncio.run(dapi.check_source_set(defn.dataset_id, dapi.SourceSetCheckRequest(
            filenames=names, single_upload=len(names) == 1)))
    if len(names) == 1:
        from app.api import admin_upload as up
        with patch.object(up, "get_definition_service", return_value=ds):
            try:
                asyncio.run(up.upload_start(up.StartRequest(filename=names[0], size=1, dataset_id=defn.dataset_id)))
                api_ok = True
            except HTTPException as e:
                api_ok = e.status_code != 422
        assert ui["ok"] == api_ok
        return
    if not names:
        assert ui["ok"] is False
        return
    from starlette.datastructures import UploadFile
    files = [UploadFile(file=io.BytesIO(b"x"), filename=n) for n in names]
    ss, jm = Mock(), Mock()
    jm.has_running_job.return_value = False
    jm.create.return_value = Mock(job_id="job-1")
    run = Mock(return_value=None)
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss), \
         patch.object(api, "get_job_manager", return_value=jm), \
         patch.object(api.pipeline_service, "run_ingest_upload", run):
        res = asyncio.run(api.upload_dataset(defn.dataset_id, Mock(state=Mock(request_id="r")), files,
                                             principal=Mock(actor_id="op")))
    api_ok = getattr(res, "status_code", 200) == 200
    assert ui["ok"] == api_ok
    if not api_ok:
        body = json.loads(res.body)
        assert body["error_code"] == ui["error_code"] and res.status_code == 422
        jm.create.assert_not_called()
    else:
        call = run.call_args
        assert call.kwargs["acquisition"]["original_files"] == names
        Path(call.args[5]).unlink(missing_ok=True)  # API が梱包した一時 bundle


def test_16b_chunk_finish_inspects_bundle_members(tmp_path):
    from app.api import admin_upload as up
    defn = _river()
    ds = Mock()
    ds.get.return_value = defn
    part = _zip(tmp_path / "u.part", {n: b"x" for n in A31[:3]})
    up._sessions["u1"] = {"upload_id": "u1", "filename": "my_bundle.zip", "tmp_path": str(part), "dataset_id": defn.dataset_id}
    jm = Mock()
    jm.has_running_job.return_value = False
    with patch.object(up, "get_definition_service", return_value=ds), \
         patch.object(up, "get_state_service", return_value=Mock()), \
         patch.object(up, "get_job_manager", return_value=jm), pytest.raises(HTTPException) as e:
        asyncio.run(up.upload_finish(up.FinishRequest(upload_id="u1", dataset_id=defn.dataset_id,
                                                      total_size=part.stat().st_size), Mock(), principal=Mock()))
    assert e.value.status_code == 422 and e.value.detail["error_code"] == sg.SOURCE_SET_INCOMPLETE
    assert not part.exists() and "u1" not in up._sessions
    jm.create.assert_not_called()
    # pattern 不一致の zip は start では bundle 候補として許可（finish で判定）
    ev = sg.upload_start_evaluation(defn, "my_bundle.zip")
    assert ev.ok and ev.bundle_name == "my_bundle.zip"


# ── data ops 集約（11-14, 18-25, 27-29）───────────────────────────────────────

class Runtime:
    def __init__(self, tmp: Path):
        self.tmp, self.rt = tmp, tmp / "runtime"

    def publish(self, files: dict, feature_counts=None):
        v = self.rt / "versions" / V1
        manifest = {}
        for rel, content in files.items():
            (v / rel).parent.mkdir(parents=True, exist_ok=True)
            (v / rel).write_bytes(content)
            manifest[rel] = _sha(content)
            if rel.startswith("frontend/tiles/"):
                (self.rt / rel).parent.mkdir(parents=True, exist_ok=True)
                (self.rt / rel).write_bytes(content)
        (v / "_manifest.json").write_text(json.dumps({"files": manifest, "feature_counts": feature_counts or {}}))
        if not (self.rt / "current").is_symlink():
            os.symlink(f"versions/{V1}", self.rt / "current")
        return v


def _mbtiles(path: Path) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metadata (name text, value text)")
    conn.execute("CREATE TABLE tiles (zoom_level int, tile_column int, tile_row int, tile_data blob)")
    conn.executemany("INSERT INTO metadata VALUES (?, ?)", [
        ("minzoom", "4"), ("maxzoom", "14"), ("format", "pbf"),
        ("json", json.dumps({"vector_layers": [{"id": "flood"}]}))])
    conn.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", [(4, i, i, b"t") for i in range(5)])
    conn.commit()
    conn.close()
    return path.read_bytes()


@pytest.fixture
def ops(tmp_path, monkeypatch, store):
    monkeypatch.setattr(drr, "_default_cache", drr.SourceShaCache(tmp_path / "cache" / "src.json"))
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "cache" / "tile.json"))
    monkeypatch.setattr(dos, "martin_catalog_ids", lambda ttl=60.0: None)
    monkeypatch.setattr(dos, "_app_properties", lambda: dict(PROPS))
    monkeypatch.setenv("OHG2_DATA_RUNTIME_ROOT", str(tmp_path / "runtime"))
    drr._view_cache.clear()
    dos._fc_cache.clear()
    yield Runtime(tmp_path)
    drr._view_cache.clear()
    dos._fc_cache.clear()


def _river_world(ops, store, *, active=True, routing_content=b"ROUTING", canonical_sha=None):
    tmp = ops.tmp
    canonical = tmp / "data_lake/validated/tokyo/flood/tokyo-river-001.geojson"
    canonical.parent.mkdir(parents=True, exist_ok=True)
    canonical.write_bytes(b"CANONICAL")
    derived = tmp / "data_lake/derived/tokyo/flood"
    derived.mkdir(parents=True, exist_ok=True)
    (derived / "tokyo-river-001.routing.geojson").write_bytes(b"ROUTING")
    (derived / "tokyo-river-001.routing.meta.json").write_text(json.dumps({
        "contract": CONTRACT_VERSION, "dataset_id": "TOKYO-RIVER-001", "source_canonical_path": str(canonical),
        "source_canonical_sha256": canonical_sha or _sha(b"CANONICAL"), "routing_artifact_sha256": _sha(b"ROUTING"),
        "builder_name": BUILDER_NAME, "builder_version": "1.1.0", "tau": 0.85, "min_split_size": 0.0002,
        "feature_count": 822693, "source_feature_count": 947590, "generated_at": "2026-10-05T15:41:41Z"}))
    tile_bytes = _mbtiles(tmp / "build" / "tokyo_river_001.mbtiles")
    ops.publish({
        "backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson": routing_content,
        "frontend/tiles/tokyo/flood/tokyo_river_001.mbtiles": tile_bytes,
        "backend/hazard/inland_flood/tokyo/tokyo_inland_flood_A51.geojson": b"A51",
        "backend/hazard/storm_surge/tokyo_storm_surge.geojson": b"SS",
    }, feature_counts={"backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson": 822693,
                       "backend/hazard/inland_flood/tokyo/tokyo_inland_flood_A51.geojson": 194})
    if active:
        store.add(ah.AcquisitionRecord(
            dataset_id="TOKYO-RIVER-001", acquisition_method="upload", active=True, status="processed",
            validity="valid",
            source_files=[ah.SourceFile(name=n, size=1, sha256="0" * 64, container="TOKYO-RIVER-001_bundle_x.zip") for n in A31],
            bundle=ah.SourceFile(name="TOKYO-RIVER-001_bundle_x.zip", size=4), ingest_job_id="job-1"))
    state = DatasetState(dataset_id="TOKYO-RIVER-001", storage_status=StorageStatus.stored,
                         normalize_status=NormalizeStatus.success, validation_status=ValidationStatus.passed,
                         current_validated_path=str(canonical), deploy_status=DeployStatus.not_deployed)
    return state


def _console(defns_states, **kw):
    ds, ss = Mock(), Mock()
    ds.list_all.return_value = [d for d, _ in defns_states]
    ss.init_from_definition.side_effect = lambda d: next(s for dd, s in defns_states if dd.dataset_id == d.dataset_id)
    return dos.build_console(ds, ss, **kw)


def test_24_river_reference_dataset_all_layers(ops, store):
    """基準実装: 取得 → 変換 → 公開 → 稼働 → tile → integrity を 1 画面分のデータで追える。
    DatasetState は not_deployed（stale cache）でも runtime を正として published。"""
    state = _river_world(ops, store)
    c = _console([(_river(), state)], allow_hash=True, allow_heavy=True)
    r = c["datasets"][0]
    acq = r["acquisition"]
    assert acq["source_provider"] == "国土交通省 国土数値情報" and acq["source_group_mode"] == "all_required"
    assert acq["single_batch_required"] and acq["provenance_status"] == dos.PROVENANCE_COMPLETE
    assert [f["name"] for f in acq["active"]["source_files"]] == A31
    assert r["transform"]["canonical"]["feature_count"] == 947590            # 18
    assert r["transform"]["derived"]["feature_count"] == 822693              # 19
    assert r["transform"]["derived"]["status"] == dos.OK
    assert r["runtime"]["runtime_status"] == "published"                     # 13, 23, 24
    assert r["runtime"]["manifest_match"] is True and r["runtime"]["feature_count"] == 822693
    assert c["current_version"] == V1                                        # 22
    assert r["runtime"]["backend"]["loader_target"] is True                  # 21
    assert r["runtime"]["backend"]["loaded"] == dos.UNOBSERVED
    t = r["tile"]                                                            # 20
    assert t["status"] == dos.OK and t["tileset_id"] == "tokyo_river_001" and t["in_current"]
    assert t["metadata"]["vector_layers"] == ["flood"] and t["metadata"]["maxzoom"] == "14"
    assert t["integrity"]["tile_count"] == 5 and t["integrity"]["quick_check"] == "ok"
    integ = r["integrity"]
    assert integ["overall"] == dos.OK and integ["unobserved"] == ["backend"]
    assert {k: v["status"] for k, v in integ["components"].items()} == {
        "source": "OK", "canonical": "OK", "derived": "OK", "runtime": "OK", "backend": "UNOBSERVED", "tile": "OK"}


def test_11_provenance_unknown_is_shown_not_filled(ops, store):
    state = _river_world(ops, store, active=False)
    defn = _defn("flood", "TOKYO-RIVER-001", requires_tile_build=True)  # 取得元未定義
    r = _console([(defn, state)])["datasets"][0]
    acq = r["acquisition"]
    assert acq["provenance_status"] == dos.PROVENANCE_INCOMPLETE and acq["active"] is None
    assert acq["source_provider"] is None and acq["source_group_mode"] is None
    assert r["integrity"]["components"]["source"]["status"] == dos.WARNING
    assert r["integrity"]["overall"] == dos.WARNING


def test_12_unregistered_runtime_listed_with_loader_use(ops, store):
    state = _river_world(ops, store)
    c = _console([(_river(), state)])
    by = {u["rel_path"]: u for u in c["unregistered_runtime_artifacts"]}
    a51 = by["backend/hazard/inland_flood/tokyo/tokyo_inland_flood_A51.geojson"]
    assert a51["label"] == "UNREGISTERED RUNTIME SOURCE" and a51["provenance"] == "UNKNOWN"
    assert a51["loader_target"] is True and a51["in_use"] is True and a51["feature_count"] == 194
    flat = by["backend/hazard/storm_surge/tokyo_storm_surge.geojson"]
    assert flat["loader_target"] is True  # flat 旧配置も storm_surge loader（rglob）の対象＝使用中
    assert (ops.rt / "versions" / V1 / "backend/hazard/storm_surge/tokyo_storm_surge.geojson").exists()  # 削除しない


def test_14_mismatch_shown_not_published_label(ops, store):
    state = _river_world(ops, store, routing_content=b"OLD-ROUTING")
    r = _console([(_river(), state)], allow_hash=True)["datasets"][0]
    assert r["runtime"]["runtime_status"] == "mismatch" and r["runtime"]["manifest_match"] is False
    assert r["integrity"]["components"]["runtime"]["status"] == dos.WARNING
    assert r["integrity"]["overall"] != dos.OK


def test_14b_stale_derived_is_error(ops, store):
    state = _river_world(ops, store, canonical_sha=_sha(b"OTHER"))
    r = _console([(_river(), state)], allow_hash=True)["datasets"][0]
    assert r["transform"]["derived"]["status"] == dos.ERROR
    assert r["integrity"]["overall"] == dos.ERROR


def test_15_unsupported_tsunami(ops, store):
    """tsunami は UNSUPPORTED 表示、管理画面の反映 API も拒否（既存 test_hazard_atomic_phase1 と同一契約）。"""
    ops.publish({"backend/hazard/tsunami/tsunami_tokyo.geojson": b"T"})
    defn = _defn("tsunami", "TOKYO-TSUNAMI-001")
    state = DatasetState(dataset_id=defn.dataset_id)
    r = _console([(defn, state)])["datasets"][0]
    assert r["runtime"]["runtime_status"] == "unsupported" and r["runtime"]["status"] == dos.WARNING
    from app.api import admin_datasets as api
    ds, ss, jm = Mock(), Mock(), Mock()
    ds.get.return_value = defn
    ss.init_from_definition.return_value = DatasetState(dataset_id=defn.dataset_id, is_deployable=True)
    jm.has_running_job.return_value = False
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss), \
         patch.object(api, "get_job_manager", return_value=jm):
        res = asyncio.run(api.deploy_dataset(defn.dataset_id, Mock(state=Mock(request_id="r")),
                                             principal=Mock(actor_id="op"), body=None))
    assert json.loads(res.body)["error_code"] == "ATOMIC_PUBLISH_UNSUPPORTED"
    jm.create.assert_not_called()


def test_25_list_does_not_hash_or_scan(ops, store):
    state = _river_world(ops, store)
    with patch.object(drr, "sha256_file", side_effect=AssertionError("一覧で hash しない")), \
         patch.object(dos.TileInfoCache, "get", wraps=dos.get_tile_cache().get) as tget:
        r = _console([(_river(), state)], allow_hash=False, allow_heavy=False)["datasets"][0]
    assert all(call.args[1] is False for call in tget.call_args_list)
    assert r["tile"]["integrity"] is None and r["transform"]["canonical"]["sha256"] is None
    # 詳細で 1 回計算した後は一覧でもキャッシュ値（再計算しない）
    _console([(_river(), state)], allow_hash=True, allow_heavy=True)
    with patch.object(drr, "sha256_file", side_effect=AssertionError("再 hash しない")), \
         patch.object(dos.sqlite3, "connect", wraps=sqlite3.connect) as conn:
        r2 = _console([(_river(), state)], allow_hash=False, allow_heavy=False)["datasets"][0]
    assert r2["runtime"]["runtime_status"] == "published" and r2["tile"]["integrity"]["tile_count"] == 5
    assert conn.call_count == 1  # metadata 読み取りのみ（tile 全走査・quick_check なし）


def test_29_non_target_dataset_regression(ops, store):
    ops.publish({"backend/hazard/flood/tokyo/x.routing.geojson": b"x"})
    osm = _defn(None, "ROAD-DRIVING-KANTO-001", requires_normalize=False, requires_validation=False)
    state = DatasetState(dataset_id=osm.dataset_id, deploy_status=DeployStatus.deployed)
    r = _console([(osm, state)])["datasets"][0]
    assert r["runtime"]["runtime_status"] == "legacy"
    assert r["integrity"]["components"]["runtime"]["status"] == dos.NOT_APPLICABLE
    assert r["tile"]["status"] == dos.NOT_APPLICABLE and r["transform"]["derived"]["status"] == dos.NOT_APPLICABLE
    assert not sg.evaluate_source_set(osm, ["kanto-latest.osm.pbf"]).enforced


@pytest.mark.parametrize("rel,expected", [
    ("backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson", True),
    ("backend/hazard/flood/tokyo/tokyo-river-001.geojson", False),
    ("backend/hazard/flood/tokyo_flood_check.geojsonl", False),
    ("backend/hazard/storm_surge/tokyo_storm_surge.geojson", True),
    ("backend/hazard/landslide/tokyo/tokyo_landslide_A33.geojson", True),
    ("backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson", False),
    ("backend/hazard/tsunami/tsunami_tokyo.geojson", True),
    ("backend/hazard/tsunami/tsunami_chiba.geojson", False),
    ("frontend/tiles/tokyo/flood/x.mbtiles", False),
])
def test_21_loader_contract(rel, expected):
    assert dos.loader_contract(rel, PROPS)["loader_target"] is expected
    assert dos.loader_contract("backend/hazard/flood/tokyo/a.routing.geojson", {"hazard.flood.enabled": "false"})["loader_target"] is False
    assert dos.loader_contract(rel, {})["loader_target"] in (None, False)


def test_routing_validation_fact_from_job_log(tmp_path, monkeypatch):
    from app.services import dataset_state_service as dss
    monkeypatch.setattr(dss, "_ADMIN_STATE_DIR", tmp_path / "admin" / "state")
    logs = tmp_path / "admin" / "logs"
    logs.mkdir(parents=True)
    (logs / "job-1.log").write_text(
        '[t] {"routing": "/data_lake/derived/tokyo/flood/tokyo-river-001.routing.geojson", "feature_count": 822693, '
        '"coverage_false_negatives": 0, "seconds": 40.1}\n')
    got = dos.routing_validation_from_logs(["job-1"], "tokyo-river-001.routing.geojson", 822693)
    assert got == {"coverage_false_negatives": 0, "feature_count": 822693, "source": "job log job-1"}
    assert dos.routing_validation_from_logs(["job-1"], "tokyo-river-001.routing.geojson", 1) is None  # 別世代は不採用


# ── 移行（事実のみ・推測しない）──────────────────────────────────────────────────

def test_migration_restores_facts_only(tmp_path):
    from app.services import acquisition_migration as am
    admin = tmp_path / "admin"
    (admin / "history").mkdir(parents=True)
    (admin / "jobs").mkdir()
    raw = _zip(tmp_path / "raw" / "TOKYO-RIVER-001_bundle_s.zip", {n: n.encode() for n in A31})
    (admin / "history" / "TOKYO-RIVER-001.jsonl").write_text(json.dumps({
        "operation_type": "ingest", "result": "success", "source_file_name": raw.name, "job_id": "j1",
        "executed_at": "2026-10-05T15:34:55.793531"}) + "\n")
    (admin / "jobs" / "j1.json").write_text(json.dumps({"job_type": "ingest_upload", "actor_id": "op:x",
                                                        "fetch_url": None, "created_at": "2026-10-05T15:34:54"}))
    state = DatasetState(dataset_id="TOKYO-RIVER-001", current_raw_path=str(raw), normalize_status="success",
                         validation_status="pass")
    rec = am.build_migrated_record(_river(), state, admin_dir=admin)
    assert rec.acquisition_method == ah.AcquisitionMethod.upload and rec.record_origin == "migrated"
    assert [f.name for f in rec.source_files] == A31 and rec.bundle.name == raw.name
    assert rec.acquired_at.isoformat() == "2026-10-05T15:34:55.793531+00:00" and rec.active
    assert rec.source_url is None and rec.source_page_url is None and rec.source_year is None  # 推測しない
    # job 記録が無い → legacy_unknown・取得日時 None
    (admin / "history" / "TOKYO-RIVER-001.jsonl").unlink()
    rec2 = am.build_migrated_record(_river(), state, admin_dir=admin)
    assert rec2.acquisition_method == ah.AcquisitionMethod.legacy_unknown and rec2.acquired_at is None


def test_migration_reads_state_without_self_healing_delete(tmp_path):
    """移行は DatasetStateService.load（stale path で state file を削除する）を使わない。"""
    from app.services import acquisition_migration as am
    sdir = tmp_path / "admin" / "state"
    sdir.mkdir(parents=True)
    f = sdir / "TOKYO-RIVER-001.json"
    f.write_text(json.dumps({"dataset_id": "TOKYO-RIVER-001", "current_raw_path": "/nonexistent/raw.zip"}))
    st = am.read_state_readonly("TOKYO-RIVER-001", admin_dir=tmp_path / "admin")
    assert st.current_raw_path == "/nonexistent/raw.zip" and f.exists()
    ds = Mock()
    ds.list_all.return_value = [_river()]
    out = am.migrate_all(ds, store=ah.AcquisitionStore(tmp_path / "acq"),
                         ss=lambda i: am.read_state_readonly(i, admin_dir=tmp_path / "admin"))
    assert out == [{"dataset_id": "TOKYO-RIVER-001", "action": "no_facts"}] and f.exists()


# ── registry / UI 静的契約 ──────────────────────────────────────────────────────

def test_registry_river_definition_and_consistency():
    from app.services.dataset_definition_service import get_definition_service
    ds = get_definition_service()
    river = ds.get("TOKYO-RIVER-001")
    assert river.source_group_mode.value == "all_required" and river.ingest_mode.value == "single_batch"
    assert river.required_source_count == 4 and river.source_file_patterns == PATTERNS
    assert sg.evaluate_source_set(river, river.expected_source_files).ok
    assert [p for d in ds.list_all() for p in sg.definition_problems(d)] == []
    # 他 dataset は推測で取得元を補っていない
    # 取得元は repository 内の証拠（KSJ A31 原本・資料）がある flood 2 件だけ。他は推測で補っていない
    assert {d.dataset_id for d in ds.list_all() if d.source_provider} == {"TOKYO-RIVER-001", "KANAGAWA-RIVER-001"}


def test_ui_uses_server_judgement_and_text_status():
    js = (ROOT / "operator/frontend-admin/datasets.js").read_text(encoding="utf-8")
    assert "/data-ops/${encodeURIComponent(d.dataset_id)}/source-set/check" in js
    assert "function applyExecuteGuard" in js and "_sourceSetEval.confirm_message" in js
    ops_js = (ROOT / "operator/frontend-admin/data-ops.js").read_text(encoding="utf-8")
    assert "innerHTML" not in ops_js  # 外部由来の値は textContent のみ
    assert "UNREGISTERED RUNTIME SOURCE" in ops_js and "PROVENANCE INCOMPLETE" in ops_js
    assert "delete" not in ops_js.lower().replace("削除はしない", "")  # 削除操作を置かない
    html = (ROOT / "operator/frontend-admin/data-ops.html").read_text(encoding="utf-8")
    assert 'src="/admin/js/admin-shell.js"' in html


def test_operator_registers_data_ops_router_with_auth():
    src = (ROOT / "backend/app_operator.py").read_text(encoding="utf-8")
    routers = src[src.index("OPERATOR_ROUTERS = ["):src.index("]", src.index("OPERATOR_ROUTERS = ["))]
    assert "admin_data_ops_router" in routers

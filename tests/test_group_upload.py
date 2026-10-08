"""
複数原本を 1 acquisition として直接アップロード（利用者に bundle zip を作らせない）。

  group/start   全原本の名前・size → 原本セット判定（source_group）。不足・不正は送信前に 422
  chunk         file ごとに既存 chunk 送信
  group/finish  全 file 受信確認 → 再判定 → サーバーが無圧縮 bundle を disk 上で組立 → 取込 job 1 件
  1 ファイルの上限は max_browser_upload_mb（引き上げない）。合計は chunk upload 上限まで。
"""
from __future__ import annotations

import asyncio
import hashlib
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api import admin_upload as up  # noqa: E402
from app.models.admin_dataset import Job, JobType  # noqa: E402
from app.services import acquisition_history as ah  # noqa: E402
from app.services import pipeline_service as ps  # noqa: E402
from app.services import source_group as sg  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

MESHES = ["5238", "5239", "5338", "5339"]
OFFICIAL = ["A31a-25_14_10_GML.zip", "A31a-25_14_20_GML.zip"] + [
    f"A31b-25_{c}_{m}_GML.zip" for m in MESHES for c in ("10", "20")]
MB = 1024 * 1024


def _content(name):
    return f"payload-{name}".encode() * 3


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(up, "_TMP_DIR", tmp_path / "uploads")
    up._sessions.clear()
    up._groups.clear()
    defn = get_definition_service().get("KANAGAWA-RIVER-001")
    ds = Mock()
    ds.get.return_value = defn
    jm = Mock()
    jm.has_running_job.return_value = False
    jm.create.return_value = Mock(job_id="job-g")
    run = Mock(return_value=None)
    patches = [patch.object(up, "get_definition_service", return_value=ds),
               patch.object(up, "get_job_manager", return_value=jm),
               patch.object(up, "get_state_service", return_value=Mock()),
               patch.object(up.pipeline_service, "run_ingest_upload", run)]
    for p in patches:
        p.start()
    yield {"defn": defn, "jm": jm, "run": run, "tmp": tmp_path}
    for p in patches:
        p.stop()
    up._sessions.clear()
    up._groups.clear()


def _start(names, sizes=None):
    sizes = sizes or [len(_content(n)) for n in names]
    return asyncio.run(up.upload_group_start(up.GroupStartRequest(
        dataset_id="KANAGAWA-RIVER-001", files=[{"filename": n, "size": s} for n, s in zip(names, sizes)])))


async def _send_chunk(upload_id, data):
    async def stream():
        yield data
    req = Mock()
    req.stream = stream
    return await up.upload_chunk(req, x_upload_id=upload_id, x_chunk_index=0, x_chunk_offset=0)


def _finish(res, sizes=None, drop=0):
    files = [{"upload_id": u["upload_id"], "total_size": (sizes or {}).get(u["filename"], u["size"])}
             for u in res["uploads"]][drop:]
    return asyncio.run(up.upload_group_finish(up.GroupFinishRequest(
        group_id=res["group_id"], dataset_id="KANAGAWA-RIVER-001", files=files),
        Mock(state=Mock(request_id="r")), principal=Mock(actor_id="op")))


def test_full_group_flow_builds_bundle_and_one_job(env):
    res = _start(OFFICIAL)
    assert len(res["uploads"]) == 10 and res["source_set"]["ok"]
    for u in res["uploads"]:
        asyncio.run(_send_chunk(u["upload_id"], _content(u["filename"])))
    out = _finish(res)
    assert out.job_id == "job-g"
    env["jm"].create.assert_called_once()  # 10 原本で取込 job は 1 件
    call = env["run"].call_args
    bundle = Path(call.args[5])
    assert call.kwargs["acquisition"] == {"method": "upload", "original_files": OFFICIAL}
    with zipfile.ZipFile(bundle) as zf:
        infos = zf.infolist()
        assert sorted(i.filename for i in infos) == sorted(OFFICIAL)
        assert all(i.compress_type == zipfile.ZIP_STORED for i in infos)  # 無圧縮で組立
        for i in infos:
            assert zf.read(i) == _content(i.filename)  # 原本 bytes をそのまま保持
    assert sg.evaluate_stored_file(env["defn"], bundle).ok
    assert not list((env["tmp"] / "uploads").glob("*.part"))  # 中間 file は削除
    assert up._sessions == {} and up._groups == {}
    bundle.unlink()


@pytest.mark.parametrize("names,code", [
    (OFFICIAL[:-1], sg.SOURCE_SET_INCOMPLETE),
    (OFFICIAL + ["A31b-25_10_5240_GML.zip"], sg.SOURCE_SET_UNEXPECTED),
    ([n.replace("_14_", "_13_") for n in OFFICIAL], sg.SOURCE_SET_INCOMPLETE),
])
def test_start_rejects_before_any_data_is_sent(env, names, code):
    with pytest.raises(HTTPException) as e:
        _start(names)
    assert e.value.status_code == 422 and e.value.detail["error_code"] == code
    assert up._sessions == {} and up._groups == {}


def test_per_file_limit_kept_at_definition_value(env):
    sizes = [10] * 10
    sizes[5] = 201 * MB  # 200MB を超える 1 ファイル
    with pytest.raises(HTTPException) as e:
        _start(OFFICIAL, sizes)
    assert e.value.status_code == 413 and "200MB" in e.value.detail
    # 合計 263MB 相当でも 1 ファイルずつ上限内なら受付（従来の FormData 経路の合計 200MB 制約を受けない）
    ok = _start(OFFICIAL, [int(x * MB) for x in (34.19, 0.01, 36.49, 1.97, 6.75, 1.3, 22.9, 12.16, 112.79, 34.99)])
    assert len(ok["uploads"]) == 10


def test_duplicate_names_rejected(env):
    with pytest.raises(HTTPException) as e:
        _start([OFFICIAL[0], OFFICIAL[0]])
    assert e.value.status_code == 400


def test_finish_requires_all_files_and_exact_sizes(env):
    res = _start(OFFICIAL)
    for u in res["uploads"][:-1]:
        asyncio.run(_send_chunk(u["upload_id"], _content(u["filename"])))
    with pytest.raises(HTTPException) as e:
        _finish(res)  # 最後の 1 件が未受信
    assert e.value.status_code == 400
    with pytest.raises(HTTPException) as e:
        _finish(res, drop=1)  # 完了通知が全件そろっていない
    assert e.value.status_code == 400
    env["jm"].create.assert_not_called()


def test_group_member_cannot_finish_alone(env):
    res = _start(OFFICIAL)
    u = res["uploads"][0]
    asyncio.run(_send_chunk(u["upload_id"], _content(u["filename"])))
    with pytest.raises(HTTPException) as e:
        asyncio.run(up.upload_finish(up.FinishRequest(upload_id=u["upload_id"], dataset_id="KANAGAWA-RIVER-001",
                                                      total_size=u["size"]), Mock(), principal=Mock()))
    assert e.value.status_code == 409
    env["jm"].create.assert_not_called()


def test_cancel_removes_parts(env):
    res = _start(OFFICIAL)
    asyncio.run(_send_chunk(res["uploads"][0]["upload_id"], b"x"))
    asyncio.run(up.upload_group_cancel(up.GroupCancelRequest(group_id=res["group_id"])))
    assert up._sessions == {} and up._groups == {}
    assert not list((env["tmp"] / "uploads").glob("*.part"))


def test_pipeline_records_ten_originals_with_sha(tmp_path, monkeypatch):
    """group が組み立てた bundle → acquisition に内部 10 原本の名前・size・sha256（bundle 名だけにしない）。"""
    defn = get_definition_service().get("KANAGAWA-RIVER-001")
    store = ah.AcquisitionStore(tmp_path / "acq")
    monkeypatch.setattr(ps, "get_acquisition_store", lambda: store)
    monkeypatch.setattr(up, "_TMP_DIR", tmp_path)
    parts = []
    for n in OFFICIAL:
        p = tmp_path / f"{n}.part"
        p.write_bytes(_content(n))
        parts.append((n, p))
    bundle = up._build_group_bundle("KANAGAWA-RIVER-001", parts)
    job = Job(job_id="j", dataset_id="KANAGAWA-RIVER-001", job_type=JobType.ingest_upload)
    ps._record_acquisition(job, defn, bundle, {"method": "upload", "original_files": OFFICIAL})
    rec = store.list("KANAGAWA-RIVER-001")[0]
    assert [f.name for f in rec.source_files] == sorted(OFFICIAL)
    for f in rec.source_files:
        assert f.size == len(_content(f.name)) and f.sha256 == hashlib.sha256(_content(f.name)).hexdigest()
        assert f.container == bundle.name
    assert rec.validity == ah.AcquisitionValidity.valid


def test_ui_uses_group_upload_for_multiple_files():
    js = (ROOT / "operator/frontend-admin/datasets.js").read_text(encoding="utf-8")
    um = (ROOT / "operator/frontend-admin/upload-manager.js").read_text(encoding="utf-8")
    branch = js[js.index("// 複数原本 → 1 件の取得として chunk upload"):js.index("} else if (_activeInputTab === \"fetch_url\")")]
    assert "uploadGroup(files, d.dataset_id" in branch and "FormData" not in branch
    assert "async uploadGroup(" in um and "'/group/start'" in um and "'/group/finish'" in um
    assert "start.uploads[fi]" in um  # 名前ではなく順序で対応付け（sanitize 差異を避ける）

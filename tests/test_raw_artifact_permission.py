"""
RAW-ARTIFACT-PERMISSION（2026-10-12）: raw 原本は保存直後に mode 0644 へ揃える（umask・一時 file の mode に依存しない）。

VPS に root:root 0600 の raw が 13 件残っていた。2026-04 の operator は root 実行で、upload の一時 file
（NamedTemporaryFile = 0600）を shutil.copy2 で raw へ保存したため mode が引き継がれた。operator（uid 10002）
からは読めず、取得履歴・出典を検証できなかった。VPS 側は 13 件を明示 path だけ 1000:1000 0644 に正規化済み
（~/backups/raw-permission-normalization-20261012/）。ここでは再発を防ぐ。
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import stat
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetState, Job, JobType  # noqa: E402
from app.services import pipeline_service as ps  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

DID = "TOKYO-LANDSLIDE-001"
NAME = "A33-24_13_GML.zip"


def _mode(p: Path) -> int:
    return stat.S_IMODE(p.stat().st_mode)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _upload_tmp(tmp_path: Path) -> Path:
    """admin API と同じく NamedTemporaryFile（0600）で一時 file を作る。"""
    d = tmp_path / "uploads"
    d.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, dir=d, suffix=".zip") as tmp:
        with zipfile.ZipFile(tmp, "w") as zf:
            zf.writestr("A33-24_13.xml", "<ksj/>")
    final = d / NAME
    os.replace(tmp.name, final)
    return final


@pytest.fixture
def ingest(tmp_path, monkeypatch):
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    defn = get_definition_service().get(DID)

    def run(src: Path):
        job = Job(job_id="job-raw-perm", dataset_id=DID, job_type=JobType.ingest_upload)
        jm, ss = Mock(), Mock()
        state = DatasetState(dataset_id=DID)
        with patch.object(ps, "_run_post_ingest_pipeline", new=Mock(side_effect=lambda *a, **k: asyncio.sleep(0))), \
             patch.object(ps, "_record_acquisition", return_value=None), \
             patch.object(ps, "_finalize_acquisition", return_value=None):
            asyncio.run(ps.run_ingest_upload(job, defn, state, jm, ss, src))
        return tmp_path / defn.raw_storage_path / NAME, jm

    return run


def test_01_02_03_uploaded_raw_is_0644_readable_and_unchanged(tmp_path, ingest):
    src = _upload_tmp(tmp_path)
    assert _mode(src) == 0o600  # 一時 file は 0600（以前はこれが raw に引き継がれた）
    sha = _sha(src)
    raw, _ = ingest(src)
    assert _mode(raw) == ps.RAW_FILE_MODE == 0o644
    assert raw.stat().st_uid == os.getuid()  # 所有者は書き込んだ process（chown しない）
    with raw.open("rb") as f:
        assert f.read(2) == b"PK"
    assert _sha(raw) == sha


def test_04_overwriting_existing_0600_raw_becomes_0644(tmp_path, ingest):
    defn = get_definition_service().get(DID)
    existing = tmp_path / defn.raw_storage_path / NAME
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"old")
    os.chmod(existing, 0o600)
    raw, _ = ingest(_upload_tmp(tmp_path))
    assert raw == existing and _mode(raw) == 0o644 and raw.read_bytes() != b"old"


def test_07_umask_does_not_change_raw_mode(tmp_path, ingest):
    old = os.umask(0o077)
    try:
        raw, _ = ingest(_upload_tmp(tmp_path))
    finally:
        os.umask(old)
    assert _mode(raw) == 0o644


def test_fetched_raw_is_0644(tmp_path, monkeypatch):
    """URL / 公式取得は raw dir へ直接 download する（curl の mode は umask 依存）。保存処理で揃える。"""
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    defn = get_definition_service().get(DID)
    dest = tmp_path / defn.raw_storage_path / NAME
    dest.parent.mkdir(parents=True)
    with zipfile.ZipFile(dest, "w") as zf:
        zf.writestr("A33-24_13.xml", "<ksj/>")
    os.chmod(dest, 0o600)
    job = Job(job_id="job-fetch", dataset_id=DID, job_type=JobType.ingest_fetch_url)
    with patch.object(ps, "_run_post_ingest_pipeline", new=Mock(side_effect=lambda *a, **k: asyncio.sleep(0))), \
         patch.object(ps, "_record_acquisition", return_value=None), \
         patch.object(ps, "_finalize_acquisition", return_value=None):
        asyncio.run(ps._store_downloaded(job, defn, DatasetState(dataset_id=DID), Mock(), Mock(), dest))
    assert _mode(dest) == 0o644


def test_chmod_failure_is_logged_not_silent(tmp_path, monkeypatch):
    def deny(*a, **k):
        raise PermissionError("Operation not permitted")
    monkeypatch.setattr(ps.os, "chmod", deny)
    jm = Mock()
    ps._apply_raw_file_mode(Mock(), jm, tmp_path / "x.zip")
    assert any("raw file mode" in str(c.args[1]) for c in jm.log.call_args_list)


def test_05_06_no_extract_or_rename_into_raw():
    """raw へは copy2（upload）か download だけで保存する（展開・rename で raw を作る経路は無い）。
    新しい保存経路を足したら _apply_raw_file_mode を通すこと。"""
    src = (ROOT / "backend/app/services/pipeline_service.py").read_text(encoding="utf-8")
    store_paths = src.count("_apply_raw_file_mode(job, jm, dest_path)")
    assert store_paths == 2  # run_ingest_upload と _store_downloaded


def test_08_isolation_never_touches_real_raw(tmp_path, ingest):
    real = ROOT / "data_lake/raw/tokyo/landslide" / NAME
    before = real.stat() if real.exists() else None
    ingest(_upload_tmp(tmp_path))
    after = real.stat() if real.exists() else None
    assert (before and (before.st_mtime_ns, before.st_mode)) == (after and (after.st_mtime_ns, after.st_mode))

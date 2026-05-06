"""
admin_upload.py — 大容量ファイル チャンクアップロード API

POST   /api/admin/upload/start    セッション開始
POST   /api/admin/upload/chunk    チャンク送信
POST   /api/admin/upload/finish   完了・パイプライン起動
DELETE /api/admin/upload/cancel   キャンセル・中間ファイル削除
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.models.admin_dataset import JobAccepted, JobType
from app.services.admin_log_service import write_app_log
from app.services.dataset_definition_service import get_definition_service
from app.services.dataset_state_service import get_state_service
from app.services.job_manager import get_job_manager
from app.services import pipeline_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/upload", tags=["admin-upload"])

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_TMP_DIR = _PROJECT_ROOT / "data_runtime" / "uploads" / "tmp"
_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB

# in-memory session store: upload_id → metadata dict
_sessions: Dict[str, dict] = {}
_lock = asyncio.Lock()

_SAFE_NAME_RE = re.compile(r"[^\w\-. ]+")
_ALLOWED_EXTS = {".zip", ".geojson", ".json", ".mbtiles", ".gpkg", ".gml"}


def _sanitize_filename(name: str) -> str:
    name = Path(name).name  # strip directory components
    name = _SAFE_NAME_RE.sub("_", name)
    return name or "upload"


def _write_app_log_safe(message: str, level: str = "INFO") -> None:
    try:
        write_app_log(message, level=level)
    except Exception:
        pass


# ── POST /start ───────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    filename: str
    size: int
    dataset_id: str


class StartResponse(BaseModel):
    upload_id: str
    chunk_size: int


@router.post("/start", response_model=StartResponse)
async def upload_start(body: StartRequest):
    ds = get_definition_service()
    defn = ds.get(body.dataset_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"dataset_id={body.dataset_id} not found")

    if body.size > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"ファイルサイズが上限（{_MAX_UPLOAD_BYTES // 1024**3}GB）を超えています")

    safe_name = _sanitize_filename(body.filename)
    ext = Path(safe_name).suffix.lower()
    if defn.accepted_extensions and ext not in defn.accepted_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"ファイル形式 '{ext}' は非対応です。対応形式: {defn.accepted_extensions}",
        )

    import uuid
    upload_id = str(uuid.uuid4())

    _TMP_DIR.mkdir(parents=True, exist_ok=True)

    async with _lock:
        _sessions[upload_id] = {
            "upload_id": upload_id,
            "filename": safe_name,
            "size": body.size,
            "dataset_id": body.dataset_id,
            "received_bytes": 0,
            "tmp_path": str(_TMP_DIR / f"{upload_id}.part"),
            "started_at": time.time(),
        }

    _write_app_log_safe(
        f"UPLOAD_START upload_id={upload_id} dataset_id={body.dataset_id} filename={safe_name} size={body.size}"
    )
    return StartResponse(upload_id=upload_id, chunk_size=_CHUNK_SIZE)


# ── POST /chunk ───────────────────────────────────────────────────────────────

@router.post("/chunk")
async def upload_chunk(
    request: Request,
    x_upload_id: str = Header(...),
    x_chunk_index: int = Header(...),
    x_chunk_offset: int = Header(...),
):
    session = _sessions.get(x_upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="upload session not found")

    tmp_path = Path(session["tmp_path"])

    # stream write — never buffer entire chunk in memory
    written = 0
    with open(tmp_path, "ab") as f:
        f.seek(0, 2)
        current_pos = f.tell()
        if current_pos != x_chunk_offset:
            # offset mismatch — likely a retry; truncate to expected position
            f.truncate(x_chunk_offset)
            f.seek(x_chunk_offset)
        async for data in request.stream():
            f.write(data)
            written += len(data)

    async with _lock:
        session["received_bytes"] = x_chunk_offset + written

    _write_app_log_safe(
        f"UPLOAD_PROGRESS upload_id={x_upload_id} chunk={x_chunk_index} offset={x_chunk_offset} written={written}",
        level="DEBUG",
    )
    return {"received": True, "chunk_index": x_chunk_index, "written": written}


# ── POST /finish ──────────────────────────────────────────────────────────────

class FinishRequest(BaseModel):
    upload_id: str
    dataset_id: str
    total_size: int
    sha256: Optional[str] = None


@router.post("/finish", response_model=JobAccepted)
async def upload_finish(body: FinishRequest):
    session = _sessions.get(body.upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="upload session not found")

    tmp_path = Path(session["tmp_path"])
    if not tmp_path.exists():
        raise HTTPException(status_code=400, detail="temp file missing")

    actual_size = tmp_path.stat().st_size
    if actual_size != body.total_size:
        raise HTTPException(
            status_code=400,
            detail=f"サイズ不一致 expected={body.total_size} actual={actual_size}",
        )

    if body.sha256:
        h = hashlib.sha256()
        with open(tmp_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != body.sha256:
            tmp_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="SHA256 チェックサム不一致")

    ds_svc = get_definition_service()
    ss = get_state_service()
    jm = get_job_manager()

    defn = ds_svc.get(body.dataset_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"dataset_id={body.dataset_id} not found")

    if jm.has_running_job(body.dataset_id):
        raise HTTPException(status_code=409, detail="このデータセットでは現在別の処理が実行中です")

    # rename temp file to include original filename for pipeline readability
    safe_name = session["filename"]
    final_tmp = tmp_path.parent / safe_name
    tmp_path.rename(final_tmp)

    state = ss.init_from_definition(defn)
    job = jm.create(body.dataset_id, JobType.ingest_upload)
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_ingest_upload(job, defn, state, jm, ss, final_tmp))

    async with _lock:
        _sessions.pop(body.upload_id, None)

    _write_app_log_safe(
        f"UPLOAD_FINISH upload_id={body.upload_id} dataset_id={body.dataset_id} "
        f"job_id={job.job_id} size={actual_size}"
    )
    return JobAccepted(job_id=job.job_id, message="ファイルを受け付けました。処理を開始します。")


# ── DELETE /cancel ────────────────────────────────────────────────────────────

class CancelRequest(BaseModel):
    upload_id: str


@router.delete("/cancel")
async def upload_cancel(body: CancelRequest):
    async with _lock:
        session = _sessions.pop(body.upload_id, None)

    if session:
        tmp_path = Path(session["tmp_path"])
        tmp_path.unlink(missing_ok=True)
        # also remove renamed file if finish was partially called
        renamed = tmp_path.parent / session["filename"]
        renamed.unlink(missing_ok=True)

    _write_app_log_safe(f"UPLOAD_CANCEL upload_id={body.upload_id}")
    return {"cancelled": True}

"""
admin_upload.py — 大容量ファイル チャンクアップロード API

POST   /api/admin/upload/start    セッション開始
POST   /api/admin/upload/chunk    チャンク送信
POST   /api/admin/upload/finish   完了・パイプライン起動
DELETE /api/admin/upload/cancel   キャンセル・中間ファイル削除

複数原本を 1 acquisition として投入する（利用者に zip を作らせない）:
POST   /api/admin/upload/group/start   全原本の名前・size を受け取り、原本セット判定（source_group）
                                       を通ったものだけ file ごとの upload_id を発行
POST   /api/admin/upload/chunk         （file ごとに既存の chunk 送信を使う）
POST   /api/admin/upload/group/finish  全 file の受信完了を確認し、サーバー側で bundle zip（無圧縮）
                                       を disk 上で組み立てて取込 job を 1 件起動
DELETE /api/admin/upload/group/cancel  キャンセル・中間ファイル削除
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.models.admin_dataset import JobAccepted, JobType
from app.services.admin_log_service import write_app_log
from app.services.dataset_definition_service import get_definition_service
from app.services.dataset_state_service import get_state_service
from app.services.job_manager import get_job_manager
from app.services.operator_auth import OperatorPrincipal, require_operator_role
from app.services import pipeline_service
from app.services import source_group

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin/upload", tags=["admin-upload"])

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_TMP_DIR = _PROJECT_ROOT / "data_runtime" / "uploads" / "tmp"
_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024 * 1024  # 10 GB

# in-memory session store: upload_id → metadata dict
_sessions: Dict[str, dict] = {}
# 複数原本 group: group_id → {"dataset_id", "upload_ids": [...], "started_at"}
_groups: Dict[str, dict] = {}
_MAX_GROUP_FILES = 50
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
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

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

    # 取得原本セットの hard guard（source_group）。all_required の原本 1 件だけを単独投入する等の
    # 部分投入はここで拒否する。pattern に一致しない zip は bundle 候補として finish 時に zip 内を判定。
    ev = source_group.upload_start_evaluation(defn, safe_name)
    if not ev.ok:
        raise HTTPException(status_code=422, detail={
            "error_code": ev.error_code, "message": " / ".join(ev.blocking_reasons), "source_set": ev.as_dict(),
        })

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
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

    upload_id: str
    dataset_id: str
    total_size: int
    sha256: Optional[str] = None


@router.post("/finish", response_model=JobAccepted)
async def upload_finish(
    body: FinishRequest,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
    session = _sessions.get(body.upload_id)
    if session is None:
        raise HTTPException(status_code=404, detail="upload session not found")
    if session.get("group_id"):
        # 複数原本 group の一部を単独で取込ませない（部分投入の迂回路を作らない）
        raise HTTPException(status_code=409, detail="この upload は複数原本 group の一部です。group/finish を使用してください")

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

    # 取得原本セットの hard guard: bundle zip は central directory の原本名で判定（展開しない）
    ev = source_group.evaluate_stored_file(defn, tmp_path, display_name=safe_name)
    if not ev.ok:
        tmp_path.unlink(missing_ok=True)
        async with _lock:
            _sessions.pop(body.upload_id, None)
        raise HTTPException(status_code=422, detail={
            "error_code": ev.error_code, "message": " / ".join(ev.blocking_reasons), "source_set": ev.as_dict(),
        })

    final_tmp = tmp_path.parent / safe_name
    tmp_path.rename(final_tmp)

    state = ss.init_from_definition(defn)
    job = jm.create(
        body.dataset_id, JobType.ingest_upload,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.last_job_id = job.job_id
    ss.save(state)

    jm.submit(job, pipeline_service.run_ingest_upload(
        job, defn, state, jm, ss, final_tmp,
        acquisition={"method": "upload", "original_files": [safe_name]},
    ))

    async with _lock:
        _sessions.pop(body.upload_id, None)

    _write_app_log_safe(
        f"UPLOAD_FINISH upload_id={body.upload_id} dataset_id={body.dataset_id} "
        f"job_id={job.job_id} size={actual_size}"
    )
    return JobAccepted(job_id=job.job_id, message="ファイルを受け付けました。処理を開始します。")


# ── DELETE /cancel ────────────────────────────────────────────────────────────

class CancelRequest(BaseModel):
    # Phase 2-B.3 (5.2節): 未知fieldを拒否する（extra="forbid"）。
    model_config = ConfigDict(extra="forbid")

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


# ── 複数原本 group upload ──────────────────────────────────────────────────────

class GroupFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    size: int


class GroupStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset_id: str
    files: List[GroupFile]


class GroupFinishFile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_id: str
    total_size: int
    sha256: Optional[str] = None


class GroupFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    dataset_id: str
    files: List[GroupFinishFile]


class GroupCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str


def _reject_source_set(ev) -> None:
    raise HTTPException(status_code=422, detail={
        "error_code": ev.error_code, "message": " / ".join(ev.blocking_reasons), "source_set": ev.as_dict(),
    })


@router.post("/group/start")
async def upload_group_start(body: GroupStartRequest):
    """複数原本の受付開始。データ送信前に原本セット（source_group）を判定し、不足・不正なら 422。"""
    ds = get_definition_service()
    defn = ds.get(body.dataset_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"dataset_id={body.dataset_id} not found")
    if not body.files or len(body.files) > _MAX_GROUP_FILES:
        raise HTTPException(status_code=400, detail=f"ファイル数は 1〜{_MAX_GROUP_FILES} 件です")

    names = [_sanitize_filename(f.filename) for f in body.files]
    if len(set(names)) != len(names):
        raise HTTPException(status_code=400, detail="同名のファイルが含まれています")
    per_file_limit = defn.max_browser_upload_mb * 1024 * 1024 if defn.max_browser_upload_mb > 0 else _MAX_UPLOAD_BYTES
    for name, f in zip(names, body.files):
        ext = Path(name).suffix.lower()
        if defn.accepted_extensions and ext not in defn.accepted_extensions:
            raise HTTPException(status_code=400, detail=f"ファイル '{name}' の形式 '{ext}' は非対応です")
        if f.size <= 0 or f.size > per_file_limit:
            raise HTTPException(status_code=413, detail=(
                f"ファイル '{name}' のサイズが上限（1 ファイル {per_file_limit // (1024 * 1024)}MB）を超えています"))
    if sum(f.size for f in body.files) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"合計サイズが上限（{_MAX_UPLOAD_BYTES // 1024**3}GB）を超えています")

    ev = source_group.evaluate_source_set(defn, names)
    if not ev.ok:
        _reject_source_set(ev)
    if get_job_manager().has_running_job(body.dataset_id):
        raise HTTPException(status_code=409, detail="このデータセットでは現在別の処理が実行中です")

    _TMP_DIR.mkdir(parents=True, exist_ok=True)
    group_id = str(uuid.uuid4())
    uploads = []
    async with _lock:
        for name, f in zip(names, body.files):
            upload_id = str(uuid.uuid4())
            _sessions[upload_id] = {
                "upload_id": upload_id, "filename": name, "size": f.size, "dataset_id": body.dataset_id,
                "received_bytes": 0, "tmp_path": str(_TMP_DIR / f"{upload_id}.part"), "started_at": time.time(),
                "group_id": group_id,
            }
            uploads.append({"filename": name, "upload_id": upload_id, "size": f.size})
        _groups[group_id] = {"dataset_id": body.dataset_id, "upload_ids": [u["upload_id"] for u in uploads],
                             "started_at": time.time()}
    _write_app_log_safe(
        f"UPLOAD_GROUP_START group_id={group_id} dataset_id={body.dataset_id} files={len(uploads)} "
        f"total={sum(f.size for f in body.files)}"
    )
    return {"group_id": group_id, "chunk_size": _CHUNK_SIZE, "uploads": uploads, "source_set": ev.as_dict()}


def _cleanup_group(group_id: str) -> None:
    group = _groups.pop(group_id, None)
    if not group:
        return
    for upload_id in group["upload_ids"]:
        session = _sessions.pop(upload_id, None)
        if session:
            Path(session["tmp_path"]).unlink(missing_ok=True)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _build_group_bundle(dataset_id: str, parts: List[tuple]) -> Path:
    """受信済み原本を無圧縮 zip（ZIP_STORED）へ disk 上で組み立てる（全体を memory に載せない）。
    normalize は従来どおり bundle zip 内の原本を展開して処理する。"""
    final = _TMP_DIR / f"{dataset_id}_bundle_{uuid.uuid4().hex[:8]}.zip"
    tmp = final.with_name(f".{final.name}.building")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for name, part in parts:
                zf.write(part, arcname=name)
        tmp.rename(final)
    finally:
        tmp.unlink(missing_ok=True)
    return final


@router.post("/group/finish", response_model=JobAccepted)
async def upload_group_finish(
    body: GroupFinishRequest,
    request: Request,
    principal: OperatorPrincipal = Depends(require_operator_role),
):
    group = _groups.get(body.group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="upload group not found")
    if group["dataset_id"] != body.dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id が group と一致しません")
    declared = {f.upload_id: f for f in body.files}
    if set(declared) != set(group["upload_ids"]):
        raise HTTPException(status_code=400, detail="group の全ファイルについて完了通知が必要です")

    defn = get_definition_service().get(body.dataset_id)
    if defn is None:
        raise HTTPException(status_code=404, detail=f"dataset_id={body.dataset_id} not found")

    parts = []
    for upload_id in group["upload_ids"]:
        session = _sessions.get(upload_id)
        f = declared[upload_id]
        part = Path(session["tmp_path"]) if session else None
        if session is None or part is None or not part.exists():
            raise HTTPException(status_code=400, detail=f"受信データがありません: {session and session['filename']}")
        actual = part.stat().st_size
        if actual != f.total_size or actual != session["size"]:
            raise HTTPException(status_code=400, detail=(
                f"サイズ不一致 {session['filename']}: expected={session['size']} actual={actual}"))
        if f.sha256 and _sha256_file(part) != f.sha256:
            _cleanup_group(body.group_id)
            raise HTTPException(status_code=400, detail=f"SHA256 チェックサム不一致: {session['filename']}")
        parts.append((session["filename"], part))

    # 受信した実ファイル名の集合で再判定（start 時の判定を信用しきらない）
    names = [n for n, _ in parts]
    ev = source_group.evaluate_source_set(defn, names)
    if not ev.ok:
        _cleanup_group(body.group_id)
        _reject_source_set(ev)

    jm = get_job_manager()
    if jm.has_running_job(body.dataset_id):
        raise HTTPException(status_code=409, detail="このデータセットでは現在別の処理が実行中です")

    bundle = await asyncio.to_thread(_build_group_bundle, body.dataset_id, parts)
    _cleanup_group(body.group_id)
    ev_bundle = source_group.evaluate_stored_file(defn, bundle)
    if not ev_bundle.ok:
        bundle.unlink(missing_ok=True)
        _reject_source_set(ev_bundle)

    ss = get_state_service()
    state = ss.init_from_definition(defn)
    job = jm.create(
        body.dataset_id, JobType.ingest_upload,
        actor_id=principal.actor_id, request_id=getattr(request.state, "request_id", None),
    )
    state.last_job_id = job.job_id
    ss.save(state)
    jm.submit(job, pipeline_service.run_ingest_upload(
        job, defn, state, jm, ss, bundle,
        acquisition={"method": "upload", "original_files": names},
    ))
    _write_app_log_safe(
        f"UPLOAD_GROUP_FINISH group_id={body.group_id} dataset_id={body.dataset_id} job_id={job.job_id} "
        f"files={len(names)} bundle={bundle.name}"
    )
    return JobAccepted(job_id=job.job_id, message=f"{len(names)} ファイルを 1 件の取得として受け付けました。処理を開始します。")


@router.delete("/group/cancel")
async def upload_group_cancel(body: GroupCancelRequest):
    async with _lock:
        _cleanup_group(body.group_id)
    _write_app_log_safe(f"UPLOAD_GROUP_CANCEL group_id={body.group_id}")
    return {"cancelled": True}

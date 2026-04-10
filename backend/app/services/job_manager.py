"""
job_manager.py — 非同期ジョブ管理エンジン

ジョブを data_lake/admin/jobs/{job_id}.json に永続化し、
asyncio を使ってバックグラウンドで実行する。
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Coroutine, Dict, List, Optional

from app.models.admin_dataset import Job, JobStatus, JobStep, JobType
from app.models.admin_dataset import DeployStatus, NormalizeStatus, OsrmRebuildStatus, ValidationStatus

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ADMIN_JOBS_DIR = _PROJECT_ROOT / "data_lake" / "admin" / "jobs"
_ADMIN_LOGS_DIR = _PROJECT_ROOT / "data_lake" / "admin" / "logs"
_LOG_TAIL_LINES = 200


class JobManager:
    """
    ジョブの作成・永続化・バックグラウンド実行を管理する。

    MVP 方針: FastAPI + asyncio のみ。外部ジョブキュー（Celery等）は不使用。
    """

    def __init__(
        self,
        jobs_dir: Optional[Path] = None,
        logs_dir: Optional[Path] = None,
    ) -> None:
        self._jobs_dir = (jobs_dir or _ADMIN_JOBS_DIR).resolve()
        self._logs_dir = (logs_dir or _ADMIN_LOGS_DIR).resolve()
        self._jobs_dir.mkdir(parents=True, exist_ok=True)
        self._logs_dir.mkdir(parents=True, exist_ok=True)
        # インメモリで実行中ジョブを追跡（プロセス再起動で消えるが MVP では許容）
        self._running: Dict[str, asyncio.Task] = {}

    # ── ジョブファイル操作 ────────────────────────────────────────────────────

    def _job_path(self, job_id: str) -> Path:
        return self._jobs_dir / f"{job_id}.json"

    def _log_path(self, job_id: str) -> Path:
        return self._logs_dir / f"{job_id}.log"

    def _save(self, job: Job) -> None:
        path = self._job_path(job.job_id)
        with path.open("w", encoding="utf-8") as f:
            json.dump(job.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)

    def _load(self, job_id: str) -> Optional[Job]:
        path = self._job_path(job_id)
        if not path.exists():
            return None
        with path.open("r", encoding="utf-8") as f:
            return Job(**json.load(f))

    # ── ジョブ作成 ────────────────────────────────────────────────────────────

    def create(
        self,
        dataset_id: str,
        job_type: JobType,
        requested_by: str = "ui",
        fetch_url: Optional[str] = None,
    ) -> Job:
        job_id = str(uuid.uuid4())
        log_path = str(self._log_path(job_id))
        job = Job(
            job_id=job_id,
            dataset_id=dataset_id,
            job_type=job_type,
            log_path=log_path,
            requested_by=requested_by,
            fetch_url=fetch_url,
        )
        self._save(job)
        return job

    # ── ジョブ状態更新 ────────────────────────────────────────────────────────

    def update(
        self,
        job: Job,
        *,
        status: Optional[JobStatus] = None,
        step: Optional[JobStep] = None,
        progress_message: Optional[str] = None,
        error_code: Optional[str] = None,
        user_message: Optional[str] = None,
        action_message: Optional[str] = None,
        exit_code: Optional[int] = None,
    ) -> Job:
        if status is not None:
            job.status = status
            if status == JobStatus.running and job.started_at is None:
                job.started_at = datetime.utcnow()
            if status in (JobStatus.success, JobStatus.failed, JobStatus.canceled):
                job.ended_at = datetime.utcnow()
        if step is not None:
            job.step = step
        if progress_message is not None:
            job.progress_message = progress_message
        if error_code is not None:
            job.error_code = error_code
        if user_message is not None:
            job.user_message = user_message
        if action_message is not None:
            job.action_message = action_message
        if exit_code is not None:
            job.exit_code = exit_code
        self._save(job)
        return job

    # ── ログ書き込み ──────────────────────────────────────────────────────────

    def log(self, job: Job, message: str) -> None:
        if not job.log_path:
            return
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{ts}] {message}\n"
        with open(job.log_path, "a", encoding="utf-8") as f:
            f.write(line)

    def log_tail(self, job_id: str) -> List[str]:
        path = self._log_path(job_id)
        if not path.exists():
            return []
        lines = path.read_text(encoding="utf-8").splitlines()
        return lines[-_LOG_TAIL_LINES:]

    # ── 実行中ジョブ管理 ──────────────────────────────────────────────────────

    def has_running_job(self, dataset_id: str) -> bool:
        """dataset に実行中ジョブがあるか確認する（インメモリ + 状態ファイル）。"""
        # インメモリのタスクで確認
        for key, task in list(self._running.items()):
            did = key.split(":")[0]
            if did == dataset_id and not task.done():
                return True
        # ファイルベースでもチェック（再起動後の残留状態）
        for path in self._jobs_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("dataset_id") == dataset_id and data.get("status") in (
                    "queued",
                    "running",
                ):
                    return True
            except Exception:
                pass
        return False

    def get_running_dataset_ids(self) -> List[str]:
        """実行中の dataset_id 一覧を返す。"""
        result = set()
        for path in self._jobs_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") in ("queued", "running"):
                    result.add(data["dataset_id"])
            except Exception:
                pass
        return list(result)

    # ── バックグラウンド実行 ──────────────────────────────────────────────────

    def submit(
        self,
        job: Job,
        coro: Coroutine,
    ) -> None:
        """コルーチンをバックグラウンドタスクとして登録する。"""
        key = f"{job.dataset_id}:{job.job_id}"

        async def _wrapper():
            try:
                await coro
            except Exception as exc:
                logger.exception("Unhandled error in job %s: %s", job.job_id, exc)
                latest = self._load(job.job_id)
                if latest and latest.status == JobStatus.running:
                    self.update(
                        latest,
                        status=JobStatus.failed,
                        step=JobStep.failed,
                        error_code="INTERNAL_ERROR",
                        user_message="予期しないエラーが発生しました。",
                        action_message="ログを確認し、管理者に連絡してください。",
                        exit_code=1,
                    )
            finally:
                self._running.pop(key, None)

        task = asyncio.create_task(_wrapper())
        self._running[key] = task

    # ── 照会 API ──────────────────────────────────────────────────────────────

    def get(self, job_id: str) -> Optional[Job]:
        return self._load(job_id)

    def list_recent(self, dataset_id: Optional[str] = None, limit: int = 20) -> List[Job]:
        jobs = []
        for path in sorted(self._jobs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                with path.open("r", encoding="utf-8") as f:
                    job = Job(**json.load(f))
                if dataset_id and job.dataset_id != dataset_id:
                    continue
                jobs.append(job)
                if len(jobs) >= limit:
                    break
            except Exception as exc:
                logger.warning("Failed to read job file %s: %s", path, exc)
        return jobs

    def cleanup_stale_running(self) -> None:
        """起動時に queued/running のまま残ったジョブを failed にリセットする。"""
        from app.services.dataset_state_service import get_state_service

        ss = get_state_service()
        for path in self._jobs_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") in ("queued", "running"):
                    data["status"] = "failed"
                    data["error_code"] = "INTERNAL_ERROR"
                    data["user_message"] = "サーバ再起動により処理が中断されました。"
                    data["action_message"] = "再度実行してください。"
                    data["ended_at"] = datetime.utcnow().isoformat()
                    with path.open("w", encoding="utf-8") as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)

                    dataset_id = data.get("dataset_id")
                    if dataset_id:
                        state = ss.load(dataset_id)
                        step = data.get("step")
                        if step == "normalize" and state.normalize_status == NormalizeStatus.running:
                            state.normalize_status = NormalizeStatus.failed
                        elif step == "validate" and state.validation_status != ValidationStatus.passed:
                            state.validation_status = ValidationStatus.failed
                        elif step in ("deploy", "backup") and state.deploy_status == DeployStatus.deploying:
                            state.deploy_status = DeployStatus.not_deployed
                        elif step == "osrm_rebuild" and state.osrm_rebuild_status == OsrmRebuildStatus.running:
                            state.osrm_rebuild_status = OsrmRebuildStatus.failed
                        state.updated_at = datetime.utcnow()
                        ss.save(state)
            except Exception as exc:
                logger.warning("Failed to cleanup stale job %s: %s", path, exc)


# シングルトン
_instance: Optional[JobManager] = None


def get_job_manager() -> JobManager:
    global _instance
    if _instance is None:
        _instance = JobManager()
    return _instance

"""
job_manager.py — 非同期ジョブ管理エンジン

ジョブを data_lake/admin/jobs/{job_id}.json に永続化し、
asyncio を使ってバックグラウンドで実行する。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Coroutine, Dict, List, Optional

from app.models.admin_dataset import Job, JobStatus, JobStep, JobType
from app.models.admin_dataset import DeployStatus, NormalizeStatus, OsrmRebuildStatus, ValidationStatus
from app.services.admin_log_service import write_job_log
from app.services.admin_metadata_fs import chmod_quiet
from app.services.operator_audit_log import AuditSinkError, log_operator_internal_inspect

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_ADMIN_JOBS_DIR = _PROJECT_ROOT / "data_lake" / "admin" / "jobs"
_ADMIN_LOGS_DIR = _PROJECT_ROOT / "data_lake" / "admin" / "logs"
_BOOT_STATE_PATH = _PROJECT_ROOT / "data_lake" / "admin" / "boot_state.json"
_LOG_TAIL_LINES = 200


# ── ブート情報収集 ────────────────────────────────────────────────────────────

def _read_hot_reload_config() -> tuple:
    """
    api.reload 値を app.properties から読む。
    job_manager.py は main.py より先に import されるため API_RELOAD を参照できない。

    検索順序:
      1. APP_PROPERTIES_FILE 環境変数（明示指定）
      2. /app/app.properties（Docker コンテナ内の一般的なマウントパス）
      3. _PROJECT_ROOT / "backend" / "app.properties"（ローカル開発）

    Returns:
      (hot_reload_enabled: Optional[bool], actual_config_path: Optional[str])
      読み取り失敗時は (None, None)
    """
    candidates: list = []
    env_path = os.environ.get("APP_PROPERTIES_FILE")
    if env_path:
        candidates.append(Path(env_path))
    candidates.append(Path("/app/app.properties"))
    candidates.append(_PROJECT_ROOT / "backend" / "app.properties")

    for config_path in candidates:
        if not config_path.exists():
            continue
        try:
            for line in config_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                if key.strip() == "api.reload":
                    return val.strip().lower() in ("true", "1", "yes"), str(config_path)
        except Exception:
            continue

    return None, None


def _get_container_id_from_cgroup() -> Optional[str]:
    """
    Docker コンテナ ID を複数の方法で取得する（高速・同期）。

    試行順序:
      1. /proc/self/cgroup (cgroup v1: "12:memory:/docker/<64hex>")
      2. /proc/self/cgroup (cgroup v2: "0::/system.slice/docker-<64hex>.scope")
      3. /etc/hostname (Docker Compose はデフォルトでコンテナ short ID をホスト名にする)
      4. $HOSTNAME 環境変数（同上）

    非 Docker 環境では None を返す。startup 時のみ呼ぶ。
    """
    def _is_container_id(s: str) -> bool:
        s = s.strip()
        return 12 <= len(s) <= 64 and all(c in "0123456789abcdef" for c in s)

    # --- 方法1・2: /proc/self/cgroup ---
    try:
        cgroup = Path("/proc/self/cgroup").read_text(encoding="utf-8")
        for line in cgroup.splitlines():
            parts = line.split("/")
            for part in reversed(parts):
                part = part.strip()
                # cgroup v1: 64文字の hex ID
                if len(part) == 64 and all(c in "0123456789abcdef" for c in part):
                    return part[:12]
                # cgroup v2 systemd: "docker-<64hex>.scope"
                if part.startswith("docker-") and part.endswith(".scope"):
                    cid = part[len("docker-"):-len(".scope")]
                    if _is_container_id(cid):
                        return cid[:12]
    except Exception:
        pass

    # --- 方法3: /etc/hostname ---
    # Docker Compose はデフォルトでコンテナ short ID (12 hex) をホスト名にセットする
    try:
        hostname = Path("/etc/hostname").read_text(encoding="utf-8").strip()
        if len(hostname) == 12 and all(c in "0123456789abcdef" for c in hostname):
            return hostname
    except Exception:
        pass

    # --- 方法4: $HOSTNAME 環境変数 ---
    hostname = os.environ.get("HOSTNAME", "").strip()
    if len(hostname) == 12 and all(c in "0123456789abcdef" for c in hostname):
        return hostname

    return None


def _fetch_docker_inspect(container_id: str) -> dict:
    """
    docker inspect <container_id> を実行して詳細情報を返す。
    取得失敗（CLI 未導入・タイムアウト等）時は空 dict を返す。
    cleanup_stale_running() 実行時のみ呼ぶこと。

    Phase 2-B.3: `container_id`は必ず`_get_container_id_from_cgroup()`が
    /proc/self/cgroup・/etc/hostname・$HOSTNAMEから検出した自プロセスのID
    （呼出元は`_enrich_boot_state_with_docker_inspect()`の1箇所のみ、
    `_BOOT_STATE["container_id"]`経由）であり、HTTP request・job parameter・
    その他の外部入力からこの引数へ値が渡ることはない（`inspect:self`、
    allowlist対象外の内部処理として第5.3節で区別されている）。
    実行結果は`operator_internal_inspect`監査eventとして記録する
    （actor_idは常に固定値"system"、値そのもの・生stdout/stderrは記録しない）。

    返却フィールド（取得できたものだけ含まれる）:
      container_started_at    : コンテナ起動時刻 (ISO 8601)
      container_restart_count : RestartCount (int)
      container_oom_killed    : OOMKilled フラグ (bool)
    """
    audit_result = "failure"
    audit_error_code: Optional[str] = "DOCKER_INSPECT_FAILED"
    try:
        proc = subprocess.run(
            ["docker", "inspect", container_id],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode == 0:
            info = json.loads(proc.stdout)
            if info:
                item = info[0]
                state = item.get("State", {})
                result: dict = {}
                if "StartedAt" in state:
                    result["container_started_at"] = state["StartedAt"]
                if "RestartCount" in item:
                    result["container_restart_count"] = item["RestartCount"]
                if "OOMKilled" in state:
                    result["container_oom_killed"] = state["OOMKilled"]
                audit_result = "success"
                audit_error_code = None
                return result
    except Exception:
        pass
    finally:
        try:
            log_operator_internal_inspect(result=audit_result, error_code=audit_error_code)
        except AuditSinkError:
            # inspect:selfは既存どおり「失敗してもwarningのみでcleanup処理を
            # 継続する」既存挙動（第5.3節）を維持する。監査sink自体の障害で
            # stale-job cleanupという安全側処理を止めない。
            logger.warning("operator_internal_inspect audit sink write failed")
    return {}


def _enrich_boot_state_with_docker_inspect() -> None:
    """
    _BOOT_STATE に docker inspect の結果を補完し boot_state.json を更新する。
    cleanup_stale_running() の先頭で 1 回だけ呼ぶ（冪等 — 既取得なら何もしない）。
    """
    container_id = _BOOT_STATE.get("container_id")
    if not container_id or "container_restart_count" in _BOOT_STATE:
        return  # 非 Docker 環境、または既に取得済み

    inspect_result = _fetch_docker_inspect(container_id)
    if not inspect_result:
        return

    _BOOT_STATE.update(inspect_result)
    try:
        _BOOT_STATE_PATH.write_text(
            json.dumps(_BOOT_STATE, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        chmod_quiet(_BOOT_STATE_PATH)
    except Exception as exc:
        logger.warning("Failed to update boot_state.json with docker inspect: %s", exc)


def _load_or_create_boot_state() -> dict:
    """
    起動時に boot_state.json を読み書きし、現在のブート情報を返す。

    返却フィールド:
      boot_id      : このプロセス起動を一意に識別する UUID
      pid          : 現在の PID
      started_at   : 起動タイムスタンプ (ISO 8601)
      container_id : Docker コンテナ短縮 ID（非 Docker 環境では null）
      prev_boot_id : 直前の boot_id（初回は null）
    """
    # 本functionはmodule import時（プロセス起動時）に無条件で一度だけ実行
    # される。実運用では`data_lake`は常にbind mountされ配下directoryの
    # 作成は問題なく成功するが、`data_lake`自体が存在しない・書込不可な
    # 環境（volumeを持たない隔離image smoke test等）ではmkdir失敗が
    # import chain全体をcrashさせてしまう。boot state自体は起動診断用の
    # 補助情報であり必須ではないため、作成失敗時は以降を空のboot stateで
    # 継続する（既存のwrite失敗時try/exceptと同じ扱い）。
    try:
        _BOOT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("Failed to create boot_state.json directory: %s", exc)
        return {
            "boot_id": str(uuid.uuid4()),
            "pid": os.getpid(),
            "started_at": datetime.utcnow().isoformat(),
            "prev_boot_id": None,
            "container_id": _get_container_id_from_cgroup(),
            "hot_reload_enabled": False,
            "actual_config_path": None,
        }

    prev_boot_id: Optional[str] = None
    if _BOOT_STATE_PATH.exists():
        try:
            prev = json.loads(_BOOT_STATE_PATH.read_text(encoding="utf-8"))
            prev_boot_id = prev.get("boot_id")
        except Exception:
            pass

    hot_reload_enabled, actual_config_path = _read_hot_reload_config()

    current: dict = {
        "boot_id": str(uuid.uuid4()),
        "pid": os.getpid(),
        "started_at": datetime.utcnow().isoformat(),
        "prev_boot_id": prev_boot_id,
        "container_id": _get_container_id_from_cgroup(),
        "hot_reload_enabled": hot_reload_enabled,
        "actual_config_path": actual_config_path,
        # container_started_at / container_restart_count / container_oom_killed は
        # cleanup_stale_running() 実行時に _enrich_boot_state_with_docker_inspect() で補完する
    }
    try:
        _BOOT_STATE_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        chmod_quiet(_BOOT_STATE_PATH)
    except Exception as exc:
        logger.warning("Failed to write boot_state.json: %s", exc)

    return current


# プロセス起動時に一度だけ実行
_BOOT_STATE: dict = _load_or_create_boot_state()


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
        chmod_quiet(path)

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
        actor_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> Job:
        """ジョブを作成する。

        Phase 2-B.3: `actor_id`/`request_id`は、認証済みoperator requestから
        submitされたjobについて、実際にDocker操作を行う時点
        （pipeline_service.py→docker_operation_gateway.execute_operation）まで
        job contextとして伝播させ、HTTP受付とDocker実行結果を対応付ける
        （第6節）。system起因（authenticated request以外）で作成されるjobでは
        Noneのままとなる。既存の永続化job JSON（Phase 2-B.3以前に作成された
        もの）にはこれらのfieldが存在しないが、Pydantic側でOptional・既定値
        Noneとしているため読込は失敗しない（黙示的な"unknown"文字列への
        置換はしない。Noneは「本phase以前のjobであり対応actorを持たない」
        ことを表す明示的な状態として扱う）。
        """
        job_id = str(uuid.uuid4())
        log_path = str(self._log_path(job_id))
        job = Job(
            job_id=job_id,
            dataset_id=dataset_id,
            job_type=job_type,
            log_path=log_path,
            requested_by=requested_by,
            fetch_url=fetch_url,
            boot_id=_BOOT_STATE["boot_id"],
            actor_id=actor_id,
            request_id=request_id,
        )
        self._save(job)
        return job

    def _safe_write_job_log(self, message: str, level: str = "INFO", job_id: Optional[str] = None) -> None:
        try:
            write_job_log(message=message, level=level, job_id=job_id)
        except Exception:
            pass

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
        previous_status = job.status
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
        if status is not None and status != previous_status:
            if status == JobStatus.running:
                self._safe_write_job_log(
                    f"job started type={job.job_type.value} dataset_id={job.dataset_id}",
                    level="INFO",
                    job_id=job.job_id,
                )
            elif status == JobStatus.success:
                self._safe_write_job_log(
                    f"job success type={job.job_type.value} dataset_id={job.dataset_id}",
                    level="INFO",
                    job_id=job.job_id,
                )
            elif status == JobStatus.failed:
                self._safe_write_job_log(
                    f"job failed type={job.job_type.value} dataset_id={job.dataset_id} error_code={job.error_code or 'UNKNOWN'}",
                    level="ERROR",
                    job_id=job.job_id,
                )
            elif status == JobStatus.canceled:
                self._safe_write_job_log(
                    f"job canceled type={job.job_type.value} dataset_id={job.dataset_id}",
                    level="WARNING",
                    job_id=job.job_id,
                )
        return job

    # ── ログ書き込み ──────────────────────────────────────────────────────────

    def log(self, job: Job, message: str) -> None:
        if not job.log_path:
            return
        ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"[{ts}] {message}\n"
        with open(job.log_path, "a", encoding="utf-8") as f:
            f.write(line)
        chmod_quiet(job.log_path)

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
                self._safe_write_job_log(
                    f"job coroutine accepted type={job.job_type.value} dataset_id={job.dataset_id}",
                    level="INFO",
                    job_id=job.job_id,
                )
                await coro
                latest = self._load(job.job_id)
                if latest and latest.status == JobStatus.queued:
                    self._safe_write_job_log(
                        f"job completed without explicit status transition type={job.job_type.value} dataset_id={job.dataset_id}",
                        level="WARNING",
                        job_id=job.job_id,
                    )
            except Exception as exc:
                logger.exception("Unhandled error in job %s: %s", job.job_id, exc)
                self._safe_write_job_log(
                    f"job failed with unhandled exception type={job.job_type.value} dataset_id={job.dataset_id} error={exc}",
                    level="ERROR",
                    job_id=job.job_id,
                )
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

    def _append_log(self, log_path: Optional[str], message: str) -> None:
        """ジョブログファイルに 1 行追記する（ファイルが存在しない場合は作成）。"""
        if not log_path:
            return
        try:
            ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"[{ts}] {message}\n")
            chmod_quiet(log_path)
        except Exception as exc:
            logger.warning("Failed to append to log %s: %s", log_path, exc)

    @staticmethod
    def _diagnose_restart(
        job_boot_id: Optional[str],
        job_started_at: Optional[str] = None,
    ) -> dict:
        """
        ジョブの boot_id と現在の boot_id を比較し、中断原因を推定する。

        引数:
          job_boot_id   : ジョブ JSON に記録された boot_id
          job_started_at: ジョブの started_at (ISO 8601)。diag に含める参考情報。

        返却:
          cause    : "different_boot" | "no_boot_id" | "same_boot_crash"
          possible : ユーザ向けの可能性列挙リスト
          diag     : ログ向け詳細情報 dict
        """
        current = _BOOT_STATE
        now_boot     = current["boot_id"]
        prev_boot    = current.get("prev_boot_id")
        container_id = current.get("container_id")

        hot_reload_enabled = current.get("hot_reload_enabled")
        # hot_reload_possible: reload=true なら data_lake 書き換えで再起動しうる
        hot_reload_possible = bool(hot_reload_enabled) if hot_reload_enabled is not None else None

        diag: dict = {
            "current_boot_id":            now_boot,
            "previous_boot_id":           prev_boot,
            "current_pid":                current.get("pid"),
            "current_started_at":         current.get("started_at"),
            "container_id":               container_id,
            "container_started_at":       current.get("container_started_at"),
            "container_restart_count":    current.get("container_restart_count"),
            "container_oom_killed":       current.get("container_oom_killed"),
            "hot_reload_enabled":         hot_reload_enabled,
            "hot_reload_possible":        hot_reload_possible,
            "actual_config_path":         current.get("actual_config_path"),
            "job_boot_id":                job_boot_id,
            "job_started_at":             job_started_at,
        }

        if job_boot_id is None:
            # 旧フォーマット（boot_id 未記録）の場合
            cause = "no_boot_id"
            detected_by = "missing_boot_id"
            possible = [
                "process_restarted",
                "container_restarted",
                "unknown_external_restart",
            ]
        elif job_boot_id != now_boot:
            # boot_id が違う → 別プロセス起動をまたいでいることが確実
            cause = "different_boot"
            detected_by = "boot_id_mismatch"
            if container_id and current.get("container_restart_count") is not None:
                # docker inspect で RestartCount が取れた → コンテナ再起動が有力
                possible = ["container_restarted", "process_restarted"]
            elif container_id:
                # コンテナ内だが inspect 失敗（CLI 未公開等）
                possible = ["container_restarted", "process_restarted", "unknown_external_restart"]
            else:
                # 非 Docker 環境
                possible = ["process_restarted", "unknown_external_restart"]
            # hot reload が有効なら data_lake 書き換えトリガーの可能性を追加
            if hot_reload_possible:
                possible = ["hot_reload_triggered"] + possible
        else:
            # 同一 boot_id だが running のまま残っている（asyncio タスク例外など）
            cause = "same_boot_crash"
            detected_by = "same_boot_stale_status"
            possible = ["asyncio_task_exception", "process_signal"]

        diag["detected_by"] = detected_by
        return {"cause": cause, "detected_by": detected_by, "possible": possible, "diag": diag}

    def cleanup_stale_running(self) -> None:
        """起動時に queued/running のまま残ったジョブを failed にリセットする。

        処理内容:
          1. boot_id 比較で中断原因を推定し、ジョブログへ診断情報を追記
          2. ジョブ JSON を failed に更新（原因別の user_message）
          3. normalize 中断時: current_normalized_path をクリア
          4. normalize 中断時: *.tmp.geojson を削除
        """
        from app.services.dataset_state_service import get_state_service
        from app.services.dataset_definition_service import get_definition_service

        # stale job 診断に備え docker inspect 情報を補完（初回のみ実行・冪等）
        _enrich_boot_state_with_docker_inspect()

        ss = get_state_service()
        ds = get_definition_service()

        for path in self._jobs_dir.glob("*.json"):
            try:
                with path.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                if data.get("status") not in ("queued", "running"):
                    continue

                step     = data.get("step") or "unknown"
                log_path = data.get("log_path")

                # ── 原因診断 ─────────────────────────────────────────────────
                result   = self._diagnose_restart(
                    data.get("boot_id"),
                    job_started_at=data.get("started_at"),
                )
                cause       = result["cause"]
                detected_by = result["detected_by"]
                possible    = result["possible"]
                diag        = result["diag"]

                # cause 別の user_message
                if cause == "different_boot":
                    user_msg = (
                        f"backend プロセスが再起動・再生成されたため、ジョブが中断されました"
                        f"（ステップ: {step}）。"
                        "原因はアプリ外（Docker restart / host 再起動など）の可能性があります。"
                        "出力は未確定です。"
                    )
                elif cause == "same_boot_crash":
                    user_msg = (
                        f"同一プロセス内でジョブが異常終了しました（ステップ: {step}）。"
                        "asyncio タスク例外またはシグナルによる中断の可能性があります。"
                    )
                else:  # no_boot_id
                    user_msg = (
                        f"プロセス再起動によりジョブが中断されました（ステップ: {step}）。"
                        "原因の詳細は特定できません（旧フォーマットのジョブ）。"
                    )

                # ── ジョブ JSON 更新 ──────────────────────────────────────────
                data["status"]         = "failed"
                data["error_code"]     = "INTERNAL_ERROR"
                data["user_message"]   = user_msg
                data["action_message"] = (
                    "再度実行してください。前回の出力は無効化されています。"
                    f" 推定原因: {', '.join(possible)}"
                )
                data["ended_at"] = datetime.utcnow().isoformat()
                with path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                chmod_quiet(path)

                # ── ジョブログへ診断情報を追記 ────────────────────────────────
                self._append_log(log_path, (
                    f"[SYSTEM] プロセス起動変化を検出。ジョブを failed に移行します。"
                    f" cause={cause}  detected_by={detected_by}  possible={possible}"
                ))
                for k, v in diag.items():
                    self._append_log(log_path, f"[SYSTEM]   {k}: {v}")

                # ── データセット state の整合性回復 ───────────────────────────
                dataset_id = data.get("dataset_id")
                if not dataset_id:
                    continue

                state = ss.load(dataset_id)

                if step == "normalize" and state.normalize_status == NormalizeStatus.running:
                    state.normalize_status = NormalizeStatus.failed

                    if state.current_normalized_path:
                        self._append_log(
                            log_path,
                            f"[SYSTEM] current_normalized_path をクリア"
                            f" (中断前参照: {state.current_normalized_path})",
                        )
                        state.current_normalized_path = None

                    defn = ds.get(dataset_id)
                    if defn and defn.normalized_storage_path:
                        norm_dir = (_PROJECT_ROOT / defn.normalized_storage_path).resolve()
                        for tmp_file in norm_dir.glob("*.tmp.geojson"):
                            try:
                                tmp_file.unlink()
                                self._append_log(
                                    log_path,
                                    f"[SYSTEM] 中断 tmp ファイルを削除: {tmp_file.name}",
                                )
                                logger.info("Removed stale tmp file: %s", tmp_file)
                            except OSError as exc:
                                logger.warning("Failed to remove tmp file %s: %s", tmp_file, exc)

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

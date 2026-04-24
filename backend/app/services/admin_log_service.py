"""
admin_log_service.py — 管理画面 Logs タブ用のログ読み取りサービス
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from app.services.config_definition_service import get_config_definition_service
from app.services.config_state_service import get_config_state_service

logger = logging.getLogger(__name__)
_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
_DEFAULT_LOG_LEVEL = "INFO"
_DEFAULT_RETENTION_DAYS = 7
_DEFAULT_MAX_FILE_SIZE_MB = 100
_DEFAULT_CLEANUP_ENABLED = True
_JST = timezone(timedelta(hours=9), name="JST")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_now_iso() -> str:
    return datetime.now(_JST).isoformat(timespec="seconds")


def get_current_log_level() -> str:
    try:
        defn = get_config_definition_service().get("logging.level")
        if defn is None:
            return _DEFAULT_LOG_LEVEL
        current = str(get_config_state_service().resolve_value(defn)).upper()
        if current in _LOG_LEVELS:
            return current
    except Exception:
        pass
    return _DEFAULT_LOG_LEVEL


def should_log(level: str) -> bool:
    normalized = str(level).upper()
    if normalized not in _LOG_LEVELS:
        normalized = _DEFAULT_LOG_LEVEL
    current = get_current_log_level()
    try:
        return _LOG_LEVELS.index(normalized) >= _LOG_LEVELS.index(current)
    except ValueError:
        return normalized != "DEBUG"


def get_config_value(key: str, default: Any) -> Any:
    try:
        defn = get_config_definition_service().get(key)
        if defn is None:
            return default
        return get_config_state_service().resolve_value(defn)
    except Exception:
        return default


class AdminLogService:
    """固定ログソースの末尾取得とファイル追従を提供する。"""

    def __init__(
        self,
        source_paths: Optional[Dict[str, Path]] = None,
        heartbeat_interval_sec: float = 10.0,
        poll_interval_sec: float = 1.0,
    ) -> None:
        project_root = Path(__file__).resolve().parents[3]
        logs_dir = project_root / "data_runtime" / "logs"
        self._source_paths = source_paths or {
            "app": logs_dir / "app.log",
            "jobs": logs_dir / "jobs.log",
        }
        self._labels = {
            "app": "Application",
            "jobs": "Jobs",
        }
        self._heartbeat_interval_sec = heartbeat_interval_sec
        self._poll_interval_sec = poll_interval_sec
        for path in self._source_paths.values():
            path.parent.mkdir(parents=True, exist_ok=True)

    def list_sources(self) -> List[dict]:
        return [
            {"key": key, "label": self._labels.get(key, key.title())}
            for key in self._source_paths.keys()
        ]

    def status(self) -> dict:
        sources = []
        for key in self._source_paths.keys():
            path = self.validate_source(key)
            size_bytes = path.stat().st_size if path.exists() else 0
            sources.append({
                "key": key,
                "label": self._labels.get(key, key.title()),
                "size_bytes": size_bytes,
            })
        return {"sources": sources}

    def validate_source(self, source: str) -> Path:
        if source not in self._source_paths:
            raise KeyError(source)
        return self._source_paths[source]

    def tail_lines(self, source: str, limit: int = 200) -> List[str]:
        path = self.validate_source(source)
        if not path.exists():
            return []

        lines: deque[str] = deque(maxlen=max(1, limit))
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                lines.append(line.rstrip("\n"))
        return list(lines)

    async def stream_lines(self, source: str) -> AsyncIterator[str]:
        path = self.validate_source(source)
        position = path.stat().st_size if path.exists() else 0
        heartbeat_deadline = asyncio.get_running_loop().time() + self._heartbeat_interval_sec

        while True:
            try:
                if path.exists():
                    current_size = path.stat().st_size
                    if current_size < position:
                        position = 0

                    if current_size > position:
                        with path.open("r", encoding="utf-8", errors="replace") as f:
                            f.seek(position)
                            for raw_line in f:
                                line = raw_line.rstrip("\n")
                                payload = {"line": line, "ts": _utc_now_iso()}
                                yield self._format_sse("log", payload)
                            position = f.tell()

                now = asyncio.get_running_loop().time()
                if now >= heartbeat_deadline:
                    yield self._format_sse("heartbeat", {})
                    heartbeat_deadline = now + self._heartbeat_interval_sec

                await asyncio.sleep(self._poll_interval_sec)
            except asyncio.CancelledError:
                raise

    def _format_sse(self, event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    def write_app_log(self, message: str, level: str = "INFO") -> None:
        self._write_line("app", f"{_local_now_iso()} {level.upper()} app {message}")

    def write_job_log(
        self,
        message: str,
        level: str = "INFO",
        job_id: Optional[str] = None,
    ) -> None:
        suffix = f" job_id={job_id}" if job_id else ""
        self._write_line("jobs", f"{_local_now_iso()} {level.upper()} job{suffix} {message}")

    def _write_line(self, source: str, line: str) -> None:
        path = self.validate_source(source)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"{line}\n")

    def cleanup_logs(self) -> dict:
        cleanup_enabled = bool(get_config_value("logging.cleanup_enabled", _DEFAULT_CLEANUP_ENABLED))
        retention_days = int(get_config_value("logging.retention_days", _DEFAULT_RETENTION_DAYS))
        max_file_size_bytes = int(get_config_value("logging.max_file_size_mb", _DEFAULT_MAX_FILE_SIZE_MB)) * 1024 * 1024
        result = {
            "cleanup_enabled": cleanup_enabled,
            "retention_days": retention_days,
            "max_file_size_bytes": max_file_size_bytes,
            "sources": [],
        }
        if not cleanup_enabled:
            return result

        cutoff = datetime.now(_JST) - timedelta(days=retention_days)
        for key in self._source_paths.keys():
            source_result = {
                "key": key,
                "truncated": False,
                "deleted_files": [],
                "size_bytes_before": 0,
                "size_bytes_after": 0,
            }
            path = self.validate_source(key)
            try:
                if path.exists():
                    source_result["size_bytes_before"] = path.stat().st_size
                    if path.stat().st_size > max_file_size_bytes:
                        with path.open("w", encoding="utf-8"):
                            pass
                        source_result["truncated"] = True
                deleted_files = self._delete_old_files(path, cutoff)
                source_result["deleted_files"] = deleted_files
                source_result["size_bytes_after"] = path.stat().st_size if path.exists() else 0
            except Exception:
                pass
            result["sources"].append(source_result)

        try:
            write_app_log(
                "log cleanup executed "
                f"retention_days={retention_days} max_file_size_bytes={max_file_size_bytes}",
                level="INFO",
            )
        except Exception:
            pass
        return result

    def _delete_old_files(self, base_path: Path, cutoff: datetime) -> List[str]:
        deleted: List[str] = []
        parent = base_path.parent
        prefix = base_path.name + "."
        if not parent.exists():
            return deleted
        for candidate in parent.iterdir():
            if not candidate.is_file():
                continue
            if not candidate.name.startswith(prefix):
                continue
            try:
                modified_at = datetime.fromtimestamp(candidate.stat().st_mtime, tz=_JST)
                if modified_at < cutoff:
                    candidate.unlink(missing_ok=True)
                    deleted.append(candidate.name)
            except Exception:
                continue
        return deleted


_admin_log_service: Optional[AdminLogService] = None


def get_admin_log_service() -> AdminLogService:
    global _admin_log_service
    if _admin_log_service is None:
        _admin_log_service = AdminLogService()
    return _admin_log_service


def write_app_log(message: str, level: str = "INFO") -> None:
    if not should_log(level):
        return
    try:
        getattr(logger, level.lower(), logger.info)("app_log %s", message)
    except Exception:
        pass
    get_admin_log_service().write_app_log(message=message, level=level)


def write_job_log(message: str, level: str = "INFO", job_id: Optional[str] = None) -> None:
    if not should_log(level):
        return
    try:
        getattr(logger, level.lower(), logger.info)("job_log job_id=%s %s", job_id, message)
    except Exception:
        pass
    get_admin_log_service().write_job_log(message=message, level=level, job_id=job_id)

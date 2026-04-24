"""
admin_log_service.py — 管理画面 Logs タブ用のログ読み取りサービス
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from app.services.config_definition_service import get_config_definition_service
from app.services.config_state_service import get_config_state_service

logger = logging.getLogger(__name__)
_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR"]
_DEFAULT_LOG_LEVEL = "INFO"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local_now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


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

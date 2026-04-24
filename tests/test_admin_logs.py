import asyncio
import json
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import admin as admin_api
from app.services import admin_log_service
from app.services.admin_log_service import AdminLogService


def _service(tmp_path: Path) -> AdminLogService:
    return AdminLogService(
        source_paths={
            "app": tmp_path / "app.log",
            "jobs": tmp_path / "jobs.log",
        },
        heartbeat_interval_sec=60.0,
        poll_interval_sec=0.01,
    )


def test_tail_lines_returns_latest_entries(tmp_path):
    service = _service(tmp_path)
    app_log = tmp_path / "app.log"
    app_log.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")

    assert service.tail_lines("app", limit=2) == ["line-2", "line-3"]


def test_tail_lines_returns_empty_for_missing_file(tmp_path):
    service = _service(tmp_path)

    assert service.tail_lines("app", limit=10) == []


def test_write_app_log_and_write_job_log_append_lines(tmp_path):
    service = _service(tmp_path)
    original_service = admin_log_service._admin_log_service
    admin_log_service._admin_log_service = service

    try:
        admin_log_service.write_app_log("backend startup")
        admin_log_service.write_job_log("job started type=deploy dataset_id=TOKYO-001", job_id="job-123")
    finally:
        admin_log_service._admin_log_service = original_service

    app_lines = (tmp_path / "app.log").read_text(encoding="utf-8").splitlines()
    job_lines = (tmp_path / "jobs.log").read_text(encoding="utf-8").splitlines()

    assert len(app_lines) == 1
    assert "INFO app backend startup" in app_lines[0]

    assert len(job_lines) == 1
    assert "INFO job job_id=job-123 job started type=deploy dataset_id=TOKYO-001" in job_lines[0]


def test_stream_lines_emits_appended_line(tmp_path):
    service = _service(tmp_path)
    app_log = tmp_path / "app.log"
    app_log.write_text("seed\n", encoding="utf-8")

    async def _run():
        stream = service.stream_lines("app")
        task = asyncio.create_task(anext(stream))
        await asyncio.sleep(0.05)
        with app_log.open("a", encoding="utf-8") as handle:
            handle.write("next-line\n")
        event = await asyncio.wait_for(task, timeout=1.0)
        await stream.aclose()
        return event

    event = asyncio.run(_run())
    assert "event: log" in event
    payload = json.loads(event.split("data: ", 1)[1].strip())
    assert payload["line"] == "next-line"
    assert payload["ts"]


def test_logs_api_returns_sources_and_rejects_invalid_source(tmp_path):
    service = _service(tmp_path)
    (tmp_path / "jobs.log").write_text("job-line\n", encoding="utf-8")

    original_service = admin_api._log_service
    admin_api._log_service = service

    try:
        sources = asyncio.run(admin_api.list_log_sources())
        assert sources == [
            {"key": "app", "label": "Application"},
            {"key": "jobs", "label": "Jobs"},
        ]

        logs = asyncio.run(admin_api.get_logs(source="jobs", limit=10))
        assert logs == {"lines": ["job-line"]}

        with pytest.raises(HTTPException) as exc:
            asyncio.run(admin_api.get_logs(source="invalid", limit=10))
        assert exc.value.status_code == 400
        assert exc.value.detail == "invalid source: invalid"
    finally:
        admin_api._log_service = original_service

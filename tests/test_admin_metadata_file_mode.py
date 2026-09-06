"""
test_admin_metadata_file_mode.py — writer側atomic create/replace時のmode契約テスト

Residual Finding Remediation 03 (DATA-LAKE-ADMIN-WRITER-CONTRACT) 第11/12節:
directory ownershipを是正しても、各writerがumask依存の0644等で新規fileを
作り続ければcontractが再び崩れる。DatasetStateService.save()/append_history()、
ActiveMappingService._save()、operator_audit_log._write()が、書込直後に
明示的へ chmod_quiet() でtarget mode（0640）を適用することを確認する。
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.admin_metadata_fs import ADMIN_METADATA_FILE_MODE  # noqa: E402


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_dataset_state_save_applies_target_mode(tmp_path):
    from app.services.dataset_state_service import DatasetStateService
    from app.models.admin_dataset import DatasetState

    service = DatasetStateService(state_dir=tmp_path / "state", history_dir=tmp_path / "history")
    service.save(DatasetState(dataset_id="TEST-001"))

    path = tmp_path / "state" / "TEST-001.json"
    assert path.exists()
    assert _mode(path) == ADMIN_METADATA_FILE_MODE


def test_dataset_state_append_history_applies_target_mode(tmp_path):
    from app.services.dataset_state_service import DatasetStateService
    from app.models.admin_dataset import DatasetHistory, OperationType

    service = DatasetStateService(state_dir=tmp_path / "state", history_dir=tmp_path / "history")
    service.append_history(DatasetHistory(
        history_id="hist-1",
        dataset_id="TEST-001",
        operation_type=OperationType.deploy,
    ))

    path = tmp_path / "history" / "TEST-001.jsonl"
    assert path.exists()
    assert _mode(path) == ADMIN_METADATA_FILE_MODE


def test_active_mapping_save_applies_target_mode(tmp_path):
    from app.services.active_mapping_service import ActiveMappingService

    mappings_path = tmp_path / "active_mappings.json"
    service = ActiveMappingService(mappings_path=mappings_path)
    service.set_active("storm_surge", "tokyo", "TOKYO-SURGE-001")

    assert mappings_path.exists()
    assert _mode(mappings_path) == ADMIN_METADATA_FILE_MODE


def test_operator_audit_log_write_applies_target_mode(tmp_path):
    import app.services.operator_audit_log as audit_log

    audit_path = tmp_path / "logs" / "operator_audit.log"
    original_path = audit_log.AUDIT_LOG_PATH
    audit_log.AUDIT_LOG_PATH = audit_path
    try:
        audit_log.log_operator_auth(
            request_id="req-1", actor_id="test-actor", result="success", reason_code="OK",
        )
    finally:
        audit_log.AUDIT_LOG_PATH = original_path

    assert audit_path.exists()
    assert _mode(audit_path) == ADMIN_METADATA_FILE_MODE


def test_job_manager_save_applies_target_mode(tmp_path):
    from app.services.job_manager import JobManager
    from app.models.admin_dataset import JobType

    jm = JobManager(jobs_dir=tmp_path / "jobs", logs_dir=tmp_path / "logs")
    job = jm.create(job_type=JobType.deploy, dataset_id="TEST-001")

    job_path = tmp_path / "jobs" / f"{job.job_id}.json"
    assert job_path.exists()
    assert _mode(job_path) == ADMIN_METADATA_FILE_MODE


def test_job_manager_log_applies_target_mode(tmp_path):
    from app.services.job_manager import JobManager
    from app.models.admin_dataset import JobType

    jm = JobManager(jobs_dir=tmp_path / "jobs", logs_dir=tmp_path / "logs")
    job = jm.create(job_type=JobType.deploy, dataset_id="TEST-001")
    jm.log(job, "test message")

    assert Path(job.log_path).exists()
    assert _mode(Path(job.log_path)) == ADMIN_METADATA_FILE_MODE

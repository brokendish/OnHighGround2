"""
test_shelter_backend_mirror_ownership.py — Residual Finding Remediation 05 Phase B2

pipeline_service.run_deploy()（copy_file deploy_modeの汎用handler、
shelter系datasetの正規writer）が、data_runtime/current/backend/shelters
と同じowner/group/mode契約（operator_uid:leases_gid, dir 0750 / file 0640）
を、既存destination上書き・backup作成時にも明示的に適用することを確認する。

対象はshelter系dataset（layer_type in shelter/evacuation_shelter/
emergency_shelter）のみに限定されており、OSM/road/tide等の他copy_file
datasetの挙動を変更しないことも確認する（scope外への影響がないこと）。

実際のchown()はroot権限を要するため、os.chownをmockする。
"""
from __future__ import annotations

import asyncio
import os
import stat
import sys
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.runtime_publish import VERSION_DIR_MODE, VERSION_FILE_MODE  # noqa: E402


def _make_defn(**overrides):
    from app.models.admin_dataset import DatasetDefinition

    base = dict(
        dataset_id="TEST-SHELTER-001",
        region="tokyo",
        category="shelter",
        display_name="test",
        description="test",
        hint_text="test",
        impact_scope="test",
        accepted_input_modes=[],
        accepted_extensions=[],
        max_browser_upload_mb=0,
        requires_normalize=False,
        requires_validation=True,
        requires_deploy=True,
        requires_osrm_rebuild=False,
        raw_storage_path="data_lake/raw/tokyo/shelter",
        validated_storage_path="data_lake/validated/tokyo/shelter",
        runtime_path="data_runtime/backend/shelters",
        deploy_mode="copy_file",
        layer_type="evacuation_shelter",
    )
    base.update(overrides)
    return DatasetDefinition(**base)


def _run_deploy(tmp_path, defn, validated_content: bytes, existing_dest: bytes | None = None):
    from app.services.pipeline_service import run_deploy
    from app.services.dataset_state_service import DatasetStateService
    from app.models.admin_dataset import DatasetState

    src = tmp_path / "validated" / "tokyo-shelter-001.geojson"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(validated_content)

    runtime_dir = tmp_path / defn.runtime_path
    if existing_dest is not None:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        (runtime_dir / src.name).write_bytes(existing_dest)

    state = DatasetState(dataset_id=defn.dataset_id, current_validated_path=str(src))
    ss = DatasetStateService(state_dir=tmp_path / "state", history_dir=tmp_path / "history")
    job = Mock(job_id="test-job-1", actor_id=None, request_id=None)
    jm = Mock()

    with patch("app.services.pipeline_service._PROJECT_ROOT", tmp_path):
        asyncio.run(run_deploy(job, defn, state, jm, ss))

    dest = runtime_dir / src.name
    return runtime_dir, dest


# ── C. 新規file → 10002:20001 0640 / A相当: directory新規作成時のcontract ────

def test_new_shelter_deploy_creates_dir_and_file_with_target_contract(tmp_path):
    defn = _make_defn()

    with patch("os.chown") as mock_chown:
        runtime_dir, dest = _run_deploy(tmp_path, defn, b'{"type": "FeatureCollection", "features": [1]}')

    assert dest.exists()
    assert dest.read_bytes() == b'{"type": "FeatureCollection", "features": [1]}'
    assert stat.S_IMODE(dest.stat().st_mode) == VERSION_FILE_MODE
    assert stat.S_IMODE(runtime_dir.stat().st_mode) == VERSION_DIR_MODE

    calls = {str(c.args[0]): c.args[1:] for c in mock_chown.call_args_list}
    assert calls[str(dest)] == (-1, 20001)
    assert calls[str(runtime_dir)] == (-1, 20001)


# ── D. 既存destination file → overwrite成功 → metadata contract維持 ──────────

def test_existing_destination_overwrite_succeeds_with_target_contract(tmp_path):
    defn = _make_defn()

    with patch("os.chown") as mock_chown:
        runtime_dir, dest = _run_deploy(
            tmp_path, defn,
            b'{"version": "new"}',
            existing_dest=b'{"version": "old"}',
        )

    assert dest.read_bytes() == b'{"version": "new"}'
    assert stat.S_IMODE(dest.stat().st_mode) == VERSION_FILE_MODE

    # backupはactiveと異なりleases groupへ公開しない
    # （OWNER Section 25: operator自身のprimary group、public read対象外）
    backup = runtime_dir / "tokyo-shelter-001.backup.geojson"
    assert backup.exists()
    assert backup.read_bytes() == b'{"version": "old"}'
    assert stat.S_IMODE(backup.stat().st_mode) == VERSION_FILE_MODE

    calls = {str(c.args[0]): c.args[1:] for c in mock_chown.call_args_list}
    assert calls[str(dest)] == (-1, 20001)
    backup_gid = calls[str(backup)][1]
    assert backup_gid != 20001, "backupはleases_gidへ公開してはいけない"
    assert backup_gid == os.getgid(), "backupはoperator自身のprimary groupのままであるべき"


# ── E. 2回目deploy → idempotent ───────────────────────────────────────────────

def test_second_deploy_is_idempotent(tmp_path):
    defn = _make_defn()

    with patch("os.chown") as mock_chown:
        runtime_dir1, dest1 = _run_deploy(tmp_path, defn, b'{"v": 1}')
        runtime_dir2, dest2 = _run_deploy(tmp_path, defn, b'{"v": 2}', existing_dest=dest1.read_bytes())

    assert dest2.read_bytes() == b'{"v": 2}'
    assert stat.S_IMODE(dest2.stat().st_mode) == VERSION_FILE_MODE
    assert stat.S_IMODE(runtime_dir2.stat().st_mode) == VERSION_DIR_MODE


# ── G. operator write（既に別testでshutil.copy2成功を確認済み、ここではcontract側） ─

def test_kanagawa_nested_runtime_path_gets_contract(tmp_path):
    """shelters/kanagawaのようなnested runtime_pathでも同じcontractが適用される。"""
    defn = _make_defn(
        dataset_id="TEST-SHELTER-KANAGAWA-001",
        region="kanagawa",
        runtime_path="data_runtime/backend/shelters/kanagawa",
        layer_type="emergency_shelter",
    )

    with patch("os.chown") as mock_chown:
        runtime_dir, dest = _run_deploy(tmp_path, defn, b'{"region": "kanagawa"}')

    assert stat.S_IMODE(runtime_dir.stat().st_mode) == VERSION_DIR_MODE
    assert stat.S_IMODE(dest.stat().st_mode) == VERSION_FILE_MODE


# ── H. scope外dataset（非shelter）には影響しないこと ──────────────────────────

def test_non_shelter_dataset_is_not_affected_by_ownership_fix(tmp_path):
    """OSM/road/tide等、shelter以外のcopy_fileモードdatasetには
    chmod/chown処理を一切適用しない（scope外への影響防止）。"""
    defn = _make_defn(
        dataset_id="TEST-TIDE-001",
        category="tide",
        runtime_path="data_runtime/backend/tide/jma",
        layer_type=None,
    )

    with patch("os.chown") as mock_chown:
        runtime_dir, dest = _run_deploy(tmp_path, defn, b'{"not": "a shelter"}')

    assert dest.exists()
    assert dest.read_bytes() == b'{"not": "a shelter"}'
    # shelter専用ownership処理が一切呼ばれていないこと
    assert mock_chown.call_count == 0


# ── C/D. public reader contract（論理検証） ────────────────────────────────────

def test_active_file_mode_grants_group_read_backup_does_not_leak_to_leases() -> None:
    """VERSION_FILE_MODE(0640)はgroup読み取りbitを持つ。activeとbackupの
    違いはgid（leases vs operator primary）であり、mode自体は同じ0640。
    otherへは一切publicを含め権限を与えない契約であることを固定する。
    実際のmulti-UID越しのfilesystem挙動はVPS runtime validationで確認する。
    """
    assert VERSION_FILE_MODE & 0o040, "groupにread権限が無ければpublicはactive fileをread不可"
    assert not (VERSION_FILE_MODE & 0o004), "otherにread権限を与えてはいけない"
    assert not (VERSION_FILE_MODE & 0o020), "groupへwrite権限を与えてはいけない（public writerにしない）"
    assert VERSION_DIR_MODE & 0o050 == 0o050, "groupにtraverse+read権限が無ければpublicはdirectory到達不可"
    assert not (VERSION_DIR_MODE & 0o007), "otherに一切の権限を与えてはいけない"

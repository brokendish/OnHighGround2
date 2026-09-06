"""
test_init_data_lake_admin.py — scripts/publish/init_data_lake_admin.py テスト

Residual Finding Remediation 03 (DATA-LAKE-ADMIN-WRITER-CONTRACT):
data_lake/admin配下（state/jobs/history/logs、boot_state.json、
active_mappings.json）をbackend-operator（UID 10002）writer契約へ是正する
one-shot initializerの検証。

実際のchown()はroot権限を要するため、テストではos.chownをmockし
「正しいuid/gidが正しいpathに対して要求されたか」を検証する。
mode（chmod）はrootを要さないため、実際にtmp_path上でchmodを実行し
実際のstat結果で検証する（fake stat構造体は使わない）。
"""
from __future__ import annotations

import importlib.util
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "publish" / "init_data_lake_admin.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("init_data_lake_admin", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()

_OPERATOR_UID, _OPERATOR_GID, _LEASES_GID = 10002, 10002, 20001


def _run_main(admin_root: Path):
    argv = [
        "init_data_lake_admin.py",
        str(admin_root),
        "--operator-uid", str(_OPERATOR_UID),
        "--operator-gid", str(_OPERATOR_GID),
        "--leases-gid", str(_LEASES_GID),
    ]
    with patch.object(sys, "argv", argv), \
         patch("os.geteuid", return_value=0):
        return mod.main()


# ── A. fresh install ──────────────────────────────────────────────────────────

def test_fresh_install_creates_all_directories_with_expected_mode(tmp_path):
    admin_root = tmp_path / "admin"

    with patch("os.chown") as mock_chown:
        rc = _run_main(admin_root)

    assert rc == 0
    for sub in ("", "state", "jobs", "history", "logs"):
        d = admin_root / sub if sub else admin_root
        assert d.is_dir()
        assert stat.S_IMODE(d.stat().st_mode) == mod.DIR_MODE

    # chown引数の正しさ（root/state/active_mappingsはleases_gid、他はoperator_gid）
    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(admin_root)] == (_OPERATOR_UID, _LEASES_GID)
    assert calls[str(admin_root / "state")] == (_OPERATOR_UID, _LEASES_GID)
    assert calls[str(admin_root / "jobs")] == (_OPERATOR_UID, _OPERATOR_GID)
    assert calls[str(admin_root / "history")] == (_OPERATOR_UID, _OPERATOR_GID)
    assert calls[str(admin_root / "logs")] == (_OPERATOR_UID, _OPERATOR_GID)


def test_fresh_install_does_not_create_missing_files(tmp_path):
    """boot_state.json/active_mappings.jsonはfresh installでは存在しないため作らない
    （各serviceが初回書込時に自然生成する）。"""
    admin_root = tmp_path / "admin"
    with patch("os.chown"):
        _run_main(admin_root)

    assert not (admin_root / "boot_state.json").exists()
    assert not (admin_root / "active_mappings.json").exists()


# ── B. idempotency ────────────────────────────────────────────────────────────

def test_idempotent_second_run_no_content_change(tmp_path):
    admin_root = tmp_path / "admin"
    (admin_root / "state").mkdir(parents=True)
    existing = admin_root / "state" / "TOKYO-SURGE-001.json"
    existing.write_text('{"dataset_id": "TOKYO-SURGE-001"}', encoding="utf-8")
    original_content = existing.read_text(encoding="utf-8")

    with patch("os.chown"):
        rc1 = _run_main(admin_root)
        rc2 = _run_main(admin_root)

    assert rc1 == 0 and rc2 == 0
    assert existing.read_text(encoding="utf-8") == original_content
    # ディレクトリ数が増えていない（duplicate生成なし）
    assert sorted(p.name for p in admin_root.iterdir()) == ["history", "jobs", "logs", "state"]
    assert stat.S_IMODE((admin_root / "state").stat().st_mode) == mod.DIR_MODE
    assert stat.S_IMODE(existing.stat().st_mode) == mod.FILE_MODE


# ── C. legacy directory migration（既存non-empty directory是正） ─────────────

def test_legacy_nonempty_directory_is_claimed_non_recursively(tmp_path):
    admin_root = tmp_path / "admin"
    jobs_dir = admin_root / "jobs"
    jobs_dir.mkdir(parents=True)
    jobs_dir.chmod(0o755)  # legacy mode相当
    job_file = jobs_dir / "abc123.json"
    job_file.write_text('{"job_id": "abc123"}', encoding="utf-8")

    with patch("os.chown") as mock_chown:
        rc = _run_main(admin_root)

    assert rc == 0
    assert stat.S_IMODE(jobs_dir.stat().st_mode) == mod.DIR_MODE
    assert stat.S_IMODE(job_file.stat().st_mode) == mod.FILE_MODE
    assert job_file.read_text(encoding="utf-8") == '{"job_id": "abc123"}'
    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(job_file)] == (_OPERATOR_UID, _OPERATOR_GID)


# ── D. existing root-owned runtime file（content保持、target ownership付与） ──

def test_existing_state_files_content_preserved_and_target_ownership_requested(tmp_path):
    admin_root = tmp_path / "admin"
    state_dir = admin_root / "state"
    state_dir.mkdir(parents=True)
    files = {
        "TOKYO-PSEUDO-INLAND-FLOOD-001.json": '{"dataset_id": "TOKYO-PSEUDO-INLAND-FLOOD-001"}',
        "TOKYO-LOWLAND-POOR-DRAINAGE-001.json": '{"dataset_id": "TOKYO-LOWLAND-POOR-DRAINAGE-001"}',
    }
    for name, content in files.items():
        (state_dir / name).write_text(content, encoding="utf-8")

    with patch("os.chown") as mock_chown:
        rc = _run_main(admin_root)

    assert rc == 0
    for name, content in files.items():
        f = state_dir / name
        assert f.read_text(encoding="utf-8") == content
        assert stat.S_IMODE(f.stat().st_mode) == mod.FILE_MODE
    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    for name in files:
        assert calls[str(state_dir / name)] == (_OPERATOR_UID, _LEASES_GID)


# ── E. writer test（新規file/directoryがoperator-writable contractになる） ────

def test_new_state_file_dir_is_operator_group_leases(tmp_path):
    admin_root = tmp_path / "admin"
    with patch("os.chown") as mock_chown:
        _run_main(admin_root)

    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(admin_root / "state")] == (_OPERATOR_UID, _LEASES_GID)
    assert stat.S_IMODE((admin_root / "state").stat().st_mode) == 0o2750


# ── F. public security（publicはwriterにしない、必要なpathだけread contract） ──

def test_jobs_history_logs_do_not_get_leases_group(tmp_path):
    """public非公開のjobs/history/logsにleases_gidを付与しないこと。"""
    admin_root = tmp_path / "admin"
    with patch("os.chown") as mock_chown:
        _run_main(admin_root)

    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    for sub in ("jobs", "history", "logs"):
        gid = calls[str(admin_root / sub)][1]
        assert gid == _OPERATOR_GID
        assert gid != _LEASES_GID


# ── G. operator-only metadata（不要にleases_gidを広げない） ───────────────────

def test_boot_state_json_is_operator_only_not_leases(tmp_path):
    admin_root = tmp_path / "admin"
    admin_root.mkdir(parents=True)
    boot_state = admin_root / "boot_state.json"
    boot_state.write_text('{"boot_id": "x"}', encoding="utf-8")

    with patch("os.chown") as mock_chown:
        _run_main(admin_root)

    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(boot_state)] == (_OPERATOR_UID, _OPERATOR_GID)


def test_active_mappings_json_gets_leases_gid_for_public_read(tmp_path):
    admin_root = tmp_path / "admin"
    admin_root.mkdir(parents=True)
    active_mappings = admin_root / "active_mappings.json"
    active_mappings.write_text('{"storm_surge:tokyo": "TOKYO-SURGE-001"}', encoding="utf-8")

    with patch("os.chown") as mock_chown:
        _run_main(admin_root)

    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(active_mappings)] == (_OPERATOR_UID, _LEASES_GID)


# ── root権限チェック ──────────────────────────────────────────────────────────

def test_requires_root(tmp_path):
    admin_root = tmp_path / "admin"
    argv = [
        "init_data_lake_admin.py",
        str(admin_root),
        "--operator-uid", str(_OPERATOR_UID),
        "--operator-gid", str(_OPERATOR_GID),
        "--leases-gid", str(_LEASES_GID),
    ]
    with patch.object(sys, "argv", argv), \
         patch("os.geteuid", return_value=1000):
        try:
            mod.main()
            assert False, "root以外ではSystemExitするはず"
        except SystemExit as exc:
            assert exc.code == 1
    assert not admin_root.exists(), "root権限チェック前にdirectoryを作ってはいけない"


# ── dotfile/拡張子フィルタ ─────────────────────────────────────────────────────

def test_dotfiles_and_unmatched_extensions_are_not_touched(tmp_path):
    admin_root = tmp_path / "admin"
    state_dir = admin_root / "state"
    state_dir.mkdir(parents=True)
    gitkeep = state_dir / ".gitkeep"
    gitkeep.write_text("", encoding="utf-8")
    readme = state_dir / "README.md"
    readme.write_text("not a state file", encoding="utf-8")

    original_gitkeep_mode = stat.S_IMODE(gitkeep.stat().st_mode)
    original_readme_mode = stat.S_IMODE(readme.stat().st_mode)

    with patch("os.chown") as mock_chown:
        _run_main(admin_root)

    touched_paths = {call.args[0] for call in mock_chown.call_args_list}
    assert str(gitkeep) not in touched_paths
    assert str(readme) not in touched_paths
    assert stat.S_IMODE(gitkeep.stat().st_mode) == original_gitkeep_mode
    assert stat.S_IMODE(readme.stat().st_mode) == original_readme_mode

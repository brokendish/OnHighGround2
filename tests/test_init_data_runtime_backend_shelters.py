"""
test_init_data_runtime_backend_shelters.py — Residual Finding Remediation 05 Phase B2

scripts/publish/init_data_runtime_backend_shelters.py テスト。

OWNER Section 25（least-privilege correction）に従い、directory配下の
non-dot fileを一律同じmetadataへ寄せるのではなく、用途別に明示分類する:
  - active shelter GeoJSON: operator_uid:leases_gid 0640
  - recognized backup: operator_uid:operator_gid 0640
  - dormant legacy file（tokyo_shelter.geojson）: 一切変更しない
  - unknown file: fail-closedでSTOP、自動chownしない

実際のchown()はroot権限を要するため、テストではos.chownをmockし
「正しいuid/gidが正しいpathに対して要求されたか」を検証する。
"""
from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path
from unittest.mock import patch

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "publish" / "init_data_runtime_backend_shelters.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("init_data_runtime_backend_shelters", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()

_OPERATOR_UID, _OPERATOR_GID, _LEASES_GID = 10002, 10002, 20001


def _run_main(backend_root: Path):
    argv = [
        "init_data_runtime_backend_shelters.py",
        str(backend_root),
        "--operator-uid", str(_OPERATOR_UID),
        "--operator-gid", str(_OPERATOR_GID),
        "--leases-gid", str(_LEASES_GID),
    ]
    with patch.object(sys, "argv", argv), \
         patch("os.geteuid", return_value=0):
        return mod.main()


def _make_full_tree(backend_root: Path, *, include_dormant=True, include_backups=True):
    shelters = backend_root / "shelters"
    kanagawa = shelters / "kanagawa"
    emergency = backend_root / "emergency_shelters"
    kanagawa.mkdir(parents=True)
    emergency.mkdir(parents=True)

    (shelters / "tokyo-shelter-001.geojson").write_bytes(b"tokyo shelter active")
    (kanagawa / "kanagawa-evac-001.geojson").write_bytes(b"kanagawa evac active")
    (kanagawa / "kanagawa-shelter-001.geojson").write_bytes(b"kanagawa shelter active")
    (emergency / "tokyo-evac-001.geojson").write_bytes(b"tokyo evac active")

    if include_backups:
        (shelters / "tokyo-shelter-001.backup.geojson").write_bytes(b"tokyo shelter backup")
        (kanagawa / "kanagawa-shelter-001.backup.geojson").write_bytes(b"kanagawa shelter backup")
        (emergency / "tokyo-evac-001.backup.geojson").write_bytes(b"tokyo evac backup")

    if include_dormant:
        (shelters / "tokyo_shelter.geojson").write_bytes(b"dormant legacy content")


# ── A. active GeoJSON → 10002:20001 0640 ──────────────────────────────────────

def test_active_geojson_files_get_leases_gid(tmp_path):
    backend_root = tmp_path / "backend"
    _make_full_tree(backend_root)

    with patch("os.chown") as mock_chown:
        rc = _run_main(backend_root)

    assert rc == 0
    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    for rel in mod._ACTIVE_FILES:
        path = str(backend_root / rel)
        assert stat.S_IMODE((backend_root / rel).stat().st_mode) == mod.ACTIVE_FILE_MODE
        assert calls[path] == (_OPERATOR_UID, _LEASES_GID)


# ── B. backup → 10002:10002 0640（leases_gidではない） ────────────────────────

def test_backup_files_get_operator_gid_not_leases(tmp_path):
    backend_root = tmp_path / "backend"
    _make_full_tree(backend_root)

    with patch("os.chown") as mock_chown:
        _run_main(backend_root)

    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    for rel in mod._BACKUP_FILES:
        path = str(backend_root / rel)
        assert stat.S_IMODE((backend_root / rel).stat().st_mode) == mod.BACKUP_FILE_MODE
        gid_used = calls[path][1]
        assert gid_used == _OPERATOR_GID
        assert gid_used != _LEASES_GID


# ── E. dormant tokyo_shelter.geojson → bootstrap後metadata不変 ───────────────

def test_dormant_legacy_file_is_never_touched(tmp_path):
    backend_root = tmp_path / "backend"
    _make_full_tree(backend_root)
    dormant = backend_root / "shelters" / "tokyo_shelter.geojson"
    original_mode = stat.S_IMODE(dormant.stat().st_mode)
    original_content = dormant.read_bytes()

    with patch("os.chown") as mock_chown:
        _run_main(backend_root)

    touched = {c.args[0] for c in mock_chown.call_args_list}
    assert str(dormant) not in touched
    assert stat.S_IMODE(dormant.stat().st_mode) == original_mode
    assert dormant.read_bytes() == original_content


# ── F. unknown file → 自動mutationされない（fail-closed） ─────────────────────

def test_unknown_file_causes_fail_closed_stop(tmp_path):
    backend_root = tmp_path / "backend"
    _make_full_tree(backend_root)
    unknown = backend_root / "shelters" / "unexpected-mystery-file.geojson"
    unknown.write_bytes(b"nobody knows what this is")
    original_mode = stat.S_IMODE(unknown.stat().st_mode)

    with patch("os.chown") as mock_chown:
        try:
            _run_main(backend_root)
            assert False, "unknown fileがある場合はSystemExitするはず"
        except SystemExit as exc:
            assert exc.code == 1

    # fail-closedのため、どのfileにもchownが実行されていないこと
    assert mock_chown.call_count == 0
    assert stat.S_IMODE(unknown.stat().st_mode) == original_mode


def test_no_unknown_files_passes_normally(tmp_path):
    """既知file（active/backup/dormant）のみの構成ならSTOPしない。"""
    backend_root = tmp_path / "backend"
    _make_full_tree(backend_root)

    with patch("os.chown"):
        rc = _run_main(backend_root)

    assert rc == 0


# ── backup不存在（未deployのbackup）は単にskip ────────────────────────────────

def test_missing_backup_is_gracefully_skipped(tmp_path):
    backend_root = tmp_path / "backend"
    _make_full_tree(backend_root, include_backups=False)

    with patch("os.chown") as mock_chown:
        rc = _run_main(backend_root)

    assert rc == 0
    calls = {c.args[0] for c in mock_chown.call_args_list}
    for rel in mod._BACKUP_FILES:
        assert str(backend_root / rel) not in calls


# ── directory自体 → 10002:20001 0750 ─────────────────────────────────────────

def test_directories_get_leases_gid_0750(tmp_path):
    backend_root = tmp_path / "backend"
    _make_full_tree(backend_root)

    with patch("os.chown") as mock_chown:
        _run_main(backend_root)

    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    for rel in mod._SHELTER_DIRS:
        target = backend_root / rel
        assert stat.S_IMODE(target.stat().st_mode) == mod.DIR_MODE
        assert calls[str(target)] == (_OPERATOR_UID, _LEASES_GID)


def test_missing_shelter_dir_is_skipped_not_force_created(tmp_path):
    backend_root = tmp_path / "backend"
    backend_root.mkdir()

    with patch("os.chown") as mock_chown:
        rc = _run_main(backend_root)

    assert rc == 0
    for rel in mod._SHELTER_DIRS:
        assert not (backend_root / rel).exists()
    assert len(mock_chown.call_args_list) == 0


# ── idempotency ───────────────────────────────────────────────────────────────

def test_idempotent_second_run_no_content_change(tmp_path):
    backend_root = tmp_path / "backend"
    _make_full_tree(backend_root)

    with patch("os.chown"):
        rc1 = _run_main(backend_root)
        rc2 = _run_main(backend_root)

    assert rc1 == 0 and rc2 == 0
    active = backend_root / "shelters" / "tokyo-shelter-001.geojson"
    assert active.read_bytes() == b"tokyo shelter active"
    assert stat.S_IMODE(active.stat().st_mode) == mod.ACTIVE_FILE_MODE


# ── root権限チェック ──────────────────────────────────────────────────────────

def test_requires_root(tmp_path):
    backend_root = tmp_path / "backend"
    argv = [
        "init_data_runtime_backend_shelters.py",
        str(backend_root),
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
    assert not backend_root.exists()

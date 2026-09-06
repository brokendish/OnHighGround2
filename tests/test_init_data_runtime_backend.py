"""
test_init_data_runtime_backend.py — scripts/publish/init_data_runtime_backend.py テスト

Residual Finding Remediation 05 Phase B1 (DATA-RUNTIME-BACKEND-LEGACY-OWNERSHIP):
data_runtime/backend/hazard のflat mirrorをbackend-operator writer契約
（operator_uid:leases_gid, dir 0750 / file 0640、data_runtime/current
versioned側と同一）へ是正するone-shot initializerの検証。

実際のchown()はroot権限を要するため、テストではos.chownをmockし
「正しいuid/gidが正しいpathに対して要求されたか」を検証する。
mode（chmod）はrootを要さないため、実際にtmp_path上でchmodを実行し
実際のstat結果で検証する。
"""
from __future__ import annotations

import importlib.util
import stat
import sys
from pathlib import Path
from unittest.mock import patch

_MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts" / "publish" / "init_data_runtime_backend.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("init_data_runtime_backend", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load_module()

_OPERATOR_UID, _OPERATOR_GID, _LEASES_GID = 10002, 10002, 20001


def _run_main(hazard_root: Path):
    argv = [
        "init_data_runtime_backend.py",
        str(hazard_root),
        "--operator-uid", str(_OPERATOR_UID),
        "--operator-gid", str(_OPERATOR_GID),
        "--leases-gid", str(_LEASES_GID),
    ]
    with patch.object(sys, "argv", argv), \
         patch("os.geteuid", return_value=0):
        return mod.main()


# ── A. fresh install ──────────────────────────────────────────────────────────

# ── OWNER Section 11 correction review item A: hazard root legacy metadata ───

def test_hazard_root_legacy_mode_is_corrected_to_target_contract(tmp_path):
    """/data_runtime/backend/hazard root inode自体が、legacy 1000:1000相当
    （world-readable 0755）のown/modeで既に存在する場合でも、bootstrap経由で
    10002:20001 0750へ是正されること（Phase B1のscope: root inode自体を
    含める、というOWNER指示に対応）。"""
    hazard_root = tmp_path / "hazard"
    hazard_root.mkdir()
    hazard_root.chmod(0o755)  # legacy相当のmode

    with patch("os.chown") as mock_chown:
        rc = _run_main(hazard_root)

    assert rc == 0
    assert stat.S_IMODE(hazard_root.stat().st_mode) == mod.DIR_MODE
    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(hazard_root)] == (_OPERATOR_UID, _LEASES_GID)


def test_all_existing_type_directories_claimed_with_leases_gid(tmp_path):
    """既に全typeがdeploy済み（legacy migration相当）の場合、hazard root
    および7 type全てが正しいcontractへ是正される。"""
    hazard_root = tmp_path / "hazard"
    for hazard_type in mod._HAZARD_TYPES:
        (hazard_root / hazard_type).mkdir(parents=True)

    with patch("os.chown") as mock_chown:
        rc = _run_main(hazard_root)

    assert rc == 0
    assert hazard_root.is_dir()
    assert stat.S_IMODE(hazard_root.stat().st_mode) == mod.DIR_MODE
    for hazard_type in mod._HAZARD_TYPES:
        type_dir = hazard_root / hazard_type
        assert type_dir.is_dir()
        assert stat.S_IMODE(type_dir.stat().st_mode) == mod.DIR_MODE

    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(hazard_root)] == (_OPERATOR_UID, _LEASES_GID)
    for hazard_type in mod._HAZARD_TYPES:
        assert calls[str(hazard_root / hazard_type)] == (_OPERATOR_UID, _LEASES_GID)


def test_fresh_install_with_no_existing_types_only_claims_root(tmp_path):
    """真のfresh install（type directoryが1件も存在しない）ではhazard root
    のみ生成され、type directoryは空生成しない（次回deployが自然に作る）。"""
    hazard_root = tmp_path / "hazard"

    with patch("os.chown") as mock_chown:
        rc = _run_main(hazard_root)

    assert rc == 0
    assert hazard_root.is_dir()
    for hazard_type in mod._HAZARD_TYPES:
        assert not (hazard_root / hazard_type).exists()
    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(hazard_root)] == (_OPERATOR_UID, _LEASES_GID)
    assert len(calls) == 1


# ── B. idempotency ────────────────────────────────────────────────────────────

def test_idempotent_second_run_no_content_change(tmp_path):
    hazard_root = tmp_path / "hazard"
    type_dir = hazard_root / "tsunami"
    type_dir.mkdir(parents=True)
    existing = type_dir / "tsunami_tokyo.geojson"
    existing.write_text('{"type": "FeatureCollection"}', encoding="utf-8")
    original_content = existing.read_text(encoding="utf-8")

    with patch("os.chown"):
        rc1 = _run_main(hazard_root)
        rc2 = _run_main(hazard_root)

    assert rc1 == 0 and rc2 == 0
    assert existing.read_text(encoding="utf-8") == original_content
    assert stat.S_IMODE(existing.stat().st_mode) == mod.FILE_MODE
    assert stat.S_IMODE(type_dir.stat().st_mode) == mod.DIR_MODE


# ── C. legacy non-empty directory migration（非recursive） ────────────────────

def test_legacy_nonempty_type_directory_claimed_non_recursively(tmp_path):
    hazard_root = tmp_path / "hazard"
    type_dir = hazard_root / "storm_surge"
    type_dir.mkdir(parents=True)
    type_dir.chmod(0o755)  # legacy 1000:1000相当のmode
    hazard_file = type_dir / "tokyo-surge-001.geojson"
    hazard_file.write_bytes(b"geojson content")

    with patch("os.chown") as mock_chown:
        rc = _run_main(hazard_root)

    assert rc == 0
    assert stat.S_IMODE(type_dir.stat().st_mode) == mod.DIR_MODE
    assert stat.S_IMODE(hazard_file.stat().st_mode) == mod.FILE_MODE
    assert hazard_file.read_bytes() == b"geojson content"
    calls = {call.args[0]: call.args[1:] for call in mock_chown.call_args_list}
    assert calls[str(hazard_file)] == (_OPERATOR_UID, _LEASES_GID)


# ── D. content preservation across all matched extensions ────────────────────

def test_geojson_and_geojsonl_both_migrated_content_preserved(tmp_path):
    hazard_root = tmp_path / "hazard"
    type_dir = hazard_root / "flood"
    type_dir.mkdir(parents=True)
    geojson_file = type_dir / "tokyo-river-001.geojson"
    geojson_file.write_bytes(b"AAA")
    geojsonl_file = type_dir / "tokyo_flood_check.geojsonl"
    geojsonl_file.write_bytes(b"BBB")

    with patch("os.chown"):
        _run_main(hazard_root)

    assert geojson_file.read_bytes() == b"AAA"
    assert geojsonl_file.read_bytes() == b"BBB"
    assert stat.S_IMODE(geojson_file.stat().st_mode) == mod.FILE_MODE
    assert stat.S_IMODE(geojsonl_file.stat().st_mode) == mod.FILE_MODE


# ── E. dotfile (.gitkeep等) は対象外 ───────────────────────────────────────────

def test_gitkeep_and_backup_files_handling(tmp_path):
    """.gitkeepはdotfileとして対象外。.backup.geojsonはgeojson拡張子に
    一致するため対象（既存active mirrorの一部として明示migration対象）。"""
    hazard_root = tmp_path / "hazard"
    type_dir = hazard_root / "tsunami"
    type_dir.mkdir(parents=True)
    gitkeep = type_dir / ".gitkeep"
    gitkeep.write_text("", encoding="utf-8")
    backup_file = type_dir / "kanagawa-tsunami-001.backup.geojson"
    backup_file.write_bytes(b"backup content")
    original_gitkeep_mode = stat.S_IMODE(gitkeep.stat().st_mode)

    with patch("os.chown") as mock_chown:
        _run_main(hazard_root)

    touched = {c.args[0] for c in mock_chown.call_args_list}
    assert str(gitkeep) not in touched
    assert stat.S_IMODE(gitkeep.stat().st_mode) == original_gitkeep_mode
    assert str(backup_file) in touched
    assert stat.S_IMODE(backup_file.stat().st_mode) == mod.FILE_MODE
    assert backup_file.read_bytes() == b"backup content"


# ── F. missing type directory is skipped, not created blindly for all 7 ──────

def test_missing_type_directory_is_skipped_not_force_created(tmp_path):
    hazard_root = tmp_path / "hazard"
    hazard_root.mkdir()
    # 7 typeのうち1件だけ実在させる
    only_type = hazard_root / "pseudo_inland_flood"
    only_type.mkdir()

    with patch("os.chown"):
        rc = _run_main(hazard_root)

    assert rc == 0
    for hazard_type in mod._HAZARD_TYPES:
        type_dir = hazard_root / hazard_type
        if hazard_type == "pseudo_inland_flood":
            assert type_dir.exists()
        else:
            assert not type_dir.exists(), f"{hazard_type} は存在しないtypeとしてskipされるはず"


# ── root権限チェック ──────────────────────────────────────────────────────────

def test_requires_root(tmp_path):
    hazard_root = tmp_path / "hazard"
    argv = [
        "init_data_runtime_backend.py",
        str(hazard_root),
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
    assert not hazard_root.exists()

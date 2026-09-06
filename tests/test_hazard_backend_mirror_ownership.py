"""
test_hazard_backend_mirror_ownership.py — Residual Finding Remediation 05 Phase B1

pipeline_service._reload_hazard_backend_mirror() が、data_runtime/current
（versioned hazard mirror）と同じ owner/group/mode契約
（operator_uid:leases_gid, dir 0750 / file 0640）を、既存destination上書き時
にも明示的に適用することを確認する。

実際のchown()は「自分が所有していないUIDへの変更」または「所属していない
GIDへの変更」にroot権限を要するため、テストではos.chownをmockし、
「正しいpathへ正しいgidが要求されたか」を検証する。chmod（mode是正）は
root不要のため実際にtmp_path上で実行し、実stat結果で検証する。
"""
from __future__ import annotations

import stat
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.runtime_publish import VERSION_DIR_MODE, VERSION_FILE_MODE  # noqa: E402


def _make_defn(**overrides):
    from app.models.admin_dataset import DatasetDefinition

    base = dict(
        dataset_id="TEST-HAZARD-001",
        region="tokyo",
        category="hazard",
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
        raw_storage_path="data_lake/raw/tokyo/lowland_poor_drainage",
        validated_storage_path="data_lake/validated/tokyo/lowland_poor_drainage",
        runtime_path="data_runtime/backend/hazard/lowland_poor_drainage",
        deploy_mode="copy_file",
        layer_type="lowland_poor_drainage",
    )
    base.update(overrides)
    return DatasetDefinition(**base)


def _call_reload(tmp_path, defn, validated_content: bytes):
    from app.services.pipeline_service import _reload_hazard_backend_mirror
    from app.models.admin_dataset import DatasetState

    src = tmp_path / "validated" / f"tokyo-{defn.layer_type}-001.geojson"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(validated_content)

    backend_dir = tmp_path / "data_runtime" / "backend" / "hazard" / defn.layer_type
    defn = defn.model_copy(update={"runtime_path": str(backend_dir)})
    state = DatasetState(dataset_id=defn.dataset_id, current_validated_path=str(src))

    job = Mock()
    jm = Mock()

    with patch("app.services.pipeline_service._PROJECT_ROOT", tmp_path):
        _reload_hazard_backend_mirror(job, defn, state, jm)

    return backend_dir, backend_dir / src.name


# ── A. lowland_poor_drainage: 既存destinationを上書き ─────────────────────────

def test_lowland_overwrite_existing_destination_applies_target_contract(tmp_path):
    defn = _make_defn(layer_type="lowland_poor_drainage", region="tokyo")
    backend_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "lowland_poor_drainage"
    backend_dir.mkdir(parents=True)
    existing_dest = backend_dir / "tokyo-lowland_poor_drainage-001.geojson"

    with patch("os.chown") as mock_chown:
        result_dir, dest = _call_reload(tmp_path, defn, b'{"type": "FeatureCollection", "features": [1]}')

    assert dest.exists()
    assert dest.read_bytes() == b'{"type": "FeatureCollection", "features": [1]}'
    assert stat.S_IMODE(dest.stat().st_mode) == VERSION_FILE_MODE
    assert stat.S_IMODE(result_dir.stat().st_mode) == VERSION_DIR_MODE

    chown_calls = {str(c.args[0]): c.args[1:] for c in mock_chown.call_args_list}
    assert chown_calls[str(dest)] == (-1, 20001)
    assert chown_calls[str(result_dir)] == (-1, 20001)


def test_lowland_overwrite_replaces_stale_content(tmp_path):
    """既存destinationに古い内容が入っていても、新しい内容へ確実に上書きされる。"""
    defn = _make_defn(layer_type="lowland_poor_drainage", region="tokyo")
    backend_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "lowland_poor_drainage"
    backend_dir.mkdir(parents=True)
    dest_path = backend_dir / "tokyo-lowland_poor_drainage-001.geojson"
    dest_path.write_bytes(b"OLD STALE CONTENT")

    with patch("os.chown"):
        _, dest = _call_reload(tmp_path, defn, b'{"type": "FeatureCollection", "features": [2]}')

    assert dest.read_bytes() == b'{"type": "FeatureCollection", "features": [2]}'


# ── B. pseudo_inland_flood: 既存destinationを上書き ───────────────────────────

def test_pseudo_overwrite_existing_destination_applies_target_contract(tmp_path):
    defn = _make_defn(
        layer_type="pseudo_inland_flood", region="tokyo",
        raw_storage_path="data_lake/raw/tokyo/pseudo_inland_flood",
        validated_storage_path="data_lake/validated/tokyo/pseudo_inland_flood",
        runtime_path="data_runtime/backend/hazard/pseudo_inland_flood",
    )
    backend_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "pseudo_inland_flood"
    backend_dir.mkdir(parents=True)

    with patch("os.chown") as mock_chown:
        result_dir, dest = _call_reload(tmp_path, defn, b'{"type": "FeatureCollection", "features": [3]}')

    assert dest.exists()
    assert stat.S_IMODE(dest.stat().st_mode) == VERSION_FILE_MODE
    chown_calls = {str(c.args[0]): c.args[1:] for c in mock_chown.call_args_list}
    assert chown_calls[str(dest)] == (-1, 20001)


# ── C. 新規directory作成時も同じcontractが適用される ──────────────────────────

def test_reload_creates_new_directory_with_target_contract(tmp_path):
    defn = _make_defn(layer_type="lowland_poor_drainage", region="kanagawa")
    # backend_dirを事前作成しない（初回reload相当）

    with patch("os.chown") as mock_chown:
        result_dir, dest = _call_reload(tmp_path, defn, b'{"type": "FeatureCollection", "features": []}')

    assert result_dir.exists()
    assert stat.S_IMODE(result_dir.stat().st_mode) == VERSION_DIR_MODE
    chown_calls = {str(c.args[0]): c.args[1:] for c in mock_chown.call_args_list}
    assert chown_calls[str(result_dir)] == (-1, 20001)


# ── D. missing source は既存のgraceful skip挙動を維持する ─────────────────────

def test_missing_validated_source_is_still_graceful_noop(tmp_path):
    from app.services.pipeline_service import _reload_hazard_backend_mirror
    from app.models.admin_dataset import DatasetState

    defn = _make_defn(layer_type="lowland_poor_drainage")
    state = DatasetState(dataset_id=defn.dataset_id, current_validated_path=None)
    job = Mock()
    jm = Mock()

    with patch("app.services.pipeline_service._PROJECT_ROOT", tmp_path):
        _reload_hazard_backend_mirror(job, defn, state, jm)

    backend_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "lowland_poor_drainage"
    assert not backend_dir.exists()


# ── E. 2回目reload → idempotent ───────────────────────────────────────────────

def test_second_reload_is_idempotent(tmp_path):
    """同一hazard typeを2回reloadしても、directory/fileともcontractが
    安定し、2回目もchmod/chown呼び出しが正しい引数で行われる
    （不整合や重複artifactを生まない）。"""
    defn = _make_defn(layer_type="lowland_poor_drainage", region="tokyo")

    with patch("os.chown") as mock_chown:
        result_dir1, dest1 = _call_reload(tmp_path, defn, b'{"version": 1}')
        result_dir2, dest2 = _call_reload(tmp_path, defn, b'{"version": 2}')

    assert result_dir1 == result_dir2
    assert dest1 == dest2
    assert dest2.read_bytes() == b'{"version": 2}'
    assert stat.S_IMODE(dest2.stat().st_mode) == VERSION_FILE_MODE
    assert stat.S_IMODE(result_dir2.stat().st_mode) == VERSION_DIR_MODE

    # 2回目呼び出し分もdir/fileそれぞれ正しいgidでchownされていること
    calls_for_dest = [c for c in mock_chown.call_args_list if c.args[0] == dest2]
    calls_for_dir = [c for c in mock_chown.call_args_list if c.args[0] == result_dir2]
    assert calls_for_dest[-1].args[1:] == (-1, 20001)
    assert calls_for_dir[-1].args[1:] == (-1, 20001)
    # directoryが重複生成されていない（同一inode想定、ここではpathの一意性で確認）
    assert len(list(result_dir2.parent.iterdir())) == 1


# ── F. public reader contract → group 20001経由でread可能（論理検証） ─────────

def test_target_mode_and_group_grant_group_read_for_public() -> None:
    """VERSION_FILE_MODE(0640)はgroup読み取りbitを持ち、leases_gid(20001)を
    supplemental groupに持つbackend-public（owner不一致）がread可能である
    contractを、mode bit計算として固定する。実際のmulti-UID越しのfilesystem
    挙動はVPS runtime validationで確認する（unit testの範囲外）。
    """
    assert VERSION_FILE_MODE & 0o040, "groupにread権限が無ければpublicはread不可"
    assert not (VERSION_FILE_MODE & 0o004), "otherにread権限を与えてはいけない（public以外への漏洩防止）"
    assert not (VERSION_FILE_MODE & 0o020), "groupへwrite権限を与えてはいけない（public writerにしない）"
    assert VERSION_DIR_MODE & 0o050 == 0o050, "groupにtraverse+read権限が無ければpublicはdirectory到達不可"
    assert not (VERSION_DIR_MODE & 0o007), "otherに一切の権限を与えてはいけない"

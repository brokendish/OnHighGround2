"""
STATE-DESTRUCTIVE-LOAD 再発防止（2026-10-07 実害: host 上の load が container path の state を削除）。

  - load() は読むだけ（削除・再推定・保存しない）。記録 path の可視性は path_status() で返す
  - 記録 path が別 namespace（host から見た /data_runtime、container から見た /Users 等）の場合、
    init_from_definition は state を作り直さない
  - atomic publish 対象の versions 内 artifact が見えないだけなら作り直さず reconcile に委ねる
  - 既存の DATASET-STATE-INVALIDATION（definition 契約と矛盾する path の再解決）は維持
  - テストは実 data_lake/admin に書けない（tests/admin_isolation.py の guard）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetDefinition, DeployStatus  # noqa: E402
from app.services import dataset_state_service as dss  # noqa: E402

CONTAINER_STATE = {
    "dataset_id": "TOKYO-RIVER-001",
    "current_raw_path": "/data_lake/raw/tokyo/flood/TOKYO-RIVER-001_bundle_stmxod68.zip",
    "current_validated_path": "/data_lake/validated/tokyo/flood/tokyo-river-001.geojson",
    "current_runtime_path": "/data_runtime/versions/20261006T132110Z-6f6d963c/backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson",
    "normalize_status": "success", "validation_status": "pass", "deploy_status": "deployed",
    "storage_status": "stored", "last_job_id": "job-keep", "backup_path": "/backup/keep",
}
HOST_STATE = dict(CONTAINER_STATE, current_raw_path="/Users/nobody-ohg2-test/raw.zip",
                  current_runtime_path="/Users/nobody-ohg2-test/versions/x/backend/hazard/flood/tokyo/a.routing.geojson")


def _defn(layer_type="flood"):
    return DatasetDefinition(
        dataset_id="TOKYO-RIVER-001", region="tokyo", category=layer_type, display_name="t", description="t",
        hint_text="t", impact_scope="t", accepted_input_modes=[], accepted_extensions=[], max_browser_upload_mb=0,
        requires_normalize=True, requires_validation=True, requires_deploy=True, requires_osrm_rebuild=False,
        raw_storage_path="data_lake/raw/tokyo/flood", validated_storage_path="data_lake/validated/tokyo/flood",
        runtime_path="data_runtime/backend/hazard/flood", deploy_mode="copy_file", layer_type=layer_type,
    )


def _svc(tmp_path, payload):
    svc = dss.DatasetStateService(state_dir=tmp_path / "state", history_dir=tmp_path / "history")
    f = tmp_path / "state" / "TOKYO-RIVER-001.json"
    f.write_text(json.dumps(payload), encoding="utf-8")
    return svc, f


def _namespace_absent(path: str) -> bool:
    p = Path(path)
    return not (Path(p.parts[0]) / p.parts[1]).exists()


@pytest.mark.parametrize("payload", [CONTAINER_STATE, HOST_STATE])
def test_load_never_deletes_or_rewrites(tmp_path, payload):
    if not _namespace_absent(payload["current_runtime_path"]):
        pytest.skip("この process では当該 namespace が存在する")
    svc, f = _svc(tmp_path, payload)
    before = f.read_bytes()
    state = svc.load("TOKYO-RIVER-001")
    assert f.read_bytes() == before
    assert state.current_runtime_path == payload["current_runtime_path"]
    assert state.last_job_id == "job-keep" and state.backup_path == "/backup/keep"
    status = svc.path_status(state)
    assert status["current_runtime_path"] == dss.PATH_UNOBSERVABLE


@pytest.mark.parametrize("payload", [CONTAINER_STATE, HOST_STATE])
def test_init_from_definition_keeps_state_outside_namespace(tmp_path, payload):
    if not _namespace_absent(payload["current_runtime_path"]):
        pytest.skip("この process では当該 namespace が存在する")
    svc, f = _svc(tmp_path, payload)
    before = f.read_bytes()
    state = svc.init_from_definition(_defn())
    assert f.read_bytes() == before  # 再推定・保存しない
    assert state.deploy_status == DeployStatus.deployed
    assert state.current_runtime_path == payload["current_runtime_path"]
    assert state.current_validated_path == payload["current_validated_path"]


def test_atomic_versions_artifact_missing_defers_to_reconcile(tmp_path, monkeypatch):
    """namespace 内でも、versions 配下の artifact が無いだけなら作り直さない（reconcile が stale 判定）。"""
    rt = tmp_path / "runtime"
    (rt / "versions").mkdir(parents=True)
    monkeypatch.setenv("OHG2_DATA_RUNTIME_ROOT", str(rt))
    payload = dict(CONTAINER_STATE, current_runtime_path=str(rt / "versions/old/backend/hazard/flood/tokyo/a.routing.geojson"))
    svc, f = _svc(tmp_path, payload)
    before = f.read_bytes()
    state = svc.init_from_definition(_defn())
    assert f.read_bytes() == before and state.current_runtime_path == payload["current_runtime_path"]


def test_path_visibility_values(tmp_path):
    existing = tmp_path / "a.txt"
    existing.write_text("x")
    assert dss.DatasetStateService.path_visibility(str(existing)) == dss.PATH_PRESENT
    assert dss.DatasetStateService.path_visibility(str(tmp_path / "missing.txt")) == dss.PATH_MISSING
    assert dss.DatasetStateService.path_visibility("/nonexistent-ohg2-root/x/y") == dss.PATH_UNOBSERVABLE
    assert dss.DatasetStateService.path_visibility(None) is None


def test_load_source_has_no_unlink():
    src = (ROOT / "backend/app/services/dataset_state_service.py").read_text(encoding="utf-8")
    load = src[src.index("    def load(self"):src.index("    @staticmethod\n    def path_visibility")]
    assert "unlink" not in load and "save(" not in load and "_infer_state_from_filesystem" not in load


# ── guard 自体の検証 ────────────────────────────────────────────────────────────

def test_admin_dir_is_isolated_for_tests():
    import os
    from admin_isolation import REAL_ADMIN
    iso = Path(os.environ["OHG2_ADMIN_DIR"]).resolve()
    assert iso != REAL_ADMIN and REAL_ADMIN not in iso.parents
    assert dss._ADMIN_STATE_DIR.resolve().parent == iso
    from app.services import active_mapping_service, job_manager
    assert job_manager._BOOT_STATE_PATH.resolve().parent == iso
    assert active_mapping_service._MAPPINGS_PATH.resolve().parent == iso


def test_guard_blocks_real_admin_write():
    import admin_isolation as ai
    start = len(ai._hits)
    with pytest.raises(PermissionError):
        open(ai.REAL_ADMIN / "state" / "__guard_probe__.json", "w")
    assert len(ai._hits) == start + 1 and ai._hits[-1]["event"] == "open"
    assert not (ai.REAL_ADMIN / "state" / "__guard_probe__.json").exists()
    del ai._hits[start:]  # 意図的な probe なので本テストの失敗扱いから除外

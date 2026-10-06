"""
pipeline_service の flood routing 工程（derive → routing validation）と反映ゲートのテスト。

  - flood は validate 後に derive routing → validate routing を実行し、成功時のみ deployable
  - derive 失敗 / routing validation 失敗 → job failed・deployable にしない（publish 禁止）
  - 反映（run_deploy）: routing が canonical と不一致なら DEPLOY_BLOCKED_ROUTING_CONTRACT で中止
  - 反映成功時の配置は test_admin_atomic_publish_deploy.py（atomic publish 経由）で検証
  - flood 以外の layer は routing 工程を通らない
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("shapely")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetDefinition, DatasetState, JobStep, StorageStatus  # noqa: E402
from app.services import pipeline_service as ps  # noqa: E402


def _defn(layer_type="flood", **overrides) -> DatasetDefinition:
    base = dict(
        dataset_id="TOKYO-RIVER-001", region="tokyo", category="flood", display_name="t", description="t",
        hint_text="t", impact_scope="t", accepted_input_modes=[], accepted_extensions=[],
        max_browser_upload_mb=0, requires_normalize=False, requires_validation=False, requires_deploy=True,
        requires_osrm_rebuild=False, raw_storage_path="data_lake/raw/tokyo/flood",
        validated_storage_path="data_lake/validated/tokyo/flood",
        runtime_path="data_runtime/backend/hazard/flood", deploy_mode="copy_file", layer_type=layer_type,
    )
    base.update(overrides)
    return DatasetDefinition(**base)


def _canonical(tmp_path: Path) -> Path:
    p = tmp_path / "data_lake" / "validated" / "tokyo" / "flood" / "tokyo-river-001.geojson"
    p.parent.mkdir(parents=True)
    feat = {"type": "Feature", "properties": {"flood_rank": 2},
            "geometry": {"type": "Polygon", "coordinates": [[[139.0, 35.0], [139.01, 35.0], [139.01, 35.01],
                                                             [139.0, 35.01], [139.0, 35.0]]]}}
    p.write_text('{"type":"FeatureCollection","features":[\n' + json.dumps(feat, separators=(",", ":")) + "\n]}\n",
                 encoding="utf-8")
    return p


def _state(canonical: Path) -> DatasetState:
    return DatasetState(dataset_id="TOKYO-RIVER-001", storage_status=StorageStatus.stored,
                        current_validated_path=str(canonical))


async def _run_with_current_python(cmd, job, jm, timeout=None):
    """pipeline は 'python3' を起動するため、テストでは shapely の入った現在の Python で実行する。"""
    cmd = [sys.executable if c == "python3" else c for c in cmd]
    return subprocess.run(cmd, capture_output=True).returncode


def _failed_code(jm: Mock):
    for call in jm.update.call_args_list:
        if call.kwargs.get("step") == JobStep.failed:
            return call.kwargs.get("error_code")
    return None


def _ss():
    ss = Mock()
    ss.update_deployable.side_effect = lambda st, _d: setattr(st, "is_deployable", True)
    return ss


def test_flood_pipeline_derives_and_validates_routing(tmp_path):
    canonical = _canonical(tmp_path)
    state, jm, ss = _state(canonical), Mock(), _ss()
    with patch.object(ps, "_run_subprocess", _run_with_current_python):
        asyncio.run(ps._run_post_ingest_pipeline(Mock(), _defn(), state, jm, ss))

    routing = tmp_path / "data_lake" / "derived" / "tokyo" / "flood" / "tokyo-river-001.routing.geojson"
    assert routing.is_file() and routing.with_name("tokyo-river-001.routing.meta.json").is_file()
    steps = [c.kwargs.get("step") for c in jm.update.call_args_list]
    assert steps.index(JobStep.derive_routing) < steps.index(JobStep.validate_routing)
    assert _failed_code(jm) is None
    assert state.is_deployable is True


def test_derive_failure_blocks_publish(tmp_path):
    canonical = _canonical(tmp_path)
    state, jm, ss = _state(canonical), Mock(), _ss()
    state.is_deployable = True

    async def _fail(*_a, **_k):
        return 1

    with patch.object(ps, "_run_subprocess", _fail):
        asyncio.run(ps._run_post_ingest_pipeline(Mock(), _defn(), state, jm, ss))
    assert _failed_code(jm) == "ROUTING_DERIVE_FAILED"
    assert state.is_deployable is False
    ss.update_deployable.assert_not_called()


def test_routing_validation_failure_blocks_publish(tmp_path):
    canonical = _canonical(tmp_path)
    state, jm, ss = _state(canonical), Mock(), _ss()
    calls = []

    async def _derive_ok_validate_fail(cmd, job, jm_, timeout=None):
        calls.append(cmd)
        if "validate_flood_routing_artifact.py" in " ".join(cmd):
            return 1
        return await _run_with_current_python(cmd, job, jm_)

    with patch.object(ps, "_run_subprocess", _derive_ok_validate_fail):
        asyncio.run(ps._run_post_ingest_pipeline(Mock(), _defn(), state, jm, ss))
    assert _failed_code(jm) == "ROUTING_VALIDATION_FAILED"
    assert state.is_deployable is False
    ss.update_deployable.assert_not_called()


def test_non_flood_layer_skips_routing_steps(tmp_path):
    canonical = _canonical(tmp_path)
    state, jm, ss = _state(canonical), Mock(), _ss()

    async def _must_not_run(*_a, **_k):
        raise AssertionError("routing 工程は flood 以外で実行されない")

    with patch.object(ps, "_run_subprocess", _must_not_run):
        asyncio.run(ps._run_post_ingest_pipeline(Mock(), _defn(layer_type="storm_surge"), state, jm, ss))
    steps = [c.kwargs.get("step") for c in jm.update.call_args_list]
    assert JobStep.derive_routing not in steps
    assert not (tmp_path / "data_lake" / "derived").exists()


def _job() -> Mock:
    return Mock(job_id="job-test-001", requested_by="test", actor_id="test", request_id="req-test")


def _deploy(tmp_path, state, jm, ss):
    with patch.object(ps, "_PROJECT_ROOT", tmp_path):
        asyncio.run(ps.run_deploy(_job(), _defn(), state, jm, ss))


def test_deploy_blocked_when_routing_stale(tmp_path):
    canonical = _canonical(tmp_path)
    state, jm, ss = _state(canonical), Mock(), _ss()
    with patch.object(ps, "_run_subprocess", _run_with_current_python):
        asyncio.run(ps._run_post_ingest_pipeline(Mock(), _defn(), state, jm, ss))
    canonical.write_text(canonical.read_text(encoding="utf-8").replace('"flood_rank":2', '"flood_rank":3'),
                         encoding="utf-8")

    jm2 = Mock()
    _deploy(tmp_path, state, jm2, ss)
    assert _failed_code(jm2) == "DEPLOY_BLOCKED_ROUTING_CONTRACT"
    assert not (tmp_path / "data_runtime").exists()


def test_deploy_blocked_when_routing_missing(tmp_path):
    canonical = _canonical(tmp_path)
    state, jm = _state(canonical), Mock()
    _deploy(tmp_path, state, jm, _ss())
    assert _failed_code(jm) == "DEPLOY_BLOCKED_ROUTING_CONTRACT"
    assert not (tmp_path / "data_runtime").exists()

# 反映成功時の配置（runtime には routing artifact のみ・flat path へ書かない・atomic publish 経由）は
# tests/test_admin_atomic_publish_deploy.py::test_flood_migration_goes_through_atomic_wrapper_and_switches_current
# で検証する（管理画面反映の atomic publish 統合により flat copy 経路を廃止したため）。

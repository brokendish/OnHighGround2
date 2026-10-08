"""
HAZARD-ADMIN-ATOMIC-PUBLISH Phase 1（inland_flood / landslide / lowland_poor_drainage / tsunami）の
publish 契約テスト（pipeline 側は test_admin_atomic_publish_deploy.py）。

  - resolver は inland_flood / landslide / lowland_poor_drainage の active dataset の validated を解決
  - deploy_to_runtime.sh の registry overlay は normalized 一括配置の後・shelter の前、fail-closed
  - publish-status: publish_mode / current_version / artifact_present / deployable / runtime_status
  - tsunami は反映・戻すを拒否、atomic 対象の戻すも拒否
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.models.admin_dataset import DatasetDefinition, DatasetState, StorageStatus  # noqa: E402
from test_resolve_hazard_sources import _base_defn, _run_resolver  # noqa: E402

DEPLOY = (ROOT / "scripts/publish/deploy_to_runtime.sh").read_text(encoding="utf-8")


# ── resolver ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("layer_type,dataset_id,name", [
    ("inland_flood", "TOKYO-URBAN-001", "tokyo-urban-001.geojson"),
    ("landslide", "TOKYO-LANDSLIDE-001", "tokyo-landslide-001.geojson"),
    ("lowland_poor_drainage", "TOKYO-LOWLAND-POOR-DRAINAGE-001", "lowland_poor_drainage.geojson"),
])
def test_resolver_resolves_overlay_types(tmp_path, capsys, layer_type, dataset_id, name):
    vdir = tmp_path / "validated" / "tokyo" / layer_type
    vdir.mkdir(parents=True)
    src = vdir / name
    src.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    defs = [_base_defn(dataset_id=dataset_id, layer_type=layer_type, validated_storage_path=str(vdir),
                       runtime_path=f"data_runtime/backend/hazard/{layer_type}")]
    rc = _run_resolver(tmp_path, "tokyo", ["inland_flood", "landslide", "lowland_poor_drainage"],
                       {f"{layer_type}:tokyo": dataset_id}, defs)
    assert rc == 0
    assert capsys.readouterr().out.strip().split("\t") == [layer_type, dataset_id, str(src)]


def test_resolver_overlay_fails_closed_when_active_unresolvable(tmp_path, capsys):
    defs = [_base_defn(dataset_id="TOKYO-LANDSLIDE-001", layer_type="landslide",
                       validated_storage_path=str(tmp_path / "missing"),
                       runtime_path="data_runtime/backend/hazard/landslide")]
    rc = _run_resolver(tmp_path, "tokyo", ["inland_flood", "landslide", "lowland_poor_drainage"],
                       {"landslide:tokyo": "TOKYO-LANDSLIDE-001"}, defs)
    assert rc == 1 and capsys.readouterr().out == ""


# ── deploy_to_runtime.sh ────────────────────────────────────────────────────────

def test_overlay_block_runs_after_normalized_sections_and_before_shelters():
    lowland = DEPLOY.index('log_info "--- lowland_poor_drainage ---"')
    overlay = DEPLOY.index('log_info "--- inland_flood / landslide / lowland_poor_drainage (registry overlay) ---"')
    shelters = DEPLOY.index("# ─── backend: shelters")
    assert lowland < overlay < shelters
    block = DEPLOY[overlay:shelters]
    assert "--layer-type inland_flood" in block and "--layer-type landslide" in block
    assert "--layer-type lowland_poor_drainage" in block
    assert 'log_error "hazard source resolver (inland_flood/landslide/lowland_poor_drainage) が失敗しました' in block
    assert block.count("exit 1") >= 2  # resolver 失敗・解決 path 不在は fail-closed
    # 既存の normalized 一括配置（legacy companion 維持）を削除していない
    assert 'deploy_dir \\\n        "${NORMALIZED}/inland_flood"' in DEPLOY
    assert 'deploy_dir \\\n        "${NORMALIZED}/landslide"' in DEPLOY


def test_tsunami_publish_logic_unchanged():
    """tsunami は今回変更しない（registry 切替は OWNER 判断事項）。"""
    tsunami = DEPLOY[DEPLOY.index('log_info "--- tsunami ---"'):DEPLOY.index('log_info "--- inland_flood ---"')]
    assert 'filename="tsunami_${target}.geojson"' in tsunami
    assert "resolve_hazard_sources" not in tsunami


# ── API ─────────────────────────────────────────────────────────────────────────

def _defn(layer_type, dataset_id):
    return DatasetDefinition(
        dataset_id=dataset_id, region="tokyo", category=layer_type, display_name="t", description="t",
        hint_text="t", impact_scope="t", accepted_input_modes=[], accepted_extensions=[],
        max_browser_upload_mb=0, requires_normalize=False, requires_validation=False, requires_deploy=True,
        requires_osrm_rebuild=False, raw_storage_path=f"data_lake/raw/tokyo/{layer_type}",
        validated_storage_path=f"data_lake/validated/tokyo/{layer_type}",
        runtime_path=f"data_runtime/backend/hazard/{layer_type}", deploy_mode="copy_file", layer_type=layer_type,
    )


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    import hashlib
    from app.services import dataset_runtime_reconcile as drr
    rt = tmp_path / "runtime"
    v = rt / "versions" / "20261006T000000Z-00000001"
    rel = "backend/hazard/landslide/tokyo/tokyo-landslide-001.geojson"
    (v / rel).parent.mkdir(parents=True)
    (v / rel).write_text("{}")
    (v / "_manifest.json").write_text(json.dumps({"files": {rel: hashlib.sha256(b"{}").hexdigest()}}))
    os.symlink("versions/20261006T000000Z-00000001", rt / "current")
    monkeypatch.setenv("OHG2_DATA_RUNTIME_ROOT", str(rt))
    monkeypatch.setattr(drr, "_default_cache", drr.SourceShaCache(tmp_path / "sha_cache.json"))
    validated = tmp_path / "validated"
    for name in ("landslide/tokyo-landslide-001.geojson", "inland_flood/tokyo-urban-001.geojson"):
        (validated / name).parent.mkdir(parents=True, exist_ok=True)
        (validated / name).write_text("{}")
    from types import SimpleNamespace
    return SimpleNamespace(root=rt, validated=validated)


def _publish_status(defn, validated):
    from app.api import admin_datasets as api
    ds, ss = Mock(), Mock()
    ds.get.return_value = defn
    ss.init_from_definition.return_value = DatasetState(
        dataset_id=defn.dataset_id, storage_status=StorageStatus.stored,
        current_validated_path=validated, is_deployable=True)
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss):
        return asyncio.run(api.get_publish_status(defn.dataset_id))


def test_publish_status_atomic_published(runtime):
    st = _publish_status(_defn("landslide", "TOKYO-LANDSLIDE-001"),
                         str(runtime.validated / "landslide/tokyo-landslide-001.geojson"))
    assert st["publish_mode"] == "atomic"
    assert st["current_version"] == "20261006T000000Z-00000001"
    assert st["artifact_present"] is True and st["runtime_status"] == "published"
    assert st["matches_source"] is True and st["state_reconciled"] is True
    assert st["deployable"] is False  # 実行環境と一致 → 反映不要
    assert st["flood_routing_migration_required"] is False and st["migration_allowed_for_dataset"] is False


def test_publish_status_atomic_not_in_current(runtime):
    st = _publish_status(_defn("inland_flood", "TOKYO-URBAN-001"),
                         str(runtime.validated / "inland_flood/tokyo-urban-001.geojson"))
    assert st["publish_mode"] == "atomic"
    assert st["artifact_present"] is False and st["runtime_status"] == "not_published"


def test_publish_status_tsunami_unsupported(runtime):
    st = _publish_status(_defn("tsunami", "TOKYO-TSUNAMI-001"),
                         "/data_lake/validated/tokyo/tsunami/tokyo-tsunami-001.geojson")
    assert st["publish_mode"] == "unsupported" and st["runtime_status"] == "unsupported"
    assert st["artifact_present"] is False


def _api(fn_name, defn, **kw):
    from app.api import admin_datasets as api
    ds, ss, jm = Mock(), Mock(), Mock()
    ds.get.return_value = defn
    state = DatasetState(dataset_id=defn.dataset_id, storage_status=StorageStatus.stored, is_deployable=True,
                         backup_path="/x")
    ss.init_from_definition.return_value = state
    jm.has_running_job.return_value = False
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss), \
         patch.object(api, "get_job_manager", return_value=jm):
        res = asyncio.run(getattr(api, fn_name)(defn.dataset_id, Mock(state=Mock(request_id="r")),
                                                principal=Mock(actor_id="op"), **kw))
    jm.create.assert_not_called()
    return json.loads(res.body)["error_code"]


def test_api_tsunami_deploy_rejected(runtime):
    assert _api("deploy_dataset", _defn("tsunami", "TOKYO-TSUNAMI-001"), body=None) == "ATOMIC_PUBLISH_UNSUPPORTED"


@pytest.mark.parametrize("layer_type,dataset_id", [
    ("tsunami", "TOKYO-TSUNAMI-001"), ("landslide", "TOKYO-LANDSLIDE-001"),
    ("inland_flood", "TOKYO-URBAN-001"), ("lowland_poor_drainage", "TOKYO-LOWLAND-POOR-DRAINAGE-001"),
])
def test_api_flat_rollback_rejected(runtime, layer_type, dataset_id):
    assert _api("rollback_dataset", _defn(layer_type, dataset_id)) == "ROLLBACK_ATOMIC_PUBLISH_MANAGED"


def test_ui_type_lists_match_backend():
    from app.services import admin_atomic_publish as aap
    js = (ROOT / "operator/frontend-admin/datasets.js").read_text(encoding="utf-8")
    for t in aap.ATOMIC_PUBLISH_LAYER_TYPES:
        assert f'"{t}"' in js[js.index("const ATOMIC_PUBLISH_LAYER_TYPES"):js.index("const ATOMIC_PUBLISH_UNSUPPORTED_LAYER_TYPES")]
    assert 'const ATOMIC_PUBLISH_UNSUPPORTED_LAYER_TYPES = ["tsunami"];' in js
    assert aap.ATOMIC_PUBLISH_UNSUPPORTED_LAYER_TYPES == frozenset({"tsunami"})

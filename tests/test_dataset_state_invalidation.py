"""
test_dataset_state_invalidation.py — DATASET-STATE-INVALIDATION 再発防止テスト

Residual Finding Remediation 02 Phase B2:
dataset_definitions.json の runtime_path を修正しても、data_lake/admin/state/
{dataset_id}.json に永続化された state.current_runtime_path が無条件で
採用され続け、definition側の変更が runtime へ反映されない欠陥があった。

DatasetStateService.init_from_definition() に、persisted
current_runtime_path が現在の definition.runtime_path 契約と矛盾しない
（stale でない）ことを確認し、矛盾する場合のみ filesystem から再解決する
最小限の stale-state detection を追加した。既存の正常な state（definition
と矛盾しないもの）はこの分岐に入らず、従来どおり即座に load される。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def _make_service(tmp_path):
    from app.services.dataset_state_service import DatasetStateService

    return DatasetStateService(
        state_dir=tmp_path / "state", history_dir=tmp_path / "history"
    )


def _make_defn(tmp_path, layer_type: str, region: str, runtime_dir: Path, validated_dir: Path):
    from app.models.admin_dataset import DatasetDefinition

    return DatasetDefinition(
        dataset_id=f"TEST-{layer_type.upper()}-{region.upper()}-001",
        region=region,
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
        raw_storage_path=str(tmp_path / "raw" / region / layer_type),
        validated_storage_path=str(validated_dir),
        runtime_path=str(runtime_dir),
        deploy_mode="copy_file",
        layer_type=layer_type,
    )


def _write_state_json(state_dir: Path, dataset_id: str, payload: dict) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / f"{dataset_id}.json").write_text(json.dumps(payload), encoding="utf-8")


# ── A. 既存state + definitionと一致 → そのまま再利用（fast load） ─────────────

def test_matching_state_is_reused_without_rescan(tmp_path):
    from app.models.admin_dataset import DeployStatus
    import time

    validated_dir = tmp_path / "validated"
    validated_dir.mkdir()
    # flat runtime_path 契約の汎用検証には非 atomic type を使う
    # （storm_surge / flood / pseudo_inland_flood は管理画面反映が atomic publish 管理）
    validated_file = validated_dir / "landslide.geojson"
    validated_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    runtime_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "landslide"
    runtime_dir.mkdir(parents=True)
    deployed_file = runtime_dir / validated_file.name
    deployed_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    defn = _make_defn(tmp_path, "landslide", "tokyo", runtime_dir, validated_dir)
    service = _make_service(tmp_path)

    _write_state_json(tmp_path / "state", defn.dataset_id, {
        "dataset_id": defn.dataset_id,
        "current_validated_path": str(validated_file),
        "current_runtime_path": str(deployed_file),
        "deploy_status": DeployStatus.deployed.value,
        "updated_at": "2020-01-01T00:00:00",
    })

    # 再scanが起きないことを証明するため、元のvalidated fileより新しいmtimeの
    # decoy fileをvalidated_dirへ追加する。もし誤って
    # _infer_state_from_filesystem()が走れば、_find_representative_file()は
    # mtimeが新しい方（decoy）を選んでしまうはず。既存stateがそのまま
    # 再利用されるなら、current_validated_pathは元のfileのままである。
    time.sleep(0.01)
    decoy_file = validated_dir / "landslide_decoy.geojson"
    decoy_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    state = service.init_from_definition(defn)

    assert state.current_runtime_path == str(deployed_file)
    assert state.current_validated_path == str(validated_file), "decoyへ再解決されてはいけない"
    assert state.updated_at.isoformat().startswith("2020-01-01")


# ── B. stale state（旧runtime_path） → 再解決される ────────────────────────────

def test_stale_state_with_old_runtime_path_is_reresolved(tmp_path):
    from app.models.admin_dataset import DeployStatus

    validated_dir = tmp_path / "validated"
    validated_dir.mkdir()
    validated_file = validated_dir / "tokyo-lowland-poor-drainage-001.geojson"
    validated_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    old_runtime_dir = tmp_path / "data_runtime" / "frontend" / "tiles" / "tokyo" / "lowland_poor_drainage"
    old_runtime_dir.mkdir(parents=True)
    old_deployed_file = old_runtime_dir / validated_file.name
    old_deployed_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    new_runtime_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "lowland_poor_drainage"
    new_runtime_dir.mkdir(parents=True)
    new_deployed_file = new_runtime_dir / validated_file.name
    new_deployed_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    # definitionは新runtime_pathを指す（registry是正後の状態）
    defn = _make_defn(tmp_path, "lowland_poor_drainage", "tokyo", new_runtime_dir, validated_dir)
    service = _make_service(tmp_path)

    # persisted stateは旧runtime_pathを指したまま（是正前のstale cache）
    _write_state_json(tmp_path / "state", defn.dataset_id, {
        "dataset_id": defn.dataset_id,
        "current_validated_path": str(validated_file),
        "current_runtime_path": str(old_deployed_file),
        "deploy_status": DeployStatus.deployed.value,
        "updated_at": "2020-01-01T00:00:00",
    })

    state = service.init_from_definition(defn)

    assert state.current_runtime_path == str(new_deployed_file), (
        "stale stateはfilesystem再解決によりdefinitionの新runtime_path配下の"
        "artifactへ更新されるはず"
    )
    # 再解決後は永続化もされる
    reloaded = service.load(defn.dataset_id)
    assert reloaded.current_runtime_path == str(new_deployed_file)


# ── C. pseudo_inland_flood相当 ────────────────────────────────────────────────

def test_stale_state_pseudo_inland_flood_scenario(tmp_path):
    from app.models.admin_dataset import DeployStatus

    validated_dir = tmp_path / "validated"
    validated_dir.mkdir()
    validated_file = validated_dir / "pseudo_inland_flood.geojson"
    validated_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    old_runtime_dir = tmp_path / "data_runtime" / "frontend" / "tiles" / "tokyo" / "pseudo_inland_flood"
    old_runtime_dir.mkdir(parents=True)
    old_deployed_file = old_runtime_dir / validated_file.name
    old_deployed_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    new_runtime_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "pseudo_inland_flood"
    new_runtime_dir.mkdir(parents=True)
    new_deployed_file = new_runtime_dir / validated_file.name
    new_deployed_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    defn = _make_defn(tmp_path, "pseudo_inland_flood", "tokyo", new_runtime_dir, validated_dir)
    service = _make_service(tmp_path)

    _write_state_json(tmp_path / "state", defn.dataset_id, {
        "dataset_id": defn.dataset_id,
        "current_validated_path": str(validated_file),
        "current_runtime_path": str(old_deployed_file),
        "deploy_status": DeployStatus.deployed.value,
        "updated_at": "2020-01-01T00:00:00",
    })

    # pseudo_inland_flood は管理画面反映が atomic publish 管理になったため、flat path の
    # artifact では deployed と見なさない。current version に artifact が無い（ここでは
    # atomic runtime 自体が無い）→ stale として再推定され、deployable（未反映）になる。
    with patch("app.services.dataset_state_service.data_runtime_root", return_value=tmp_path / "no_runtime"), \
         patch("app.services.admin_atomic_publish.data_runtime_root", return_value=tmp_path / "no_runtime"):
        state = service.init_from_definition(defn)

    assert state.deploy_status == DeployStatus.deployable
    assert state.current_runtime_path is None
    assert new_deployed_file.exists()  # flat file は残るが deployed の根拠にしない


# ── D. lowland_poor_drainage（kanagawa）相当 ──────────────────────────────────

def test_stale_state_lowland_kanagawa_scenario(tmp_path):
    from app.models.admin_dataset import DeployStatus

    validated_dir = tmp_path / "validated"
    validated_dir.mkdir()
    validated_file = validated_dir / "kanagawa-lowland-poor-drainage-001.geojson"
    validated_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    old_runtime_dir = tmp_path / "data_runtime" / "frontend" / "tiles" / "kanagawa" / "lowland_poor_drainage"
    old_runtime_dir.mkdir(parents=True)
    old_deployed_file = old_runtime_dir / validated_file.name
    old_deployed_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    new_runtime_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "lowland_poor_drainage"
    new_runtime_dir.mkdir(parents=True)
    new_deployed_file = new_runtime_dir / validated_file.name
    new_deployed_file.write_text('{"type": "FeatureCollection", "features": [1]}', encoding="utf-8")

    defn = _make_defn(tmp_path, "lowland_poor_drainage", "kanagawa", new_runtime_dir, validated_dir)
    service = _make_service(tmp_path)

    _write_state_json(tmp_path / "state", defn.dataset_id, {
        "dataset_id": defn.dataset_id,
        "current_validated_path": str(validated_file),
        "current_runtime_path": str(old_deployed_file),
        "deploy_status": DeployStatus.deployed.value,
        "updated_at": "2020-01-01T00:00:00",
    })

    state = service.init_from_definition(defn)

    assert state.current_runtime_path == str(new_deployed_file)


# ── E. state file不存在 → 従来どおり自動検出 ──────────────────────────────────

def test_missing_state_file_falls_back_to_filesystem_inference(tmp_path):
    validated_dir = tmp_path / "validated"
    validated_dir.mkdir()
    validated_file = validated_dir / "inland_flood.geojson"
    validated_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    runtime_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "inland_flood"
    runtime_dir.mkdir(parents=True)
    deployed_file = runtime_dir / validated_file.name
    deployed_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    defn = _make_defn(tmp_path, "inland_flood", "tokyo", runtime_dir, validated_dir)
    service = _make_service(tmp_path)

    # state fileは一切作らない（初回起動相当）
    state = service.init_from_definition(defn)

    assert state.current_runtime_path == str(deployed_file)
    assert (tmp_path / "state" / f"{defn.dataset_id}.json").exists(), "推定結果がcacheされるはず"


# ── F. 正常stateを不要に破棄しない（re-inferをtriggerしない） ─────────────────

def test_valid_state_does_not_trigger_reinfer_save(tmp_path):
    from app.models.admin_dataset import DeployStatus
    from app.services.dataset_state_service import DatasetStateService

    validated_dir = tmp_path / "validated"
    validated_dir.mkdir()
    validated_file = validated_dir / "tsunami.geojson"
    validated_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    runtime_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "tsunami"
    runtime_dir.mkdir(parents=True)
    deployed_file = runtime_dir / validated_file.name
    deployed_file.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    defn = _make_defn(tmp_path, "tsunami", "tokyo", runtime_dir, validated_dir)
    service = _make_service(tmp_path)

    _write_state_json(tmp_path / "state", defn.dataset_id, {
        "dataset_id": defn.dataset_id,
        "current_validated_path": str(validated_file),
        "current_runtime_path": str(deployed_file),
        "deploy_status": DeployStatus.deployed.value,
        "updated_at": "2020-01-01T00:00:00",
    })

    with patch.object(DatasetStateService, "save") as mock_save:
        state = service.init_from_definition(defn)

    mock_save.assert_not_called()
    assert state.current_runtime_path == str(deployed_file)

"""
test_hazard_registry_backend_mirror.py — Residual Finding Remediation 02 再発防止テスト

pseudo_inland_flood / lowland_poor_drainage の HTTP 500 は、
dataset_definitions.json の runtime_path が backend-public から traverse
不可能な operator専用領域（data_runtime/frontend/tiles/...）を指していた
ことが根本原因だった（PermissionError）。

このテストは以下を再発防止として固定する:
  A. registry の runtime_path が正しい backend/hazard 契約を指すこと
  B. _reload_hazard_backend_mirror() が validated file と同じ basename で
     data_runtime/backend/hazard/{layer_type}/ へコピーすること
     （HazardDatasetService の copy_file deploy_mode 解決契約と一致させるため）
  C. HazardDatasetService が実際に runtime_path からファイルを開けること
     （mockではなく一時ディレクトリ上の実ファイルで検証する）
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[1]
    / "data_lake" / "registry" / "dataset_definitions.json"
)
_ACTIVE_MAPPINGS_PATH = (
    Path(__file__).resolve().parents[1]
    / "data_lake" / "admin" / "active_mappings.json"
)


# ── A. registry test ──────────────────────────────────────────────────────────

def _load_registry() -> list[dict]:
    with _REGISTRY_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _find_def(entries: list[dict], dataset_id: str) -> dict:
    for e in entries:
        if e.get("dataset_id") == dataset_id:
            return e
    raise AssertionError(f"dataset not found in registry: {dataset_id}")


def test_pseudo_inland_flood_tokyo_runtime_path_is_backend_hazard():
    entries = _load_registry()
    defn = _find_def(entries, "TOKYO-PSEUDO-INLAND-FLOOD-001")
    assert defn["runtime_path"] == "data_runtime/backend/hazard/pseudo_inland_flood"


def test_lowland_poor_drainage_tokyo_runtime_path_is_backend_hazard():
    entries = _load_registry()
    defn = _find_def(entries, "TOKYO-LOWLAND-POOR-DRAINAGE-001")
    assert defn["runtime_path"] == "data_runtime/backend/hazard/lowland_poor_drainage"


def test_lowland_poor_drainage_kanagawa_runtime_path_is_backend_hazard():
    entries = _load_registry()
    defn = _find_def(entries, "KANAGAWA-LOWLAND-POOR-DRAINAGE-001")
    assert defn["runtime_path"] == "data_runtime/backend/hazard/lowland_poor_drainage"


def test_pseudo_inland_flood_kanagawa_mapping_absent():
    """tokyo限定機能: pseudo_inland_flood:kanagawa はactive_mappings.jsonに登録しない。"""
    if not _ACTIVE_MAPPINGS_PATH.exists():
        return  # ローカル環境依存のfileが無い場合はスキップ相当
    with _ACTIVE_MAPPINGS_PATH.open("r", encoding="utf-8") as f:
        mappings = json.load(f)
    assert "pseudo_inland_flood:kanagawa" not in mappings


def test_runtime_paths_do_not_reference_operator_only_tiles_tree():
    """data_runtime/frontend/tiles（operator専用0750）を指すhazard datasetが無いこと。"""
    entries = _load_registry()
    for e in entries:
        runtime_path = e.get("runtime_path") or ""
        if e.get("category") == "hazard":
            assert "data_runtime/frontend/tiles" not in runtime_path, (
                f"{e.get('dataset_id')} runtime_path はbackend-publicがtraverse不可"
                f"の operator専用領域を指している: {runtime_path}"
            )


# ── B. pseudo pipeline test（_reload_hazard_backend_mirror） ──────────────────

def _make_defn(**overrides):
    from app.models.admin_dataset import DatasetDefinition

    base = dict(
        dataset_id="TEST-PSEUDO-001",
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
        raw_storage_path="data_lake/raw/tokyo/pseudo_inland_flood",
        validated_storage_path="data_lake/validated/tokyo/pseudo_inland_flood",
        runtime_path="data_runtime/backend/hazard/pseudo_inland_flood",
        deploy_mode="copy_file",
        layer_type="pseudo_inland_flood",
    )
    base.update(overrides)
    return DatasetDefinition(**base)


def test_reload_hazard_backend_mirror_copies_with_validated_basename(tmp_path):
    from app.services.pipeline_service import _reload_hazard_backend_mirror
    from app.models.admin_dataset import DatasetState

    src = tmp_path / "validated" / "pseudo_inland_flood.geojson"
    src.parent.mkdir(parents=True)
    src.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    backend_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "pseudo_inland_flood"
    defn = _make_defn(runtime_path=str(backend_dir))
    state = DatasetState(dataset_id=defn.dataset_id, current_validated_path=str(src))

    job = Mock()
    jm = Mock()

    with patch("app.services.pipeline_service._PROJECT_ROOT", tmp_path):
        _reload_hazard_backend_mirror(job, defn, state, jm)

    dest = backend_dir / "pseudo_inland_flood.geojson"
    assert dest.exists(), "コピー先が validated file と同じ basename で作成されていない"
    assert dest.read_text(encoding="utf-8") == src.read_text(encoding="utf-8")


def test_reload_hazard_backend_mirror_missing_source_is_noop(tmp_path):
    from app.services.pipeline_service import _reload_hazard_backend_mirror
    from app.models.admin_dataset import DatasetState

    backend_dir = tmp_path / "data_runtime" / "backend" / "hazard" / "pseudo_inland_flood"
    defn = _make_defn(runtime_path=str(backend_dir))
    state = DatasetState(dataset_id=defn.dataset_id, current_validated_path=None)

    job = Mock()
    jm = Mock()

    _reload_hazard_backend_mirror(job, defn, state, jm)

    assert not backend_dir.exists(), "sourceが無い場合はdestination directoryすら作成されないはず"
    jm.log.assert_called_once()
    assert "スキップ" in jm.log.call_args[0][1]


def test_reload_hazard_backend_mirror_applies_to_lowland_and_pseudo():
    from app.services.pipeline_service import _HAZARD_BACKEND_MIRROR_TYPES

    assert _HAZARD_BACKEND_MIRROR_TYPES == {"lowland_poor_drainage", "pseudo_inland_flood"}


# ── C. API/dataset integration test（実file・実service、mockでpathだけ返さない） ──

def _build_hazard_service_with_fixtures(tmp_path):
    """tmp_path配下に最小fixtureを配置し、実service一式（definition/state/
    active_mapping）をfixtureへ向けたHazardDatasetServiceを返す。"""
    from app.services.dataset_definition_service import DatasetDefinitionService
    from app.services.dataset_state_service import DatasetStateService
    from app.services.active_mapping_service import ActiveMappingService
    from app.services.hazard_dataset_service import HazardDatasetService

    def _write_fixture_dataset(dataset_id: str, region: str, layer_type: str, content: dict):
        validated_dir = tmp_path / "validated" / region / layer_type
        validated_dir.mkdir(parents=True, exist_ok=True)
        # lowlandはハイフン+連番、pseudoはtype名そのもの、というVPS実際の
        # 命名差（Phase A実測）を再現し、basename一致ロジックを厳密に検証する。
        basename = (
            "pseudo_inland_flood.geojson" if layer_type == "pseudo_inland_flood"
            else f"{region}-lowland-poor-drainage-001.geojson"
        )
        validated_file = validated_dir / basename
        validated_file.write_text(json.dumps(content), encoding="utf-8")

        runtime_dir = tmp_path / "data_runtime" / "backend" / "hazard" / layer_type
        runtime_dir.mkdir(parents=True, exist_ok=True)
        # _reload_hazard_backend_mirror が実際に行うのと同じ規約
        # （validated fileと同名でコピー）を模してdeployed済み状態を再現する。
        (runtime_dir / basename).write_text(json.dumps(content), encoding="utf-8")

        return {
            "dataset_id": dataset_id,
            "region": region,
            "category": "hazard",
            "display_name": dataset_id,
            "description": "test",
            "hint_text": "test",
            "impact_scope": "test",
            "accepted_input_modes": [],
            "accepted_extensions": [],
            "max_browser_upload_mb": 0,
            "requires_normalize": False,
            "requires_validation": True,
            "requires_deploy": True,
            "requires_osrm_rebuild": False,
            "raw_storage_path": str(tmp_path / "raw" / region / layer_type),
            "validated_storage_path": str(validated_dir),
            "runtime_path": str(runtime_dir),
            "deploy_mode": "copy_file",
            "layer_type": layer_type,
        }

    definitions = [
        _write_fixture_dataset("TEST-PSEUDO-TOKYO-001", "tokyo", "pseudo_inland_flood",
                                {"type": "FeatureCollection", "features": [{"id": "pseudo-tokyo"}]}),
        _write_fixture_dataset("TEST-LOWLAND-TOKYO-001", "tokyo", "lowland_poor_drainage",
                                {"type": "FeatureCollection", "features": [{"id": "lowland-tokyo"}]}),
        _write_fixture_dataset("TEST-LOWLAND-KANAGAWA-001", "kanagawa", "lowland_poor_drainage",
                                {"type": "FeatureCollection", "features": [{"id": "lowland-kanagawa"}]}),
    ]

    definitions_path = tmp_path / "dataset_definitions.json"
    definitions_path.write_text(json.dumps(definitions), encoding="utf-8")

    mappings_path = tmp_path / "active_mappings.json"
    mappings = {
        "pseudo_inland_flood:tokyo": "TEST-PSEUDO-TOKYO-001",
        "lowland_poor_drainage:tokyo": "TEST-LOWLAND-TOKYO-001",
        "lowland_poor_drainage:kanagawa": "TEST-LOWLAND-KANAGAWA-001",
        # pseudo_inland_flood:kanagawa は意図的に未登録（404 contract control）
    }
    mappings_path.write_text(json.dumps(mappings), encoding="utf-8")

    definition_service = DatasetDefinitionService(definitions_path=definitions_path)
    state_service = DatasetStateService(
        state_dir=tmp_path / "state", history_dir=tmp_path / "history"
    )
    mapping_service = ActiveMappingService(mappings_path=mappings_path)

    return definition_service, state_service, mapping_service, HazardDatasetService()


def test_pseudo_tokyo_resolves_via_fixed_registry_path(tmp_path):
    definition_service, state_service, mapping_service, service = _build_hazard_service_with_fixtures(tmp_path)

    with patch("app.services.hazard_dataset_service.get_definition_service", return_value=definition_service), \
         patch("app.services.hazard_dataset_service.get_state_service", return_value=state_service), \
         patch("app.services.hazard_dataset_service.get_active_mapping_service", return_value=mapping_service):
        result = service.get_active_hazard_geojson("pseudo_inland_flood", "tokyo")

    assert result["type"] == "FeatureCollection"
    assert result["features"][0]["id"] == "pseudo-tokyo"


def test_lowland_tokyo_resolves_via_fixed_registry_path(tmp_path):
    definition_service, state_service, mapping_service, service = _build_hazard_service_with_fixtures(tmp_path)

    with patch("app.services.hazard_dataset_service.get_definition_service", return_value=definition_service), \
         patch("app.services.hazard_dataset_service.get_state_service", return_value=state_service), \
         patch("app.services.hazard_dataset_service.get_active_mapping_service", return_value=mapping_service):
        result = service.get_active_hazard_geojson("lowland_poor_drainage", "tokyo")

    assert result["features"][0]["id"] == "lowland-tokyo"


def test_lowland_kanagawa_resolves_via_fixed_registry_path(tmp_path):
    definition_service, state_service, mapping_service, service = _build_hazard_service_with_fixtures(tmp_path)

    with patch("app.services.hazard_dataset_service.get_definition_service", return_value=definition_service), \
         patch("app.services.hazard_dataset_service.get_state_service", return_value=state_service), \
         patch("app.services.hazard_dataset_service.get_active_mapping_service", return_value=mapping_service):
        result = service.get_active_hazard_geojson("lowland_poor_drainage", "kanagawa")

    assert result["features"][0]["id"] == "lowland-kanagawa"


def test_pseudo_kanagawa_raises_keyerror_404_contract(tmp_path):
    """未登録regionはHTTP 500ではなく404契約（KeyError）を維持すること。"""
    definition_service, state_service, mapping_service, service = _build_hazard_service_with_fixtures(tmp_path)

    with patch("app.services.hazard_dataset_service.get_definition_service", return_value=definition_service), \
         patch("app.services.hazard_dataset_service.get_state_service", return_value=state_service), \
         patch("app.services.hazard_dataset_service.get_active_mapping_service", return_value=mapping_service):
        try:
            service.get_active_hazard_geojson("pseudo_inland_flood", "kanagawa")
            assert False, "KeyErrorが送出されるはず"
        except KeyError as exc:
            assert "not registered" in str(exc)

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.active_mapping_service import get_active_mapping_service
from app.services.dataset_definition_service import get_definition_service
from app.services.dataset_state_service import get_state_service


class HazardDatasetService:
    """Provide active hazard datasets resolved from the admin dataset foundation."""

    HAZARD_LAYER_TYPES = {
        "tsunami",
        "flood",
        "storm_surge",
        "inland_flood",
        "landslide",
        "pseudo_inland_flood",
    }

    def _load_json(self, path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid GeoJSON in {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"GeoJSON root must be an object: {path}")
        return data

    def _resolve_active_dataset(self, hazard_type: str, region_code: str):
        if hazard_type not in self.HAZARD_LAYER_TYPES:
            raise KeyError(f"Unsupported hazard_type: {hazard_type}")

        dataset_id = get_active_mapping_service().get_active(hazard_type, region_code)
        if not dataset_id:
            raise KeyError(f"Active dataset is not registered: {hazard_type}:{region_code}")

        defn = get_definition_service().get(dataset_id)
        if defn is None:
            raise KeyError(f"Dataset definition not found: {dataset_id}")

        state = get_state_service().init_from_definition(defn)
        active_path = (
            state.current_runtime_path
            or state.current_validated_path
            or state.current_normalized_path
        )
        if not active_path:
            raise FileNotFoundError(f"Active dataset has no resolved artifact: {dataset_id}")

        return dataset_id, defn, state, Path(active_path)

    def get_active_hazard_geojson(self, hazard_type: str, region_code: str) -> Dict[str, Any]:
        _, _, _, geojson_path = self._resolve_active_dataset(hazard_type, region_code)
        return self._load_json(geojson_path)

    def get_active_hazard_meta(self, hazard_type: str, region_code: str) -> Dict[str, Any]:
        dataset_id, defn, state, geojson_path = self._resolve_active_dataset(hazard_type, region_code)
        return {
            "dataset_id": dataset_id,
            "layer_type": defn.layer_type,
            "region": defn.region,
            "display_name": defn.display_name,
            "deploy_status": state.deploy_status,
            "artifact_path": str(geojson_path),
            "is_active": True,
        }

    def list_active_hazard_datasets(self) -> List[Dict[str, Any]]:
        active_datasets: List[Dict[str, Any]] = []
        ds = get_definition_service()
        ss = get_state_service()
        for mapping in get_active_mapping_service().list_all():
            if mapping["layer_type"] not in self.HAZARD_LAYER_TYPES:
                continue
            dataset_id = mapping["dataset_id"]
            defn = ds.get(dataset_id)
            if defn is None:
                continue
            state = ss.init_from_definition(defn)
            active_datasets.append(
                {
                    "registry_key": f"{mapping['layer_type']}:{mapping['region']}",
                    "dataset_id": dataset_id,
                    "dataset_type": "hazard",
                    "hazard_type": defn.layer_type,
                    "region_code": defn.region,
                    "region_name": defn.region,
                    "title": defn.display_name,
                    "status": state.deploy_status,
                    "is_active": True,
                    "path": state.current_runtime_path or state.current_validated_path or state.current_normalized_path,
                }
            )

        return active_datasets

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.services.dataset_registry import DatasetRegistry


class HazardDatasetService:
    """Provide active hazard datasets resolved from registry files."""

    def __init__(self, registry: Optional[DatasetRegistry] = None) -> None:
        self.registry = registry or DatasetRegistry()

    def _load_json(self, path: Path) -> Dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid GeoJSON in {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise ValueError(f"GeoJSON root must be an object: {path}")
        return data

    def get_active_hazard_geojson(self, hazard_type: str, region_code: str) -> Dict[str, Any]:
        dataset_id = self.registry.resolve_active_dataset_id("hazard", hazard_type, region_code)
        geojson_path = self.registry.resolve_normalized_file_path(dataset_id)
        return self._load_json(geojson_path)

    def get_active_hazard_meta(self, hazard_type: str, region_code: str) -> Dict[str, Any]:
        dataset_id = self.registry.resolve_active_dataset_id("hazard", hazard_type, region_code)
        return self.registry.load_dataset_meta(dataset_id)

    def list_active_hazard_datasets(self) -> List[Dict[str, Any]]:
        active_map = self.registry.load_active_map()
        dataset_index = {
            record.get("dataset_id"): record
            for record in self.registry.load_dataset_index()
            if isinstance(record, dict) and record.get("dataset_id")
        }

        active_datasets: List[Dict[str, Any]] = []
        for key, dataset_id in sorted(active_map.items()):
            if not key.startswith("hazard:"):
                continue

            meta = self.registry.load_dataset_meta(dataset_id)
            record = dataset_index.get(dataset_id, {})
            active_datasets.append(
                {
                    "registry_key": key,
                    "dataset_id": dataset_id,
                    "dataset_type": meta.get("dataset_type"),
                    "hazard_type": meta.get("hazard_type"),
                    "region_code": meta.get("region_code"),
                    "region_name": meta.get("region_name"),
                    "title": meta.get("title"),
                    "version": meta.get("version"),
                    "status": meta.get("status"),
                    "is_active": meta.get("is_active"),
                    "path": record.get("path"),
                    "files": meta.get("files", {}),
                }
            )

        return active_datasets

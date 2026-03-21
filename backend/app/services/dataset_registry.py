import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class DatasetRegistry:
    """Resolve active hazard datasets from filesystem-based registry files."""

    def __init__(self, data_root: Optional[Path] = None) -> None:
        project_root = Path(__file__).resolve().parents[3]
        self.project_root = project_root
        self.data_root = data_root.resolve() if data_root else (project_root / "data").resolve()
        self.registry_root = self.data_root / "registry"
        self.datasets_root = self.data_root / "datasets"

    def _load_json(self, path: Path) -> Any:
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {path}")
        try:
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    def _resolve_dataset_dir_from_record(self, record: Dict[str, Any]) -> Path:
        raw_path = record.get("path")
        if not raw_path:
            raise KeyError(f"Dataset record missing path: {record}")

        dataset_dir = Path(raw_path)
        if not dataset_dir.is_absolute():
            dataset_dir = (self.project_root / dataset_dir).resolve()

        if not dataset_dir.exists():
            raise FileNotFoundError(f"Dataset directory not found: {dataset_dir}")
        return dataset_dir

    def load_active_map(self) -> Dict[str, str]:
        path = self.registry_root / "active_map.json"
        data = self._load_json(path)
        if not isinstance(data, dict):
            raise ValueError(f"active_map.json must be an object: {path}")
        return data

    def load_dataset_index(self) -> List[Dict[str, Any]]:
        path = self.registry_root / "datasets.json"
        data = self._load_json(path)
        if not isinstance(data, list):
            raise ValueError(f"datasets.json must be an array: {path}")
        return data

    def resolve_active_dataset_id(self, dataset_type: str, hazard_type: str, region_code: str) -> str:
        active_map = self.load_active_map()
        key = f"{dataset_type}:{hazard_type}:{region_code}"
        dataset_id = active_map.get(key)
        if not dataset_id:
            raise KeyError(f"Active dataset is not registered: {key}")
        return dataset_id

    def get_dataset_record(self, dataset_id: str) -> Dict[str, Any]:
        for record in self.load_dataset_index():
            if record.get("dataset_id") == dataset_id:
                return record
        raise KeyError(f"Dataset is not indexed: {dataset_id}")

    def load_dataset_meta(self, dataset_id: str) -> Dict[str, Any]:
        record = self.get_dataset_record(dataset_id)
        dataset_dir = self._resolve_dataset_dir_from_record(record)
        meta_path = dataset_dir / "meta.json"
        data = self._load_json(meta_path)
        if not isinstance(data, dict):
            raise ValueError(f"meta.json must be an object: {meta_path}")
        return data

    def resolve_normalized_file_path(self, dataset_id: str) -> Path:
        meta = self.load_dataset_meta(dataset_id)
        files = meta.get("files")
        if not isinstance(files, dict):
            raise KeyError(f"Dataset meta missing files: {dataset_id}")

        normalized_rel = files.get("normalized")
        if not normalized_rel:
            raise KeyError(f"Dataset meta missing files.normalized: {dataset_id}")

        record = self.get_dataset_record(dataset_id)
        dataset_dir = self._resolve_dataset_dir_from_record(record)
        normalized_path = (dataset_dir / normalized_rel).resolve()
        if not normalized_path.exists():
            raise FileNotFoundError(f"Normalized GeoJSON not found: {normalized_path}")
        return normalized_path

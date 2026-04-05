"""
dataset_definition_service.py — データセット定義の読み込みサービス

data_lake/registry/dataset_definitions.json を Single Source of Truth として読み込む。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.models.admin_dataset import DatasetDefinition

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFINITIONS_PATH = _PROJECT_ROOT / "data_lake" / "registry" / "dataset_definitions.json"


class DatasetDefinitionService:
    """データセット定義を読み込み、キャッシュして提供する。"""

    def __init__(self, definitions_path: Optional[Path] = None) -> None:
        self._path = definitions_path or _DEFINITIONS_PATH
        self._cache: Optional[Dict[str, DatasetDefinition]] = None

    def _load(self) -> Dict[str, DatasetDefinition]:
        if not self._path.exists():
            logger.warning("dataset_definitions.json not found: %s", self._path)
            return {}
        with self._path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        result: Dict[str, DatasetDefinition] = {}
        for item in raw:
            try:
                defn = DatasetDefinition(**item)
                result[defn.dataset_id] = defn
            except Exception as exc:
                logger.error("Failed to parse dataset definition %s: %s", item.get("dataset_id"), exc)
        return result

    def _get_cache(self) -> Dict[str, DatasetDefinition]:
        if self._cache is None:
            self._cache = self._load()
        return self._cache

    def reload(self) -> None:
        """キャッシュを破棄して再読み込みする。"""
        self._cache = None

    def list_all(self) -> List[DatasetDefinition]:
        return list(self._get_cache().values())

    def get(self, dataset_id: str) -> Optional[DatasetDefinition]:
        return self._get_cache().get(dataset_id)

    def get_or_raise(self, dataset_id: str) -> DatasetDefinition:
        defn = self.get(dataset_id)
        if defn is None:
            raise KeyError(dataset_id)
        return defn

    def list_by_region(self, region: str) -> List[DatasetDefinition]:
        return [d for d in self._get_cache().values() if d.region == region]

    def list_regions(self) -> List[str]:
        return sorted({d.region for d in self._get_cache().values()})


# シングルトン
_instance: Optional[DatasetDefinitionService] = None


def get_definition_service() -> DatasetDefinitionService:
    global _instance
    if _instance is None:
        _instance = DatasetDefinitionService()
    return _instance

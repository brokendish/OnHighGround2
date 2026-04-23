"""
config_definition_service.py — 管理対象設定の定義読み込みサービス
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from app.models.admin_config import ConfigDefinition

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFINITIONS_PATH = _PROJECT_ROOT / "data_lake" / "registry" / "config_definitions.json"


class ConfigDefinitionService:
    """config_definitions.json を読み込み、キー単位で参照できるようにする。"""

    def __init__(self, definitions_path: Optional[Path] = None) -> None:
        self._path = definitions_path or _DEFINITIONS_PATH
        self._cache: Optional[Dict[str, ConfigDefinition]] = None

    def _load(self) -> Dict[str, ConfigDefinition]:
        if not self._path.exists():
            logger.warning("config_definitions.json not found: %s", self._path)
            return {}
        with self._path.open("r", encoding="utf-8") as f:
            raw = json.load(f)

        result: Dict[str, ConfigDefinition] = {}
        for item in raw:
            try:
                defn = ConfigDefinition(**item)
                result[defn.key] = defn
            except Exception as exc:
                logger.error("Failed to parse config definition %s: %s", item.get("key"), exc)
        return result

    def _get_cache(self) -> Dict[str, ConfigDefinition]:
        if self._cache is None:
            self._cache = self._load()
        return self._cache

    def reload(self) -> None:
        self._cache = None

    def list_all(self) -> List[ConfigDefinition]:
        return sorted(
            self._get_cache().values(),
            key=lambda d: (d.category, d.ui_order, d.key),
        )

    def get(self, key: str) -> Optional[ConfigDefinition]:
        return self._get_cache().get(key)


_instance: Optional[ConfigDefinitionService] = None


def get_config_definition_service() -> ConfigDefinitionService:
    global _instance
    if _instance is None:
        _instance = ConfigDefinitionService()
    return _instance

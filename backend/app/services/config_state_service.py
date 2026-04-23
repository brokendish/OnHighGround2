"""
config_state_service.py — 設定の現在値・履歴の永続管理サービス
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.admin_config import (
    ConfigDefinition,
    ConfigHistoryEntry,
    ConfigItem,
    ConfigValueType,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SYSTEM_DIR = _PROJECT_ROOT / "data_runtime" / "system"
_OVERRIDES_PATH = _SYSTEM_DIR / "config_overrides.json"
_HISTORY_PATH = _SYSTEM_DIR / "config_history.json"
_MAX_HISTORY = 500


class ConfigValidationError(ValueError):
    def __init__(self, message: str, error_code: str = "CONFIG_VALIDATION_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code


class ConfigStateService:
    """override > default の現在値解決と更新履歴の追記を担当する。"""

    def __init__(
        self,
        overrides_path: Optional[Path] = None,
        history_path: Optional[Path] = None,
    ) -> None:
        self._overrides_path = overrides_path or _OVERRIDES_PATH
        self._history_path = history_path or _HISTORY_PATH
        self._overrides_path.parent.mkdir(parents=True, exist_ok=True)
        self._history_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_overrides(self) -> Dict[str, Any]:
        if not self._overrides_path.exists():
            return {}
        with self._overrides_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}

    def _save_overrides(self, overrides: Dict[str, Any]) -> None:
        with self._overrides_path.open("w", encoding="utf-8") as f:
            json.dump(overrides, f, ensure_ascii=False, indent=2)

    def _load_history(self) -> List[ConfigHistoryEntry]:
        if not self._history_path.exists():
            return []
        with self._history_path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            return []
        return [ConfigHistoryEntry(**item) for item in raw]

    def _save_history(self, history: List[ConfigHistoryEntry]) -> None:
        trimmed = history[-_MAX_HISTORY:]
        with self._history_path.open("w", encoding="utf-8") as f:
            json.dump(
                [entry.model_dump(mode="json") for entry in trimmed],
                f,
                ensure_ascii=False,
                indent=2,
                default=str,
            )

    def _latest_updated_at_by_key(self) -> Dict[str, datetime]:
        updated: Dict[str, datetime] = {}
        for entry in self._load_history():
            current = updated.get(entry.key)
            if current is None or entry.updated_at > current:
                updated[entry.key] = entry.updated_at
        return updated

    def resolve_value(self, defn: ConfigDefinition) -> Any:
        overrides = self._load_overrides()
        return overrides.get(defn.key, defn.default_value)

    def list_items(self, definitions: List[ConfigDefinition]) -> List[ConfigItem]:
        overrides = self._load_overrides()
        updated_at_by_key = self._latest_updated_at_by_key()
        items: List[ConfigItem] = []
        for defn in definitions:
            items.append(self._build_item(
                defn,
                current_value=overrides.get(defn.key, defn.default_value),
                updated_at=updated_at_by_key.get(defn.key),
            ))
        return items

    def get_item(self, defn: ConfigDefinition) -> ConfigItem:
        updated_at_by_key = self._latest_updated_at_by_key()
        return self._build_item(
            defn,
            current_value=self.resolve_value(defn),
            updated_at=updated_at_by_key.get(defn.key),
        )

    def _build_item(
        self,
        defn: ConfigDefinition,
        current_value: Any,
        updated_at: Optional[datetime],
    ) -> ConfigItem:
        return ConfigItem(
            key=defn.key,
            category=defn.category,
            label=defn.label,
            type=defn.type,
            default_value=defn.default_value,
            current_value=current_value,
            description=defn.description,
            min=defn.min,
            max=defn.max,
            editable=defn.editable,
            apply_mode=defn.apply_mode,
            ui_order=defn.ui_order,
            updated_at=updated_at,
        )

    def validate_value(self, defn: ConfigDefinition, value: Any) -> Any:
        if not defn.editable:
            raise ConfigValidationError("この設定は編集できません。", "CONFIG_NOT_EDITABLE")

        if defn.type == ConfigValueType.integer:
            if isinstance(value, bool):
                raise ConfigValidationError("整数を入力してください。")
            try:
                normalized = int(value)
            except (TypeError, ValueError) as exc:
                raise ConfigValidationError("整数を入力してください。") from exc
            if isinstance(value, float) and not value.is_integer():
                raise ConfigValidationError("整数を入力してください。")
            self._validate_range(defn, normalized)
            return normalized

        if defn.type == ConfigValueType.float:
            if isinstance(value, bool):
                raise ConfigValidationError("数値を入力してください。")
            try:
                normalized = float(value)
            except (TypeError, ValueError) as exc:
                raise ConfigValidationError("数値を入力してください。") from exc
            self._validate_range(defn, normalized)
            return normalized

        if defn.type == ConfigValueType.boolean:
            if not isinstance(value, bool):
                raise ConfigValidationError("true または false を指定してください。")
            return value

        if defn.type == ConfigValueType.string:
            if not isinstance(value, str):
                raise ConfigValidationError("文字列を入力してください。")
            return value

        raise ConfigValidationError("未対応の設定型です。")

    def _validate_range(self, defn: ConfigDefinition, value: float) -> None:
        if defn.min is not None and value < defn.min:
            raise ConfigValidationError(f"{defn.min} 以上の値を入力してください。")
        if defn.max is not None and value > defn.max:
            raise ConfigValidationError(f"{defn.max} 以下の値を入力してください。")

    def update_value(self, defn: ConfigDefinition, raw_value: Any) -> tuple[Any, Any, datetime, ConfigItem]:
        new_value = self.validate_value(defn, raw_value)
        overrides = self._load_overrides()
        old_value = overrides.get(defn.key, defn.default_value)
        updated_at = datetime.now(timezone.utc)

        overrides[defn.key] = new_value
        self._save_overrides(overrides)

        history = self._load_history()
        history.append(ConfigHistoryEntry(
            key=defn.key,
            old_value=old_value,
            new_value=new_value,
            updated_at=updated_at,
        ))
        self._save_history(history)

        return old_value, new_value, updated_at, self._build_item(defn, new_value, updated_at)

    def list_history(self, key: Optional[str] = None, limit: int = 100) -> List[ConfigHistoryEntry]:
        history = self._load_history()
        if key:
            history = [entry for entry in history if entry.key == key]
        history = sorted(history, key=lambda entry: entry.updated_at, reverse=True)
        return history[:max(1, min(limit, _MAX_HISTORY))]


_instance: Optional[ConfigStateService] = None


def get_config_state_service() -> ConfigStateService:
    global _instance
    if _instance is None:
        _instance = ConfigStateService()
    return _instance

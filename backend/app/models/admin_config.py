"""
admin_config.py — 管理画面の設定管理モデル定義
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConfigValueType(str, Enum):
    integer = "integer"
    float = "float"
    boolean = "boolean"
    string = "string"


class ConfigApplyMode(str, Enum):
    reload = "reload"
    immediate = "immediate"
    live = "live"


class ConfigDefinition(BaseModel):
    key: str
    category: str
    label: str
    type: ConfigValueType
    default_value: Any
    description: str = ""
    options: Optional[list[str]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    editable: bool = True
    apply_mode: ConfigApplyMode = ConfigApplyMode.reload
    ui_order: int = 100


class ConfigItem(BaseModel):
    key: str
    category: str
    label: str
    type: ConfigValueType
    default_value: Any
    current_value: Any
    description: str = ""
    options: Optional[list[str]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    editable: bool = True
    apply_mode: ConfigApplyMode = ConfigApplyMode.reload
    ui_order: int = 100
    updated_at: Optional[datetime] = None


class ConfigUpdateRequest(BaseModel):
    value: Any = Field(..., description="更新後の設定値")


class ConfigUpdateResponse(BaseModel):
    key: str
    old_value: Any
    new_value: Any
    updated_at: datetime
    item: ConfigItem


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConfigHistoryEntry(BaseModel):
    key: str
    old_value: Any
    new_value: Any
    updated_at: datetime = Field(default_factory=_utc_now)

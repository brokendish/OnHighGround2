import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.admin_config import ConfigDefinition
from app.services.config_state_service import (
    ConfigStateService,
    ConfigValidationError,
)


def _service(tmp_path: Path) -> ConfigStateService:
    return ConfigStateService(
        overrides_path=tmp_path / "config_overrides.json",
        history_path=tmp_path / "config_history.json",
    )


def _integer_def(**overrides) -> ConfigDefinition:
    data = {
        "key": "navigation.arrival_distance_m",
        "category": "navigation",
        "label": "到着判定距離",
        "type": "integer",
        "default_value": 12,
        "min": 1,
        "max": 50,
        "editable": True,
        "apply_mode": "reload",
        "ui_order": 10,
    }
    data.update(overrides)
    return ConfigDefinition(**data)


def test_config_update_persists_override_and_history(tmp_path):
    svc = _service(tmp_path)
    defn = _integer_def()

    old_value, new_value, updated_at, item = svc.update_value(defn, 15)

    assert old_value == 12
    assert new_value == 15
    assert item.current_value == 15
    assert item.updated_at == updated_at
    assert svc.resolve_value(defn) == 15

    history = svc.list_history()
    assert len(history) == 1
    assert history[0].key == defn.key
    assert history[0].old_value == 12
    assert history[0].new_value == 15


def test_config_update_rejects_out_of_range(tmp_path):
    svc = _service(tmp_path)
    defn = _integer_def()

    with pytest.raises(ConfigValidationError):
        svc.update_value(defn, 100)


def test_config_update_rejects_wrong_type(tmp_path):
    svc = _service(tmp_path)
    defn = _integer_def()

    with pytest.raises(ConfigValidationError):
        svc.update_value(defn, "not-a-number")


def test_config_update_rejects_not_editable(tmp_path):
    svc = _service(tmp_path)
    defn = _integer_def(editable=False)

    with pytest.raises(ConfigValidationError):
        svc.update_value(defn, 10)

"""
test_hazard_meta_tileset_exception_hardening.py —
HAZARD-META-EXCEPTION-HARDENING-GAP remediation テスト。

hazards.py::get_active_hazard_meta() 内の _find_tileset_for_region() 呼び
出しは、従来try/exceptの外にあり、PermissionError/OSError/sqlite3.Error/
予期しない例外がapplication-levelで一切処理されず、FastAPI/Starlette
のdefault 500 handlerへ素通りしていた（HAZARD-META-TILESET-READ-
PERMISSION-GAPの実障害時、まさにこの経路でPermissionErrorが発生して
いた。debug=falseによりraw leakは実証されなかったが、安全性が
framework既定動作依存になっていた）。

この修正は _find_tileset_for_region() 呼び出しだけを局所的な
`except Exception` で囲み、既存の _HAZARD_INTERNAL_ERROR_DETAIL
（"Hazard data is temporarily unavailable"、既存のgeneric error wording
と整合させるため新しい文言は追加しない）で500化し、
logger.exception()でserver-side診断情報を残す。

route全体は囲んでいない——meta取得自体（hazard_dataset_service呼び出し）
の既存try/except・404契約・正常系schemaは一切変更していない。
"""
from __future__ import annotations

import logging
import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from _testclient_compat import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import hazards  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app, raise_server_exceptions=False)


_FAKE_META = {
    "dataset_id": "TOKYO-URBAN-001", "layer_type": "inland_flood", "region": "tokyo",
    "display_name": "d", "deploy_status": "deployed", "artifact_path": "/x", "is_active": True,
}


def _with_meta_ok_and_tileset_side_effect(exc):
    return patch.object(hazards, "_find_tileset_for_region", side_effect=exc), \
        patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=dict(_FAKE_META))


# ── A. PermissionError injection ──────────────────────────────────────────────

def test_A_permission_error_returns_500_generic_no_raw_path(client, caplog):
    leaked_path = "/data_runtime/frontend/tiles/tokyo/inland_flood"
    exc = PermissionError(13, "Permission denied")
    exc.filename = leaked_path

    p_tileset, p_meta = _with_meta_ok_and_tileset_side_effect(exc)
    with p_tileset, p_meta, caplog.at_level(logging.ERROR):
        resp = client.get("/api/hazards/inland_flood/tokyo/meta")

    assert resp.status_code == 500
    assert resp.json() == {"detail": hazards._HAZARD_INTERNAL_ERROR_DETAIL}
    assert leaked_path not in resp.text
    assert "Permission denied" not in resp.text
    assert "Errno" not in resp.text


# ── B. OSError injection ───────────────────────────────────────────────────────

def test_B_oserror_returns_500_no_errno_or_path(client):
    leaked_path = "/data_runtime/frontend/tiles/kanagawa/flood"
    exc = OSError(f"[Errno 13] Permission denied: '{leaked_path}'")

    p_tileset, p_meta = _with_meta_ok_and_tileset_side_effect(exc)
    with p_tileset, p_meta:
        resp = client.get("/api/hazards/flood/kanagawa/meta")

    assert resp.status_code == 500
    assert resp.json() == {"detail": hazards._HAZARD_INTERNAL_ERROR_DETAIL}
    assert leaked_path not in resp.text
    assert "Errno" not in resp.text
    assert "Permission denied" not in resp.text


# ── C. sqlite3.DatabaseError injection ────────────────────────────────────────

def test_C_sqlite_error_returns_500_no_raw_sqlite_detail(client):
    exc = sqlite3.DatabaseError("file is not a database: /data_runtime/frontend/tiles/tokyo/flood/corrupt.mbtiles")

    p_tileset, p_meta = _with_meta_ok_and_tileset_side_effect(exc)
    with p_tileset, p_meta:
        resp = client.get("/api/hazards/flood/tokyo/meta")

    assert resp.status_code == 500
    assert resp.json() == {"detail": hazards._HAZARD_INTERNAL_ERROR_DETAIL}
    assert "sqlite" not in resp.text.lower()
    assert "/data_runtime/" not in resp.text
    assert ".mbtiles" not in resp.text


# ── D. unexpected RuntimeError ─────────────────────────────────────────────────

def test_D_unexpected_runtime_error_returns_500_no_raw_message(client):
    exc = RuntimeError("unexpected internal marker XYZZY-SECRET-DETAIL")

    p_tileset, p_meta = _with_meta_ok_and_tileset_side_effect(exc)
    with p_tileset, p_meta:
        resp = client.get("/api/hazards/storm_surge/tokyo/meta")

    assert resp.status_code == 500
    assert resp.json() == {"detail": hazards._HAZARD_INTERNAL_ERROR_DETAIL}
    assert "XYZZY-SECRET-DETAIL" not in resp.text


# ── E. logger.exception が呼ばれ、context（hazard_type/region/operation）を含む ──

def test_E_logger_exception_called_with_context(client, caplog):
    exc = PermissionError("Permission denied")

    p_tileset, p_meta = _with_meta_ok_and_tileset_side_effect(exc)
    with p_tileset, p_meta, caplog.at_level(logging.ERROR):
        resp = client.get("/api/hazards/lowland_poor_drainage/kanagawa/meta")

    assert resp.status_code == 500
    matching = [
        r for r in caplog.records
        if r.levelno >= logging.ERROR and "tileset_lookup" in r.getMessage()
    ]
    assert matching, "tileset_lookup操作を示すERRORログが記録されていない"
    assert any("lowland_poor_drainage" in r.getMessage() for r in matching)
    assert any("kanagawa" in r.getMessage() for r in matching)
    # server-side logへ実例外のroot causeが残っていること
    assert any(r.exc_info and r.exc_info[1] is exc for r in matching)


# ── F. 正常系 → 200・schema不変 ────────────────────────────────────────────────

def test_F_normal_meta_response_unchanged(client):
    fake_tileset = {"tileset_id": "tokyo_urban_001", "source_layer": "inland_flood"}
    with patch.object(hazards, "_find_tileset_for_region", return_value=fake_tileset), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=dict(_FAKE_META)):
        resp = client.get("/api/hazards/inland_flood/tokyo/meta")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tileset_id"] == "tokyo_urban_001"
    assert data["tileset_source_layer"] == "inland_flood"
    assert data["dataset_id"] == "TOKYO-URBAN-001"


# ── G. tileset不存在 → 既存nullable semantics不変（例外ではない） ─────────────

def test_G_tileset_absent_keeps_null_fields_not_error(client):
    with patch.object(hazards, "_find_tileset_for_region", return_value=None), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=dict(_FAKE_META)):
        resp = client.get("/api/hazards/inland_flood/tokyo/meta")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tileset_id"] is None
    assert data["tileset_source_layer"] is None


# ── H. 既存404契約は不変（tileset lookupより前の分岐、影響を受けない） ────────

def test_H_existing_404_contract_unaffected(client):
    exc = KeyError("Active dataset is not registered: flood:kanagawa")
    tileset_spy_called = {"called": False}

    def _spy(*a, **k):
        tileset_spy_called["called"] = True
        return None

    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", side_effect=exc), \
         patch.object(hazards, "_find_tileset_for_region", side_effect=_spy):
        resp = client.get("/api/hazards/flood/kanagawa/meta")

    assert resp.status_code == 404
    assert "not registered" in resp.text
    # meta取得自体が失敗した時点でreturnするため、tileset lookupには到達しない
    assert tileset_spy_called["called"] is False

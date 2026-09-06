"""
test_simulation_api_error_response.py — OPERATOR-ERROR-DETAIL-LEAK 回帰テスト

Residual Finding Remediation 06:
Phase A投資調査でadmin.py/admin_config.pyには実際のraw exception detail leak
が無いことを確認したが、operator専用routerの一つであるsimulation.py（
/api/simulation/run, /api/simulation/scenarios/save）に、
except Exception as exc: ... "message": str(exc) という形でraw exception
文字列がresponse bodyへ直接混入する実装が見つかった。

save_scenario()はdata_runtime/simulation/scenarios/{id}.jsonへ
os.makedirs + open(path, "w")で書込むため、PermissionError/OSErrorが
発生した場合、内部filesystem pathがそのままoperator API responseへ
露出しうる（今回のfindingの典型例）。

このテストは:
  - fixtureで意図的にPermissionError/OSError/予期しない例外を注入し、
    response bodyに内部path/errno detailが含まれないことを確認する。
  - 既存のgraceful degradation構造（status/フィールド形状）は維持されて
    いることを確認する（HTTP status自体は元々200のまま変更しない）。
  - server-side loggingでroot causeが失われていないことをcaplogで確認する。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import simulation  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(simulation.router)
    return TestClient(app, raise_server_exceptions=False)


# ── A. /api/simulation/run: PermissionError → path非公開 ──────────────────────

def test_simulation_run_permission_error_hides_path(client, caplog):
    leaked_path = "/data_runtime/simulation/scenarios/scenario-008.json"
    exc = OSError(f"[Errno 13] Permission denied: '{leaked_path}'")

    with patch.object(simulation, "run_simulation", side_effect=exc), \
         caplog.at_level(logging.ERROR):
        resp = client.post("/api/simulation/run", json={
            "scenario_id": "scenario-008",
            "origin": [139.0, 35.0],
            "destination": [139.1, 35.1],
        })

    assert resp.status_code == 200  # 既存のgraceful degradation構造を維持
    body_text = resp.text
    assert leaked_path not in body_text
    assert "Permission denied" not in body_text
    assert "Errno" not in body_text
    data = resp.json()
    assert data["status"] == "unavailable"
    # server-side logへはroot causeが残っていること
    assert any(
        (r.exc_info and leaked_path in str(r.exc_info[1])) or leaked_path in r.getMessage()
        for r in caplog.records
    )


# ── B. /api/simulation/scenarios/save: OSError → errno非公開 ──────────────────

def test_scenario_save_oserror_hides_path_and_errno(client):
    leaked_path = "/data_runtime/simulation/scenarios/scenario-001.json"
    exc = OSError(13, "Permission denied")
    exc.filename = leaked_path
    exc_with_path = OSError(f"[Errno 13] Permission denied: '{leaked_path}'")

    with patch.object(simulation, "save_scenario", side_effect=exc_with_path):
        resp = client.post("/api/simulation/scenarios/save", json={
            "scenario_id": "scenario-001",
            "title": "test",
            "origin": [139.0, 35.0],
            "destination": [139.1, 35.1],
        })

    assert resp.status_code == 200
    assert leaked_path not in resp.text
    assert "Permission denied" not in resp.text
    assert "Errno" not in resp.text
    data = resp.json()
    assert data["status"] == "error"


# ── C. 予期しない例外（ValueError等）も同様にraw message非公開 ────────────────

def test_scenario_save_unexpected_exception_hides_raw_message(client):
    exc = ValueError("Invalid scenario payload at /data_runtime/simulation/scenarios/x.json")

    with patch.object(simulation, "save_scenario", side_effect=exc):
        resp = client.post("/api/simulation/scenarios/save", json={
            "scenario_id": "scenario-002",
            "title": "test",
            "origin": [139.0, 35.0],
            "destination": [139.1, 35.1],
        })

    assert resp.status_code == 200
    assert "/data_runtime/" not in resp.text


# ── D. 正常系は変更されない ────────────────────────────────────────────────────

def test_scenario_save_success_unchanged(client):
    with patch.object(simulation, "save_scenario", return_value="/data_runtime/simulation/scenarios/ok.json"):
        resp = client.post("/api/simulation/scenarios/save", json={
            "scenario_id": "ok",
            "title": "test",
            "origin": [139.0, 35.0],
            "destination": [139.1, 35.1],
        })

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["path"] == "/data_runtime/simulation/scenarios/ok.json"


def test_simulation_scenarios_list_unaffected(client):
    """/api/simulation/scenarios（一覧取得）は元々str(exc)を使っておらず、
    今回のfixで挙動を変えないことを確認する。"""
    with patch.object(simulation, "get_scenarios", side_effect=RuntimeError("boom")):
        resp = client.get("/api/simulation/scenarios")

    assert resp.status_code == 200
    assert resp.json() == {"status": "unavailable", "scenarios": []}


# ── E. server-side logging: exceptionがloggerへ記録される ─────────────────────

def test_scenario_save_logs_exception_with_context(client, caplog):
    exc = OSError("[Errno 28] No space left on device: '/data_runtime/simulation/scenarios/big.json'")

    with patch.object(simulation, "save_scenario", side_effect=exc), \
         caplog.at_level(logging.ERROR):
        resp = client.post("/api/simulation/scenarios/save", json={
            "scenario_id": "big",
            "title": "test",
            "origin": [139.0, 35.0],
            "destination": [139.1, 35.1],
        })

    assert resp.status_code == 200
    assert any(r.levelno >= logging.ERROR for r in caplog.records), "server-side logへexceptionが記録されていない"

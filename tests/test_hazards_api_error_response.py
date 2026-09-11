"""
test_hazards_api_error_response.py — PUBLIC-ERROR-DETAIL-LEAK 回帰テスト

Residual Finding Remediation 04:
/api/hazards/{hazard_type}/{region_code} 系routeがPermissionError/OSError/
ValueErrorをHTTPException(detail=str(exc))へそのまま変換しており、内部
filesystem path・errnoメッセージが未認証public clientへ露出していた
（実例: "[Errno 13] Permission denied: '/data_runtime/frontend/tiles/...'"）。

このテストは:
  - fixtureで意図的にPermissionError/OSError/ValueError/予期しない例外を
    hazard_dataset_serviceから送出させ、response bodyに内部detailが
    含まれないことを確認する（修正後のregression test）。
  - 既存4xx契約（dataset未登録→404、pseudo_inland_flood:kanagawa等）は
    変更されていないことを確認する。
  - server-side loggingでroot causeが失われていないことをcaplogで確認する。

hazards.pyのrouterのみを軽量FastAPI test appへmountし、
hazard_dataset_serviceをmockすることで、実データ読み込みを伴う
app_public.py全体のimportを避ける。
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

from app.api import hazards  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app, raise_server_exceptions=False)


# ── A. PermissionError → path/errno非公開、既存500維持 ────────────────────────

def test_permission_error_hides_filesystem_path(client, caplog):
    # LARGE-HAZARD-FULL-BODY-POLICY Phase B1対応: pseudo_inland_floodは
    # policy-rejected type（422、has_active_hazard_datasetのみ呼ばれる）に
    # なったため対象から外した。STORM-SURGE-FALLBACK-STREAMING/
    # TSUNAMI-FALLBACK-STREAMING Phase B1で、storm_surge/tsunamiも専用
    # streaming routeへ移行しcatch-allを経由しなくなったため、これらも
    # 対象から外れた。inland_flood/landslideも既に専用route。
    #
    # この結果、catch-all（get_active_hazard_geojson()経由のjson.load()
    # full-body path）を実際に経由する現行の実hazard typeは無くなった
    # （HAZARD-PUBLIC-CATCHALL-JSONLOAD-DEAD-PATH candidate、TSUNAMI-
    # FALLBACK-STREAMING Phase B1 OWNER Gate参照）。本テストの意図は
    # 「catch-all route自身の例外→HTTPException変換ロジックがpath/errnoを
    # 漏らさないこと」の検証であり、特定の実hazard typeの業務的意味には
    # 依存しない。get_active_hazard_geojson()を完全にmockするため、
    # HazardDatasetService.HAZARD_LAYER_TYPES非登録の合成type文字列
    # （`test_file_not_found_keeps_404_detail`と同じ`some_type`パターン）を
    # 使い、実typeの切り替え保守を続ける代わりにこの依存自体を断つ。
    leaked_path = "/data_runtime/frontend/tiles/tokyo/some_type/tokyo-some-type-001.geojson"
    exc = PermissionError(13, "Permission denied")
    exc.filename = leaked_path
    # OSErrorのstr()表現は "[Errno 13] Permission denied: '<path>'" になる
    exc_with_path = OSError(f"[Errno 13] Permission denied: '{leaked_path}'")

    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson", side_effect=exc_with_path), \
         caplog.at_level(logging.ERROR):
        resp = client.get("/api/hazards/some_type/tokyo")

    assert resp.status_code == 500
    body_text = resp.text
    assert leaked_path not in body_text
    assert "Permission denied" not in body_text
    assert "Errno" not in body_text
    # server-side logへはroot causeが残っていること
    assert any(leaked_path in record.getMessage() or leaked_path in str(record.exc_info)
               for record in caplog.records) or any(
                   record.exc_info and leaked_path in str(record.exc_info[1])
                   for record in caplog.records
               )


def test_permission_error_on_meta_endpoint_hides_path(client):
    leaked_path = "/data_runtime/frontend/tiles/tokyo/lowland_poor_drainage/tokyo-lowland-poor-drainage-001.geojson"
    exc = OSError(f"[Errno 13] Permission denied: '{leaked_path}'")

    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", side_effect=exc):
        resp = client.get("/api/hazards/lowland_poor_drainage/tokyo/meta")

    assert resp.status_code == 500
    assert leaked_path not in resp.text
    assert "Permission denied" not in resp.text


def test_permission_error_on_active_list_endpoint_hides_path(client):
    leaked_path = "/data_runtime/frontend/tiles/kanagawa/lowland_poor_drainage/kanagawa-lowland-poor-drainage-001.geojson"
    exc = OSError(f"[Errno 13] Permission denied: '{leaked_path}'")

    with patch.object(hazards.hazard_dataset_service, "list_active_hazard_datasets", side_effect=exc):
        resp = client.get("/api/hazards/active")

    assert resp.status_code == 500
    assert leaked_path not in resp.text


# ── B. OSError一般（IOError等）→ raw errno非公開 ──────────────────────────────

def test_generic_oserror_hides_errno_detail(client):
    # TSUNAMI-FALLBACK-STREAMING Phase B1対応: tsunami/storm_surgeとも専用
    # streaming routeへ移行したため、catch-all自身のcontractを検証する
    # 合成type（`some_type`）を使う。上記test_permission_error_hides_
    # filesystem_pathのコメント参照。
    exc = OSError(28, "No space left on device")  # errno例: ENOSPC

    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson", side_effect=exc):
        resp = client.get("/api/hazards/some_type/tokyo")

    assert resp.status_code == 500
    assert "No space left on device" not in resp.text
    assert "28" not in resp.text or "errno" not in resp.text.lower()


# ── C. malformed GeoJSON（ValueError、path埋め込み）→ path非公開 ──────────────

def test_value_error_with_embedded_path_hides_path(client):
    # TSUNAMI-FALLBACK-STREAMING Phase B1対応: 上記と同じ理由で合成type
    # （`some_type`）へ切り替える。
    leaked_path = "/data_lake/validated/tokyo/some_type/tokyo-some-type-001.geojson"
    exc = ValueError(f"GeoJSON root must be an object: {leaked_path}")

    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson", side_effect=exc):
        resp = client.get("/api/hazards/some_type/tokyo")

    assert resp.status_code == 500
    assert leaked_path not in resp.text


# ── D. dataset not registered → 既存404契約維持 ───────────────────────────────

def test_dataset_not_registered_keeps_404_detail(client):
    # LARGE-HAZARD-FULL-BODY-POLICY/STORM-SURGE/TSUNAMI-FALLBACK-STREAMING
    # 各Phase B1対応: pseudo_inland_flood/storm_surge/tsunamiは、いずれも
    # get_active_hazard_geojson()経由のcatch-all pathを経由しなくなった
    # （pseudo_inland_flood自身の404契約はhas_active_hazard_datasetベースで
    # test_hazard_large_response_limit.py側に別途カバーする）。本テストは
    # catch-all route自身の404 mapping契約を検証する合成type（`some_type`）
    # へ切り替える。
    exc = KeyError("Active dataset is not registered: some_type:chiba")

    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson", side_effect=exc):
        resp = client.get("/api/hazards/some_type/chiba")

    assert resp.status_code == 404
    assert "not registered" in resp.text


def test_file_not_found_keeps_404_detail(client):
    exc = FileNotFoundError("Active dataset has no resolved artifact: TOKYO-XXX-001")

    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson", side_effect=exc):
        resp = client.get("/api/hazards/some_type/tokyo")

    assert resp.status_code == 404
    assert "no resolved artifact" in resp.text


# ── E. pseudo_inland_flood/kanagawa 実contractも確認（KeyError経由） ──────────

def test_pseudo_kanagawa_404_contract_unchanged(client):
    # LARGE-HAZARD-FULL-BODY-POLICY Phase B1対応: pseudo_inland_floodは
    # policy-rejected typeとなり、404判定はhas_active_hazard_dataset()
    # 経由になった（get_active_hazard_geojson()はこのtypeでは一切呼ばれ
    # ない）。「pseudo_inland_flood:kanagawaは未登録region」という実contract
    # 自体（404であること）は変更していないため、mock対象のみ更新して
    # 同じ契約を検証する。
    exc = KeyError("Active dataset is not registered: pseudo_inland_flood:kanagawa")
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", side_effect=exc), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get("/api/hazards/pseudo_inland_flood/kanagawa")
    assert resp.status_code == 404
    load_mock.assert_not_called()


# ── F. 正常系 → 200維持 ────────────────────────────────────────────────────────

def test_normal_response_untouched(client):
    # TSUNAMI-FALLBACK-STREAMING Phase B1対応: storm_surge/tsunamiとも専用
    # streaming routeへ移行したため、catch-all自身の正常応答契約を検証する
    # 合成type（`some_type`）を使う。
    payload = {"type": "FeatureCollection", "features": []}
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson", return_value=payload):
        resp = client.get("/api/hazards/some_type/tokyo")

    assert resp.status_code == 200
    assert resp.json() == payload


# ── G. server-side logging: 予期しない例外もloggerへ記録される ────────────────

def test_unexpected_value_error_logs_exception_with_context(client, caplog):
    exc = ValueError("Invalid GeoJSON in /data_lake/validated/x.geojson: some parse error")
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", side_effect=exc), \
         caplog.at_level(logging.ERROR):
        resp = client.get("/api/hazards/pseudo_inland_flood/tokyo/meta")

    assert resp.status_code == 500
    assert any(r.levelno >= logging.ERROR for r in caplog.records), "server-side logへexceptionが記録されていない"

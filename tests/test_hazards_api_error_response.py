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

HAZARD-PUBLIC-CATCHALL-JSONLOAD-DEAD-PATH対応（2026-09-12）: catch-all
route（`GET /{hazard_type}/{region_code}`）の
`hazard_dataset_service.get_active_hazard_geojson()`呼び出しは、
全7 hazard typeがreject分岐または専用streaming routeへ吸収済みで
構造的に到達不能だったため除去された。これに伴い、この呼び出しの
例外マッピング（PermissionError/OSError/ValueError→500、
FileNotFoundError/KeyError→404）を合成type（`some_type`）経由で検証
していた旧テスト群は、検証対象の実装が既に存在しないため削除した
（同種のPUBLIC-ERROR-DETAIL-LEAK safety property自体は、reject分岐
（`has_active_hazard_dataset()`呼び出し）に対する
`test_hazard_policy_rejected_types.py::test_M_internal_path_does_not_
leak_on_policy_rejected_type`で引き続き実証されている——生きている
コードパスでの検証に一本化した）。代わりに、catch-allの新しい
「未対応/未登録hazard_typeは常に404」という契約自体をこのファイルで
検証する。

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
from _testclient_compat import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import hazards  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app, raise_server_exceptions=False)


# ── A. PermissionError → path/errno非公開、既存500維持（/meta route） ─────────

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


# ── D. unknown hazard_type → 404 contract（HAZARD-PUBLIC-CATCHALL-
#      JSONLOAD-DEAD-PATH対応後の新しい検証対象） ──────────────────────────────

def test_unknown_hazard_type_returns_404_without_calling_service(client):
    """catch-allは、reject分岐にも専用streaming routeにも該当しない
    hazard_typeについて、`hazard_dataset_service.get_active_hazard_
    geojson()`を一切呼び出さず、直接404を返す（dead path除去の直接
    証明）。既存の「Unsupported hazard_type」文言・KeyErrorのstr()表現
    （前後の引用符を含む）という後方互換contractも確認する。"""
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get("/api/hazards/some_type/tokyo")

    assert resp.status_code == 404
    assert resp.json() == {"detail": "'Unsupported hazard_type: some_type'"}
    load_mock.assert_not_called()


def test_unknown_hazard_type_404_even_if_service_mock_would_succeed(client):
    """万一mockが正常値を返すよう設定されていても（＝サービス層の挙動に
    一切依存せず）、catch-all自身の分岐ロジックだけで404になることを
    確認する（本当に到達不能であることの証明、mockの設定内容に無関係）。"""
    with patch.object(
        hazards.hazard_dataset_service, "get_active_hazard_geojson",
        return_value={"type": "FeatureCollection", "features": []},
    ):
        resp = client.get("/api/hazards/completely_unknown_type/tokyo")

    assert resp.status_code == 404


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


# ── F. server-side logging: 予期しない例外もloggerへ記録される ────────────────

def test_unexpected_value_error_logs_exception_with_context(client, caplog):
    exc = ValueError("Invalid GeoJSON in /data_lake/validated/x.geojson: some parse error")
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", side_effect=exc), \
         caplog.at_level(logging.ERROR):
        resp = client.get("/api/hazards/pseudo_inland_flood/tokyo/meta")

    assert resp.status_code == 500
    assert any(r.levelno >= logging.ERROR for r in caplog.records), "server-side logへexceptionが記録されていない"

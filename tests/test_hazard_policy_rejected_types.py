"""
test_hazard_policy_rejected_types.py — LARGE-HAZARD-FULL-BODY-POLICY
Phase B1 回帰テスト。

OWNER決定（2026-09-07、HYBRID_POLICY、Phase B1スコープ）:
`pseudo_inland_flood`/`lowland_poor_drainage`は、frontend consumer 0件・
tile infrastructure完備・external public download contract無しという
delivery-policy上の理由により、public full-body GeoJSON responseを
提供しない。floodのsize/availability理由（413、
`_HAZARD_LARGE_RESPONSE_DETAIL`）とは意味が異なるため、別のHTTP status
（422 Unprocessable Entity）・別のdetail文言（`_HAZARD_POLICY_REJECTED_
DETAIL`）を用いる。

422選定理由（コード側コメントと同一）: 対象datasetは実在するため404は
不採用、sizeが理由ではないため413の機械的流用は不採用、認証が理由では
ないため403は不採用、恒久的なpolicyであり一時的な状態競合ではないため
409も不採用。「requestは理解できるが、この形では提供しない」を最も
適切に表すのが422。

hazards.pyのrouterのみを軽量FastAPI test appへmountし、
hazard_dataset_serviceをmockすることで、実データ読み込みを伴う
app_public.py全体のimportを避ける（HAZARD-ENGINE-LARGE-DATASET-
MEMORY-BLOCKER remediation時の教訓）。
"""
from __future__ import annotations

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


# ── A/B/C. pseudo(tokyo) / lowland(tokyo) / lowland(kanagawa) → 422拒否 ────────

@pytest.mark.parametrize("hazard_type,region", [
    ("pseudo_inland_flood", "tokyo"),
    ("lowland_poor_drainage", "tokyo"),
    ("lowland_poor_drainage", "kanagawa"),
])
def test_ABC_policy_rejected_types_return_422(client, hazard_type, region):
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get(f"/api/hazards/{hazard_type}/{region}")

    assert resp.status_code == 422
    load_mock.assert_not_called()


# ── D/E. target routesでjson.load/get_active_hazard_geojsonが一切呼ばれない ────

def test_DE_no_file_parse_for_policy_rejected_types(client):
    call_log = []

    def _probe_spy(hazard_type, region_code):
        call_log.append(("probe", hazard_type, region_code))
        return True

    def _load_spy(hazard_type, region_code):
        call_log.append(("load", hazard_type, region_code))
        return {"type": "FeatureCollection", "features": []}

    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", side_effect=_probe_spy), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson", side_effect=_load_spy):
        resp = client.get("/api/hazards/pseudo_inland_flood/tokyo")

    assert resp.status_code == 422
    assert call_log == [("probe", "pseudo_inland_flood", "tokyo")]  # loadは一度も呼ばれていない


# ── F. 不存在region → 既存404 semantics維持（422ではない） ────────────────────

@pytest.mark.parametrize("hazard_type,region", [
    ("pseudo_inland_flood", "chiba"),
    ("lowland_poor_drainage", "chiba"),
])
def test_F_unregistered_region_still_404_not_422(client, hazard_type, region):
    with patch.object(
        hazards.hazard_dataset_service, "has_active_hazard_dataset",
        side_effect=KeyError(f"Active dataset is not registered: {hazard_type}:{region}"),
    ) as probe_mock, \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get(f"/api/hazards/{hazard_type}/{region}")

    assert resp.status_code == 404
    probe_mock.assert_called_once_with(hazard_type, region)
    load_mock.assert_not_called()


def test_F2_file_not_found_still_404(client):
    with patch.object(
        hazards.hazard_dataset_service, "has_active_hazard_dataset",
        side_effect=FileNotFoundError("Active dataset has no resolved artifact: TOKYO-PSEUDO-INLAND-FLOOD-001"),
    ):
        resp = client.get("/api/hazards/pseudo_inland_flood/tokyo")

    assert resp.status_code == 404


# ── G. meta remains 200 where dataset exists ────────────────────────────────

@pytest.mark.parametrize("hazard_type,region", [
    ("pseudo_inland_flood", "tokyo"),
    ("lowland_poor_drainage", "tokyo"),
    ("lowland_poor_drainage", "kanagawa"),
])
def test_G_meta_endpoint_unaffected(client, hazard_type, region):
    fake_meta = {
        "dataset_id": f"{region.upper()}-X-001", "layer_type": hazard_type, "region": region,
        "display_name": "dummy", "deploy_status": "deployed", "artifact_path": "/dummy", "is_active": True,
    }
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=fake_meta), \
         patch("app.api.hazards._find_tileset_for_region", return_value=None):
        resp = client.get(f"/api/hazards/{hazard_type}/{region}/meta")

    assert resp.status_code == 200
    assert resp.json()["dataset_id"] == f"{region.upper()}-X-001"


# ── H. flood remains 413（別の理由・別のdetail、区別できていること） ──────────

def test_H_flood_still_413_with_distinct_detail(client):
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True):
        resp = client.get("/api/hazards/flood/tokyo")

    assert resp.status_code == 413
    assert resp.json()["detail"] == hazards._HAZARD_LARGE_RESPONSE_DETAIL
    assert resp.json()["detail"] != hazards._HAZARD_POLICY_REJECTED_DETAIL


# ── I/J. policy-rejected typesとは無関係のtypeは無変更（200維持） ─────────────
# storm_surge/tsunamiは、それぞれSTORM-SURGE-FALLBACK-STREAMING/
# TSUNAMI-FALLBACK-STREAMING Phase B1でcatch-all routeを経由しない専用
# streaming routeへ切り替わったため対象から除外（それぞれの契約は専用
# test fileで検証する）。catch-all自身の「policy-rejected typesとは無関係の
# typeはhas_active_hazard_dataset()を経由しない」という分岐契約は特定の
# 実typeに依存しないため、合成type（`some_type`）で検証する
# （HAZARD-PUBLIC-CATCHALL-JSONLOAD-DEAD-PATH candidate参照）。

@pytest.mark.parametrize("hazard_type", ["some_type"])
def test_IJ_storm_surge_tsunami_unaffected(client, hazard_type):
    fake_geojson = {"type": "FeatureCollection", "features": []}
    with patch.object(
        hazards.hazard_dataset_service, "get_active_hazard_geojson", return_value=fake_geojson,
    ) as load_mock, \
         patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset") as probe_mock:
        resp = client.get(f"/api/hazards/{hazard_type}/tokyo")

    assert resp.status_code == 200
    assert resp.json() == fake_geojson
    load_mock.assert_called_once_with(hazard_type, "tokyo")
    probe_mock.assert_not_called()


# ── K/L. inland_flood/landslide streaming routeは無変更（catch-allを経由しない）

@pytest.mark.parametrize("hazard_type", ["inland_flood", "landslide"])
def test_KL_streaming_routes_unaffected(hazard_type):
    # inland_flood/landslideは専用route（catch-allより先に定義）が処理する
    # ため、_HAZARD_POLICY_REJECTED_TYPES/_HAZARD_LARGE_RESPONSE_LIMITED_TYPES
    # のいずれにも属さないことを静的に確認する（catch-allに到達しない設計を
    # 壊していないことの保証）。
    assert hazard_type not in hazards._HAZARD_POLICY_REJECTED_TYPES
    assert hazard_type not in hazards._HAZARD_LARGE_RESPONSE_LIMITED_TYPES


# ── M. internal path non-leak（500 pathでも同様のgeneric detail契約） ─────────

def test_M_internal_path_does_not_leak_on_policy_rejected_type(client):
    leaked_path = "/data_runtime/backend/hazard/pseudo_inland_flood/tokyo/pseudo_inland_flood.geojson"
    with patch.object(
        hazards.hazard_dataset_service, "has_active_hazard_dataset",
        side_effect=OSError(f"[Errno 13] Permission denied: '{leaked_path}'"),
    ):
        resp = client.get("/api/hazards/pseudo_inland_flood/tokyo")

    assert resp.status_code == 500
    assert leaked_path not in resp.text
    assert "Errno" not in resp.text
    assert resp.json()["detail"] == hazards._HAZARD_INTERNAL_ERROR_DETAIL


# ── policy declaration: scope固定 ───────────────────────────────────────────

def test_policy_rejected_types_scope_is_pseudo_and_lowland_only():
    assert hazards._HAZARD_POLICY_REJECTED_TYPES == frozenset({
        "pseudo_inland_flood", "lowland_poor_drainage",
    })
    # floodとpolicy-rejected typesは互いに素であること（理由が異なるため
    # 二重分類しない）
    assert hazards._HAZARD_LARGE_RESPONSE_LIMITED_TYPES.isdisjoint(hazards._HAZARD_POLICY_REJECTED_TYPES)

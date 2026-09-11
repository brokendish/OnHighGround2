"""
test_hazard_large_response_limit.py — LARGE-HAZARD-GEOJSON-SWAP-THRASH
Phase B1 回帰テスト。

OWNER決定（2026-09-07、Phase B1、スコープ最小）: `GET /api/hazards/flood/
{region_code}`（catch-all route）は、current active artifactが数百MB規模
（flood/tokyo ≈500MB, flood/kanagawa ≈310MB）に達し、
`HazardDatasetService.get_active_hazard_geojson()`のjson.load()フルロード
＋FastAPI JSONResponseの再シリアライズにより、severeなmemory/swap thrash
を引き起こした実績がある（OWNER Phase A investigation）。

対応: hazard_type == "flood" の場合、fileへ一切触れず（json.load()を
発生させず）413 Payload Too Largeを返す。他type（storm_surge/tsunami/
pseudo_inland_flood/lowland_poor_drainage/inland_flood/landslide）は
今回のスコープ外（KEEP FOR NOW/FOLLOW-UP）であり無変更。

OWNER Gate指摘対応（2026-09-07 second round）: 当初案（file内容は読まず
Pathだけを返す`resolve_active_hazard_path()`）は、lease-protected path
（current/versioned tree配下、GCから保護されている一時的な参照）を
service境界の外（hazards.py以降）へ公開してしまう余地を作っていた。
これを`has_active_hazard_dataset()`（boolのみ返す、Pathは一切公開しない）
へ置き換えた。このテストはその契約を検証する。

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
from app.services.hazard_dataset_service import HazardDatasetService  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app, raise_server_exceptions=False)


# ── A. flood + valid region（probe success）→ 413、fileは一切読まれない ────────

def test_A_flood_valid_region_rejected_with_413_without_reading_file(client):
    with patch.object(
        hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True,
    ) as probe_mock, \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get("/api/hazards/flood/tokyo")

    assert resp.status_code == 413
    probe_mock.assert_called_once_with("flood", "tokyo")
    load_mock.assert_not_called()  # json.load()に相当する経路が一切呼ばれていないこと


def test_A2_flood_kanagawa_also_rejected_with_413(client):
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get("/api/hazards/flood/kanagawa")

    assert resp.status_code == 413
    load_mock.assert_not_called()


# ── B. flood + 未登録region（probe failure）→ 従来通り404（413ではない） ───────

def test_B_flood_unregistered_region_still_404_not_413(client):
    with patch.object(
        hazards.hazard_dataset_service, "has_active_hazard_dataset",
        side_effect=KeyError("Active dataset is not registered: flood:chiba"),
    ) as probe_mock, \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get("/api/hazards/flood/chiba")

    assert resp.status_code == 404
    probe_mock.assert_called_once_with("flood", "chiba")
    load_mock.assert_not_called()


def test_B2_flood_file_not_found_still_404(client):
    with patch.object(
        hazards.hazard_dataset_service, "has_active_hazard_dataset",
        side_effect=FileNotFoundError("Active dataset has no resolved artifact: TOKYO-RIVER-001"),
    ):
        resp = client.get("/api/hazards/flood/tokyo")

    assert resp.status_code == 404


# ── C. probeはPath objectを一切公開しない（bool専用契約） ──────────────────────

def test_C_probe_return_type_is_bool_not_path(tmp_path, monkeypatch):
    """has_active_hazard_dataset()の戻り値がPathでもtupleでもなく、
    純粋なboolであることを、実サービス（mock無し）に対して直接検証する。
    current tree／flat fallbackいずれの解決経路でもPathを外部へ返さない
    契約を保証する（OWNER Gate指摘：lease-protected pathをservice境界の
    外へ公開しない）。"""
    service = HazardDatasetService()

    # current側は未初期化環境をシミュレート（is_available()==False相当）
    # とし、flat fallback（_resolve_active_dataset）だけを通す。
    fake_path = tmp_path / "tokyo-river-001.geojson"
    fake_path.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")

    monkeypatch.setattr(
        service, "_try_resolve_from_current",
        lambda hazard_type, region_code, loader: None,  # currentは未配備 → flatへ
    )
    monkeypatch.setattr(
        service, "_resolve_active_dataset",
        lambda hazard_type, region_code: ("TOKYO-RIVER-001", None, None, fake_path),
    )

    result = service.has_active_hazard_dataset("flood", "tokyo")

    assert result is True
    assert not isinstance(result, Path)
    assert not isinstance(result, tuple)


def test_C2_probe_via_current_tree_also_returns_bool_only(monkeypatch):
    """current tree経由で解決した場合も、loaderへ渡した`lambda _p: True`の
    戻り値（bool）だけが伝播し、Pathがcallerへ届かないことを確認する。"""
    service = HazardDatasetService()

    captured_loader_arg = {}

    def _fake_try_resolve(hazard_type, region_code, loader):
        # 実装が使うloaderへ実際にPathを渡し、loaderの戻り値だけを
        # 返すこと（Path自体は_try_resolve_from_current内部に閉じ込め
        # られ、呼び出し元へは戻らないこと）を検証する。
        fake_path = Path("/data_runtime/versions/dummy/backend/hazard/flood/tokyo/x.geojson")
        result = loader(fake_path)
        captured_loader_arg["result"] = result
        return result

    monkeypatch.setattr(service, "_try_resolve_from_current", _fake_try_resolve)

    result = service.has_active_hazard_dataset("flood", "tokyo")

    assert result is True
    assert captured_loader_arg["result"] is True
    assert not isinstance(result, Path)


# ── D. 413 responseがgeneric detailのみ（内部path等を含まない） ────────────────

def test_D_413_response_detail_is_generic_no_internal_leak(client):
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True):
        resp = client.get("/api/hazards/flood/tokyo")

    body = resp.json()
    assert "detail" in body
    assert "/data_runtime" not in body["detail"]
    assert "tokyo-river-001.geojson" not in body["detail"]
    assert "meta" in body["detail"].lower()  # /meta参照への案内を含む


# ── E. floodのLIMITとは無関係のtypeは無変更（200維持） ─────────────────────────
# pseudo_inland_flood/lowland_poor_drainageは、本テスト作成後の
# LARGE-HAZARD-FULL-BODY-POLICY Phase B1でpolicy-rejected type（422）に
# なったため、対象から除外（そちらの契約は
# tests/test_hazard_policy_rejected_types.py で検証する）。
# storm_surge/tsunamiは、本テスト作成後のSTORM-SURGE-FALLBACK-STREAMING/
# TSUNAMI-FALLBACK-STREAMING各Phase B1で、catch-all routeを経由しない専用
# streaming routeへ切り替わったため対象から除外（get_active_hazard_geojson()
# を呼ばなくなった。その契約はそれぞれ専用test fileで検証する）。
#
# この結果、_HAZARD_LARGE_RESPONSE_LIMITED_TYPES/_HAZARD_POLICY_REJECTED_
# TYPESのいずれにも属さない現行の実hazard typeは無くなった
# （HAZARD-PUBLIC-CATCHALL-JSONLOAD-DEAD-PATH candidate）。本テストの意図は
# 「LIMIT対象外typeがprobe-onlyを経由せず通常load pathへ到達すること」という
# catch-all自身の分岐契約の検証であり、特定の実typeに依存しないため、
# 合成type（`some_type`）へ切り替える。

@pytest.mark.parametrize("hazard_type", ["some_type"])
def test_E_other_types_unaffected_normal_response(client, hazard_type):
    fake_geojson = {"type": "FeatureCollection", "features": []}
    with patch.object(
        hazards.hazard_dataset_service, "get_active_hazard_geojson", return_value=fake_geojson,
    ) as load_mock, \
         patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset") as probe_mock:
        resp = client.get(f"/api/hazards/{hazard_type}/tokyo")

    assert resp.status_code == 200
    assert resp.json() == fake_geojson
    load_mock.assert_called_once_with(hazard_type, "tokyo")
    probe_mock.assert_not_called()  # 413経路（probe-only）は通らない


# ── F. meta endpointはfloodについても無変更（200維持） ─────────────────────────

def test_F_flood_meta_endpoint_still_returns_200(client):
    fake_meta = {
        "dataset_id": "TOKYO-RIVER-001",
        "layer_type": "flood",
        "region": "tokyo",
        "display_name": "洪水浸水想定区域",
        "deploy_status": "deployed",
        "artifact_path": "/data_runtime/backend/hazard/flood/tokyo/tokyo-river-001.geojson",
        "is_active": True,
    }
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=fake_meta), \
         patch("app.api.hazards._find_tileset_for_region", return_value=None):
        resp = client.get("/api/hazards/flood/tokyo/meta")

    assert resp.status_code == 200
    assert resp.json()["dataset_id"] == "TOKYO-RIVER-001"


# ── G. 500 pathのgeneric error detail契約は413対象typeでも維持 ─────────────────

def test_G_flood_internal_error_still_uses_generic_detail(client):
    leaked_path = "/data_runtime/backend/hazard/flood/tokyo/tokyo-river-001.geojson"
    with patch.object(
        hazards.hazard_dataset_service, "has_active_hazard_dataset",
        side_effect=OSError(f"[Errno 13] Permission denied: '{leaked_path}'"),
    ):
        resp = client.get("/api/hazards/flood/tokyo")

    assert resp.status_code == 500
    assert leaked_path not in resp.text
    assert "Errno" not in resp.text
    assert resp.json()["detail"] == hazards._HAZARD_INTERNAL_ERROR_DETAIL


# ── H. has_active_hazard_datasetが1回だけ呼ばれ、fileの内容読込に相当する
#      関数（get_active_hazard_geojson）が一切呼ばれないことを再確認 ───────────

def test_H_no_file_parse_path_for_limited_type(client):
    call_log = []

    def _probe_spy(hazard_type, region_code):
        call_log.append(("probe", hazard_type, region_code))
        return True

    def _load_spy(hazard_type, region_code):
        call_log.append(("load", hazard_type, region_code))
        return {"type": "FeatureCollection", "features": []}

    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", side_effect=_probe_spy), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson", side_effect=_load_spy):
        resp = client.get("/api/hazards/flood/tokyo")

    assert resp.status_code == 413
    assert call_log == [("probe", "flood", "tokyo")]  # loadは一度も呼ばれていない


# ── I. limited-typesの集合そのものがscope通りflood単独であることの固定 ─────────

def test_I_limited_types_scope_is_flood_only():
    assert hazards._HAZARD_LARGE_RESPONSE_LIMITED_TYPES == frozenset({"flood"})


# ── J. 既存current lease load contract（get_active_hazard_geojson）は無変更 ────

def test_J_existing_current_lease_load_contract_unchanged(monkeypatch):
    """has_active_hazard_dataset()追加後も、get_active_hazard_geojson()は
    引き続き_try_resolve_from_current()へself._load_jsonをloaderとして渡し、
    lease scope内でfile内容を読み込む既存契約のままであることを確認する
    （OWNER Gate指摘のcontract維持要件）。"""
    service = HazardDatasetService()
    fake_data = {"type": "FeatureCollection", "features": [{"marker": "CURRENT"}]}

    captured = {}

    def _fake_try_resolve(hazard_type, region_code, loader):
        captured["loader"] = loader
        # 実装同様、loaderをlease scope内で呼ぶ
        return loader(Path("/dummy/path.geojson"))

    monkeypatch.setattr(service, "_try_resolve_from_current", _fake_try_resolve)
    monkeypatch.setattr(service, "_load_json", lambda path: fake_data)

    result = service.get_active_hazard_geojson("flood", "tokyo")

    assert result == fake_data
    assert captured["loader"] == service._load_json

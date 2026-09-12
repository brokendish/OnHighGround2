"""
test_hazard_public_catchall_dead_path.py —
HAZARD-PUBLIC-CATCHALL-JSONLOAD-DEAD-PATH Phase A/B 回帰テスト。

catch-all route（`GET /api/hazards/{hazard_type}/{region_code}`）は
`HazardDatasetService.get_active_hazard_geojson()`（`json.load()`による
full memory展開を伴う）を呼び出していたが、7つの実hazard type全てが
reject分岐（flood/pseudo_inland_flood/lowland_poor_drainage）または
本routeより前に登録済みの専用streaming route（inland_flood/landslide/
storm_surge/tsunami）へ既に吸収されており、この呼び出しへ到達すること
は構造的にあり得なくなっていた（各Phaseの独立したOWNER Gate報告で
段階的に確認・記録済み）。

本ファイルは:
  A. 「reject分岐typeの集合」∪「専用streaming route typeの集合」が
     `HazardDatasetService.HAZARD_LAYER_TYPES`の全量と一致すること
     （production real type consumer = 0の静的固定）。
  B. `get_active_hazard_geojson()`呼び出しの実除去
     （catch-allのsource codeに当該呼び出しが存在しないこと）。
  C. 7type全ての現行regression matrix
     （flood→413, pseudo/lowland→422, inland_flood/landslide/
     storm_surge/tsunami→専用streaming route経由）。
  D. `HazardDatasetService.get_active_hazard_geojson()`自体は
     他consumer（サービス単体テスト）のため削除していないことの確認。

を一箇所にまとめて検証する。
"""
from __future__ import annotations

import ast
import inspect
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


# ── A. production real type consumer = 0 の静的固定 ────────────────────────────

def test_reject_and_dedicated_route_types_cover_all_known_hazard_types():
    """dedicated routeを持つtype（inland_flood/landslide/storm_surge/
    tsunami）とpolicy-rejected/large-response-limited type（flood/
    pseudo_inland_flood/lowland_poor_drainage）の和集合が、
    HazardDatasetService.HAZARD_LAYER_TYPESの全量と一致することを
    静的に検証する（実hazard typeが誰もcatch-allのfull-body load
    branchへ到達しないことの根拠）。"""
    dedicated_route_types = {"inland_flood", "landslide", "storm_surge", "tsunami"}
    rejected_or_limited_types = (
        hazards._HAZARD_LARGE_RESPONSE_LIMITED_TYPES | hazards._HAZARD_POLICY_REJECTED_TYPES
    )
    accounted_for = dedicated_route_types | rejected_or_limited_types

    assert accounted_for == HazardDatasetService.HAZARD_LAYER_TYPES


def test_dedicated_routes_registered_before_catch_all():
    """dedicated route 4件全てが、catch-allより前にrouterへ登録されている
    こと（FastAPIのroute解決順序がSection Aの前提と整合すること）。"""
    paths = [route.path for route in hazards.router.routes]
    catch_all_index = paths.index("/api/hazards/{hazard_type}/{region_code}")

    for hazard_type in ("inland_flood", "landslide", "storm_surge", "tsunami"):
        dedicated_index = paths.index(f"/api/hazards/{hazard_type}/{{region}}")
        assert dedicated_index < catch_all_index, f"{hazard_type} route is not registered before catch-all"


# ── B. get_active_hazard_geojson()呼び出しの実除去（source code検証） ─────────

def test_catch_all_source_does_not_call_service_get_active_hazard_geojson():
    """catch-all route関数のsource codeに
    `hazard_dataset_service.get_active_hazard_geojson`という**呼び出し**
    （AST Call node）がもはや存在しないことを確認する（実装がdead path
    を本当に除去したことの静的証明、mockの有無に依存しない）。docstring
    内の説明文（過去に何を除去したかの記述）はAST解析では無視される
    ため、単純な文字列検索より正確に判定できる。"""
    source = inspect.getsource(hazards.get_active_hazard_geojson)
    tree = ast.parse(source)

    def _dotted_name(node: ast.AST) -> str:
        if isinstance(node, ast.Attribute):
            return f"{_dotted_name(node.value)}.{node.attr}"
        if isinstance(node, ast.Name):
            return node.id
        return ""

    calls = [
        _dotted_name(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    ]
    assert "hazard_dataset_service.get_active_hazard_geojson" not in calls


# ── C. 7type regression matrix ─────────────────────────────────────────────────

def test_flood_still_413(client):
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True):
        resp = client.get("/api/hazards/flood/tokyo")
    assert resp.status_code == 413


@pytest.mark.parametrize("hazard_type", ["pseudo_inland_flood", "lowland_poor_drainage"])
def test_policy_rejected_types_still_422(client, hazard_type):
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True):
        resp = client.get(f"/api/hazards/{hazard_type}/tokyo")
    assert resp.status_code == 422


@pytest.mark.parametrize("hazard_type", ["inland_flood", "landslide", "storm_surge", "tsunami"])
def test_streaming_route_types_do_not_reach_catch_all(client, hazard_type, monkeypatch):
    """4 dedicated route typeは、catch-all自身の`get_active_hazard_
    geojson`が一切呼ばれない（専用routeが先に処理する）ことを確認する。
    実storm_surge/tsunami/inland_flood/landslideのstreaming挙動自体は
    それぞれの専用test fileで詳細に検証済み——ここではrouting到達性の
    みを確認する。versioned/flatとも見つからない状態を想定し、
    サービス層の例外で404になっても構わない（到達性の確認が目的）。"""
    called = {"value": False}

    def _spy(*a, **k):
        called["value"] = True
        return {"type": "FeatureCollection", "features": []}

    monkeypatch.setattr(hazards.hazard_dataset_service, "get_active_hazard_geojson", _spy)

    client.get(f"/api/hazards/{hazard_type}/tokyo")

    assert called["value"] is False


def test_unknown_type_returns_404_not_2xx_or_5xx(client):
    resp = client.get("/api/hazards/totally_unknown_type_xyz/tokyo")
    assert resp.status_code == 404


# ── D. HazardDatasetService.get_active_hazard_geojson()自体は削除していない ────

def test_service_method_still_exists_for_other_consumers():
    """HazardDatasetService.get_active_hazard_geojson()自体は、
    current/versioned優先解決contractの直接単体テスト
    （test_hazard_dataset_service_current_priority.py等）という
    独立したconsumerを持つため削除しない。メソッドが存在し、
    HAZARD_LAYER_TYPES外のtypeに対しては引き続きKeyErrorを送出する
    という契約自体は無変更であることを確認する。"""
    svc = HazardDatasetService()
    assert hasattr(svc, "get_active_hazard_geojson")

    with pytest.raises(KeyError):
        svc.get_active_hazard_geojson("totally_unknown_type_xyz", "tokyo")

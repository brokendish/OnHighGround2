"""
test_tsunami_fallback_streaming.py — TSUNAMI-FALLBACK-STREAMING Phase B1
回帰テスト。

OWNER決定（STREAM_FALLBACK、storm_surgeで確立済みのpatternを横展開）:
`GET /api/hazards/tsunami/{region}` を、catch-all route経由の
`json.load()`＋`JSONResponse`再シリアライズから、inland_flood/landslide/
storm_surgeと同じcurrent/versioned優先・lease保護`StreamingResponse`／
flat`FileResponse`パターンへ切り替える。frontendは既にtile-first
（`useStaticVectorTiles`）でこのrouteをtile失敗時のfallbackとしてのみ
呼ぶため、frontend変更は行わない。

**重要な発見（OWNER Gate報告）**: tsunamiのcurrent/versioned artifactは
storm_surge等と異なりregion-subdirectory layoutではなく、
`tsunami_{region}.geojson`というregion**接尾辞**のflat命名
（`HazardDatasetService._resolve_current_hazard_file()`の既存docstring・
VPS実機`find`で実証済み: `tsunami_tokyo.geojson`/`tsunami_kanagawa.geojson`、
region subdirectory無し）。`_runtime_stream_or_none()`のlegacy glob
patternsに接尾辞形（`*_{region}.geojson`）を追加することで対応した
（`stream_versioned_glob()`自体・lease機構は無変更）。

lease機構は本物のLeaseCoordinator/leased_version_rootをtmp_path上に
最小構成で用意して動かす（test_storm_surge_fallback_streaming.pyと同じ
方針）。巨大な実artifact（tokyo≈20-30MB, kanagawa≈同程度）は使わず、
合成の小さなFeatureCollectionのみを使う。
"""
from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from _testclient_compat import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import runtime_lease  # noqa: E402
from app.services.runtime_lease import LeaseCoordinator  # noqa: E402
from app.services import runtime_version_access as rva  # noqa: E402
from app.services.runtime_publish import VERSION_FILE_MODE  # noqa: E402
from app.api import hazards  # noqa: E402


VERSION_ID = "20260101T000000Z-aaaaaaaa"


def _fake_renameat2_noreplace(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None:
    try:
        os.stat(dst_name, dir_fd=dst_dir_fd, follow_symlinks=False)
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), dst_name)
    except FileNotFoundError:
        pass
    os.rename(src_name, dst_name, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)


def _setup_lease_environment(tmp_path: Path) -> Path:
    leases_root = tmp_path / "leases"
    leases_root.mkdir()
    os.chmod(leases_root, 0o2770)
    for name in ("active", "locks", "retired"):
        d = leases_root / name
        d.mkdir()
        os.chmod(d, 0o3770)
    coord_lock = leases_root / "coordination.lock"
    coord_lock.touch()
    os.chmod(coord_lock, 0o660)
    return leases_root


def _setup_data_runtime(tmp_path: Path, version_id: str = VERSION_ID) -> tuple[Path, Path]:
    data_runtime_root = tmp_path / "data_runtime"
    versions_dir = data_runtime_root / "versions"
    versions_dir.mkdir(parents=True)
    version_root = versions_dir / version_id
    version_root.mkdir()
    os.chmod(version_root, 0o750)
    os.chmod(data_runtime_root, 0o750)
    (data_runtime_root / "current").symlink_to(f"versions/{version_id}")
    return data_runtime_root, version_root


def _make_coordinator(leases_root: Path) -> LeaseCoordinator:
    return LeaseCoordinator(
        leases_root,
        uid=os.getuid(),
        gid=os.getgid(),
        lease_ttl_s=30.0,
        expect_owner_gid=os.getgid(),
        capacity_min_free_bytes=None,
        min_free_inodes=None,
        leases_owner_uid=None,
    )


def _tsunami_feature_collection(marker: str) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"depth": 3.2, "marker": marker},
                "geometry": {"type": "Point", "coordinates": [139.8, 35.5]},
            }
        ],
    }


def _write_geojson(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_tsunami_feature_collection(marker)), encoding="utf-8")
    os.chmod(path, VERSION_FILE_MODE)


@pytest.fixture
def env(tmp_path, monkeypatch):
    leases_root = _setup_lease_environment(tmp_path)
    data_runtime_root, version_root = _setup_data_runtime(tmp_path)
    coordinator = _make_coordinator(leases_root)

    monkeypatch.setattr(rva, "LEASES_ROOT", leases_root)
    monkeypatch.setattr(rva, "DATA_RUNTIME_ROOT", data_runtime_root)
    monkeypatch.setattr(rva, "_coordinator", coordinator)
    monkeypatch.setattr(rva, "get_coordinator", lambda: coordinator)
    monkeypatch.setattr(rva, "_LEASES_OWNER_UID", os.getuid())
    monkeypatch.setattr(rva, "_LEASES_GID", os.getgid())
    monkeypatch.setattr(runtime_lease, "renameat2_noreplace", _fake_renameat2_noreplace)

    monkeypatch.setattr(hazards.runtime_version_access, "LEASES_ROOT", leases_root)
    monkeypatch.setattr(hazards.runtime_version_access, "DATA_RUNTIME_ROOT", data_runtime_root)
    monkeypatch.setattr(hazards.runtime_version_access, "_coordinator", coordinator)
    monkeypatch.setattr(hazards.runtime_version_access, "get_coordinator", lambda: coordinator)

    return {
        "data_runtime_root": data_runtime_root,
        "version_root": version_root,
        "coordinator": coordinator,
        "leases_root": leases_root,
    }


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app, raise_server_exceptions=False)


# ── A. Tokyo versioned stream（実layout: tsunami_tokyo.geojson、接尾辞flat） ───

def test_A_tokyo_versioned_stream_suffix_layout(env, client):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_tokyo.geojson",
        "TOKYO-TSUNAMI",
    )

    resp = client.get("/api/hazards/tsunami/tokyo")

    assert resp.status_code == 200
    assert resp.json()["features"][0]["properties"]["marker"] == "TOKYO-TSUNAMI"
    assert "etag" not in resp.headers
    assert "last-modified" not in resp.headers


# ── B. Kanagawa versioned stream ──────────────────────────────────────────────

def test_B_kanagawa_versioned_stream_suffix_layout(env, client):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_kanagawa.geojson",
        "KANAGAWA-TSUNAMI",
    )

    resp = client.get("/api/hazards/tsunami/kanagawa")

    assert resp.status_code == 200
    assert resp.json()["features"][0]["properties"]["marker"] == "KANAGAWA-TSUNAMI"
    assert "etag" not in resp.headers


# ── H. wrong-region isolation（Tokyo/Kanagawa双方存在時に混同しない） ──────────

def test_H_wrong_region_isolation(env, client):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_tokyo.geojson", "TOKYO"
    )
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_kanagawa.geojson", "KANAGAWA"
    )

    tokyo_resp = client.get("/api/hazards/tsunami/tokyo")
    kanagawa_resp = client.get("/api/hazards/tsunami/kanagawa")

    assert tokyo_resp.json()["features"][0]["properties"]["marker"] == "TOKYO"
    assert kanagawa_resp.json()["features"][0]["properties"]["marker"] == "KANAGAWA"


# ── C. Chiba既存404維持（backend側未登録、versioned/flatとも一致しない） ──────

def test_C_chiba_keeps_existing_404(env, client, monkeypatch):
    # Tokyo/Kanagawaのversioned artifactは存在するが、Chiba用は一切無い
    # （現実のbackend側未登録状態を模擬）。
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_tokyo.geojson", "TOKYO"
    )
    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", lambda hazard_type, region: None)

    resp = client.get("/api/hazards/tsunami/chiba")

    assert resp.status_code == 404
    assert "tsunami" in resp.json()["detail"]


# ── D. no json.load呼び出し ────────────────────────────────────────────────────

def test_D_no_load_json_called(env, client, monkeypatch):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_tokyo.geojson", "TOKYO"
    )

    load_json_calls = []
    orig = hazards.hazard_dataset_service._load_json

    def _spy(*args, **kwargs):
        load_json_calls.append(args)
        return orig(*args, **kwargs)

    monkeypatch.setattr(hazards.hazard_dataset_service, "_load_json", _spy)

    resp = client.get("/api/hazards/tsunami/tokyo")

    assert resp.status_code == 200
    assert load_json_calls == []


# ── E. no get_active_hazard_geojson呼び出し ───────────────────────────────────

def test_E_no_get_active_hazard_geojson_called(env, client, monkeypatch):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_tokyo.geojson", "TOKYO"
    )

    called = {"value": False}

    def _spy(*args, **kwargs):
        called["value"] = True
        raise AssertionError("get_active_hazard_geojson should not be called for tsunami route")

    monkeypatch.setattr(hazards.hazard_dataset_service, "get_active_hazard_geojson", _spy)

    resp = client.get("/api/hazards/tsunami/tokyo")

    assert resp.status_code == 200
    assert called["value"] is False


# ── F. versioned-over-flat ─────────────────────────────────────────────────────

def test_F_versioned_selected_over_flat(env, client, monkeypatch, tmp_path):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_tokyo.geojson", "VERSIONED"
    )
    flat_file = tmp_path / "flat" / "tsunami_tokyo.geojson"
    _write_geojson(flat_file, "FLAT")

    flat_called = {"value": False}

    def _flat_spy(hazard_type, region):
        flat_called["value"] = True
        return flat_file

    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", _flat_spy)

    resp = client.get("/api/hazards/tsunami/tokyo")

    assert resp.status_code == 200
    assert resp.json()["features"][0]["properties"]["marker"] == "VERSIONED"
    assert flat_called["value"] is False


# ── G. flat fallback（versioned無し、flatあり） ────────────────────────────────

def test_G_flat_fallback_used_when_no_versioned_artifact(env, client, monkeypatch, tmp_path):
    # tsunami/tsunami_tokyo.geojson自体を作らない（真の未配備）。
    flat_file = tmp_path / "flat" / "tsunami_tokyo.geojson"
    _write_geojson(flat_file, "FLAT-FALLBACK")

    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", lambda hazard_type, region: flat_file)

    resp = client.get("/api/hazards/tsunami/tokyo")

    assert resp.status_code == 200
    assert resp.json()["features"][0]["properties"]["marker"] == "FLAT-FALLBACK"
    assert "etag" in resp.headers  # FileResponse特有のヘッダー


# ── I. route-order（tsunamiがcatch-allより先に登録されている） ────────────────

def test_I_tsunami_route_registered_before_catch_all():
    paths = [route.path for route in hazards.router.routes]
    tsunami_index = paths.index("/api/hazards/tsunami/{region}")
    catch_all_index = paths.index("/api/hazards/{hazard_type}/{region_code}")
    assert tsunami_index < catch_all_index


# ── J. application/json維持（既存catch-all契約と同一） ────────────────────────

def test_J_content_type_is_application_json(env, client):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "tsunami" / "tsunami_tokyo.geojson", "TOKYO"
    )

    resp = client.get("/api/hazards/tsunami/tokyo")

    assert resp.headers["content-type"].startswith("application/json")


# ── K. frontend TILE_FIRST unchanged（frontend source未変更の静的確認） ───────

def test_K_frontend_source_unchanged():
    frontend_path = Path(__file__).resolve().parents[1] / "frontend" / "js" / "hazard-layers.js"
    source = frontend_path.read_text(encoding="utf-8")
    # tsunamiがuseStaticVectorTiles（tile-first）のままであることを確認。
    # 本Phase B1はbackendのfallback API実装のみを変更しており、frontendの
    # tile-first判定ロジック自体には一切触れていない。
    tsunami_start = source.find("tsunami_tokyo: {")
    tsunami_end = source.find("tsunami_kanagawa:", tsunami_start)
    assert tsunami_start != -1 and tsunami_end > tsunami_start
    assert "useStaticVectorTiles: true" in source[tsunami_start:tsunami_end]


# ── L/M. Tokyo/Kanagawa fallback response.json()互換 ──────────────────────────

@pytest.mark.parametrize("region,marker", [("tokyo", "TOKYO-COMPAT"), ("kanagawa", "KANAGAWA-COMPAT")])
def test_LM_streamed_response_round_trips_standard_feature_collection_shape(env, client, region, marker):
    original = _tsunami_feature_collection(marker)
    target = env["version_root"] / "backend" / "hazard" / "tsunami" / f"tsunami_{region}.geojson"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(original), encoding="utf-8")
    os.chmod(target, VERSION_FILE_MODE)

    resp = client.get(f"/api/hazards/tsunami/{region}")
    parsed = resp.json()  # frontendの `await response.json()` と同じ操作

    assert parsed == original
    assert parsed["type"] == "FeatureCollection"
    assert isinstance(parsed["features"], list)


# ── N. storm_surge regression（前phaseの実装が引き続き機能） ──────────────────

def test_N_storm_surge_route_still_precedes_catch_all():
    paths = [route.path for route in hazards.router.routes]
    storm_surge_index = paths.index("/api/hazards/storm_surge/{region}")
    catch_all_index = paths.index("/api/hazards/{hazard_type}/{region_code}")
    assert storm_surge_index < catch_all_index


# ── O/P. flood 413 / pseudo・lowland 422 regression ────────────────────────────

@pytest.mark.parametrize("hazard_type,expected_status", [
    ("flood", 413),
    ("pseudo_inland_flood", 422),
    ("lowland_poor_drainage", 422),
])
def test_OP_flood_pseudo_lowland_regression_unchanged(client, hazard_type, expected_status):
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get(f"/api/hazards/{hazard_type}/tokyo")

    assert resp.status_code == expected_status
    load_mock.assert_not_called()


# ── Q. inland_flood/landslide streaming route順序不変 ──────────────────────────

@pytest.mark.parametrize("hazard_type", ["inland_flood", "landslide"])
def test_Q_inland_flood_landslide_still_precede_catch_all(hazard_type):
    paths = [route.path for route in hazards.router.routes]
    dedicated_index = paths.index(f"/api/hazards/{hazard_type}/{{region}}")
    catch_all_index = paths.index("/api/hazards/{hazard_type}/{region_code}")
    assert dedicated_index < catch_all_index


# ── catch-all remaining consumers調査: 全real typeが専用route/reject対象に ─────

def test_catch_all_has_no_remaining_real_type_consumer():
    """TSUNAMI-FALLBACK-STREAMING Phase B1完了後、catch-allの
    get_active_hazard_geojson()full-body json.load pathを実際に経由する
    現行の実hazard typeが存在しないことを確認する
    （HAZARD-PUBLIC-CATCHALL-JSONLOAD-DEAD-PATH candidateの根拠）。

    dedicated routeを持つtype（inland_flood/landslide/storm_surge/
    tsunami）とpolicy-rejected/large-response-limited type（flood/
    pseudo_inland_flood/lowland_poor_drainage）の和集合が、
    HazardDatasetService.HAZARD_LAYER_TYPESの全量と一致することを
    静的に検証する。
    """
    from app.services.hazard_dataset_service import HazardDatasetService

    dedicated_route_types = {"inland_flood", "landslide", "storm_surge", "tsunami"}
    rejected_or_limited_types = (
        hazards._HAZARD_LARGE_RESPONSE_LIMITED_TYPES | hazards._HAZARD_POLICY_REJECTED_TYPES
    )
    accounted_for = dedicated_route_types | rejected_or_limited_types

    assert accounted_for == HazardDatasetService.HAZARD_LAYER_TYPES


# ── R. tsunami-warning regression（alert UIとhazard fallback transportは独立） ─

def test_R_tsunami_warning_module_not_referenced_by_hazards_api():
    hazards_source = Path(__file__).resolve().parents[1] / "backend" / "app" / "api" / "hazards.py"
    source = hazards_source.read_text(encoding="utf-8")
    assert "tsunami_warning" not in source  # backend側hazards.pyはalert機構と無関係

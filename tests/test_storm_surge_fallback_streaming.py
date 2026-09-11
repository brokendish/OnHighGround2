"""
test_storm_surge_fallback_streaming.py — STORM-SURGE-FALLBACK-STREAMING
Phase B1 回帰テスト。

OWNER決定（STREAM_FALLBACK、2026-09-07）: `GET /api/hazards/storm_surge/
{region}` を、catch-all route経由の`json.load()`＋`JSONResponse`再
シリアライズ（tokyo≈54MB/kanagawa≈82MBのfull memory展開）から、
inland_flood/landslideと同じcurrent/versioned優先・lease保護
`StreamingResponse`／flat`FileResponse`パターンへ切り替える。
RUNTIME-VERSION-STREAM-REGION-LAYOUT-GAP Phase B0で修正済みの
`stream_versioned_glob(..., region=region)`をそのまま再利用する
（新しいlease実装は行わない）。

lease機構は本物のLeaseCoordinator/leased_version_rootをtmp_path上に
最小構成で用意して動かす（test_runtime_version_stream_region_layout.py
と同じ方針）。巨大な実artifact（50-80MB）は使わず、合成の小さな
FeatureCollectionのみを使う（Section 18）。
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
from fastapi.testclient import TestClient

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


def _storm_surge_feature_collection(marker: str) -> dict:
    """frontend側 normalizeToFeatureCollection() が期待する標準的な形状
    （実際のstorm_surge featureに近い最小構成）を合成する。"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"depth": 1.5, "marker": marker},
                "geometry": {"type": "Point", "coordinates": [139.7, 35.6]},
            }
        ],
    }


def _write_geojson(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_storm_surge_feature_collection(marker)), encoding="utf-8")
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


# ── A. Tokyo versioned stream ─────────────────────────────────────────────────

def test_A_tokyo_versioned_stream(env, client):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "storm_surge" / "tokyo" / "current.geojson",
        "TOKYO-STORM-SURGE",
    )

    resp = client.get("/api/hazards/storm_surge/tokyo")

    assert resp.status_code == 200
    body = resp.json()
    assert body["features"][0]["properties"]["marker"] == "TOKYO-STORM-SURGE"
    # StreamingResponse特有: FileResponseが自動付与するヘッダーが存在しない。
    assert "etag" not in resp.headers
    assert "last-modified" not in resp.headers


# ── B. Kanagawa versioned stream ──────────────────────────────────────────────

def test_B_kanagawa_versioned_stream(env, client):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "storm_surge" / "kanagawa" / "current.geojson",
        "KANAGAWA-STORM-SURGE",
    )

    resp = client.get("/api/hazards/storm_surge/kanagawa")

    assert resp.status_code == 200
    assert resp.json()["features"][0]["properties"]["marker"] == "KANAGAWA-STORM-SURGE"
    assert "etag" not in resp.headers


# ── I. wrong-region isolation（Tokyo/Kanagawa双方存在時に混同しない） ──────────

def test_I_wrong_region_isolation(env, client):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "storm_surge" / "tokyo" / "a.geojson", "TOKYO"
    )
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "storm_surge" / "kanagawa" / "b.geojson", "KANAGAWA"
    )

    tokyo_resp = client.get("/api/hazards/storm_surge/tokyo")
    kanagawa_resp = client.get("/api/hazards/storm_surge/kanagawa")

    assert tokyo_resp.json()["features"][0]["properties"]["marker"] == "TOKYO"
    assert kanagawa_resp.json()["features"][0]["properties"]["marker"] == "KANAGAWA"


# ── C. no json.load呼び出し（_load_json未使用の証明） ─────────────────────────

def test_C_no_load_json_called(env, client, monkeypatch):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "storm_surge" / "tokyo" / "current.geojson", "TOKYO"
    )

    load_json_calls = []
    orig = hazards.hazard_dataset_service._load_json

    def _spy(*args, **kwargs):
        load_json_calls.append(args)
        return orig(*args, **kwargs)

    monkeypatch.setattr(hazards.hazard_dataset_service, "_load_json", _spy)

    resp = client.get("/api/hazards/storm_surge/tokyo")

    assert resp.status_code == 200
    assert load_json_calls == []  # json.load()を発生させる_load_json()は一度も呼ばれない


# ── D. no get_active_hazard_geojson呼び出し ───────────────────────────────────

def test_D_no_get_active_hazard_geojson_called(env, client, monkeypatch):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "storm_surge" / "tokyo" / "current.geojson", "TOKYO"
    )

    called = {"value": False}

    def _spy(*args, **kwargs):
        called["value"] = True
        raise AssertionError("get_active_hazard_geojson should not be called for storm_surge route")

    monkeypatch.setattr(hazards.hazard_dataset_service, "get_active_hazard_geojson", _spy)

    resp = client.get("/api/hazards/storm_surge/tokyo")

    assert resp.status_code == 200
    assert called["value"] is False


# ── E. versioned-over-flat ─────────────────────────────────────────────────────

def test_E_versioned_selected_over_flat(env, client, monkeypatch, tmp_path):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "storm_surge" / "tokyo" / "current.geojson", "VERSIONED"
    )
    flat_file = tmp_path / "flat" / "tokyo_storm_surge.geojson"
    _write_geojson(flat_file, "FLAT")

    flat_called = {"value": False}

    def _flat_spy(hazard_type, region):
        flat_called["value"] = True
        return flat_file

    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", _flat_spy)

    resp = client.get("/api/hazards/storm_surge/tokyo")

    assert resp.status_code == 200
    assert resp.json()["features"][0]["properties"]["marker"] == "VERSIONED"
    assert flat_called["value"] is False  # flat resolverへは一切降りない


# ── F. flat fallback（versioned無し、flatあり） ────────────────────────────────

def test_F_flat_fallback_used_when_no_versioned_artifact(env, client, monkeypatch, tmp_path):
    # storm_surge/tokyoディレクトリ自体を作らない（真の未配備）。
    flat_file = tmp_path / "flat" / "tokyo_storm_surge.geojson"
    _write_geojson(flat_file, "FLAT-FALLBACK")

    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", lambda hazard_type, region: flat_file)

    resp = client.get("/api/hazards/storm_surge/tokyo")

    assert resp.status_code == 200
    assert resp.json()["features"][0]["properties"]["marker"] == "FLAT-FALLBACK"
    assert "etag" in resp.headers  # FileResponse特有のヘッダー（既存契約通り）


# ── G. 404 semantics（versioned/flat双方無し） ────────────────────────────────

def test_G_404_when_both_versioned_and_flat_absent(env, client, monkeypatch):
    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", lambda hazard_type, region: None)

    resp = client.get("/api/hazards/storm_surge/tokyo")

    assert resp.status_code == 404
    assert "storm_surge" in resp.json()["detail"]


# ── H. generic 500（内部エラー時、path/errno非leak） ──────────────────────────

def test_H_internal_error_does_not_leak_path(env, client, monkeypatch):
    leaked_path = "/data_runtime/versions/xxx/backend/hazard/storm_surge/tokyo/current.geojson"

    def _boom(*args, **kwargs):
        raise OSError(f"[Errno 13] Permission denied: '{leaked_path}'")

    monkeypatch.setattr(hazards, "_runtime_stream_or_none", _boom)

    resp = client.get("/api/hazards/storm_surge/tokyo")

    assert resp.status_code == 500
    assert leaked_path not in resp.text
    assert "Errno" not in resp.text


# ── J. route-order（storm_surgeがcatch-allより先に登録されている） ────────────

def test_J_storm_surge_route_registered_before_catch_all():
    paths = [route.path for route in hazards.router.routes]
    storm_surge_index = paths.index("/api/hazards/storm_surge/{region}")
    catch_all_index = paths.index("/api/hazards/{hazard_type}/{region_code}")
    assert storm_surge_index < catch_all_index


# ── K/L. flood/pseudo/lowland regression（catch-all側、変更なし） ─────────────

@pytest.mark.parametrize("hazard_type,expected_status", [
    ("flood", 413),
    ("pseudo_inland_flood", 422),
    ("lowland_poor_drainage", 422),
])
def test_KL_flood_pseudo_lowland_regression_unchanged(client, monkeypatch, hazard_type, expected_status):
    with patch.object(hazards.hazard_dataset_service, "has_active_hazard_dataset", return_value=True), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_geojson") as load_mock:
        resp = client.get(f"/api/hazards/{hazard_type}/tokyo")

    assert resp.status_code == expected_status
    load_mock.assert_not_called()


# ── M. tsunami regression（catch-all側、json.loadパス無変更） ─────────────────

def test_M_tsunami_regression_still_uses_catch_all_json_load(client, monkeypatch):
    fake_geojson = {"type": "FeatureCollection", "features": []}
    with patch.object(
        hazards.hazard_dataset_service, "get_active_hazard_geojson", return_value=fake_geojson,
    ) as load_mock:
        resp = client.get("/api/hazards/tsunami/tokyo")

    assert resp.status_code == 200
    assert resp.json() == fake_geojson
    load_mock.assert_called_once_with("tsunami", "tokyo")  # storm_surgeとは異なりcatch-all経由のまま


# ── N. inland_flood/landslide streaming unchanged（storm_surge追加の影響なし） ─

@pytest.mark.parametrize("hazard_type", ["inland_flood", "landslide"])
def test_N_inland_flood_landslide_still_precede_catch_all(hazard_type):
    paths = [route.path for route in hazards.router.routes]
    dedicated_index = paths.index(f"/api/hazards/{hazard_type}/{{region}}")
    catch_all_index = paths.index("/api/hazards/{hazard_type}/{region_code}")
    assert dedicated_index < catch_all_index


# ── O. frontend fallback compatibility ─────────────────────────────────────────
# frontend側 loadHazardLayer() は apiFetch(...).json() → normalizeToFeatureCollection()
# という手順のみに依存し、サーバー側の生成方式（streaming vs single-shot）には
# 一切依存しない（Phase A調査で確認済み）。ここではStreamingResponse化された
# storm_surge routeのresponse bodyが、frontendが要求する標準的な
# FeatureCollection形状のまま損失なく往復することを直接証明する。

def test_O_streamed_response_round_trips_standard_feature_collection_shape(env, client):
    original = _storm_surge_feature_collection("FRONTEND-COMPAT")
    target = env["version_root"] / "backend" / "hazard" / "storm_surge" / "tokyo" / "current.geojson"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(original), encoding="utf-8")
    os.chmod(target, VERSION_FILE_MODE)

    resp = client.get("/api/hazards/storm_surge/tokyo")
    parsed = resp.json()  # frontendの `await response.json()` と同じ操作

    assert parsed == original  # streaming経由でも内容が完全に一致（feature欠落/順序破壊なし）
    assert parsed["type"] == "FeatureCollection"
    assert isinstance(parsed["features"], list)
    assert parsed["features"][0]["geometry"]["type"] == "Point"

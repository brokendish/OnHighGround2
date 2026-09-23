"""
test_runtime_version_stream_region_layout.py — RUNTIME-VERSION-STREAM-
REGION-LAYOUT-GAP Phase B0 回帰テスト。

`runtime_version_access.stream_versioned_glob()` は従来
`<subdir_relative>` 直下を非再帰globしていたため、Dual Storage
Remediation Phase C1で確立された実際のruntime layout
（`<subdir_relative>/<region>/<file>`、region配下directory）へ到達
できず、常にNoneを返していた。この結果、inland_flood/landslideは
「current/versioned優先・lease保護streaming」という設計意図に反し、
実機では常にflat mirror経由のFileResponseで配信されていた
（`content-length`/`last-modified`/`etag`ヘッダーの存在で実証済み）。

Phase B0は`stream_versioned_glob()`に`region`引数を追加し、
1. `<subdir_relative>/<region>/*.geojson`（region subdirectory、primary）
2. `<subdir_relative>`直下の`patterns`glob（legacy direct-child、fallback）
という優先順位を導入する。既存のfallback semantics（一致0件→None→
呼び出し側がFileResponseへfallback）・lease lifecycle（acquire→
resolve→stream→renew→release）・HTTP contractは変更しない。

lease機構は本物のLeaseCoordinator/leased_version_rootをtmp_path上に
最小構成で用意して動かす（test_hazard_dataset_service_current_priority.py
と同じ方針: mock化しすぎるとlease契約自体の検証にならないため）。
"""
from __future__ import annotations

import asyncio
import errno
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import runtime_lease  # noqa: E402
from app.services.runtime_lease import LeaseCoordinator  # noqa: E402
from app.services import runtime_version_access as rva  # noqa: E402
from app.services.runtime_publish import VERSION_FILE_MODE  # noqa: E402


VERSION_ID = "20260101T000000Z-aaaaaaaa"


def _fake_renameat2_noreplace(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None:
    """renameat2(2)はLinux専用syscallでmacOSでは利用不能
    （test_hazard_dataset_service_current_priority.pyと同じ代替、本番コード
    は変更しない）。"""
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


def _write_geojson(path: Path, marker: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"type": "FeatureCollection", "features": [], "marker": marker}),
        encoding="utf-8",
    )
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
    # stream_versioned_glob()/stream_versioned_file()はcoordinatorの
    # leases_owner_uid設定とは独立に、モジュールレベルの
    # _LEASES_OWNER_UID/_LEASES_GID（本番ではoperator uid:leases gid）で
    # data_runtime root/version directory/配信fileのownershipを検証する
    # （leased_version_rootとは別の検証経路）。test実行ユーザーの
    # uid/gidへ合わせないと、tmp_path上のfileが本物のoperator所有では
    # ないためownership検証が常に失敗する。
    monkeypatch.setattr(rva, "_LEASES_OWNER_UID", os.getuid())
    monkeypatch.setattr(rva, "_LEASES_GID", os.getgid())
    monkeypatch.setattr(runtime_lease, "renameat2_noreplace", _fake_renameat2_noreplace)

    return {
        "data_runtime_root": data_runtime_root,
        "version_root": version_root,
        "coordinator": coordinator,
        "leases_root": leases_root,
    }


async def _collect(gen) -> bytes:
    chunks = []
    async for chunk in gen:
        chunks.append(chunk)
    return b"".join(chunks)


def _stream_and_collect(subdir_relative, patterns, request_kind, region=None):
    async def _run():
        gen = await rva.stream_versioned_glob(subdir_relative, patterns, request_kind, region=region)
        if gen is None:
            return None
        return await _collect(gen)

    return asyncio.run(_run())


# ── A. region-subdirectory current artifactを発見 ────────────────────────────

def test_A_region_subdirectory_artifact_discovered(env):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "tokyo" / "tokyo-urban-001.geojson",
        "TOKYO-CURRENT",
    )

    content = _stream_and_collect(
        "backend/hazard/inland_flood",
        ["tokyo_*.geojson", "tokyo-*.geojson"],
        "http-hazard-inland_flood",
        region="tokyo",
    )

    assert content is not None
    assert json.loads(content)["marker"] == "TOKYO-CURRENT"


# ── B. TokyoがKanagawa artifactを選ばない ─────────────────────────────────────

def test_B_tokyo_does_not_select_kanagawa_artifact(env):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "tokyo" / "a.geojson", "TOKYO"
    )
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "kanagawa" / "b.geojson", "KANAGAWA"
    )

    content = _stream_and_collect(
        "backend/hazard/inland_flood",
        ["tokyo_*.geojson", "tokyo-*.geojson"],
        "http-hazard-inland_flood",
        region="tokyo",
    )

    assert json.loads(content)["marker"] == "TOKYO"


# ── C. KanagawaがTokyo artifactを選ばない ─────────────────────────────────────

def test_C_kanagawa_does_not_select_tokyo_artifact(env):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "tokyo" / "a.geojson", "TOKYO"
    )
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "kanagawa" / "b.geojson", "KANAGAWA"
    )

    content = _stream_and_collect(
        "backend/hazard/inland_flood",
        ["kanagawa_*.geojson", "kanagawa-*.geojson"],
        "http-hazard-inland_flood",
        region="kanagawa",
    )

    assert json.loads(content)["marker"] == "KANAGAWA"


# ── D. lease acquire before resolution ────────────────────────────────────────

def test_D_lease_acquired_before_resolution(env, monkeypatch):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "landslide" / "tokyo" / "x.geojson", "TOKYO"
    )

    coordinator = env["coordinator"]
    calls = []
    orig_acquire = coordinator.acquire_current

    def _spy(*args, **kwargs):
        calls.append("acquire")
        return orig_acquire(*args, **kwargs)

    monkeypatch.setattr(coordinator, "acquire_current", _spy)

    async def _run():
        gen = await rva.stream_versioned_glob(
            "backend/hazard/landslide", ["tokyo_*.geojson", "tokyo-*.geojson"],
            "http-hazard-landslide", region="tokyo",
        )
        # acquireはgenerator生成前（stream_versioned_glob自体のawait完了時点）
        # に既に完了していなければならない。
        assert calls == ["acquire"]
        return await _collect(gen)

    content = asyncio.run(_run())
    assert json.loads(content)["marker"] == "TOKYO"


# ── E. lease held during first/middle/final chunk ─────────────────────────────

def test_E_lease_held_through_entire_stream_lifecycle(env, monkeypatch):
    # chunk単位での挙動を検証するため、chunk sizeを小さくする。
    monkeypatch.setattr(rva, "_CHUNK_SIZE", 4)

    payload = json.dumps({"type": "FeatureCollection", "features": [], "marker": "TOKYO" * 5}).encode()
    target = env["version_root"] / "backend" / "hazard" / "landslide" / "tokyo" / "x.geojson"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    os.chmod(target, VERSION_FILE_MODE)

    coordinator = env["coordinator"]
    release_calls = []
    orig_release = coordinator.release

    def _spy_release(handle):
        release_calls.append(handle)
        return orig_release(handle)

    monkeypatch.setattr(coordinator, "release", _spy_release)

    async def _run():
        gen = await rva.stream_versioned_glob(
            "backend/hazard/landslide", ["tokyo_*.geojson", "tokyo-*.geojson"],
            "http-hazard-landslide", region="tokyo",
        )
        first = await gen.__anext__()
        assert release_calls == []  # 最初のchunk取得時点でまだreleaseされていない

        middle_chunks = [first]
        for _ in range(3):
            middle_chunks.append(await gen.__anext__())
        assert release_calls == []  # 中間chunk取得時点でもまだ

        remaining = [c async for c in gen]  # 最後まで消費（generator exhaust）
        assert len(release_calls) == 1  # exhaust後、初めてreleaseが1回だけ呼ばれる
        return b"".join(middle_chunks) + b"".join(remaining)

    content = asyncio.run(_run())
    assert content == payload


# ── F. lease renewal occurs when required ─────────────────────────────────────

def test_F_lease_renewal_occurs_mid_stream(env, monkeypatch):
    monkeypatch.setattr(rva, "_CHUNK_SIZE", 4)
    monkeypatch.setattr(rva, "_RENEW_AFTER_S", 0.0)  # 常に閾値超過扱いにする

    payload = b"0123456789ABCDEF"  # 4chunk分
    target = env["version_root"] / "backend" / "hazard" / "landslide" / "tokyo" / "x.geojson"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    os.chmod(target, VERSION_FILE_MODE)

    coordinator = env["coordinator"]
    renew_calls = []
    orig_renew = coordinator.renew

    def _spy_renew(handle):
        renew_calls.append(handle)
        return orig_renew(handle)

    monkeypatch.setattr(coordinator, "renew", _spy_renew)

    content = _stream_and_collect(
        "backend/hazard/landslide", ["tokyo_*.geojson", "tokyo-*.geojson"],
        "http-hazard-landslide", region="tokyo",
    )

    assert content == payload
    assert len(renew_calls) >= 1  # 閾値0のため複数chunkのいずれかで最低1回はrenewされる


# ── G. generator close時にもrelease ───────────────────────────────────────────

def test_G_generator_close_still_releases_lease(env, monkeypatch):
    monkeypatch.setattr(rva, "_CHUNK_SIZE", 4)

    payload = b"0123456789ABCDEF"
    target = env["version_root"] / "backend" / "hazard" / "landslide" / "tokyo" / "x.geojson"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    os.chmod(target, VERSION_FILE_MODE)

    coordinator = env["coordinator"]
    release_calls = []
    orig_release = coordinator.release

    def _spy_release(handle):
        release_calls.append(handle)
        return orig_release(handle)

    monkeypatch.setattr(coordinator, "release", _spy_release)

    async def _run():
        gen = await rva.stream_versioned_glob(
            "backend/hazard/landslide", ["tokyo_*.geojson", "tokyo-*.geojson"],
            "http-hazard-landslide", region="tokyo",
        )
        await gen.__anext__()  # 部分消費のみ（client切断を模擬）
        await gen.aclose()  # StreamingResponse側が中断時に呼ぶのと同じ操作

    asyncio.run(_run())
    assert len(release_calls) == 1  # 中断時でもfinallyでreleaseが1回だけ呼ばれる


# ── H. no versioned file → existing fallback semantics（Noneを返す） ──────────

def test_H_no_versioned_file_returns_none(env):
    # inland_flood/tokyoディレクトリ自体を作らない（真の未配備）
    content = _stream_and_collect(
        "backend/hazard/inland_flood",
        ["tokyo_*.geojson", "tokyo-*.geojson"],
        "http-hazard-inland_flood",
        region="tokyo",
    )
    assert content is None


# ── I. legacy direct-child layout compatibility（region省略時は従来通り） ─────

def test_I_legacy_direct_child_layout_still_works_without_region(env):
    # region subdirectoryではなく、hazard_type直下にlegacy命名で配置。
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "flood" / "tokyo-river-001.geojson", "LEGACY-FLAT-STYLE"
    )

    content = _stream_and_collect(
        "backend/hazard/flood", ["tokyo_*.geojson", "tokyo-*.geojson"], "http-hazard-flood",
    )  # region未指定＝従来呼び出し

    assert json.loads(content)["marker"] == "LEGACY-FLAT-STYLE"


def test_I2_legacy_direct_child_layout_used_as_fallback_when_region_subdir_absent(env):
    # region引数はあるが、region subdirectoryが存在しない場合は
    # legacy direct-child globへ降格する。
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "flood" / "tokyo-river-001.geojson", "LEGACY-FALLBACK"
    )

    content = _stream_and_collect(
        "backend/hazard/flood", ["tokyo_*.geojson", "tokyo-*.geojson"], "http-hazard-flood",
        region="tokyo",
    )

    assert json.loads(content)["marker"] == "LEGACY-FALLBACK"


# ── J. wrong-region artifact ignored（region subdir存在時、legacy側の別region
#      命名ファイルが混入しないこと） ─────────────────────────────────────────

def test_J_wrong_region_legacy_artifact_ignored_when_region_subdir_present(env):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "flood" / "tokyo" / "current.geojson", "TOKYO-CURRENT"
    )
    # legacy側に紛らわしい別regionのfileが同じhazard_typeディレクトリ直下に
    # 存在していても、region subdirectoryが見つかった時点でlegacy globは
    # 一切試みられない。
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "flood" / "kanagawa-legacy-001.geojson", "WRONG-REGION"
    )

    content = _stream_and_collect(
        "backend/hazard/flood", ["tokyo_*.geojson", "tokyo-*.geojson"], "http-hazard-flood",
        region="tokyo",
    )

    assert json.loads(content)["marker"] == "TOKYO-CURRENT"


# ── K. backup/irrelevant file ignored（拡張子フィルタによる除外） ─────────────

def test_K_backup_irrelevant_file_ignored(env):
    region_dir = env["version_root"] / "backend" / "hazard" / "storm_surge" / "tokyo"
    _write_geojson(region_dir / "current.geojson", "REAL")
    (region_dir / "current.geojson.bak").write_text("stale backup, not valid geojson filter target")
    (region_dir / "README.txt").write_text("irrelevant")

    content = _stream_and_collect(
        "backend/hazard/storm_surge", ["tokyo_*.geojson", "tokyo-*.geojson"], "http-hazard-storm_surge",
        region="tokyo",
    )

    assert json.loads(content)["marker"] == "REAL"


# ── L. 無制限recursive globを使っていないことの確認（別hazard_typeへ越境しない）

def test_L_does_not_cross_into_sibling_hazard_type_directory(env):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "tokyo" / "a.geojson", "INLAND"
    )
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "landslide" / "tokyo" / "b.geojson", "LANDSLIDE"
    )

    content = _stream_and_collect(
        "backend/hazard/inland_flood", ["tokyo_*.geojson", "tokyo-*.geojson"], "http-hazard-inland_flood",
        region="tokyo",
    )

    assert json.loads(content)["marker"] == "INLAND"


# ── Source contract proof: versioned + flat両方存在時、versionedが選択される ───
# （Section 14: current/versioned primary contractの明示的証明）

def test_versioned_selected_over_flat_when_both_exist(env, tmp_path):
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "tokyo" / "current.geojson", "VERSIONED"
    )
    flat_file = tmp_path / "flat_mirror" / "tokyo-urban-001.geojson"
    _write_geojson(flat_file, "FLAT")

    content = _stream_and_collect(
        "backend/hazard/inland_flood", ["tokyo_*.geojson", "tokyo-*.geojson"], "http-hazard-inland_flood",
        region="tokyo",
    )

    # stream_versioned_globはflat側を一切見ない（そもそもflatを探索する
    # コードパスを持たない）——戻り値がVERSIONED markerであることで、
    # 呼び出し側（hazards.py）がこれをNoneでない限りFileResponse
    # fallbackへ進まない、という既存contractと合わせて「versioned優先」
    # を証明する。
    assert json.loads(content)["marker"] == "VERSIONED"
    assert flat_file.exists()  # flat側は変更・削除されず存在し続ける（無関係）


# ── region引数省略時は完全に従来動作（後方互換） ──────────────────────────────

def test_region_omitted_preserves_prior_direct_child_only_behavior(env):
    # region subdirectoryを用意しても、regionを渡さない限り一切見に行かない
    # （既存呼び出し元がある場合の後方互換）。
    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "tokyo" / "a.geojson", "SHOULD-NOT-BE-SEEN"
    )

    content = _stream_and_collect(
        "backend/hazard/inland_flood", ["tokyo_*.geojson", "tokyo-*.geojson"], "http-hazard-inland_flood",
    )  # region省略

    assert content is None  # legacy direct-child globにも一致しないため従来通りNone


# ── Section 12: inland_flood route regression（versioned streaming path使用の証明）

def test_inland_flood_route_uses_versioned_streaming_not_flat_fallback(env, monkeypatch):
    from fastapi import FastAPI
    from _testclient_compat import TestClient
    from app.api import hazards

    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "inland_flood" / "tokyo" / "current.geojson",
        "ROUTE-VERSIONED",
    )

    monkeypatch.setattr(hazards.runtime_version_access, "LEASES_ROOT", env["leases_root"])
    monkeypatch.setattr(hazards.runtime_version_access, "DATA_RUNTIME_ROOT", env["data_runtime_root"])
    monkeypatch.setattr(hazards.runtime_version_access, "_coordinator", env["coordinator"])
    monkeypatch.setattr(hazards.runtime_version_access, "get_coordinator", lambda: env["coordinator"])

    flat_fallback_called = {"value": False}

    def _flat_spy(hazard_type, region):
        flat_fallback_called["value"] = True
        return None

    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", _flat_spy)

    app = FastAPI()
    app.include_router(hazards.router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/hazards/inland_flood/tokyo")

    assert resp.status_code == 200
    assert resp.json()["marker"] == "ROUTE-VERSIONED"
    assert flat_fallback_called["value"] is False  # flat fallbackへは一切降りない
    # StreamingResponse特有のヘッダー欠如（content-length/etag自動付与なし）
    # がFileResponseではなくStreamingResponse経由であることの傍証。
    assert "etag" not in resp.headers
    assert "last-modified" not in resp.headers


# ── Section 13: landslide route regression（同上、mock/fixtureのみ） ──────────

def test_landslide_route_uses_versioned_streaming_not_flat_fallback(env, monkeypatch):
    from fastapi import FastAPI
    from _testclient_compat import TestClient
    from app.api import hazards

    _write_geojson(
        env["version_root"] / "backend" / "hazard" / "landslide" / "kanagawa" / "current.geojson",
        "ROUTE-VERSIONED-LANDSLIDE",
    )

    monkeypatch.setattr(hazards.runtime_version_access, "LEASES_ROOT", env["leases_root"])
    monkeypatch.setattr(hazards.runtime_version_access, "DATA_RUNTIME_ROOT", env["data_runtime_root"])
    monkeypatch.setattr(hazards.runtime_version_access, "_coordinator", env["coordinator"])
    monkeypatch.setattr(hazards.runtime_version_access, "get_coordinator", lambda: env["coordinator"])

    flat_fallback_called = {"value": False}

    def _flat_spy(hazard_type, region):
        flat_fallback_called["value"] = True
        return None

    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", _flat_spy)

    app = FastAPI()
    app.include_router(hazards.router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/hazards/landslide/kanagawa")

    assert resp.status_code == 200
    assert resp.json()["marker"] == "ROUTE-VERSIONED-LANDSLIDE"
    assert flat_fallback_called["value"] is False


# ── route regression: versioned側に無い場合は従来通りflat fallbackへ降りる ─────

def test_inland_flood_route_falls_back_to_flat_when_no_versioned_artifact(env, monkeypatch, tmp_path):
    from fastapi import FastAPI
    from _testclient_compat import TestClient
    from app.api import hazards

    # versioned側にinland_flood/tokyoを一切用意しない（真の未配備）。

    monkeypatch.setattr(hazards.runtime_version_access, "LEASES_ROOT", env["leases_root"])
    monkeypatch.setattr(hazards.runtime_version_access, "DATA_RUNTIME_ROOT", env["data_runtime_root"])
    monkeypatch.setattr(hazards.runtime_version_access, "_coordinator", env["coordinator"])
    monkeypatch.setattr(hazards.runtime_version_access, "get_coordinator", lambda: env["coordinator"])

    flat_file = tmp_path / "flat" / "tokyo-urban-001.geojson"
    _write_geojson(flat_file, "FLAT-FALLBACK")
    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", lambda hazard_type, region: flat_file)

    app = FastAPI()
    app.include_router(hazards.router)
    client = TestClient(app, raise_server_exceptions=False)

    resp = client.get("/api/hazards/inland_flood/tokyo")

    assert resp.status_code == 200
    assert resp.json()["marker"] == "FLAT-FALLBACK"
    assert "etag" in resp.headers  # FileResponse特有のヘッダー

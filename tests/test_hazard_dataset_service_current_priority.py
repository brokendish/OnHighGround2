"""
test_hazard_dataset_service_current_priority.py — Dual Storage Remediation
Phase C2（HazardDatasetService current/versioned priority）テスト。

HazardDatasetService.get_active_hazard_geojson() が
  Tier 1: current/versioned（lease保護）
  Tier 2: flat（既存 _resolve_active_dataset 経由）
の優先順で解決し、current側が存在する限りflatを一切見ないこと、
current側が壊れている場合はflatへ隠蔽逃げしないこと（fail-closed）、
lease acquire/releaseが実際に呼ばれること、を検証する。

lease機構は本物の LeaseCoordinator / leased_version_root をtmp_path上に
最小構成で用意して動かす（mock化しすぎるとlease契約自体の検証にならない
ため）。coordination.lockのowner検証は leases_owner_uid=None で意図的に
skipする（runtime_lease.pyのdocstringに明記された「test harness等との
後方互換」目的の既定動作）。
"""
from __future__ import annotations

import errno
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.hazard_dataset_service import HazardDatasetService  # noqa: E402
from app.services import runtime_lease  # noqa: E402
from app.services.runtime_lease import LeaseCoordinator  # noqa: E402
from app.services import runtime_version_access as rva  # noqa: E402


VERSION_ID = "20260101T000000Z-aaaaaaaa"


def _fake_renameat2_noreplace(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None:
    """renameat2(2)はLinux専用syscallでmacOSでは利用不能
    （backend/app/services/runtime_atomic.py参照）。lease契約自体の検証
    （このtestの目的）とは無関係な環境依存syscallのため、check-then-rename
    ではあるがtest専用にdirfd相対renameで代替する（本番コードは変更しない、
    テストからのみ差し替える）。"""
    try:
        os.stat(dst_name, dir_fd=dst_dir_fd, follow_symlinks=False)
        raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), dst_name)
    except FileNotFoundError:
        pass
    os.rename(src_name, dst_name, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)


def _setup_lease_environment(tmp_path: Path) -> Path:
    """coordination.lock/active/locks/retiredを最小構成で用意する。
    leases_owner_uid=Noneで動かす前提のため、owner/modeはprocess自身の
    実行ユーザーに揃えれば十分（本番のoperator専用ownershipは要求しない）。
    """
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


@pytest.fixture
def env(tmp_path, monkeypatch):
    """current機構が導入済み・正常な最小環境。current対象datasetは
    テストごとに個別に配置する。flat側の解決（_resolve_active_dataset）は
    active_mapping/definition/state serviceをmonkeypatchする。"""
    leases_root = _setup_lease_environment(tmp_path)
    data_runtime_root, version_root = _setup_data_runtime(tmp_path)
    coordinator = _make_coordinator(leases_root)

    monkeypatch.setattr(rva, "LEASES_ROOT", leases_root)
    monkeypatch.setattr(rva, "DATA_RUNTIME_ROOT", data_runtime_root)
    monkeypatch.setattr(rva, "_coordinator", coordinator)
    monkeypatch.setattr(rva, "get_coordinator", lambda: coordinator)
    monkeypatch.setattr(runtime_lease, "renameat2_noreplace", _fake_renameat2_noreplace)

    return {
        "data_runtime_root": data_runtime_root,
        "version_root": version_root,
        "coordinator": coordinator,
        "leases_root": leases_root,
    }


def _patch_flat_resolution(monkeypatch, service: HazardDatasetService, flat_path):
    """_resolve_active_dataset()（flat/DatasetState経由）をmockし、
    flat_pathがNoneならFileNotFoundError、そうでなければそのPathを返す。"""
    def _fake(hazard_type, region_code):
        if hazard_type not in service.HAZARD_LAYER_TYPES:
            raise KeyError(f"Unsupported hazard_type: {hazard_type}")
        if flat_path is None:
            raise FileNotFoundError("Active dataset is not registered")
        return ("FAKE-DATASET", None, None, flat_path)

    monkeypatch.setattr(service, "_resolve_active_dataset", _fake)


# ── A. current exists + flat exists → current ────────────────────────────────

def test_A_current_and_flat_both_exist_prefers_current(env, tmp_path, monkeypatch):
    service = HazardDatasetService()
    current_file = env["version_root"] / "backend" / "hazard" / "flood" / "tokyo" / "tokyo-river-001.geojson"
    _write_geojson(current_file, "CURRENT")

    flat_file = tmp_path / "flat" / "tokyo-river-001.geojson"
    _write_geojson(flat_file, "FLAT")
    _patch_flat_resolution(monkeypatch, service, flat_file)

    result = service.get_active_hazard_geojson("flood", "tokyo")
    assert result["marker"] == "CURRENT"


# ── B. current absent + flat exists → flat ────────────────────────────────────

def test_B_current_dataset_absent_falls_back_to_flat(env, tmp_path, monkeypatch):
    service = HazardDatasetService()
    # current側にflood/tokyoディレクトリを作らない（真の未配備）

    flat_file = tmp_path / "flat" / "tokyo-river-001.geojson"
    _write_geojson(flat_file, "FLAT")
    _patch_flat_resolution(monkeypatch, service, flat_file)

    result = service.get_active_hazard_geojson("flood", "tokyo")
    assert result["marker"] == "FLAT"


def test_B2_current_mechanism_not_initialized_falls_back_to_flat(tmp_path, monkeypatch):
    """coordination.lock自体が存在しない（atomic publish機構未導入）場合も
    flatへfallbackする（真の未導入環境、既存is_available()契約）。"""
    leases_root = tmp_path / "leases_missing"
    monkeypatch.setattr(rva, "LEASES_ROOT", leases_root)  # mkdirしない = 未導入

    service = HazardDatasetService()
    flat_file = tmp_path / "flat" / "tokyo-river-001.geojson"
    _write_geojson(flat_file, "FLAT")
    _patch_flat_resolution(monkeypatch, service, flat_file)

    result = service.get_active_hazard_geojson("flood", "tokyo")
    assert result["marker"] == "FLAT"


# ── C. both absent → existing 404相当（例外がそのまま伝播） ──────────────────

def test_C_both_absent_raises_existing_not_found(env, monkeypatch):
    service = HazardDatasetService()
    # currentにもflatにも対象datasetを置かない
    _patch_flat_resolution(monkeypatch, service, None)

    with pytest.raises(FileNotFoundError):
        service.get_active_hazard_geojson("flood", "tokyo")


# ── D. current malformed → flatへ隠蔽逃げしない ──────────────────────────────

def test_D_current_malformed_does_not_hide_behind_flat(env, tmp_path, monkeypatch):
    service = HazardDatasetService()
    current_file = env["version_root"] / "backend" / "hazard" / "flood" / "tokyo" / "broken.geojson"
    current_file.parent.mkdir(parents=True, exist_ok=True)
    current_file.write_text("{not valid json", encoding="utf-8")

    flat_file = tmp_path / "flat" / "tokyo-river-001.geojson"
    _write_geojson(flat_file, "FLAT")
    _patch_flat_resolution(monkeypatch, service, flat_file)

    with pytest.raises(ValueError):
        service.get_active_hazard_geojson("flood", "tokyo")


# ── E. current unsupported region → flat fallback ────────────────────────────

def test_E_current_missing_region_falls_back_to_flat(env, tmp_path, monkeypatch):
    service = HazardDatasetService()
    # flood/tokyoは存在するが、kanagawaは無い
    _write_geojson(env["version_root"] / "backend" / "hazard" / "flood" / "tokyo" / "x.geojson", "CURRENT")

    flat_file = tmp_path / "flat" / "kanagawa-river-001.geojson"
    _write_geojson(flat_file, "FLAT")
    _patch_flat_resolution(monkeypatch, service, flat_file)

    result = service.get_active_hazard_geojson("flood", "kanagawa")
    assert result["marker"] == "FLAT"


# ── F. pseudo tokyo → current ─────────────────────────────────────────────────

def test_F_pseudo_inland_flood_tokyo_prefers_current(env, tmp_path, monkeypatch):
    service = HazardDatasetService()
    current_file = env["version_root"] / "backend" / "hazard" / "pseudo_inland_flood" / "tokyo" / "pseudo_inland_flood.geojson"
    _write_geojson(current_file, "CURRENT")

    flat_file = tmp_path / "flat" / "pseudo_inland_flood.geojson"
    _write_geojson(flat_file, "FLAT")
    _patch_flat_resolution(monkeypatch, service, flat_file)

    result = service.get_active_hazard_geojson("pseudo_inland_flood", "tokyo")
    assert result["marker"] == "CURRENT"


# ── G. pseudo kanagawa → 既存のunsupported挙動 ────────────────────────────────

def test_G_pseudo_inland_flood_kanagawa_unsupported_falls_through(env, monkeypatch):
    service = HazardDatasetService()
    # current側にpseudo_inland_flood/kanagawaは存在しない（仕様上サポート外）
    _patch_flat_resolution(monkeypatch, service, None)  # flat側にも登録なし

    with pytest.raises(FileNotFoundError):
        service.get_active_hazard_geojson("pseudo_inland_flood", "kanagawa")


# ── H. unknown type → 従来どおり拒否（currentすら見ない） ────────────────────

def test_H_unknown_hazard_type_rejected_without_touching_current(env, monkeypatch):
    service = HazardDatasetService()
    called = {"current": False}

    def _spy(*args, **kwargs):
        called["current"] = True
        return None

    monkeypatch.setattr(service, "_try_load_geojson_from_current", _spy)

    with pytest.raises(KeyError):
        service.get_active_hazard_geojson("totally_unknown_type", "tokyo")

    assert called["current"] is False


# ── I. lease acquire/release ──────────────────────────────────────────────────

def test_I_lease_acquire_and_release_called_on_current_read(env, tmp_path, monkeypatch):
    service = HazardDatasetService()
    current_file = env["version_root"] / "backend" / "hazard" / "flood" / "tokyo" / "x.geojson"
    _write_geojson(current_file, "CURRENT")

    coordinator = env["coordinator"]
    acquire_calls = []
    release_calls = []
    orig_acquire = coordinator.acquire_current
    orig_release = coordinator.release

    def _spy_acquire(*args, **kwargs):
        handle = orig_acquire(*args, **kwargs)
        acquire_calls.append(handle)
        return handle

    def _spy_release(handle):
        release_calls.append(handle)
        return orig_release(handle)

    monkeypatch.setattr(coordinator, "acquire_current", _spy_acquire)
    monkeypatch.setattr(coordinator, "release", _spy_release)

    result = service.get_active_hazard_geojson("flood", "tokyo")
    assert result["marker"] == "CURRENT"
    assert len(acquire_calls) == 1
    assert len(release_calls) == 1


def test_I2_flat_fallback_when_mechanism_unavailable_does_not_touch_lease(tmp_path, monkeypatch):
    """atomic publish機構自体が未導入（coordination.lock不在）の場合は
    lease coordinatorに一切触れない。"""
    leases_root = tmp_path / "leases_missing"
    monkeypatch.setattr(rva, "LEASES_ROOT", leases_root)

    called = {"coordinator": False}

    def _fake_get_coordinator():
        called["coordinator"] = True
        raise AssertionError("coordinatorへ触れるべきではない")

    monkeypatch.setattr(rva, "get_coordinator", _fake_get_coordinator)

    service = HazardDatasetService()
    flat_file = tmp_path / "flat" / "tokyo-river-001.geojson"
    _write_geojson(flat_file, "FLAT")
    _patch_flat_resolution(monkeypatch, service, flat_file)

    result = service.get_active_hazard_geojson("flood", "tokyo")
    assert result["marker"] == "FLAT"
    assert called["coordinator"] is False


# ── J. response schema/status unchanged（既存構造の維持） ────────────────────

def test_J_response_is_plain_dict_matching_existing_schema(env, tmp_path, monkeypatch):
    service = HazardDatasetService()
    current_file = env["version_root"] / "backend" / "hazard" / "flood" / "tokyo" / "x.geojson"
    current_file.parent.mkdir(parents=True, exist_ok=True)
    current_file.write_text(
        json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": None}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(service, "_resolve_active_dataset", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError()))

    result = service.get_active_hazard_geojson("flood", "tokyo")
    assert isinstance(result, dict)
    assert result["type"] == "FeatureCollection"
    assert isinstance(result["features"], list)


# ── Divergent content: current優先を明示的に証明 ──────────────────────────────

def test_divergent_current_and_flat_content_current_wins(env, tmp_path, monkeypatch):
    service = HazardDatasetService()
    current_file = env["version_root"] / "backend" / "hazard" / "storm_surge" / "tokyo" / "a.geojson"
    _write_geojson(current_file, "CURRENT-DIFFERENT-CONTENT")

    flat_file = tmp_path / "flat" / "b.geojson"
    _write_geojson(flat_file, "FLAT-DIFFERENT-CONTENT")
    _patch_flat_resolution(monkeypatch, service, flat_file)

    result = service.get_active_hazard_geojson("storm_surge", "tokyo")
    assert result["marker"] == "CURRENT-DIFFERENT-CONTENT"


# ── 横断整合性: resolver / validator / HazardDatasetService の type set drift検知 ──

# ── current switch consistency: read中にcurrentが切り替わっても壊れない ──────

def test_current_switch_mid_read_does_not_corrupt_active_read(env, tmp_path, monkeypatch):
    """acquire_current()はversion_idをglobal shared critical section内で
    確定させ、以降そのread処理全体は確定済みversion_root配下だけを見る
    （leased_version_rootの契約）。read処理の途中でcurrent symlinkが
    別versionへ切り替わっても、既に開始しているreadはversion Aの内容の
    ままであることを検証する（version Bの内容が混入しない）。"""
    data_runtime_root = env["data_runtime_root"]
    version_b_root = data_runtime_root / "versions" / "20260101T000000Z-bbbbbbbb"
    version_b_root.mkdir()
    os.chmod(version_b_root, 0o750)

    current_a_file = env["version_root"] / "backend" / "hazard" / "flood" / "tokyo" / "a.geojson"
    _write_geojson(current_a_file, "VERSION-A")
    _write_geojson(version_b_root / "backend" / "hazard" / "flood" / "tokyo" / "b.geojson", "VERSION-B")

    service = HazardDatasetService()
    orig_load_json = service._load_json

    def _switch_current_then_load(path):
        # version_root解決（acquire_current完了）後、実際のfile読み込み
        # 直前でcurrent symlinkを差し替える（read中の切替を模擬）。
        current_link = data_runtime_root / "current"
        current_link.unlink()
        current_link.symlink_to("versions/20260101T000000Z-bbbbbbbb")
        return orig_load_json(path)

    monkeypatch.setattr(service, "_load_json", _switch_current_then_load)

    result = service.get_active_hazard_geojson("flood", "tokyo")

    # 既にacquireで確定していたversion Aの内容のまま返る（Bの内容は混入しない）。
    assert result["marker"] == "VERSION-A"


def test_hazard_type_contracts_do_not_drift(monkeypatch):
    """ATOMIC-PUBLISH-WIRED-TYPE-CONTRACT-DRIFT対策。
    HazardDatasetServiceが供給しうるtype集合は、runtime_dataset_validate
    が受理するwired type集合の部分集合でなければならない
    （HazardDatasetServiceが読めるのにpublish側が拒否する組み合わせ、
    または逆に、validatorだけが知っていてconsumerが知らないtypeが
    サイレントに生まれないことを保証する）。"""
    from app.services import runtime_dataset_validate as rdv

    assert HazardDatasetService.HAZARD_LAYER_TYPES <= rdv._WIRED_HAZARD_TYPES

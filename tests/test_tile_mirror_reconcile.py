"""
TILE-AWARE-ROLLBACK: rollback 先 version の manifest を正として Martin 用 mirror（data_runtime/frontend/tiles）を
合わせる（scripts/publish/reconcile_tile_mirror.py・rollback_runtime.sh）。

activate_version.py --rollback は current symlink だけを戻し、mirror は publish 時の追加専用同期でしか
更新されなかった（退役 tile が戻らない／差し替え前の tile に戻らない）。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reconcile_tile_mirror", ROOT / "scripts/publish/reconcile_tile_mirror.py")
rtm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rtm)

A16 = "frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-16_14.mbtiles"
A20 = "frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-20_14.mbtiles"
URBAN = "frontend/tiles/tokyo/inland_flood/tokyo_urban_001.mbtiles"
SURGE = "frontend/tiles/kanagawa/storm_surge/kanagawa_surge_001.mbtiles"
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="renameat2 / identity 検証は Linux 専用")
GID = os.getegid()


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _version(root: Path, vid: str, files: dict) -> Path:
    v = root / "versions" / vid
    for rel, data in files.items():
        (v / rel).parent.mkdir(parents=True, exist_ok=True)
        (v / rel).write_bytes(data)
    (v / "backend").mkdir(parents=True, exist_ok=True)
    (v / "_manifest.json").write_text(json.dumps({"files": {r: _sha(d) for r, d in files.items()}}))
    return v


def _mirror(root: Path, files: dict, mode: int = 0o640):
    """publish の mirror 同期後と同じ状態（file 0640）。"""
    for rel, data in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(data)
        os.chmod(root / rel, mode)


def _state(root: Path) -> dict:
    base = root / "frontend" / "tiles"
    return {str(p.relative_to(root)): _sha(p.read_bytes()) for p in base.rglob("*") if p.is_file()} if base.is_dir() else {}


V_OLD = {A16: b"a16", A20: b"a20", URBAN: b"urban-z14", SURGE: b"surge-old"}   # 退役前・差し替え前
V_NEW = {A20: b"a20", URBAN: b"urban-z16", SURGE: b"surge-new"}                  # A16 退役・URBAN/SURGE 差し替え後


@pytest.fixture
def rt(tmp_path):
    root = tmp_path / "data_runtime"
    _version(root, "V_OLD", V_OLD)
    _version(root, "V_NEW", V_NEW)
    _mirror(root, V_NEW)
    return root


def _apply(root, vid, registry=None):
    v = root / "versions" / vid
    p = rtm.plan(root, v, registry)
    rtm.prepare(root, v, p, GID)
    rtm.commit(root, p, GID)
    return p


# ── 1〜4, 12, 13: ADD / REPLACE / REMOVE / KEEP ─────────────────────────────────

def test_rollback_restores_retired_and_old_tiles(rt):
    inode_a20 = os.stat(rt / A20).st_ino
    p = _apply(rt, "V_OLD")
    assert [a["rel"] for a in p["actions"]["ADD"]] == [A16]
    assert sorted(a["rel"] for a in p["actions"]["REPLACE"]) == sorted([URBAN, SURGE])
    assert _state(rt) == {r: _sha(d) for r, d in V_OLD.items()}          # mirror == rollback 先 manifest
    assert os.stat(rt / A20).st_ino == inode_a20                          # unrelated（同一 sha）は触らない
    assert rtm.verify(rt, rt / "versions/V_OLD", GID) == []


def test_forward_rollback_removes_retired_tile_again(rt):
    _apply(rt, "V_OLD")
    p = _apply(rt, "V_NEW")
    assert [a["rel"] for a in p["actions"]["REMOVE"]] == [A16] and p["actions"]["UNKNOWN"] == []
    assert _state(rt) == {r: _sha(d) for r, d in V_NEW.items()}
    assert rtm.verify(rt, rt / "versions/V_NEW", GID) == []


def test_versions_are_never_modified(rt):
    before = {str(p): _sha(p.read_bytes()) for p in (rt / "versions").rglob("*") if p.is_file()}
    _apply(rt, "V_OLD")
    _apply(rt, "V_NEW")
    assert {str(p): _sha(p.read_bytes()) for p in (rt / "versions").rglob("*") if p.is_file()} == before


# ── 5〜7: 削除・入力の安全策 ─────────────────────────────────────────────────────

def test_unknown_mirror_file_is_never_deleted(rt):
    _mirror(rt, {"frontend/tiles/tokyo/flood/hand_placed.mbtiles": b"???"})
    p = _apply(rt, "V_OLD")
    assert [u["rel"] for u in p["actions"]["UNKNOWN"]] == ["frontend/tiles/tokyo/flood/hand_placed.mbtiles"]
    assert (rt / "frontend/tiles/tokyo/flood/hand_placed.mbtiles").read_bytes() == b"???"
    assert "extra: frontend/tiles/tokyo/flood/hand_placed.mbtiles" in rtm.verify(rt, rt / "versions/V_OLD", GID)


def test_mirror_only_file_with_unknown_sha_is_not_deleted(rt):
    (rt / SURGE).write_bytes(b"tampered")  # どの version にも無い sha
    _version(rt, "V_NOSURGE", {A20: b"a20", URBAN: b"urban-z16"})
    p = rtm.plan(rt, rt / "versions/V_NOSURGE", None)
    assert [u["rel"] for u in p["actions"]["UNKNOWN"]] == [SURGE] and p["actions"]["REMOVE"] == []


def test_retirement_backup_sha_makes_file_removable(rt, tmp_path):
    reg = tmp_path / "d.json"
    reg.write_text(json.dumps([{"rel_path": "frontend/tiles/tokyo/flood/old.mbtiles", "disposition": "RETIRED",
                                "backup": {"sha256": _sha(b"old-flood")}}]))
    _mirror(rt, {"frontend/tiles/tokyo/flood/old.mbtiles": b"old-flood"})
    p = rtm.plan(rt, rt / "versions/V_NEW", reg)
    assert [a["rel"] for a in p["actions"]["REMOVE"]] == ["frontend/tiles/tokyo/flood/old.mbtiles"]


@pytest.mark.parametrize("bad", ["frontend/tiles/../../etc/x.mbtiles", "frontend/tiles/tokyo//x.mbtiles", "frontend/tiles/*.mbtiles"])
def test_path_traversal_in_manifest_is_rejected(tmp_path, bad):
    root = tmp_path / "rt"
    v = root / "versions" / "V"
    v.mkdir(parents=True)
    (v / "_manifest.json").write_text(json.dumps({"files": {bad: "0" * 64}}))
    with pytest.raises(ValueError):
        rtm.plan(root, v, None)


def test_symlink_in_mirror_is_rejected(rt, tmp_path):
    (tmp_path / "outside.mbtiles").write_bytes(b"x")
    os.symlink(tmp_path / "outside.mbtiles", rt / "frontend/tiles/tokyo/tsunami/link.mbtiles")
    with pytest.raises(ValueError, match="通常 file 以外"):
        rtm.plan(rt, rt / "versions/V_OLD", None)


def test_version_file_not_matching_manifest_aborts_before_any_change(rt):
    (rt / "versions/V_OLD" / A16).write_bytes(b"corrupted")  # manifest と不一致
    before = _state(rt)
    p = rtm.plan(rt, rt / "versions/V_OLD", None)
    with pytest.raises(RuntimeError, match="sha256"):
        rtm.prepare(rt, rt / "versions/V_OLD", p, GID)
    assert _state(rt) == before  # 一時 file も残らない


# ── 8〜9: permission・中断 ────────────────────────────────────────────────────────

def test_restored_tiles_are_normalized_to_runtime_permissions(rt):
    os.chmod(rt / SURGE, 0o644)
    os.chmod(rt / A20, 0o644)  # sha 一致（KEEP）でも legacy の mode は正規化する
    _apply(rt, "V_OLD")
    for rel in (A16, A20, URBAN, SURGE):
        st = os.stat(rt / rel)
        assert oct(st.st_mode & 0o777) == oct(0o640) and st.st_gid == GID


def test_interrupted_after_prepare_leaves_mirror_unchanged_and_commit_converges(rt):
    before = _state(rt)
    v = rt / "versions/V_OLD"
    p = rtm.plan(rt, v, None)
    rtm.prepare(rt, v, p, GID)
    assert {k: s for k, s in _state(rt).items() if not Path(k).name.startswith(".")} == before  # 公開名は未変更
    assert rtm.plan(rt, v, None)["summary"] == p["summary"]                                   # 一時 file は計画に影響しない
    rtm.cleanup(rt)                                                                            # current 切替失敗時の後始末
    assert _state(rt) == before
    rtm.prepare(rt, v, p, GID)
    rtm.commit(rt, p, GID)
    rtm.commit(rt, rtm.plan(rt, v, None), GID)  # 再実行しても安全（冪等）
    assert rtm.verify(rt, v, GID) == []


def test_cli_plan_exit_codes(rt):
    run = lambda *a: subprocess.run([sys.executable, str(ROOT / "scripts/publish/reconcile_tile_mirror.py"),
                                     "--data-runtime-root", str(rt), "--registry", str(rt / "none.json"), "--gid", str(GID), *a],
                                    capture_output=True, text=True)
    out = run("--version", "V_OLD", "--plan")
    assert out.returncode == 0 and json.loads(out.stdout)["summary"]["ADD"] == 1
    assert run("--version", "V_NEW", "--verify").returncode == 0
    assert run("--version", "V_OLD", "--verify").returncode == 1


def test_rollback_wrapper_order_and_guidance():
    w = (ROOT / "scripts/publish/rollback_runtime.sh").read_text(encoding="utf-8")
    order = [w.index("--plan)"), w.index('"${RECONCILE[@]}" --prepare'), w.index("activate_version.py\" --data-runtime-root"),
             w.index('"${RECONCILE[@]}" --commit'), w.index("reconcile_dataset_state.py"), w.index('"${RECONCILE[@]}" --verify')]
    assert order == sorted(order) and "umask 0007" in w
    for p in ("backend/app/api/admin_datasets.py", "backend/app/services/pipeline_service.py"):
        assert "rollback_runtime.sh <version-id>" in (ROOT / p).read_text(encoding="utf-8")


# ── Linux: rollback_runtime.sh 全体（実 activate_version.py の identity 検証つき）──────

def _sqlite(data: str) -> bytes:
    p = Path(os.environ.get("TMPDIR", "/tmp")) / f"t-{os.getpid()}-{abs(hash(data))}.mbtiles"
    p.unlink(missing_ok=True)
    c = sqlite3.connect(p); c.execute("create table metadata(name text, value text)"); c.execute("insert into metadata values ('m', ?)", (data,)); c.commit(); c.close()
    b = p.read_bytes(); p.unlink()
    return b


@linux_only
@pytest.mark.skipif(os.geteuid() != 10002, reason="operator identity（10002 / supplemental 20001）で実行する")
def test_rollback_runtime_round_trip(tmp_path):
    sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(ROOT / "tests"))
    from app.services.runtime_publish import AtomicPublisher
    from test_atomic_publish_validation_reuse import _build, _normalize, _validator
    root = tmp_path / "data_runtime"
    (root / ".staging").mkdir(parents=True); (root / "versions").mkdir()
    (root / ".publish.lock").touch(mode=0o600)
    pub = AtomicPublisher(root, expect_uid=10002, expect_gid=10002, capacity_min_free_bytes=None, min_free_inodes=None)
    tiles = {"old": {A16: _sqlite("a16"), A20: _sqlite("a20"), URBAN: _sqlite("urban14")},
             "new": {A20: _sqlite("a20"), URBAN: _sqlite("urban16")}}
    vids = {}
    for name, vid in (("old", "20261011T050000Z-0000b001"), ("new", "20261011T050100Z-0000b002")):
        s = root / ".staging" / vid; s.mkdir(mode=0o750); _build(s)
        for rel, data in tiles[name].items():
            (s / rel).parent.mkdir(parents=True, exist_ok=True); (s / rel).write_bytes(data)
        _normalize(s); pub.publish(vid, _validator(True)); vids[name] = vid
    _mirror(root, tiles["new"])
    env = {**os.environ, "OHG2_DATA_RUNTIME_ROOT": str(root), "OHG2_ADMIN_DIR": str(tmp_path / "admin"), "OHG2_LEASES_GID": "20001"}
    # この fixture は mirror 整合の往復だけを見るため、本番 registry の required tile（RIVER・PSEUDO 等）を持たない。
    # REQUIRED-TILE-ROLLBACK-GUARD が拒否するので override を明示する（拒否そのものは test_rollback_preflight.py）。
    run = lambda vid: subprocess.run(["bash", str(ROOT / "scripts/publish/rollback_runtime.sh"), vid, "--allow-missing-required-tiles"],
                                     capture_output=True, text=True, env=env)
    out = run(vids["old"])
    assert out.returncode == 0, out.stdout + out.stderr
    assert os.readlink(root / "current") == f"versions/{vids['old']}"
    assert _state(root) == rtm.version_tiles(root / "versions" / vids["old"])  # manifest の tile 一覧と sha に完全一致
    assert A16 in _state(root)
    out = run(vids["new"])
    assert out.returncode == 0, out.stdout + out.stderr
    assert _state(root) == rtm.version_tiles(root / "versions" / vids["new"]) and A16 not in _state(root)


@linux_only
@pytest.mark.skipif(os.geteuid() != 10002, reason="operator identity で実行する")
def test_rollback_to_missing_version_changes_nothing(tmp_path):
    root = tmp_path / "data_runtime"
    _version(root, "V_NEW", V_NEW); _mirror(root, V_NEW)
    os.symlink("versions/V_NEW", root / "current")
    before = _state(root)
    out = subprocess.run(["bash", str(ROOT / "scripts/publish/rollback_runtime.sh"), "20261011T000000Z-deadbeef"],
                         capture_output=True, text=True, env={**os.environ, "OHG2_DATA_RUNTIME_ROOT": str(root)})
    assert out.returncode == 1 and os.readlink(root / "current") == "versions/V_NEW" and _state(root) == before

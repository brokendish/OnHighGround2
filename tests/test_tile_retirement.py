"""
TILE-RETIREMENT: tile_dispositions.json の disposition=RETIRED（rel_path 明示）だけを publish の staging と
Martin 用 mirror から取り除く。前 version は不変、unrelated tile は残す、wildcard で消さない。

2026-10-11: kanagawa_tsunami_A40-16_14（A40 2016 年版、A40-20_14 の実質重複・frontend 参照なし）を退役。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.services import data_ops_service as dos  # noqa: E402

spec = importlib.util.spec_from_file_location("apply_tile_retirements", ROOT / "scripts/publish/apply_tile_retirements.py")
ret = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ret)

A16 = "frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-16_14.mbtiles"
A20 = "frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-20_14.mbtiles"
TOKYO = "frontend/tiles/tokyo/tsunami/tokyo_tsunami_A40-23_13.mbtiles"
CHIBA = "frontend/tiles/tokyo/tsunami/chiba_tsunami_A40-18_12.mbtiles"
linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="renameat2 は Linux 専用")


def _record(sha, rel=A16, **kw):
    r = {"rel_path": rel, "tileset_id": Path(rel).stem, "disposition": "RETIRED", "reason": "dup",
         "replacement": "kanagawa_tsunami_A40-20_14", "retired_at": "2026-10-11", "consumer": "なし", "notes": ["x"],
         "backup": {"path": "data_lake/_backup/x.mbtiles", "sha256": sha}}
    r.update(kw)
    return r


def _write(p: Path, data: bytes) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def _tree(root, files):
    for rel, data in files.items():
        _write(root / rel, data)
    return root


# ── record 検証 ─────────────────────────────────────────────────────────────────

def test_production_registry_has_complete_retirement_record():
    items = ret.load_retirements(ROOT / "data_lake/registry/tile_dispositions.json")
    assert [i["rel_path"] for i in items] == [A16]
    i = items[0]
    assert i["replacement"] == "kanagawa_tsunami_A40-20_14" and i["retired_at"] == "2026-10-11"
    assert i["backup"]["sha256"] == "8e143ba482066d98371c569c202ed97e28e8dbb0d3faccb546836e160373f799"
    assert i["backup"]["path"].startswith("data_lake/_backup/retired-tiles-20261011/")


@pytest.mark.parametrize("bad", [
    {"replacement": ""}, {"backup": {"path": "x"}}, {"rel_path": "frontend/tiles/tokyo/tsunami/*.mbtiles"},
    {"rel_path": "frontend/tiles/../secret.mbtiles"}, {"rel_path": "backend/hazard/x.geojson"}, {"tileset_id": "other"},
])
def test_incomplete_or_unsafe_record_is_rejected(tmp_path, bad):
    p = tmp_path / "d.json"
    p.write_text(json.dumps([_record("0" * 64, **bad)]))
    with pytest.raises(ValueError):
        ret.load_retirements(p)


def test_non_retired_records_are_ignored(tmp_path):
    p = tmp_path / "d.json"
    p.write_text(json.dumps([{"rel_path": TOKYO, "disposition": "RETIRE_CANDIDATE"}, {"rel_path": CHIBA, "disposition": "KEEP_LEGACY"}]))
    assert ret.load_retirements(p) == []


# ── staging / mirror ───────────────────────────────────────────────────────────

def test_staging_removes_only_retired_rel_path(tmp_path):
    files = {A16: b"old", A20: b"new", TOKYO: b"t", CHIBA: b"c", "frontend/tiles/tokyo/tsunami/x.txt": b"z"}
    st = _tree(tmp_path / "stg", files)
    removed = ret.apply_staging(st, [_record("0" * 64)])
    assert removed == [A16] and not (st / A16).exists()
    for rel in (A20, TOKYO, CHIBA, "frontend/tiles/tokyo/tsunami/x.txt"):
        assert (st / rel).read_bytes() == files[rel]


def test_mirror_removes_only_when_absent_from_current_and_backup_sha_matches(tmp_path):
    sha = hashlib.sha256(b"old").hexdigest()
    rt = _tree(tmp_path / "rt", {A16: b"old", A20: b"new", TOKYO: b"t", CHIBA: b"c"})
    cur = _tree(tmp_path / "cur", {A20: b"new", TOKYO: b"t", CHIBA: b"c"})
    removed, kept = ret.apply_mirror(rt, cur, [_record(sha)])
    assert removed == [A16] and kept == [] and not (rt / A16).exists()
    assert all((rt / r).exists() for r in (A20, TOKYO, CHIBA))


def test_mirror_keeps_file_still_in_current(tmp_path):
    sha = hashlib.sha256(b"old").hexdigest()
    rt = _tree(tmp_path / "rt", {A16: b"old"})
    cur = _tree(tmp_path / "cur", {A16: b"old"})  # 例: 退役前 version へ rollback 中
    removed, kept = ret.apply_mirror(rt, cur, [_record(sha)])
    assert removed == [] and "current にまだ存在" in kept[0] and (rt / A16).exists()


def test_mirror_keeps_file_whose_sha_differs_from_backup(tmp_path):
    rt = _tree(tmp_path / "rt", {A16: b"unexpected"})
    removed, kept = ret.apply_mirror(rt, tmp_path / "cur", [_record(hashlib.sha256(b"old").hexdigest())])
    assert removed == [] and "backup と一致しない" in kept[0] and (rt / A16).exists()


def test_backup_restores_retired_tile(tmp_path):
    sha = _write(tmp_path / "backup.mbtiles", b"old")
    rt = tmp_path / "rt"
    shutil.copy2(tmp_path / "backup.mbtiles", rt / A16) if (rt / A16).parent.mkdir(parents=True, exist_ok=True) is None else None
    assert hashlib.sha256((rt / A16).read_bytes()).hexdigest() == sha


def test_wrapper_applies_retirement_before_activate_and_before_mirror_sync():
    w = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    i_stage = w.index('apply_tile_retirements.py" --staging "${STAGING_DIR}"')
    i_activate = w.index('python3 "${SCRIPT_DIR}/activate_version.py"')
    i_sync = w.index('bash "${SCRIPT_DIR}/sync_frontend_tiles_mirror.sh"')
    i_mirror = w.index('apply_tile_retirements.py" --mirror "${DATA_RUNTIME}" --current "${DATA_RUNTIME}/current"')
    # mirror の除去は同期より前（同じ id の旧 path と新 path が同時に見えると Martin が改名するため）
    assert i_stage < i_activate < i_mirror < i_sync
    block = w[i_stage - 120:i_stage + 300]
    assert "exit 1" in block  # staging 適用失敗は publish を止める


def test_cli_dry_record_check_and_missing_registry(tmp_path):
    out = subprocess.run([sys.executable, str(ROOT / "scripts/publish/apply_tile_retirements.py"), "--registry",
                          str(tmp_path / "none.json"), "--staging", str(tmp_path)], capture_output=True, text=True)
    assert out.returncode == 0 and "retired_records=0" in out.stdout
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([_record("0" * 64, replacement="")]))
    out = subprocess.run([sys.executable, str(ROOT / "scripts/publish/apply_tile_retirements.py"), "--registry",
                          str(bad), "--staging", str(tmp_path)], capture_output=True, text=True)
    assert out.returncode == 1 and "不完全" in out.stderr


# ── Data Ops ──────────────────────────────────────────────────────────────────

@pytest.fixture
def _cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "tc.json"))


def test_data_ops_retired_listing(tmp_path, _cache):
    from test_data_ops_tile_semantics import _runtime, _tile_bytes
    from app.services.dataset_definition_service import get_definition_service
    t = _tile_bytes(tmp_path)
    after = _runtime(tmp_path / "a", {A20: t, TOKYO: t}, {A20: t, TOKYO: t})
    r = {u["rel_path"]: u for u in dos.retired_tile_section(after, catalog=["kanagawa_tsunami_A40-20_14"])}
    assert r[A16]["status"] == dos.OK and r[A16]["label"] == "RETIRED" and r[A16]["replacement"] == "kanagawa_tsunami_A40-20_14"
    assert A16 not in {u["rel_path"] for u in dos.legacy_tile_section(after, get_definition_service().list_all())}
    before = _runtime(tmp_path / "b", {A16: t, A20: t}, {A16: t, A20: t})
    r = {u["rel_path"]: u for u in dos.retired_tile_section(before, catalog=["kanagawa_tsunami_A40-16_14"])}
    assert r[A16]["status"] == dos.WARNING and "残存" in r[A16]["label"]
    leg = {u["rel_path"]: u for u in dos.legacy_tile_section(before, get_definition_service().list_all())}
    assert leg[A16]["disposition"] == "RETIRED"
    d = get_definition_service().get("KANAGAWA-TSUNAMI-001")
    assert dos.tile_section(d, after, False, ["kanagawa_tsunami_A40-20_14"])["status"] == dos.OK


# ── publisher（Linux）: 新 version から除外・前 version 不変・rollback ─────────────

@linux_only
def test_publish_excludes_retired_tile_and_previous_version_is_intact(tmp_path):
    from test_atomic_publish_validation_reuse import _build, _normalize, _tree_state, _validator
    from app.services.runtime_publish import AtomicPublisher
    from app.services import runtime_dataset_validate as rdv
    root = tmp_path / "data_runtime"
    (root / ".staging").mkdir(parents=True)
    (root / "versions").mkdir()
    (root / ".publish.lock").touch(mode=0o600)
    pub = AtomicPublisher(root, expect_uid=os.geteuid(), expect_gid=os.getegid(), capacity_min_free_bytes=None, min_free_inodes=None)
    v1 = "20261011T000000Z-00000a01"
    s1 = root / ".staging" / v1
    s1.mkdir(mode=0o750)
    _build(s1)
    sha16 = _write(s1 / A16, b"sqlite-ish-old")  # .mbtiles は sqlite 検証されるので本物を作る
    import sqlite3
    for rel in (A16, A20):
        (s1 / rel).unlink(missing_ok=True)
        c = sqlite3.connect(s1 / rel); c.execute("create table metadata(name text, value text)"); c.execute("insert into metadata values ('n', ?)", (rel,)); c.commit(); c.close()
    sha16 = hashlib.sha256((s1 / A16).read_bytes()).hexdigest()
    _normalize(s1)
    pub.publish(v1, _validator(True))
    before = _tree_state(root / "versions" / v1)
    v2 = "20261011T000100Z-00000a02"
    s2 = root / ".staging" / v2
    s2.mkdir(mode=0o750)
    subprocess.run(["cp", "-a", "--reflink=auto", f"{root}/versions/{v1}/.", str(s2)], check=True)
    (s2 / rdv.MANIFEST_BASENAME).unlink()
    assert ret.apply_staging(s2, [_record(sha16)]) == [A16]
    _normalize(s2)
    pub.publish(v2, _validator(True))
    m2 = json.loads((root / "versions" / v2 / rdv.MANIFEST_BASENAME).read_text())["files"]
    assert A16 not in m2 and A20 in m2
    assert _tree_state(root / "versions" / v1) == before  # 前 version は不変（A16 を含む）
    # mirror: 新 current に無いので消える（unrelated は残る）
    _tree(root, {A16: (root / "versions" / v1 / A16).read_bytes(), A20: (root / "versions" / v1 / A20).read_bytes()})
    removed, _ = ret.apply_mirror(root, root / "current", [_record(sha16)])
    assert removed == [A16] and (root / A20).exists()
    # rollback: 前 version 自体は正常に選べる（mirror は rollback で同期されない＝退役 tile は配信されない）
    pub.rollback(v1)
    assert os.readlink(root / "current") == f"versions/{v1}" and (root / "current" / A16).exists()
    assert not (root / A16).exists()

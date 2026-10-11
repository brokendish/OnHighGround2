"""
TILE-PATH-MIGRATION: KANAGAWA-TSUNAMI-001 の tile（kanagawa_tsunami_A40-20_14）を tokyo/tsunami から
kanagawa/tsunami へ移す（2026-10-11）。tileset_id・frontend の静的 ID・tile の内容は変えない。

旧 path は tile_dispositions.json の disposition=MIGRATED（migrated_to = 新 path、sha256）として記録し、
  - publish: 移動先が staging にある場合だけ旧 path を除く（同じ tileset_id を 2 か所に置かない）
  - mirror: current に無く sha256 が一致する旧 path だけ除く
  - rollback: 移動前 version へ戻すと旧 path に復元・新 path を除去（reconcile_tile_mirror）
  - rollback guard / Data Ops: 旧 path にある tile を同じ tile として扱う
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
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.services import data_ops_service as dos  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/publish/{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ret = _load("apply_tile_retirements")
rtm = _load("reconcile_tile_mirror")
rpf = _load("rollback_preflight")

OLD = "frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-20_14.mbtiles"
NEW = "frontend/tiles/kanagawa/tsunami/kanagawa_tsunami_A40-20_14.mbtiles"
A16 = "frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-16_14.mbtiles"
TOKYO = "frontend/tiles/tokyo/tsunami/tokyo_tsunami_A40-23_13.mbtiles"
CHIBA = "frontend/tiles/tokyo/tsunami/chiba_tsunami_A40-18_12.mbtiles"
REG = ROOT / "data_lake/registry/tile_dispositions.json"


def _migration():
    return [d for d in json.loads(REG.read_text(encoding="utf-8")) if d.get("disposition") == "MIGRATED"]


def _write(root: Path, rel: str, data: bytes) -> str:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


# ── 契約 ─────────────────────────────────────────────────────────────────────

def test_registry_points_to_regional_path_with_same_tileset_id():
    d = get_definition_service().get("KANAGAWA-TSUNAMI-001")
    assert d.tile_rel_path == NEW and dos.tile_tileset_id(d) == "kanagawa_tsunami_A40-20_14"
    assert d.tile_requirement == "optional"
    assert dos.tile_rel_candidates(d) == [NEW, OLD]


def test_migration_record_is_complete_and_safe():
    [m] = _migration()
    assert (m["rel_path"], m["migrated_to"], m["tileset_id"]) == (OLD, NEW, "kanagawa_tsunami_A40-20_14")
    assert m["sha256"] == "8c0c2cf3e68306e76edc8575979a3838a7564989596fd2750a1c2e2cf2c06dbb" and m["migrated_at"] == "2026-10-11"
    assert ret.load_migrations(REG) == [m]


@pytest.mark.parametrize("bad", [{"migrated_to": OLD}, {"migrated_to": "frontend/tiles/kanagawa/tsunami/other.mbtiles"},
                                 {"sha256": ""}, {"migrated_to": "frontend/tiles/../x.mbtiles"}])
def test_invalid_migration_record_is_rejected(tmp_path, bad):
    [m] = _migration()
    p = tmp_path / "d.json"
    p.write_text(json.dumps([dict(m, **bad)]))
    with pytest.raises(ValueError):
        ret.load_migrations(p)


def test_frontend_static_ids_unchanged():
    js = (ROOT / "frontend/js/hazard-layers.js").read_text(encoding="utf-8")
    assert "{ tilesetId: 'kanagawa_tsunami_A40-20_14', sourceLayer: 'kanagawa_tsunami_A40-20_14', opacityFn: () => 0.18 }" in js
    assert "{ tilesetId: 'tokyo_tsunami_A40-23_13', sourceLayer: 'tokyo_tsunami_A40-23_13', opacityFn: () => 0.18 }" in js
    assert "{ tilesetId: 'chiba_tsunami_A40-18_12', sourceLayer: 'chiba_tsunami_A40-18_12', opacityFn: () => 0.18 }" in js
    assert "kanagawa_tsunami_A40-16_14" not in js


def test_martin_config_serves_regional_path_and_keeps_tokyo():
    cfg = (ROOT / "config/martin.yaml").read_text(encoding="utf-8")
    paths = [l.strip()[2:] for l in cfg.splitlines() if l.strip().startswith("- /tiles/")]
    assert "/tiles/kanagawa/tsunami" in paths and "/tiles/tokyo/tsunami" in paths


def test_a40_16_stays_retired():
    d = {x["rel_path"]: x for x in json.loads(REG.read_text(encoding="utf-8"))}
    assert d[A16]["disposition"] == "RETIRED"


# ── publish（staging）/ mirror ────────────────────────────────────────────────

def test_staging_removes_old_path_only_when_new_path_present(tmp_path):
    files = {OLD: b"a20", NEW: b"a20", TOKYO: b"t", CHIBA: b"c"}
    for rel, data in files.items():
        _write(tmp_path, rel, data)
    assert ret.apply_staging_migrations(tmp_path, _migration()) == [OLD]
    assert not (tmp_path / OLD).exists() and all((tmp_path / r).exists() for r in (NEW, TOKYO, CHIBA))


def test_staging_aborts_if_new_path_missing(tmp_path):
    _write(tmp_path, OLD, b"a20")
    with pytest.raises(ValueError, match="移動先"):
        ret.apply_staging_migrations(tmp_path, _migration())
    assert (tmp_path / OLD).exists()  # 旧 path を消して tile を失うことはない


def test_mirror_removes_old_path_only_when_absent_from_current_and_sha_matches(tmp_path):
    [m] = _migration()
    rt, cur = tmp_path / "rt", tmp_path / "cur"
    _write(cur, NEW, b"x")
    (rt / OLD).parent.mkdir(parents=True)
    (rt / OLD).write_bytes(b"different")
    removed, kept = ret.apply_mirror_migrations(rt, cur, [m])
    assert removed == [] and "一致しない" in kept[0]
    fake = dict(m, sha256=hashlib.sha256(b"different").hexdigest())
    assert ret.apply_mirror_migrations(rt, cur, [fake])[0] == [OLD]
    _write(rt, OLD, b"different")
    _write(cur, OLD, b"different")  # current に残っていれば消さない
    assert ret.apply_mirror_migrations(rt, cur, [fake])[0] == []


# ── meta API（_find_tileset_for_region）────────────────────────────────────────

def _mbtiles(path: Path, layer: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.execute("create table metadata(name text, value text)")
    c.execute("insert into metadata values ('json', ?)", (json.dumps({"vector_layers": [{"id": layer}]}),))
    c.commit()
    c.close()


def test_meta_resolves_kanagawa_from_regional_dir_and_tokyo_unchanged(tmp_path, monkeypatch):
    from app.api import hazards
    monkeypatch.setattr(hazards, "_TILE_ROOT", tmp_path)
    _mbtiles(tmp_path / "kanagawa/tsunami/kanagawa_tsunami_A40-20_14.mbtiles", "kanagawa_tsunami_A40-20_14")
    _mbtiles(tmp_path / "tokyo/tsunami/tokyo_tsunami_A40-23_13.mbtiles", "tokyo_tsunami_A40-23_13")
    _mbtiles(tmp_path / "tokyo/tsunami/chiba_tsunami_A40-18_12.mbtiles", "chiba_tsunami_A40-18_12")
    k = hazards._find_tileset_for_region("tsunami", "kanagawa", "KANAGAWA-TSUNAMI-001")
    t = hazards._find_tileset_for_region("tsunami", "tokyo", "TOKYO-TSUNAMI-001")
    assert k["tileset_id"] == "kanagawa_tsunami_A40-20_14" and t["tileset_id"] == "tokyo_tsunami_A40-23_13"
    assert hazards._find_tileset_for_region("tsunami", "chiba") is None  # chiba は tokyo dir 同居のまま（変更なし）


# ── Data Ops / rollback guard（移動前 version）────────────────────────────────────

@pytest.fixture
def _cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "tc.json"))


@pytest.mark.parametrize("rel", [NEW, OLD])
def test_data_ops_tile_ok_before_and_after_migration(tmp_path, _cache, rel):
    from test_data_ops_tile_semantics import _runtime, _tile_bytes
    t = _tile_bytes(tmp_path)
    view = _runtime(tmp_path, {rel: t}, {rel: t})
    s = dos.tile_section(get_definition_service().get("KANAGAWA-TSUNAMI-001"), view, False, ["kanagawa_tsunami_A40-20_14"])
    assert (s["status"], s["state"], s["rel_path"]) == (dos.OK, "TILE_OK", rel)
    assert rel not in {u["rel_path"] for u in dos.legacy_tile_section(view, get_definition_service().list_all())}


@pytest.mark.parametrize("rel", [NEW, OLD])
def test_rollback_guard_sees_tile_at_either_path(tmp_path, rel):
    v = tmp_path / "versions" / "V"
    sha = _write(v, rel, b"a20")
    (v / "_manifest.json").write_text(json.dumps({"files": {rel: sha}}))
    r = rpf.preflight(v, ROOT / "data_lake/registry/dataset_definitions.json")
    c = {x["dataset_id"]: x for x in r["checks"]}["KANAGAWA-TSUNAMI-001"]
    assert (c["state"], c["severity"], c["tile_rel_path"]) == ("present", "OK", rel)


def test_reconcile_moves_tile_between_paths(tmp_path):
    root = tmp_path / "rt"
    for vid, rel in (("V_OLD", OLD), ("V_NEW", NEW)):
        v = root / "versions" / vid
        files = {rel: b"a20", TOKYO: b"t", CHIBA: b"c"}
        for r, d in files.items():
            _write(v, r, d)
        (v / "_manifest.json").write_text(json.dumps({"files": {r: hashlib.sha256(d).hexdigest() for r, d in files.items()}}))
    for r, d in {NEW: b"a20", TOKYO: b"t", CHIBA: b"c"}.items():
        _write(root, r, d)
    gid = os.getegid()
    for vid, present, absent in (("V_OLD", OLD, NEW), ("V_NEW", NEW, OLD)):
        v = root / "versions" / vid
        p = rtm.plan(root, v, REG)
        rtm.prepare(root, v, p, gid)
        rtm.commit(root, p, gid)
        assert (root / present).exists() and not (root / absent).exists() and (root / TOKYO).exists() and (root / CHIBA).exists()
        assert rtm.verify(root, v, gid) == []


def test_moved_tileset_is_removed_before_added(tmp_path, monkeypatch):
    """Martin は同じ source id が 2 か所に見えると後着を `<id>.1` に改名するため、移動では旧 path を先に消す。"""
    root = tmp_path / "rt"
    v = root / "versions" / "V_OLD"
    files = {OLD: b"a20", TOKYO: b"t"}
    for r, d in files.items():
        _write(v, r, d)
    (v / "_manifest.json").write_text(json.dumps({"files": {r: hashlib.sha256(d).hexdigest() for r, d in files.items()}}))
    vn = root / "versions" / "V_NEW"  # 移動後 version（mirror の新 path の素性）
    _write(vn, NEW, b"a20")
    (vn / "_manifest.json").write_text(json.dumps({"files": {NEW: hashlib.sha256(b"a20").hexdigest()}}))
    for r, d in {NEW: b"a20", TOKYO: b"t", A16: b"a16"}.items():
        _write(root, r, d)
    events = []
    real_unlink, real_replace = Path.unlink, os.replace
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (events.append(("rm", self.name, str(self.parent).split("tiles/")[-1])), real_unlink(self, *a, **k))[1])
    monkeypatch.setattr(rtm.os, "replace", lambda src, dst: (events.append(("add", Path(dst).name, str(Path(dst).parent).split("tiles/")[-1])), real_replace(src, dst))[1])
    reg = tmp_path / "d.json"
    reg.write_text(json.dumps(_migration() + [{"rel_path": A16, "disposition": "RETIRED", "backup": {"sha256": hashlib.sha256(b"a16").hexdigest()}}]))
    p = rtm.plan(root, v, reg)
    rtm.prepare(root, v, p, os.getegid())
    events.clear()
    rtm.commit(root, p, os.getegid())
    a20 = [e for e in events if e[1] == "kanagawa_tsunami_A40-20_14.mbtiles"]
    assert a20 == [("rm", "kanagawa_tsunami_A40-20_14.mbtiles", "kanagawa/tsunami"), ("add", "kanagawa_tsunami_A40-20_14.mbtiles", "tokyo/tsunami")]
    assert ("rm", "kanagawa_tsunami_A40-16_14.mbtiles", "tokyo/tsunami") in events  # 移動でない削除も行う


# ── Linux: publish → rollback → forward（operator identity・実 activate_version）──────

@pytest.mark.skipif(not sys.platform.startswith("linux") or os.geteuid() != 10002, reason="operator identity で実行する")
def test_publish_rollback_forward_round_trip(tmp_path):
    from app.services.runtime_publish import AtomicPublisher
    from app.services import runtime_dataset_validate as rdv
    from test_atomic_publish_validation_reuse import _build, _normalize, _validator
    root = tmp_path / "data_runtime"
    (root / ".staging").mkdir(parents=True); (root / "versions").mkdir(); (root / ".publish.lock").touch(mode=0o600)
    pub = AtomicPublisher(root, expect_uid=10002, expect_gid=10002, capacity_min_free_bytes=None, min_free_inodes=None)
    required = [dos.tile_rel(d) for d in get_definition_service().list_all() if dos.tile_requirement(d) == "required"]
    tmp_tile = tmp_path / "a20.mbtiles"
    _mbtiles(tmp_tile, "kanagawa_tsunami_A40-20_14")
    a20 = tmp_tile.read_bytes()
    # 移動前 version（A40-20 は tokyo/tsunami）
    v1 = "20261011T070000Z-0000d001"
    s1 = root / ".staging" / v1; s1.mkdir(mode=0o750); _build(s1)
    for rel in required + [TOKYO, CHIBA]:
        if not (s1 / rel).exists():  # _build が作る tile（kanagawa_river_001）はそのまま使う
            _mbtiles(s1 / rel, Path(rel).stem)
    _write(s1, OLD, a20)
    _normalize(s1); pub.publish(v1, _validator(True))
    subprocess.run([sys.executable, str(ROOT / "scripts/publish/reconcile_tile_mirror.py"), "--data-runtime-root", str(root),
                    "--registry", str(REG), "--apply"], check=True, capture_output=True)
    # 移動後 version: current を種に staging → deploy が新 path に置く → 移動 record で旧 path を除く
    v2 = "20261011T070100Z-0000d002"
    s2 = root / ".staging" / v2; s2.mkdir(mode=0o750)
    subprocess.run(["cp", "-a", "--reflink=auto", f"{root}/versions/{v1}/.", str(s2)], check=True)
    (s2 / rdv.MANIFEST_BASENAME).unlink()
    _write(s2, NEW, a20)
    out = subprocess.run([sys.executable, str(ROOT / "scripts/publish/apply_tile_retirements.py"), "--registry", str(REG), "--staging", str(s2)],
                         capture_output=True, text=True)
    assert out.returncode == 0 and OLD in out.stdout, out.stdout + out.stderr
    _normalize(s2); pub.publish(v2, _validator(True))
    m2 = json.loads((root / "versions" / v2 / rdv.MANIFEST_BASENAME).read_text())["files"]
    assert NEW in m2 and OLD not in m2
    subprocess.run([sys.executable, str(ROOT / "scripts/publish/reconcile_tile_mirror.py"), "--data-runtime-root", str(root),
                    "--registry", str(REG), "--apply"], check=True, capture_output=True)
    assert (root / NEW).exists() and not (root / OLD).exists()
    env = {**os.environ, "OHG2_DATA_RUNTIME_ROOT": str(root), "OHG2_ADMIN_DIR": str(tmp_path / "admin")}
    for vid, present, absent in ((v1, OLD, NEW), (v2, NEW, OLD)):
        out = subprocess.run(["bash", str(ROOT / "scripts/publish/rollback_runtime.sh"), vid], capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stdout + out.stderr  # guard は旧 path の tile を認識する（override 不要）
        assert (root / present).exists() and not (root / absent).exists()
        assert hashlib.sha256((root / present).read_bytes()).hexdigest() == hashlib.sha256(a20).hexdigest()

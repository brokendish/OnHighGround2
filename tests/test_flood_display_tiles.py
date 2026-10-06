"""
洪水表示 tile（MBTiles）/ Martin 配置の回帰テスト。

背景（Local 実機）:
  - meta API の tileset 選択が「最大サイズ」のため、旧 pipeline の tokyo_flood_max.mbtiles
    （666,833 件・穴あき欠落）が現行 canonical の tokyo_river_001.mbtiles（947,590 件）より優先された
  - tile build が Martin 監視 directory 内に `<out>.tmp.mbtiles` を作り Martin が SQLITE_BUSY
  - mirror sync が最終名を直接書き換え、Martin がコピー途中を reload して malformed

  1. tile build は Martin 監視外（data_lake/tiles/.build）で生成する
  2. 完成・quick_check 後にだけ atomic に配置する
  3. 不完全 / malformed MBTiles を最終名で公開しない
  5. active dataset の tile（tokyo_river_001）を選ぶ・.tmp を候補にしない
  6. legacy tokyo_flood_max への表示参照が残っていない
  7. mirror sync は一時名 → rename（コピー途中に最終名を書き換えない）・同一内容は再配置しない
  8. file mode / group contract
  9. tile build 失敗時、既存の正常な MBTiles を保持
 10. 配置したときだけ Martin を再起動（同一内容なら再起動しない）
 11. frontend の layer URL / source-layer
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.api import hazards  # noqa: E402
from app.models.admin_dataset import DatasetDefinition, DatasetState, StorageStatus, TileBuildStatus  # noqa: E402
from app.services import mbtiles_install as mi  # noqa: E402
from app.services import pipeline_service as ps  # noqa: E402

GID = os.getgid()


def _make_mbtiles(path: Path, layer: str = "flood", tiles: int = 3) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metadata (name text, value text)")
    conn.execute("CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob)")
    conn.executemany("INSERT INTO metadata VALUES (?, ?)", [
        ("maxzoom", "16"), ("json", json.dumps({"vector_layers": [{"id": layer}]}))])
    conn.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", [(5, i, i, b"x" * 10) for i in range(tiles)])
    conn.commit()
    conn.close()
    return path


def _corrupt(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 50 + b"garbage" * 100)
    return path


# ── 1/2/3/9/10. tile build ──────────────────────────────────────────────────────

def _defn() -> DatasetDefinition:
    return DatasetDefinition(
        dataset_id="TOKYO-RIVER-001", region="tokyo", category="flood", display_name="t", description="t",
        hint_text="t", impact_scope="t", accepted_input_modes=[], accepted_extensions=[],
        max_browser_upload_mb=0, requires_normalize=False, requires_validation=False, requires_deploy=True,
        requires_osrm_rebuild=False, raw_storage_path="data_lake/raw/tokyo/flood",
        validated_storage_path="data_lake/validated/tokyo/flood",
        runtime_path="data_runtime/backend/hazard/flood", deploy_mode="copy_file", layer_type="flood",
        requires_tile_build=True,
    )


@pytest.fixture
def tb(tmp_path, monkeypatch):
    canonical = tmp_path / "data_lake/validated/tokyo/flood/tokyo-river-001.geojson"
    canonical.parent.mkdir(parents=True)
    canonical.write_text('{"type":"FeatureCollection","features":[]}')
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("OHG2_LEASES_GID", str(GID))
    mirror_dir = tmp_path / "data_runtime/frontend/tiles/tokyo/flood"
    return {"tmp": tmp_path, "canonical": canonical, "mirror_dir": mirror_dir,
            "mirror": mirror_dir / "tokyo_river_001.mbtiles",
            "lake": tmp_path / "data_lake/tiles/tokyo/flood/tokyo_river_001.mbtiles"}


def _run_tile_build(tb, fake_build, martin=None):
    state = DatasetState(dataset_id="TOKYO-RIVER-001", storage_status=StorageStatus.stored,
                         current_validated_path=str(tb["canonical"]))
    martin = martin or Mock(return_value=0)

    async def _docker(op, job, jm):
        return martin(op)

    jm = Mock()
    with patch.object(ps, "_run_subprocess", fake_build), patch.object(ps, "_run_docker_operation", _docker):
        asyncio.run(ps._do_tile_build(Mock(job_id="job-tile-1"), _defn(), state, jm, Mock()))
    return state, jm, martin


def _fake_build(tb, produce=_make_mbtiles, seen=None):
    async def _run(cmd, job, jm, timeout=None):
        out = Path(cmd[3])
        if seen is not None:
            seen.append(out)
        tmp = Path(str(out) + ".tmp.mbtiles")  # build_tiles_flood.sh と同じ一時名
        produce(tmp)
        os.replace(tmp, out)
        return 0
    return _run


def test_tile_build_outside_martin_dir_and_atomic_install(tb):
    seen = []
    state, jm, martin = _run_tile_build(tb, _fake_build(tb, seen=seen))
    out = seen[0]
    assert tb["tmp"] / "data_lake/tiles/.build" in out.parents          # Martin 監視外で生成
    assert tb["tmp"] / "data_runtime" not in out.parents
    assert not (tb["tmp"] / "data_lake/tiles/.build/job-tile-1").exists()  # work dir は片付け
    assert tb["lake"].is_file() and tb["mirror"].is_file()
    assert sorted(p.name for p in tb["mirror_dir"].iterdir()) == ["tokyo_river_001.mbtiles"]  # .tmp/.partial なし
    assert state.tile_build_status == TileBuildStatus.success
    assert state.current_tile_path == str(tb["mirror"])
    st = tb["mirror"].stat()
    assert stat.S_IMODE(st.st_mode) == 0o640 and st.st_gid == GID     # 8. contract
    martin.assert_called_once_with("restart:martin")                   # 10. 配置したので再起動


def test_corrupt_build_output_is_not_published_and_existing_kept(tb):
    _make_mbtiles(tb["lake"], tiles=7)
    os.utime(tb["lake"], (0, 0))  # canonical より古い → 再ビルド対象
    mi.install_mbtiles(tb["lake"], tb["mirror"], GID)
    before = (tb["lake"].read_bytes(), tb["mirror"].read_bytes())

    state, jm, martin = _run_tile_build(tb, _fake_build(tb, produce=_corrupt))
    assert state.tile_build_status == TileBuildStatus.failed
    assert (tb["lake"].read_bytes(), tb["mirror"].read_bytes()) == before   # 9. 既存を保持
    assert sorted(p.name for p in tb["mirror_dir"].iterdir()) == ["tokyo_river_001.mbtiles"]
    martin.assert_not_called()


def test_build_failure_keeps_existing(tb):
    _make_mbtiles(tb["lake"], tiles=7)
    os.utime(tb["lake"], (0, 0))
    mi.install_mbtiles(tb["lake"], tb["mirror"], GID)
    before = tb["mirror"].read_bytes()

    async def _fail(cmd, job, jm, timeout=None):
        Path(str(cmd[3]) + ".tmp.mbtiles").write_bytes(b"partial")
        return 10

    state, _jm, martin = _run_tile_build(tb, _fail)
    assert state.tile_build_status == TileBuildStatus.failed
    assert tb["mirror"].read_bytes() == before
    assert not (tb["tmp"] / "data_lake/tiles/.build/job-tile-1").exists()
    martin.assert_not_called()


def test_up_to_date_tile_is_not_rebuilt_and_martin_not_restarted(tb):
    _make_mbtiles(tb["lake"])
    mi.install_mbtiles(tb["lake"], tb["mirror"], GID)

    async def _must_not_build(*_a, **_k):
        raise AssertionError("最新の tile を再ビルドしてはいけない")

    state, _jm, martin = _run_tile_build(tb, _must_not_build)
    assert state.tile_build_status == TileBuildStatus.success
    martin.assert_not_called()


def test_up_to_date_but_malformed_lake_tile_is_rebuilt(tb):
    _corrupt(tb["lake"])
    seen = []
    state, _jm, _m = _run_tile_build(tb, _fake_build(tb, seen=seen))
    assert seen, "malformed な既存 tile は再ビルドされる"
    mi.quick_check(tb["lake"])
    assert state.tile_build_status == TileBuildStatus.success


# ── 2/3/4/8. install_mbtiles ────────────────────────────────────────────────────

def test_install_rejects_malformed_source(tmp_path):
    dest = _make_mbtiles(tmp_path / "m/a.mbtiles")
    before = dest.read_bytes()
    with pytest.raises(mi.MbtilesInstallError):
        mi.install_mbtiles(_corrupt(tmp_path / "bad.mbtiles"), dest, GID)
    assert dest.read_bytes() == before
    assert [p.name for p in dest.parent.iterdir()] == ["a.mbtiles"]


def test_install_never_exposes_partial_under_final_name(tmp_path, monkeypatch):
    src = _make_mbtiles(tmp_path / "src.mbtiles", tiles=5)
    dest = tmp_path / "mirror/tokyo/flood/a.mbtiles"
    observed = []
    real_replace = os.replace

    def _spy_replace(a, b):
        observed.append((Path(a).name, sorted(p.name for p in Path(b).parent.iterdir())))
        return real_replace(a, b)

    monkeypatch.setattr(mi.os, "replace", _spy_replace)
    assert mi.install_mbtiles(src, dest, GID) is True
    tmp_name, listing = observed[0]
    assert not tmp_name.endswith(".mbtiles") and tmp_name.startswith(".")   # Martin が拾わない名前
    assert "a.mbtiles" not in listing                                       # rename 前に最終名は存在しない
    assert dest.read_bytes() == src.read_bytes()
    for d in (dest.parent, dest.parent.parent):                             # 新規 dir も contract
        assert stat.S_IMODE(d.stat().st_mode) == 0o750


def test_install_same_content_fixes_group_mode_without_rewrite(tmp_path):
    src = _make_mbtiles(tmp_path / "src.mbtiles")
    dest = tmp_path / "m/a.mbtiles"
    dest.parent.mkdir()
    dest.write_bytes(src.read_bytes())
    dest.chmod(0o600)
    ino = dest.stat().st_ino
    assert mi.install_mbtiles(src, dest, GID) is False
    assert dest.stat().st_ino == ino                     # 再コピーしない（Martin reload を起こさない）
    assert stat.S_IMODE(dest.stat().st_mode) == 0o640


# ── 5. meta の tileset 選択 ─────────────────────────────────────────────────────

@pytest.fixture
def tile_root(tmp_path, monkeypatch):
    monkeypatch.setattr(hazards, "_TILE_ROOT", tmp_path)
    return tmp_path


def test_active_dataset_tile_preferred_over_larger_legacy(tile_root):
    d = tile_root / "tokyo/flood"
    _make_mbtiles(d / "tokyo_flood_max.mbtiles", layer="tokyo_flood_max", tiles=500)  # legacy（大きい）
    _make_mbtiles(d / "tokyo_river_001.mbtiles", layer="flood", tiles=3)
    assert (d / "tokyo_flood_max.mbtiles").stat().st_size > (d / "tokyo_river_001.mbtiles").stat().st_size
    assert hazards._find_tileset_for_region("flood", "tokyo", "TOKYO-RIVER-001") == \
        {"tileset_id": "tokyo_river_001", "source_layer": "flood"}
    # dataset_id 無し（従来呼び出し）は従来どおり最大サイズ
    assert hazards._find_tileset_for_region("flood", "tokyo")["tileset_id"] == "tokyo_flood_max"


def test_tmp_and_hidden_mbtiles_are_never_selected(tile_root):
    d = tile_root / "tokyo/flood"
    _make_mbtiles(d / "tokyo_river_001.mbtiles.tmp.mbtiles", tiles=500)
    _make_mbtiles(d / ".tokyo_river_001.mbtiles.partial-1", tiles=500)
    _make_mbtiles(d / "tokyo_flood_max.mbtiles", layer="tokyo_flood_max", tiles=3)
    assert hazards._find_tileset_for_region("flood", "tokyo", "TOKYO-RIVER-001")["tileset_id"] == "tokyo_flood_max"


def test_missing_active_tile_falls_back_to_existing(tile_root):
    _make_mbtiles(tile_root / "tokyo/storm_surge/tokyo_storm_surge.mbtiles", layer="tokyo_storm_surge")
    assert hazards._find_tileset_for_region("storm_surge", "tokyo", "TOKYO-SURGE-001")["tileset_id"] == \
        "tokyo_storm_surge"


def test_meta_passes_dataset_id_to_tileset_selection():
    src = (ROOT / "backend/app/api/hazards.py").read_text(encoding="utf-8")
    assert '_find_tileset_for_region(hazard_type, region_code, meta.get("dataset_id"))' in src


# ── 6/11. legacy 参照 / frontend ────────────────────────────────────────────────

def test_admin_hazard_registry_points_to_canonical_tile():
    from app.services.admin_hazard_service import _LAYER_DEFINITIONS
    d = _LAYER_DEFINITIONS["flood_tokyo_max"]
    assert d["tileset_id"] == "tokyo_river_001"
    assert d["source_path"] == "data_lake/validated/tokyo/flood/tokyo-river-001.geojson"
    assert d["runtime_tiles_path"].endswith("tokyo/flood/tokyo_river_001.mbtiles")


def test_frontend_flood_tokyo_vector_source_and_meta():
    src = (ROOT / "frontend/js/hazard-layers.js").read_text(encoding="utf-8")
    block = src[src.index("    flood_tokyo_max: ["): src.index("    flood_kanagawa_max: [")]
    assert "tilesetId: 'tokyo_river_001'" in block
    assert "sourceLayer: 'flood'" in block
    assert "tokyo_flood_max" not in block
    assert "metaUrl: '/api/hazards/flood/tokyo/meta'" in src


# ── 7/8. mirror sync（scripts/publish/sync_frontend_tiles_mirror.sh） ───────────

def _run_sync(src: Path, dst: Path, spy_dir: Path | None = None, log: Path | None = None):
    env = {**os.environ, "OHG2_LEASES_GID": str(GID)}
    if spy_dir is not None:
        # cp をラップし、コピー中の配置先 directory の状態を記録する
        spy_dir.mkdir()
        (spy_dir / "cp").write_text(
            "#!/bin/bash\n/bin/cp \"$@\"\n"
            f"for a in \"$@\"; do :; done; d=$(dirname \"$a\"); ls -A \"$d\" >> {log}; "
            f"echo ---- >> {log}\n")
        (spy_dir / "cp").chmod(0o755)
        env["PATH"] = f"{spy_dir}:{env['PATH']}"
    return subprocess.run(["bash", str(ROOT / "scripts/publish/sync_frontend_tiles_mirror.sh"), str(src), str(dst)],
                          capture_output=True, text=True, env=env)


def test_mirror_sync_atomic_rename_and_skip_identical(tmp_path):
    src, dst = tmp_path / "current", tmp_path / "mirror"
    same = _make_mbtiles(src / "tokyo/flood/a.mbtiles")
    changed = _make_mbtiles(src / "tokyo/flood/b.mbtiles", tiles=9)
    (dst / "tokyo/flood").mkdir(parents=True)
    (dst / "tokyo/flood/a.mbtiles").write_bytes(same.read_bytes())
    _make_mbtiles(dst / "tokyo/flood/b.mbtiles", tiles=2)
    old_b = (dst / "tokyo/flood/b.mbtiles").read_bytes()
    ino_a = (dst / "tokyo/flood/a.mbtiles").stat().st_ino
    log = tmp_path / "cp.log"

    r = _run_sync(src, dst, spy_dir=tmp_path / "spy", log=log)
    assert r.returncode == 0, r.stderr
    assert (dst / "tokyo/flood/b.mbtiles").read_bytes() == changed.read_bytes()
    assert (dst / "tokyo/flood/a.mbtiles").stat().st_ino == ino_a           # 同一内容は再配置しない
    assert sorted(p.name for p in (dst / "tokyo/flood").iterdir()) == ["a.mbtiles", "b.mbtiles"]
    # コピー直後（rename 前）の状態: 最終名 b.mbtiles は旧内容のまま、一時名は .mbtiles で終わらない
    snapshot = log.read_text().split("----")[0].split()
    temps = [n for n in snapshot if n.startswith(".b.mbtiles.syncing-")]
    assert temps and not any(t.endswith(".mbtiles") for t in temps)
    assert old_b != changed.read_bytes()
    for f in (dst / "tokyo/flood").iterdir():
        st = f.stat()
        assert stat.S_IMODE(st.st_mode) == 0o640 and st.st_gid == GID


def test_mirror_sync_does_not_use_in_place_copy():
    src = (ROOT / "scripts/publish/sync_frontend_tiles_mirror.sh").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "--remove-destination" not in code
    assert "rsync -a" not in code
    assert 'mv -f -- "${tmp}" "${target}"' in code
    assert 'cmp -s -- "${f}" "${target}"' in code


# ── 4. staging の malformed MBTiles は publish 検証で拒否される（既存契約の確認） ──

def test_staging_rejects_malformed_mbtiles(tmp_path):
    from app.services import runtime_dataset_validate as rdv
    from app.services.runtime_atomic import RuntimeAtomicError
    staging = tmp_path / "staging"
    (staging / "backend").mkdir(parents=True)
    _corrupt(staging / "frontend/tiles/tokyo/flood/tokyo_river_001.mbtiles")
    with patch.object(rdv, "_resolve_configured_tsunami_targets", return_value=(frozenset(), None)):
        with pytest.raises(RuntimeAtomicError):
            rdv.validate_and_manifest_staging(staging, None)

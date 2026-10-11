"""
publish（deploy_to_runtime.sh）の frontend tile directory 名の契約。

tile は data_lake/tiles/<region>/<layer_type>/<dataset>.mbtiles に build され（pipeline_service._do_tile_build）、
Martin config・Data Ops・meta API も <layer_type> の directory を読む。URBAN dataset は category=urban_flood /
layer_type=inland_flood で、publish だけが旧名 urban_flood を探していたため正式 tile が current に入らなかった
（2026-10-11）。旧名 directory は publish せず警告だけ出す（Martin が scan しない path のため）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/publish/deploy_to_runtime.sh"


def _tile_block() -> str:
    s = SCRIPT.read_text(encoding="utf-8")
    start = s.index('    log_info "--- frontend tiles ---"')
    end = s.index("    # ── frontend/layers へ同期")
    return s[start:end]


def _run_block(tmp_path: Path, dirs: dict) -> subprocess.CompletedProcess:
    """tile 配置ブロックだけを実行し、deploy_dir の呼び出しを記録する（実 publish はしない）。"""
    tiles = tmp_path / "tiles"
    for d, files in dirs.items():
        (tiles / d).mkdir(parents=True, exist_ok=True)
        for f in files:
            (tiles / d / f).write_bytes(b"x")
    script = (
        'log_info(){ :; }; log_warn(){ echo "WARN $*"; }\n'
        'deploy_dir(){ echo "DEPLOY $1 -> $2 [$3]"; }\n'
        f'TILES="{tiles}"; RUNTIME_FRONTEND_TILES="{tmp_path}/rt"; SKIPPED_FILES=()\n'
        + _tile_block()
    )
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True, env={"PATH": os.environ["PATH"]})


def test_inland_flood_tiles_are_published_from_canonical_path(tmp_path):
    out = _run_block(tmp_path, {"inland_flood": ["tokyo_urban_001.mbtiles"]})
    assert out.returncode == 0, out.stderr
    assert f"DEPLOY {tmp_path}/tiles/inland_flood -> {tmp_path}/rt/inland_flood [*.mbtiles]" in out.stdout
    assert "urban_flood" not in out.stdout.replace("WARN", "")


def test_legacy_urban_flood_dir_is_not_published_but_warned(tmp_path):
    out = _run_block(tmp_path, {"urban_flood": ["tokyo_urban_001.mbtiles"]})
    assert out.returncode == 0, out.stderr
    assert "DEPLOY" not in [l.split()[0] for l in out.stdout.splitlines() if "urban_flood" in l]
    assert "legacy tile dir（publish しない）" in out.stdout and "inland_flood" in out.stdout


def test_empty_legacy_dir_is_silent(tmp_path):
    out = _run_block(tmp_path, {"urban_flood": []})
    assert "legacy tile dir" not in out.stdout


def test_tile_dirs_match_dataset_layer_types():
    """tile 契約を持つ dataset の layer_type はすべて publish の tile loop が扱う（逆に旧名は扱わない）。"""
    m = re.search(r"for hazard_type in ([a-z_ ]+); do", _tile_block())
    loop = set(m.group(1).split())
    defs = json.loads((ROOT / "data_lake/registry/dataset_definitions.json").read_text(encoding="utf-8"))
    tiled = {d["layer_type"] for d in defs if d.get("tile_requirement") in ("required", "optional")}
    assert tiled <= loop, tiled - loop
    assert "urban_flood" not in loop and "inland_flood" in loop


def test_tile_build_writes_to_layer_type_dir():
    src = (ROOT / "backend/app/services/pipeline_service.py").read_text(encoding="utf-8")
    assert 'lake_tile = tiles_root / defn.region / defn.layer_type / f"{tile_stem}.mbtiles"' in src


@pytest.mark.parametrize("cfg,needle", [("config/martin.yaml", "/tiles/{r}/inland_flood"),
                                        ("config/martin-local.yaml", "/data_runtime/frontend/tiles/{r}/inland_flood")])
def test_martin_scans_inland_flood_dir(cfg, needle):
    text = (ROOT / cfg).read_text(encoding="utf-8")
    for r in ("tokyo", "kanagawa"):
        assert needle.format(r=r) in text


def test_urban_tile_contract_stays_optional():
    defs = {d["dataset_id"]: d for d in json.loads((ROOT / "data_lake/registry/dataset_definitions.json").read_text(encoding="utf-8"))}
    for did in ("TOKYO-URBAN-001", "KANAGAWA-URBAN-001"):
        assert defs[did]["layer_type"] == "inland_flood" and defs[did]["tile_requirement"] == "optional"

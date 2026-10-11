"""
dataset の tile 契約を持たない current 内 tile の分類（2026-10-11 棚卸し）。

  tokyo_tsunami_A40-23_13     → TOKYO-TSUNAMI-001 に登録（optional、geometry 全件一致）
  kanagawa_tsunami_A40-20_14  → KANAGAWA-TSUNAMI-001 に登録（optional、geometry 全件一致）
  kanagawa_tsunami_A40-16_14  → RETIRED（2016 年版の実質重複。frontend 参照削除後に退役、tests/test_tile_retirement.py）
  chiba_tsunami_A40-18_12     → CHIBA-TSUNAMI-001 に登録（required、2026-10-11 に chiba/tsunami へ移動する MIGRATED）
  tokyo_flood_max / tokyo_storm_surge → RETIRE_CANDIDATE（frontend 未使用、後継 tile あり）
使用中の tile を退役候補にしない。退役候補・未分類は ERROR にしない（削除もしない）。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.services import data_ops_service as dos  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402
from test_data_ops_tile_semantics import _runtime, _tile_bytes  # noqa: E402

DISPOSITIONS = json.loads((ROOT / "data_lake/registry/tile_dispositions.json").read_text(encoding="utf-8"))


def _frontend_tileset_ids() -> set:
    js = (ROOT / "frontend/js/hazard-layers.js").read_text(encoding="utf-8")
    block = js[js.index("const VECTOR_TILE_SOURCES = {"):]
    block = block[:block.index("\n};")]
    return set(re.findall(r"tilesetId: '([^']+)'", block))


@pytest.fixture(autouse=True)
def _tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "tile-cache.json"))


def test_retire_candidates_are_unused_by_frontend():
    used = _frontend_tileset_ids()
    for d in DISPOSITIONS:
        stem = Path(d["rel_path"]).stem
        if d["disposition"] == "RETIRE_CANDIDATE":
            assert stem not in used, stem
            assert d["superseded_by"], stem


def test_used_frontend_tiles_are_never_retire_candidates():
    used = _frontend_tileset_ids()
    managed = {dos.tile_tileset_id(d) for d in get_definition_service().list_all()
               if dos.tile_requirement(d) != "not_applicable" and d.layer_type}
    for d in DISPOSITIONS:
        stem = Path(d["rel_path"]).stem
        if stem in used:
            # MIGRATED は同じ tileset の旧 path（使用中の tile は新 path にある）
            assert d["disposition"] in ("KEEP_LEGACY", "UNKNOWN_CONTRACT", "MIGRATED"), stem
    # frontend が静的 ID で参照する tile は、dataset 契約か分類のどちらかに必ず載っている
    classified = {Path(d["rel_path"]).stem for d in DISPOSITIONS}
    assert used <= managed | classified, used - managed - classified


def test_tsunami_static_ids_are_registered_to_existing_datasets():
    ds = get_definition_service()
    used = _frontend_tileset_ids()
    for did, region, stem in (("TOKYO-TSUNAMI-001", "tokyo", "tokyo_tsunami_A40-23_13"),
                              ("KANAGAWA-TSUNAMI-001", "kanagawa", "kanagawa_tsunami_A40-20_14")):
        d = ds.get(did)
        assert d.tile_requirement == "optional" and dos.tile_tileset_id(d) == stem and stem in used
        assert d.tile_rel_path == f"frontend/tiles/{region}/tsunami/{stem}.mbtiles"  # 2026-10-11 に kanagawa を地域 path へ移動
    # CHIBA-TSUNAMI-001（2026-10-11 正式化）: API が 404 のため tile が唯一の表示経路 → required
    d = ds.get("CHIBA-TSUNAMI-001")
    assert d.tile_requirement == "required" and dos.tile_tileset_id(d) == "chiba_tsunami_A40-18_12" and "chiba_tsunami_A40-18_12" in used
    assert d.tile_rel_path == "frontend/tiles/chiba/tsunami/chiba_tsunami_A40-18_12.mbtiles"


def _view_with(tmp_path, rels):
    t = _tile_bytes(tmp_path)
    return _runtime(tmp_path, {r: t for r in rels}, {r: t for r in rels})


def test_registered_tsunami_tile_is_tile_ok(tmp_path):
    d = get_definition_service().get("TOKYO-TSUNAMI-001")
    view = _view_with(tmp_path, [d.tile_rel_path])
    s = dos.tile_section(d, view, allow_heavy=False, catalog=["tokyo_tsunami_A40-23_13"])
    assert (s["status"], s["state"], s["tileset_id"], s["requirement"]) == (dos.OK, "TILE_OK", "tokyo_tsunami_A40-23_13", "optional")


def test_registered_tsunami_tile_missing_is_optional_warning(tmp_path):
    d = get_definition_service().get("KANAGAWA-TSUNAMI-001")
    s = dos.tile_section(d, _runtime(tmp_path, {}, {}), allow_heavy=False, catalog=[])
    assert (s["status"], s["state"]) == (dos.WARNING, "OPTIONAL_TILE_MISSING")


def test_legacy_listing_shows_dispositions_and_excludes_registered(tmp_path):
    rels = [d["rel_path"] for d in DISPOSITIONS] + [
        "frontend/tiles/tokyo/tsunami/tokyo_tsunami_A40-23_13.mbtiles",
        "frontend/tiles/kanagawa/tsunami/kanagawa_tsunami_A40-20_14.mbtiles",
        "frontend/tiles/tokyo/flood/some_new_unknown.mbtiles"]
    items = {u["rel_path"]: u for u in dos.legacy_tile_section(_view_with(tmp_path, rels), get_definition_service().list_all())}
    assert "frontend/tiles/tokyo/tsunami/tokyo_tsunami_A40-23_13.mbtiles" not in items  # 契約で管理下
    assert "frontend/tiles/kanagawa/tsunami/kanagawa_tsunami_A40-20_14.mbtiles" not in items
    for d in DISPOSITIONS:
        if d["disposition"] == "MIGRATED":
            assert d["rel_path"] not in items  # 移動前の旧 path は dataset の tile（管理下）として扱う
            continue
        u = items[d["rel_path"]]
        assert u["disposition"] == d["disposition"] and u["label"] == dos.TILE_DISPOSITION_LABELS[d["disposition"]]
    assert items["frontend/tiles/tokyo/flood/some_new_unknown.mbtiles"]["label"] == "UNREGISTERED CURRENT TILE（分類未定）"
    assert all("status" not in u for u in items.values())  # 一覧は ERROR 判定に入らない


def test_retire_candidate_does_not_affect_dataset_overall(tmp_path):
    """退役候補 tile の存在で dataset（後継 tile の持ち主）が ERROR にならない。"""
    river = get_definition_service().get("TOKYO-RIVER-001")
    view = _view_with(tmp_path, [dos.tile_rel(river), "frontend/tiles/tokyo/flood/tokyo_flood_max.mbtiles"])
    s = dos.tile_section(river, view, allow_heavy=False, catalog=["tokyo_river_001"])
    assert s["status"] == dos.OK


def test_kanagawa_frontend_uses_only_current_edition():
    """二重描画の解消: tsunami_kanagawa は A40-20 だけ（tileset ID・source layer・opacity は従来どおり）。"""
    js = (ROOT / "frontend/js/hazard-layers.js").read_text(encoding="utf-8")
    block = js[js.index("    tsunami_kanagawa: ["):]
    block = block[:block.index("    ],")]
    assert "kanagawa_tsunami_A40-16_14" not in js
    assert block.count("tilesetId:") == 1
    assert "{ tilesetId: 'kanagawa_tsunami_A40-20_14', sourceLayer: 'kanagawa_tsunami_A40-20_14', opacityFn: () => 0.18 }" in block
    for key, tid in (("tsunami_tokyo", "tokyo_tsunami_A40-23_13"), ("tsunami_chiba", "chiba_tsunami_A40-18_12")):
        b = js[js.index(f"    {key}: ["):]
        assert f"{{ tilesetId: '{tid}', sourceLayer: '{tid}', opacityFn: () => 0.18 }}" in b[:b.index("    ],")]
    disp = {Path(d["rel_path"]).stem: d for d in DISPOSITIONS}
    assert disp["kanagawa_tsunami_A40-16_14"]["disposition"] == "RETIRED"


def test_dispositions_file_is_well_formed():
    rels = [d["rel_path"] for d in DISPOSITIONS]
    assert len(rels) == len(set(rels))
    for d in DISPOSITIONS:
        assert d["disposition"] in dos.TILE_DISPOSITIONS and d["notes"] and d["consumer"]
        assert d["rel_path"].startswith("frontend/tiles/") and d["rel_path"].endswith(".mbtiles")

"""
Data Ops の表示 tile 判定（tile_requirement 契約）。

2026-10-11 棚卸し: ERROR 7 件はすべて「current に tile が無く、mirror の管理外 tile（4〜5 月生成）を
Martin が配信している」状態。frontend の表示経路を dataset ごとに確認して契約を定義した:
  required : tile が唯一の表示経路（flood は API 413、pseudo / lowland は API 422）
  optional : tile 優先だが API GeoJSON（200）で代替表示できる（storm_surge / inland_flood）
未定義（requires_tile_build=true で tile_requirement なし）は UNKNOWN。判定を甘くして ERROR を消さない。
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import data_ops_service as dos  # noqa: E402
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

SURGE = "KANAGAWA-SURGE-001"
LOWLAND = "TOKYO-LOWLAND-POOR-DRAINAGE-001"


def _tile_bytes(tmp: Path, marker: str = "a") -> bytes:
    p = tmp / f"t-{marker}.mbtiles"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE metadata (name text, value text)")
    conn.execute("CREATE TABLE tiles (zoom_level int, tile_column int, tile_row int, tile_data blob)")
    conn.executemany("INSERT INTO metadata VALUES (?, ?)", [("minzoom", "5"), ("maxzoom", "12"), ("m", marker),
                     ("json", json.dumps({"vector_layers": [{"id": "x"}]}))])
    conn.commit()
    conn.close()
    return p.read_bytes()


def _rel(defn) -> str:
    return f"frontend/tiles/{defn.region}/{defn.layer_type}/{dos.tile_tileset_id(defn)}.mbtiles"


def _runtime(tmp: Path, current: dict, mirror: dict):
    """current version（files={rel: bytes}）と Martin mirror（data_runtime/frontend/tiles）を作る。"""
    rt = tmp / "rt"
    v = rt / "versions" / "V1"
    files = {"backend/hazard/storm_surge/kanagawa/x.geojson": b"{}", **current}
    for rel, data in files.items():
        (v / rel).parent.mkdir(parents=True, exist_ok=True)
        (v / rel).write_bytes(data)
    (v / "_manifest.json").write_text(json.dumps({"files": {r: hashlib.sha256(d).hexdigest() for r, d in files.items()}}))
    for rel, data in mirror.items():
        (rt / rel).parent.mkdir(parents=True, exist_ok=True)
        (rt / rel).write_bytes(data)
    os.symlink("versions/V1", rt / "current")
    drr._view_cache.clear()
    return drr.load_runtime_view(rt)


@pytest.fixture(autouse=True)
def _tile_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "tile-cache.json"))


def _defn(dataset_id, **upd):
    d = get_definition_service().get(dataset_id)
    return d.model_copy(update=upd) if upd else d


def _sec(tmp_path, defn, current_tile=True, mirror_tile=True, catalog="match", mirror_bytes=None):
    t = _tile_bytes(tmp_path)
    rel = _rel(defn)
    view = _runtime(tmp_path, {rel: t} if current_tile else {},
                    {rel: mirror_bytes if mirror_bytes is not None else t} if mirror_tile else {})
    cat = None if catalog is None else ([dos.tile_tileset_id(defn)] if catalog == "match" else [])
    return dos.tile_section(defn, view, allow_heavy=False, catalog=cat)


# ── 1〜7: 契約ごとの判定 ──────────────────────────────────────────────────────────

def test_required_missing_is_error(tmp_path):
    s = _sec(tmp_path, _defn(LOWLAND), current_tile=False, mirror_tile=False)
    assert (s["status"], s["state"], s["label"]) == (dos.ERROR, "REQUIRED_TILE_MISSING", "REQUIRED TILE MISSING")


def test_required_present_is_ok(tmp_path):
    s = _sec(tmp_path, _defn(LOWLAND))
    assert (s["status"], s["state"], s["requirement"], s["managed"]) == (dos.OK, "TILE_OK", "required", True)


def test_required_only_in_legacy_mirror_stays_error(tmp_path):
    """表示はできていても、publish・rollback の管理外なら必須 tile は ERROR のまま（緩和しない）。"""
    s = _sec(tmp_path, _defn(LOWLAND), current_tile=False)
    assert (s["status"], s["state"]) == (dos.ERROR, "REQUIRED_TILE_UNMANAGED")
    assert "Martin が配信中" in s["reason"]


def test_optional_missing_is_warning(tmp_path):
    s = _sec(tmp_path, _defn(SURGE), current_tile=False, mirror_tile=False)
    assert (s["status"], s["state"], s["label"]) == (dos.WARNING, "OPTIONAL_TILE_MISSING", "OPTIONAL TILE MISSING")


def test_optional_legacy_unmanaged_is_warning(tmp_path):
    s = _sec(tmp_path, _defn(SURGE), current_tile=False)
    assert (s["status"], s["state"], s["label"]) == (dos.WARNING, "LEGACY_UNMANAGED_TILE", "LEGACY UNMANAGED TILE")


def test_not_applicable_is_na(tmp_path):
    s = _sec(tmp_path, _defn(SURGE, tile_requirement="not_applicable"), current_tile=False, mirror_tile=False)
    assert (s["status"], s["state"], s["label"]) == (dos.NOT_APPLICABLE, "TILE_NOT_APPLICABLE", "TILE N/A")
    landslide = get_definition_service().get("TOKYO-LANDSLIDE-001")  # requires_tile_build なし
    assert dos.tile_section(landslide, _runtime(tmp_path / "x", {}, {}), False)["status"] == dos.NOT_APPLICABLE


def test_not_applicable_tile_does_not_raise_overall():
    comps = {"runtime": {"status": dos.OK}, "tile": {"status": dos.NOT_APPLICABLE}}
    assert dos._overall(comps) == dos.OK
    comps["tile"]["status"] = dos.WARNING
    assert dos._overall(comps) == dos.WARNING
    comps["tile"]["status"] = dos.ERROR
    assert dos._overall(comps) == dos.ERROR


def test_unknown_contract_is_unknown(tmp_path):
    s = _sec(tmp_path, _defn(SURGE, tile_requirement=None), current_tile=False)
    assert (s["status"], s["state"], s["requirement"]) == (dos.UNKNOWN, "UNKNOWN_TILE_CONTRACT", "unknown")


# ── 8: current / mirror / Martin の整合（契約に関係なく壊れた tile は ERROR）───────────

@pytest.mark.parametrize("dataset_id", [LOWLAND, SURGE])
def test_mirror_mismatch_is_error_even_for_optional(tmp_path, dataset_id):
    s = _sec(tmp_path, _defn(dataset_id), mirror_bytes=b"short")
    assert (s["status"], s["state"]) == (dos.ERROR, "TILE_BROKEN")


@pytest.mark.parametrize("dataset_id", [LOWLAND, SURGE])
def test_martin_not_serving_current_tile_is_error(tmp_path, dataset_id):
    s = _sec(tmp_path, _defn(dataset_id), catalog="missing")
    assert (s["status"], s["state"]) == (dos.ERROR, "TILE_BROKEN") and "Martin catalog" in s["reason"]


def test_legacy_tile_listing(tmp_path):
    defs = get_definition_service().list_all()
    surge = _defn(SURGE)
    river = _defn("KANAGAWA-RIVER-001")
    t = _tile_bytes(tmp_path)
    view = _runtime(tmp_path, {_rel(river): t, "frontend/tiles/tokyo/flood/tokyo_flood_max.mbtiles": t},
                    {_rel(river): t, _rel(surge): t, "frontend/tiles/tokyo/storm_surge/tokyo_storm_surge.mbtiles": t})
    items = {u["rel_path"]: u for u in dos.legacy_tile_section(view, defs, catalog=["kanagawa_surge_001"])}
    assert _rel(river) not in items  # 管理下
    assert items[_rel(surge)]["dataset_id"] == SURGE and items[_rel(surge)]["in_current"] is False
    assert items[_rel(surge)]["martin_registered"] == dos.OK and items[_rel(surge)]["label"].startswith("LEGACY TILE")
    assert items["frontend/tiles/tokyo/flood/tokyo_flood_max.mbtiles"]["label"].startswith("UNREGISTERED TILE（current 内・dataset の tile 契約なし")
    assert items["frontend/tiles/tokyo/storm_surge/tokyo_storm_surge.mbtiles"]["label"] == "UNREGISTERED TILE（mirror のみ）"


# ── registry: 事実確認できた dataset だけに契約を設定 ─────────────────────────────

EXPECTED = {
    "TOKYO-RIVER-001": "required", "KANAGAWA-RIVER-001": "required",
    "TOKYO-PSEUDO-INLAND-FLOOD-001": "required",
    "TOKYO-LOWLAND-POOR-DRAINAGE-001": "required", "KANAGAWA-LOWLAND-POOR-DRAINAGE-001": "required",
    "TOKYO-SURGE-001": "optional", "KANAGAWA-SURGE-001": "optional",
    "TOKYO-URBAN-001": "optional", "KANAGAWA-URBAN-001": "optional",
}


def test_registry_tile_requirements_are_pinned():
    got = {d.dataset_id: d.tile_requirement for d in get_definition_service().list_all() if d.tile_requirement}
    assert got == EXPECTED
    for d in get_definition_service().list_all():
        if d.dataset_id in EXPECTED:
            assert d.requires_tile_build and d.tile_notes, d.dataset_id


def test_frontend_contract_matches_requirement():
    """required = frontend に API fallback が無い（apiUrl なし）か API が全量応答を拒否する type。"""
    js = (ROOT / "frontend/js/hazard-layers.js").read_text(encoding="utf-8")
    for key in ("pseudo_inland_flood_tokyo", "lowland_poor_drainage_tokyo", "lowland_poor_drainage_kanagawa"):
        block = js[js.index(f"    {key}: {{"):]
        block = block[:block.index("\n    }")]
        assert "apiUrl" not in block, key
    for key in ("storm_surge_tokyo", "storm_surge_kanagawa", "inland_flood_tokyo", "inland_flood_kanagawa"):
        block = js[js.index(f"    {key}: {{"):]
        block = block[:block.index("\n    }")]
        assert "apiUrl: '/api/hazards/" in block, key
    hz = (ROOT / "backend/app/api/hazards.py").read_text(encoding="utf-8")
    assert '_HAZARD_LARGE_RESPONSE_LIMITED_TYPES = frozenset({"flood"})' in hz
    assert '"pseudo_inland_flood",' in hz and '"lowland_poor_drainage",' in hz

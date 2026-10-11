"""
CHIBA-TSUNAMI-001 の正式 dataset 化（2026-10-11、Local build phase）。

  source    : 国土数値情報 A40-18_12（2018 年、v1.0。2026-10-11 時点で最新）
  canonical : data_lake/validated/chiba/tsunami/chiba-tsunami-001.geojson（公式 pipeline で生成）
  tile      : frontend/tiles/chiba/tsunami/chiba_tsunami_A40-18_12.mbtiles（required、tileset_id は不変）
              旧 path tokyo/tsunami/ は tile_dispositions.json の MIGRATED
  backend   : hazard.tsunami.targets には加えない（OWNER 判断待ち）

data_lake の実 file（gitignore）を使う test は、file が無い環境では skip する。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.services import data_ops_service as dos  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


nt = _load("normalize_tsunami", "scripts/normalize/normalize_tsunami.py")
ret = _load("apply_tile_retirements", "scripts/publish/apply_tile_retirements.py")
rpf = _load("rollback_preflight", "scripts/publish/rollback_preflight.py")

DID = "CHIBA-TSUNAMI-001"
STEM = "chiba_tsunami_A40-18_12"
NEW = f"frontend/tiles/chiba/tsunami/{STEM}.mbtiles"
OLD = f"frontend/tiles/tokyo/tsunami/{STEM}.mbtiles"
LEGACY_SHA = "847dc791257628a9945c12b2561cd53395907cd58e565fb78c3c4719cc25a85c"
SOURCE_SHA = "becf21ab28d686cef622e3b26cf56b6782c6fb868dc0ca98d38e7bdb6875689b"
CANONICAL_SHA = "1dad9f90c4ff4cfad73d918a37d7eac85f3edb1dce614f680b47e2e3619178bc"
REGISTRY = ROOT / "data_lake/registry/dataset_definitions.json"
DISPOSITIONS = ROOT / "data_lake/registry/tile_dispositions.json"
RAW = ROOT / "data_lake/raw/chiba/tsunami/A40-18_12_GML.zip"
CANONICAL = ROOT / "data_lake/validated/chiba/tsunami/chiba-tsunami-001.geojson"
TILE = ROOT / "data_lake/tiles/chiba/tsunami" / f"{STEM}.mbtiles"


def _defn():
    return get_definition_service().get(DID)


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _write(root: Path, rel: str, data: bytes) -> str:
    (root / rel).parent.mkdir(parents=True, exist_ok=True)
    (root / rel).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


# ── source provenance ──────────────────────────────────────────────────────────

def test_definition_records_official_source():
    d = _defn()
    assert (d.region, d.layer_type, d.category) == ("chiba", "tsunami", "tsunami")
    assert d.source_url == "https://nlftp.mlit.go.jp/ksj/gml/data/A40/A40-18/A40-18_12_GML.zip"
    assert d.official_source_url == "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A40-2024.html"
    assert (d.source_year, d.source_version, d.expected_source_region_code) == ("2018", "1.0", "12")
    assert d.expected_source_files == ["A40-18_12_GML.zip"] and d.required_source_count == 1
    assert re.match(d.source_region_code_regex, "A40-18_12_GML.zip").group(1) == "12"
    assert not re.match(d.source_region_code_regex, "A40-20_14_GML.zip").group(1) == "12"  # 神奈川は千葉に入らない
    for kind in ("raw", "normalized", "validated"):
        assert getattr(d, f"{kind}_storage_path") == f"data_lake/{kind}/chiba/tsunami"


@pytest.mark.skipif(not RAW.is_file(), reason="raw zip が無い環境（data_lake は gitignore）")
def test_raw_source_is_the_official_zip():
    assert RAW.stat().st_size == 70_755_828 and _sha256(RAW) == SOURCE_SHA


# ── normalize: 深さ表現 ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,depth", [
    # 千葉（A40-18_12）: 「以上 未満」形式
    ("0.01m以上 0.3m未満", 0.5), ("0.3m以上 0.5m未満", 0.5), ("0.5m以上 1.0m未満", 0.75),
    ("1.0m以上 3.0m未満", 2.0), ("3.0m以上 5.0m未満", 4.0), ("5.0m以上 10.0m未満", 5.0),
    ("10.0m以上 20.0m未満", 10.0), ("20.0m以上", 20.0),
    # 東京・神奈川の表記（全角空白・波ダッシュ）
    ("0.3m未満", 0.5), ("0.3m以上 ～ 0.5m未満", 0.5), ("1m以上 ～ 2m未満", 1.5), ("5m以上 ～ 10m未満", 5.0),
    # 旧実装は先頭の数値列を誤読して 5.0 を返していた（2026-10-11 修正）
    ("0.5m以上 ～ 1m未満", 0.75),
])
def test_depth_expression(text, depth):
    assert nt._extract_depth_value(text) == pytest.approx(depth)


def test_depth_expression_keeps_numeric_and_empty_inputs():
    assert nt._extract_depth_value(2.5) == pytest.approx(2.5)
    assert nt._extract_depth_value(None) is None
    assert nt._extract_depth_value("") is None


# ── canonical ──────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not CANONICAL.is_file(), reason="canonical が無い環境（data_lake は gitignore）")
def test_canonical_schema_and_count():
    import ijson
    assert _sha256(CANONICAL) == CANONICAL_SHA
    n, depths, kinds = 0, set(), set()
    keys = {"A40_001", "A40_002", "A40_003", "dataset_id", "depth", "depth_text", "hazard_type"}
    with open(CANONICAL, "rb") as f:
        for feat in ijson.items(f, "features.item", use_float=True):
            n += 1
            p = feat["properties"]
            assert set(p) == keys and p["dataset_id"] == DID and p["hazard_type"] == "tsunami"
            depths.add(p["depth"])
            kinds.add(feat["geometry"]["type"])
    assert n == 175_389 and kinds == {"MultiPolygon"}
    assert depths <= {0.5, 0.75, 2.0, 4.0, 5.0, 10.0, 20.0}


# ── tile 契約 / path ────────────────────────────────────────────────────────────

def test_tile_contract_points_to_chiba_path_with_same_tileset_id():
    d = _defn()
    assert d.tile_requirement == "required" and d.tile_rel_path == NEW
    assert dos.tile_tileset_id(d) == STEM
    assert dos.tile_rel_candidates(d) == [NEW, OLD]


def test_migration_record_for_legacy_path():
    m = {x["tileset_id"]: x for x in ret.load_migrations(DISPOSITIONS)}[STEM]
    assert (m["rel_path"], m["migrated_to"], m["sha256"]) == (OLD, NEW, LEGACY_SHA)


@pytest.mark.skipif(not TILE.is_file(), reason="tile が無い環境（data_lake は gitignore）")
def test_regenerated_tile_metadata():
    import sqlite3
    c = sqlite3.connect(f"file:{TILE}?mode=ro", uri=True)
    meta = dict(c.execute("SELECT name, value FROM metadata"))
    layers = json.loads(meta["json"])["vector_layers"]
    assert [l["id"] for l in layers] == [STEM]  # frontend の sourceLayer と一致
    assert (meta["minzoom"], meta["maxzoom"]) == ("5", "16")
    assert c.execute("PRAGMA quick_check").fetchone()[0] == "ok"


def test_staging_moves_chiba_only_when_new_path_present(tmp_path):
    migs = [m for m in ret.load_migrations(DISPOSITIONS) if m["tileset_id"] == STEM]
    _write(tmp_path, OLD, b"legacy")
    with pytest.raises(ValueError, match="移動先"):
        ret.apply_staging_migrations(tmp_path, migs)  # region chiba を含まない publish は止まる（tile を失わない）
    assert (tmp_path / OLD).exists()
    _write(tmp_path, NEW, b"new")
    assert ret.apply_staging_migrations(tmp_path, migs) == [OLD]
    assert (tmp_path / NEW).exists() and not (tmp_path / OLD).exists()


# ── frontend / Martin ──────────────────────────────────────────────────────────

def test_frontend_static_id_unchanged():
    js = (ROOT / "frontend/js/hazard-layers.js").read_text(encoding="utf-8")
    assert f"{{ tilesetId: '{STEM}', sourceLayer: '{STEM}', opacityFn: () => 0.18 }}" in js
    assert "apiUrl: '/api/hazards/tsunami/chiba'" in js


def test_martin_config_keeps_legacy_dir_until_production_migration():
    """Martin 1.14.0 は設定した path が無いと起動しない。chiba/tsunami は本番の dir 作成後、
    MARTIN_RESTART_REQUIRED の再起動と同時に追加する（それまで旧 tile を tokyo/tsunami から配信）。"""
    for name, prefix in (("martin.yaml", "/tiles/"), ("martin-local.yaml", "/data_runtime/frontend/tiles/")):
        cfg = (ROOT / "config" / name).read_text(encoding="utf-8")
        paths = [l.strip()[2:] for l in cfg.splitlines() if l.strip().startswith(f"- {prefix}")]
        assert f"{prefix}tokyo/tsunami" in paths, name
        assert f"{prefix}chiba/tsunami" not in paths, name


# ── Data Ops / rollback guard ──────────────────────────────────────────────────

@pytest.fixture
def _cache(tmp_path, monkeypatch):
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "tc.json"))


@pytest.mark.parametrize("rel", [NEW, OLD])
def test_data_ops_shows_chiba_tile_ok_at_either_path(tmp_path, _cache, rel):
    from test_data_ops_tile_semantics import _runtime, _tile_bytes
    t = _tile_bytes(tmp_path)
    view = _runtime(tmp_path, {rel: t}, {rel: t})
    s = dos.tile_section(_defn(), view, False, [STEM])
    assert (s["status"], s["state"], s["rel_path"], s["requirement"]) == (dos.OK, "TILE_OK", rel, "required")
    assert rel not in {u["rel_path"] for u in dos.legacy_tile_section(view, get_definition_service().list_all())}


def test_data_ops_missing_chiba_tile_is_error(tmp_path, _cache):
    from test_data_ops_tile_semantics import _runtime
    s = dos.tile_section(_defn(), _runtime(tmp_path, {}, {}), False, [])
    assert (s["status"], s["state"]) == (dos.ERROR, "REQUIRED_TILE_MISSING")


@pytest.mark.parametrize("rel,verdict_ok", [(OLD, True), (NEW, True), (None, False)])
def test_rollback_guard_for_chiba(tmp_path, rel, verdict_ok):
    v = tmp_path / "versions" / "V"
    files = {}
    if rel:
        files[rel] = _write(v, rel, b"chiba")
    v.mkdir(parents=True, exist_ok=True)
    (v / "_manifest.json").write_text(json.dumps({"files": files}))
    c = {x["dataset_id"]: x for x in rpf.preflight(v, REGISTRY)["checks"]}[DID]
    assert (c["severity"] == "OK") is verdict_ok
    if not verdict_ok:
        assert c["severity"] == "BLOCK"  # 移動前・移動後のどちらにも無い version へは戻さない


# ── backend target 未追加時の既存挙動 ────────────────────────────────────────────

def test_backend_tsunami_targets_unchanged():
    props = (ROOT / "backend/app.properties").read_text(encoding="utf-8")
    assert re.search(r"^hazard\.tsunami\.targets=tokyo,kanagawa$", props, re.M)


def test_chiba_runtime_geojson_is_not_a_loader_target():
    props = {"hazard.tsunami.targets": "tokyo,kanagawa"}
    assert dos.loader_contract("backend/hazard/tsunami/tsunami_chiba.geojson", props)["loader_target"] is False
    assert dos.loader_contract("backend/hazard/tsunami/tsunami_kanagawa.geojson", props)["loader_target"] is True


def test_deploy_never_places_legacy_samples_outside_tokyo():
    """region chiba の publish で、内水氾濫・土砂災害の開発用 sample が chiba の runtime（ナビ判定）へ入らない。"""
    sh = (ROOT / "scripts/publish/deploy_to_runtime.sh").read_text(encoding="utf-8")
    for kind in ("inland_flood", "landslide"):
        i = sh.index(f'"${{RUNTIME_BACKEND}}/hazard/{kind}/${{REGION}}/{kind}_sample.geojson"')
        start = sh.rindex(f'if [[ -d "${{NORMALIZED}}/{kind}" ]]', 0, i)
        block = sh[start:sh.index("\nfi\n", i)]
        tokyo, other = block.split('elif [[ "${REGION}" == "tokyo" ]]; then')
        tokyo_branch, else_branch = other.split("\nelse\n")
        assert f"{kind}_sample.geojson" in tokyo_branch and "deploy_file" in tokyo_branch, kind
        assert "deploy_file" not in else_branch and "sample" not in else_branch.replace("sample を", ""), kind

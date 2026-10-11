"""
Tsunami Backend Safety Contract（2026-10-11）。

  A. TSUNAMI-UNLOADED-REGION-SAFETY: targets で読まない region の地点を "outside" / safe と返さない
     OUTSIDE  = その region の dataset を読み、polygon 外だった
     UNKNOWN  = その region の dataset を読んでいない（hazard_coverage_status=SOURCE_UNAVAILABLE）
  B. API-EXPOSURE-CONTRACT: dataset の存在・directory の file では public GeoJSON API を有効にしない
  C. TSUNAMI-REGION-OWNERSHIP: tsunami の runtime artifact は region 一致の registry dataset からだけ選ぶ
     ＋ MIGRATED の移動先 region を publish 対象へ自動で含める
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

import tsunami_coverage as tc  # noqa: E402
from hazard_engine import HazardEngine  # noqa: E402
from hazard_service import HazardService, derive_hazard_safe  # noqa: E402


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


nt = _load("normalize_tsunami", "scripts/normalize/normalize_tsunami.py")
rts = _load("resolve_tsunami_source", "scripts/publish/resolve_tsunami_source.py")
ret = _load("apply_tile_retirements", "scripts/publish/apply_tile_retirements.py")

REGISTRY = ROOT / "data_lake/registry/dataset_definitions.json"
COVERAGE = tc.coverage_dir_for(REGISTRY)
TATEYAMA, KATAKAI, NARITA = (34.9960, 139.8640), (35.5390, 140.4610), (35.7764, 140.3183)
CANON = {r: ROOT / f"data_lake/validated/{r}/tsunami/{r}-tsunami-001.geojson" for r in ("tokyo", "kanagawa", "chiba")}


# ── fixture: 小さな合成 tsunami polygon ───────────────────────────────────────────

def _square(lat, lon, d=0.002):
    return [[lon - d, lat - d], [lon + d, lat - d], [lon + d, lat + d], [lon - d, lat + d], [lon - d, lat - d]]


def _fc(path: Path, dataset_id: str, centers, depth_text="0.5m以上 1.0m未満"):
    feats = [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [_square(*c)]},
              "properties": {"dataset_id": dataset_id, "depth_text": depth_text,
                             "depth": nt._extract_depth_value(depth_text), "hazard_type": "tsunami"}}
             for c in centers]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
    return path


KANAGAWA_PT = (35.3080, 139.5430)   # 鎌倉 由比ヶ浜


@pytest.fixture
def chiba_index(tmp_path):
    src = _fc(tmp_path / "chiba.geojson", "CHIBA-TSUNAMI-001", [TATEYAMA, KATAKAI])
    p = tmp_path / "cov" / "chiba.json"
    p.parent.mkdir()
    p.write_text(json.dumps(tc.build_index(src, "CHIBA-TSUNAMI-001", "chiba")), encoding="utf-8")
    return tc.load_index(p, "CHIBA-TSUNAMI-001", "chiba")


def _service(tmp_path, regions):
    hs = HazardService()
    srcs = {"kanagawa": [KANAGAWA_PT], "chiba": [TATEYAMA, KATAKAI]}
    for r in regions:
        hs.load_geojson_streaming("tsunami", _fc(tmp_path / f"tsunami_{r}.geojson", f"{r.upper()}-TSUNAMI-001", srcs[r]),
                                  bbox_only=True)
    hs.set_expected_tsunami_sources(list(regions))
    return hs


# ── A. UNKNOWN と OUTSIDE ───────────────────────────────────────────────────────

def test_unloaded_region_is_unknown_not_outside(tmp_path, chiba_index):
    hs = _service(tmp_path, ["kanagawa"])
    hs.set_tsunami_unevaluated_coverage([chiba_index], [])
    for pt in (TATEYAMA, KATAKAI):
        assert hs.assess_candidate(*pt)["tsunami"] == "unknown"


def test_unloaded_region_is_not_safe(tmp_path, chiba_index):
    hs = _service(tmp_path, ["kanagawa"])
    hs.set_tsunami_unevaluated_coverage([chiba_index], [])
    ev = HazardEngine(hs).evaluate_point(*TATEYAMA)
    assert ev["is_danger"] is False  # 検出は無い
    assert ev["hazard_coverage_status"]["tsunami"] == "SOURCE_UNAVAILABLE"
    assert ev["aggregate_status"] == "SOURCE_UNAVAILABLE"  # 安全の確定ではない
    assert derive_hazard_safe(ev["hazard_assessment"]) is None
    assert HazardEngine(hs).evaluate_destination(*TATEYAMA)["hazard_safe"] is None


def test_loaded_inside_is_danger(tmp_path, chiba_index):
    hs = _service(tmp_path, ["kanagawa", "chiba"])
    ev = HazardEngine(hs).evaluate_point(*TATEYAMA)
    assert ev["hazard_assessment"]["tsunami"] == "inside" and ev["is_danger"] is True
    assert ev["aggregate_status"] == "HAZARD_DETECTED"


def test_loaded_outside_is_outside(tmp_path, chiba_index):
    hs = _service(tmp_path, ["kanagawa", "chiba"])
    assert hs.assess_candidate(*NARITA)["tsunami"] == "outside"
    # 評価していない region があっても、その範囲外の地点は outside のまま（index は bbox の上位集合）
    hs2 = _service(tmp_path, ["kanagawa"])
    hs2.set_tsunami_unevaluated_coverage([chiba_index], [])
    assert hs2.assess_candidate(*NARITA)["tsunami"] == "outside"
    assert hs2.assess_candidate(*KANAGAWA_PT)["tsunami"] == "inside"  # 読み込んだ region の inside は変えない


def test_unresolved_region_fails_closed(tmp_path):
    hs = _service(tmp_path, ["kanagawa"])
    hs.set_tsunami_unevaluated_coverage([], ["chiba: index が無い"])
    assert hs.assess_candidate(*NARITA)["tsunami"] == "unknown"


def test_resolve_unevaluated_requires_index_matching_registry(tmp_path):
    reg = tmp_path / "registry" / "dataset_definitions.json"
    reg.parent.mkdir()
    reg.write_text(json.dumps([{"dataset_id": "CHIBA-TSUNAMI-001", "region": "chiba", "layer_type": "tsunami"},
                               {"dataset_id": "TOKYO-TSUNAMI-001", "region": "tokyo", "layer_type": "tsunami"}]))
    cov = tc.coverage_dir_for(reg)
    idx, problems = tc.resolve_unevaluated(reg, cov, ["tokyo"])
    assert idx == [] and problems and problems[0].startswith("chiba")  # index 欠落は fail closed
    cov.mkdir()
    src = _fc(tmp_path / "c.geojson", "CHIBA-TSUNAMI-001", [TATEYAMA])
    bad = tc.build_index(src, "CHIBA-TSUNAMI-001", "chiba")
    (cov / "chiba.json").write_text(json.dumps(dict(bad, region="tokyo")))
    assert tc.resolve_unevaluated(reg, cov, ["tokyo"])[1]  # region 不一致は不採用
    (cov / "chiba.json").write_text(json.dumps(bad))
    idx, problems = tc.resolve_unevaluated(reg, cov, ["tokyo"])
    assert [i.region for i in idx] == ["chiba"] and problems == []
    assert tc.resolve_unevaluated(reg, cov, ["tokyo", "chiba"]) == ([], [])  # 評価する region は対象外


def test_index_rejects_foreign_dataset_features(tmp_path):
    src = _fc(tmp_path / "x.geojson", "TOKYO-TSUNAMI-001", [TATEYAMA])
    with pytest.raises(ValueError):
        tc.build_index(src, "CHIBA-TSUNAMI-001", "chiba")


# ── 実データ: 登録済み index と CHIBA target PoC ──────────────────────────────────

@pytest.mark.parametrize("region", ["tokyo", "kanagawa", "chiba"])
def test_committed_index_matches_registry_and_canonical(region):
    defs = dict((r, d) for d, r in tc.registered_tsunami_datasets(REGISTRY))
    raw = json.loads((COVERAGE / f"{region}.json").read_text(encoding="utf-8"))
    idx = tc.load_index(COVERAGE / f"{region}.json", defs[region], region)
    assert idx.cell_count() > 0
    if not CANON[region].is_file():
        pytest.skip("canonical が無い環境（data_lake は gitignore）")
    assert tc.build_index(CANON[region], defs[region], region) == raw  # 現行 canonical から作り直しても同じ
    hs = HazardService()
    hs.load_geojson_streaming("tsunami", CANON[region], bbox_only=True)
    arr = hs._tsunami_bboxes_np.astype(np.float64)
    for s, w, n, e in arr[:: max(1, len(arr) // 5000)]:
        for lat, lon in ((s, w), (n, e), ((s + n) / 2, (w + e) / 2)):
            assert idx.contains(lat, lon)  # index の外は必ず bbox の外（outside が事実として正しい）


def _runtime_named(tmp_path, region):
    """backend の読込規約と同じ tsunami_<region>.geojson 名（source stem で target を照合する）。"""
    p = tmp_path / f"tsunami_{region}.geojson"
    if not p.exists():
        p.symlink_to(CANON[region])
    return p


@pytest.mark.skipif(not all(p.is_file() for p in CANON.values()), reason="canonical が無い環境")
def test_chiba_target_poc_three_states(tmp_path):
    full = HazardService()
    for r in ("tokyo", "kanagawa", "chiba"):
        full.load_geojson_streaming("tsunami", _runtime_named(tmp_path, r), bbox_only=True)
    full.set_expected_tsunami_sources(["tokyo", "kanagawa", "chiba"])
    assert full.get_missing_tsunami_sources() == []
    assert full.assess_candidate(*TATEYAMA)["tsunami"] == "inside"
    assert full.assess_candidate(*KATAKAI)["tsunami"] == "inside"
    assert full.assess_candidate(*NARITA)["tsunami"] == "outside"
    current = HazardService()  # 本番と同じ targets=tokyo,kanagawa
    for r in ("tokyo", "kanagawa"):
        current.load_geojson_streaming("tsunami", _runtime_named(tmp_path, r), bbox_only=True)
    current.set_expected_tsunami_sources(["tokyo", "kanagawa"])
    current.set_tsunami_unevaluated_coverage(*tc.resolve_unevaluated(REGISTRY, COVERAGE, ["tokyo", "kanagawa"]))
    assert current.assess_candidate(*TATEYAMA)["tsunami"] == "unknown"
    assert current.assess_candidate(*KATAKAI)["tsunami"] == "unknown"
    assert current.assess_candidate(*NARITA)["tsunami"] == "outside"


# ── frontend: 未評価を「区域外 / 安全」と表示しない ───────────────────────────────

def test_hazard_check_response_carries_coverage_contract():
    src = (ROOT / "backend/app_public.py").read_text(encoding="utf-8")
    block = src[src.index('@app.get("/api/hazard-check")'):src.index('@app.get("/api/reverse-geocode"')]
    assert '"aggregate_status": point_eval["aggregate_status"]' in block
    assert '"hazard_coverage_status": point_eval["hazard_coverage_status"]' in block
    assert "set_tsunami_unevaluated_coverage" in src


def test_danger_panel_does_not_show_safe_for_unknown():
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node が無い")
    script = r"""
const fs = require('fs'); const vm = require('vm');
const el = { className: '', innerHTML: '', style: { display: '', cssText: '' } };
const ctx = { document: { getElementById: () => el }, console, getHazardDisplayName: (h) => h,
              getSeverityRank: () => 1, getSeverityInfo: () => ({ icon: '!', text: 't' }) };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8') + '\n;this.displayHazardStatus = displayHazardStatus;', ctx);
const out = {};
ctx.displayHazardStatus({ is_danger: false, hazards: [], assessment: { tsunami: 'unknown', flood: 'outside' },
                          aggregate_status: 'SOURCE_UNAVAILABLE' });
out.unknown = { cls: el.className, html: el.innerHTML };
ctx.displayHazardStatus({ is_danger: false, hazards: [], assessment: { tsunami: 'outside' },
                          aggregate_status: 'NO_HAZARD_RECORD' });
out.outside = { cls: el.className, html: el.innerHTML };
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "-e", script, str(ROOT / "frontend/js/ui.js")], capture_output=True, text=True, check=True)
    out = json.loads(r.stdout)
    assert "✅" not in out["unknown"]["html"] and "区域外です" not in out["unknown"]["html"]
    assert "津波" in out["unknown"]["html"] and "unknown" in out["unknown"]["cls"]
    assert "✅" in out["outside"]["html"] and "safe" in out["outside"]["cls"]  # 評価済み outside は従来どおり


# ── B. API exposure ─────────────────────────────────────────────────────────────

ENABLED = {"TOKYO-TSUNAMI-001", "KANAGAWA-TSUNAMI-001", "TOKYO-SURGE-001", "KANAGAWA-SURGE-001",
           "TOKYO-URBAN-001", "KANAGAWA-URBAN-001", "TOKYO-LANDSLIDE-001", "KANAGAWA-LANDSLIDE-001"}


def test_api_exposure_is_explicit_and_existing_set_unchanged():
    from app.services.dataset_definition_service import get_definition_service
    defs = get_definition_service().list_all()
    assert {d.dataset_id for d in defs if d.api_exposure == "enabled"} == ENABLED
    assert get_definition_service().get("CHIBA-TSUNAMI-001").api_exposure == "disabled"
    raw = json.loads(REGISTRY.read_text(encoding="utf-8"))
    assert all(d.get("api_exposure") in (None, "enabled", "disabled") for d in raw)


@pytest.fixture
def api(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from _testclient_compat import TestClient
    from app.api import hazards
    from app.services import dataset_definition_service as dds
    monkeypatch.setattr(hazards, "_BACKEND_DIR", tmp_path / "backend")
    monkeypatch.setattr(hazards.runtime_version_access, "is_available", lambda: False)

    def _no_active(*a, **k):
        raise KeyError("no active")
    monkeypatch.setattr(hazards.hazard_dataset_service, "_resolve_active_dataset", _no_active)
    defs = []
    monkeypatch.setattr(dds, "get_definition_service", lambda: SimpleNamespace(list_all=lambda: defs))
    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app), defs, tmp_path


def _defn(layer_type, region, exposure):
    return SimpleNamespace(layer_type=layer_type, region=region, api_exposure=exposure)


@pytest.mark.parametrize("hazard_type", ["tsunami", "storm_surge", "inland_flood", "landslide"])
def test_directory_file_alone_does_not_publish_api(api, hazard_type):
    client, defs, tmp = api
    _fc(tmp / "data_lake/normalized/chiba" / hazard_type / "big.geojson", "CHIBA-X", [TATEYAMA])
    assert client.get(f"/api/hazards/{hazard_type}/chiba").status_code == 404  # dataset 未登録
    defs.append(_defn(hazard_type, "chiba", None))
    assert client.get(f"/api/hazards/{hazard_type}/chiba").status_code == 404  # 未設定 = disabled
    defs[-1] = _defn(hazard_type, "chiba", "disabled")
    assert client.get(f"/api/hazards/{hazard_type}/chiba").status_code == 404
    defs[-1] = _defn(hazard_type, "chiba", "enabled")
    assert client.get(f"/api/hazards/{hazard_type}/chiba").status_code == 200  # 明示した場合だけ配信


def test_exposure_check_failure_is_fail_closed(api, monkeypatch):
    client, _, tmp = api
    from app.services import dataset_definition_service as dds

    def _boom():
        raise OSError("registry unreadable")
    monkeypatch.setattr(dds, "get_definition_service", _boom)
    _fc(tmp / "data_lake/normalized/tokyo/tsunami/t.geojson", "TOKYO-TSUNAMI-001", [TATEYAMA])
    assert client.get("/api/hazards/tsunami/tokyo").status_code == 500


# ── C. region ownership（tsunami deploy）────────────────────────────────────────

def _d(did, region, exposure=None):
    return SimpleNamespace(dataset_id=did, region=region, layer_type="tsunami", api_exposure=exposure,
                           validated_storage_path=f"data_lake/validated/{region}/tsunami")


def _lake(tmp_path):
    lake = tmp_path / "data_lake"
    _fc(lake / "validated/tokyo/tsunami/tokyo-tsunami-001.geojson", "TOKYO-TSUNAMI-001", [(35.64, 139.79)])
    _fc(lake / "validated/chiba/tsunami/chiba-tsunami-001.geojson", "CHIBA-TSUNAMI-001", [TATEYAMA])
    # 旧 pipeline の残骸（file 名だけなら chiba に見える）
    _fc(lake / "validated/tokyo/tsunami/tsunami_chiba.geojson", "LEGACY", [TATEYAMA])
    _fc(lake / "normalized/tokyo/tsunami/tsunami_chiba.geojson", "LEGACY", [TATEYAMA])
    return lake


DEFS = [_d("TOKYO-TSUNAMI-001", "tokyo", "enabled"), _d("CHIBA-TSUNAMI-001", "chiba", "disabled")]


def test_tokyo_deploy_never_picks_chiba_artifact(tmp_path):
    lake = _lake(tmp_path)
    out = rts.resolve("tokyo", ["tokyo", "kanagawa", "chiba"], DEFS, lake, nt._extract_depth_value)
    assert {(k, d) for k, d, _ in out} == {("backend", "TOKYO-TSUNAMI-001"), ("frontend_layer", "TOKYO-TSUNAMI-001")}
    assert all(p.name == "tokyo-tsunami-001.geojson" for _, _, p in out)


def test_chiba_not_in_targets_deploys_no_geojson(tmp_path):
    lake = _lake(tmp_path)
    assert rts.resolve("chiba", ["tokyo", "kanagawa"], DEFS, lake, nt._extract_depth_value) == []
    out = rts.resolve("chiba", ["tokyo", "kanagawa", "chiba"], DEFS, lake, nt._extract_depth_value)
    assert [(k, d) for k, d, _ in out] == [("backend", "CHIBA-TSUNAMI-001")]  # api_exposure=disabled → layer 無し


def test_region_mismatch_fails_closed(tmp_path):
    lake = _lake(tmp_path)
    _fc(lake / "validated/chiba/tsunami/chiba-tsunami-001.geojson", "TOKYO-TSUNAMI-001", [TATEYAMA])
    with pytest.raises(ValueError, match="region 不一致"):
        rts.resolve("chiba", ["chiba"], DEFS, lake, nt._extract_depth_value)
    bad = [_d("CHIBA-TSUNAMI-001", "chiba")]
    bad[0].validated_storage_path = "data_lake/validated/tokyo/tsunami"
    with pytest.raises(ValueError):
        rts.resolve("chiba", ["chiba"], bad, lake, nt._extract_depth_value)
    with pytest.raises(ValueError, match="複数"):
        rts.resolve("tokyo", ["tokyo"], DEFS + [_d("TOKYO-TSUNAMI-002", "tokyo")], lake, nt._extract_depth_value)
    with pytest.raises(ValueError, match="registry に tsunami dataset が無い"):
        rts.resolve("osaka", ["osaka"], DEFS, lake, nt._extract_depth_value)


def test_stale_depth_canonical_is_not_published(tmp_path):
    lake = _lake(tmp_path)
    p = lake / "validated/tokyo/tsunami/tokyo-tsunami-001.geojson"
    fc = json.loads(p.read_text())
    fc["features"][0]["properties"].update(depth_text="0.5m以上 ～ 1m未満", depth=5.0)  # 旧 normalizer の誤変換
    p.write_text(json.dumps(fc))
    with pytest.raises(ValueError, match="再生成"):
        rts.resolve("tokyo", ["tokyo"], DEFS, lake, nt._extract_depth_value)


def test_deploy_script_selects_tsunami_only_via_registry():
    sh = (ROOT / "scripts/publish/deploy_to_runtime.sh").read_text(encoding="utf-8")
    assert "resolve_tsunami_source.py" in sh
    assert '-name "${target}-tsunami-*.geojson"' not in sh and 'tsunami/tsunami_${REGION}.geojson" ]]' not in sh
    assert '"${RUNTIME_BACKEND}/hazard/tsunami/tsunami_${REGION}.geojson"' in sh
    assert 'find "${NORMALIZED}/tsunami"' not in sh


# ── C'. MIGRATED の移動先 region を publish 対象へ自動で含める ─────────────────────

OLD = "frontend/tiles/tokyo/tsunami/chiba_tsunami_A40-18_12.mbtiles"
NEW = "frontend/tiles/chiba/tsunami/chiba_tsunami_A40-18_12.mbtiles"
MIG = {"rel_path": OLD, "migrated_to": NEW, "tileset_id": "chiba_tsunami_A40-18_12"}


def _tile_defs(tile_rel=NEW, region="chiba"):
    return [SimpleNamespace(dataset_id="CHIBA-TSUNAMI-001", region=region, tile_rel_path=tile_rel),
            SimpleNamespace(dataset_id="TOKYO-TSUNAMI-001", region="tokyo", tile_rel_path=None)]


def _current(tmp_path, *rels):
    for r in rels:
        (tmp_path / r).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / r).write_bytes(b"t")
    return tmp_path


def test_pending_migration_region_is_included(tmp_path):
    assert ret.pending_migration_regions(_current(tmp_path, OLD), [MIG], _tile_defs()) == ["chiba"]


def test_completed_migration_adds_nothing(tmp_path):
    assert ret.pending_migration_regions(_current(tmp_path, OLD, NEW), [MIG], _tile_defs()) == []
    assert ret.pending_migration_regions(_current(tmp_path / "n"), [MIG], _tile_defs()) == []


def test_unknown_or_inconsistent_region_is_rejected(tmp_path):
    cur = _current(tmp_path, OLD)
    with pytest.raises(ValueError, match="tile 契約に無い"):
        ret.pending_migration_regions(cur, [MIG], _tile_defs(tile_rel="frontend/tiles/chiba/tsunami/other.mbtiles"))
    with pytest.raises(ValueError, match="一致しない"):
        ret.pending_migration_regions(cur, [MIG], _tile_defs(region="tokyo"))


def test_registry_migrations_resolve_to_known_regions(tmp_path):
    from app.services.dataset_definition_service import get_definition_service
    migs = ret.load_migrations(ROOT / "data_lake/registry/tile_dispositions.json")
    cur = _current(tmp_path, *[m["rel_path"] for m in migs])
    assert ret.pending_migration_regions(cur, migs, get_definition_service().list_all()) == ["chiba", "kanagawa"]


def test_wrapper_adds_pending_regions_before_deploy():
    w = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    i_auto = w.index("--pending-migration-regions --current")
    assert w.index('log_step "seed staging from current"') < i_auto < w.index('for _region in "${REGIONS[@]}"; do\n    log_info "--- region')
    assert 'REGIONS+=("${_r}")' in w and "^[a-z][a-z0-9_]*$" in w


def test_nav_hazard_row_does_not_show_safe_for_unknown():
    """navigation.js _updateHazardRow（2026-10-11 OWNER 承認でこの分岐だけ変更）。"""
    import shutil
    import subprocess
    if not shutil.which("node"):
        pytest.skip("node が無い")
    script = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
const start = src.indexOf('function _updateHazardRow'); const end = src.indexOf('\n}\n', start) + 3;
const el = { className: '', innerHTML: '' };
const ctx = { document: { getElementById: () => el }, getHazardLabel: h => h }; vm.createContext(ctx);
vm.runInContext(src.slice(start, end) + ';this.f = _updateHazardRow;', ctx);
const out = {};
ctx.f(false, { tsunami: 'unknown', flood: 'outside' }); out.unknown = el.innerHTML;
ctx.f(false, { tsunami: 'outside', landslide: { status: 'outside' } }); out.outside = el.innerHTML;
ctx.f(true, { tsunami: 'inside' }); out.danger = el.innerHTML;
console.log(JSON.stringify(out));
"""
    r = subprocess.run(["node", "-e", script, str(ROOT / "frontend/js/navigation.js")],
                       capture_output=True, text=True, check=True)
    out = json.loads(r.stdout)
    assert "✅" not in out["unknown"] and "判定不可" in out["unknown"]
    assert out["outside"] == '<span class="mbc-hazard-safe">✅ 安全</span>'
    assert "mbc-hazard-danger" in out["danger"]


# ── C''. hazard.tsunami.targets の region を publish 対象へ自動で含める ─────────────

def _tsunami_defs(*regions):
    return [SimpleNamespace(dataset_id=f"{r.upper()}-TSUNAMI-001", region=r, layer_type="tsunami") for r in regions]


def test_target_region_missing_from_current_is_included(tmp_path):
    cur = _current(tmp_path, "backend/hazard/tsunami/tsunami_tokyo.geojson", "backend/hazard/tsunami/tsunami_kanagawa.geojson")
    defs = _tsunami_defs("tokyo", "kanagawa", "chiba")
    assert rts.missing_target_regions(cur, ["tokyo", "kanagawa", "chiba"], defs) == ["chiba"]
    _current(tmp_path, "backend/hazard/tsunami/tsunami_chiba.geojson")
    assert rts.missing_target_regions(cur, ["tokyo", "kanagawa", "chiba"], defs) == []  # 2 回目以降は追加しない


def test_unknown_target_region_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="1 件ではない"):
        rts.missing_target_regions(_current(tmp_path), ["osaka"], _tsunami_defs("tokyo"))
    with pytest.raises(ValueError):
        rts.missing_target_regions(_current(tmp_path), ["tokyo"], _tsunami_defs("tokyo", "tokyo"))


def test_wrapper_adds_missing_target_regions():
    w = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    i = w.index("--missing-target-regions --current")
    assert i < w.index('for _region in "${REGIONS[@]}"; do\n    log_info "--- region')
    assert 'log_error "hazard.tsunami.targets から publish region を決められない' in w


def test_production_targets_load_chiba_as_loader_target():
    from app.services import data_ops_service as dos
    props = dos._app_properties()
    assert dos.loader_contract("backend/hazard/tsunami/tsunami_chiba.geojson", props)["loader_target"] is True
    idx, unresolved = tc.resolve_unevaluated(REGISTRY, COVERAGE, ["tokyo", "kanagawa", "chiba"])
    assert idx == [] and unresolved == []  # 全 registry region を評価 → 未評価扱いは消える

"""
DEM-SOURCE-PROVENANCE（2026-10-12）: DEM の出典で確定できたこと・できないことを事実で固定し、
DEM から生成する PSEUDO を「派生 dataset」の一般契約（derived_from + generator）で照合する。

DEM（TOKYO-DEM-001）: elevation.tif（sha256 fdd8e3b3…）。data_processing/convert_dem.py が基盤地図情報 DEM の GML を
変換したもの（緯度経度を入れ替える geotransform がメッシュ 5339 で現 artifact と一致）。原本 zip が残っておらず、
基盤地図情報のダウンロードはログインが必要なため、公式原本との照合はできない → source は UNKNOWN のまま。
PSEUDO: generator を DEM fdd8e3b3… に対して pinned toolchain で実行すると canonical fffc6041… とバイト一致。
派生元・出力は VERIFIED だが、上流 DEM の source が未確認なので PSEUDO も WARNING（UPSTREAM_SOURCE_UNVERIFIED）。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetDefinition, DatasetState, DerivedInput  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from app.services import source_group as sg  # noqa: E402
from app.services import source_identity as si  # noqa: E402
from app.services.acquisition_history import SourceFile  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

DEM = "TOKYO-DEM-001"
PSEUDO = "TOKYO-PSEUDO-INLAND-FLOOD-001"
DEM_SHA = "fdd8e3b37b53cec7587e863ee37c4f7bf4aeaf41a4f1c279cead88356226a77f"  # 旧 artifact（convert_dem 由来の証跡）
PSEUDO_SHA = "fffc6041be74bdc53e0f89ce6b9735c4385bbcc1576b9cd3227837d468b5a33e"  # 旧 PSEUDO
# DEM-RUNTIME-REPAIR（2026-10-12）: 標準配置へ並べ替えた DEM と、そこから再生成した PSEUDO
NEW_DEM_SHA = "837bb7042c15c9b5ccefebaaaae55d269616fc0ae8acc850f190b246a18d31d7"
NEW_PSEUDO_SHA = "b2b378177a7f945fc045806bfe0bc46f9760478517d899a4dc47c0cf5cb17252"
LEGACY_DEM_FILE = ROOT / "data_lake/_backup/dem_superseded_20261012/elevation.tif"
DEM_FILE = ROOT / "data_lake/validated/tokyo/dem/elevation.tif"


def _d(did):
    return get_definition_service().get(did)


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


# ── 1, 2, 11. DEM の出典: 確定できないものは埋めない ────────────────────────────────

def test_01_11_dem_source_stays_unknown_with_facts_recorded():
    d = _d(DEM)
    assert d.source_provider is None and d.source_dataset_name is None  # 「GSI らしい」で埋めない
    assert not d.expected_source_files and not d.expected_source_sha256
    assert si.verify(d, [SourceFile(name="elevation.tif", sha256=DEM_SHA)]).status == si.SOURCE_UNKNOWN
    notes = " ".join(d.ingest_notes)
    for fact in (DEM_SHA, "convert_dem.py", "FGD_GMLSchema", "5339", "確定できないこと", "ログインが必要", "source を確定するには"):
        assert fact in notes, fact


def test_02_dem_artifact_sha_matches_registry():
    if not DEM_FILE.is_file():
        pytest.skip("DEM が無い環境")
    assert _sha(DEM_FILE) == NEW_DEM_SHA == _d(DEM).artifact_sha256
    assert [i.sha256 for i in _d(PSEUDO).derived_from] == [NEW_DEM_SHA]
    if LEGACY_DEM_FILE.is_file():
        assert _sha(LEGACY_DEM_FILE) == DEM_SHA  # 旧 artifact は削除せず保管


# ── 3-7. raster metadata と生成経路の署名 ────────────────────────────────────────

@pytest.fixture(scope="module")
def raster():
    rasterio = pytest.importorskip("rasterio")
    if not DEM_FILE.is_file():
        pytest.skip("DEM が無い環境")
    with rasterio.open(DEM_FILE) as src:
        yield src


def test_03_04_raster_metadata_and_crs(raster):
    assert raster.driver == "GTiff" and raster.count == 1 and raster.dtypes == ("float32",)
    assert (raster.width, raster.height) == (18000, 12000)
    assert raster.crs.to_epsg() == 6668 and raster.profile.get("compress", "").lower() == "lzw"


def test_05_06_resolution_and_bounds(raster):
    """修正版 DEM は標準配置（x = 経度 139°–140°、y = 緯度 35°20′–36°、画素 0.2″）。"""
    assert raster.res == pytest.approx((1 / 18000, 1 / 18000), rel=1e-6)
    b = raster.bounds
    assert (b.left, b.bottom, b.right, b.top) == pytest.approx((139.0, 35 + 1 / 3, 140.0, 36.0), abs=1e-6)
    assert raster.nodata == -9999.0


def test_07_legacy_geotransform_is_the_old_convert_dem_signature():
    """旧 convert_dem.py は lowerCorner/upperCorner（緯度 経度）を west/south に渡していた。メッシュ 5339 の
    5m 格子でその式を使うと、旧 artifact の geotransform と一致する（convert_dem 由来の証跡）。"""
    rasterio = pytest.importorskip("rasterio")
    if not LEGACY_DEM_FILE.is_file():
        pytest.skip("旧 DEM が無い環境")
    from rasterio.transform import from_bounds
    expected = from_bounds(35 + 1 / 3, 139.0, 36.0, 140.0, 18000, 12000)
    with rasterio.open(LEGACY_DEM_FILE) as src:
        assert tuple(src.transform)[:6] == pytest.approx(tuple(expected)[:6], abs=1e-7)
    src = (ROOT / "data_processing/convert_dem.py").read_text(encoding="utf-8")
    assert "FGD_GMLSchema" in src and "south, west = min(lower[0], upper[0]), min(lower[1], upper[1])" in src


# ── 8, 12. PSEUDO の派生元・生成器 ────────────────────────────────────────────────

def test_08_pseudo_dependency_and_output_sha():
    p = _d(PSEUDO)
    assert p.derived_from == [DerivedInput(dataset_id=DEM, artifact="validated", sha256=NEW_DEM_SHA)]
    assert p.generator["output_sha256"] == NEW_PSEUDO_SHA and sg.definition_problems(p) == []
    canon = ROOT / p.validated_storage_path / "pseudo_inland_flood.geojson"
    if canon.is_file():
        assert _sha(canon) == NEW_PSEUDO_SHA


def test_12_toolchain_record_matches_pinned_script():
    gen = _d(PSEUDO).generator
    sh = (ROOT / gen["script"]).read_text(encoding="utf-8")
    assert 'EXPECTED_GDAL="3.9.3"' in sh and "--platform linux/amd64" in sh
    for lib in ("rasterio==1.4.3", "shapely==2.1.2", "numpy==1.26.4", "pyproj==3.7.2", "affine==3.0.1"):
        assert lib in sh and lib.replace("==", " ") in gen["toolchain"], lib
    assert "linux/amd64" in gen["toolchain"] and "GDAL 3.9.3" in gen["toolchain"]
    assert (ROOT / gen["program"]).is_file()


# ── 9, 10. 派生 dataset の一般契約（Data Ops）──────────────────────────────────────

def _defn(did, **kw):
    base = dict(dataset_id=did, region="tokyo", category="hazard", display_name="t", description="t", hint_text="t",
                impact_scope="t", accepted_input_modes=["upload"], accepted_extensions=[".tif"], max_browser_upload_mb=0,
                requires_normalize=False, requires_validation=False, requires_deploy=True, requires_osrm_rebuild=False,
                raw_storage_path="x", runtime_path="none/x", layer_type=None)
    base.update(kw)
    return DatasetDefinition(**base)


@pytest.fixture
def world(tmp_path, monkeypatch):
    cache = drr.SourceShaCache(tmp_path / "cache.json")
    monkeypatch.setattr(drr, "get_source_sha_cache", lambda: cache)
    up_file = tmp_path / "up.tif"
    up_file.write_bytes(b"UPSTREAM")
    out_file = tmp_path / "out.geojson"
    out_file.write_bytes(b"OUTPUT")
    up = _defn("UP-001")
    states = {"UP-001": DatasetState(dataset_id="UP-001", current_validated_path=str(up_file)),
              "DER-001": DatasetState(dataset_id="DER-001", current_validated_path=str(out_file))}
    ss = Mock()
    ss.init_from_definition.side_effect = lambda d: states[d.dataset_id]

    def derived(input_sha=None, output_sha=None, upstream_status=dos.OK):
        der = _defn("DER-001", source_type="generated",
                    derived_from=[DerivedInput(dataset_id="UP-001", sha256=input_sha or hashlib.sha256(b"UPSTREAM").hexdigest())],
                    generator={"script": "gen.sh", "output_sha256": output_sha or hashlib.sha256(b"OUTPUT").hexdigest()})
        rows = {"UP-001": {"integrity": {"components": {"source": {"status": upstream_status}}}}}
        return der, dos.derived_section(der, states["DER-001"], rows, {"UP-001": up, "DER-001": der}, ss, allow_hash=True)
    return derived


def test_09_all_verified_is_ok(world):
    _, s = world()
    assert s["status"] == dos.OK and s["labels"] == ["DERIVED_FROM_VERIFIED"]
    assert s["inputs"][0]["dependency"] == dos.DERIVED_VERIFIED and s["output"]["status"] == dos.DERIVED_VERIFIED


def test_09b_upstream_unverified_keeps_warning(world):
    _, s = world(upstream_status=dos.WARNING)
    assert s["status"] == dos.WARNING and "UPSTREAM_SOURCE_UNVERIFIED" in s["labels"]


def test_09c_input_or_output_mismatch_is_error(world):
    _, s = world(input_sha="1" * 64)
    assert s["status"] == dos.ERROR and "DERIVED_INPUT_MISMATCH" in s["labels"]
    _, s = world(output_sha="2" * 64)
    assert s["status"] == dos.ERROR and "DERIVED_OUTPUT_MISMATCH" in s["labels"]


def test_09d_definition_problems():
    bad = _defn("D-1", derived_from=[DerivedInput(dataset_id="D-1", sha256="xyz")])
    probs = " ".join(sg.definition_problems(bad))
    assert "64 桁" in probs and "自分自身" in probs and "generator" in probs


def test_10_apply_replaces_external_source_requirements_without_hiding_upstream(world):
    der, s = world(upstream_status=dos.WARNING)
    row = {"acquisition": {"provenance_missing": ["取得元組織（source_provider）", "採用中の取得履歴（acquisition history）"],
                           "status": dos.WARNING},
           "integrity": {"components": {"source": {"status": dos.WARNING}, "runtime": {"status": dos.OK}},
                         "labels": [{"label": "SOURCE_PROVENANCE_MISSING", "severity": dos.WARNING},
                                    {"label": "ACQUISITION_HISTORY_MISSING", "severity": dos.WARNING}],
                         "overall": dos.WARNING}}
    dos._apply_derived(row, der, s)
    labels = [l["label"] for l in row["integrity"]["labels"]]
    assert "SOURCE_PROVENANCE_MISSING" not in labels and "UPSTREAM_SOURCE_UNVERIFIED" in labels
    assert row["acquisition"]["provenance_missing"] == [] and row["integrity"]["overall"] == dos.WARNING
    assert row["acquisition"]["derived"] is s


def test_10b_ui_shows_derived_rows_as_text():
    js = (ROOT / "operator/frontend-admin/data-ops.js").read_text(encoding="utf-8")
    assert '["派生元"' in js and '["生成器"' in js and "acq.derived" in js and "innerHTML" not in js


# ── 13, 14. 隔離 ───────────────────────────────────────────────────────────────

def test_13_14_no_real_admin_writes(tmp_path, world):
    real = ROOT / "data_lake/admin"
    before = {p: p.stat().st_mtime_ns for p in (real / "acquisitions").glob("*.json")} if real.is_dir() else {}
    cache_file = real / "cache" / "source_sha256.json"
    cache_before = cache_file.stat().st_mtime_ns if cache_file.exists() else None
    world()
    after = {p: p.stat().st_mtime_ns for p in (real / "acquisitions").glob("*.json")} if real.is_dir() else {}
    assert before == after
    assert (cache_file.stat().st_mtime_ns if cache_file.exists() else None) == cache_before

"""
normalize_river_flood.py — A31a/A31b GML パーサーの回帰テスト

fixture: tests/fixtures/flood_a31/（synthetic。実データではない）
  A31a-20-gml321-curve.xml          2024年度版相当（GML 3.2.1 名前空間）/ 通常 Curve
  A31a-20-gml32-curve.xml           2025年度版相当（GML 3.2 名前空間）/ 通常 Curve
  A31a-20-gml32-orientable-hole.xml OrientableCurve 経由の穴あきポリゴン、
                                    orientation="-"、2 本の Curve で構成される Ring
  A31a-20-gml32-unresolved.xml      参照先が存在しない curveMember（fail closed 確認用）

検証項目:
  1. GML 3.2.1 / 3.2 の両名前空間で同一ジオメトリ・同一プロパティを出力する
  2. Surface → curveMember → OrientableCurve → baseCurve → Curve を解決する
  3. exterior / interior を区別し coordinates = [exterior, hole1, hole2, ...] とする
     （穴を外周へ連結しない）
  4. orientation="-" は baseCurve の点順を反転する
  5. 複数 curveMember の Ring は接続点を重複させずに連結し、閉じる
  6. ジオメトリ未解決が 1 件でもあれば fail closed（件数・理由を明示）
  7. nested ZIP（bundle.zip ⊃ A31a ZIP ⊃ 20_/A31a-20-*.xml）を正規化でき、
     10_/30_/KS-META は除外される
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "normalize"))
import normalize_river_flood as nrf


FIXTURES = Path(__file__).parent / "fixtures" / "flood_a31"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _parse(xml: bytes, tmp_path: Path) -> list[dict]:
    out = tmp_path / "out.geojsonl"
    nrf._parse_a31_xml_stream(io.BytesIO(xml), out, "test")
    return [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]


def _square(lat0, lon0, lat1, lon1) -> list:
    """posList の順（lat0,lon0 → lat0,lon1 → lat1,lon1 → lat1,lon0 → 閉）を GeoJSON [lon,lat] で返す"""
    return [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]


# ── 1. GML 名前空間（2024: 3.2.1 / 2025: 3.2）──────────────────────────────

@pytest.mark.parametrize("name", ["A31a-20-gml321-curve.xml", "A31a-20-gml32-curve.xml"])
def test_plain_curve_resolved_for_both_gml_namespaces(name, tmp_path):
    feats = _parse(_fixture(name), tmp_path)
    assert len(feats) == 1
    assert feats[0]["geometry"] == {
        "type": "Polygon",
        "coordinates": [_square(35.0, 139.0, 35.1, 139.1)],
    }
    assert feats[0]["properties"] == {
        "water_depth": 2,
        "river_name": "境川",
        "river_number": "1300100001",
    }


def test_gml321_and_gml32_produce_identical_output(tmp_path):
    a = _parse(_fixture("A31a-20-gml321-curve.xml"), tmp_path)
    b = _parse(_fixture("A31a-20-gml32-curve.xml"), tmp_path)
    assert a == b


# ── 2-5. OrientableCurve / 穴 / orientation / 複数 curveMember ─────────────

@pytest.fixture
def hole_feats(tmp_path):
    feats = _parse(_fixture("A31a-20-gml32-orientable-hole.xml"), tmp_path)
    assert len(feats) == 2
    return feats


def test_orientable_curve_polygon_with_holes(hole_feats):
    geom = hole_feats[0]["geometry"]
    assert geom["type"] == "Polygon"
    exterior, hole1, hole2 = geom["coordinates"]  # 穴は外周へ連結されず別 ring
    assert exterior == _square(35.0, 139.0, 35.1, 139.1)
    assert hole1 == [[139.02, 35.02], [139.02, 35.04], [139.04, 35.04], [139.04, 35.02], [139.02, 35.02]]
    assert hole_feats[0]["properties"]["water_depth"] == 3


def test_orientation_minus_reverses_base_curve(hole_feats):
    hole2 = hole_feats[0]["geometry"]["coordinates"][2]
    base = [[139.06, 35.06], [139.08, 35.06], [139.08, 35.08], [139.06, 35.08], [139.06, 35.06]]
    assert hole2 == list(reversed(base))


def test_every_ring_is_closed(hole_feats):
    for feat in hole_feats:
        for ring in feat["geometry"]["coordinates"]:
            assert ring[0] == ring[-1]
            assert len(ring) >= 4


def test_ring_from_multiple_curve_members_is_joined_and_closed(hole_feats):
    geom = hole_feats[1]["geometry"]
    assert geom["coordinates"] == [[
        [139.2, 35.2], [139.3, 35.2], [139.3, 35.3], [139.2, 35.3], [139.2, 35.2],
    ]]
    assert hole_feats[1]["properties"]["water_depth"] == 6


def test_polygon_with_holes_is_valid_geometry(hole_feats):
    shapely_geometry = pytest.importorskip("shapely.geometry")
    poly = shapely_geometry.shape(hole_feats[0]["geometry"])
    assert poly.is_valid
    assert len(poly.interiors) == 2
    assert poly.area == pytest.approx(0.01 - 2 * 0.0004)


# ── 6. fail closed ────────────────────────────────────────────────────────

def test_unresolved_geometry_fails_closed_with_count_and_reason(tmp_path):
    with pytest.raises(ValueError) as exc_info:
        _parse(_fixture("A31a-20-gml32-unresolved.xml"), tmp_path)
    msg = str(exc_info.value)
    assert "解決できなかったフィーチャ: 1 件" in msg
    assert "参照先 Curve/OrientableCurve が見つからない: 1 件" in msg
    assert "fail closed" in msg


def test_unknown_gml_namespace_fails_closed(tmp_path):
    xml = _fixture("A31a-20-gml32-curve.xml").replace(
        b"http://schemas.opengis.net/gml/3.2", b"http://www.opengis.net/gml/3.2"
    )
    with pytest.raises(ValueError, match="bounds の参照先 Surface が見つからない: 1 件"):
        _parse(xml, tmp_path)


# ── 7. nested ZIP / normalize() ───────────────────────────────────────────

def _inner_zip(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _bundle(tmp_path: Path, entries_by_zip: dict) -> Path:
    bundle = tmp_path / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        for zip_name, entries in entries_by_zip.items():
            zf.writestr(zip_name, _inner_zip(entries))
    return bundle


def test_normalize_nested_zip_bundle(tmp_path):
    bundle = _bundle(tmp_path, {
        "A31a-25_13_10_GML.zip": {
            "20_test/A31a-20-25_13_1300100001_10.xml": _fixture("A31a-20-gml32-curve.xml"),
            # 10_/30_/KS-META は除外される（含まれていれば feature 数が増える）
            "10_test/A31a-10-25_13_1300100001_10.xml": _fixture("A31a-20-gml32-curve.xml"),
            "30_test/A31a-30-25_13_1300100001_10.xml": _fixture("A31a-20-gml32-curve.xml"),
            "KS-META-A31a-25_13_10.xml": b"<meta/>",
        },
        "A31a-25_13_20_GML.zip": {
            "20_test/A31a-20-25_13_8303030339_20.xml": _fixture("A31a-20-gml32-orientable-hole.xml"),
        },
    })
    out = tmp_path / "flood.geojson"
    assert nrf.normalize(bundle, out, "TOKYO-RIVER-001") == 0

    feats = json.loads(out.read_text(encoding="utf-8"))["features"]
    assert len(feats) == 3
    assert all(f["geometry"] and f["geometry"]["type"] == "Polygon" for f in feats)
    assert [len(f["geometry"]["coordinates"]) for f in feats] == [1, 3, 1]
    assert feats[0]["properties"] == {
        "hazard_type": "flood",
        "flood_rank": 2,
        "depth_text": "0.5m以上3m未満",
        "depth": 1.75,
        "river_name": "境川",
        "river_number": "1300100001",
        "dataset_id": "TOKYO-RIVER-001",
    }
    assert feats[2]["properties"]["flood_rank"] == 5  # waterDepth=6 → rank 5


def test_normalize_fails_closed_and_writes_no_output(tmp_path):
    bundle = _bundle(tmp_path, {
        "A31a-25_13_10_GML.zip": {
            "20_test/A31a-20-25_13_1300100001_10.xml": _fixture("A31a-20-gml32-curve.xml"),
            "20_test/A31a-20-25_13_1300100002_10.xml": _fixture("A31a-20-gml32-unresolved.xml"),
        },
    })
    out = tmp_path / "flood.geojson"
    assert nrf.normalize(bundle, out, "TOKYO-RIVER-001") == 1
    assert not out.exists()
    assert not out.with_suffix(".tmp.geojson").exists()

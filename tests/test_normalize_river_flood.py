"""
normalize_river_flood.py の回帰テスト

検証項目:
  1. DEPTH_TO_RANK: waterDepth 1-5 → rank 1-5、waterDepth 6 → rank 5
  2. normalize() 経由で waterDepth 1-6 が flood_rank / depth_text / depth に変換される
  3. water_depth（parse 直後の生値）から _extract_rank で rank を解決できる
  4. 不正 XML / Shift-JIS 宣言 / MaximumScale なしは fail closed
  5. _is_flood_gml の許可方式フィルタ（A31a-20-* / A31b-20-* のみ）

2026-10 整理: commit d13b818（ogr2ogr → iterparse 置換）で削除された
_iter_gml_features / _parse_xml を参照していた陳腐化テストを整理した。
削除したテストと代替テスト（tests/test_normalize_river_flood_a31_gml.py）:
  - test_maximum_scale_yields_feature        → test_plain_curve_resolved_for_both_gml_namespaces
  - test_properties_river_name               → test_plain_curve_resolved_for_both_gml_namespaces
  - test_no_underscore_prefix_href_also_works → test_plain_curve_resolved_for_both_gml_namespaces
  - test_underscore_prefix_href（"#_cvN" を "cvN" に読み替える前提。"_cvN" は実在する
    gml:OrientableCurve の id であり仕様に反するため削除）
                                             → test_orientable_curve_polygon_with_holes,
                                               test_unresolved_geometry_fails_closed_with_count_and_reason
  - test_old_a31a_element_assumption_absent（削除済み関数のソース文字列検査）
                                             → test_plain_curve_resolved_for_both_gml_namespaces
  - test_utf8_parses_ok                      → 全 fixture（UTF-8）を使う a31_gml テスト群
  - test_flood_rank_added / test_depth_text_added → test_normalize_nested_zip_bundle
移植: test_properties_flood_rank / test_water_depth_fallback / test_invalid_xml_raises_value_error /
      test_no_maximum_scale_prints_warn / test_shift_jis_declaration_raises_value_error（本ファイル）
"""

import io
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

# テスト対象モジュールを直接 import
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts" / "normalize"))
import normalize_river_flood as nrf

FIXTURES = Path(__file__).parent / "fixtures" / "flood_a31"


def _gml_with_depth(water_depth: int) -> bytes:
    xml = (FIXTURES / "A31a-20-gml32-curve.xml").read_bytes()
    return xml.replace(b"<ksj:waterDepth>2</ksj:waterDepth>",
                       f"<ksj:waterDepth>{water_depth}</ksj:waterDepth>".encode())


def _normalize_xml(tmp_path: Path, xml: bytes):
    """XML を A31a ZIP に入れて normalize() を実行し、(exit code, features) を返す。"""
    src = tmp_path / "A31a-25_13_10_GML.zip"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("20_test/A31a-20-25_13_1300100001_10.xml", xml)
    out = tmp_path / "flood.geojson"
    rc = nrf.normalize(src, out, "TOKYO-RIVER-001")
    feats = json.loads(out.read_text(encoding="utf-8"))["features"] if out.exists() else []
    return rc, feats


# ── テスト ────────────────────────────────────────────────────────────────────

class TestDepthToRank:
    """DEPTH_TO_RANK マッピングの確認"""

    def test_depth_1_to_5_maps_to_same_rank(self):
        for d in range(1, 6):
            assert nrf.DEPTH_TO_RANK[d] == d

    def test_depth_6_maps_to_rank_5(self):
        assert nrf.DEPTH_TO_RANK[6] == 5

    def test_no_other_keys(self):
        assert set(nrf.DEPTH_TO_RANK.keys()) == {1, 2, 3, 4, 5, 6}


class TestNormalizeProperties:
    """normalize() が付与する標準プロパティ"""

    @pytest.mark.parametrize("depth,expected_rank", [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 5)])
    def test_properties_flood_rank(self, tmp_path, depth, expected_rank):
        """waterDepth 1-6 → flood_rank / depth_text / depth（移植: 旧 test_properties_flood_rank）"""
        rc, feats = _normalize_xml(tmp_path, _gml_with_depth(depth))
        assert rc == 0 and len(feats) == 1
        props = feats[0]["properties"]
        assert props["flood_rank"] == expected_rank
        assert props["depth_text"] == nrf.RANK_TABLE[expected_rank][0]
        assert props["depth"] == nrf.RANK_TABLE[expected_rank][1]

    def test_water_depth_fallback(self, tmp_path):
        """parse 直後の water_depth → _extract_rank で flood_rank を解決できる
        （移植: 旧版は parse 直後に flood_rank がある前提だったが、現行は normalize() で付与する）"""
        out = tmp_path / "out.geojsonl"
        nrf._parse_a31_xml_stream(io.BytesIO(_gml_with_depth(4)), out, "test")
        props = json.loads(out.read_text(encoding="utf-8").splitlines()[0])["properties"]
        assert props["water_depth"] == 4
        assert "flood_rank" not in props
        assert nrf._extract_rank(props) == 4

    def test_extract_rank_from_flood_rank_key(self):
        """_extract_rank: flood_rank キーから直接解決する"""
        assert nrf._extract_rank({"flood_rank": 3}) == 3

    def test_extract_rank_unknown_returns_zero(self):
        """_extract_rank: 未知値は 0 を返す"""
        assert nrf._extract_rank({"flood_rank": 99}) == 0
        assert nrf._extract_rank({}) == 0


class TestFailClosedInputs:
    """不正入力は fail closed（出力を作らない）"""

    def test_invalid_xml_fails_closed(self, tmp_path):
        """壊れた XML: parser は ParseError、normalize() は exit 1 で出力なし
        （移植: 旧 test_invalid_xml_raises_value_error）"""
        with pytest.raises(ET.ParseError):
            nrf._parse_a31_xml_stream(io.BytesIO(b"<broken xml"), tmp_path / "o.jsonl", "test")
        rc, feats = _normalize_xml(tmp_path, b"<broken xml")
        assert rc == 1 and feats == []
        assert not (tmp_path / "flood.geojson").exists()

    def test_no_maximum_scale_fails_closed(self, tmp_path):
        """MaximumScale 要素がない XML → 0 件で ValueError（移植: 旧 test_no_maximum_scale_prints_warn）"""
        empty = b'<?xml version="1.0" encoding="UTF-8"?><root xmlns:gml="http://schemas.opengis.net/gml/3.2"/>'
        with pytest.raises(ValueError, match="0 件"):
            nrf._parse_a31_xml_stream(io.BytesIO(empty), tmp_path / "o.jsonl", "no-features-test")

    def test_shift_jis_declaration_raises_value_error(self, tmp_path):
        """Shift-JIS 宣言の XML は ValueError（移植: 旧 TestParseXml の同名テスト）"""
        sjis_xml = '<?xml version="1.0" encoding="Shift_JIS"?><r/>'.encode("shift-jis")
        with pytest.raises(ValueError):
            nrf._parse_a31_xml_stream(io.BytesIO(sjis_xml), tmp_path / "o.jsonl", "test-sjis")


class TestFloodGmlFilter:
    """_is_flood_gml() の許可方式フィルタのテスト

    A31a-20-* / A31b-20-* のみ True を返し、
    KS-META-*.xml や 10_/30_/41_/42_ カテゴリはすべて False になること。
    """

    def test_a31a_20_allowed(self):
        """A31a-20- は処理対象"""
        assert nrf._is_flood_gml("A31a-20-24_13_1300020001_10.xml")

    def test_a31b_20_allowed(self):
        """A31b-20- も処理対象"""
        assert nrf._is_flood_gml("A31b-20-24_13_1300020001_10.xml")

    def test_a31a_10_rejected(self):
        """A31a-10- はスキップ"""
        assert not nrf._is_flood_gml("A31a-10-24_13_1300020001_10.xml")

    def test_a31a_30_rejected(self):
        assert not nrf._is_flood_gml("A31a-30-24_13_1300020001_10.xml")

    def test_a31a_41_rejected(self):
        assert not nrf._is_flood_gml("A31a-41-24_13_1300020001_10.xml")

    def test_a31a_42_rejected(self):
        assert not nrf._is_flood_gml("A31a-42-24_13_1300020001_10.xml")

    def test_ks_meta_rejected(self):
        """KS-META-*.xml はスキップ（メタデータ）"""
        assert not nrf._is_flood_gml("KS-META-A31a-24_13_10.xml")

    def test_unknown_xml_rejected(self):
        """未知の XML はスキップ"""
        assert not nrf._is_flood_gml("flood_data.xml")
        assert not nrf._is_flood_gml("some_other.xml")

    def test_garbled_dir_with_a31a_20_allowed(self):
        """文字化けしたディレクトリ配下の A31a-20- ファイルは処理対象"""
        garbled_path = "A31a-24_13_10_GML/20_\x91\x6D\x92\xE8/A31a-20-24_13_1300020001_10.xml"
        assert nrf._is_flood_gml(garbled_path)

    def test_garbled_dir_with_ks_meta_rejected(self):
        """文字化けしたディレクトリ配下の KS-META-*.xml もスキップ"""
        garbled_path = "A31a-24_13_10_GML/\x91\x6D\x92\xE8/KS-META-A31a-24_13_10.xml"
        assert not nrf._is_flood_gml(garbled_path)

    def test_case_insensitive(self):
        """大文字・小文字を区別しない"""
        assert nrf._is_flood_gml("a31a-20-24_13_1300020001_10.xml")
        assert nrf._is_flood_gml("A31B-20-24_13_1300020001_10.xml")

"""
normalize_river_flood.py の回帰テスト

検証項目:
  1. MaximumScale 構造の GML から正しくフィーチャを抽出できる
  2. A31a / A31b 要素を直接探す旧ロジックが無いこと
  3. _ プレフィックスミスマッチ（gml:id="cvN" / href="#_cvN"）を吸収できる
  4. 不正 XML → ValueError (WARN してスキップ、トレースバックなし)
  5. Shift-JIS encoding 宣言の XML → ValueError (WARN してスキップ)
  6. DEPTH_TO_RANK: waterDepth 1-5 → rank 1-5、waterDepth 6 → rank 5
  7. 出力プロパティに hazard_type / dataset_id / flood_rank / depth_text / depth が含まれる
"""

import io
import sys
import textwrap
import pytest

# テスト対象モジュールを直接 import
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent / "scripts" / "normalize"))
import normalize_river_flood as nrf


# ── ヘルパー ─────────────────────────────────────────────────────────────────

def _minimal_gml(water_depth: int, curve_id_in_href: str = "_cv0") -> bytes:
    """
    最小限の A31a スタイル GML バイト列を生成する。

    構造:
      gml:Curve gml:id="cv0"
      gml:Surface gml:id="sf0" (curveMember href="#_cv0")
      ksj:MaximumScale
        ksj:bounds xlink:href="#sf0"
        ksj:waterDepth = water_depth
        ksj:riverName  = "テスト川"
    """
    xml = f"""\
<?xml version="1.0" encoding="UTF-8"?>
<root xmlns:gml="http://www.opengis.net/gml/3.2"
      xmlns:ksj="http://nlftp.mlit.go.jp/ksj/schemas/ksj-app"
      xmlns:xlink="http://www.w3.org/1999/xlink">
  <gml:Curve gml:id="cv0">
    <gml:segments>
      <gml:LineStringSegment>
        <gml:posList>35.0 139.0 35.0 139.1 35.1 139.1 35.1 139.0 35.0 139.0</gml:posList>
      </gml:LineStringSegment>
    </gml:segments>
  </gml:Curve>
  <gml:Surface gml:id="sf0">
    <gml:patches>
      <gml:PolygonPatch>
        <gml:exterior>
          <gml:Ring>
            <gml:curveMember xlink:href="#{curve_id_in_href}"/>
          </gml:Ring>
        </gml:exterior>
      </gml:PolygonPatch>
    </gml:patches>
  </gml:Surface>
  <ksj:MaximumScale>
    <ksj:bounds xlink:href="#sf0"/>
    <ksj:waterDepth>{water_depth}</ksj:waterDepth>
    <ksj:riverName>テスト川</ksj:riverName>
    <ksj:riverNumber>1234567890</ksj:riverNumber>
  </ksj:MaximumScale>
</root>
""".encode("utf-8")
    return xml


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


class TestIterGmlFeatures:
    """_iter_gml_features の正常系テスト"""

    def test_maximum_scale_yields_feature(self):
        """MaximumScale 要素からフィーチャが得られる"""
        feats = list(nrf._iter_gml_features(_minimal_gml(3), "test"))
        assert len(feats) == 1
        feat = feats[0]
        assert feat["type"] == "Feature"
        assert "geometry" in feat
        assert feat["geometry"] is not None

    def test_properties_flood_rank(self):
        """waterDepth → flood_rank 変換が正しい"""
        for depth, expected_rank in [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 5)]:
            feats = list(nrf._iter_gml_features(_minimal_gml(depth), f"depth={depth}"))
            assert len(feats) == 1
            assert feats[0]["properties"]["flood_rank"] == expected_rank, f"depth={depth}"

    def test_properties_river_name(self):
        """river_name / river_number が含まれる"""
        feats = list(nrf._iter_gml_features(_minimal_gml(2), "test"))
        props = feats[0]["properties"]
        assert props["river_name"] == "テスト川"
        assert props["river_number"] == "1234567890"

    def test_underscore_prefix_href(self):
        """gml:id='cv0' / href='#_cv0' のミスマッチを吸収できる"""
        # _minimal_gml のデフォルト curve_id_in_href は "_cv0"
        feats = list(nrf._iter_gml_features(_minimal_gml(1, curve_id_in_href="_cv0"), "test"))
        assert len(feats) == 1
        assert feats[0]["geometry"] is not None

    def test_no_underscore_prefix_href_also_works(self):
        """href='#cv0'（_ なし）でも動作する"""
        feats = list(nrf._iter_gml_features(_minimal_gml(1, curve_id_in_href="cv0"), "test"))
        assert len(feats) == 1

    def test_invalid_xml_raises_value_error(self):
        """壊れた XML → ValueError（トレースバックなし・WARN のみ）"""
        with pytest.raises(ValueError, match="GML/XML パースエラー"):
            list(nrf._iter_gml_features(b"<broken xml", "test"))

    def test_no_maximum_scale_prints_warn(self, capsys):
        """MaximumScale 要素がない XML → フィーチャ 0 件 + WARN"""
        empty_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
<root xmlns:gml="http://www.opengis.net/gml/3.2"/>"""
        feats = list(nrf._iter_gml_features(empty_xml, "no-features-test"))
        assert feats == []
        captured = capsys.readouterr()
        assert "MaximumScale" in captured.err
        assert "WARN" in captured.err

    def test_old_a31a_element_assumption_absent(self):
        """旧ロジックの A31a / A31b 要素への直接参照が存在しないこと（ソース検査）"""
        import inspect
        source = inspect.getsource(nrf._iter_gml_features)
        # 旧コードは _local(elem.tag) in ("A31a", "A31b") というロジックを使っていた
        # ドキュメント文字列内での言及は許容するが、ロジックとしての比較は存在しないはず
        assert '("A31a", "A31b")' not in source
        assert '!= "A31a"' not in source
        assert '== "A31a"' not in source


class TestParseXml:
    """_parse_xml のエンコーディング処理テスト"""

    def test_utf8_parses_ok(self):
        root = nrf._parse_xml(b'<?xml version="1.0" encoding="UTF-8"?><r/>', "test")
        assert root.tag == "r"

    def test_shift_jis_declaration_raises_value_error(self):
        """Shift-JIS 宣言の XML は ValueError（WARN してスキップ扱い）"""
        sjis_xml = '<?xml version="1.0" encoding="Shift_JIS"?><r/>'.encode("shift-jis")
        with pytest.raises(ValueError, match="GML/XML パースエラー"):
            nrf._parse_xml(sjis_xml, "test-sjis")


class TestNormalizeProperties:
    """GML フィーチャから normalize() が付与する標準プロパティのテスト

    normalize() は iter_features() を内部で呼ぶため、
    ここでは _iter_gml_features の出力を直接 normalize のロジックに通して検証する。
    """

    def _gml_to_features(self, water_depth: int, dataset_id: str = "DS-001") -> list[dict]:
        """最小 GML から _iter_gml_features を実行し、normalize が付与するプロパティを構築する"""
        raw_feats = list(nrf._iter_gml_features(_minimal_gml(water_depth), "test"))
        result = []
        for feat in raw_feats:
            props = feat.get("properties") or {}
            rank = nrf._extract_rank(props)
            rank_info = nrf.RANK_TABLE.get(rank)
            out_props: dict = {
                "hazard_type": "flood",
                "flood_rank": rank,
                "depth_text": rank_info[0] if rank_info else "",
            }
            if rank_info:
                out_props["depth"] = rank_info[1]
            for extra in ("river_name", "river_number"):
                if props.get(extra):
                    out_props[extra] = props[extra]
            if dataset_id:
                out_props["dataset_id"] = dataset_id
            result.append({**feat, "properties": out_props})
        return result

    def test_flood_rank_added(self):
        """flood_rank が正しく付与される"""
        feats = self._gml_to_features(3, "TOKYO-RIVER-001")
        assert len(feats) == 1
        props = feats[0]["properties"]
        assert props["flood_rank"] == 3
        assert props["hazard_type"] == "flood"
        assert props["dataset_id"] == "TOKYO-RIVER-001"

    def test_depth_text_added(self):
        """depth_text / depth が RANK_TABLE から付与される"""
        feats = self._gml_to_features(2, "DS-001")
        props = feats[0]["properties"]
        assert props["depth_text"] == "0.5m以上3m未満"
        assert props["depth"] == 1.75

    def test_water_depth_fallback(self):
        """GML 直出力の water_depth → _extract_rank で flood_rank を解決できる"""
        # _iter_gml_features が出力する props には water_depth も含まれる
        raw_feats = list(nrf._iter_gml_features(_minimal_gml(4), "test"))
        assert len(raw_feats) == 1
        # water_depth=4 → DEPTH_TO_RANK → flood_rank=4
        assert raw_feats[0]["properties"]["water_depth"] == 4
        assert raw_feats[0]["properties"]["flood_rank"] == 4
        rank = nrf._extract_rank(raw_feats[0]["properties"])
        assert rank == 4

    def test_extract_rank_from_flood_rank_key(self):
        """_extract_rank: flood_rank キーから直接解決する"""
        assert nrf._extract_rank({"flood_rank": 3}) == 3

    def test_extract_rank_unknown_returns_zero(self):
        """_extract_rank: 未知値は 0 を返す"""
        assert nrf._extract_rank({"flood_rank": 99}) == 0
        assert nrf._extract_rank({}) == 0

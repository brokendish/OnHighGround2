"""
安全性クリティカル回帰テスト — OnHighGround2

対象:
  A. DEM NoData (-9999.0) が現在地標高として通り抜けないこと
  B. 津波ターゲット設定がフロントエンド表示範囲と一致していること
  C. 沿岸サンプル点の判定漏れ現状記録テスト（データ・設定・期待挙動の明示）

再現事実（2026-03-31 動的テスト）:
  - 35.6316, 139.8085 で current_location.elevation = -9999.0 が返された
  - 推奨候補の elevation_gain = 10005.81（「現在地より10006m高い」）
  - hazard.tsunami.targets=tokyo のみで chiba 沿岸が outside 判定
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import numpy as np

# backend を sys.path に追加
BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from elevation_service import ElevationService


# ── A. DEM NoData 回帰テスト ──────────────────────────────────────────────────

class TestDEMNoData(unittest.TestCase):
    """DEM NoData センチネル値 (-9999.0) が漏れないことを確認する"""

    def _make_service_with_nodata_value(self, nodata_config, grid_value):
        """
        dataset.nodata を nodata_config に設定し、
        ラスタの全ピクセルを grid_value にした ElevationService を返すモック
        """
        svc = ElevationService.__new__(ElevationService)
        svc.dem_path = Path("/nonexistent.tif")

        mock_ds = MagicMock()
        mock_ds.nodata = nodata_config
        mock_ds.bounds = MagicMock(left=139.0, right=140.5, bottom=35.0, top=36.5)

        # CRS 変換をスキップ（EPSG:4326 のまま）
        mock_ds.crs = None

        # transform_matrix: rowcol が (0, 0) を返せるよう設定
        import rasterio.transform as rt
        mock_ds.transform = rt.from_bounds(139.0, 35.0, 140.5, 36.5, 100, 100)

        svc.dataset = mock_ds
        svc.elevation_data = np.full((100, 100), grid_value, dtype=np.float32)
        svc.transform_matrix = mock_ds.transform

        return svc

    # ── _is_nodata 単体 ──

    def test_is_nodata_catches_negative_9999_exact(self):
        """dataset.nodata=None のとき -9999.0 ちょうどを NoData と判定する"""
        svc = ElevationService.__new__(ElevationService)
        svc.dataset = MagicMock()
        svc.dataset.nodata = None
        self.assertTrue(svc._is_nodata(-9999.0),
                        "-9999.0 は NoData として弾かれるべき")

    def test_is_nodata_catches_more_negative_than_9999(self):
        """dataset.nodata=None のとき -9999.0 未満も NoData と判定する"""
        svc = ElevationService.__new__(ElevationService)
        svc.dataset = MagicMock()
        svc.dataset.nodata = None
        self.assertTrue(svc._is_nodata(-10000.0))
        self.assertTrue(svc._is_nodata(-9999.5))

    def test_is_nodata_does_not_reject_valid_elevation(self):
        """正常な標高値（0m, -5m など）は NoData と判定しない"""
        svc = ElevationService.__new__(ElevationService)
        svc.dataset = MagicMock()
        svc.dataset.nodata = None
        self.assertFalse(svc._is_nodata(0.0))
        self.assertFalse(svc._is_nodata(5.0))
        self.assertFalse(svc._is_nodata(-5.0))   # 海面下だが有効な地形値

    def test_is_nodata_catches_nan(self):
        svc = ElevationService.__new__(ElevationService)
        svc.dataset = MagicMock()
        svc.dataset.nodata = None
        self.assertTrue(svc._is_nodata(float('nan')))

    def test_is_nodata_with_dataset_nodata_set_to_9999(self):
        """-9999.0 は dataset.nodata が設定されていても弾かれる（二重ガード）"""
        svc = ElevationService.__new__(ElevationService)
        svc.dataset = MagicMock()
        svc.dataset.nodata = -9999.0
        self.assertTrue(svc._is_nodata(-9999.0))

    # ── get_elevation / get_elevation_interpolated 経由 ──

    def test_get_elevation_returns_none_for_nodata_grid(self):
        """ラスタ全面が -9999.0 の場合 get_elevation は None を返す"""
        svc = self._make_service_with_nodata_value(nodata_config=None, grid_value=-9999.0)
        result = svc.get_elevation(35.63, 139.81)
        self.assertIsNone(result,
            f"NoData 点の標高は None であるべき（got {result}）")

    def test_get_elevation_interpolated_returns_none_for_nodata_grid(self):
        """補間メソッドでも -9999.0 は None になる"""
        svc = self._make_service_with_nodata_value(nodata_config=None, grid_value=-9999.0)
        result = svc.get_elevation_interpolated(35.63, 139.81)
        self.assertIsNone(result,
            f"補間でも NoData 点は None であるべき（got {result}）")

    def test_find_evacuation_returns_empty_when_current_elev_is_nodata(self):
        """現在地標高が NoData なら find_evacuation_destinations は [] を返す"""
        svc = self._make_service_with_nodata_value(nodata_config=None, grid_value=-9999.0)
        result = svc.find_evacuation_destinations(35.63, 139.81)
        self.assertEqual(result, [],
            "現在地 NoData のとき避難候補リストは空であるべき")

    def test_elevation_gain_cannot_be_absurdly_large(self):
        """
        正常データ(5m)から NoData(-9999.0)を引いた elevation_gain が
        出力候補に含まれないことを確認する回帰テスト。
        再現値: elevation_gain = 10005.81 (= destination_elev - (-9999.0))
        """
        svc = ElevationService.__new__(ElevationService)
        svc.dataset = MagicMock()
        svc.dataset.nodata = None
        svc.dataset.crs = None

        import rasterio.transform as rt
        svc.transform_matrix = rt.from_bounds(139.0, 35.0, 140.5, 36.5, 100, 100)
        svc.dataset.transform = svc.transform_matrix
        svc.dataset.bounds = MagicMock(left=139.0, right=140.5, bottom=35.0, top=36.5)

        # ラスタの大部分を 5m とし、現在地付近だけ -9999.0 に
        data = np.full((100, 100), 5.0, dtype=np.float32)
        # 中心付近（現在地）を NoData にする
        data[45:55, 45:55] = -9999.0
        svc.elevation_data = data

        result = svc.find_evacuation_destinations(35.75, 139.75, min_elevation_gain=0.1)
        for cand in result:
            self.assertLess(
                abs(cand["elevation_gain"]), 1000,
                f"elevation_gain が異常に大きい: {cand['elevation_gain']} — NoData 起因の false safe の可能性"
            )


# ── B. 津波ターゲット整合性テスト ────────────────────────────────────────────

class TestTsunamiTargetConsistency(unittest.TestCase):
    """
    app.properties の hazard.tsunami.targets がフロントエンド表示範囲と一致しているか確認

    フロントエンドが表示する津波ファイル（frontend/hazard/）:
      - tsunami_tokyo.geojson
      - tsunami_kanagawa.geojson
      - tsunami_chiba.geojson

    バックエンドの設定が tokyo のみなら kanagawa/chiba の沿岸点が outside になり、
    その点が hazard_safe=true と判定されてしまう（false safe）。
    """

    PROPS_PATH = Path(__file__).resolve().parents[1] / "backend" / "app.properties"
    FRONTEND_TSUNAMI_DIR = Path(__file__).resolve().parents[1] / "frontend" / "hazard"

    def _load_props(self):
        props = {}
        with self.PROPS_PATH.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                props[k.strip()] = v.strip()
        return props

    def _frontend_tsunami_prefectures(self):
        """frontend/hazard/ に存在する tsunami_*.geojson から prefecture 名を抽出"""
        return {
            p.stem.replace("tsunami_", "")
            for p in self.FRONTEND_TSUNAMI_DIR.glob("tsunami_*.geojson")
        }

    def test_backend_targets_cover_all_frontend_tsunami_prefectures(self):
        """
        backend の hazard.tsunami.targets が
        frontend の tsunami_*.geojson に対応する全 prefecture を含むこと。
        含まない場合は false safe（フロントで危険表示 ≠ バックエンド判定）になる。
        """
        props = self._load_props()
        raw_targets = props.get("hazard.tsunami.targets", "tokyo")
        backend_targets = {t.strip() for t in raw_targets.split(",") if t.strip()}

        frontend_prefectures = self._frontend_tsunami_prefectures()

        missing = frontend_prefectures - backend_targets
        self.assertEqual(
            missing, set(),
            f"backend の tsunami.targets に含まれていない prefecture: {missing}\n"
            f"  backend targets : {backend_targets}\n"
            f"  frontend display: {frontend_prefectures}\n"
            "フロントで表示しているのに backend が判定しない → false safe になります。"
        )

    def test_backend_tsunami_targets_is_not_tokyo_only(self):
        """
        tokyo のみが設定されている場合は失敗させる（最低限のガード）。
        kanagawa / chiba の沿岸が outside 判定になり false safe になる。
        """
        props = self._load_props()
        raw_targets = props.get("hazard.tsunami.targets", "tokyo")
        targets = {t.strip() for t in raw_targets.split(",") if t.strip()}
        self.assertIn("kanagawa", targets,
                      "kanagawa が tsunami.targets に含まれていません（false safe）")
        self.assertIn("chiba", targets,
                      "chiba が tsunami.targets に含まれていません（false safe）")


# ── C. 沿岸サンプル点 判定漏れ現状記録テスト ──────────────────────────────────

class TestCoastalSamplePoints(unittest.TestCase):
    """
    動的テストで確認した沿岸サンプル点の現状を記録するテスト。

    以下のサンプル点は 2026-03-31 時点で flood/storm_surge/tsunami すべて outside。
    これが「データが存在しない安全地点」なのか「データカバレッジ外」なのかは
    現時点では不明。このテストは現状を明示するもので、即断で仕様変更はしない。

    期待挙動:
      - 設定が tokyo,kanagawa,chiba の場合、少なくとも津波については
        kanagawa/chiba データが評価対象になること
      - outside = "危険でない" ではなく "データなし or カバレッジ外" と解釈すること
      - hazard_safe=true を返すには全レイヤーで outside or safe の確認が必要
    """

    # 動的テストで確認したサンプル点（2026-03-31）
    COASTAL_SAMPLE_POINTS = [
        {"name": "ariake_north",  "lat": 35.6415, "lon": 139.7905,
         "note": "有明北部、全レイヤー outside"},
        {"name": "shin_kiba",     "lat": 35.6468, "lon": 139.8269,
         "note": "新木場付近、全レイヤー outside"},
        {"name": "kasai_rinkai",  "lat": 35.6427, "lon": 139.8588,
         "note": "葛西臨海公園付近、全レイヤー outside"},
        {"name": "haneda_edge",   "lat": 35.5494, "lon": 139.7847,
         "note": "羽田沖付近、全レイヤー outside"},
    ]

    def test_coastal_sample_points_are_documented(self):
        """
        沿岸サンプル点が記録されており、座標が合理的な範囲内にあること。
        このテストが失敗した場合はサンプル点の定義が壊れていることを意味する。
        """
        for pt in self.COASTAL_SAMPLE_POINTS:
            self.assertIn("lat", pt)
            self.assertIn("lon", pt)
            # 東京湾周辺の合理的な範囲チェック
            self.assertGreater(pt["lat"], 35.0)
            self.assertLess(pt["lat"], 36.0)
            self.assertGreater(pt["lon"], 139.0)
            self.assertLess(pt["lon"], 140.5)

    def test_coastal_outside_means_data_gap_not_safe(self):
        """
        outside 判定は「安全」ではなく「評価不能」であることを
        derive_hazard_safe の仕様として確認する。

        HazardService が利用可能な場合のみ実行する（データ依存のため skip 可）。
        """
        try:
            from hazard_service import derive_hazard_safe
        except ImportError:
            self.skipTest("hazard_service が import できません")

        # 全レイヤー outside の場合の hazard_safe を確認
        # derive_hazard_safe({}) or derive_hazard_safe(all outside) が
        # True（safe）を返すかどうかを検証
        # 仕様: データなし(None) → hazard_safe=None (unknown) であること
        all_outside_assessment = {}  # データなし = 空
        result = derive_hazard_safe(all_outside_assessment)
        # None (unknown) か False (unsafe) であること。True (safe) を返してはいけない。
        # ※ 現在の実装が True を返す場合はバグとして記録する
        if result is True:
            # 現状を記録するが失敗させる
            self.fail(
                "derive_hazard_safe({}) が True を返しています。"
                "データなしを 'safe' と解釈するのは false safe です。"
                "None（判定不能）を返すように修正してください。"
            )


# ── D. tsunami degraded / missing target 回帰テスト ─────────────────────────

class TestTsunamiDegradedCoverage(unittest.TestCase):
    """
    設定した tsunami targets の一部が未ロードの場合に
    hazard_safe=True が返らないことを検証する。

    問題経緯（2026-04-01 再レビュー）:
      - app.properties: hazard.tsunami.targets=tokyo,kanagawa,chiba
      - runtime に chiba ファイルが存在しない場合、main.py は skip して続行
      - assess_candidate() は「ロード済みの tokyo/kanagawa のみで評価」
      - chiba 沿岸の点は任意の tsunami polygon に入らない → outside
      - derive_hazard_safe → True（false safe）
    修正後の期待:
      - 設定 targets に未ロードがあれば assess_candidate() が tsunami="unknown" を返す
      - derive_hazard_safe → None（unknown）
    """

    def _make_service(self, loaded_targets, expected_targets):
        """
        loaded_targets: 実際にロードするターゲット名リスト（ファイルは存在しない想定のためスキップ）
        expected_targets: set_expected_tsunami_sources に渡すリスト
        """
        from hazard_service import HazardService
        svc = HazardService()
        svc.set_expected_tsunami_sources(expected_targets)
        # 実ファイルなしでソースのみ登録（内部 _sources を直接操作）
        svc._sources["tsunami"] = [f"tsunami_{t}" for t in loaded_targets]
        # polygon は空（チェックは not loaded → outside にはならないが、
        # 今回は coverage チェックのみを確認するので空でよい）
        return svc

    def test_missing_chiba_gives_unknown_in_assess_candidate(self):
        """chiba が未ロードのとき assess_candidate で tsunami=unknown になる"""
        from hazard_service import HazardService, derive_hazard_safe
        svc = HazardService()
        # tokyo, kanagawa のみロード済み（chiba 欠落）
        svc._sources["tsunami"] = ["tsunami_tokyo", "tsunami_kanagawa"]
        svc._polygons["tsunami"] = []  # polygon は空（判定のため）
        svc.set_expected_tsunami_sources(["tokyo", "kanagawa", "chiba"])

        missing = svc.get_missing_tsunami_sources()
        self.assertEqual(missing, ["tsunami_chiba"],
                         "欠落リストに chiba が含まれるべき")

        self.assertFalse(svc.has_full_tsunami_coverage(),
                         "chiba 欠落なので full coverage は False であるべき")

    def test_all_targets_loaded_gives_full_coverage(self):
        """全ターゲットがロード済みなら has_full_tsunami_coverage=True"""
        from hazard_service import HazardService
        svc = HazardService()
        svc._sources["tsunami"] = ["tsunami_tokyo", "tsunami_kanagawa", "tsunami_chiba"]
        svc.set_expected_tsunami_sources(["tokyo", "kanagawa", "chiba"])
        self.assertTrue(svc.has_full_tsunami_coverage())
        self.assertEqual(svc.get_missing_tsunami_sources(), [])

    def test_no_expected_targets_means_no_degraded_check(self):
        """set_expected_tsunami_sources 未呼出なら degraded チェックなし（デフォルト安全）"""
        from hazard_service import HazardService
        svc = HazardService()
        # 期待値を設定しない
        self.assertTrue(svc.has_full_tsunami_coverage(),
                        "期待値未設定のとき full_coverage は True（チェックしない）")
        self.assertEqual(svc.get_missing_tsunami_sources(), [])

    def test_assess_candidate_injects_unknown_when_coverage_incomplete(self):
        """
        coverage 不完全なとき assess_candidate() が tsunami='unknown' を返す。
        derive_hazard_safe がこれを受けて None（unknown）を返すことを確認。

        モック設定:
          - tsunami の _sources に tokyo のみ登録（chiba 欠落）
          - _polygons["tsunami"] に ダミーポリゴン（遠い場所）を入れて
            loaded_hazard_types() にリストされるようにする
          - coverage 不完全 → assess_candidate が tsunami="unknown" に上書き
        """
        from hazard_service import HazardService, derive_hazard_safe

        # ダミーポリゴン（北海道沖・テスト点 35.64 から遠い → outside 判定）
        dummy_poly = {"bbox": (43.0, 141.0, 44.0, 142.0), "coords": [
            [141.0, 43.0], [142.0, 43.0], [142.0, 44.0], [141.0, 44.0], [141.0, 43.0]
        ]}

        svc = HazardService()
        svc._polygons["flood"]   = [dummy_poly]
        svc._sources["flood"]    = ["tokyo_flood"]
        svc._polygons["tsunami"] = [dummy_poly]   # loaded_hazard_types に含まれるよう非空
        svc._sources["tsunami"]  = ["tsunami_tokyo"]  # tokyo のみロード済み
        svc.set_expected_tsunami_sources(["tokyo", "kanagawa", "chiba"])  # chiba 欠落

        assessment = svc.assess_candidate(35.6415, 139.7905)  # 有明北部

        self.assertIn("tsunami", assessment,
                      "assess_candidate は tsunami キーを含むべき")
        self.assertEqual(assessment["tsunami"], "unknown",
                         "coverage 不完全のとき tsunami は 'unknown' であるべき")

        hazard_safe = derive_hazard_safe(assessment)
        self.assertIsNone(hazard_safe,
                          "tsunami=unknown を含む場合 derive_hazard_safe は None(unknown) であるべき（True は false safe）")

    def test_assess_candidate_tsunami_outside_when_full_coverage(self):
        """
        full coverage のときは tsunami の通常判定が行われる（outside → True の可能性がある）。
        ここでは flood も tsunami も outside で hazard_safe=True が返ることを確認。

        モック設定:
          - 全3ターゲット(tokyo/kanagawa/chiba)をロード済みとしてマーク
          - ダミーポリゴン（遠い場所）→ テスト点は outside
          - coverage は full → unknown への上書きなし → derive_hazard_safe=True
        """
        from hazard_service import HazardService, derive_hazard_safe

        dummy_poly = {"bbox": (43.0, 141.0, 44.0, 142.0), "coords": [
            [141.0, 43.0], [142.0, 43.0], [142.0, 44.0], [141.0, 44.0], [141.0, 43.0]
        ]}

        svc = HazardService()
        svc._polygons["flood"]   = [dummy_poly]
        svc._sources["flood"]    = ["tokyo_flood"]
        svc._polygons["tsunami"] = [dummy_poly]
        svc._sources["tsunami"]  = ["tsunami_tokyo", "tsunami_kanagawa", "tsunami_chiba"]
        svc.set_expected_tsunami_sources(["tokyo", "kanagawa", "chiba"])  # 全件ロード済み

        assessment = svc.assess_candidate(35.6415, 139.7905)
        # coverage は full なので unknown への上書きなし → 通常判定（ダミーポリゴンは外 → outside）
        self.assertEqual(assessment.get("tsunami"), "outside",
                         "full coverage + ダミーポリゴン外 → outside であるべき")

        hazard_safe = derive_hazard_safe(assessment)
        self.assertTrue(hazard_safe,
                        "full coverage で全 outside なら hazard_safe=True が正しい")


# ── E. フロントエンド buildHazardReasonBlock ロジック回帰テスト（ソースコード検証）──

class TestBuildHazardReasonBlockSourceGuards(unittest.TestCase):
    """
    buildHazardReasonBlock() のソースコードが安全ロジックを含むことを検証する。
    JS 実行環境がないため、ソースコードの文字列検索で保証する。

    問題経緯（2026-04-01 再レビュー）:
      - assessment に unknown が含まれてもサイレントに SAFE_HAZARD_TEXT を表示していた
      - inside が0件かつ unknown が1件以上のとき、UNKNOWN_HAZARD_TEXT を返すべき
    """

    SOURCE_PATH = Path(__file__).resolve().parents[1] / "frontend" / "js" / "ui.js"

    @classmethod
    def setUpClass(cls):
        cls.SOURCE = cls.SOURCE_PATH.read_text(encoding="utf-8")

    def test_unknown_hazard_text_constant_is_defined(self):
        """UNKNOWN_HAZARD_TEXT 定数が定義されていること"""
        self.assertIn("UNKNOWN_HAZARD_TEXT", self.SOURCE,
                      "UNKNOWN_HAZARD_TEXT 定数が未定義です")

    def test_build_hazard_reason_block_checks_unknown_status(self):
        """buildHazardReasonBlock が 'unknown' を検出していること"""
        self.assertIn("value === 'unknown'", self.SOURCE,
                      "buildHazardReasonBlock が string の 'unknown' を検出していません")
        self.assertIn("status === 'unknown'", self.SOURCE,
                      "buildHazardReasonBlock が object の status='unknown' を検出していません")

    def test_build_hazard_reason_block_has_unknown_branch(self):
        """unknown があった場合に UNKNOWN_HAZARD_TEXT を返す分岐が存在すること"""
        self.assertIn("hasUnknown", self.SOURCE,
                      "hasUnknown フラグが存在しません（unknown 検出フラグが必要）")
        # UNKNOWN_HAZARD_TEXT を返す分岐
        self.assertIn("is-unknown", self.SOURCE,
                      "is-unknown CSS クラスが使われていません")

    def test_safe_text_not_returned_when_unknown_present(self):
        """
        SAFE_HAZARD_TEXT を返す分岐が 'hasUnknown' チェックの後にあること。
        （hasUnknown=true のとき SAFE_HAZARD_TEXT に到達しないことをコード順で保証する）
        """
        safe_idx    = self.SOURCE.find("return `<div class=\"hazard-reason-block\"><span class=\"hazard-reason-item is-safe\">")
        unknown_idx = self.SOURCE.find("return `<div class=\"hazard-reason-block\"><span class=\"hazard-reason-item is-unknown\">")
        # unknown return が safe return より前にある（unknown を先に弾く）
        self.assertNotEqual(unknown_idx, -1, "is-unknown return 文が見つかりません")
        self.assertNotEqual(safe_idx,    -1, "is-safe return 文が見つかりません")
        self.assertLess(unknown_idx, safe_idx,
                        "is-unknown の return が is-safe の return より後にあります — "
                        "unknown のとき safe が表示される false safe の可能性があります")

    def test_null_assessment_returns_unknown_not_safe(self):
        """
        assessment が null/undefined のとき SAFE ではなく UNKNOWN を返すこと。
        ソース上で最初の return が is-unknown であることを確認。
        """
        block_start = self.SOURCE.find("function buildHazardReasonBlock(")
        self.assertNotEqual(block_start, -1)
        block_src = self.SOURCE[block_start:block_start + 300]
        self.assertIn("is-unknown", block_src,
                      "buildHazardReasonBlock の冒頭（null チェック）で is-unknown を返していません")
        self.assertNotIn("is-safe", block_src,
                         "buildHazardReasonBlock の冒頭（null チェック）で is-safe を返しています — false safe")


if __name__ == "__main__":
    unittest.main(verbosity=2)

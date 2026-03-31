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


if __name__ == "__main__":
    unittest.main(verbosity=2)

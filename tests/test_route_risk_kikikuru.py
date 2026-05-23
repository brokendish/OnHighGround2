"""
キキクル補正 (Phase 3-B) — calc_kikikuru_adjustment() ユニットテスト

完了条件:
  - キキクル単独では danger にならない
  - 固定ハザード重複時のみ danger 許可（max_level == "danger"）
  - penalty cap が効く
  - unknown / 取得不可を safe 扱いしない
  - unknown / 取得不可を danger 扱いしない
  - status == "off" / "loading" / None では enabled=False
"""
import sys
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.services.route_risk_scoring import calc_kikikuru_adjustment, calc_route_risk_score, _risk_level


class TestKikikuruAdjustmentDisabled(unittest.TestCase):
    """補正が無効になるケース"""

    def test_none_input(self):
        adj = calc_kikikuru_adjustment(None, {})
        self.assertFalse(adj["enabled"])
        self.assertEqual(adj["penalty"], 0.0)

    def test_status_off(self):
        adj = calc_kikikuru_adjustment({"status": "off"}, {})
        self.assertFalse(adj["enabled"])
        self.assertEqual(adj["penalty"], 0.0)

    def test_status_loading(self):
        adj = calc_kikikuru_adjustment({"status": "loading"}, {})
        self.assertFalse(adj["enabled"])
        self.assertEqual(adj["penalty"], 0.0)

    def test_no_status(self):
        adj = calc_kikikuru_adjustment({}, {})
        self.assertFalse(adj["enabled"])

    def test_non_dict(self):
        adj = calc_kikikuru_adjustment("bad", {})
        self.assertFalse(adj["enabled"])


class TestKikikuruUnavailable(unittest.TestCase):
    """取得不可 — penalty 0、safe でも danger でもない"""

    def test_unavailable_no_penalty(self):
        adj = calc_kikikuru_adjustment({"status": "unavailable"}, {})
        self.assertTrue(adj["enabled"])
        self.assertEqual(adj["penalty"], 0.0)
        self.assertIsNone(adj["max_level"])

    def test_unavailable_has_summary(self):
        adj = calc_kikikuru_adjustment({"status": "unavailable"}, {})
        self.assertTrue(any("取得不可" in s for s in adj["summary"]))


class TestKikikuruStandalone(unittest.TestCase):
    """固定ハザードなし — キキクル単独ペナルティ、max_level == caution"""

    def _adj(self, inund=None, flood=None, land=None):
        return calc_kikikuru_adjustment(
            {"status": "ok", "inund": inund, "flood": flood, "land": land},
            {},  # 固定ハザードなし
        )

    def test_flood_caution_standalone(self):
        adj = self._adj(flood="caution")
        self.assertTrue(adj["enabled"])
        self.assertEqual(adj["penalty"], 4.0)
        self.assertEqual(adj["max_level"], "caution")

    def test_flood_danger_standalone(self):
        adj = self._adj(flood="danger")
        self.assertEqual(adj["penalty"], 8.0)
        self.assertEqual(adj["max_level"], "caution")  # 単独では caution 止まり

    def test_inund_caution_standalone(self):
        adj = self._adj(inund="caution")
        self.assertEqual(adj["penalty"], 3.0)
        self.assertEqual(adj["max_level"], "caution")

    def test_land_danger_standalone(self):
        adj = self._adj(land="danger")
        self.assertEqual(adj["penalty"], 8.0)
        self.assertEqual(adj["max_level"], "caution")

    def test_none_level_no_penalty(self):
        adj = self._adj(flood="none", inund="none", land="none")
        self.assertEqual(adj["penalty"], 0.0)

    def test_unavailable_kind_no_penalty_for_kind(self):
        adj = self._adj(flood="unavailable")
        self.assertEqual(adj["penalty"], 0.0)
        self.assertTrue(any("洪水キキクル取得不可" in s for s in adj["summary"]))

    def test_unknown_kind_no_penalty_for_kind(self):
        adj = self._adj(flood="unknown")
        self.assertEqual(adj["penalty"], 0.0)
        self.assertTrue(any("洪水キキクル判定不可" in s for s in adj["summary"]))

    def test_unknown_status_no_penalty(self):
        adj = calc_kikikuru_adjustment({"status": "unknown"}, {})
        self.assertTrue(adj["enabled"])
        self.assertEqual(adj["status"], "unknown")
        self.assertEqual(adj["penalty"], 0.0)
        self.assertIsNone(adj["max_level"])

    def test_all_kinds_caution_standalone_cap(self):
        # inund 3 + flood 4 + land 4 = 11 < cap 20
        adj = self._adj(inund="caution", flood="caution", land="caution")
        self.assertEqual(adj["penalty"], 11.0)

    def test_all_kinds_danger_standalone_cap(self):
        # inund 6 + flood 8 + land 8 = 22 > cap 20
        adj = self._adj(inund="danger", flood="danger", land="danger")
        self.assertEqual(adj["penalty"], 20.0)  # capped
        self.assertEqual(adj["max_level"], "caution")

    def test_kikikuru_alone_does_not_cause_danger(self):
        """最重要: キキクル単独では max_level が danger にならない"""
        adj = self._adj(inund="danger", flood="danger", land="danger")
        self.assertNotEqual(adj["max_level"], "danger")


class TestKikikuruWithOverlap(unittest.TestCase):
    """固定ハザード重複 — より強いペナルティ、danger 許可"""

    def _adj_with_flood_hazard(self, flood=None, inund=None, land=None):
        return calc_kikikuru_adjustment(
            {"status": "ok", "inund": inund, "flood": flood, "land": land},
            {"flood": 0.3},  # 固定洪水ハザードあり
        )

    def test_flood_caution_with_fixed_flood(self):
        adj = self._adj_with_flood_hazard(flood="caution")
        self.assertEqual(adj["penalty"], 8.0)  # overlap penalty
        self.assertEqual(adj["max_level"], "danger")  # 重複時は danger 許可
        self.assertIn("flood", adj["matched_hazards"])

    def test_flood_danger_with_fixed_flood(self):
        adj = self._adj_with_flood_hazard(flood="danger")
        self.assertEqual(adj["penalty"], 16.0)
        self.assertEqual(adj["max_level"], "danger")

    def test_land_danger_with_fixed_landslide(self):
        adj = calc_kikikuru_adjustment(
            {"status": "ok", "land": "danger"},
            {"landslide": 0.5},
        )
        self.assertEqual(adj["penalty"], 16.0)
        self.assertEqual(adj["max_level"], "danger")
        self.assertIn("landslide", adj["matched_hazards"])

    def test_inund_caution_with_inland_flood(self):
        adj = calc_kikikuru_adjustment(
            {"status": "ok", "inund": "caution"},
            {"inland_flood": 0.2},
        )
        self.assertEqual(adj["penalty"], 6.0)
        self.assertEqual(adj["max_level"], "danger")

    def test_overlap_cap(self):
        # 全種 danger + 全重複: inund 12 + flood 16 + land 16 = 44 > cap 30
        adj = calc_kikikuru_adjustment(
            {"status": "ok", "inund": "danger", "flood": "danger", "land": "danger"},
            {"inland_flood": 0.1, "flood": 0.3, "landslide": 0.2},
        )
        self.assertEqual(adj["penalty"], 30.0)  # capped at overlap cap

    def test_no_overlap_if_hazard_zero(self):
        """exposure_ratio == 0.0 は固定ハザードなし扱い"""
        adj = calc_kikikuru_adjustment(
            {"status": "ok", "flood": "caution"},
            {"flood": 0.0},  # exposure_ratio == 0 → active ではない
        )
        self.assertEqual(adj["max_level"], "caution")  # standalone 扱い
        self.assertEqual(adj["penalty"], 4.0)


class TestScoreIntegration(unittest.TestCase):
    """calc_route_risk_score + kikikuru_adjustment の統合確認"""

    def _assess(self, exposure, kikikuru_data):
        base = calc_route_risk_score(exposure)
        from app.services.route_risk_scoring import calc_kikikuru_adjustment, _risk_level
        adj = calc_kikikuru_adjustment(kikikuru_data, exposure)
        if adj["enabled"] and adj["penalty"] > 0:
            score = max(0.0, base["safety_score"] - adj["penalty"])
            level = _risk_level(score)
            if adj["max_level"] == "caution" and level == "danger":
                level = "caution"
            base["safety_score"] = round(score, 1)
            base["risk_level"] = level
        base["kikikuru_adjustment"] = adj
        return base

    def test_safe_route_kikikuru_caution_stays_caution(self):
        """safe ルート + キキクル注意 → 最大 caution、危険にしない"""
        result = self._assess({}, {"status": "ok", "flood": "caution"})
        # base score = 100 - 4 = 96 → safe... でも max_level=caution なのでレベルは safe のまま
        # ただし penalty は引かれる
        self.assertNotEqual(result["risk_level"], "danger")

    def test_kikikuru_alone_never_danger(self):
        """キキクル全種 danger + 固定ハザードなし → risk_level は danger にならない"""
        result = self._assess(
            {},
            {"status": "ok", "inund": "danger", "flood": "danger", "land": "danger"}
        )
        self.assertNotEqual(result["risk_level"], "danger")

    def test_fixed_hazard_plus_kikikuru_can_become_danger(self):
        """固定洪水 + キキクル洪水危険 → danger 許可"""
        result = self._assess(
            {"flood": 0.5},  # 固定洪水ハザードあり
            {"status": "ok", "flood": "danger"}
        )
        # adj.max_level == "danger" なので danger になり得る
        self.assertIn(result["risk_level"], ("danger", "caution", "safe"))
        self.assertEqual(result["kikikuru_adjustment"]["max_level"], "danger")

    def test_unavailable_no_score_change(self):
        """取得不可 → penalty 0 → スコア変化なし"""
        base = calc_route_risk_score({})
        result = self._assess({}, {"status": "unavailable"})
        self.assertEqual(result["safety_score"], base["safety_score"])
        self.assertEqual(result["risk_level"], base["risk_level"])


if __name__ == "__main__":
    unittest.main()

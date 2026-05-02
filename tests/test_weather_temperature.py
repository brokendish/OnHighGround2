"""気温異常値対策のユニットテスト。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import pytest
from services.amedas_client import normalize_temperature, is_valid_temperature, extract_temperature
from services.weather_service import _select_temperature


# ── normalize_temperature ──────────────────────────────────────────────────────

class TestNormalizeTemperature:
    def test_normal_value(self):
        assert normalize_temperature(22.5) == 22.5

    def test_10x_value_117(self):
        assert normalize_temperature(117) == pytest.approx(11.7)

    def test_10x_value_195(self):
        assert normalize_temperature(195) == pytest.approx(19.5)

    def test_boundary_60_stays(self):
        # 60 は > 60 でないのでそのまま
        assert normalize_temperature(60) == 60.0

    def test_boundary_61_divides(self):
        assert normalize_temperature(61) == pytest.approx(6.1)

    def test_negative_stays(self):
        assert normalize_temperature(-5.0) == -5.0


# ── is_valid_temperature ───────────────────────────────────────────────────────

class TestIsValidTemperature:
    def test_valid_common(self):
        assert is_valid_temperature(22.5) is True

    def test_valid_lower_bound(self):
        assert is_valid_temperature(-20.0) is True

    def test_valid_upper_bound(self):
        assert is_valid_temperature(45.0) is True

    def test_too_cold(self):
        assert is_valid_temperature(-20.1) is False

    def test_too_hot(self):
        assert is_valid_temperature(45.1) is False

    def test_none(self):
        assert is_valid_temperature(None) is False

    def test_minus_9999(self):
        assert is_valid_temperature(-9999) is False


# ── extract_temperature ────────────────────────────────────────────────────────

class TestExtractTemperature:
    def test_normal_value(self):
        obs = {"temp": [22.5, 0]}
        assert extract_temperature(obs) == pytest.approx(22.5)

    def test_10x_value(self):
        # 117 → 11.7℃
        obs = {"temp": [117, 0]}
        assert extract_temperature(obs) == pytest.approx(11.7)

    def test_missing_key(self):
        assert extract_temperature({}) is None

    def test_out_of_range_discarded(self):
        obs = {"temp": [-9999, 0]}
        assert extract_temperature(obs) is None

    def test_extreme_heat_discarded(self):
        # 460 → 46.0℃（> 45）→ 破棄
        obs = {"temp": [460, 0]}
        assert extract_temperature(obs) is None


# ── _select_temperature ────────────────────────────────────────────────────────

def _make_stations(*entries):
    """(station_id, distance_km, temp) のリストから stations + map_data を作る。"""
    stations = []
    map_data = {}
    for sid, dist_km, temp in entries:
        stations.append({"station_id": sid, "distance_m": dist_km * 1000})
        if temp is not None:
            map_data[sid] = {"temp": [temp, 0], "wind": [3.0, 0]}
    return stations, map_data


class TestSelectTemperature:
    def test_single_station_near(self):
        stations, map_data = _make_stations(("S1", 5.0, 22.5))
        temp, conf = _select_temperature(stations, map_data)
        assert temp == pytest.approx(22.5)
        assert conf == "high"

    def test_single_station_medium(self):
        stations, map_data = _make_stations(("S1", 15.0, 18.0))
        temp, conf = _select_temperature(stations, map_data)
        assert temp == pytest.approx(18.0)
        assert conf == "medium"

    def test_single_station_far(self):
        stations, map_data = _make_stations(("S1", 25.0, 16.0))
        temp, conf = _select_temperature(stations, map_data)
        assert temp == pytest.approx(16.0)
        assert conf == "low"

    def test_two_stations_small_diff(self):
        # 差 < 5℃ → 近い方をそのまま採用
        stations, map_data = _make_stations(("S1", 5.0, 20.0), ("S2", 8.0, 22.0))
        temp, conf = _select_temperature(stations, map_data)
        assert temp == pytest.approx(20.0)
        assert conf == "high"

    def test_two_stations_large_diff_averages(self):
        # 差 >= 5℃ → 平均
        stations, map_data = _make_stations(("S1", 5.0, 11.7), ("S2", 8.0, 19.5))
        temp, conf = _select_temperature(stations, map_data)
        assert temp == pytest.approx(15.6)
        # high + averaged → medium
        assert conf == "medium"

    def test_large_diff_already_medium_stays(self):
        # primary が 15km（medium）で差が大きい場合は medium のまま
        stations, map_data = _make_stations(("S1", 15.0, 11.7), ("S2", 18.0, 19.5))
        temp, conf = _select_temperature(stations, map_data)
        assert temp == pytest.approx(15.6)
        assert conf == "medium"

    def test_no_valid_stations_returns_none(self):
        stations, map_data = _make_stations(("S1", 5.0, None))
        temp, conf = _select_temperature(stations, map_data)
        assert temp is None
        assert conf == "low"

    def test_10x_encoded_value(self):
        # JMA から 117 が来た場合 → 11.7℃ に正規化されて採用される
        stations, map_data = _make_stations(("S1", 5.0, 117))
        temp, conf = _select_temperature(stations, map_data)
        assert temp == pytest.approx(11.7)
        assert conf == "high"

    def test_distance_priority_5km_over_15km(self):
        stations, map_data = _make_stations(("S1", 5.0, 20.0), ("S2", 15.0, 20.5))
        temp, conf = _select_temperature(stations, map_data)
        assert temp == pytest.approx(20.0)
        assert conf == "high"

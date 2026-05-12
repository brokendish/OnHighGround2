"""
test_tide_service_jma.py — tide_service (JMA runtime) のユニットテスト
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import tide_service as svc
from app.services.tide_parser import TideFormatError, parse_line, iter_hourly, find_extremes


# ── tide_parser ───────────────────────────────────────────────────────────────

def _jma_line(ymd="260101", values=None, station="TK"):
    values = values or [" 85"] * 24
    return "".join(values) + ymd[:2] + f"{int(ymd[2:4]):2d}" + f"{int(ymd[4:6]):2d}" + station


def test_parse_line_valid():
    line = _jma_line("260101", [" 85"] * 24)
    day, values = parse_line(line)
    assert day is not None
    assert day.year == 2026
    assert day.month == 1
    assert day.day == 1
    assert len(values) == 24
    assert values[0] == 85


def test_parse_line_missing_value():
    line = _jma_line("260101", ["999"] * 24)
    _day, values = parse_line(line)
    assert all(v is None for v in values)


def test_parse_line_mixed():
    line = _jma_line("260101", [" 85"] * 12 + ["999"] * 12)
    _day, values = parse_line(line)
    assert values[0] == 85
    assert values[12] is None


def test_parse_line_strict_rejects_broken_fixed_length():
    line = " 85" * 23
    try:
        parse_line(line, strict=True)
    except TideFormatError as exc:
        assert "fixed length short" in str(exc)
    else:
        raise AssertionError("expected TideFormatError")


def test_iter_hourly_logs_and_skips_invalid_data_line(caplog):
    text = "\n".join([
        " 85" * 23,
        _jma_line("260102", [" 90"] * 24),
    ])
    records = iter_hourly("TK", text, log_errors=True)
    assert len(records) == 24
    assert "invalid tide format station=TK line=1" in caplog.text


def test_iter_hourly_count():
    lines = [_jma_line("260101", [" 85"] * 24), _jma_line("260102", [" 90"] * 24)]
    text = "\n".join(lines)
    records = iter_hourly("TK", text)
    assert len(records) == 48
    assert records[0]["station"] == "TK"
    assert records[0]["datetime"].startswith("2026-01-01T00:00:00")
    assert records[0]["tide_cm"] == 85


def test_find_extremes_structure():
    lines = []
    for d in range(1, 4):
        lines.append(_jma_line(f"2601{d:02d}", [" 85"] * 24))
    records = iter_hourly("TK", "\n".join(lines))
    extremes = find_extremes("TK", records)
    assert len(extremes) == 3
    for ex in extremes:
        assert "station" in ex
        assert "date" in ex
        assert "high_tides" in ex
        assert "low_tides" in ex


# ── tide_service ──────────────────────────────────────────────────────────────

def test_get_tide_info_no_data_returns_unavailable(monkeypatch):
    """runtime データがない場合は available=False を返す。"""
    monkeypatch.setattr(svc, "_stations", [])
    monkeypatch.setattr(svc, "_hourly_index", {})
    monkeypatch.setattr(svc, "_extremes_index", {})
    monkeypatch.setattr(svc, "_loaded_year", None)
    monkeypatch.setattr(svc, "_load_runtime", lambda: None)

    result = svc.get_tide_info(35.65, 139.77)
    assert result is not None
    assert result["available"] is False
    assert result["source"] == "jma"


def test_get_tide_info_with_data(monkeypatch):
    """runtime に東京データが存在する場合のレスポンス形状を確認する。"""
    from datetime import datetime, timezone, timedelta

    now = datetime.now(svc.JST)
    tomorrow = (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)

    hourly = [
        {
            "station": "TK",
            "datetime": now.replace(minute=0, second=0, microsecond=0).isoformat(),
            "tide_cm": 132,
        }
    ]
    extremes = [
        {
            "station": "TK",
            "date": tomorrow.strftime("%Y-%m-%d"),
            "high_tides": [{"time": tomorrow.isoformat(), "tide_cm": 165}],
            "low_tides": [],
        }
    ]

    monkeypatch.setattr(svc, "_stations", [
        {"station_code": "TK", "name": "東京", "lat": 35.65, "lon": 139.77},
    ])
    monkeypatch.setattr(svc, "_hourly_index", {"TK": hourly})
    monkeypatch.setattr(svc, "_extremes_index", {"TK": extremes})
    monkeypatch.setattr(svc, "_loaded_year", "2026")

    result = svc.get_tide_info(35.6812, 139.7671)
    assert result["available"] is True
    assert result["source"] == "jma"
    assert result["station"]["id"] == "TK"
    assert result["station"]["name"] == "東京"
    assert isinstance(result["station"]["distance_km"], float)

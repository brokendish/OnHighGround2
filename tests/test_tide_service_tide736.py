import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import tide_service as svc


def test_tide736_event_uses_unix_milliseconds():
    event = svc._event_from_tide736_item(
        {"time": "09:38", "unix": 1778373480000, "cm": 134.9},
        "high",
    )

    assert event["type"] == "high"
    assert event["time"].isoformat() == "2026-05-10T09:38:00+09:00"
    assert event["height_cm"] == 134.9


def test_get_tide_info_returns_reference_shape(monkeypatch):
    now = svc.datetime.now(svc.JST)
    station = {
        "id": "tokyo",
        "name": "東京港",
        "lat": 35.63,
        "lon": 139.79,
        "tide736": {"pc": "13", "hc": "2"},
    }

    monkeypatch.setattr(svc, "_STATIONS", [station])
    monkeypatch.setattr(
        svc,
        "_build_tide736_events",
        lambda station, now: [
            {"type": "high", "time": now + timedelta(minutes=80), "height_cm": 134.9},
            {"type": "low", "time": now + timedelta(minutes=220), "height_cm": 61.8},
        ],
    )

    body = svc.get_tide_info(35.6812, 139.7671)

    assert body["available"] is True
    assert body["source"] == "tide736"
    assert body["is_reference"] is True
    assert body["station"]["name"] == "東京港"
    assert body["station"]["distance_km"] >= 0
    assert body["next_high_tide"]["remaining_minutes"] >= 0
    assert body["next_low_tide"]["time"].endswith("+09:00")


def test_get_tide_info_without_events_is_unavailable(monkeypatch):
    monkeypatch.setattr(
        svc,
        "_STATIONS",
        [{"id": "tokyo", "name": "東京港", "lat": 35.63, "lon": 139.79}],
    )
    monkeypatch.setattr(svc, "_build_tide736_events", lambda station, now: [])

    body = svc.get_tide_info(35.6812, 139.7671)

    assert body == {"available": False, "source": "tide736", "is_reference": True}

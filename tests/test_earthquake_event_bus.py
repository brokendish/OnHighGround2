"""
test_earthquake_event_bus.py — 地震SSEイベントバスの回帰テスト
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.earthquake_event_bus import EarthquakeEventBus


def _run(coro):
    return asyncio.run(coro)


def test_publish_delivers_to_multiple_subscribers():
    async def _inner():
        bus = EarthquakeEventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        event = {"event_id": "dev-001", "epicenter_name": "東京湾"}

        bus.publish(event)

        got1 = await asyncio.wait_for(q1.get(), timeout=1.0)
        got2 = await asyncio.wait_for(q2.get(), timeout=1.0)
        return got1, got2

    got1, got2 = _run(_inner())
    assert got1["event_id"] == "dev-001"
    assert got2["event_id"] == "dev-001"


def test_unsubscribe_stops_delivery():
    bus = EarthquakeEventBus()
    q1 = bus.subscribe()
    q2 = bus.subscribe()

    bus.unsubscribe(q1)
    bus.publish({"event_id": "dev-002"})

    assert q1.empty()
    assert not q2.empty()


def test_recent_events_are_capped_at_100():
    bus = EarthquakeEventBus()

    for i in range(105):
        bus.publish({"event_id": f"dev-{i:03d}"})

    recent = bus.recent_events()
    assert len(recent) == 100
    assert recent[0]["event_id"] == "dev-005"
    assert recent[-1]["event_id"] == "dev-104"

"""
test_earthquake_realtime_service.py — P2P WS → event bus の重複排除テスト
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import earthquake_realtime_service as realtime_module
from app.services.earthquake_realtime_service import EarthquakeRealtimeService


class FakeBus:
    def __init__(self):
        self.events = []

    def publish(self, event):
        self.events.append(event)


class FakeP2PClient:
    instances = []

    def __init__(self, on_event, on_state_change=None):
        self.on_event = on_event
        self.on_state_change = on_state_change
        self.started = False
        self.stopped = False
        FakeP2PClient.instances.append(self)

    def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True


def test_start_publishes_unique_events_and_skips_duplicates(monkeypatch, caplog):
    bus = FakeBus()
    FakeP2PClient.instances = []
    monkeypatch.setattr(realtime_module, "get_earthquake_event_bus", lambda: bus)
    monkeypatch.setattr(realtime_module, "P2PWebSocketClient", FakeP2PClient)

    service = EarthquakeRealtimeService()

    with caplog.at_level(logging.INFO):
        service.start()
        client = FakeP2PClient.instances[0]
        client.on_event({"event_id": "eq-001", "epicenter_name": "東京湾", "magnitude": 4.8})
        client.on_event({"event_id": "eq-001", "epicenter_name": "東京湾", "magnitude": 4.9})
        client.on_event({"event_id": "eq-002", "epicenter_name": "相模湾", "magnitude": 3.1})

    assert client.started is True
    assert [event["event_id"] for event in bus.events] == ["eq-001", "eq-002"]
    assert "earthquake realtime event published: event_id=eq-001" in caplog.text
    assert "earthquake realtime duplicate skipped: event_id=eq-001" in caplog.text


def test_state_change_publishes_sse_status_event(monkeypatch):
    bus = FakeBus()
    FakeP2PClient.instances = []
    monkeypatch.setattr(realtime_module, "get_earthquake_event_bus", lambda: bus)
    monkeypatch.setattr(realtime_module, "P2PWebSocketClient", FakeP2PClient)

    service = EarthquakeRealtimeService()
    service.start()
    client = FakeP2PClient.instances[0]

    client.on_state_change({
        "state": "reconnecting",
        "source": "p2p_ws",
        "next_retry_seconds": 5,
    })

    assert bus.events == [{
        "_sse_type": "status",
        "state": "reconnecting",
        "source": "p2p_ws",
        "next_retry_seconds": 5,
    }]


def test_stop_closes_client(monkeypatch):
    bus = FakeBus()
    FakeP2PClient.instances = []
    monkeypatch.setattr(realtime_module, "get_earthquake_event_bus", lambda: bus)
    monkeypatch.setattr(realtime_module, "P2PWebSocketClient", FakeP2PClient)

    service = EarthquakeRealtimeService()
    service.start()
    client = FakeP2PClient.instances[0]

    asyncio.run(service.stop())

    assert client.stopped is True


def test_seen_id_cache_is_capped_at_300():
    service = EarthquakeRealtimeService()

    for i in range(305):
        service._mark_seen(f"eq-{i:03d}")

    assert len(service._seen_ids) == 300
    assert "eq-000" not in service._seen_set
    assert "eq-004" not in service._seen_set
    assert "eq-005" in service._seen_set
    assert "eq-304" in service._seen_set

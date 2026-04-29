"""
test_earthquake_source_p2p_ws.py — P2P WebSocket 地震情報の正規化テスト
"""
from __future__ import annotations

import logging
import asyncio
from datetime import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import earthquake_source_p2p_ws as p2p_ws_module
from app.services.earthquake_source_p2p_ws import P2PWebSocketClient, normalize_p2p_ws_message


def p2p_message(**overrides):
    payload = {
        "id": "69f17616e88ee598246bec91",
        "code": 551,
        "earthquake": {
            "time": "2026/04/29 12:34:56.789",
            "maxScale": 45,
            "domesticTsunami": "NonEffective",
            "hypocenter": {
                "name": "東京湾",
                "latitude": 35.5,
                "longitude": 139.8,
                "depth": 30,
                "magnitude": 4.8,
            },
        },
    }
    payload.update(overrides)
    return payload


def test_normalize_code_551_full_message_matches_earthquake_event_contract():
    event = normalize_p2p_ws_message(p2p_message())

    assert event is not None
    assert event["event_id"] == "69f17616e88ee598246bec91"
    assert event["occurred_at"] == "2026-04-29T12:34:56+09:00"
    assert event["epicenter_name"] == "東京湾"
    assert event["lat"] == 35.5
    assert event["lng"] == 139.8
    assert event["depth_km"] == 30
    assert event["magnitude"] == 4.8
    assert event["max_intensity"] == "5弱"
    assert event["tsunami_info"] == "若干の海面変動あり"
    assert event["source"] == "p2p_ws"
    assert event["raw"]["code"] == 551


def test_normalize_uses_fingerprint_when_external_id_is_missing():
    raw = p2p_message(id=None)

    first = normalize_p2p_ws_message(raw)
    second = normalize_p2p_ws_message(raw)

    assert first is not None
    assert second is not None
    assert first["event_id"].startswith("p2p-ws-")
    assert first["event_id"] == second["event_id"]


def test_normalize_handles_missing_coordinates_and_unknown_values():
    raw = p2p_message(
        earthquake={
            "time": "2026/04/29 12:34:56",
            "maxScale": -1,
            "domesticTsunami": "Unknown",
            "hypocenter": {
                "name": "",
                "latitude": -200,
                "longitude": -200,
                "depth": -1,
                "magnitude": -1,
            },
        },
    )

    event = normalize_p2p_ws_message(raw)

    assert event is not None
    assert event["epicenter_name"] == "不明"
    assert event["lat"] is None
    assert event["lng"] is None
    assert event["depth_km"] is None
    assert event["magnitude"] is None
    assert event["max_intensity"] == "不明"
    assert event["tsunami_info"] == "調査中"


def test_normalize_returns_none_when_time_is_unusable():
    raw = p2p_message(earthquake={"time": "bad", "hypocenter": {}})

    assert normalize_p2p_ws_message(raw) is None


def test_client_handles_code_551_and_skips_invalid_messages(caplog):
    received = []
    client = P2PWebSocketClient(on_event=received.append)

    with caplog.at_level(logging.INFO):
        client._handle_message("not json")
        client._handle_message('{"code": 552}')
        client._handle_message(
            '{"id":"ws-001","code":551,"earthquake":{"time":"2026/04/29 12:34:56","maxScale":40,'
            '"domesticTsunami":"None","hypocenter":{"name":"東京湾","latitude":35.5,'
            '"longitude":139.8,"depth":30,"magnitude":4.8}}}'
        )

    assert len(received) == 1
    assert received[0]["event_id"] == "ws-001"
    assert received[0]["max_intensity"] == "4"
    assert "invalid JSON skipped" in caplog.text
    assert "unknown code=552 ignored" in caplog.text
    assert "earthquake event received: id=ws-001" in caplog.text


def test_reconnect_loop_uses_exponential_backoff_and_future_retry_time(monkeypatch):
    sleeps = []
    status_events = []
    client = P2PWebSocketClient(on_event=lambda event: None, on_state_change=status_events.append)
    started_at = datetime.fromisoformat(p2p_ws_module._now_iso())

    async def fail_connect():
        raise RuntimeError("boom")

    async def fake_sleep(delay):
        sleeps.append(delay)
        if len(sleeps) >= 3:
            client._running = False

    monkeypatch.setattr(client, "_connect_and_receive", fail_connect)
    monkeypatch.setattr(p2p_ws_module.asyncio, "sleep", fake_sleep)

    client._running = True
    asyncio.run(client._run_loop())

    assert sleeps == [5, 10, 20]
    reconnecting_events = [
        event for event in status_events
        if event["state"] == "reconnecting" and "next_retry_seconds" in event
    ]
    assert [event["next_retry_seconds"] for event in reconnecting_events] == [5, 10, 20]
    assert client.get_status()["retry_count"] == 3
    assert client.get_status()["next_retry_at"] is not None
    assert datetime.fromisoformat(client.get_status()["next_retry_at"]) > started_at


def test_reconnect_success_resets_retry_count_and_notifies_connected(monkeypatch):
    status_events = []
    client = P2PWebSocketClient(on_event=lambda event: None, on_state_change=status_events.append)
    attempts = {"count": 0}

    async def connect_then_return():
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("first fail")
        client._last_connected_at = p2p_ws_module._now_iso()
        client._last_error = None
        client._next_retry_at = None
        client._retry_count = 0
        client._set_state("connected")
        client._notify_state_change()
        client._running = False

    async def fake_sleep(_delay):
        return None

    monkeypatch.setattr(client, "_connect_and_receive", connect_then_return)
    monkeypatch.setattr(p2p_ws_module.asyncio, "sleep", fake_sleep)

    client._running = True
    asyncio.run(client._run_loop())

    assert attempts["count"] == 2
    assert client.get_status()["retry_count"] == 0
    assert client.get_status()["next_retry_at"] is None
    assert any(event["state"] == "connected" for event in status_events)


def test_disconnect_after_connected_counts_as_first_retry(monkeypatch):
    sleeps = []
    status_events = []
    client = P2PWebSocketClient(on_event=lambda event: None, on_state_change=status_events.append)

    async def connect_then_close():
        client._last_connected_at = p2p_ws_module._now_iso()
        client._last_error = None
        client._next_retry_at = None
        client._retry_count = 0
        client._set_state("connected")
        client._notify_state_change()

    async def fake_sleep(delay):
        sleeps.append(delay)
        client._running = False

    monkeypatch.setattr(client, "_connect_and_receive", connect_then_close)
    monkeypatch.setattr(p2p_ws_module.asyncio, "sleep", fake_sleep)

    client._running = True
    asyncio.run(client._run_loop())

    assert sleeps == [5]
    assert client.get_status()["retry_count"] == 1
    assert any(
        event["state"] == "reconnecting" and event.get("next_retry_seconds") == 5
        for event in status_events
    )

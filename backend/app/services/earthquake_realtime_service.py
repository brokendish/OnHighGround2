"""
earthquake_realtime_service.py — 地震リアルタイムサービス

P2P WebSocket → 重複排除 → EarthquakeEventBus → SSE
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.services.earthquake_event_bus import get_earthquake_event_bus
from app.services.earthquake_source_p2p_ws import P2PWebSocketClient

logger = logging.getLogger(__name__)

_MAX_SEEN = 300  # 重複排除用の直近 event_id 保持件数
_JST = timezone(timedelta(hours=9))


def _now_iso() -> str:
    return datetime.now(_JST).isoformat()


class EarthquakeRealtimeService:
    """P2P WebSocket → 重複排除 → EarthquakeEventBus へのパイプライン。"""

    def __init__(self) -> None:
        self._seen_ids: deque[str] = deque()
        self._seen_set: set[str] = set()
        self._ws_client: Optional[P2PWebSocketClient] = None
        self._last_event_at: Optional[str] = None

    # ── 重複排除 ───────────────────────────────────────────────────────────────
    def _is_seen(self, event_id: str) -> bool:
        return event_id in self._seen_set

    def _mark_seen(self, event_id: str) -> None:
        if len(self._seen_ids) >= _MAX_SEEN:
            oldest = self._seen_ids.popleft()
            self._seen_set.discard(oldest)
        self._seen_ids.append(event_id)
        self._seen_set.add(event_id)

    # ── 状態変更コールバック（P2P WS → SSE status event） ─────────────────────
    def _on_state_change(self, info: Dict[str, Any]) -> None:
        bus = get_earthquake_event_bus()
        status_event: Dict[str, Any] = {"_sse_type": "status", **info}
        try:
            bus.publish(status_event)
        except Exception as exc:
            logger.warning("Failed to publish SSE status event: %s", exc)

    # ── ライフサイクル ─────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._ws_client is not None:
            return
        bus = get_earthquake_event_bus()

        def _on_event(event: Dict[str, Any]) -> None:
            event_id = str(event.get("event_id") or "")
            if not event_id:
                logger.debug("earthquake event: no event_id, skipped")
                return

            if self._is_seen(event_id):
                logger.info("earthquake realtime duplicate skipped: event_id=%s", event_id)
                return

            self._mark_seen(event_id)
            self._last_event_at = _now_iso()

            logger.info(
                "earthquake realtime event published: event_id=%s epicenter=%s magnitude=%s",
                event_id,
                event.get("epicenter_name"),
                event.get("magnitude"),
            )
            bus.publish(event)

        self._ws_client = P2PWebSocketClient(
            on_event=_on_event,
            on_state_change=self._on_state_change,
        )
        self._ws_client.start()
        logger.info("EarthquakeRealtimeService started")

    async def stop(self) -> None:
        if self._ws_client:
            await self._ws_client.stop()
            self._ws_client = None
        logger.info("EarthquakeRealtimeService stopped")

    # ── ステータス ─────────────────────────────────────────────────────────────
    def get_status(self) -> Dict[str, Any]:
        base: Dict[str, Any] = {
            "enabled": self._ws_client is not None,
            "source": "p2p_ws",
            "last_event_at": self._last_event_at,
        }
        if self._ws_client:
            base.update(self._ws_client.get_status())
        else:
            base.update({
                "state": "disconnected",
                "retry_count": 0,
                "last_connected_at": None,
                "last_error": None,
                "next_retry_at": None,
            })
        return base


_realtime_service: Optional[EarthquakeRealtimeService] = None


def get_realtime_service() -> EarthquakeRealtimeService:
    global _realtime_service
    if _realtime_service is None:
        _realtime_service = EarthquakeRealtimeService()
    return _realtime_service

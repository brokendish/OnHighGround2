"""
earthquake_event_bus.py — 地震イベントバス
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_MAX_RECENT = 100


class EarthquakeEventBus:
    def __init__(self) -> None:
        self._queues: list[asyncio.Queue] = []
        self._recent: deque[Dict[str, Any]] = deque(maxlen=_MAX_RECENT)

    def publish(self, event: Dict[str, Any]) -> None:
        self._recent.append(event)
        for q in list(self._queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("EarthquakeEventBus: subscriber queue full, dropping event")

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._queues.append(q)
        logger.debug("EarthquakeEventBus: subscriber added, total=%d", len(self._queues))
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._queues.remove(q)
            logger.debug("EarthquakeEventBus: subscriber removed, total=%d", len(self._queues))
        except ValueError:
            pass

    def recent_events(self) -> List[Dict[str, Any]]:
        return list(self._recent)


_bus: EarthquakeEventBus | None = None


def get_earthquake_event_bus() -> EarthquakeEventBus:
    global _bus
    if _bus is None:
        _bus = EarthquakeEventBus()
    return _bus

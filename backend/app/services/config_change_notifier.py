"""
config_change_notifier.py — Config更新のSSE配信ブロードキャスター

PUT /api/admin/config/{key} が成功したときに broadcast() を呼ぶ。
GET /api/admin/config/stream の接続クライアントに config_updated イベントを送る。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List


class ConfigChangeNotifier:
    """接続中の全クライアントへConfig更新通知を配信するキューベースブロードキャスター。"""

    _HEARTBEAT_INTERVAL_SEC = 10.0

    def __init__(self) -> None:
        self._queues: List[asyncio.Queue] = []

    def broadcast(self, key: str, new_value: Any) -> None:
        """Config更新時に呼び出す。イベントループが動いていない場合は無視。"""
        if not self._queues:
            return
        payload = {"key": key, "new_value": new_value}
        for q in list(self._queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

    async def stream(self) -> AsyncIterator[str]:
        """SSEイベントジェネレーター。クライアント切断まで yield し続ける。"""
        q: asyncio.Queue[Dict | None] = asyncio.Queue(maxsize=20)
        self._queues.append(q)
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=self._HEARTBEAT_INTERVAL_SEC)
                    yield _sse("config_updated", payload)
                except asyncio.TimeoutError:
                    yield _sse("heartbeat", {})
        except asyncio.CancelledError:
            raise
        finally:
            self._queues.remove(q)


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


_notifier: ConfigChangeNotifier | None = None


def get_config_change_notifier() -> ConfigChangeNotifier:
    global _notifier
    if _notifier is None:
        _notifier = ConfigChangeNotifier()
    return _notifier

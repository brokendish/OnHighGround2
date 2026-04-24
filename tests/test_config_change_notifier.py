"""
test_config_change_notifier.py — ConfigChangeNotifier の回帰テスト

テスト対象:
  - broadcast() リスナーなしでもクラッシュしない
  - broadcast() の内容がストリームに届く（SSEフォーマット確認）
  - 複数リスナーへの同時配信
  - ストリーム終了（CancelledError）でキューが正常に解放される
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.config_change_notifier import ConfigChangeNotifier


# ── 同期ラッパー ─────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


# ── テスト ────────────────────────────────────────────────────────

def test_broadcast_with_no_listeners_does_not_raise():
    notifier = ConfigChangeNotifier()
    notifier.broadcast("navigation.off_route_distance_m", 25)


def test_broadcast_delivers_config_updated_event():
    async def _inner():
        notifier = ConfigChangeNotifier()

        async def _take_one():
            async for chunk in notifier.stream():
                return chunk

        task = asyncio.create_task(_take_one())
        await asyncio.sleep(0)  # キュー登録を待つ
        notifier.broadcast("navigation.off_route_distance_m", 25)
        return await asyncio.wait_for(task, timeout=2.0)

    chunk = _run(_inner())
    assert chunk.startswith("event: config_updated\n")
    data_line = next(l for l in chunk.splitlines() if l.startswith("data: "))
    payload = json.loads(data_line[len("data: "):])
    assert payload["key"] == "navigation.off_route_distance_m"
    assert payload["new_value"] == 25
    assert chunk.endswith("\n\n")


def test_broadcast_delivers_to_multiple_listeners():
    async def _inner():
        notifier = ConfigChangeNotifier()
        chunks_a: list[str] = []
        chunks_b: list[str] = []

        async def listen(bucket: list[str]):
            async for chunk in notifier.stream():
                bucket.append(chunk)
                return

        task_a = asyncio.create_task(listen(chunks_a))
        task_b = asyncio.create_task(listen(chunks_b))
        await asyncio.sleep(0)

        notifier.broadcast("navigation.near_goal_distance_m", 30)
        await asyncio.wait_for(asyncio.gather(task_a, task_b), timeout=2.0)
        return chunks_a, chunks_b

    chunks_a, chunks_b = _run(_inner())
    assert len(chunks_a) == 1
    assert len(chunks_b) == 1
    assert "near_goal_distance_m" in chunks_a[0]
    assert "near_goal_distance_m" in chunks_b[0]


def test_stream_cleanup_on_cancel():
    async def _inner():
        notifier = ConfigChangeNotifier()

        async def _listen():
            async for _ in notifier.stream():
                pass

        task = asyncio.create_task(_listen())
        await asyncio.sleep(0)
        assert len(notifier._queues) == 1

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        return len(notifier._queues)

    remaining = _run(_inner())
    assert remaining == 0

"""
earthquake_source_p2p_ws.py — P2P地震情報 WebSocket クライアント + 正規化

P2P公式仕様: https://www.p2pquake.net/develop/json_v2/
WebSocket接続先: wss://api.p2pquake.net/v2/ws
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from hashlib import sha1
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

_P2P_WS_URL = "wss://api.p2pquake.net/v2/ws"
_BACKOFF_BASE = 5    # seconds (初回再接続待機)
_BACKOFF_MAX  = 60   # seconds (最大待機)
_JST = timezone(timedelta(hours=9))

_SCALE_MAP: Dict[int, str] = {
    -1: "不明",
    10: "1",
    20: "2",
    30: "3",
    40: "4",
    45: "5弱",
    50: "5強",
    55: "6弱",
    60: "6強",
    70: "7",
}

_TSUNAMI_MAP: Dict[str, str] = {
    "None": "なし",
    "Unknown": "調査中",
    "Checking": "確認中",
    "NonEffective": "若干の海面変動あり",
    "Watch": "津波注意報",
    "Warning": "津波警報",
}


def _now_iso() -> str:
    return datetime.now(_JST).isoformat()


def _iso_after(seconds: int) -> str:
    return (datetime.now(_JST) + timedelta(seconds=seconds)).isoformat()


def _parse_time(time_str: Optional[str]) -> Optional[str]:
    """P2P 時刻文字列 "YYYY/MM/DD HH:MM:SS" → ISO 8601 文字列 (JST)"""
    if not time_str:
        return None
    try:
        dt = datetime.strptime(time_str.strip()[:19], "%Y/%m/%d %H:%M:%S")
        return dt.replace(tzinfo=_JST).isoformat()
    except ValueError:
        logger.debug("P2P WS: cannot parse time: %s", time_str)
        return None


def _valid_coordinate(value: Any) -> Optional[float]:
    if not isinstance(value, (int, float)):
        return None
    # P2P は座標不明時に -200 を返す
    if value <= -180:
        return None
    coordinate = float(value)
    if not (-180 <= coordinate <= 180):
        return None
    return coordinate


def _make_fingerprint(
    occurred_at: str,
    epicenter_name: str,
    magnitude: Any,
    max_intensity: str,
) -> str:
    key = f"{occurred_at}|{epicenter_name}|{magnitude}|{max_intensity}"
    return sha1(key.encode()).hexdigest()[:16]


def normalize_p2p_ws_message(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """P2P WebSocket メッセージ 1 件を EarthquakeEvent 形式へ変換する。"""
    eq = raw.get("earthquake") or {}
    hypo = eq.get("hypocenter") or {}

    occurred_at = _parse_time(eq.get("time"))
    if occurred_at is None:
        logger.debug("normalize failed: occurred_at is None, raw_id=%s", raw.get("id"))
        return None

    lat = _valid_coordinate(hypo.get("latitude"))
    lng = _valid_coordinate(hypo.get("longitude"))

    magnitude = hypo.get("magnitude", -1)
    depth_km = hypo.get("depth", -1)
    max_scale = eq.get("maxScale", -1)
    tsunami_code = eq.get("domesticTsunami", "None")
    epicenter_name = hypo.get("name") or "不明"

    max_intensity = _SCALE_MAP.get(max_scale, "不明")
    tsunami_info = _TSUNAMI_MAP.get(tsunami_code, str(tsunami_code))

    # event_id: 安定した外部IDがあればREST API側と同じIDを使用し、
    # ポーリング取得済みイベントとの重複をfrontend upsertで吸収できるようにする。
    external_id = raw.get("id")
    if external_id:
        event_id = str(external_id)
    else:
        mag_val = magnitude if isinstance(magnitude, (int, float)) and magnitude > 0 else -1
        fp = _make_fingerprint(occurred_at, epicenter_name, mag_val, max_intensity)
        event_id = f"p2p-ws-{fp}"

    return {
        "event_id": event_id,
        "occurred_at": occurred_at,
        "epicenter_name": epicenter_name,
        "lat": lat,
        "lng": lng,
        "depth_km": depth_km if isinstance(depth_km, (int, float)) and depth_km > 0 else None,
        "magnitude": magnitude if isinstance(magnitude, (int, float)) and magnitude > 0 else None,
        "max_intensity": max_intensity,
        "tsunami_info": tsunami_info,
        "source": "p2p_ws",
        "raw": raw,
    }


class P2PWebSocketClient:
    """P2P地震情報 WebSocket クライアント（指数バックオフ再接続 + 状態管理）。"""

    def __init__(
        self,
        on_event: Callable[[Dict[str, Any]], None],
        on_state_change: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        self._on_event = on_event
        self._on_state_change = on_state_change
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # 状態
        self._state: str = "disconnected"
        self._retry_count: int = 0
        self._last_connected_at: Optional[str] = None
        self._last_error: Optional[str] = None
        self._next_retry_at: Optional[str] = None

    # ── 状態管理 ──────────────────────────────────────────────────────────────
    def _set_state(self, state: str) -> None:
        self._state = state

    def _notify_state_change(self, next_retry_seconds: Optional[int] = None) -> None:
        if not self._on_state_change:
            return
        info: Dict[str, Any] = {"state": self._state, "source": "p2p_ws"}
        if next_retry_seconds is not None:
            info["next_retry_seconds"] = next_retry_seconds
        try:
            self._on_state_change(info)
        except Exception as exc:
            logger.warning("on_state_change callback failed: %s", exc)

    def get_status(self) -> Dict[str, Any]:
        return {
            "state": self._state,
            "retry_count": self._retry_count,
            "last_connected_at": self._last_connected_at,
            "last_error": self._last_error,
            "next_retry_at": self._next_retry_at,
        }

    # ── ライフサイクル ─────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.ensure_future(self._run_loop())
        logger.info("P2P WS client task scheduled")

    async def stop(self) -> None:
        self._running = False
        self._set_state("disconnected")
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    # ── 接続ループ（指数バックオフ） ──────────────────────────────────────────
    async def _run_loop(self) -> None:
        while self._running:
            state = "connecting" if self._retry_count == 0 else "reconnecting"
            self._set_state(state)
            self._notify_state_change()

            try:
                await self._connect_and_receive()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("P2P WS disconnected: %s", exc)

            if not self._running:
                break

            self._retry_count += 1

            effective_retry = max(self._retry_count, 1)
            delay = min(_BACKOFF_BASE * (2 ** (effective_retry - 1)), _BACKOFF_MAX)
            self._next_retry_at = _iso_after(delay)
            self._set_state("reconnecting")
            logger.info("P2P WS reconnect scheduled delay=%ds retry_count=%d", delay, self._retry_count)
            self._notify_state_change(next_retry_seconds=delay)

            try:
                await asyncio.sleep(delay)
            except asyncio.CancelledError:
                break

        self._set_state("disconnected")

    async def _connect_and_receive(self) -> None:
        import websockets  # import inside function — 起動失敗でもbackend継続

        logger.info("P2P WS connect attempt: %s", _P2P_WS_URL)
        connect_kwargs: Dict[str, Any] = {}
        # websockets 14+ では additional_headers、旧版は extra_headers
        try:
            import inspect
            sig = inspect.signature(websockets.connect)
            if "additional_headers" in sig.parameters:
                connect_kwargs["additional_headers"] = {
                    "User-Agent": "OnHighGround2/1.0 (+https://github.com/brokendish/OnHighGround2)"
                }
            elif "extra_headers" in sig.parameters:
                connect_kwargs["extra_headers"] = {
                    "User-Agent": "OnHighGround2/1.0 (+https://github.com/brokendish/OnHighGround2)"
                }
        except Exception:
            pass  # ヘッダ設定に失敗しても接続を試みる

        async with websockets.connect(_P2P_WS_URL, **connect_kwargs) as ws:
            previous_retry_count = self._retry_count
            self._retry_count = 0
            self._last_connected_at = _now_iso()
            self._last_error = None
            self._next_retry_at = None
            self._set_state("connected")
            logger.info("P2P WS connected")
            self._notify_state_change()

            if previous_retry_count > 0:
                logger.info("P2P WS reconnect success after %d attempt(s)", previous_retry_count)

            async for message in ws:
                if not self._running:
                    break
                self._handle_message(message)

        logger.info("P2P WS disconnected")

    # ── メッセージ処理 ────────────────────────────────────────────────────────
    def _handle_message(self, raw_message: str) -> None:
        try:
            data = json.loads(raw_message)
        except (json.JSONDecodeError, TypeError):
            logger.warning("P2P WS: invalid JSON skipped")
            return

        code = data.get("code")
        if code != 551:
            if code is not None:
                logger.info("P2P WS: unknown code=%s ignored", code)
            return

        logger.info("earthquake event received: id=%s", data.get("id"))

        try:
            event = normalize_p2p_ws_message(data)
        except Exception as exc:
            logger.warning("normalize failed: %s", exc)
            return

        if event is None:
            return

        try:
            self._on_event(event)
        except Exception as exc:
            logger.warning("on_event callback failed: %s", exc)

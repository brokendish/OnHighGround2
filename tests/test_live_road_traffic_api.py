"""
test_live_road_traffic_api.py — GET /api/live/road-traffic/summary API 契約テスト

検証観点:
- レスポンス構造と型
- APIキー不要（取得を試みる）
- 通信失敗時の unavailable 返却
- status が契約値内
- prefecture / bbox / lat+lng パラメーター処理
- 取得不可とデータなしの分離
- stale フラグの型
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

_VALID_STATUSES = {"ok", "unavailable"}


def _run(coro):
    return asyncio.run(coro)


# ── 基本レスポンス構造（モックモード） ──────────────────────────────────────────

def test_summary_returns_dict():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary())
    assert isinstance(result, dict)


def test_summary_has_status():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary())
    assert "status" in result


def test_summary_has_items():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary())
    assert "items" in result
    assert isinstance(result["items"], list)


def test_summary_has_scope():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary())
    assert "scope" in result


def test_summary_has_stale():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary())
    assert "stale" in result
    assert isinstance(result["stale"], bool)


# ── APIキー不要：通信失敗時のみ unavailable ───────────────────────────────────

def test_fetch_failure_returns_unavailable():
    """通信失敗時のみ unavailable を返す（APIキー未設定は理由にならない）。"""
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(side_effect=URLError("timeout"))):
            result = _run(get_road_traffic_summary())
    assert result["status"] == "unavailable"


def test_fetch_failure_items_empty():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(side_effect=URLError("timeout"))):
            result = _run(get_road_traffic_summary())
    assert result["items"] == []


def test_fetch_failure_has_message():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(side_effect=URLError("timeout"))):
            result = _run(get_road_traffic_summary())
    assert "message" in result


def test_no_api_key_still_attempts_fetch():
    """APIキー未設定でも取得を試みる（即座に unavailable にならない）。"""
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    called = []
    async def fake_fetch():
        called.append(True)
        return []
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=fake_fetch):
            result = _run(get_road_traffic_summary())
    assert called, "APIキー未設定でも _fetch_all_items が呼ばれるべき"
    assert result["status"] == "ok"


# ── モックモード → ok ────────────────────────────────────────────────────────

def test_mock_returns_ok():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true", "ROAD_TRAFFIC_API_KEY": ""}):
        result = _run(get_road_traffic_summary())
    assert result["status"] == "ok"


def test_mock_items_not_empty():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true", "ROAD_TRAFFIC_API_KEY": ""}):
        result = _run(get_road_traffic_summary())
    assert len(result["items"]) > 0


# ── status 値が契約値内 ───────────────────────────────────────────────────────

def test_status_in_valid_set_failure():
    """取得失敗時も status は契約値内。"""
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(side_effect=URLError("x"))):
            result = _run(get_road_traffic_summary())
    assert result["status"] in _VALID_STATUSES


def test_status_in_valid_set_mock():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary())
    assert result["status"] in _VALID_STATUSES


# ── prefecture パラメーター ───────────────────────────────────────────────────

def test_prefecture_scope():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary(prefecture="東京都"))
    assert result["scope"]["mode"] == "prefecture"
    assert result["scope"]["prefecture"] == "東京都"


def test_osaka_scope_is_not_tokyo():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary(prefecture="大阪府"))
    assert result["scope"]["prefecture"] == "大阪府"


# ── bbox パラメーター ─────────────────────────────────────────────────────────

def test_bbox_scope():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary(bbox="139.5,35.5,140.0,35.9"))
    assert result["scope"]["mode"] == "bbox"


def test_bbox_priority_over_prefecture():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary(prefecture="東京都", bbox="138.0,34.0,141.0,36.5"))
    assert result["scope"]["mode"] == "bbox"


# ── lat/lng パラメーター ──────────────────────────────────────────────────────

def test_latlon_scope():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary(lat=35.6812, lng=139.7671))
    assert result["scope"]["mode"] in ("location", "all")


# ── 取得不可とデータなしの分離 ────────────────────────────────────────────────

def test_unavailable_not_same_as_empty_data():
    """取得不可はステータス "unavailable"。items=[] との混同禁止。"""
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(side_effect=URLError("x"))):
            result = _run(get_road_traffic_summary())
    assert result["status"] == "unavailable"
    assert "message" in result


def test_items_each_have_status_and_severity():
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary())
    for item in result["items"]:
        assert "status"       in item
        assert "status_label" in item
        assert "severity"     in item
        assert isinstance(item["severity"], int)


def test_items_no_undefined_source():
    """sourceフィールドが空文字や"undefined"でない。"""
    import app.services.live_road_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0
    from app.api.live_road_traffic import get_road_traffic_summary
    with patch.dict(os.environ, {"ROAD_TRAFFIC_USE_MOCK": "true"}):
        result = _run(get_road_traffic_summary())
    for item in result["items"]:
        assert item.get("source", "") not in ("", "undefined", "null")

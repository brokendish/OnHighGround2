"""
test_live_train_api.py — GET /api/live/trains/summary API 契約テスト

検証観点:
- レスポンス構造と型
- APIキー未設定時の unavailable 返却
- status が契約値内
- prefecture パラメーター処理
- stale フラグの型
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

_VALID_STATUSES = {"ok", "unavailable", "stale"}


def _run(coro):
    return asyncio.run(coro)


# ── 基本レスポンス構造（APIキーなし） ─────────────────────────────────────────

def test_summary_returns_dict():
    from app.api.live_train import get_train_summary
    body = _run(get_train_summary())
    assert isinstance(body, dict)


def test_summary_has_required_keys():
    from app.api.live_train import get_train_summary
    body = _run(get_train_summary())
    for key in ("status", "stale", "scope", "updated_at", "items"):
        assert key in body, f"key={key} がない"


def test_items_is_list():
    from app.api.live_train import get_train_summary
    body = _run(get_train_summary())
    assert isinstance(body["items"], list)


def test_status_is_valid():
    from app.api.live_train import get_train_summary
    body = _run(get_train_summary())
    assert body["status"] in _VALID_STATUSES


def test_stale_is_bool():
    from app.api.live_train import get_train_summary
    body = _run(get_train_summary())
    assert isinstance(body["stale"], bool)


def test_scope_is_dict():
    from app.api.live_train import get_train_summary
    body = _run(get_train_summary())
    assert isinstance(body["scope"], dict)


def test_updated_at_is_string():
    from app.api.live_train import get_train_summary
    body = _run(get_train_summary())
    assert isinstance(body["updated_at"], str)


# ── APIキー未設定 → unavailable ──────────────────────────────────────────────

def test_no_api_key_status_unavailable():
    original = os.environ.pop("ODPT_API_KEY", None)
    try:
        from app.api.live_train import get_train_summary
        body = _run(get_train_summary())
        assert body["status"] == "unavailable"
    finally:
        if original is not None:
            os.environ["ODPT_API_KEY"] = original


def test_no_api_key_items_empty():
    original = os.environ.pop("ODPT_API_KEY", None)
    try:
        from app.api.live_train import get_train_summary
        body = _run(get_train_summary())
        assert body["items"] == []
    finally:
        if original is not None:
            os.environ["ODPT_API_KEY"] = original


def test_no_api_key_message_present():
    original = os.environ.pop("ODPT_API_KEY", None)
    try:
        from app.api.live_train import get_train_summary
        body = _run(get_train_summary())
        assert "message" in body
    finally:
        if original is not None:
            os.environ["ODPT_API_KEY"] = original


def test_no_api_key_http_200():
    """APIキー未設定でも 5xx ではなく正常なレスポンスを返す（FastAPI 経由では 200）。"""
    original = os.environ.pop("ODPT_API_KEY", None)
    try:
        from app.api.live_train import get_train_summary
        body = _run(get_train_summary())
        assert body is not None
    finally:
        if original is not None:
            os.environ["ODPT_API_KEY"] = original


def test_no_api_key_prefecture_scope_preserved():
    original = os.environ.pop("ODPT_API_KEY", None)
    try:
        from app.api.live_train import get_train_summary
        body = _run(get_train_summary(prefecture="大阪府"))
        assert body["status"] == "unavailable"
        assert body["scope"].get("mode") == "prefecture"
        assert body["scope"].get("prefecture") == "大阪府"
    finally:
        if original is not None:
            os.environ["ODPT_API_KEY"] = original


def test_no_api_key_location_scope_preserved():
    original = os.environ.pop("ODPT_API_KEY", None)
    try:
        from app.api.live_train import get_train_summary
        body = _run(get_train_summary(lat=35.681236, lng=139.767125))
        assert body["status"] == "unavailable"
        assert body["scope"].get("mode") == "location"
        assert body["scope"].get("prefecture") == "東京都"
    finally:
        if original is not None:
            os.environ["ODPT_API_KEY"] = original


# ── prefecture パラメーター ──────────────────────────────────────────────────

def test_prefecture_param_sets_scope():
    import app.services.live_train_service as svc
    os.environ["ODPT_API_KEY"] = "test-key"
    try:
        svc._cache = {
            "status":     "ok",
            "stale":      False,
            "scope":      {},
            "updated_at": "2026-06-14T18:00:00+09:00",
            "items":      [],
        }
        svc._cache_at = svc._monotonic()

        from app.api.live_train import get_train_summary
        body = _run(get_train_summary(prefecture="東京都"))
        assert body["scope"].get("mode") == "prefecture"
        assert body["scope"].get("prefecture") == "東京都"
    finally:
        svc._cache    = None
        svc._cache_at = 0.0
        os.environ.pop("ODPT_API_KEY", None)


def test_prefecture_param_items_filtered():
    """prefecture 指定で対象外路線が除外される。"""
    import app.services.live_train_service as svc
    from app.models.live_train import STATUS_DELAY, SEVERITY

    os.environ["ODPT_API_KEY"] = "test-key"
    try:
        item_tokyo = {
            "railway_id":    "odpt.Railway:TokyoMetro.Ginza",
            "operator_id":   "odpt.Operator:TokyoMetro",
            "operator_name": "東京メトロ",
            "railway_name":  "銀座線",
            "status":        STATUS_DELAY,
            "status_label":  "遅延",
            "severity":      SEVERITY[STATUS_DELAY],
            "description":   "遅延",
            "updated_at":    "2026-06-14T18:00:00+09:00",
            "source":        "ODPT",
        }
        item_osaka = {
            "railway_id":    "odpt.Railway:Kintetsu.Osaka",
            "operator_id":   "odpt.Operator:Kintetsu",
            "operator_name": "近畿日本鉄道",
            "railway_name":  "大阪線",
            "status":        STATUS_DELAY,
            "status_label":  "遅延",
            "severity":      SEVERITY[STATUS_DELAY],
            "description":   "遅延",
            "updated_at":    "2026-06-14T18:00:00+09:00",
            "source":        "ODPT",
        }
        svc._cache = {
            "status":     "ok",
            "stale":      False,
            "scope":      {},
            "updated_at": "2026-06-14T18:00:00+09:00",
            "items":      [item_tokyo, item_osaka],
        }
        svc._cache_at = svc._monotonic()

        from app.api.live_train import get_train_summary
        body = _run(get_train_summary(prefecture="東京都"))
        ids = [it["operator_id"] for it in body["items"]]
        assert "odpt.Operator:TokyoMetro" in ids
        assert "odpt.Operator:Kintetsu" not in ids
    finally:
        svc._cache    = None
        svc._cache_at = 0.0
        os.environ.pop("ODPT_API_KEY", None)


# ── アイテム構造確認 ──────────────────────────────────────────────────────────

def test_item_has_required_fields_when_present():
    """items に要素がある場合、各要素に必須フィールドが存在する。"""
    import app.services.live_train_service as svc
    from app.models.live_train import STATUS_SUSPENDED, SEVERITY

    os.environ["ODPT_API_KEY"] = "test-key"
    try:
        item = {
            "railway_id":    "odpt.Railway:Keio.Keio",
            "operator_id":   "odpt.Operator:Keio",
            "operator_name": "京王電鉄",
            "railway_name":  "京王線",
            "status":        STATUS_SUSPENDED,
            "status_label":  "運転見合わせ",
            "severity":      SEVERITY[STATUS_SUSPENDED],
            "description":   "大雨の影響で運転を見合わせています",
            "updated_at":    "2026-06-14T17:58:00+09:00",
            "source":        "ODPT",
        }
        svc._cache = {
            "status":     "ok",
            "stale":      False,
            "scope":      {},
            "updated_at": "2026-06-14T18:00:00+09:00",
            "items":      [item],
        }
        svc._cache_at = svc._monotonic()

        from app.api.live_train import get_train_summary
        body = _run(get_train_summary(prefecture="東京都"))
        if body["items"]:
            result_item = body["items"][0]
            for key in ("railway_id", "operator_name", "railway_name", "status",
                        "status_label", "severity", "description", "updated_at"):
                assert key in result_item, f"アイテムに key={key} がない"
    finally:
        svc._cache    = None
        svc._cache_at = 0.0
        os.environ.pop("ODPT_API_KEY", None)

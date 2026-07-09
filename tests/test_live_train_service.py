"""
test_live_train_service.py — live_train_service ユニットテスト

外部 API (ODPT) は一切呼ばない。
正規化ロジック・ステータス判定・キャッシュ動作を検証する。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.models.live_train import (
    SEVERITY,
    STATUS_DELAY,
    STATUS_LABEL,
    STATUS_NORMAL,
    STATUS_PARTIAL_SUSPENSION,
    STATUS_SUSPENDED,
    STATUS_UNAVAILABLE,
    STATUS_UNKNOWN,
)
from app.services.live_train_service import (
    _OPERATOR_NAMES,
    _RAILWAY_NAMES,
    _excluded_keywords,
    _fetch_all_disruptions,
    _is_excluded_source,
    _item_matches_prefecture,
    _matches_geojson,
    _nearest_prefecture_from_latlon,
    _operator_key,
    _railway_key,
    _railway_name_from_id,
    _operator_name_from_id,
    normalize_odpt_item,
    normalize_status,
    build_train_summary,
)


def _run(coro):
    return asyncio.run(coro)


# ── normalize_status ──────────────────────────────────────────────────────────

def test_status_none_is_normal():
    assert normalize_status(None) == STATUS_NORMAL


def test_status_empty_string_is_normal():
    assert normalize_status("") == STATUS_NORMAL


def test_status_heijou_is_normal():
    assert normalize_status({"ja": "平常"}) == STATUS_NORMAL


def test_status_heijou_kanji_is_normal():
    assert normalize_status({"ja": "平常通り運転"}) == STATUS_NORMAL


def test_status_delay_ja():
    assert normalize_status({"ja": "遅延"}) == STATUS_DELAY


def test_status_delay_en():
    assert normalize_status({"en": "Delay"}) == STATUS_DELAY


def test_status_suspended_ja():
    assert normalize_status({"ja": "運転見合わせ"}) == STATUS_SUSPENDED


def test_status_suspended_from_text():
    assert normalize_status({"ja": "その他"}, {"ja": "大雨の影響で運転を見合わせています"}) == STATUS_SUSPENDED


def test_status_partial_suspension_ja():
    assert normalize_status({"ja": "一部運休"}) == STATUS_PARTIAL_SUSPENSION


def test_status_partial_en():
    assert normalize_status({"en": "Partial Service Suspended"}) == STATUS_PARTIAL_SUSPENSION


def test_status_unknown_text():
    assert normalize_status({"ja": "ダイヤ乱れ"}) == STATUS_UNKNOWN


def test_status_string_delay():
    assert normalize_status("遅延") == STATUS_DELAY


def test_status_string_suspended():
    assert normalize_status("運転見合わせ") == STATUS_SUSPENDED


# ── normalize_odpt_item ───────────────────────────────────────────────────────

def _make_raw(
    railway="odpt.Railway:Odakyu.Odawara",
    operator="odpt.Operator:Odakyu",
    status=None,
    text=None,
    date="2026-06-14T18:00:00+09:00",
):
    raw = {
        "odpt:railway":  railway,
        "odpt:operator": operator,
        "dc:date":       date,
    }
    if status is not None:
        raw["odpt:trainInformationStatus"] = status
    if text is not None:
        raw["odpt:trainInformationText"] = text
    return raw


def test_normalize_normal_returns_none():
    """平常路線は None を返す（フィルタリング済み）。"""
    raw = _make_raw(status=None)
    assert normalize_odpt_item(raw) is None


def test_normalize_delay_returns_item():
    raw = _make_raw(status={"ja": "遅延"}, text={"ja": "一部列車に遅れ"})
    item = normalize_odpt_item(raw)
    assert item is not None
    assert item["status"] == STATUS_DELAY


def test_normalize_suspended_returns_item():
    raw = _make_raw(status={"ja": "運転見合わせ"})
    item = normalize_odpt_item(raw)
    assert item is not None
    assert item["status"] == STATUS_SUSPENDED


def test_normalize_partial_suspension():
    raw = _make_raw(status={"ja": "一部運休"})
    item = normalize_odpt_item(raw)
    assert item is not None
    assert item["status"] == STATUS_PARTIAL_SUSPENSION


def test_normalize_item_has_required_keys():
    raw = _make_raw(status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item is not None
    for key in ("railway_id", "operator_id", "operator_name", "railway_name",
                "status", "status_label", "severity", "description", "updated_at", "source"):
        assert key in item, f"key={key} がない"


def test_normalize_railway_id_preserved():
    raw = _make_raw(railway="odpt.Railway:Odakyu.Odawara", status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item["railway_id"] == "odpt.Railway:Odakyu.Odawara"


def test_normalize_operator_name_lookup():
    raw = _make_raw(operator="odpt.Operator:Odakyu", status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item["operator_name"] == "小田急電鉄"


def test_normalize_railway_name_lookup():
    raw = _make_raw(railway="odpt.Railway:Odakyu.Odawara", status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item["railway_name"] == "小田原線"


def test_normalize_unknown_operator_uses_key():
    raw = _make_raw(operator="odpt.Operator:Unknown", status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item["operator_name"] == "Unknown"


def test_normalize_severity_delay():
    raw = _make_raw(status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item["severity"] == SEVERITY[STATUS_DELAY]


def test_normalize_severity_suspended():
    raw = _make_raw(status={"ja": "運転見合わせ"})
    item = normalize_odpt_item(raw)
    assert item["severity"] == SEVERITY[STATUS_SUSPENDED]


def test_normalize_status_label_is_japanese():
    raw = _make_raw(status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item["status_label"] == STATUS_LABEL[STATUS_DELAY]


def test_normalize_source_is_odpt():
    raw = _make_raw(status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item["source"] == "ODPT"


def test_normalize_missing_railway_returns_none():
    raw = {"odpt:operator": "odpt.Operator:Odakyu", "odpt:trainInformationStatus": {"ja": "遅延"}}
    assert normalize_odpt_item(raw) is None


def test_normalize_description_from_text():
    raw = _make_raw(status={"ja": "遅延"}, text={"ja": "大雨の影響で遅延が発生しています"})
    item = normalize_odpt_item(raw)
    assert "遅延" in item["description"] or "大雨" in item["description"]


# ── 空配列 → 障害なし ────────────────────────────────────────────────────────

def test_empty_odpt_list_no_items():
    """ODPT が空配列を返したとき = 障害なし。"""
    from app.services.live_train_service import normalize_odpt_item
    raw_list = []
    items = [normalize_odpt_item(r) for r in raw_list if normalize_odpt_item(r)]
    assert items == []


# ── 都道府県フィルター ────────────────────────────────────────────────────────

def _make_item(operator_id="odpt.Operator:Odakyu", railway_id="odpt.Railway:Odakyu.Odawara"):
    return {
        "railway_id":    railway_id,
        "operator_id":   operator_id,
        "operator_name": "小田急電鉄",
        "railway_name":  "小田原線",
        "status":        STATUS_DELAY,
        "status_label":  "遅延",
        "severity":      SEVERITY[STATUS_DELAY],
        "description":   "遅延",
        "updated_at":    "2026-06-14T18:00:00+09:00",
        "source":        "ODPT",
    }


def test_prefecture_filter_tokyo_matches_odakyu():
    item = _make_item()
    assert _item_matches_prefecture(item, "東京都") is True


def test_prefecture_filter_kanagawa_matches_odakyu():
    item = _make_item()
    assert _item_matches_prefecture(item, "神奈川県") is True


def test_prefecture_filter_osaka_does_not_match_odakyu():
    item = _make_item()
    assert _item_matches_prefecture(item, "大阪府") is False


def test_prefecture_filter_jreast_matches_many():
    item = _make_item(operator_id="odpt.Operator:JR-East")
    assert _item_matches_prefecture(item, "東京都") is True
    assert _item_matches_prefecture(item, "神奈川県") is True
    assert _item_matches_prefecture(item, "宮城県") is True


def test_prefecture_filter_unknown_operator_no_match():
    item = _make_item(operator_id="odpt.Operator:Unknown")
    assert _item_matches_prefecture(item, "東京都") is False


# ── APIキー未設定 → unavailable ───────────────────────────────────────────────

def test_no_api_key_returns_unavailable():
    import os
    original = os.environ.pop("ODPT_API_KEY", None)
    try:
        result = _run(build_train_summary())
        assert result["status"] == "unavailable"
        assert result["items"] == []
    finally:
        if original is not None:
            os.environ["ODPT_API_KEY"] = original


# ── stale cache ───────────────────────────────────────────────────────────────

def test_stale_cache_on_fetch_failure():
    """取得失敗時に stale cache を返し stale=True が付く。"""
    import app.services.live_train_service as svc
    import os

    # APIキーを設定（unavailable パスを避ける）
    os.environ["ODPT_API_KEY"] = "test-key"
    try:
        # キャッシュに手動でデータをセット
        from app.models.live_train import STATUS_DELAY, SEVERITY
        mock_item = _make_item()
        svc._cache = {
            "status":     "ok",
            "stale":      False,
            "scope":      {},
            "updated_at": "2026-06-14T18:00:00+09:00",
            "items":      [mock_item],
        }
        svc._cache_at = 0.0  # TTL 切れ状態にする

        async def _fail(*args, **kwargs):
            raise RuntimeError("fetch failed")

        with patch("app.services.live_train_service._fetch_all_disruptions", side_effect=_fail):
            result = _run(build_train_summary())

        assert result["stale"] is True
        assert len(result["items"]) > 0
    finally:
        svc._cache    = None
        svc._cache_at = 0.0
        os.environ.pop("ODPT_API_KEY", None)


# ── prefecture フィルター + scope ─────────────────────────────────────────────

def test_prefecture_scope_filters_items():
    """prefecture 指定時に非対象路線が除外される。"""
    import app.services.live_train_service as svc
    import os

    os.environ["ODPT_API_KEY"] = "test-key"
    try:
        odakyu = _make_item(operator_id="odpt.Operator:Odakyu")
        kintetsu = _make_item(
            operator_id="odpt.Operator:Kintetsu",
            railway_id="odpt.Railway:Kintetsu.Osaka",
        )
        svc._cache = {
            "status":     "ok",
            "stale":      False,
            "scope":      {},
            "updated_at": "2026-06-14T18:00:00+09:00",
            "items":      [odakyu, kintetsu],
        }
        svc._cache_at = svc._monotonic()  # 有効なキャッシュ

        result = _run(build_train_summary(prefecture="東京都"))

        # 小田急は東京都対応、近鉄は対象外
        ids = [it["operator_id"] for it in result["items"]]
        assert "odpt.Operator:Odakyu" in ids
        assert "odpt.Operator:Kintetsu" not in ids
        assert result["scope"]["mode"] == "prefecture"
        assert result["scope"]["prefecture"] == "東京都"
    finally:
        svc._cache    = None
        svc._cache_at = 0.0
        os.environ.pop("ODPT_API_KEY", None)


# ── モデル定数 確認 ──────────────────────────────────────────────────────────

def test_severity_order():
    """severity は normal < delay < partial_suspension < suspended < unavailable。"""
    assert SEVERITY[STATUS_NORMAL]             < SEVERITY[STATUS_DELAY]
    assert SEVERITY[STATUS_DELAY]              < SEVERITY[STATUS_PARTIAL_SUSPENSION]
    assert SEVERITY[STATUS_PARTIAL_SUSPENSION] < SEVERITY[STATUS_SUSPENDED]
    assert SEVERITY[STATUS_SUSPENDED]          < SEVERITY[STATUS_UNAVAILABLE]


def test_status_label_covers_all_statuses():
    for status in (STATUS_NORMAL, STATUS_DELAY, STATUS_PARTIAL_SUSPENSION,
                   STATUS_SUSPENDED, STATUS_UNKNOWN, STATUS_UNAVAILABLE):
        assert status in STATUS_LABEL


def test_operator_names_has_major_operators():
    for op in ("JR-East", "TokyoMetro", "Odakyu", "Kintetsu"):
        assert op in _OPERATOR_NAMES


def test_railway_names_has_major_railways():
    assert "JR-East.Yamanote" in _RAILWAY_NAMES
    assert "TokyoMetro.Ginza" in _RAILWAY_NAMES
    assert "Odakyu.Odawara" in _RAILWAY_NAMES


# ── operator_key / railway_key ────────────────────────────────────────────────

def test_operator_key_strips_prefix():
    assert _operator_key("odpt.Operator:Odakyu") == "Odakyu"


def test_railway_key_strips_prefix():
    assert _railway_key("odpt.Railway:Odakyu.Odawara") == "Odakyu.Odawara"


def test_operator_key_no_prefix():
    assert _operator_key("Odakyu") == "Odakyu"


def test_railway_name_fallback_for_unknown():
    name = _railway_name_from_id("odpt.Railway:FutureLine.NewBranch")
    assert name == "NewBranch"


def test_operator_name_fallback_for_unknown():
    name = _operator_name_from_id("odpt.Operator:FutureLine")
    assert name == "FutureLine"


# ── チャレンジ/期間限定データ除外 (Phase 7-A.5) ───────────────────────────────

def test_excluded_keywords_default_covers_challenge_terms():
    keywords = _excluded_keywords()
    for kw in ("challenge", "contest", "2026", "limited", "temporary", "experimental"):
        assert kw in keywords


def test_is_excluded_source_challenge_operator():
    raw = _make_raw(operator="odpt.Operator:Challenge2026Operator", status={"ja": "遅延"})
    assert _is_excluded_source(raw) is True


def test_is_excluded_source_challenge_railway():
    raw = _make_raw(railway="odpt.Railway:Challenge2026.SomeLine", status={"ja": "遅延"})
    assert _is_excluded_source(raw) is True


def test_is_excluded_source_normal_item_not_excluded():
    raw = _make_raw(status={"ja": "遅延"})
    assert _is_excluded_source(raw) is False


def test_is_excluded_source_ignores_date_field():
    """dc:date に '2026' を含んでいても、識別子フィールドでなければ除外しない。"""
    raw = _make_raw(status={"ja": "遅延"}, date="2026-07-08T12:00:00+09:00")
    assert _is_excluded_source(raw) is False


def test_excluded_keywords_env_override(monkeypatch):
    monkeypatch.setenv("ODPT_EXCLUDE_KEYWORDS", "foo,bar")
    assert _excluded_keywords() == ("foo", "bar")


def test_fetch_all_disruptions_filters_challenge_items():
    """_fetch_all_disruptions が challenge2026 相当のraw itemを除外する。"""
    import os

    os.environ["ODPT_API_KEY"] = "test-key"
    raw_list = [
        _make_raw(railway="odpt.Railway:Challenge2026.SomeLine",
                   operator="odpt.Operator:Challenge2026",
                   status={"ja": "遅延"}),
        _make_raw(railway="odpt.Railway:JR-West.Kobe",
                   operator="odpt.Operator:JR-West",
                   status={"ja": "遅延"}),
    ]
    try:
        with patch("app.services.live_train_service._fetch_odpt_train_information",
                   return_value=raw_list):
            items = _run(_fetch_all_disruptions())
        railway_ids = [it["railway_id"] for it in items]
        assert "odpt.Railway:Challenge2026.SomeLine" not in railway_ids
        assert "odpt.Railway:JR-West.Kobe" in railway_ids
    finally:
        os.environ.pop("ODPT_API_KEY", None)


# ── matched_geojson 診断フィールド (Phase 7-A.5) ──────────────────────────────

def test_matched_geojson_true_for_known_kanto_lines():
    assert _matches_geojson("京王線") is True
    assert _matches_geojson("東武東上線") is True
    assert _matches_geojson("有楽町線") is True  # OSM名「東京メトロ有楽町線」に部分一致


def test_matched_geojson_false_for_fictional_line():
    assert _matches_geojson("検証架空線") is False


def test_matched_geojson_empty_name_is_false():
    assert _matches_geojson("") is False


def test_matched_geojson_short_name_requires_exact_match():
    """短い bare 名 (「本線」等) は部分一致による誤爆を避け、完全一致のみ許可する。"""
    assert _matches_geojson("本線") is False


def test_normalize_item_includes_matched_geojson_field():
    raw = _make_raw(railway="odpt.Railway:Tobu.TobuTojo",
                     operator="odpt.Operator:Tobu", status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert "matched_geojson" in item
    assert item["matched_geojson"] is True
    assert item["railway_name"] == "東上線"


def test_normalize_item_matched_geojson_false_for_non_kanto_operator():
    raw = _make_raw(railway="odpt.Railway:JR-Kyushu.Kagoshima",
                     operator="odpt.Operator:JR-Kyushu", status={"ja": "遅延"})
    item = normalize_odpt_item(raw)
    assert item["matched_geojson"] is False

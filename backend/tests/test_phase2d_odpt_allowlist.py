"""
Phase 2-D Round 2 — ODPT operator license allowlist（P2D-ODPT-TERMS）試験。

対応する指示書: tasks/public-release/phase2d_claude_remediation_instruction_round2.md 第7.3節

最低限の検証項目（指示書第7.3節1〜10）:
    1. allowlisted TokyoMetroを受理
    2. unknown operatorを除外
    3. missing operator IDを除外
    4. license mapping欠落entryを起動時またはtest時にFAIL
    5. challenge datasetを除外
    6. cacheへunknownが入らない
    7. UIへprovider・terms・timestampが表示される
    8. API failure時に古い情報を現在情報として断定しない
    9. token / response全量をlogへ出さない
    10. allowlist空の場合にfail-closed

実行:
    cd backend && ../venv/bin/python -m pytest tests/test_phase2d_odpt_allowlist.py -v
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import odpt_allowlist  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_allowlist_cache():
    odpt_allowlist.reset_cache_for_testing()
    yield
    odpt_allowlist.reset_cache_for_testing()


def _write_allowlist(tmp_path: Path, entries: list) -> Path:
    p = tmp_path / "odpt_allowlist_data.json"
    p.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. allowlisted TokyoMetroを受理
# ---------------------------------------------------------------------------

def test_odpt_a01_allowlisted_tokyometro_accepted(tmp_path, monkeypatch):
    monkeypatch.setattr(
        odpt_allowlist, "_DATA_PATH",
        _write_allowlist(tmp_path, [{"operator_id": "TokyoMetro", "license": "公共交通オープンデータ基本ライセンス",
                                       "terms_url": "https://developer.odpt.org/terms", "confirmed_date": "2026-08-21"}]),
    )
    assert odpt_allowlist.is_operator_allowed("TokyoMetro") is True


# ---------------------------------------------------------------------------
# 2. unknown operatorを除外
# ---------------------------------------------------------------------------

def test_odpt_a02_unknown_operator_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(
        odpt_allowlist, "_DATA_PATH",
        _write_allowlist(tmp_path, [{"operator_id": "TokyoMetro", "license": "X", "terms_url": "https://x", "confirmed_date": "2026-08-21"}]),
    )
    assert odpt_allowlist.is_operator_allowed("SomeUnknownOperator") is False


# ---------------------------------------------------------------------------
# 3. missing operator IDを除外
# ---------------------------------------------------------------------------

def test_odpt_a03_missing_operator_id_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(
        odpt_allowlist, "_DATA_PATH",
        _write_allowlist(tmp_path, [{"operator_id": "TokyoMetro", "license": "X", "terms_url": "https://x", "confirmed_date": "2026-08-21"}]),
    )
    assert odpt_allowlist.is_operator_allowed("") is False
    assert odpt_allowlist.is_operator_allowed(None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 4. license mapping欠落entryを起動時またはtest時にFAIL（=読み込み時に拒否・除外）
# ---------------------------------------------------------------------------

def test_odpt_a04_entry_missing_license_field_is_rejected_at_load(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(
        odpt_allowlist, "_DATA_PATH",
        _write_allowlist(tmp_path, [
            {"operator_id": "TokyoMetro", "license": "公共交通オープンデータ基本ライセンス", "terms_url": "https://x", "confirmed_date": "2026-08-21"},
            {"operator_id": "NoLicenseOperator", "terms_url": "https://x", "confirmed_date": "2026-08-21"},  # license欠落
        ]),
    )
    with caplog.at_level(logging.ERROR):
        entries = odpt_allowlist.get_allowlist_entries()
    ids = {e["operator_id"] for e in entries}
    assert "NoLicenseOperator" not in ids
    assert "TokyoMetro" in ids
    assert odpt_allowlist.is_operator_allowed("NoLicenseOperator") is False


# ---------------------------------------------------------------------------
# 5. challenge datasetを除外（既存の_is_excluded_source + allowlist二重防御）
# ---------------------------------------------------------------------------

def test_odpt_a05_challenge_limited_operator_not_in_initial_allowlist():
    # JR-Eastは2026-08-21にckan.odpt.orgで「公共交通オープンデータチャレンジ限定
    # ライセンス」と確認されたため、実allowlist data（odpt_allowlist_data.json）に
    # 意図的に含めていない。
    real_entries = json.loads(
        (Path(__file__).resolve().parents[1] / "app" / "services" / "odpt_allowlist_data.json").read_text(encoding="utf-8")
    )
    operator_ids = {e["operator_id"] for e in real_entries}
    assert "JR-East" not in operator_ids
    assert "TokyoMetro" in operator_ids
    assert "Toei" in operator_ids


# ---------------------------------------------------------------------------
# 6〜9: live_train_service統合（fetchのmock、cache/UI/log挙動）
# ---------------------------------------------------------------------------

def _import_fresh_live_train_service(monkeypatch, tmp_path, allowlist_entries):
    """live_train_serviceをモジュールcacheごと再import（グローバルcache変数を
    綺麗な状態にするため）。"""
    monkeypatch.setattr(odpt_allowlist, "_DATA_PATH", _write_allowlist(tmp_path, allowlist_entries))
    odpt_allowlist.reset_cache_for_testing()
    sys.modules.pop("app.services.live_train_service", None)
    import app.services.live_train_service as lts  # noqa: PLC0415
    importlib.reload(lts)
    lts._cache = None
    lts._cache_at = 0.0
    return lts


_RAW_TOKYOMETRO = {
    "odpt:operator": "odpt.Operator:TokyoMetro",
    "odpt:railway": "odpt.Railway:TokyoMetro.Ginza",
    "odpt:trainInformationStatus": {"ja": "遅延"},
    "odpt:trainInformationText": {"ja": "銀座線は遅延しています。"},
    "dc:date": "2026-08-21T10:00:00+09:00",
}

_RAW_UNKNOWN_OPERATOR = {
    "odpt:operator": "odpt.Operator:SomeUnknownRailway",
    "odpt:railway": "odpt.Railway:SomeUnknownRailway.Main",
    "odpt:trainInformationStatus": {"ja": "遅延"},
    "odpt:trainInformationText": {"ja": "不明事業者は遅延しています。"},
    "dc:date": "2026-08-21T10:00:00+09:00",
}


def test_odpt_a06_unknown_operator_not_cached_or_returned(tmp_path, monkeypatch):
    lts = _import_fresh_live_train_service(
        monkeypatch, tmp_path,
        [{"operator_id": "TokyoMetro", "license": "公共交通オープンデータ基本ライセンス", "terms_url": "https://developer.odpt.org/terms", "confirmed_date": "2026-08-21"}],
    )
    monkeypatch.setattr(lts, "_odpt_api_key", lambda: "dummy-key-for-test")
    monkeypatch.setattr(lts, "_fetch_odpt_train_information", lambda api_key, base_url: [_RAW_TOKYOMETRO, _RAW_UNKNOWN_OPERATOR])

    items = asyncio.run(lts._fetch_all_disruptions())
    operator_ids = {i["operator_id"] for i in items}
    assert "odpt.Operator:SomeUnknownRailway" not in operator_ids
    assert "odpt.Operator:TokyoMetro" in operator_ids
    assert len(items) == 1


# ---------------------------------------------------------------------------
# 7. UIへprovider・terms・timestampが表示される（item内へのlicense情報付与を確認）
# ---------------------------------------------------------------------------

def test_odpt_a07_item_carries_provider_terms_timestamp_for_ui(tmp_path, monkeypatch):
    lts = _import_fresh_live_train_service(
        monkeypatch, tmp_path,
        [{"operator_id": "TokyoMetro", "license": "公共交通オープンデータ基本ライセンス", "terms_url": "https://developer.odpt.org/terms", "confirmed_date": "2026-08-21"}],
    )
    monkeypatch.setattr(lts, "_odpt_api_key", lambda: "dummy-key-for-test")
    monkeypatch.setattr(lts, "_fetch_odpt_train_information", lambda api_key, base_url: [_RAW_TOKYOMETRO])

    items = asyncio.run(lts._fetch_all_disruptions())
    assert len(items) == 1
    item = items[0]
    assert item["operator_name"]  # provider
    assert item["license"] == "公共交通オープンデータ基本ライセンス"
    assert item["license_terms_url"] == "https://developer.odpt.org/terms"
    assert item["license_confirmed_at"] == "2026-08-21"
    assert item["updated_at"]  # timestamp


# ---------------------------------------------------------------------------
# 8. API failure時に古い情報を現在情報として断定しない（stale flag確認）
# ---------------------------------------------------------------------------

def test_odpt_a08_api_failure_marks_result_stale_not_current(tmp_path, monkeypatch):
    lts = _import_fresh_live_train_service(
        monkeypatch, tmp_path,
        [{"operator_id": "TokyoMetro", "license": "X", "terms_url": "https://x", "confirmed_date": "2026-08-21"}],
    )
    monkeypatch.setattr(lts, "_odpt_api_key", lambda: "dummy-key-for-test")

    # 1回目: 正常取得してcacheへ積む
    monkeypatch.setattr(lts, "_fetch_odpt_train_information", lambda api_key, base_url: [_RAW_TOKYOMETRO])
    first = asyncio.run(lts.build_train_summary())
    assert first["status"] == "ok"
    assert first["stale"] is False

    # cache TTLを強制的に過去へ戻し、2回目はAPI failureを起こす
    lts._cache_at -= (lts._CACHE_TTL + 1)

    def _raise(*args, **kwargs):
        raise lts.URLError("simulated network failure")

    monkeypatch.setattr(lts, "_fetch_odpt_train_information", _raise)
    second = asyncio.run(lts.build_train_summary())
    # stale=Trueが「これは最新取得に失敗したcached情報である」という明示flagであり、
    # 呼び出し側（UI）はこれを見て「現在情報」として断定しない設計になっている。
    assert second["stale"] is True


# ---------------------------------------------------------------------------
# 9. token / response全量をlogへ出さない
# ---------------------------------------------------------------------------

def test_odpt_a09_api_key_not_logged(tmp_path, monkeypatch, caplog):
    lts = _import_fresh_live_train_service(
        monkeypatch, tmp_path,
        [{"operator_id": "TokyoMetro", "license": "X", "terms_url": "https://x", "confirmed_date": "2026-08-21"}],
    )
    secret_key = "SUPER-SECRET-ODPT-TOKEN-VALUE-12345"
    monkeypatch.setattr(lts, "_odpt_api_key", lambda: secret_key)
    monkeypatch.setattr(lts, "_fetch_odpt_train_information", lambda api_key, base_url: [_RAW_TOKYOMETRO, _RAW_UNKNOWN_OPERATOR])

    with caplog.at_level(logging.DEBUG):
        asyncio.run(lts._fetch_all_disruptions())

    all_log_text = "\n".join(r.message for r in caplog.records)
    assert secret_key not in all_log_text
    # raw payload全量（説明文本文等）もログへ出していないことを確認
    assert "銀座線は遅延しています" not in all_log_text


# ---------------------------------------------------------------------------
# 10. allowlist空の場合にfail-closed
# ---------------------------------------------------------------------------

def test_odpt_a10_empty_allowlist_denies_all(tmp_path, monkeypatch):
    monkeypatch.setattr(odpt_allowlist, "_DATA_PATH", _write_allowlist(tmp_path, []))
    assert odpt_allowlist.is_operator_allowed("TokyoMetro") is False
    assert odpt_allowlist.get_allowed_operator_ids() == set()


def test_odpt_a10b_malformed_json_fail_closed(tmp_path, monkeypatch, caplog):
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(odpt_allowlist, "_DATA_PATH", bad_path)
    with caplog.at_level(logging.ERROR):
        entries = odpt_allowlist.get_allowlist_entries()
    assert entries == []
    assert odpt_allowlist.is_operator_allowed("TokyoMetro") is False


def test_odpt_a10c_missing_file_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(odpt_allowlist, "_DATA_PATH", tmp_path / "does_not_exist.json")
    assert odpt_allowlist.get_allowlist_entries() == []
    assert odpt_allowlist.is_operator_allowed("TokyoMetro") is False

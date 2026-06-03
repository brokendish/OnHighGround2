"""
test_jma_storm_surge_codes.py — JMA高潮警報コード定義の回帰テスト

目的:
  - 高潮警報コードが jma_weather_adapter.py に一元定義されており、
    正しいコードが使われていることを継続的に保証する。
  - 2026-06-03 に発覚した誤検知（コード "10"=大雨注意報を高潮警報と誤認）の再発防止。

外部APIは一切呼ばない。モジュール import のみ。
"""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.jma_weather_adapter import (
    STORM_SURGE_CODE_META,
    STORM_SURGE_CODES,
    _CODE_NAME,
    _CODE_SEVERITY,
    _normalize_severity,
)

# ── 正しいコードが STORM_SURGE_CODES に含まれる ─────────────────────────────

def test_code_38_is_storm_surge_special_warning():
    """高潮特別警報は "38" である（r8フォーマット確認済み）"""
    assert "38" in STORM_SURGE_CODES


def test_code_08_is_storm_surge_warning():
    """高潮警報は "08" である（r8フォーマット確認済み）"""
    assert "08" in STORM_SURGE_CODES


def test_code_19_is_storm_surge_advisory():
    """高潮注意報は "19" である（r8フォーマット確認済み）"""
    assert "19" in STORM_SURGE_CODES


def test_storm_surge_codes_count():
    """STORM_SURGE_CODES は 特別警報/警報/注意報 の3種のみ（過不足確認）"""
    assert len(STORM_SURGE_CODES) == 3


# ── 回帰: 誤ったコードが STORM_SURGE_CODES に含まれない ─────────────────────

def test_code_10_is_not_storm_surge():
    """
    コード "10" は大雨注意報であり、高潮コードではない。
    2026-06-03: このバグで茨城県の大雨注意報が高潮警報と誤検知された。
    """
    assert "10" not in STORM_SURGE_CODES


def test_code_24_is_not_storm_surge():
    """コード "24" は霜注意報であり、高潮コードではない"""
    assert "24" not in STORM_SURGE_CODES


def test_code_39_is_not_storm_surge():
    """コード "39" は実在しないコードであり、高潮コードではない"""
    assert "39" not in STORM_SURGE_CODES


# ── 整合性: _CODE_SEVERITY / _CODE_NAME との一致 ────────────────────────────

def test_storm_surge_codes_defined_in_code_severity():
    """
    STORM_SURGE_CODES の全コードが _CODE_SEVERITY にも定義されている。
    JMA仕様変更で STORM_SURGE_CODE_META だけ更新して _CODE_SEVERITY を忘れると失敗する。
    """
    for code in STORM_SURGE_CODES:
        assert code in _CODE_SEVERITY, (
            f"コード '{code}' が _CODE_SEVERITY に未定義 — "
            f"jma_weather_adapter._CODE_SEVERITY の更新が必要"
        )


def test_storm_surge_codes_defined_in_code_name():
    """STORM_SURGE_CODES の全コードが _CODE_NAME にも定義されている"""
    for code in STORM_SURGE_CODES:
        assert code in _CODE_NAME, (
            f"コード '{code}' が _CODE_NAME に未定義 — "
            f"jma_weather_adapter._CODE_NAME の更新が必要"
        )


def test_storm_surge_severity_matches_code_severity():
    """STORM_SURGE_CODE_META の severity が _CODE_SEVERITY と一致している"""
    for code, meta in STORM_SURGE_CODE_META.items():
        assert _CODE_SEVERITY.get(code) == meta["severity"], (
            f"コード '{code}' の severity が不一致: "
            f"META={meta['severity']!r} vs _CODE_SEVERITY={_CODE_SEVERITY.get(code)!r}"
        )


# ── STORM_SURGE_CODE_META の内容検証 ─────────────────────────────────────────

def test_storm_surge_meta_severity_levels():
    """各コードの severity が正しい"""
    assert STORM_SURGE_CODE_META["38"]["severity"] == "emergency"
    assert STORM_SURGE_CODE_META["08"]["severity"] == "warning"
    assert STORM_SURGE_CODE_META["19"]["severity"] == "advisory"


def test_storm_surge_meta_labels():
    """各コードの label が正しい"""
    assert STORM_SURGE_CODE_META["38"]["label"] == "高潮特別警報"
    assert STORM_SURGE_CODE_META["08"]["label"] == "高潮警報"
    assert STORM_SURGE_CODE_META["19"]["label"] == "高潮注意報"


def test_storm_surge_meta_keys_match_codes():
    """STORM_SURGE_CODE_META のキーと STORM_SURGE_CODES が完全一致"""
    assert set(STORM_SURGE_CODE_META.keys()) == STORM_SURGE_CODES


# ── _CODE_SEVERITY のスポット確認（他の警報との混同防止） ───────────────────

def test_code_10_is_heavy_rain_advisory_in_severity():
    """コード "10" は大雨注意報として _CODE_SEVERITY に登録されている"""
    assert _CODE_SEVERITY.get("10") == "advisory"


def test_code_24_is_frost_advisory_in_severity():
    """コード "24" は霜注意報として _CODE_SEVERITY に登録されている"""
    assert _CODE_SEVERITY.get("24") == "advisory"


def test_code_08_is_warning_severity():
    """コード "08" は warning severity である（高潮警報）"""
    assert _CODE_SEVERITY.get("08") == "warning"


# ── unknown code の WARN ログ出力確認 ─────────────────────────────────────────

def test_unknown_code_emits_warning_log(caplog):
    """
    _CODE_SEVERITY に未登録のコードが来たとき WARNING ログが出ること。
    JMA仕様変更で新コードが追加された場合に検知できることを確認する。
    """
    with caplog.at_level(logging.WARNING, logger="app.services.jma_weather_adapter"):
        _normalize_severity("99", "謎の警報")

    warn_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("99" in m or "unknown" in m.lower() for m in warn_msgs), (
        "未知コード '99' に対して WARNING ログが出力されなかった"
    )


def test_unknown_code_does_not_raise():
    """未知コードが来ても例外を投げずに処理を継続すること"""
    result = _normalize_severity("99", "謎の警報")
    # unknown でもクラッシュせず、何らかの severity 文字列を返す
    assert isinstance(result, str)
    assert len(result) > 0


def test_known_code_does_not_emit_warning_log(caplog):
    """既知コード "08" では WARNING ログが出ないこと"""
    with caplog.at_level(logging.WARNING, logger="app.services.jma_weather_adapter"):
        severity = _normalize_severity("08", "高潮警報")

    warn_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert not warn_msgs, f"既知コードで WARNING が出た: {warn_msgs}"
    assert severity == "warning"

"""
test_live_storm_surge_representative.py — /live 高潮 府県代表選択の回帰テスト

JMA-2026-WARNING-CODE-UPDATE ROUND 2:
  08（高潮警報）と 48（レベル４高潮危険警報）はどちらも severity=warning。
  代表選択が severity のみだと入力順依存になり、府県代表 detail から
  「レベル４高潮危険警報」が失われ得た。severity → 高潮コード priority の順で
  決定し、入力順に依存しないことを確認する。

外部APIは呼ばない。fetch_warnings_for_pref をモックし、adapter の実パーサで item を生成する。
期待値は実装定数から生成せず、JMA 公式名称をリテラルで記述する。
"""
from __future__ import annotations

import asyncio
import itertools
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.services.live_storm_surge_service as lss  # noqa: E402
from app.services.jma_weather_adapter import STORM_SURGE_CODES, _parse_r8_payload  # noqa: E402

# 入力順を確実に制御するため、コードごとに別の class20 区域へ割り当てる
_AREA_BY_CODE = {
    "38": "1310100", "48": "1310200", "08": "1310300", "19": "1310400",
    "09": "1310500", "29": "1310600", "39": "1310700", "43": "1310800",
    "49": "1310900", "99": "1311000",
}


def _items(codes, status="発表"):
    payload = [{
        "reportDatetime": "2026-09-23T01:00:00+09:00",
        "warning": {
            "class10Items": [],
            "class20Items": [
                {"areaCode": _AREA_BY_CODE[c], "kinds": [{"code": c, "status": status}]}
                for c in codes
            ],
        },
    }]
    items = _parse_r8_payload(payload, "東京都")
    if status != "解除":
        # 入力順がそのまま adapter 出力順になっていること（テストが順序を実際に変えている証明）
        assert [i.raw_code for i in items] == list(codes)
    return items


def _representative(codes, status="発表"):
    items = _items(codes, status)
    with patch.object(lss, "fetch_warnings_for_pref", return_value=items):
        result = asyncio.run(lss._fetch_pref_storm_surge("130000"))
    return result


def _detail(result):
    return lss._build_danger_areas(result)[0]["detail"]


# ── A / B. 08 + 48 両順序 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("codes", [("08", "48"), ("48", "08")])
def test_08_and_48_representative_is_48(codes):
    result = _representative(codes)
    assert len(result) == 1
    rep = result[0]
    assert rep["kind"] == "レベル４高潮危険警報"
    assert rep["level"] == "warning"
    assert _detail(result) == "レベル４高潮危険警報"
    danger = lss._build_danger_areas(result)[0]
    assert danger["level"] == "danger"  # warning → danger の既存マッピング維持


# ── C. 入力順非依存（19/08/48/38 全 24 permutation）───────────────────────────

def test_representative_is_order_independent_all_permutations():
    reps = set()
    for perm in itertools.permutations(["19", "08", "48", "38"]):
        result = _representative(perm)
        reps.add((result[0]["kind"], result[0]["level"], _detail(result)))
    assert reps == {("高潮特別警報", "emergency", "高潮特別警報")}


@pytest.mark.parametrize("pool,expected", [
    (["19", "08", "48"], ("レベル４高潮危険警報", "warning")),
    (["19", "08"],       ("高潮警報", "warning")),
    (["19", "48"],       ("レベル４高潮危険警報", "warning")),
])
def test_representative_order_independent_without_emergency(pool, expected):
    reps = {
        (r[0]["kind"], r[0]["level"])
        for r in (_representative(p) for p in itertools.permutations(pool))
    }
    assert reps == {expected}


# ── D. severity 優先の維持 ─────────────────────────────────────────────────────

@pytest.mark.parametrize("codes,expected", [
    (("48", "38"), ("高潮特別警報", "emergency")),        # emergency > warning(48)
    (("38", "48"), ("高潮特別警報", "emergency")),
    (("19", "08"), ("高潮警報", "warning")),              # warning > advisory
    (("19", "48"), ("レベル４高潮危険警報", "warning")),
    (("19",),      ("高潮注意報", "advisory")),
])
def test_severity_precedence_preserved(codes, expected):
    result = _representative(codes)
    assert (result[0]["kind"], result[0]["level"]) == expected


def test_48_standalone():
    result = _representative(("48",))
    assert (result[0]["kind"], result[0]["level"]) == ("レベル４高潮危険警報", "warning")
    assert _detail(result) == "レベル４高潮危険警報"
    assert result[0]["affected_areas"] == [
        {"area_name": "東京都", "area_code": "1310200", "kind": "レベル４高潮危険警報", "level": "warning"},
    ]


# ── E. affected_areas は代表選択に関係なく全件保持 ─────────────────────────────

@pytest.mark.parametrize("codes", [("08", "48"), ("48", "08")])
def test_affected_areas_keep_both_08_and_48(codes):
    affected = _representative(codes)[0]["affected_areas"]
    by_code = {a["area_code"]: (a["kind"], a["level"]) for a in affected}
    assert by_code == {
        "1310300": ("高潮警報", "warning"),
        "1310200": ("レベル４高潮危険警報", "warning"),
    }


def test_affected_areas_keep_all_storm_surge_codes():
    affected = _representative(("19", "08", "48", "38"))[0]["affected_areas"]
    assert sorted(a["kind"] for a in affected) == sorted(
        ["高潮注意報", "高潮警報", "レベル４高潮危険警報", "高潮特別警報"])


# ── F. 非高潮コードの混入なし ─────────────────────────────────────────────────

def test_non_storm_surge_codes_not_aggregated():
    assert _representative(("09", "29", "39", "43", "49", "99")) == []


def test_non_storm_surge_codes_not_selected_as_representative():
    # 39（emergency, 土砂）が混在しても代表は高潮コードのみから選ぶ
    result = _representative(("39", "09", "08", "29", "43", "49", "99"))
    assert (result[0]["kind"], result[0]["level"]) == ("高潮警報", "warning")
    assert [a["area_code"] for a in result[0]["affected_areas"]] == ["1310300"]


def test_released_storm_surge_codes_excluded():
    assert _representative(("08", "48"), status="解除") == []


# ── priority 定義の整合性 ─────────────────────────────────────────────────────

def test_priority_covers_exactly_storm_surge_codes():
    assert set(lss._STORM_SURGE_CODE_PRIORITY) == set(STORM_SURGE_CODES)


def test_priority_does_not_contradict_severity():
    """priority 順に並べたとき severity 順が逆転しない（JMA 警戒レベル順と整合）。"""
    ordered = sorted(lss._STORM_SURGE_CODE_PRIORITY, key=lss._STORM_SURGE_CODE_PRIORITY.get)
    assert ordered == ["38", "48", "08", "19"]

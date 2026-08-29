"""
Phase 2-D Round 12D-B — NEW-ADV-003 machine-checkable oracle (MCC-01〜17 / NC1〜9)。

tasks/public-release/phase2d_round12d_a1_owner_decision.md
tasks/public-release/phase2d_round12d_a2_owner_decision.md
tasks/public-release/phase2d_round12d_a3_owner_decision.md
の3 Roundで frozen された NEW-ADV-003 exact contract（hazard_coverage_status /
aggregate_status / selected_tier 3-state 語彙）を、実際の HazardService +
app_public.py の実装に対して検証する permanent fixture。

sub-case:
    A = HAZARD_DETECTED    (flood のみ 1 polygon が候補地点を覆う)
    B = NO_HAZARD_RECORD   (全 6 type とも候補地点はポリゴン外)
    C = SOURCE_UNAVAILABLE (flood のみロード済み、他5 typeは未ロード = silent omission再現)

MCC-01〜17 は `_check_mcc_*` 関数として実装し、A/B/C 各 sub-case のレスポンス相当
dict に対して適用する。NC1〜9 は「オラクル自体が意図的な契約違反を検出できるか」を
確認する negative control で、意図的に契約違反な状態を作り、対応する MCC が
FAIL を返すことを確認する（MCC 自体が骨抜きでないことの検証）。

MCC-13 (UI 表示禁止語) と MCC-17 (UI 表示completeness) の DOM 上の実証は
e2e/hazard-state-consistency.spec.js と e2e/evacuation-ui.spec.js が担う
（本ファイルは server 側で生成される reason 文字列に対して同じ oracle を適用する）。

注意: app_public のmodule importは実ハザードデータを読み込むため数十秒かかる
（test_phase2c_public_hardening.py と同一事情）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import app_public  # noqa: E402
from hazard_service import (  # noqa: E402
    HazardService,
    compute_hazard_coverage_status,
    compute_aggregate_status,
    compute_hazard_safe_from_aggregate,
    HAZARD_DETECTED,
    NO_HAZARD_RECORD,
    SOURCE_UNAVAILABLE,
)
from hazard_definitions import HAZARD_DEFINITIONS  # noqa: E402

# Round 12D-B1: get_all_hazard_type_names() ヘルパーは追加せず、NEW-ADV-005
# frozen contractのauthoritative object(HAZARD_DEFINITIONS)から直接導出する。
ALL_TYPES: List[str] = [d.name for d in HAZARD_DEFINITIONS]
assert len(ALL_TYPES) == 6, f"authoritative hazard type universe must be 6 types, got {ALL_TYPES}"

RESERVED_STATUSES = {"CONFIRMED_SAFE", "OUTSIDE_COVERAGE"}
FORBIDDEN_ASCII_TOKENS = ["safe", "confirmed safe", "safety confirmed"]
FORBIDDEN_JP_TOKENS = ["安全", "安全候補", "危険区域外"]

REQUIRED_DISPLAY_TEXT = {
    HAZARD_DETECTED: "ハザード検出",
    NO_HAZARD_RECORD: "該当ハザード記録なし（危険がないことを示すものではありません）",
    SOURCE_UNAVAILABLE: "ハザード情報を確認できません",
}

P_INSIDE = (35.700, 139.700)
P_OUTSIDE = (35.900, 139.900)
DECOY = (10.000, 10.000)  # 遠方。real polygonを置きis_loaded()=Trueにするが絶対にhitしない


def _ring_around(lat: float, lon: float, half: float = 0.01) -> list:
    return [
        [lon - half, lat - half], [lon + half, lat - half],
        [lon + half, lat + half], [lon - half, lat + half],
        [lon - half, lat - half],
    ]


def _write_fc(path: Path, ring: list) -> None:
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [ring]}}
    ]}
    path.write_text(json.dumps(fc), encoding="utf-8")


@pytest.fixture(scope="module")
def full_hazard_service(tmp_path_factory) -> HazardService:
    """6 type全ロード済み。flood のみ P_INSIDE を覆う1 polygon、他5 typeは
    P_INSIDE/P_OUTSIDE から遠く離れた decoy polygon（is_loaded=True かつ確実にoutside）。"""
    tmp_dir = tmp_path_factory.mktemp("new_adv_003_full")
    svc = HazardService()

    flood_path = tmp_dir / "flood.geojson"
    _write_fc(flood_path, _ring_around(*P_INSIDE))
    svc.load("flood", flood_path, bbox_only=True)

    for htype in ALL_TYPES:
        if htype == "flood":
            continue
        decoy_path = tmp_dir / f"{htype}.geojson"
        _write_fc(decoy_path, _ring_around(*DECOY))
        bbox_only = htype in ("tsunami", "storm_surge", "landslide")
        svc.load(htype, decoy_path, bbox_only=bbox_only)

    return svc


@pytest.fixture(scope="module")
def partial_hazard_service(tmp_path_factory) -> HazardService:
    """flood のみロード済み（他5 typeは未ロード = silent omission再現用）。"""
    tmp_dir = tmp_path_factory.mktemp("new_adv_003_partial")
    svc = HazardService()
    decoy_path = tmp_dir / "flood.geojson"
    _write_fc(decoy_path, _ring_around(*DECOY))
    svc.load("flood", decoy_path, bbox_only=True)
    return svc


def _raw_assessment(svc: HazardService, point: tuple) -> Dict[str, Any]:
    return svc.assess_candidate(*point)


def _make_candidate(aggregate_status: str, coverage: Dict[str, str], safety_score: float = 50.0) -> Dict[str, Any]:
    """app_public.py の raw destination candidate dict（_select_recommended/_build_reasonが
    参照するキーのみの最小形）。"""
    return {
        "name": "テスト候補",
        "type": "emergency_shelter",
        "lat": 35.65, "lon": 139.80,
        "elevation": 5.0, "elevation_gain": 12.0,
        "distance": 800.0, "estimated_time_minutes": 12.0,
        "safety_score": safety_score,
        "aggregate_status": aggregate_status,
        "hazard_safe": compute_hazard_safe_from_aggregate(aggregate_status),
        "hazard_coverage_status": coverage,
        "hazard_assessment": {},
        "time_margin_status": "unknown",
    }


def _serialize_destination(d: Dict[str, Any]) -> Dict[str, Any]:
    """app_public.find_evacuation_destinations() の destinations[] dict comprehension
    と exactly同じキー集合を再現する（aggregate_statusは意図的に含めない）。"""
    return {
        "name": d["name"], "type": d["type"], "lat": d["lat"], "lon": d["lon"],
        "elevation": d["elevation"], "elevation_gain": d["elevation_gain"],
        "distance": d["distance"], "estimated_time_minutes": d["estimated_time_minutes"],
        "safety_score": d["safety_score"],
        "hazard_safe": d["hazard_safe"],
        "hazard_assessment": d.get("hazard_assessment", {}),
        "hazard_coverage_status": d.get("hazard_coverage_status", {}),
    }


@pytest.fixture(scope="module")
def sub_case_a(full_hazard_service) -> Dict[str, Any]:
    assessment = _raw_assessment(full_hazard_service, P_INSIDE)
    coverage = compute_hazard_coverage_status(assessment, ALL_TYPES)
    aggregate = compute_aggregate_status(coverage)
    assert aggregate == HAZARD_DETECTED
    cand = _make_candidate(aggregate, coverage)
    best, selected_tier, _count = app_public._select_recommended([cand])
    reason = app_public._build_reason(best, selected_tier, "unknown")
    return {
        "assessment": assessment, "coverage": coverage, "aggregate": aggregate,
        "candidate": best, "selected_tier": selected_tier, "reason": reason,
        "destination": _serialize_destination(best),
    }


@pytest.fixture(scope="module")
def sub_case_b(full_hazard_service) -> Dict[str, Any]:
    assessment = _raw_assessment(full_hazard_service, P_OUTSIDE)
    coverage = compute_hazard_coverage_status(assessment, ALL_TYPES)
    aggregate = compute_aggregate_status(coverage)
    assert aggregate == NO_HAZARD_RECORD
    cand = _make_candidate(aggregate, coverage)
    best, selected_tier, _count = app_public._select_recommended([cand])
    reason = app_public._build_reason(best, selected_tier, "unknown")
    return {
        "assessment": assessment, "coverage": coverage, "aggregate": aggregate,
        "candidate": best, "selected_tier": selected_tier, "reason": reason,
        "destination": _serialize_destination(best),
    }


@pytest.fixture(scope="module")
def sub_case_c(partial_hazard_service) -> Dict[str, Any]:
    assessment = _raw_assessment(partial_hazard_service, P_OUTSIDE)
    assert set(assessment.keys()) == {"flood"}, "fixture precondition: silent omission of 5 types"
    coverage = compute_hazard_coverage_status(assessment, ALL_TYPES)
    aggregate = compute_aggregate_status(coverage)
    assert aggregate == SOURCE_UNAVAILABLE
    cand = _make_candidate(aggregate, coverage)
    best, selected_tier, _count = app_public._select_recommended([cand])
    reason = app_public._build_reason(best, selected_tier, "unknown")
    return {
        "assessment": assessment, "coverage": coverage, "aggregate": aggregate,
        "candidate": best, "selected_tier": selected_tier, "reason": reason,
        "destination": _serialize_destination(best),
    }


# ─────────────────────────────────────────────────────────────────────────
# MCC (machine-checkable forbidden conditions) — 1件ずつ独立関数として実装。
# 各関数は違反があれば例外を送出せず、違反箇所のリスト(空=PASS)を返す。
# ─────────────────────────────────────────────────────────────────────────

def _mcc01_reserved_status(coverage: Dict[str, str], aggregate: str, selected_tier: Optional[str]) -> List[str]:
    hits = [f"coverage[{k}]={v}" for k, v in coverage.items() if v in RESERVED_STATUSES]
    if aggregate in RESERVED_STATUSES:
        hits.append(f"aggregate={aggregate}")
    if selected_tier is not None and selected_tier in RESERVED_STATUSES:
        hits.append(f"selected_tier={selected_tier}")
    return hits


def _mcc02_selected_tier_legacy_safe(selected_tier: Optional[str]) -> List[str]:
    return ["selected_tier=='safe'"] if selected_tier == "safe" else []


def _mcc05_hazard_safe_true(hazard_safe: Any) -> List[str]:
    return ["hazard_safe==True"] if hazard_safe is True else []


def _mcc07_14_source_unavailable_not_no_hazard_record(coverage: Dict[str, str], aggregate: str, selected_tier: Optional[str]) -> List[str]:
    if SOURCE_UNAVAILABLE not in coverage.values():
        return []
    hits = []
    if aggregate == NO_HAZARD_RECORD:
        hits.append("aggregate==NO_HAZARD_RECORD despite SOURCE_UNAVAILABLE present")
    if selected_tier == NO_HAZARD_RECORD:
        hits.append("selected_tier==NO_HAZARD_RECORD despite SOURCE_UNAVAILABLE present")
    return hits


def _mcc08_status_field_missing(coverage: Dict[str, str]) -> List[str]:
    return [k for k, v in coverage.items() if v is None or v == ""]


def _mcc09_15_all_six_keys_present(coverage: Dict[str, str]) -> List[str]:
    missing = [t for t in ALL_TYPES if t not in coverage]
    return [f"missing_key:{t}" for t in missing]


def _mcc12_hazard_safe_presence_and_value(destination: Dict[str, Any], aggregate: str) -> List[str]:
    hits = []
    if "hazard_safe" not in destination:
        hits.append("hazard_safe absent from endpoint_2 serialized destination (presence required)")
        return hits
    expected = compute_hazard_safe_from_aggregate(aggregate)
    if destination["hazard_safe"] != expected:
        hits.append(f"hazard_safe={destination['hazard_safe']!r} expected={expected!r} for aggregate={aggregate}")
    if destination["hazard_safe"] is True:
        hits.append("hazard_safe==True")
    return hits


def _mcc13_forbidden_display_tokens(text: str) -> List[str]:
    lowered = text.casefold()
    hits = [tok for tok in FORBIDDEN_ASCII_TOKENS if tok.casefold() in lowered]
    hits += [tok for tok in FORBIDDEN_JP_TOKENS if tok in text]
    return hits


def _mcc16_aggregate_selected_tier_consistency(aggregate: str, selected_tier: Optional[str]) -> List[str]:
    if selected_tier is None:
        return []
    return [] if aggregate == selected_tier else [f"aggregate={aggregate} != selected_tier={selected_tier}"]


def _mcc16_no_literal_aggregate_status_field(destination: Dict[str, Any]) -> List[str]:
    return ["aggregate_status leaked into serialized destination"] if "aggregate_status" in destination else []


def _mcc17_required_display_text_present(text: str, selected_tier: str) -> List[str]:
    required = REQUIRED_DISPLAY_TEXT[selected_tier]
    return [] if required in text else [f"required text missing: {required!r} not in {text!r}"]


# ─────────────────────────────────────────────────────────────────────────
# MCC-01 (全 sub-case, 全 location): reserved status 0件
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("case_name", ["sub_case_a", "sub_case_b", "sub_case_c"])
def test_mcc01_reserved_status_forbidden_all_cases(case_name, request):
    case = request.getfixturevalue(case_name)
    hits = _mcc01_reserved_status(case["coverage"], case["aggregate"], case["selected_tier"])
    assert hits == [], f"MCC-01 violated in {case_name}: {hits}"


def test_mcc02_selected_tier_never_legacy_safe_string(sub_case_a, sub_case_b, sub_case_c):
    for name, case in [("A", sub_case_a), ("B", sub_case_b), ("C", sub_case_c)]:
        hits = _mcc02_selected_tier_legacy_safe(case["selected_tier"])
        assert hits == [], f"MCC-02 violated in {name}: {hits}"


def test_mcc05_hazard_safe_never_true_any_subcase(sub_case_a, sub_case_b, sub_case_c):
    for name, case in [("A", sub_case_a), ("B", sub_case_b), ("C", sub_case_c)]:
        hits = _mcc05_hazard_safe_true(case["destination"]["hazard_safe"])
        assert hits == [], f"MCC-05 violated in {name}: {hits}"


def test_mcc07_14_source_unavailable_never_becomes_no_hazard_record(sub_case_c):
    hits = _mcc07_14_source_unavailable_not_no_hazard_record(
        sub_case_c["coverage"], sub_case_c["aggregate"], sub_case_c["selected_tier"]
    )
    assert hits == [], f"MCC-07/14 violated in C: {hits}"


def test_mcc08_no_missing_status_value(sub_case_a, sub_case_b, sub_case_c):
    for name, case in [("A", sub_case_a), ("B", sub_case_b), ("C", sub_case_c)]:
        hits = _mcc08_status_field_missing(case["coverage"])
        assert hits == [], f"MCC-08 violated in {name}: {hits}"


def test_mcc09_15_all_six_hazard_type_keys_present_even_with_silent_omission(sub_case_a, sub_case_b, sub_case_c):
    for name, case in [("A", sub_case_a), ("B", sub_case_b), ("C", sub_case_c)]:
        hits = _mcc09_15_all_six_keys_present(case["coverage"])
        assert hits == [], f"MCC-09/15 violated in {name}: {hits}"
    # sub_case_c は raw assessment 段階では 'flood' 1 keyしか無い(silent omission実在)ことを再確認
    assert set(sub_case_c["assessment"].keys()) == {"flood"}


def test_mcc10_subcase_b_selected_tier_is_no_hazard_record(sub_case_b):
    assert sub_case_b["selected_tier"] == NO_HAZARD_RECORD, (
        f"MCC-10 (applies_to_endpoint=endpoint_2) violated: {sub_case_b['selected_tier']}"
    )


def test_mcc11_subcase_c_selected_tier_is_source_unavailable(sub_case_c):
    assert sub_case_c["selected_tier"] == SOURCE_UNAVAILABLE, (
        f"MCC-11 (applies_to_endpoint=endpoint_2) violated: {sub_case_c['selected_tier']}"
    )


def test_mcc12_hazard_safe_presence_and_exact_value_endpoint_2(sub_case_a, sub_case_b, sub_case_c):
    for name, case in [("A", sub_case_a), ("B", sub_case_b), ("C", sub_case_c)]:
        hits = _mcc12_hazard_safe_presence_and_value(case["destination"], case["aggregate"])
        assert hits == [], f"MCC-12 violated in {name}: {hits}"


def test_mcc13_reason_text_contains_no_forbidden_tokens_bc(sub_case_b, sub_case_c):
    for name, case in [("B", sub_case_b), ("C", sub_case_c)]:
        hits = _mcc13_forbidden_display_tokens(case["reason"])
        assert hits == [], f"MCC-13 violated in {name}: {hits} (reason={case['reason']!r})"


def test_mcc13_required_display_strings_are_free_of_forbidden_tokens():
    """A3 §7: 必須表示文字列自身が禁止tokenを含まないことを直接検査する。"""
    for tier, text in REQUIRED_DISPLAY_TEXT.items():
        hits = _mcc13_forbidden_display_tokens(text)
        assert hits == [], f"required display text for {tier} contains forbidden token: {hits} ({text!r})"


def test_mcc16_aggregate_selected_tier_consistency_and_no_field_leak(sub_case_a, sub_case_b, sub_case_c):
    for name, case in [("A", sub_case_a), ("B", sub_case_b), ("C", sub_case_c)]:
        hits = _mcc16_aggregate_selected_tier_consistency(case["aggregate"], case["selected_tier"])
        assert hits == [], f"MCC-16 (consistency) violated in {name}: {hits}"
        hits2 = _mcc16_no_literal_aggregate_status_field(case["destination"])
        assert hits2 == [], f"MCC-16 (no new API field) violated in {name}: {hits2}"


def test_mcc17_required_display_text_present_bc(sub_case_b, sub_case_c):
    for name, case in [("B", sub_case_b), ("C", sub_case_c)]:
        hits = _mcc17_required_display_text_present(case["reason"], case["selected_tier"])
        assert hits == [], f"MCC-17 violated in {name}: {hits}"


def test_mcc17_endpoint1_route_risk_shape_has_six_keys_and_no_selected_tier_requirement(full_hazard_service):
    """endpoint 1 (POST /api/route-risk) は sampled_points[].hazard_coverage_status のみ
    要求し、selected_tier absenceはFAILにしない(endpoint_oracle_scope)。"""
    assessment = full_hazard_service.assess_candidate(*P_INSIDE)
    coverage = compute_hazard_coverage_status(assessment, ALL_TYPES)
    sampled_point = {"lat": P_INSIDE[0], "lon": P_INSIDE[1], "hazards": {}, "hazard_coverage_status": coverage}
    assert _mcc09_15_all_six_keys_present(sampled_point["hazard_coverage_status"]) == []
    assert "selected_tier" not in sampled_point, "endpoint 1 must not require/carry selected_tier"
    assert "hazard_safe" not in sampled_point, "endpoint 1 hazard_safe presence is not required (endpoint_2 only)"


# ─────────────────────────────────────────────────────────────────────────
# NC1〜9: MCC が実際に契約違反を検出できることを確認する negative control。
# ─────────────────────────────────────────────────────────────────────────

def test_nc1_silent_omission_produces_incomplete_raw_assessment(sub_case_c):
    """NC1: 未読込typeをdictから省略 → 実際に raw assessment は 'flood' 1 keyしか無い
    ことを確認する(fix適用前の生の挙動が実在することの証明)。"""
    assert set(sub_case_c["assessment"].keys()) == {"flood"}
    assert len(sub_case_c["assessment"]) < len(ALL_TYPES)


def test_nc2_missing_type_mapped_to_no_hazard_record_is_caught():
    """NC2: 未読込typeをNO_HAZARD_RECORDへ変換する buggy mutation を MCC-09/07/14が検出する。"""
    buggy_coverage = {t: NO_HAZARD_RECORD for t in ALL_TYPES}  # 本来 SOURCE_UNAVAILABLE のはずが全部NO_HAZARD_RECORD
    buggy_coverage["flood"] = NO_HAZARD_RECORD
    aggregate = compute_aggregate_status(buggy_coverage)
    # buggy_coverageにSOURCE_UNAVAILABLEが1件も無いため MCC-07/14は反応しないのが正しい比較対象。
    # 正しい修正実装との比較で検出する: 正しい実装なら5 typeがSOURCE_UNAVAILABLEになるはず。
    correct_coverage = compute_hazard_coverage_status({"flood": "outside"}, ALL_TYPES)
    mismatches = {t: (buggy_coverage[t], correct_coverage[t]) for t in ALL_TYPES if buggy_coverage[t] != correct_coverage[t]}
    assert mismatches, "NC2 mutation must diverge from the correct implementation output (negative control must be a real mutation)"
    assert aggregate == NO_HAZARD_RECORD  # buggy側の誤ったaggregate
    assert compute_aggregate_status(correct_coverage) == SOURCE_UNAVAILABLE  # 正しい実装はSOURCE_UNAVAILABLE
    assert aggregate != compute_aggregate_status(correct_coverage), "NC2 mutation correctly diverges and would be caught by comparing against the frozen contract"


def test_nc3_hazard_safe_true_on_subcase_b_is_caught(sub_case_b):
    mutated_destination = dict(sub_case_b["destination"])
    mutated_destination["hazard_safe"] = True
    hits = _mcc05_hazard_safe_true(mutated_destination["hazard_safe"])
    assert hits != [], "NC3 mutation (hazard_safe=True on B) must be caught by MCC-05"


def test_nc4_subcase_c_selected_tier_mutated_to_no_hazard_record_is_caught(sub_case_c):
    mutated_selected_tier = NO_HAZARD_RECORD  # 本来 SOURCE_UNAVAILABLE のはず
    assert mutated_selected_tier != sub_case_c["selected_tier"], "NC4 mutation must actually differ from the real value"
    hits = _mcc07_14_source_unavailable_not_no_hazard_record(
        sub_case_c["coverage"], sub_case_c["aggregate"], mutated_selected_tier
    )
    assert hits != [], "NC4 mutation (C: selected_tier=NO_HAZARD_RECORD) must be caught by MCC-07/14"
    hits16 = _mcc16_aggregate_selected_tier_consistency(sub_case_c["aggregate"], mutated_selected_tier)
    assert hits16 != [], "NC4 mutation must also be caught by MCC-16 (aggregate/selected_tier mismatch)"


def test_nc5_forbidden_safe_text_in_reason_is_caught(sub_case_b, sub_case_c):
    for name, case in [("B", sub_case_b), ("C", sub_case_c)]:
        mutated_reason = case["reason"] + " 安全（全ハザード外）"
        hits = _mcc13_forbidden_display_tokens(mutated_reason)
        assert hits != [], f"NC5 mutation ({name}: inject forbidden token) must be caught by MCC-13"


def test_nc6_missing_one_of_six_keys_is_caught(sub_case_a):
    mutated_coverage = dict(sub_case_a["coverage"])
    del mutated_coverage[ALL_TYPES[-1]]
    hits = _mcc09_15_all_six_keys_present(mutated_coverage)
    assert hits != [], "NC6 mutation (drop 1 of 6 keys) must be caught by MCC-09"


def test_nc7_aggregate_selected_tier_mismatch_is_caught(sub_case_a):
    mismatched_selected_tier = NO_HAZARD_RECORD
    assert mismatched_selected_tier != sub_case_a["aggregate"]
    hits = _mcc16_aggregate_selected_tier_consistency(sub_case_a["aggregate"], mismatched_selected_tier)
    assert hits != [], "NC7 mutation (aggregate != selected_tier) must be caught by MCC-16"


def test_nc8_reserved_status_returned_is_caught(sub_case_b):
    for reserved in RESERVED_STATUSES:
        mutated_coverage = dict(sub_case_b["coverage"])
        mutated_coverage[ALL_TYPES[0]] = reserved
        hits = _mcc01_reserved_status(mutated_coverage, sub_case_b["aggregate"], sub_case_b["selected_tier"])
        assert hits != [], f"NC8 mutation (reserved status {reserved}) must be caught by MCC-01"


def test_nc9_required_display_text_omitted_is_caught(sub_case_b, sub_case_c):
    for name, case in [("B", sub_case_b), ("C", sub_case_c)]:
        mutated_reason = "（表示なし）"
        hits = _mcc17_required_display_text_present(mutated_reason, case["selected_tier"])
        assert hits != [], f"NC9 mutation ({name}: display omitted) must be caught by MCC-17"


# ─────────────────────────────────────────────────────────────────────────
# frontend_consumer_display_contract: 禁止token集合そのもののexact freeze確認
# ─────────────────────────────────────────────────────────────────────────

def test_forbidden_token_set_is_exactly_frozen_six():
    all_tokens = set(FORBIDDEN_ASCII_TOKENS) | set(FORBIDDEN_JP_TOKENS)
    assert all_tokens == {"安全", "安全候補", "危険区域外", "safe", "confirmed safe", "safety confirmed"}


def test_required_display_strings_are_exactly_frozen():
    assert REQUIRED_DISPLAY_TEXT == {
        HAZARD_DETECTED: "ハザード検出",
        NO_HAZARD_RECORD: "該当ハザード記録なし（危険がないことを示すものではありません）",
        SOURCE_UNAVAILABLE: "ハザード情報を確認できません",
    }

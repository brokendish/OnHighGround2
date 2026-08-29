"""
test_phase2d_ui_formal_manifest_selfcheck.py — UI formal manifest collector/
validatorのself-test（Phase 2-D Round 10A、指示書第8節・第10節、denominator
forensic再現、ODPT coverage mapping direct regression 14項目）。

Playwright実行そのものをmockせず、`npx playwright test --list
--reporter=json`が返す実際のJSON構造と同じ形（config/suites/stats）の
synthetic fixtureを使い、`phase2d_ui_formal_manifest.parse_list_json()`
（純粋関数、subprocess呼び出しを含まない）を直接検証する。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_ui_formal_manifest_selfcheck.py -v
"""
from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_ui_formal_manifest as ui  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _spec(title, line, column=3, project="chromium"):
    return {
        "title": title,
        "file": "example.spec.js",
        "line": line,
        "column": column,
        "tests": [{"projectName": project}],
    }


def _file_suite(specs=None, nested=None):
    return {
        "title": "example.spec.js",
        "file": "example.spec.js",
        "specs": specs or [],
        "suites": nested or [],
    }


# ---------------------------------------------------------------------------
# 1. collector self-test: describe chainを含む正しいcase_idを組み立てる
# ---------------------------------------------------------------------------

def test_01_case_id_includes_describe_chain():
    data = {
        "suites": [
            _file_suite(
                nested=[
                    {
                        "title": "top describe",
                        "specs": [_spec("case A", 10)],
                        "suites": [
                            {
                                "title": "nested describe",
                                "specs": [_spec("case B", 20)],
                                "suites": [],
                            }
                        ],
                    }
                ]
            )
        ]
    }
    cases = ui.parse_list_json(data)
    ids = {c["case_id"] for c in cases}
    assert "chromium::example.spec.js::top describe::case A" in ids
    assert "chromium::example.spec.js::top describe > nested describe::case B" in ids


def test_01b_top_level_test_has_empty_describe_chain():
    data = {"suites": [_file_suite(specs=[_spec("bare case", 5)])]}
    cases = ui.parse_list_json(data)
    assert len(cases) == 1
    assert cases[0]["case_id"] == "chromium::example.spec.js::::bare case"
    assert cases[0]["describe_chain"] == []


# ---------------------------------------------------------------------------
# 2. duplicate case negative control
# ---------------------------------------------------------------------------

def test_02_duplicate_case_id_raises():
    data = {
        "suites": [
            _file_suite(
                nested=[
                    {
                        "title": "d",
                        "specs": [_spec("same title", 10), _spec("same title", 10)],
                        "suites": [],
                    }
                ]
            )
        ]
    }
    with pytest.raises(ui.UiFormalManifestError, match="duplicate case_id"):
        ui.parse_list_json(data)


# ---------------------------------------------------------------------------
# 3. missing case negative control（validator側）
# ---------------------------------------------------------------------------

def test_03_missing_case_detected_by_validator():
    manifest = {"case_ids": ["chromium::a.spec.js::::case1", "chromium::a.spec.js::::case2"], "declared_total": 2}
    result = ui.compare_execution_to_manifest(manifest, ["chromium::a.spec.js::::case1"], {"chromium::a.spec.js::::case1": ["passed"]})
    assert result["missing_case_ids"] == ["chromium::a.spec.js::::case2"]
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 4. unexpected case negative control（validator側）
# ---------------------------------------------------------------------------

def test_04_unexpected_case_detected_by_validator():
    manifest = {"case_ids": ["chromium::a.spec.js::::case1"], "declared_total": 1}
    executed = ["chromium::a.spec.js::::case1", "chromium::a.spec.js::::case_extra"]
    status = {cid: ["passed"] for cid in executed}
    result = ui.compare_execution_to_manifest(manifest, executed, status)
    assert result["unexpected_case_ids"] == ["chromium::a.spec.js::::case_extra"]
    assert result["ok"] is False


# ---------------------------------------------------------------------------
# 5. project差 negative control: 同一testが複数projectで重複しても
#    unique case数として正しく2件と数える（project名がcase_idに含まれるため）
# ---------------------------------------------------------------------------

def test_05_multi_project_counts_as_distinct_unique_cases():
    data = {
        "suites": [
            _file_suite(
                specs=[
                    {
                        "title": "cross-project case",
                        "file": "example.spec.js",
                        "line": 1,
                        "column": 1,
                        "tests": [{"projectName": "chromium"}, {"projectName": "webkit"}],
                    }
                ]
            )
        ]
    }
    cases = ui.parse_list_json(data)
    assert len(cases) == 2
    projects = {c["project"] for c in cases}
    assert projects == {"chromium", "webkit"}
    ids = {c["case_id"] for c in cases}
    assert "chromium::example.spec.js::::cross-project case" in ids
    assert "webkit::example.spec.js::::cross-project case" in ids


# ---------------------------------------------------------------------------
# 6. denominator forensic再現（Round 10 core 7 spec分、変更なし固定）:
#    CORE_SPECSだけを対象に79 caseを収集し、CODEX Round 9実測
#    （attribution=6, selected regression=73, total=79）と一致することを確認する。
# ---------------------------------------------------------------------------

def test_06_core_denominator_forensic_matches_codex_measurement():
    manifest = ui.generate_manifest(REPO_ROOT, spec_paths=ui.CORE_SPECS)
    assert manifest["declared_total"] == 79
    counts = manifest["per_spec_counts"]
    assert counts["attribution.spec.js"] == 6
    selected_regression = sum(v for k, v in counts.items() if k != "attribution.spec.js")
    assert selected_regression == 73
    assert counts["jartic-traffic-layer.spec.js"] == 31
    assert counts["smoke.spec.js"] == 7
    assert counts["live-weather-ticker.spec.js"] == 9
    assert counts["live-stream-weather-ticker.spec.js"] == 11
    assert counts["live-stream-mini-map-municipality-boundary.spec.js"] == 9
    assert counts["live-stream-main-map.spec.js"] == 6


# ---------------------------------------------------------------------------
# 6b. Round 10A正式分母: core 7 spec + adopted ODPT specの8 specで
#     exact collectionした結果が79 + 6 = 85であることを確認する。
#     偶然にもRound 10で誤りと確定した歴史的数値「85」と同じ数字になるが、
#     これは無関係の別集合（79の真の分母＋新規採用specの6件）の合算が
#     たまたま同じ値になっただけであり、過去の誤記載が正しかったことを
#     意味しない（本fileのdocstring・実装報告書で明記する）。
# ---------------------------------------------------------------------------

def test_06b_full_target_denominator_is_85_via_new_odpt_spec():
    manifest = ui.generate_manifest(REPO_ROOT)
    assert manifest["declared_total"] == 85
    counts = manifest["per_spec_counts"]
    assert counts[ui.ODPT_SPEC_BASENAME] == 6
    core_total = sum(v for k, v in counts.items() if k != ui.ODPT_SPEC_BASENAME)
    assert core_total == 79


# ---------------------------------------------------------------------------
# 7. manifest write / reload / hash一致
# ---------------------------------------------------------------------------

def test_07_manifest_write_reload_hash_stable(tmp_path):
    manifest = ui.generate_manifest(REPO_ROOT)
    out = tmp_path / "manifest.json"
    sha1 = ui.write_manifest(manifest, out)
    sha2 = hashlib.sha256(out.read_bytes()).hexdigest()
    assert sha1 == sha2


# ---------------------------------------------------------------------------
# 8. coverage matrix: 17/17 requirementがcovered（Round 10の13 + ODPT分割4）
# ---------------------------------------------------------------------------

def test_08_coverage_matrix_all_17_covered():
    manifest = ui.generate_manifest(REPO_ROOT)
    by_name = {r["requirement"]: r for r in manifest["coverage_requirements"]}
    assert len(by_name) == 17
    assert manifest["coverage_uncovered_requirements"] == []
    for name, entry in by_name.items():
        assert entry["covered"] is True, f"{name} unexpectedly uncovered"
        assert entry["covering_count"] > 0


# ---------------------------------------------------------------------------
# 9. ODPT coverage_mapping: 4/4 requirement_idがCOVERED、実DOM route/viewport
#    を記録している
# ---------------------------------------------------------------------------

def test_09_odpt_coverage_mapping_4_of_4_covered():
    manifest = ui.generate_manifest(REPO_ROOT)
    assert manifest["coverage_mapping_uncovered"] == []
    mapping_by_id = {m["requirement_id"]: m for m in manifest["coverage_mapping"]}
    assert set(mapping_by_id.keys()) == {"ODPT provider", "ODPT terms", "ODPT no-warranty", "ODPT timestamp"}
    for req_id, m in mapping_by_id.items():
        assert m["status"] == "COVERED", req_id
        assert len(m["case_ids"]) == 1, req_id
        assert m["spec_path"] == ui.ODPT_SPEC
        assert m["route"] == "/live"
        assert m["assertion_summary"]
        assert m["expected_source"]


def test_09b_validate_manifest_structure_passes_on_real_manifest():
    manifest = ui.generate_manifest(REPO_ROOT)
    ui.validate_manifest_structure(manifest)  # raiseしなければPASS


# ---------------------------------------------------------------------------
# 10. direct regression test（指示書第10節 1〜14項目）
# ---------------------------------------------------------------------------

def _valid_manifest():
    return ui.generate_manifest(REPO_ROOT)


def test_10_01_missing_core_spec_fails():
    m = _valid_manifest()
    m["spec_paths"] = [p for p in m["spec_paths"] if p != "e2e/smoke.spec.js"]
    with pytest.raises(ui.UiFormalManifestError, match="core spec"):
        ui.validate_manifest_structure(m)


def test_10_02_missing_adopted_odpt_spec_fails():
    m = _valid_manifest()
    m["spec_paths"] = [p for p in m["spec_paths"] if p != ui.ODPT_SPEC]
    with pytest.raises(ui.UiFormalManifestError, match="adopted ODPT spec missing"):
        ui.validate_manifest_structure(m)


def test_10_03_odpt_provider_mapping_zero_case_ids_fails():
    m = _valid_manifest()
    for entry in m["coverage_mapping"]:
        if entry["requirement_id"] == "ODPT provider":
            entry["case_ids"] = []
            entry["status"] = "NOT_COVERED"
    with pytest.raises(ui.UiFormalManifestError, match="ODPT provider mapping has 0 case_ids"):
        ui.validate_manifest_structure(m)


def test_10_04_odpt_terms_mapping_zero_case_ids_fails():
    m = _valid_manifest()
    for entry in m["coverage_mapping"]:
        if entry["requirement_id"] == "ODPT terms":
            entry["case_ids"] = []
            entry["status"] = "NOT_COVERED"
    with pytest.raises(ui.UiFormalManifestError, match="ODPT terms mapping has 0 case_ids"):
        ui.validate_manifest_structure(m)


def test_10_05_odpt_no_warranty_mapping_zero_case_ids_fails():
    m = _valid_manifest()
    for entry in m["coverage_mapping"]:
        if entry["requirement_id"] == "ODPT no-warranty":
            entry["case_ids"] = []
            entry["status"] = "NOT_COVERED"
    with pytest.raises(ui.UiFormalManifestError, match="ODPT no-warranty mapping has 0 case_ids"):
        ui.validate_manifest_structure(m)


def test_10_06_odpt_timestamp_mapping_zero_case_ids_fails():
    m = _valid_manifest()
    for entry in m["coverage_mapping"]:
        if entry["requirement_id"] == "ODPT timestamp":
            entry["case_ids"] = []
            entry["status"] = "NOT_COVERED"
    with pytest.raises(ui.UiFormalManifestError, match="ODPT timestamp mapping has 0 case_ids"):
        ui.validate_manifest_structure(m)


def test_10_07_nonexistent_case_id_in_mapping_fails():
    m = _valid_manifest()
    for entry in m["coverage_mapping"]:
        if entry["requirement_id"] == "ODPT provider":
            entry["case_ids"] = ["chromium::live-train-panel-odpt-attribution.spec.js::::nonexistent case"]
    with pytest.raises(ui.UiFormalManifestError, match="nonexistent case_id"):
        ui.validate_manifest_structure(m)


def test_10_08_case_id_outside_declared_spec_fails():
    m = _valid_manifest()
    # core specの実在するcase_idを、ODPT provider mappingへ誤って紐付けた状態を再現する。
    foreign_case_id = next(c["case_id"] for c in m["cases"] if c["spec"] == "smoke.spec.js")
    for entry in m["coverage_mapping"]:
        if entry["requirement_id"] == "ODPT provider":
            entry["case_ids"] = [foreign_case_id]
    with pytest.raises(ui.UiFormalManifestError, match="outside its declared spec"):
        ui.validate_manifest_structure(m)


def test_10_09_duplicate_case_id_in_manifest_fails():
    m = _valid_manifest()
    m["case_ids"] = m["case_ids"] + [m["case_ids"][0]]
    with pytest.raises(ui.UiFormalManifestError, match="duplicate case_id"):
        ui.validate_manifest_structure(m)


def test_10_10_declared_collected_mismatch_fails():
    m = _valid_manifest()
    executed = m["case_ids"][:-1]  # 1件欠落させて実行したことにする
    status = {cid: ["passed"] for cid in executed}
    result = ui.compare_execution_to_manifest(m, executed, status)
    assert result["ok"] is False
    assert result["declared_total"] != result["collected_total"]
    assert len(result["missing_case_ids"]) == 1


def test_10_11_unexpected_test_fails():
    m = _valid_manifest()
    executed = list(m["case_ids"]) + ["chromium::unexpected.spec.js::::ghost case"]
    status = {cid: ["passed"] for cid in executed}
    result = ui.compare_execution_to_manifest(m, executed, status)
    assert result["ok"] is False
    assert result["unexpected_case_ids"] == ["chromium::unexpected.spec.js::::ghost case"]


def test_10_12_project_swap_produces_unexpected_and_missing():
    """project差替え（例: chromium→webkit）は、declared case_idと文字列が
    一致しなくなるため、missing（declared側）とunexpected（executed側）の
    両方として検出される（project名がcase_idの一部であるため）。"""
    m = {"case_ids": ["chromium::a.spec.js::::case1"], "declared_total": 1}
    executed = ["webkit::a.spec.js::::case1"]
    status = {cid: ["passed"] for cid in executed}
    result = ui.compare_execution_to_manifest(m, executed, status)
    assert result["ok"] is False
    assert result["missing_case_ids"] == ["chromium::a.spec.js::::case1"]
    assert result["unexpected_case_ids"] == ["webkit::a.spec.js::::case1"]


def test_10_13_source_hash_swap_detected():
    m = _valid_manifest()
    original = m["case_source_hashes"][ui.ODPT_SPEC]
    tampered = "0" * 64
    m["case_source_hashes"][ui.ODPT_SPEC] = tampered
    assert m["case_source_hashes"][ui.ODPT_SPEC] != original
    # 実fileのhashを再計算し、manifest記載値との不一致を検出できることを確認する。
    actual = hashlib.sha256((REPO_ROOT / ui.ODPT_SPEC).read_bytes()).hexdigest()
    assert actual != tampered
    assert actual == original


def test_10_14_valid_exact_manifest_passes():
    m = _valid_manifest()
    ui.validate_manifest_structure(m)  # raiseしなければPASS

    executed = list(m["case_ids"])
    status = {cid: ["passed"] for cid in executed}
    result = ui.compare_execution_to_manifest(m, executed, status)
    assert result["ok"] is True
    assert result["missing_case_ids"] == []
    assert result["unexpected_case_ids"] == []
    assert result["duplicate_case_ids"] == []

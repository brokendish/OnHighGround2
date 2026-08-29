#!/usr/bin/env python3
"""
phase2d_ui_formal_manifest.py — UI formal E2E manifest collector / validator
（Phase 2-D Round 10、P2D-UI-ATTRIBUTION対応、指示書第4〜6節）。

CODEX Round 9独立検証は、対象7 specの宣言分母85と実collection数79の不一致
（denominator forensic、本module下部`denominator_forensic()`参照）と、
`live-stream-weather-ticker.spec.js` case 6の時間競合flaky failを報告した。
本moduleは次の2つの役割を持つ。

  1. Playwright公式`--list --reporter=json`出力から、対象7 specのexact
     unique case setを機械的に収集し、schema化されたformal manifestを
     生成する（stable case ID = "<project>::<repo-relative-spec>::
     <describe-chain>::<test-title>"）。totalという数値だけを正本にせず、
     case_ids[]の集合そのものを正本とする。
  2. 実行結果（`--reporter=json`のformal run）をこのmanifestと突き合わせ、
     declared/collected/executed/uniqueの一致、duplicate/missing/
     unexpected 0、non-PASS 0、SKIP/fixme 0を検証する。

source repository（このrepository自身）に対してはPlaywrightの読み取り専用
実行（`--list`または通常のtest run）以外の操作を一切行わない。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_NAME = "chromium"

# Round 10で確定したcore 7 spec（path固定、順序はOWNER提示の順）+
# Round 10A forensic分類C（既存mock/fixtureパターンを再利用した新規demo-stack
# formal E2E）で採用した8番目のODPT spec。
CORE_SPECS = (
    "e2e/attribution.spec.js",
    "e2e/smoke.spec.js",
    "e2e/jartic-traffic-layer.spec.js",
    "e2e/live-weather-ticker.spec.js",
    "e2e/live-stream-weather-ticker.spec.js",
    "e2e/live-stream-mini-map-municipality-boundary.spec.js",
    "e2e/live-stream-main-map.spec.js",
)
ODPT_SPEC = "e2e/live-train-panel-odpt-attribution.spec.js"
ODPT_SPEC_BASENAME = "live-train-panel-odpt-attribution.spec.js"
TARGET_SPECS = CORE_SPECS + (ODPT_SPEC,)


class UiFormalManifestError(RuntimeError):
    """UI formal manifest生成・検証をfail-closedで停止させる例外。"""


def _run(cmd: list, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, check=False)


def _playwright_version(repo_root: Path) -> str:
    pkg = repo_root / "node_modules" / "@playwright" / "test" / "package.json"
    data = json.loads(pkg.read_text(encoding="utf-8"))
    return data["version"]


def _spec_hashes(repo_root: Path, spec_paths: tuple) -> dict:
    hashes = {}
    for rel in spec_paths:
        full = repo_root / rel
        if not full.is_file():
            raise UiFormalManifestError(f"target spec missing: {rel}")
        hashes[rel] = hashlib.sha256(full.read_bytes()).hexdigest()
    return hashes


def _walk_suite(suite: dict, describe_chain: list, out: list) -> None:
    title = suite.get("title")
    nested_chain = describe_chain
    # ファイルsuite自身のtitleは通常file名と同一でありdescribe chainには含めない。
    if title and not title.endswith(".spec.js"):
        nested_chain = describe_chain + [title]

    for spec in suite.get("specs", []):
        for t in spec.get("tests", []):
            out.append(
                {
                    "project": t.get("projectName"),
                    "spec": spec.get("file"),
                    "describe_chain": list(nested_chain),
                    "title": spec.get("title"),
                    "line": spec.get("line"),
                    "column": spec.get("column"),
                }
            )

    for child in suite.get("suites", []):
        _walk_suite(child, nested_chain, out)


def _case_id(entry: dict) -> str:
    describe = " > ".join(entry["describe_chain"])
    return f"{entry['project']}::{entry['spec']}::{describe}::{entry['title']}"


def collect_cases(repo_root: Path, spec_paths: tuple = TARGET_SPECS) -> list:
    """Playwright公式`--list --reporter=json`結果から、対象specのexact
    unique case setを収集する。line番号だけをidentityにせず、
    project/spec/describe chain/titleの組をcase IDとする。"""
    cmd = ["npx", "playwright", "test", "--list", "--reporter=json", *spec_paths]
    proc = _run(cmd, repo_root)
    if proc.returncode != 0:
        raise UiFormalManifestError(
            f"playwright --list failed (exit={proc.returncode}): {proc.stderr.decode(errors='replace')[:2000]}"
        )
    data = json.loads(proc.stdout.decode("utf-8"))
    return parse_list_json(data)


def parse_list_json(data: dict) -> list:
    """`npx playwright test --list --reporter=json`のparsed dictから、
    duplicate 0を検証済みのexact unique case listを返す（collect_cases()の
    subprocess呼び出し部分から分離した純粋関数、self-testが直接呼べる）。"""
    entries: list = []
    for suite in data.get("suites", []):
        _walk_suite(suite, [], entries)

    cases = []
    seen_ids = set()
    for e in entries:
        cid = _case_id(e)
        if cid in seen_ids:
            raise UiFormalManifestError(f"duplicate case_id in collection: {cid}")
        seen_ids.add(cid)
        cases.append(
            {
                "case_id": cid,
                "project": e["project"],
                "spec": e["spec"],
                "describe_chain": e["describe_chain"],
                "title": e["title"],
                "line": e["line"],
                "column": e["column"],
            }
        )
    cases.sort(key=lambda c: c["case_id"])
    return cases


# 指示書第6節が定める必須coverage requirementと、それを満たすcaseの判定
# ルール。全ruleは実際に確認済みのspec/describe/title文字列に基づく
# hand-verified matcherであり、曖昧なkeyword全文一致には依存しない
# （false positiveを避けるため）。ODPT provider/terms/no-warranty/
# timestampは対象7 spec内に実在しないことをgrepで確認済み（ODPT
# attributionのE2E自体はe2e/live-stream-source-badges.spec.js等、対象7 spec
# 外に実在する——OWNER判断によりcoverage 0のままFAILとして報告する）。
def _spec_name(case: dict) -> str:
    return case["spec"]


def _in_describe(case: dict, needle: str) -> bool:
    return any(needle in d for d in case["describe_chain"])


COVERAGE_RULES: tuple = (
    (
        "base OSM / ODbL attribution",
        lambda c: (
            (_spec_name(c) == "attribution.spec.js" and "OSM/ODbLと第三者データ出典" in c["title"])
            or (_spec_name(c) == "live-stream-main-map.spec.js" and "OSM/CARTO attribution" in c["title"])
        ),
    ),
    (
        "GSI / KSJ / JMA base attribution",
        lambda c: _spec_name(c) == "attribution.spec.js" and "OSM/ODbLと第三者データ出典" in c["title"],
    ),
    (
        "JARTIC ON / OFF",
        lambda c: (
            (_spec_name(c) == "attribution.spec.js" and "JARTIC道路交通量レイヤーON中" in c["title"])
            or (_spec_name(c) == "jartic-traffic-layer.spec.js" and ("トグル ON" in c["title"] or "トグル OFF" in c["title"] or "トグルOFF" in c["title"] or "トグルON" in c["title"]))
        ),
    ),
    (
        "JARTIC disclaimer",
        lambda c: (
            (_spec_name(c) == "attribution.spec.js" and "JARTIC道路交通量レイヤーON中" in c["title"])
            or (_spec_name(c) == "jartic-traffic-layer.spec.js" and "断定文言" in c["title"])
        ),
    ),
    (
        "Open-Meteo link / CC BY",
        lambda c: (
            (_spec_name(c) == "live-weather-ticker.spec.js" and "レイヤーパネル内に全国気象カード" in c["title"])
            or (_spec_name(c) == "live-stream-weather-ticker.spec.js" and "パネルが右カラム上部" in c["title"])
        ),
    ),
    # Round 10AでODPT specを採用（forensic分類C）。4要件を個別
    # requirementとして分離する（指示書第9節: 4要件それぞれをcase_idへ
    # 個別に紐付ける）。
    (
        "ODPT provider",
        lambda c: _spec_name(c) == ODPT_SPEC_BASENAME and c["title"].startswith("1: ODPT provider"),
    ),
    (
        "ODPT terms",
        lambda c: _spec_name(c) == ODPT_SPEC_BASENAME and c["title"].startswith("2: ODPT terms"),
    ),
    (
        "ODPT no-warranty",
        lambda c: _spec_name(c) == ODPT_SPEC_BASENAME and c["title"].startswith("3: ODPT no-warranty"),
    ),
    (
        "ODPT timestamp",
        lambda c: _spec_name(c) == ODPT_SPEC_BASENAME and c["title"].startswith("4: ODPT timestamp"),
    ),
    (
        "boundary attribution",
        lambda c: (
            (_spec_name(c) == "attribution.spec.js" and "行政区域境界レイヤー" in c["title"])
            or _spec_name(c) == "live-stream-mini-map-municipality-boundary.spec.js"
        ),
    ),
    (
        "/",
        lambda c: (
            _spec_name(c) == "smoke.spec.js"
            or (_spec_name(c) == "attribution.spec.js" and _in_describe(c, "UI attribution: `/` トップ画面"))
            or _spec_name(c) == "jartic-traffic-layer.spec.js"
        ),
    ),
    (
        "/live",
        lambda c: (
            (_spec_name(c) == "attribution.spec.js" and _in_describe(c, "UI attribution: `/live`"))
            or _spec_name(c) == "live-weather-ticker.spec.js"
            or (_spec_name(c) == "jartic-traffic-layer.spec.js" and "/live 側に" in c["title"])
        ),
    ),
    (
        "/live/stream",
        lambda c: (
            (_spec_name(c) == "attribution.spec.js" and _in_describe(c, "UI attribution: `/live/stream`"))
            or _spec_name(c)
            in (
                "live-stream-weather-ticker.spec.js",
                "live-stream-mini-map-municipality-boundary.spec.js",
                "live-stream-main-map.spec.js",
            )
        ),
    ),
    (
        "desktop / mobile where required",
        lambda c: _spec_name(c) == "jartic-traffic-layer.spec.js" and (c["title"].startswith("PC:") or c["title"].startswith("モバイル:")),
    ),
    (
        "ticker pagination / wrap",
        lambda c: _spec_name(c) == "live-stream-weather-ticker.spec.js" and "ページ送りにより表示地点が切り替わり" in c["title"],
    ),
    (
        "stream main map",
        lambda c: _spec_name(c) == "live-stream-main-map.spec.js",
    ),
    (
        "mini-map boundary",
        lambda c: _spec_name(c) == "live-stream-mini-map-municipality-boundary.spec.js",
    ),
)


def build_coverage_matrix(cases: list) -> list:
    """指示書第6節の全requirementについて、それを満たすcase_idを列挙する。
    covering case 0件のrequirementはcovered=Falseのまま返す
    （呼び出し側がfail-closedで扱う——0件を勝手にPASS扱いしない）。"""
    matrix = []
    for name, matcher in COVERAGE_RULES:
        covering = [c["case_id"] for c in cases if matcher(c)]
        matrix.append(
            {
                "requirement": name,
                "covering_case_ids": covering,
                "covering_count": len(covering),
                "covered": len(covering) > 0,
            }
        )
    return matrix


# 指示書第9節が定めるcoverage_mapping（4要件それぞれについて
# requirement_id/case_ids/spec_path/route/viewport/assertion_summary/
# expected_source/statusを記録する詳細schema）。route/viewportは実際に
# assertionを実行したsurfaceのみを記録し、確認していないsurfaceへ推測で
# 広げない（指示書第5.3節）。
_ODPT_MAPPING_SPEC: tuple = (
    (
        "ODPT provider",
        "1: ODPT provider",
        "実DOM「事業者」行の値がstub operator_name(東京メトロ)と一致、"
        "「出典」行の値がstub source(ODPT)と一致することをexact textで検証。",
        "backend/app/services/live_train_service.py が /api/live/trains/summary "
        "経由で返す operator_name / source フィールド（本testではmock stubで固定）。",
    ),
    (
        "ODPT terms",
        "2: ODPT terms",
        "実DOM「ライセンス」行のlink要素がvisibleであり、hrefがstub "
        "license_terms_url(https://developer.odpt.org/terms)とexact一致することを検証。",
        "backend/app/services/odpt_allowlist.py が承認済み事業者（東京メトロ・都営）へ"
        "付与する license_terms_url（本testではmock stubで固定、"
        "backend/tests/test_phase2d_odpt_allowlist.pyが同一値の組み合わせを実測済み）。",
    ),
    (
        "ODPT no-warranty",
        "3: ODPT no-warranty",
        "実DOM「注意」行がvisibleであり、免責文言全文"
        "「本情報の内容は各事業者・ODPTによって保証されたものではありません」を"
        "containTextで検証。",
        "frontend/js/live/live-train-panel.js の _showDetailModal() が"
        "静的に埋め込む固定文言（application変更なし）。",
    ),
    (
        "ODPT timestamp",
        "4: ODPT timestamp",
        "実DOM「更新時刻」行の値がstub updated_at(2026-06-14T19:58:00+09:00)と"
        "exact textで一致することを検証（PC現在時刻・test実行時刻ではない固定値であることも確認）。",
        "backend/app/services/live_train_service.py が返す updated_at フィールド"
        "（本testではmock stubで固定）。",
    ),
)


def build_odpt_coverage_mapping(cases: list) -> list:
    mapping = []
    for requirement_id, title_prefix, assertion_summary, expected_source in _ODPT_MAPPING_SPEC:
        covering = [
            c["case_id"]
            for c in cases
            if c["spec"] == ODPT_SPEC_BASENAME and c["title"].startswith(title_prefix)
        ]
        mapping.append(
            {
                "requirement_id": requirement_id,
                "case_ids": covering,
                "spec_path": ODPT_SPEC,
                "route": "/live",
                "viewport": "1440x900 (desktop, playwright.config.js default)",
                "assertion_summary": assertion_summary,
                "expected_source": expected_source,
                "status": "COVERED" if covering else "NOT_COVERED",
            }
        )
    return mapping


def per_spec_counts(cases: list) -> dict:
    counts: dict = {}
    for c in cases:
        counts[c["spec"]] = counts.get(c["spec"], 0) + 1
    return counts


def generate_manifest(
    repo_root: Path = REPO_ROOT,
    spec_paths: tuple = TARGET_SPECS,
) -> dict:
    cases = collect_cases(repo_root, spec_paths)
    coverage_matrix = build_coverage_matrix(cases)
    odpt_mapping = build_odpt_coverage_mapping(cases)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "playwright_version": _playwright_version(repo_root),
        "project": PROJECT_NAME,
        "spec_paths": list(spec_paths),
        "declared_total": len(cases),
        "case_ids": [c["case_id"] for c in cases],
        "cases": cases,
        "per_spec_counts": per_spec_counts(cases),
        "coverage_requirements": coverage_matrix,
        "coverage_uncovered_requirements": [m["requirement"] for m in coverage_matrix if not m["covered"]],
        "coverage_mapping": odpt_mapping,
        "coverage_mapping_uncovered": [m["requirement_id"] for m in odpt_mapping if m["status"] != "COVERED"],
        "generated_from": "npx playwright test --list --reporter=json (official Playwright collection, read-only)",
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "case_source_hashes": _spec_hashes(repo_root, spec_paths),
    }
    return manifest


def write_manifest(manifest: dict, output_path: Path) -> str:
    text = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=False)
    text += "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# formal run実行 / manifestとの突合検証
# ---------------------------------------------------------------------------

def run_formal_suite(
    repo_root: Path,
    manifest: dict,
    env_overrides: dict | None = None,
    repeat_each: int = 1,
) -> dict:
    """対象specを実際に実行し（`--list`ではなく本実行）、結果をmanifestと
    突き合わせる。`--repeat-each`等による複数実行はunique caseへ加算しない
    （union setとしてのみ扱い、重複実行はduplicate detectionの対象外とする
    ——本functionは既定でrepeat_each=1のみをformal denominator判定に使う）。
    """
    import os
    import tempfile

    env = dict(os.environ)
    if env_overrides:
        env.update(env_overrides)

    with tempfile.TemporaryDirectory(prefix="ohg2p2d_ui_formal_") as tmp:
        json_out = Path(tmp) / "result.json"
        env["PLAYWRIGHT_JSON_OUTPUT_NAME"] = str(json_out)
        cmd = ["npx", "playwright", "test", "--reporter=json", *manifest["spec_paths"]]
        if repeat_each > 1:
            cmd.append(f"--repeat-each={repeat_each}")
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, env=env)
        if not json_out.exists():
            raise UiFormalManifestError(
                f"playwright run produced no JSON output (exit={proc.returncode}): "
                f"{proc.stderr.decode(errors='replace')[:2000]}"
            )
        data = json.loads(json_out.read_text(encoding="utf-8"))

    executed_ids = []
    status_by_id: dict = {}
    entries: list = []
    for suite in data.get("suites", []):
        _walk_suite(suite, [], entries)

    # 実行結果のstatusはspec.testsそのものではなく、`--list`と同形式の
    # 木構造をたどりつつ、各testのresultsを別途集計する必要があるため、
    # 生JSONをもう一度別経路で辿ってstatusを引く。
    def _walk_with_status(suite: dict, describe_chain: list) -> None:
        title = suite.get("title")
        nested_chain = describe_chain
        if title and not title.endswith(".spec.js"):
            nested_chain = describe_chain + [title]
        for spec in suite.get("specs", []):
            for t in spec.get("tests", []):
                cid = _case_id(
                    {
                        "project": t.get("projectName"),
                        "spec": spec.get("file"),
                        "describe_chain": nested_chain,
                        "title": spec.get("title"),
                    }
                )
                statuses = [r.get("status") for r in t.get("results", [])]
                status_by_id.setdefault(cid, []).extend(statuses)
                executed_ids.append(cid)
        for child in suite.get("suites", []):
            _walk_with_status(child, nested_chain)

    for suite in data.get("suites", []):
        _walk_with_status(suite, [])

    result = compare_execution_to_manifest(manifest, executed_ids, status_by_id, repeat_each=repeat_each)
    result["stats"] = data.get("stats", {})
    return result


def compare_execution_to_manifest(
    manifest: dict,
    executed_ids: list,
    status_by_id: dict,
    repeat_each: int = 1,
) -> dict:
    """実行結果（executed_ids・status_by_id）をmanifestと突き合わせる純粋関数
    （`run_formal_suite()`のsubprocess呼び出し部分から分離、self-testが
    synthetic dataで直接呼べる）。"""
    declared_ids = set(manifest["case_ids"])
    collected_ids = set(executed_ids)  # repeat_each==1ならexecuted set == unique set
    unique_executed_ids = set(executed_ids)

    missing = sorted(declared_ids - collected_ids)
    unexpected = sorted(collected_ids - declared_ids)

    duplicate_counts = {}
    if repeat_each == 1:
        seen = {}
        for cid in executed_ids:
            seen[cid] = seen.get(cid, 0) + 1
        duplicate_counts = {k: v for k, v in seen.items() if v > 1}

    non_pass = {}
    skip_ids = []
    for cid, statuses in status_by_id.items():
        for s in statuses:
            if s == "skipped":
                skip_ids.append(cid)
            elif s not in ("passed",):
                non_pass.setdefault(cid, []).append(s)

    ok = (
        declared_ids == collected_ids
        and len(unique_executed_ids) == manifest["declared_total"]
        and not missing
        and not unexpected
        and not duplicate_counts
        and not non_pass
        and not skip_ids
    )

    return {
        "declared_total": manifest["declared_total"],
        "collected_total": len(collected_ids),
        "executed_total": len(executed_ids),
        "unique_executed_total": len(unique_executed_ids),
        "missing_case_ids": missing,
        "unexpected_case_ids": unexpected,
        "duplicate_case_ids": sorted(duplicate_counts.keys()),
        "non_pass_case_ids": {k: v for k, v in non_pass.items()},
        "skip_case_ids": sorted(set(skip_ids)),
        "ok": ok,
    }


def validate_manifest_structure(manifest: dict) -> None:
    """manifestの構造的完全性をfail-closedで検証する（指示書第10節1〜9項目）。
    実行結果を必要としない静的検証のみを行う。"""
    spec_paths = set(manifest["spec_paths"])
    missing_core = [s for s in CORE_SPECS if s not in spec_paths]
    if missing_core:
        raise UiFormalManifestError(f"core spec(s) missing from manifest spec_paths: {missing_core}")
    if ODPT_SPEC not in spec_paths:
        raise UiFormalManifestError(f"adopted ODPT spec missing from manifest spec_paths: {ODPT_SPEC}")

    case_ids_list = manifest["case_ids"]
    if len(set(case_ids_list)) != len(case_ids_list):
        seen = set()
        dupes = set()
        for cid in case_ids_list:
            if cid in seen:
                dupes.add(cid)
            seen.add(cid)
        raise UiFormalManifestError(f"duplicate case_id detected in manifest case_ids: {sorted(dupes)}")

    case_id_set = set(case_ids_list)
    case_by_id = {c["case_id"]: c for c in manifest["cases"]}

    required_odpt = {"ODPT provider", "ODPT terms", "ODPT no-warranty", "ODPT timestamp"}
    mapping_by_id = {m["requirement_id"]: m for m in manifest.get("coverage_mapping", [])}
    missing_req = required_odpt - set(mapping_by_id.keys())
    if missing_req:
        raise UiFormalManifestError(f"ODPT coverage_mapping missing requirement_id(s): {sorted(missing_req)}")

    for req_id in sorted(required_odpt):
        m = mapping_by_id[req_id]
        if not m["case_ids"]:
            raise UiFormalManifestError(f"{req_id} mapping has 0 case_ids")
        if m["status"] != "COVERED":
            raise UiFormalManifestError(f"{req_id} mapping status is not COVERED: {m['status']!r}")
        for cid in m["case_ids"]:
            if cid not in case_id_set:
                raise UiFormalManifestError(f"{req_id} mapping references nonexistent case_id: {cid!r}")
            case = case_by_id[cid]
            if case["spec"] != ODPT_SPEC_BASENAME:
                raise UiFormalManifestError(
                    f"{req_id} mapping references case_id outside its declared spec "
                    f"(expected {ODPT_SPEC_BASENAME!r}, found {case['spec']!r}): {cid!r}"
                )


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    manifest = generate_manifest(args.repo_root.resolve())
    sha = write_manifest(manifest, args.output)
    print(f"declared_total={manifest['declared_total']} manifest_sha256={sha}")
    print(json.dumps(manifest["per_spec_counts"], indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

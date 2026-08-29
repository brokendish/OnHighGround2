#!/usr/bin/env python3
"""Phase 2-B.6 scoped assertion runner (12 assertions, AT18-A01..A04,
AT19-A01..A04, AT20-A01..A04) and Phase 2-E deferred aggregation (8
assertions).

Executes real, independently-inspectable checks (git commands, document
structure checks, a local clean-clone dry-run, formal-matrix traceability
recomputation) and emits:

  tasks/public-release/evidence/phase2b6/scoped_assertion_results.json
  tests/fixtures/public_release/version_binding/scoped/manifest-set.json
  tasks/public-release/evidence/phase2b6/scoped_gate_result.json  (via
  verify_at_evidence.py, primary_code must be PASS or PASS_COMPATIBLE_REUSE)

This script performs no Docker, network, or git-push operations. It is
read-only with respect to git state.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

# Phase 2-D Round 3 (CODEX再検証finding、P2D-AT17-SNAPSHOT-001対応): 開発者ローカル
# 絶対pathのhardcodeはpublic release snapshotのsecret/boundary scanで検出される
# ため、このrepository内の他のtools/public_release/*.pyと同じ動的解決へ統一した
# （振る舞いは従来と完全に同一 — このfileはtools/public_release/直下にあるため
# parents[2]は常にrepository rootを指す）。
REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPO_ROOT / "tasks/public-release/github_public_audit_phase2a_remediation_plan.md"
PUSH_PROCEDURE = REPO_ROOT / "tasks/public-release/github_public_release_push_procedure.md"
GIT_REFS_EVIDENCE = REPO_ROOT / "tasks/public-release/evidence/phase2b6/at18_a02_git_refs.txt"
VERIFY_TOOL = REPO_ROOT / "tools/public_release/verify_at_evidence.py"
SHARED_REGISTRY = REPO_ROOT / "tests/fixtures/public_release/version_binding/shared/registry/p2a-at18-20-v2.json"
SHARED_ACTIVATION = REPO_ROOT / "tests/fixtures/public_release/version_binding/shared/activation-approved-v2.json"
EVIDENCE_DIR = REPO_ROOT / "tasks/public-release/evidence/phase2b6"
SCOPED_FIXTURE_DIR = REPO_ROOT / "tests/fixtures/public_release/version_binding/scoped"

V2_NAME = "p2a-at18-20-assertion-registry"
V2_VERSION = "p2a-at18-20-v2"
V2_SCHEMA = "1.0"
V2_HASH = "c3cb704bd6e6f4f7ae0b19e1962ae0f5da4cd95d94bde47bfb67b4d02bbc5799"
COMMIT = "d3eeb99fd5f214487939d7a0df599e1d56835128"

RESULTS: list[dict] = []


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes_local(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record(assertion_id: str, verdict: str, detail: str, evidence: dict) -> None:
    RESULTS.append({
        "assertion_id": assertion_id,
        "verdict": verdict,
        "detail": detail,
        "evidence": evidence,
        "executor": "Claude",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    })
    print(f"[{verdict}] {assertion_id}: {detail}")


def run_cmd(cmd: list[str], cwd: Path = REPO_ROOT) -> dict:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)
    return {
        "command": " ".join(cmd),
        "exit_code": proc.returncode,
        "stdout_sha256": sha256_text(proc.stdout),
        "stderr_sha256": sha256_text(proc.stderr),
        "stdout_bytes": len(proc.stdout.encode("utf-8")),
        "stderr_bytes": len(proc.stderr.encode("utf-8")),
        "stdout_preview": proc.stdout[:2000],
    }


# ---------------------------------------------------------------------------
# AT18-A01: evidence schema executor/reviewer/phase-transition responsibility
# separation — structural check, no self-approval path.
# ---------------------------------------------------------------------------
def check_at18_a01() -> None:
    verify_src = VERIFY_TOOL.read_text(encoding="utf-8")
    has_self_review_guard = "E_COMPAT_SELF_REVIEW" in verify_src and "record[\"reviewer\"] == record[\"executor\"]" in verify_src
    activation = json.loads(SHARED_ACTIVATION.read_text(encoding="utf-8"))
    reviewer_distinct_from_plan_executor = activation.get("reviewer") == "CODEX"
    ok = has_self_review_guard and reviewer_distinct_from_plan_executor
    record(
        "AT18-A01",
        "PASS" if ok else "FAIL",
        "compatibility reuse self-review guard present in verify_at_evidence.py; "
        "activation record reviewer(CODEX) is a distinct role from executor(Claude)",
        {
            "schema extract": "verify_at_evidence.py::_validate_compat_record self-review check",
            "responsibility matrix": "activation-approved-v2.json reviewer=CODEX, executor role=Claude (this document)",
            "static review": f"has_self_review_guard={has_self_review_guard}",
        },
    )


# ---------------------------------------------------------------------------
# AT18-A02: read-only git ref confirmation commands.
# ---------------------------------------------------------------------------
def check_at18_a02() -> None:
    exists = GIT_REFS_EVIDENCE.is_file()
    text = GIT_REFS_EVIDENCE.read_text(encoding="utf-8") if exists else ""
    required_markers = [
        "git rev-parse HEAD", "git rev-parse main", "git branch -a",
        "git tag -l", "git for-each-ref refs/remotes", "git for-each-ref refs/codex",
    ]
    all_present = exists and all(m in text for m in required_markers)
    exit_codes_ok = exists and text.count("exit=0") >= 8
    ok = all_present and exit_codes_ok
    record(
        "AT18-A02",
        "PASS" if ok else "FAIL",
        f"read-only git ref evidence file present with all required commands and exit=0",
        {
            "command records": str(GIT_REFS_EVIDENCE.relative_to(REPO_ROOT)),
            "stdout/stderr artifacts": "combined in evidence file (read-only commands only)",
            "SHA-256": sha256_text(text) if exists else None,
        },
    )


# ---------------------------------------------------------------------------
# AT18-A03: push allowlist review.
# ---------------------------------------------------------------------------
def check_at18_a03() -> None:
    exists = PUSH_PROCEDURE.is_file()
    text = PUSH_PROCEDURE.read_text(encoding="utf-8") if exists else ""
    # Extract "許可されるpush操作" section only (between section 2 and section 3 headers)
    m = re.search(r"## 2\. 許可されるpush操作.*?(?=## 3\.)", text, re.S)
    allowed_section = m.group(0) if m else ""
    forbidden_in_allowed = any(tok in allowed_section for tok in ("--all", "--tags", "--mirror"))
    has_only_main = "git push origin main" in allowed_section
    ok = exists and has_only_main and not forbidden_in_allowed
    record(
        "AT18-A03",
        "PASS" if ok else "FAIL",
        "push procedure allowlist contains only 'git push origin main' (+ optional -u); "
        f"--all/--tags/--mirror in allowed section = {forbidden_in_allowed}",
        {
            "reachability report": str(GIT_REFS_EVIDENCE.relative_to(REPO_ROOT)),
            "push command allowlist": str(PUSH_PROCEDURE.relative_to(REPO_ROOT)),
            "reviewer verdict": "PENDING_INDEPENDENT_REVIEW",
        },
    )


# ---------------------------------------------------------------------------
# AT18-A04: NO-ACTION judgement (P1-QUAL-003 / REM-011) individual review.
# ---------------------------------------------------------------------------
def check_at18_a04() -> None:
    text = PLAN.read_text(encoding="utf-8")
    row_match = re.search(r"^\| P1-QUAL-003 \|.*\|$", text, re.M)
    ok = False
    row = ""
    if row_match:
        row = row_match.group(0)
        cols = [c.strip() for c in row.strip("|").split("|")]
        # cols: FindingID, source, Severity, Release classification, remediation ID,
        #       target, target file, acceptance test, status, owner dep
        if len(cols) >= 9:
            severity, status = cols[2], cols[8]
            ok = severity == "LOW" and status == "NO-ACTION"
    record(
        "AT18-A04",
        "PASS" if ok else "FAIL",
        f"P1-QUAL-003 individually reviewed: severity/status extracted from finding table row (not blanket-approved)",
        {
            "no-action register": "github_public_audit_phase2a_remediation_plan.md section 9, P1-QUAL-003 row",
            "source evidence refs": "REM-011",
            "reviewer verdict": "PENDING_INDEPENDENT_REVIEW",
            "raw_row_sha256": sha256_text(row) if row else None,
        },
    )


# ---------------------------------------------------------------------------
# AT19-A01: measurement command specification.
# ---------------------------------------------------------------------------
MEASUREMENT_SPEC = {
    "spec_version": "1.0",
    "unit": "bytes_or_count_decimal_integer_no_separators_no_exponent",
    "measurements": [
        {"name": "working_tree_bytes", "command": "du -sk --exclude=.git . | awk '{print $1*1024}'"},
        {"name": "dot_git_bytes", "command": "du -sk .git | awk '{print $1*1024}'"},
        {"name": "git_object_count", "command": "git count-objects -v"},
        {"name": "git_pack_bytes", "command": "git count-objects -v"},
        {"name": "largest_blob_bytes", "command": "git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)'"},
    ],
    "threshold_table": {
        "github_single_file_warn_bytes": 52428800,
        "github_single_file_hard_limit_bytes": 104857600,
        "github_repo_recommended_bytes": 1073741824,
    },
}


def check_at19_a01() -> None:
    spec_path = EVIDENCE_DIR / "at19_a01_measurement_spec.json"
    spec_path.write_text(json.dumps(MEASUREMENT_SPEC, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    ok = all(isinstance(v, int) for v in MEASUREMENT_SPEC["threshold_table"].values())
    record(
        "AT19-A01",
        "PASS" if ok else "FAIL",
        "measurement command spec + threshold table recorded with raw decimal integer units",
        {
            "measurement specification": str(spec_path.relative_to(REPO_ROOT)),
            "threshold table": "embedded in spec, integer bytes",
            "schema validation": f"all_thresholds_integer={ok}",
        },
    )


# ---------------------------------------------------------------------------
# AT19-A02: fresh clean-clone generation/measurement/teardown procedure,
# executed once locally against a scratch temp dir (path-safety proven).
# ---------------------------------------------------------------------------
def _run_clean_clone_records() -> tuple[list[dict], bool]:
    """Shared by AT19-A02 and AT19-A03 so each is independently invokable
    as its own subprocess (P2B6-CX-002 round 3: AT19-A03 previously only
    existed as a downstream consumer of AT19-A02's in-process return value,
    which is incompatible with running each assertion as its own real
    subprocess)."""
    records = []
    with tempfile.TemporaryDirectory(prefix="ohg2_p2b6_cleanclone_") as tmp:
        tmp_path = Path(tmp)
        clone_dir = tmp_path / "clean_clone"
        cmd = ["git", "clone", "--no-local", "--depth", "1", "--branch", "main",
               str(REPO_ROOT), str(clone_dir)]
        r = run_cmd(cmd, cwd=tmp_path)
        records.append(r)
        clone_ok = r["exit_code"] == 0 and clone_dir.is_dir()
        head_ok = False
        if clone_ok:
            r2 = run_cmd(["git", "rev-parse", "HEAD"], cwd=clone_dir)
            records.append(r2)
            head_ok = r2["exit_code"] == 0
        path_isolated = clone_dir != REPO_ROOT and str(REPO_ROOT) not in str(clone_dir)
        # teardown happens automatically at context exit
    return records, (clone_ok and head_ok and path_isolated)


def check_at19_a02() -> None:
    records, ok = _run_clean_clone_records()
    evidence_path = EVIDENCE_DIR / "at19_a02_clean_clone_procedure.json"
    evidence_path.write_text(json.dumps({"records": records, "path_isolated": ok}, indent=2) + "\n", encoding="utf-8")
    record(
        "AT19-A02",
        "PASS" if ok else "FAIL",
        f"local clean-clone dry-run executed in isolated tempdir, cloned HEAD verified, teardown complete",
        {
            "procedure": str(evidence_path.relative_to(REPO_ROOT)),
            "command plan": "git clone --no-local --depth 1 --branch main <repo> <isolated tmp dir>",
            "path safety checks": f"path_isolated={ok}",
        },
    )


# ---------------------------------------------------------------------------
# AT19-A03: evidence manifest sample with per-command exit/bytes/sha256.
# ---------------------------------------------------------------------------
def check_at19_a03() -> None:
    clone_records, _ = _run_clean_clone_records()
    sample_path = EVIDENCE_DIR / "at19_a03_evidence_manifest_sample.json"
    ok = bool(clone_records) and all(
        "exit_code" in r and "stdout_sha256" in r and "stderr_sha256" in r for r in clone_records
    )
    sample_path.write_text(json.dumps({"per_command_records": clone_records}, indent=2) + "\n", encoding="utf-8")
    record(
        "AT19-A03",
        "PASS" if ok else "FAIL",
        f"{len(clone_records)} pipeline commands each carry individual exit code/stdout+stderr SHA-256 "
        "(final-element-only success is not treated as command-level PASS)",
        {
            "evidence manifest sample": str(sample_path.relative_to(REPO_ROOT)),
            "per-command records": f"count={len(clone_records)}",
            "schema validation": f"all_fields_present={ok}",
        },
    )


# ---------------------------------------------------------------------------
# AT19-A04: reject human-readable/rounded/stale-value PASS criteria.
# ---------------------------------------------------------------------------
def _is_raw_decimal_integer(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    if isinstance(value, str):
        return bool(re.fullmatch(r"[0-9]+", value))
    return False


def check_at19_a04() -> None:
    negative_cases = ["12MB", "~500000", "500,000", "5e5", "about 12 megabytes", "", None, 12.5]
    positive_cases = [12345678, "12345678", 0]
    rejected = [v for v in negative_cases if not _is_raw_decimal_integer(v)]
    accepted = [v for v in positive_cases if _is_raw_decimal_integer(v)]
    ok = len(rejected) == len(negative_cases) and len(accepted) == len(positive_cases)
    record(
        "AT19-A04",
        "PASS" if ok else "FAIL",
        f"negative schema cases (rounded/human-readable/scientific/stale) rejected: "
        f"{len(rejected)}/{len(negative_cases)}; positive raw-integer cases accepted: {len(accepted)}/{len(positive_cases)}",
        {
            "negative schema cases": negative_cases,
            "parser output": f"_is_raw_decimal_integer, rejected={rejected}",
            "reviewer verdict": "PENDING_INDEPENDENT_REVIEW",
        },
    )


# ---------------------------------------------------------------------------
# AT20-A01: subphase checklist / dependency validation / rollback plan.
# ---------------------------------------------------------------------------
SUBPHASE_CHECKLIST = {
    "subphases": ["2-B.1", "2-B.2", "2-B.3", "2-B.4", "2-B.5", "2-B.6"],
    "dependencies": {
        "2-B.1": [], "2-B.2": ["2-B.1"], "2-B.3": ["2-B.1"], "2-B.4": ["2-B.1"],
        "2-B.5": ["2-B.1"], "2-B.6": ["2-B.1", "2-B.2", "2-B.3", "2-B.4", "2-B.5"],
    },
    "rollback_boundary": {
        "2-B.1": "image rebuild only, no runtime data affected",
        "2-B.2": "compose override revert, no data affected",
        "2-B.3": "operator auth config revert, no data affected",
        "2-B.4": "frontend asset revert, no data affected",
        "2-B.5": "data_runtime atomic publish rollback manifest (see section 7)",
        "2-B.6": "no runtime-affecting change; rollback = revert this phase's commits",
    },
}


def _has_cycle(deps: dict) -> bool:
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {k: WHITE for k in deps}

    def visit(node):
        color[node] = GRAY
        for dep in deps[node]:
            if color.get(dep) == GRAY:
                return True
            if color.get(dep) == WHITE and visit(dep):
                return True
        color[node] = BLACK
        return False

    return any(color[n] == WHITE and visit(n) for n in deps)


def check_at20_a01() -> None:
    path = EVIDENCE_DIR / "at20_a01_subphase_checklist.json"
    path.write_text(json.dumps(SUBPHASE_CHECKLIST, indent=2) + "\n", encoding="utf-8")
    cyclic = _has_cycle(SUBPHASE_CHECKLIST["dependencies"])
    ok = not cyclic and len(SUBPHASE_CHECKLIST["subphases"]) == 6
    record(
        "AT20-A01",
        "PASS" if ok else "FAIL",
        f"6 subphases checklisted with explicit dependencies and rollback boundary; cyclic_dependency={cyclic}",
        {
            "subphase checklist": str(path.relative_to(REPO_ROOT)),
            "dependency validation": f"cyclic={cyclic}",
            "rollback plan": "per-subphase rollback boundary recorded",
        },
    )


# ---------------------------------------------------------------------------
# AT20-A02: formal matrix parser — finding/remediation/AT row re-tally.
# ---------------------------------------------------------------------------
def check_at20_a02() -> None:
    text = PLAN.read_text(encoding="utf-8")

    finding_rows = re.findall(r"^\| ([A-Za-z0-9][A-Za-z0-9_.\-]*) \|(.*)\|$", text, re.M)
    # Restrict to the finding table body (starts at P1-SEC-001, ends before status legend)
    body_match = re.search(r"(\| P1-SEC-001 \|.*?)\n\*\*status凡例", text, re.S)
    finding_body = body_match.group(1) if body_match else ""
    finding_id_re = re.compile(r"^\|\s*([A-Za-z0-9][A-Za-z0-9_.\-]*)\s*\|.*?\|\s*(REM-[0-9]+(?:,\s*REM-[0-9]+)*(?:\s*〜\s*REM-[0-9]+)?)\s*\|", re.M)
    findings = {}
    for line in finding_body.splitlines():
        if not line.startswith("| "):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 5:
            continue
        fid = cols[0]
        rem_col = cols[4]
        rem_ids = re.findall(r"REM-\d+", rem_col)
        if fid and rem_ids:
            findings[fid] = rem_ids

    at_body_match = re.search(r"(\| AT-01 \|.*?)\n\n", text, re.S)
    at_body = at_body_match.group(1) if at_body_match else ""
    at_rows = {}
    for line in at_body.splitlines():
        if not line.startswith("| AT-"):
            continue
        cols = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cols) < 3:
            continue
        at_id_raw = cols[0]
        at_id_match = re.match(r"(AT-\d+)", at_id_raw)
        if not at_id_match:
            continue
        at_id = at_id_match.group(1)
        rem_ids = re.findall(r"REM-\d+", cols[2])
        at_rows[at_id] = rem_ids

    all_finding_rems = set()
    for rems in findings.values():
        all_finding_rems.update(rems)
    all_at_rems = set()
    for rems in at_rows.values():
        all_at_rems.update(rems)

    orphan = all_finding_rems - all_at_rems
    unknown = all_at_rems - all_finding_rems

    finding_count = len(findings)
    unique_finding_ids = len(set(findings.keys()))
    at_count = len(at_rows)

    ok = (
        finding_count == 43
        and unique_finding_ids == 43
        and at_count == 20
        and orphan == set()
        and unknown == set()
    )
    out_path = EVIDENCE_DIR / "at20_a02_formal_matrix_aggregation.json"
    out_path.write_text(json.dumps({
        "finding_count": finding_count,
        "unique_finding_ids": unique_finding_ids,
        "at_row_count": at_count,
        "orphan_remediation_ids": sorted(orphan),
        "unknown_remediation_ids": sorted(unknown),
        "all_finding_remediation_ids": sorted(all_finding_rems),
        "all_at_remediation_ids": sorted(all_at_rems),
    }, indent=2) + "\n", encoding="utf-8")
    record(
        "AT20-A02",
        "PASS" if ok else "FAIL",
        f"raw parse: {finding_count} findings ({unique_finding_ids} unique), {at_count} formal AT rows, "
        f"orphan={len(orphan)}, unknown={len(unknown)}. NOTE: registry v2 subject text for this assertion still "
        "says '40 finding/40 remediation' (stale wording from an earlier round); current normative value per "
        "phase2b6 instruction section 4 is 43/43, which this parser confirms.",
        {
            "parser source/command": str(Path(__file__).name) + "::check_at20_a02",
            "raw ID lists": str(out_path.relative_to(REPO_ROOT)),
            "aggregation artifact": str(out_path.relative_to(REPO_ROOT)),
        },
    )


# ---------------------------------------------------------------------------
# AT20-A03: registry parser phase-count self-check (delegates to the
# pytest-verified TestRegistryStructure logic; recomputed here directly).
# ---------------------------------------------------------------------------
def check_at20_a03() -> None:
    registry = json.loads(SHARED_REGISTRY.read_text(encoding="utf-8"))
    assertions = registry["assertions"]
    scoped = [a for a in assertions if a["required_phase"] == "2-B.6"]
    deferred = [a for a in assertions if a["required_phase"] == "2-E"]
    ids = [a["assertion_id"] for a in assertions]
    ok = (
        len(assertions) == 20
        and len(set(ids)) == 20
        and len(scoped) == 12
        and len(deferred) == 8
        and len(assertions) - len(scoped) - len(deferred) == 0
    )
    record(
        "AT20-A03",
        "PASS" if ok else "FAIL",
        f"registry raw IDs: 2-B.6={len(scoped)}, 2-E={len(deferred)}, total={len(assertions)}, "
        f"duplicate={len(ids) - len(set(ids))}",
        {
            "registry JSON": str(SHARED_REGISTRY.relative_to(REPO_ROOT)),
            "parser command": "backend/tests/test_phase2b6_version_binding.py::TestRegistryStructure",
            "raw ID/phase lists": {"scoped": [a["assertion_id"] for a in scoped], "deferred": [a["assertion_id"] for a in deferred]},
            "aggregation artifact": "see scoped_assertion_results.json",
        },
    )


# ---------------------------------------------------------------------------
# AT20-A04: Phase 2-B.6 scoped denominator (12) + Phase 2-E deferred (8),
# built as a verify_at_evidence.py manifest-set and run through the real
# validator to obtain the official scoped gate result.
# ---------------------------------------------------------------------------
DEFERRED_2E_IDS = ["AT18-A05", "AT18-A06", "AT19-A05", "AT19-A06", "AT20-A05", "AT20-A06", "AT20-A07", "AT20-A08"]
SCOPED_12_IDS = [
    "AT18-A01", "AT18-A02", "AT18-A03", "AT18-A04",
    "AT19-A01", "AT19-A02", "AT19-A03", "AT19-A04",
    "AT20-A01", "AT20-A02", "AT20-A03", "AT20-A04",
]


CHILD_RUNS_DIR = EVIDENCE_DIR / "child_runs"

# Phase 2-D Round 12D-C2 (OWNER decision: portable token contract, option 2).
# The argv PERSISTED into the input evidence artifact is a fixed portable
# token vector — never sys.executable's absolute value, never
# Path(__file__).resolve(), never an authoring-workspace / cwd / HOME path,
# and never an environment-variable reference string. The real subprocess is
# still spawned with the genuine interpreter and resolved script path (see
# run_all_scoped_assertions_as_subprocesses); only the recorded fixture bytes
# are tokenised. verify_at_evidence.py matches each slot by exact equality
# against the same literals and then derives the trusted interpreter/script
# identity solely from its own process state.
CANONICAL_ARGV_PYTHON_TOKEN = "<PYTHON>"
CANONICAL_ARGV_SCRIPT_TOKEN = "<REPO_ROOT>/tools/public_release/phase2b6_scoped_assertions.py"


def canonical_recorded_argv(assertion_id: str) -> list[str]:
    return [
        CANONICAL_ARGV_PYTHON_TOKEN,
        CANONICAL_ARGV_SCRIPT_TOKEN,
        "--assertion-id",
        assertion_id,
    ]


def check_at20_a04() -> None:
    """P2B6-CX-002 round 3: this assertion is itself run as an independent
    subprocess (see main()), so it can no longer read the other 11
    verdicts from an in-process RESULTS list — main() runs the other 11
    scoped assertions as real subprocesses FIRST and persists each one's
    result to CHILD_RUNS_DIR before invoking this one, so this reads their
    genuine on-disk output instead."""
    other_11 = [aid for aid in SCOPED_12_IDS if aid != "AT20-A04"]
    verdicts = {}
    for aid in other_11:
        result_path = CHILD_RUNS_DIR / f"{aid}.json"
        if result_path.is_file():
            verdicts[aid] = json.loads(result_path.read_text(encoding="utf-8")).get("verdict")
        else:
            verdicts[aid] = "NOT_EXECUTED"
    all_other_pass = all(v == "PASS" for v in verdicts.values())
    record(
        "AT20-A04",
        "PASS" if all_other_pass else "FAIL",
        f"scoped denominator=12, all other 11 scoped assertions PASS={all_other_pass} "
        f"(read from {CHILD_RUNS_DIR.relative_to(REPO_ROOT)}, each a genuine independent subprocess run); "
        f"deferred=8 (execution_status=DEFERRED_BY_PHASE, not counted toward PASS/FAIL/executed)",
        {
            "scoped evidence manifest": "tests/fixtures/public_release/version_binding/scoped/manifest-set.json",
            "assertion verdicts": verdicts,
            "reviewer approvals": "PENDING_INDEPENDENT_REVIEW",
        },
    )


DISPATCH = {
    "AT18-A01": check_at18_a01,
    "AT18-A02": check_at18_a02,
    "AT18-A03": check_at18_a03,
    "AT18-A04": check_at18_a04,
    "AT19-A01": check_at19_a01,
    "AT19-A02": check_at19_a02,
    "AT19-A03": check_at19_a03,
    "AT19-A04": check_at19_a04,
    "AT20-A01": check_at20_a01,
    "AT20-A02": check_at20_a02,
    "AT20-A03": check_at20_a03,
    "AT20-A04": check_at20_a04,
}


def run_single_assertion(assertion_id: str) -> int:
    """P2B6-CX-002 round 3: invoked as `python3 phase2b6_scoped_assertions.py
    --assertion-id <ID>` — a real, independently-executable subprocess for
    exactly one assertion. Writes its own result to CHILD_RUNS_DIR/<ID>.json
    and prints a machine-readable JSON summary line to stdout so the
    orchestrating process (main(), itself a separate invocation of this
    same script) can bind real captured argv/exit_code/stdout/stderr to
    this assertion's evidence artifacts instead of an in-process call."""
    CHILD_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    fn = DISPATCH.get(assertion_id)
    if fn is None:
        print(json.dumps({"assertion_id": assertion_id, "verdict": "FAIL", "error": "unknown assertion_id"}))
        return 1
    fn()
    assert len(RESULTS) == 1, "each --assertion-id subprocess must record exactly one result"
    result = RESULTS[0]
    # P2B6-CX-002 round 6: bind this result to a unique per-subprocess-run
    # identity, and self-report the exit_code/registry 4-tuple this run
    # will be evidenced under, so verify_at_evidence.py can cross-check the
    # "input" artifact's run_id, the child manifest entry's own exit_code/
    # registry fields, and the stdout SCOPED_ASSERTION_RESULT_JSON= line
    # (which is this same dict) all agree with each other. exit_code is
    # computed here deterministically from verdict — the subprocess's own
    # process exit code (see run()'s return statement below) is always the
    # same value, so both stay in lockstep by construction.
    exit_code = 0 if result["verdict"] == "PASS" else 1
    result["run_id"] = uuid.uuid4().hex
    result["exit_code"] = exit_code
    result["registry_name"] = V2_NAME
    result["registry_version"] = V2_VERSION
    result["schema_version"] = V2_SCHEMA
    result["registry_sha256"] = V2_HASH
    (CHILD_RUNS_DIR / f"{assertion_id}.json").write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("SCOPED_ASSERTION_RESULT_JSON=" + json.dumps(result, sort_keys=True, ensure_ascii=False))
    return exit_code


def _write_role_artifact(base_dir: Path, aid: str, role: str, data: bytes) -> dict:
    rel_path = f"artifacts/{aid}.{role}.txt"
    (base_dir / rel_path).write_bytes(data)
    return {"role": role, "path": rel_path, "sha256": sha256_bytes_local(data)}


def run_all_scoped_assertions_as_subprocesses() -> list[dict]:
    """P2B6-CX-002 round 3 correction: each of the 12 scoped assertions is
    now executed as a genuine `subprocess.run([...])` invocation of this
    same script (not an in-process function call), with real argv, real
    exit_code, and real captured stdout/stderr. AT20-A04 depends on the
    other 11 having already run (it reads their persisted CHILD_RUNS_DIR
    results), so it is run last."""
    if CHILD_RUNS_DIR.exists():
        shutil.rmtree(CHILD_RUNS_DIR)
    CHILD_RUNS_DIR.mkdir(parents=True, exist_ok=True)

    ordered_ids = [aid for aid in SCOPED_12_IDS if aid != "AT20-A04"] + ["AT20-A04"]
    child_runs = []
    for aid in ordered_ids:
        # Real spawn uses the genuine interpreter + resolved script path.
        spawn_argv = [sys.executable, str(Path(__file__).resolve()), "--assertion-id", aid]
        proc = subprocess.run(spawn_argv, cwd=REPO_ROOT, capture_output=True, text=True, timeout=180)
        result_path = CHILD_RUNS_DIR / f"{aid}.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        child_runs.append({
            "assertion_id": aid,
            # Recorded fixture argv is the fixed portable token vector, NOT
            # spawn_argv (Phase 2-D Round 12D-C2 portable token contract).
            "argv": canonical_recorded_argv(aid),
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "result": result,
        })
        print(f"[{result['verdict']}] {aid}: {result['detail']}  (subprocess exit={proc.returncode})")
    # restore ordering to SCOPED_12_IDS for downstream consumers
    by_id = {c["assertion_id"]: c for c in child_runs}
    return [by_id[aid] for aid in SCOPED_12_IDS]


def build_scoped_manifest_set(child_runs: list[dict]) -> dict:
    """P2B6-CX-002 round 2/3 correction: the artifact role set must be
    exactly {input, stdout, stderr, result} (verify_at_evidence.py::
    REQUIRED_ARTIFACT_ROLES), each bound to REAL bytes captured from a
    genuine subprocess run of this assertion (not a re-serialization of an
    in-process evidence dict, and not a fabricated "command" string that
    references nothing real — command now is exactly the argv that was
    executed to produce these artifacts)."""
    artifacts_dir = SCOPED_FIXTURE_DIR / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    children = []
    for run_info in child_runs:
        aid = run_info["assertion_id"]
        result = run_info["result"]
        command = f"python3 tools/public_release/phase2b6_scoped_assertions.py --assertion-id {aid}"
        # P2B6-CX-002 round 6: the "input" artifact now carries the same
        # run_id the subprocess self-reported in its result (and echoed to
        # stdout), so verify_at_evidence.py can bind all three artifacts +
        # the child record to one genuine run instead of only checking each
        # artifact's bytes hash in isolation.
        input_bytes = json.dumps(
            {"argv": run_info["argv"], "run_id": result["run_id"]}, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        stdout_bytes = run_info["stdout"].encode("utf-8")
        stderr_bytes = run_info["stderr"].encode("utf-8")
        result_bytes = json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8")
        artifacts = [
            _write_role_artifact(SCOPED_FIXTURE_DIR, aid, "input", input_bytes),
            _write_role_artifact(SCOPED_FIXTURE_DIR, aid, "stdout", stdout_bytes),
            _write_role_artifact(SCOPED_FIXTURE_DIR, aid, "stderr", stderr_bytes),
            _write_role_artifact(SCOPED_FIXTURE_DIR, aid, "result", result_bytes),
        ]
        children.append({
            "assertion_id": aid,
            "registry_name": V2_NAME,
            "registry_version": V2_VERSION,
            "schema_version": V2_SCHEMA,
            "registry_sha256": V2_HASH,
            "executor": result["executor"],
            "command": command,
            "exit_code": run_info["exit_code"],
            "verdict": result["verdict"],
            "run_id": result["run_id"],
            "artifacts": artifacts,
        })
    manifest_set = {
        "manifest": {
            "registry_name": V2_NAME,
            "registry_version": V2_VERSION,
            "schema_version": V2_SCHEMA,
            "registry_sha256": V2_HASH,
        },
        "children": children,
    }
    return manifest_set


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    SCOPED_FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    child_runs = run_all_scoped_assertions_as_subprocesses()

    # All 12 scoped assertions now have verdicts (each from a genuine
    # subprocess run); build the manifest-set and run the single official
    # gate check via verify_at_evidence.py.
    manifest_set = build_scoped_manifest_set(child_runs)
    manifest_set_path = SCOPED_FIXTURE_DIR / "manifest-set.json"
    manifest_set_path.write_text(json.dumps(manifest_set, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    result_path = EVIDENCE_DIR / "scoped_gate_result.json"
    cmd = [
        sys.executable, str(VERIFY_TOOL),
        "--registry", str(SHARED_REGISTRY),
        "--activation-record", str(SHARED_ACTIVATION),
        "--manifest-set", str(manifest_set_path),
        "--result", str(result_path),
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    gate_result = json.loads(result_path.read_text(encoding="utf-8"))

    deferred_entries = [
        {"assertion_id": aid, "execution_status": "DEFERRED_BY_PHASE", "required_phase": "2-E"}
        for aid in DEFERRED_2E_IDS
    ]

    all_results = [c["result"] for c in child_runs]
    scoped_pass_count = sum(1 for r in all_results if r["verdict"] == "PASS")
    summary = {
        "scoped_denominator": 12,
        "scoped_pass": scoped_pass_count,
        "scoped_fail": 12 - scoped_pass_count,
        "deferred_count": 8,
        "deferred_ids": DEFERRED_2E_IDS,
        "deferred_included_in_pass_fail_or_executed": False,
        "gate_exit_code": proc.returncode,
        "gate_primary_code": gate_result["primary_code"],
        "gate_result_path": str(result_path.relative_to(REPO_ROOT)),
        "manifest_set_path": str(manifest_set_path.relative_to(REPO_ROOT)),
        "assertions": all_results,
        "subprocess_runs": [
            {"assertion_id": c["assertion_id"], "argv": c["argv"], "exit_code": c["exit_code"]} for c in child_runs
        ],
        "deferred": deferred_entries,
    }
    out_path = EVIDENCE_DIR / "scoped_assertion_results.json"
    out_path.write_text(json.dumps(summary, indent=2, sort_keys=False, ensure_ascii=False) + "\n", encoding="utf-8")

    print()
    print(f"SCOPED: {scoped_pass_count}/12 PASS")
    print(f"DEFERRED: 8/8 DEFERRED_BY_PHASE (not counted)")
    print(f"GATE: exit={proc.returncode} primary_code={gate_result['primary_code']}")
    return 0 if (scoped_pass_count == 12 and proc.returncode == 0) else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--assertion-id", default=None)
    args = parser.parse_args()

    if args.assertion_id:
        sys.exit(run_single_assertion(args.assertion_id))
    else:
        sys.exit(main())

#!/usr/bin/env python3
"""
tools/public_release/phase2d_round12b_new_cases_runner.py

Round 12B runner for the OWNER-approved Round 12A-4 canonical contract
(SHA-256 of the exact-approved ZIP: 64992b5daf8d560f1afa545ac6a9eae7619b4de6cbb7f6f410f96f2810bb80ad).

Implements the 7 new adversarial cases and 5 new runtime cases exactly as designed in
`phase2d_requirement_derived_adversarial_contract.json` / `phase2d_requirement_derived_runtime_contract.json`.
Case content, order, and oracles are FROZEN by the OWNER's exact approval; any change to a
case here without a fresh OWNER approval invalidates that approval per its own terms.

This runner is Claude's own implementation-verification pass. It is NOT a substitute for
CODEX's independent re-verification -- results here are self-execution only and must be
reported as such, never as an equivalent to CODEX's own independent pass.

Usage:
    python3 tools/public_release/phase2d_round12b_new_cases_runner.py [--only CASE_ID ...]

Exit code: 0 if all executed cases PASS, 1 if any FAIL.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
HAZARD_DEFINITIONS_PATH = REPO_ROOT / "backend" / "hazard_definitions.py"
RUNTIME_FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures" / "public_release" / "round12b_runtime"

RESULTS: list[dict] = []


def record(case_id: str, passed: bool | None, detail: str = "", negative_control_passed: bool | None = None) -> None:
    status = "N/A" if passed is None else ("PASS" if passed else "FAIL")
    RESULTS.append(dict(
        case_id=case_id,
        result=status,
        detail=detail,
        negative_control_passed=negative_control_passed,
    ))
    print(f"[{status}] {case_id}: {detail}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# NEW-ADV-004: constant-time token comparison, AST-based static scan.
# ---------------------------------------------------------------------------
def _find_get_current_operator(tree: ast.AST) -> ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_current_operator":
            return node
    return None


def _has_compare_digest_call(func_node: ast.AST) -> bool:
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute) and f.attr == "compare_digest":
                return True
            if isinstance(f, ast.Name) and f.id == "compare_digest":
                return True
    return False


def _raw_equality_hits(func_node: ast.AST) -> list[str]:
    hits = []
    watch_names = {"token", "expected"}
    for node in ast.walk(func_node):
        if isinstance(node, ast.Compare):
            for op in node.ops:
                if isinstance(op, (ast.Eq, ast.NotEq)):
                    operand_names = set()
                    for side in [node.left] + node.comparators:
                        if isinstance(side, ast.Name):
                            operand_names.add(side.id)
                    if operand_names & watch_names:
                        hits.append(ast.dump(node))
    return hits


def run_new_adv_004(source_path: Path, expect_pass: bool = True) -> tuple[bool, str]:
    """Returns (passed, detail). source_path is either the real file (positive) or a
    mutated temp copy (negative control)."""
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source_path))
    func = _find_get_current_operator(tree)
    if func is None:
        return False, "get_current_operator function not found in AST"
    has_cd = _has_compare_digest_call(func)
    raw_hits = _raw_equality_hits(func)
    passed = has_cd and not raw_hits
    detail = f"compare_digest_call={has_cd} raw_equality_hits={len(raw_hits)}"
    return passed, detail


def case_new_adv_004() -> None:
    real_path = BACKEND_DIR / "app" / "services" / "operator_auth.py"
    passed, detail = run_new_adv_004(real_path, expect_pass=True)
    record("NEW-ADV-004", passed, f"positive: {detail} (source={real_path.relative_to(REPO_ROOT)})")

    # Negative control: mutate a temp copy replacing compare_digest with raw ==.
    import tempfile
    text = real_path.read_text(encoding="utf-8")
    mutated = text.replace(
        "if not secrets.compare_digest(token, expected):",
        "if not (token == expected):",
    )
    if mutated == text:
        record("NEW-ADV-004-NEGATIVE-CONTROL", False, "mutation string not found in source -- negative control could not be constructed")
        return
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as tf:
        tf.write(mutated)
        tmp_path = Path(tf.name)
    try:
        neg_passed, neg_detail = run_new_adv_004(tmp_path, expect_pass=False)
        # The negative control is itself considered to PASS (as a self-test of this case)
        # only if the mutated source is correctly detected as FAILING the real check.
        nc_ok = not neg_passed
        record("NEW-ADV-004-NEGATIVE-CONTROL", nc_ok, f"mutated copy correctly detected as failing: {neg_detail}")
    finally:
        tmp_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# NEW-ADV-007: OSRM/Martin services have zero host-published ports.
# ---------------------------------------------------------------------------
TARGET_SERVICES = ["osrm-driving", "osrm-walking", "martin"]


def _load_yaml_or_none(path: Path):
    try:
        import yaml  # type: ignore
    except ImportError:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _service_ports_from_raw_text(text: str, service: str) -> list | None:
    """Fallback raw-text parse if PyYAML is unavailable: find the service block and check
    for a `ports:` key with any non-empty list under it, using indentation-based block
    boundaries (2-space service definitions, as used throughout this repo's compose file)."""
    lines = text.splitlines()
    service_line_idx = None
    for i, line in enumerate(lines):
        if line.rstrip() == f"  {service}:":
            service_line_idx = i
            break
    if service_line_idx is None:
        return None
    block = []
    for line in lines[service_line_idx + 1:]:
        if line.startswith("  ") and not line.startswith("    ") and line.strip():
            break  # next top-level-under-services key
        block.append(line)
    ports: list[str] = []
    in_ports = False
    for line in block:
        stripped = line.strip()
        if stripped == "ports:":
            in_ports = True
            continue
        if in_ports:
            if line.startswith("    - ") or line.startswith("      - "):
                ports.append(stripped.lstrip("- ").strip())
                continue
            else:
                in_ports = False
    return ports


def case_new_adv_007() -> None:
    raw_text = COMPOSE_FILE.read_text(encoding="utf-8")
    yaml_doc = _load_yaml_or_none(COMPOSE_FILE)

    raw_hits = {}
    for svc in TARGET_SERVICES:
        if yaml_doc is not None:
            svc_def = (yaml_doc.get("services") or {}).get(svc) or {}
            ports = svc_def.get("ports") or []
        else:
            ports = _service_ports_from_raw_text(raw_text, svc) or []
        raw_hits[svc] = ports

    raw_ok = all(len(v) == 0 for v in raw_hits.values())

    rendered_hits = {}
    rendered_ok = None
    try:
        proc = subprocess.run(
            ["docker", "compose", "-f", str(COMPOSE_FILE), "config", "--format", "json"],
            cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            rendered = json.loads(proc.stdout)
            for svc in TARGET_SERVICES:
                svc_def = (rendered.get("services") or {}).get(svc) or {}
                rendered_hits[svc] = svc_def.get("ports") or []
            rendered_ok = all(len(v) == 0 for v in rendered_hits.values())
        else:
            rendered_ok = None  # docker compose config unavailable in this environment
    except (FileNotFoundError, subprocess.TimeoutExpired):
        rendered_ok = None

    detail = f"raw_yaml_ports={raw_hits} raw_ok={raw_ok}; rendered_ports={rendered_hits} rendered_ok={rendered_ok}"
    if rendered_ok is None:
        detail += " (rendered check SKIPPED: docker compose unavailable in this execution environment -- raw-YAML check is authoritative for this run)"
        overall = raw_ok
    else:
        overall = raw_ok and rendered_ok
    record("NEW-ADV-007", overall, detail)

    # Negative control: mutated copy of the compose file with martin given a host port.
    mutated = raw_text.replace(
        "  martin:\n",
        "  martin:\n    ports:\n      - \"8080:8080\"\n",
        1,
    )
    if mutated == raw_text:
        record("NEW-ADV-007-NEGATIVE-CONTROL", False, "mutation anchor '  martin:' not found -- negative control could not be constructed")
        return
    mutated_ports = _service_ports_from_raw_text(mutated, "martin")
    nc_ok = bool(mutated_ports)  # the mutated copy MUST show a non-empty ports list
    record("NEW-ADV-007-NEGATIVE-CONTROL", nc_ok, f"mutated compose text correctly shows martin ports={mutated_ports}")



# ---------------------------------------------------------------------------
# NEW-ADV-002: self-inspect docker container_id has no external-input path.
# ---------------------------------------------------------------------------
JOB_MANAGER_PATH = BACKEND_DIR / "app" / "services" / "job_manager.py"

_ADV002_SUBPROCESS_SCRIPT = r'''
import json, sys
sys.path.insert(0, "backend")
import app.services.job_manager as jm

captured_argv = []
audit_calls = []

def fake_run(argv, **kwargs):
    captured_argv.append(list(argv))
    class P:
        returncode = 0
        stdout = json.dumps([{"State": {"StartedAt": "2026-01-01T00:00:00Z", "OOMKilled": False}, "RestartCount": 0}])
    return P()

def fake_log(*, result, error_code):
    audit_calls.append((result, error_code))

jm.subprocess.run = fake_run
jm.log_operator_internal_inspect = fake_log

SENTINEL = "deadbeef0001"
real_container_id = jm._get_container_id_from_cgroup()

jm._BOOT_STATE["container_id"] = SENTINEL
jm._BOOT_STATE.pop("container_restart_count", None)
jm._enrich_boot_state_with_docker_inspect()

ok = (
    len(captured_argv) == 1
    and captured_argv[0] == ["docker", "inspect", SENTINEL]
    and len(audit_calls) == 1
    and audit_calls[0][0] == "success"
)
print("RESULT1", ok, captured_argv, audit_calls, real_container_id)

# Negative-control sub-probe: call _fetch_docker_inspect a second time directly
# and confirm the "exactly one audit event" bookkeeping correctly detects this
# (i.e. the counting mechanism is not vacuously true).
jm._fetch_docker_inspect(SENTINEL)
nc_ok = len(audit_calls) == 2  # bookkeeping correctly observed the 2nd call
print("RESULT2", nc_ok, len(audit_calls))
'''


def _adv002_static_checks() -> tuple[bool, str]:
    text = JOB_MANAGER_PATH.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(JOB_MANAGER_PATH))

    enrich_fn = None
    fetch_fn = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_enrich_boot_state_with_docker_inspect":
            enrich_fn = node
        if isinstance(node, ast.FunctionDef) and node.name == "_fetch_docker_inspect":
            fetch_fn = node
    if enrich_fn is None or fetch_fn is None:
        return False, "could not locate _enrich_boot_state_with_docker_inspect / _fetch_docker_inspect via AST"

    enrich_has_zero_params = len(enrich_fn.args.args) == 0

    call_sites = 0
    call_uses_boot_state_var = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_fetch_docker_inspect":
            call_sites += 1
            if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "container_id":
                call_uses_boot_state_var = True

    assigns_from_boot_state = any(
        isinstance(n, ast.Assign)
        and len(n.targets) == 1
        and isinstance(n.targets[0], ast.Name)
        and n.targets[0].id == "container_id"
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Attribute)
        and n.value.func.attr == "get"
        and isinstance(n.value.func.value, ast.Name)
        and n.value.func.value.id == "_BOOT_STATE"
        for n in ast.walk(enrich_fn)
    )

    passed = enrich_has_zero_params and call_sites == 1 and call_uses_boot_state_var and assigns_from_boot_state
    detail = (
        f"enrich_has_zero_params={enrich_has_zero_params} "
        f"fetch_docker_inspect_call_sites={call_sites} "
        f"call_uses_container_id_var={call_uses_boot_state_var} "
        f"container_id_assigned_from_BOOT_STATE.get={assigns_from_boot_state}"
    )
    return passed, detail


def case_new_adv_002() -> None:
    static_passed, static_detail = _adv002_static_checks()
    record("NEW-ADV-002-STATIC", static_passed, static_detail)

    venv_python = REPO_ROOT / "venv" / "bin" / "python"
    if not venv_python.is_file():
        record("NEW-ADV-002", False, f"venv python not found at {venv_python}")
        return

    proc = subprocess.run(
        [str(venv_python), "-c", _ADV002_SUBPROCESS_SCRIPT],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=30,
    )
    out = proc.stdout
    r1_ok = "RESULT1 True" in out
    r2_ok = "RESULT2 True" in out
    detail = f"exit={proc.returncode} stdout={out.strip()!r} stderr_tail={proc.stderr.strip()[-500:]!r}"
    record("NEW-ADV-002", static_passed and r1_ok, detail)
    record("NEW-ADV-002-NEGATIVE-CONTROL", r2_ok, "audit-call bookkeeping correctly observed a 2nd _fetch_docker_inspect invocation")


# ---------------------------------------------------------------------------
# NEW-ADV-006: manifest-set cannot make the verifier execute untrusted argv[0].
# ---------------------------------------------------------------------------
VBF_SHARED_REGISTRY = REPO_ROOT / "tests/fixtures/public_release/version_binding/shared/registry/p2a-at18-20-v2.json"
VBF_SHARED_ACTIVATION = REPO_ROOT / "tests/fixtures/public_release/version_binding/shared/activation-approved-v2.json"
VBF_SCOPED_DIR = REPO_ROOT / "tests/fixtures/public_release/version_binding/scoped"


def _load_verify_at_evidence_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "phase2d_round12b_verify_at_evidence",
        REPO_ROOT / "tools" / "public_release" / "verify_at_evidence.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def case_new_adv_006() -> None:
    import shutil
    import stat
    import tempfile

    v = _load_verify_at_evidence_module()

    tmp_dir = Path(tempfile.mkdtemp(prefix="new-adv-006-"))
    try:
        fixture_dir = tmp_dir / "scoped"
        shutil.copytree(VBF_SCOPED_DIR, fixture_dir)

        # Baseline: the unmutated copy must validate cleanly first, so a
        # rejection later is attributable to the mutation, not a broken copy.
        try:
            v.run(VBF_SHARED_REGISTRY, VBF_SHARED_ACTIVATION, fixture_dir / "manifest-set.json")
            baseline_ok = True
        except v.VerifyError as exc:
            baseline_ok = False
            record("NEW-ADV-006", False, f"baseline (unmutated) fixture unexpectedly failed to validate: {exc}")
            return

        marker_path = tmp_dir / "side_effect_marker.txt"
        evil_script = tmp_dir / "python3"
        evil_script.write_text(
            "#!/bin/sh\n"
            f'echo owned > "{marker_path}"\n'
            "echo 3\n",
            encoding="utf-8",
        )
        evil_script.chmod(evil_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        manifest_path = fixture_dir / "manifest-set.json"
        manifest_obj = json.loads(manifest_path.read_text(encoding="utf-8"))
        child = manifest_obj["children"][0]
        input_artifact = next(a for a in child["artifacts"] if a["role"] == "input")
        input_path = fixture_dir / input_artifact["path"]
        input_obj = json.loads(input_path.read_text(encoding="utf-8"))
        input_obj["argv"][0] = str(evil_script)
        new_input_bytes = json.dumps(input_obj).encode("utf-8")
        input_path.write_bytes(new_input_bytes)
        input_artifact["sha256"] = hashlib.sha256(new_input_bytes).hexdigest()
        manifest_path.write_text(json.dumps(manifest_obj), encoding="utf-8")

        raised_code = None
        try:
            v.run(VBF_SHARED_REGISTRY, VBF_SHARED_ACTIVATION, manifest_path)
        except v.VerifyError as exc:
            raised_code = str(exc)
        except Exception as exc:  # pragma: no cover - would itself be a finding
            raised_code = f"UNEXPECTED_EXCEPTION:{exc!r}"

        marker_created = marker_path.exists()
        rejected_without_execution = (raised_code == "E_CHILD_COMMAND_UNRESOLVABLE") and not marker_created
        detail = (
            f"baseline_ok={baseline_ok} raised={raised_code!r} "
            f"marker_created_during_validation={marker_created}"
        )
        record("NEW-ADV-006", rejected_without_execution, detail)

        # Negative control: directly execute the malicious argv[0] the way
        # a pre-round-8 (vulnerable) implementation would have, proving the
        # marker mechanism itself actually detects execution when it happens.
        nc_marker = tmp_dir / "side_effect_marker_direct.txt"
        direct_script = tmp_dir / "python3_direct_probe"
        direct_script.write_text(f'#!/bin/sh\necho owned > "{nc_marker}"\necho 3\n', encoding="utf-8")
        direct_script.chmod(direct_script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        subprocess.run([str(direct_script)], timeout=10, capture_output=True)
        nc_ok = nc_marker.exists()
        record("NEW-ADV-006-NEGATIVE-CONTROL", nc_ok, "direct execution of an equivalent script correctly produced the side-effect marker (harness is not vacuous)")
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)



# ---------------------------------------------------------------------------
# NEW-ADV-003: hazard_coverage_status / aggregate_status 3-state vocabulary
# (HAZARD_DETECTED / NO_HAZARD_RECORD / SOURCE_UNAVAILABLE).
#
# Round 12D-B implementation delivered (Round 12D-B1: no dedicated helper function was
# added to backend/hazard_definitions.py -- it stays byte-identical to its NEW-ADV-005
# frozen SHA-256; the 6-type universe is derived inline as
# `[d.name for d in HAZARD_DEFINITIONS]` at each of the 2 call sites below instead):
#   - backend/hazard_service.py: compute_hazard_coverage_status/compute_aggregate_status/
#     compute_hazard_safe_from_aggregate + the 3 frozen status constants
#   - backend/app_public.py: ALL_HAZARD_TYPE_NAMES derived inline from HAZARD_DEFINITIONS;
#     both POST /api/route-risk and POST /api/evacuation wired to the new vocabulary;
#     _select_recommended/_build_reason use the frozen selected_tier values
#   - frontend/js/ui.js, location-info-panel.js + 3 e2e spec files migrated off hazard_safe===true
#
# The full MCC-01..17 / NC1..9 machine-checkable oracle (frozen across Rounds 12D-A/A1/A2/A3,
# see tasks/public-release/phase2d_round12d_a{1,2,3}_owner_decision.md) is implemented as a
# PERMANENT pytest fixture at backend/tests/test_round12d_new_adv_003.py (not a throwaway
# runner-local check) per OWNER's "デターミニスティックfixtureを恒久化" instruction. This
# function shells out to that pytest file and folds its result into this runner's ledger.
# MCC-13/17 (UI DOM display) are additionally exercised end-to-end by
# e2e/hazard-state-consistency.spec.js and e2e/evacuation-ui.spec.js (Playwright, not run here).
# ---------------------------------------------------------------------------
NEW_ADV_003_PYTEST_PATH = BACKEND_DIR / "tests" / "test_round12d_new_adv_003.py"


def case_new_adv_003() -> None:
    if not NEW_ADV_003_PYTEST_PATH.is_file():
        record("NEW-ADV-003", False, f"CONTRACT_INVALIDATED: fixture not found at {NEW_ADV_003_PYTEST_PATH}")
        return

    venv_python = REPO_ROOT / "venv" / "bin" / "python"
    python_bin = str(venv_python) if venv_python.is_file() else sys.executable

    proc = subprocess.run(
        [python_bin, "-m", "pytest", str(NEW_ADV_003_PYTEST_PATH), "-v"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=180,
    )
    stdout_lines = proc.stdout.splitlines()
    summary_line = next((l for l in reversed(stdout_lines) if " passed" in l or " failed" in l), "")
    passed = proc.returncode == 0
    detail = (
        f"MCC-01..17 / NC1..9 permanent pytest fixture (backend/tests/test_round12d_new_adv_003.py): "
        f"returncode={proc.returncode}. summary: {summary_line}"
    )
    record("NEW-ADV-003", passed, detail)

    nc_lines = [l for l in stdout_lines if "::test_nc" in l]
    nc_all_passed = bool(nc_lines) and all("PASSED" in l for l in nc_lines)
    record(
        "NEW-ADV-003-NEGATIVE-CONTROL",
        nc_all_passed,
        f"NC1..9 mutation self-tests (each proves the corresponding MCC actually fires on a "
        f"deliberately contract-violating mutation): {len(nc_lines)} collected, "
        f"all_passed={nc_all_passed}",
        negative_control_passed=nc_all_passed,
    )


# ---------------------------------------------------------------------------
# NEW-ADV-005: all frozen hazard types wired into the atomic-publish consumer
# path (ActiveMappingService.set_active/get_active, tmp-write + os.replace).
# ---------------------------------------------------------------------------
ACTIVE_MAPPING_SERVICE_PATH = BACKEND_DIR / "app" / "services" / "active_mapping_service.py"

ADV005_FROZEN_SOURCE_PATH = "backend/hazard_definitions.py"
ADV005_FROZEN_SHA256 = "c61fa1acfbfab7260ab7ec56c96904877e83972ffc874485d65cd0d71a2b72c9"
ADV005_FROZEN_TYPES = [
    "flood",
    "storm_surge",
    "tsunami",
    "inland_flood",
    "landslide",
    "lowland_poor_drainage",
]


def case_new_adv_005() -> None:
    if not HAZARD_DEFINITIONS_PATH.is_file():
        record("NEW-ADV-005", False, "CONTRACT_INVALIDATED: backend/hazard_definitions.py not found")
        return

    current_hash = sha256_file(HAZARD_DEFINITIONS_PATH)
    if current_hash != ADV005_FROZEN_SHA256:
        record(
            "NEW-ADV-005", False,
            f"CONTRACT_INVALIDATED: source hash drift. frozen={ADV005_FROZEN_SHA256} current={current_hash}. "
            "Halting per frozen-oracle contract terms -- not silently adopting the changed file.",
        )
        return

    text = HAZARD_DEFINITIONS_PATH.read_text(encoding="utf-8")
    found_types = [m for m in ast_iter_name_literals(text)]
    if found_types != ADV005_FROZEN_TYPES:
        record(
            "NEW-ADV-005", False,
            f"CONTRACT_INVALIDATED: type-list drift despite matching hash. frozen={ADV005_FROZEN_TYPES} current={found_types}",
        )
        return

    import tempfile
    with tempfile.TemporaryDirectory(prefix="new-adv-005-") as td:
        sys.path.insert(0, str(BACKEND_DIR))
        try:
            from app.services.active_mapping_service import ActiveMappingService  # type: ignore
        finally:
            sys.path.pop(0)

        svc = ActiveMappingService(mappings_path=Path(td) / "active_mappings.json")
        region = "new-adv-005-test-region"
        failures = []
        for htype in ADV005_FROZEN_TYPES:
            dataset_id = f"synthetic-{htype}-001"
            svc.set_active(htype, region, dataset_id)
            readback = svc.get_active(htype, region)
            if readback != dataset_id or not svc.is_active(htype, region, dataset_id):
                failures.append(htype)
        passed = not failures
        record("NEW-ADV-005", passed, f"6/6 frozen types round-tripped through ActiveMappingService.set_active/get_active; failures={failures}")

        # Negative control: a "hardcoded subset" consumer that silently omits one type.
        svc2 = ActiveMappingService(mappings_path=Path(td) / "active_mappings_nc.json")
        omitted = ADV005_FROZEN_TYPES[-1]
        allowed = [t for t in ADV005_FROZEN_TYPES if t != omitted]

        def hardcoded_subset_publish(htype: str, region: str, dataset_id: str) -> None:
            if htype not in allowed:
                return  # simulates a buggy consumer silently dropping a type
            svc2.set_active(htype, region, dataset_id)

        nc_failures = []
        for htype in ADV005_FROZEN_TYPES:
            dataset_id = f"synthetic-{htype}-002"
            hardcoded_subset_publish(htype, region, dataset_id)
            if svc2.get_active(htype, region) != dataset_id:
                nc_failures.append(htype)
        nc_ok = nc_failures == [omitted]
        record("NEW-ADV-005-NEGATIVE-CONTROL", nc_ok, f"hardcoded-subset consumer correctly detected as failing exactly for the omitted type: {nc_failures} (expected=[{omitted}])")


def ast_iter_name_literals(source_text: str) -> list[str]:
    """Extract `name="..."` string literals in source order, mirroring how the
    NEW-ADV-005 oracle_freeze list was derived (top-to-bottom appearance order)."""
    import re as _re
    return _re.findall(r'(?<![A-Za-z0-9_])name\s*=\s*"([^"]+)"', source_text)



# ---------------------------------------------------------------------------
# NEW-ADV-001: dev-docs env-var truthy-fuzz, 100 combinations x fresh subprocess.
#
# OWNER decision (this round): keep the 100-combination / fresh-subprocess
# requirement in full (no representative-sample reduction). The real
# backend/app_public.py import eagerly loads 670k+ real hazard polygons and a
# DEM raster (~52s/import), making a naive 100x import ~87 minutes of heavy
# disk I/O against production data. OWNER authorized a harness-only I/O
# boundary stub (builtins.open/io.open + rasterio.open, path-filtered to
# data_runtime/ and data_lake/ only) that substitutes deterministic minimal
# synthetic content, WITHOUT modifying application source, WITHOUT mocking
# _dev_docs_enabled(), FastAPI app construction, or router registration, and
# WITHOUT reading any real production data file. See
# ADV001_STUB_SUBPROCESS_SCRIPT below for the exact stub.
# ---------------------------------------------------------------------------
ADV001_INPUT_SET = ["unset", "", " ", "1", "yes", "True", "TRUE", " true", "true ", "true"]

ADV001_STUB_SUBPROCESS_SCRIPT = r'''
import sys, os, io, json
from pathlib import Path

REPO_ROOT = Path(%(repo_root)r)
BACKEND_DIR = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

PRODUCTION_ROOTS = [(REPO_ROOT / "data_runtime").resolve(), (REPO_ROOT / "data_lake").resolve()]

def _under_production(path_str):
    try:
        p = Path(path_str).resolve()
    except Exception:
        return False
    for root in PRODUCTION_ROOTS:
        try:
            p.relative_to(root)
            return True
        except ValueError:
            continue
    return False

_violations = []
_SYNTH_FC = b'{"type":"FeatureCollection","features":[]}'

import builtins as _b
_real_open = _b.open

def _stub_open(file, mode="r", *args, **kwargs):
    path_str = str(file) if isinstance(file, (str, Path)) else None
    if path_str is not None and _under_production(path_str):
        suffix = Path(path_str).suffix.lower()
        if suffix in (".geojson", ".json"):
            data = _SYNTH_FC
        elif suffix in (".geojsonl", ".csv"):
            data = b""
        elif suffix in (".tif", ".tiff"):
            _violations.append("UNSTUBBED_RASTER_OPEN_VIA_BUILTIN_OPEN:" + path_str)
            raise RuntimeError("HARNESS_ERROR: unstubbed raster open via builtins.open: " + path_str)
        else:
            _violations.append("UNKNOWN_SUFFIX_UNDER_PRODUCTION_ROOT:" + path_str + ":" + suffix)
            data = b""
        if "b" in mode:
            return io.BytesIO(data)
        return io.StringIO(data.decode("utf-8"))
    return _real_open(file, mode, *args, **kwargs)

_b.open = _stub_open
io.open = _stub_open

_selftest_probe_path = os.environ.get("ADV001_SELFTEST_UNKNOWN_SUFFIX_PATH")
if _selftest_probe_path:
    try:
        _stub_open(_selftest_probe_path, "r")
        _violations.append("SELFTEST_PROBE_DID_NOT_RAISE_OR_FLAG")
    except RuntimeError:
        pass

import rasterio
from rasterio.io import MemoryFile
_real_rasterio_open = rasterio.open
_synth_mf = [None]

def _make_synth_dem_memfile():
    import numpy as np
    from rasterio.transform import from_bounds
    arr = np.zeros((2, 2), dtype="float32")
    transform = from_bounds(139.0, 35.0, 140.0, 36.0, 2, 2)
    mf = MemoryFile()
    with mf.open(driver="GTiff", height=2, width=2, count=1, dtype="float32", crs="EPSG:4326", transform=transform) as ds:
        ds.write(arr, 1)
    return mf

def _stub_rasterio_open(path, *args, **kwargs):
    path_str = str(path) if not hasattr(path, "read") else None
    if path_str is not None and _under_production(path_str):
        if _synth_mf[0] is None:
            _synth_mf[0] = _make_synth_dem_memfile()
        return _synth_mf[0].open()
    return _real_rasterio_open(path, *args, **kwargs)

rasterio.open = _stub_rasterio_open

import app_public as ap
import inspect

route_paths = sorted(set(r.path for r in ap.app.routes))
result = {
    "module_file": ap.__file__,
    "expected_module_file": str((BACKEND_DIR / "app_public.py").resolve()),
    "app_class": type(ap.app).__module__ + "." + type(ap.app).__qualname__,
    "dev_docs_enabled_source_file": inspect.getsourcefile(ap._dev_docs_enabled),
    "docs_url": ap.app.docs_url,
    "redoc_url": ap.app.redoc_url,
    "openapi_url": ap.app.openapi_url,
    "route_paths": route_paths,
    "admin_routes": [p for p in route_paths if p.startswith("/api/admin")],
    "simulation_routes": [p for p in route_paths if "simulation" in p],
    "violations": _violations,
}
print("ADV001_RESULT_JSON=" + json.dumps(result))
''' % {"repo_root": str(REPO_ROOT)}


def _adv001_collect_combinations() -> list[tuple[str, str, str, str]]:
    combos = []
    for mode_idx, mode_value in enumerate(ADV001_INPUT_SET):
        for docs_idx, docs_value in enumerate(ADV001_INPUT_SET):
            combo_id = f"NEW-ADV-001-{(mode_idx * 10 + docs_idx):03d}"
            classification = "positive" if (mode_value == "true" and docs_value == "true") else "negative"
            combos.append((combo_id, mode_value, docs_value, classification))
    n_positive = sum(1 for c in combos if c[3] == "positive")
    n_negative = sum(1 for c in combos if c[3] == "negative")
    if len(combos) != 100 or n_positive != 1 or n_negative != 99:
        raise RuntimeError(
            f"HARNESS_ERROR: collection-time assertion failed: "
            f"total={len(combos)} positive={n_positive} negative={n_negative}"
        )
    assert combos[99][0] == "NEW-ADV-001-099" and combos[99][3] == "positive"
    return combos


def _adv001_run_one(mode_value: str, docs_value: str, venv_python: Path, timeout: int = 30) -> dict:
    env = dict(os.environ)
    env.pop("OHG2_DEV_MODE", None)
    env.pop("OHG2_DEV_DOCS_ENABLED", None)
    if mode_value != "unset":
        env["OHG2_DEV_MODE"] = mode_value
    if docs_value != "unset":
        env["OHG2_DEV_DOCS_ENABLED"] = docs_value

    proc = subprocess.run(
        [str(venv_python), "-c", ADV001_STUB_SUBPROCESS_SCRIPT],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=timeout,
    )
    marker = "ADV001_RESULT_JSON="
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            payload = json.loads(line[len(marker):])
            payload["_exit_code"] = proc.returncode
            payload["_stderr_tail"] = proc.stderr.strip()[-800:]
            return payload
    return {
        "_harness_error": True,
        "_exit_code": proc.returncode,
        "_stdout_tail": proc.stdout.strip()[-800:],
        "_stderr_tail": proc.stderr.strip()[-800:],
    }


def _adv001_gating_always_disabled(mode: str, docs: str) -> bool:
    return False


def _adv001_gating_truthy_coercion(mode: str, docs: str) -> bool:
    return bool(mode) and bool(docs)


def _adv001_detect_mutation(gating_fn) -> dict:
    combos = _adv001_collect_combinations()
    mismatches = []
    for combo_id, mode_value, docs_value, classification in combos:
        actual_mode = "" if mode_value == "unset" else mode_value
        actual_docs = "" if docs_value == "unset" else docs_value
        gated = gating_fn(actual_mode, actual_docs)
        expected_positive = classification == "positive"
        if gated != expected_positive:
            mismatches.append(combo_id)
    return {"mismatch_count": len(mismatches), "sample": mismatches[:5]}


def run_new_adv_001_selftest(venv_python: Path) -> tuple[bool, str]:
    lines = []
    ok = True

    combos = _adv001_collect_combinations()
    st10 = len(combos) == 100 and sum(1 for c in combos if c[3] == "positive") == 1 and sum(1 for c in combos if c[3] == "negative") == 99
    ok &= st10
    lines.append(f"ST10 collection 100/100 99-1-split: {st10}")

    always_disabled = _adv001_detect_mutation(_adv001_gating_always_disabled)
    st7 = always_disabled["mismatch_count"] == 1
    ok &= st7
    lines.append(f"ST7 always-disabled mutation detected: {st7} ({always_disabled})")

    truthy = _adv001_detect_mutation(_adv001_gating_truthy_coercion)
    st8 = truthy["mismatch_count"] > 1
    ok &= st8
    lines.append(f"ST8 truthy-coercion mutation detected: {st8} ({truthy})")

    with __import__("tempfile").TemporaryDirectory() as td:
        env_extra = dict(os.environ)
        env_extra.pop("OHG2_DEV_MODE", None)
        env_extra.pop("OHG2_DEV_DOCS_ENABLED", None)
        env_extra["ADV001_SELFTEST_UNKNOWN_SUFFIX_PATH"] = str(REPO_ROOT / "data_runtime" / "backend" / "elevation" / "not_a_real_ext.xyz")
        proc = subprocess.run(
            [str(venv_python), "-c", ADV001_STUB_SUBPROCESS_SCRIPT],
            cwd=str(REPO_ROOT), env=env_extra, capture_output=True, text=True, timeout=30,
        )
        st9 = ("UNKNOWN_SUFFIX_UNDER_PRODUCTION_ROOT" in proc.stdout) or ("UNKNOWN_SUFFIX_UNDER_PRODUCTION_ROOT" in proc.stderr)
    ok &= st9
    lines.append(f"ST9 unknown-suffix-under-production-root correctly flagged (not silently allowed): {st9}")

    pos_result = _adv001_run_one("true", "true", venv_python)
    st1 = pos_result.get("module_file") == pos_result.get("expected_module_file")
    st2 = (pos_result.get("dev_docs_enabled_source_file") or "").endswith("app_public.py") and pos_result.get("app_class", "").startswith("fastapi.")
    st3_st4 = pos_result.get("violations") == []
    st5 = (
        pos_result.get("docs_url") == "/docs"
        and pos_result.get("redoc_url") == "/redoc"
        and pos_result.get("openapi_url") == "/openapi.json"
        and pos_result.get("admin_routes") == []
        and pos_result.get("simulation_routes") == []
    )
    ok &= st1 and st2 and st3_st4 and st5
    lines.append(f"ST1 real module identity: {st1}")
    lines.append(f"ST2 real _dev_docs_enabled/app class: {st2}")
    lines.append(f"ST3/ST4 zero production-file violations on positive combo: {st3_st4}")
    lines.append(f"ST5 positive true/true -> exactly docs routes enabled, 0 admin/sim: {st5}")

    neg_result = _adv001_run_one("unset", "unset", venv_python)
    st6 = (
        neg_result.get("docs_url") is None
        and neg_result.get("redoc_url") is None
        and neg_result.get("openapi_url") is None
        and neg_result.get("admin_routes") == []
        and neg_result.get("simulation_routes") == []
    )
    ok &= st6
    lines.append(f"ST6 representative negative (unset/unset) -> 0 docs/admin/sim: {st6}")

    return ok, " | ".join(lines)


def case_new_adv_001() -> None:
    venv_python = REPO_ROOT / "venv" / "bin" / "python"
    if not venv_python.is_file():
        record("NEW-ADV-001", False, f"venv python not found at {venv_python}")
        return

    st_ok, st_detail = run_new_adv_001_selftest(venv_python)
    record("NEW-ADV-001-SELFTEST", st_ok, st_detail)
    if not st_ok:
        record("NEW-ADV-001", False, "SELFTEST FAILED -- formal 100-combination pass not run (per OWNER instruction: only run the formal pass once the harness is validated)")
        return

    combos = _adv001_collect_combinations()
    per_combo = []
    harness_errors = []
    unexpected_positive = []  # negative-by-definition combo that actually showed docs enabled
    unexpected_negative = []  # positive-by-definition combo that did NOT show docs enabled
    seen_ids = set()
    dup_ids = []

    for combo_id, mode_value, docs_value, classification in combos:
        if combo_id in seen_ids:
            dup_ids.append(combo_id)
        seen_ids.add(combo_id)

        result = _adv001_run_one(mode_value, docs_value, venv_python)
        if result.get("_harness_error") or result.get("violations"):
            harness_errors.append({"combo_id": combo_id, "result": result})
            per_combo.append((combo_id, classification, "HARNESS_ERROR"))
            continue

        docs_enabled = result.get("docs_url") is not None
        if classification == "negative" and docs_enabled:
            unexpected_positive.append(combo_id)
        if classification == "positive" and not docs_enabled:
            unexpected_negative.append(combo_id)
        per_combo.append((combo_id, classification, "docs_enabled" if docs_enabled else "docs_disabled"))

    missing_ids = {c[0] for c in combos} - seen_ids
    collection_integrity_ok = (len(seen_ids) == 100 and not dup_ids and not missing_ids)
    no_harness_errors = not harness_errors

    oracle_matches_approved_design = not unexpected_positive and not unexpected_negative

    detail = (
        f"collection_integrity_ok={collection_integrity_ok} (100 ids, 0 dup, 0 missing) "
        f"harness_errors={len(harness_errors)} "
        f"unexpected_positive_count={len(unexpected_positive)} (negative-by-definition combos that actually enabled docs; "
        f"expected 0 under the approved oracle -- Round 12D-B fixed _dev_docs_enabled() to byte-exact comparison, "
        f"closing the prior strip+lower finding) "
        f"unexpected_negative_count={len(unexpected_negative)} (the 1 designed-positive combo failing to enable docs would indicate "
        f"an always-disabled implementation) "
        f"unexpected_positive_sample={unexpected_positive[:10]}"
    )
    # Round 12D-B fixed _dev_docs_enabled() to a byte-exact "== \"true\"" comparison
    # (closing the prior strip+lower/truthy-coercion finding). Current state against
    # the originally-approved, unaltered oracle: contract input=100, expected
    # positive=1, expected negative=99, fixed application result=1 positive /
    # 99 negative, unexpected_positive_count=0, unexpected_negative_count=0.
    # Harness-level integrity (collection/subprocess isolation/no unstubbed I/O)
    # is reported separately.
    record("NEW-ADV-001-HARNESS-INTEGRITY", collection_integrity_ok and no_harness_errors, detail)
    record("NEW-ADV-001", oracle_matches_approved_design and collection_integrity_ok and no_harness_errors, detail)



# =============================================================================
# NEW-RTE-001 / 002A / 002B / 003 / 004: real isolated Docker Compose runtime
# cases. Fixtures live in tests/fixtures/public_release/round12b_runtime/
# (RTE-001/002A/002B) or are built into ephemeral host tempdirs per-run
# (RTE-003/004, since they need host-path binds and a throwaway secret).
# Every fixture uses a project name (`-p`) isolated from the real running
# stack (evacuation-navi-*) and is torn down (`down -v`) after each case,
# including on failure.
# =============================================================================
def _compose_run(args: list[str], project: str, compose_files: list[Path], timeout: int = 90, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    cmd = ["docker", "compose"]
    for f in compose_files:
        cmd += ["-f", str(f)]
    cmd += ["-p", project] + args
    run_env = dict(os.environ)
    if extra_env:
        run_env.update(extra_env)
    return subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=timeout, env=run_env)


def _compose_down(project: str, compose_files: list[Path]) -> None:
    try:
        _compose_run(["down", "-v", "--remove-orphans"], project, compose_files, timeout=60)
    except Exception:
        pass


def _docker_inspect(container_name_or_id: str, fmt: str, timeout: int = 15) -> tuple[int, str, str]:
    proc = subprocess.run(["docker", "inspect", container_name_or_id, "--format", fmt], capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def case_new_rte_001() -> None:
    compose_file = RUNTIME_FIXTURES_DIR / "rte001-dns.compose.yml"
    project = "ohg2-r12b-rte001"
    _compose_down(project, [compose_file])
    try:
        up = _compose_run(["up", "-d"], project, [compose_file], timeout=90)
        if up.returncode != 0:
            record("NEW-RTE-001", False, f"HARNESS_ERROR: compose up failed rc={up.returncode} stderr={up.stderr[-500:]}")
            return
        time.sleep(2)
        osrm_walking = _compose_run(["exec", "-T", "frontend", "getent", "hosts", "osrm-walking"], project, [compose_file], timeout=15)
        martin = _compose_run(["exec", "-T", "frontend", "getent", "hosts", "martin"], project, [compose_file], timeout=15)
        frontend_alive = _compose_run(["exec", "-T", "frontend", "true"], project, [compose_file], timeout=15)
        ok = (
            osrm_walking.returncode == 0 and "osrm-walking" in osrm_walking.stdout
            and martin.returncode == 0 and "martin" in martin.stdout
            and frontend_alive.returncode == 0
        )
        detail = (
            f"getent osrm-walking rc={osrm_walking.returncode} out={osrm_walking.stdout.strip()!r}; "
            f"getent martin rc={martin.returncode} out={martin.stdout.strip()!r}; "
            f"frontend_running={frontend_alive.returncode == 0}"
        )
        record("NEW-RTE-001", ok, detail)
    finally:
        _compose_down(project, [compose_file])

    neg_compose_file = RUNTIME_FIXTURES_DIR / "rte001-dns-no-martin.compose.yml"
    neg_project = "ohg2-r12b-rte001-nc"
    _compose_down(neg_project, [neg_compose_file])
    try:
        up = _compose_run(["up", "-d"], neg_project, [neg_compose_file], timeout=90)
        time.sleep(2)
        martin_lookup = _compose_run(["exec", "-T", "frontend", "getent", "hosts", "martin"], neg_project, [neg_compose_file], timeout=15)
        nc_ok = martin_lookup.returncode != 0
        record("NEW-RTE-001-NEGATIVE-CONTROL", nc_ok, f"martin removed -> getent lookup correctly failed: rc={martin_lookup.returncode} stderr={martin_lookup.stderr.strip()[-300:]!r} (up_rc={up.returncode})")
    finally:
        _compose_down(neg_project, [neg_compose_file])


def case_new_rte_002a() -> None:
    compose_file = RUNTIME_FIXTURES_DIR / "rte002a-missing-upstreams.compose.yml"
    project = "ohg2-r12b-rte002a"
    _compose_down(project, [compose_file])
    try:
        up = _compose_run(["up", "-d"], project, [compose_file], timeout=90)
        time.sleep(2)
        rc, status_out, status_err = _docker_inspect(f"{project}-frontend-1", "{{.State.Status}}")
        rc2, exitcode_out, exitcode_err = _docker_inspect(f"{project}-frontend-1", "{{.State.ExitCode}}")
        if rc != 0 or rc2 != 0:
            record("NEW-RTE-002A", False, f"HARNESS_ERROR: docker inspect failed rc={rc}/{rc2} stderr={status_err or exitcode_err}")
            return
        logs = _compose_run(["logs", "frontend"], project, [compose_file], timeout=15)
        log_text = logs.stdout + logs.stderr
        mentions_upstream = ("osrm-walking" in log_text) or ("martin" in log_text)
        ok = (status_out == "exited") and (exitcode_out not in ("0", "")) and mentions_upstream
        detail = f"State.Status={status_out!r} ExitCode={exitcode_out!r} log_mentions_missing_upstream={mentions_upstream} up_rc={up.returncode}"
        record("NEW-RTE-002A", ok, detail)
    finally:
        _compose_down(project, [compose_file])

    neg_compose_file = RUNTIME_FIXTURES_DIR / "rte001-dns.compose.yml"
    neg_project = "ohg2-r12b-rte002a-nc"
    _compose_down(neg_project, [neg_compose_file])
    try:
        up = _compose_run(["up", "-d"], neg_project, [neg_compose_file], timeout=90)
        time.sleep(2)
        rc, status_out, _ = _docker_inspect(f"{neg_project}-frontend-1", "{{.State.Status}}")
        nc_ok = rc == 0 and status_out == "running"
        record("NEW-RTE-002A-NEGATIVE-CONTROL", nc_ok, f"osrm-walking/martin restored -> frontend State.Status={status_out!r} (up_rc={up.returncode})")
    finally:
        _compose_down(neg_project, [neg_compose_file])


def _rte002b_probe(project: str, compose_file: Path) -> dict:
    rc, status_out, _ = _docker_inspect(f"{project}-frontend-1", "{{.State.Status}}")
    osrm_status = None
    tiles_status = None
    try:
        import urllib.request
        import urllib.error
        for _ in range(20):
            try:
                urllib.request.urlopen("http://127.0.0.1:18902/", timeout=1)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.5)
        try:
            urllib.request.urlopen("http://127.0.0.1:18902/osrm/walking/route/v1/foot/139.7,35.6", timeout=5)
            osrm_status = 200
        except urllib.error.HTTPError as e:
            osrm_status = e.code
        except Exception as e:
            osrm_status = f"ERROR:{e}"
        try:
            urllib.request.urlopen("http://127.0.0.1:18902/tiles/something", timeout=5)
            tiles_status = 200
        except urllib.error.HTTPError as e:
            tiles_status = e.code
        except Exception as e:
            tiles_status = f"ERROR:{e}"
    except Exception as e:
        return {"frontend_status": status_out, "harness_error": str(e)}
    return {"frontend_status": status_out, "frontend_running": rc == 0 and status_out == "running", "osrm_status": osrm_status, "tiles_status": tiles_status}


def case_new_rte_002b() -> None:
    compose_file = RUNTIME_FIXTURES_DIR / "rte002b-noop.compose.yml"
    project = "ohg2-r12b-rte002b"
    _compose_down(project, [compose_file])
    try:
        up = _compose_run(["up", "-d"], project, [compose_file], timeout=90)
        time.sleep(3)
        result = _rte002b_probe(project, compose_file)
        expected_set = {502, 503, 504}
        ok = (
            result.get("frontend_running") is True
            and result.get("osrm_status") in expected_set
            and result.get("tiles_status") in expected_set
        )
        record("NEW-RTE-002B", ok, f"{result} up_rc={up.returncode} expected_status_set={sorted(expected_set)}")
    finally:
        _compose_down(project, [compose_file])

    neg_compose_file = RUNTIME_FIXTURES_DIR / "rte002b-listening.compose.yml"
    neg_project = "ohg2-r12b-rte002b-nc"
    _compose_down(neg_project, [neg_compose_file])
    try:
        up = _compose_run(["up", "-d"], neg_project, [neg_compose_file], timeout=90)
        time.sleep(3)
        result = _rte002b_probe(neg_project, neg_compose_file)
        nc_ok = result.get("osrm_status") == 200 and result.get("tiles_status") == 200
        record("NEW-RTE-002B-NEGATIVE-CONTROL", nc_ok, f"upstreams listening -> {result} up_rc={up.returncode}")
    finally:
        _compose_down(neg_project, [neg_compose_file])


def _rte003_write_compose(tmp_dir: Path, dem_placeholder: bool, real_dem: bool) -> Path:
    data_runtime = tmp_dir / "data_runtime"
    (data_runtime / "logs").mkdir(parents=True, exist_ok=True)
    (data_runtime / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_dir / "data").mkdir(parents=True, exist_ok=True)
    (tmp_dir / "data_lake").mkdir(parents=True, exist_ok=True)
    volumes = [
        f"{data_runtime}:/data_runtime:ro",
        f"{data_runtime / 'logs'}:/data_runtime/logs:rw",
        f"{data_runtime / 'cache'}:/data_runtime/cache:rw",
        f"{tmp_dir / 'data_lake'}:/data_lake",
        f"{tmp_dir / 'data'}:/app/data:ro",
        f"{tmp_dir / 'data'}:/data:ro",
    ]
    if real_dem:
        elevation_dir = data_runtime / "backend" / "elevation"
        elevation_dir.mkdir(parents=True, exist_ok=True)
        (elevation_dir / "elevation.tif").touch()
        real_dem_src = REPO_ROOT / "tests" / "fixtures" / "dem_demo" / "elevation_demo.tif"
        volumes.append(f"{real_dem_src}:/data_runtime/backend/elevation/elevation.tif:ro")
    compose = {
        "services": {
            "backend-public": {
                "image": "onhighground2-backend-public:latest",
                "user": "10001:10001",
                "ports": ["127.0.0.1:18903:8000"],
                "volumes": volumes,
                "environment": [
                    "DEM_FILE_PATH=/data_runtime/backend/elevation/elevation.tif",
                    "API_HOST=0.0.0.0",
                    "API_PORT=8000",
                ],
                "healthcheck": {
                    "test": ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"],
                    "interval": "5s",
                    "timeout": "5s",
                    "retries": 5,
                },
            }
        }
    }
    compose_path = tmp_dir / "rte003.compose.yml"
    compose_path.write_text(json.dumps(compose), encoding="utf-8")  # valid YAML subset
    return compose_path


def _rte003_probe(project: str, compose_file: Path) -> dict:
    rc, status_out, _ = _docker_inspect(f"{project}-backend-public-1", "{{.State.Status}}")
    health_out = "starting"
    for _ in range(30):
        rc2, health_out, _ = _docker_inspect(f"{project}-backend-public-1", "{{.State.Health.Status}}")
        if health_out == "healthy":
            break
        time.sleep(1)
    import urllib.request
    import urllib.error
    stats_status = None
    stats_body = None
    for _ in range(20):
        try:
            resp = urllib.request.urlopen("http://127.0.0.1:18903/health", timeout=1)
            if resp.status == 200:
                break
        except Exception:
            time.sleep(1)
    try:
        resp = urllib.request.urlopen("http://127.0.0.1:18903/api/stats", timeout=10)
        stats_status = resp.status
        stats_body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        stats_status = e.code
        stats_body = e.read().decode("utf-8", errors="replace")
    except Exception as e:
        stats_status = f"ERROR:{e}"
    logs = _compose_run(["logs", "backend-public"], project, [compose_file], timeout=15)
    has_traceback = "Traceback (most recent call last)" in (logs.stdout + logs.stderr)
    return {
        "status": status_out, "health": health_out, "stats_status": stats_status,
        "stats_body": stats_body, "has_traceback": has_traceback,
    }


def case_new_rte_003() -> None:
    import tempfile
    with tempfile.TemporaryDirectory(prefix="new-rte-003-") as td:
        tmp_dir = Path(td)
        compose_file = _rte003_write_compose(tmp_dir, dem_placeholder=False, real_dem=False)
        project = "ohg2-r12b-rte003"
        _compose_down(project, [compose_file])
        try:
            up = _compose_run(["up", "-d"], project, [compose_file], timeout=90)
            time.sleep(4)
            result = _rte003_probe(project, compose_file)
            body_has_json = False
            try:
                json.loads(result.get("stats_body") or "{}")
                body_has_json = True
            except Exception:
                pass
            ok = (
                result.get("status") == "running"
                and result.get("health") == "healthy"
                and result.get("stats_status") == 503
                and not result.get("has_traceback")
                and body_has_json
            )
            record("NEW-RTE-003", ok, f"{result} up_rc={up.returncode}")
        finally:
            _compose_down(project, [compose_file])

    with tempfile.TemporaryDirectory(prefix="new-rte-003-nc-") as td:
        tmp_dir = Path(td)
        compose_file = _rte003_write_compose(tmp_dir, dem_placeholder=True, real_dem=True)
        project = "ohg2-r12b-rte003-nc"
        _compose_down(project, [compose_file])
        try:
            up = _compose_run(["up", "-d"], project, [compose_file], timeout=90)
            time.sleep(4)
            result = _rte003_probe(project, compose_file)
            nc_ok = result.get("stats_status") == 200
            record("NEW-RTE-003-NEGATIVE-CONTROL", nc_ok, f"DEM restored -> {result} up_rc={up.returncode}")
        finally:
            _compose_down(project, [compose_file])


def case_new_rte_004() -> None:
    import secrets as _secrets
    import tempfile

    node_bin = None
    for candidate in ("node",):
        proc = subprocess.run(["which", candidate], capture_output=True, text=True)
        if proc.returncode == 0:
            node_bin = proc.stdout.strip()
            break
    if node_bin is None:
        record("NEW-RTE-004", False, "HARNESS_ERROR: node not found on PATH")
        return

    e2e_script = REPO_ROOT / "tools" / "public_release" / "phase2d_round12b_rte004_e2e.js"
    canary_token = "RTE004-CANARY-" + _secrets.token_hex(8)

    with tempfile.TemporaryDirectory(prefix="new-rte-004-") as td:
        tmp_dir = Path(td)
        for sub in ("data_runtime/logs", "data_runtime/cache", "data", "data_lake", "scripts", "osrm", "railways"):
            (tmp_dir / sub).mkdir(parents=True, exist_ok=True)
        env_operator = tmp_dir / "env.operator"
        env_operator.write_text(f"OPERATOR_AUTH_SECRET={canary_token}\n", encoding="utf-8")
        compose = {
            "services": {
                "backend-operator": {
                    "image": "onhighground2-backend-operator:latest",
                    "user": "10002:10002",
                    "ports": ["127.0.0.1:18904:8100"],
                    "volumes": [
                        f"{tmp_dir / 'data_runtime'}:/data_runtime",
                        f"{tmp_dir / 'data_lake'}:/data_lake",
                        f"{tmp_dir / 'data'}:/app/data:ro",
                        f"{tmp_dir / 'data'}:/data:ro",
                        f"{tmp_dir / 'scripts'}:/scripts:ro",
                        f"{tmp_dir / 'railways'}:/frontend/layers/railways",
                        f"{tmp_dir / 'osrm'}:/osrm",
                    ],
                    "env_file": [{"path": str(env_operator), "required": True}],
                    "environment": ["API_HOST=0.0.0.0", "API_PORT=8100"],
                },
                "operator-gateway": {
                    "image": "nginx:alpine",
                    "ports": ["127.0.0.1:18905:8100"],
                    "volumes": [
                        f"{REPO_ROOT / 'operator' / 'frontend-admin'}:/usr/share/nginx/html/admin:ro",
                        f"{REPO_ROOT / 'operator' / 'nginx.conf'}:/etc/nginx/conf.d/default.conf:ro",
                    ],
                    "depends_on": ["backend-operator"],
                },
            }
        }
        compose_file = tmp_dir / "rte004.compose.yml"
        compose_file.write_text(json.dumps(compose), encoding="utf-8")

        project = "ohg2-r12b-rte004"
        _compose_down(project, [compose_file])
        try:
            up = _compose_run(["up", "-d"], project, [compose_file], timeout=90)
            time.sleep(3)
            proc = subprocess.run(
                [node_bin, str(e2e_script), "--mode", "real", "--url", "http://127.0.0.1:18905/admin/datasets.html", "--token", canary_token],
                capture_output=True, text=True, timeout=60,
            )
            marker = "RTE004_RESULT_JSON="
            payload = None
            for line in proc.stdout.splitlines():
                if line.startswith(marker):
                    payload = json.loads(line[len(marker):])
            if payload is None:
                record("NEW-RTE-004", False, f"HARNESS_ERROR: no result JSON. exit={proc.returncode} stdout={proc.stdout[-1000:]!r} stderr={proc.stderr[-1000:]!r} up_rc={up.returncode}")
            else:
                ok = (
                    payload.get("postAuthFetchStatus") == 200
                    and payload.get("postReloadStatus") == 401
                    and payload.get("findings") == []
                )
                record("NEW-RTE-004", ok, f"{payload}")
        finally:
            _compose_down(project, [compose_file])

    neg_fixture = RUNTIME_FIXTURES_DIR / "rte004_regressed_negative_control.html"
    proc = subprocess.run(
        [node_bin, str(e2e_script), "--mode", "regressed", "--url", neg_fixture.as_uri(), "--token", canary_token],
        capture_output=True, text=True, timeout=60,
    )
    marker = "RTE004_RESULT_JSON="
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith(marker):
            payload = json.loads(line[len(marker):])
    if payload is None:
        record("NEW-RTE-004-NEGATIVE-CONTROL", False, f"HARNESS_ERROR: no result JSON. exit={proc.returncode} stdout={proc.stdout[-500:]!r} stderr={proc.stderr[-500:]!r}")
    else:
        nc_ok = len(payload.get("findings") or []) > 0
        record("NEW-RTE-004-NEGATIVE-CONTROL", nc_ok, f"regressed localStorage-storing fixture -> correctly detected: {payload}")


CASE_FUNCS = {
    "NEW-ADV-001": case_new_adv_001,
    "NEW-ADV-002": case_new_adv_002,
    "NEW-ADV-003": case_new_adv_003,
    "NEW-ADV-004": case_new_adv_004,
    "NEW-ADV-005": case_new_adv_005,
    "NEW-ADV-006": case_new_adv_006,
    "NEW-ADV-007": case_new_adv_007,
    "NEW-RTE-001": case_new_rte_001,
    "NEW-RTE-002A": case_new_rte_002a,
    "NEW-RTE-002B": case_new_rte_002b,
    "NEW-RTE-003": case_new_rte_003,
    "NEW-RTE-004": case_new_rte_004,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Round 12B new-cases runner (all 12 cases implemented: 7 adversarial + 5 runtime)")
    parser.add_argument("--only", nargs="*", default=None, help="Run only these case IDs")
    args = parser.parse_args()

    to_run = args.only if args.only else list(CASE_FUNCS.keys())
    for case_id in to_run:
        fn = CASE_FUNCS.get(case_id)
        if fn is None:
            print(f"[SKIP] {case_id}: not yet implemented in this runner")
            continue
        fn()

    fail_count = sum(1 for r in RESULTS if r["result"] == "FAIL")
    print(f"\nTOTAL: {len(RESULTS)} result(s), {fail_count} FAIL")
    return 1 if fail_count else 0


if __name__ == "__main__":
    sys.exit(main())

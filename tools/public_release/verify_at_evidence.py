#!/usr/bin/env python3
"""Phase 2-B.6 AT-18~AT-20 assertion evidence manifest verifier.

Validates a manifest-set against an active (registry, activation-record)
pair using a fail-closed 4-tuple binding contract (registry_name,
registry_version, schema_version, registry_sha256). See
tasks/public-release/phase2b6_claude_implementation_instruction.md section 5
and tasks/public-release/github_public_audit_phase2a_remediation_plan.md
section 5.11 for the normative contract this implements.

Exit codes:
  0 - PASS or PASS_COMPATIBLE_REUSE
  2 - a single primary E_* failure code (fail-closed)
  3 - CLI/runtime internal error (never substitutes for an expected FAIL)

Security invariant (P2B6-CX-002 round 8): this tool never executes any
file or command path referenced by the manifest-set it is validating. All
checks against evidence-referenced paths (artifact files, argv entries,
the interpreter identity in argv[0]) are read-only stat/hash/string
comparisons against values this process derives from its own trusted
state — never a subprocess spawn of anything the untrusted input names.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION_SUPPORTED = {"1.0"}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _is_valid_timestamp(value: Any) -> bool:
    """Same semantic-parse approach as
    tools/public_release/phase2b6_rollback_validate.py::_is_valid_timestamp
    — shape-only regex checks accept calendar-invalid values."""
    if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True

# P2B6-CX-001 round 3: this project's fixed baseline commit
# (tasks/public-release/phase2b6_claude_implementation_instruction.md
# section 1). compatibility_record baseline_commit/target_commit must
# match this exactly — arbitrary strings previously validated.
BASELINE_COMMIT = "d3eeb99fd5f214487939d7a0df599e1d56835128"

# P2B6-CX-002 round 4: round 3's COMMAND_RE only checked that the command
# referenced *some* existing .py file as a prefix, so substituting a
# different real script, a different --assertion-id, or appending
# "; false" all still matched. Every Phase 2-B.6 scoped child is produced
# by exactly one script (tools/public_release/phase2b6_scoped_assertions.py
# --assertion-id <ID>, see that file's run_single_assertion()/
# run_all_scoped_assertions_as_subprocesses()); the command field must
# equal that exact canonical string for the child's own assertion_id, and
# nothing else — not a prefix match, not a different script, not extra
# shell tokens.
SCOPED_RUNNER_SCRIPT = "tools/public_release/phase2b6_scoped_assertions.py"


def _canonical_scoped_command(assertion_id: str) -> str:
    return f"python3 {SCOPED_RUNNER_SCRIPT} --assertion-id {assertion_id}"


# Phase 2-D Round 12D-C2 (OWNER decision: portable token contract, option 2).
#
# P2B6-CX-002 rounds 5-8 progressively tightened the argv check to an exact,
# non-executing match of argv[0] against this process's own resolved
# `sys.executable` and argv[1] against the resolved absolute path of the
# repo's scoped runner script. That was correct as security but NOT
# portable: the generator (phase2b6_scoped_assertions.py) baked the authoring
# machine's absolute interpreter + REPO_ROOT paths into the hash-pinned input
# artifact, so any clean clone at a different path / with a different
# interpreter failed both comparisons -> E_CHILD_COMMAND_UNRESOLVABLE
# (P2D-VBF-CHILD-PORTABILITY-001, Round 12D-C1 forensic).
#
# Under the portable token contract the input artifact records a FIXED literal
# token vector. This verifier matches each of the 4 slots by exact equality
# against its contracted literal and only then builds the trusted
# interpreter/script identity from its OWN process state (sys.executable,
# REPO_ROOT). It never: executes recorded argv, uses shell=True, calls
# os.system / eval / exec / os.path.expandvars / str.format_map, expands the
# token by str.replace or any arbitrary token expansion, derives REPO_ROOT
# from the environment / the fixture / cwd, accepts a prefix/substring/suffix
# match, keeps a legacy absolute-root allowlist, hardcodes an authoring
# path, falls back to the pre-C2 absolute argv form, or converts
# E_CHILD_COMMAND_UNRESOLVABLE into a PASS.
CANONICAL_ARGV_PYTHON_TOKEN = "<PYTHON>"
CANONICAL_ARGV_SCRIPT_TOKEN = "<REPO_ROOT>/tools/public_release/phase2b6_scoped_assertions.py"

# Frozen identity of tools/public_release/phase2b6_scoped_assertions.py under
# the Round 12D-C2 portable token contract. Cross-checked against the
# OWNER-approved candidate_untracked_policy.json entry in the Round 12D-C2
# approval package (implementation_freeze_inventory.json / focused_result.json);
# backend/tests/test_phase2b6_version_binding.py asserts the on-disk script
# still matches these exactly, so a drift here is caught at test time rather
# than silently accepted.
EXPECTED_SCOPED_RUNNER_SHA256 = "dce08eb5b4d00c041dfad8829da2a0d7bad7121785783e3238075981ffddafca"
EXPECTED_SCOPED_RUNNER_MODE = "100644"


def _trusted_python_executable() -> str:
    """The interpreter identity this verifier process itself is running
    under, resolved once from trusted process state (sys.executable) that
    the untrusted manifest-set being validated cannot influence."""
    return str(Path(sys.executable).resolve())


def _expected_scoped_script_path() -> str:
    return str((REPO_ROOT / SCOPED_RUNNER_SCRIPT).resolve())


def _build_trusted_child_command_binding() -> dict[str, str]:
    """Called ONLY after every fixed portable-token slot has matched exactly.
    Builds the trusted interpreter + scoped-runner-script identity from this
    verifier process's own state. Read-only stat/hash/readlink checks —
    never executes anything. Raises E_CHILD_COMMAND_UNRESOLVABLE if the
    scoped runner script on disk is not a regular file inside REPO_ROOT,
    reaches outside REPO_ROOT via a symlink on any path component, or does
    not match its frozen SHA-256 / mode."""
    repo_root_resolved = REPO_ROOT.resolve()
    script_decl = REPO_ROOT / SCOPED_RUNNER_SCRIPT

    # No path component from REPO_ROOT down to the script may be a symlink
    # whose target escapes REPO_ROOT.
    probe = script_decl
    seen: set[str] = set()
    while True:
        key = str(probe)
        if key in seen:
            raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
        seen.add(key)
        if probe.is_symlink():
            link = Path(os.readlink(probe))
            resolved_link = link.resolve() if link.is_absolute() else (probe.parent / link).resolve()
            try:
                resolved_link.relative_to(repo_root_resolved)
            except ValueError:
                raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
        if probe == repo_root_resolved or probe.parent == probe:
            break
        probe = probe.parent

    try:
        script_resolved = script_decl.resolve()
    except OSError:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    if not script_resolved.is_file():
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    if script_resolved != repo_root_resolved and repo_root_resolved not in script_resolved.parents:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")

    st = script_resolved.stat()
    if "100%o" % (st.st_mode & 0o777) != EXPECTED_SCOPED_RUNNER_MODE:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    if sha256_file(script_resolved) != EXPECTED_SCOPED_RUNNER_SHA256:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")

    return {
        "trusted_python": _trusted_python_executable(),
        "trusted_script": str(script_resolved),
    }


def _is_strict_int(value: Any) -> bool:
    """bool is a subclass of int in Python (isinstance(True, int) is True,
    False == 0) — P2B6-CX-002 round 6: child.exit_code=false previously
    passed `child.get("exit_code") != 0` undetected. type(x) is int
    excludes bool explicitly."""
    return type(value) is int

# Known historical registries, fixed per
# github_public_audit_phase2a_remediation_plan.md section 5.11.5 / 5.11.11.
# These constants are the canonical <V1_HASH> values used by the fixture
# matrix; they are not derived from the registry file itself so that adding
# them cannot change the registry's own canonical hash. Full 4-tuples (not
# just version->hash) are kept so compatibility_record source bindings can
# be checked for an EXACT match against a genuine historical registry
# identity, not merely "some known hash string appears somewhere"
# (P2B6-CX-001 round 2: a compat record with a doctored source name/version/
# schema alongside the correct hash previously still validated).
KNOWN_REGISTRIES = {
    "p2a-at18-20-v1": {
        "registry_name": "p2a-at18-20-assertion-registry",
        "registry_version": "p2a-at18-20-v1",
        "schema_version": "1.0",
        "registry_sha256": "b66eda7e6b9e851a72623db195807dea2a37fe3d9d6c96b38f7b7cc1bf21b71c",
    },
}
KNOWN_HISTORICAL_VERSIONS = {k: v["registry_sha256"] for k, v in KNOWN_REGISTRIES.items()}

# P2B6-CX-002 round 2: the exact set of artifact roles every child must
# carry, matching the evidence manifest contract in
# tasks/public-release/phase2b6_claude_implementation_instruction.md
# section 5 ("stdout／stderr artifact参照とSHA-256、input artifact SHA-256").
# A missing role or an arbitrary/unknown role value are both rejected;
# "some artifacts with hashes" is not sufficient — the set must be exact.
REQUIRED_ARTIFACT_ROLES = frozenset({"input", "stdout", "stderr", "result"})

REQUIRED_COMPAT_FIELDS = [
    "compatibility_record_id",
    "source_registry_name",
    "source_registry_version",
    "source_schema_version",
    "source_registry_sha256",
    "target_registry_name",
    "target_registry_version",
    "target_schema_version",
    "target_registry_sha256",
    "source_assertion_id",
    "target_assertion_id",
    "evidence_artifact_id",
    "evidence_artifact_path",
    "artifact_sha256",
    "baseline_commit",
    "target_commit",
    "reuse_scope",
    "reason",
    "executor",
    "reviewer",
    "review_timestamp",
    "verdict",
]


class VerifyError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _no_dup_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise VerifyError("E_JSON_DUPLICATE_KEY")
        seen[key] = value
    return seen


def load_json_strict(path: Path, unavailable_code: str) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise VerifyError(unavailable_code) from exc
    try:
        return json.loads(raw, object_pairs_hook=_no_dup_keys)
    except VerifyError:
        raise
    except json.JSONDecodeError as exc:
        raise VerifyError(unavailable_code) from exc


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_registry_bytes(registry_obj: dict[str, Any]) -> bytes:
    body = {k: v for k, v in registry_obj.items() if k != "registry_sha256"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def _field_state(obj: dict[str, Any], key: str) -> str:
    """Returns 'missing', 'null', 'empty', or 'present'."""
    if key not in obj:
        return "missing"
    value = obj[key]
    if value is None:
        return "null"
    if isinstance(value, str) and value == "":
        return "empty"
    return "present"


def validate_registry_self_consistency(registry_obj: dict[str, Any]) -> None:
    declared = registry_obj.get("registry_sha256")
    if not isinstance(declared, str) or not HASH_RE.match(declared):
        raise VerifyError("E_REGISTRY_UNAVAILABLE")
    computed = sha256_bytes(canonical_registry_bytes(registry_obj))
    if computed != declared:
        raise VerifyError("E_REGISTRY_SAME_VERSION_MUTATION")


def validate_activation_record(activation_obj: dict[str, Any], registry_obj: dict[str, Any]) -> None:
    verdict = activation_obj.get("review_verdict", "")
    new_state = activation_obj.get("new_state", "")
    if new_state != "APPROVED_ACTIVE" or not isinstance(verdict, str) or not verdict.startswith("PASS"):
        raise VerifyError("E_REGISTRY_NOT_APPROVED")
    for field in ("registry_name", "registry_version", "schema_version", "registry_sha256"):
        if activation_obj.get(field) != registry_obj.get(field):
            raise VerifyError("E_REGISTRY_NOT_APPROVED")


def _check_missing_null_empty(entry: dict[str, Any]) -> None:
    order = [
        ("registry_name", "NAME"),
        ("registry_version", "VERSION"),
        ("schema_version", "SCHEMA"),
        ("registry_sha256", "HASH"),
    ]
    for field, code_word in order:
        state = _field_state(entry, field)
        if state == "missing":
            raise VerifyError(f"E_BIND_{code_word}_MISSING")
        if state == "null":
            raise VerifyError(f"E_BIND_{code_word}_NULL")
        if state == "empty":
            raise VerifyError(f"E_BIND_{code_word}_EMPTY")


def validate_top_level_binding(manifest: dict[str, Any], active: dict[str, str]) -> None:
    _check_missing_null_empty(manifest)

    if manifest["registry_name"] != active["registry_name"]:
        raise VerifyError("E_BIND_NAME_UNKNOWN")

    version = manifest["registry_version"]
    if version != active["registry_version"]:
        raise VerifyError("E_BIND_VERSION_UNKNOWN")

    if manifest["schema_version"] not in SCHEMA_VERSION_SUPPORTED:
        raise VerifyError("E_BIND_SCHEMA_UNSUPPORTED")

    digest = manifest["registry_sha256"]
    if not isinstance(digest, str) or not HASH_RE.match(digest):
        raise VerifyError("E_BIND_HASH_MALFORMED")

    if digest != active["registry_sha256"]:
        if digest in KNOWN_HISTORICAL_VERSIONS.values():
            raise VerifyError("E_BIND_VERSION_HASH_MISMATCH")
        raise VerifyError("E_BIND_HASH_MISMATCH")


def _validate_child_binding(child: dict[str, Any], active: dict[str, str]) -> None:
    """P2B6-CX-001 correction: children previously only had registry_version
    and registry_sha256 checked. Every child now goes through the same
    missing/null/empty -> unknown/unsupported/malformed -> mismatch pipeline
    as the top-level manifest binding, so a child missing registry_name or
    schema_version (or any field) is rejected with the matching E_BIND_*
    code instead of silently passing or falling through to the wrong
    mixed-version branch."""
    _check_missing_null_empty(child)

    if child["registry_name"] != active["registry_name"]:
        raise VerifyError("E_BIND_NAME_UNKNOWN")
    if child["schema_version"] not in SCHEMA_VERSION_SUPPORTED:
        raise VerifyError("E_BIND_SCHEMA_UNSUPPORTED")

    digest = child["registry_sha256"]
    if not isinstance(digest, str) or not HASH_RE.match(digest):
        raise VerifyError("E_BIND_HASH_MALFORMED")

    version = child["registry_version"]
    if version == active["registry_version"]:
        if digest != active["registry_sha256"]:
            if digest in KNOWN_HISTORICAL_VERSIONS.values():
                raise VerifyError("E_BIND_VERSION_HASH_MISMATCH")
            raise VerifyError("E_BIND_HASH_MISMATCH")
        return

    if version not in KNOWN_HISTORICAL_VERSIONS:
        raise VerifyError("E_BIND_VERSION_UNKNOWN")
    if digest != KNOWN_HISTORICAL_VERSIONS[version]:
        raise VerifyError("E_BIND_HASH_MISMATCH")


def _validate_child_execution(child: dict[str, Any]) -> None:
    """P2B6-CX-002 correction: a child's own exit_code/verdict were never
    inspected, so a failed or unexecuted assertion could be included in a
    manifest-set and still contribute to an overall PASS.

    P2B6-CX-002 round 6: `child.get("exit_code") != 0` accepted JSON
    boolean `false` because `False == 0` in Python. exit_code must now be
    a strict int (bool excluded) equal to 0."""
    exit_code = child.get("exit_code")
    if not _is_strict_int(exit_code) or exit_code != 0:
        raise VerifyError("E_CHILD_EXECUTION_FAILED")
    if child.get("verdict") != "PASS":
        raise VerifyError("E_CHILD_EXECUTION_FAILED")


RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _validate_child_run_id_present(child: dict[str, Any]) -> None:
    """P2B6-CX-002 round 6: introduces a per-subprocess-run identity that
    input/result/stdout artifacts and the child record must all agree on,
    so tampering with any one artifact's self-reported exit_code/registry
    fields in isolation (while the others stay internally consistent with
    each other but not with the actual run) is detectable. See
    _validate_child_argv_binding() and _validate_child_result_binding()
    for the cross-checks against this value, and validate_children() for
    the cross-child uniqueness check.

    P2B6-CX-002 round 7: round 6 only required run_id to be a non-empty
    string, so a single blank space passed. The evidence-generation
    contract (phase2b6_scoped_assertions.py::run_single_assertion) always
    produces `uuid.uuid4().hex` — a 32-char lowercase hex string — so that
    is now the required canonical shape."""
    run_id = child.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise VerifyError("E_CHILD_RUN_ID_MISSING")
    if not RUN_ID_RE.match(run_id):
        raise VerifyError("E_CHILD_RUN_ID_MALFORMED")


def _find_artifact(child: dict[str, Any], role: str) -> dict[str, Any]:
    """Callers must only use this after _validate_child_artifacts() has
    already confirmed the exact required role set is present — by that
    point every role is guaranteed to resolve to exactly one artifact
    entry."""
    for artifact in child.get("artifacts", []):
        if isinstance(artifact, dict) and artifact.get("role") == role:
            return artifact
    raise VerifyError("E_ARTIFACT_ROLE_MISSING")


def _validate_child_command_string(child: dict[str, Any]) -> None:
    """`command` must equal the exact canonical invocation for this
    child's own assertion_id — substituting a different (but real) script,
    a different --assertion-id, or appending trailing shell tokens (e.g.
    "; false") are all rejected, not just commands referencing nothing
    real at all."""
    assertion_id = child.get("assertion_id")
    command = child.get("command")
    expected_command = _canonical_scoped_command(assertion_id)
    if command != expected_command:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    script_path = (REPO_ROOT / SCOPED_RUNNER_SCRIPT).resolve()
    if not str(script_path).startswith(str(REPO_ROOT)) or not script_path.is_file():
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")


def _validate_child_argv_binding(child: dict[str, Any], base_dir: Path) -> None:
    """Portable token contract (Phase 2-D Round 12D-C2). The "input" artifact
    records exactly {"argv": [...], "run_id": "..."}; argv must be a list of
    exactly 4 strings equal, slot by slot, to:

        [ "<PYTHON>",
          "<REPO_ROOT>/tools/public_release/phase2b6_scoped_assertions.py",
          "--assertion-id",
          <this child's assertion_id> ]

    Every slot is compared by exact string equality against its contracted
    literal — no substitution, no expansion, no prefix/substring/suffix
    acceptance, no legacy absolute-path form. Only after all four slots match
    is the trusted interpreter/script identity built from this verifier
    process's own state (see _build_trusted_child_command_binding), which also
    verifies the on-disk scoped runner script's frozen SHA-256 / mode and
    that no path component is an external symlink. The recorded argv is never
    executed.

    This is only called after _validate_child_artifacts() has already
    confirmed the "input" artifact's bytes match its declared hash."""
    assertion_id = child.get("assertion_id")
    input_artifact = _find_artifact(child, "input")
    input_path = (base_dir / str(input_artifact.get("path", ""))).resolve()
    try:
        input_obj = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    # The generation contract (phase2b6_scoped_assertions.py::
    # build_scoped_manifest_set) writes exactly {"argv": [...], "run_id": "..."}
    # and nothing else.
    if not isinstance(input_obj, dict) or set(input_obj.keys()) != {"argv", "run_id"}:
        raise VerifyError("E_INPUT_ARTIFACT_SCHEMA_INVALID")
    argv = input_obj.get("argv")
    if not isinstance(argv, list) or len(argv) != 4:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    if not all(isinstance(element, str) for element in argv):
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    token_python, token_script, flag, aid_arg = argv
    if token_python != CANONICAL_ARGV_PYTHON_TOKEN:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    if token_script != CANONICAL_ARGV_SCRIPT_TOKEN:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")
    if flag != "--assertion-id" or aid_arg != assertion_id:
        raise VerifyError("E_CHILD_COMMAND_UNRESOLVABLE")

    # All four fixed slots matched exactly -> derive the trusted binding from
    # our own process state only (never from the fixture, env, or cwd). The
    # returned dict is not needed by callers today; the call performs the
    # frozen-identity and no-external-symlink checks.
    _build_trusted_child_command_binding()

    if input_obj.get("run_id") != child.get("run_id"):
        raise VerifyError("E_CHILD_RUN_ID_MISMATCH")


def _extract_result_json_from_stdout(stdout_text: str) -> Any:
    marker = "SCOPED_ASSERTION_RESULT_JSON="
    for line in stdout_text.splitlines():
        if line.startswith(marker):
            try:
                return json.loads(line[len(marker):])
            except json.JSONDecodeError:
                return None
    return None


def _validate_child_result_binding(child: dict[str, Any], base_dir: Path) -> None:
    """P2B6-CX-002 round 5: the "result" artifact's own JSON content was
    never parsed or cross-checked against the child record — only its
    bytes hash was verified. A manifest whose result artifact bytes were
    rewritten to verdict=FAIL (with the hash recomputed to match) or whose
    child.executor was changed without updating the result artifact both
    still validated. The result artifact's assertion_id/verdict/executor
    must now match the child record exactly, and the "stdout" artifact
    must itself carry a SCOPED_ASSERTION_RESULT_JSON= line (written by
    phase2b6_scoped_assertions.py::run_single_assertion, captured verbatim
    as real subprocess stdout) agreeing with the result artifact — binding
    the declared result to what the same run's stdout actually reported."""
    result_artifact = _find_artifact(child, "result")
    result_path = (base_dir / str(result_artifact.get("path", ""))).resolve()
    try:
        result_obj = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise VerifyError("E_RESULT_ARTIFACT_MALFORMED")
    if not isinstance(result_obj, dict):
        raise VerifyError("E_RESULT_ARTIFACT_MALFORMED")
    if result_obj.get("assertion_id") != child.get("assertion_id"):
        raise VerifyError("E_RESULT_ARTIFACT_ASSERTION_ID_MISMATCH")
    if result_obj.get("verdict") != child.get("verdict"):
        raise VerifyError("E_RESULT_ARTIFACT_VERDICT_MISMATCH")
    if result_obj.get("executor") != child.get("executor"):
        raise VerifyError("E_RESULT_ARTIFACT_EXECUTOR_MISMATCH")

    # P2B6-CX-002 round 6: result_obj's own exit_code/registry 4-tuple were
    # never compared to anything — a result artifact reporting exit_code=1
    # or a different registry_version than the child record still
    # validated as long as assertion_id/verdict/executor matched. Both are
    # now bound to the child record's own (already-validated) fields, and
    # the result artifact's run_id must match the child's declared run_id
    # (see _validate_child_run_id_present() / _validate_child_argv_binding()).
    if result_obj.get("run_id") != child.get("run_id"):
        raise VerifyError("E_CHILD_RUN_ID_MISMATCH")
    result_exit_code = result_obj.get("exit_code")
    if not _is_strict_int(result_exit_code) or result_exit_code != child.get("exit_code"):
        raise VerifyError("E_RESULT_ARTIFACT_EXIT_CODE_MISMATCH")
    for field in ("registry_name", "registry_version", "schema_version", "registry_sha256"):
        if result_obj.get(field) != child.get(field):
            raise VerifyError("E_RESULT_ARTIFACT_REGISTRY_MISMATCH")

    stdout_artifact = _find_artifact(child, "stdout")
    stdout_path = (base_dir / str(stdout_artifact.get("path", ""))).resolve()
    try:
        stdout_text = stdout_path.read_text(encoding="utf-8")
    except OSError:
        raise VerifyError("E_STDOUT_RESULT_BINDING_MISSING")
    stdout_result = _extract_result_json_from_stdout(stdout_text)
    if not isinstance(stdout_result, dict):
        raise VerifyError("E_STDOUT_RESULT_BINDING_MISSING")
    for key in (
        "assertion_id", "verdict", "executor", "run_id", "exit_code",
        "registry_name", "registry_version", "schema_version", "registry_sha256",
    ):
        if stdout_result.get(key) != result_obj.get(key):
            raise VerifyError("E_STDOUT_RESULT_BINDING_MISMATCH")


def _validate_child_artifacts(child: dict[str, Any], base_dir: Path) -> None:
    """P2B6-CX-002 correction: artifact_sha256 was previously computed over
    a re-serialization of the evidence dict, never bound to real bytes on
    disk, so tampering with the recorded hash (or the artifact) went
    undetected. Every declared artifact must resolve to an existing file
    under base_dir and its SHA-256 must match the declared value exactly.
    Round 2 (P2B6-CX-002): the set of artifact roles must be exactly
    REQUIRED_ARTIFACT_ROLES — a missing role, a duplicate role, or an
    unrecognized role are all rejected (previously any non-empty list with
    a resolvable path/hash was accepted regardless of role)."""
    artifacts = child.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise VerifyError("E_ARTIFACT_MISSING")

    seen_roles: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise VerifyError("E_ARTIFACT_MISSING")
        role = artifact.get("role")
        if not role or not isinstance(role, str):
            raise VerifyError("E_ARTIFACT_ROLE_MISSING")
        if role not in REQUIRED_ARTIFACT_ROLES:
            raise VerifyError("E_ARTIFACT_ROLE_UNKNOWN")
        if role in seen_roles:
            raise VerifyError("E_ARTIFACT_ROLE_UNKNOWN")
        seen_roles.add(role)

        rel_path = artifact.get("path")
        declared_sha256 = artifact.get("sha256")
        if not rel_path or not declared_sha256:
            raise VerifyError("E_ARTIFACT_MISSING")
        if not isinstance(rel_path, str) or rel_path.startswith("/") or ".." in rel_path.split("/"):
            raise VerifyError("E_ARTIFACT_PATH_ESCAPE")
        artifact_path = (base_dir / rel_path).resolve()
        if not str(artifact_path).startswith(str(base_dir.resolve())):
            raise VerifyError("E_ARTIFACT_PATH_ESCAPE")
        if not artifact_path.is_file():
            raise VerifyError("E_ARTIFACT_MISSING")
        actual_sha256 = sha256_file(artifact_path)
        if actual_sha256 != declared_sha256:
            raise VerifyError("E_ARTIFACT_HASH_MISMATCH")

    if seen_roles != REQUIRED_ARTIFACT_ROLES:
        raise VerifyError("E_ARTIFACT_ROLE_MISSING")


def _validate_compat_record(record: dict[str, Any], child: dict[str, Any], active: dict[str, str], base_dir: Path) -> None:
    for field in REQUIRED_COMPAT_FIELDS:
        state = _field_state(record, field)
        if state != "present":
            raise VerifyError("E_COMPAT_RECORD_INCOMPLETE")
    if record["reviewer"] == record["executor"]:
        raise VerifyError("E_COMPAT_SELF_REVIEW")
    if record["source_assertion_id"] != child["assertion_id"] or record["target_assertion_id"] != child["assertion_id"]:
        raise VerifyError("E_COMPAT_RECORD_INCOMPLETE")
    if record["verdict"] != "APPROVED":
        raise VerifyError("E_COMPAT_RECORD_INCOMPLETE")

    # P2B6-CX-001 round 2: previously only "are these 4 fields present"
    # was checked. A record whose declared source tuple did not match any
    # genuine known historical registry (unknown name, unknown version, or
    # a hash of all zeros) still validated as long as the 4 fields existed.
    # The source tuple must now match a real KNOWN_REGISTRIES entry exactly,
    # and the target tuple must match the active registry exactly.
    source_tuple = {
        "registry_name": record["source_registry_name"],
        "registry_version": record["source_registry_version"],
        "schema_version": record["source_schema_version"],
        "registry_sha256": record["source_registry_sha256"],
    }
    known_source = KNOWN_REGISTRIES.get(record["source_registry_version"])
    if known_source is None or source_tuple != known_source:
        raise VerifyError("E_COMPAT_SOURCE_REGISTRY_UNKNOWN")

    target_tuple = {
        "registry_name": record["target_registry_name"],
        "registry_version": record["target_registry_version"],
        "schema_version": record["target_schema_version"],
        "registry_sha256": record["target_registry_sha256"],
    }
    if target_tuple != active:
        raise VerifyError("E_COMPAT_TARGET_REGISTRY_MISMATCH")

    # P2B6-CX-001 round 3: baseline_commit/target_commit/reuse_scope and the
    # evidence artifact were declared but never checked against anything —
    # a doctored commit string or an artifact hash matching nothing on disk
    # still validated. baseline/target commit must match this project's
    # fixed baseline; reuse_scope must name the reused child's own
    # assertion; the evidence artifact must resolve to real bytes.
    if record["baseline_commit"] != BASELINE_COMMIT or record["target_commit"] != BASELINE_COMMIT:
        raise VerifyError("E_COMPAT_COMMIT_MISMATCH")
    if record["reuse_scope"] != child["assertion_id"]:
        raise VerifyError("E_COMPAT_SCOPE_MISMATCH")

    evidence_path = record.get("evidence_artifact_path")
    declared_sha256 = record.get("artifact_sha256")
    if not evidence_path or not isinstance(evidence_path, str):
        raise VerifyError("E_COMPAT_ARTIFACT_MISSING")
    if evidence_path.startswith("/") or ".." in evidence_path.split("/"):
        raise VerifyError("E_ARTIFACT_PATH_ESCAPE")
    resolved = (base_dir / evidence_path).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise VerifyError("E_ARTIFACT_PATH_ESCAPE")
    if not resolved.is_file():
        raise VerifyError("E_COMPAT_ARTIFACT_MISSING")
    if sha256_file(resolved) != declared_sha256:
        raise VerifyError("E_COMPAT_ARTIFACT_HASH_MISMATCH")

    # P2B6-CX-001 round 4: evidence_artifact_id/executor/review_timestamp
    # were declared-but-unchecked fields — an arbitrary artifact id, an
    # executor that did not match the reused child's own executor, or a
    # non-timestamp review_timestamp string all still validated.
    expected_artifact_id = f"{child['assertion_id']}-evidence-from-{record['source_registry_version']}"
    if record["evidence_artifact_id"] != expected_artifact_id:
        raise VerifyError("E_COMPAT_ARTIFACT_ID_MISMATCH")
    if record["executor"] != child["executor"]:
        raise VerifyError("E_COMPAT_EXECUTOR_MISMATCH")
    if not _is_valid_timestamp(record["review_timestamp"]):
        raise VerifyError("E_COMPAT_REVIEW_TIMESTAMP_INVALID")


def validate_children(
    manifest_set: dict[str, Any],
    active: dict[str, str],
    base_dir: Path,
    known_assertion_ids: set[str],
    required_denominator: set[str],
) -> str:
    """Returns overall primary PASS code: 'PASS' or 'PASS_COMPATIBLE_REUSE'."""
    children = manifest_set.get("children")
    if not isinstance(children, list) or not children:
        raise VerifyError("E_CHILDREN_EMPTY")

    compat_records = {
        rec.get("compatibility_record_id"): rec
        for rec in manifest_set.get("compatibility_records", [])
        if isinstance(rec, dict)
    }

    used_reuse = False
    seen_assertion_ids: set[str] = set()
    seen_run_ids: set[str] = set()
    for child in children:
        if not isinstance(child, dict):
            raise VerifyError("E_BIND_NAME_MISSING")

        # P2B6-CX-001 round 2: an assertion_id outside the active registry's
        # known set (e.g. a fabricated "AT99-A99") or a duplicate within the
        # same manifest-set previously validated as long as its own 4-tuple
        # binding fields were well-formed. Both are now rejected.
        assertion_id = child.get("assertion_id")
        if not assertion_id or not isinstance(assertion_id, str):
            raise VerifyError("E_BIND_ASSERTION_ID_UNKNOWN")
        if assertion_id not in known_assertion_ids:
            raise VerifyError("E_BIND_ASSERTION_ID_UNKNOWN")
        if assertion_id in seen_assertion_ids:
            raise VerifyError("E_BIND_ASSERTION_ID_DUPLICATE")
        seen_assertion_ids.add(assertion_id)

        _validate_child_binding(child, active)

        # P2B6-CX-002 round 5: artifact structure/bytes must be validated
        # before any semantic parsing of command/argv/result content that
        # reads those same artifact files — otherwise a corrupted, missing,
        # or mis-rolled artifact surfaces as a command-resolution failure
        # instead of the more specific E_ARTIFACT_* code the fixture
        # contract expects, inverting the intended primary-error priority.
        _validate_child_artifacts(child, base_dir)
        _validate_child_run_id_present(child)

        # P2B6-CX-002 round 7: run_id existing/well-formed on each child in
        # isolation was not enough — nothing stopped two children (with
        # their own input/result/stdout all internally rewritten to match)
        # from sharing the same run_id, defeating its purpose as a
        # per-subprocess-run identity.
        run_id = child["run_id"]
        if run_id in seen_run_ids:
            raise VerifyError("E_CHILD_RUN_ID_DUPLICATE")
        seen_run_ids.add(run_id)

        _validate_child_command_string(child)
        _validate_child_argv_binding(child, base_dir)
        _validate_child_result_binding(child, base_dir)

        if child["registry_version"] != active["registry_version"]:
            record_id = child.get("compatibility_record_id")
            if not record_id:
                raise VerifyError("E_BIND_MIXED_VERSION")
            record = compat_records.get(record_id)
            if record is None:
                raise VerifyError("E_COMPAT_RECORD_MISSING")
            _validate_compat_record(record, child, active, base_dir)
            used_reuse = True

        _validate_child_execution(child)

    # P2B6-CX-001 round 3: the set of children was never checked against
    # the complete required denominator, so shrinking to e.g. 1 or 11 of
    # the 12 Phase 2-B.6 scoped assertions still validated as PASS.
    if seen_assertion_ids != required_denominator:
        raise VerifyError("E_CHILDREN_DENOMINATOR_MISMATCH")

    return "PASS_COMPATIBLE_REUSE" if used_reuse else "PASS"


def run(registry_path: Path, activation_path: Path, manifest_set_path: Path) -> dict[str, Any]:
    registry_obj = load_json_strict(registry_path, "E_REGISTRY_UNAVAILABLE")
    validate_registry_self_consistency(registry_obj)

    activation_obj = load_json_strict(activation_path, "E_REGISTRY_UNAVAILABLE")
    validate_activation_record(activation_obj, registry_obj)

    active = {
        "registry_name": registry_obj["registry_name"],
        "registry_version": registry_obj["registry_version"],
        "schema_version": registry_obj["schema_version"],
        "registry_sha256": registry_obj["registry_sha256"],
    }

    manifest_set_obj = load_json_strict(manifest_set_path, "E_REGISTRY_UNAVAILABLE")
    manifest = manifest_set_obj.get("manifest")
    if not isinstance(manifest, dict):
        raise VerifyError("E_BIND_NAME_MISSING")

    known_assertion_ids = {
        a["assertion_id"] for a in registry_obj.get("assertions", []) if isinstance(a, dict) and "assertion_id" in a
    }
    # P2B6-CX-001 round 3: the only manifest-set shape this tool currently
    # validates is a Phase 2-B.6 scoped aggregation, so the required
    # denominator is exactly the registry's required_phase="2-B.6" set
    # (12 assertions). A manifest-set containing anything other than
    # exactly this set — fewer, more, or substituted IDs — is rejected.
    required_denominator = {
        a["assertion_id"]
        for a in registry_obj.get("assertions", [])
        if isinstance(a, dict) and a.get("required_phase") == "2-B.6"
    }

    validate_top_level_binding(manifest, active)
    primary_code = validate_children(
        manifest_set_obj, active, manifest_set_path.parent, known_assertion_ids, required_denominator
    )
    return {"primary_code": primary_code, "active": active, "manifest_set": manifest_set_obj}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--activation-record", required=True, type=Path)
    parser.add_argument("--manifest-set", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)

    started_at = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "command": "python3 " + " ".join(["tools/public_release/verify_at_evidence.py"] + (argv if argv is not None else sys.argv[1:])),
        "started_at": started_at,
    }

    input_hashes = {}
    for label, path in (
        ("registry", args.registry),
        ("activation_record", args.activation_record),
        ("manifest_set", args.manifest_set),
    ):
        if path.is_file():
            try:
                input_hashes[label] = sha256_file(path)
            except OSError:
                input_hashes[label] = None
        else:
            input_hashes[label] = None
    result["input_sha256"] = input_hashes

    exit_code: int
    try:
        outcome = run(args.registry, args.activation_record, args.manifest_set)
    except VerifyError as exc:
        exit_code = 2
        result["primary_code"] = exc.code
        result["exit_code"] = exit_code
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report, never mask as FAIL
        exit_code = 3
        result["primary_code"] = "E_INTERNAL_ERROR"
        result["internal_error"] = f"{type(exc).__name__}: {exc}"
        result["exit_code"] = exit_code
    else:
        exit_code = 0
        result["primary_code"] = outcome["primary_code"]
        result["exit_code"] = exit_code

    result["finished_at"] = datetime.now(timezone.utc).isoformat()

    args.result.parent.mkdir(parents=True, exist_ok=True)
    result_text = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    args.result.write_text(result_text, encoding="utf-8")
    result_sha256 = sha256_bytes(result_text.encode("utf-8"))
    sidecar = args.result.with_suffix(args.result.suffix + ".sha256")
    sidecar.write_text(result_sha256 + "\n", encoding="utf-8")

    if exit_code == 0:
        print(result["primary_code"])
    else:
        print(result["primary_code"], file=sys.stderr)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

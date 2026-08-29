#!/usr/bin/env python3
"""Phase 2-B.6 rollback manifest schema validator.

Validates a rollback manifest against the fixed schema defined in
tasks/public-release/phase2b6_claude_implementation_instruction.md section 7.
This validator is the fail-closed gate that must run BEFORE any rollback
state change is attempted (see backend/tests/test_phase2b6_rollback.py for
the live isolated-root integration test that enforces this ordering against
backend/app/services/runtime_publish.py::AtomicPublisher.rollback()).

No secret values are ever accepted, printed, or persisted by this tool —
only dummy markers in fixtures.

Exit codes:
  0 - VALID
  2 - a single primary E_ROLLBACK_* failure code (fail-closed)
  3 - CLI/runtime internal error
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}([+-]\d{2}:\d{2}|Z)$")


def _is_strict_int(value: Any) -> bool:
    """P2B6-CX-003 round 2: Python's bool is a subclass of int, so a bare
    `isinstance(x, int)` check accepts `True`/`False` for fields that must
    be genuine integers (e.g. exit_code)."""
    return isinstance(value, int) and not isinstance(value, bool)


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value != ""


def _is_valid_timestamp(value: Any) -> bool:
    """P2B6-CX-003 round 2: TIMESTAMP_RE only checked digit-count shape, so
    a calendar-invalid value like `2026-99-99T99:99:99Z` (correct shape,
    impossible date) still matched. Parse semantically after the shape
    check to reject impossible calendar/clock values."""
    if not isinstance(value, str) or not TIMESTAMP_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True

ALLOWED_OPERATOR_JOB_STATE_FIELDS = {"running_jobs", "pending_jobs", "restore_policy"}
ALLOWED_RESULT_FIELDS = {"exit_code", "status", "timestamp"}
ALLOWED_COMPATIBILITY_CONTRACT_FIELDS = {"schema_compatible", "notes"}

REQUIRED_TOP_LEVEL_FIELDS = [
    "manifest_id",
    "version_id",
    "previous_version_id",
    "generated_at",
    "schema_version",
    "manifest_checksum",
    "configuration",
    "image",
    "data",
    "compatibility_contract",
    "operator_job_state",
    "secret",
    "publish_result",
    "rollback_result",
    "verified_at",
    "executor",
    "reviewer",
]
ALLOWED_TOP_LEVEL_FIELDS = set(REQUIRED_TOP_LEVEL_FIELDS)

REQUIRED_CONFIG_FIELDS = {"name", "before_path", "before_sha256", "after_path", "after_sha256"}
REQUIRED_IMAGE_FIELDS = {"service", "before_digest", "after_digest"}
REQUIRED_DATA_FIELDS = {
    "dataset_name", "before_runtime_version_id", "after_runtime_version_id",
    "manifest_sha256", "file_set_sha256",
}
ALLOWED_SECRET_FIELDS = {"name", "location", "recovery_procedure"}
REQUIRED_SECRET_FIELDS = {"name", "location", "recovery_procedure"}

# Fields that, if present anywhere in a secret entry, indicate an actual
# secret value has leaked into the manifest instead of a reference/procedure.
FORBIDDEN_SECRET_VALUE_KEYS = {"value", "token", "password", "secret", "key", "private_key", "credential"}


class RollbackValidationError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _no_dup_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        seen[key] = value
    return seen


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RollbackValidationError("E_ROLLBACK_MANIFEST_UNAVAILABLE") from exc
    try:
        obj = json.loads(raw, object_pairs_hook=_no_dup_keys)
    except json.JSONDecodeError as exc:
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID") from exc
    if not isinstance(obj, dict):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    return obj


def canonical_checksum_bytes(manifest: dict[str, Any]) -> bytes:
    body = {k: v for k, v in manifest.items() if k != "manifest_checksum"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return text.encode("utf-8")


def _is_relative_safe_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    if value.startswith("/"):
        return False
    parts = value.split("/")
    if ".." in parts:
        return False
    return True


def validate(manifest: dict[str, Any]) -> None:
    # 1. additional-field policy (strict allowlist)
    unknown = set(manifest.keys()) - ALLOWED_TOP_LEVEL_FIELDS
    if unknown:
        raise RollbackValidationError("E_ROLLBACK_ADDITIONAL_FIELD")

    # 2. required top-level fields present
    for field in REQUIRED_TOP_LEVEL_FIELDS:
        if field not in manifest or manifest[field] is None:
            raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")

    # 3. schema_version support
    schema_version = manifest["schema_version"]
    if not isinstance(schema_version, str) or schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_UNSUPPORTED")

    # 4. type/shape checks (still "invalid schema" class)
    if not isinstance(manifest["configuration"], list) or not isinstance(manifest["image"], list):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    if not isinstance(manifest["data"], dict) or not isinstance(manifest["secret"], list):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")

    # 4a. P2B6-CX-003 correction: operator_job_state/publish_result/
    # rollback_result/compatibility_contract were only checked for
    # presence, never for type or internal shape, so e.g. a bare string in
    # place of operator_job_state passed as VALID. Every nested object below
    # now goes through a strict allowlist + required-field + type pipeline.
    if not isinstance(manifest["compatibility_contract"], dict):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    if not _is_valid_timestamp(manifest["generated_at"]):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    if not _is_valid_timestamp(manifest["verified_at"]):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")

    # P2B6-CX-003 round 2: manifest_id/version_id/previous_version_id/
    # executor/reviewer were only checked for presence (via
    # REQUIRED_TOP_LEVEL_FIELDS), never for type, so an integer manifest_id
    # or an array reviewer previously validated.
    for identifier_field in ("manifest_id", "version_id", "previous_version_id", "executor", "reviewer"):
        if not _is_nonempty_str(manifest[identifier_field]):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")

    compat = manifest["compatibility_contract"]
    if set(compat.keys()) - ALLOWED_COMPATIBILITY_CONTRACT_FIELDS:
        raise RollbackValidationError("E_ROLLBACK_ADDITIONAL_FIELD")
    if not ALLOWED_COMPATIBILITY_CONTRACT_FIELDS.issubset(compat.keys()):
        raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")
    if not isinstance(compat["schema_compatible"], bool):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    if not isinstance(compat["notes"], str):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")

    job_state = manifest["operator_job_state"]
    if not isinstance(job_state, dict):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    if set(job_state.keys()) - ALLOWED_OPERATOR_JOB_STATE_FIELDS:
        raise RollbackValidationError("E_ROLLBACK_ADDITIONAL_FIELD")
    if not ALLOWED_OPERATOR_JOB_STATE_FIELDS.issubset(job_state.keys()):
        raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")
    if not isinstance(job_state["running_jobs"], list) or not isinstance(job_state["pending_jobs"], list):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    if not all(isinstance(x, str) for x in job_state["running_jobs"] + job_state["pending_jobs"]):
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    if not isinstance(job_state["restore_policy"], str) or not job_state["restore_policy"]:
        raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")

    for result_field in ("publish_result", "rollback_result"):
        result_obj = manifest[result_field]
        if not isinstance(result_obj, dict):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        if set(result_obj.keys()) - ALLOWED_RESULT_FIELDS:
            raise RollbackValidationError("E_ROLLBACK_ADDITIONAL_FIELD")
        if not ALLOWED_RESULT_FIELDS.issubset(result_obj.keys()):
            raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")
        if result_obj["exit_code"] is not None and not _is_strict_int(result_obj["exit_code"]):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        if not _is_nonempty_str(result_obj["status"]):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        if result_obj["timestamp"] is not None and not _is_valid_timestamp(result_obj["timestamp"]):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")

    # 5. checksum verification
    declared_checksum = manifest["manifest_checksum"]
    if not isinstance(declared_checksum, str) or not SHA256_RE.match(declared_checksum):
        raise RollbackValidationError("E_ROLLBACK_CHECKSUM_MALFORMED")
    computed = hashlib.sha256(canonical_checksum_bytes(manifest)).hexdigest()
    if computed != declared_checksum:
        raise RollbackValidationError("E_ROLLBACK_CHECKSUM_MISMATCH")

    # 6. configuration entries: strict allowlist, required fields, hash format, path safety
    for entry in manifest["configuration"]:
        if not isinstance(entry, dict):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        if set(entry.keys()) - REQUIRED_CONFIG_FIELDS:
            raise RollbackValidationError("E_ROLLBACK_ADDITIONAL_FIELD")
        if not REQUIRED_CONFIG_FIELDS.issubset(entry.keys()):
            raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")
        if not _is_nonempty_str(entry["name"]):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        for path_field in ("before_path", "after_path"):
            if not _is_relative_safe_path(entry[path_field]):
                raise RollbackValidationError("E_ROLLBACK_PATH_ESCAPE")
        for hash_field in ("before_sha256", "after_sha256"):
            value = entry[hash_field]
            if not isinstance(value, str) or not SHA256_RE.match(value):
                raise RollbackValidationError("E_ROLLBACK_HASH_MALFORMED")

    # 7. image entries: strict allowlist, required fields, digest format
    for entry in manifest["image"]:
        if not isinstance(entry, dict):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        if set(entry.keys()) - REQUIRED_IMAGE_FIELDS:
            raise RollbackValidationError("E_ROLLBACK_ADDITIONAL_FIELD")
        if not REQUIRED_IMAGE_FIELDS.issubset(entry.keys()):
            raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")
        if not _is_nonempty_str(entry["service"]):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        for digest_field in ("before_digest", "after_digest"):
            value = entry[digest_field]
            if not isinstance(value, str) or not IMAGE_DIGEST_RE.match(value):
                raise RollbackValidationError("E_ROLLBACK_HASH_MALFORMED")

    # 8. data section: strict allowlist, required fields, hash format, cross-reference consistency
    data = manifest["data"]
    if set(data.keys()) - REQUIRED_DATA_FIELDS:
        raise RollbackValidationError("E_ROLLBACK_ADDITIONAL_FIELD")
    if not REQUIRED_DATA_FIELDS.issubset(data.keys()):
        raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")
    for identifier_field in ("dataset_name", "before_runtime_version_id", "after_runtime_version_id"):
        if not _is_nonempty_str(data[identifier_field]):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
    for hash_field in ("manifest_sha256", "file_set_sha256"):
        value = data[hash_field]
        if not isinstance(value, str) or not SHA256_RE.match(value):
            raise RollbackValidationError("E_ROLLBACK_HASH_MALFORMED")
    if data["before_runtime_version_id"] != manifest["previous_version_id"]:
        raise RollbackValidationError("E_ROLLBACK_REFERENCE_INCONSISTENT")
    if data["after_runtime_version_id"] != manifest["version_id"]:
        raise RollbackValidationError("E_ROLLBACK_REFERENCE_INCONSISTENT")

    # 9. secret entries: strict allowlist of fields, no value-bearing keys
    for entry in manifest["secret"]:
        if not isinstance(entry, dict):
            raise RollbackValidationError("E_ROLLBACK_SCHEMA_INVALID")
        keys = set(entry.keys())
        if not REQUIRED_SECRET_FIELDS.issubset(keys):
            raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")
        extra_keys = keys - ALLOWED_SECRET_FIELDS
        if extra_keys & FORBIDDEN_SECRET_VALUE_KEYS or extra_keys:
            raise RollbackValidationError("E_ROLLBACK_SECRET_VALUE_LEAK")
        for field in ("name", "location", "recovery_procedure"):
            if not isinstance(entry[field], str) or not entry[field]:
                raise RollbackValidationError("E_ROLLBACK_REQUIRED_MISSING")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--result", required=True, type=Path)
    args = parser.parse_args(argv)

    result: dict[str, Any] = {"command": "phase2b6_rollback_validate.py --manifest " + str(args.manifest)}
    try:
        manifest = load_manifest(args.manifest)
        validate(manifest)
    except RollbackValidationError as exc:
        exit_code = 2
        result["primary_code"] = exc.code
    except Exception as exc:  # noqa: BLE001
        exit_code = 3
        result["primary_code"] = "E_INTERNAL_ERROR"
        result["internal_error"] = f"{type(exc).__name__}: {exc}"
    else:
        exit_code = 0
        result["primary_code"] = "VALID"

    result["exit_code"] = exit_code
    args.result.parent.mkdir(parents=True, exist_ok=True)
    args.result.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(result["primary_code"], file=sys.stderr if exit_code else sys.stdout)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

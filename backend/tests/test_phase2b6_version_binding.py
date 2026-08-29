"""
Phase 2-B.6 受入試験 — AT-18〜AT-20 assertion evidence registry の
4-tuple binding parser（`tools/public_release/verify_at_evidence.py`）と、
承認済みregistry構造の自動試験
（tasks/public-release/phase2b6_claude_implementation_instruction.md 第4-6節）。

対象:
  - VBF-P001/P002, VBF-N001〜N025（27 fixture、第6節）
  - registry raw/unique/mandatory 20/20/20、phase別12/8、REM-041 6件exact set、
    canonical SHA-256再計算一致（第4節）

実行:
    cd backend && ../venv/bin/python -m pytest tests/test_phase2b6_version_binding.py -v

このファイルはsubprocessで実CLIを呼び出す（production codeにtest専用
bypassを入れないという方針に合わせ、parser自体へのtest-only分岐はない）。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "tools/public_release/verify_at_evidence.py"
FIXTURE_BASE = REPO_ROOT / "tests/fixtures/public_release/version_binding"
SHARED_REGISTRY = FIXTURE_BASE / "shared/registry/p2a-at18-20-v2.json"
SHARED_ACTIVATION = FIXTURE_BASE / "shared/activation-approved-v2.json"

V2_HASH = "c3cb704bd6e6f4f7ae0b19e1962ae0f5da4cd95d94bde47bfb67b4d02bbc5799"

VBF_CASES = [
    ("VBF-P001", 0, "PASS"),
    ("VBF-P002", 0, "PASS_COMPATIBLE_REUSE"),
    ("VBF-N001", 2, "E_BIND_NAME_MISSING"),
    ("VBF-N002", 2, "E_BIND_NAME_NULL"),
    ("VBF-N003", 2, "E_BIND_NAME_EMPTY"),
    ("VBF-N004", 2, "E_BIND_VERSION_MISSING"),
    ("VBF-N005", 2, "E_BIND_VERSION_NULL"),
    ("VBF-N006", 2, "E_BIND_VERSION_EMPTY"),
    ("VBF-N007", 2, "E_BIND_SCHEMA_MISSING"),
    ("VBF-N008", 2, "E_BIND_SCHEMA_NULL"),
    ("VBF-N009", 2, "E_BIND_SCHEMA_EMPTY"),
    ("VBF-N010", 2, "E_BIND_HASH_MISSING"),
    ("VBF-N011", 2, "E_BIND_HASH_NULL"),
    ("VBF-N012", 2, "E_BIND_HASH_EMPTY"),
    ("VBF-N013", 2, "E_BIND_NAME_UNKNOWN"),
    ("VBF-N014", 2, "E_BIND_VERSION_UNKNOWN"),
    ("VBF-N015", 2, "E_BIND_SCHEMA_UNSUPPORTED"),
    ("VBF-N016", 2, "E_BIND_HASH_MALFORMED"),
    ("VBF-N017", 2, "E_BIND_HASH_MISMATCH"),
    ("VBF-N018", 2, "E_REGISTRY_UNAVAILABLE"),
    ("VBF-N019", 2, "E_BIND_MIXED_VERSION"),
    ("VBF-N020", 2, "E_BIND_VERSION_HASH_MISMATCH"),
    ("VBF-N021", 2, "E_REGISTRY_SAME_VERSION_MUTATION"),
    ("VBF-N022", 2, "E_REGISTRY_NOT_APPROVED"),
    ("VBF-N023", 2, "E_COMPAT_RECORD_MISSING"),
    ("VBF-N024", 2, "E_COMPAT_RECORD_INCOMPLETE"),
    ("VBF-N025", 2, "E_COMPAT_SELF_REVIEW"),
]

assert len(VBF_CASES) == 27
assert len({fid for fid, _, _ in VBF_CASES}) == 27
assert sum(1 for _, exit_code, code in VBF_CASES if code in ("PASS", "PASS_COMPATIBLE_REUSE")) == 2
assert sum(1 for _, exit_code, code in VBF_CASES if code not in ("PASS", "PASS_COMPATIBLE_REUSE")) == 25


def _registry_for(fixture_id: str) -> Path:
    if fixture_id == "VBF-N018":
        return FIXTURE_BASE / "VBF-N018/registry/does-not-exist.json"
    if fixture_id == "VBF-N021":
        return FIXTURE_BASE / "VBF-N021/registry/p2a-at18-20-v2-same-version-mutated.json"
    return SHARED_REGISTRY


def _activation_for(fixture_id: str) -> Path:
    if fixture_id == "VBF-N022":
        return FIXTURE_BASE / "VBF-N022/activation-record.json"
    return SHARED_ACTIVATION


@pytest.mark.parametrize("fixture_id,expected_exit,expected_code", VBF_CASES)
def test_version_binding_fixture(tmp_path, fixture_id, expected_exit, expected_code):
    manifest_set = FIXTURE_BASE / fixture_id / "manifest-set.json"
    assert manifest_set.is_file(), f"{fixture_id} manifest-set.json missing"

    result_path = tmp_path / f"{fixture_id}.json"
    cmd = [
        sys.executable, str(TOOL),
        "--registry", str(_registry_for(fixture_id)),
        "--activation-record", str(_activation_for(fixture_id)),
        "--manifest-set", str(manifest_set),
        "--result", str(result_path),
    ]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=30)

    assert proc.returncode == expected_exit, (
        f"{fixture_id}: exit {proc.returncode} != {expected_exit}; "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    assert result_path.is_file(), f"{fixture_id}: result JSON not written"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["primary_code"] == expected_code, (
        f"{fixture_id}: primary_code {result['primary_code']!r} != {expected_code!r}"
    )
    assert result["exit_code"] == expected_exit
    for key in ("registry", "activation_record", "manifest_set"):
        if fixture_id == "VBF-N018" and key == "registry":
            # This fixture's entire point is that the registry path does not
            # exist, so its input hash is legitimately absent.
            assert result["input_sha256"].get(key) is None
            continue
        assert result["input_sha256"].get(key), f"{fixture_id}: missing input_sha256[{key}]"


def test_no_duplicate_fixture_ids():
    ids = [fid for fid, _, _ in VBF_CASES]
    assert len(ids) == len(set(ids))


def test_vbf_n018_registry_path_absent():
    """The unavailable-registry fixture must never create the file it tests for."""
    target = FIXTURE_BASE / "VBF-N018/registry/does-not-exist.json"
    assert not target.exists()
    assert not target.is_symlink()


class TestRegistryStructure:
    """AT20-A02/AT20-A03のparser個別条件 — raw/unique/mandatory/phase集計、
    REM-041 exact set、canonical hash再計算一致（第4・11節）。"""

    @pytest.fixture(scope="class")
    def registry(self):
        with open(SHARED_REGISTRY, "rb") as f:
            raw = f.read()
        return json.loads(raw, object_pairs_hook=self._no_dup_keys)

    @staticmethod
    def _no_dup_keys(pairs):
        seen = {}
        for k, v in pairs:
            assert k not in seen, f"duplicate key {k}"
            seen[k] = v
        return seen

    def test_raw_unique_mandatory_20(self, registry):
        assertions = registry["assertions"]
        assert len(assertions) == 20
        ids = [a["assertion_id"] for a in assertions]
        assert len(set(ids)) == 20
        assert all(a["mandatory"] is True for a in assertions)

    def test_phase_counts_12_8(self, registry):
        assertions = registry["assertions"]
        scoped = [a for a in assertions if a["required_phase"] == "2-B.6"]
        deferred = [a for a in assertions if a["required_phase"] == "2-E"]
        assert len(scoped) == 12
        assert len(deferred) == 8
        assert len(scoped) + len(deferred) == 20
        unknown_phase = [a for a in assertions if a["required_phase"] not in ("2-B.6", "2-E")]
        assert unknown_phase == []

    def test_expected_counts_field_matches_raw(self, registry):
        counts = registry["expected_counts"]
        for test_id, expect in (("AT-18", (4, 2, 6)), ("AT-19", (4, 2, 6)), ("AT-20", (4, 4, 8))):
            b6, e, total = expect
            assert counts[test_id]["2-B.6"] == b6
            assert counts[test_id]["2-E"] == e
            assert counts[test_id]["total"] == total
            raw_b6 = sum(1 for a in registry["assertions"] if a["test_id"] == test_id and a["required_phase"] == "2-B.6")
            raw_e = sum(1 for a in registry["assertions"] if a["test_id"] == test_id and a["required_phase"] == "2-E")
            assert raw_b6 == b6
            assert raw_e == e
        assert counts["overall"]["2-B.6"] == 12
        assert counts["overall"]["2-E"] == 8
        assert counts["overall"]["total"] == 20

    def test_rem_041_exact_six_assertions(self, registry):
        expected = {"AT18-A01", "AT19-A03", "AT20-A03", "AT20-A04", "AT20-A06", "AT20-A08"}
        actual = {
            a["assertion_id"] for a in registry["assertions"] if "REM-041" in a["remediation_ids"]
        }
        assert actual == expected

    def test_canonical_hash_matches_declared(self, registry):
        body = {k: v for k, v in registry.items() if k != "registry_sha256"}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        computed = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        assert computed == registry["registry_sha256"] == V2_HASH

    def test_no_orphan_or_unknown_test_id(self, registry):
        known_test_ids = {"AT-18", "AT-19", "AT-20"}
        for a in registry["assertions"]:
            assert a["test_id"] in known_test_ids
            assert a["subject"]
            assert a["expected"]
            assert a["evidence_types"]
            assert a["remediation_ids"]


def test_activation_record_matches_registry():
    activation = json.loads(SHARED_ACTIVATION.read_text(encoding="utf-8"))
    registry = json.loads(SHARED_REGISTRY.read_text(encoding="utf-8"))
    for field in ("registry_name", "registry_version", "schema_version", "registry_sha256"):
        assert activation[field] == registry[field]
    assert activation["new_state"] == "APPROVED_ACTIVE"
    assert activation["review_verdict"].startswith("PASS")


# ---------------------------------------------------------------------------
# P2B6-R2-CX-001 / round 3: fixture tree contamination detection.
#
# CODEX round-2 independent verification found 81 " 2.*"-suffixed duplicate
# files under this directory, traced to iCloud Drive sync conflict copies
# created while this repo (under ~/Documents) was being rewritten rapidly
# during fixture generation. CODEX round-3 then found the first allowlist
# used regex RANGES (e.g. `N0[0-2][0-9]`) that admit non-canonical IDs such
# as VBF-N000 or VBF-N026..N029 without being caught, because
# test_version_binding_fixture only iterates the fixed 27-entry VBF_CASES
# list rather than comparing against the actual directory contents. This
# version builds the allowlist from the exact 27 fixture IDs (VBF_CASES)
# instead of a pattern range, so anything outside that exact set — a
# duplicate copy, a fabricated VBF-N026, or a stray directory — fails.
# ---------------------------------------------------------------------------
import re as _re

_ARTIFACT_ROLE_RE = r"(input|stdout|stderr|result)"

_ALLOWED_FIXTURE_TREE_EXACT = {
    "shared/activation-approved-v2.json",
    "shared/registry/p2a-at18-20-v2.json",
    "VBF-P002/manifests/AT18-A02-v1.json",
    "VBF-P002/compatibility/AT18-A02-v1-to-v2.json",
    "VBF-N019/manifests/AT18-A02-v1.json",
    "VBF-N021/registry/p2a-at18-20-v2-same-version-mutated.json",
    "VBF-N022/activation-record.json",
    "scoped/manifest-set.json",
}


def _build_allowed_fixture_tree_patterns() -> list[_re.Pattern]:
    fixture_ids = sorted({fid for fid, _, _ in VBF_CASES})
    assert len(fixture_ids) == 27, "VBF_CASES must stay at exactly 27 IDs for this allowlist to be exact"
    patterns = [_re.escape(p) for p in _ALLOWED_FIXTURE_TREE_EXACT]
    for fid in fixture_ids:
        escaped = _re.escape(fid)
        patterns.append(rf"{escaped}/manifest-set\.json")
        patterns.append(rf"{escaped}/artifacts/AT\d{{2}}-A0[1-9](-v1)?\.{_ARTIFACT_ROLE_RE}\.txt")
        patterns.append(rf"results/{escaped}\.json")
        patterns.append(rf"results/{escaped}\.json\.sha256")
    patterns.append(rf"scoped/artifacts/AT\d{{2}}-A0[1-9]\.{_ARTIFACT_ROLE_RE}\.txt")
    return [_re.compile(f"^{p}$") for p in patterns]


_ALLOWED_FIXTURE_TREE_RE = _build_allowed_fixture_tree_patterns()


def test_fixture_tree_has_no_unexpected_files():
    unexpected = []
    for path in FIXTURE_BASE.rglob("*"):
        if path.is_dir():
            continue
        rel = str(path.relative_to(FIXTURE_BASE))
        if not any(pat.match(rel) for pat in _ALLOWED_FIXTURE_TREE_RE):
            unexpected.append(rel)
    assert unexpected == [], f"unexpected/unaccounted files in fixture tree: {unexpected}"


def test_fixture_tree_has_no_unexpected_directories():
    """A directory named VBF-N026 (etc.) with no files inside it would pass
    the file-level allowlist above trivially (rglob never yields an empty
    dir as a file). Check top-level VBF-* directory names directly against
    the exact 27-ID set too."""
    fixture_ids = {fid for fid, _, _ in VBF_CASES}
    actual_vbf_dirs = {p.name for p in FIXTURE_BASE.iterdir() if p.is_dir() and p.name.startswith("VBF-")}
    assert actual_vbf_dirs == fixture_ids, f"unexpected VBF-* directories: {actual_vbf_dirs - fixture_ids}"


# ---------------------------------------------------------------------------
# Phase 2-D Round 12D-C2 — portable token contract (OWNER decision: option 2).
#
# The input evidence artifact records a fixed literal token vector, never a
# machine-absolute interpreter or repo path. verify_at_evidence.py matches
# each of the 4 argv slots by exact string equality against its contracted
# literal and then derives the trusted interpreter/script identity from its
# own process state. These tests are the resolver's mutation suite for that
# contract, plus a portability check (same fixture, different absolute root,
# same outcome) and a drift guard on the frozen scoped-runner identity.
# ---------------------------------------------------------------------------
import importlib.util as _ilu  # noqa: E402
import os as _os  # noqa: E402
import shutil as _shutil  # noqa: E402

_SCOPED_RUNNER = REPO_ROOT / "tools/public_release/phase2b6_scoped_assertions.py"
_RUN_ID = "0" * 32
_PY_TOK = "<PYTHON>"
_SC_TOK = "<REPO_ROOT>/tools/public_release/phase2b6_scoped_assertions.py"


def _load_verify_module(name: str, root: Path):
    spec = _ilu.spec_from_file_location(name, str(root / "tools/public_release/verify_at_evidence.py"))
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def veva():
    return _load_verify_module("veva_under_test", REPO_ROOT)


def _write_input_child(tmp_path: Path, argv, run_id=_RUN_ID, assertion_id="AT18-A01"):
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    body = json.dumps({"argv": argv, "run_id": run_id}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    (tmp_path / "artifacts/x.input.txt").write_bytes(body)
    return {
        "assertion_id": assertion_id,
        "run_id": run_id,
        "artifacts": [{"role": "input", "path": "artifacts/x.input.txt",
                       "sha256": hashlib.sha256(body).hexdigest()}],
    }


_CANONICAL_ARGV = [_PY_TOK, _SC_TOK, "--assertion-id", "AT18-A01"]

_ARGV_MUTATIONS = {
    "abs_python_path": ["/usr/bin/python3", _SC_TOK, "--assertion-id", "AT18-A01"],
    "abs_repo_path": [_PY_TOK, str(_SCOPED_RUNNER), "--assertion-id", "AT18-A01"],
    "argv0_python3_literal": ["python3", _SC_TOK, "--assertion-id", "AT18-A01"],
    "argv1_relative_script": [_PY_TOK, "tools/public_release/phase2b6_scoped_assertions.py", "--assertion-id", "AT18-A01"],
    "PYTHON_token_suffix": ["<PYTHON>x", _SC_TOK, "--assertion-id", "AT18-A01"],
    "PYTHON_token_prefix": ["x<PYTHON>", _SC_TOK, "--assertion-id", "AT18-A01"],
    "dollar_brace_PYTHON": ["${PYTHON}", _SC_TOK, "--assertion-id", "AT18-A01"],
    "brace_PYTHON": ["{PYTHON}", _SC_TOK, "--assertion-id", "AT18-A01"],
    "repo_root_no_script_suffix": [_PY_TOK, "<REPO_ROOT>", "--assertion-id", "AT18-A01"],
    "repo_root_dotdot": [_PY_TOK, "<REPO_ROOT>/../tools/public_release/phase2b6_scoped_assertions.py", "--assertion-id", "AT18-A01"],
    "repo_root_double_slash": [_PY_TOK, "<REPO_ROOT>//tools/public_release/phase2b6_scoped_assertions.py", "--assertion-id", "AT18-A01"],
    "repo_root_embedded_traversal": [_PY_TOK, "<REPO_ROOT>/tools/public_release/../../../etc/passwd", "--assertion-id", "AT18-A01"],
    "token_in_argv2": [_PY_TOK, _SC_TOK, _PY_TOK, "AT18-A01"],
    "token_in_argv3": [_PY_TOK, _SC_TOK, "--assertion-id", _SC_TOK],
    "argv_extra_element": [_PY_TOK, _SC_TOK, "--assertion-id", "AT18-A01", "--x"],
    "argv_missing_element": [_PY_TOK, _SC_TOK, "--assertion-id"],
    "argv_non_string_element": [_PY_TOK, _SC_TOK, "--assertion-id", 1],
    "shell_metacharacter": [_PY_TOK, _SC_TOK + "; rm -rf /", "--assertion-id", "AT18-A01"],
    # A machine-absolute path pinned to some other authoring workspace: the
    # literal is assembled at runtime so this test file itself carries no
    # absolute developer path (typed boundary scan must stay ABSOLUTE_USER_PATH=0).
    "legacy_authoring_root": [_PY_TOK, str(REPO_ROOT) + "/tools/public_release/phase2b6_scoped_assertions.py", "--assertion-id", "AT18-A01"],
    "arbitrary_cleanclone_root": [_PY_TOK, "/opt/ci/checkout/tools/public_release/phase2b6_scoped_assertions.py", "--assertion-id", "AT18-A01"],
    "env_var_root_literal": [_PY_TOK, "$REPO_ROOT/tools/public_release/phase2b6_scoped_assertions.py", "--assertion-id", "AT18-A01"],
    "policy_unlisted_target": [_PY_TOK, "<REPO_ROOT>/tools/public_release/not_in_policy.py", "--assertion-id", "AT18-A01"],
    "wrong_assertion_id_in_argv3": [_PY_TOK, _SC_TOK, "--assertion-id", "AT18-A02"],
}


class TestPortableTokenContract:
    def test_canonical_token_constants(self, veva):
        assert veva.CANONICAL_ARGV_PYTHON_TOKEN == _PY_TOK
        assert veva.CANONICAL_ARGV_SCRIPT_TOKEN == _SC_TOK

    def test_frozen_scoped_runner_identity_matches_disk(self, veva):
        data = _SCOPED_RUNNER.read_bytes()
        assert hashlib.sha256(data).hexdigest() == veva.EXPECTED_SCOPED_RUNNER_SHA256, (
            "verify_at_evidence.EXPECTED_SCOPED_RUNNER_SHA256 has drifted from the "
            "on-disk phase2b6_scoped_assertions.py — update the constant and re-freeze."
        )
        mode = "100%o" % (_os.stat(_SCOPED_RUNNER).st_mode & 0o777)
        assert mode == veva.EXPECTED_SCOPED_RUNNER_MODE

    def test_canonical_argv_accepted(self, veva, tmp_path):
        child = _write_input_child(tmp_path, list(_CANONICAL_ARGV))
        veva._validate_child_argv_binding(child, tmp_path)  # no raise

    @pytest.mark.parametrize("name", sorted(_ARGV_MUTATIONS))
    def test_argv_mutation_rejected(self, veva, tmp_path, name):
        child = _write_input_child(tmp_path, _ARGV_MUTATIONS[name])
        with pytest.raises(veva.VerifyError):
            veva._validate_child_argv_binding(child, tmp_path)

    def test_argv_not_list_rejected(self, veva, tmp_path):
        child = _write_input_child(tmp_path, {"0": _PY_TOK})
        with pytest.raises(veva.VerifyError):
            veva._validate_child_argv_binding(child, tmp_path)

    def test_run_id_mismatch_still_detected(self, veva, tmp_path):
        child = _write_input_child(tmp_path, list(_CANONICAL_ARGV), run_id="0" * 32)
        child["run_id"] = "1" * 32
        with pytest.raises(veva.VerifyError):
            veva._validate_child_argv_binding(child, tmp_path)

    def test_trusted_binding_rejects_missing_scoped_runner(self, tmp_path):
        root = tmp_path / "noscript"
        (root / "tools/public_release").mkdir(parents=True)
        _shutil.copy2(REPO_ROOT / "tools/public_release/verify_at_evidence.py",
                      root / "tools/public_release/verify_at_evidence.py")
        mod = _load_verify_module("veva_noscript", root)
        with pytest.raises(mod.VerifyError):
            mod._build_trusted_child_command_binding()

    def test_trusted_binding_rejects_sha_drift(self, tmp_path):
        root = tmp_path / "badsha"
        (root / "tools/public_release").mkdir(parents=True)
        _shutil.copy2(REPO_ROOT / "tools/public_release/verify_at_evidence.py",
                      root / "tools/public_release/verify_at_evidence.py")
        (root / "tools/public_release/phase2b6_scoped_assertions.py").write_text("# different bytes\n")
        mod = _load_verify_module("veva_badsha", root)
        with pytest.raises(mod.VerifyError):
            mod._build_trusted_child_command_binding()

    def test_trusted_binding_rejects_external_symlink(self, tmp_path):
        root = tmp_path / "extlink"
        (root / "tools/public_release").mkdir(parents=True)
        _shutil.copy2(REPO_ROOT / "tools/public_release/verify_at_evidence.py",
                      root / "tools/public_release/verify_at_evidence.py")
        outside = tmp_path / "outside_scoped.py"
        _shutil.copy2(_SCOPED_RUNNER, outside)
        _os.symlink(str(outside), str(root / "tools/public_release/phase2b6_scoped_assertions.py"))
        mod = _load_verify_module("veva_extlink", root)
        with pytest.raises(mod.VerifyError):
            mod._build_trusted_child_command_binding()

    def test_portable_across_relocated_root(self, tmp_path):
        """VBF-P001 validates identically when the whole tree is relocated to
        an unrelated absolute path (the pre-C2 failure mode)."""
        root = tmp_path / "relocated" / "OnHighGround2-clone"
        (root / "tools/public_release").mkdir(parents=True)
        for s in ("verify_at_evidence.py", "phase2b6_scoped_assertions.py"):
            _shutil.copy2(REPO_ROOT / "tools/public_release" / s, root / "tools/public_release" / s)
        _shutil.copytree(FIXTURE_BASE, root / "tests/fixtures/public_release/version_binding",
                         ignore=_shutil.ignore_patterns("* 2"))
        mod = _load_verify_module("veva_relocated", root)
        base = root / "tests/fixtures/public_release/version_binding"
        outcome = mod.run(base / "shared/registry/p2a-at18-20-v2.json",
                          base / "shared/activation-approved-v2.json",
                          base / "VBF-P001/manifest-set.json")
        assert outcome["primary_code"] == "PASS"

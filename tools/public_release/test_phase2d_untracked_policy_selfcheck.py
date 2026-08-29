"""
test_phase2d_untracked_policy_selfcheck.py — untracked default-deny承認policyの
negative control（Phase 2-D Round 5A、指示書第4節）。

すべてrepo-external fixture git repository（`tmp_path`配下）で検証し、実
source repository（OnHighGround2自身）には一切触れない。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_untracked_policy_selfcheck.py -v
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402
import phase2d_untracked_policy as policy_mod  # noqa: E402


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _init_fixture_repo(tmp_path: Path, name: str = "fixture_repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@local.invalid")
    _git(repo, "config", "user.name", "Fixture")
    (repo / "backend").mkdir()
    (repo / "backend" / "app.py").write_text("print('baseline')\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "frontend").mkdir()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo


def _approved_entry_for(repo: Path, path: str, classification: str) -> dict:
    full = repo / path
    object_type, mode = policy_mod._object_type_and_mode(full)
    sha256 = policy_mod._content_sha256(full, object_type)
    size = full.lstat().st_size if object_type != "SYMLINK" else len(os.readlink(full))
    return {
        "path": path, "sha256": sha256, "size": size, "mode": mode,
        "object_type": object_type, "classification": classification,
    }


def _approved_policy(*entries: dict) -> dict:
    return {"schema_version": 1, "entries": list(entries)}


# ---------------------------------------------------------------------------
# 4.1 必ず拒否
# ---------------------------------------------------------------------------

def test_01_unapproved_python_probe_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "unapproved_probe.py").write_text("print('probe')\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=None)
    assert not any(e["path"] == "backend/unapproved_probe.py" for e in manifest["entries"])
    pending = next(e for e in manifest["pending_owner_approval_entries"] if e["path"] == "backend/unapproved_probe.py")
    assert pending["approval_status"] == "PENDING_OWNER_APPROVAL"
    assert manifest["pending_owner_approval_count"] > 0


def test_02_unapproved_shell_probe_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "scripts" / "unapproved_probe.sh").write_text("#!/bin/sh\necho probe\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=None)
    assert not any(e["path"] == "scripts/unapproved_probe.sh" for e in manifest["entries"])


def test_03_unapproved_js_probe_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "frontend" / "unapproved_probe.js").write_text("console.log('probe')\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=None)
    assert not any(e["path"] == "frontend/unapproved_probe.js" for e in manifest["entries"])


def test_04_unapproved_json_probe_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "unapproved_probe.json").write_text('{"x":1}\n', encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=None)
    assert not any(e["path"] == "backend/unapproved_probe.json" for e in manifest["entries"])


def test_05_sibling_file_in_approved_directory_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "approved.py").write_text("print('approved')\n", encoding="utf-8")
    (repo / "backend" / "sibling_unapproved.py").write_text("print('sibling')\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "backend/approved.py", "BUILD_INPUT"))
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert any(e["path"] == "backend/approved.py" for e in manifest["entries"])
    assert not any(e["path"] == "backend/sibling_unapproved.py" for e in manifest["entries"])


def test_06_case_only_difference_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "Approved.PY").write_text("print('approved')\n", encoding="utf-8")
    approved_entry = _approved_entry_for(repo, "backend/Approved.PY", "BUILD_INPUT")
    # approved policyはlowercase版のpathで登録されているが、実ファイルはcase違い
    mismatched = dict(approved_entry)
    mismatched["path"] = "backend/approved.py"
    approved = _approved_policy(mismatched)
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert not any(e["path"] == "backend/Approved.PY" for e in manifest["entries"])


def test_07_same_path_different_hash_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "drifted.py").write_text("print('v1')\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "backend/drifted.py", "BUILD_INPUT"))
    # approval後にfileの内容が変わった
    (repo / "backend" / "drifted.py").write_text("print('v2 — changed after approval')\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert not any(e["path"] == "backend/drifted.py" for e in manifest["entries"])


def test_08_same_hash_different_path_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "original.py").write_text("print('identical content')\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "backend/original.py", "BUILD_INPUT"))
    (repo / "backend" / "copy.py").write_text("print('identical content')\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert any(e["path"] == "backend/original.py" for e in manifest["entries"])
    assert not any(e["path"] == "backend/copy.py" for e in manifest["entries"])


def test_09_symlink_instead_of_approved_regular_file_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "target.py").write_text("print('target')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add target")
    (repo / "backend" / "link_or_file.py").write_text("print('regular')\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "backend/link_or_file.py", "BUILD_INPUT"))
    (repo / "backend" / "link_or_file.py").unlink()
    os.symlink("target.py", repo / "backend" / "link_or_file.py")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert not any(e["path"] == "backend/link_or_file.py" for e in manifest["entries"])


def test_10_executable_mode_change_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    target = repo / "scripts" / "tool.sh"
    target.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "scripts/tool.sh", "BUILD_INPUT"))
    os.chmod(target, 0o755)  # approval後にexecutable modeへ変更
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert not any(e["path"] == "scripts/tool.sh" for e in manifest["entries"])


def test_11_parent_traversal_path_rejected():
    with pytest.raises(policy_mod.PolicyError):
        policy_mod.validate_canonical_path("backend/../../../escape.py")


def test_12_absolute_path_rejected():
    with pytest.raises(policy_mod.PolicyError):
        policy_mod.validate_canonical_path("/etc/passwd")


def test_13_unicode_normalization_collision_rejected():
    # "が" (NFC, U+304C) と "か"+濁点 (NFD, U+304B U+3099) は見た目同じでも
    # 別バイト列。NFDのまま渡されたcanonical pathはambiguousとして拒否する。
    nfd_path = "docs/が.md"
    with pytest.raises(policy_mod.PolicyError):
        policy_mod.validate_canonical_path(nfd_path)


# ---------------------------------------------------------------------------
# 4.2 承認後だけ受理できること
# ---------------------------------------------------------------------------

def test_14_exact_match_all_fields_approved(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new_module.py").write_text("print('new')\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "backend/new_module.py", "BUILD_INPUT"))
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    entry = next(e for e in manifest["entries"] if e["path"] == "backend/new_module.py")
    assert entry["state"] == "ADDED"


def test_15_classification_mismatch_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new_module.py").write_text("print('new')\n", encoding="utf-8")
    entry = _approved_entry_for(repo, "backend/new_module.py", "BUILD_INPUT")
    entry["classification"] = "TEST_FIXTURE"  # 実際のclassify()結果と食い違う
    approved = _approved_policy(entry)
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert not any(e["path"] == "backend/new_module.py" for e in manifest["entries"])


def test_16_default_deny_with_no_policy(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "anything.py").write_text("print('anything')\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=None)
    assert manifest["entries"] == [] or all(e["state"] != "ADDED" for e in manifest["entries"])


# ---------------------------------------------------------------------------
# candidate policy生成自体のself-test
# ---------------------------------------------------------------------------

def test_17_candidate_generation_rejects_duplicate_and_casefold_collision():
    # macOSのdefault filesystemはcase-insensitiveなため、2つの別名file
    # （backend/dup.py と backend/DUP.py）を実際に同時作成できない。
    # collision検出ロジック自体はpath文字列のみで判定できるため、
    # `check_no_duplicates_or_casefold_collisions()`を直接synthetic pathで検証する。
    with pytest.raises(policy_mod.PolicyError, match="case-fold"):
        policy_mod.check_no_duplicates_or_casefold_collisions(
            ["backend/dup.py", "backend/DUP.py"]
        )


def test_17b_duplicate_path_rejected():
    with pytest.raises(policy_mod.PolicyError, match="duplicate"):
        policy_mod.check_no_duplicates_or_casefold_collisions(
            ["backend/a.py", "backend/a.py"]
        )


def test_18_candidate_generation_classifies_correctly(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new_module.py").write_text("print('new')\n", encoding="utf-8")
    candidate = policy_mod.generate_candidate_untracked_policy(repo)
    entry = next(e for e in candidate["entries"] if e["path"] == "backend/new_module.py")
    assert entry["classification"] == "BUILD_INPUT"


def test_19_approved_policy_self_hash_field_rejected(tmp_path):
    policy_path = tmp_path / "approved.json"
    import json
    policy_path.write_text(
        json.dumps({"schema_version": 1, "entries": [], "self_sha256": "deadbeef"}),
        encoding="utf-8",
    )
    with pytest.raises(policy_mod.PolicyError, match="self-record"):
        policy_mod.load_approved_untracked_policy(policy_path)


def test_20_approved_policy_duplicate_path_rejected(tmp_path):
    policy_path = tmp_path / "approved.json"
    import json
    entry = {
        "path": "backend/a.py", "sha256": "0" * 64, "size": 1, "mode": "100644",
        "object_type": "REGULAR_FILE", "classification": "BUILD_INPUT",
    }
    policy_path.write_text(
        json.dumps({"schema_version": 1, "entries": [entry, dict(entry)]}), encoding="utf-8"
    )
    with pytest.raises(policy_mod.PolicyError, match="duplicate"):
        policy_mod.load_approved_untracked_policy(policy_path)

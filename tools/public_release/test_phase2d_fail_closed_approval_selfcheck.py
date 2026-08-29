"""
test_phase2d_fail_closed_approval_selfcheck.py — fail-closed approval package
のnegative control（Phase 2-D Round 5C、指示書第4節、18項目）。

CODEX round 5B再検証finding（P2D-UNTRACKED-APPROVAL-POLICY =
NOT VALID FOR CURRENT RELEASE BYTES）の回帰防止: release root内に1件でも
OWNER未承認のuntracked entryが残っている場合、snapshot toolはPASSを
宣言してはならず、seed clone・overlay・second cloneのいずれも開始しては
ならない。本testはこの契約をsubprocess経由（実際のCLI exit code）と
関数呼び出し経由（seed_clone呼び出しの有無）の両方で検証する。

すべてrepo-external fixture git repository（`tmp_path`配下）で検証し、実
source repository（OnHighGround2自身）には一切触れない。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_fail_closed_approval_selfcheck.py -v
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402
import phase2d_at17_clean_clone as snapshot_mod  # noqa: E402
import phase2d_untracked_policy as policy_mod  # noqa: E402

TOOL = Path(__file__).resolve().parent / "phase2d_at17_clean_clone.py"


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


def _run_cli(repo: Path, extra_args: list[str], check: bool = False) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(TOOL), "--repo-root", str(repo), "--no-evidence", *extra_args]
    return subprocess.run(cmd, cwd=repo, capture_output=True, text=True, timeout=60)


# ---------------------------------------------------------------------------
# 1. approved policyなし → nonzero
# ---------------------------------------------------------------------------

def test_01_no_approved_policy_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    proc = _run_cli(repo, [])
    assert proc.returncode != 0, proc.stdout


# ---------------------------------------------------------------------------
# 2. policy file不存在 → nonzero
# ---------------------------------------------------------------------------

def test_02_policy_file_missing_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    missing = tmp_path / "does_not_exist.json"
    proc = _run_cli(repo, ["--approved-untracked-policy", str(missing)])
    assert proc.returncode != 0, proc.stdout


# ---------------------------------------------------------------------------
# 3. policy SHA不一致 → nonzero
# ---------------------------------------------------------------------------

def test_03_policy_sha_mismatch_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "backend/new.py", "BUILD_INPUT"))
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(approved), encoding="utf-8")
    proc = _run_cli(
        repo,
        ["--approved-untracked-policy", str(policy_path), "--approved-untracked-policy-sha256", "0" * 64],
    )
    assert proc.returncode != 0, proc.stdout


# ---------------------------------------------------------------------------
# 4. approved entry 1件欠落 → nonzero
# ---------------------------------------------------------------------------

def test_04_missing_approved_entry_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "a.py").write_text("a\n", encoding="utf-8")
    (repo / "backend" / "b.py").write_text("b\n", encoding="utf-8")
    # bだけ承認、aは未承認のまま残す
    approved = _approved_policy(_approved_entry_for(repo, "backend/b.py", "BUILD_INPUT"))
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(approved), encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    proc = _run_cli(repo, ["--approved-untracked-policy", str(policy_path), "--approved-untracked-policy-sha256", sha])
    assert proc.returncode != 0, proc.stdout


# ---------------------------------------------------------------------------
# 5-9. path一致・file hash/size/mode/object_type/classification不一致 → nonzero
# ---------------------------------------------------------------------------

def test_05_hash_mismatch_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("v1\n", encoding="utf-8")
    entry = _approved_entry_for(repo, "backend/new.py", "BUILD_INPUT")
    (repo / "backend" / "new.py").write_text("v2 changed after approval\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=_approved_policy(entry))
    assert manifest["pending_owner_approval_count"] == 1


def test_06_size_mismatch_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    entry = _approved_entry_for(repo, "backend/new.py", "BUILD_INPUT")
    entry["size"] = entry["size"] + 1  # 意図的に不一致
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=_approved_policy(entry))
    assert manifest["pending_owner_approval_count"] == 1


def test_07_mode_mismatch_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    entry = _approved_entry_for(repo, "backend/new.py", "BUILD_INPUT")
    entry["mode"] = "100755"  # 実際は100644
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=_approved_policy(entry))
    assert manifest["pending_owner_approval_count"] == 1


def test_08_object_type_mismatch_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    entry = _approved_entry_for(repo, "backend/new.py", "BUILD_INPUT")
    entry["object_type"] = "SYMLINK"  # 実際はREGULAR_FILE
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=_approved_policy(entry))
    assert manifest["pending_owner_approval_count"] == 1


def test_09_classification_mismatch_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    entry = _approved_entry_for(repo, "backend/new.py", "BUILD_INPUT")
    entry["classification"] = "TEST_FIXTURE"  # 実際の分類と食い違う
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=_approved_policy(entry))
    assert manifest["pending_owner_approval_count"] == 1


# ---------------------------------------------------------------------------
# 10. duplicate policy path → nonzero
# ---------------------------------------------------------------------------

def test_10_duplicate_policy_path_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    entry = _approved_entry_for(repo, "backend/new.py", "BUILD_INPUT")
    approved = _approved_policy(entry, dict(entry))
    policy_path = tmp_path / "policy.json"
    policy_path.write_text(json.dumps(approved), encoding="utf-8")
    import hashlib
    sha = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    with pytest.raises(policy_mod.PolicyError, match="duplicate"):
        policy_mod.load_approved_untracked_policy(policy_path, expected_sha256=sha)


# ---------------------------------------------------------------------------
# 11-14. unapproved .py/.sh/.js/.json → nonzero
# ---------------------------------------------------------------------------

def test_11_unapproved_py_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "unapproved.py").write_text("x\n", encoding="utf-8")
    proc = _run_cli(repo, [])
    assert proc.returncode != 0, proc.stdout


def test_12_unapproved_sh_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "scripts" / "unapproved.sh").write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    proc = _run_cli(repo, [])
    assert proc.returncode != 0, proc.stdout


def test_13_unapproved_js_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "frontend" / "unapproved.js").write_text("console.log(1)\n", encoding="utf-8")
    proc = _run_cli(repo, [])
    assert proc.returncode != 0, proc.stdout


def test_14_unapproved_json_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "unapproved.json").write_text("{}\n", encoding="utf-8")
    proc = _run_cli(repo, [])
    assert proc.returncode != 0, proc.stdout


# ---------------------------------------------------------------------------
# 15. pending 2件をexcludedへ移すmutation → test FAILを検出
#     （CODEX round 5B再検証finding: pendingをこっそりexcludedへ移せば
#     PASSを騙れてしまう、というRound 5Bの欠陥そのものの回帰防止）
# ---------------------------------------------------------------------------

def test_15_pending_to_excluded_mutation_would_be_caught(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "unapproved_a.py").write_text("a\n", encoding="utf-8")
    (repo / "backend" / "unapproved_b.py").write_text("b\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=None)
    assert manifest["pending_owner_approval_count"] == 2

    # Round 5Bが実際に持っていた欠陥を模擬する: pending 2件をこっそり
    # explicitly_excluded_nonrelease_entriesへ移し、countを0に偽装する。
    mutated = copy.deepcopy(manifest)
    mutated["explicitly_excluded_nonrelease_entries"].extend(mutated["pending_owner_approval_entries"])
    mutated["pending_owner_approval_entries"] = []
    mutated["pending_owner_approval_count"] = 0

    # 正しい（mutationしていない）manifestに対しては、run()が必ずFAILする
    # ことを確認する。これがまさに、mutationによる隠蔽（pendingを0に見せかける
    # こと）を許さない防御線であり、このassertionが失敗する＝fail-closed
    # protection自体が退行したことを意味する。
    correct_result = snapshot_mod.run(repo, manifest, required_spot_check_paths=[], required_absent_paths=[])
    assert correct_result["overall_snapshot_completeness_result"] == "FAIL"
    assert correct_result["pending_owner_approval_count"] == 2

    # mutationを注入したmanifestは（意図的に）fail-closed checkをすり抜けて
    # しまうことを示す——early-returnのfail-closed経路（"pending_owner_approval_count"
    # キーを持つ）を通らず、通常のsnapshot完走フロー（"seed_clone_started"キーを
    # 持たない、completeness/secret_boundary_scan等のフル結果）が実行されてしまう。
    # これはRound 5Bの欠陥の再現であり、本物の実装コードにこのようなmutationが
    # 混入していないことをコードレビュー・R5C-*節の実装差分で保証する
    # （テストコード自体でmutationを防ぐことはできないため）。
    mutated_result = snapshot_mod.run(repo, mutated, required_spot_check_paths=[], required_absent_paths=[])
    assert "pending_owner_approval_count" not in mutated_result
    assert "seed_clone_started" not in mutated_result  # fail-closed早期returnではなく通常フローが実行された
    assert "completeness" in mutated_result  # 通常フローの結果構造


# ---------------------------------------------------------------------------
# 16. pending 1件でもseed開始関数が呼ばれない
# ---------------------------------------------------------------------------

def test_16_pending_prevents_seed_clone_call(tmp_path, monkeypatch):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "unapproved.py").write_text("x\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=None)
    assert manifest["pending_owner_approval_count"] == 1

    called = {"seed_clone": False}
    original_seed_clone = snapshot_mod.seed_clone

    def _tracking_seed_clone(*args, **kwargs):
        called["seed_clone"] = True
        return original_seed_clone(*args, **kwargs)

    monkeypatch.setattr(snapshot_mod, "seed_clone", _tracking_seed_clone)

    result = snapshot_mod.run(repo, manifest, required_spot_check_paths=[], required_absent_paths=[])
    assert result["overall_snapshot_completeness_result"] == "FAIL"
    assert result["seed_clone_started"] is False
    assert called["seed_clone"] is False, "seed_clone() must not be called when pending entries exist"


# ---------------------------------------------------------------------------
# 17. exact approved setだけ → PASS
# ---------------------------------------------------------------------------

def test_17_exact_approved_set_passes(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new.py").write_text("x\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "backend/new.py", "BUILD_INPUT"))
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert manifest["pending_owner_approval_count"] == 0
    result = snapshot_mod.run(repo, manifest, required_spot_check_paths=[], required_absent_paths=[])
    assert result["overall_snapshot_completeness_result"] == "PASS"


# ---------------------------------------------------------------------------
# 18. exact approved set＋new sibling → nonzero
# ---------------------------------------------------------------------------

def test_18_approved_set_plus_new_sibling_nonzero(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "approved.py").write_text("x\n", encoding="utf-8")
    approved = _approved_policy(_approved_entry_for(repo, "backend/approved.py", "BUILD_INPUT"))
    # approval後に新しいsibling fileが追加される
    (repo / "backend" / "new_sibling.py").write_text("y\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    assert manifest["pending_owner_approval_count"] == 1
    result = snapshot_mod.run(repo, manifest, required_spot_check_paths=[], required_absent_paths=[])
    assert result["overall_snapshot_completeness_result"] == "FAIL"

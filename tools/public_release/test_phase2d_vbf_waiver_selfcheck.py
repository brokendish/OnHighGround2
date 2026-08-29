"""
test_phase2d_vbf_waiver_selfcheck.py — VBF ABSOLUTE_USER_PATH waiverの
negative control（Phase 2-D Round 5A、指示書第6節、15項目）。

「absolute path waiverがあるfileだから安全」とまとめて判定しないこと——
exact occurrence一致だけを抑制し、1 byteでも変化したfileのwaiverは全失効する
ことを検証する。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_vbf_waiver_selfcheck.py -v
"""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_typed_boundary_scan as scanner  # noqa: E402
import phase2d_vbf_waiver as waiver_mod  # noqa: E402


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@local.invalid")
    _git(repo, "config", "user.name", "Fixture")
    (repo / "fixtures").mkdir()
    return repo


def _commit_all(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "content")


def _base_setup(tmp_path: Path):
    repo = _init_repo(tmp_path)
    target = repo / "fixtures" / "artifact.txt"
    target.write_text("/Users/someone/project/venv/bin/python\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    waiver = waiver_mod.generate_candidate_vbf_waiver(repo, findings["ABSOLUTE_USER_PATH"])
    return repo, target, findings, waiver


# ---------------------------------------------------------------------------
# 1. exact approved absolute-path occurrenceだけ抑制
# ---------------------------------------------------------------------------

def test_01_exact_occurrence_suppressed(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings, waiver, None, repo)
    assert len(suppressed) == 1
    assert result["ABSOLUTE_USER_PATH"] == []


# ---------------------------------------------------------------------------
# 2. sibling fileのabsolute pathはFAIL
# ---------------------------------------------------------------------------

def test_02_sibling_file_not_covered(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    (repo / "fixtures" / "sibling.txt").write_text("/Users/someone/other/path\n", encoding="utf-8")
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert len(suppressed) == 1  # 元のartifact.txtのoccurrenceだけ
    remaining_paths = {f["path"] for f in result["ABSOLUTE_USER_PATH"]}
    assert "fixtures/sibling.txt" in remaining_paths


# ---------------------------------------------------------------------------
# 3. new occurrence追加でFAIL（そのfileのwaiverは失効、既存分も含め残る）
# ---------------------------------------------------------------------------

def test_03_new_occurrence_added_causes_full_fail(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    target.write_text(
        "/Users/someone/project/venv/bin/python\n/Users/someone/second/occurrence\n",
        encoding="utf-8",
    )
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert suppressed == []
    assert len(result["ABSOLUTE_USER_PATH"]) == 2


# ---------------------------------------------------------------------------
# 4. occurrence削除でもpolicy mismatchとしてFAIL
# ---------------------------------------------------------------------------

def test_04_occurrence_removed_causes_fail(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "fixtures" / "artifact.txt"
    target.write_text("/Users/a/one\n/Users/a/two\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    waiver = waiver_mod.generate_candidate_vbf_waiver(repo, findings["ABSOLUTE_USER_PATH"])

    target.write_text("/Users/a/one\n", encoding="utf-8")  # 2つ目のoccurrenceを削除
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert suppressed == []  # file hashが変わっているのでwaiver失効
    assert len(result["ABSOLUTE_USER_PATH"]) == 1


# ---------------------------------------------------------------------------
# 5. file hash変更でFAIL
# ---------------------------------------------------------------------------

def test_05_file_hash_changed_causes_fail(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    target.write_text("/Users/someone/project/venv/bin/python  # trailing comment\n", encoding="utf-8")
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert suppressed == []
    assert len(result["ABSOLUTE_USER_PATH"]) == 1


# ---------------------------------------------------------------------------
# 6. line移動でFAIL
# ---------------------------------------------------------------------------

def test_06_line_moved_causes_fail(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    target.write_text("\n/Users/someone/project/venv/bin/python\n", encoding="utf-8")  # 1行挿入して行がずれる
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert suppressed == []
    assert len(result["ABSOLUTE_USER_PATH"]) == 1


# ---------------------------------------------------------------------------
# 7-10. secret canary / private key / Authorization / Cookie追加でFAIL
#       （waiverが適用されてもABSOLUTE_USER_PATH以外は無関係にFAILし続ける）
# ---------------------------------------------------------------------------

def test_07_secret_canary_added_still_fails(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    (repo / "fixtures" / "secret.py").write_text('REAL_API_SECRET = "aReal12345RandomLookingValue"\n', encoding="utf-8")
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert len(result["SECRET_VALUE"]) == 1


def test_08_private_key_added_still_fails(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    (repo / "fixtures" / "key.pem").write_text("-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----\n", encoding="utf-8")
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert len(result["PRIVATE_KEY"]) == 1


def test_09_authorization_added_still_fails(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    (repo / "fixtures" / "req.txt").write_text("Authorization: Bearer sk-real-token-value\n", encoding="utf-8")
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert len(result["AUTHORIZATION_VALUE"]) == 1


def test_10_cookie_added_still_fails(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    (repo / "fixtures" / "req.txt").write_text("Cookie: session=realvalue123\n", encoding="utf-8")
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert len(result["COOKIE_VALUE"]) == 1


# ---------------------------------------------------------------------------
# 11-12. external symlink / cache追加でFAIL
# ---------------------------------------------------------------------------

def test_11_external_symlink_added_still_fails(tmp_path):
    import os
    repo, target, findings, waiver = _base_setup(tmp_path)
    os.symlink("/etc/passwd", repo / "fixtures" / "escape_link")
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert len(result["EXTERNAL_SYMLINK"]) == 1


def test_12_cache_dir_added_still_fails(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    (repo / "fixtures" / "test-results").mkdir()
    (repo / "fixtures" / "test-results" / "t.txt").write_text("x\n", encoding="utf-8")
    _commit_all(repo)
    findings2 = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings2, waiver, None, repo)
    assert len(result["CACHE_OR_TEST_RESULT"]) == 1


# ---------------------------------------------------------------------------
# 13. finding type偽装でFAIL
# ---------------------------------------------------------------------------

def test_13_finding_type_spoofing_rejected(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    spoofed = copy.deepcopy(waiver)
    spoofed["finding_type"] = "SECRET_VALUE"
    with pytest.raises(waiver_mod.VbfWaiverError, match="finding_type"):
        waiver_mod.apply_vbf_waiver(findings, spoofed, None, repo)


# ---------------------------------------------------------------------------
# 14. policy schema不正でFAIL
# ---------------------------------------------------------------------------

def test_14_malformed_schema_rejected(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    policy_path = tmp_path / "bad.json"
    policy_path.write_text(json.dumps({"schema_version": 1, "finding_type": "ABSOLUTE_USER_PATH"}), encoding="utf-8")
    with pytest.raises(waiver_mod.VbfWaiverError, match="files"):
        waiver_mod.load_approved_vbf_waiver(policy_path)


def test_14b_occurrence_count_mismatch_rejected(tmp_path):
    policy_path = tmp_path / "bad2.json"
    policy_path.write_text(
        json.dumps(
            {
                "schema_version": 1, "finding_type": "ABSOLUTE_USER_PATH",
                "files": [{"path": "x.txt", "file_sha256": "0" * 64, "occurrence_count": 2, "occurrences": []}],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(waiver_mod.VbfWaiverError, match="occurrence_count mismatch"):
        waiver_mod.load_approved_vbf_waiver(policy_path)


# ---------------------------------------------------------------------------
# 15. policy hash不一致でFAIL
# ---------------------------------------------------------------------------

def test_15_policy_hash_mismatch_rejected(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    policy_path = tmp_path / "waiver.json"
    waiver_mod.write_candidate_waiver(waiver, policy_path)
    with pytest.raises(waiver_mod.VbfWaiverError, match="SHA-256 mismatch"):
        waiver_mod.load_approved_vbf_waiver(policy_path, expected_sha256="0" * 64)


def test_15b_policy_hash_match_succeeds(tmp_path):
    repo, target, findings, waiver = _base_setup(tmp_path)
    policy_path = tmp_path / "waiver.json"
    actual_sha = waiver_mod.write_candidate_waiver(waiver, policy_path)
    loaded = waiver_mod.load_approved_vbf_waiver(policy_path, expected_sha256=actual_sha)
    assert loaded["finding_type"] == "ABSOLUTE_USER_PATH"

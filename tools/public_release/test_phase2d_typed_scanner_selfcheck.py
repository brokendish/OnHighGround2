"""
test_phase2d_typed_scanner_selfcheck.py — finding type別boundary scannerの
unit / negative control（Phase 2-D Round 5A、指示書第5.2節・第8章）。

各finding typeが独立して検出され、他の種別と混線しないこと、また
VBF waiverが`ABSOLUTE_USER_PATH`以外へ絶対に波及しないことを検証する。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_typed_scanner_selfcheck.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

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
    (repo / "backend").mkdir()
    return repo


def _commit_all(repo: Path) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "content")


# ---------------------------------------------------------------------------
# 各finding typeの独立検出
# ---------------------------------------------------------------------------

def test_01_secret_value_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend" / "config.py").write_text('MY_API_SECRET = "aReal12345RandomLookingValue"\n', encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["SECRET_VALUE"]) == 1
    assert findings["SECRET_VALUE"][0]["line_number"] == 1
    assert all(len(v) == 0 for k, v in findings.items() if k != "SECRET_VALUE")


def test_02_private_key_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend" / "key.pem").write_text("-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["PRIVATE_KEY"]) == 1


def test_03_authorization_value_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend" / "req.txt").write_text("Authorization: Bearer sk-real-looking-token-value-123\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["AUTHORIZATION_VALUE"]) == 1
    assert len(findings["COOKIE_VALUE"]) == 0


def test_04_cookie_value_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend" / "req.txt").write_text("Cookie: session=abcdef123456realvalue\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["COOKIE_VALUE"]) == 1
    assert len(findings["AUTHORIZATION_VALUE"]) == 0


def test_05_prohibited_file_env_operator_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend" / ".env.operator").write_text("OPERATOR_AUTH_SECRET=x\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["PROHIBITED_FILE"]) == 1


def test_06_external_symlink_detected(tmp_path):
    import os
    repo = _init_repo(tmp_path)
    (repo / "backend" / "in_repo.py").write_text("x\n", encoding="utf-8")
    os.symlink("/etc/passwd", repo / "backend" / "escape_link.py")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["EXTERNAL_SYMLINK"]) == 1


def test_07_cache_or_test_result_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend" / "test-results").mkdir()
    (repo / "backend" / "test-results" / "trace.txt").write_text("x\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["CACHE_OR_TEST_RESULT"]) == 1


def test_08_absolute_user_path_detected(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend" / "recorded.txt").write_text("/Users/someone/project/venv/bin/python\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["ABSOLUTE_USER_PATH"]) == 1
    finding = findings["ABSOLUTE_USER_PATH"][0]
    assert finding["line_number"] == 1
    assert finding["column_start"] == 1


# ---------------------------------------------------------------------------
# 型の混線がないこと（VBF policyがABSOLUTE_USER_PATH以外へ波及しない）
# ---------------------------------------------------------------------------

def test_09_vbf_waiver_never_suppresses_secret_value(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "backend" / "mixed.py"
    target.write_text(
        '# /Users/someone/project reference\nMY_API_SECRET = "aReal12345RandomLookingValue"\n',
        encoding="utf-8",
    )
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    assert len(findings["ABSOLUTE_USER_PATH"]) == 1
    assert len(findings["SECRET_VALUE"]) == 1

    # このfileのABSOLUTE_USER_PATH occurrenceだけをwaiverで承認する
    candidate = waiver_mod.generate_candidate_vbf_waiver(repo, findings["ABSOLUTE_USER_PATH"])
    result, suppressed = waiver_mod.apply_vbf_waiver(findings, candidate, None, repo)

    assert len(suppressed) == 1
    assert result["ABSOLUTE_USER_PATH"] == []
    # SECRET_VALUEはwaiverの影響を一切受けず残る（指示書第5.5節）
    assert len(result["SECRET_VALUE"]) == 1


def test_10_vbf_waiver_never_suppresses_private_key(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "backend" / "mixed.pem"
    target.write_text(
        "# /Users/someone/project\n-----BEGIN RSA PRIVATE KEY-----\nMIIB\n-----END RSA PRIVATE KEY-----\n",
        encoding="utf-8",
    )
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    candidate = waiver_mod.generate_candidate_vbf_waiver(repo, findings["ABSOLUTE_USER_PATH"])
    result, suppressed = waiver_mod.apply_vbf_waiver(findings, candidate, None, repo)
    assert result["ABSOLUTE_USER_PATH"] == []
    assert len(result["PRIVATE_KEY"]) == 1


def test_11_vbf_waiver_never_suppresses_authorization(tmp_path):
    repo = _init_repo(tmp_path)
    target = repo / "backend" / "mixed.txt"
    target.write_text(
        "/Users/someone/project\nAuthorization: Bearer sk-real-looking-token-value-123\n",
        encoding="utf-8",
    )
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    candidate = waiver_mod.generate_candidate_vbf_waiver(repo, findings["ABSOLUTE_USER_PATH"])
    result, suppressed = waiver_mod.apply_vbf_waiver(findings, candidate, None, repo)
    assert result["ABSOLUTE_USER_PATH"] == []
    assert len(result["AUTHORIZATION_VALUE"]) == 1


def test_12_no_waiver_when_approved_is_none(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "backend" / "recorded.txt").write_text("/Users/someone/project\n", encoding="utf-8")
    _commit_all(repo)
    findings = scanner.scan_typed(repo)
    result, suppressed = waiver_mod.apply_vbf_waiver(findings, None, None, repo)
    assert suppressed == []
    assert len(result["ABSOLUTE_USER_PATH"]) == 1

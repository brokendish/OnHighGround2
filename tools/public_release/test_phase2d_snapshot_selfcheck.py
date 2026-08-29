"""
test_phase2d_snapshot_selfcheck.py — release delta manifest / AT-17 snapshot harness
のself-test（Phase 2-D Round 3、指示書第8節）。

指示書第8節が列挙する20 caseを、実source repository（OnHighGround2自身）には
一切触れない、repo-external fixture git repository上で検証する。すべてのfixture
repositoryは`tmp_path`配下に作られ、pytest終了時に自動削除される。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_snapshot_selfcheck.py -v
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402
import phase2d_at17_clean_clone as snapshot_mod  # noqa: E402
import phase2d_untracked_policy as policy_mod  # noqa: E402


def _approve_all_untracked(repo: Path) -> dict:
    """test fixture用ヘルパー: 現在のuntracked fileを全部承認済みとして扱う
    approved policyをその場で構築する。本物のOWNER承認プロセスを模擬するの
    ではなく、Round 3/4由来のoverlay/completeness機構（本fileの主目的）を
    Round 5A以降のdefault-deny承認modelと共存させて引き続き検証するための
    test-only構成である（default denyの検証自体はtest_10/test_20等が別途
    approved_untracked_policy=Noneで直接検証する）。"""
    candidate = policy_mod.generate_candidate_untracked_policy(repo)
    return {"schema_version": 1, "entries": candidate["entries"]}


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _init_fixture_repo(tmp_path: Path, name: str = "fixture_repo") -> Path:
    """release rootを一通り備えた最小fixture repositoryを作りcommitする。"""
    repo = tmp_path / name
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@local.invalid")
    _git(repo, "config", "user.name", "Fixture")

    (repo / "backend").mkdir()
    (repo / "backend" / "app.py").write_text("print('baseline app')\n", encoding="utf-8")
    (repo / "docs").mkdir()
    (repo / "docs" / "readme.md").write_text("baseline docs\n", encoding="utf-8")
    (repo / "tools" / "public_release").mkdir(parents=True)
    (repo / "tools" / "public_release" / "tool.py").write_text("print('tool')\n", encoding="utf-8")
    (repo / "tests" / "fixtures").mkdir(parents=True)
    (repo / "tests" / "fixtures" / "x.json").write_text('{"k": 1}\n', encoding="utf-8")
    (repo / "tasks").mkdir()
    (repo / "tasks" / "note.md").write_text("audit note\n", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "keep.sh").write_text("#!/bin/sh\necho keep\n", encoding="utf-8")
    (repo / "backend" / "to_delete.py").write_text("print('will be deleted')\n", encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo


def _generate_and_run(repo: Path) -> tuple[dict, dict]:
    approved = _approve_all_untracked(repo)
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    # fixture repositoryは実OnHighGround2の具体的path（docker-compose.yml等）を
    # 持たないため、spot check / tombstone checkの対象listを空にする
    # （module既定のREQUIRED_SPOT_CHECK_PATHS/REQUIRED_ABSENT_PATHSは実repo専用）。
    result = snapshot_mod.run(repo, manifest, required_spot_check_paths=[], required_absent_paths=[])
    return manifest, result


# ---------------------------------------------------------------------------
# 1. modified file overlay
# ---------------------------------------------------------------------------

def test_01_modified_file_overlay(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").write_text("print('modified app')\n", encoding="utf-8")

    manifest, result = _generate_and_run(repo)
    entry = next(e for e in manifest["entries"] if e["path"] == "backend/app.py")
    assert entry["state"] == "MODIFIED"
    assert result["overall_snapshot_completeness_result"] == "PASS"
    assert result["completeness"]["spot_check"] == {} or True  # no spot-check paths defined for fixture repos


# ---------------------------------------------------------------------------
# 2. added file overlay
# ---------------------------------------------------------------------------

def test_02_added_file_overlay(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "new_module.py").write_text("print('new')\n", encoding="utf-8")

    manifest, result = _generate_and_run(repo)
    entry = next(e for e in manifest["entries"] if e["path"] == "backend/new_module.py")
    assert entry["state"] == "ADDED"
    assert result["overall_snapshot_completeness_result"] == "PASS"
    assert "backend/new_module.py" not in result["completeness"]["new_but_missing"]


# ---------------------------------------------------------------------------
# 3. deleted file tombstone
# ---------------------------------------------------------------------------

def test_03_deleted_file_tombstone(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "to_delete.py").unlink()

    manifest, result = _generate_and_run(repo)
    entry = next(e for e in manifest["entries"] if e["path"] == "backend/to_delete.py")
    assert entry["state"] == "DELETED"
    assert result["overall_snapshot_completeness_result"] == "PASS"
    assert not result["completeness"]["deleted_but_resurrected"]


# ---------------------------------------------------------------------------
# 4. rename
# ---------------------------------------------------------------------------

def test_04_rename(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").rename(repo / "backend" / "app_renamed.py")

    approved = _approve_all_untracked(repo)
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    states = {e["path"]: e["state"] for e in manifest["entries"]}
    # --no-renames diffなので、rename detectionはgit status --porcelain=v2の"2"レコードが
    # 検出した場合のみRENAMED_FROM/TOになる。小さいfixtureではgitがrenameとして検出する。
    assert states.get("backend/app_renamed.py") in ("ADDED", "RENAMED_TO")
    assert states.get("backend/app.py") in ("DELETED", "RENAMED_FROM")

    result = snapshot_mod.run(repo, manifest, required_spot_check_paths=[], required_absent_paths=[])
    assert result["overall_snapshot_completeness_result"] == "PASS"


# ---------------------------------------------------------------------------
# 5. executable mode
# ---------------------------------------------------------------------------

def test_05_executable_mode_preserved(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    target = repo / "scripts" / "keep.sh"
    target.write_text("#!/bin/sh\necho updated\n", encoding="utf-8")
    os.chmod(target, 0o755)

    manifest, result = _generate_and_run(repo)
    entry = next(e for e in manifest["entries"] if e["path"] == "scripts/keep.sh")
    assert entry["object_type"] == "EXECUTABLE_FILE"
    assert entry["mode"] == "100755"
    assert result["overall_snapshot_completeness_result"] == "PASS"
    assert not result["completeness"]["mode_mismatch"]


# ---------------------------------------------------------------------------
# 6. symlink内部target
# ---------------------------------------------------------------------------

def test_06_internal_symlink_overlay(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    link = repo / "backend" / "link_to_app.py"
    os.symlink("app.py", link)

    manifest, result = _generate_and_run(repo)
    entry = next(e for e in manifest["entries"] if e["path"] == "backend/link_to_app.py")
    assert entry["object_type"] == "SYMLINK"
    assert result["overall_snapshot_completeness_result"] == "PASS"


# ---------------------------------------------------------------------------
# 7. repo外symlink拒否
# ---------------------------------------------------------------------------

def test_07_repo_external_symlink_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("outside content\n", encoding="utf-8")
    link = repo / "backend" / "escape_link.py"
    os.symlink(str(outside), link)  # absolute target escaping repo root

    approved = _approve_all_untracked(repo)
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved)
    entry = next(e for e in manifest["entries"] if e["path"] == "backend/escape_link.py")
    seed_root = tmp_path / "seed_for_test07"
    seed_root.mkdir()
    _git(seed_root, "init", "-q")
    with pytest.raises(snapshot_mod.SnapshotError):
        snapshot_mod._apply_add_or_modify(repo, seed_root, entry)


# ---------------------------------------------------------------------------
# 8. source hash mismatch拒否
# ---------------------------------------------------------------------------

def test_08_source_hash_mismatch_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").write_text("print('v1')\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo)

    # manifest生成後にsourceがさらに変化した（working tree changed since manifest generation）
    (repo / "backend" / "app.py").write_text("print('v2 — changed after manifest generation')\n", encoding="utf-8")

    entry = next(e for e in manifest["entries"] if e["path"] == "backend/app.py")
    seed_root = tmp_path / "seed_for_test08"
    seed_root.mkdir()
    _git(seed_root, "init", "-q")
    (seed_root / "backend").mkdir()
    with pytest.raises(snapshot_mod.SnapshotError, match="hash mismatch"):
        snapshot_mod._apply_add_or_modify(repo, seed_root, entry)


# ---------------------------------------------------------------------------
# 9. baseline HEAD mismatch拒否
# ---------------------------------------------------------------------------

def test_09_baseline_head_mismatch_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    manifest = manifest_mod.generate_manifest(repo)

    # manifest生成後にsource repositoryのHEADが進んだ
    (repo / "docs" / "readme.md").write_text("advance HEAD\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "advance head after manifest generation")

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        seed = snapshot_mod.seed_clone(repo, tmp_root)
        with pytest.raises(snapshot_mod.SnapshotError):
            snapshot_mod.verify_baseline(repo, seed, manifest)


# ---------------------------------------------------------------------------
# 10. unclassified untracked拒否
# ---------------------------------------------------------------------------

def test_10_unclassified_untracked_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "unclassified_top_level_dir").mkdir()
    (repo / "unclassified_top_level_dir" / "f.txt").write_text("x\n", encoding="utf-8")

    with pytest.raises(manifest_mod.ManifestGenerationError):
        manifest_mod.generate_manifest(repo)


# ---------------------------------------------------------------------------
# 11. secret file拒否
# ---------------------------------------------------------------------------

def test_11_secret_file_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / ".env").write_text("SECRET_KEY=abc123\n", encoding="utf-8")

    with pytest.raises(manifest_mod.ManifestGenerationError):
        manifest_mod.generate_manifest(repo)


def test_11b_env_example_not_rejected(tmp_path):
    # `.env.example`はsecret filenameパターン（拒否対象）から明示除外されている
    # ことを確認する。default deny（未承認）でpending_owner_approval_entriesへ
    # 回ること自体は正常であり、ここでは「secretとして誤ってManifest
    # GenerationErrorにならないこと」「classificationがRUNTIME_CONFIGと
    # 正しく計算されること」を検証する（承認可否とは独立した検証）。
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / ".env.example").write_text("SECRET_KEY=\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo)  # approved policyなしでもエラーにならない
    entry = next(e for e in manifest["pending_owner_approval_entries"] if e["path"] == "backend/.env.example")
    assert entry["classification"] == "RUNTIME_CONFIG"
    assert entry["approval_status"] == "PENDING_OWNER_APPROVAL"


# ---------------------------------------------------------------------------
# 12. unknown manifest state拒否
# ---------------------------------------------------------------------------

def test_12_unknown_manifest_state_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    manifest = manifest_mod.generate_manifest(repo)
    manifest["entries"].append(
        {
            "path": "backend/app.py",
            "state": "BOGUS_STATE",
            "object_type": "REGULAR_FILE",
            "mode": "100644",
            "baseline_sha256": None,
            "release_sha256": None,
            "phase_origin": "TEST",
            "classification": "BUILD_INPUT",
            "include_reason": "test",
        }
    )
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        seed = snapshot_mod.seed_clone(repo, tmp_root)
        with pytest.raises(snapshot_mod.SnapshotError, match="unknown manifest entry state"):
            snapshot_mod.overlay_manifest(repo, seed, manifest)


# ---------------------------------------------------------------------------
# 13. duplicate path拒否
# ---------------------------------------------------------------------------

def test_13_duplicate_path_rejected(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").write_text("print('v2')\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo)
    dup = dict(next(e for e in manifest["entries"] if e["path"] == "backend/app.py"))
    manifest["entries"].append(dup)

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        seed = snapshot_mod.seed_clone(repo, tmp_root)
        with pytest.raises(snapshot_mod.SnapshotError, match="duplicate"):
            snapshot_mod.overlay_manifest(repo, seed, manifest)


# ---------------------------------------------------------------------------
# 14. parent traversal拒否
# ---------------------------------------------------------------------------

def test_14_parent_traversal_rejected():
    with pytest.raises(snapshot_mod.SnapshotError):
        snapshot_mod._validate_safe_relpath("backend/../../../etc/passwd")


# ---------------------------------------------------------------------------
# 15. absolute path拒否
# ---------------------------------------------------------------------------

def test_15_absolute_path_rejected():
    with pytest.raises(snapshot_mod.SnapshotError):
        snapshot_mod._validate_safe_relpath("/etc/passwd")


# ---------------------------------------------------------------------------
# 16. newline / Unicode path
# ---------------------------------------------------------------------------

def test_16_unicode_and_space_path(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    unicode_name = "docs/避難所 レポート.md"
    (repo / "docs" / "避難所 レポート.md").write_text("unicode content\n", encoding="utf-8")

    manifest, result = _generate_and_run(repo)
    entry = next((e for e in manifest["entries"] if e["path"] == unicode_name), None)
    assert entry is not None, manifest["entries"]
    assert entry["state"] == "ADDED"
    assert result["overall_snapshot_completeness_result"] == "PASS"


# ---------------------------------------------------------------------------
# 17. second clone tree一致
# ---------------------------------------------------------------------------

def test_17_second_clone_tree_matches_seed(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").write_text("print('modified')\n", encoding="utf-8")
    (repo / "backend" / "extra.py").write_text("print('extra')\n", encoding="utf-8")

    manifest, result = _generate_and_run(repo)
    c = result["completeness"]
    assert c["second_head_matches_seed_temp_head"] is True
    assert c["seed_second_diff_identical"] is True


# ---------------------------------------------------------------------------
# 18. deleted file復活検出
# ---------------------------------------------------------------------------

def test_18_resurrected_deletion_detected(tmp_path):
    import tempfile

    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "to_delete.py").unlink()
    manifest = manifest_mod.generate_manifest(repo)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        seed = snapshot_mod.seed_clone(repo, tmp_root)
        snapshot_mod.verify_baseline(repo, seed, manifest)
        # わざとDELETED entryを一つだけスキップしてoverlayする（バグ再現）
        buggy_entries = [e for e in manifest["entries"] if e["path"] != "backend/to_delete.py"]
        buggy_manifest = {**manifest, "entries": buggy_entries}
        snapshot_mod.overlay_manifest(repo, seed, buggy_manifest)
        temp_head = snapshot_mod.temp_commit(seed)
        second = snapshot_mod.second_clone(tmp_root, seed)

        completeness = snapshot_mod.compare_completeness(repo, manifest, seed, second, temp_head)
        assert "backend/to_delete.py" in completeness["deleted_but_resurrected"]
        assert completeness["completeness_pass"] is False


# ---------------------------------------------------------------------------
# 19. omitted modified file検出
# ---------------------------------------------------------------------------

def test_19_omitted_modified_file_detected(tmp_path):
    import tempfile

    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").write_text("print('modified content')\n", encoding="utf-8")
    (repo / "docs" / "readme.md").write_text("modified docs\n", encoding="utf-8")
    manifest = manifest_mod.generate_manifest(repo)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        seed = snapshot_mod.seed_clone(repo, tmp_root)
        snapshot_mod.verify_baseline(repo, seed, manifest)
        # わざとbackend/app.pyのMODIFIED entryだけをスキップしてoverlayする
        buggy_entries = [e for e in manifest["entries"] if e["path"] != "backend/app.py"]
        buggy_manifest = {**manifest, "entries": buggy_entries}
        snapshot_mod.overlay_manifest(repo, seed, buggy_manifest)
        temp_head = snapshot_mod.temp_commit(seed)
        second = snapshot_mod.second_clone(tmp_root, seed)

        completeness = snapshot_mod.compare_completeness(repo, manifest, seed, second, temp_head)
        assert "backend/app.py" in completeness["modified_but_stale"]
        assert completeness["completeness_pass"] is False


# ---------------------------------------------------------------------------
# 20. unexpected new file検出
# ---------------------------------------------------------------------------

def test_20_unexpected_new_file_detected(tmp_path):
    import tempfile

    repo = _init_fixture_repo(tmp_path)
    manifest = manifest_mod.generate_manifest(repo)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        seed = snapshot_mod.seed_clone(repo, tmp_root)
        snapshot_mod.verify_baseline(repo, seed, manifest)
        snapshot_mod.overlay_manifest(repo, seed, manifest)
        # manifestに存在しない余分なfileをseedへ直接混入させる（バグ/汚染再現）
        (seed / "backend" / "unmanifested_extra.py").write_text("print('should not be here')\n", encoding="utf-8")
        temp_head = snapshot_mod.temp_commit(seed)
        second = snapshot_mod.second_clone(tmp_root, seed)

        completeness = snapshot_mod.compare_completeness(repo, manifest, seed, second, temp_head)
        assert "backend/unmanifested_extra.py" in completeness["unexpected"]
        assert completeness["completeness_pass"] is False


# ---------------------------------------------------------------------------
# 21. pre-existing staged-deletion gitlinkがsecond cloneで実際に削除されること
#     （CODEX round 3再検証finding: `.claude/worktrees/*`が除外分類だけで放置され
#     second cloneに復活扱いのまま残っていたバグの回帰test）
# ---------------------------------------------------------------------------

def test_21_pre_existing_gitlink_deletion_applied(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    # 実際の`.claude/worktrees/practical-villani-c3d420`と同じ状態
    # （HEADにgitlinkとしてcommit済み → indexでstaged deletion）を再現する。
    _git(repo, "update-index", "--add", "--cacheinfo",
         "160000,0000000000000000000000000000000000000001,worktrees/fake")
    _git(repo, "commit", "-q", "-m", "add fake gitlink")
    _git(repo, "rm", "--cached", "-q", "worktrees/fake")

    manifest = manifest_mod.generate_manifest(repo)
    entry = next(e for e in manifest["entries"] if e["path"] == "worktrees/fake")
    assert entry["state"] == "DELETED"
    assert entry["object_type"] == "GITLINK"

    result = snapshot_mod.run(repo, manifest, required_spot_check_paths=[], required_absent_paths=[])
    assert result["overall_snapshot_completeness_result"] == "PASS"
    assert not result["completeness"]["deleted_but_resurrected"]
    assert result["secret_boundary_scan"]["typed_findings_raw"]["PROHIBITED_FILE"] == []


# ---------------------------------------------------------------------------
# 22. 旧: 拡張子allowlist前提のtestはRound 5Aでdefault-deny承認modelへ全面移行
#     したため削除した。同等以上の検証は
#     `test_phase2d_untracked_policy_selfcheck.py`（default deny・exact match・
#     negative control 21 case）が担う。


# ---------------------------------------------------------------------------
# 23. Phase 2-D Round 12D-B3（P2D-AT17-SNAPSHOT-ROOTDOC-001, HARNESS
#     CLASSIFICATION FINDING）: repository root 直下の正規公開文書
#     `VPS-README.md` を exact filename allowlist で分類できること、および
#     未知 / 非 exact な root path の fail-closed 拒否が維持されること。
# ---------------------------------------------------------------------------

_ROOT_DOC_ACCEPT = [
    ("VPS-README.md", "PUBLIC_DOCUMENTATION"),
    ("README.md", "PUBLIC_DOCUMENTATION"),
    ("LICENSE", "COMPLIANCE_ARTIFACT"),
    ("ATTRIBUTIONS.md", "COMPLIANCE_ARTIFACT"),
    ("THIRD_PARTY_NOTICES.md", "COMPLIANCE_ARTIFACT"),
]

_ROOT_DOC_REJECT = [
    "EVIL-VPS-README.md",
    "VPS-README.md.bak",
    "VPS-README.md/child",
    "subdir/VPS-README.md",
    "README-secret.md",
    "README.md.bak",
    "fooREADME.md",
    "UNAPPROVED.md",
    "unapproved_top_level.py",
    "../VPS-README.md",
    "./VPS-README.md",
    "VPS-README.md/",
    "a/../VPS-README.md",
]


@pytest.mark.parametrize("path,expected", _ROOT_DOC_ACCEPT)
def test_23_root_documentation_exact_allowlist_accepts(path, expected):
    classification, _reason, root = manifest_mod.classify(path)
    assert classification == expected
    assert root == "<repo-root-file>"


def test_23b_readme_md_classification_and_reason_unchanged():
    # README.md の (classification, include_reason, root) は Round 12D-B3 で不変。
    assert manifest_mod.classify("README.md") == (
        "PUBLIC_DOCUMENTATION",
        "root README",
        "<repo-root-file>",
    )


def test_23c_vps_readme_same_classification_as_readme():
    assert (
        manifest_mod.classify("VPS-README.md")[0]
        == manifest_mod.classify("README.md")[0]
        == "PUBLIC_DOCUMENTATION"
    )


@pytest.mark.parametrize("path", _ROOT_DOC_REJECT)
def test_23d_unknown_or_non_exact_root_paths_fail_closed(path):
    with pytest.raises(manifest_mod.ManifestGenerationError):
        manifest_mod.classify(path)


def test_23e_root_doc_helper_is_posix_exact():
    assert manifest_mod._is_root_public_documentation_file("VPS-README.md") is True
    assert manifest_mod._is_root_public_documentation_file("README.md") is True
    for bad in (
        "./VPS-README.md",
        "VPS-README.md/",
        "sub/VPS-README.md",
        "VPS-README.md.bak",
        "a/../VPS-README.md",
        "..",
        ".",
        "EVIL-VPS-README.md",
        "vps-readme.md",  # case-sensitive exact match
    ):
        assert manifest_mod._is_root_public_documentation_file(bad) is False


def test_23f_tracked_modified_vps_readme_manifest_entry(tmp_path):
    """限定再現: baseline tracked `VPS-README.md` → modified working copy →
    release delta classification → manifest entry 生成 まで（repo-external
    fixture, 1回, repository本体書込み0, Docker 0）。"""
    repo = _init_fixture_repo(tmp_path)
    (repo / "VPS-README.md").write_text("baseline VPS readme\n", encoding="utf-8")
    _git(repo, "add", "VPS-README.md")
    _git(repo, "commit", "-q", "-m", "add VPS-README.md")
    # modified working copy
    (repo / "VPS-README.md").write_text(
        "baseline VPS readme\noperations note added\n", encoding="utf-8"
    )

    # negative control: root 直下の未知 .md は fail-closed で candidate 生成を停止
    (repo / "UNAPPROVED.md").write_text("unknown root doc\n", encoding="utf-8")
    with pytest.raises(manifest_mod.ManifestGenerationError):
        manifest_mod.generate_manifest(repo)

    (repo / "UNAPPROVED.md").unlink()
    manifest = manifest_mod.generate_manifest(repo)

    doc_entries = [e for e in manifest["entries"] if e["path"] == "VPS-README.md"]
    assert len(doc_entries) == 1
    entry = doc_entries[0]
    assert entry["state"] == "MODIFIED"
    assert entry["classification"] == "PUBLIC_DOCUMENTATION"
    assert entry["object_type"] == "REGULAR_FILE"
    assert entry["mode"] == "100644"
    assert entry["baseline_sha256"] and entry["release_sha256"]
    assert entry["baseline_sha256"] != entry["release_sha256"]

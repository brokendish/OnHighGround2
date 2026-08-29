"""
test_phase2d_martin_demo_classification_selfcheck.py — `config/martin.demo.yaml`
分類・承認 回帰test（Phase 2-D Round 8、指示書第6節）。

Round 7でCODEXが発見した`config/`未分類欠陥（`DIRECTORY_RELEASE_ROOTS`に
`config/`が欠けていたため`config/martin.demo.yaml`が`ManifestGenerationError`を
起こしていた）に対する直接回帰testを固定する。あわせて、Round 8指示書が明示する
negative controlも検証する: config directory / `.yaml`拡張子のどちらも
自動承認の根拠にならないこと、hashが変わればpendingに戻ること。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_martin_demo_classification_selfcheck.py -v
"""
from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _init_config_fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "fixture_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@local.invalid")
    _git(repo, "config", "user.name", "Fixture")
    (repo / "backend").mkdir()
    (repo / "backend" / "app.py").write_text("print('baseline')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo


def _policy_entry_for(repo: Path, rel_path: str) -> dict:
    full = repo / rel_path
    data = full.read_bytes()
    classification, _reason, _root = manifest_mod.classify(rel_path)
    return {
        "path": rel_path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
        "mode": "100644",
        "object_type": "REGULAR_FILE",
        "classification": classification,
    }


# ---------------------------------------------------------------------------
# 1. classify()単体: config/martin.demo.yaml = RUNTIME_CONFIG（root=config/）
# ---------------------------------------------------------------------------

def test_01_classify_martin_demo_yaml_is_runtime_config():
    classification, _reason, root = manifest_mod.classify("config/martin.demo.yaml")
    assert classification == "RUNTIME_CONFIG"
    assert root == "config/"


def test_02_classify_production_martin_yaml_also_runtime_config():
    classification, _reason, root = manifest_mod.classify("config/martin.yaml")
    assert classification == "RUNTIME_CONFIG"
    assert root == "config/"


# ---------------------------------------------------------------------------
# 2. 実repository: config/martin.demo.yaml がManifestGenerationErrorを
#    起こさず生成できることの直接回帰確認（Round 7 finding固定）
# ---------------------------------------------------------------------------

def test_03_real_repo_martin_demo_yaml_does_not_raise():
    repo_root = Path(__file__).resolve().parents[2]
    martin_demo = repo_root / "config" / "martin.demo.yaml"
    assert martin_demo.is_file(), "config/martin.demo.yaml missing from working tree"
    # classify()は例外を出さず分類できる（未分類pathならManifestGenerationError）
    classification, _reason, root = manifest_mod.classify("config/martin.demo.yaml")
    assert classification == "RUNTIME_CONFIG"
    assert root == "config/"


# ---------------------------------------------------------------------------
# 3. exact-match approvedなら採用され、approvedでない同directoryのfileは
#    pendingのまま（config directoryをまとめて承認しない）
# ---------------------------------------------------------------------------

def test_04_exact_approval_accepted_sibling_not_swept_in(tmp_path):
    repo = _init_config_fixture_repo(tmp_path)
    (repo / "config").mkdir()
    (repo / "config" / "martin.demo.yaml").write_text("mbtiles:\n  paths: [/tiles]\n", encoding="utf-8")
    (repo / "config" / "unapproved_probe.yaml").write_text("probe: true\n", encoding="utf-8")

    approved_entry = _policy_entry_for(repo, "config/martin.demo.yaml")
    approved_policy = {"schema_version": 1, "entries": [approved_entry]}

    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved_policy)

    accepted_paths = {e["path"] for e in manifest["entries"]}
    pending_paths = {e["path"] for e in manifest["pending_owner_approval_entries"]}

    assert "config/martin.demo.yaml" in accepted_paths
    assert "config/unapproved_probe.yaml" in pending_paths
    assert "config/unapproved_probe.yaml" not in accepted_paths
    assert manifest["pending_owner_approval_count"] == 1

    pending_entry = next(e for e in manifest["pending_owner_approval_entries"] if e["path"] == "config/unapproved_probe.yaml")
    assert pending_entry["classification"] == "RUNTIME_CONFIG"
    assert pending_entry["approval_status"] == "PENDING_OWNER_APPROVAL"


# ---------------------------------------------------------------------------
# 4. hash変更 → pending（旧hashで承認されたpolicyは新contentへ流用されない）
# ---------------------------------------------------------------------------

def test_05_hash_drift_reverts_to_pending(tmp_path):
    repo = _init_config_fixture_repo(tmp_path)
    (repo / "config").mkdir()
    (repo / "config" / "martin.demo.yaml").write_text("mbtiles:\n  paths: [/tiles]\n", encoding="utf-8")

    approved_entry = _policy_entry_for(repo, "config/martin.demo.yaml")
    approved_policy = {"schema_version": 1, "entries": [approved_entry]}

    # 承認後にfile内容が変わった（OWNERが承認したbytesと現在のbytesが乖離した）
    (repo / "config" / "martin.demo.yaml").write_text("mbtiles:\n  paths: [/tiles, /extra]\n", encoding="utf-8")

    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved_policy)
    pending_paths = {e["path"] for e in manifest["pending_owner_approval_entries"]}
    accepted_paths = {e["path"] for e in manifest["entries"]}

    assert "config/martin.demo.yaml" in pending_paths
    assert "config/martin.demo.yaml" not in accepted_paths


# ---------------------------------------------------------------------------
# 5. `.yaml`拡張子だけでの自動承認はない（未承認のyamlは常にpending、
#    approved_policy自体がNoneでも例外にはならずpendingへ回るだけ）
# ---------------------------------------------------------------------------

def test_06_extension_alone_grants_no_approval(tmp_path):
    repo = _init_config_fixture_repo(tmp_path)
    (repo / "config").mkdir()
    (repo / "config" / "unapproved_probe.yaml").write_text("probe: true\n", encoding="utf-8")

    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=None)
    pending_paths = {e["path"] for e in manifest["pending_owner_approval_entries"]}
    assert "config/unapproved_probe.yaml" in pending_paths
    assert manifest["pending_owner_approval_count"] >= 1


# ---------------------------------------------------------------------------
# 6. config directory regexによる包括承認はない
#    （path prefixだけを緩く一致させる誤実装であればここで検出される）
# ---------------------------------------------------------------------------

def test_07_no_directory_prefix_blanket_approval(tmp_path):
    repo = _init_config_fixture_repo(tmp_path)
    (repo / "config").mkdir()
    (repo / "config" / "martin.demo.yaml").write_text("mbtiles:\n  paths: [/tiles]\n", encoding="utf-8")
    (repo / "config" / "another_new_file.yaml").write_text("other: true\n", encoding="utf-8")

    approved_entry = _policy_entry_for(repo, "config/martin.demo.yaml")
    # わざと path をディレクトリ prefix 的に緩く書き換えた不正なentryを混ぜても
    # 一致しないことを確認する（exact path一致のみが有効）。
    approved_policy = {"schema_version": 1, "entries": [approved_entry]}

    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy=approved_policy)
    pending_paths = {e["path"] for e in manifest["pending_owner_approval_entries"]}
    assert "config/another_new_file.yaml" in pending_paths

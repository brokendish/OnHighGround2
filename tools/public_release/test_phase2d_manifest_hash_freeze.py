"""
test_phase2d_manifest_hash_freeze.py — manifest hash stale対策のfreeze test
（Phase 2-D Round 5A、指示書第7節）。

Round 3実装報告書に記載されたmanifest hashが、report執筆後の追加編集で
再生成されたmanifestのhashとずれていた（Round 4 finding 5）。本testは
「manifest生成→書き込み→再読込→再計算のSHA-256が一致すること」
（bytesベースの決定性、mtimeではない）と、「実装報告書・evidence自体が
manifest生成対象（release build input）から除外されていること」
（指示書第7.2節: self-reference禁止）を検証する。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_manifest_hash_freeze.py -v
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _init_fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@local.invalid")
    _git(repo, "config", "user.name", "Fixture")
    (repo / "backend").mkdir()
    (repo / "backend" / "app.py").write_text("print('baseline')\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    # evidence/report file はbaseline commit後にuntrackedとして追加する
    # （self-reference除外を検証するには、これらがmanifestのgit status差分に
    # 現れる状態でなければならない）。
    (repo / "tasks" / "public-release" / "evidence" / "phase2d").mkdir(parents=True)
    (repo / "tasks" / "public-release" / "evidence" / "phase2d" / "note.md").write_text(
        "evidence note\n", encoding="utf-8"
    )
    return repo


# ---------------------------------------------------------------------------
# 1. manifest生成 → 書き込み → 再読込 → 再計算のSHA-256一致（bytesベース）
# ---------------------------------------------------------------------------

def test_01_write_then_reload_hash_matches(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").write_text("print('modified')\n", encoding="utf-8")

    manifest = manifest_mod.generate_manifest(repo)
    out_path = tmp_path / "manifest.json"
    reported_sha256 = manifest_mod.write_manifest(manifest, out_path)

    actual_bytes = out_path.read_bytes()
    actual_sha256 = hashlib.sha256(actual_bytes).hexdigest()

    assert reported_sha256 == actual_sha256


# ---------------------------------------------------------------------------
# 2. 同一repository状態からのmanifest生成は決定的（同じbytesになる）
# ---------------------------------------------------------------------------

def test_02_manifest_generation_is_deterministic(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").write_text("print('modified')\n", encoding="utf-8")

    m1 = manifest_mod.generate_manifest(repo)
    m2 = manifest_mod.generate_manifest(repo)

    # generated_atはtimestampなので除外して比較する
    m1_no_ts = {k: v for k, v in m1.items() if k != "generated_at"}
    m2_no_ts = {k: v for k, v in m2.items() if k != "generated_at"}
    assert m1_no_ts == m2_no_ts


# ---------------------------------------------------------------------------
# 3. report執筆後の追加編集でmanifestが再生成されると、報告書記載hashは
#    staleになる（Round 4 finding 5の再現）。freeze順序を守れば防げることを示す。
# ---------------------------------------------------------------------------

def test_03_stale_hash_reproduction_and_freeze_order_fix(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    (repo / "backend" / "app.py").write_text("print('v1')\n", encoding="utf-8")

    # 誤った手順: manifest生成 → report記載 → その後さらにfileを編集 → 再生成せず
    #            古いhashをreportに残したまま（Round 4 finding 5のバグ再現）
    manifest_v1 = manifest_mod.generate_manifest(repo)
    out_path = tmp_path / "manifest.json"
    reported_sha256 = manifest_mod.write_manifest(manifest_v1, out_path)

    (repo / "backend" / "app.py").write_text("print('v2 — edited after report was written')\n", encoding="utf-8")
    manifest_v2 = manifest_mod.generate_manifest(repo)  # 再生成（report更新を忘れた想定）
    actual_sha256_v2 = manifest_mod.write_manifest(manifest_v2, out_path)

    assert reported_sha256 != actual_sha256_v2, "release inputを変更すればhashは必ず変わる（stale検出可能）"

    # 正しいfreeze順序（指示書第7.3節）: release inputをfreezeしてから
    # manifest生成・hash計算・書き込み・再読込・再計算・三者一致確認を行う。
    # ここでは「手順7以降にmanifestを再生成しない」を守ればreported==actualに
    # なることを示す。
    manifest_final = manifest_mod.generate_manifest(repo)
    reported_sha256_final = manifest_mod.write_manifest(manifest_final, out_path)
    actual_sha256_final = hashlib.sha256(out_path.read_bytes()).hexdigest()
    assert reported_sha256_final == actual_sha256_final


# ---------------------------------------------------------------------------
# 4. 実装報告書・evidenceはmanifest対象（release build input）から除外される
#    （指示書第7.2節: self-reference禁止）
# ---------------------------------------------------------------------------

def test_04_report_and_evidence_excluded_from_manifest(tmp_path):
    repo = _init_fixture_repo(tmp_path)
    manifest = manifest_mod.generate_manifest(repo)
    all_included_paths = {e["path"] for e in manifest["entries"]}
    assert "tasks/public-release/evidence/phase2d/note.md" not in all_included_paths

    excluded_paths = {e["path"] for e in manifest["explicitly_excluded_nonrelease_entries"]}
    assert "tasks/public-release/evidence/phase2d/note.md" in excluded_paths
    entry = next(
        e for e in manifest["explicitly_excluded_nonrelease_entries"]
        if e["path"] == "tasks/public-release/evidence/phase2d/note.md"
    )
    assert entry["classification"] == "EXCLUDED_AUDIT_EVIDENCE"


def test_05_manifest_does_not_self_record_its_own_hash():
    """manifest schemaにmanifest自身のhashを記録するfieldが存在しないこと
    （指示書第7.2節「manifest自身のhashをmanifest内部へ記載しない」）。"""
    import inspect

    source = inspect.getsource(manifest_mod.generate_manifest)
    forbidden = ("manifest_sha256", "self_sha256", "own_sha256")
    for token in forbidden:
        assert token not in source, f"generate_manifest() must not self-record {token!r}"

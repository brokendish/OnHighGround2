"""
KTF-003 EVIDENCE-IMMUTABILITY（2026-10-12、OWNER 承認方針）の focused self-test。

formal evidence は immutable / append-only: run ごとに一意の directory、同じ名前への 2 回目の書き込みは失敗、
一時 file → 検証 → link（既存を置き換えない）、provenance（HEAD・tool・round・attempt・結果・sha256）。
現実装が「たまたま別 path を使う」ことではなく、上書きを防ぐ仕組みそのものを negative control で確かめる。
実 repository の tasks/ には書かない（一時 git repository を使う）。
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import formal_evidence as fe  # noqa: E402


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "fixture@local.invalid"],
                 ["config", "user.name", "Fixture"]):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "README").write_text("fixture\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "fixture"], cwd=path, check=True, capture_output=True)
    return path


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("OHG2_FORMAL_ROUND", raising=False)
    monkeypatch.delenv("OHG2_FORMAL_ATTEMPT", raising=False)
    r = _git_repo(tmp_path / "repo")
    monkeypatch.setattr(fe, "REPO_ROOT", r)
    return r


def _writable(p: Path) -> None:
    p.chmod(p.stat().st_mode | stat.S_IWUSR)


# ── identity ─────────────────────────────────────────────────────────────────────────

def test_identity_and_provenance(repo):
    run = fe.open_run("phase2d", "at17", round_label="final")
    run.write_json("result.json", {"ok": True})
    run.finalize({"exit_code": 0})
    prov = json.loads((run.directory / "provenance.json").read_text(encoding="utf-8"))
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
    assert prov["schema"] == fe.SCHEMA
    assert {k: prov[k] for k in ("phase", "tool", "round", "attempt", "git_head")} == {
        "phase": "phase2d", "tool": "at17", "round": "final", "attempt": 1, "git_head": head}
    assert prov["generated_at"] and prov["run_id"] and prov["execution_result"] == {"exit_code": 0}
    assert set(prov["files"]) == {"result.json"} and len(prov["files"]["result.json"]["sha256"]) == 64
    assert run.directory.name.startswith(tuple("0123456789")) and f"-{head[:12]}-at17-final-a1-" in run.directory.name
    assert fe.verify_run(run.directory) == []


def test_attempts_are_distinct_and_explicit_duplicate_is_refused(repo):
    a = fe.open_run("phase2d", "at14")
    b = fe.open_run("phase2d", "at14")
    assert (a.identity["attempt"], b.identity["attempt"]) == (1, 2) and a.directory != b.directory
    with pytest.raises(fe.EvidenceError):
        fe.open_run("phase2d", "at14", attempt=2)
    other_round = fe.open_run("phase2d", "at14", round_label="r2", attempt=1)  # round が違えば別 identity
    assert other_round.identity["attempt"] == 1


def test_negative_control_same_run_directory_is_refused(repo, monkeypatch):
    """乱数・時刻が衝突して同じ directory 名になっても、既存 directory には入らない（mkdir exist_ok=False）。"""
    monkeypatch.setattr(fe.secrets, "token_hex", lambda n: "deadbeef")
    first = fe.open_run("phase2d", "at17", attempt=1)
    first.write_text("a.txt", "A\n")

    class _FrozenDatetime(fe.datetime):
        @classmethod
        def now(cls, tz=None):
            return fe.datetime.strptime(first.directory.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=fe.timezone.utc)

    monkeypatch.setattr(fe, "datetime", _FrozenDatetime)
    monkeypatch.setattr(fe, "_same_identity_runs", lambda *a, **k: [])  # attempt の照合もすり抜けた想定
    with pytest.raises(FileExistsError):
        fe.open_run("phase2d", "at17", attempt=1)
    assert (first.directory / "a.txt").read_text() == "A\n"


@pytest.mark.parametrize("bad", ["", "../x", "UPPER", "a/b", "x" * 65])
def test_labels_are_validated(repo, bad):
    with pytest.raises(fe.EvidenceError):
        fe.open_run("phase2d", bad or "", round_label="ok")


# ── append-only ──────────────────────────────────────────────────────────────────────

def test_negative_control_second_write_to_same_name_fails_and_keeps_first(repo):
    run = fe.open_run("phase2d", "at17")
    sha = run.write_text("result.json", "first\n")
    with pytest.raises(FileExistsError):
        run.write_text("result.json", "second\n")
    assert (run.directory / "result.json").read_text() == "first\n"
    assert fe.hashlib.sha256(b"first\n").hexdigest() == sha


def test_negative_control_link_refuses_overwrite_even_if_existence_check_is_bypassed(repo, monkeypatch):
    """事前の exists() 判定が競合ですり抜けても、最終名は os.link（置き換えない）で作るので上書きされない。"""
    run = fe.open_run("phase2d", "at17")
    (run.directory / "result.json").write_text("concurrent writer\n")
    real_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self: False if self.name == "result.json" else real_exists(self))
    with pytest.raises(FileExistsError):
        run.write_text("result.json", "late writer\n")
    assert (run.directory / "result.json").read_text() == "concurrent writer\n"
    assert not [p for p in run.directory.iterdir() if ".tmp-" in p.name]


def test_negative_control_finalized_run_rejects_writes_and_is_read_only(repo):
    run = fe.open_run("phase2d", "at17")
    run.write_text("a.txt", "A\n")
    run.finalize({"exit_code": 0})
    with pytest.raises(fe.EvidenceError):
        run.write_text("b.txt", "B\n")
    assert not os.access(run.directory / "a.txt", os.W_OK) and not os.access(run.directory, os.W_OK)
    with pytest.raises(fe.EvidenceError):
        run.finalize({"exit_code": 0})


def test_negative_control_legacy_overwrite_is_detected(repo):
    """旧実装のように同じ file を書き直した場合、provenance 照合と snapshot 比較の両方が検出する。"""
    run = fe.open_run("phase2d", "at17")
    run.write_json("result.json", {"entries": 674})
    run.finalize({"exit_code": 0})
    before = fe.snapshot_tree(run.directory)
    target = run.directory / "result.json"
    _writable(run.directory)
    _writable(target)
    target.write_text('{"entries": 0}\n')  # 旧 AT-17 の固定名上書きの再現
    assert fe.verify_run(run.directory) == ["内容が provenance と一致しない: result.json"]
    assert fe.changed_or_removed(before, fe.snapshot_tree(run.directory)) == ["result.json"]
    target.unlink()
    assert fe.changed_or_removed(before, fe.snapshot_tree(run.directory)) == ["result.json"]


def test_finalize_rejects_unrecorded_file_and_verify_detects_extra_or_missing(repo):
    run = fe.open_run("phase2d", "at17")
    run.write_text("a.txt", "A\n")
    (run.directory / "stray.txt").write_text("x")
    with pytest.raises(fe.EvidenceError):
        run.finalize({"exit_code": 0})
    assert fe.verify_run(run.directory) == ["provenance.json が無い（未完了の run）"]


# ── atomic write ─────────────────────────────────────────────────────────────────────

def test_atomic_write_invalid_json_leaves_nothing(repo):
    run = fe.open_run("phase2d", "at17")
    with pytest.raises(json.JSONDecodeError):
        run.write_bytes("result.json", b'{"truncated": ', validate=lambda b: json.loads(b.decode("utf-8")))
    assert list(run.directory.iterdir()) == []


def test_atomic_write_interrupted_write_leaves_nothing(repo, monkeypatch):
    run = fe.open_run("phase2d", "at17")
    calls = {"n": 0}
    real_write = os.write

    def flaky_write(fd, data):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_write(fd, bytes(data)[:3])  # 途中まで書いてから失敗
        raise OSError("disk full")

    monkeypatch.setattr(fe.os, "write", flaky_write)
    with pytest.raises(OSError):
        run.write_text("result.json", "complete content\n")
    assert list(run.directory.iterdir()) == []


def test_atomic_write_readback_mismatch_is_rejected(repo, monkeypatch):
    run = fe.open_run("phase2d", "at17")
    real_read = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda self: b"corrupt" if ".tmp-" in self.name else real_read(self))
    with pytest.raises(fe.EvidenceError):
        run.write_text("result.json", "content\n")
    assert list(run.directory.iterdir()) == []


# ── tool 統合 ─────────────────────────────────────────────────────────────────────────

def test_at14_save_evidence_never_overwrites(repo):
    import phase2d_at14_check as at14
    d1 = at14.save_evidence([{"check_id": "x", "passed": True}], True, 1, 1, repo_root=repo)
    snap = fe.snapshot_tree(d1)
    d2 = at14.save_evidence([{"check_id": "x", "passed": False}], False, 0, 1, repo_root=repo)
    assert d1 != d2 and fe.snapshot_tree(d1) == snap
    assert fe.verify_run(d1) == [] and fe.verify_run(d2) == []
    assert json.loads((d2 / "provenance.json").read_text())["execution_result"]["overall"] == "FAIL"


def test_at17_save_evidence_keeps_judgement_and_result(repo):
    import phase2d_at17_clean_clone as at17
    result = {"overall_snapshot_completeness_result": "PASS", "approved_untracked_policy_applied": False}
    d = at17.save_evidence(repo, {"schema_version": 1, "entries": []}, result)
    saved = json.loads((d / "at17_snapshot_result.json").read_text(encoding="utf-8"))
    assert saved["overall_snapshot_completeness_result"] == "PASS"
    assert saved["manifest_sha256"] == fe.hashlib.sha256((d / "release_delta_manifest.json").read_bytes()).hexdigest()


@pytest.mark.parametrize("tool,phase", [("phase2b1_image_inspect", "phase2b1"),
                                        ("phase2b2_compose_boundary", "phase2b2"),
                                        ("phase2c_official_runner", "phase2c")])
def test_direct_writer_tools_use_a_fresh_run_directory_each_time(repo, monkeypatch, tool, phase):
    mod = __import__(tool)
    original = mod.EVIDENCE_DIR

    def fake_inner():
        mod.EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        (mod.EVIDENCE_DIR / "summary.json").write_text('{"run": "x"}\n')
        return 0

    monkeypatch.setattr(mod, "_main", fake_inner)
    try:
        assert mod.main() == 0
        first = mod.EVIDENCE_DIR
        snap = fe.snapshot_tree(first)
        assert mod.main() == 0
        second = mod.EVIDENCE_DIR
    finally:
        mod.EVIDENCE_DIR = original
    assert first != second and first.parent == second.parent == fe.evidence_root(repo, phase)
    assert fe.snapshot_tree(first) == snap and fe.verify_run(first) == [] and fe.verify_run(second) == []
    assert set(json.loads((second / "provenance.json").read_text())["files"]) == {"summary.json"}


def test_no_formal_tool_writes_to_the_lost_round5c_names():
    """KTF-003 の固定名（phase2d_round5c_* / phase2d_at14_results.json の旧位置）へ書く code が無い。"""
    for f in HERE.glob("phase2*.py"):
        code = [l for l in f.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("#")]
        joined = "\n".join(code)
        assert '"phase2d_round5c_release_delta_manifest.json"' not in joined, f.name
        assert '"phase2d_round5c_at17_snapshot_result.json"' not in joined, f.name

"""
PUBLIC-RELEASE-HARNESS-MODERNIZATION（2026-10-12）の focused self-test。B1〜B7 について、正しい状態が PASS し、
壊した状態（negative control）が検出されることを確かめる。実 Local stack・実 data_lake / data_runtime は使わない
（compose は `config` の描画だけで、container を起動しない。seed は空の一時 directory で代用する）。

  B1 追跡 gitlink 0・.claude/worktrees は ignore
  B2/B3/B4 隔離: 2b2・2b3・2b4 の override を描画して隔離違反 0（実 repository rw bind・実 stack 固定名・実 .env）、
           helper は seed 先の無い rw bind を拒否し、違反の各種別を検出する
  B4 deny manifest は current HEAD の clean clone から作られ（entry > 0）、public 配信面への operator 資産混入を検出する
  B5 .env.example が code の参照する env key を全て持つ（OHG2_ADMIN_DIR を含む）
  B6 RTE-004 は selector だけを更新し、oracle（200 / 401 / findings 0）は不変
  B7 AT-17 は delta = 0 の clean clone を正本として completeness / spot check / 禁止物を検査する
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import phase2_isolated_stack as iso  # noqa: E402
import phase2d_at14_check as at14  # noqa: E402
import phase2d_at17_clean_clone as at17  # noqa: E402
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402

DOCKER = shutil.which("docker")


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _fake_seeded(tmp_path: Path) -> dict:
    seeded = {k: tmp_path / f"seed_{k}" for k in ("data_lake", "data_runtime", "railways", "osrm")}
    for p in seeded.values():
        p.mkdir(parents=True)
    (seeded["data_lake"] / "admin").mkdir()
    (seeded["osrm"] / "foot.lua").write_text("-- fixture\n")
    return seeded


# ── B1 ───────────────────────────────────────────────────────────────────────────────

def test_b1_no_tracked_gitlink_and_worktrees_ignored():
    staged = _git(REPO_ROOT, "ls-files", "-s").stdout.splitlines()
    assert [l for l in staged if l.startswith("160000 ")] == []
    assert _git(REPO_ROOT, "check-ignore", "-q", ".claude/worktrees/x", check=False).returncode == 0


# ── B2 / B3 / B4: 隔離 helper ─────────────────────────────────────────────────────────

def test_isolation_helper_remaps_rw_binds_and_keeps_ro_scripts(tmp_path):
    seeded = _fake_seeded(tmp_path)
    vols = iso.service_volumes("runtime-init", seeded)
    assert f"{seeded['data_runtime'].resolve()}:/data_runtime:rw" in vols
    assert f"{(seeded['data_lake'] / 'admin').resolve()}:/data_lake/admin:rw" in vols
    for script in ("init_lease_volume.py", "init_data_lake_admin.py", "init_data_runtime_backend.py",
                   "init_data_runtime_backend_shelters.py"):
        assert f"./scripts/publish/{script}:/{script}:ro" in vols
    assert not [v for v in vols if v.startswith("./data_")]
    assert iso.lease_volume_override("p") == {"lease-coordination": {"name": "p-lease-coordination"}}


def test_isolation_helper_refuses_unmapped_rw_bind(tmp_path):
    compose = tmp_path / "c.yml"
    compose.write_text("services:\n  runtime-init:\n    volumes:\n      - ./unknown:/x\n")
    with pytest.raises(RuntimeError, match="seed 先が無い"):
        iso.service_volumes("runtime-init", _fake_seeded(tmp_path), compose)


def test_isolation_violations_detects_each_kind(tmp_path):
    rendered = {
        "services": {
            "a": {"container_name": "evacuation-navi-runtime-init", "volumes": []},
            "b": {"volumes": [{"type": "bind", "source": str(REPO_ROOT / "data_runtime"), "target": "/d"}]},
            "c": {"env_file": [{"path": str(REPO_ROOT / ".env")}]},
            "ok": {"volumes": [{"type": "bind", "source": str(tmp_path / "seed"), "target": "/d"},
                               {"type": "bind", "source": str(REPO_ROOT / "scripts"), "target": "/s", "read_only": True}]},
        },
        "volumes": {"lease-coordination": {"name": "evacuation-navi-lease-coordination"}},
        "networks": {"default": {"name": "evacuation-navi-network"}},
    }
    hits = iso.isolation_violations(rendered, [tmp_path])
    assert len(hits) == 5 and not [h for h in hits if h.startswith("ok:")]


@pytest.mark.skipif(DOCKER is None, reason="docker compose が無い")
@pytest.mark.parametrize("tool", ["phase2b2_compose_boundary", "phase2b3_operator_security", "phase2b4_frontend_boundary"])
def test_rendered_overrides_have_no_isolation_violation(tmp_path, monkeypatch, tool):
    mod = __import__(tool)
    seeded = _fake_seeded(tmp_path)
    if tool == "phase2b2_compose_boundary":
        monkeypatch.setattr(mod, "seed_temp_data_dirs", lambda d: seeded)
        override = mod.build_override_compose(tmp_path, mod.PROJECT_NAME_OPERATOR, "op")
        cmd = mod.compose_cmd(override, [], mod.PROJECT_NAME_OPERATOR)
    else:
        override = mod.build_override_compose(tmp_path, seeded)
        cmd = mod.compose_cmd(override, [])
    rendered = iso.render_config(cmd, ["operator"])
    assert "runtime-init" in rendered["services"] and "operator-gateway" in rendered["services"]
    assert iso.isolation_violations(rendered, [tmp_path]) == []


def test_2b3_has_no_stale_service_name():
    code = (HERE / "phase2b3_operator_security.py").read_text(encoding="utf-8")
    lines = [l for l in code.splitlines() if not l.lstrip().startswith("#")]
    assert not [l for l in lines if "operator-publish-proxy" in l]


# ── B4 ───────────────────────────────────────────────────────────────────────────────

def test_b4_deny_manifest_from_clean_clone_and_negative_control(tmp_path):
    import phase2b4_frontend_boundary as fb
    clone = tmp_path / "candidate"
    ok, detail = fb.make_clean_clone(clone)
    assert ok, detail
    manifest = fb.build_deny_manifest(clone / "operator" / "frontend-admin")
    assert len(manifest["entries"]) > 0  # commit 済みでも検証対象は 0 にならない
    surface = fb.classify_public_surface(clone, manifest)
    assert surface["ok"] and surface["counts"]["PUBLIC_DENIED"] == 0
    # negative control: operator 資産を public 配信面へ置いて commit すると PUBLIC_DENIED になる
    leaked = clone / "frontend" / "datasets.html"
    leaked.write_bytes((clone / "operator" / "frontend-admin" / "datasets.html").read_bytes())
    _git(clone, "add", "frontend/datasets.html")
    surface2 = fb.classify_public_surface(clone, manifest)
    assert not surface2["ok"] and "frontend/datasets.html" in surface2["denied"]


# ── B5 ───────────────────────────────────────────────────────────────────────────────

def test_b5_env_example_covers_referenced_keys():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    keys = at14._extract_actual_public_env_keys(REPO_ROOT)
    assert "OHG2_ADMIN_DIR" in keys
    assert at14.check_env_example_key_coverage(text, keys).passed
    removed = "\n".join(l for l in text.splitlines() if "OHG2_ADMIN_DIR" not in l)
    assert not at14.check_env_example_key_coverage(removed, keys).passed


# ── B6 ───────────────────────────────────────────────────────────────────────────────

def test_b6_selector_only_change_and_frozen_oracle():
    e2e = (HERE / "phase2d_round12b_rte004_e2e.js").read_text(encoding="utf-8")
    assert "page.fill('#login-form input#token', token)" in e2e
    assert "page.click('#login-form button#submit-btn')" in e2e
    assert "page.fill('#operator-auth-bar" not in e2e and "page.click('#operator-auth-bar" not in e2e
    runner = (HERE / "phase2d_round12b_new_cases_runner.py").read_text(encoding="utf-8")
    assert 'payload.get("postAuthFetchStatus") == 200' in runner
    assert 'payload.get("postReloadStatus") == 401' in runner
    assert 'payload.get("findings") == []' in runner


# ── B7 ───────────────────────────────────────────────────────────────────────────────

def _fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@local.invalid")
    _git(repo, "config", "user.name", "Fixture")
    (repo / "backend").mkdir()
    (repo / "backend" / "app.py").write_text("print('app')\n")
    (repo / "docs").mkdir()
    (repo / "docs" / "readme.md").write_text("docs\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "all committed")
    return repo


def test_b7_delta_zero_clean_clone_is_candidate(tmp_path):
    repo = _fixture_repo(tmp_path)
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy={"schema_version": 1, "entries": []})
    assert manifest["entry_count"] == 0
    result = at17.run(repo, manifest, required_spot_check_paths=["backend/app.py", "docs/readme.md"],
                      required_absent_paths=["backend/removed.py"])
    c = result["completeness"]
    assert c["completeness_pass"], c
    assert c["tree_inventory"]["clean_clone_tracked_files"] == 2 and c["tree_inventory"]["tree_mismatch_count"] == 0
    assert all(v["ok"] and v["matches_candidate_head"] for v in c["spot_check"].values())


def test_b7_negative_controls(tmp_path):
    repo = _fixture_repo(tmp_path)
    manifest = manifest_mod.generate_manifest(repo, approved_untracked_policy={"schema_version": 1, "entries": []})
    # spot path が clean clone に無い
    r = at17.run(repo, manifest, required_spot_check_paths=["backend/missing.py"], required_absent_paths=[])
    assert not r["completeness"]["completeness_pass"]
    # 公開禁止物（gitlink）が追跡されている
    sub = _fixture_repo(tmp_path / "sub")
    head = _git(sub, "rev-parse", "HEAD").stdout.strip()
    _git(repo, "update-index", "--add", "--cacheinfo", f"160000,{head},vendor/sub")
    _git(repo, "commit", "-q", "-m", "gitlink")
    manifest2 = manifest_mod.generate_manifest(repo, approved_untracked_policy={"schema_version": 1, "entries": []})
    r2 = at17.run(repo, manifest2, required_spot_check_paths=[], required_absent_paths=[])
    assert not r2["completeness"]["completeness_pass"]
    assert r2["completeness"]["tree_inventory"]["prohibited"] == ["vendor/sub"]

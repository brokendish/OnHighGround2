"""
test_phase2d_osrm_isolation_selfcheck.py — OSRM fixture contamination gate /
demo Compose isolation のself-test（Phase 2-D Round 8、指示書第8節）。

Round 7 candidate（650 entries）には、tests/fixtures/osm_demo/ という
read-onlyであるべきsource fixture配下へ osrm-driving/osrm-walking container が
osrm-extract/partition/customize の出力（.osrm*、54 file）を直接書き込んでいた
ことによる混入があった（CODEX round 7実測）。本fileは次を検証する。

  - `phase2d_release_delta_manifest.scan_osrm_runtime_contamination()` /
    `_raise_if_osrm_contaminated()` が、git statusではなくfilesystemを直接
    scanして`.osrm*`残存を検出しfail-closedで停止すること（`.gitignore`の
    有無に依存しない）。
  - `generate_manifest()` / `phase2d_untracked_policy.generate_candidate_
    untracked_policy()` の両方の入口でこのgateが効くこと（Round 7はこの経路の
    片方（後者）だけを通ったため混入した）。
  - `docker-compose.demo.yml` の静的構造（source fixtureがread-only mount、
    変換出力が専用named volumeへ分離されていること、既存成果物があれば
    FAILする起動commandになっていること）。

実source repository（OnHighGround2自身）のtests/fixtures/osm_demo/には触れず、
すべてrepo-external fixture git repository（tmp_path配下）または
docker-compose.demo.yml自体の静的parseで検証する。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_osrm_isolation_selfcheck.py -v
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase2d_release_delta_manifest as manifest_mod  # noqa: E402
import phase2d_untracked_policy as policy_mod  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def _init_osm_fixture_repo(tmp_path: Path) -> Path:
    """osm_demo fixtureを持つ最小fixture repositoryを作る（release rootの
    存在確認だけが目的で、tests/fixtures/以外は空でよい）。"""
    repo = tmp_path / "fixture_repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "fixture@local.invalid")
    _git(repo, "config", "user.name", "Fixture")

    osm_dir = repo / "tests" / "fixtures" / "osm_demo" / "validated" / "tokyo" / "osm" / "driving"
    osm_dir.mkdir(parents=True)
    (osm_dir / "kanto-260214.osm.pbf").write_bytes(b"fake-pbf-bytes")
    (repo / "tests" / "fixtures" / "osm_demo" / "MANIFEST.json").write_text("{}\n", encoding="utf-8")

    (repo / "backend").mkdir()
    (repo / "backend" / "app.py").write_text("print('baseline')\n", encoding="utf-8")

    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo


# ---------------------------------------------------------------------------
# 1. contamination scan: 検出なし（clean）
# ---------------------------------------------------------------------------

def test_01_clean_fixture_no_contamination(tmp_path):
    repo = _init_osm_fixture_repo(tmp_path)
    assert manifest_mod.scan_osrm_runtime_contamination(repo) == []
    # generate_manifest自体は正常に完走する（他に問題がなければ）
    manifest_mod.generate_manifest(repo)


# ---------------------------------------------------------------------------
# 2. contamination scan: .osrm本体ファイルを検出
# ---------------------------------------------------------------------------

def test_02_osrm_base_file_detected(tmp_path):
    repo = _init_osm_fixture_repo(tmp_path)
    stray = repo / "tests/fixtures/osm_demo/validated/tokyo/osm/driving/kanto-260214.osrm"
    stray.write_bytes(b"fake-osrm-graph")

    found = manifest_mod.scan_osrm_runtime_contamination(repo)
    assert found == ["tests/fixtures/osm_demo/validated/tokyo/osm/driving/kanto-260214.osrm"]

    with pytest.raises(manifest_mod.ManifestGenerationError, match="OSRM runtime build artifact"):
        manifest_mod.generate_manifest(repo)


# ---------------------------------------------------------------------------
# 3. contamination scan: .osrm.* 派生ファイル（例: .osrm.partition）も検出
# ---------------------------------------------------------------------------

def test_03_osrm_derived_artifact_detected(tmp_path):
    repo = _init_osm_fixture_repo(tmp_path)
    stray = repo / "tests/fixtures/osm_demo/validated/tokyo/osm/driving/kanto-260214.osrm.partition"
    stray.write_bytes(b"fake-partition-data")

    found = manifest_mod.scan_osrm_runtime_contamination(repo)
    assert found == ["tests/fixtures/osm_demo/validated/tokyo/osm/driving/kanto-260214.osrm.partition"]


# ---------------------------------------------------------------------------
# 4. .osm.pbf source fixtureは誤検出しない
# ---------------------------------------------------------------------------

def test_04_source_pbf_not_flagged(tmp_path):
    repo = _init_osm_fixture_repo(tmp_path)
    found = manifest_mod.scan_osrm_runtime_contamination(repo)
    assert found == []
    # .osm.pbf自体がpatternに引っかからないことも直接確認する
    assert not manifest_mod.OSRM_RUNTIME_ARTIFACT_FILENAME_PATTERN.search("kanto-260214.osm.pbf")


# ---------------------------------------------------------------------------
# 5. `.gitignore`でgit statusから見えなくなっても検出する（filesystem直接scan）
# ---------------------------------------------------------------------------

def test_05_contamination_detected_even_if_gitignored(tmp_path):
    repo = _init_osm_fixture_repo(tmp_path)
    (repo / ".gitignore").write_text("tests/fixtures/osm_demo/**/*.osrm*\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-q", "-m", "add gitignore")

    stray = repo / "tests/fixtures/osm_demo/validated/tokyo/osm/driving/kanto-260214.osrm"
    stray.write_bytes(b"fake-osrm-graph")

    # git statusにはこのfileは一切現れないことを確認した上で、それでも
    # contamination scanが検出することを確認する。
    status = _git(repo, "status", "--porcelain=v2", "--untracked-files=all").stdout
    assert "kanto-260214.osrm" not in status

    found = manifest_mod.scan_osrm_runtime_contamination(repo)
    assert found == ["tests/fixtures/osm_demo/validated/tokyo/osm/driving/kanto-260214.osrm"]
    with pytest.raises(manifest_mod.ManifestGenerationError):
        manifest_mod.generate_manifest(repo)


# ---------------------------------------------------------------------------
# 6. candidate policy生成（`phase2d_untracked_policy`側の入口）も同じgateで止まる
# ---------------------------------------------------------------------------

def test_06_candidate_policy_generation_blocked_by_contamination(tmp_path):
    repo = _init_osm_fixture_repo(tmp_path)
    stray = repo / "tests/fixtures/osm_demo/validated/tokyo/osm/driving/kanto-260214.osrm.mldgr"
    stray.write_bytes(b"fake-mldgr")

    with pytest.raises(policy_mod.PolicyError, match="OSRM runtime build artifact"):
        policy_mod.generate_candidate_untracked_policy(repo)


# ---------------------------------------------------------------------------
# 7. contamination gateの適用範囲は宣言されたfixture rootに限定される
#    （他のtest fixtureへ`.osrm`という文字列を含むfileがあっても誤爆しない）
# ---------------------------------------------------------------------------

def test_07_scope_limited_to_declared_fixture_root(tmp_path):
    repo = _init_osm_fixture_repo(tmp_path)
    other = repo / "tests" / "fixtures" / "unrelated_demo"
    other.mkdir(parents=True)
    (other / "not_really.osrm").write_bytes(b"unrelated")

    found = manifest_mod.scan_osrm_runtime_contamination(repo)
    assert found == []


# ---------------------------------------------------------------------------
# 8. 実repository: cleanup後、汚染ゼロであることの回帰確認
# ---------------------------------------------------------------------------

def test_08_real_repo_osm_demo_fixture_currently_clean():
    found = manifest_mod.scan_osrm_runtime_contamination(REPO_ROOT)
    assert found == [], f"real repository fixture still contains OSRM runtime artifacts: {found}"


# ---------------------------------------------------------------------------
# 9〜12. docker-compose.demo.yml 静的構造検証
# ---------------------------------------------------------------------------

class _ComposeOverrideLoader(yaml.SafeLoader):
    pass


def _override_constructor(loader: yaml.Loader, node: yaml.Node):
    return loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)


_ComposeOverrideLoader.add_constructor("!override", _override_constructor)


def _load_demo_compose() -> dict:
    text = (REPO_ROOT / "docker-compose.demo.yml").read_text(encoding="utf-8")
    return yaml.load(text, Loader=_ComposeOverrideLoader)


def test_09_osrm_driving_fixture_mounted_read_only():
    compose = _load_demo_compose()
    volumes = compose["services"]["osrm-driving"]["volumes"]
    fixture_mounts = [v for v in volumes if "tests/fixtures/osm_demo/validated" in v]
    assert len(fixture_mounts) == 1
    assert fixture_mounts[0].endswith(":ro"), fixture_mounts[0]
    assert "/fixture_input" in fixture_mounts[0]
    # source fixtureをそのまま/data_lake/validatedへrwでmountしていないこと
    # （Round 6の混入原因そのものが再発していないことの直接確認）
    assert not any(
        "tests/fixtures/osm_demo/validated" in v and v.endswith(":rw") for v in volumes
    )


def test_10_osrm_walking_fixture_mounted_read_only():
    compose = _load_demo_compose()
    volumes = compose["services"]["osrm-walking"]["volumes"]
    fixture_mounts = [v for v in volumes if "tests/fixtures/osm_demo/validated" in v]
    assert len(fixture_mounts) == 1
    assert fixture_mounts[0].endswith(":ro"), fixture_mounts[0]
    assert not any(
        "tests/fixtures/osm_demo/validated" in v and v.endswith(":rw") for v in volumes
    )


def test_11_osrm_output_uses_dedicated_named_volumes():
    compose = _load_demo_compose()
    driving_volumes = compose["services"]["osrm-driving"]["volumes"]
    walking_volumes = compose["services"]["osrm-walking"]["volumes"]
    assert any(v.startswith("osrm-driving-work:/data_lake/validated") for v in driving_volumes)
    assert any(v.startswith("osrm-walking-work:/data_lake/validated") for v in walking_volumes)

    top_level_volumes = compose["volumes"]
    assert "osrm-driving-work" in top_level_volumes
    assert "osrm-walking-work" in top_level_volumes
    assert top_level_volumes["osrm-driving-work"]["name"] == "${COMPOSE_PROJECT_NAME:-onhighground2-demo}-osrm-driving-work"
    assert top_level_volumes["osrm-walking-work"]["name"] == "${COMPOSE_PROJECT_NAME:-onhighground2-demo}-osrm-walking-work"


def test_12_osrm_commands_fail_closed_on_pre_existing_output():
    compose = _load_demo_compose()
    for svc in ("osrm-driving", "osrm-walking"):
        command = compose["services"][svc]["command"]
        assert "ls -A /data_lake/validated" in command
        assert "FATAL" in command and "exit 1" in command
        # 既存成果物チェックがextract呼び出しより前に置かれていること
        check_pos = command.index("ls -A /data_lake/validated")
        extract_pos = command.index("osrm-extract")
        assert check_pos < extract_pos
        # copy後のsource hash比較が入っていること
        assert "sha256sum" in command
        assert "EXPECTED_SHA=" in command
        # 必須artifact setの検証がrouted起動より前にあること
        routed_pos = command.index("osrm-routed")
        artifact_check_pos = command.index("missing required OSRM artifact")
        assert artifact_check_pos < routed_pos


def test_13_osrm_shell_variables_correctly_escaped_for_compose():
    """Compose interpolation対象になる裸の`$VAR`が紛れ込んでいないことを確認する
    （`$$`でescapeし忘れると、Composeがcontainerへ渡す前に空文字へ変換して
    しまい、command自体が壊れる）。"""
    compose = _load_demo_compose()
    import re

    bare_var_pattern = re.compile(r"(?<!\$)\$(?!\$)[A-Za-z_][A-Za-z0-9_]*")
    for svc in ("osrm-driving", "osrm-walking"):
        command = compose["services"][svc]["command"]
        assert not bare_var_pattern.search(command), (
            f"{svc}: found un-escaped $VAR in command that Compose would try to "
            "interpolate itself"
        )

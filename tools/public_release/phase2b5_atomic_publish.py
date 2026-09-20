#!/usr/bin/env python3
"""
tools/public_release/phase2b5_atomic_publish.py

Phase 2-B.5（atomic runtime publish・reader lease・GC）の統合検証script。
AT-11（14系統）とDP-N01〜N20を、隔離Compose stack・実container・実
filesystemを組み合わせて判定する。

tools/public_release/phase2b5_inner_tests.py がAT-11 1〜12,14と大半の
DP-N（filesystem/process level）を実行する。本scriptは:
  - 隔離stackの構築・cleanup
  - AT-11 #13（実container numeric identity/permission negative matrix）
  - DP-N01〜N03（Compose設定mutationの検出）
  - 過去phase回帰の起点
を担当する。

使い方:
    ./venv/bin/python tools/public_release/phase2b5_atomic_publish.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required. Run via ./venv/bin/python.", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

_RUN_TAG = os.environ.get("OHG2_PHASE2B5_RUN_TAG") or datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
PROJECT_NAME = f"ohg2p2b5{_RUN_TAG}".lower().replace("_", "")

RESULTS: List[Dict[str, Any]] = []
INNER_EXPECTED_COUNT = 72
RUNTIME_INIT_CONTAINER_ID: Optional[str] = None
RUNTIME_INIT_IDENTITY: Dict[str, Any] = {}
_GLOBAL_FAIL_FAST_ENABLED = False
_FORMAL_FAILURE_OBSERVED = False


class FormalCaseFailure(RuntimeError):
    """A formal case failed; stop emitting cases and enter finally-only cleanup."""


def record(name: str, passed: bool, detail: str = "") -> None:
    global _FORMAL_FAILURE_OBSERVED
    if _GLOBAL_FAIL_FAST_ENABLED and _FORMAL_FAILURE_OBSERVED:
        # A nested finally may still need to release resources, but it must not
        # append another formal case after the first non-PASS result.
        return
    RESULTS.append({"name": name, "pass": bool(passed), "detail": str(detail)[-3000:]})
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}")
    if not passed and detail:
        print(f"        detail: {str(detail)[:600]}")
    if not passed and _GLOBAL_FAIL_FAST_ENABLED:
        _FORMAL_FAILURE_OBSERVED = True
        raise FormalCaseFailure(name)


def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("cwd", str(REPO_ROOT))
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def check_docker_available() -> bool:
    return _run(["docker", "info"]).returncode == 0


def inner_runner_args(inner_test_src: Path) -> List[str]:
    """Return the isolated inner-runner argv without replaying Compose dependencies."""
    return [
        "run", "--rm", "--no-deps",
        "-v", f"{inner_test_src}:/inner_test.py:ro",
        "--entrypoint", "python3",
        "backend-operator", "/inner_test.py",
    ]


def validate_inner_summary(
    child_exit: int, summary_line: Optional[str]
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """Fail closed before any post-inner formal case can be emitted."""
    if child_exit != 0:
        return False, None, f"inner child exit={child_exit}"
    if summary_line is None:
        return False, None, "inner summary missing"
    try:
        summary = json.loads(summary_line)
    except (json.JSONDecodeError, TypeError) as exc:
        return False, None, f"inner summary malformed: {type(exc).__name__}"
    if not isinstance(summary, dict):
        return False, None, "inner summary malformed: root is not an object"
    results = summary.get("results")
    if not isinstance(results, list):
        return False, None, "inner summary malformed: results is not a list"
    total = summary.get("total")
    passed = summary.get("pass")
    failed = summary.get("fail")
    skipped = summary.get("skip", 0)
    if any(isinstance(value, bool) or not isinstance(value, int)
           for value in (total, passed, failed, skipped)):
        return False, None, "inner summary malformed: count fields are not integers"
    if total != INNER_EXPECTED_COUNT or len(results) != INNER_EXPECTED_COUNT:
        return False, None, f"inner count mismatch: total={total} results={len(results)} expected={INNER_EXPECTED_COUNT}"
    if failed != 0 or skipped != 0 or passed != INNER_EXPECTED_COUNT:
        return False, None, f"inner non-pass summary: pass={passed} fail={failed} skip={skipped}"
    if total != passed + failed + skipped:
        return False, None, "inner summary malformed: counts do not add up"
    names: List[str] = []
    for index, result in enumerate(results):
        if not isinstance(result, dict) or not isinstance(result.get("name"), str) or not result["name"]:
            return False, None, f"inner summary malformed: result[{index}] identity"
        if result.get("pass") is not True:
            return False, None, f"inner result[{index}] is not PASS"
        names.append(result["name"])
    if len(set(names)) != INNER_EXPECTED_COUNT:
        return False, None, "inner duplicate result name detected"
    # The frozen inner source emits synchronously in deterministic source order.
    # A complete unique result list therefore maps positionally, without gaps, to
    # the frozen S10-006..S10-077 interval.
    mapped_ids = [f"S10-{order:03d}" for order in range(6, 78)]
    if len(mapped_ids) != len(results) or mapped_ids[0] != "S10-006" or mapped_ids[-1] != "S10-077":
        return False, None, "inner order mapping mismatch"
    summary["mapped_case_ids"] = mapped_ids
    return True, summary, "72 unique PASS results map exactly to S10-006..S10-077"


# ------------------------------------------------------------------
# 隔離override（container_name/volume nameがdocker-compose.ymlで固定
# されているため、run-tagごとに一意な名前へ上書きする必要がある。
# Phase 2-B.4検証時、この上書きを怠ったためdependency経由で実repository
# のdata_runtime/lease-coordination volumeへ意図せず触れる事故があった。
# 同じ誤りを防ぐため、runtime-initとbackend-operatorのcontainer_name、
# およびlease-coordination volumeのnameを、baseファイルの固定値ごと
# override fileで明示的に上書きする。
# ------------------------------------------------------------------

def build_override(tmp_dir: Path) -> Path:
    override = {
        "services": {
            "runtime-init": {
                "container_name": f"{PROJECT_NAME}-runtime-init",
                "volumes": [
                    "lease-coordination:/run/onhighground2/leases:rw",
                    f"{tmp_dir}/data_runtime:/data_runtime:rw",
                    f"{REPO_ROOT}/scripts/publish/init_lease_volume.py:/init_lease_volume.py:ro",
                ],
            },
            "backend-operator": {
                "container_name": f"{PROJECT_NAME}-backend-operator",
                "volumes": [
                    "lease-coordination:/run/onhighground2/leases:rw",
                    f"{tmp_dir}/data_runtime:/data_runtime:rw",
                    f"{REPO_ROOT}/data_lake:/data_lake:ro",
                    f"{REPO_ROOT}/backend:/app:ro",
                    f"{REPO_ROOT}/scripts:/scripts:ro",
                    f"{tmp_dir}/dummy_railways:/frontend/layers/railways:ro",
                ],
                "env_file": [],
                # AT-11-13g-j検証のためcontainerを起動状態に保つ最小限のdummy secret。
                # 実秘密ではなく、Phase 2-B.1で確定済みのfail-closed起動検証を
                # 満たすためだけの固定文字列。
                "environment": ["OPERATOR_AUTH_SECRET=OHG2_PHASE2B5_DUMMY_SECRET_DO_NOT_USE"],
            },
            "backend-public": {
                "container_name": f"{PROJECT_NAME}-backend-public",
                "volumes": [
                    f"{tmp_dir}/data_runtime:/data_runtime:ro",
                    f"{tmp_dir}/data_runtime/logs:/data_runtime/logs:rw",
                    f"{tmp_dir}/data_runtime/cache:/data_runtime/cache:rw",
                    "lease-coordination:/run/onhighground2/leases:rw",
                    f"{REPO_ROOT}/data_lake:/data_lake:ro",
                    f"{REPO_ROOT}/data:/app/data:ro",
                    f"{REPO_ROOT}/data:/data:ro",
                    f"{tmp_dir}/dummy_shelter_data:/app/shelter_data:ro",
                    f"{REPO_ROOT}/backend:/app:ro",
                    f"{REPO_ROOT}/scripts:/scripts:ro",
                    f"{tmp_dir}/dummy_railways:/frontend/layers/railways:ro",
                    f"{tmp_dir}/dummy_osrm:/osrm:ro",
                ],
                "env_file": [],
            },
        },
        "volumes": {
            "lease-coordination": {"name": f"{PROJECT_NAME}-lease-coordination"},
        },
        "networks": {
            "default": {"name": f"{PROJECT_NAME}-default"},
            "operator-internal": {"name": f"{PROJECT_NAME}-operator-internal"},
            "operator-publish": {"name": f"{PROJECT_NAME}-operator-publish"},
        },
    }
    for d in ("data_runtime", "dummy_railways", "dummy_shelter_data", "dummy_osrm", "data_runtime/logs", "data_runtime/cache"):
        (tmp_dir / d).mkdir(parents=True, exist_ok=True)

    override_path = tmp_dir / "docker-compose.override.phase2b5.yml"
    with open(override_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(override, f, sort_keys=False)
    return override_path


def compose_cmd(override_file: Path, extra: List[str]) -> List[str]:
    return [
        "docker", "compose",
        "-f", str(COMPOSE_FILE),
        "-f", str(override_file),
        "-p", PROJECT_NAME,
        *extra,
    ]


def cleanup_stack(override_file: Path, *, record_results: bool = True) -> None:
    def cleanup_record(name: str, passed: bool, detail: str = "") -> None:
        nonlocal record_results
        if record_results:
            try:
                record(name, passed, detail)
            except FormalCaseFailure:
                # Cleanup must remain best-effort, but no later cleanup controls may
                # be emitted as formal cases after its first non-PASS result.
                record_results = False

    _remove_retained_runtime_init()
    proc = _run(compose_cmd(override_file, ["--profile", "operator", "down", "--remove-orphans", "--timeout", "15"]))
    cleanup_record("cleanup: docker compose down succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-1000:])

    ps_proc = _run(compose_cmd(override_file, ["ps", "-a", "-q"]))
    remaining = [l for l in ps_proc.stdout.splitlines() if l.strip()] if ps_proc.returncode == 0 else ["<query failed>"]
    cleanup_record("cleanup: post-down container残存 0件", len(remaining) == 0, f"remaining={remaining}")

    vol_proc = _run(["docker", "volume", "ls", "-q", "--filter", f"name={PROJECT_NAME}-lease-coordination"])
    vols = [l for l in vol_proc.stdout.splitlines() if l.strip()]
    if vols:
        rm_proc = _run(["docker", "volume", "rm", "-f", *vols])
        cleanup_record("cleanup: lease-coordination volume削除", rm_proc.returncode == 0, (rm_proc.stdout + rm_proc.stderr)[-300:])
    recheck = _run(["docker", "volume", "ls", "-q", "--filter", f"name={PROJECT_NAME}-lease-coordination"])
    still = [l for l in recheck.stdout.splitlines() if l.strip()]
    cleanup_record("cleanup: test volume残存 0件", len(still) == 0, f"still={still}")

    for tag in (f"{PROJECT_NAME}-backend-public:latest", f"{PROJECT_NAME}-backend-operator:latest",
                f"{PROJECT_NAME}-runtime-init:latest"):
        _run(["docker", "rmi", "-f", tag])
    img_check = _run(["docker", "images", "-q", "--filter", f"reference={PROJECT_NAME}-*"])
    remaining_imgs = [l for l in img_check.stdout.splitlines() if l.strip()] if img_check.returncode == 0 else ["<query failed>"]
    cleanup_record("cleanup: test project image残存 0件", len(remaining_imgs) == 0, f"remaining={remaining_imgs}")


def cleanup_negative_control() -> None:
    bogus_compose = REPO_ROOT / "tools" / "public_release" / "__nonexistent_phase2b5_compose__.yml"
    bogus_project = f"{PROJECT_NAME}-bogus"

    proc = _run(["docker", "compose", "-f", str(bogus_compose), "-p", bogus_project, "ps", "-a", "-q"])
    record("cleanup negative control 1/6: 存在しないcompose fileへのps queryは非0で失敗する",
           proc.returncode != 0, (proc.stdout + proc.stderr)[-300:])

    proc = _run(["docker", "compose", "-f", str(bogus_compose), "-p", bogus_project, "down", "--timeout", "5"])
    record("cleanup negative control 2/6: 存在しないcompose fileへのdownは非0で失敗する",
           proc.returncode != 0, (proc.stdout + proc.stderr)[-300:])

    fake_volume_name = f"{PROJECT_NAME}-nonexistent-volume-xyz"
    proc = _run(["docker", "volume", "rm", fake_volume_name])
    record("cleanup negative control 3/6: 存在しないvolumeへのrmは非0で失敗する",
           proc.returncode != 0, (proc.stdout + proc.stderr)[-300:])

    proc = _run(["docker", "compose", "-f", str(bogus_compose), "-p", f"{bogus_project}-requery", "ps", "-a", "-q"])
    record("cleanup negative control 4/6: cleanup後の再照会（bogus compose）は非0で失敗する",
           proc.returncode != 0, (proc.stdout + proc.stderr)[-300:])

    residue_label = f"ohg2p2b5ncresidue={_RUN_TAG}"
    residue_name = f"ohg2-p2b5-nc-residue-{_RUN_TAG}"
    run_proc = _run(["docker", "run", "-d", "--rm", "--name", residue_name, "--label", residue_label, "alpine:latest", "sleep", "60"])
    if run_proc.returncode != 0:
        record("cleanup negative control 5/6: 削除後残存の誤PASS防止（fake residual container起動）", False,
               (run_proc.stdout + run_proc.stderr)[-300:])
        record("cleanup negative control 6/6: 実削除後は残存0件と正しく判定できる（positive control）", False, "前段起動失敗")
        return
    try:
        query_proc = _run(["docker", "ps", "-q", "--filter", f"label={residue_label}"])
        residue_ids = [l for l in query_proc.stdout.splitlines() if l.strip()]
        record("cleanup negative control 5/6: 削除せず残したcontainerを0件と誤判定しない",
               query_proc.returncode == 0 and len(residue_ids) > 0, f"residue_ids={residue_ids}")
    finally:
        _run(["docker", "rm", "-f", residue_name])
    recheck_proc = _run(["docker", "ps", "-a", "-q", "--filter", f"label={residue_label}"])
    recheck_ids = [l for l in recheck_proc.stdout.splitlines() if l.strip()]
    record("cleanup negative control 6/6: 実削除後は残存0件と正しく判定できる（positive control）",
           recheck_proc.returncode == 0 and len(recheck_ids) == 0, f"recheck_ids={recheck_ids}")


# ------------------------------------------------------------------
# DP-N01〜N03: raw compose config mutation検出（phase2b4スタイル）
# ------------------------------------------------------------------

def negative_fixtures_compose(run_tmp: Path) -> None:
    base_text = COMPOSE_FILE.read_text(encoding="utf-8")

    # DP-N01: public /data_runtimeをrwへ変更
    mutated = base_text.replace(
        "      - ./data_runtime:/data_runtime:ro\n",
        "      - ./data_runtime:/data_runtime\n",
        1,
    )
    ok = mutated != base_text and "- ./data_runtime:/data_runtime:ro" not in mutated.split("backend-public:")[1].split("backend-operator:")[0]
    record("DP-N01: public /data_runtimeをrwへ変更する差分をraw sourceで検出できる", ok,
           f"mutation_found={mutated != base_text}")

    # DP-N02: current末端pathを直接bind mount（想定外パターンの検出）
    has_leaf_mount = "data_runtime/current:/data_runtime" in base_text
    record("DP-N02: 現行docker-compose.ymlにcurrent末端の直接bind mountが存在しない", not has_leaf_mount)

    # DP-N03: supplemental GID 20001を除去した場合の検出（source上のgroup_add確認）
    public_block = base_text.split("backend-public:")[1].split("backend-operator:")[0]
    has_group_add = 'group_add' in public_block and '"20001"' in public_block
    record("DP-N03: backend-publicのgroup_add(20001)が現行sourceに存在する（除去差分の対比基準）", has_group_add)
    mutated3 = base_text.replace('    group_add:\n      - "20001"\n', "", 1)
    record("DP-N03b: group_add(20001)を除去する変異をraw sourceで検出できる", mutated3 != base_text)


# ------------------------------------------------------------------
# AT-11 #13: 実container numeric identity / permission negative matrix
# ------------------------------------------------------------------

def _remove_retained_runtime_init() -> None:
    """Best-effort finally cleanup; intentionally not a formal case emission."""
    global RUNTIME_INIT_CONTAINER_ID
    if RUNTIME_INIT_CONTAINER_ID:
        _run(["docker", "container", "rm", "-f", RUNTIME_INIT_CONTAINER_ID])
        RUNTIME_INIT_CONTAINER_ID = None


def _runtime_init_identity_check() -> None:
    """S10-089: inspect only the exact S10-005 container object, never an ambiguous name."""
    global RUNTIME_INIT_IDENTITY
    container_id = RUNTIME_INIT_CONTAINER_ID
    if not container_id:
        record("AT-11-13j: runtime-init（one-shotのみ）はroot(0:0)で実行される", False,
               "runtime-init container ID unavailable")
        return
    proc = _run(["docker", "container", "inspect", container_id, "--format", "{{json .}}"])
    payload: Dict[str, Any] = {}
    try:
        payload = json.loads(proc.stdout) if proc.returncode == 0 else {}
    except json.JSONDecodeError:
        payload = {}
    state = payload.get("State") if isinstance(payload.get("State"), dict) else {}
    observed = {
        "object_type": "container",
        "container_id": payload.get("Id"),
        "name": payload.get("Name"),
        "Config.User": (payload.get("Config") or {}).get("User"),
        "State.Status": state.get("Status"),
        "State.ExitCode": state.get("ExitCode"),
        "State.OOMKilled": state.get("OOMKilled"),
        "State.Error": state.get("Error"),
        "Created": payload.get("Created"),
        "StartedAt": state.get("StartedAt"),
        "FinishedAt": state.get("FinishedAt"),
    }
    RUNTIME_INIT_IDENTITY = observed
    passed = (
        proc.returncode == 0
        and observed["container_id"] == container_id
        and observed["Config.User"] == "0:0"
        and observed["State.ExitCode"] == 0
        and observed["State.OOMKilled"] is False
        and observed["State.Error"] == ""
    )
    record("AT-11-13j: runtime-init（one-shotのみ）はroot(0:0)で実行される", passed,
           json.dumps(observed, ensure_ascii=False, sort_keys=True))
    _remove_retained_runtime_init()


def at11_13_container_identity_matrix(override_file: Path) -> None:
    bp_id = _get_container_id(override_file, "backend-public")
    bo_id = _get_container_id(override_file, "backend-operator")

    if bp_id:
        proc = _run(["docker", "exec", bp_id, "id", "-u"])
        record("AT-11-13a: backend-public実containerのeuidが10001", proc.stdout.strip() == "10001", proc.stdout)
        proc = _run(["docker", "exec", bp_id, "id", "-g"])
        record("AT-11-13b: backend-public実containerのegidが10001", proc.stdout.strip() == "10001", proc.stdout)
        proc = _run(["docker", "exec", bp_id, "id", "-G"])
        groups = proc.stdout.strip().split()
        record("AT-11-13c: backend-public実containerがsupplemental GID 20001を持つ", "20001" in groups, proc.stdout)
        # 注意: umaskはprocess単位の属性でありcontainer全体では共有されない。
        # `docker exec ... umask` は新規processを起動するため、Dockerfile CMDの
        # `sh -c "umask 0007 && exec ..."` が設定したumaskを継承しない
        # （最初のrunでこれを誤って0022と判定し、修正した）。実際に稼働している
        # PID 1（uvicorn、umask設定shellの子processとしてexecされている）の
        # umaskを/proc/1/status経由で確認する。
        proc = _run(["docker", "exec", bp_id, "sh", "-c", "cat /proc/1/status | grep -i Umask"])
        record("AT-11-13d: backend-public実PID1(uvicorn)のumaskが0007", "0007" in proc.stdout, proc.stdout)

        # 書込negative: publicはdata_runtime配下（logs/cache以外）に書けない
        proc = _run(["docker", "exec", bp_id, "sh", "-c", "touch /data_runtime/should_not_be_writable 2>&1; echo EXIT=$?"])
        record("AT-11-13e: backend-public実containerは/data_runtime直下へ書き込めない（read-only mount）",
               "EXIT=0" not in proc.stdout, proc.stdout)
        proc = _run(["docker", "exec", bp_id, "sh", "-c", "touch /data_runtime/logs/should_be_writable 2>&1; echo EXIT=$?"])
        record("AT-11-13f: backend-public実containerは/data_runtime/logsへ書き込める（narrow rw mount）",
               "EXIT=0" in proc.stdout, proc.stdout)
    else:
        record("AT-11-13a-f: backend-public container取得失敗のためskip", False, "container not found")

    if bo_id:
        proc = _run(["docker", "exec", bo_id, "id", "-u"])
        record("AT-11-13g: backend-operator実containerのeuidが10002", proc.stdout.strip() == "10002", proc.stdout)
        proc = _run(["docker", "exec", bo_id, "id", "-G"])
        groups = proc.stdout.strip().split()
        record("AT-11-13h: backend-operator実containerがsupplemental GID 20001を持つ", "20001" in groups, proc.stdout)
        proc = _run(["docker", "exec", bo_id, "sh", "-c", "touch /data_runtime/operator_can_write 2>&1; echo EXIT=$?"])
        record("AT-11-13i: backend-operator実containerは/data_runtimeへ書き込める（rw mount）",
               "EXIT=0" in proc.stdout, proc.stdout)
    else:
        record("AT-11-13g-i: backend-operator container取得失敗のためskip", False, "container not found")

    # runtime-initがrootであることの確認（one-shot initializerだけの例外）。
    # S10-005で確定したcontainer IDをtyped inspectするため、同名imageへの
    # Docker object fallbackは起こり得ない。
    _runtime_init_identity_check()


def _get_container_id(override_file: Path, service: str) -> Optional[str]:
    proc = _run(compose_cmd(override_file, ["ps", "-q", service]))
    cid = proc.stdout.strip().splitlines()
    return cid[0] if cid else None


def _wait_backend_public_settled(override_file: Path, timeout_s: int = 60) -> Tuple[bool, str]:
    """AT-11 #13の固定`time.sleep(3)`は、backend-publicの起動処理（避難場所・
    ハザードデータ読み込み等）が3秒を超えると、containerがまだ起動完了して
    いない状態でidentity matrixのdocker execを実行してしまい、AT-11-13a〜fの
    いずれか単発がランダムにFAILする既知の脆弱性を持つ（この待機時間の脆弱性
    自体は既にPhase 2-B.5報告書で開示済みで、コード側のfail-closed判定ロジック
    には影響しない）。tools/public_release/phase2b2_compose_boundary.py::
    wait_backend_public_ready()と同じ「実際にHTTP /healthが応答するまで
    poll」方式へ置き換え、固定sleepへの依存を除去する。"""
    bp_id = _get_container_id(override_file, "backend-public")
    if not bp_id:
        return False, "backend-public container not found"
    deadline = time.time() + timeout_s
    last_detail = ""
    while time.time() < deadline:
        r = _run(["docker", "exec", bp_id, "python", "-c",
                   "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"])
        if r.returncode == 0:
            return True, "backend-public /health reachable"
        last_detail = (r.stdout + r.stderr)[-300:]
        time.sleep(1)
    return False, last_detail


# ------------------------------------------------------------------
# P2B5-CX-007: Linux-native volume上でのpublished tree単独permission
# mutation matrix（`.publish.lock`のowner/group/mode単独変異）。
#
# data_runtimeはproduction上ではhost bind mountだが、macOS Docker Desktop
# はcontainer側numeric UIDをhost側ownershipへ正しく反映しない制約がある
# （実装報告書で開示済み）。この検証だけは、Linux-native filesystemを
# 持つDocker named volumeをdata_runtime代わりに使うことで、real Linux VPS
# のbind mount挙動と同等の数値ownership厳密性を確認する。
# ------------------------------------------------------------------

def linux_native_permission_matrix() -> None:
    volume_name = f"{PROJECT_NAME}-permtest-data-runtime"
    inner_script = REPO_ROOT / "tools" / "public_release" / "phase2b5_permission_matrix_inner.py"

    _run(["docker", "volume", "create", volume_name])
    try:
        proc = _run(
            [
                "docker", "run", "--rm",
                "--user", "0:0",
                "-v", f"{volume_name}:/data_runtime",
                "-v", f"{REPO_ROOT}/backend/app:/app/app:ro",
                # RUNTIME-MBTILES-GROUP-CONTRACT: flat mirror同期scriptの権限matrix用
                "-v", f"{REPO_ROOT}/scripts:/scripts:ro",
                "-v", f"{inner_script}:/perm_test.py:ro",
                "python:3.11-slim", "python3", "/perm_test.py",
            ],
            timeout=120,
        )
        summary_line = None
        for line in proc.stdout.splitlines():
            if line.strip().startswith("{") and '"results"' in line:
                summary_line = line.strip()
        if summary_line:
            summary = json.loads(summary_line)
            for r in summary["results"]:
                record(f"[P2B5-CX-007] {r['name']}", r["pass"], r.get("detail", ""))
        else:
            record(
                "P2B5-CX-007: Linux-native permission matrixのsummary取得",
                False,
                (proc.stdout + proc.stderr)[-1500:],
            )
    finally:
        rm_proc = _run(["docker", "volume", "rm", "-f", volume_name])
        record("P2B5-CX-007 cleanup: permission matrix用named volumeを削除", rm_proc.returncode == 0, (rm_proc.stdout + rm_proc.stderr)[-300:])
        recheck = _run(["docker", "volume", "ls", "-q", "--filter", f"name={volume_name}"])
        still = [l for l in recheck.stdout.splitlines() if l.strip()]
        record("P2B5-CX-007 cleanup: 残存0件を確認", len(still) == 0, f"still={still}")


def dp_n01_n03_real_container_mutation() -> None:
    """CODEX P2B5-CX-006（第3ラウンド）対応: DP-N01・DP-N03は従来raw
    compose文字列の静的比較のみで、mutated composeを実際にcontainerへ
    反映して対象operationをfail-closedにする検証がなかった。ここでは
    実際のbackend-public image（docker-compose.ymlのmount flag／group_add
    と等価な`docker run -v ...:ro`／`--group-add`）を直接操作し、
    1項目だけの変異が実際にpublicの書込／読取挙動を変えることを実container
    で確認する。named volume（macOS bind mount制約を回避するため）を使う。

    DP-N02（current末端の直接bind mount不在の確認）は「危険なpatternが
    存在しないことの静的確認」という性質上、実container mutationの
    対象化が本質的に難しいため、本ラウンドでも静的source確認のままである
    （negative_fixtures_compose()、正直な開示として報告書へ記載）。
    """
    image = "onhighground2-backend-public:latest"
    check_img = _run(["docker", "image", "inspect", image])
    if check_img.returncode != 0:
        record("DP-N01/DP-N03 real container mutation: backend-public imageが存在する", False, check_img.stderr[-500:])
        return

    # ── DP-N01: public /data_runtimeмountのro/rw ────────────────────────
    # 注意: /data_runtime root自体はmode 0750（group=leases_gidもr-xのみで
    # write不可）のため、「単純にroot直下へ書けるか」だけではro/rw mount
    # flagの差が現れない（file自体の権限が既にwriteを拒否するため）。
    # ro mount flagが提供する"file権限とは独立した"防御層としての価値を
    # 検証するため、public自身がowner（write bit付き、mode 0640）で
    # 所有するfileを対象にする。
    vol01 = f"{PROJECT_NAME}-dpn01-data-runtime"
    _run(["docker", "volume", "create", vol01])
    try:
        seed01 = _run(
            ["docker", "run", "--rm", "--user", "0:0", "-v", f"{vol01}:/data_runtime", image, "python3", "-c",
             "import os\n"
             "fd = os.open('/data_runtime/public_owned.txt', os.O_CREAT|os.O_WRONLY, 0o640)\n"
             "os.close(fd)\n"
             "os.chown('/data_runtime/public_owned.txt', 10001, 10001)\n"],
            timeout=30,
        )
        record("DP-N01 準備: public owner・write bit付きfileを用意する", seed01.returncode == 0,
               (seed01.stdout + seed01.stderr)[-300:])

        proc_ro = _run(
            ["docker", "run", "--rm", "--user", "10001:10001",
             "-v", f"{vol01}:/data_runtime:ro",
             image, "python3", "-c", "open('/data_runtime/public_owned.txt', 'w').write('x')"],
            timeout=30,
        )
        record(
            "DP-N01【実container】baseline: compose記載どおりmount flag=ro → 自身がowner（write bit付き）の"
            "fileであっても、ro mount自体がfile権限とは独立した防御層としてpublic実containerの書込を拒否する",
            proc_ro.returncode != 0, (proc_ro.stdout + proc_ro.stderr)[-500:],
        )
        proc_rw = _run(
            ["docker", "run", "--rm", "--user", "10001:10001",
             "-v", f"{vol01}:/data_runtime",
             image, "python3", "-c", "open('/data_runtime/public_owned.txt', 'w').write('x')"],
            timeout=30,
        )
        record(
            "DP-N01【実container・mutation】: mount flagから`:ro`を外す（実際のcompose変異と同値）→ "
            "public実containerでの/data_runtime書込が実際に成功してしまう（ro mountという防御層が失われる実証）",
            proc_rw.returncode == 0, (proc_rw.stdout + proc_rw.stderr)[-500:],
        )
    finally:
        _run(["docker", "volume", "rm", "-f", vol01])
        recheck = _run(["docker", "volume", "ls", "-q", "--filter", f"name={vol01}"])
        still = [l for l in recheck.stdout.splitlines() if l.strip()]
        record("DP-N01 cleanup: 実container検証用named volume残存0件", len(still) == 0, f"still={still}")

    # ── DP-N03: public group_add(20001)の有無 ───────────────────────────
    vol03 = f"{PROJECT_NAME}-dpn03-data-runtime"
    _run(["docker", "volume", "create", vol03])
    try:
        # root権限でversion tree＋currentをP2B5-CX-007修正後の正規schemeで用意する
        # （root: operator:leases_gid mode 0750, version tree: leases_gid mode 640/750）。
        seed_script = (
            "import os\n"
            "OP,LG=10002,20001\n"
            "os.chown('/data_runtime', OP, LG); os.chmod('/data_runtime', 0o750)\n"
            "d='/data_runtime/versions/20260101T000000Z-deadbeef/backend/hazard'\n"
            "os.makedirs(d, mode=0o750, exist_ok=True)\n"
            "fp=d+'/f.geojson'\n"
            "fd=os.open(fp, os.O_CREAT|os.O_WRONLY, 0o640); os.write(fd, b'{}'); os.close(fd)\n"
            "for dp,_,fns in os.walk('/data_runtime/versions'):\n"
            "    os.chown(dp, OP, LG)\n"
            "    for fn in fns: os.chown(os.path.join(dp,fn), OP, LG)\n"
            "os.symlink('versions/20260101T000000Z-deadbeef', '/data_runtime/current')\n"
        )
        seed = _run(["docker", "run", "--rm", "--user", "0:0", "-v", f"{vol03}:/data_runtime",
                     image, "python3", "-c", seed_script], timeout=30)
        record("DP-N03 準備: root権限でversion tree/current(正規scheme)を用意する", seed.returncode == 0,
               (seed.stdout + seed.stderr)[-500:])

        read_script = "open('/data_runtime/current/backend/hazard/f.geojson').read()"
        proc_with_group = _run(
            ["docker", "run", "--rm", "--user", "10001:10001", "--group-add", "20001",
             "-v", f"{vol03}:/data_runtime:ro", image, "python3", "-c", read_script],
            timeout=30,
        )
        record(
            "DP-N03【実container】baseline: compose記載どおりgroup_add(20001)あり → "
            "public実containerがcurrent配下を実際にreadできる",
            proc_with_group.returncode == 0, (proc_with_group.stdout + proc_with_group.stderr)[-500:],
        )
        proc_without_group = _run(
            ["docker", "run", "--rm", "--user", "10001:10001",
             "-v", f"{vol03}:/data_runtime:ro", image, "python3", "-c", read_script],
            timeout=30,
        )
        record(
            "DP-N03【実container・mutation】: group_add(20001)を外す（実際のcompose変異と同値）→ "
            "public実containerでのcurrent配下readが実際に失敗する（設定除去の実害の実証）",
            proc_without_group.returncode != 0, (proc_without_group.stdout + proc_without_group.stderr)[-500:],
        )
    finally:
        _run(["docker", "volume", "rm", "-f", vol03])
        recheck = _run(["docker", "volume", "ls", "-q", "--filter", f"name={vol03}"])
        still = [l for l in recheck.stdout.splitlines() if l.strip()]
        record("DP-N03 cleanup: 実container検証用named volume残存0件", len(still) == 0, f"still={still}")


def dp_n02_real_container_mutation(run_tmp: Path) -> None:
    """CODEX P2B5-CX-006（第4ラウンド）対応: DP-N02は従来「現行composeに
    leaf mount文字列が存在しないこと」を確認する静的検査のみで、mutated
    Composeを実際にcontainerへ反映して危険性を発火させていなかった。

    `current`の末端（解決済みsymlink target）を直接bind mountすると、
    Dockerのbind mountはmount namespace構築時に一度だけsymlinkを解決して
    その時点のtarget directoryをmountするため、後からhost側で`current`を
    re-pointしても、既存container内のleaf mountは古いversionを指したまま
    になる（staleな内容を配信し続ける）。これはhost bind mount本来の
    挙動（`/data_runtime`全体をmountしてcontainer内でsymlinkを毎回動的に
    解決する現行composeの方式）とは異なる、危険な代替設定である。

    named volumeではなくhost tmp directory（実docker-composeのbind mount
    と同じ機構）を使う。
    """
    dr = run_tmp / "dpn02_data_runtime"
    (dr / "versions" / "v1" / "backend" / "hazard").mkdir(parents=True, exist_ok=True)
    (dr / "versions" / "v2" / "backend" / "hazard").mkdir(parents=True, exist_ok=True)
    (dr / "versions" / "v1" / "backend" / "hazard" / "f.geojson").write_text('{"marker":"v1"}')
    (dr / "versions" / "v2" / "backend" / "hazard" / "f.geojson").write_text('{"marker":"v2"}')
    current_link = dr / "current"
    if current_link.exists() or current_link.is_symlink():
        current_link.unlink()
    current_link.symlink_to("versions/v1")

    image = "onhighground2-backend-public:latest"
    container_name = f"{PROJECT_NAME}-dpn02-leaf"
    _run(["docker", "rm", "-f", container_name])
    try:
        up = _run(
            ["docker", "run", "-d", "--name", container_name,
             "-v", f"{dr}:/data_runtime:ro",
             "-v", f"{dr}/current:/leaf_mount:ro",  # DP-N02の変異そのもの: current末端の直接bind mount
             image, "sleep", "60"],
        )
        record("DP-N02 準備: leaf mount付きcontainerの起動が成功する", up.returncode == 0, (up.stdout + up.stderr)[-500:])
        if up.returncode != 0:
            return

        leaf_before = _run(["docker", "exec", container_name, "cat", "/leaf_mount/backend/hazard/f.geojson"])
        record("DP-N02【実container】baseline: leaf mount経由でv1の内容を読める", leaf_before.stdout.strip() == '{"marker":"v1"}',
               leaf_before.stdout)

        # host側でcurrentをv2へ実際に再publish相当でrepointする
        current_link.unlink()
        current_link.symlink_to("versions/v2")

        leaf_after = _run(["docker", "exec", container_name, "cat", "/leaf_mount/backend/hazard/f.geojson"])
        record(
            "DP-N02【実container・mutation】: current末端の直接bind mountは、host側でcurrentをv2へ"
            "repointした後もv1のまま固まって取り残される（stale配信の実害の実証。mount namespace構築時に"
            "symlinkが一度だけ解決されるため）",
            leaf_after.stdout.strip() == '{"marker":"v1"}', leaf_after.stdout,
        )

        normal_after = _run(["docker", "exec", container_name, "cat", "/data_runtime/current/backend/hazard/f.geojson"])
        record(
            "DP-N02【対比】: 現行composeと同じ全体mount（/data_runtime）経由でcurrentを辿ると、"
            "同じrepoint後に正しくv2を観測できる（leaf mountの危険性との対比）",
            normal_after.stdout.strip() == '{"marker":"v2"}', normal_after.stdout,
        )
    finally:
        rm = _run(["docker", "rm", "-f", container_name])
        record("DP-N02 cleanup: leaf mount検証用containerを削除", rm.returncode == 0, (rm.stdout + rm.stderr)[-300:])


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------

def main() -> int:
    global RUNTIME_INIT_CONTAINER_ID, RUNTIME_INIT_IDENTITY, _GLOBAL_FAIL_FAST_ENABLED, _FORMAL_FAILURE_OBSERVED
    print(f"run tag: {_RUN_TAG}")
    print(f"project name: {PROJECT_NAME}")

    if not check_docker_available():
        print("Docker daemon not available — aborting.")
        return 1

    _GLOBAL_FAIL_FAST_ENABLED = True
    _FORMAL_FAILURE_OBSERVED = False
    RUNTIME_INIT_CONTAINER_ID = None
    RUNTIME_INIT_IDENTITY = {}
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b5_run_") as run_tmp:
        run_tmp_path = Path(run_tmp)
        override_file: Optional[Path] = None
        formal_failed = False
        try:
            negative_fixtures_compose(run_tmp_path)
            override_file = build_override(run_tmp_path)

            # 1. runtime-init（one-shot、隔離named volume + 隔離data_runtime）
            runtime_init_name = f"{PROJECT_NAME}-runtime-init-once"
            proc = _run(
                compose_cmd(override_file, ["run", "--no-deps", "--name", runtime_init_name, "runtime-init"]),
                timeout=120,
            )
            runtime_id_proc = _run(["docker", "container", "inspect", runtime_init_name, "--format", "{{.Id}}"])
            RUNTIME_INIT_CONTAINER_ID = runtime_id_proc.stdout.strip() if runtime_id_proc.returncode == 0 else None
            record(
                "runtime-init（隔離stack）が成功する",
                proc.returncode == 0 and bool(RUNTIME_INIT_CONTAINER_ID),
                (proc.stdout + proc.stderr + runtime_id_proc.stderr)[-1500:],
            )

            # 2. inner testsをbackend-operator image内で実行（AT-11 1-12,14 + DP-N大半）
            inner_test_src = REPO_ROOT / "tools" / "public_release" / "phase2b5_inner_tests.py"
            proc = _run(compose_cmd(override_file, inner_runner_args(inner_test_src)), timeout=300)
            print(proc.stdout)
            if proc.stderr:
                print(proc.stderr, file=sys.stderr)
            inner_summary_line = None
            for line in proc.stdout.splitlines():
                if line.strip().startswith("{") and '"total"' in line:
                    inner_summary_line = line.strip()
            inner_ok, inner_summary, inner_detail = validate_inner_summary(proc.returncode, inner_summary_line)
            if not inner_ok or inner_summary is None:
                record("inner tests fail-fast contract", False, inner_detail)

            for r in inner_summary["results"]:
                record(f"[inner] {r['name']}", r["pass"], r.get("detail", ""))

            # 3. AT-11 #13: backend-public/backend-operatorを起動して実containerで検証
            # 明示的にbackend-public/backend-operatorだけを指定する。
            # 引数なしのupは、fixed container_nameを持つ他service（frontend,
            # osrm-walking, martin等）も含む全serviceを起動しようとし、
            # 実運用中のonhighground2 stackと名前が衝突する（実際に発生し、
            # 本toolの前回runで検出・修正した）。
            up_cmd = ["--profile", "operator", "up", "-d", "--no-deps", "backend-public", "backend-operator"]
            proc = _run(compose_cmd(override_file, up_cmd), timeout=300)
            record("backend-public/backend-operator（隔離stack）起動", proc.returncode == 0, (proc.stdout + proc.stderr)[-1500:])
            if proc.returncode == 0:
                settled_ok, settled_detail = _wait_backend_public_settled(override_file)
                record("backend-public（隔離stack）がidentity matrix開始前にhealthyになる", settled_ok, settled_detail)
                at11_13_container_identity_matrix(override_file)

            # 4. P2B5-CX-007: Linux-native volumeでのpublished tree単独permission matrix
            linux_native_permission_matrix()

            # 4b. P2B5-CX-006（第3〜4ラウンド）: DP-N01/N02/N03の実container mutation検証
            dp_n01_n03_real_container_mutation()
            dp_n02_real_container_mutation(run_tmp_path)

            # 5. cleanup negative control
            cleanup_negative_control()
        except FormalCaseFailure:
            formal_failed = True
        finally:
            if override_file is not None:
                cleanup_stack(override_file, record_results=not formal_failed)
            else:
                _remove_retained_runtime_init()

        _GLOBAL_FAIL_FAST_ENABLED = False
        return _finish(run_tmp_path, override_file)


def _finish(run_tmp_path: Path, override_file: Path) -> int:
    failed = [r for r in RESULTS if not r["pass"]]
    print()
    print(f"TOTAL: {len(RESULTS)}  PASS: {len(RESULTS) - len(failed)}  FAIL: {len(failed)}")
    print(f"exit code: {1 if failed else 0}")
    if failed:
        print("FAILED CHECKS:")
        for r in failed:
            print(f"  - {r['name']}")
    # Phase 2-B.3(P2B3-CX-003)の踏襲: 検証evidenceはrepository内へ書き込まず
    # OS一時領域へ出力する。
    summary_path = Path(tempfile.gettempdir()) / f"ohg2_phase2b5_summary_{_RUN_TAG}.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump({"run_tag": _RUN_TAG, "results": RESULTS}, f, ensure_ascii=False, indent=2)
    print(f"summary written to (repository外): {summary_path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
tools/public_release/phase2b1_image_inspect.py

Phase 2-B.1 の実物Docker image検査（AT-02・AT-12）を実行する、
自動再実行可能な検査script。

tasks/public-release/github_public_audit_phase2a_remediation_plan.md 第5.6・5.7節
（2-B.1）、および
tasks/public-release/phase2b1_claude_implementation_instruction.md 3.3・3.4・4節の
AT-02・AT-12に対応する。

実行内容（すべて実際に `docker build` / `docker run` を伴う。mock・静的レビューのみ
での代替はしない）:
  1. public image（backend/Dockerfile）・operator image（backend/Dockerfile.operator）
     の実物build
  2. public imageのDocker CLI・Docker SDK系Pythonパッケージ・admin/simulation/
     layer_types_apiモジュール・dummy secret markerの不在検査
  3. public ASGI entrypointのsmoke test（コンテナ内でuvicorn起動→/health）
  4. operator関連環境変数を与えてもpublic管理routeが増えないことのimageレベル確認
  5. operator imageのDocker CLI保持確認、dummy secretでの起動成功、
     secret未設定/空/空白での非0終了（fail-closed）
  6. AT-12: 実build contextに対するdummy marker canary build
     （`.env`・runtime data・admin moduleがpublic build contextへ送信されないことを
     canary Dockerfileで再現的に確認する。operator側は同じmoduleが正しく
     到達可能であることの陽性対照として確認する）
  7. image inspect・package inventory・filesystem inventoryのartifactを保存

事前条件: Dockerデーモンが起動していること。実秘密・既存credential・VPSの`.env`は
一切使用しない（本scriptはdummy markerのみを使用する）。

使い方:
    python3 tools/public_release/phase2b1_image_inspect.py

終了コード: 全項目PASSなら0、1件でもFAILがあれば1。
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Dockerfile単位の.dockerignore（<Dockerfile名>.dockerignore）はBuildKitでのみ
# 有効なため、明示的に有効化する（第5.6節）。
os.environ.setdefault("DOCKER_BUILDKIT", "1")

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
EVIDENCE_DIR = REPO_ROOT / "tasks" / "public-release" / "evidence" / "phase2b1"

# 一意tag（P2B1-CX指示: 「Claudeの既存image/tagだけに依存せず、今回用の一意tagを
# 使う」対応）。実行のたびに異なるtagを使うことで、古いtag・古いimage layerを
# 誤って再利用したまま合否判定してしまうことを防ぐ。
_RUN_TAG = os.environ.get("OHG2_PHASE2B1_RUN_TAG") or datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
PUBLIC_IMAGE_TAG = f"ohg2-phase2b1-public-fix-{_RUN_TAG}:latest"
OPERATOR_IMAGE_TAG = f"ohg2-phase2b1-operator-fix-{_RUN_TAG}:latest"

DUMMY_SECRET_MARKER = "OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE"

# public imageに存在してはならないファイル（admin/simulation/layer_types/
# Docker操作を行うservice、operator entrypoint自身）
#
# P2B1-CX-001/CX-003（CODEX独立検証、2026-08-10）: 当初このdenylistは
# app/api/simulation.py（router）のみを含み、app/models/simulation.py と
# app/services/simulation_service.py（router実装が依存するmodel/service本体）
# が漏れていたため、public final filesystemと保存layer双方への混入を
# 自動検出できていなかった。両ファイルを追加する。
FORBIDDEN_PUBLIC_FILES = [
    "app/api/admin.py",
    "app/api/admin_config.py",
    "app/api/admin_datasets.py",
    "app/api/admin_upload.py",
    "app/api/layer_types_api.py",
    "app/api/simulation.py",
    "app/models/simulation.py",
    "app/services/simulation_service.py",
    "app/services/pipeline_service.py",
    "app/services/job_manager.py",
    "app/services/admin_hazard_service.py",
    "app/services/config_change_notifier.py",
    "app_operator.py",
    "Dockerfile.operator",
]

# Docker SDK / Docker操作関連のPython packageとして検出してはならない名前
FORBIDDEN_PY_PACKAGES = ["docker", "python-on-whales", "aiodocker", "docker-py"]

# tar member名の末尾一致で判定するための正規化ヘルパー


def _forbidden_path_hit(member_name: str, forbidden_paths: List[str]) -> Optional[str]:
    """tar member名（例: 'app/app/models/simulation.py'）が禁止pathのいずれかで
    終わっているかを判定する。WORKDIR /app のため 'app/<path>' または
    'app/app/<path>' のいずれの形でも一致するよう、末尾一致で判定する。"""
    name = member_name[2:] if member_name.startswith("./") else member_name
    for fp in forbidden_paths:
        if name == fp or name.endswith("/" + fp):
            return fp
    return None


def _is_ds_store(member_name: str) -> bool:
    name = member_name[2:] if member_name.startswith("./") else member_name
    return name.rsplit("/", 1)[-1] == ".DS_Store"

RESULTS: List[Dict[str, Any]] = []


def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def record(name: str, passed: bool, detail: str = "", command: Optional[List[str]] = None) -> None:
    RESULTS.append(
        {
            "name": name,
            "pass": bool(passed),
            "detail": detail[-4000:],
            "command": " ".join(command) if command else None,
        }
    )
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}")
    if not passed and detail:
        print(f"        detail: {detail[:500]}")


def check_docker_available() -> bool:
    proc = _run(["docker", "info"])
    ok = proc.returncode == 0
    record("docker daemon available", ok, proc.stdout + proc.stderr, ["docker", "info"])
    return ok


# ------------------------------------------------------------------
# 1. 実物image build
# ------------------------------------------------------------------

def build_image(tag: str, dockerfile: str) -> bool:
    # -f はdocker CLI呼び出し時のcwdbasisで解決されるため、build context相対の
    # 相対pathではなく絶対pathを渡す（cwd起因の取り違えを避けるため）。
    # --no-cache: 一意tagと合わせ、古いlayer cacheを再利用したまま合否判定
    # してしまうことを避ける（P2B1-CX指示対応）。
    cmd = [
        "docker", "build",
        "--no-cache",
        "-f", str(BACKEND_DIR / dockerfile),
        "-t", tag,
        str(BACKEND_DIR),
    ]
    start = time.time()
    proc = _run(cmd, cwd=str(REPO_ROOT))
    elapsed = time.time() - start
    ok = proc.returncode == 0
    record(
        f"docker build succeeds: {tag} ({dockerfile}, {elapsed:.0f}s)",
        ok,
        proc.stdout[-3000:] + "\n" + proc.stderr[-3000:],
        cmd,
    )
    (EVIDENCE_DIR / f"build_log_{Path(dockerfile).name}.txt").write_text(
        proc.stdout + "\n" + proc.stderr, encoding="utf-8"
    )
    return ok


# ------------------------------------------------------------------
# 2〜5. image内部検査
# ------------------------------------------------------------------

def image_exec(tag: str, args: List[str], env: Optional[Dict[str, str]] = None, timeout: int = 60) -> subprocess.CompletedProcess:
    cmd = ["docker", "run", "--rm"]
    if env:
        for k, v in env.items():
            cmd += ["-e", f"{k}={v}"]
    cmd += ["--entrypoint", args[0], tag] + args[1:]
    return _run(cmd, timeout=timeout)


def get_image_id(tag: str) -> str:
    proc = _run(["docker", "inspect", "--format={{.Id}}", tag])
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _docker_rmi(tag: str) -> subprocess.CompletedProcess:
    return _run(["docker", "rmi", "-f", tag])


def _docker_images_query(tag: str) -> subprocess.CompletedProcess:
    return _run(["docker", "images", "-q", tag])


def _cleanup_tag_and_verify(
    tag: str,
    rmi_fn=_docker_rmi,
    query_fn=_docker_images_query,
) -> Tuple[bool, str]:
    """1つのrun tagについて、rmi実行とその結果検証をfail-closedに行う。

    CODEX限定再検証第4回（2026-08-10）P2B1-CX-003指摘への対応: 旧実装は
    `docker rmi`のreturn codeを確認せず、`docker images -q`もreturn code
    非0（＝クエリ自体の失敗）と正常な空stdout（＝tag不在）を区別していなかった。
    そのためDocker daemon停止等でクエリ自体が失敗しても「tagは存在しない」と
    誤判定し、cleanup検証がfail-openになっていた（DOCKER_HOST不正等での
    独立negative controlで再現済み）。

    rmi_fn/query_fnを差し替え可能にしているのは、self-testで実Dockerを
    使わずfakeのCompletedProcessを注入し、rmi失敗／クエリ失敗／削除後残存／
    正常完了の4経路をロジック単体で検証できるようにするため
    （`self_test_cleanup_verification_logic`参照）。

    戻り値: (ok, detail)
      ok=True となるのは次のいずれかの場合のみ。
        - rmi前の存在照会が成功し、かつtagがそもそも存在しなかった
          （build失敗等でtag未作成、cleanup不要）
        - rmi前の存在照会が成功してtagが存在し、rmiが成功（return code 0）し、
          rmi後の存在照会も成功してtagが実在しないことを確認できた
      次はいずれもok=Falseとする（クエリ失敗を「存在しない」とみなさない）。
        - rmi前・rmi後いずれかの存在照会自体が失敗（return code非0）
        - rmiのreturn codeが非0
        - rmi後の存在照会でtagがなお存在する
    """
    pre = query_fn(tag)
    if pre.returncode != 0:
        return False, (
            f"pre-cleanup existence query failed (rc={pre.returncode}); "
            f"cannot verify absence — treated as FAIL, not as 'tag absent'. "
            f"stderr={pre.stderr[-500:]}"
        )
    if not pre.stdout.strip():
        return True, f"tag did not exist before cleanup (nothing to remove): {tag}"

    rmi = rmi_fn(tag)
    if rmi.returncode != 0:
        return False, (
            f"docker rmi -f failed (rc={rmi.returncode}); "
            f"stdout={rmi.stdout[-500:]} stderr={rmi.stderr[-500:]}"
        )

    post = query_fn(tag)
    if post.returncode != 0:
        return False, (
            f"post-cleanup existence query failed (rc={post.returncode}); "
            f"cannot verify absence — treated as FAIL, not as 'tag absent'. "
            f"stderr={post.stderr[-500:]}"
        )
    if post.stdout.strip():
        return False, f"tag still exists after docker rmi -f: {post.stdout.strip()}"

    return True, f"tag removed and absence verified: {tag}"


def cleanup_run_tags_and_verify() -> None:
    """今回のrun専用tag（public/operator）を無条件でcleanupし、削除結果を
    fail-closedに検証する（`_cleanup_tag_and_verify`参照）。

    CODEX限定再検証第3回（2026-08-10）P2B1-CX-003指摘への対応: `build_image()`は
    `docker build`成功（＝Docker daemon上にtagが実在する状態）の後、`record()`や
    evidence `write_text()`を経てから戻り値を返す。この戻り値区間で例外が
    発生すると、呼び出し元の成功flag（`public_built`/`operator_built`）への
    代入が完了しないため、flag真偽に依存するcleanup条件（`if public_built: ...`）
    が偽のままcleanupされない経路が実測された。一意run tagはユーザー既存資産と
    衝突しないため、flagの真偽に関わらず常にcleanupを試みる。
    """
    for tag in (PUBLIC_IMAGE_TAG, OPERATOR_IMAGE_TAG):
        ok, detail = _cleanup_tag_and_verify(tag)
        record(
            f"cleanup: run tag {tag} が確実に削除されたことを検証できる",
            ok,
            detail,
        )


def self_test_cleanup_verification_logic() -> None:
    """P2B1-CX-003第4回negative control（CODEX限定再検証、2026-08-10）。

    `_cleanup_tag_and_verify`のfail-closedロジックを、実Dockerを使わず
    fakeの`subprocess.CompletedProcess`を注入した4パターンで検証する。
    rmi失敗・存在照会失敗（検証不能）・削除後残存の3経路はFAIL、
    正常なtag削除完了の1経路だけPASSになることを確認する
    （CODEX指摘: クエリ自体の失敗をtag不存在と誤判定しない）。
    """

    def _fake(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)

    scenarios = [
        (
            "rmi失敗はFAILと判定する",
            [_fake(0, "sha256:existing-image-id"), _fake(1, "", "Error: unable to remove image")],
            False,
        ),
        (
            "削除前の存在照会失敗（検証不能）はFAILと判定する（不在と誤判定しない）",
            [_fake(1, "", "Cannot connect to the Docker daemon")],
            False,
        ),
        (
            "削除後の存在照会失敗（検証不能）はFAILと判定する（不在と誤判定しない）",
            [_fake(0, "sha256:existing-image-id"), _fake(0, ""), _fake(1, "", "Cannot connect to the Docker daemon")],
            False,
        ),
        (
            "rmi成功後もtagが残存していればFAILと判定する",
            [_fake(0, "sha256:existing-image-id"), _fake(0, ""), _fake(0, "sha256:still-here")],
            False,
        ),
        (
            "rmi前からtag不在ならcleanup不要としてPASSと判定する",
            [_fake(0, "")],
            True,
        ),
        (
            "rmi成功かつ削除後不在確認ができればPASSと判定する",
            [_fake(0, "sha256:existing-image-id"), _fake(0, ""), _fake(0, "")],
            True,
        ),
    ]

    all_ok = True
    details = []
    for label, side_effects, expected_ok in scenarios:
        # rmi_fn/query_fnは同じiteratorから順に消費させることで、
        # 「pre-query → rmi → post-query」という実呼び出し順序どおりに
        # fake結果を割り当てる。
        it = iter(side_effects)

        def _query_fn(_tag, _it=it):
            return next(_it)

        def _rmi_fn(_tag, _it=it):
            return next(_it)

        actual_ok, detail = _cleanup_tag_and_verify(
            "ohg2-phase2b1-selftest-cleanup-logic:fake",
            rmi_fn=_rmi_fn,
            query_fn=_query_fn,
        )
        scenario_pass = actual_ok == expected_ok
        all_ok = all_ok and scenario_pass
        details.append(f"[{'OK' if scenario_pass else 'MISMATCH'}] {label}: expected_ok={expected_ok} actual_ok={actual_ok} detail={detail}")

    record(
        "self-test (P2B1-CX-003): cleanup検証ロジックがrmi失敗/クエリ失敗/削除後残存をFAIL、正常完了だけPASSと判定する",
        all_ok,
        "\n".join(details),
    )


def self_test_cleanup_survives_build_exception() -> None:
    """P2B1-CX-003第3回negative control（CODEX限定再検証、2026-08-10）。

    `build_image()`相当の処理がDocker tag作成成功後・戻り値return前に
    例外を送出しても、`main()`のfinally節が成功flagに依存せず無条件で
    cleanup・検証を行えることを、軽量な実imageを使って確認する
    （実際にDocker daemonへtagを作成する必要があるため、synthetic tar
    fixtureのみで完結する`self_test_layer_scanner()`とは別に、
    `check_docker_available()`確認後・public/operator本buildの前に実行する）。
    """
    test_tag = f"ohg2-phase2b1-selftest-cleanup-{_RUN_TAG}:latest"
    _run(["docker", "rmi", "-f", test_tag])  # 前回実行の残骸があれば念のため除去

    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b1_selftest_cleanup_") as tmp:
        dockerfile_path = Path(tmp) / "Dockerfile"
        dockerfile_path.write_text("FROM busybox\n", encoding="utf-8")

        cleanup_ran = False
        try:
            try:
                proc = _run(["docker", "build", "-f", str(dockerfile_path), "-t", test_tag, tmp])
                if proc.returncode != 0:
                    record(
                        "self-test (P2B1-CX-003): cleanup negative control用test imageのbuild成功",
                        False,
                        proc.stdout + proc.stderr,
                    )
                    return
                # tag作成完了直後・成功flag代入前に例外を送出する状況を再現する
                # （build_image()内のrecord()/write_text()が例外を送出するケースの模擬）。
                raise RuntimeError("synthetic exception after tag creation, before return (self-test)")
            finally:
                # main()のfinallyと同じ「成功flagに依存しない無条件cleanup」を検証する。
                _run(["docker", "rmi", "-f", test_tag])
                cleanup_ran = True
        except RuntimeError:
            pass  # 合成例外は想定どおりの発火なので握りつぶす（self-testの一部）

    post = _docker_images_query(test_tag)
    # クエリ自体が失敗した場合は「存在しない」とみなさず検証失敗として扱う
    # （CODEX指摘: query失敗をtag不在と誤判定しない、第11.5節対応）。
    query_ok = post.returncode == 0
    still_exists = bool(post.stdout.strip()) if query_ok else True
    record(
        "self-test (P2B1-CX-003): build tag作成後・return前の例外でも無条件cleanupが機能する",
        cleanup_ran and query_ok and not still_exists,
        f"cleanup_ran={cleanup_ran} query_ok={query_ok} still_exists={still_exists}",
    )


def inspect_public_image() -> None:
    tag = PUBLIC_IMAGE_TAG
    image_id = get_image_id(tag)
    print(f"    public image ID: {image_id}")

    # --- Docker CLI 0件 ---
    proc = image_exec(tag, ["sh", "-c", "which docker; echo EXIT:$?"])
    docker_cli_absent = ("EXIT:0" not in proc.stdout)
    record(
        "public image: Docker CLI 実行ファイル 0件",
        docker_cli_absent,
        proc.stdout + proc.stderr,
        ["docker", "run", "--entrypoint", "sh", tag, "-c", "which docker"],
    )

    # --- Docker SDK 関連 Python package 0件 ---
    proc = image_exec(tag, ["pip", "list", "--format=json"])
    forbidden_found = []
    if proc.returncode == 0:
        try:
            pkgs = {p["name"].lower() for p in json.loads(proc.stdout)}
        except Exception:
            pkgs = set()
        forbidden_found = [p for p in FORBIDDEN_PY_PACKAGES if p.lower() in pkgs]
    record(
        "public image: Docker SDK 関連 Python package 0件",
        proc.returncode == 0 and not forbidden_found,
        f"forbidden_found={forbidden_found}\n{proc.stdout[-1500:]}",
        ["docker", "run", "--entrypoint", "pip", tag, "list"],
    )
    (EVIDENCE_DIR / "public_pip_list.json").write_text(proc.stdout, encoding="utf-8")

    # --- Docker socket mount / VOLUME 0件（image config） ---
    proc = _run(["docker", "inspect", tag])
    volumes_ok = False
    inspect_json = "[]"
    if proc.returncode == 0:
        inspect_json = proc.stdout
        try:
            data = json.loads(proc.stdout)
            cfg = data[0].get("Config", {}) if data else {}
            volumes = cfg.get("Volumes") or {}
            volumes_ok = not any("docker.sock" in v for v in volumes.keys())
            volumes_ok = volumes_ok and (len(volumes) == 0)
        except Exception:
            volumes_ok = False
    record(
        "public image: Docker socket VOLUME宣言 0件",
        proc.returncode == 0 and volumes_ok,
        proc.stdout[-1500:],
        ["docker", "inspect", tag],
    )
    (EVIDENCE_DIR / "public_docker_inspect.json").write_text(inspect_json, encoding="utf-8")

    # --- final filesystem 全体inventory（scanned file count記録用） ---
    all_files_proc = image_exec(tag, ["find", "/app", "-type", "f"])
    all_files = [l for l in all_files_proc.stdout.splitlines() if l.strip()]
    print(f"    public image final filesystem scanned file count: {len(all_files)}")

    # --- operator/admin/simulation module 0件（filesystem inventory） ---
    # find の argv を直接渡す（sh -c 経由だと "(" "）" がshellのsubshell構文と
    # 衝突しfindがsyntax errorで終了してしまうため、shellを経由しない）。
    find_cmd = ["find", "/app", "-type", "f", "("]
    for i, f in enumerate(FORBIDDEN_PUBLIC_FILES):
        if i:
            find_cmd.append("-o")
        find_cmd += ["-path", f"/app/{f}"]
    find_cmd.append(")")
    proc = image_exec(tag, find_cmd)
    found_files = [l for l in proc.stdout.splitlines() if l.strip()]
    record(
        f"public image final filesystem: operator/admin/simulation module 0件 (scanned {len(all_files)} files, hits={len(found_files)})",
        proc.returncode == 0 and not found_files,
        f"found={found_files}",
        find_cmd,
    )
    (EVIDENCE_DIR / "public_filesystem_denylist_scan.txt").write_text(proc.stdout, encoding="utf-8")

    # --- .DS_Store 0件（final filesystem、任意階層、P2B1-CX-001対応） ---
    ds_store_proc = image_exec(tag, ["find", "/app", "-name", ".DS_Store"])
    ds_store_hits = [l for l in ds_store_proc.stdout.splitlines() if l.strip()]
    record(
        f"public image final filesystem: .DS_Store 0件 (hits={len(ds_store_hits)})",
        ds_store_proc.returncode == 0 and not ds_store_hits,
        f"found={ds_store_hits}",
        ["find", "/app", "-name", ".DS_Store"],
    )

    # --- dummy secret marker 0件 ---
    proc = image_exec(
        tag,
        ["sh", "-c", f"grep -rl '{DUMMY_SECRET_MARKER}' /app 2>/dev/null; echo DONE"],
    )
    marker_found = [l for l in proc.stdout.splitlines() if l.strip() and l.strip() != "DONE"]
    record(
        "public image: dummy secret marker 0件",
        not marker_found,
        f"found={marker_found}",
    )

    # --- public ASGI smoke test ---
    smoke_public(tag)

    # --- operator環境変数を与えてもpublic route集合が変わらない（imageレベル） ---
    env_operator_routes(tag)

    # --- docker save 全保存layer検査（P2B1-CX-001/CX-003対応） ---
    scan_all_saved_layers(tag)


def smoke_public(tag: str) -> None:
    container = "ohg2-phase2b1-public-smoke"
    _run(["docker", "rm", "-f", container])
    run_cmd = ["docker", "run", "-d", "--name", container, tag]
    proc = _run(run_cmd)
    if proc.returncode != 0:
        record("public image: ASGI smoke (container start)", False, proc.stdout + proc.stderr, run_cmd)
        return
    try:
        healthy = False
        last_detail = ""
        for _ in range(30):
            time.sleep(2)
            check = _run(["docker", "exec", container, "curl", "-sf", "http://localhost:8000/health"])
            last_detail = check.stdout + check.stderr
            if check.returncode == 0:
                healthy = True
                break
        record(
            "public image: ASGI smoke test (/health reachable inside container)",
            healthy,
            last_detail,
            ["docker", "exec", container, "curl", "-sf", "http://localhost:8000/health"],
        )
        logs = _run(["docker", "logs", container])
        (EVIDENCE_DIR / "public_smoke_container_logs.txt").write_text(
            logs.stdout + logs.stderr, encoding="utf-8"
        )
    finally:
        _run(["docker", "rm", "-f", container])


def env_operator_routes(tag: str) -> None:
    script = (
        "import json,app_public;"
        "print(json.dumps(sorted({getattr(r,'path',None) for r in app_public.app.routes})))"
    )
    baseline = image_exec(tag, ["python", "-c", script])
    with_operator_env = image_exec(
        tag,
        ["python", "-c", script],
        env={
            "OPERATOR_AUTH_SECRET": DUMMY_SECRET_MARKER,
            "OPERATOR_ENABLED": "true",
            "OPERATOR_LISTEN_HOST": "0.0.0.0",
            "OPERATOR_PORT": "8100",
        },
        timeout=120,
    )
    # stdoutにはlogging.StreamHandler(sys.stdout)によるtimestamp付きログ行が
    # 混在する（実行のたびにtimestampが変わるため単純な全文比較はできない）。
    # 比較対象は最終行のJSON route一覧のみとする（tests/test_phase2b1_entrypoint_boundary.py
    # の_run_introspectと同じ方針）。
    def _last_json_line(stdout: str) -> str:
        lines = [l for l in stdout.strip().splitlines() if l.strip()]
        return lines[-1] if lines else ""

    baseline_last = _last_json_line(baseline.stdout)
    with_env_last = _last_json_line(with_operator_env.stdout)
    ok = (
        baseline.returncode == 0
        and with_operator_env.returncode == 0
        and baseline_last == with_env_last
        and baseline_last != ""
    )
    record(
        "public image: operator env var 付与前後でroute一覧が完全一致",
        ok,
        f"baseline_rc={baseline.returncode} with_env_rc={with_operator_env.returncode}\n"
        f"baseline_last_line(head)={baseline_last[:800]}\nwith_env_last_line(head)={with_env_last[:800]}\n"
        f"stderr_baseline={baseline.stderr[-800:]}\nstderr_with_env={with_operator_env.stderr[-800:]}",
    )


def _open_layer_tar(data: bytes) -> tarfile.TarFile:
    """gzip圧縮／非圧縮のいずれであっても安全に判定して開く（P2B1-CX-003対応）。
    tarfileの自動判定モード（'r:*'）を使い、圧縮方式をheaderから判定させる。"""
    return tarfile.open(fileobj=io.BytesIO(data), mode="r:*")


_MARKER_SCAN_CHUNK_SIZE = 8 * 1024 * 1024  # 8MiB


def _scan_member_for_marker(fileobj, marker_bytes: bytes, chunk_size: int = _MARKER_SCAN_CHUNK_SIZE) -> bool:
    """member内容をsize上限なしでchunk streamしながらdummy markerを検出する
    （CODEX P2B1-CX-003指摘: 旧実装は50MB以上のfileを無条件でmarker走査対象外にしており、
    保存layer中の巨大fileへの秘密混入を検出できないfail-openだった）。

    chunk境界をまたいでmarkerが分割される可能性があるため、次chunkの先頭へ
    `len(marker_bytes) - 1` byteのoverlapを保持してから連結・検索する。
    """
    overlap_len = max(len(marker_bytes) - 1, 0)
    tail = b""
    while True:
        chunk = fileobj.read(chunk_size)
        if not chunk:
            return False
        buf = tail + chunk
        if marker_bytes in buf:
            return True
        tail = buf[-overlap_len:] if overlap_len else b""


def _scan_tar_members(
    inner: tarfile.TarFile,
    label: str,
    forbidden_paths: List[str],
    marker_bytes: bytes,
) -> Dict[str, Any]:
    """1つのtarfileオブジェクトのmemberを走査する共通ロジック。

    CODEX P2B1-CX-003指摘への対応:
      - member sizeによる走査除外を行わない（上限なし、`_scan_member_for_marker`で
        stream走査するためメモリへ全読込しない）。
      - `extractfile()`が`None`を返す場合・読み取り中に例外が発生した場合は
        `except Exception: pass`で握り潰さず、`read_errors`へ明示的に記録する
        （呼び出し側はread_errorsが非空なら検査全体をFAILにする）。
    """
    forbidden_hits: List[str] = []
    ds_store_hits: List[str] = []
    marker_hits: List[str] = []
    read_errors: List[str] = []
    member_count = 0

    for member in inner.getmembers():
        member_count += 1
        hit_fp = _forbidden_path_hit(member.name, forbidden_paths)
        if hit_fp:
            forbidden_hits.append(f"{label}: {member.name} (matched {hit_fp})")
        if _is_ds_store(member.name):
            ds_store_hits.append(f"{label}: {member.name}")
        if member.isfile() and member.size > 0:
            fileobj = None
            try:
                fileobj = inner.extractfile(member)
                if fileobj is None:
                    read_errors.append(f"{label}: {member.name} (extractfile returned None)")
                    continue
                if _scan_member_for_marker(fileobj, marker_bytes):
                    marker_hits.append(f"{label}: {member.name}")
            except Exception as exc:
                read_errors.append(f"{label}: {member.name} (read error: {exc!r})")
            finally:
                if fileobj is not None:
                    try:
                        fileobj.close()
                    except Exception:
                        pass

    return {
        "forbidden_hits": forbidden_hits,
        "ds_store_hits": ds_store_hits,
        "marker_hits": marker_hits,
        "read_errors": read_errors,
        "member_count": member_count,
    }


def self_test_layer_scanner() -> None:
    """P2B1-CX-003（CODEX限定再検証、2026-08-10）negative control。

    実際のpublic/operator imageとは独立したsynthetic tar fixtureを使い、
    `_scan_tar_members`/`_scan_member_for_marker`のロジックそのものが
    次の2点を正しく検出できることを確認する自己検証。
      A. 50,000,001 byte（旧上限50MB超）の通常fileに埋め込んだdummy markerを
         見逃さず検出できること（size上限撤廃の確認）。
      B. memberの読み取りが失敗した場合、例外を握り潰さずread_errorsとして
         明示的に検出できること（fail-closedの確認）。
    """
    marker_bytes = DUMMY_SECRET_MARKER.encode("utf-8")

    # --- Fixture A: 50,000,001 byte（旧上限50MBを1byte超える）ファイル、末尾にmarker embed ---
    big_size = 50_000_001
    big_content = b"\x00" * (big_size - len(marker_bytes)) + marker_bytes
    buf_a = io.BytesIO()
    with tarfile.open(fileobj=buf_a, mode="w") as tf:
        info = tarfile.TarInfo(name="self_test_big_file_with_marker.bin")
        info.size = len(big_content)
        tf.addfile(info, io.BytesIO(big_content))
    buf_a.seek(0)
    tar_a = tarfile.open(fileobj=buf_a, mode="r")
    try:
        result_a = _scan_tar_members(tar_a, "self-test-A", [], marker_bytes)
    finally:
        tar_a.close()
    record(
        f"self-test (P2B1-CX-003): {big_size:,} byte（50MB超）ファイルのdummy markerを検出できる",
        len(result_a["marker_hits"]) == 1 and not result_a["read_errors"],
        f"marker_hits={result_a['marker_hits']} read_errors={result_a['read_errors']} member_size={big_size}",
    )

    # --- Fixture B: extractfile()が読み取り時に例外を送出するmemberを再現し、
    #     read_errorsへ明示的に記録される（握り潰さない）ことを確認する ---
    buf_b = io.BytesIO()
    with tarfile.open(fileobj=buf_b, mode="w") as tf:
        info = tarfile.TarInfo(name="self_test_unreadable_member.bin")
        payload = b"x" * 100
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    buf_b.seek(0)
    tar_b = tarfile.open(fileobj=buf_b, mode="r")
    try:
        with unittest.mock.patch.object(
            tar_b, "extractfile", side_effect=OSError("synthetic unreadable member (self-test)")
        ):
            result_b = _scan_tar_members(tar_b, "self-test-B", [], marker_bytes)
    finally:
        tar_b.close()
    record(
        "self-test (P2B1-CX-003): member読取エラーを握り潰さず検出できる（fail-closed確認）",
        len(result_b["read_errors"]) == 1 and "synthetic unreadable member" in result_b["read_errors"][0],
        f"read_errors={result_b['read_errors']}",
    )


def scan_all_saved_layers(tag: str) -> None:
    """`docker save`した実archiveの全保存layerを走査し、simulation 2ファイル・
    任意階層の.DS_Store・dummy marker内容の混入を検査する（P2B1-CX-001/CX-003対応）。

    - final filesystemのview（whiteout後）だけでなく、docker save archiveが
      参照する全layer blobを対象にする。
    - path traversal対策として、tar memberはいずれのpathへも直接extractせず、
      extractfile()でfile-likeオブジェクトとしてメモリ上でのみ走査する。
    - Docker従来形式（manifest.json + <layerid>/layer.tar）とOCI layout形式
      （index.json + blobs/sha256/<digest>）の両方に対応する。
    - 形式不明・layer読取不能・0 layer走査はPASSではなく検査FAILとする。
    """
    image_id = get_image_id(tag)
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b1_save_") as tmp:
        tar_path = Path(tmp) / "image.tar"
        save_proc = _run(["docker", "save", "-o", str(tar_path), tag])
        if save_proc.returncode != 0:
            record(
                "public image: docker save 成功",
                False,
                save_proc.stdout + save_proc.stderr,
                ["docker", "save", "-o", str(tar_path), tag],
            )
            return
        record("public image: docker save 成功", True, f"tar size={tar_path.stat().st_size} bytes")

        outer: Optional[tarfile.TarFile] = None
        try:
            outer = tarfile.open(str(tar_path), mode="r")
            names = outer.getnames()

            layer_blobs: List[Tuple[str, bytes]] = []  # (label, bytes)
            fmt = "unknown"

            if "index.json" in names:
                fmt = "oci-layout"

                def _read_blob_json(digest: str) -> dict:
                    blob_path = "blobs/" + digest.replace(":", "/")
                    return json.loads(outer.extractfile(outer.getmember(blob_path)).read())

                def _find_image_manifest(start_digests: List[str]) -> Optional[dict]:
                    """OCI index.jsonから実際のimage manifest（'layers'を持つもの）を
                    再帰的に探索する。containerd/buildxのOCI layoutでは
                    index.json -> (中間image index、マルチプラットフォーム対応) ->
                    platform別manifest + attestation-manifest、という2段以上の
                    ネストになり得るため、単純に1階層だけ辿ると本体のimage
                    manifestではなくattestation-manifest等を誤って参照しうる。
                    'vnd.docker.reference.type=attestation-manifest' は
                    layersを持たない付随情報であり除外する。"""
                    visited = set()
                    queue = list(start_digests)
                    while queue:
                        digest = queue.pop(0)
                        if digest in visited:
                            continue
                        visited.add(digest)
                        blob = _read_blob_json(digest)
                        if blob.get("layers"):
                            return blob
                        for m in blob.get("manifests", []):
                            ann = m.get("annotations", {}) or {}
                            if ann.get("vnd.docker.reference.type") == "attestation-manifest":
                                continue
                            queue.append(m["digest"])
                    return None

                index_data = json.loads(outer.extractfile(outer.getmember("index.json")).read())
                top_digests = [m["digest"] for m in index_data.get("manifests", [])]
                manifest_data = _find_image_manifest(top_digests)
                if manifest_data is None:
                    record(
                        "public image: docker save archive形式を認識できる",
                        False,
                        "index.jsonから'layers'を持つimage manifestへ到達できなかった"
                        "（image index/attestation-manifestのみ）",
                    )
                    return
                for i, layer in enumerate(manifest_data.get("layers", [])):
                    digest = layer["digest"]
                    blob_path = "blobs/" + digest.replace(":", "/")
                    data = outer.extractfile(outer.getmember(blob_path)).read()
                    layer_blobs.append((f"layer[{i}] {digest}", data))
            elif "manifest.json" in names:
                fmt = "docker-manifest"
                manifest_data = json.loads(outer.extractfile(outer.getmember("manifest.json")).read())
                layer_paths = manifest_data[0].get("Layers", [])
                for i, lp in enumerate(layer_paths):
                    data = outer.extractfile(outer.getmember(lp)).read()
                    layer_blobs.append((f"layer[{i}] {lp}", data))
            else:
                record(
                    "public image: docker save archive形式を認識できる",
                    False,
                    f"index.json/manifest.jsonのいずれも見つからない。top-level names(head)={names[:20]}",
                )
                return

            record(f"public image: docker save archive形式判定 ({fmt})", True, f"names_count={len(names)}")

            if not layer_blobs:
                record(
                    "public image: 保存layerが1件以上ある",
                    False,
                    "layer 0件（0 layer走査はPASSにしない）",
                )
                return

            forbidden_hits: List[str] = []
            ds_store_hits: List[str] = []
            marker_hits: List[str] = []
            read_errors: List[str] = []
            total_member_count = 0
            marker_bytes = DUMMY_SECRET_MARKER.encode("utf-8")

            for label, data in layer_blobs:
                try:
                    inner = _open_layer_tar(data)
                except Exception as exc:
                    record(
                        f"public image: 保存layer読取可能 ({label})",
                        False,
                        f"layer blobをtarとして開けなかった: {exc}",
                    )
                    return
                try:
                    # _scan_tar_members: size上限なしでstream走査し、読み取り例外は
                    # read_errorsへ明示的に記録する（P2B1-CX-003対応、握り潰さない）。
                    layer_result = _scan_tar_members(inner, label, FORBIDDEN_PUBLIC_FILES, marker_bytes)
                finally:
                    inner.close()
                forbidden_hits.extend(layer_result["forbidden_hits"])
                ds_store_hits.extend(layer_result["ds_store_hits"])
                marker_hits.extend(layer_result["marker_hits"])
                read_errors.extend(layer_result["read_errors"])
                total_member_count += layer_result["member_count"]

            print(f"    public image ID: {image_id}")
            print(f"    saved layer count: {len(layer_blobs)}")
            print(f"    saved layer member count: {total_member_count}")
            print(f"    forbidden module path hits (all layers): {len(forbidden_hits)}")
            print(f"    .DS_Store hits (all layers): {len(ds_store_hits)}")
            print(f"    dummy marker hits (all layers): {len(marker_hits)}")
            print(f"    member read errors (all layers): {len(read_errors)}")

            record(
                f"public image: 全保存layer({len(layer_blobs)}件、member{total_member_count}件)でoperator/admin/simulation module 0件",
                not forbidden_hits,
                f"hits={forbidden_hits}",
            )
            record(
                f"public image: 全保存layerで.DS_Store 0件 (member{total_member_count}件走査)",
                not ds_store_hits,
                f"hits={ds_store_hits}",
            )
            record(
                f"public image: 全保存layerでdummy secret marker 0件 (member{total_member_count}件走査、size上限なし)",
                not marker_hits,
                f"hits={marker_hits}",
            )
            # P2B1-CX-003対応: member読取エラーは握り潰さず、1件でもあれば
            # 検査全体をFAILにする（read不能なmemberにmarkerが存在する可能性を
            # 「未検査のまま見逃す」ことを許容しない）。
            record(
                f"public image: 全保存layerでmember読取エラー 0件 (member{total_member_count}件走査)",
                not read_errors,
                f"errors={read_errors}",
            )

            (EVIDENCE_DIR / "public_saved_layers_scan.json").write_text(
                json.dumps(
                    {
                        "image_id": image_id,
                        "format": fmt,
                        "layer_count": len(layer_blobs),
                        "member_count": total_member_count,
                        "forbidden_hits": forbidden_hits,
                        "ds_store_hits": ds_store_hits,
                        "marker_hits": marker_hits,
                        "read_errors": read_errors,
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        finally:
            if outer is not None:
                outer.close()
    # tempdir（docker save先の一時tarファイル）はwith-block終了時に自動削除される


def inspect_operator_image() -> None:
    tag = OPERATOR_IMAGE_TAG

    # --- Docker CLI 保持 ---
    proc = image_exec(tag, ["sh", "-c", "docker --version; echo EXIT:$?"])
    ok = "EXIT:0" in proc.stdout
    record(
        "operator image: Docker CLI 保持",
        ok,
        proc.stdout + proc.stderr,
        ["docker", "run", "--entrypoint", "sh", tag, "-c", "docker --version"],
    )

    # --- dummy secretで起動成功 ---
    proc = image_exec(
        tag,
        ["python", "-c", "import app_operator; print('OPERATOR_IMPORT_OK')"],
        env={"OPERATOR_AUTH_SECRET": DUMMY_SECRET_MARKER},
        timeout=60,
    )
    ok = proc.returncode == 0 and "OPERATOR_IMPORT_OK" in proc.stdout
    record(
        "operator image: dummy secretでentrypoint smoke成功",
        ok,
        proc.stdout + proc.stderr,
    )

    # --- secret未設定/空/空白で非0終了 ---
    for label, value in [("unset", None), ("empty", ""), ("whitespace", "   ")]:
        env = {} if value is None else {"OPERATOR_AUTH_SECRET": value}
        proc = image_exec(
            tag,
            ["python", "-c", "import app_operator; print('SHOULD_NOT_PRINT')"],
            env=env,
            timeout=60,
        )
        ok = proc.returncode != 0 and "SHOULD_NOT_PRINT" not in proc.stdout
        record(
            f"operator image: secret={label} で非0終了 (fail-closed)",
            ok,
            f"rc={proc.returncode}\n{proc.stdout}{proc.stderr}",
        )

    # --- operator側でsimulation sourceを誤って除外していないことの確認
    #     （P2B1-CX-001必須確認項目、backend/Dockerfile.dockerignore はpublic専用の
    #     ため、operator側（backend/.dockerignore）には影響しないはずだが実物imageで
    #     再確認する） ---
    simulation_files = ["app/models/simulation.py", "app/services/simulation_service.py"]
    find_cmd = ["find", "/app", "-type", "f", "("]
    for i, f in enumerate(simulation_files):
        if i:
            find_cmd.append("-o")
        find_cmd += ["-path", f"/app/{f}"]
    find_cmd.append(")")
    proc = image_exec(tag, find_cmd)
    found = [l for l in proc.stdout.splitlines() if l.strip()]
    record(
        "operator image: simulation model/service が誤って除外されていない（2件とも存在）",
        proc.returncode == 0 and len(found) == 2,
        f"found={found}",
        find_cmd,
    )

    # --- image inspect / package inventory の保存 ---
    proc = _run(["docker", "inspect", tag])
    (EVIDENCE_DIR / "operator_docker_inspect.json").write_text(proc.stdout, encoding="utf-8")
    proc = image_exec(tag, ["pip", "list", "--format=json"])
    (EVIDENCE_DIR / "operator_pip_list.json").write_text(proc.stdout, encoding="utf-8")


# ------------------------------------------------------------------
# 6. AT-12: dummy marker canary build（build contextからの除外を再現的に確認）
# ------------------------------------------------------------------

def canary_build_context() -> None:
    # canary targetをbuild前に確定しておく（P2B1-CX-003対応: 正常終了・検査FAIL・
    # 未処理例外のいずれでも、このtag集合だけをtry/finallyで確実にcleanupするため）。
    canary_targets = {
        "env-secret": ".env",
        "runtime-data": f"data_runtime/{DUMMY_SECRET_MARKER}.marker",
        "admin-module": "app/api/admin.py",
    }
    canary_tags = [f"ohg2-phase2b1-canary-public-{label}:latest" for label in canary_targets] + [
        "ohg2-phase2b1-canary-operator-admin:latest",
        "ohg2-phase2b1-canary-operator-env:latest",
    ]

    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b1_canary_") as tmp:
        try:
            tmp_path = Path(tmp)
            canary_context = tmp_path / "context"
            shutil.copytree(BACKEND_DIR, canary_context, symlinks=True)

            # dummy marker群を配置（実秘密は使用しない）
            (canary_context / ".env").write_text(
                f"CANARY_SECRET={DUMMY_SECRET_MARKER}\n", encoding="utf-8"
            )
            runtime_dir = canary_context / "data_runtime"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / f"{DUMMY_SECRET_MARKER}.marker").write_text(
                DUMMY_SECRET_MARKER, encoding="utf-8"
            )

            # --- CANARY-A: public (Dockerfile / Dockerfile.dockerignore) は
            #     .env / data_runtime/* / app/api/admin.py のいずれも送信されないこと ---
            for label, target in canary_targets.items():
                canary_dockerfile = canary_context / "Dockerfile"
                canary_dockerfile.write_text(
                    f"FROM busybox\nCOPY {target} /canary-proof\n",
                    encoding="utf-8",
                )
                cmd = [
                    "docker", "build",
                    "-f", str(canary_dockerfile),
                    "-t", f"ohg2-phase2b1-canary-public-{label}:latest",
                    str(canary_context),
                ]
                proc = _run(cmd, cwd=str(canary_context))
                # public canaryは「buildが失敗する」ことが期待結果（=除外されている証拠）
                excluded = proc.returncode != 0
                record(
                    f"AT-12 canary (public/Dockerfile.dockerignore): '{target}' はbuild contextへ送信されない",
                    excluded,
                    proc.stdout[-1000:] + proc.stderr[-1500:],
                    cmd,
                )

            # --- CANARY-B: operator (Dockerfile.operator / 共通.dockerignore) は
            #     admin.py は到達できる（陽性対照）が、.env は除外されること ---
            canary_dockerfile_operator = canary_context / "Dockerfile.operator"
            canary_dockerfile_operator.write_text(
                "FROM busybox\nCOPY app/api/admin.py /canary-proof\n",
                encoding="utf-8",
            )
            cmd = [
                "docker", "build",
                "-f", str(canary_dockerfile_operator),
                "-t", "ohg2-phase2b1-canary-operator-admin:latest",
                str(canary_context),
            ]
            proc = _run(cmd, cwd=str(canary_context))
            reachable = proc.returncode == 0
            record(
                "AT-12 canary (operator/.dockerignore, 陽性対照): app/api/admin.py はbuild contextへ到達する",
                reachable,
                proc.stdout[-1000:] + proc.stderr[-1500:],
                cmd,
            )

            canary_dockerfile_operator.write_text(
                "FROM busybox\nCOPY .env /canary-proof\n",
                encoding="utf-8",
            )
            cmd = [
                "docker", "build",
                "-f", str(canary_dockerfile_operator),
                "-t", "ohg2-phase2b1-canary-operator-env:latest",
                str(canary_context),
            ]
            proc = _run(cmd, cwd=str(canary_context))
            excluded = proc.returncode != 0
            record(
                "AT-12 canary (operator/.dockerignore): '.env' はbuild contextへ送信されない",
                excluded,
                proc.stdout[-1000:] + proc.stderr[-1500:],
                cmd,
            )

            # --- 完成image（canary busybox image）にmarkerが焼き込まれていないことも確認 ---
            # public側は全build失敗のためimage自体が存在しない = markerは0件で自明PASS。
            # operator側の admin canary は成功したimageのfilesystemを確認し、
            # dummy secret markerそのもの（DUMMY_SECRET_MARKER文字列）は含まれないことを確認する。
            proc = _run(
                [
                    "docker", "run", "--rm",
                    "ohg2-phase2b1-canary-operator-admin:latest",
                    "grep", "-r", DUMMY_SECRET_MARKER, "/canary-proof",
                ]
            )
            marker_absent_in_admin_canary = proc.returncode != 0  # grep: no match => exit 1
            record(
                "AT-12: operator陽性対照imageにdummy secret marker文字列が含まれない",
                marker_absent_in_admin_canary,
                proc.stdout + proc.stderr,
            )
        finally:
            # cleanup（P2B1-CX-003対応: 正常終了・検査FAIL・未処理例外のいずれでも
            # 確実に実行する。canary imageは存在しないtagに対するrmiもno-opで安全）。
            for t in canary_tags:
                _run(["docker", "rmi", "-f", t])
    # tempdir (canary build context) は with-block終了時に自動削除される


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------

def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"run tag: {_RUN_TAG}")
    print(f"public image tag:   {PUBLIC_IMAGE_TAG}")
    print(f"operator image tag: {OPERATOR_IMAGE_TAG}")

    # negative control（synthetic fixture／fakeのCompletedProcessのみ、
    # 実imageやDocker daemonに影響しない）を最初に実行する。
    self_test_layer_scanner()
    self_test_cleanup_verification_logic()

    if not check_docker_available():
        print("Docker daemon not available — aborting image inspection.")
        write_summary()
        return 1

    # negative control（実Docker daemonを使用。tag作成後・return前の例外でも
    # cleanupが機能することを、本buildの前に確認する。P2B1-CX-003第3回対応）。
    self_test_cleanup_survives_build_exception()

    public_built = False
    operator_built = False
    public_image_id = "(build failed)"
    operator_image_id = "(build failed)"
    try:
        public_built = build_image(PUBLIC_IMAGE_TAG, "Dockerfile")
        operator_built = build_image(OPERATOR_IMAGE_TAG, "Dockerfile.operator")

        if public_built:
            public_image_id = get_image_id(PUBLIC_IMAGE_TAG)
            inspect_public_image()
        if operator_built:
            operator_image_id = get_image_id(OPERATOR_IMAGE_TAG)
            inspect_operator_image()

        canary_build_context()
    finally:
        # cleanup（P2B1-CX-003第3回対応、CODEX限定再検証指摘: build_image()は
        # Docker daemon上にtagを作成した後、record()やevidence write_text()を
        # 経てから戻り値を返す。この区間で例外が発生すると、呼び出し元の
        # 成功flag（public_built/operator_built）への代入が完了しないため、
        # 旧実装の「if public_built: ...」というflag依存cleanupは実行されず、
        # tagが残り得ることが独立negative controlで実測された。
        # 一意run tagはユーザー既存資産と衝突しないため、flagの真偽に関わらず
        # 常にcleanupを試み、削除結果も検証する（cleanup_run_tags_and_verify）。
        cleanup_run_tags_and_verify()

    write_summary()

    failed = [r for r in RESULTS if not r["pass"]]
    print()
    print(f"public image ID:   {public_image_id}")
    print(f"operator image ID: {operator_image_id}")
    print(f"TOTAL: {len(RESULTS)}  PASS: {len(RESULTS) - len(failed)}  FAIL: {len(failed)}")
    print(f"exit code: {1 if failed else 0}")
    if failed:
        print("FAILED CHECKS:")
        for r in failed:
            print(f"  - {r['name']}")

    return 1 if failed else 0


def write_summary() -> None:
    failed = [r for r in RESULTS if not r["pass"]]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_tag": _RUN_TAG,
        "public_image_tag": PUBLIC_IMAGE_TAG,
        "operator_image_tag": OPERATOR_IMAGE_TAG,
        "total_checks": len(RESULTS),
        "pass_count": len(RESULTS) - len(failed),
        "fail_count": len(failed),
        "exit_code": 1 if failed else 0,
        "results": RESULTS,
    }
    (EVIDENCE_DIR / "phase2b1_image_inspect_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())

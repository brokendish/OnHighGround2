#!/usr/bin/env python3
"""
tools/public_release/phase2b3_operator_security.py

Phase 2-B.3（operator Bearer認証・Docker operation allowlist・監査ログ）の
統合・回帰検証script。AT-10・AT-09-AUTH-EXTに対応する。

unit-levelのAUTH/DOP/AUD fixture（fake docker、実Docker操作なし）は
`backend/tests/test_phase2b3_operator_security.py`が担当する。本scriptは
それに加えて、実Docker daemon・実Compose project・実network経由でのみ
確認できる項目を担当する:

  1. backend/tests/test_phase2b1_entrypoint_boundary.py 再実行（Phase 2-B.1回帰）
  2. backend/tests/test_phase2b3_operator_security.py 再実行（AUTH/DOP/AUD全fixture）
  3. tools/public_release/phase2b2_compose_boundary.py 再実行
     （Phase 2-B.2回帰: AT-03/AT-05/AT-09-BIND/CF-N01〜N13/cleanup）
  4. 実Compose project・dummy tokenでのoperator profile起動
  5. host loopback（bind三層②）経由での実HTTP認証境界:
     無認証401・誤token401・正tokenで200、WWW-Authenticate header確認
  6. 実`ssh -L`経由でも同じ認証境界が機能すること（AT-09-AUTH-EXT）
  7. public frontend経由で /api/admin/*, /api/simulation/* が404のまま
  8. cleanup（P2B2-CX-002の教訓を踏襲したfail-closedなnetwork query）

実Docker containerへのrestart/exec（state-changing Docker操作）は本scriptでも
一切行わない（第9.2節の禁止事項）。operator profileの起動・healthcheck・
read-onlyな認証境界確認にとどめる。

事前条件: Dockerデーモンが起動していること。実秘密は使用しない
（dummy tokenのみ）。

使い方:
    ./venv/bin/python tools/public_release/phase2b3_operator_security.py

終了コード: 全項目PASSなら0、1件でもFAILがあれば1。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML is required (pip install pyyaml). Run via ./venv/bin/python.", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
# Phase 2-B.3限定修正（CODEX P2B3-CX-003再指摘対応）: evidence出力先は
# repository外（システム一時領域）に限定する。実装報告書（本scriptの実行
# 結果）自体はrepository内のreport markdownへ記載する（そちらは永続成果物
# であり一時artifactではない）。
#
# 限定修正（3回目）: 当初は固定path（`tempfile.gettempdir()/ohg2_phase2b3_evidence`）
# を使っていたが、mainの実行終了時に削除されず、CODEX検証時点でも前回実行分の
# summary/override 2ファイルが残存していると指摘された。固定のEVIDENCE_DIR
# 定数は廃止し、`main()`がrunごとに`tempfile.TemporaryDirectory()`を生成して
# evidence出力先とし、with-block終了時に自動削除・直後に残存0件を確認する
# 設計へ変更した（詳細はmain()参照）。
TOOLS_DIR = Path(__file__).resolve().parent

_RUN_TAG = os.environ.get("OHG2_PHASE2B3_RUN_TAG") or datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")
PROJECT_NAME = f"ohg2p2b3{_RUN_TAG}".lower().replace("_", "")
CONTAINER_PREFIX = f"ohg2p2b3-{_RUN_TAG}"
NETWORK_PREFIX = CONTAINER_PREFIX

DUMMY_OPERATOR_SECRET = "OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE"  # Phase 2-B.1/2-B.2と同一の既定dummy
WRONG_TOKEN = "OHG2_PHASE2B3_WRONG_TOKEN_DO_NOT_USE"

OPERATOR_TARGET_PORT = 8100
OPERATOR_HOST_PORT = 19500 + (hash(_RUN_TAG) % 300)

RESULTS: List[Dict[str, Any]] = []


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
        print(f"        detail: {detail[:600]}")


def _run(cmd: List[str], **kwargs) -> subprocess.CompletedProcess:
    kwargs.setdefault("cwd", str(REPO_ROOT))
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


# ------------------------------------------------------------------
# 1. サブプロセス回帰: Phase 2-B.1 pytest, Phase 2-B.3 pytest, Phase 2-B.2 script
# ------------------------------------------------------------------


def run_phase2b1_regression() -> None:
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_phase2b1_entrypoint_boundary.py", "-q",
    ]
    proc = _run(cmd, cwd=str(REPO_ROOT / "backend"), timeout=300)
    record(
        "Phase 2-B.1回帰: test_phase2b1_entrypoint_boundary.py PASS",
        proc.returncode == 0,
        (proc.stdout + proc.stderr)[-3000:],
        cmd,
    )


def run_phase2b3_unit_fixtures() -> None:
    env = os.environ.copy()
    env["OPERATOR_AUTH_SECRET"] = DUMMY_OPERATOR_SECRET
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_phase2b3_operator_security.py", "-q",
    ]
    proc = _run(cmd, cwd=str(REPO_ROOT / "backend"), timeout=300, env=env)
    record(
        "AUTH/DOP/AUD全fixture: test_phase2b3_operator_security.py PASS",
        proc.returncode == 0,
        (proc.stdout + proc.stderr)[-4000:],
        cmd,
    )


def run_phase2b2_regression() -> None:
    """Phase 2-B.2回帰（AT-03/AT-05/AT-09-BIND/CF-N01〜N13/cleanup）を、
    独立run_tagのもとで phase2b2_compose_boundary.py をサブプロセス実行して
    確認する。docker-compose.ymlのnetwork/sidecar/bind三層設計は本phaseで
    変更していないため、この再実行がそのままPhase 2-B.2境界の無回帰確認となる。
    """
    env = os.environ.copy()
    env["OHG2_PHASE2B2_RUN_TAG"] = f"{_RUN_TAG}p2b3reg"
    cmd = [sys.executable, str(TOOLS_DIR / "phase2b2_compose_boundary.py")]
    proc = _run(cmd, timeout=1200, env=env)
    tail = (proc.stdout + proc.stderr)[-4000:]
    record(
        "Phase 2-B.2回帰: phase2b2_compose_boundary.py PASS（AT-03/AT-05/AT-09-BIND/CF-N/cleanup）",
        proc.returncode == 0,
        tail,
        cmd,
    )


# ------------------------------------------------------------------
# 2. 実Compose project起動基盤（Phase 2-B.2と同型のbind三層・sidecar override）
# ------------------------------------------------------------------


class _OverrideList(list):
    """Compose Specの `!override` YAMLタグ（第19節/Phase 2-B.2で確立した手法の再利用）。"""


def _override_list_representer(dumper: "yaml.Dumper", data: "_OverrideList"):
    return dumper.represent_sequence("!override", list(data))


yaml.add_representer(_OverrideList, _override_list_representer)


def seed_temp_data_dirs(run_tmp_path: Path) -> Dict[str, Path]:
    """Phase 2-B.3限定修正（CODEX P2B3-CX-003再指摘対応、3回目）: data_lake・
    data_runtime・frontend/layers/railways・osrmを、実repositoryから
    run固有の書込可能一時ディレクトリへ複製する。macOS APFS上の`cp -R`は
    clonefile()による copy-on-write cloneを自動的に使うため、実測では
    data_lake（約24GB）で約85秒、data_runtime（約6.3GB）で約25秒と、
    実容量に対して十分高速・省容量に完了する。

    これにより、test containerが書き込む先（audit log・job log・app log等、
    アプリケーション自身が本番でも必要とする書込先）が実repositoryの
    bind sourceから完全に分離され、既存の本番stackとログ・監査・状態
    ファイルを共有しなくなる（第18節のCODEX指摘「共有rw mount」への対応）。
    """
    mapping = {
        "data_lake": REPO_ROOT / "data_lake",
        "data_runtime": REPO_ROOT / "data_runtime",
        "railways": REPO_ROOT / "frontend" / "layers" / "railways",
        "osrm": REPO_ROOT / "osrm",
    }
    seeded: Dict[str, Path] = {}
    for key, src in mapping.items():
        dest = run_tmp_path / f"seed_{key}"
        proc = _run(["cp", "-R", str(src), str(dest)], timeout=600)
        record(
            f"seed: {key}を実repositoryから一意な書込可能一時ディレクトリへcopy succeeds",
            proc.returncode == 0 and dest.exists(),
            (proc.stdout + proc.stderr)[-500:],
        )
        seeded[key] = dest
    return seeded


def build_override_compose(tmp_dir: Path, seeded: Dict[str, Path]) -> Path:
    # Phase 2-B.3限定修正（CODEX P2B3-CX-003対応）: 旧実装はcontainer名・
    # dummy secretだけを上書きし、base docker-compose.ymlの
    # `env_file: [.env]` / `env_file: [.env.operator]` をそのまま継承していた。
    # `env_file: !reset []`で両backend serviceのenv_fileを完全に空へ置換し、
    # 必要なdummy値だけを`environment:`で明示注入する。あわせて
    # `compose_cmd()`側で`--env-file /dev/null`を使い、Compose変数展開
    # （`${VAR}`置換）自体もrepository rootの`.env`を参照しないようにする
    # （二重の分離）。
    #
    # Phase 2-B.3限定修正（CODEX P2B3-CX-003再指摘対応、3回目）: data_lake・
    # data_runtime・frontend/layers/railways・osrmのmount先を、
    # `seed_temp_data_dirs()`が用意したrun固有の一時copyへ差し替えた
    # （書込は実repositoryへ一切及ばない）。`./backend:/app`のhot-reload
    # bindは完全に削除した（imageは`--build`のたびに`COPY . .`で現在の
    # ソースを取り込み済みのため、host bindなしでも同じコードで動作する。
    # 削除により、この経路での実repositoryとの共有も消える）。
    # `./data`・`国土地理院避難所データ`・`./scripts`は元からread-onlyの
    # 直接bindであり、test containerから書込む経路がないため実repository
    # 参照のまま維持する（CODEXの懸念は「rw」mountに限定される）。
    common_volumes = _OverrideList(
        [
            f"{seeded['data_runtime'].resolve()}:/data_runtime",
            f"{seeded['data_lake'].resolve()}:/data_lake",
            "./data:/app/data:ro",
            "./data:/data:ro",
            "./国土地理院避難所データ:/app/shelter_data:ro",
            "./scripts:/scripts:ro",
            f"{seeded['railways'].resolve()}:/frontend/layers/railways",
            f"{seeded['osrm'].resolve()}:/osrm",
        ]
    )

    override = {
        "services": {
            "backend-public": {
                "container_name": f"{CONTAINER_PREFIX}-backend-public",
                "env_file": _OverrideList([]),
                "volumes": common_volumes,
            },
            "backend-operator": {
                "container_name": f"{CONTAINER_PREFIX}-backend-operator",
                "env_file": _OverrideList([]),
                "environment": {
                    "OPERATOR_AUTH_SECRET": DUMMY_OPERATOR_SECRET,
                },
                "volumes": _OverrideList(
                    list(common_volumes) + ["/var/run/docker.sock:/var/run/docker.sock"]
                ),
            },
            "operator-publish-proxy": {
                "container_name": f"{CONTAINER_PREFIX}-operator-publish-proxy",
                "ports": _OverrideList(
                    [
                        {
                            "name": "operator-http",
                            "target": OPERATOR_TARGET_PORT,
                            "published": str(OPERATOR_HOST_PORT),
                            "host_ip": "127.0.0.1",
                            "protocol": "tcp",
                            "mode": "host",
                        }
                    ]
                ),
            },
            "frontend": {
                "container_name": f"{CONTAINER_PREFIX}-frontend",
                "ports": _OverrideList(["0:80"]),
                "depends_on": _OverrideList(["backend-public", "osrm-walking"]),
            },
            "osrm-walking": {
                "container_name": f"{CONTAINER_PREFIX}-osrm-walking",
                "ports": _OverrideList(["0:5001"]),
                # Phase 2-B.3限定修正（CODEX P2B3-CX-003継続指摘対応、4回目）:
                # baseの`./data_lake:/data_lake`・`./osrm/foot.lua:/opt/foot.lua`
                # （いずれもrw、`:ro`指定なし）がoverride対象から漏れており、
                # osrm-walkingだけが実repositoryのdata_lake/osrmを直接共有した
                # ままだった（container名・portsしか上書きしていなかったため）。
                # backend-public/backend-operatorと同じseed先へ差し替える。
                "volumes": _OverrideList(
                    [
                        f"{seeded['data_lake'].resolve()}:/data_lake",
                        f"{seeded['osrm'].resolve()}/foot.lua:/opt/foot.lua",
                    ]
                ),
            },
            "martin": {
                "container_name": f"{CONTAINER_PREFIX}-martin",
            },
        },
        "networks": {
            "default": {"name": f"{NETWORK_PREFIX}-default"},
            "operator-internal": {"name": f"{NETWORK_PREFIX}-operator-internal", "internal": True},
            "operator-publish": {"name": f"{NETWORK_PREFIX}-operator-publish"},
        },
    }
    path = tmp_dir / "docker-compose.override.phase2b3.yml"
    path.write_text(yaml.dump(override, sort_keys=False), encoding="utf-8")
    return path


def compose_cmd(override_file: Path, extra: List[str], compose_file: Path = COMPOSE_FILE) -> List[str]:
    # --env-file /dev/null: repository rootの実`.env`をCompose変数展開
    # （`${VAR}`置換）の対象から外す（P2B3-CX-003対応）。個々のserviceの
    # `env_file:`はoverride側で`!reset []`しているため、実.envの内容が
    # container実行時環境へロードされる経路はこれで塞がれる。
    # `compose_file`は既定で実repositoryの`docker-compose.yml`だが、
    # `env_isolation_negative_control()`（CODEX P2B3-CX-003再指摘対応、
    # 3回目）だけは完全synthetic base composeを明示的に渡し、実repository
    # ／実`.env`を一切参照しない。
    return [
        "docker", "compose", "--env-file", "/dev/null",
        "-f", str(compose_file), "-f", str(override_file), "-p", PROJECT_NAME,
    ] + extra


def get_container_id(override_file: Path, service: str) -> Optional[str]:
    proc = _run(compose_cmd(override_file, ["ps", "-q", service]))
    out = proc.stdout.strip()
    return out.splitlines()[0] if out else None


def get_host_published_port(override_file: Path, service: str, container_port: int) -> Optional[str]:
    proc = _run(compose_cmd(override_file, ["port", service, str(container_port)]))
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip().rsplit(":", 1)[-1]


def docker_exec(container_id: str, cmd: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return _run(["docker", "exec", container_id] + cmd, timeout=timeout)


def _cleanup_project_networks() -> None:
    """P2B2-CX-002の教訓（fail-closedなnetwork query）をそのまま踏襲する。"""
    net_query_cmd = ["docker", "network", "ls", "--filter", f"label=com.docker.compose.project={PROJECT_NAME}", "-q"]
    net_proc = _run(net_query_cmd)
    if net_proc.returncode != 0:
        record("cleanup: test project network inventory query succeeds", False, net_proc.stderr[-500:], net_query_cmd)
        return
    remaining = [l for l in net_proc.stdout.splitlines() if l.strip()]
    if not remaining:
        record("cleanup: test project network残存 0件", True, "remaining=[]")
        return
    rm_failures = []
    for net_id in remaining:
        rm_proc = _run(["docker", "network", "rm", net_id])
        if rm_proc.returncode != 0:
            rm_failures.append((net_id, rm_proc.stderr[-300:]))
    record("cleanup: docker network rm succeeds for all leftover networks", not rm_failures, f"rm_failures={rm_failures}")
    recheck = _run(net_query_cmd)
    if recheck.returncode != 0:
        record("cleanup: post-removal network re-query succeeds", False, recheck.stderr[-500:], net_query_cmd)
        return
    still = [l for l in recheck.stdout.splitlines() if l.strip()]
    record("cleanup: test project network残存 0件", len(still) == 0, f"still={still}")


def cleanup_stack(override_file: Path) -> None:
    proc = _run(compose_cmd(override_file, ["--profile", "operator", "down", "--remove-orphans", "--timeout", "15"]))
    record("cleanup: docker compose down succeeds", proc.returncode == 0, (proc.stdout + proc.stderr)[-1000:])

    ps_proc = _run(compose_cmd(override_file, ["ps", "-a", "-q"]))
    if ps_proc.returncode != 0:
        record("cleanup: post-down container inventory query succeeds", False, ps_proc.stderr[-500:])
    else:
        remaining = [l for l in ps_proc.stdout.splitlines() if l.strip()]
        record("cleanup: post-down container残存 0件", len(remaining) == 0, f"remaining_ids={remaining}")

    _cleanup_project_networks()

    for tag in (f"{PROJECT_NAME}-backend-public:latest", f"{PROJECT_NAME}-backend-operator:latest"):
        _run(["docker", "rmi", "-f", tag])
    img_check = _run(["docker", "images", "-q", "--filter", f"reference={PROJECT_NAME}-*"])
    remaining_imgs = [l for l in img_check.stdout.splitlines() if l.strip()] if img_check.returncode == 0 else ["<query failed>"]
    record("cleanup: test project image残存 0件", len(remaining_imgs) == 0, f"remaining={remaining_imgs}")


def try_connect_tcp(host: str, port: int, timeout_s: float = 3.0) -> Tuple[bool, str]:
    import socket as socket_mod

    family = socket_mod.AF_INET6 if ":" in host else socket_mod.AF_INET
    try:
        with socket_mod.socket(family, socket_mod.SOCK_STREAM) as s:
            s.settimeout(timeout_s)
            s.connect((host, port))
            return True, "connected"
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)


def wait_backend_public_ready(override_file: Path, timeout_s: int = 90) -> Tuple[bool, str]:
    bp_id = get_container_id(override_file, "backend-public")
    if not bp_id:
        return False, "backend-public container not found"
    deadline = time.time() + timeout_s
    last_detail = ""
    while time.time() < deadline:
        r = docker_exec(bp_id, ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"])
        if r.returncode == 0:
            return True, "backend-public /health reachable"
        last_detail = (r.stdout + r.stderr)[-300:]
        time.sleep(2)
    return False, last_detail


def wait_operator_ready(operator_host_port: int, timeout_s: int = 90) -> Tuple[bool, str]:
    """`/operator/health`（唯一の匿名可routeとして維持されている契約、第4.3節）が
    200を返すまで待機する。Bearer認証境界の実測に先立つ起動待ちであり、
    このrouteはそもそも認証不要契約のため無トークンで確認する。"""
    deadline = time.time() + timeout_s
    last_detail = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{operator_host_port}/operator/health", timeout=3) as resp:
                if resp.status == 200:
                    return True, "operator /operator/health reachable"
        except Exception as exc:  # noqa: BLE001
            last_detail = repr(exc)
        time.sleep(2)
    return False, last_detail


# ------------------------------------------------------------------
# 3. AT-10 / AT-09-AUTH-EXT: 実network経由のBearer認証境界
# ------------------------------------------------------------------


def http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: float = 5.0):
    """response headerはkeyを小文字化して返す（HTTP header名は大小無視、
    `dict(resp.getheaders())`はcaseを保持したまま返るため呼び出し側での
    大文字小文字不一致誤判定を避ける）。"""
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return resp.status, hdrs, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in (e.headers or {}).items()}
        return e.code, hdrs, e.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return None, {}, repr(exc)


def at10_host_loopback_auth_checks(operator_host_port: int) -> None:
    url = f"http://127.0.0.1:{operator_host_port}/api/admin/hazards"

    status, headers, body = http_get(url)
    record(
        "AT-10: host loopback経由、無認証requestが401（保護route、operator/healthではない）",
        status == 401,
        f"status={status} www-authenticate={headers.get('www-authenticate')} body={body[:200]}",
    )
    record(
        "AT-10: 401応答にWWW-Authenticate: Bearerが付与される",
        headers.get("www-authenticate") == "Bearer",
        f"headers={headers}",
    )
    record(
        "AT-10: 401応答本文にdummy secret値そのものが含まれない",
        DUMMY_OPERATOR_SECRET not in body,
        f"body={body[:200]}",
    )

    status, headers, body = http_get(url, headers={"Authorization": f"Bearer {WRONG_TOKEN}"})
    record(
        "AT-10: host loopback経由、誤token requestが401",
        status == 401,
        f"status={status} body={body[:200]}",
    )

    status, headers, body = http_get(url, headers={"Authorization": f"Bearer {DUMMY_OPERATOR_SECRET}"})
    record(
        "AT-10: host loopback経由、正token requestが200（保護read routeへ到達）",
        status == 200,
        f"status={status} body={body[:200]}",
    )

    # /operator/health は唯一の匿名可route（第4.3節）: 無token・誤tokenのいずれでも200
    status, _, body = http_get(f"http://127.0.0.1:{operator_host_port}/operator/health")
    record(
        "AT-10: /operator/healthのみ無認証でも200のまま（唯一の匿名可例外route）",
        status == 200 and '"role"' in body and '"operator"' in body,
        f"status={status} body={body[:200]}",
    )


def at09_auth_ext_ssh_forward_auth_check(operator_host_port: int) -> None:
    """AT-09-AUTH-EXT: SSH forward到達後もoperator認証なしでは操作が成立しないこと。

    Phase 2-B.2で確立したrepository外の一時sshd harnessを再利用し、forward経由でも
    無認証401・正token200が成立することを実機・実通信で確認する。VPSへは接続しない。
    """
    ssh_bin_candidates = ["/usr/sbin/sshd"]
    sshd_path = next((p for p in ssh_bin_candidates if Path(p).exists()), None)
    if not sshd_path:
        record("AT-09-AUTH-EXT: SSH forward経由の認証境界", False, "BLOCKED: sshdバイナリが見つからずtest harnessを構成できない")
        return

    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b3_sshd_") as tmp:
        tmp_path = Path(tmp)
        host_key = tmp_path / "hostkey"
        client_key = tmp_path / "clientkey"
        authorized_keys = tmp_path / "authorized_keys"
        sshd_config = tmp_path / "sshd_config"
        pid_file = tmp_path / "sshd.pid"

        gen1 = _run(["ssh-keygen", "-t", "ed25519", "-f", str(host_key), "-N", "", "-q"])
        gen2 = _run(["ssh-keygen", "-t", "ed25519", "-f", str(client_key), "-N", "", "-q"])
        if gen1.returncode != 0 or gen2.returncode != 0:
            record("AT-09-AUTH-EXT: SSH forward経由の認証境界", False, "BLOCKED: ssh-keygenに失敗")
            return
        authorized_keys.write_text((client_key.with_suffix(".pub")).read_text(), encoding="utf-8")
        os.chmod(authorized_keys, 0o600)

        sshd_test_port = 2300 + (hash(_RUN_TAG) % 300)
        sshd_config.write_text(
            "\n".join(
                [
                    f"Port {sshd_test_port}",
                    "ListenAddress 127.0.0.1",
                    f"HostKey {host_key}",
                    f"PidFile {pid_file}",
                    f"AuthorizedKeysFile {authorized_keys}",
                    "PasswordAuthentication no",
                    "KbdInteractiveAuthentication no",
                    "PermitRootLogin no",
                    "AllowTcpForwarding local",
                    "X11Forwarding no",
                    "PermitOpen 127.0.0.1:*",
                    "ForceCommand /usr/bin/true",
                    "UsePAM no",
                    "StrictModes no",
                    "LogLevel ERROR",
                ]
            ),
            encoding="utf-8",
        )
        os.chmod(sshd_config, 0o600)
        os.chmod(host_key, 0o600)

        verify = _run([sshd_path, "-f", str(sshd_config), "-t"])
        if verify.returncode != 0:
            record("AT-09-AUTH-EXT: SSH forward経由の認証境界", False, f"BLOCKED: sshd_config検証失敗: {verify.stderr}")
            return

        sshd_proc = subprocess.Popen(
            [sshd_path, "-f", str(sshd_config), "-D", "-e"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(tmp_path),
        )
        try:
            time.sleep(1.0)
            if sshd_proc.poll() is not None:
                out, err = sshd_proc.communicate(timeout=2)
                record("AT-09-AUTH-EXT: SSH forward経由の認証境界", False, f"BLOCKED: sshd起動失敗: {err.decode(errors='replace')[:500]}")
                return

            local_forward_port = 12300 + (hash(_RUN_TAG) % 300)
            ssh_cmd = [
                "ssh", "-F", "none",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "BatchMode=yes",
                "-o", "ExitOnForwardFailure=yes",
                "-i", str(client_key),
                "-p", str(sshd_test_port),
                "-L", f"127.0.0.1:{local_forward_port}:127.0.0.1:{operator_host_port}",
                "-N", "127.0.0.1",
            ]
            ssh_client_proc = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                time.sleep(2.0)
                if ssh_client_proc.poll() is not None:
                    out, err = ssh_client_proc.communicate(timeout=2)
                    record(
                        "AT-09-AUTH-EXT: SSH forward経由の認証境界", False,
                        f"BLOCKED: ssh -L 起動失敗: {err.decode(errors='replace')[:500]}", ssh_cmd,
                    )
                    return

                forward_url = f"http://127.0.0.1:{local_forward_port}/api/admin/hazards"
                status, headers, body = http_get(forward_url)
                record(
                    "AT-09-AUTH-EXT: 実ssh -L forward経由、無認証requestが401",
                    status == 401,
                    f"status={status} body={body[:200]}",
                    ssh_cmd,
                )
                status, headers, body = http_get(forward_url, headers={"Authorization": f"Bearer {DUMMY_OPERATOR_SECRET}"})
                record(
                    "AT-09-AUTH-EXT: 実ssh -L forward経由、正tokenで200",
                    status == 200,
                    f"status={status} body={body[:200]}",
                    ssh_cmd,
                )
            finally:
                ssh_client_proc.terminate()
                try:
                    ssh_client_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    ssh_client_proc.kill()
        finally:
            sshd_proc.terminate()
            try:
                sshd_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                sshd_proc.kill()


def public_regression_checks(override_file: Path) -> None:
    fe_host_port = get_host_published_port(override_file, "frontend", 80)
    if not fe_host_port:
        record("public回帰: frontend host port取得", False, "取得失敗")
        return
    base = f"http://127.0.0.1:{fe_host_port}"

    status, _, _ = http_get(base + "/api/admin/config")
    record("public回帰: frontend経由 /api/admin/config が404のまま", status == 404, f"status={status}")

    status, _, _ = http_get(base + "/api/simulation/scenarios")
    record("public回帰: frontend経由 /api/simulation/scenarios が404のまま", status == 404, f"status={status}")

    for path, expected in [("/", 200), ("/live", 200), ("/live/stream", 200)]:
        status, _, _ = http_get(base + path)
        record(f"public回帰: frontend経由 {path} が{expected}", status == expected, f"status={status}")


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------


def check_docker_available() -> bool:
    proc = _run(["docker", "info"])
    ok = proc.returncode == 0
    record("docker daemon available", ok, (proc.stdout + proc.stderr)[-500:])
    return ok


# Phase 2-B.3限定修正（CODEX P2B3-CX-003再指摘対応）: `docker compose config`
# は既定でservice env_fileの中身をresolveして`environment`へ吸収し、rendered
# 出力から`env_file`キー自体を消してしまう。旧実装の`preflight_env_isolation_check()`
# はこの既定resolutionの出力に対して`svc.get("env_file")`を見ていたため、
# env_file resetを外したbad overrideに対しても常に`env_file`キーが存在せず
# 「合格」してしまうfail-openだった（CODEXが独立negative controlで実測・再現）。
# `--no-env-resolution`フラグでenv_fileの生キー残存を直接検査し、さらに
# 既定解決後の`environment`キー集合を既知allowlistと照合する
# （env_file以外の経路での混入も検出する二重チェック）。
EXPECTED_ENVIRONMENT_KEYS = {
    "backend-public": {"API_HOST", "API_PORT", "DEM_FILE_PATH"},
    "backend-operator": {"API_HOST", "API_PORT", "OPERATOR_AUTH_SECRET"},
}


def _rendered_config(override_file: Path, extra_flags: List[str], compose_file: Path = COMPOSE_FILE) -> Optional[dict]:
    cmd = compose_cmd(override_file, ["--profile", "operator", "config"] + extra_flags + ["--format", "json"], compose_file)
    proc = _run(cmd)
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _env_isolation_hits(no_env_resolution_data: dict, default_resolution_data: dict) -> List[tuple]:
    """rendered config 2種（`--no-env-resolution`あり／なし）から、env_file
    残存・許可外environment keyの両方を検出する。戻り値はhitのlist
    （空なら合格）。"""
    hits: List[tuple] = []
    no_env_services = no_env_resolution_data.get("services", {})
    default_services = default_resolution_data.get("services", {})
    for name, allowed_keys in EXPECTED_ENVIRONMENT_KEYS.items():
        svc_raw = no_env_services.get(name, {})
        env_file = svc_raw.get("env_file")
        if env_file:
            hits.append((name, "env_file_present", env_file))

        svc_resolved = default_services.get(name, {})
        environment = svc_resolved.get("environment", {}) or {}
        unexpected_keys = sorted(set(environment.keys()) - allowed_keys)
        if unexpected_keys:
            hits.append((name, "unexpected_environment_keys", unexpected_keys))
    return hits


def preflight_env_isolation_check(override_file: Path, compose_file: Path = COMPOSE_FILE) -> bool:
    """`up`を実行する前に、backend-public / backend-operatorいずれも
    env_file残存が0件・rendered environmentが既知許可key集合のみである
    ことをfail-closedに確認する。このcheckがFAILの場合、呼び出し元は
    `up`を実行してはならない（実`.env`の継承有無を実行前に必ず検出する）。

    `compose_file`は既定で実repositoryの`docker-compose.yml`。
    `env_isolation_negative_control()`（CODEX P2B3-CX-003再指摘対応、
    3回目）だけは完全synthetic base composeを渡し、実repository／実`.env`
    を一切参照させない。"""
    no_env_data = _rendered_config(override_file, ["--no-env-resolution"], compose_file)
    if no_env_data is None:
        record("preflight: --no-env-resolution rendered config取得 succeeds", False)
        return False
    default_data = _rendered_config(override_file, [], compose_file)
    if default_data is None:
        record("preflight: 既定rendered config取得 succeeds", False)
        return False

    hits = _env_isolation_hits(no_env_data, default_data)
    record(
        "preflight: env_file残存0件・rendered environmentが許可key集合のみ（実.env非継承）",
        not hits,
        f"hits={hits}",
    )
    return not hits


def build_synthetic_env_negative_control_fixture(tmp_dir: Path) -> Tuple[Path, Path]:
    """Phase 2-B.3限定修正（CODEX P2B3-CX-003再指摘対応、3回目）:
    `env_isolation_negative_control()`が実repositoryの`docker-compose.yml`・
    実`.env`を一切読まないよう、完全に独立した最小base composeと、
    実秘密ではないsynthetic canary値だけを持つenv fileをtmp_dir内だけに
    作る（実containerは起動しない、`docker compose config`の静的render
    にのみ使う）。"""
    canary_env_path = tmp_dir / "synthetic_canary.env"
    canary_env_path.write_text("SYNTH_CANARY_KEY=synthetic-canary-value-not-real\n", encoding="utf-8")

    synthetic_compose = {
        "services": {
            "backend-public": {
                "image": "alpine:3.20",
                "env_file": [{"path": str(canary_env_path), "required": False}],
                "environment": {"API_HOST": "0.0.0.0", "API_PORT": "8000"},
            },
            "backend-operator": {
                "image": "alpine:3.20",
                "env_file": [{"path": str(canary_env_path), "required": False}],
                "environment": {"API_HOST": "0.0.0.0", "API_PORT": "8100"},
            },
        },
    }
    synthetic_compose_path = tmp_dir / "docker-compose.synthetic.yml"
    synthetic_compose_path.write_text(yaml.dump(synthetic_compose, sort_keys=False), encoding="utf-8")
    return synthetic_compose_path, canary_env_path


def build_bad_override_missing_env_reset(tmp_dir: Path) -> Path:
    """P2B3-CX-003 negative control専用: env_file resetを意図的に外した
    override（container名だけ変更し、synthetic base composeのenv_fileは
    素通しする）。`preflight_env_isolation_check()`がこれを正しく検出し
    Falseを返すことを確認するためだけに使う。"""
    bad_prefix = f"{CONTAINER_PREFIX}-envnegctrl"
    override = {
        "services": {
            "backend-public": {"container_name": f"{bad_prefix}-backend-public"},
            "backend-operator": {"container_name": f"{bad_prefix}-backend-operator"},
        },
    }
    path = tmp_dir / "docker-compose.override.phase2b3.envnegctrl.yml"
    path.write_text(yaml.dump(override, sort_keys=False), encoding="utf-8")
    return path


def _run_isolated(fn, *args, **kwargs):
    """検査関数をグローバルRESULTSから隔離して実行し、戻り値と
    その呼び出し専用の結果listを返す（本来の検査結果を汚染しない）。"""
    global RESULTS
    saved = RESULTS
    RESULTS = []
    try:
        result = fn(*args, **kwargs)
        return result, RESULTS
    finally:
        RESULTS = saved


def env_isolation_negative_control() -> None:
    """CODEXが独立negative controlで実証したfail-open
    （env_file reset省略時もpreflightがPASSしてしまうバグ）の再発防止check。
    完全synthetic base compose・synthetic canary env fileだけを使い、
    実repositoryの`docker-compose.yml`・実`.env`は一切読まない
    （`docker compose config`は静的renderのみでcontainerを起動しないため、
    実Docker操作も発生しない）。"""
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b3_envnegctrl_") as tmp:
        tmp_path = Path(tmp)
        synthetic_compose_path, _canary_env_path = build_synthetic_env_negative_control_fixture(tmp_path)
        bad_override = build_bad_override_missing_env_reset(tmp_path)
        result, inner_results = _run_isolated(
            preflight_env_isolation_check, bad_override, synthetic_compose_path
        )
        record(
            "CTRL-ENV-01: 完全synthetic base compose（実.env非依存）でenv_file reset省略overrideに対しpreflightが正しくFAIL判定する",
            result is False,
            f"result={result} inner={inner_results}",
        )


def preflight_rw_mount_isolation_check(
    override_file: Path, run_tmp_path: Path, compose_file: Path = COMPOSE_FILE
) -> bool:
    """Phase 2-B.3限定修正（CODEX P2B3-CX-003継続指摘対応、4回目）:
    `preflight_env_isolation_check()`はenv_fileだけを検査しており、
    volume mountの取りこぼしは検出できなかった（`osrm-walking`の
    `./data_lake:/data_lake`・`./osrm/foot.lua:/opt/foot.lua`という
    rw bindがoverride対象から漏れ、実repositoryを直接共有したまま
    CODEXに実測された）。本checkは、operator profileで起動する
    **全service**のresolved volumeを列挙し、Docker socket以外のrw
    bind sourceがすべて`run_tmp_path`（このrunがseed_temp_data_dirs()で
    用意した書込可能一時領域）配下であることをfail-closedに確認する。
    service追加やbase Compose変更で同種の取りこぼしが再発しても、
    このcheckが機械的に検出する（個別serviceのvolumes overrideし忘れに
    依存しない）。

    `compose_file`は既定で実`docker-compose.yml`。
    `rw_mount_isolation_negative_control()`だけはsynthetic composeを渡す。
    """
    data = _rendered_config(override_file, [], compose_file)
    if data is None:
        record("preflight: 全service rw mount inventory取得 succeeds", False)
        return False

    # Phase 2-B.3限定修正（CODEX P2B3-CX-003継続指摘対応、5回目）: 旧実装は
    # `source.startswith(run_tmp_resolved)`という文字列prefix比較だったため、
    # run treeと文字列prefixが一致するだけのsibling directory
    # （例: run tree "<tmp>/run" に対し "<tmp>/run_evil"）を誤ってrun tree
    # 配下と判定してしまうfail-openをCODEXが独立negative controlで実証した。
    # `Path.resolve()`後、path component単位（`parents`）で厳密に包含判定する。
    run_tmp_resolved = run_tmp_path.resolve()
    docker_socket = "/var/run/docker.sock"
    hits = []
    for svc_name, svc in data.get("services", {}).items():
        for vol in svc.get("volumes", []) or []:
            if not isinstance(vol, dict) or vol.get("type") != "bind":
                continue
            if vol.get("read_only"):
                continue
            source = str(vol.get("source", ""))
            if source == docker_socket:
                continue
            source_path = Path(source).resolve()
            is_inside = source_path == run_tmp_resolved or run_tmp_resolved in source_path.parents
            if not is_inside:
                hits.append((svc_name, source, vol.get("target")))

    record(
        "preflight: 起動対象全serviceのrw bind sourceがrun tree配下のみ（Docker socket除く）",
        not hits,
        f"hits={hits}",
    )
    return not hits


def _write_synthetic_leaky_fixture(cfg_path: Path, leaky_source: Path) -> Tuple[Path, Path]:
    synthetic_compose = {
        "services": {
            "leaky-service": {
                "image": "alpine:3.20",
                "volumes": [f"{leaky_source}:/leaky"],
            },
        },
    }
    synthetic_compose_path = cfg_path / "docker-compose.synthetic-rwmount.yml"
    synthetic_compose_path.write_text(yaml.dump(synthetic_compose, sort_keys=False), encoding="utf-8")

    empty_override = cfg_path / "docker-compose.override.empty.yml"
    empty_override.write_text(yaml.dump({"services": {}}, sort_keys=False), encoding="utf-8")
    return synthetic_compose_path, empty_override


def rw_mount_isolation_negative_control() -> None:
    """CODEXが実測したosrm-walkingのrw bind取りこぼしと同型のfail-openを
    `preflight_rw_mount_isolation_check()`が正しく検出することを、
    実repositoryを使わないsynthetic serviceで確認する。"""
    # CTRL-RWMOUNT-01: run treeと無関係な外部path
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b3_rwmountnegctrl_run_") as fake_run_tmp, \
            tempfile.TemporaryDirectory(prefix="ohg2_phase2b3_rwmountnegctrl_outside_") as outside_tmp, \
            tempfile.TemporaryDirectory(prefix="ohg2_phase2b3_rwmountnegctrl_cfg_") as cfg_tmp:
        fake_run_path = Path(fake_run_tmp)
        outside_path = Path(outside_tmp)
        cfg_path = Path(cfg_tmp)

        synthetic_compose_path, empty_override = _write_synthetic_leaky_fixture(cfg_path, outside_path)

        result, inner_results = _run_isolated(
            preflight_rw_mount_isolation_check, empty_override, fake_run_path, synthetic_compose_path
        )
        record(
            "CTRL-RWMOUNT-01: run tree外を指すrw bindを持つsynthetic serviceに対しpreflightが正しくFAIL判定する",
            result is False,
            f"result={result} inner={inner_results}",
        )

    # CTRL-RWMOUNT-02（CODEX P2B3-CX-003継続指摘対応、5回目）: run treeと
    # 文字列prefixが一致するだけのsibling directory（例: run tree "run" に
    # 対し兄弟directory "run_evil"）を指すrw bind。旧実装の
    # `source.startswith(run_tmp_resolved)`という文字列比較はこれを誤って
    # run tree配下と判定してしまうfail-openをCODEXが実証した。`Path.parents`
    # 判定への修正後、このsibling caseも正しくFAILとなることを確認する。
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b3_rwmountnegctrl2_") as parent_tmp:
        parent_path = Path(parent_tmp)
        fake_run_path2 = parent_path / "run"
        sibling_path2 = parent_path / "run_evil"
        fake_run_path2.mkdir()
        sibling_path2.mkdir()

        synthetic_compose_path2, empty_override2 = _write_synthetic_leaky_fixture(parent_path, sibling_path2)

        result2, inner_results2 = _run_isolated(
            preflight_rw_mount_isolation_check, empty_override2, fake_run_path2, synthetic_compose_path2
        )
        record(
            "CTRL-RWMOUNT-02: run tree名と文字列prefixが一致するsibling directory（\"run_evil\" vs \"run\"）を指すrw bindに対しpreflightが正しくFAIL判定する",
            result2 is False,
            f"result={result2} inner={inner_results2}",
        )


def main() -> int:
    print(f"run tag: {_RUN_TAG}")
    print(f"project name: {PROJECT_NAME}")
    print(f"operator host port: {OPERATOR_HOST_PORT}")

    run_phase2b1_regression()
    run_phase2b3_unit_fixtures()

    if not check_docker_available():
        print("Docker daemon not available — aborting live checks.")
        # Docker未使用のためevidence一時領域は作成していない。
        exit_code = 1
        print()
        print(f"TOTAL: {len(RESULTS)}  PASS: {len(RESULTS)}  FAIL: {sum(1 for r in RESULTS if not r['pass'])}")
        return exit_code

    run_phase2b2_regression()
    env_isolation_negative_control()
    rw_mount_isolation_negative_control()

    # Phase 2-B.3限定修正（CODEX P2B3-CX-003再指摘対応、3回目）: evidence出力
    # （override compose・summary JSON）とdata_lake/data_runtime等のseed copy
    # を、run全体を包む単一のtemporary directory配下へ統一した。この
    # with-blockを抜けるとPythonの`TemporaryDirectory`がtree全体を確実に
    # 削除する（正常終了・例外いずれの経路でも）。ブロックを抜けた直後に
    # 明示的な残存確認も行う。
    run_tmp_holder: Dict[str, Path] = {}
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b3_run_") as run_tmp:
        run_tmp_path = Path(run_tmp)
        run_tmp_holder["path"] = run_tmp_path

        seeded = seed_temp_data_dirs(run_tmp_path)
        override_file = build_override_compose(run_tmp_path, seeded)
        (run_tmp_path / "docker-compose.override.used.yml").write_text(
            override_file.read_text(encoding="utf-8"), encoding="utf-8"
        )
        try:
            if preflight_env_isolation_check(override_file) and preflight_rw_mount_isolation_check(override_file, run_tmp_path):
                up_cmd = ["--profile", "operator", "up", "-d", "--build"]
                proc = _run(compose_cmd(override_file, up_cmd), timeout=600)
                record(
                    "operator profile stack起動 (dummy token) succeeds",
                    proc.returncode == 0,
                    (proc.stdout + proc.stderr)[-2000:],
                    compose_cmd(override_file, up_cmd),
                )
                if proc.returncode == 0:
                    ready_ok, ready_detail = wait_backend_public_ready(override_file)
                    record("backend-publicがhealthyになる", ready_ok, ready_detail)

                    published = get_host_published_port(override_file, "operator-publish-proxy", OPERATOR_TARGET_PORT)
                    operator_host_port = int(published) if published else OPERATOR_HOST_PORT
                    op_ready_ok, op_ready_detail = wait_operator_ready(operator_host_port)
                    record("operator (/operator/health)がhealthyになる", op_ready_ok, op_ready_detail)

                    if op_ready_ok:
                        at10_host_loopback_auth_checks(operator_host_port)
                        at09_auth_ext_ssh_forward_auth_check(operator_host_port)

                    if ready_ok:
                        public_regression_checks(override_file)
            else:
                print("preflight (env isolation / rw mount isolation) check failed — aborting before any container start (fail-closed).")
        finally:
            cleanup_stack(override_file)

        write_summary(run_tmp_path)

    # with-blockを抜けた直後: temporary directory自体が確実に削除されている
    # ことを明示確認する（CODEX指摘「固定evidence 2ファイル残存」の再発防止）。
    residue_path = run_tmp_holder["path"]
    record(
        "cleanup: run全体のevidence一時ディレクトリが削除され残存0件",
        not residue_path.exists(),
        f"path={residue_path}",
    )

    failed = [r for r in RESULTS if not r["pass"]]
    print()
    print(f"TOTAL: {len(RESULTS)}  PASS: {len(RESULTS) - len(failed)}  FAIL: {len(failed)}")
    print(f"exit code: {1 if failed else 0}")
    if failed:
        print("FAILED CHECKS:")
        for r in failed:
            print(f"  - {r['name']}")
    return 1 if failed else 0


def write_summary(evidence_dir: Path) -> None:
    """summaryをrun固有の一時evidence_dir配下へ書く。呼び出し元の
    `with tempfile.TemporaryDirectory()`ブロックが終了すると、このfileを
    含むtree全体が自動的に削除される（一時artifactとしてrepository外へ
    残さない、CODEX P2B3-CX-003再指摘対応）。"""
    failed = [r for r in RESULTS if not r["pass"]]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_tag": _RUN_TAG,
        "project_name": PROJECT_NAME,
        "operator_host_port": OPERATOR_HOST_PORT,
        "total_checks": len(RESULTS),
        "pass_count": len(RESULTS) - len(failed),
        "fail_count": len(failed),
        "exit_code": 1 if failed else 0,
        "results": RESULTS,
    }
    (evidence_dir / "phase2b3_operator_security_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())

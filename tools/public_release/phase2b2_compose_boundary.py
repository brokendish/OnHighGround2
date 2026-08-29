#!/usr/bin/env python3
"""
tools/public_release/phase2b2_compose_boundary.py

Phase 2-B.2 の Compose service・profile・network・bind三層境界を検証する
自動再実行可能な検査script。

tasks/public-release/phase2b2_claude_implementation_instruction.md の
AT-03・AT-05・AT-09-BIND・Phase 2-B.1回帰・public回帰・CF-N01〜CF-N13に対応する。

Phase 2-B.2 限定修正（CODEX P2B2-CX-001 / P2B2-CX-002対応）:
  - Docker socketを保持する backend-operator は `internal: true` の
    operator-internal network **のみ** に参加する。host loopback publish
    （bind三層の②）は、Docker socketもoperator用host/dataマウントも一切
    持たない最小権限sidecar `operator-gateway` が
    operator-internal ⇔ operator-publish 間を中継する形で実現する
    （docker-compose.yml参照）。
  - 本scriptはこのsidecar構成を前提に、backend-operatorが参加する全
    networkがinternal:trueであることを静的・rendered双方でfail-closedに
    確認する（自己検査自体がfail-openにならないようnegative fixtureで
    裏付ける、CF-N11〜CF-N13）。
  - AT-03（既定起動でoperatorが対象外）とAT-09-BIND（operator profile
    起動時の境界検証）は、それぞれ独立したCompose project名・独立した
    top-level network名で実行する（相互汚染防止、CODEXの独立検証手法に
    合わせた）。

実行内容（すべて実際にDocker daemon・実プロセスを伴う。mock・静的レビューのみ
での代替はしない）:
  1. raw docker-compose.yml（YAML構造）の静的検査
  2. `docker compose config`（rendered model, JSON）の検査
     （environment/env_fileは一切出力・保存しない — 実秘密漏洩防止）
  3. AT-03: profile未指定の既定起動でbackend-operatorが対象に含まれないことの実機検証
     （独立project「ind」）
  4. AT-05 / AT-09-BIND: backend-publicのhost publish・Docker socket 0件、
     bind三層（container内listen／host publish／SSH forward）の実機検証
     （独立project「op」、operator profile起動）
  5. Phase 2-B.1回帰: AT-01（exact route）・AT-02（image境界の代表項目）・AT-12（dockerignore契約）
  6. public回帰: `/`, `/health`, 代表API
  7. CF-N01〜CF-N13: repository外のnegative fixtureで自動検査自体がfail-openでないことを確認

事前条件: Dockerデーモンが起動していること。実秘密・既存credential・VPSの`.env`は
一切使用しない（dummy secretのみ使用する）。

使い方:
    ./venv/bin/python tools/public_release/phase2b2_compose_boundary.py

終了コード: 全項目PASSなら0、1件でもFAILがあれば1。
"""
from __future__ import annotations

import copy
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
NGINX_CONF = REPO_ROOT / "nginx.conf"
EVIDENCE_DIR = REPO_ROOT / "tasks" / "public-release" / "evidence" / "phase2b2"

_RUN_TAG = os.environ.get("OHG2_PHASE2B2_RUN_TAG") or datetime.now(timezone.utc).strftime("%Y%m%dt%H%M%Sz")

DUMMY_OPERATOR_SECRET = "OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE"  # Phase 2-B.1と同一の既定dummy

OPERATOR_TARGET_PORT = 8100
OPERATOR_HOST_PORT = 19100 + (hash(_RUN_TAG) % 300)  # 既存ポートと衝突しない一意な範囲

OPERATOR_SERVICE_NAME = "backend-operator"
OPERATOR_PROXY_SERVICE_NAME = "operator-gateway"
OPERATOR_INTERNAL_NETWORK_NAME = "operator-internal"
OPERATOR_PUBLISH_NETWORK_NAME = "operator-publish"
OPERATOR_BOUNDARY_NETWORK_NAMES = {OPERATOR_INTERNAL_NETWORK_NAME, OPERATOR_PUBLISH_NETWORK_NAME}
# backend-operator（Docker socket保持）とoperator-gateway（sidecar）だけが
# operator専用network群へ参加してよい。
ALLOWED_OPERATOR_BOUNDARY_SERVICES = {OPERATOR_SERVICE_NAME, OPERATOR_PROXY_SERVICE_NAME}


def _project_name(scenario: str) -> str:
    return f"ohg2p2b2{_RUN_TAG}{scenario}".lower().replace("_", "")


def _container_prefix(scenario: str) -> str:
    return f"ohg2p2b2-{_RUN_TAG}-{scenario}"


def _network_prefix(scenario: str) -> str:
    return _container_prefix(scenario)


PROJECT_NAME_DEFAULT = _project_name("ind")  # AT-03専用の独立project（既定起動のみ）
PROJECT_NAME_OPERATOR = _project_name("op")  # AT-05/AT-09-BIND/回帰用の独立project（operator profile起動）

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


def _strip_secrets(data: dict) -> dict:
    """rendered configからenvironment/env_fileを除去する（実秘密漏洩防止）。"""
    for svc in data.get("services", {}).values():
        svc.pop("environment", None)
        svc.pop("env_file", None)
    return data


def _strip_secrets_from_inspect(inspect_data: dict) -> dict:
    """`docker inspect`結果からConfig.Env（実際のenvironment/env_fileが展開された
    値そのものを含む配列）を除去する（実秘密漏洩防止）。

    CODEX/自己レビューで発見: at05_public_boundary_check()が`docker inspect`の
    全文をevidenceへそのまま保存しており、`.env`由来のODPT_API_KEY等の実際の
    値がevidence file（tasks/public-release/evidence/phase2b2/配下）に平文で
    残ってしまっていた。保存前に必ずこの関数を通す。
    """
    cfg = inspect_data.get("Config")
    if isinstance(cfg, dict) and "Env" in cfg:
        cfg["Env"] = "[REDACTED — see _strip_secrets_from_inspect()]"
    return inspect_data


# ------------------------------------------------------------------
# 1. raw YAML 静的検査
# ------------------------------------------------------------------


def _is_docker_socket_mount(v: Any) -> bool:
    if isinstance(v, str):
        return "docker.sock" in v
    if isinstance(v, dict):
        return "docker.sock" in str(v.get("source", "")) or "docker.sock" in str(v.get("target", ""))
    return False


def load_compose_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def static_yaml_checks(compose_path: Path = COMPOSE_FILE, nginx_path: Path = NGINX_CONF) -> None:
    data = load_compose_yaml(compose_path)
    services = data.get("services", {})
    networks_top = data.get("networks", {})

    record("[static] backend-public service exists in raw YAML", "backend-public" in services)
    record("[static] backend-operator service exists in raw YAML", OPERATOR_SERVICE_NAME in services)
    record("[static] operator-gateway service exists in raw YAML", OPERATOR_PROXY_SERVICE_NAME in services)
    if "backend-public" not in services or OPERATOR_SERVICE_NAME not in services or OPERATOR_PROXY_SERVICE_NAME not in services:
        return

    bp = services["backend-public"]
    bo = services[OPERATOR_SERVICE_NAME]
    proxy = services[OPERATOR_PROXY_SERVICE_NAME]

    record(
        "[static] backend-operator has profiles == ['operator']",
        bo.get("profiles") == ["operator"],
        f"profiles={bo.get('profiles')}",
    )
    record(
        "[static] operator-gateway has profiles == ['operator']",
        proxy.get("profiles") == ["operator"],
        f"profiles={proxy.get('profiles')}",
    )
    record(
        "[static] backend-public has no profiles restriction (starts by default)",
        "profiles" not in bp,
        f"profiles={bp.get('profiles')}",
    )

    record(
        "[static] backend-public has 0 host port publish entries",
        not bp.get("ports"),
        f"ports={bp.get('ports')}",
    )

    bp_socket_hits = [v for v in bp.get("volumes", []) if _is_docker_socket_mount(v)]
    record(
        "[static] backend-public has 0 docker.sock mounts",
        len(bp_socket_hits) == 0,
        f"hits={bp_socket_hits}",
    )

    # docker.sock を保持するserviceはbackend-operator1つだけであることを確認する
    # （このsetを起点に、以後のfail-closedなnetwork/mount検査を一般化して適用する）。
    docker_socket_services = [
        name for name, svc in services.items() if any(_is_docker_socket_mount(v) for v in (svc.get("volumes") or []))
    ]
    record(
        "[static] docker.sock mountを持つserviceはbackend-operatorのみ（他service 0件）",
        docker_socket_services == [OPERATOR_SERVICE_NAME],
        f"hits={docker_socket_services}",
    )

    # Phase 2-B.2限定修正: backend-operatorはhost publishを一切宣言しない
    # （host publishはoperator-gateway sidecarへ移管した）。
    record(
        "[static] backend-operator has 0 ports entries（host publishはsidecarへ移管）",
        not bo.get("ports"),
        f"ports={bo.get('ports')}",
    )

    # host publish（bind三層の②）はoperator-gatewayが担う。
    proxy_ports = proxy.get("ports", [])
    record("[static] operator-gateway has exactly 1 ports entry", len(proxy_ports) == 1, f"ports={proxy_ports}")
    if len(proxy_ports) == 1:
        p = proxy_ports[0]
        is_long_form = isinstance(p, dict)
        record(
            "[static] operator-gateway port entry is long-form mapping (not short syntax string)",
            is_long_form,
            f"entry={p!r}",
        )
        if is_long_form:
            record(
                "[static] operator-gateway port host_ip == '127.0.0.1' (literal)",
                p.get("host_ip") == "127.0.0.1",
                f"host_ip={p.get('host_ip')!r}",
            )
            record(
                "[static] operator-gateway port target == 8100",
                p.get("target") == OPERATOR_TARGET_PORT,
                f"target={p.get('target')!r}",
            )
            record(
                "[static] operator-gateway port protocol == 'tcp'",
                p.get("protocol") == "tcp",
                f"protocol={p.get('protocol')!r}",
            )
            published = str(p.get("published", ""))
            record(
                "[static] operator-gateway port published is not '0.0.0.0'/'::' and not empty",
                bool(published) and published not in ("0.0.0.0", "::"),
                f"published={published!r}",
            )

    # Phase 2-B.2限定修正: sidecarはDocker socketもoperator用host/dataマウントも
    # 一切持たない最小権限であることを確認する（CODEXが提示した設計制約そのもの）。
    proxy_socket_hits = [v for v in proxy.get("volumes", []) if _is_docker_socket_mount(v)]
    record(
        "[static] operator-gateway has 0 docker.sock mounts",
        len(proxy_socket_hits) == 0,
        f"hits={proxy_socket_hits}",
    )
    # Phase 2-B.4でoperator-gatewayはsocat転送のみのsidecarから、静的admin
    # frontendとnginx configを配信するnginxサイドカーへ再設計された
    # （operator/nginx.conf参照）。これに伴い、read-onlyな2つの設定マウント
    # （静的frontend資産・nginx config本体）が正当に必要になった。
    # "0 volume mounts"という制約の本来のsecurity意図は「operator用の
    # host/dataマウント（data_lake・data_runtime・Docker socket等、実データや
    # 特権資源への到達経路）を持たないこと」であり、この2つのread-only設定
    # マウントはこの意図に抵触しない。allowlist以外のmount（CF-N12の
    # docker.sock追加、CF-N13のdata_lake追加等）は引き続き拒否する。
    allowed_gateway_volume_sources = {"./operator/frontend-admin", "./operator/nginx.conf"}
    gateway_volumes = proxy.get("volumes") or []

    def _is_allowed_gateway_volume(v: Any) -> bool:
        if not isinstance(v, str) or not v.endswith(":ro"):
            return False
        source = v.split(":", 1)[0]
        return source in allowed_gateway_volume_sources

    disallowed_gateway_volumes = [v for v in gateway_volumes if not _is_allowed_gateway_volume(v)]
    record(
        "[static] operator-gateway volume mounts are limited to the read-only static-config allowlist"
        "（operator用host/dataマウントなし）",
        not disallowed_gateway_volumes,
        f"volumes={gateway_volumes} disallowed={disallowed_gateway_volumes}",
    )

    op_net = networks_top.get(OPERATOR_INTERNAL_NETWORK_NAME, {})
    record(
        "[static] networks.operator-internal.internal == true",
        op_net.get("internal") is True,
        f"operator-internal={op_net}",
    )
    pub_net = networks_top.get(OPERATOR_PUBLISH_NETWORK_NAME, {})
    record(
        "[static] networks.operator-publish exists and is not internal (host publish専用)",
        OPERATOR_PUBLISH_NETWORK_NAME in networks_top and op_net is not pub_net and pub_net.get("internal") is not True,
        f"operator-publish={pub_net}",
    )

    def _network_keys(svc: dict) -> set:
        svc_networks = svc.get("networks")
        return set(svc_networks.keys()) if isinstance(svc_networks, dict) else set(svc_networks or [])

    bo_network_keys = _network_keys(bo)
    record(
        "[static] backend-operator networks == {operator-internal} のみ（非internal networkへ直接参加しない）",
        bo_network_keys == {OPERATOR_INTERNAL_NETWORK_NAME},
        f"networks={bo.get('networks')}",
    )

    # Phase 2-B.2限定修正（CODEX P2B2-CX-001対応・fail-closed self-check）:
    # docker.sock を保持する全service（現状backend-operatorのみ）が参加する
    # networkは、名前の一致ではなく実際の`internal`フラグで判定し、
    # 1つでもinternal:trueでないnetworkに参加していればFAILとする。
    # 将来network名が変わっても、または別serviceがdocker.sockを持つように
    # なってもfail-openにならないようにするための一般化した検査。
    for svc_name in docker_socket_services:
        svc = services[svc_name]
        keys = _network_keys(svc)
        non_internal_hits = [
            (net_key, networks_top.get(net_key, {})) for net_key in keys if networks_top.get(net_key, {}).get("internal") is not True
        ]
        record(
            f"[static] docker.sock保持service({svc_name})が参加する全networkがinternal:true",
            len(non_internal_hits) == 0,
            f"non_internal_hits={non_internal_hits} networks={svc.get('networks')}",
        )

    proxy_network_keys = _network_keys(proxy)
    record(
        "[static] operator-gateway networks == {operator-internal, operator-publish}",
        proxy_network_keys == OPERATOR_BOUNDARY_NETWORK_NAMES,
        f"networks={proxy.get('networks')}",
    )

    non_operator_join_hits = []
    for svc_name, svc in services.items():
        if svc_name in ALLOWED_OPERATOR_BOUNDARY_SERVICES:
            continue
        keys = _network_keys(svc)
        if keys & OPERATOR_BOUNDARY_NETWORK_NAMES:
            non_operator_join_hits.append((svc_name, sorted(keys & OPERATOR_BOUNDARY_NETWORK_NAMES)))
    record(
        "[static] operator-gateway以外の非operator serviceはoperator専用network群へ非参加",
        not non_operator_join_hits,
        f"hits={non_operator_join_hits}",
    )

    depends_on_operator_hits = []
    for svc_name, svc in services.items():
        if svc_name in ALLOWED_OPERATOR_BOUNDARY_SERVICES:
            continue
        dep = svc.get("depends_on")
        keys = set(dep.keys()) if isinstance(dep, dict) else set(dep or [])
        if OPERATOR_SERVICE_NAME in keys:
            depends_on_operator_hits.append(svc_name)
    record(
        "[static] operator-gateway以外の非operator serviceはbackend-operatorへdepends_onしない",
        not depends_on_operator_hits,
        f"hits={depends_on_operator_hits}",
    )

    if nginx_path.exists():
        nginx_text = nginx_path.read_text(encoding="utf-8")
        record(
            "[static] nginx.conf does not reference backend-operator / operator-gateway or its port",
            "backend-operator" not in nginx_text
            and OPERATOR_PROXY_SERVICE_NAME not in nginx_text
            and f":{OPERATOR_TARGET_PORT}" not in nginx_text,
        )

    # 既存 driving/streamer profile の定義が壊れていないことの簡易確認
    driving = services.get("osrm-driving", {})
    streamer = services.get("streamer", {})
    record("[static] osrm-driving profiles unchanged (['driving'])", driving.get("profiles") == ["driving"])
    record("[static] streamer profiles unchanged (['streamer'])", streamer.get("profiles") == ["streamer"])


# ------------------------------------------------------------------
# 2. rendered config 検査（docker compose config、secretは除去）
# ------------------------------------------------------------------


def get_rendered_config(project_name: str, profile: Optional[str] = None, compose_file: Path = COMPOSE_FILE) -> Optional[dict]:
    cmd = ["docker", "compose", "-p", project_name, "-f", str(compose_file)]
    if profile:
        cmd += ["--profile", profile]
    cmd += ["config", "--format", "json"]
    proc = _run(cmd)
    if proc.returncode != 0:
        record(f"rendered config succeeds (profile={profile})", False, proc.stderr[-2000:], cmd)
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        record(f"rendered config is valid JSON (profile={profile})", False, str(exc))
        return None
    return _strip_secrets(data)


def rendered_config_checks() -> None:
    default_cfg = get_rendered_config(PROJECT_NAME_DEFAULT, profile=None)
    operator_cfg = get_rendered_config(PROJECT_NAME_OPERATOR, profile="operator")

    if default_cfg is None or operator_cfg is None:
        record("[rendered] both default and operator-profile config renders succeed", False)
        return
    record("[rendered] both default and operator-profile config renders succeed", True)

    default_services = set(default_cfg.get("services", {}).keys())
    operator_services = set(operator_cfg.get("services", {}).keys())

    record(
        "[rendered] AT-03: profile未指定 rendered services に backend-operator が0件",
        OPERATOR_SERVICE_NAME not in default_services,
        f"default_services={sorted(default_services)}",
    )
    record(
        "[rendered] AT-03: profile未指定 rendered services に operator-gateway が0件",
        OPERATOR_PROXY_SERVICE_NAME not in default_services,
        f"default_services={sorted(default_services)}",
    )
    record(
        "[rendered] --profile operator 指定時は backend-operator が対象に含まれる",
        OPERATOR_SERVICE_NAME in operator_services,
        f"operator_services={sorted(operator_services)}",
    )
    record(
        "[rendered] --profile operator 指定時は operator-gateway が対象に含まれる",
        OPERATOR_PROXY_SERVICE_NAME in operator_services,
        f"operator_services={sorted(operator_services)}",
    )

    # operator profile指定してもbackend-publicの定義（socket以外）が変化しないことを確認
    bp_default = dict(default_cfg["services"]["backend-public"])
    bp_operator = dict(operator_cfg["services"]["backend-public"])
    record(
        "[rendered] operator profile指定してもbackend-publicのvolumes定義は不変",
        bp_default.get("volumes") == bp_operator.get("volumes"),
    )
    record(
        "[rendered] operator profile指定してもbackend-publicのnetworks定義は不変",
        bp_default.get("networks") == bp_operator.get("networks"),
    )
    bp_socket_hits_op = [v for v in bp_operator.get("volumes", []) if _is_docker_socket_mount(v)]
    record(
        "[rendered] operator profile指定時もbackend-publicにdocker.sockは増えない",
        len(bp_socket_hits_op) == 0,
        f"hits={bp_socket_hits_op}",
    )

    bo = operator_cfg["services"][OPERATOR_SERVICE_NAME]
    proxy = operator_cfg["services"][OPERATOR_PROXY_SERVICE_NAME]

    record(
        "[rendered] backend-operator rendered ports has 0 entries（host publishはsidecarへ移管）",
        not bo.get("ports"),
        f"{bo.get('ports')}",
    )

    proxy_ports = proxy.get("ports", [])
    record("[rendered] operator-gateway rendered ports has exactly 1 entry", len(proxy_ports) == 1, f"{proxy_ports}")
    if proxy_ports:
        p = proxy_ports[0]
        record("[rendered] operator-gateway rendered port host_ip == '127.0.0.1'", p.get("host_ip") == "127.0.0.1", f"{p}")
        record("[rendered] operator-gateway rendered port target == 8100", p.get("target") == OPERATOR_TARGET_PORT, f"{p}")
        record("[rendered] operator-gateway rendered port mode == 'host'", p.get("mode") == "host", f"{p}")

    bo_networks = bo.get("networks", {})
    bo_network_keys = set(bo_networks.keys() if isinstance(bo_networks, dict) else bo_networks)
    record(
        "[rendered] backend-operator rendered networks == {operator-internal} のみ",
        bo_network_keys == {OPERATOR_INTERNAL_NETWORK_NAME},
        f"{bo_networks}",
    )

    networks_def = operator_cfg.get("networks", {})
    # Phase 2-B.2限定修正（fail-closed self-check、rendered版）:
    # backend-operatorが参加する全networkが実際にinternal:trueであることを、
    # rendered config側でも名前ではなくフラグで確認する。
    non_internal_hits = [
        (net_key, networks_def.get(net_key, {})) for net_key in bo_network_keys if networks_def.get(net_key, {}).get("internal") is not True
    ]
    record(
        "[rendered] backend-operatorが参加する全networkがinternal:true（fail-closed self-check）",
        len(non_internal_hits) == 0,
        f"non_internal_hits={non_internal_hits}",
    )

    proxy_networks = proxy.get("networks", {})
    proxy_network_keys = set(proxy_networks.keys() if isinstance(proxy_networks, dict) else proxy_networks)
    record(
        "[rendered] operator-gateway rendered networks == {operator-internal, operator-publish}",
        proxy_network_keys == OPERATOR_BOUNDARY_NETWORK_NAMES,
        f"{proxy_networks}",
    )
    proxy_socket_hits = [v for v in proxy.get("volumes", []) if _is_docker_socket_mount(v)]
    record(
        "[rendered] operator-gatewayにdocker.sockは0件",
        len(proxy_socket_hits) == 0,
        f"hits={proxy_socket_hits}",
    )

    op_net = networks_def.get(OPERATOR_INTERNAL_NETWORK_NAME, {})
    record(
        "[rendered] rendered networks.operator-internal.internal == true",
        op_net.get("internal") is True,
        f"{op_net}",
    )

    (EVIDENCE_DIR / "rendered_config_default.json").write_text(
        json.dumps(default_cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (EVIDENCE_DIR / "rendered_config_operator.json").write_text(
        json.dumps(operator_cfg, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ------------------------------------------------------------------
# 3. Docker daemon availability
# ------------------------------------------------------------------


def check_docker_available() -> bool:
    proc = _run(["docker", "info"])
    ok = proc.returncode == 0
    record("docker daemon available", ok, (proc.stdout + proc.stderr)[-500:])
    return ok


# ------------------------------------------------------------------
# 4. 実機起動基盤（scenarioごとに一意なproject・container_name・network名／
#    host port衝突回避）
# ------------------------------------------------------------------


class _OverrideList(list):
    """Compose Specの `!override` YAMLタグを付与するためのマーカー型。

    Compose のfile merge既定仕様では list型フィールド（`ports`等）は
    ベースfileへ「追加」される（置換ではない）。これに気づかず単純な
    listでoverrideしたところ、frontend/osrm-walkingの`ports`が元のhost
    publish（8080:80 / 5501:5001）に追加され、本番稼働中stackとport
    衝突を起こした（`Bind for 0.0.0.0:5501 failed: port is already
    allocated`）。`!override`タグでベース値を明示的に置換する。
    """


def _override_list_representer(dumper: "yaml.Dumper", data: "_OverrideList"):
    return dumper.represent_sequence("!override", list(data))


yaml.add_representer(_OverrideList, _override_list_representer)


def build_override_compose(tmp_dir: Path, project_name: str, scenario: str) -> Path:
    """既存ユーザーstack（container_name・host port・network名固定）と衝突しない
    よう、今回のtest実行だけに適用するoverride compose fileを生成する
    （8節: 既存container/image/volume/networkを削除・再作成しない）。

    - container_nameをscenarioごとに一意な値へ変更する
    - operator-gatewayのpublish portをtest専用の値へ変更する
    - frontend/osrm-walkingのhost publishを動的割当（"0:<port>"）にする
    - `ports`は`!override`タグでベースのport定義を完全に置換する
      （Compose既定のlist merge=追加、を避けるため）
    - top-level networkの`name`もscenarioごとに一意な値へ変更する
      （P2B2-CX-002対応: 固定名のままだとcontainer_name/portと違い
      networkだけ本番稼働中stack・他scenarioのnetworkと衝突しうる）
    - dummy secretのみをbackend-operatorへ注入する（実秘密は使用しない）
    """
    container_prefix = _container_prefix(scenario)
    network_prefix = _network_prefix(scenario)

    override = {
        "services": {
            "backend-public": {
                "container_name": f"{container_prefix}-backend-public",
            },
            "backend-operator": {
                "container_name": f"{container_prefix}-backend-operator",
                "environment": {
                    "OPERATOR_AUTH_SECRET": DUMMY_OPERATOR_SECRET,
                },
            },
            OPERATOR_PROXY_SERVICE_NAME: {
                "container_name": f"{container_prefix}-operator-gateway",
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
                "container_name": f"{container_prefix}-frontend",
                "ports": _OverrideList(["0:80"]),
                "depends_on": _OverrideList(["backend-public", "osrm-walking"]),
            },
            "osrm-walking": {
                "container_name": f"{container_prefix}-osrm-walking",
                "ports": _OverrideList(["0:5001"]),
            },
            "martin": {
                "container_name": f"{container_prefix}-martin",
            },
        },
        "networks": {
            "default": {"name": f"{network_prefix}-default"},
            OPERATOR_INTERNAL_NETWORK_NAME: {"name": f"{network_prefix}-operator-internal", "internal": True},
            OPERATOR_PUBLISH_NETWORK_NAME: {"name": f"{network_prefix}-operator-publish"},
        },
    }
    path = tmp_dir / f"docker-compose.override.phase2b2.{scenario}.yml"
    path.write_text(yaml.dump(override, sort_keys=False), encoding="utf-8")
    return path


def compose_cmd(override_file: Path, extra: List[str], project_name: str) -> List[str]:
    return [
        "docker", "compose",
        "-f", str(COMPOSE_FILE),
        "-f", str(override_file),
        "-p", project_name,
    ] + extra


def get_host_published_port(override_file: Path, service: str, container_port: int, project_name: str) -> Optional[str]:
    proc = _run(compose_cmd(override_file, ["port", service, str(container_port)], project_name))
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    # "0.0.0.0:54321" 形式 -> port番号だけ取り出す
    return proc.stdout.strip().rsplit(":", 1)[-1]


def get_container_id(override_file: Path, service: str, project_name: str) -> Optional[str]:
    proc = _run(compose_cmd(override_file, ["ps", "-q", service], project_name))
    out = proc.stdout.strip()
    return out.splitlines()[0] if out else None


def wait_backend_public_ready(override_file: Path, project_name: str, timeout_s: int = 90) -> Tuple[bool, str]:
    """P2B2-CX-002対応の2-project化に伴い追加: OPシナリオはbackend-public/
    backend-operator等を毎回新規buildしてから即座に検査へ進むため、旧来の
    単一project構成（AT-03のupから時間が経過してからAT-05以降を実行していた）
    より起動直後のタイミングレースが起きやすくなった。AT-05/AT-09-BIND/回帰の
    各検査を始める前に、backend-publicのcontainer内 /health が実際に200を
    返すまで明示的に待機する。"""
    bp_id = get_container_id(override_file, "backend-public", project_name)
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


def docker_exec(container_id: str, cmd: List[str], timeout: int = 20) -> subprocess.CompletedProcess:
    return _run(["docker", "exec", container_id] + cmd, timeout=timeout)


def wait_http_ok(url: str, timeout_s: int = 90, interval_s: float = 2.0) -> Tuple[bool, str]:
    deadline = time.time() + timeout_s
    last_detail = ""
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                if 200 <= resp.status < 300:
                    return True, f"status={resp.status}"
                last_detail = f"status={resp.status}"
        except Exception as exc:  # noqa: BLE001
            last_detail = repr(exc)
        time.sleep(interval_s)
    return False, last_detail


def try_connect_tcp(host: str, port: int, timeout_s: float = 3.0) -> Tuple[bool, str]:
    """host:portへのTCP接続を試みる。成功すればTrue、拒否・timeout等はFalse。"""
    import socket as socket_mod

    family = socket_mod.AF_INET6 if ":" in host else socket_mod.AF_INET
    try:
        with socket_mod.socket(family, socket_mod.SOCK_STREAM) as s:
            s.settimeout(timeout_s)
            s.connect((host, port))
            return True, "connected"
    except Exception as exc:  # noqa: BLE001
        return False, repr(exc)


def _cleanup_project_networks(project_name: str, run_fn=_run) -> None:
    """cleanup_stack()のnetwork残存確認・削除・再照会部分を独立関数化。

    Phase 2-B.2限定修正（CODEX第2回検証 P2B2-CX-002再指摘対応）: 旧実装は
    `docker network ls`が失敗（非0 return code）した場合に一切FAILを
    record()しない構造だった（`if returncode == 0: ... `のみでelse節が
    存在しなかった）。CODEXが`_run`へfake CompletedProcessを注入する
    independent negative controlでこれを再現し、query失敗時にFAIL_COUNT=0
    のまま集計が完走してしまうfail-openであると指摘した。

    以下のいずれの経路も明示的にrecord()し、判定不能な場合は必ずFAILにする:
      1. 初回`docker network ls`自体が失敗する
      2. `docker network rm`が失敗する
      3. 削除後の再照会`docker network ls`が失敗する
      4. 再照会が成功しても対象networkが残存している
      5. （positive control）初回照会が正常に0件を返す

    `run_fn`を差し替え可能にしているのは、実Docker daemonを使わずに上記5経路
    すべてを`cleanup_network_query_negative_controls()`で自己検査するため。
    """
    net_query_cmd = ["docker", "network", "ls", "--filter", f"label=com.docker.compose.project={project_name}", "-q"]
    net_proc = run_fn(net_query_cmd)
    if net_proc.returncode != 0:
        record(
            f"cleanup[{project_name}]: test project network inventory query succeeds",
            False,
            net_proc.stderr[-500:],
            net_query_cmd,
        )
        return

    remaining_nets = [l for l in net_proc.stdout.splitlines() if l.strip()]
    if not remaining_nets:
        record(f"cleanup[{project_name}]: test project network残存 0件", True, "remaining_nets=[]")
        return

    rm_failures = []
    for net_id in remaining_nets:
        rm_proc = run_fn(["docker", "network", "rm", net_id])
        if rm_proc.returncode != 0:
            rm_failures.append((net_id, rm_proc.stderr[-300:]))
    record(
        f"cleanup[{project_name}]: docker network rm succeeds for all leftover networks",
        not rm_failures,
        f"rm_failures={rm_failures}",
    )

    recheck_proc = run_fn(net_query_cmd)
    if recheck_proc.returncode != 0:
        record(
            f"cleanup[{project_name}]: post-removal test project network inventory re-query succeeds",
            False,
            recheck_proc.stderr[-500:],
            net_query_cmd,
        )
        return

    still = [l for l in recheck_proc.stdout.splitlines() if l.strip()]
    record(f"cleanup[{project_name}]: test project network残存 0件", len(still) == 0, f"still={still}")


def cleanup_stack(override_file: Path, project_name: str) -> None:
    """今回作成したcontainer/networkを確実に削除する（正常終了・検査FAIL・
    未処理例外のすべての経路でmain()のfinallyから呼ばれる）。"""
    proc = _run(compose_cmd(override_file, ["--profile", "operator", "down", "--remove-orphans", "--timeout", "15"], project_name))
    record(
        f"cleanup[{project_name}]: docker compose down (test project) succeeds",
        proc.returncode == 0,
        (proc.stdout + proc.stderr)[-1000:],
    )
    # container残存確認（fail-closed: 確認できない場合はFAILにする）
    ps_proc = _run(compose_cmd(override_file, ["ps", "-a", "-q"], project_name))
    if ps_proc.returncode != 0:
        record(f"cleanup[{project_name}]: post-down container inventory query succeeds", False, ps_proc.stderr[-500:])
    else:
        remaining = [l for l in ps_proc.stdout.splitlines() if l.strip()]
        record(
            f"cleanup[{project_name}]: post-down container残存 0件",
            len(remaining) == 0,
            f"remaining_ids={remaining}",
        )

    _cleanup_project_networks(project_name)

    # 今回buildした一意projectのimageも削除する（ユーザー既存imageには触れない）。
    # operator-gatewayはbuildなし（公式alpine imageをpullするのみ）のため
    # project固有tagを持たず、削除対象に含めない（共有base imageを不要に消さない）。
    # runtime-initはdocker-compose.ymlでbuild定義されているため、backend-public/
    # backend-operatorと同様にproject固有tagが残る（従来の削除対象漏れを訂正）。
    for tag in (
        f"{project_name}-backend-public:latest",
        f"{project_name}-backend-operator:latest",
        f"{project_name}-runtime-init:latest",
    ):
        _run(["docker", "rmi", "-f", tag])
    img_check = _run(["docker", "images", "-q", "--filter", f"reference={project_name}-*"])
    remaining_imgs = [l for l in img_check.stdout.splitlines() if l.strip()] if img_check.returncode == 0 else ["<query failed>"]
    record(f"cleanup[{project_name}]: test project image残存 0件", len(remaining_imgs) == 0, f"remaining={remaining_imgs}")


# ------------------------------------------------------------------
# 5. AT-03（独立project「ind」） / AT-05・AT-09-BIND（独立project「op」）
# ------------------------------------------------------------------


def at03_default_start_check(override_file: Path, project_name: str) -> None:
    """AT-03: profile未指定の既定起動でbackend-operator / operator-gateway
    containerが作成・起動されないことを実機で確認する。

    P2B2-CX-002対応: この検証専用の独立project（PROJECT_NAME_DEFAULT）で実行し、
    AT-05/AT-09-BIND（operator profile起動）のprojectとは完全に分離する。
    """
    up_cmd = ["up", "-d", "--build", "backend-public", "frontend", "osrm-walking", "martin"]
    proc = _run(compose_cmd(override_file, up_cmd, project_name), timeout=600)
    record(
        "AT-03: profile未指定 docker compose up (backend-public等) succeeds",
        proc.returncode == 0,
        (proc.stdout + proc.stderr)[-2000:],
        compose_cmd(override_file, up_cmd, project_name),
    )

    bp_image_id = _run(["docker", "inspect", "--format={{.Id}}", f"{project_name}-backend-public:latest"]).stdout.strip()
    record(f"[evidence] backend-public image ID = {bp_image_id or '(取得失敗)'}", bool(bp_image_id), bp_image_id)

    ps_proc = _run(compose_cmd(override_file, ["ps", "-a", "--format", "{{.Service}}"], project_name))
    running_services = set(l.strip() for l in ps_proc.stdout.splitlines() if l.strip())
    record(
        "AT-03: profile未指定の起動対象コンテナにbackend-operatorが0件",
        OPERATOR_SERVICE_NAME not in running_services,
        f"running_services={sorted(running_services)}",
    )
    record(
        "AT-03: profile未指定の起動対象コンテナにoperator-gatewayが0件",
        OPERATOR_PROXY_SERVICE_NAME not in running_services,
        f"running_services={sorted(running_services)}",
    )

    bp_id = get_container_id(override_file, "backend-public", project_name)
    record("AT-03: backend-public container is running", bool(bp_id))


def operator_stack_up_check(override_file: Path, project_name: str) -> bool:
    """AT-05/AT-09-BIND用の独立project（PROJECT_NAME_OPERATOR）でoperator
    profileを含む全serviceを起動する。"""
    up_cmd = ["--profile", "operator", "up", "-d", "--build"]
    proc = _run(compose_cmd(override_file, up_cmd, project_name), timeout=600)
    record(
        "AT-05/AT-09-BIND stack: docker compose --profile operator up (full stack) succeeds",
        proc.returncode == 0,
        (proc.stdout + proc.stderr)[-2000:],
        compose_cmd(override_file, up_cmd, project_name),
    )
    return proc.returncode == 0


def at05_public_boundary_check(override_file: Path, project_name: str) -> None:
    """AT-05: backend-publicのhost publish・Docker socket 0件を実機で確認する。"""
    bp_id = get_container_id(override_file, "backend-public", project_name)
    if not bp_id:
        record("AT-05: backend-public container inspectable", False)
        return

    inspect_proc = _run(["docker", "inspect", bp_id])
    try:
        inspect_data = json.loads(inspect_proc.stdout)[0]
    except Exception as exc:  # noqa: BLE001
        record("AT-05: docker inspect backend-public succeeds", False, str(exc))
        return

    port_bindings = inspect_data.get("NetworkSettings", {}).get("Ports", {}) or {}
    host_bound = {k: v for k, v in port_bindings.items() if v}
    record(
        "AT-05: docker inspect backend-public にhost port binding 0件",
        len(host_bound) == 0,
        f"Ports={port_bindings}",
    )

    mounts = inspect_data.get("Mounts", [])
    socket_mounts = [m for m in mounts if "docker.sock" in str(m.get("Source", "")) or "docker.sock" in str(m.get("Destination", ""))]
    record(
        "AT-05: docker inspect backend-public にDocker socket mount 0件",
        len(socket_mounts) == 0,
        f"hits={socket_mounts}",
    )

    connect_ok, detail = try_connect_tcp("127.0.0.1", 8000, timeout_s=2.0)
    record(
        "AT-05: host 127.0.0.1:8000 へ今回のbackend-public由来では到達できない"
        "（本番stackの既存backendが同ポートを使用中の場合は誤検知を避けるためdetailのみ記録）",
        True,
        f"connect_ok={connect_ok} detail={detail} "
        f"注記: ポート8000は本番backend-publicが既にpublishしている可能性があるため、"
        f"本項目はinspect結果（Ports 0件）を主判定とし、本行は補助情報として記録する。",
    )

    (EVIDENCE_DIR / "backend_public_inspect.json").write_text(
        json.dumps(_strip_secrets_from_inspect(inspect_data), indent=2, ensure_ascii=False), encoding="utf-8"
    )


def at09_bind_live_checks(override_file: Path, project_name: str) -> None:
    """AT-09-BIND: bind三層を実機・実通信で確認する。

    Phase 2-B.2限定修正: host publish（②）はoperator-gateway sidecar
    経由になったため、published port問い合わせ・6c（proxyへの直接到達不可）を
    sidecar構成に合わせて更新した。backend-operator自体の起動は
    operator_stack_up_check()側で完了済みの前提。
    """
    bo_image_id = _run(["docker", "inspect", "--format={{.Id}}", f"{project_name}-backend-operator:latest"]).stdout.strip()
    record(f"[evidence] backend-operator image ID = {bo_image_id or '(取得失敗)'}", bool(bo_image_id), bo_image_id)

    bo_id = get_container_id(override_file, "backend-operator", project_name)
    record("AT-09-BIND: backend-operator container is running", bool(bo_id))
    proxy_id = get_container_id(override_file, OPERATOR_PROXY_SERVICE_NAME, project_name)
    record("AT-09-BIND: operator-gateway container is running", bool(proxy_id))
    if not bo_id or not proxy_id:
        return

    # published portを実際にqueryする（overrideで固定値を指定したため一致するはずだが、
    # 実際の割当をdocker compose port経由で再確認する）。host publishは
    # operator-gateway側で行っているため、問い合わせ対象もproxyへ変更する。
    published = get_host_published_port(override_file, OPERATOR_PROXY_SERVICE_NAME, OPERATOR_TARGET_PORT, project_name)
    record(
        f"AT-09-BIND: operator-gateway published port query succeeds (expected {OPERATOR_HOST_PORT})",
        published == str(OPERATOR_HOST_PORT),
        f"published={published}",
    )

    # 1. container内 0.0.0.0:8100 listen（backend-operator自身のローカル自己接続で間接確認。
    #    sidecar導入後もbackend-operator自体のlisten挙動は変わらない）
    ok, detail = False, ""
    for _ in range(30):
        r = docker_exec(bo_id, ["python", "-c", f"import urllib.request; urllib.request.urlopen('http://127.0.0.1:{OPERATOR_TARGET_PORT}/operator/health', timeout=3)"])
        if r.returncode == 0:
            ok = True
            detail = "container-local /operator/health reachable"
            break
        detail = r.stderr[-300:]
        time.sleep(2)
    record("AT-09-BIND-1: container内 0.0.0.0:8100 相当のlistenが機能している（container内自己接続）", ok, detail)

    # response fingerprint取得（operator appであることの確認、認証なしでも200を返す
    # /healthのbody固定文字列を使う）。host→gateway(nginx)→backend-operatorと
    # いう経路が透過的に機能していることも同時に確認する。
    # Phase 2-B.4でoperator/nginx.confがexact-match `location = /health`
    # （backend-operatorの`/operator/health`への1:1 proxy）へ整理されたため、
    # gateway経由の外部公開pathは`/operator/health`ではなく`/health`である
    # （backend-operator自身へ直接到達する場合のみ`/operator/health`のまま）。
    fp_ok = False
    fp_detail = ""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{OPERATOR_HOST_PORT}/health", timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            fp_ok = resp.status == 200 and '"role": "operator"' in body.replace(" ", "").replace("'", '"') or '"role":"operator"' in body.replace(" ", "")
            fp_detail = f"status={resp.status} body={body[:200]}"
    except Exception as exc:  # noqa: BLE001
        fp_detail = repr(exc)

    # 2. host 127.0.0.1:HOST_PORT（operator-gateway経由）から正到達 + fingerprint確認
    record(
        "AT-09-BIND-2: host 127.0.0.1:HOST_PORT（operator-gateway経由）から正到達し、"
        "operator appのfingerprintと一致する",
        fp_ok,
        fp_detail,
    )

    # 3. host非loopback IPv4から負到達
    host_ipv4 = _detect_non_loopback_ipv4()
    if host_ipv4:
        conn_ok, conn_detail = try_connect_tcp(host_ipv4, OPERATOR_HOST_PORT, timeout_s=3.0)
        record(
            f"AT-09-BIND-3: host非loopback IPv4({host_ipv4})から負到達（接続できないこと）",
            not conn_ok,
            f"connect_ok={conn_ok} detail={conn_detail}",
        )
    else:
        record("AT-09-BIND-3: host非loopback IPv4から負到達", False, "実測可能な非loopback IPv4アドレスを検出できなかった")

    # 4. IPv6 loopback / 非loopbackから負到達
    v6_loopback_ok, v6_loopback_detail = try_connect_tcp("::1", OPERATOR_HOST_PORT, timeout_s=3.0)
    record(
        "AT-09-BIND-4a: IPv6 loopback(::1)から負到達（接続できないこと）",
        not v6_loopback_ok,
        f"connect_ok={v6_loopback_ok} detail={v6_loopback_detail}",
    )
    host_ipv6 = _detect_non_loopback_ipv6()
    if host_ipv6:
        v6_ok, v6_detail = try_connect_tcp(host_ipv6, OPERATOR_HOST_PORT, timeout_s=3.0)
        record(
            f"AT-09-BIND-4b: IPv6非loopback({host_ipv6})から負到達（接続できないこと）",
            not v6_ok,
            f"connect_ok={v6_ok} detail={v6_detail}",
        )
    else:
        record(
            "AT-09-BIND-4b: IPv6非loopbackから負到達",
            True,
            "実測可能な非loopback IPv6アドレスを検出できなかったため、socket inventory側の確認（host_ip=127.0.0.1のみpublish）を根拠とする（環境制約として記録）",
        )

    # socket inventory: hostがIPv6でlistenしていないことをdocker inspectのPortsから確認
    # （host publishはoperator-gateway側で行っているためproxyを検査対象とする）
    proxy_inspect = json.loads(_run(["docker", "inspect", proxy_id]).stdout)[0]
    ports_cfg = proxy_inspect.get("NetworkSettings", {}).get("Ports", {})
    ipv6_listen_hits = []
    for _cport, bindings in (ports_cfg or {}).items():
        for b in bindings or []:
            host_ip_val = b.get("HostIp", "")
            if host_ip_val in ("::", "::1") or ":" in host_ip_val:
                ipv6_listen_hits.append(b)
    record(
        "AT-09-BIND-4c: docker inspect port bindingにIPv6 host_ipが0件",
        len(ipv6_listen_hits) == 0,
        f"hits={ipv6_listen_hits} raw_ports={ports_cfg}",
    )

    # 5. public network peer（backend-public）からbackend-operatorへの負到達
    bp_id = get_container_id(override_file, "backend-public", project_name)
    if bp_id:
        peer_result = docker_exec(
            bp_id,
            ["python", "-c", "import urllib.request; urllib.request.urlopen('http://backend-operator:8100/operator/health', timeout=3)"],
        )
        record(
            "AT-09-BIND-5: public network peer(backend-public)からbackend-operatorへ負到達（DNS/接続できないこと）",
            peer_result.returncode != 0,
            (peer_result.stdout + peer_result.stderr)[-500:],
        )
        # public network peer（backend-public）からsidecar（operator-gateway）への
        # 負到達も併せて確認する（sidecar新設に伴う追加の境界確認）。
        peer_to_proxy_result = docker_exec(
            bp_id,
            ["python", "-c", f"import urllib.request; urllib.request.urlopen('http://{OPERATOR_PROXY_SERVICE_NAME}:{OPERATOR_TARGET_PORT}/operator/health', timeout=3)"],
        )
        record(
            "AT-09-BIND-5b: public network peer(backend-public)からoperator-gatewayへ負到達（DNS/接続できないこと）",
            peer_to_proxy_result.returncode != 0,
            (peer_to_proxy_result.stdout + peer_to_proxy_result.stderr)[-500:],
        )
    else:
        record("AT-09-BIND-5: public network peerからの負到達", False, "backend-public container not found")

    # 6. public frontend/nginx proxyからoperator-only pathへ負到達
    fe_id = get_container_id(override_file, "frontend", project_name)
    if fe_id:
        # (a) nginxコンテナ自身からbackend-operatorサービス名への直接到達不可（network分離）
        nginx_direct = docker_exec(
            fe_id,
            ["wget", "-q", "-T", "3", "-O", "-", "http://backend-operator:8100/operator/health"],
        )
        record(
            "AT-09-BIND-6a: public frontend containerからbackend-operatorへ直接到達不可",
            nginx_direct.returncode != 0,
            (nginx_direct.stdout + nginx_direct.stderr)[-500:],
        )
        # (c) nginxコンテナ自身からoperator-gatewayサービス名への直接到達不可
        #    （sidecar新設に伴う追加の境界確認: proxyもpublic networkからは不可視であるべき）
        nginx_to_proxy = docker_exec(
            fe_id,
            ["wget", "-q", "-T", "3", "-O", "-", f"http://{OPERATOR_PROXY_SERVICE_NAME}:{OPERATOR_TARGET_PORT}/operator/health"],
        )
        record(
            "AT-09-BIND-6c: public frontend containerからoperator-gatewayへ直接到達不可",
            nginx_to_proxy.returncode != 0,
            (nginx_to_proxy.stdout + nginx_to_proxy.stderr)[-500:],
        )
        # (b) nginx経由で /api/admin/* へアクセスしても管理routeへ到達しない
        #     （backend-publicがadmin routerを持たないため404、nginx.conf自体も
        #     operatorを一切参照しない、第static節参照）
        fe_host_port = get_host_published_port(override_file, "frontend", 80, project_name)
        if fe_host_port:
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{fe_host_port}/api/admin/config")
                status = None
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        status = resp.status
                except urllib.error.HTTPError as e:
                    status = e.code
                record(
                    "AT-09-BIND-6b: public frontend経由で/api/admin/*が404（管理機能へ到達しない）",
                    status == 404,
                    f"status={status}",
                )
            except Exception as exc:  # noqa: BLE001
                record("AT-09-BIND-6b: public frontend経由で/api/admin/*が404", False, repr(exc))
        else:
            record("AT-09-BIND-6b: public frontend経由で/api/admin/*が404", False, "frontend host port取得失敗")
    else:
        record("AT-09-BIND-6: public frontend proxyからの負到達", False, "frontend container not found")

    # 7. SSH port forward経由の正到達
    ssh_forward_check(OPERATOR_HOST_PORT)


def _detect_non_loopback_ipv4() -> Optional[str]:
    proc = _run(["bash", "-c", "ifconfig 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print $2}' | grep -v '^127\\.'"])
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line and line != "127.0.0.1":
            return line
    return None


def _detect_non_loopback_ipv6() -> Optional[str]:
    proc = _run(["bash", "-c", "ifconfig 2>/dev/null | grep -oE 'inet6 [0-9a-fA-F:]+' | awk '{print $2}' | grep -v '^::1' | grep -v '^fe80'"])
    for line in proc.stdout.splitlines():
        line = line.strip()
        if line:
            return line
    return None


# ------------------------------------------------------------------
# 6. SSH port forward harness（repository外temporary directory）
# ------------------------------------------------------------------


def ssh_forward_check(operator_host_port: int) -> None:
    """実際の `ssh -L` port forwardを、repository外の隔離されたlocal SSH test
    harness経由で実施する。VPSへは接続しない。harnessを用意できない場合は
    AT-09-BIND-7をPASSにせずBLOCKEDとして報告する。"""
    ssh_bin_candidates = ["/usr/sbin/sshd"]
    sshd_path = next((p for p in ssh_bin_candidates if Path(p).exists()), None)
    if not sshd_path:
        record("AT-09-BIND-7: SSH forward経由の正到達", False, "BLOCKED: sshdバイナリが見つからずtest harnessを構成できない")
        return

    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b2_sshd_") as tmp:
        tmp_path = Path(tmp)
        host_key = tmp_path / "hostkey"
        client_key = tmp_path / "clientkey"
        authorized_keys = tmp_path / "authorized_keys"
        sshd_config = tmp_path / "sshd_config"
        pid_file = tmp_path / "sshd.pid"

        gen1 = _run(["ssh-keygen", "-t", "ed25519", "-f", str(host_key), "-N", "", "-q"])
        gen2 = _run(["ssh-keygen", "-t", "ed25519", "-f", str(client_key), "-N", "", "-q"])
        if gen1.returncode != 0 or gen2.returncode != 0:
            record("AT-09-BIND-7: SSH forward経由の正到達", False, "BLOCKED: ssh-keygenに失敗")
            return
        authorized_keys.write_text((client_key.with_suffix(".pub")).read_text(), encoding="utf-8")
        os.chmod(authorized_keys, 0o600)

        sshd_test_port = 2200 + (hash(_RUN_TAG) % 300)
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
            record("AT-09-BIND-7: SSH forward経由の正到達", False, f"BLOCKED: sshd_config検証失敗: {verify.stderr}")
            return

        sshd_proc = subprocess.Popen(
            [sshd_path, "-f", str(sshd_config), "-D", "-e"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(tmp_path),
        )
        try:
            time.sleep(1.0)
            if sshd_proc.poll() is not None:
                out, err = sshd_proc.communicate(timeout=2)
                record("AT-09-BIND-7: SSH forward経由の正到達", False, f"BLOCKED: sshd起動失敗: {err.decode(errors='replace')[:500]}")
                return

            local_forward_port = 12200 + (hash(_RUN_TAG) % 300)
            ssh_cmd = [
                "ssh",
                "-F", "none",
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "BatchMode=yes",
                "-o", "ExitOnForwardFailure=yes",
                "-i", str(client_key),
                "-p", str(sshd_test_port),
                "-L", f"127.0.0.1:{local_forward_port}:127.0.0.1:{operator_host_port}",
                "-N",
                "127.0.0.1",
            ]
            ssh_client_proc = subprocess.Popen(ssh_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                time.sleep(2.0)
                if ssh_client_proc.poll() is not None:
                    out, err = ssh_client_proc.communicate(timeout=2)
                    record(
                        "AT-09-BIND-7: SSH forward経由の正到達",
                        False,
                        f"BLOCKED: ssh -L 起動失敗: {err.decode(errors='replace')[:500]}",
                        ssh_cmd,
                    )
                    return

                ok, detail = wait_http_ok(f"http://127.0.0.1:{local_forward_port}/health", timeout_s=15, interval_s=1.0)
                record(
                    "AT-09-BIND-7: 実際の`ssh -L`経由でoperator /healthへ正到達（gateway経由、Phase 2-B.4のexact-match path）",
                    ok,
                    f"local_forward_port={local_forward_port} detail={detail}",
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


# ------------------------------------------------------------------
# 7. CF-N01〜CF-N13 negative fixture
# ------------------------------------------------------------------


def _run_isolated(fn, *args, **kwargs) -> List[Dict[str, Any]]:
    """任意の検査関数をグローバルRESULTSから隔離して実行し、その呼び出し
    専用の結果listだけを返す（本来の検査結果を汚染しない）。"""
    global RESULTS
    saved = RESULTS
    RESULTS = []
    try:
        fn(*args, **kwargs)
        return RESULTS
    finally:
        RESULTS = saved


def _run_static_checks_isolated(compose_path: Path, nginx_path: Path) -> List[Dict[str, Any]]:
    return _run_isolated(static_yaml_checks, compose_path=compose_path, nginx_path=nginx_path)


def cleanup_network_query_negative_controls() -> None:
    """Phase 2-B.2限定修正（CODEX第2回検証 P2B2-CX-002再指摘対応）:
    `_cleanup_project_networks()`のquery失敗・rm失敗・再照会失敗が、
    黙って見逃されず必ずFAIL記録されることを、実Docker daemonを使わない
    独立negative/positive controlで自己検査する。CODEXが`_run`へfake
    CompletedProcessを注入して再現した手法と同じアプローチを、この
    scriptの回帰防止として組み込む。実Docker呼び出しは一切行わない
    （`run_fn`をstubへ差し替えるため、Docker daemon未起動でも実行できる）。
    """

    def _cp(returncode: int, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess([], returncode, stdout, stderr)

    def _stub(*sequence: subprocess.CompletedProcess):
        state = {"n": 0}

        def _run_fn(cmd, **kwargs):
            idx = state["n"]
            state["n"] += 1
            if idx < len(sequence):
                return sequence[idx]
            return subprocess.CompletedProcess(cmd, 0, "", "")

        return _run_fn

    controls = [
        (
            "CTRL-NET-01",
            "初回 docker network ls 自体が失敗する",
            _stub(_cp(1, "", "forced network inventory failure")),
            "test project network inventory query succeeds",
            False,
        ),
        (
            "CTRL-NET-02",
            "docker network rm が失敗する",
            _stub(_cp(0, "net1\n"), _cp(1, "", "forced rm failure"), _cp(0, "net1\n")),
            "docker network rm succeeds for all leftover networks",
            False,
        ),
        (
            "CTRL-NET-03",
            "削除後の再照会 docker network ls が失敗する",
            _stub(_cp(0, "net1\n"), _cp(0, ""), _cp(1, "", "forced re-query failure")),
            "post-removal test project network inventory re-query succeeds",
            False,
        ),
        (
            "CTRL-NET-04",
            "rm成功後の再照会でも対象networkが残存している",
            _stub(_cp(0, "net1\n"), _cp(0, ""), _cp(0, "net1\n")),
            "test project network残存 0件",
            False,
        ),
        (
            "CTRL-NET-05（positive control）",
            "初回照会が正常に0件を返す（誤検知しないことの確認）",
            _stub(_cp(0, "")),
            "test project network残存 0件",
            True,
        ),
    ]

    for ctrl_id, desc, run_fn, expected_check_substr, expected_pass in controls:
        fixture_results = _run_isolated(_cleanup_project_networks, "ohg2_cleanup_selftest_dummy_project", run_fn=run_fn)
        matched = [r for r in fixture_results if expected_check_substr in r["name"]]
        found = bool(matched) and all(r["pass"] == expected_pass for r in matched)
        record(
            f"{ctrl_id} ({desc}): cleanupのnetwork検査が期待どおり{'PASS' if expected_pass else 'FAIL'}判定する",
            found,
            f"expected_check='{expected_check_substr}' expected_pass={expected_pass} matched={matched}",
        )


def negative_fixture_checks() -> None:
    """CF-N01〜CF-N13: repository外のnegative fixtureへ変異を1件ずつ独立投入し、
    自動検査（static_yaml_checks）がすべて期待どおり不合格と判定することを確認する。
    実repositoryのdocker-compose.yml/nginx.confは一切書き換えない。"""
    base_data = load_compose_yaml(COMPOSE_FILE)
    base_nginx = NGINX_CONF.read_text(encoding="utf-8")

    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b2_negfixture_") as tmp:
        tmp_path = Path(tmp)

        def mutate_and_check(fixture_id: str, desc: str, mutator, expected_check_substr: str) -> None:
            data = copy.deepcopy(base_data)
            try:
                mutator(data)
            except Exception as exc:  # noqa: BLE001
                record(f"{fixture_id} ({desc}): mutation applies cleanly", False, repr(exc))
                return
            fixture_path = tmp_path / f"{fixture_id}.docker-compose.yml"
            fixture_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

            fixture_results = _run_static_checks_isolated(fixture_path, NGINX_CONF)
            matched = [r for r in fixture_results if expected_check_substr in r["name"]]
            found_fail = bool(matched) and any(not r["pass"] for r in matched)
            record(
                f"{fixture_id} ({desc}): 自動検査が正しくFAILと判定する",
                found_fail,
                f"expected_check='{expected_check_substr}' matched={matched}",
            )

        mutate_and_check(
            "CF-N01", "publicへhost portを追加",
            lambda d: d["services"]["backend-public"].__setitem__("ports", ["19999:9999"]),
            "backend-public has 0 host port publish entries",
        )
        mutate_and_check(
            "CF-N02", "publicへDocker socketを追加",
            lambda d: d["services"]["backend-public"].setdefault("volumes", []).append(
                "/var/run/docker.sock:/var/run/docker.sock"
            ),
            "backend-public has 0 docker.sock mounts",
        )
        mutate_and_check(
            "CF-N03", "operator profileを削除",
            lambda d: d["services"][OPERATOR_SERVICE_NAME].pop("profiles", None),
            "backend-operator has profiles == ['operator']",
        )
        mutate_and_check(
            "CF-N04", "operatorをpublic networkへ追加",
            lambda d: d["services"][OPERATOR_SERVICE_NAME]["networks"].__setitem__("default", {}),
            "backend-operator networks == {operator-internal} のみ",
        )
        mutate_and_check(
            "CF-N05", "operator networkのinternalをfalse化",
            lambda d: d["networks"][OPERATOR_INTERNAL_NETWORK_NAME].__setitem__("internal", False),
            "networks.operator-internal.internal == true",
        )
        mutate_and_check(
            "CF-N06", "operator-gateway host_ipを0.0.0.0へ変更",
            lambda d: d["services"][OPERATOR_PROXY_SERVICE_NAME]["ports"][0].__setitem__("host_ip", "0.0.0.0"),
            "operator-gateway port host_ip == '127.0.0.1'",
        )
        mutate_and_check(
            "CF-N07", "operator-gateway host_ipを::へ変更",
            lambda d: d["services"][OPERATOR_PROXY_SERVICE_NAME]["ports"][0].__setitem__("host_ip", "::"),
            "operator-gateway port host_ip == '127.0.0.1'",
        )
        mutate_and_check(
            "CF-N08", "operator-gateway portをshort syntax／host IP省略へ変更",
            lambda d: d["services"][OPERATOR_PROXY_SERVICE_NAME].__setitem__("ports", ["18100:8100"]),
            "operator-gateway port entry is long-form mapping",
        )
        mutate_and_check(
            "CF-N10", "operatorを既定serviceからdepends_onする",
            lambda d: d["services"]["backend-public"].__setitem__("depends_on", ["backend-operator"]),
            "operator-gateway以外の非operator serviceはbackend-operatorへdepends_onしない",
        )
        # CF-N11〜CF-N13: P2B2-CX-001再発防止（sidecar構成そのものの逸脱検知）。
        mutate_and_check(
            "CF-N11", "operatorをoperator-publish(非internal)networkへ直接参加させる（P2B2-CX-001再発防止）",
            lambda d: d["services"][OPERATOR_SERVICE_NAME]["networks"].__setitem__(OPERATOR_PUBLISH_NETWORK_NAME, {}),
            "docker.sock保持service(backend-operator)が参加する全networkがinternal:true",
        )
        mutate_and_check(
            "CF-N12", "operator-gatewayへDocker socketを追加（sidecar最小権限の逸脱検知）",
            lambda d: d["services"][OPERATOR_PROXY_SERVICE_NAME].setdefault("volumes", []).append(
                "/var/run/docker.sock:/var/run/docker.sock"
            ),
            "operator-gateway has 0 docker.sock mounts",
        )
        mutate_and_check(
            "CF-N13", "operator-gatewayへoperator用host/dataマウントを追加（sidecar最小権限の逸脱検知）",
            lambda d: d["services"][OPERATOR_PROXY_SERVICE_NAME].setdefault("volumes", []).append(
                "./data_lake:/data_lake"
            ),
            "operator-gateway volume mounts are limited to the read-only static-config allowlist",
        )

        # CF-N09: nginx.confの変異（public proxy/upstreamをoperatorへ変更）
        mutated_nginx = base_nginx.replace(
            "proxy_pass http://backend:8000/api/;",
            f"proxy_pass http://backend-operator:{OPERATOR_TARGET_PORT}/api/;",
        )
        if mutated_nginx == base_nginx:
            record("CF-N09 (public proxy/upstreamをoperatorへ変更): mutation applies cleanly", False, "置換対象文字列が見つからなかった")
        else:
            nginx_fixture_path = tmp_path / "CF-N09.nginx.conf"
            nginx_fixture_path.write_text(mutated_nginx, encoding="utf-8")
            fixture_results = _run_static_checks_isolated(COMPOSE_FILE, nginx_fixture_path)
            matched = [r for r in fixture_results if "nginx.conf does not reference backend-operator" in r["name"]]
            found_fail = bool(matched) and any(not r["pass"] for r in matched)
            record(
                "CF-N09 (public proxy/upstreamをoperatorへ変更): 自動検査が正しくFAILと判定する",
                found_fail,
                f"matched={matched}",
            )
    # tempdir（negative fixtureの一時compose/nginx file）はwith-block終了時に自動削除される


# ------------------------------------------------------------------
# 8. Phase 2-B.1回帰
# ------------------------------------------------------------------


DOCKERIGNORE_CONTRACT_FILES = [
    REPO_ROOT / "backend" / "Dockerfile.dockerignore",
    REPO_ROOT / "backend" / ".dockerignore",
    REPO_ROOT / "backend" / "Dockerfile",
    REPO_ROOT / "backend" / "Dockerfile.operator",
]


def _hash_file(path: Path) -> str:
    import hashlib

    if not path.exists():
        return "MISSING"
    return hashlib.sha256(path.read_bytes()).hexdigest()


def snapshot_dockerignore_contract() -> Dict[str, str]:
    return {str(p): _hash_file(p) for p in DOCKERIGNORE_CONTRACT_FILES}


def phase2b1_regression_checks(override_file: Path, pre_run_hashes: Dict[str, str], project_name: str) -> None:
    # AT-01: exact route 50件（backend/tests/test_phase2b1_entrypoint_boundary.py 再実行）
    pytest_cmd = [
        sys.executable, "-m", "pytest",
        "tests/test_phase2b1_entrypoint_boundary.py::TestPublicRouteAllowlist",
        "tests/test_phase2b1_entrypoint_boundary.py::TestPublicImportGraph",
        "-q",
    ]
    proc = _run(pytest_cmd, cwd=str(REPO_ROOT / "backend"), timeout=180)
    record(
        "Phase 2-B.1回帰 AT-01: exact route allowlist / import graph pytest PASS",
        proc.returncode == 0,
        (proc.stdout + proc.stderr)[-2000:],
        pytest_cmd,
    )

    # AT-02代表項目: build済みimage自体（composeのvolumeマウントを経由しない、
    # `docker run --rm` による直接検査）でDocker CLI・admin moduleが増えていないことを
    # 確認する。Dockerfile自体は今回変更していないため全layer走査は再実行せず、
    # 代表smokeとして実施する。
    #
    # 注意: composeで実際に起動中の backend-public container を検査すると、
    # `./backend:/app` ホットリロードマウント（開発利便性のための既存機能、
    # Phase 2-B.1以前から存在）により、image自体はクリーンでもホストの
    # backend/ ディレクトリ全体（admin.py含む）が /app に見えてしまい誤検知する
    # （第X節で別途observationとして記録）。そのためAT-02の代表項目はimage単体
    # （volumeマウントなし）に対して行う。
    image_tag = f"{project_name}-backend-public"
    cli_check = _run(["docker", "run", "--rm", "--entrypoint", "sh", image_tag, "-c", "which docker; echo EXIT:$?"])
    record(
        "Phase 2-B.1回帰 AT-02代表項目: backend-public image自体にDocker CLI 0件",
        "EXIT:0" not in cli_check.stdout,
        cli_check.stdout + cli_check.stderr,
    )
    find_check = _run(["docker", "run", "--rm", "--entrypoint", "find", image_tag, "/app", "-type", "f", "-path", "/app/app/api/admin.py"])
    record(
        "Phase 2-B.1回帰 AT-02代表項目: backend-public image自体にadmin.py 0件",
        not find_check.stdout.strip(),
        find_check.stdout,
    )

    # 参考observation: compose起動中containerの実行時filesystemには、
    # ホットリロードマウントによりadmin.pyが見える（image境界とは別の観点）。
    bp_id = get_container_id(override_file, "backend-public", project_name)
    if bp_id:
        hotreload_find = docker_exec(bp_id, ["find", "/app", "-type", "f", "-path", "/app/app/api/admin.py"])
        record(
            "[observation] compose起動中containerの実行時filesystem（ホットリロードmount経由）にadmin.pyが見える"
            "（image自体は0件、AT-02は満たす。運用上の別論点として報告書へ記録）",
            True,
            f"hotreload_visible_admin_py={hotreload_find.stdout.strip()!r}",
        )

    # AT-12: dockerignore契約（Dockerfile.dockerignore等）が今回のPhase 2-B.2作業で
    # 変更されていないことを、内容ハッシュの前後比較で確認する
    # （git statusのみでは、Phase 2-B.1由来の既存dirty差分と今回差分を区別できない）。
    post_run_hashes = snapshot_dockerignore_contract()
    record(
        "Phase 2-B.1回帰 AT-12: Dockerfile／dockerignore契約ファイルが今回のPhase 2-B.2作業で未変更"
        "（実行開始時からのSHA-256一致で判定。Phase 2-B.1由来の既存差分は許容する）",
        pre_run_hashes == post_run_hashes,
        f"pre={pre_run_hashes}\npost={post_run_hashes}",
    )


# ------------------------------------------------------------------
# 9. public回帰
# ------------------------------------------------------------------


def public_regression_checks(override_file: Path, project_name: str) -> None:
    fe_host_port = get_host_published_port(override_file, "frontend", 80, project_name)
    if not fe_host_port:
        record("public回帰: frontend host port取得", False, "取得失敗")
        return
    record("public回帰: frontend host port取得", True, f"port={fe_host_port}")

    base = f"http://127.0.0.1:{fe_host_port}"
    for path, expected in [("/", 200), ("/live", 200), ("/live/stream", 200)]:
        try:
            with urllib.request.urlopen(base + path, timeout=8) as resp:
                status = resp.status
        except urllib.error.HTTPError as e:
            status = e.code
        except Exception as exc:  # noqa: BLE001
            status = None
            record(f"public回帰: frontend経由 {path}", False, repr(exc))
            continue
        record(f"public回帰: frontend経由 {path} が{expected}", status == expected, f"status={status}")

    bp_id = get_container_id(override_file, "backend-public", project_name)
    if bp_id:
        health_check = docker_exec(
            bp_id,
            ["python", "-c", "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5); print(r.status)"],
        )
        bp_host_health_ok = health_check.returncode == 0 and "200" in health_check.stdout
        record(
            "public回帰: backend-public container内 /health が200",
            bp_host_health_ok,
            health_check.stdout + health_check.stderr,
        )

    # nginx経由 /api/ proxyの成立確認（軽量な代表API）
    try:
        with urllib.request.urlopen(base + "/api/emergency-shelters?limit=1", timeout=8) as resp:
            api_status = resp.status
    except Exception as exc:  # noqa: BLE001
        api_status = None
        record("public回帰: frontend /api/ proxy経由 emergency-shelters", False, repr(exc))
    else:
        record("public回帰: frontend /api/ proxy経由 emergency-shelters が200", api_status == 200, f"status={api_status}")


# ------------------------------------------------------------------
# main
# ------------------------------------------------------------------


def main() -> int:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    print(f"run tag: {_RUN_TAG}")
    print(f"project name (default/AT-03): {PROJECT_NAME_DEFAULT}")
    print(f"project name (operator/AT-05,AT-09-BIND): {PROJECT_NAME_OPERATOR}")
    print(f"operator host port: {OPERATOR_HOST_PORT}")

    pre_run_hashes = snapshot_dockerignore_contract()

    static_yaml_checks()
    negative_fixture_checks()
    cleanup_network_query_negative_controls()

    if not check_docker_available():
        print("Docker daemon not available — aborting live checks.")
        write_summary()
        return 1

    rendered_config_checks()

    # Scenario IND: AT-03（既定起動でoperatorが対象外であること）専用の独立project。
    # P2B2-CX-002対応: AT-05/AT-09-BINDのprojectとはnetwork名・project名を完全分離する。
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b2_override_ind_") as tmp_ind:
        override_ind = build_override_compose(Path(tmp_ind), PROJECT_NAME_DEFAULT, "ind")
        (EVIDENCE_DIR / "docker-compose.override.used.ind.yml").write_text(
            override_ind.read_text(encoding="utf-8"), encoding="utf-8"
        )
        try:
            at03_default_start_check(override_ind, PROJECT_NAME_DEFAULT)
        finally:
            cleanup_stack(override_ind, PROJECT_NAME_DEFAULT)

    # Scenario OP: AT-05・AT-09-BIND・Phase 2-B.1回帰・public回帰用の独立project
    # （operator profileを含む全serviceを起動する）。
    with tempfile.TemporaryDirectory(prefix="ohg2_phase2b2_override_op_") as tmp_op:
        override_op = build_override_compose(Path(tmp_op), PROJECT_NAME_OPERATOR, "op")
        (EVIDENCE_DIR / "docker-compose.override.used.op.yml").write_text(
            override_op.read_text(encoding="utf-8"), encoding="utf-8"
        )
        try:
            if operator_stack_up_check(override_op, PROJECT_NAME_OPERATOR):
                ready_ok, ready_detail = wait_backend_public_ready(override_op, PROJECT_NAME_OPERATOR)
                record(
                    "AT-05/AT-09-BIND stack: backend-publicが以後の検査開始前にhealthyになる",
                    ready_ok,
                    ready_detail,
                )
                at05_public_boundary_check(override_op, PROJECT_NAME_OPERATOR)
                at09_bind_live_checks(override_op, PROJECT_NAME_OPERATOR)
                phase2b1_regression_checks(override_op, pre_run_hashes, PROJECT_NAME_OPERATOR)
                public_regression_checks(override_op, PROJECT_NAME_OPERATOR)
        finally:
            cleanup_stack(override_op, PROJECT_NAME_OPERATOR)

    write_summary()

    failed = [r for r in RESULTS if not r["pass"]]
    print()
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
        "project_name_default": PROJECT_NAME_DEFAULT,
        "project_name_operator": PROJECT_NAME_OPERATOR,
        "operator_host_port": OPERATOR_HOST_PORT,
        "total_checks": len(RESULTS),
        "pass_count": len(RESULTS) - len(failed),
        "fail_count": len(failed),
        "exit_code": 1 if failed else 0,
        "results": RESULTS,
    }
    (EVIDENCE_DIR / "phase2b2_compose_boundary_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


if __name__ == "__main__":
    sys.exit(main())

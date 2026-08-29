#!/usr/bin/env python3
"""
Phase 2-C P2C-CX-004 — public `/simulation` deny漏れの限定回帰test。

CODEX Round 8で `/simulation`（`/api/` プレフィクス外）がnginxの明示deny
locationを持たず、generic `location /` のSPA fallback
（`try_files $uri $uri/ /index.html`）に一致してindex.htmlを200で返す
（RTE-DENY-13-GET/HEAD=200、RTE-DENY-13-OPTIONS=405）ことが指摘された。
`nginx.conf` へ `location = /simulation` と `location ^~ /simulation/` を
追加した修正がこの契約を固定することを、実際のnginx configとfrontend
静的assetを使った隔離Docker containerへの実HTTP requestで検証する。

production containerには一切触れない。専用network・専用container名
（実行ごとに一意なsuffix付き）だけを作成し、実行後に必ず削除する。
mock upstream（backend/osrm-walking/martin）はnginxの起動時DNS解決を
満たすためだけの最小HTTP responderで、実backendのbusiness logicは
検証しない（それは本scriptのscope外）。

終了コード: 0 = 全case PASS, 1 = 1件以上FAIL, 2 = 実行時エラー（Docker利用不可等）。

実行:
    python3 tools/public_release/phase2c_cx004_simulation_deny_check.py
"""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NGINX_CONF = REPO_ROOT / "nginx.conf"
FRONTEND_DIR = REPO_ROOT / "frontend"

# nginx.conf の upstream host:port と一致させる（DNS解決失敗でnginxが
# 起動できないため、mock upstreamのnetwork-aliasを合わせる必要がある）。
MOCK_UPSTREAMS = {
    "backend": 8000,
    "osrm-walking": 5001,
    "martin": 3000,
}

# (method, path, expected_status)
CASES = [
    ("GET", "/simulation", 404),
    ("HEAD", "/simulation", 404),
    ("OPTIONS", "/simulation", 404),
    ("GET", "/simulation/", 404),
    ("GET", "/simulation/example", 404),
    ("GET", "/simulation?x=1", 404),
    ("GET", "/api/simulation", 404),
    ("GET", "/api/simulation/example", 404),
    # 既存の公開SPA route／health既存挙動が壊れていないことの回帰確認
    ("GET", "/", 200),
    ("GET", "/index.html", 200),
]

RUN_TAG = f"ohg2p2ccx004_{int(time.time())}"
NET_NAME = f"{RUN_TAG}_net"
HOST_PORT = 18199


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def check_docker_available() -> bool:
    return _run(["docker", "info"]).returncode == 0


def http_request(method: str, path: str, timeout: float = 5.0) -> int | None:
    url = f"http://127.0.0.1:{HOST_PORT}{path}"
    req = urllib.request.Request(url, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def wait_ready(timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if http_request("GET", "/") is not None:
            return True
        time.sleep(0.5)
    return False


def cleanup(container_names: list[str]) -> None:
    for name in container_names:
        _run(["docker", "stop", name])
    _run(["docker", "network", "rm", NET_NAME])


def main() -> int:
    if not check_docker_available():
        print("Docker daemon not available — aborting.")
        return 2

    container_names = []
    net_created = False
    exit_code = 2
    try:
        proc = _run(["docker", "network", "create", NET_NAME])
        if proc.returncode != 0:
            print(f"network create failed: {proc.stderr}")
            return 2
        net_created = True

        for alias, port in MOCK_UPSTREAMS.items():
            name = f"{RUN_TAG}_{alias}"
            container_names.append(name)
            proc = _run([
                "docker", "run", "-d", "--rm",
                "--network", NET_NAME,
                "--network-alias", alias,
                "--name", name,
                "python:3.11-slim", "python3", "-m", "http.server", str(port),
            ])
            if proc.returncode != 0:
                print(f"mock upstream {alias} failed to start: {proc.stderr}")
                return 2

        frontend_name = f"{RUN_TAG}_frontend"
        container_names.append(frontend_name)
        proc = _run([
            "docker", "run", "-d", "--rm",
            "--network", NET_NAME,
            "--name", frontend_name,
            "-p", f"127.0.0.1:{HOST_PORT}:80",
            "-v", f"{NGINX_CONF}:/etc/nginx/conf.d/default.conf:ro",
            "-v", f"{FRONTEND_DIR}:/usr/share/nginx/html:ro",
            "nginx:alpine",
        ])
        if proc.returncode != 0:
            print(f"frontend nginx failed to start: {proc.stderr}")
            return 2

        if not wait_ready():
            logs = _run(["docker", "logs", frontend_name])
            print(f"frontend nginx did not become ready:\n{logs.stdout}\n{logs.stderr}")
            return 2

        failed = []
        for method, path, expected in CASES:
            actual = http_request(method, path)
            ok = actual == expected
            verdict = "PASS" if ok else "FAIL"
            print(f"{verdict}  {method:8s} {path:28s} expect={expected} actual={actual}")
            if not ok:
                failed.append((method, path, expected, actual))

        exit_code = 1 if failed else 0
        print()
        print(f"TOTAL: {len(CASES)}  PASS: {len(CASES) - len(failed)}  FAIL: {len(failed)}")
        return exit_code
    finally:
        cleanup(container_names if net_created else [])


if __name__ == "__main__":
    sys.exit(main())

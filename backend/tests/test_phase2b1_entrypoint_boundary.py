"""
Phase 2-B.1 受入試験 — public/operator entrypoint分離・import graph境界・
operator secret fail-closed（AT-01、AT-02の一部、第5.7節2-B.1）。

対応する受入条件（tasks/public-release/phase2b1_claude_implementation_instruction.md 4節）:
  AT-01:
    - public route一覧が明示allowlistと一致
    - admin/simulation/operator routeが0件
    - public import graph内のadmin/simulation/Docker操作moduleが0件
    - operator関連環境変数を与えた前後でpublic route一覧が完全一致
  AT-02 (image検証を除く、entrypointレベルの事前条件):
    - operator imageはdummy secretありでoperator entrypoint smoke成功、
      secretなし／空／空白で非0終了

実物Docker imageの検査（AT-02の残り・AT-12）は
tools/public_release/phase2b1_image_inspect.py が別途担当する
（docker build を要するためpytestの対象外）。

実行:
    cd backend && ../venv/bin/python -m pytest tests/test_phase2b1_entrypoint_boundary.py -v

注意: app_public のimportはハザードデータ（実データ、数十万ポリゴン規模）を
実際にロードするため、各サブプロセスの実行に数十秒かかる。これは
production起動時間そのものであり、テストの不備ではない。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
INTROSPECT_SCRIPT = Path(__file__).resolve().parent / "_phase2b1_introspect_app_public.py"

SUBPROCESS_TIMEOUT_SECONDS = 180

# ============================================================
# public entrypoint route allowlist（method+path exact set、第5.1節）
# ============================================================
# P2B1-CX-002（CODEX独立検証、2026-08-10）: 旧実装はprefix包括許可
# （例: "/api/live"配下を無条件許可）だったため、想定外route追加を検出
# できないtest coverage gapがあった。CODEX独立検証で実測・固定された
# 50件のmethod+path exact setを規範値とし、完全一致（missing/extraの
# 両方を個別に診断）へ置き換える。
#
# Phase 2-C（第3.1節）対応: app_public.pyがdocs_url/redoc_url/openapi_url=None
# へ変更され、production既定（本testが検証する「clean env」）ではFastAPI docs
# 4routeがpublic route tableへ登録されなくなった。50件から4件
# （/docs, /docs/oauth2-redirect, /openapi.json, /redoc）を除いた46件から、
# P2E-R51-SEC-001でpublic dev publish routeを除いた45件が
# 新しい規範値である。development限定でdocsを再有効化した場合の検証は
# tests/test_phase2c_public_hardening.py::TestDocsDevelopmentModeToggle が
# 別途担当する（本testはproduction既定のnegativeケースのみを扱う）。
#
# 正規化契約: "<comma-separated sorted HTTP methods> <path>"
#   例: "GET /health", "POST /api/evacuation"
#
# 出典: tasks/public-release/github_public_audit_phase2b1_codex_verification.md
#       第4.1節（実物public image内でのroute inventory実測、50件）から
#       Phase 2-Cのdocs無効化差分を反映
EXPECTED_PUBLIC_ROUTES = frozenset(
    {
        "GET /",
        "GET,HEAD /health",
        "GET /api/astro/current",
        "GET /api/earthquakes",
        "GET /api/earthquakes/realtime/status",
        "GET /api/earthquakes/recent",
        "GET /api/earthquakes/stream",
        "GET /api/elevation",
        "POST /api/elevation-profile",
        "GET /api/emergency-shelters",
        "POST /api/evacuation",
        "GET /api/hazard-check",
        "GET /api/hazards/active",
        "GET /api/hazards/inland_flood/{region}",
        "GET /api/hazards/landslide/{region}",
        "GET /api/hazards/{hazard_type}/{region_code}",
        "GET /api/hazards/{hazard_type}/{region_code}/meta",
        "GET /api/jartic/traffic",
        "GET /api/live/earthquakes/history",
        "GET /api/live/rain/timeline",
        "GET /api/live/road-traffic/summary",
        "GET /api/live/storm_surge/warnings",
        "GET /api/live/summary",
        "GET /api/live/sun-moon",
        "GET /api/live/tide/stations",
        "GET /api/live/tide/stations/{station_id}",
        "GET /api/live/trains/osm",
        "GET /api/live/trains/summary",
        "GET /api/live/weather/jma/prefectures",
        "POST /api/navigation/route/compare",
        "GET /api/reverse-geocode",
        "POST /api/route-risk",
        "GET /api/stats",
        "GET /api/tide/current",
        "GET /api/tide/hourly",
        "GET /api/tide/stations",
        "GET /api/tsunami/warnings/current",
        "GET /api/weather/alerts/current",
        "GET /api/weather/current",
        "GET /api/weather/precipitation/summary",
        "GET /api/weather/rain/tile/latest",
        "GET /api/weather/rain/tile/times",
        "GET /api/weather/risk/context",
        "POST /api/weather/risk/route",
        "GET /api/weather/warnings",
    }
)
assert len(EXPECTED_PUBLIC_ROUTES) == 45

# 管理・operator機能のroute prefix denylist（public routeに1件でも現れてはならない）
DENYLIST_PREFIXES = (
    "/api/admin",
    "/api/simulation",
)


def _canonical_route_lines(introspection: Dict[str, Any]) -> set:
    """introspection結果を "<comma-separated sorted methods> <path>" 集合へ正規化する。

    FastAPI/StarletteのAPIRoute.methodsは、GET routeにHEADが自動追加される等
    実route object由来の値をそのまま使う（静的推測ではなく実測に基づく）。
    """
    lines = set()
    for path, methods in introspection["routes"]:
        canonical_methods = ",".join(sorted(methods))
        lines.add(f"{canonical_methods} {path}")
    return lines

# public import graphに存在してはならないmodule（admin/simulation router、
# Docker操作を行うservice、operator entrypoint自身）
FORBIDDEN_MODULES = (
    "app.api.admin",
    "app.api.admin_config",
    "app.api.admin_datasets",
    "app.api.admin_upload",
    "app.api.layer_types_api",
    "app.api.simulation",
    "app.services.pipeline_service",
    "app.services.job_manager",
    "app.services.admin_hazard_service",
    "app.services.config_change_notifier",
    "app_operator",
)


def _run_introspect(env_overrides: Dict[str, str]) -> Dict[str, Any]:
    """app_public を別プロセスでimportし、route一覧とimportされたmodule集合を得る。"""
    env = os.environ.copy()
    env.update(env_overrides)
    proc = subprocess.run(
        [sys.executable, str(INTROSPECT_SCRIPT)],
        cwd=str(BACKEND_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=SUBPROCESS_TIMEOUT_SECONDS,
    )
    assert proc.returncode == 0, (
        f"app_public introspection subprocess failed (exit={proc.returncode}).\n"
        f"stdout(tail)={proc.stdout[-2000:]}\nstderr(tail)={proc.stderr[-4000:]}"
    )
    # stdoutの最終行がJSON（それ以前の行は起動ログ）
    last_line = proc.stdout.strip().splitlines()[-1]
    return json.loads(last_line)


@pytest.fixture(scope="module")
def public_introspection_clean_env() -> Dict[str, Any]:
    """operator関連環境変数を一切与えない状態でのapp_public introspection結果。"""
    return _run_introspect({})


@pytest.fixture(scope="module")
def public_introspection_operator_env() -> Dict[str, Any]:
    """operator関連環境変数（不正・ダミー値含む）を与えた状態でのapp_public introspection結果。

    「operator関連環境変数を設定してもpublic route集合が変化しない構造にする」
    （instruction 3.1節）の検証。
    """
    return _run_introspect(
        {
            "OPERATOR_AUTH_SECRET": "OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE",
            "OPERATOR_ENABLED": "true",
            "OPERATOR_LISTEN_HOST": "0.0.0.0",
            "OPERATOR_PORT": "8100",
        }
    )


def _route_paths(introspection: Dict[str, Any]) -> set:
    return {path for path, _methods in introspection["routes"]}


class TestPublicRouteAllowlist:
    """AT-01: public route一覧が明示allowlist（45件のmethod+path exact set）と完全一致、
    admin/simulation/operator routeが0件（P2B1-CX-002対応、prefix包括許可を廃止）。"""

    def test_all_public_routes_match_exact_allowlist(self, public_introspection_clean_env):
        actual = _canonical_route_lines(public_introspection_clean_env)
        assert actual, "app_public にrouteが1件も登録されていない（introspectionが壊れている疑い）"

        missing = sorted(EXPECTED_PUBLIC_ROUTES - actual)
        extra = sorted(actual - EXPECTED_PUBLIC_ROUTES)
        assert missing == [] and extra == [], (
            f"public route一覧が規範allowlist（45件）と完全一致しない。\n"
            f"missing（規範集合にあるがpublicに存在しない）: {missing}\n"
            f"extra（publicに存在するが規範集合にない、想定外route追加の疑い）: {extra}"
        )
        assert len(actual) == 45, f"route数が45件ではない: {len(actual)}"

    def test_no_admin_or_simulation_routes(self, public_introspection_clean_env):
        paths = _route_paths(public_introspection_clean_env)
        denied = [p for p in paths if any(p == d or p.startswith(d + "/") for d in DENYLIST_PREFIXES)]
        assert denied == [], f"admin/simulation routeがpublic entrypointに存在する: {sorted(denied)}"


class TestPublicImportGraph:
    """AT-01: public import graph内のadmin/simulation/Docker操作moduleが0件。"""

    def test_no_forbidden_modules_in_public_import_graph(self, public_introspection_clean_env):
        modules = set(public_introspection_clean_env["modules"])
        present = sorted(modules & set(FORBIDDEN_MODULES))
        assert present == [], (
            f"public import graphに禁止moduleが含まれている: {present}"
        )


class TestOperatorEnvVarInvariance:
    """AT-01: operator関連環境変数を与えた前後でpublic route一覧が完全一致。"""

    def test_route_set_unchanged_with_operator_env_vars(
        self, public_introspection_clean_env, public_introspection_operator_env
    ):
        clean_routes = public_introspection_clean_env["routes"]
        operator_env_routes = public_introspection_operator_env["routes"]
        assert sorted(clean_routes) == sorted(operator_env_routes), (
            "operator関連環境変数の有無でpublic route一覧が変化した。\n"
            f"only in clean env: {sorted(set(map(tuple, clean_routes)) - set(map(tuple, operator_env_routes)))}\n"
            f"only in operator env: {sorted(set(map(tuple, operator_env_routes)) - set(map(tuple, clean_routes)))}"
        )

    def test_no_forbidden_modules_even_with_operator_env_vars(self, public_introspection_operator_env):
        modules = set(public_introspection_operator_env["modules"])
        present = sorted(modules & set(FORBIDDEN_MODULES))
        assert present == [], (
            f"operator環境変数を与えた状態でpublic import graphに禁止moduleが含まれている: {present}"
        )


class TestOperatorFailClosedSecret:
    """AT-02項目10（entrypointレベル）: operator secret未設定／空／空白でfail-closed。"""

    def _run_app_operator_import(self, secret_value):
        env = os.environ.copy()
        if secret_value is None:
            env.pop("OPERATOR_AUTH_SECRET", None)
        else:
            env["OPERATOR_AUTH_SECRET"] = secret_value
        proc = subprocess.run(
            [sys.executable, "-c", "import app_operator; print('IMPORT_OK')"],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return proc

    @pytest.mark.parametrize(
        "secret_value",
        [None, "", "   ", "\t\n"],
        ids=["unset", "empty", "whitespace", "whitespace-tab-newline"],
    )
    def test_missing_or_blank_secret_exits_nonzero(self, secret_value):
        proc = self._run_app_operator_import(secret_value)
        assert proc.returncode != 0, (
            f"OPERATOR_AUTH_SECRET={secret_value!r} でapp_operatorのimportが"
            f"exit code 0で成功してしまった（fail-closed要件違反）"
        )
        assert "IMPORT_OK" not in proc.stdout

    def test_dummy_secret_allows_startup(self):
        proc = self._run_app_operator_import("OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE")
        assert proc.returncode == 0, (
            f"dummy secretを与えてもapp_operatorのimportが失敗した: "
            f"exit={proc.returncode} stderr(tail)={proc.stderr[-2000:]}"
        )
        assert "IMPORT_OK" in proc.stdout

    def test_operator_entrypoint_registers_no_public_only_bespoke_routes(self):
        """operator appにはpublicのbespoke route（/, /health等）が登録されていないことを
        併せて確認する（operator import graph側の簡易チェック）。
        """
        env = os.environ.copy()
        env["OPERATOR_AUTH_SECRET"] = "OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE"
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import json, app_operator\n"
                "paths = sorted(getattr(r, 'path', None) for r in app_operator.app.routes)\n"
                "print(json.dumps(paths))",
            ],
            cwd=str(BACKEND_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert proc.returncode == 0, proc.stderr[-2000:]
        paths = json.loads(proc.stdout.strip().splitlines()[-1])
        assert "/" not in paths
        assert "/health" not in paths
        assert "/api/evacuation" not in paths
        # operator routerは /api/admin または /api/simulation 配下のみ
        # （OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN Phase B: /api/login・
        # /api/session・/api/logout・/api/system/shutdown はWeb管理画面の
        # login/session/shutdown専用routeで、operator-only・public appには
        # 存在しない意図的な例外として固定allowlistへ追加する）。
        for p in paths:
            if p in (
                None,
                "/operator/health",
                "/openapi.json",
                "/docs",
                "/docs/oauth2-redirect",
                "/redoc",
                "/api/login",
                "/api/session",
                "/api/logout",
                "/api/system/shutdown",
            ):
                continue
            assert p.startswith("/api/admin") or p.startswith("/api/simulation"), (
                f"operator entrypointに想定外のroute prefixが登録されている: {p}"
            )

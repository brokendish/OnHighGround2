"""
test_operator_admin_session.py — OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN Phase B
自動テスト（login/session/logout/CSRF/shutdown）。

既存のtest_phase2b3_operator_security.pyと同じ方針:
- 実Docker containerをstartする/停止するpositive testは行わない
  （asyncio.create_subprocess_execをfake化し、argvと呼出し順序だけを検査）。
- audit log・JobManager・operator_sessionのin-memory storeをtestごとに
  隔離する（実運用状態を汚さない）。

実行:
    cd backend && OPERATOR_AUTH_SECRET=OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE \
        ../venv/bin/python -m pytest tests/test_operator_admin_session.py -v
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("OPERATOR_AUTH_SECRET", "OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE")

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
DUMMY_SECRET = os.environ["OPERATOR_AUTH_SECRET"]

sys.path.insert(0, str(BACKEND_DIR)) if str(BACKEND_DIR) not in sys.path else None

import app_operator  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.services import job_manager as job_manager_module  # noqa: E402
from app.services import operator_audit_log  # noqa: E402
from app.services import operator_session  # noqa: E402
from app.services import docker_operation_gateway as gw  # noqa: E402
import app.api.admin_session as admin_session_module  # noqa: E402


@pytest.fixture(autouse=True)
def _redirect_audit_log(tmp_path, monkeypatch):
    monkeypatch.setattr(operator_audit_log, "AUDIT_LOG_PATH", tmp_path / "operator_audit.log")
    yield


@pytest.fixture(autouse=True)
def _redirect_job_manager(tmp_path, monkeypatch):
    fresh = job_manager_module.JobManager(jobs_dir=tmp_path / "jobs", logs_dir=tmp_path / "logs")
    monkeypatch.setattr(job_manager_module, "_instance", fresh)
    yield


@pytest.fixture(autouse=True)
def _clear_sessions():
    operator_session.clear_all_sessions()
    yield
    operator_session.clear_all_sessions()


@pytest.fixture()
def client() -> TestClient:
    # `Secure` cookie（意図的に常時付与、docs/8節参照）はhttpxのcookie jarが
    # http://ではなくhttps://相手にしか送り返さない。実ブラウザの挙動を正しく
    # 再現するため、TestClientのbase_urlをhttpsにする（ASGI経由の疑似
    # requestであり実TLSは介在しない。cookie jarの送信可否判定だけがこの
    # schemeを見る）。
    return TestClient(app_operator.app, base_url="https://testserver")


def _read_audit_events() -> List[Dict[str, Any]]:
    path = operator_audit_log.AUDIT_LOG_PATH
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _events_of(events: List[Dict[str, Any]], name: str) -> List[Dict[str, Any]]:
    return [e for e in events if e.get("event") == name]


def _login(client: TestClient, token: str = DUMMY_SECRET):
    return client.post("/api/login", json={"token": token})


def _login_get_session_id(client: TestClient, token: str = DUMMY_SECRET):
    """loginしてsession_idを取り出す。

    本testはbackendを直接（nginxのrewriteを経由せず）叩くため、Set-Cookieの
    `Path=/admin`はhttpxのcookie jarにとって`/api/...`宛のrequestとは
    非一致になり、以後の呼出しへ自動再送されない（これは実ブラウザの
    Path scoping契約を正しく再現しているだけで、bugではない——実際の
    productionではbrowserは常に`/admin/api/...`を呼び、nginxがrewriteして
    backendへ届く時点で既にcookieは付いている）。
    そのためtestではjarに任せず、`cookies=`引数で明示的に載せる。
    """
    r = _login(client, token)
    sid = r.cookies.get(operator_session.SESSION_COOKIE_NAME)
    return r, sid


def _cookie(session_id: str) -> Dict[str, str]:
    return {operator_session.SESSION_COOKIE_NAME: session_id}


# ============================================================
# Authentication（login）
# ============================================================


class TestLogin:
    def test_valid_token_logs_in(self, client):
        r = _login(client)
        assert r.status_code == 200
        body = r.json()
        assert body["authenticated"] is True
        assert "csrf_token" in body and body["csrf_token"]
        assert operator_session.SESSION_COOKIE_NAME in r.cookies

    def test_invalid_token_rejected(self, client):
        r = _login(client, token="wrong-token")
        assert r.status_code == 401
        assert DUMMY_SECRET not in r.text

    def test_empty_token_rejected(self, client):
        r = _login(client, token="")
        assert r.status_code == 401

    def test_missing_token_field_rejected(self, client):
        r = client.post("/api/login", json={})
        assert r.status_code == 401

    def test_missing_body_rejected_not_422(self, client):
        """空bodyでも422ではなく401（test_auth_n08の全route401契約と一致させる）。"""
        r = client.post("/api/login")
        assert r.status_code == 401

    def test_malformed_json_body_rejected_not_500(self, client):
        r = client.post("/api/login", content=b"{not-json", headers={"content-type": "application/json"})
        assert r.status_code == 401

    def test_token_never_in_response(self, client):
        r = _login(client)
        assert DUMMY_SECRET not in r.text
        r2 = _login(client, token="wrong-token-xyz")
        assert "wrong-token-xyz" not in r2.text

    def test_token_never_logged(self, client):
        _login(client, token="canary-login-token-value")
        log_text = operator_audit_log.AUDIT_LOG_PATH.read_text(encoding="utf-8") \
            if operator_audit_log.AUDIT_LOG_PATH.exists() else ""
        assert "canary-login-token-value" not in log_text

    def test_login_success_audit_event(self, client):
        _login(client)
        events = _events_of(_read_audit_events(), "operator_login")
        successes = [e for e in events if e["result"] == "success"]
        assert successes
        e = successes[0]
        assert set(e.keys()) == {"event", "timestamp", "request_id", "actor_id", "result", "reason_code"}
        assert e["reason_code"] == "OK"

    def test_login_failure_audit_event(self, client):
        _login(client, token="wrong")
        events = _events_of(_read_audit_events(), "operator_login")
        failures = [e for e in events if e["result"] == "failure"]
        assert failures
        assert failures[0]["reason_code"] == "TOKEN_MISMATCH"


# ============================================================
# Session status / reload
# ============================================================


class TestSessionStatus:
    def test_cookie_attributes(self, client):
        r = _login(client)
        set_cookie = r.headers.get("set-cookie", "")
        assert "Secure" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie or "SameSite=Strict" in set_cookie
        assert "Path=/admin" in set_cookie
        assert "Max-Age=3600" in set_cookie

    def test_session_status_after_login(self, client):
        _, sid = _login_get_session_id(client)
        r = client.get("/api/session", cookies=_cookie(sid))
        assert r.status_code == 200
        body = r.json()
        assert body["authenticated"] is True
        assert body["csrf_token"]

    def test_session_survives_reload_simulation(self, client):
        """reload = 新規request（JSクロージャ状態は失われるがcookieは残る）を模擬。"""
        _, sid = _login_get_session_id(client)
        r1 = client.get("/api/session", cookies=_cookie(sid))
        r2 = client.get("/api/session", cookies=_cookie(sid))
        assert r1.status_code == 200 and r2.status_code == 200

    def test_no_session_rejected(self, client):
        r = client.get("/api/session")
        assert r.status_code == 401

    def test_expired_session_rejected(self, client):
        _, sid = _login_get_session_id(client)
        # in-memory storeを直接操作し、期限切れ状態を作る（実TTL 60分を待たない）。
        assert operator_session.session_count() == 1
        with operator_session._lock:  # noqa: SLF001 — test専用の直接操作
            expired = operator_session._sessions[sid]
            from dataclasses import replace
            from datetime import datetime, timedelta, timezone
            operator_session._sessions[sid] = replace(
                expired, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
        r = client.get("/api/session", cookies=_cookie(sid))
        assert r.status_code == 401


# ============================================================
# Logout
# ============================================================


class TestLogout:
    def test_logout_requires_csrf(self, client):
        r_login, sid = _login_get_session_id(client)
        r = client.post("/api/logout", cookies=_cookie(sid))
        assert r.status_code == 403

    def test_logout_invalidates_session(self, client):
        r_login, sid = _login_get_session_id(client)
        csrf = r_login.json()["csrf_token"]
        r = client.post("/api/logout", cookies=_cookie(sid), headers={"X-CSRF-Token": csrf})
        assert r.status_code == 200
        # sessionが破棄され、同じsession_idでの以後の/api/sessionは401
        r2 = client.get("/api/session", cookies=_cookie(sid))
        assert r2.status_code == 401

    def test_logout_audit_event(self, client):
        r_login, sid = _login_get_session_id(client)
        client.post("/api/logout", cookies=_cookie(sid), headers={"X-CSRF-Token": r_login.json()["csrf_token"]})
        events = _events_of(_read_audit_events(), "operator_logout")
        assert events
        assert set(events[0].keys()) == {"event", "timestamp", "request_id", "actor_id"}


# ============================================================
# Authorization（既存admin APIをsessionでも通せる）
# ============================================================


class TestSessionAuthorizesExistingAdminApi:
    def test_session_authorizes_existing_get_route(self, client):
        _, sid = _login_get_session_id(client)
        r = client.get("/api/admin/hazards", cookies=_cookie(sid))
        assert r.status_code == 200

    def test_session_without_csrf_rejected_on_mutation(self, client):
        _, sid = _login_get_session_id(client)
        r = client.post("/api/admin/logs/navigation", json={"message": "x"}, cookies=_cookie(sid))
        assert r.status_code == 403

    def test_session_with_valid_csrf_authorizes_mutation(self, client):
        r_login, sid = _login_get_session_id(client)
        r = client.post(
            "/api/admin/logs/navigation",
            json={"message": "x"},
            cookies=_cookie(sid),
            headers={"X-CSRF-Token": r_login.json()["csrf_token"]},
        )
        assert r.status_code != 401 and r.status_code != 403

    def test_legacy_bearer_still_works_unaffected_by_session_changes(self, client):
        r = client.get("/api/admin/hazards", headers={"Authorization": f"Bearer {DUMMY_SECRET}"})
        assert r.status_code == 200

    def test_bearer_does_not_require_csrf(self, client):
        """Bearerクライアント（非ブラウザ）はCSRF header無しでmutationを呼べる
        （既存CLI/testの後方互換、owner方針どおり）。"""
        r = client.post(
            "/api/admin/logs/navigation",
            json={"message": "x"},
            headers={"Authorization": f"Bearer {DUMMY_SECRET}"},
        )
        assert r.status_code != 403


# ============================================================
# CSRF
# ============================================================


class TestCSRF:
    def test_wrong_csrf_token_rejected(self, client):
        r_login, sid = _login_get_session_id(client)
        r = client.post("/api/logout", cookies=_cookie(sid), headers={"X-CSRF-Token": "not-the-real-token"})
        assert r.status_code == 403

    def test_get_endpoints_never_require_csrf(self, client):
        _, sid = _login_get_session_id(client)
        r = client.get("/api/session", cookies=_cookie(sid))
        assert r.status_code == 200  # GETはCSRF不要

    def test_shutdown_get_method_not_allowed(self, client):
        _, sid = _login_get_session_id(client)
        r = client.get("/api/system/shutdown", cookies=_cookie(sid))
        assert r.status_code == 405


# ============================================================
# Docker operation catalog（stop targets）
# ============================================================


class TestShutdownCatalog:
    def test_exactly_two_stop_operations(self):
        stop_ops = {k for k in gw.ALLOWED_OPERATION_IDS if k.startswith("stop:")}
        assert stop_ops == {"stop:operator-gateway", "stop:backend-operator"}

    def test_stop_targets_are_operator_only(self):
        """新規stop系operationのtarget_idが、operator profileの2 container
        （operator-gateway・backend-operator）だけであることを確認する。
        既存restart系operation（martin/osrm）はこのtestの対象外——それらは
        Phase 2-B.3から存在する別機能であり、今回のshutdown機能が
        追加で操作可能にするtargetではない、という点だけをここでは確認する。"""
        forbidden = {
            "evacuation-navi-frontend",
            "evacuation-navi-backend",
            "evacuation-navi-martin",
            "evacuation-navi-osrm-walking",
            "evacuation-navi-osrm-driving",
            "evacuation-navi-runtime-init",
        }
        stop_targets = {gw._CATALOG[k].target_id for k in gw._CATALOG if k.startswith("stop:")}
        assert stop_targets == {"evacuation-navi-operator-gateway", "evacuation-navi-backend-operator"}
        assert not (stop_targets & forbidden)

    def test_stop_operations_use_fixed_argv_docker_stop(self):
        assert gw._CATALOG["stop:operator-gateway"].argv == ("docker", "stop", "evacuation-navi-operator-gateway")
        assert gw._CATALOG["stop:backend-operator"].argv == ("docker", "stop", "evacuation-navi-backend-operator")


# ============================================================
# Shutdown sequence（202 first, then ordered stop）
# ============================================================


class TestShutdownSequence:
    def test_shutdown_requires_valid_session(self, client):
        r = client.post("/api/system/shutdown")
        assert r.status_code == 401

    def test_shutdown_requires_csrf(self, client):
        _, sid = _login_get_session_id(client)
        r = client.post("/api/system/shutdown", cookies=_cookie(sid))
        assert r.status_code == 403

    def test_shutdown_returns_202_with_valid_session_and_csrf(self, client, monkeypatch):
        # background task自体は即時実行されうるが、execute_operationをstubして
        # 実docker呼び出しは発生させない。
        calls = []

        async def _stub_execute(operation_id, *, actor_id, request_id, log_line=None):
            calls.append(operation_id)
            return gw.DockerOperationResult(returncode=0, timed_out=False)

        monkeypatch.setattr(admin_session_module, "execute_operation", _stub_execute)
        monkeypatch.setattr(admin_session_module, "_SHUTDOWN_DELAY_SECONDS", 0)

        r_login, sid = _login_get_session_id(client)
        r = client.post(
            "/api/system/shutdown",
            cookies=_cookie(sid),
            headers={"X-CSRF-Token": r_login.json()["csrf_token"]},
        )
        assert r.status_code == 202
        assert "docker compose --profile operator up -d" in r.json()["message"]

    def test_shutdown_no_request_parameters_control_target(self, client, monkeypatch):
        """requestにcontainer名を注入しても無視され、固定catalogのみが呼ばれる。"""
        calls = []

        async def _stub_execute(operation_id, *, actor_id, request_id, log_line=None):
            calls.append(operation_id)
            return gw.DockerOperationResult(returncode=0, timed_out=False)

        monkeypatch.setattr(admin_session_module, "execute_operation", _stub_execute)
        monkeypatch.setattr(admin_session_module, "_SHUTDOWN_DELAY_SECONDS", 0)

        r_login, sid = _login_get_session_id(client)
        r = client.post(
            "/api/system/shutdown",
            cookies=_cookie(sid),
            headers={"X-CSRF-Token": r_login.json()["csrf_token"]},
            json={"target": "evacuation-navi-backend", "container": "evacuation-navi-martin"},
        )
        assert r.status_code == 202
        assert calls == ["stop:operator-gateway", "stop:backend-operator"]

    def test_perform_shutdown_stops_gateway_before_backend_operator(self, monkeypatch):
        """_perform_shutdown自体を直接実行し、呼出し順序を検証する
        （HTTP round-trip・BackgroundTasksのタイミング依存を避けた直接単体試験）。"""
        calls = []

        async def _stub_execute(operation_id, *, actor_id, request_id, log_line=None):
            calls.append(operation_id)
            return gw.DockerOperationResult(returncode=0, timed_out=False)

        monkeypatch.setattr(admin_session_module, "execute_operation", _stub_execute)
        monkeypatch.setattr(admin_session_module, "_SHUTDOWN_DELAY_SECONDS", 0)

        asyncio.run(admin_session_module._perform_shutdown(request_id="r1", actor_id="op:test000000"))
        assert calls == ["stop:operator-gateway", "stop:backend-operator"]

    def test_shutdown_requested_audit_event_logged_before_docker_calls(self, monkeypatch):
        order = []

        async def _stub_execute(operation_id, *, actor_id, request_id, log_line=None):
            order.append(("docker", operation_id))
            return gw.DockerOperationResult(returncode=0, timed_out=False)

        def _stub_log_requested(*, request_id, actor_id):
            order.append(("audit", "shutdown_requested"))

        monkeypatch.setattr(admin_session_module, "execute_operation", _stub_execute)
        monkeypatch.setattr(admin_session_module, "log_operator_shutdown_requested", _stub_log_requested)
        monkeypatch.setattr(admin_session_module, "_SHUTDOWN_DELAY_SECONDS", 0)

        asyncio.run(admin_session_module._perform_shutdown(request_id="r1", actor_id="op:test000000"))
        assert order[0] == ("audit", "shutdown_requested")
        assert order[1:] == [("docker", "stop:operator-gateway"), ("docker", "stop:backend-operator")]

    def test_shutdown_does_not_fake_success_on_docker_operation_error(self, monkeypatch):
        """個別operationがDockerOperationErrorを送出しても、_perform_shutdownは
        握りつぶして次へ進む（例外を飲み込むが、成功を偽装するイベントは書かない
        ——docker_operation_gateway自身のaudit fail-closed規律にすべて委ねる）。"""
        calls = []

        async def _stub_execute_first_fails(operation_id, *, actor_id, request_id, log_line=None):
            calls.append(operation_id)
            if operation_id == "stop:operator-gateway":
                raise gw.DockerOperationError("SPAWN_FAILED", "boom")
            return gw.DockerOperationResult(returncode=0, timed_out=False)

        monkeypatch.setattr(admin_session_module, "execute_operation", _stub_execute_first_fails)
        monkeypatch.setattr(admin_session_module, "_SHUTDOWN_DELAY_SECONDS", 0)

        asyncio.run(admin_session_module._perform_shutdown(request_id="r1", actor_id="op:test000000"))
        # 1件目が失敗しても2件目（backend-operator自己停止）は試行される。
        assert calls == ["stop:operator-gateway", "stop:backend-operator"]


# ============================================================
# XSS regression（datasets.js修正の後退防止・静的text検査）
# ============================================================


class TestDatasetsJsXssRegression:
    """OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN Phase Bの XSS audit
    （2026-09-12実施）で検出・修正した5件が再発しないことを、
    既存test_dop_n05/n06と同じ静的text検査の方針で確認する。"""

    _DATASETS_JS = REPO_ROOT / "operator" / "frontend-admin" / "datasets.js"

    def _text(self) -> str:
        return self._DATASETS_JS.read_text(encoding="utf-8")

    def test_esc_js_helper_exists(self):
        text = self._text()
        assert "function escJs(" in text

    def test_current_file_name_is_escaped(self):
        text = self._text()
        assert 'title="${escAttr(d.current_file_name)}"' in text
        assert "${escHtml(d.current_file_name)}" in text
        # 旧・無エスケープの直接埋め込みが残っていないこと
        assert 'title="${d.current_file_name}"' not in text

    def test_dataset_id_onclick_uses_escattr_escjs(self):
        text = self._text()
        onclick_dataset_id = re.findall(r"onclick=\"open\w+\('([^']*)'\)\"", text)
        assert onclick_dataset_id, "onclick(...dataset_id...)パターンが見つからない"
        for expr in onclick_dataset_id:
            assert expr in ("${escAttr(escJs(d.dataset_id))}", "${escAttr(escJs(d.last_job_id))}"), (
                f"未エスケープのonclick埋め込みを検出: {expr!r}"
            )

    def test_detail_fields_are_escaped(self):
        text = self._text()
        assert "${escHtml(defn.dataset_id)}" in text
        assert "${escHtml(defn.runtime_path)}" in text
        assert "${escHtml(job.error_code)}" in text

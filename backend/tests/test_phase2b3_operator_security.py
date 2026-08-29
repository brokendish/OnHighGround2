"""
Phase 2-B.3 受入試験 — operator Bearer認証・認可・Docker operation allowlist・
構造化監査ログ（AT-10、tasks/public-release/phase2b3_claude_implementation_instruction.md 第9節）。

AUTH-P01/P02, AUTH-N01〜N08, DOP-P01〜P07, DOP-N01〜N08, AUD-P01〜P06, AUD-N01〜N06
の全fixtureをこのファイルに実装する。

実Docker containerをrestart／execするpositive testは行わない（第9.2節の禁止事項）。
subprocess runnerをfake化し、生成argvと呼出し回数のみを検査する。

実行:
    cd backend && OPERATOR_AUTH_SECRET=OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE \
        ../venv/bin/python -m pytest tests/test_phase2b3_operator_security.py -v

注意: app_operatorはmodule import時にOPERATOR_AUTH_SECRETのfail-closed検証を
行うため、本ファイルの先頭（他のimportより前）で環境変数を設定する
（test_phase2b1_entrypoint_boundary.pyがsubprocess経由で毎回新規importするのとは
異なり、本ファイルはTestClientでの多数fixtureを高速に回すためprocess内で
一度だけimportし、以後は使い回す）。
"""
from __future__ import annotations

import ast
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

os.environ.setdefault("OPERATOR_AUTH_SECRET", "OHG2_PHASE2B1_DUMMY_SECRET_DO_NOT_USE")

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"
DUMMY_SECRET = os.environ["OPERATOR_AUTH_SECRET"]
AUTH_HEADERS = {"Authorization": f"Bearer {DUMMY_SECRET}"}

sys.path.insert(0, str(BACKEND_DIR)) if str(BACKEND_DIR) not in sys.path else None

import app_operator  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.services import job_manager as job_manager_module  # noqa: E402
from app.services import operator_audit_log  # noqa: E402
from app.services import docker_operation_gateway as gw  # noqa: E402
from app.services.operator_auth import OperatorPrincipal, require_operator_role  # noqa: E402


# ------------------------------------------------------------------
# 共通fixture: 実data_lakeを一切汚さないよう、audit log・JobManagerを
# testごとにtmp_pathへ差し替える。
# ------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _redirect_audit_log(tmp_path, monkeypatch):
    monkeypatch.setattr(operator_audit_log, "AUDIT_LOG_PATH", tmp_path / "operator_audit.log")
    yield


@pytest.fixture(autouse=True)
def _redirect_job_manager(tmp_path, monkeypatch):
    fresh = job_manager_module.JobManager(jobs_dir=tmp_path / "jobs", logs_dir=tmp_path / "logs")
    monkeypatch.setattr(job_manager_module, "_instance", fresh)
    yield


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app_operator.app)


def _read_audit_events() -> List[Dict[str, Any]]:
    path = operator_audit_log.AUDIT_LOG_PATH
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def _events_of(events: List[Dict[str, Any]], name: str) -> List[Dict[str, Any]]:
    return [e for e in events if e.get("event") == name]


# ============================================================
# AUTH-P: 正常系
# ============================================================


class TestAuthPositive:
    def test_auth_p01_valid_bearer_read_route_succeeds(self, client):
        r = client.get("/api/admin/hazards", headers=AUTH_HEADERS)
        assert r.status_code == 200

    def test_auth_p02_valid_bearer_state_changing_reaches_service_mock(self, client, monkeypatch):
        called = {"n": 0}

        async def _stub(job, jm):
            called["n"] += 1

        from app.services import pipeline_service

        monkeypatch.setattr(pipeline_service, "run_osrm_profile_rebuild", _stub)

        r = client.post("/api/admin/osrm/rebuild", headers=AUTH_HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert body["accepted"] is True
        assert body["job_id"]


# ============================================================
# AUTH-N: 異常系（すべて401、raw tokenは応答へ含めない）
# ============================================================


class TestAuthNegative:
    TARGET = "/api/admin/hazards"

    def test_auth_n01_missing_authorization(self, client):
        r = client.get(self.TARGET)
        assert r.status_code == 401
        assert r.headers.get("www-authenticate") == "Bearer"
        assert DUMMY_SECRET not in r.text

    def test_auth_n02_invalid_scheme(self, client):
        r = client.get(self.TARGET, headers={"Authorization": f"Basic {DUMMY_SECRET}"})
        assert r.status_code == 401

    def test_auth_n02_empty_token(self, client):
        r = client.get(self.TARGET, headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    def test_auth_n03_token_mismatch(self, client):
        r = client.get(self.TARGET, headers={"Authorization": "Bearer wrong-token-value"})
        assert r.status_code == 401
        assert DUMMY_SECRET not in r.text

    def test_auth_n04_token_in_query_only(self, client):
        r = client.get(f"{self.TARGET}?token={DUMMY_SECRET}")
        assert r.status_code == 401

    def test_auth_n05_token_in_cookie_only(self, client):
        r = client.get(self.TARGET, cookies={"operator_token": DUMMY_SECRET})
        assert r.status_code == 401

    def test_auth_n06_token_in_body_only(self, client):
        r = client.post(
            "/api/admin/logs/navigation",
            json={"message": "x", "token": DUMMY_SECRET},
        )
        assert r.status_code in (401, 422)
        # 401（未認証拒否）が本来の期待値。422（extra=forbidによるbody拒否）は
        # 認証チェックより先にbody検証が走った場合の代替許容値だが、
        # 実際の到達順序は下のtest_auth_dependency_runs_before_body_validationで
        # 別途固定検証する。
        assert r.status_code == 401, (
            "token in body only は認証dependencyで401拒否されるべき"
            "（body検証より先に認証が評価される設計、実測で確認）"
        )

    def test_auth_n06_token_in_form_only(self, client):
        r = client.request(
            "DELETE",
            "/api/admin/upload/cancel",
            data={"upload_id": "x", "token": DUMMY_SECRET},
        )
        assert r.status_code == 401

    def test_auth_n07_authenticated_non_operator_principal_forbidden(self):
        """dependency単体試験（HTTP round-trip不要、instruction 9.1節の指定どおり）。"""
        from fastapi import HTTPException

        fake_principal = OperatorPrincipal(role="not-operator", actor_id="op:deadbeef0000")
        with pytest.raises(HTTPException) as exc_info:
            require_operator_role(fake_principal)
        assert exc_info.value.status_code == 403

    def test_auth_n08_no_unprotected_operator_route(self, client):
        """静的route inventory + 実HTTP testの両方でoperator管理route未保護0件を保証する。

        P2B3-CX-001再指摘対応: 旧実装はdocs系4route（/docs, /redoc,
        /openapi.json, /docs/oauth2-redirect）を許容集合から除外しており、
        これらがBearerなしで200到達可能なままCODEXに検出された
        （AUTH-N08自体が検出対象を狭めてしまうfail-open）。
        `/operator/health`は`app_operator.py`でdocs_url等をNoneにして
        docs系route自体を無効化したためapp.routesに存在しなくなった。
        許容集合は`/operator/health`1件だけに絞り、docs系routeが万一
        再度現れた場合もこのtestが検出できるようにする。
        """
        anonymous_allowed = {"/operator/health"}
        checked = 0
        for route in app_operator.app.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None)
            if path is None or methods is None:
                continue
            if path in anonymous_allowed:
                continue
            concrete_path = path.replace("{dataset_id}", "test-dataset") \
                .replace("{layer_type}", "shelter") \
                .replace("{region}", "tokyo") \
                .replace("{job_id}", "test-job") \
                .replace("{key:path}", "test.key") \
                .replace("{layer_key}", "tsunami")
            for method in methods:
                if method == "HEAD":
                    continue
                checked += 1
                r = client.request(method, concrete_path)
                assert r.status_code == 401, (
                    f"未保護のoperator管理routeを検出: {method} {path} "
                    f"(status={r.status_code}, 期待値=401)"
                )
        assert checked > 0, "route inventory testが1件もrouteを検査していない"


# ============================================================
# AUTH dependency解決順序の確認（AUTH-N06裏付け）
# ============================================================


def test_auth_dependency_runs_before_body_validation(client):
    """認証header欠落時、bodyがextra=forbid違反でも401（422ではない）が優先されることを
    直接確認する（AUTH-N06の前提）。"""
    r = client.post("/api/admin/logs/navigation", json={"message": "x", "unexpected": "y"})
    assert r.status_code == 401


# ============================================================
# P2B3-CX-001 再指摘対応: docs系routeの完全無効化
# ============================================================


class TestDocsRoutesDisabled:
    """CODEX P2B3-CX-001: `/operator/health`以外に匿名到達可能なrouteが
    4件（/docs, /redoc, /openapi.json, /docs/oauth2-redirect）存在した。
    `app_operator.py`でdocs_url=None等を指定し、これらのroute自体を
    登録させない設計へ修正した。"""

    @pytest.mark.parametrize(
        "path", ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"]
    )
    def test_docs_route_does_not_exist(self, client, path):
        r = client.get(path)
        assert r.status_code == 404, f"{path} が存在してはならない（status={r.status_code}）"

    def test_no_docs_paths_in_route_table(self):
        paths = {getattr(r, "path", None) for r in app_operator.app.routes}
        for forbidden in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            assert forbidden not in paths, f"{forbidden} がroute tableに残存している"


# ============================================================
# extra=forbid（Pydantic model未知field拒否）
# ============================================================


class TestExtraForbid:
    def test_navigation_log_request_rejects_unknown_field(self, client):
        r = client.post(
            "/api/admin/logs/navigation",
            json={"message": "x", "container": "evacuation-navi-martin"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422

    def test_fetch_url_request_rejects_unknown_field(self, client):
        r = client.post(
            "/api/admin/datasets/test-dataset/fetch-url",
            json={"url": "http://example.invalid/x", "command": "rm -rf /"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422

    def test_set_active_mapping_rejects_unknown_field(self, client):
        r = client.put(
            "/api/admin/active-mappings/shelter/tokyo",
            json={"dataset_id": "x", "args": ["--evil"]},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422

    def test_simulation_run_rejects_unknown_field(self, client):
        r = client.post(
            "/api/simulation/run",
            json={
                "scenario_id": "manual",
                "origin": [139.0, 35.0],
                "destination": [139.1, 35.1],
                "container": "evacuation-navi-osrm-driving",
            },
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422


# ============================================================
# DOP-P: Docker operation allowlist 正常系（7 operation解決）
# ============================================================


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: bytes = b""):
        self.returncode = returncode
        self._stdout = stdout
        self.killed = False

    async def communicate(self):
        return self._stdout, b""

    def kill(self):
        self.killed = True

    async def wait(self):
        return self.returncode


class _SpawnRecorder:
    """asyncio.create_subprocess_execの呼出しargvを記録するfake。"""

    def __init__(self, returncode: int = 0, raise_timeout: bool = False, raise_spawn_error: bool = False):
        self.calls: List[tuple] = []
        self._returncode = returncode
        self._raise_timeout = raise_timeout
        self._raise_spawn_error = raise_spawn_error

    async def __call__(self, *argv, **kwargs):
        self.calls.append(argv)
        if self._raise_spawn_error:
            raise OSError("fake spawn failure")
        return _FakeProc(returncode=self._returncode)


class TestDockerOperationPositive:
    @pytest.mark.parametrize("operation_id", sorted(gw.ALLOWED_OPERATION_IDS))
    def test_dop_p_all_seven_operations_resolve_to_expected_argv(self, operation_id, monkeypatch):
        """DOP-P01〜P07: 固定7 operationが期待verb／target／argvへ一意に解決する。"""
        recorder = _SpawnRecorder(returncode=0)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder)

        result = asyncio.run(
            gw.execute_operation(operation_id, actor_id="op:test000000", request_id="req-1")
        )
        assert result.success
        assert len(recorder.calls) == 1
        argv = recorder.calls[0]
        assert argv[0] == "docker"
        assert argv[1] in ("restart", "exec")
        spec = gw._CATALOG[operation_id]
        assert tuple(argv) == spec.argv
        assert spec.target_id in argv

    def test_dop_p_exactly_seven_operations_in_catalog(self):
        assert len(gw.ALLOWED_OPERATION_IDS) == 7
        assert gw.ALLOWED_OPERATION_IDS == {
            "restart:martin",
            "restart:osrm:walking",
            "restart:osrm:driving",
            "exec:profile_rebuild:extract",
            "exec:profile_rebuild:partition",
            "exec:profile_rebuild:customize",
            "restart:profile",
        }


# ============================================================
# DOP-N: 異常系
# ============================================================


class TestDockerOperationNegative:
    def test_dop_n01_unknown_operation_id_rejected(self, monkeypatch):
        recorder = _SpawnRecorder()
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder)

        with pytest.raises(gw.DockerOperationError) as exc_info:
            asyncio.run(gw.execute_operation("restart:unknown-target", actor_id="a", request_id="r"))
        assert exc_info.value.error_code == "UNKNOWN_OPERATION"
        assert recorder.calls == []

    def test_dop_n02_arbitrary_container_field_rejected_gateway_not_called(self, client, monkeypatch):
        """API入力に任意containerを追加しても4xxで拒否され、gatewayが呼ばれない。"""
        gateway_called = {"n": 0}

        async def _spy(*args, **kwargs):
            gateway_called["n"] += 1
            raise AssertionError("gateway should not be called")

        monkeypatch.setattr(gw, "execute_operation", _spy)

        r = client.post(
            "/api/admin/datasets/test-dataset/fetch-url",
            json={"url": "http://example.invalid/x", "container": "evacuation-navi-martin"},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert gateway_called["n"] == 0

    def test_dop_n03_arbitrary_command_args_field_rejected_gateway_not_called(self, client, monkeypatch):
        gateway_called = {"n": 0}

        async def _spy(*args, **kwargs):
            gateway_called["n"] += 1
            raise AssertionError("gateway should not be called")

        monkeypatch.setattr(gw, "execute_operation", _spy)

        r = client.put(
            "/api/admin/active-mappings/shelter/tokyo",
            json={"dataset_id": "x", "command": "docker", "args": ["restart", "evacuation-navi-martin"]},
            headers=AUTH_HEADERS,
        )
        assert r.status_code == 422
        assert gateway_called["n"] == 0

    def test_dop_n04_osrm_mode_enum_outside_catalog_rejected(self, monkeypatch):
        """OSRM modeはcatalog key（walking/driving）に閉じており、それ以外は
        UNKNOWN_OPERATIONとしてsubprocess 0回で拒否される。"""
        recorder = _SpawnRecorder()
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder)

        with pytest.raises(gw.DockerOperationError) as exc_info:
            asyncio.run(gw.execute_operation("restart:osrm:invalid_mode", actor_id="a", request_id="r"))
        assert exc_info.value.error_code == "UNKNOWN_OPERATION"
        assert recorder.calls == []

    def test_dop_n05_no_shell_true_or_shell_string_in_source(self):
        """静的AST検査: `shell=True` keyword引数・`create_subprocess_shell`呼出し・
        argv内の`["sh","-c",...]`/`["bash","-c",...]`パターンがbackend/app配下の
        実コードに0件であることを確認する（コメント・docstring中の説明文言は
        対象外、実際に実行されるコードのみを見る）。"""
        hits = []
        for path in sorted(APP_DIR.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func_name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
                    if func_name == "create_subprocess_shell":
                        hits.append((str(path), "create_subprocess_shell"))
                    for kw in node.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            hits.append((str(path), "shell=True"))
                if isinstance(node, (ast.List, ast.Tuple)):
                    values = [getattr(el, "value", None) for el in node.elts]
                    for i in range(len(values) - 1):
                        if values[i] in ("sh", "bash") and values[i + 1] == "-c":
                            hits.append((str(path), f"[{values[i]!r}, '-c', ...]"))
        assert hits == [], f"shell=True/shell文字列の使用を検出: {hits}"

    def test_dop_n06_no_docker_subprocess_outside_gateway(self):
        """静的AST検査: docker_operation_gateway.py（allowlist本体）と
        job_manager.py（inspect:self、固定container_idのみ）以外に、
        argvの先頭が"docker"となるsubprocess呼出しが存在しないことを確認する。"""
        allowed_files = {
            APP_DIR / "services" / "docker_operation_gateway.py",
        }
        subprocess_call_names = {
            "run", "Popen", "call", "check_call", "check_output",
            "create_subprocess_exec", "create_subprocess_shell",
        }
        hits = []
        for path in sorted(APP_DIR.rglob("*.py")):
            if path in allowed_files:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                func_name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
                if func_name not in subprocess_call_names:
                    continue
                if not node.args:
                    continue
                first_arg = node.args[0]
                elements = first_arg.elts if isinstance(first_arg, (ast.List, ast.Tuple)) else None
                if not elements:
                    continue
                first_el = elements[0]
                first_val = getattr(first_el, "value", None)
                if first_val == "docker":
                    if path.name == "job_manager.py" and "inspect" in ast.dump(first_arg):
                        # job_manager.py: docker inspect <self-id>のみ許容
                        # （第5.3節row5、inspect:self）。self-idはコード内で
                        # /proc/self/cgroup等から検出した値のみで、外部入力を
                        # 一切受け取らないことはtest_dop_n07で別途確認する。
                        continue
                    hits.append((str(path), ast.dump(first_arg)[:200]))
        assert hits == [], f"gateway外でdocker subprocessを検出: {hits}"

    def test_dop_n07_inspect_self_container_id_not_externally_injectable(self):
        """job_manager._fetch_docker_inspect()の唯一の呼出し元が、
        リクエスト・ジョブパラメータではなく内部検出値
        （_BOOT_STATE["container_id"]、cgroup/hostname由来）だけを渡すことを
        ソース上で確認する。"""
        text = (APP_DIR / "services" / "job_manager.py").read_text(encoding="utf-8")
        call_sites = [
            line for line in text.splitlines() if "_fetch_docker_inspect(" in line and "def " not in line
        ]
        assert call_sites, "呼出し箇所が見つからない"
        for line in call_sites:
            assert "container_id" in line, f"想定外の引数で呼び出されている: {line!r}"
        # container_idローカル変数自体が_BOOT_STATE由来であることも確認する。
        assert 'container_id = _BOOT_STATE.get("container_id")' in text

    def test_dop_n08_timeout_and_nonzero_exit_become_sanitized_failure(self, monkeypatch):
        # timeout
        async def _hang(*a, **k):
            raise AssertionError("communicate should not be reached synchronously in this fake")

        class _HangingProc:
            def __init__(self):
                self.killed = False

            async def communicate(self):
                await asyncio.sleep(999)

            def kill(self):
                self.killed = True

            async def wait(self):
                return 137

        async def _spawn_hanging(*argv, **kwargs):
            return _HangingProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn_hanging)
        monkeypatch.setattr(gw, "DEFAULT_TIMEOUT_SECONDS", 0.05)
        # spec.timeoutはdataclass生成時にDEFAULT_TIMEOUT_SECONDSを束縛済みのため、
        # catalogを直接短縮timeoutへ差し替える。
        import dataclasses

        patched_catalog = {
            k: dataclasses.replace(v, timeout=0.05) for k, v in gw._CATALOG.items()
        }
        monkeypatch.setattr(gw, "_CATALOG", patched_catalog)

        result = asyncio.run(
            gw.execute_operation("restart:martin", actor_id="a", request_id="r")
        )
        assert result.timed_out is True
        assert result.returncode == 124

        # non-zero exit
        recorder = _SpawnRecorder(returncode=137)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder)
        result2 = asyncio.run(
            gw.execute_operation("restart:martin", actor_id="a", request_id="r")
        )
        assert not result2.success
        assert result2.returncode == 137


# ============================================================
# AUD-P: 監査event schema
# ============================================================


class TestAuditPositive:
    def test_aud_p01_auth_success_event_schema(self, client):
        client.get("/api/admin/hazards", headers=AUTH_HEADERS)
        events = _events_of(_read_audit_events(), "operator_auth")
        successes = [e for e in events if e["result"] == "success"]
        assert successes
        e = successes[0]
        assert set(e.keys()) == {"event", "timestamp", "request_id", "actor_id", "result", "reason_code"}
        assert e["actor_id"].startswith("op:")
        assert e["reason_code"] == "OK"

    def test_aud_p02_auth_failure_event_schema(self, client):
        client.get("/api/admin/hazards")
        events = _events_of(_read_audit_events(), "operator_auth")
        failures = [e for e in events if e["result"] == "failure"]
        assert failures
        e = failures[0]
        assert set(e.keys()) == {"event", "timestamp", "request_id", "actor_id", "result", "reason_code"}
        assert e["reason_code"] in operator_audit_log.AUTH_REASON_CODES

    def test_aud_p03_request_accepted_rejected_event_schema(self, client):
        client.get("/api/admin/hazards", headers=AUTH_HEADERS)
        client.get("/api/admin/hazards")
        events = _events_of(_read_audit_events(), "operator_request")
        assert any(e["result"] == "accepted" for e in events)
        assert any(e["result"] == "rejected" for e in events)
        for e in events:
            assert set(e.keys()) == {
                "event", "timestamp", "request_id", "actor_id", "method", "route_id", "result", "status_code",
            }
            assert "?" not in e["route_id"]

    def test_aud_p04_actor_id_request_id_propagated_to_job(self, client, monkeypatch):
        captured = {}

        async def _stub(job, jm):
            captured["actor_id"] = job.actor_id
            captured["request_id"] = job.request_id

        from app.services import pipeline_service

        monkeypatch.setattr(pipeline_service, "run_osrm_profile_rebuild", _stub)

        r = client.post("/api/admin/osrm/rebuild", headers=AUTH_HEADERS)
        assert r.status_code == 200
        assert captured["actor_id"] is not None and captured["actor_id"].startswith("op:")
        assert captured["request_id"] is not None

    def test_aud_p05_docker_operation_success_failure_timeout_event_schema(self, monkeypatch):
        recorder = _SpawnRecorder(returncode=0)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder)
        asyncio.run(gw.execute_operation("restart:martin", actor_id="op:test000000", request_id="req-x"))

        events = _events_of(_read_audit_events(), "operator_docker_operation")
        assert events, "operator_docker_operation eventが記録されていない"
        for e in events:
            assert set(e.keys()) == {
                "event", "timestamp", "request_id", "actor_id", "operation_id", "target_id", "result", "error_code",
            }
        results = {e["result"] for e in events}
        assert "attempting" in results
        assert "success" in results

    def test_aud_p06_inspect_self_event_schema(self, monkeypatch):
        monkeypatch.setattr(
            job_manager_module.subprocess, "run",
            lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="[]", stderr=""),
        )
        job_manager_module._fetch_docker_inspect("deadbeef0000")
        events = _events_of(_read_audit_events(), "operator_internal_inspect")
        assert events
        e = events[-1]
        assert set(e.keys()) == {"event", "timestamp", "actor_id", "operation_id", "result", "error_code"}
        assert e["actor_id"] == "system"
        assert e["operation_id"] == "inspect:self"


# ============================================================
# AUD-N: 秘密canary・fail-closed
# ============================================================


class TestAuditNegative:
    def test_aud_n01_token_canary_zero_hits_in_log_and_response(self, client, tmp_path):
        canary = "OHG2-CANARY-TOKEN-8f2c9e1a"
        r = client.get("/api/admin/hazards", headers={"Authorization": f"Bearer {canary}"})
        assert r.status_code == 401
        assert canary not in r.text
        log_text = operator_audit_log.AUDIT_LOG_PATH.read_text(encoding="utf-8") \
            if operator_audit_log.AUDIT_LOG_PATH.exists() else ""
        assert canary not in log_text

    def test_aud_n02_authorization_cookie_query_body_canary_zero_hits(self, client):
        canary = "OHG2-CANARY-QCB-77aa"
        client.get(f"/api/admin/hazards?token={canary}")
        client.get("/api/admin/hazards", cookies={"t": canary})
        client.post("/api/admin/logs/navigation", json={"message": "x", "canary_field": canary})

        log_text = operator_audit_log.AUDIT_LOG_PATH.read_text(encoding="utf-8") \
            if operator_audit_log.AUDIT_LOG_PATH.exists() else ""
        assert canary not in log_text
        full_auth_header_canary = f"Bearer {canary}"
        assert full_auth_header_canary not in log_text

    def test_aud_n02b_unknown_path_canary_zero_hits_route_id_fixed(self, client):
        """P2B3-CX-002再指摘対応: 未マッチpath自体にcanaryを埋め込んだ場合、
        `operator_request.route_id`が生pathをそのまま記録しないことを確認する
        （固定placeholder "unmatched" を使う設計、operator_audit_middleware.py参照）。"""
        canary = "OHG2-CANARY-UNMATCHED-PATH-55bb"
        r = client.get(f"/{canary}")
        assert r.status_code == 404

        events = _events_of(_read_audit_events(), "operator_request")
        unmatched = [e for e in events if e["route_id"] == "unmatched"]
        assert unmatched, "route未解決requestがoperator_requestとして記録されていない"

        log_text = operator_audit_log.AUDIT_LOG_PATH.read_text(encoding="utf-8") \
            if operator_audit_log.AUDIT_LOG_PATH.exists() else ""
        assert canary not in log_text

    def test_aud_n03_stdout_stderr_exception_canary_zero_hits(self, monkeypatch, tmp_path):
        """P2B3-CX-002再指摘対応: CODEXは「AUD-N03がlog_line未指定でaudit
        fileだけを検索しており、実pipelineのjob log漏洩を検出しない」と
        指摘した。本testは実`JobManager`+`pipeline_service._run_docker_operation()`
        を経由させ、job logファイルもcanary 0 hitであることを直接確認する。"""
        canary = b"OHG2-CANARY-STDOUT-99zz"

        class _NoisyProc:
            returncode = 1

            async def communicate(self):
                return canary, b""

            def kill(self):
                pass

            async def wait(self):
                return 1

        async def _spawn(*argv, **kwargs):
            return _NoisyProc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn)

        from app.models.admin_dataset import JobType
        from app.services import pipeline_service

        jm = job_manager_module.get_job_manager()
        job = jm.create("test-dataset", JobType.deploy, actor_id="op:test000000", request_id="req-y")
        ret = asyncio.run(pipeline_service._run_docker_operation("restart:martin", job, jm))
        assert ret == 1  # nonzero returncode → sanitized failure

        audit_text = operator_audit_log.AUDIT_LOG_PATH.read_text(encoding="utf-8") \
            if operator_audit_log.AUDIT_LOG_PATH.exists() else ""
        assert canary.decode() not in audit_text

        job_log_path = Path(job.log_path)
        job_log_text = job_log_path.read_text(encoding="utf-8") if job_log_path.exists() else ""
        assert canary.decode() not in job_log_text, (
            f"subprocess生stdoutがjob logへ漏洩している: {job_log_text!r}"
        )

    def test_aud_n03b_spawn_exception_text_canary_zero_hits(self, monkeypatch):
        """P2B3-CX-002再指摘対応: subprocess起動失敗時の例外textにcanaryが
        含まれていても、job log／監査logのいずれにも生text化されないことを
        確認する（`DockerOperationError`は固定messageのみを持つ設計）。"""
        canary = "OHG2-CANARY-SPAWNEXC-33cc"

        async def _spawn_raises(*argv, **kwargs):
            raise OSError(f"exec failed: {canary}")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn_raises)

        from app.models.admin_dataset import JobType
        from app.services import pipeline_service

        jm = job_manager_module.get_job_manager()
        job = jm.create("test-dataset", JobType.deploy, actor_id="op:test000000", request_id="req-z")
        ret = asyncio.run(pipeline_service._run_docker_operation("restart:martin", job, jm))
        assert ret == 1

        job_log_path = Path(job.log_path)
        job_log_text = job_log_path.read_text(encoding="utf-8") if job_log_path.exists() else ""
        assert canary not in job_log_text, f"spawn exception textがjob logへ漏洩している: {job_log_text!r}"

        audit_text = operator_audit_log.AUDIT_LOG_PATH.read_text(encoding="utf-8") \
            if operator_audit_log.AUDIT_LOG_PATH.exists() else ""
        assert canary not in audit_text

    def test_aud_n04_pre_exec_audit_failure_blocks_subprocess(self, monkeypatch):
        recorder = _SpawnRecorder()
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder)

        def _raise(*a, **k):
            raise operator_audit_log.AuditSinkError("forced pre-exec failure")

        monkeypatch.setattr(gw, "log_operator_docker_operation", _raise)

        with pytest.raises(gw.DockerOperationError) as exc_info:
            asyncio.run(gw.execute_operation("restart:martin", actor_id="a", request_id="r"))
        assert exc_info.value.error_code == "AUDIT_SINK_UNAVAILABLE"
        assert recorder.calls == [], "pre-exec監査書込失敗時にsubprocessが呼ばれてはならない"

    def test_aud_n05_completion_audit_failure_not_reported_as_success(self, monkeypatch):
        recorder = _SpawnRecorder(returncode=0)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", recorder)

        call_count = {"n": 0}
        real_log = operator_audit_log.log_operator_docker_operation

        def _flaky(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return real_log(*args, **kwargs)  # pre-exec attempt: succeeds
            raise operator_audit_log.AuditSinkError("forced completion failure")

        monkeypatch.setattr(gw, "log_operator_docker_operation", _flaky)

        with pytest.raises(gw.DockerOperationError) as exc_info:
            asyncio.run(gw.execute_operation("restart:martin", actor_id="a", request_id="r"))
        assert exc_info.value.error_code == "AUDIT_SINK_FAILURE_POST_EXEC"
        # subprocess自体は実際に実行された（Docker側は成功した可能性がある）が、
        # 呼出し元へは例外として伝わり、成功と誤認されない。
        assert len(recorder.calls) == 1

    def test_aud_n06_malformed_audit_event_not_treated_as_success(self):
        """JSON化できないfieldを渡すとAuditSinkErrorが送出され、
        黙って成功扱いにならないことを確認する。"""
        with pytest.raises(operator_audit_log.AuditSinkError):
            operator_audit_log._write("operator_auth", {"unserializable": object()})

"""
operator_audit_log.py — Phase 2-B.3 operator構造化監査ログ

tasks/public-release/phase2b3_claude_implementation_instruction.md 第7節。

必須event（固定4種、field構成も固定）:
    operator_auth              : timestamp, request_id, actor_id, result, reason_code
    operator_request            : timestamp, request_id, actor_id, method, route_id, result, status_code
    operator_docker_operation    : timestamp, request_id, actor_id, operation_id, target_id, result, error_code
    operator_internal_inspect    : timestamp, actor_id=system, operation_id=inspect:self, result, error_code

Phase B（OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN）追加event（固定3種、同じ規律）:
    operator_login              : timestamp, request_id, actor_id, result, reason_code
    operator_logout              : timestamp, request_id, actor_id
    operator_shutdown_requested  : timestamp, request_id, actor_id
（stop:operator-gateway / stop:backend-operatorの実行自体は既存の
 operator_docker_operationをそのまま再利用する。新event typeは増やさない。）

設計方針:
    - 各eventにつき専用関数（`log_operator_*`）だけを公開し、汎用`**fields`受け口は
      持たない。呼び出し側が誤って任意fieldを追加できない構造にする（型安全性による
      秘密混入防止）。
    - token, Authorization, cookie, request body, env値, Docker argv, 生stdout/stderr,
      stack traceはいずれの関数の引数にも存在しない（呼べない）。
    - 書込に失敗した場合は例外を握りつぶさず`AuditSinkError`を送出する。呼び出し側
      （operator_auth.py, docker_operation_gateway.py）がこれをfail-closedに使う。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from app.services.admin_metadata_fs import chmod_quiet

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]

# tests/phase2b3_operator_security.py からmonkeypatchしてtmp pathへ差し替える
# ことを想定し、module levelの変数として公開する（環境変数経由の間接化はしない）。
AUDIT_LOG_PATH = _PROJECT_ROOT / "data_lake" / "admin" / "logs" / "operator_audit.log"

_write_lock = Lock()

# 固定result語彙（7.1/7.2節: 「result／reason／errorは固定codeにする」）
AUTH_RESULTS = frozenset({"success", "failure"})
AUTH_REASON_CODES = frozenset(
    {"OK", "MISSING_AUTHORIZATION", "INVALID_SCHEME", "EMPTY_TOKEN", "TOKEN_MISMATCH", "AUDIT_SINK_UNAVAILABLE"}
)
LOGIN_RESULTS = frozenset({"success", "failure"})
LOGIN_REASON_CODES = frozenset({"OK", "EMPTY_TOKEN", "TOKEN_MISMATCH", "AUDIT_SINK_UNAVAILABLE"})
REQUEST_RESULTS = frozenset({"accepted", "rejected"})
DOCKER_OPERATION_RESULTS = frozenset({"attempting", "success", "failure", "timeout"})
DOCKER_OPERATION_ERROR_CODES = frozenset(
    {"UNKNOWN_OPERATION", "SPAWN_FAILED", "NONZERO_EXIT", "TIMEOUT", "AUDIT_SINK_UNAVAILABLE", "AUDIT_SINK_FAILURE_POST_EXEC"}
)
INTERNAL_INSPECT_RESULTS = frozenset({"success", "failure"})


class AuditSinkError(Exception):
    """監査sinkへの書込に失敗した場合に送出する。呼び出し側はこれをfail-closedに扱う。"""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(event: str, record: dict) -> None:
    """JSON 1行を追記する。失敗時は`AuditSinkError`を送出する（握りつぶさない）。

    `json.dumps`自体の失敗（不正な型のfieldが紛れ込んだ場合等）もこの関数内で
    捕捉し`AuditSinkError`へ変換する。呼び出し側の`log_operator_*`関数は固定
    signatureのみを公開しているため、通常はこの経路に到達しない
    （到達した場合はプログラミングエラーであり、握りつぶさずraiseする）。
    """
    try:
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError) as exc:
        logger.error("operator audit event is not JSON-serializable: event=%s error=%s", event, exc)
        raise AuditSinkError(f"non-serializable audit event: {type(exc).__name__}") from exc

    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _write_lock:
            with AUDIT_LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            chmod_quiet(AUDIT_LOG_PATH)
    except OSError as exc:
        logger.error("operator audit sink write failed: event=%s error=%s", event, type(exc).__name__)
        raise AuditSinkError(f"audit sink write failed: {type(exc).__name__}") from exc


def log_operator_auth(*, request_id: str, actor_id: str, result: str, reason_code: str) -> None:
    """認証成功／失敗を記録する（token・Authorization headerの値そのものは含まない）。"""
    if result not in AUTH_RESULTS:
        raise ValueError(f"invalid operator_auth result: {result!r}")
    if reason_code not in AUTH_REASON_CODES:
        raise ValueError(f"invalid operator_auth reason_code: {reason_code!r}")
    _write(
        "operator_auth",
        {
            "event": "operator_auth",
            "timestamp": _utc_now_iso(),
            "request_id": request_id,
            "actor_id": actor_id,
            "result": result,
            "reason_code": reason_code,
        },
    )


def log_operator_request(
    *, request_id: str, actor_id: str, method: str, route_id: str, result: str, status_code: int
) -> None:
    """request受付結果を記録する（route_idはraw URLではなくroute template。query stringは含まない）。"""
    if result not in REQUEST_RESULTS:
        raise ValueError(f"invalid operator_request result: {result!r}")
    _write(
        "operator_request",
        {
            "event": "operator_request",
            "timestamp": _utc_now_iso(),
            "request_id": request_id,
            "actor_id": actor_id,
            "method": method,
            "route_id": route_id,
            "result": result,
            "status_code": int(status_code),
        },
    )


def log_operator_docker_operation(
    *,
    request_id: str,
    actor_id: str,
    operation_id: str,
    target_id: str,
    result: str,
    error_code: Optional[str],
) -> None:
    """Docker operation gatewayの実行結果を記録する（生stdout/stderr/argvは含まない）。"""
    if result not in DOCKER_OPERATION_RESULTS:
        raise ValueError(f"invalid operator_docker_operation result: {result!r}")
    if error_code is not None and error_code not in DOCKER_OPERATION_ERROR_CODES:
        raise ValueError(f"invalid operator_docker_operation error_code: {error_code!r}")
    _write(
        "operator_docker_operation",
        {
            "event": "operator_docker_operation",
            "timestamp": _utc_now_iso(),
            "request_id": request_id,
            "actor_id": actor_id,
            "operation_id": operation_id,
            "target_id": target_id,
            "result": result,
            "error_code": error_code,
        },
    )


def log_operator_login(*, request_id: str, actor_id: str, result: str, reason_code: str) -> None:
    """Web管理画面のlogin試行結果を記録する（供給されたtoken値そのものは含まない）。"""
    if result not in LOGIN_RESULTS:
        raise ValueError(f"invalid operator_login result: {result!r}")
    if reason_code not in LOGIN_REASON_CODES:
        raise ValueError(f"invalid operator_login reason_code: {reason_code!r}")
    _write(
        "operator_login",
        {
            "event": "operator_login",
            "timestamp": _utc_now_iso(),
            "request_id": request_id,
            "actor_id": actor_id,
            "result": result,
            "reason_code": reason_code,
        },
    )


def log_operator_logout(*, request_id: str, actor_id: str) -> None:
    """Web管理画面のlogoutを記録する（session idそのものは含まない）。"""
    _write(
        "operator_logout",
        {
            "event": "operator_logout",
            "timestamp": _utc_now_iso(),
            "request_id": request_id,
            "actor_id": actor_id,
        },
    )


def log_operator_shutdown_requested(*, request_id: str, actor_id: str) -> None:
    """「管理画面を終了」requestが受理されたことを記録する。

    実際のcontainer停止（stop:operator-gateway / stop:backend-operator）は
    既存のlog_operator_docker_operationが別途attempting/success/failure/timeoutを
    記録する。本eventは「shutdown requestそのものが受理された」という、
    どのDocker operationよりも先に必ず1件だけ書けるはずの事実だけを記録する。
    """
    _write(
        "operator_shutdown_requested",
        {
            "event": "operator_shutdown_requested",
            "timestamp": _utc_now_iso(),
            "request_id": request_id,
            "actor_id": actor_id,
        },
    )


def log_operator_internal_inspect(*, result: str, error_code: Optional[str]) -> None:
    """job_manager.py起動時のstale-job cleanupが行う自己`docker inspect`を記録する。

    actor_idは常に固定値"system"、operation_idは常に固定値"inspect:self"。
    外部request由来の値は一切受け取らない（引数として存在しない）。
    """
    if result not in INTERNAL_INSPECT_RESULTS:
        raise ValueError(f"invalid operator_internal_inspect result: {result!r}")
    _write(
        "operator_internal_inspect",
        {
            "event": "operator_internal_inspect",
            "timestamp": _utc_now_iso(),
            "actor_id": "system",
            "operation_id": "inspect:self",
            "result": result,
            "error_code": error_code,
        },
    )

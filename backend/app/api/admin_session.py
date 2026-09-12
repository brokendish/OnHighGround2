"""
admin_session.py — Phase B operator Web管理画面 session認証・shutdown

tasks/OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN Phase B。

`OPERATOR_ROUTERS`（app_operator.py）とは別に登録するrouter。
login自体は必然的に匿名でなければならないため、他routerのような
router単位一括`dependencies=[Depends(require_operator_role)]`は使わず、
route単位で個別dependencyを指定する。
"""
from __future__ import annotations

import asyncio
import secrets
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from app.services.docker_operation_gateway import DockerOperationError, execute_operation
from app.services.operator_audit_log import (
    AuditSinkError,
    log_operator_login,
    log_operator_logout,
    log_operator_shutdown_requested,
)
from app.services.operator_auth import derive_actor_id, get_admin_session, get_operator_secret
from app.services.operator_session import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    Session,
    create_session,
    delete_session,
)

# 内部登録pathは /api/login 等（"admin"は含まない）。外部公開pathは
# operator/nginx.conf が /admin/api/* → /api/* へrewriteして統一する
# （owner方針: 外部から見える operator resource は /admin/* 配下だけに
# 収める。同じrewrite規則で既存の /api/admin/*・/api/simulation/* も
# /admin/api/admin/*・/admin/api/simulation/* として公開する）。
router = APIRouter(prefix="/api", tags=["admin-session"])

# gatewayを停止した後もresponseが確実に配送され終えるための余裕（秒）。
# Starletteのbackground taskはresponse送信完了後に実行される契約だが、
# 途中のproxy(nginx/Caddy)によるbufferingも見込んだ追加の安全マージン。
_SHUTDOWN_DELAY_SECONDS = 1.5

# stop対象は固定2件のみ（docker_operation_gatewayのcatalogと同じ順序:
# 「入口(gateway)を先に落として画面自体を利用不能にし、実処理(backend-operator)
# は最後に自己停止する」）。この順序はここでハードコードし、requestからは
# 一切変更できない。
_SHUTDOWN_OPERATION_SEQUENCE = ("stop:operator-gateway", "stop:backend-operator")


class _LoginBody(BaseModel):
    """login request body。

    owner方針: 認証系routeはPydanticのbody必須検証による422ではなく、
    欠落・不正値も含め常に401（unauthorized）で応答する
    （既存Bearer認証の「raw tokenを一切responseへ含めない・常に401」という
    契約と同じ哲学。既存のtest_auth_n08_no_unprotected_operator_routeが
    全routeへ無認証requestを送り401のみを期待するため、bodyが空でも
    422にならない必要がある）。
    """

    model_config = ConfigDict(extra="forbid")
    token: Optional[str] = None


def _set_session_cookie(response: Response, session: Session) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session.session_id,
        max_age=SESSION_TTL_SECONDS,
        path="/admin",
        secure=True,
        httponly=True,
        samesite="strict",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/admin", secure=True, httponly=True, samesite="strict")


@router.post("/login")
async def login(request: Request) -> JSONResponse:
    """OPERATOR_AUTH_SECRETによるWeb管理画面login。

    唯一の入力はJSON body `{"token": "..."}`。query／form／cookie／headerから
    は受理しない。供給されたtoken値はどのlogへも出力しない。
    """
    request_id = getattr(request.state, "request_id", None) or "unknown"

    raw_body = await request.body()
    try:
        body = _LoginBody.model_validate_json(raw_body) if raw_body else _LoginBody()
    except Exception:  # noqa: BLE001 — 不正なbodyは常にunauthorizedへ丸める
        body = _LoginBody(token=None)

    supplied = body.token

    def _reject(reason_code: str) -> JSONResponse:
        try:
            log_operator_login(request_id=request_id, actor_id="anonymous", result="failure", reason_code=reason_code)
        except AuditSinkError:
            pass
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})

    if not supplied:
        return _reject("EMPTY_TOKEN")

    expected = get_operator_secret()
    if not secrets.compare_digest(supplied, expected):
        return _reject("TOKEN_MISMATCH")

    actor_id = derive_actor_id(supplied)
    session = create_session(actor_id=actor_id)

    try:
        log_operator_login(request_id=request_id, actor_id=actor_id, result="success", reason_code="OK")
    except AuditSinkError:
        # 認証成功の監査書込自体が失敗した場合、既存Bearer認証と同じ方針で
        # sessionを発行せずfail-closedにする。
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    resp = JSONResponse(status_code=200, content={"authenticated": True, "csrf_token": session.csrf_token})
    _set_session_cookie(resp, session)
    return resp


@router.get("/session")
async def session_status(session: Session = Depends(get_admin_session)) -> JSONResponse:
    """reload後のsession状態復元用。有効なsessionが無ければ`get_admin_session`
    dependencyが401を送出する（ここへは到達しない）。"""
    return JSONResponse(status_code=200, content={"authenticated": True, "csrf_token": session.csrf_token})


@router.post("/logout")
async def logout(request: Request, session: Session = Depends(get_admin_session)) -> JSONResponse:
    """現在のsessionを破棄する。CSRF検証は`get_admin_session`が行う
    （POSTのためstate変更method扱い）。"""
    request_id = getattr(request.state, "request_id", None) or "unknown"
    delete_session(session.session_id)
    try:
        log_operator_logout(request_id=request_id, actor_id=session.actor_id)
    except AuditSinkError:
        pass
    resp = JSONResponse(status_code=200, content={"logged_out": True})
    _clear_session_cookie(resp)
    return resp


async def _perform_shutdown(*, request_id: str, actor_id: str) -> None:
    """responseを送信し終えた後（Starlette BackgroundTaskの契約）にのみ実行される。

    順序固定: operator-gateway（入口）を先に停止し、画面自体を利用不能にする。
    backend-operator（実処理・本processが動くcontainer自身）は最後に自己停止する。

    既知の制約: 最後のbackend-operator自己停止は、docker daemonがcontainerを
    畳む過程でこのprocess自体も終了させるため、`stop:backend-operator`の
    post-exec完了監査eventが書き切れない可能性がある（stop要求自体はdaemonが
    受理した時点で実行されるためaction自体は成立する）。これを隠さず、
    成功を偽装するfallbackは実装しない。
    """
    try:
        log_operator_shutdown_requested(request_id=request_id, actor_id=actor_id)
    except AuditSinkError:
        pass

    await asyncio.sleep(_SHUTDOWN_DELAY_SECONDS)

    for operation_id in _SHUTDOWN_OPERATION_SEQUENCE:
        try:
            await execute_operation(operation_id, actor_id=actor_id, request_id=request_id)
        except DockerOperationError:
            # 個別operationの失敗（audit sink障害・spawn失敗等）でも次のtargetの
            # 停止試行は続行する。詳細はoperator_docker_operation監査eventに残る。
            continue


@router.post("/system/shutdown")
async def system_shutdown(
    request: Request,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_admin_session),
) -> JSONResponse:
    """「管理画面を終了」。

    - request bodyからtarget等のparameterは一切受け取らない
      （固定シーケンス`_SHUTDOWN_OPERATION_SEQUENCE`のみ）。
    - HTTP 202を返した後（BackgroundTaskとしてresponse配送完了後に実行される）
      にのみ実際の停止処理へ入る。
    """
    request_id = getattr(request.state, "request_id", None) or "unknown"
    background_tasks.add_task(_perform_shutdown, request_id=request_id, actor_id=session.actor_id)
    return JSONResponse(
        status_code=202,
        content={
            "message": (
                "管理画面を終了しています。再度利用するにはVPS上で "
                "docker compose --profile operator up -d を実行してください。"
            )
        },
    )

"""
operator_auth.py — Phase 2-B.3 operator Bearer認証・認可

tasks/public-release/phase2b3_claude_implementation_instruction.md 第4節。

唯一の認証入力は `Authorization: Bearer <token>` header。query／JSON body／
form／cookie／URL／別headerからは一切token を受理しない（本moduleは
`request.headers.get("authorization")` 以外のいかなる入力源も読まない）。

認証（`get_current_operator`）と認可（`require_operator_role`）を分離する。
現状は単一role（"operator"）しか存在しないため認可段は実運用では素通りするが、
将来のrole追加に備え、かつAUTH-N07（認証済みnon-operator principal → 403）を
HTTP round-tripなしのdependency単体試験として書けるようにするため独立させる。
"""
from __future__ import annotations

import hashlib
import os
import secrets
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request

from app.services.operator_audit_log import AuditSinkError, log_operator_auth
from app.services.operator_session import (
    CSRF_HEADER_NAME,
    SAFE_METHODS,
    SESSION_COOKIE_NAME,
    Session,
    get_session,
)


@dataclass(frozen=True)
class OperatorPrincipal:
    role: str
    actor_id: str


def _get_operator_secret() -> str:
    """OPERATOR_AUTH_SECRETを取得する。値そのものはログへ出力しない。

    app_operator.pyの起動時fail-closed検証（Phase 2-B.1で確定済み）を
    request処理時にも防御的に再確認する。未設定・空白の場合、通常この関数へ
    到達する前にプロセス起動自体が失敗しているはずだが、テストや将来の
    起動シーケンス変更に対する多層防御として例外を送出する。
    """
    secret = os.environ.get("OPERATOR_AUTH_SECRET")
    if secret is None or secret.strip() == "":
        raise RuntimeError("OPERATOR_AUTH_SECRET is not configured")
    return secret


def _derive_actor_id(token: str) -> str:
    """raw tokenを保持せず、一方向fingerprintの短い表示だけをactor_idとする。"""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"op:{digest[:12]}"


def derive_actor_id(token: str) -> str:
    """`_derive_actor_id`の公開alias。Web login（admin_session.py）から
    Bearer認証と同一のactor_id導出規則を再利用するために公開する。"""
    return _derive_actor_id(token)


def get_operator_secret() -> str:
    """`_get_operator_secret`の公開alias。login route（token比較）が使う。"""
    return _get_operator_secret()


async def get_current_operator(request: Request) -> OperatorPrincipal:
    """認証段: `Authorization: Bearer <token>` のみを検証する。

    - headerなし、scheme不正、token空、token不一致はいずれも401
      （`WWW-Authenticate: Bearer` 付き、本文は固定最小schema）。
    - token比較は`secrets.compare_digest`（constant-time）。
    - tokenの前後空白は勝手にtrimしない（別値として受理しない）。
    """
    request_id = getattr(request.state, "request_id", None) or "unknown"
    auth_header = request.headers.get("authorization")

    def _reject(reason_code: str, actor_id: str) -> None:
        try:
            log_operator_auth(request_id=request_id, actor_id=actor_id, result="failure", reason_code=reason_code)
        except AuditSinkError:
            # 監査書込に失敗しても認証拒否そのものは必ず成立させる（fail-closed）。
            pass
        raise HTTPException(
            status_code=401,
            detail="unauthorized",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not auth_header:
        _reject("MISSING_AUTHORIZATION", "anonymous")

    scheme, _, token = auth_header.partition(" ")
    if scheme.lower() != "bearer":
        _reject("INVALID_SCHEME", "anonymous")
    if not token:
        _reject("EMPTY_TOKEN", "invalid")

    expected = _get_operator_secret()
    if not secrets.compare_digest(token, expected):
        _reject("TOKEN_MISMATCH", "invalid")

    actor_id = _derive_actor_id(token)
    request.state.actor_id = actor_id
    try:
        log_operator_auth(request_id=request_id, actor_id=actor_id, result="success", reason_code="OK")
    except AuditSinkError:
        # 認証成功の監査書込自体が失敗した場合も、認証を成立させない（fail-closed）。
        raise HTTPException(status_code=500, detail="internal error")

    return OperatorPrincipal(role="operator", actor_id=actor_id)


def _validate_csrf_or_raise(request: Request, session: Session) -> None:
    """state変更method（POST/PUT/PATCH/DELETE等）に対し、`X-CSRF-Token`
    headerがsession発行時のcsrf_tokenと一致することをconstant-timeで確認する。

    GET/HEAD/OPTIONSはstateを変更しない前提のため対象外とする
    （owner方針。同方針をmutation route側も守る責務を持つ）。
    """
    if request.method in SAFE_METHODS:
        return
    supplied = request.headers.get(CSRF_HEADER_NAME)
    if not supplied or not secrets.compare_digest(supplied, session.csrf_token):
        raise HTTPException(status_code=403, detail="csrf_token_invalid")


async def get_current_operator_or_session(request: Request) -> OperatorPrincipal:
    """既存Bearer認証routerを、session cookieでも通せるように拡張する
    combined dependency。

    優先順位:
      1. `ohg_admin_session` cookieが有効なsessionを指している場合、それを使う
         （state変更methodはCSRF検証も課す）。
      2. cookieが無い、または無効／期限切れの場合は既存の`get_current_operator`
         （Authorization: Bearerのみ）へそのまま委譲する。

    既存のCLI/test/legacy Bearerクライアントの挙動・監査event・401 responseは
    一切変更しない（cookieを一切送らない限り、本関数は`get_current_operator`と
    完全に同一の経路を通る）。
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    session = get_session(session_id) if session_id else None
    if session is not None:
        _validate_csrf_or_raise(request, session)
        request.state.actor_id = session.actor_id
        return OperatorPrincipal(role="operator", actor_id=session.actor_id)
    return await get_current_operator(request)


async def get_admin_session(request: Request) -> Session:
    """Web管理画面専用session dependency（`ohg_admin_session` cookieのみを見る。

    Bearerへはfallbackしない——logout／shutdownはブラウザsessionの概念であり、
    Bearer保有だけでは（sessionを介さず）呼べないようにする設計上の判断
    （defense in depth。Bearer秘密の漏洩単独でshutdownへ到達させない）。
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    session = get_session(session_id)
    if session is None:
        raise HTTPException(status_code=401, detail="unauthorized")
    _validate_csrf_or_raise(request, session)
    return session


def require_operator_role(principal: OperatorPrincipal = Depends(get_current_operator_or_session)) -> OperatorPrincipal:
    """認可段: `role == "operator"` であることを確認する。

    AUTH-N07: 「認証済みだが operator role でない principal」は本番HTTP経路
    からは到達しない（token検証成功時は常にrole="operator"を返すため）。
    このため本関数はdependency単体試験として直接呼び出し、fake principalを
    渡して403となることを確認する（HTTP round-tripは不要）。
    """
    if principal.role != "operator":
        raise HTTPException(status_code=403, detail="forbidden")
    return principal

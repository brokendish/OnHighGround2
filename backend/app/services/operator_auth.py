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


def require_operator_role(principal: OperatorPrincipal = Depends(get_current_operator)) -> OperatorPrincipal:
    """認可段: `role == "operator"` であることを確認する。

    AUTH-N07: 「認証済みだが operator role でない principal」は本番HTTP経路
    からは到達しない（token検証成功時は常にrole="operator"を返すため）。
    このため本関数はdependency単体試験として直接呼び出し、fake principalを
    渡して403となることを確認する（HTTP round-tripは不要）。
    """
    if principal.role != "operator":
        raise HTTPException(status_code=403, detail="forbidden")
    return principal

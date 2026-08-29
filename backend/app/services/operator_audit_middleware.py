"""
operator_audit_middleware.py — Phase 2-B.3 operator `operator_request` event記録

全operator requestに一意な`request_id`を発行し（`request.state.request_id`、
`get_current_operator`が参照する）、認証成功時は`request.state.actor_id`も
併せて記録し、最終的なHTTP status codeとともに`operator_request` eventを
書き込む。routeはraw URL（query string含む）ではなく、Starletteが解決した
route templateを使う。
"""
from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.types import ASGIApp

from app.services.operator_audit_log import AuditSinkError, log_operator_request


class OperatorAuditMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        request.state.request_id = str(uuid.uuid4())

        try:
            response = await call_next(request)
        except Exception:
            self._safe_log(request, status_code=500, result="rejected")
            raise

        status_code = response.status_code
        result = "accepted" if status_code < 400 else "rejected"
        self._safe_log(request, status_code=status_code, result=result)
        return response

    @staticmethod
    def _safe_log(request: Request, *, status_code: int, result: str) -> None:
        actor_id = getattr(request.state, "actor_id", None) or "anonymous"
        request_id = getattr(request.state, "request_id", None) or "unknown"
        route = request.scope.get("route")
        # Phase 2-B.3限定修正（CODEX P2B3-CX-002対応）: route未解決（404等）の
        # 場合、旧実装はrequest.url.path（生のURL path、攻撃者が自由に指定
        # できる文字列）をそのままroute_idへ記録していたため、path自体へ
        # canary／probe文字列を含めるとaudit JSONLへ生の形で残ってしまって
        # いた。route template（固定route ID）が存在する場合のみそれを使い、
        # 存在しない場合は常に固定placeholder "unmatched" を使う
        # （query stringはいずれの経路でも含まれない）。
        route_id = getattr(route, "path", None) if route is not None else "unmatched"
        try:
            log_operator_request(
                request_id=request_id,
                actor_id=actor_id,
                method=request.method,
                route_id=route_id,
                result=result,
                status_code=status_code,
            )
        except AuditSinkError:
            # request-level監査の書込失敗はresponseそのものを止めない
            # （Docker操作の事前監査とは異なり、ここは「受付結果の記録」であり
            # 操作の実行可否そのものをこの一線に依存させると可用性が過度に
            # 脆くなるため）。事前のDocker操作gatewayはこれとは別に
            # fail-closedを行う（docker_operation_gateway.py参照）。
            pass

"""
避難ナビゲーションAPI — operator entrypoint (Phase 2-B.1 / Phase 2-B.3)

これは operator trust boundary 専用の独立した FastAPI エントリポイントである。
admin / admin_config / admin_datasets / admin_upload / simulation / layer_types
（/api/admin プレフィクスの管理用マッピングAPI）の各routerのみを登録する。

public entrypoint（backend/app_public.py）をimportしてrouterを追加する方式は
禁止されている（tasks/public-release/github_public_audit_phase2a_remediation_plan.md
第5.1節）。このモジュールは app_public を一切importしない。

OPERATOR_AUTH_SECRET が未設定・空文字・空白のみの場合は、起動そのものを
非0終了でfail-closedにする（Phase 2-B.1の完了条件、本ファイルでも維持）。

Phase 2-B.3: 全operator routerへ`require_operator_role`（Bearer認証＋認可）を
app.include_router()のdependencies=[]で一括適用する（route単位のdecorator
列挙に依存しない、付け忘れを構造的に防ぐ）。`/operator/health`のみ匿名可の
最小livenessとして例外扱いする（本ファイル内で直接定義、OPERATOR_ROUTERSには
含まれない）。`OperatorAuditMiddleware`で全requestにrequest_idを発行し、
`operator_request`監査eventを記録する。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fastapi import Depends, FastAPI

from app.api.admin import router as admin_router
from app.api.admin_config import router as admin_config_router
from app.api.admin_datasets import router as admin_datasets_router
from app.api.admin_datasets import jobs_router as admin_jobs_router
from app.api.admin_upload import router as admin_upload_router
from app.api.layer_types_api import router as layer_types_router
from app.api.simulation import router as simulation_router
from app.services.job_manager import get_job_manager
from app.services.admin_log_service import write_app_log
from app.services.operator_audit_middleware import OperatorAuditMiddleware
from app.services.operator_auth import require_operator_role

BASE_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=os.getenv("OPERATOR_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def _validate_operator_auth_secret() -> str:
    """OPERATOR_AUTH_SECRET が実質的に設定されていることを検証する。

    未設定・空文字・空白のみの場合はプロセスをexit code 1で終了させる
    （fail-closed。public appへのフォールバックや黙示的な機能縮退はしない）。
    値そのものはログへ出力しない。
    """
    secret = os.environ.get("OPERATOR_AUTH_SECRET")
    if secret is None or secret.strip() == "":
        logger.error(
            "OPERATOR_AUTH_SECRET is not set (or is empty/whitespace-only). "
            "operator entrypoint refuses to start (fail-closed). "
            "Set OPERATOR_AUTH_SECRET in .env.operator before starting backend-operator."
        )
        sys.exit(1)
    return secret


# 起動時fail-closedチェック（モジュールimport時に実行される）。
# 秘密の値そのものは以後どこにも保持・ログ出力しない
# （Bearer認証本体の実装はPhase 2-B.3のスコープ）。
_validate_operator_auth_secret()


# FastAPIアプリケーション初期化（public appとは完全に独立したインスタンス）
#
# Phase 2-B.3限定修正（CODEX P2B3-CX-001対応）: FastAPI既定のdocs系route
# （/docs, /redoc, /openapi.json, /docs/oauth2-redirect）は、include_router()の
# dependencies=[]では保護されずapp自体が無条件登録するため、Bearer認証なしで
# 到達可能なまま残っていた。openapi.jsonは管理route inventoryそのものを
# 匿名で返してしまうため、docs_url/redoc_url/openapi_url をすべてNoneにして
# 生成自体を無効化する（`/operator/health`以外の匿名到達可能routeを0件にする、
# 第4.3節の「例外はこの1 routeだけに固定」という要件を文字通り満たす）。
app = FastAPI(
    title="避難ナビゲーションAPI (operator)",
    description="operator専用の管理・シミュレーションAPI。public entrypointとは別entrypoint・別imageで提供する。",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    # operator UIは別途 operator/frontend-admin/ から配信する計画（Phase 2-B.4）。
)

# Phase 2-B.3: 全operator requestにrequest_idを発行し、operator_request監査
# eventを記録するmiddleware。認証dependency（get_current_operator）は
# request.state.request_idを参照するため、必ずrouting/dependency解決より
# 外側で先にrequest_idを確定させる必要がある（add_middlewareが先）。
app.add_middleware(OperatorAuditMiddleware)

# operator専用routerのみを登録する。public routerは一切importしない。
# 各routerへdependencies=[Depends(require_operator_role)]をapp.include_router()
# 単位で一括適用する。route個別のdecorator列挙に依存しないため、新規route
# 追加時の認証付け忘れが構造的に起こらない（第4.3節）。
OPERATOR_ROUTERS = [
    admin_router,
    admin_config_router,
    admin_datasets_router,
    admin_jobs_router,
    admin_upload_router,
    layer_types_router,
    simulation_router,
]
for _router in OPERATOR_ROUTERS:
    app.include_router(_router, dependencies=[Depends(require_operator_role)])


@app.on_event("startup")
async def _startup():
    """起動時: stale job cleanup（docker inspect を内部で伴う）。

    public entrypointではこの処理を行わない（Docker操作をpublic import graphへ
    持ち込まないため）。operator entrypointに一本化する。
    """
    try:
        write_app_log("backend-operator startup")
    except Exception:
        pass
    get_job_manager().cleanup_stale_running()


@app.on_event("shutdown")
async def _shutdown():
    try:
        write_app_log("backend-operator shutdown", level="WARNING")
    except Exception:
        pass


@app.get("/operator/health")
async def operator_health():
    """operator entrypoint自体の最小ヘルスチェック（public /health とは別）。"""
    return {"status": "ok", "role": "operator"}


if __name__ == "__main__":
    import uvicorn

    operator_host = os.getenv("OPERATOR_LISTEN_HOST", "0.0.0.0")
    try:
        operator_port = int(os.getenv("OPERATOR_PORT", "8100"))
    except ValueError:
        operator_port = 8100

    logger.info("operator entrypoint starting: host=%s port=%s", operator_host, operator_port)
    # Phase 2-B.3限定修正（CODEX P2B3-CX-002対応）: access logはraw path・query
    # stringを含むため無効化する（Dockerfile.operatorのCMDと同じ方針）。
    uvicorn.run("app_operator:app", host=operator_host, port=operator_port, access_log=False)

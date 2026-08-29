"""
main.py — public-only compatibility shim (Phase 2-B.1)

このファイルは既存の起動経路（`Dockerfile` の `CMD ["uvicorn", "main:app", ...]`、
README/QUICKSTART の `python main.py`、開発用ホットリロード等）を変更せずに
維持するための薄い互換シムである。

実体は backend/app_public.py に分離されている。このシムは app_public から
`app` を re-export するだけであり、operator専用モジュール
（app.api.admin*, app.api.simulation, app.api.layer_types_api,
app.services.pipeline_service, app.services.job_manager 等）は
一切importしない。

管理機能・Docker操作を伴うoperator機能は backend/app_operator.py が別途提供する
（tasks/public-release/github_public_audit_phase2a_remediation_plan.md 第5.1節）。
"""
from app_public import app  # noqa: F401  (re-export for `uvicorn main:app`)

if __name__ == "__main__":
    from app_public import (
        API_HOST,
        API_LOG_LEVEL,
        API_PORT,
        API_RELOAD,
        BASE_DIR,
        logger,
    )
    import uvicorn

    logger.info(
        "uvicorn config: host=%s port=%s reload=%s log_level=%s",
        API_HOST, API_PORT, API_RELOAD, API_LOG_LEVEL,
    )

    uvicorn_kwargs: dict = dict(
        host=API_HOST,
        port=API_PORT,
        reload=API_RELOAD,
        log_level=API_LOG_LEVEL,
    )

    if API_RELOAD:
        # reload=true の場合、監視対象をアプリソースのみに限定する。
        # data_lake/, data_runtime/ の書き換えによる意図しない再起動を防ぐ。
        uvicorn_kwargs["reload_dirs"] = [str(BASE_DIR / "app")]
        uvicorn_kwargs["reload_excludes"] = [
            "**/data_lake/**",
            "**/data_runtime/**",
            "**/*.json",
            "**/*.log",
            "**/*.geojson",
            "**/*.geojsonl",
            "**/*.tmp.*",
            "**/*.mbtiles",
            "**/*.tif",
            "**/*.pbf",
        ]

    uvicorn.run("app_public:app", **uvicorn_kwargs)

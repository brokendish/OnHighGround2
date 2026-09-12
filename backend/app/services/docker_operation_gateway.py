"""
docker_operation_gateway.py — Phase 2-B.3 Docker operation allowlist gateway

tasks/public-release/phase2b3_claude_implementation_instruction.md 第5節。

Docker実行を1つのoperator専用gatewayへ集約する。API入力からcontainer名・
Docker verb・command・argv・shell文字列を一切受け取らない。9種の
operation_idだけがコード内固定catalogから解決され、それぞれ固定verb・固定
target container・固定argv templateへ一意に対応する。allowlistにない
operationはdefault branchで実行できない構造（catalogに存在しないkeyは
即座にDockerOperationErrorとなり、subprocessは1つも起動されない）。

Phase B（OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN）で`stop:operator-gateway`・
`stop:backend-operator`の2件を追加した（元7種）。対象はoperator profileの
2 containerに固定。

`asyncio.create_subprocess_exec`（shell=False）でのみ起動する。
`shell=True`・shell文字列・`sh -c`・`bash -c`は使用しない（DOP-N05で
静的検査する）。

Docker実行直前に監査sinkへ"attempting" eventを書けない場合はfail-closedで
実行しない。実行後の完了event書込に失敗した場合も、成功を偽装せず
`DockerOperationError(error_code="AUDIT_SINK_FAILURE_POST_EXEC")`を送出する
（呼び出し側=pipeline_service.pyがこれをjob失敗として扱う）。
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from app.services.operator_audit_log import AuditSinkError, log_operator_docker_operation

_MARTIN_CONTAINER = "evacuation-navi-martin"
_OSRM_CONTAINER_NAMES = {
    "walking": "evacuation-navi-osrm-walking",
    "driving": "evacuation-navi-osrm-driving",
}
_PROFILE_CONTAINER = "evacuation-navi-osrm-walking"
_OPERATOR_GATEWAY_CONTAINER = "evacuation-navi-operator-gateway"
_BACKEND_OPERATOR_CONTAINER = "evacuation-navi-backend-operator"
_PROFILE_PBF = "/data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf"
_PROFILE_OSRM = _PROFILE_PBF.replace(".osm.pbf", ".osrm")

DEFAULT_TIMEOUT_SECONDS = 120


@dataclass(frozen=True)
class _OperationSpec:
    argv: Tuple[str, ...]
    target_id: str
    timeout: int = DEFAULT_TIMEOUT_SECONDS


# ── 固定catalog（第5.1節: この7種以外のoperation_idは一切解決されない） ──────
_CATALOG: dict[str, _OperationSpec] = {
    "restart:martin": _OperationSpec(
        argv=("docker", "restart", _MARTIN_CONTAINER),
        target_id=_MARTIN_CONTAINER,
    ),
    "restart:osrm:walking": _OperationSpec(
        argv=("docker", "restart", _OSRM_CONTAINER_NAMES["walking"]),
        target_id=_OSRM_CONTAINER_NAMES["walking"],
    ),
    "restart:osrm:driving": _OperationSpec(
        argv=("docker", "restart", _OSRM_CONTAINER_NAMES["driving"]),
        target_id=_OSRM_CONTAINER_NAMES["driving"],
    ),
    "exec:profile_rebuild:extract": _OperationSpec(
        argv=("docker", "exec", _PROFILE_CONTAINER, "osrm-extract", "--threads", "2", "-p", "/opt/foot.lua", _PROFILE_PBF),
        target_id=_PROFILE_CONTAINER,
        timeout=3600,
    ),
    "exec:profile_rebuild:partition": _OperationSpec(
        argv=("docker", "exec", _PROFILE_CONTAINER, "osrm-partition", "--threads", "2", _PROFILE_OSRM),
        target_id=_PROFILE_CONTAINER,
        timeout=3600,
    ),
    "exec:profile_rebuild:customize": _OperationSpec(
        argv=("docker", "exec", _PROFILE_CONTAINER, "osrm-customize", "--threads", "2", _PROFILE_OSRM),
        target_id=_PROFILE_CONTAINER,
        timeout=3600,
    ),
    "restart:profile": _OperationSpec(
        argv=("docker", "restart", _PROFILE_CONTAINER),
        target_id=_PROFILE_CONTAINER,
    ),
    # OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN Phase B: 管理画面「終了」機能。
    # 対象は固定2 containerのみ（operator profile限定）。backend-public /
    # frontend / martin / osrm-walking / runtime-init はcatalogに一切存在せず、
    # 構造的に対象にできない。呼出し順序（gateway→backend-operator）は
    # app_operator.py側のbackground taskが保証する（本file自体は順序を
    # 強制しない、単一操作の実行gatewayに徹する）。
    "stop:operator-gateway": _OperationSpec(
        argv=("docker", "stop", _OPERATOR_GATEWAY_CONTAINER),
        target_id=_OPERATOR_GATEWAY_CONTAINER,
    ),
    "stop:backend-operator": _OperationSpec(
        argv=("docker", "stop", _BACKEND_OPERATOR_CONTAINER),
        target_id=_BACKEND_OPERATOR_CONTAINER,
    ),
}

ALLOWED_OPERATION_IDS = frozenset(_CATALOG.keys())
assert len(ALLOWED_OPERATION_IDS) == 9, f"operation catalog must have exactly 9 entries, has {len(ALLOWED_OPERATION_IDS)}"


class DockerOperationError(Exception):
    """gateway呼出しの失敗（catalog未知operation・spawn失敗・監査sink障害等）。"""

    def __init__(self, error_code: str, message: str = "") -> None:
        self.error_code = error_code
        super().__init__(message or error_code)


class DockerOperationResult:
    __slots__ = ("returncode", "timed_out")

    def __init__(self, returncode: int, timed_out: bool) -> None:
        self.returncode = returncode
        self.timed_out = timed_out

    @property
    def success(self) -> bool:
        return not self.timed_out and self.returncode == 0


def _record(
    *, request_id: str, actor_id: str, operation_id: str, target_id: str, result: str, error_code: Optional[str]
) -> None:
    log_operator_docker_operation(
        request_id=request_id,
        actor_id=actor_id,
        operation_id=operation_id,
        target_id=target_id,
        result=result,
        error_code=error_code,
    )


async def execute_operation(
    operation_id: str,
    *,
    actor_id: str,
    request_id: str,
    log_line: Optional[Callable[[str], None]] = None,
) -> DockerOperationResult:
    """固定catalogの1 operationだけをshell=Falseで実行する。

    - operation_idがcatalogに存在しない場合、subprocessは1つも起動されず
      `DockerOperationError("UNKNOWN_OPERATION")`を送出する。
    - `log_line`は既存のjob log（`jm.log(job, ...)`）へ進捗を流すための任意
      コールバック。Phase 2-B.3限定修正（CODEX P2B3-CX-002対応）:
      当初はsubprocessの生stdout/stderr（mergeされたもの）をそのまま
      `log_line`へ転送しており、独立canary検証でjob logへの生出力漏洩が
      実際に再現された。job logも含め、どの経路にも生stdout/stderr・生
      exception textを一切書かない設計へ変更した。`log_line`には固定
      operation_id・固定進捗文・固定return codeだけを渡す
      （argv自体はcatalog固定値でrequest入力を含まないため、実行前の
      コマンド表示のみは安全上問題なく維持する）。
    """
    if operation_id not in _CATALOG:
        raise DockerOperationError("UNKNOWN_OPERATION", "unknown operation_id")

    spec = _CATALOG[operation_id]

    try:
        _record(
            request_id=request_id, actor_id=actor_id, operation_id=operation_id,
            target_id=spec.target_id, result="attempting", error_code=None,
        )
    except AuditSinkError as exc:
        raise DockerOperationError("AUDIT_SINK_UNAVAILABLE", "pre-exec audit write failed") from exc

    if log_line:
        # argvはcatalog固定値のみ（request入力を含まない）のため表示して安全。
        log_line(f"$ {' '.join(spec.argv)}")

    try:
        proc = await asyncio.create_subprocess_exec(
            *spec.argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except Exception:  # noqa: BLE001
        _record(
            request_id=request_id, actor_id=actor_id, operation_id=operation_id,
            target_id=spec.target_id, result="failure", error_code="SPAWN_FAILED",
        )
        if log_line:
            log_line(f"[ERROR] operation {operation_id} failed to start")
        raise DockerOperationError("SPAWN_FAILED", "subprocess spawn failed")

    try:
        _, _ = await asyncio.wait_for(proc.communicate(), timeout=spec.timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        if log_line:
            log_line(f"[ERROR] operation {operation_id} timed out after {spec.timeout}s")
        _record(
            request_id=request_id, actor_id=actor_id, operation_id=operation_id,
            target_id=spec.target_id, result="timeout", error_code="TIMEOUT",
        )
        return DockerOperationResult(returncode=124, timed_out=True)

    result = "success" if proc.returncode == 0 else "failure"
    error_code = None if proc.returncode == 0 else "NONZERO_EXIT"

    if log_line:
        log_line(f"operation {operation_id} completed: result={result} exit_code={proc.returncode}")

    try:
        _record(
            request_id=request_id, actor_id=actor_id, operation_id=operation_id,
            target_id=spec.target_id, result=result, error_code=error_code,
        )
    except AuditSinkError:
        # 実行後の完了event記録に失敗した: 操作(Docker側)は既に完了している
        # 可能性があるが、それを「監査上確認できた成功」として扱わない
        # （7.2節「Docker実行後のcompletion event記録失敗は操作済みの可能性を
        # 隠さず、jobを成功扱いにせず監査障害として明示する」）。
        raise DockerOperationError("AUDIT_SINK_FAILURE_POST_EXEC", "completion audit write failed")

    return DockerOperationResult(returncode=proc.returncode, timed_out=False)

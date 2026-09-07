"""
runtime_version_access.py — Phase 2-B.5 public backend向けlease-protected読み取りhelper。

tasks/public-release/phase2b5_claude_implementation_instruction.md 第6.3節、第8節。

public appが`/data_runtime`配下のatomic-publish対象datasetを読む際、
「lease取得 → fixed version root配下を読む → response送信完了までlease保持
→ release」を単一のasync generatorへ集約する。FastAPIの`StreamingResponse`
と組み合わせることで、既存のstreaming配信（メモリ全展開回避）を維持した
まま、読み取り中にGCが対象versionを削除しないことをlease機構で保証する。

対象はdeploy_to_runtime.shが実際に発行するdataset
（backend/elevation, backend/hazard, backend/shelters,
frontend/layers, frontend/tiles）に限定する。data_runtime配下でも
tide/weather/jartic等のlive-polling運用データや、logs/cache/simulation/
uploads/system等の運用状態は対象外（第8節データconsumer inventory参照）。
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import AsyncIterator, Optional

from .runtime_atomic import RuntimeAtomicError, verify_path_owner_mode
from .runtime_lease import LeaseCoordinator, LeaseError
from .runtime_publish import VERSION_FILE_MODE

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 262144  # 256 KiB

DATA_RUNTIME_ROOT = Path(os.environ.get("OHG2_DATA_RUNTIME_ROOT", "/data_runtime"))
LEASES_ROOT = Path(os.environ.get("OHG2_LEASES_ROOT", "/run/onhighground2/leases"))
LEASE_TTL_S = float(os.environ.get("OHG2_LEASE_TTL_SECONDS", "30"))
# CODEX P2B5-CX-005対応: streaming中の読み取りがTTLを超える場合に備え、
# TTLの半分を経過した時点でrenewする（renew intervalの明示値）。
_RENEW_AFTER_S = LEASE_TTL_S / 2.0

_PUBLIC_UID = 10001
_PUBLIC_GID = 10001
# CODEX P2B5-CX-007（第2ラウンド）対応: coordination.lock等の共有lease
# infrastructureは常にoperator uid・leases supplemental gidで所有される
# （scripts/publish/init_lease_volume.pyが作成時に確定する値）。publicの
# 自分自身のuid/gidとは無関係に、この値でowner/modeを検証する。
_LEASES_OWNER_UID = int(os.environ.get("OHG2_LEASES_OWNER_UID", "10002"))
_LEASES_GID = int(os.environ.get("OHG2_LEASES_GID", "20001"))

# CODEX P2B5-CX-007（第7ラウンド）対応: data_runtime root自体、および
# published version directory自体（`versions/<id>/`）は、従来
# application-levelのownership検証対象外だった。個別配信fileは
# `_verify_served_file_ownership()`で検証していたが、rootとversion
# directoryはOS-levelのtraverse/read権限だけに依存しており、owner
# だけを誤設定してもgroup経由のtraverseが黙って成功していた
# （独立検証: `data_runtime root single-mutation`でowner改ざん後も
# publicのcurrent symlink経由readが成功することを実証、
# `version-dir-owner-mutated SUCCESS`として同種の欠落をversion
# directoryでも確認）。deploy_to_runtime_atomic.sh／init_lease_volume.py
# が実際に確立する値（operator_uid:leases_gid、rootは0750、公開済み
# version directoryも0750）と厳密一致することを要求し、逸脱時は
# fail-closedで拒否する。
_DATA_RUNTIME_ROOT_MODE = 0o750
_VERSION_DIR_MODE = 0o750


def _verify_data_runtime_root_ownership() -> None:
    try:
        verify_path_owner_mode(DATA_RUNTIME_ROOT, _LEASES_OWNER_UID, _LEASES_GID, _DATA_RUNTIME_ROOT_MODE)
    except RuntimeAtomicError as exc:
        raise LeaseError(f"data_runtime root自体のowner/mode検証に失敗（改ざん/誤設定の疑い）: {exc}") from exc


def _verify_version_root_ownership(version_root: Path) -> None:
    try:
        verify_path_owner_mode(version_root, _LEASES_OWNER_UID, _LEASES_GID, _VERSION_DIR_MODE)
    except RuntimeAtomicError as exc:
        raise LeaseError(
            f"published version directory自体のowner/mode検証に失敗（改ざん/誤設定の疑い）: {exc}"
        ) from exc


_coordinator: Optional[LeaseCoordinator] = None


def get_coordinator() -> LeaseCoordinator:
    global _coordinator
    if _coordinator is None:
        _coordinator = LeaseCoordinator(
            LEASES_ROOT, uid=_PUBLIC_UID, gid=_PUBLIC_GID,
            lease_ttl_s=LEASE_TTL_S,
            expect_owner_gid=_LEASES_GID,
            leases_owner_uid=_LEASES_OWNER_UID,
        )
    return _coordinator


def _verify_served_file_ownership(file_path: Path) -> None:
    """CODEX P2B5-CX-007（第5ラウンド）対応: 従来、公開済みfileの実際の
    owner/group/modeは一切検証せずそのままstreamingしていた（独立検証で
    「published data fileのowner誤設定後もpublic read成功」がPASSとして
    許容されてしまう不備を指摘された）。deploy_to_runtime_atomic.shが
    生成するfileは常にoperator_uid:leases_gid・mode 0640（VERSION_FILE_MODE）
    であるはずであり、これと厳密に一致しない場合はfail-closedで拒否する
    （OS-level permission bitが偶然readを許してしまう場合でも、
    application-levelで数値ownershipの逸脱を検出する）。"""
    try:
        verify_path_owner_mode(file_path, _LEASES_OWNER_UID, _LEASES_GID, VERSION_FILE_MODE)
    except RuntimeAtomicError as exc:
        raise LeaseError(f"配信対象fileのowner/mode検証に失敗（改ざん/誤設定の疑い）: {exc}") from exc


def is_available() -> bool:
    """atomic publish/lease coordination機構がそもそも導入・初期化されて
    いる環境かどうかを返す（本phase未適用のcompose等では呼び出し側が
    legacy path解決へfallbackできるようにするための事前ゲート）。

    CODEX P2B5-CX-004（第3ラウンド）対応: 旧実装は`current`symlinkが
    「今この瞬間」有効かどうかも条件に含んでいた。これにより、
    coordination.lockが存在する＝一度は正しく初期化された環境でも、
    後からcurrentが消失・破損すると本関数がFalseを返し、呼び出し元
    （hazards.py）はこれを「未初期化」と誤解してlegacy pathへ静かに
    fallbackしていた（独立検証で
    INITIALIZED_TREE_MISSING_CURRENT_RETURNED_NONE=Trueとして再現）。
    「導入済みかどうか」はcoordination.lockの存在（runtime-initが
    一度でも実行された証跡）だけで判定し、currentの現在の状態は
    acquire_current()側のLeaseErrorとしてfail-closedに扱う。
    """
    return (LEASES_ROOT / "coordination.lock").exists()


async def stream_versioned_file(relative_path: str, request_kind: str) -> AsyncIterator[bytes]:
    """`data_runtime/current/<relative_path>` をlease保護下でstreamingする。

    呼び出し側は `StreamingResponse(stream_versioned_file(...), media_type=...)`
    として使う。responseがconsumerへ送信完了する（generatorがexhaustする）まで
    leaseを保持し、finallyで確実にreleaseする。

    CODEX P2B5-CX-001対応: currentの解決を`acquire_current()`内部の
    global shared critical sectionで行い、readlinkとacquireの間にGCが
    割り込むTOCTOUを排除する（このfunction単体ではreadlinkしない）。
    """
    _verify_data_runtime_root_ownership()
    coordinator = get_coordinator()
    handle = coordinator.acquire_current(DATA_RUNTIME_ROOT, request_kind)
    try:
        version_root = DATA_RUNTIME_ROOT / "versions" / handle.payload.version_id
        _verify_version_root_ownership(version_root)
        file_path = (version_root / relative_path).resolve()
        if version_root.resolve() not in file_path.parents and file_path != version_root.resolve():
            raise LeaseError(f"root境界外へのpath: {file_path}")
        if not file_path.is_file():
            raise FileNotFoundError(str(file_path))
        _verify_served_file_ownership(file_path)
        last_renew = time.monotonic()
        with open(file_path, "rb") as f:
            while True:
                chunk = f.read(_CHUNK_SIZE)
                if not chunk:
                    break
                if time.monotonic() - last_renew > _RENEW_AFTER_S:
                    handle = coordinator.renew(handle)
                    last_renew = time.monotonic()
                yield chunk
    finally:
        coordinator.release(handle)


async def stream_versioned_glob(
    subdir_relative: str, patterns: list, request_kind: str, region: Optional[str] = None
) -> Optional[AsyncIterator[bytes]]:
    """`data_runtime/current/<subdir_relative>` 配下でpatternsに一致する
    ファイルをsize降順で1件選び、lease保護下でstreamingするasync generatorを
    返す。一致0件・currentやlease機構が未初期化の場合はNoneを返し、
    呼び出し側がdata_lake等のlegacy pathへfallbackできるようにする。

    lease取得はglob（対象探索）より先に行う。glob後にleaseを取得すると、
    「対象file選定」と「lease保護開始」の間にGCが該当versionを削除しうる
    競合window（TOCTOU）が生じるため、必ずleaseを先に取ってversionを
    確定的に保護してから探索する。currentの解決自体も`acquire_current()`
    のglobal shared critical section内で行う（P2B5-CX-001対応）。

    CODEX P2B5-CX-004（第3ラウンド）対応: 旧実装は`current`が
    symlinkでない場合を一律「未初期化」とみなしNoneを返していた。しかし
    coordination.lockが既に存在する（＝leases infrastructure自体は
    初期化済み）状態でcurrentだけが消失している場合は「未初期化」ではなく
    **真の整合性異常**（current破損・削除攻撃等）であり、独立検証で
    `INITIALIZED_TREE_MISSING_CURRENT_RETURNED_NONE=True`として
    fail-openが再現された。「未初期化」と判定してよいのは、leases
    coordination volume自体がそもそも用意されていない場合（coordination.lock
    不在）だけに限定し、それ以外はcurrentの状態に関わらず
    `acquire_current()`を呼び出して真の異常をLeaseErrorとして伝播させる
    （`except LeaseError: return None`は使わない、第2ラウンドで確立した
    方針をここでも一貫させる）。

    RUNTIME-VERSION-STREAM-REGION-LAYOUT-GAP対応（Phase B0）: Dual Storage
    Remediation Phase C1で確立された実際のruntime layoutは
    `<subdir_relative>/<region>/<file>`というregion配下directory構成
    （例: `backend/hazard/inland_flood/tokyo/tokyo-urban-001.geojson`）だが、
    本関数は従来`<subdir_relative>`直下をpatternsで非再帰globしていたため
    一段浅く、region配下directoryへ到達できず常にNoneを返していた
    （実機のcontent-length/last-modified/etagヘッダーにより、inland_flood/
    landslideが従来の設計意図に反し、常にFileResponse＝flat fallback経由で
    配信されていたことを実証済み。current/versioned優先・lease保護
    streamingという意図が実質的にdead code化していた）。

    `region`が指定された場合、まず`<subdir_relative>/<region>/`を非再帰で
    `*.geojson`検索する（region directory自体がregion/typeのscopingを
    担うため、patternsによるprefix/suffixフィルタは不要——このsize最大
    tie-break選択は`HazardDatasetService._resolve_current_hazard_file()`の
    region_subdir分岐と同一の既存selector contractを踏襲したもので、新規に
    導入したものではない）。一致すればそれを正本として使う。一致しない
    場合（region配下directoryが存在しない、または空）は、従来通り
    `<subdir_relative>`直下を`patterns`で検索するlegacy direct-child glob
    へfallbackする。`region`省略時は従来の挙動と完全に同一。

    無制限recursive glob（`**/*.geojson`）は使わない——wrong region /
    backup / legacy / 無関係datasetを誤って拾う可能性があるため、常に
    単一のexact directoryをnon-recursiveでglobする。
    """
    coordinator = get_coordinator()
    if not (LEASES_ROOT / "coordination.lock").exists():
        return None
    _verify_data_runtime_root_ownership()
    handle = coordinator.acquire_current(DATA_RUNTIME_ROOT, request_kind)
    version_root = DATA_RUNTIME_ROOT / "versions" / handle.payload.version_id
    try:
        _verify_version_root_ownership(version_root)
        matches = []
        if region is not None:
            region_dir = version_root / subdir_relative / region
            if region_dir.is_dir():
                matches.extend(region_dir.glob("*.geojson"))
        if not matches:
            subdir = version_root / subdir_relative
            if subdir.is_dir():
                for pattern in patterns:
                    matches.extend(subdir.glob(pattern))
    except BaseException:
        # 検証failure等でgeneratorへ移行できない場合、ここでleaseを
        # 確実に解放する（以降の正常系はgeneratorのfinallyが解放を担う）。
        coordinator.release(handle)
        raise
    if not matches:
        coordinator.release(handle)
        return None
    chosen_rel = str(max(matches, key=lambda p: p.stat().st_size).relative_to(version_root))

    async def _gen() -> AsyncIterator[bytes]:
        nonlocal handle
        try:
            file_path = version_root / chosen_rel
            _verify_served_file_ownership(file_path)
            last_renew = time.monotonic()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    if time.monotonic() - last_renew > _RENEW_AFTER_S:
                        handle = coordinator.renew(handle)
                        last_renew = time.monotonic()
                    yield chunk
        finally:
            coordinator.release(handle)

    return _gen()


def resolve_versioned_path_sync(relative_path: str) -> Optional[Path]:
    """短時間read-only操作（存在確認等）専用の同期ヘルパー。streamingを伴う
    responseには stream_versioned_file を使うこと（leaseの保持期間が
    file読み取り全体をカバーしないため、大きなfileの配信には使わない）。

    CODEX P2B5-CX-004（第3ラウンド）対応: 「未初期化」と判定してよいのは
    coordination.lock不在（leases infrastructure自体が未用意）の場合のみ。
    それ以外（coordination.lockは存在するがcurrentが消失/破損している等）は
    真の整合性異常としてLeaseErrorを呼び出し元へ伝播させる
    （stream_versioned_glob()と同じ理由）。
    """
    if not (LEASES_ROOT / "coordination.lock").exists():
        return None
    _verify_data_runtime_root_ownership()
    coordinator = get_coordinator()
    handle = coordinator.acquire_current(DATA_RUNTIME_ROOT, "existence-check")
    try:
        version_root = DATA_RUNTIME_ROOT / "versions" / handle.payload.version_id
        _verify_version_root_ownership(version_root)
        file_path = version_root / relative_path
        if not file_path.is_file():
            return None
        _verify_served_file_ownership(file_path)
        return file_path
    finally:
        coordinator.release(handle)

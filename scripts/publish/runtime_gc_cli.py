#!/usr/bin/env python3
"""
runtime_gc_cli.py — Phase 2-B.5 operator stale lease cleanup / version GC CLI。

tasks/public-release/phase2b5_claude_implementation_instruction.md 第7節。

operator container内（UID 10002:10002、supplemental GID 20001）でのみ
実行することを前提とし、起動直後にidentityを検証する（第4.2節）。

既存operator CLI経路として提供する。新しいoperator HTTP routeは追加しない
（第3節「本phaseを理由に新しいpublic routeやoperator HTTP routeを増やして
はいけません」）。

使い方:
    python3 runtime_gc_cli.py --data-runtime-root /data_runtime \
        --leases-root /run/onhighground2/leases

第7.3節で確定する定数（default値・根拠・単位・上下限）:

    version_retention_count       = 3   （直近3世代は無条件保持。rollback対象を
                                          確実に残すための最小値。upper boundは
                                          運用のdisk容量次第、default単位は「世代数」）
    capacity_min_free_bytes       = 1073741824 (1 GiB)
                                          （publish先filesystemの空き容量が1GiB未満
                                          ならGC・publishとも安全側で停止する。
                                          repository/local test dataから安全な
                                          default容量を確定できないため、実運用では
                                          `--capacity-min-free-bytes` を必ずVPSの
                                          実ディスクサイズに応じて明示設定すること
                                          （未設定を「無制限」とは解釈しない）。）
    max_future_skew_s             = 5.0 秒（NTP等の通常のclock driftを許容する
                                          上限。これを超える未来timestampは
                                          fail-closedとする）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from app.services.runtime_atomic import ExpectedIdentity, RuntimeAtomicError, verify_process_identity
from app.services.runtime_gc import RuntimeGc, GcFailClosedError

EXPECTED_OPERATOR_UID = 10002
EXPECTED_OPERATOR_GID = 10002
EXPECTED_SUPPLEMENTAL_GID = 20001
EXPECTED_UMASK = 0o007

DEFAULT_RETENTION_COUNT = 3
DEFAULT_CAPACITY_MIN_FREE_BYTES = 1024 ** 3  # 1 GiB
DEFAULT_MAX_FUTURE_SKEW_S = 5.0


def _update_protected_list(versions_dir: Path, add: list, remove: list) -> None:
    """CODEX P2B5-CX-005対応: rollback保護をretention countへの暗黙依存に
    せず、明示的な`versions/.protected.json`を操作するCLI経由の手段を
    提供する。"""
    protected_path = versions_dir / ".protected.json"
    current = []
    if protected_path.is_file():
        current = json.loads(protected_path.read_text(encoding="utf-8"))
    current_set = set(current)
    current_set.update(add)
    current_set.difference_update(remove)
    tmp_path = protected_path.with_suffix(".json.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(sorted(current_set), f)
        f.flush()
        import os as _os
        _os.fsync(f.fileno())
    import os as _os
    _os.rename(tmp_path, protected_path)
    _os.chmod(protected_path, 0o640)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-runtime-root", required=True)
    parser.add_argument("--leases-root", default="/run/onhighground2/leases")
    parser.add_argument("--retention-count", type=int, default=DEFAULT_RETENTION_COUNT)
    parser.add_argument("--capacity-min-free-bytes", type=int, default=DEFAULT_CAPACITY_MIN_FREE_BYTES)
    parser.add_argument("--max-future-skew-s", type=float, default=DEFAULT_MAX_FUTURE_SKEW_S)
    parser.add_argument("--audit-dir", default=None)
    parser.add_argument(
        "--protect-version", action="append", default=[],
        help="明示的にrollback保護対象へ加えるversion ID（繰り返し指定可）",
    )
    parser.add_argument(
        "--unprotect-version", action="append", default=[],
        help="明示的rollback保護対象から外すversion ID（繰り返し指定可）",
    )
    parser.add_argument(
        "--skip-identity-check", action="store_true",
        help="第4.2節のidentity検証を明示的にskipする（テスト目的限定。運用では使用しない）",
    )
    args = parser.parse_args()

    if not args.skip_identity_check:
        try:
            verify_process_identity(
                ExpectedIdentity(
                    uid=EXPECTED_OPERATOR_UID,
                    gid=EXPECTED_OPERATOR_GID,
                    supplemental_gids=frozenset({EXPECTED_SUPPLEMENTAL_GID}),
                    umask=EXPECTED_UMASK,
                )
            )
        except RuntimeAtomicError as exc:
            print(f"FAIL identity: {exc}", file=sys.stderr)
            return 1

    data_root = Path(args.data_runtime_root)
    leases_root = Path(args.leases_root)
    audit_dir = Path(args.audit_dir) if args.audit_dir else (data_root / "manifests" / "phase2b5_audit")

    if args.protect_version or args.unprotect_version:
        _update_protected_list(data_root / "versions", args.protect_version, args.unprotect_version)

    gc = RuntimeGc(
        data_runtime_root=data_root,
        leases_root=leases_root,
        expect_writer_uid=EXPECTED_OPERATOR_UID,
        expect_writer_gid=EXPECTED_OPERATOR_GID,
        version_retention_count=args.retention_count,
        max_future_skew_s=args.max_future_skew_s,
        capacity_min_free_bytes=args.capacity_min_free_bytes,
    )

    try:
        result = gc.run(audit_dir=audit_dir)
    except GcFailClosedError as exc:
        print(f"FAIL-CLOSED: {exc}", file=sys.stderr)
        print("version削除・lock cleanup・自動修復は0件のまま終了する。", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "stale_leases_removed": result.stale_leases_removed,
                "orphan_locks_removed": result.orphan_locks_removed,
                "versions_deleted": result.versions_deleted,
                "versions_retained": result.versions_retained,
                "duration_s": round(result.finished_at - result.started_at, 3),
                "audit_path": str(result.audit_path) if result.audit_path else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

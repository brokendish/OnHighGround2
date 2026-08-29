#!/usr/bin/env python3
"""
activate_version.py — Phase 2-B.5 atomic publish activation CLI（operator専用）。

tasks/public-release/phase2b5_claude_implementation_instruction.md 第5節。

deploy_to_runtime.sh がstaging（data_runtime/.staging/<version-id>/）へ
datasetを生成した後、このCLIがvalidate→fsync→no-replace rename→
symlink atomic swapを実行してcurrentへ活性化する。

operator container内（UID 10002:10002、supplemental GID 20001）でのみ
実行することを前提とし、起動直後にidentityを検証する（第4.2節）。

使い方:
    python3 activate_version.py --data-runtime-root /data_runtime --version-id <id>
    python3 activate_version.py --data-runtime-root /data_runtime --rollback <id>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "/app")  # backend/ が /app へmountされるcontainer前提

from app.services.runtime_atomic import ExpectedIdentity, RuntimeAtomicError, verify_process_identity
from app.services.runtime_publish import AtomicPublisher, VERSION_FILE_MODE, PublishDurabilityError
from app.services.runtime_dataset_validate import validate_and_manifest_staging, write_manifest

# CODEX P2B5-CX-006（第4ラウンド）対応: exit 3は「current自体は新versionへ
# 切り替わったが、その耐久性（クラッシュ後の生存）を確認できなかった」
# ことを示す専用の終了コード。呼び出し元（deploy_to_runtime_atomic.sh）は
# これをexit 1（真の公開失敗、currentは変化していない）と区別し、
# 「公開はされたがoperatorの確認が必要」として扱うこと。
EXIT_DURABILITY_UNKNOWN = 3

EXPECTED_OPERATOR_UID = 10002
EXPECTED_OPERATOR_GID = 10002
EXPECTED_SUPPLEMENTAL_GID = 20001
EXPECTED_UMASK = 0o007


def _validate_staging(staging_path: Path, previous_version_path) -> None:
    """CODEX P2B5-CX-003対応: 「空でない」「backendが存在する」だけでなく、
    JSON/GeoJSON/GeoJSONLの構文検証、mbtilesのSQLite健全性検証、
    全fileのchecksum manifest生成までをここで行う。1件でも不正な内容が
    あればRuntimeAtomicErrorを送出し、current swapへ進ませない。

    第8ラウンド対応: `previous_version_path`（supersedeする直前version、
    初回publishではNone）を渡し、件数整合性検証（前回からの壊滅的な
    Feature件数減少の検出）を有効にする。
    """
    manifest, feature_counts = validate_and_manifest_staging(staging_path, previous_version_path)
    write_manifest(staging_path, manifest, VERSION_FILE_MODE, feature_counts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-runtime-root", required=True)
    parser.add_argument("--version-id", help="publishするversion ID（.stagingに存在すること）")
    parser.add_argument("--rollback", help="rollback先のversion ID（versions/に存在すること）")
    parser.add_argument("--audit-dir", default=None)
    parser.add_argument(
        "--skip-identity-check",
        action="store_true",
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

    root = Path(args.data_runtime_root)
    publisher = AtomicPublisher(root, expect_uid=EXPECTED_OPERATOR_UID, expect_gid=EXPECTED_OPERATOR_GID)
    audit_dir = Path(args.audit_dir) if args.audit_dir else (root / "manifests" / "phase2b5_audit")

    try:
        if args.rollback:
            result = publisher.rollback(args.rollback, audit_dir=audit_dir)
            action = "rollback"
        elif args.version_id:
            result = publisher.publish(args.version_id, _validate_staging, audit_dir=audit_dir)
            action = "publish"
        else:
            print("FAIL: --version-id または --rollback のいずれかが必要", file=sys.stderr)
            return 1
    except PublishDurabilityError as exc:
        # CODEX P2B5-CX-006（第4ラウンド）対応: 汎用RuntimeAtomicErrorの
        # except節でgeneric failureへ潰さない。current自体は既に
        # version_idへ切り替わっているため、stdoutへ機械可読な
        # status=DURABILITY_UNKNOWNを出力し、専用exit codeで区別する。
        print(
            json.dumps(
                {
                    "status": "DURABILITY_UNKNOWN",
                    "action": "publish",
                    "version_id": args.version_id,
                    "detail": str(exc),
                },
                ensure_ascii=False,
            )
        )
        print(f"DURABILITY_UNKNOWN publish: {exc}", file=sys.stderr)
        return EXIT_DURABILITY_UNKNOWN
    except RuntimeAtomicError as exc:
        print(f"FAIL {args.rollback and 'rollback' or 'publish'}: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "action": action,
                "version_id": result.version_id,
                "previous_version_id": result.previous_version_id,
                "duration_s": round(result.finished_at - result.started_at, 3),
                "audit_path": str(result.audit_path) if result.audit_path else None,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

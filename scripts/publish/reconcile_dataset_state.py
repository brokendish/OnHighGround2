#!/usr/bin/env python3
"""
reconcile_dataset_state.py — CLI publish 後に DatasetState を実 runtime へ同期する（operator 専用）。

deploy_to_runtime_atomic.sh は publish 成功後にこの CLI を呼ぶ。実 runtime（current + manifest +
artifact）を正として dataset ごとの runtime_status を判定し、DatasetState の deploy_status /
current_runtime_path / deployed_at / is_deployable だけを補正する（last_job_id / backup_path は
変更しない）。publish 自体の成否には影響しない（呼び出し側は失敗を warning として扱う）。

使い方（backend-operator container 内。backend/ が /app に mount される前提）:
    python3 /scripts/publish/reconcile_dataset_state.py [--data-runtime-root /data_runtime] [--no-hash]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _import_backend():
    here = Path(__file__).resolve()
    for cand in (Path("/app"), here.parents[2] / "backend"):
        if (cand / "app" / "services" / "dataset_runtime_reconcile.py").is_file():
            sys.path.insert(0, str(cand))
            return
    raise SystemExit("backend（app.services）が見つかりません")


def main() -> int:
    p = argparse.ArgumentParser(description="DatasetState を実 runtime（current）へ同期する")
    p.add_argument("--data-runtime-root", default=None)
    p.add_argument("--no-hash", action="store_true",
                   help="反映元 sha256 をキャッシュに無い場合も計算しない（判定不能は state を変更しない）")
    p.add_argument("--dry-run", action="store_true", help="DatasetState を保存しない")
    a = p.parse_args()
    if a.data_runtime_root:
        os.environ["OHG2_DATA_RUNTIME_ROOT"] = a.data_runtime_root
    _import_backend()
    from app.services.dataset_runtime_reconcile import reconcile_all

    report = reconcile_all(allow_hash=not a.no_hash, persist=not a.dry_run)
    summary = {
        "current_version": report["current_version"],
        "runtime_error": report["runtime_error"],
        "statuses": {r["dataset_id"]: r["runtime_status"] for r in report["results"]},
        "errors": report["errors"],
        "unregistered_runtime_artifacts": [u["rel_path"] for u in report["unregistered_runtime_artifacts"]],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if report["runtime_error"] or report["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())

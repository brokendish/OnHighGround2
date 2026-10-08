#!/usr/bin/env python3
"""
backfill_acquisition_history.py — 既存 dataset の取得履歴を事実から復元して記録する（operator 専用）。

復元元は DatasetState.current_raw_path の raw・admin history・job 記録・raw zip の原本名と sha256 のみ。
復元できない項目は空 / legacy_unknown のまま（推測しない）。既に取得履歴がある dataset は変更しない。

使い方（backend-operator container 内）:
    python3 /scripts/publish/backfill_acquisition_history.py --dataset TOKYO-RIVER-001 --dry-run
    python3 /scripts/publish/backfill_acquisition_history.py --dataset TOKYO-RIVER-001
    python3 /scripts/publish/backfill_acquisition_history.py --dataset A --dataset B   # 複数指定
    python3 /scripts/publish/backfill_acquisition_history.py --dry-run                 # 全 dataset

validity（valid / provenance_mismatch / provenance_suspect / unknown）は provenance_validity で判定し、
出力 JSON に含める。mismatch / suspect / unknown も履歴として記録し（valid へ昇格しない）、warning を出す。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _import_backend():
    here = Path(__file__).resolve()
    for cand in (Path("/app"), here.parents[2] / "backend"):
        if (cand / "app" / "services" / "acquisition_migration.py").is_file():
            sys.path.insert(0, str(cand))
            return
    raise SystemExit("backend（app.services）が見つかりません")


def main() -> int:
    p = argparse.ArgumentParser(description="取得履歴（acquisition history）を既存の事実から復元する")
    p.add_argument("--dataset", "--dataset-id", dest="dataset", action="append", default=None,
                   help="対象 dataset（複数回指定可）。未指定は全 dataset")
    p.add_argument("--dry-run", action="store_true", help="記録しない（復元内容だけ表示）")
    a = p.parse_args()
    _import_backend()
    from app.services.acquisition_migration import migrate_all

    import logging
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s", stream=sys.stderr)
    report = migrate_all(dry_run=a.dry_run, dataset_ids=a.dataset)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if any(r["action"] == "error" for r in report) else 0


if __name__ == "__main__":
    sys.exit(main())

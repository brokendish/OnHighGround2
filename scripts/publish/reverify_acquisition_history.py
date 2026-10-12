#!/usr/bin/env python3
"""
reverify_acquisition_history.py — 既存の取得履歴を registry の source identity で再検証する（operator 専用）。

旧来の validity=valid は「期待する原本そのものか」を見ていなかった（ACQUISITION-SOURCE-CONTRACT、2026-10-12）。
記録された原本の事実（原本名・sha256）を dataset 定義の expected_source_files / expected_source_sha256 と照合し、
record ごとに旧 / 新の判定を表示する。既定は dry-run（書かない）。--apply で、判定が変わった record と照合結果が
未記録の record だけを更新する（原本の事実・取得方法・active は変えない）。

使い方（backend-operator container 内）:
    python3 /scripts/publish/reverify_acquisition_history.py                     # 全 dataset、dry-run
    python3 /scripts/publish/reverify_acquisition_history.py --dataset KANAGAWA-RIVER-001
    python3 /scripts/publish/reverify_acquisition_history.py --dataset A --apply
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
    p = argparse.ArgumentParser(description="取得履歴を registry の source identity で再検証する")
    p.add_argument("--dataset", "--dataset-id", dest="dataset", action="append", default=None,
                   help="対象 dataset（複数回指定可）。未指定は全 dataset")
    p.add_argument("--apply", action="store_true", help="判定が変わった record と照合結果が未記録の record を更新する")
    a = p.parse_args()
    _import_backend()
    from app.services.acquisition_migration import reverify_all

    print(json.dumps(reverify_all(apply=a.apply, dataset_ids=a.dataset), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

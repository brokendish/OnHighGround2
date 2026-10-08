#!/usr/bin/env python3
"""
export_build_provenance.py — build node で runtime provenance record を書き出す（operator 専用）。

data_lake/provenance/<region>/<layer_type>/<dataset_id>.json を生成する。runtime node へは成果物と
一緒に転送し、publish（stage_runtime_provenance.py）が runtime version に同梱する。

使い方（backend-operator container 内）:
    python3 /scripts/publish/export_build_provenance.py --dataset KANAGAWA-RIVER-001 [--dataset ...] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _import_backend():
    here = Path(__file__).resolve()
    for cand in (Path("/app"), here.parents[2] / "backend"):
        if (cand / "app" / "services" / "build_provenance.py").is_file():
            sys.path.insert(0, str(cand))
            return
    raise SystemExit("backend（app.services）が見つかりません")


def main() -> int:
    p = argparse.ArgumentParser(description="runtime provenance record を build node で生成する")
    p.add_argument("--dataset", action="append", required=True, help="対象 dataset（複数回指定可）")
    p.add_argument("--dry-run", action="store_true", help="書き出さずに内容だけ表示")
    a = p.parse_args()
    _import_backend()
    from app.services import build_provenance
    from app.services.acquisition_migration import read_state_readonly
    from app.services.dataset_definition_service import get_definition_service

    ds = get_definition_service()
    rc = 0
    for dataset_id in a.dataset:
        defn = ds.get(dataset_id)
        state = read_state_readonly(dataset_id) if defn else None
        if defn is None or state is None:
            print(json.dumps({"dataset_id": dataset_id, "error": "definition または state がありません"}, ensure_ascii=False))
            rc = 1
            continue
        try:
            if a.dry_run:
                rec = build_provenance.generate(defn, state)
                print(json.dumps(rec, ensure_ascii=False, indent=2))
            else:
                path = build_provenance.export(defn, state)
                rec = json.loads(path.read_text(encoding="utf-8"))
                print(json.dumps({"dataset_id": dataset_id, "written": str(path),
                                  "runtime_artifact": rec["runtime_artifact"], "tile": rec["tile"],
                                  "source_validity": (rec["source"] or {}).get("validity")}, ensure_ascii=False))
        except ValueError as exc:
            print(json.dumps({"dataset_id": dataset_id, "error": str(exc)}, ensure_ascii=False))
            rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())

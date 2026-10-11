#!/usr/bin/env python3
"""
build_tsunami_coverage_index.py — dataset registry の tsunami dataset ごとに coverage index を作る。

  入力: registry の validated_storage_path 配下の canonical（<dataset_id 小文字>.geojson）
  出力: data_lake/registry/tsunami_coverage/<region>.json（git 管理）

backend はこの index で「津波 dataset を評価していない地点」を判定し、"outside" ではなく "unknown" を返す
（backend/tsunami_coverage.py）。canonical を作り直したら index も作り直す（source_sha256 で照合できる）。

  python3 scripts/derive/build_tsunami_coverage_index.py [--dataset CHIBA-TSUNAMI-001] [--check]
  --check: 既存 index が canonical から作り直した結果と一致するか確認するだけ（書き込まない）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

import tsunami_coverage as tc  # noqa: E402

REGISTRY = ROOT / "data_lake/registry/dataset_definitions.json"


def _canonical(defn: dict) -> Path:
    return ROOT / defn["validated_storage_path"] / f"{defn['dataset_id'].lower()}.geojson"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", action="append", help="対象 dataset_id（既定: registry の tsunami 全件）")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    defs = [d for d in json.loads(REGISTRY.read_text(encoding="utf-8")) if d.get("layer_type") == "tsunami"]
    if args.dataset:
        defs = [d for d in defs if d["dataset_id"] in args.dataset]
    out_dir = tc.coverage_dir_for(REGISTRY)
    rc = 0
    for d in defs:
        src = _canonical(d)
        if not src.is_file():
            print(f"[tsunami-coverage] ERROR canonical が無い: {d['dataset_id']} {src}", file=sys.stderr)
            rc = 1
            continue
        idx = tc.build_index(src, d["dataset_id"], d["region"])
        out = out_dir / f"{d['region']}.json"
        text = json.dumps(idx, ensure_ascii=False, separators=(",", ":")) + "\n"
        if args.check:
            same = out.is_file() and out.read_text(encoding="utf-8") == text
            print(f"[tsunami-coverage] {d['dataset_id']} {'OK' if same else 'STALE'} {out.name}")
            rc = rc or (0 if same else 1)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        cells = tc.load_index(out, d["dataset_id"], d["region"]).cell_count()
        print(f"[tsunami-coverage] {d['dataset_id']} region={d['region']} features={idx['feature_count']} "
              f"cells={cells} bytes={len(text)} -> {out.relative_to(ROOT)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())

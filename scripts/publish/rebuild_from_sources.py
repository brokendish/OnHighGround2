#!/usr/bin/env python3
"""
rebuild_from_sources.py — deploy_to_runtime_atomic.sh --rebuild-from-sources の補助（operator 専用）。

通常の publish は current を種に staging を作り、region ごとの成果物を積み上げる（incremental）。この方式では、
source（registry / data_lake）からもう作られない旧 artifact（旧名の tile、旧 flat 配置の GeoJSON 等）が
current に残り続ける。--rebuild-from-sources は staging を空から作り、registry / data_lake の正式な成果物だけで
version を組み立てる（build node の環境再構築用。2026-10-12 Local Environment Reconciliation）。

  --regions                       再構築に含める region（1 行ずつ）:
                                  hazard active mapping の region ∪ hazard.tsunami.targets ∪
                                  registry の tile 契約（tile_rel_path / tile build 対象）の region
  --check-staging DIR --current DIR
                                  staging に表示必須の tile（tile_requirement=required）と tsunami target の
                                  runtime が揃っているか確認し、current から落ちる file を一覧する。
                                  欠落があれば exit 1（activate しない）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REGION_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _import_backend():
    for base in ("/app", str(Path(__file__).resolve().parents[2] / "backend")):
        if base in sys.path:
            sys.path.remove(base)
        sys.path.insert(0, base)


def rebuild_regions(mappings, definitions, targets) -> list:
    from app.services import admin_atomic_publish as aap
    from app.services import data_ops_service as dos
    regions = {m["region"] for m in mappings if m["layer_type"] in aap.HAZARD_PUBLISH_LAYER_TYPES}
    regions |= set(targets)
    for d in definitions:
        if d.layer_type in aap.HAZARD_PUBLISH_LAYER_TYPES and dos.tile_requirement(d) in ("required", "optional"):
            regions.add(dos.tile_rel(d).split("/")[2])
    bad = sorted(r for r in regions if not _REGION_RE.match(r))
    if bad:
        raise ValueError(f"region 名が不正: {bad}")
    return sorted(regions)


def check_staging(staging: Path, current: "Path | None", definitions, targets) -> dict:
    from app.services import data_ops_service as dos
    missing = []
    for d in definitions:
        if d.layer_type and dos.tile_requirement(d) == "required" and not (staging / dos.tile_rel(d)).is_file():
            missing.append(f"required tile: {dos.tile_rel(d)}（{d.dataset_id}）")
    for t in targets:
        rel = f"backend/hazard/tsunami/tsunami_{t}.geojson"
        if not (staging / rel).is_file():
            missing.append(f"tsunami target runtime: {rel}")
    dropped = []
    if current is not None and (current / "_manifest.json").is_file():
        files = json.loads((current / "_manifest.json").read_text(encoding="utf-8"))["files"]
        dropped = sorted(r for r in files if not r.startswith("provenance/") and not (staging / r).exists())
    return {"missing": missing, "dropped": dropped}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", action="store_true")
    ap.add_argument("--check-staging")
    ap.add_argument("--current")
    a = ap.parse_args()
    _import_backend()
    from app.services.active_mapping_service import get_active_mapping_service
    from app.services.dataset_definition_service import get_definition_service
    from app.services.runtime_dataset_validate import _resolve_configured_tsunami_targets
    try:
        targets, err = _resolve_configured_tsunami_targets()
        if err:
            raise ValueError(f"hazard.tsunami.targets を解決できない: {err}")
        defs = get_definition_service().list_all()
        if a.regions:
            for r in rebuild_regions(get_active_mapping_service().list_all(), defs, sorted(targets)):
                print(r)
            return 0
        if a.check_staging:
            res = check_staging(Path(a.check_staging), Path(a.current) if a.current else None, defs, sorted(targets))
            for r in res["dropped"]:
                print(f"[rebuild] current から外れる file（source から作られない）: {r}")
            for m in res["missing"]:
                print(f"[rebuild] ERROR 再構築した staging に無い: {m}", file=sys.stderr)
            print(f"[rebuild] dropped={len(res['dropped'])} missing={len(res['missing'])}")
            return 1 if res["missing"] else 0
    except Exception as exc:  # noqa: BLE001 — 判定できなければ publish しない
        print(f"[rebuild] ERROR {exc}", file=sys.stderr)
        return 1
    ap.error("--regions または --check-staging を指定する")
    return 2


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
resolve_tsunami_source.py — region の tsunami dataset（registry）の validated canonical を、配置先ごとに解決する。

TSUNAMI-REGION-OWNERSHIP（2026-10-11）: 従来の deploy_to_runtime.sh は hazard.tsunami.targets の全 target を
「tsunami_<target>.geojson / <target>-tsunami-*.geojson」という file 名で、実行中 region の validated / normalized
directory から探していた。このため --region tokyo の publish が data_lake/normalized/tokyo/tsunami/ に残る旧
tsunami_chiba.geojson を chiba の runtime file として拾いうる。file 名・directory では選ばず、registry の
dataset（region が一致する tsunami dataset）だけを正本にする。

  backend        : region が hazard.tsunami.targets に含まれる場合だけ（backend は targets の file しか読まない）
  frontend_layer : dataset の api_exposure == "enabled" の場合だけ（GeoJSON 全量の静的配信も public API と同じ契約）

検証（不一致は fail closed、部分出力なし）:
  - region の tsunami dataset は registry に 0 件か 1 件（2 件以上は曖昧）
  - canonical は data_lake/validated/<region>/tsunami/ 配下の単一 file
  - 全 feature の properties.dataset_id が dataset_id と一致（別 region の artifact の混入を拒否）
  - 全 feature の depth が現在の normalizer で depth_text を解釈した値と一致
    （normalizer 修正前に作った canonical を配信しない。例: TOKYO の「0.5m以上 ～ 1m未満」= 5.0 の誤変換）

出力: <kind>\t<dataset_id>\t<path>    kind = backend | frontend_layer
  python3 resolve_tsunami_source.py --region chiba --targets tokyo,kanagawa
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for base in ("/app", str(ROOT / "backend")):
    if base not in sys.path:
        sys.path.insert(0, base)


def _normalizer():
    spec = importlib.util.spec_from_file_location("normalize_tsunami", ROOT / "scripts/normalize/normalize_tsunami.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _data_lake_root() -> Path:
    p = Path("/data_lake")
    return p if p.is_dir() else ROOT / "data_lake"


def check_canonical(path: Path, dataset_id: str, extract_depth) -> int:
    """全 feature の dataset_id と depth を確認し、feature 数を返す。不一致は ValueError。"""
    import ijson

    n, bad_owner, bad_depth, example = 0, 0, 0, None
    with path.open("rb") as f:
        for feat in ijson.items(f, "features.item", use_float=True):
            n += 1
            p = feat.get("properties") or {}
            if p.get("dataset_id") != dataset_id:
                bad_owner += 1
                example = example or f"dataset_id={p.get('dataset_id')!r}"
                continue
            if "depth_text" in p or "depth" in p:
                expected = extract_depth(p.get("depth_text"))
                got = p.get("depth")
                if not (expected is None and got is None) and (
                        expected is None or got is None or abs(float(got) - float(expected)) > 1e-9):
                    bad_depth += 1
                    example = example or f"depth_text={p.get('depth_text')!r} depth={got!r} expected={expected!r}"
        if hasattr(os, "posix_fadvise"):
            try:
                os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            except OSError:
                pass
    if n == 0:
        raise ValueError(f"feature が 0 件: {path}")
    if bad_owner:
        raise ValueError(f"{bad_owner} 件の feature が {dataset_id} の artifact ではない（region 不一致の混入、例 {example}）: {path}")
    if bad_depth:
        raise ValueError(f"{bad_depth} 件の depth が現在の normalizer の解釈と一致しない（canonical の再生成が必要、"
                         f"例 {example}）: {path}")
    return n


def resolve(region: str, targets: list, definitions: list, data_lake: Path, extract_depth) -> list:
    defs = [d for d in definitions if d.layer_type == "tsunami" and d.region == region]
    if len(defs) > 1:
        raise ValueError(f"region={region} の tsunami dataset が複数ある: {[d.dataset_id for d in defs]}")
    if not defs:
        if region in targets:
            raise ValueError(f"hazard.tsunami.targets に {region} があるが registry に tsunami dataset が無い")
        return []
    d = defs[0]
    kinds = [k for k, on in (("backend", region in targets), ("frontend_layer", d.api_exposure == "enabled")) if on]
    if not kinds:
        return []
    expected_dir = (data_lake / "validated" / region / "tsunami").resolve()
    if not d.validated_storage_path or Path(d.validated_storage_path).parts[-2:] != (region, "tsunami"):
        raise ValueError(f"{d.dataset_id}: validated_storage_path が region={region} の tsunami ではない: {d.validated_storage_path}")
    src = (expected_dir / f"{d.dataset_id.lower()}.geojson").resolve()
    if src.parent != expected_dir or not src.is_file():
        raise ValueError(f"{d.dataset_id}: canonical が無い: {src}")
    check_canonical(src, d.dataset_id, extract_depth)
    return [(k, d.dataset_id, src) for k in kinds]


def missing_target_regions(current: Path, targets: list, definitions: list) -> list:
    """hazard.tsunami.targets にあるのに current に backend の runtime file が無い region。

    backend は targets の tsunami_<region>.geojson を読み、activate の検証も targets 全件を要求するため、
    この region を含めない publish は拒否される（admin UI の publish region は active mapping 由来で、
    tile だけの region を含まない）。wrapper が自動で含める。registry に region 一致の tsunami dataset が
    1 件だけある target に限る（未知の region は ValueError、fail closed）。"""
    out = []
    for t in targets:
        if (current / "backend" / "hazard" / "tsunami" / f"tsunami_{t}.geojson").is_file():
            continue
        owners = [d for d in definitions if d.layer_type == "tsunami" and d.region == t]
        if len(owners) != 1:
            raise ValueError(f"hazard.tsunami.targets の {t} に対応する registry tsunami dataset が 1 件ではない: "
                             f"{[d.dataset_id for d in owners]}")
        out.append(t)
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region")
    ap.add_argument("--targets", help="hazard.tsunami.targets（カンマ区切り）")
    ap.add_argument("--missing-target-regions", action="store_true",
                    help="--current の version に runtime file が無い targets の region を 1 行ずつ出力"
                         "（targets は activate の検証と同じ設定解決で読む）")
    ap.add_argument("--current")
    args = ap.parse_args()
    if args.missing_target_regions:
        try:
            from app.services.dataset_definition_service import get_definition_service
            from app.services.runtime_dataset_validate import _resolve_configured_tsunami_targets
            configured, err = _resolve_configured_tsunami_targets()
            if err or not args.current:
                raise ValueError(err or "--missing-target-regions には --current が必要")
            for r in missing_target_regions(Path(args.current), sorted(configured), get_definition_service().list_all()):
                print(r)
        except Exception as exc:  # noqa: BLE001
            print(f"[resolve_tsunami_source] FAIL missing-target-regions: {exc}", file=sys.stderr)
            return 1
        return 0
    if not args.region or args.targets is None:
        ap.error("--region と --targets が必要")
    targets = [t.strip() for t in args.targets.split(",") if t.strip()]
    try:
        from app.services.dataset_definition_service import get_definition_service
        out = resolve(args.region, targets, get_definition_service().list_all(), _data_lake_root(),
                      _normalizer()._extract_depth_value)
    except Exception as exc:  # noqa: BLE001 — 解決できなければ publish を止める
        print(f"[resolve_tsunami_source] FAIL region={args.region}: {exc}", file=sys.stderr)
        return 1
    for kind, did, path in out:
        print(f"{kind}\t{did}\t{path}")
    print(f"[resolve_tsunami_source] region={args.region} targets={targets}: {[(k, d) for k, d, _ in out]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

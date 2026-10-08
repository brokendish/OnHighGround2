#!/usr/bin/env python3
"""
stage_runtime_provenance.py — publish 中の staging へ runtime provenance record を配置する。

deploy_to_runtime_atomic.sh が region ごとの deploy_to_runtime.sh の後・activate の前に呼ぶ。
active mapping の atomic publish 対象 dataset について、data_lake/provenance/<region>/<type>/<id>.json
があれば staging/provenance/<id>.json へ配置する（activate で _manifest.json に sha256 が載る）。
record が無い dataset は何もしない（current から seed された旧 record があればそのまま残り、Data Ops が
manifest と照合して不一致なら MISMATCH と表示する）。

record の検証（runtime artifact の sha256 照合）は publish では行わない（重い hash を増やさない）。
Data Ops が current → manifest の連鎖で照合する。形式不正の record は配置せず warning（exit 0）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


def _import_backend():
    here = Path(__file__).resolve()
    for cand in (Path("/app"), here.parents[2] / "backend"):
        if (cand / "app" / "services" / "runtime_provenance.py").is_file():
            sys.path.insert(0, str(cand))
            return
    raise SystemExit("backend（app.services）が見つかりません")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--staging", required=True)
    p.add_argument("--region", action="append", required=True)
    p.add_argument("--data-lake", default=None)
    a = p.parse_args()
    _import_backend()
    from app.services import admin_atomic_publish as aap
    from app.services import runtime_provenance as rp
    from app.services.active_mapping_service import get_active_mapping_service
    from app.services.dataset_definition_service import get_definition_service
    from datetime import datetime, timezone

    staging = Path(a.staging)
    data_lake = Path(a.data_lake) if a.data_lake else (Path("/data_lake") if Path("/data_lake").is_dir()
                                                        else Path(__file__).resolve().parents[2] / "data_lake")
    regions = set(a.region)
    staged, skipped = [], []
    for m in get_active_mapping_service().list_all():
        if m["layer_type"] not in aap.ATOMIC_PUBLISH_LAYER_TYPES or m["region"] not in regions:
            continue
        src = rp.build_path(data_lake, m["region"], m["layer_type"], m["dataset_id"])
        if not src.is_file():
            continue
        try:
            record = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            skipped.append(f"{m['dataset_id']}: 読めない（{exc}）")
            continue
        errs = rp.validate_record_shape(record, m["dataset_id"])
        if errs:
            skipped.append(f"{m['dataset_id']}: {'; '.join(errs)}")
            continue
        defn = get_definition_service().get(m["dataset_id"])
        # この publish がどの検証方式で routing を受け入れたか（resolver は方式どおりに検証済みでなければ
        # publish 自体が fail-closed で止まる）を runtime record に残す
        record["publish_verification"] = {
            "method": (getattr(defn, "publish_verification_mode", None) or "canonical_file")
            if m["layer_type"] == "flood" else "validated_copy",
            "staged_at": datetime.now(timezone.utc).isoformat(),
        }
        dst = staging / rp.runtime_rel(m["dataset_id"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f".{dst.name}.staging-{os.getpid()}")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, dst)
        staged.append(m["dataset_id"])
    print(f"[INFO] runtime provenance staged: {sorted(staged)}")
    for s in skipped:
        print(f"[WARN] runtime provenance skipped: {s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

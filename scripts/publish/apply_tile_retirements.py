#!/usr/bin/env python3
"""
apply_tile_retirements.py — 退役済み tile（data_lake/registry/tile_dispositions.json の disposition=RETIRED）を
publish の staging と Martin 用 flat mirror から取り除く。

背景: frontend tile の deploy は current を種に staging を作り data_lake/tiles を追加コピーするだけで、
mirror 同期も追加専用のため、使われなくなった tile が current / mirror に残り続ける。退役は
「明示的に RETIRED と記録した rel_path だけ」を対象にする（wildcard・推測で消さない）。

  --staging <dir>   publish 前の staging から対象 rel_path を除く（manifest に入らない）。
                    record が不正なら exit 1（publish を止める）。
  --mirror <dir> --current <dir>
                    activate 後、current に無い対象 file を mirror から除く。mirror の file が
                    record の backup sha256 と一致する場合だけ消す（一致しなければ残して警告）。

前 version（versions/<id>）は一切触らない。rollback すると前 version には tile が残っているが、
mirror は rollback で同期されないため、退役 tile は配信されない（backup から戻す。docs 参照）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REQUIRED = ("rel_path", "tileset_id", "reason", "replacement", "retired_at", "backup")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load_retirements(path: Path) -> list:
    items = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i in items:
        if i.get("disposition") != "RETIRED":
            continue
        missing = [k for k in REQUIRED if not i.get(k)]
        backup = i.get("backup") or {}
        if missing or not backup.get("path") or not backup.get("sha256"):
            raise ValueError(f"RETIRED record が不完全: {i.get('rel_path')} missing={missing or 'backup.path/sha256'}")
        rel = i["rel_path"]
        if not (rel.startswith("frontend/tiles/") and rel.endswith(".mbtiles")) or ".." in rel.split("/") or "*" in rel:
            raise ValueError(f"RETIRED rel_path が不正: {rel}")
        if Path(rel).stem != i["tileset_id"]:
            raise ValueError(f"RETIRED tileset_id と rel_path が不一致: {rel} / {i['tileset_id']}")
        out.append(i)
    return out


def apply_staging(staging: Path, items: list) -> list:
    removed = []
    for i in items:
        target = staging / i["rel_path"]
        if target.is_file() and not target.is_symlink():
            target.unlink()
            removed.append(i["rel_path"])
    return removed


def apply_mirror(mirror_root: Path, current: Path, items: list) -> "tuple[list, list]":
    """mirror_root は data_runtime（rel_path は frontend/tiles/... で始まる）。"""
    removed, kept = [], []
    for i in items:
        rel = i["rel_path"]
        target = mirror_root / rel
        if not target.is_file():
            continue
        if (current / rel).exists():
            kept.append(f"{rel}: current にまだ存在するため mirror から消さない")
            continue
        if _sha256(target) != i["backup"]["sha256"]:
            kept.append(f"{rel}: mirror の sha256 が backup と一致しないため消さない")
            continue
        target.unlink()
        removed.append(rel)
    return removed, kept


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=None, help="tile_dispositions.json（既定: dataset 定義と同じ registry）")
    ap.add_argument("--staging")
    ap.add_argument("--mirror", help="data_runtime root（mirror は <root>/frontend/tiles）")
    ap.add_argument("--current")
    args = ap.parse_args()
    if args.registry:
        reg = Path(args.registry)
    else:
        sys.path.insert(0, "/app")
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
        from app.services.data_ops_service import _tile_dispositions_path
        reg = _tile_dispositions_path()
    try:
        items = load_retirements(reg) if reg.is_file() else []
    except (OSError, ValueError) as exc:
        print(f"[tile-retirement] ERROR {exc}", file=sys.stderr)
        return 1
    if args.staging:
        removed = apply_staging(Path(args.staging), items)
        print(f"[tile-retirement] staging: removed={removed} retired_records={len(items)}")
    if args.mirror:
        if not args.current:
            print("[tile-retirement] ERROR --mirror には --current が必要", file=sys.stderr)
            return 1
        removed, kept = apply_mirror(Path(args.mirror), Path(args.current), items)
        print(f"[tile-retirement] mirror: removed={removed}")
        for k in kept:
            print(f"[tile-retirement] WARN {k}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

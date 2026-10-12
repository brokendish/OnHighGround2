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

TILE-PATH-MIGRATION（disposition=MIGRATED）: 同じ tileset を別 path へ移した旧 path。staging では移動先
（migrated_to）が staging にある場合だけ旧 path を除く（移動先が無ければ publish を止める）。mirror では
current に無く、record の sha256 と一致する旧 path だけを除く。tileset_id は変えない。

前 version（versions/<id>）は一切触らない。rollback すると前 version には tile が残っているが、
mirror は rollback で同期されないため、退役 tile は配信されない（backup から戻す。docs 参照）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REQUIRED = ("rel_path", "tileset_id", "reason", "replacement", "retired_at", "backup")


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
        if os.fstat(f.fileno()).st_size >= (16 << 20) and hasattr(os, "posix_fadvise"):
            try:  # 大きい MBTiles は読了後に page cache を手放す（hint。失敗しても判定は変えない）
                os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            except OSError:
                pass
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
        for nb in i.get("node_backups") or []:
            if not isinstance(nb, dict) or not nb.get("node") or not nb.get("path") or not nb.get("sha256"):
                raise ValueError(f"RETIRED record の node_backups が不完全: {i.get('rel_path')}（node / path / sha256 が必要）")
        rel = i["rel_path"]
        if not (rel.startswith("frontend/tiles/") and rel.endswith(".mbtiles")) or ".." in rel.split("/") or "*" in rel:
            raise ValueError(f"RETIRED rel_path が不正: {rel}")
        if Path(rel).stem != i["tileset_id"]:
            raise ValueError(f"RETIRED tileset_id と rel_path が不一致: {rel} / {i['tileset_id']}")
        out.append(i)
    return out


MIGRATION_REQUIRED = ("rel_path", "tileset_id", "migrated_to", "sha256", "migrated_at", "reason")


def _check_rel(rel: str) -> None:
    if not (rel.startswith("frontend/tiles/") and rel.endswith(".mbtiles")) or ".." in rel.split("/") or "*" in rel:
        raise ValueError(f"tile path が不正: {rel}")


def load_migrations(path: Path) -> list:
    items = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for i in items:
        if i.get("disposition") != "MIGRATED":
            continue
        missing = [k for k in MIGRATION_REQUIRED if not i.get(k)]
        if missing:
            raise ValueError(f"MIGRATED record が不完全: {i.get('rel_path')} missing={missing}")
        _check_rel(i["rel_path"])
        _check_rel(i["migrated_to"])
        if i["rel_path"] == i["migrated_to"] or not (Path(i["rel_path"]).stem == Path(i["migrated_to"]).stem == i["tileset_id"]):
            raise ValueError(f"MIGRATED は同じ tileset_id の別 path への移動に限る: {i['rel_path']} -> {i['migrated_to']}")
        out.append(i)
    return out


def _region_of(rel: str) -> str:
    return rel.split("/")[2]  # frontend/tiles/<region>/<hazard>/<file>


def pending_migration_regions(current: Path, items: list, definitions: list) -> list:
    """移動が未完了（current に旧 path があり移動先が無い）の MIGRATED record の移動先 region。

    publish がこの region を含まないと staging で移動先が揃わず中止になるため、wrapper が自動で含める
    （admin UI の publish region は active mapping 由来で、tile だけの region を含まない）。自動で含めてよいのは
    移動先が registry の dataset の tile 契約（tile_rel_path）そのもので、その dataset の region と一致する
    場合だけ。未知の region・契約に無い移動先は ValueError（fail closed）。"""
    by_tile = {getattr(d, "tile_rel_path", None): d for d in definitions if getattr(d, "tile_rel_path", None)}
    known_regions = {d.region for d in definitions if getattr(d, "region", None)}
    regions = set()
    for i in items:
        if not (current / i["rel_path"]).is_file() or (current / i["migrated_to"]).exists():
            continue
        region = _region_of(i["migrated_to"])
        d = by_tile.get(i["migrated_to"])
        if d is None:
            raise ValueError(f"MIGRATED の移動先が registry の tile 契約に無い: {i['migrated_to']}")
        if region not in known_regions or d.region != region:
            raise ValueError(f"MIGRATED の移動先 region が dataset と一致しない・未知: {i['migrated_to']} "
                             f"(dataset {d.dataset_id} region={d.region})")
        regions.add(region)
    return sorted(regions)


def apply_staging_migrations(staging: Path, items: list) -> list:
    removed = []
    for i in items:
        old, new = staging / i["rel_path"], staging / i["migrated_to"]
        if not old.is_file() or old.is_symlink():
            continue
        if not new.is_file():
            raise ValueError(f"移動先の tile が staging に無いため旧 path を除けない: {i['migrated_to']}"
                             f"（data_lake/tiles/{i['migrated_to'].split('/', 2)[2]} を用意する。publish region は"
                             f" wrapper が自動で含める）")
        old.unlink()
        removed.append(i["rel_path"])
    return removed


def apply_mirror_migrations(mirror_root: Path, current: Path, items: list) -> "tuple[list, list]":
    removed, kept = [], []
    for i in items:
        target = mirror_root / i["rel_path"]
        if not target.is_file():
            continue
        if (current / i["rel_path"]).exists():
            kept.append(f"{i['rel_path']}: current にまだ存在するため mirror から消さない")
            continue
        if _sha256(target) != i["sha256"]:
            kept.append(f"{i['rel_path']}: mirror の sha256 が移動 record と一致しないため消さない")
            continue
        target.unlink()
        removed.append(i["rel_path"])
    return removed, kept


def retired_shas(item: dict) -> set:
    """退役 tile として消してよい sha256（backup と node ごとの backup）。node で build が異なる tile
    （例: tokyo_storm_surge は build node と runtime node で別 build）も、記録した sha だけを対象にする。"""
    shas = {(item.get("backup") or {}).get("sha256")}
    shas |= {nb.get("sha256") for nb in item.get("node_backups") or []}
    return {s for s in shas if s}


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
        if _sha256(target) not in retired_shas(i):
            kept.append(f"{rel}: mirror の sha256 が backup と一致しないため消さない（node_backups を含む）")
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
    ap.add_argument("--pending-migration-regions", action="store_true",
                    help="--current の version で移動が未完了の MIGRATED record の移動先 region を 1 行ずつ出力")
    args = ap.parse_args()
    sys.path.insert(0, "/app")
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
    if args.registry:
        reg = Path(args.registry)
    else:
        from app.services.data_ops_service import _tile_dispositions_path
        reg = _tile_dispositions_path()
    try:
        items = load_retirements(reg) if reg.is_file() else []
        migrations = load_migrations(reg) if reg.is_file() else []
        if args.pending_migration_regions:
            if not args.current:
                raise ValueError("--pending-migration-regions には --current が必要")
            from app.services.dataset_definition_service import get_definition_service
            for r in pending_migration_regions(Path(args.current), migrations, get_definition_service().list_all()):
                print(r)
            return 0
        if args.staging:
            removed = apply_staging(Path(args.staging), items)
            moved = apply_staging_migrations(Path(args.staging), migrations)
            print(f"[tile-retirement] staging: removed={removed} retired_records={len(items)} "
                  f"migrated_old_paths_removed={moved} migration_records={len(migrations)}")
    except (OSError, ValueError) as exc:
        print(f"[tile-retirement] ERROR {exc}", file=sys.stderr)
        return 1
    if args.mirror:
        if not args.current:
            print("[tile-retirement] ERROR --mirror には --current が必要", file=sys.stderr)
            return 1
        removed, kept = apply_mirror(Path(args.mirror), Path(args.current), items)
        moved, kept2 = apply_mirror_migrations(Path(args.mirror), Path(args.current), migrations)
        kept += kept2
        print(f"[tile-retirement] mirror: removed={removed} migrated_old_paths_removed={moved}")
        if moved:
            print("[tile-retirement] MARTIN_RESTART_REQUIRED（tile が別 directory へ移った。Martin 1.14.0 は再起動まで"
                  " 新 path の tile を `<id>.1` として扱う）")
        for k in kept:
            print(f"[tile-retirement] WARN {k}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

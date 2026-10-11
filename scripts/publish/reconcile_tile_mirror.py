#!/usr/bin/env python3
"""
reconcile_tile_mirror.py — Martin 用 flat mirror（data_runtime/frontend/tiles）を、指定 version の
manifest（frontend/tiles/**.mbtiles と sha256）に完全一致させる（TILE-AWARE-ROLLBACK）。

背景: activate_version.py --rollback は current symlink だけを戻し、mirror は publish 時の追加専用同期
（sync_frontend_tiles_mirror.sh）と退役処理でしか更新されない。そのため rollback しても退役 tile は
復元されず、差し替え前の tile にも戻らなかった。

正: 対象 version の _manifest.json（manifest と disk の一致は呼び出し側 / --verify-version で確認）。
操作:
  ADD/RESTORE  version にあり mirror に無い → version の file を一時名へ copy → sha 検証 → group/mode 正規化
               → fsync → atomic rename
  REPLACE      両方にあり sha が違う → 同上（置換）
  REMOVE       mirror にだけある → 「いずれかの version の manifest」か「退役 record の backup」に同じ sha256 で
               記録された file だけ削除（素性が確認できない file は消さず UNKNOWN として報告）
  KEEP         sha 一致
path は frontend/tiles/ 配下の *.mbtiles に限る（symlink・traversal は拒否）。wildcard 削除はしない。

段階:
  --plan     差分計画を JSON で出す（変更なし）
  --prepare  ADD/REPLACE の一時 file を mirror 内に用意し sha を検証（current 切替前に実行。失敗しても mirror 不変）
  --commit   用意した一時 file を rename し REMOVE を実行（current 切替後に実行。冪等で再実行可）
  --apply    prepare + commit
  --verify   mirror と version manifest の path / sha256 / mode / group が一致するか（不一致は exit 1）
exit: 0=一致/成功, 1=失敗, 2=成功だが UNKNOWN（素性不明で残した file）あり
"""
from __future__ import annotations

import argparse
import grp
import hashlib
import json
import os
import shutil
import stat
import sys
from pathlib import Path

FILE_MODE = 0o640
DIR_MODE = 0o750
TMP_SUFFIX = ".reconciling"
PREFIX = "frontend/tiles/"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _safe_rel(rel: str) -> bool:
    parts = rel.split("/")
    return rel.startswith(PREFIX) and rel.endswith(".mbtiles") and ".." not in parts and "" not in parts and "*" not in rel


def _tmp_path(target: Path) -> Path:
    return target.with_name(f".{target.name}{TMP_SUFFIX}")


def version_tiles(version: Path) -> dict:
    files = json.loads((version / "_manifest.json").read_text(encoding="utf-8"))["files"]
    out = {}
    for rel, sha in files.items():
        if rel.startswith(PREFIX) and rel.endswith(".mbtiles"):
            if not _safe_rel(rel):
                raise ValueError(f"manifest の tile path が不正: {rel}")
            out[rel] = sha
    return out


def mirror_tiles(root: Path) -> dict:
    base = root / "frontend" / "tiles"
    out = {}
    if not base.is_dir():
        return out
    for p in base.rglob("*.mbtiles"):
        if p.name.startswith(".") and p.name.endswith(TMP_SUFFIX):
            continue
        rel = str(p.relative_to(root))
        st = os.lstat(p)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
            raise ValueError(f"mirror に通常 file 以外がある: {rel}")
        out[rel] = p
    return out


def known_shas(root: Path, registry: Path | None) -> dict:
    """mirror から消してよい file の素性: いずれかの version manifest か退役 record の backup に記録された sha。"""
    known: dict = {}
    vdir = root / "versions"
    for v in sorted(vdir.iterdir()) if vdir.is_dir() else []:
        m = v / "_manifest.json"
        if v.is_dir() and not v.is_symlink() and m.is_file():
            try:
                for rel, sha in json.loads(m.read_text(encoding="utf-8"))["files"].items():
                    if rel.startswith(PREFIX):
                        known.setdefault(rel, set()).add(sha)
            except (OSError, ValueError, KeyError):
                continue
    if registry and registry.is_file():
        for d in json.loads(registry.read_text(encoding="utf-8")):
            b = d.get("backup") or {}
            if d.get("disposition") == "RETIRED" and d.get("rel_path") and b.get("sha256"):
                known.setdefault(d["rel_path"], set()).add(b["sha256"])
    return known


def plan(root: Path, version: Path, registry: Path | None) -> dict:
    want = version_tiles(version)
    have = mirror_tiles(root)
    known = known_shas(root, registry)
    actions = {"KEEP": [], "ADD": [], "REPLACE": [], "REMOVE": [], "UNKNOWN": []}
    for rel, sha in sorted(want.items()):
        if rel not in have:
            actions["ADD"].append({"rel": rel, "sha256": sha})
        elif _sha256(have[rel]) == sha:
            actions["KEEP"].append({"rel": rel, "sha256": sha})
        else:
            actions["REPLACE"].append({"rel": rel, "sha256": sha})
    for rel, p in sorted(have.items()):
        if rel in want:
            continue
        sha = _sha256(p)
        if _safe_rel(rel) and sha in known.get(rel, set()):
            actions["REMOVE"].append({"rel": rel, "sha256": sha})
        else:
            actions["UNKNOWN"].append({"rel": rel, "sha256": sha, "reason": "どの version manifest・退役 record にも同じ sha の記録が無い"})
    return {"version": version.name, "actions": actions,
            "summary": {k: len(v) for k, v in actions.items()}}


def _copy(src: Path, dst: Path) -> None:
    """copy_file_range（XFS reflink 等では物理 write なしの共有）→ 失敗時は通常 copy。"""
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        n = os.fstat(fi.fileno()).st_size
        try:
            off = 0
            while off < n:
                w = os.copy_file_range(fi.fileno(), fo.fileno(), n - off)
                if w == 0:
                    break
                off += w
            if off == n:
                return
        except (AttributeError, OSError):
            pass
    shutil.copyfile(src, dst)


def _normalize(p: Path, gid: int | None, mode: int) -> None:
    if gid is not None:
        try:
            os.chown(p, -1, gid)
        except PermissionError:
            pass
    os.chmod(p, mode)


def _fsync_dir(d: Path) -> None:
    fd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare(root: Path, version: Path, p: dict, gid: int | None) -> list:
    staged = []
    try:
        for a in p["actions"]["ADD"] + p["actions"]["REPLACE"]:
            src, target = version / a["rel"], root / a["rel"]
            for d in reversed([target.parent, *target.parent.parents]):
                if d == root or root not in d.parents:
                    continue
                if not d.exists():
                    d.mkdir()
                    _normalize(d, gid, DIR_MODE)
            tmp = _tmp_path(target)
            if tmp.exists():
                tmp.unlink()
            _copy(src, tmp)
            with open(tmp, "rb") as f:
                os.fsync(f.fileno())
            if _sha256(tmp) != a["sha256"]:
                raise RuntimeError(f"準備した file の sha256 が manifest と不一致: {a['rel']}")
            _normalize(tmp, gid, FILE_MODE)
            staged.append(a["rel"])
    except BaseException:
        for rel in staged:
            _tmp_path(root / rel).unlink(missing_ok=True)
        cleanup(root)
        raise
    return staged


def cleanup(root: Path) -> None:
    base = root / "frontend" / "tiles"
    if base.is_dir():
        for t in base.rglob(f".*{TMP_SUFFIX}"):
            t.unlink(missing_ok=True)


def commit(root: Path, p: dict, gid: int | None = None) -> dict:
    done = {"ADD": [], "REPLACE": [], "REMOVE": [], "NORMALIZE": []}
    for kind in ("ADD", "REPLACE"):
        for a in p["actions"][kind]:
            target = root / a["rel"]
            tmp = _tmp_path(target)
            if not tmp.is_file():
                if target.is_file() and _sha256(target) == a["sha256"]:
                    continue  # 既に反映済み（再実行）
                raise RuntimeError(f"準備済みの一時 file が無い: {a['rel']}（--prepare を先に実行）")
            os.replace(tmp, target)
            _fsync_dir(target.parent)
            done[kind].append(a["rel"])
    # sha 一致（KEEP）の file も runtime の permission 契約へ正規化する（内容は変えない。metadata のみ）
    for a in p["actions"]["KEEP"]:
        target = root / a["rel"]
        st = os.stat(target)
        if stat.S_IMODE(st.st_mode) != FILE_MODE or (gid is not None and st.st_gid != gid):
            _normalize(target, gid, FILE_MODE)
            done["NORMALIZE"].append(a["rel"])
    for a in p["actions"]["REMOVE"]:
        target = root / a["rel"]
        if target.is_file() and _sha256(target) == a["sha256"]:
            target.unlink()
            _fsync_dir(target.parent)
            done["REMOVE"].append(a["rel"])
    return done


def verify(root: Path, version: Path, gid: int | None) -> list:
    want = version_tiles(version)
    have = mirror_tiles(root)
    problems = []
    for rel, sha in want.items():
        p = have.get(rel)
        if p is None:
            problems.append(f"missing: {rel}")
            continue
        if _sha256(p) != sha:
            problems.append(f"sha-mismatch: {rel}")
        st = os.stat(p)
        if stat.S_IMODE(st.st_mode) != FILE_MODE or (gid is not None and st.st_gid != gid):
            problems.append(f"permission: {rel} mode={oct(stat.S_IMODE(st.st_mode))} gid={st.st_gid}")
    for rel in have:
        if rel not in want:
            problems.append(f"extra: {rel}")
    return problems


def _registry(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    for base in ("/app", str(Path(__file__).resolve().parents[2] / "backend")):
        sys.path.insert(0, base)
    try:
        from app.services.data_ops_service import _tile_dispositions_path
        return _tile_dispositions_path()
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-runtime-root", required=True)
    ap.add_argument("--version", help="version id（既定: current の参照先）")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--gid", type=int, default=int(os.environ.get("OHG2_LEASES_GID", "20001")))
    g = ap.add_mutually_exclusive_group(required=True)
    for m in ("plan", "prepare", "commit", "apply", "verify"):
        g.add_argument(f"--{m}", action="store_true")
    args = ap.parse_args()
    root = Path(args.data_runtime_root)
    vid = args.version or os.readlink(root / "current").split("/")[-1]
    version = root / "versions" / vid
    gid = args.gid
    try:
        grp.getgrgid(gid)
    except KeyError:
        gid = None
    try:
        if args.verify:
            problems = verify(root, version, gid)
            print(json.dumps({"version": vid, "ok": not problems, "problems": problems}, ensure_ascii=False))
            return 0 if not problems else 1
        p = plan(root, version, _registry(args.registry))
        if args.plan:
            print(json.dumps(p, ensure_ascii=False, indent=1))
            return 2 if p["actions"]["UNKNOWN"] else 0
        if args.prepare or args.apply:
            staged = prepare(root, version, p, gid)
            print(f"[tile-mirror] prepared={staged}")
        if args.commit or args.apply:
            done = commit(root, p, gid)
            print(f"[tile-mirror] version={vid} committed={done} unknown_kept={[u['rel'] for u in p['actions']['UNKNOWN']]}")
        return 2 if p["actions"]["UNKNOWN"] else 0
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        print(f"[tile-mirror] ERROR {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

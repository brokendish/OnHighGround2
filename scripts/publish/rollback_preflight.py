#!/usr/bin/env python3
"""
rollback_preflight.py — rollback 先 version が「表示に必須の tile」を持っているかを、current 切替前に判定する。

判定の正は 2 つだけ（version 名や人の記憶では判定しない）:
  - rollback 先 version の _manifest.json（tile の path と sha256）と、その実 file
  - dataset registry の tile 契約（tile_requirement / tile_rel_path）

  required        : 対応 tile が rollback 先に無い・manifest と実 file が一致しない → UNSAFE（既定で拒否）
  optional        : 無ければ WARNING（API GeoJSON fallback で表示できるため rollback は許可）
  unknown（契約未定義の tile 対象 dataset）: WARNING（required へ自動昇格はしないが、安全とも扱わない）
  not_applicable  : 対象外

tsunami consumer 契約（backend/app.properties の hazard.tsunami.targets）: targets の region の
backend/hazard/tsunami/tsunami_<region>.geojson が rollback 先に無い・壊れている → BLOCK。backend は
再起動時に target 欠落を検出して全地点の津波判定を unknown に倒すため（false safe ではないが、
全域で津波判定が使えなくなる）、required tile と同じく既定で拒否する（2026-10-11、chiba 追加時）。

registry を厳密に読む（1 件でも定義が不正・file が無い・dataset 0 件なら FAIL）。通常の定義読み込みは
不正な定義を読み飛ばすため、そのまま使うと required dataset が判定から消えて fail-open になる。

exit: 0=SAFE / SAFE_WITH_WARNINGS（--allow-missing-required-tiles で UNSAFE を通した場合も 0）
      4=UNSAFE_REQUIRED_TILE_MISSING（拒否）  1=判定不能（FAIL closed）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

SAFE = "SAFE"
SAFE_WITH_WARNINGS = "SAFE_WITH_WARNINGS"
UNSAFE = "UNSAFE_REQUIRED_TILE_MISSING"
UNSAFE_OVERRIDDEN = "UNSAFE_OVERRIDDEN"
EXIT_UNSAFE = 4


def _import_backend():
    # repo の backend（host / test 実行）を /app（container の mount）より優先する。既に sys.path にあっても
    # 先頭へ並べ直す（/app だけが先頭に入り、別の backend の app package を読むことを防ぐ）
    for base in ("/app", str(Path(__file__).resolve().parents[2] / "backend")):
        if base in sys.path:
            sys.path.remove(base)
        sys.path.insert(0, base)
    from app.models.admin_dataset import DatasetDefinition
    from app.services import data_ops_service as dos
    return DatasetDefinition, dos


def load_definitions_strict(path: Path) -> list:
    DatasetDefinition, _ = _import_backend()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"dataset registry が空または不正: {path}")
    defs, errors = [], []
    for item in raw:
        try:
            defs.append(DatasetDefinition(**item))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{item.get('dataset_id') if isinstance(item, dict) else item}: {str(exc)[:160]}")
    if errors:
        raise ValueError(f"dataset registry に不正な定義がある（判定不能）: {errors[:3]}")
    return defs


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
        if hasattr(os, "posix_fadvise"):
            try:
                os.posix_fadvise(f.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
            except OSError:
                pass
    return h.hexdigest()


def _configured_tsunami_targets() -> list:
    """activate の検証・backend と同じ設定解決で hazard.tsunami.targets を読む（読めなければ例外）。"""
    _import_backend()
    from app.services.runtime_dataset_validate import _resolve_configured_tsunami_targets
    targets, err = _resolve_configured_tsunami_targets()
    if err:
        raise ValueError(f"hazard.tsunami.targets を解決できない: {err}")
    return sorted(targets)


def tsunami_target_checks(version: Path, files: dict, targets: "list | None" = None) -> list:
    out = []
    for t in (_configured_tsunami_targets() if targets is None else targets):
        rel = f"backend/hazard/tsunami/tsunami_{t}.geojson"
        sha = files.get(rel)
        if sha is None:
            detail = "rollback 先 version に無い"
        elif not (version / rel).is_file():
            detail = "manifest にあるが実 file が無い"
        elif _sha256(version / rel) != sha:
            detail = "実 file の sha256 が manifest と一致しない"
        else:
            out.append({"dataset_id": f"tsunami-target:{t}", "requirement": "tsunami_target", "tile_rel_path": rel,
                        "state": "present", "severity": "OK", "reason": None})
            continue
        out.append({"dataset_id": f"tsunami-target:{t}", "requirement": "tsunami_target", "tile_rel_path": rel,
                    "state": "missing", "severity": "BLOCK",
                    "reason": f"hazard.tsunami.targets の {t} の runtime file が{detail.replace('rollback 先 version に無い', '無い')}"
                              "（backend 再起動で全地点の津波判定が unknown になる）"})
    return out


def preflight(version: Path, registry: Path) -> dict:
    _, dos = _import_backend()
    defs = load_definitions_strict(registry)
    try:
        files = json.loads((version / "_manifest.json").read_text(encoding="utf-8"))["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"rollback 先 version の manifest を読めない: {version}: {exc}") from exc
    checks = []
    for d in sorted(defs, key=lambda x: x.dataset_id):
        req = dos.tile_requirement(d)
        if req == "not_applicable" or not d.layer_type:
            continue
        rel = dos.tile_rel(d)
        # TILE-PATH-MIGRATION: 移動前の version では旧 path（tile_dispositions の MIGRATED）にある tile を同じ tile とみなす
        candidates = [c for c in dos.tile_rel_candidates(d) if c in files] or [rel]
        rel = candidates[0]
        sha = files.get(rel)
        if sha is None:
            state, detail = "missing", "rollback 先 version の manifest に tile が無い"
        elif not (version / rel).is_file():
            state, detail = "broken", "manifest にあるが実 file が無い"
        elif _sha256(version / rel) != sha:
            state, detail = "broken", "実 file の sha256 が manifest と一致しない"
        else:
            state, detail = "present", None
        if state == "present":
            severity = "OK" if req != "unknown" else "WARNING"
            reason = None if req != "unknown" else "tile 契約（tile_requirement）が未定義"
        elif req == "required":
            severity, reason = "BLOCK", f"表示に必須の tile が使えない（{detail}）"
        else:
            severity = "WARNING"
            reason = (f"optional tile が使えない（{detail}）。API GeoJSON で表示される" if req == "optional"
                      else f"tile 契約が未定義で欠落の影響を判定できない（{detail}）")
        checks.append({"dataset_id": d.dataset_id, "requirement": req, "tile_rel_path": rel, "state": state,
                       "severity": severity, "reason": reason})
    checks += tsunami_target_checks(version, files)
    blocked = [c for c in checks if c["severity"] == "BLOCK"]
    warned = [c for c in checks if c["severity"] == "WARNING"]
    verdict = UNSAFE if blocked else (SAFE_WITH_WARNINGS if warned else SAFE)
    return {"target_version": version.name, "verdict": verdict, "blocked": blocked, "warnings": warned, "checks": checks}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-runtime-root", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--registry", default=None, help="dataset_definitions.json（既定: 定義 service と同じ path）")
    ap.add_argument("--allow-missing-required-tiles", action="store_true",
                    help="緊急時専用: required tile が欠ける rollback を許可する（警告を出す）")
    ap.add_argument("--json", action="store_true", help="結果を JSON で出力")
    args = ap.parse_args()
    version = Path(args.data_runtime_root) / "versions" / args.version
    try:
        if not version.is_dir() or version.is_symlink():
            raise ValueError(f"rollback 先 version が無い: {version}")
        if args.registry:
            registry = Path(args.registry)
        else:
            _import_backend()
            from app.services.dataset_definition_service import _DEFINITIONS_PATH
            registry = Path(_DEFINITIONS_PATH)
        result = preflight(version, registry)
    except Exception as exc:  # noqa: BLE001 — 判定できない場合は必ず止める
        print(json.dumps({"target_version": args.version, "verdict": "ERROR", "error": str(exc)}, ensure_ascii=False)
              if args.json else f"[rollback-preflight] ERROR 判定不能（rollback しない）: {exc}", file=sys.stdout if args.json else sys.stderr)
        return 1
    if result["verdict"] == UNSAFE and args.allow_missing_required_tiles:
        result["verdict"] = UNSAFE_OVERRIDDEN
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=1))
    else:
        print(f"[rollback-preflight] target={result['target_version']} verdict={result['verdict']} "
              f"blocked={len(result['blocked'])} warnings={len(result['warnings'])}")
        for c in result["warnings"]:
            print(f"[rollback-preflight] WARNING {c['dataset_id']} ({c['requirement']}) {c['tile_rel_path']}: {c['reason']}")
        for c in result["blocked"]:
            tag = "WARNING missing required tile（--allow-missing-required-tiles で許可）" if args.allow_missing_required_tiles else "BLOCK"
            print(f"[rollback-preflight] {tag} {c['dataset_id']} {c['tile_rel_path']} target={result['target_version']}: {c['reason']}")
    if result["verdict"] == UNSAFE:
        return EXIT_UNSAFE
    return 0


if __name__ == "__main__":
    sys.exit(main())

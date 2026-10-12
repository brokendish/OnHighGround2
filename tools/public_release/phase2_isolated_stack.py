#!/usr/bin/env python3
"""
phase2_isolated_stack.py — Phase 2-B の実機検証 tool（2b2 / 2b3 / 2b4）が使う隔離 stack の共通部品
（PUBLIC-RELEASE-HARNESS-MODERNIZATION、2026-10-12）。

docker-compose.yml は container_name・named volume・network に固定名を持ち、runtime-init・backend 等は
repository の directory（./data_runtime・./data_lake・./data_lake/admin 等）を rw で bind する。検証用の
test project がそれらを上書きし忘れると、実 Local stack の container 名と衝突したり、実 lease volume・
実 data_runtime / data_lake へ書き込んだりする（2026-10-12 の formal で、2b2 / 2b3 の override が Phase 2-B.5 で
追加された runtime-init と lease-coordination volume を上書きしていなかったことが判明）。

この module は:
  1. runtime_init_service(): base compose の runtime-init 定義から、rw bind を seed 済みの一時 directory へ
     機械的に差し替えた service override を作る（対応先の無い rw bind があれば例外 = fail closed）
  2. lease_volume_override(): lease-coordination volume を project 専用名にする
  3. isolation_violations(): 描画済み compose（`docker compose config --format json`）を検査し、
     実 repository への rw bind・実 stack と同じ固定名・実 .env の読み込みを列挙する（値は返さない）
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Dict, List

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
LEASE_VOLUME_KEY = "lease-coordination"


def _base_compose(compose_file: Path = COMPOSE_FILE) -> dict:
    return yaml.safe_load(compose_file.read_text(encoding="utf-8"))


def _bind_parts(entry) -> tuple:
    """short syntax の volume 文字列 → (source, target, mode)。long syntax の dict にも対応する。"""
    if isinstance(entry, dict):
        return entry.get("source"), entry.get("target"), "ro" if entry.get("read_only") else "rw"
    parts = entry.split(":")
    source, target = parts[0], parts[1] if len(parts) > 1 else ""
    mode = parts[2] if len(parts) > 2 else "rw"
    return source, target, mode


# repository 内の rw bind source → seed 済み directory 内の対応 path（seed key, 相対 path）
_RW_REMAP = {
    "./data_runtime": ("data_runtime", ""),
    "./data_lake": ("data_lake", ""),
    "./data_lake/admin": ("data_lake", "admin"),
    "./frontend/layers/railways": ("railways", ""),
    "./osrm": ("osrm", ""),
    "./osrm/foot.lua": ("osrm", "foot.lua"),
}


def service_volumes(service: str, seeded: Dict[str, Path], compose_file: Path = COMPOSE_FILE) -> List[str]:
    """base compose の service の volume を、rw bind だけ seed 済み directory へ差し替えて返す。
    ro bind・named volume（lease 等。名前は top-level で project 専用にする）はそのまま。
    seed 先の無い rw bind があれば例外（fail closed。base compose に rw bind が増えたら tool の更新を要求する）。"""
    base = _base_compose(compose_file)["services"][service]
    volumes: List[str] = []
    for entry in base.get("volumes") or []:
        source, target, mode = _bind_parts(entry)
        if not str(source).startswith((".", "/")):          # named volume
            volumes.append(f"{source}:{target}:{mode}")
        elif mode == "ro":
            volumes.append(f"{source}:{target}:ro")
        elif source in _RW_REMAP and _RW_REMAP[source][0] in seeded:
            key, rel = _RW_REMAP[source]
            volumes.append(f"{(seeded[key] / rel).resolve() if rel else seeded[key].resolve()}:{target}:rw")
        else:
            raise RuntimeError(f"{service} の rw bind に seed 先が無い（隔離できない）: {source}")
    return volumes


def runtime_init_service(container_prefix: str, seeded: Dict[str, Path], compose_file: Path = COMPOSE_FILE) -> dict:
    """runtime-init の override（container_name を project 専用、volume は service_volumes()）。"""
    return {"container_name": f"{container_prefix}-runtime-init",
            "volumes": service_volumes("runtime-init", seeded, compose_file)}


def reset_seeded_staging(seeded: Dict[str, Path]) -> List[str]:
    """seed 済み data_runtime の、runtime-init（init_lease_volume.py）が管理する制御状態を、**複製の側だけで**
    新規 install と同じ状態へ戻す: `.staging` の中身（publish 途中の残留物）と `.publish.lock` を取り除く。

    runtime-init はこれらの owner / mode が期待（operator 10002:10002）と違うと自動修復せず fail closed で止まる。
    Local の data_runtime は host 側の file で、macOS Docker Desktop の file 共有では container 内で設定した owner が
    再現されないことがあり（複製では 0:0 に見える）、また staging の残留物が残ることがある（retention は
    operator-only GC として保留中）。test stack では runtime-init に正しい owner で作り直させる。
    実 repository の data_runtime には触れない（seeded の path が実 repository 配下なら拒否する）。"""
    root = seeded["data_runtime"]
    real = (REPO_ROOT / "data_runtime").resolve()
    if root.resolve() == real or real in root.resolve().parents:
        raise RuntimeError(f"seed 先が実 data_runtime を指している（触れない）: {root}")
    import shutil
    removed: List[str] = []
    staging = root / ".staging"
    if staging.is_dir():
        for child in sorted(staging.iterdir()):
            removed.append(f".staging/{child.name}")
            shutil.rmtree(child) if child.is_dir() and not child.is_symlink() else child.unlink()
    lock = root / ".publish.lock"
    if lock.exists() or lock.is_symlink():
        lock.unlink()
        removed.append(".publish.lock")
    # shelters: init_data_runtime_backend_shelters.py の分類（active / backup / dormant）に無い file は、Local に残った
    # 旧配置の残骸（同 script 導入前の file）。runtime-init はこれを fail closed で拒否するため、複製側だけで除く。
    # 分類は init script 自身の定義を読む（tool 側に二重に持たない）。
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_init_shelters", REPO_ROOT / "scripts" / "publish" / "init_data_runtime_backend_shelters.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    known = set(mod._ACTIVE_FILES) | set(mod._BACKUP_FILES) | set(mod._DORMANT_LEGACY_FILES)
    backend = root / "backend"
    for rel_dir in mod._SHELTER_DIRS:
        d = backend / rel_dir
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            rel = f"{rel_dir}/{f.name}"
            if f.name.startswith(".") or not f.is_file() or rel in known:
                continue
            f.unlink()
            removed.append(f"backend/{rel}")
    return removed


def lease_volume_override(container_prefix: str) -> dict:
    return {LEASE_VOLUME_KEY: {"name": f"{container_prefix}-lease-coordination"}}


def base_fixed_names(compose_file: Path = COMPOSE_FILE) -> dict:
    base = _base_compose(compose_file)
    return {
        "container_name": {v["container_name"] for v in base["services"].values() if v.get("container_name")},
        "volume": {(v or {}).get("name") for v in (base.get("volumes") or {}).values() if (v or {}).get("name")},
        "network": {(v or {}).get("name") for v in (base.get("networks") or {}).values() if (v or {}).get("name")},
    }


def render_config(compose_cmd_prefix: List[str], profiles: List[str]) -> dict:
    """`docker compose ... config --format json`。出力は呼び出し側で値を表示しないこと（environment を含む）。"""
    args = list(compose_cmd_prefix)
    for p in profiles:
        args += ["--profile", p]
    proc = subprocess.run(args + ["config", "--format", "json"], capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(f"compose config failed: {proc.stderr[-500:]}")
    return json.loads(proc.stdout)


def isolation_violations(rendered: dict, allowed_rw_roots: List[Path], repo_root: Path = REPO_ROOT,
                         compose_file: Path = COMPOSE_FILE) -> List[str]:
    """描画済み config の隔離違反（値ではなく service・mount・名前だけを返す）。

    - 実 repository 配下への rw bind（allowed_rw_roots = seed 先の外）
    - 実 stack と同じ固定 container_name / volume name / network name
    - 実 repository の .env / .env.operator を env_file として読む service
    """
    fixed = base_fixed_names(compose_file)
    repo = repo_root.resolve()
    allowed = [Path(p).resolve() for p in allowed_rw_roots]
    out: List[str] = []
    for name, svc in (rendered.get("services") or {}).items():
        if svc.get("container_name") in fixed["container_name"]:
            out.append(f"{name}: container_name が実 stack と同じ（{svc['container_name']}）")
        for m in svc.get("volumes") or []:
            if m.get("type") != "bind" or m.get("read_only"):
                continue
            src = Path(m.get("source", "")).resolve()
            if src == Path("/var/run/docker.sock"):
                continue  # docker.sock 自体の配置は 2b2 / 2b3 の境界 assertion が検査する
            inside_repo = src == repo or repo in src.parents
            inside_allowed = any(src == a or a in src.parents for a in allowed)
            if inside_repo and not inside_allowed:
                out.append(f"{name}: 実 repository への rw bind（{src.relative_to(repo) if src != repo else '.'} -> {m.get('target')}）")
        for ef in svc.get("env_file") or []:
            path = ef.get("path") if isinstance(ef, dict) else ef
            if path and Path(path).name in (".env", ".env.operator", ".env.stream"):
                out.append(f"{name}: 実 {Path(path).name} を env_file として読む")
    for key, vol in (rendered.get("volumes") or {}).items():
        if (vol or {}).get("name") in fixed["volume"]:
            out.append(f"volume {key}: name が実 stack と同じ（{vol['name']}）")
    for key, net in (rendered.get("networks") or {}).items():
        if (net or {}).get("name") in fixed["network"]:
            out.append(f"network {key}: name が実 stack と同じ（{net['name']}）")
    return out

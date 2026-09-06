#!/usr/bin/env python3
"""
init_data_runtime_backend_shelters.py — data_runtime/backend/shelters flat mirror
one-shot initializer.

Residual Finding Remediation 05 Phase B2（DATA-RUNTIME-BACKEND-LEGACY-OWNERSHIP）。

OWNER Section 25 review（least-privilege correction）に従い、directory配下の
non-dot fileを一律同じmetadataへ寄せるのではなく、用途別に明示分類する。

  - active shelter GeoJSON（backend-publicのShelterRegistry fallbackが
    実際にreadする4 file）: owner=operator_uid, group=leases_gid, mode 0640
    （public read可能、leases group経由）
  - recognized backup（*.backup.geojson、pipeline/operatorのrollback用
    artifactでpublic readerの入力ではない）: owner=operator_uid,
    group=operator_gid, mode 0640（leases groupへ公開しない）
  - dormant legacy file（tokyo_shelter.geojson、versioned側に対応が無く
    現在どちらの読込経路からも参照されない）: 一切変更しない
    （SHELTER-FLAT-LEGACY-DUPLICATE finding、別途cleanup検討）
  - unknown file（上記いずれにも一致しない非dotfile）: 自動migrationせず
    fail-closedでSTOPする（想定外の状態変化をsilentに見逃さないため）

directory自体（shelters, shelters/kanagawa, emergency_shelters）は
backend-publicのtraverseが必要なため owner=operator_uid, group=leases_gid,
mode 0750。

対象外: hazard, elevation, tide, weather, data_runtime/backend root自体、
data_runtime/current, data_lake, frontend/tiles。

使い方: root で1回だけ実行する。
    python3 init_data_runtime_backend_shelters.py /data_runtime/backend \
        --operator-uid 10002 --operator-gid 10002 --leases-gid 20001
"""
from __future__ import annotations

import argparse
import os
import stat
import sys

DIR_MODE = 0o750
ACTIVE_FILE_MODE = 0o640
BACKUP_FILE_MODE = 0o640

# backend_root（data_runtime/backend）からの相対path。
_SHELTER_DIRS = (
    "shelters",
    "shelters/kanagawa",
    "emergency_shelters",
)

# active shelter GeoJSON（ShelterRegistryのflat fallbackが実際にreadする対象、
# Phase B2投資調査で確定済み）。basenameで明示する。
_ACTIVE_FILES = (
    "shelters/tokyo-shelter-001.geojson",
    "shelters/kanagawa/kanagawa-evac-001.geojson",
    "shelters/kanagawa/kanagawa-shelter-001.geojson",
    "emergency_shelters/tokyo-evac-001.geojson",
)

# recognized backup（存在する場合のみ対象、"{active basename stem}.backup{ext}"）。
_BACKUP_FILES = (
    "shelters/tokyo-shelter-001.backup.geojson",
    "shelters/kanagawa/kanagawa-shelter-001.backup.geojson",
    "emergency_shelters/tokyo-evac-001.backup.geojson",
)

# dormant legacy file。一切変更しない（SHELTER-FLAT-LEGACY-DUPLICATE）。
_DORMANT_LEGACY_FILES = (
    "shelters/tokyo_shelter.geojson",
)


def _fail(msg: str) -> None:
    print(f"[init_data_runtime_backend_shelters] FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _claim_dir(path: str, uid: int, gid: int, mode: int) -> None:
    if os.path.lexists(path):
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode):
            _fail(f"{path} はdirectoryでない（既存artifactの種別不一致）")
        owner_ok = st.st_uid == uid and st.st_gid == gid
        mode_ok = stat.S_IMODE(st.st_mode) == mode
        if owner_ok and mode_ok:
            print(f"[init_data_runtime_backend_shelters] verified existing dir: {path}")
            return
        os.chown(path, uid, gid)
        os.chmod(path, mode)
        print(f"[init_data_runtime_backend_shelters] claimed dir ownership (non-recursive, contents untouched): {path}")
        return
    os.makedirs(path, mode=mode, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, mode)
    print(f"[init_data_runtime_backend_shelters] created dir: {path}")


def _claim_file(path: str, uid: int, gid: int, mode: int, label: str) -> None:
    if not os.path.lexists(path):
        print(f"[init_data_runtime_backend_shelters] {label} not present, skip: {path}")
        return
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        _fail(f"{path} はregular fileでない（既存artifactの種別不一致）")
    owner_ok = st.st_uid == uid and st.st_gid == gid
    mode_ok = stat.S_IMODE(st.st_mode) == mode
    if owner_ok and mode_ok:
        print(f"[init_data_runtime_backend_shelters] verified existing {label}: {path}")
        return
    os.chown(path, uid, gid)
    os.chmod(path, mode)
    print(f"[init_data_runtime_backend_shelters] claimed {label} ownership: {path}")


def _check_no_unknown_files(backend_root: str) -> None:
    """既知の active/backup/dormant のいずれにも一致しないnon-dot fileが
    存在する場合はfail-closedでSTOPする（想定外の状態変化をsilentに
    見逃さないため）。自動chown/自動生成は一切行わない。"""
    known_rel = set(_ACTIVE_FILES) | set(_BACKUP_FILES) | set(_DORMANT_LEGACY_FILES)
    for rel_dir in _SHELTER_DIRS:
        dir_path = os.path.join(backend_root, rel_dir)
        if not os.path.isdir(dir_path):
            continue
        for name in sorted(os.listdir(dir_path)):
            if name.startswith("."):
                continue
            full_path = os.path.join(dir_path, name)
            if not os.path.isfile(full_path):
                continue  # サブディレクトリ（例: shelters/kanagawa自体）はここでは対象外
            rel_path = os.path.join(rel_dir, name)
            if rel_path not in known_rel:
                _fail(
                    f"未分類のfileを検出（active/backup/dormantのいずれにも一致しない）: "
                    f"{full_path}。自動migrationしない。inventoryを再確認しOWNERへ報告すること。"
                )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("backend_root", help="data_runtime/backend のpath")
    parser.add_argument("--operator-uid", type=int, required=True)
    parser.add_argument("--operator-gid", type=int, required=True)
    parser.add_argument("--leases-gid", type=int, required=True)
    args = parser.parse_args()

    if os.geteuid() != 0:
        _fail("この initializer は root（uid 0）でのみ実行できる")

    operator_uid = args.operator_uid
    operator_gid = args.operator_gid
    leases_gid = args.leases_gid
    backend_root = args.backend_root

    _check_no_unknown_files(backend_root)

    for rel in _SHELTER_DIRS:
        target_dir = os.path.join(backend_root, rel)
        if not os.path.isdir(target_dir):
            print(f"[init_data_runtime_backend_shelters] directory not present, skip: {target_dir}")
            continue
        _claim_dir(target_dir, operator_uid, leases_gid, DIR_MODE)

    for rel in _ACTIVE_FILES:
        _claim_file(os.path.join(backend_root, rel), operator_uid, leases_gid, ACTIVE_FILE_MODE, "active geojson")

    for rel in _BACKUP_FILES:
        _claim_file(os.path.join(backend_root, rel), operator_uid, operator_gid, BACKUP_FILE_MODE, "backup")

    for rel in _DORMANT_LEGACY_FILES:
        path = os.path.join(backend_root, rel)
        if os.path.lexists(path):
            print(f"[init_data_runtime_backend_shelters] dormant legacy file left untouched (SHELTER-FLAT-LEGACY-DUPLICATE): {path}")

    print("[init_data_runtime_backend_shelters] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

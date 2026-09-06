#!/usr/bin/env python3
"""
init_data_runtime_backend.py — data_runtime/backend/hazard flat mirror one-shot initializer.

Residual Finding Remediation 05 Phase B1（DATA-RUNTIME-BACKEND-LEGACY-OWNERSHIP）。

data_runtime/backend/hazard は HazardDatasetService（backend/app/api/hazards.py
の汎用route）が実際にpublic responseへ配信するflat mirrorであり、
pipeline_service._reload_hazard_backend_mirror() がbackend-operator（UID 10002）
からshutil.copy2()で既存destinationを直接上書きする、現役のactive artifact
領域である。VPS in-place rebuildのUID hardening対象から漏れており、host
debian（UID 1000、最初期の手動bootstrap成果物）またはroot（UID 0、UID
hardening以前のadmin pipeline実行結果）所有のまま残っていたため、rebuild後
operatorがこの領域へ一度も正常に書込めていなかった（次回deploy jobが
shutil.copy2で既存fileを上書きしようとするとEACCESになる）。

対象は data_runtime/backend/hazard 配下のみ（Phase B1 scope）。
shelters/elevation/tide/weather、data_runtime/backend root自体、
data_runtime/current（versioned/lease保護側、既に10002:20001 mode 0750で
是正済みの別実体）には一切触れない。

owner/group/mode contractは、既に正しくhardening済みのdata_runtime/current
側（versioned hazard mirror）をVPS実機statで確認した値をそのまま踏襲する
（setgidビットなし、明示的なchown/chmodによる契約であり、ディレクトリの
setgid継承には依存しない設計）：

  directory: owner=operator_uid, group=leases_gid, mode 0750
  file:      owner=operator_uid, group=leases_gid, mode 0640

init_lease_volume.py / init_data_lake_admin.py と同じ設計方針（root専用
one-shot、非recursive、単一inode処理、既存non-emptyなdirectoryでもfail-closed
にしない、明示的なfile一覧によるinventory-basedなmigration、content変更なし）
を踏襲する。

使い方: root で1回だけ実行する。
    python3 init_data_runtime_backend.py /data_runtime/backend/hazard \
        --operator-uid 10002 --operator-gid 10002 --leases-gid 20001
"""
from __future__ import annotations

import argparse
import os
import stat
import sys

DIR_MODE = 0o750
FILE_MODE = 0o640

# 対象拡張子（非recursive、type directory直下1階層のみ）。
# .gitkeep等のdotfileは対象外（Git tracking境界とruntime ownership境界は
# 独立に扱う。data_runtime/backend配下は元々Git非trackedであることを
# 事前調査で確認済み）。
_HAZARD_FILE_GLOB = "*.geojson"
_HAZARD_FILE_GLOB_ALT = "*.geojsonl"

_HAZARD_TYPES = (
    "flood",
    "inland_flood",
    "landslide",
    "storm_surge",
    "tsunami",
    "lowland_poor_drainage",
    "pseudo_inland_flood",
)


def _fail(msg: str) -> None:
    print(f"[init_data_runtime_backend] FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _claim_dir(path: str, uid: int, gid: int, mode: int) -> None:
    """directory自身のowner/modeを設定する（非recursive、配下contentには触れない）。

    data_runtime/backend/hazard配下のtype directoryは実運用では常に非empty
    （既存hazard GeoJSONを含む）であるため、非emptyをfail-closedの対象に
    しない（data_runtime root自身や data_lake/admin と同じ扱い）。
    """
    if os.path.lexists(path):
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode):
            _fail(f"{path} はdirectoryでない（既存artifactの種別不一致）")
        owner_ok = st.st_uid == uid and st.st_gid == gid
        mode_ok = stat.S_IMODE(st.st_mode) == mode
        if owner_ok and mode_ok:
            print(f"[init_data_runtime_backend] verified existing dir: {path}")
            return
        os.chown(path, uid, gid)
        os.chmod(path, mode)
        print(f"[init_data_runtime_backend] claimed dir ownership (non-recursive, contents untouched): {path}")
        return
    os.makedirs(path, mode=mode, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, mode)  # mkdirのmodeはumaskの影響を受けるため明示的に再設定する
    print(f"[init_data_runtime_backend] created dir: {path}")


def _claim_file(path: str, uid: int, gid: int, mode: int) -> None:
    if not os.path.lexists(path):
        return
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        _fail(f"{path} はregular fileでない（既存artifactの種別不一致）")
    owner_ok = st.st_uid == uid and st.st_gid == gid
    mode_ok = stat.S_IMODE(st.st_mode) == mode
    if owner_ok and mode_ok:
        print(f"[init_data_runtime_backend] verified existing file: {path}")
        return
    os.chown(path, uid, gid)
    os.chmod(path, mode)
    print(f"[init_data_runtime_backend] claimed file ownership: {path}")


def _claim_existing_files_in_dir(dir_path: str, uid: int, gid: int, mode: int) -> int:
    """dir_path直下（非recursive）の *.geojson / *.geojsonl のみinventoryし、
    1件ずつownershipを是正する。dotfile・subdirectory・symlink・その他拡張子
    には一切触れない。"""
    import fnmatch

    if not os.path.isdir(dir_path):
        return 0
    count = 0
    for name in sorted(os.listdir(dir_path)):
        if name.startswith("."):
            continue
        if not (fnmatch.fnmatch(name, _HAZARD_FILE_GLOB) or fnmatch.fnmatch(name, _HAZARD_FILE_GLOB_ALT)):
            continue
        full_path = os.path.join(dir_path, name)
        st = os.lstat(full_path)
        if not stat.S_ISREG(st.st_mode):
            continue
        _claim_file(full_path, uid, gid, mode)
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hazard_root", help="data_runtime/backend/hazard のpath")
    parser.add_argument("--operator-uid", type=int, required=True)
    parser.add_argument("--operator-gid", type=int, required=True)
    parser.add_argument("--leases-gid", type=int, required=True, help="public read共有先の supplemental GID（例: 20001）")
    args = parser.parse_args()

    if os.geteuid() != 0:
        _fail("この initializer は root（uid 0）でのみ実行できる")

    root = args.hazard_root
    operator_uid = args.operator_uid
    leases_gid = args.leases_gid

    # hazard root自体（backend rootは対象外、Phase B1 scopeはhazardのみ）
    _claim_dir(root, operator_uid, leases_gid, DIR_MODE)

    total_files = 0
    for hazard_type in _HAZARD_TYPES:
        type_dir = os.path.join(root, hazard_type)
        if not os.path.isdir(type_dir):
            print(f"[init_data_runtime_backend] type directory not present, skip: {type_dir}")
            continue
        _claim_dir(type_dir, operator_uid, leases_gid, DIR_MODE)
        total_files += _claim_existing_files_in_dir(type_dir, operator_uid, leases_gid, FILE_MODE)

    print(f"[init_data_runtime_backend] OK (files claimed/verified: {total_files})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

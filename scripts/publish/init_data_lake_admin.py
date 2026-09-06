#!/usr/bin/env python3
"""
init_data_lake_admin.py — data_lake/admin runtime metadata境界 one-shot initializer.

Residual Finding Remediation 03（DATA-LAKE-ADMIN-WRITER-CONTRACT）。

data_lake/admin配下（state/jobs/history/logs、boot_state.json、
active_mappings.json）は本来backend-operator（UID 10002）が正規writerだが、
host debian（UID 1000）所有・mode 0755のまま、VPS in-place rebuildの
UID hardening対象から漏れていた。その結果、operatorが実際には
これらのfile/directoryへ書込めず、DatasetStateService.save()等が
`[Errno 13] Permission denied`でgraceful失敗し続け、
operator_audit_log.pyに至っては`AuditSinkError`によりoperator認証成功時
でもHTTP 500を返す状態になっていた。

このinitializerは、scripts/publish/init_lease_volume.pyと同じ設計方針
（root専用one-shot、既存artifactのowner/mode不一致をchmod -R/chown -Rで
自動修復しない、非emptyかつ不一致ならfail-closed）を踏襲し、
data_lake/admin配下のdirectory 5件・file 2件のsingle-inode metadataと、
各directory直下の既存runtime metadata file（拡張子で絞り込んだ1階層のみ、
再帰なし）のownership/modeをoperator writer contractへ是正する。

writer contract（第3節）:
  A. operator writer + public reader（public traverse/read が必要）:
     data_lake/admin            (root, publicがstate/active_mappingsへ
                                  traverseするため)
     data_lake/admin/state
     data_lake/admin/active_mappings.json
  B. operator-only:
     data_lake/admin/jobs
     data_lake/admin/history
     data_lake/admin/logs
     data_lake/admin/boot_state.json

directory: owner=operator_uid, group=(A: leases_gid / B: operator_gid), mode 0o2750
file:      owner=operator_uid, group=(A: leases_gid / B: operator_gid), mode 0o0640

使い方: root で1回だけ実行する。
    python3 init_data_lake_admin.py /data_lake/admin \
        --operator-uid 10002 --operator-gid 10002 --leases-gid 20001
"""
from __future__ import annotations

import argparse
import os
import stat
import sys

DIR_MODE = 0o2750
FILE_MODE = 0o0640

# 各directory直下（非recursive）で対象とする既存runtime metadata fileの拡張子。
# .gitkeep等のdotfileは対象外（Gitのtracking境界とruntime ownership境界は別途
# .gitignoreで解消済み、このinitializerはownershipのみを扱う）。
_STATE_FILE_GLOB = "*.json"
_JOBS_FILE_GLOB = "*.json"
_HISTORY_FILE_GLOB = "*.jsonl"
_LOGS_FILE_GLOB = "*.log"


def _fail(msg: str) -> None:
    print(f"[init_data_lake_admin] FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _claim_dir(path: str, uid: int, gid: int, mode: int) -> None:
    """directory自身のowner/modeを設定する（非recursive、配下contentには触れない）。

    data_lake/admin配下のdirectoryは実運用では常に非empty（既存のjob履歴・
    state file等を含む）であるため、init_lease_volume.pyの
    `_verify_or_create_dir()`が持つ「非emptyならfail-closed」判定は適用しない
    （data_runtime rootに対する`_claim_data_runtime_root()`と同じ考え方）。
    ここで行うのは単一inodeへのchown/chmodのみであり、
    「chmod -R/chown -R禁止」原則が対象とする再帰操作ではない。
    """
    if os.path.lexists(path):
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode):
            _fail(f"{path} はdirectoryでない（既存artifactの種別不一致）")
        owner_ok = st.st_uid == uid and st.st_gid == gid
        mode_ok = stat.S_IMODE(st.st_mode) == mode
        if owner_ok and mode_ok:
            print(f"[init_data_lake_admin] verified existing dir: {path}")
            return
        os.chown(path, uid, gid)
        os.chmod(path, mode)
        print(f"[init_data_lake_admin] claimed dir ownership (non-recursive, contents untouched): {path}")
        return
    os.makedirs(path, mode=mode, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, mode)  # mkdirのmodeはumaskの影響を受けるため明示的に再設定する
    print(f"[init_data_lake_admin] created dir: {path}")


def _claim_file(path: str, uid: int, gid: int, mode: int) -> None:
    """既存fileのowner/modeを設定する。存在しない場合は何もしない
    （runtime-generated fileの内容を作り替えない、fresh installでは
    各serviceが初回書込時に自然に生成する）。"""
    if not os.path.lexists(path):
        print(f"[init_data_lake_admin] file not present yet (ok, will be created by service on first write): {path}")
        return
    st = os.lstat(path)
    if not stat.S_ISREG(st.st_mode):
        _fail(f"{path} はregular fileでない（既存artifactの種別不一致）")
    owner_ok = st.st_uid == uid and st.st_gid == gid
    mode_ok = stat.S_IMODE(st.st_mode) == mode
    if owner_ok and mode_ok:
        print(f"[init_data_lake_admin] verified existing file: {path}")
        return
    os.chown(path, uid, gid)
    os.chmod(path, mode)
    print(f"[init_data_lake_admin] claimed file ownership: {path}")


def _claim_existing_files_in_dir(dir_path: str, glob_pattern: str, uid: int, gid: int, mode: int) -> int:
    """dir_path直下（非recursive）で glob_pattern に一致する既存regular fileのみ
    inventoryし、1件ずつownershipを是正する。dotfile・subdirectory・symlink等
    パターンに一致しないものには一切触れない。

    Returns: 処理したfile数。
    """
    import fnmatch

    if not os.path.isdir(dir_path):
        return 0
    count = 0
    for name in sorted(os.listdir(dir_path)):
        if name.startswith("."):
            continue
        if not fnmatch.fnmatch(name, glob_pattern):
            continue
        full_path = os.path.join(dir_path, name)
        st = os.lstat(full_path)
        if not stat.S_ISREG(st.st_mode):
            continue  # symlink/directory等はglobで既に除外されるはずだが念のためskip
        _claim_file(full_path, uid, gid, mode)
        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("admin_root", help="data_lake/admin のpath")
    parser.add_argument("--operator-uid", type=int, required=True)
    parser.add_argument("--operator-gid", type=int, required=True)
    parser.add_argument("--leases-gid", type=int, required=True, help="public read共有先の supplemental GID（例: 20001）")
    args = parser.parse_args()

    if os.geteuid() != 0:
        _fail("この initializer は root（uid 0）でのみ実行できる")

    root = args.admin_root
    operator_uid = args.operator_uid
    operator_gid = args.operator_gid
    leases_gid = args.leases_gid

    state_dir = os.path.join(root, "state")
    jobs_dir = os.path.join(root, "jobs")
    history_dir = os.path.join(root, "history")
    logs_dir = os.path.join(root, "logs")
    boot_state_path = os.path.join(root, "boot_state.json")
    active_mappings_path = os.path.join(root, "active_mappings.json")

    # admin root自体: publicがstate/active_mappings.jsonへtraverseする必要があるため
    # leases_gidを付与する（データ本体のdata_lake/{raw,normalized,validated,tiles}等
    # 兄弟directoryには一切触れない）。
    _claim_dir(root, operator_uid, leases_gid, DIR_MODE)

    # A. operator writer + public reader
    _claim_dir(state_dir, operator_uid, leases_gid, DIR_MODE)
    _claim_existing_files_in_dir(state_dir, _STATE_FILE_GLOB, operator_uid, leases_gid, FILE_MODE)
    _claim_file(active_mappings_path, operator_uid, leases_gid, FILE_MODE)

    # B. operator-only
    _claim_dir(jobs_dir, operator_uid, operator_gid, DIR_MODE)
    _claim_existing_files_in_dir(jobs_dir, _JOBS_FILE_GLOB, operator_uid, operator_gid, FILE_MODE)

    _claim_dir(history_dir, operator_uid, operator_gid, DIR_MODE)
    _claim_existing_files_in_dir(history_dir, _HISTORY_FILE_GLOB, operator_uid, operator_gid, FILE_MODE)

    _claim_dir(logs_dir, operator_uid, operator_gid, DIR_MODE)
    _claim_existing_files_in_dir(logs_dir, _LOGS_FILE_GLOB, operator_uid, operator_gid, FILE_MODE)

    _claim_file(boot_state_path, operator_uid, operator_gid, FILE_MODE)

    print("[init_data_lake_admin] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

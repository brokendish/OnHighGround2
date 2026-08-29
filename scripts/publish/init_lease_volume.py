#!/usr/bin/env python3
"""
init_lease_volume.py — Phase 2-B.5 lease coordination volume one-shot initializer.

tasks/public-release/phase2b5_claude_implementation_instruction.md 第4.3節。

network なし・Docker socket なしの one-shot initializer だけが root で
root directory・3 directory・coordination.lock・初期 clock.state を作成する。

- operator profile なしでも public 起動前に完了できる
- 既存 volume の owner/mode 不一致を chmod -R / chown -R で自動修復しない
- 再実行は正規 artifact を検証するだけで、active/lock/tombstone を
  削除・置換・再所有化しない
- initializer 失敗時は非0 exit する（public を起動させない）

使い方: root で1回だけ実行する（Compose one-shot service経由を想定）。
    python3 init_lease_volume.py /run/onhighground2/leases \
        --public-uid 10001 --operator-uid 10002 --leases-gid 20001
"""
from __future__ import annotations

import argparse
import os
import stat
import sys
import time

ROOT_MODE = 0o2770
SUBDIR_MODE = 0o3770
COORD_LOCK_MODE = 0o0660
CLOCK_STATE_MODE = 0o0660


def _fail(msg: str) -> None:
    print(f"[init_lease_volume] FAIL: {msg}", file=sys.stderr)
    sys.exit(1)


def _verify_or_create_dir(path: str, uid: int, gid: int, mode: int) -> None:
    if os.path.lexists(path):
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode):
            _fail(f"{path} はdirectoryでない（既存artifactの種別不一致）")

        owner_ok = st.st_uid == uid and st.st_gid == gid
        mode_ok = stat.S_IMODE(st.st_mode) == mode

        if not owner_ok or not mode_ok:
            # Docker named volumeの新規mount pointは、初回mount時にroot:root
            # のemptyディレクトリとして自動生成される。これは「既存artifact」
            # ではなく「未初期化のvolume」であり、中身が空である場合に限り
            # 初回だけowner/modeを設定してよい（第4.3節「再実行は正規artifactを
            # 検証するだけ」の対象は、既にlease関連artifactが存在する場合）。
            # 非emptyでowner/modeが不一致の場合は、実artifactを誤って
            # 上書きしないためfail-closedする（chmod -R/chown -R禁止）。
            if os.listdir(path):
                _fail(
                    f"{path} のowner/mode不一致（自動修復しない、非emptyのため）: "
                    f"expected={uid}:{gid}/{oct(mode)} "
                    f"actual={st.st_uid}:{st.st_gid}/{oct(stat.S_IMODE(st.st_mode))}"
                )
            os.chown(path, uid, gid)
            os.chmod(path, mode)
            print(f"[init_lease_volume] claimed fresh empty dir: {path}")
            return

        print(f"[init_lease_volume] verified existing dir: {path}")
        return
    os.mkdir(path, mode)
    os.chown(path, uid, gid)
    os.chmod(path, mode)  # mkdirのmodeはumaskの影響を受けるため明示的に再設定する
    print(f"[init_lease_volume] created dir: {path}")


def _claim_data_runtime_root(path: str, uid: int, gid: int, mode: int) -> None:
    """data_runtime root自身のowner/modeを設定する。.staging/versions等の
    子artifactと異なり、data_runtime自体は実運用では常に非empty
    （既存のflat runtime data・tide/weather/jartic等の運用dataを含む）である
    ため、_verify_or_create_dir()の「非emptyならfail-closed」は適用しない。
    ここで行うのはroot directory自身のmetadata変更のみ（非recursive、
    配下のcontentには一切触れない、単一inodeへのchown/chmod）であり、
    「chmod -R/chown -R禁止」の対象（配下を巻き込む再帰操作）ではない。"""
    if os.path.lexists(path):
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode):
            _fail(f"{path} はdirectoryでない（既存artifactの種別不一致）")
        owner_ok = st.st_uid == uid and st.st_gid == gid
        mode_ok = stat.S_IMODE(st.st_mode) == mode
        if owner_ok and mode_ok:
            print(f"[init_lease_volume] verified existing dir: {path}")
            return
        os.chown(path, uid, gid)
        os.chmod(path, mode)
        print(f"[init_lease_volume] claimed data_runtime root ownership (non-recursive, contents untouched): {path}")
        return
    os.makedirs(path, mode=mode, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, mode)
    print(f"[init_lease_volume] created dir: {path}")


def _verify_or_create_file(path: str, uid: int, gid: int, mode: int, initial_content: bytes) -> None:
    if os.path.lexists(path):
        st = os.lstat(path)
        if not stat.S_ISREG(st.st_mode):
            _fail(f"{path} はregular fileでない")
        if st.st_uid != uid or st.st_gid != gid:
            _fail(f"{path} のowner不一致（自動修復しない）: expected={uid}:{gid} actual={st.st_uid}:{st.st_gid}")
        actual_mode = stat.S_IMODE(st.st_mode)
        if actual_mode != mode:
            _fail(f"{path} のmode不一致（自動修復しない）: expected={oct(mode)} actual={oct(actual_mode)}")
        print(f"[init_lease_volume] verified existing file: {path}")
        return
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, mode)
    try:
        os.write(fd, initial_content)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chown(path, uid, gid)
    os.chmod(path, mode)
    print(f"[init_lease_volume] created file: {path}")


PUBLISH_LOCK_MODE = 0o0600
STAGING_DIR_MODE = 0o2750
VERSIONS_DIR_MODE = 0o2750
# CODEX P2B5-CX-007（第2ラウンド）permission matrix拡張作業中に発見した実バグ:
# data_runtime直下（.staging/versions/.publish.lockの親）自体のowner/modeは
# これまでどのcodeも一切管理しておらず、host bind mount作成時の状態
# （典型的にはroot:root、mkdirの既定umask依存）に委ねられていた。この場合
# operatorがcurrent symlinkを新規作成できない、あるいはpublicが
# current/versions配下を辿れない、という実害を実Linux named volumeで確認した。
# operator（新規current作成に owner rwxが必要）とpublic（current読取に
# traverseのr-xが必要）が共に持つsupplemental group（leases_gid）を
# data_runtime自身のgroupとすることで、両者が満たすべき最小権限を確立する。
DATA_RUNTIME_ROOT_MODE = 0o750


def _init_data_runtime_publish_tree(
    data_runtime_root: str, operator_uid: int, operator_gid: int, leases_gid: int
) -> None:
    """data_runtime/{.staging,versions,.publish.lock} の一回限り初期化（第5.1節）。
    data_runtimeはhost bind mountのため、operator uid/gidでの実行時にのみ
    正しい数値ownershipが付与される（host filesystemのuid写像に依存する）。"""
    _claim_data_runtime_root(data_runtime_root, operator_uid, leases_gid, DATA_RUNTIME_ROOT_MODE)
    _verify_or_create_dir(os.path.join(data_runtime_root, ".staging"), operator_uid, operator_gid, STAGING_DIR_MODE)
    _verify_or_create_dir(os.path.join(data_runtime_root, "versions"), operator_uid, operator_gid, VERSIONS_DIR_MODE)
    _verify_or_create_file(
        os.path.join(data_runtime_root, ".publish.lock"),
        operator_uid, operator_gid, PUBLISH_LOCK_MODE, b"",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("leases_root")
    parser.add_argument("--data-runtime-root", default=None, help="data_runtime/{.staging,versions,.publish.lock}も初期化する場合に指定")
    parser.add_argument("--public-uid", type=int, required=True)
    parser.add_argument("--public-gid", type=int, required=True)
    parser.add_argument("--operator-uid", type=int, required=True)
    parser.add_argument("--operator-gid", type=int, required=True)
    parser.add_argument("--leases-gid", type=int, required=True, help="supplemental GID共有先（例: 20001）")
    args = parser.parse_args()

    if os.geteuid() != 0:
        _fail("この initializer は root（uid 0）でのみ実行できる")

    root = args.leases_root
    os.makedirs(os.path.dirname(root) or "/", exist_ok=True)

    _verify_or_create_dir(root, args.operator_uid, args.leases_gid, ROOT_MODE)
    _verify_or_create_dir(os.path.join(root, "active"), args.operator_uid, args.leases_gid, SUBDIR_MODE)
    _verify_or_create_dir(os.path.join(root, "locks"), args.operator_uid, args.leases_gid, SUBDIR_MODE)
    _verify_or_create_dir(os.path.join(root, "retired"), args.operator_uid, args.leases_gid, SUBDIR_MODE)
    _verify_or_create_file(
        os.path.join(root, "coordination.lock"),
        args.operator_uid, args.leases_gid, COORD_LOCK_MODE, b"",
    )
    _verify_or_create_file(
        os.path.join(root, "clock.state"),
        args.operator_uid, args.leases_gid, CLOCK_STATE_MODE, str(time.time()).encode("utf-8"),
    )

    if args.data_runtime_root:
        _init_data_runtime_publish_tree(args.data_runtime_root, args.operator_uid, args.operator_gid, args.leases_gid)

    print("[init_lease_volume] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

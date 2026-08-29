"""
runtime_atomic.py — Phase 2-B.5 atomic runtime data publish primitives.

tasks/public-release/phase2b5_claude_implementation_instruction.md 第4〜5節。

data_runtime/ 配下の "現在稼働中のversion" を、稼働中readerが部分更新・
混在versionを一切観測しないatomic version切替へ更新するための低レベル
primitiveを提供する。

このmoduleはLinux専用である（renameat2, dir_fd相対syscallに依存する）。
python:3.11-slim（glibc）のcontainer内でのみ動作を保証する。

設計原則（禁止事項の裏返し）:
  - runtime destinationへの直接cp/rsync --inplaceは行わない
  - currentのunlink後createは行わない
  - 部分file単位のcurrent tree上書きは行わない
  - cross-filesystem renameは行わない（同一device検証を必須にする）
  - validation前にversions/currentを公開しない
  - version destinationのreplaceは行わない（no-replace primitiveのみ）
  - 失敗を成功へ読み替えるfallbackは行わない
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import fcntl
import grp
import os
import re
import shutil
import stat
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

# Phase 2-B.5限定修正: renameat2/dir_fd相対syscallへの依存はLinux専用だが、
# それを理由にmodule import自体を失敗させると、macOS開発機で
# `import app_public`（Phase 2-B.1 import graph回帰テスト等、containerを
# 経由しないhost実行）が丸ごと壊れる（実際にPhase 2-B.1回帰で検出・修正）。
# importは全platformで成功させ、Linux専用syscallの解決はrenameat2_noreplace()
# 呼び出し時まで遅延する。呼び出されない限りmacOS上でも安全にimportできる。
_libc = None
_renameat2_available: Optional[bool] = None


def _ensure_libc() -> None:
    global _libc, _renameat2_available
    if _renameat2_available is not None:
        if not _renameat2_available:
            raise RuntimeAtomicError(
                f"renameat2はこのplatformで利用不能（platform={sys.platform}）。"
                "atomic publish/leaseの活性化処理はLinux container内でのみ実行できる。"
            )
        return
    if sys.platform != "linux":
        _renameat2_available = False
        raise RuntimeAtomicError(
            f"renameat2はこのplatformで利用不能（platform={sys.platform}）。"
            "atomic publish/leaseの活性化処理はLinux container内でのみ実行できる。"
        )
    libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
    if not hasattr(libc, "renameat2"):
        _renameat2_available = False
        raise RuntimeAtomicError("この環境のglibcはrenameat2()を提供していない")
    libc.renameat2.argtypes = [
        ctypes.c_int, ctypes.c_char_p,
        ctypes.c_int, ctypes.c_char_p,
        ctypes.c_uint,
    ]
    libc.renameat2.restype = ctypes.c_int
    _libc = libc
    _renameat2_available = True


RENAME_NOREPLACE = 0x1
AT_FDCWD = -100


class RuntimeAtomicError(Exception):
    """fail-closed境界。呼び出し側はこれをcatchして安全側に倒すこと。"""


def renameat2_noreplace(src_dir_fd: int, src_name: str, dst_dir_fd: int, dst_name: str) -> None:
    """renameat2(RENAME_NOREPLACE) — destが既に存在すればerrno=EEXISTで例外。

    単一syscallでcheck-then-renameのTOCTOUを排除する（禁止事項:
    「check-then-rename」「no-replace非対応時fallback」）。
    """
    _ensure_libc()
    ret = _libc.renameat2(
        src_dir_fd, src_name.encode("utf-8"),
        dst_dir_fd, dst_name.encode("utf-8"),
        RENAME_NOREPLACE,
    )
    if ret != 0:
        err = ctypes.get_errno()
        if err == errno.EEXIST:
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), dst_name)
        if err == errno.EXDEV:
            raise RuntimeAtomicError(f"cross-filesystem rename拒否（EXDEV）: {src_name} -> {dst_name}")
        if err == errno.EINVAL:
            raise RuntimeAtomicError(
                f"RENAME_NOREPLACEが非対応（EINVAL）: filesystemがrenameat2 flagsをサポートしない"
            )
        raise OSError(err, os.strerror(err), dst_name)


def fsync_dir(dir_fd: int) -> None:
    """directory entryの永続化。file fsyncだけではrename/create/unlinkの
    directory entry自体は永続化されないため、必ず対になるdirectory fsyncを行う。"""
    os.fsync(dir_fd)


def fsync_path(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextmanager
def open_dir_fd(path: Path) -> Iterator[int]:
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield fd
    finally:
        os.close(fd)


def same_device(a: Path, b: Path) -> bool:
    return os.stat(a).st_dev == os.stat(b).st_dev


# ── capacity fail-closed gate（CODEX P2B5-CX-005第2ラウンド対応） ────────
# 旧実装はcapacity/inode/tombstone上限をRuntimeGcの事前検証にしか実装して
# おらず、GC実行時以外（publish、reader新規lease acquire）は無制限に容量・
# inodeを消費し続けられた。「上限超過時はpublish／new acquireも停止する」
# という指示書第8節の要求へ、publish()と_acquire_once()双方から呼べる
# 共通gateとしてここへ実装する。
def check_capacity_or_raise(path: Path, min_free_bytes: Optional[int], min_free_inodes: Optional[int]) -> None:
    """`path`が乗るfilesystemの空き容量・空きinodeを検証し、閾値未満なら
    RuntimeAtomicErrorで拒否する（fail-closed）。閾値がNoneの項目は
    skipする（呼び出し側が明示的に無効化した場合のみ）。"""
    if min_free_bytes is not None:
        usage = shutil.disk_usage(path)
        if usage.free < min_free_bytes:
            raise RuntimeAtomicError(
                f"空き容量不足（free={usage.free} < threshold={min_free_bytes}）: {path}"
            )
    if min_free_inodes is not None and hasattr(os, "statvfs"):
        try:
            vfs = os.statvfs(path)
            free_inodes = vfs.f_favail
            if free_inodes > 0 and free_inodes < min_free_inodes:
                raise RuntimeAtomicError(
                    f"空きinode不足（free_inodes={free_inodes} < threshold={min_free_inodes}）: {path}"
                )
        except (AttributeError, OSError):
            pass


# ── version ID ──────────────────────────────────────────────────────────
# caller提供の任意pathではなく、規定形式の一意IDだけを許可する。
# 形式: <UTC compact timestamp>-<8 hex>  例: 20260811T120000Z-a1b2c3d4
# `/`、`..`、NUL、絶対path、path separator、想定外suffixを拒否する。
_VERSION_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$")


def generate_version_id() -> str:
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{ts}-{uuid.uuid4().hex[:8]}"


def validate_version_id(version_id: str) -> str:
    if not isinstance(version_id, str) or not _VERSION_ID_RE.fullmatch(version_id):
        raise RuntimeAtomicError(f"不正なversion ID形式: {version_id!r}")
    if "/" in version_id or ".." in version_id or "\x00" in version_id:
        raise RuntimeAtomicError(f"version IDにpath構成要素が含まれる: {version_id!r}")
    return version_id


# ── process identity検証（第4.2節） ────────────────────────────────────
@dataclass(frozen=True)
class ExpectedIdentity:
    uid: int
    gid: int
    supplemental_gids: frozenset
    umask: int


def verify_process_identity(expected: ExpectedIdentity) -> None:
    """起動直後にeuid/egid/supplemental groups/umaskを検証する。
    user名の解決には依存しない（数値のみ比較）。不一致ならRuntimeAtomicError。"""
    euid = os.geteuid()
    egid = os.getegid()
    if euid != expected.uid:
        raise RuntimeAtomicError(f"euid不一致: expected={expected.uid} actual={euid}")
    if egid != expected.gid:
        raise RuntimeAtomicError(f"egid不一致: expected={expected.gid} actual={egid}")

    actual_groups = frozenset(os.getgroups())
    missing = expected.supplemental_gids - actual_groups
    if missing:
        raise RuntimeAtomicError(f"supplemental group不足: missing={sorted(missing)} actual={sorted(actual_groups)}")

    # umaskはprocess-globalなので取得のために一度set→即座に戻す（atomic性への影響なし、起動直後のみ実施）。
    current_umask = os.umask(expected.umask)
    os.umask(current_umask)
    if current_umask != expected.umask:
        raise RuntimeAtomicError(f"umask不一致: expected={oct(expected.umask)} actual={oct(current_umask)}")


def verify_path_owner_mode(path: Path, expect_uid: int, expect_gid: int, expect_mode: int) -> None:
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        raise RuntimeAtomicError(f"symlinkは許可されない: {path}")
    if st.st_uid != expect_uid or st.st_gid != expect_gid:
        raise RuntimeAtomicError(
            f"owner不一致: {path} expected={expect_uid}:{expect_gid} actual={st.st_uid}:{st.st_gid}"
        )
    actual_mode = stat.S_IMODE(st.st_mode)
    if actual_mode != expect_mode:
        raise RuntimeAtomicError(f"mode不一致: {path} expected={oct(expect_mode)} actual={oct(actual_mode)}")


# ── writer lock（第5.2節） ──────────────────────────────────────────────
class WriterLock:
    """data_runtime/.publish.lock — operator専用のexclusive lock。

    publish / rollback / version GCのcurrent判定・切替区間を直列化する。
    stable inodeのregular fileをflock(2)で保護する。lock fileは
    unlink/rename/truncateしない（禁止事項）。
    """

    def __init__(self, lock_path: Path, expect_uid: int, expect_gid: int, timeout_s: float = 30.0):
        self._lock_path = lock_path
        self._expect_uid = expect_uid
        self._expect_gid = expect_gid
        self._timeout_s = timeout_s
        self._fd: Optional[int] = None

    def __enter__(self) -> "WriterLock":
        if not self._lock_path.exists():
            raise RuntimeAtomicError(f"writer lock fileが存在しない（initializer未実行）: {self._lock_path}")
        verify_path_owner_mode(self._lock_path, self._expect_uid, self._expect_gid, 0o600)

        fd = os.open(str(self._lock_path), os.O_RDWR)
        try:
            st_by_fd = os.fstat(fd)
            st_by_path = os.stat(self._lock_path)
            if st_by_fd.st_ino != st_by_path.st_ino or st_by_fd.st_dev != st_by_path.st_dev:
                raise RuntimeAtomicError("writer lock fileのinodeがopen後に変化した（TOCTOU検出）")
            if st_by_fd.st_nlink != 1:
                raise RuntimeAtomicError(f"writer lock fileのlink countが異常: {st_by_fd.st_nlink}")

            deadline = time.monotonic() + self._timeout_s
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise RuntimeAtomicError(
                            f"writer lock取得timeout（{self._timeout_s}s）: 同時publish/rollback/GCを検出、busyとして拒否"
                        )
                    time.sleep(0.2)
        except Exception:
            os.close(fd)
            raise
        self._fd = fd
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

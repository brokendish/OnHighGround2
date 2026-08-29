"""
runtime_publish.py — Phase 2-B.5 atomic version publish / rollback orchestration.

tasks/public-release/phase2b5_claude_implementation_instruction.md 第5節。

data_runtime/
  .staging/<version-id>/   ← caller（deploy_to_runtime.sh / operator CLI）が
                              全datasetを生成する（このmoduleの責務外）
  versions/<version-id>/
  current -> versions/<version-id>
  .publish.lock

このmoduleは「staging済みのversionをvalidateして安全にcurrentへ活性化する」
という活性化(activation)部分だけを扱う。dataset本体の生成ロジックは
呼び出し側（scripts/publish/deploy_to_runtime.sh 等）が担う。
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .runtime_atomic import (
    RuntimeAtomicError,
    WriterLock,
    check_capacity_or_raise,
    fsync_dir,
    fsync_path,
    open_dir_fd,
    renameat2_noreplace,
    same_device,
    validate_version_id,
    verify_path_owner_mode,
)
from .runtime_dataset_validate import verify_manifest_matches_disk

# CODEX P2B5-CX-005（第2ラウンド）対応: RuntimeGcの事前検証と同じ既定値。
# publish()もこの閾値未満では新規versionを公開しない（fail-closed）。
DEFAULT_CAPACITY_MIN_FREE_BYTES = 1024 ** 3  # 1 GiB
DEFAULT_MIN_FREE_INODES = 1000

logger = logging.getLogger(__name__)

VERSION_DIR_MODE = 0o750
VERSION_FILE_MODE = 0o640
LOCK_FILE_MODE = 0o600

# CODEX P2B5-CX-006（第3ラウンド）対応: current rename直後のdirectory fsyncは
# 「renameそのもの」ではなく「renameの耐久性（クラッシュ時の生存）」だけを
# 保証する。POSIX rename(2)はsyscallが成功した時点で既にatomicにcurrentの
# targetを書き換えているため、その後のfsync failureで「currentを元へ戻す」
# ことは原理的に不可能（rename済みの状態を後から取り消す手段がない）。
# 以下のretryとPublishDurabilityErrorは、この構造的制約を隠さず明示する
# ための実装である。「old currentのtarget/inode/hashが不変」という要求は
# swap"直前"（symlink作成・renameat2直後、versions_fdのfsync）にのみ
# 適用可能であり、swap"直後"（current rename後、root_fdのfsync）には
# 適用できない——これは実装の不備ではなくrenameの性質そのものである。


class PublishDurabilityError(RuntimeAtomicError):
    """current renameは既に成功しているが、その耐久性（fsync）を確認できな
    かったことを示す。currentは新versionへ切り替わっているが、この状態が
    クラッシュを生き延びる保証はない、という曖昧さを呼び出し元へ明示的に
    伝える（黙って「公開失敗」として扱わせない）。"""


_POST_SWAP_FSYNC_RETRY = 3
_POST_SWAP_FSYNC_BACKOFF_S = 0.2


@dataclass(frozen=True)
class PublishResult:
    version_id: str
    previous_version_id: Optional[str]
    started_at: float
    finished_at: float
    audit_path: Optional[Path]


class AtomicPublisher:
    """data_runtime/{.staging,versions,current,.publish.lock} を管理する。"""

    def __init__(
        self,
        data_runtime_root: Path,
        expect_uid: int,
        expect_gid: int,
        capacity_min_free_bytes: Optional[int] = DEFAULT_CAPACITY_MIN_FREE_BYTES,
        min_free_inodes: Optional[int] = DEFAULT_MIN_FREE_INODES,
    ):
        self.root = data_runtime_root
        self.staging_dir = self.root / ".staging"
        self.versions_dir = self.root / "versions"
        self.current_link = self.root / "current"
        self.lock_path = self.root / ".publish.lock"
        self.expect_uid = expect_uid
        self.expect_gid = expect_gid
        # CODEX P2B5-CX-005（第2ラウンド）対応: 既定でfail-closed（Noneを
        # 明示的に渡さない限り必ず検証する）。
        self.capacity_min_free_bytes = capacity_min_free_bytes
        self.min_free_inodes = min_free_inodes

    # ── staging ──────────────────────────────────────────────────────
    def new_staging_path(self, version_id: Optional[str] = None) -> Path:
        from .runtime_atomic import generate_version_id

        vid = validate_version_id(version_id) if version_id else generate_version_id()
        path = self.staging_dir / vid
        if path.exists():
            raise RuntimeAtomicError(f"staging directoryが既に存在する: {path}")
        os.makedirs(path, mode=VERSION_DIR_MODE, exist_ok=False)
        os.chmod(path, VERSION_DIR_MODE)
        return path

    def _fsync_tree(self, root: Path) -> None:
        """file内容と各directoryをfsyncする（第5.3節 step 4）。"""
        for dirpath, dirnames, filenames in os.walk(root):
            for fn in filenames:
                fsync_path(Path(dirpath) / fn)
            fsync_path(Path(dirpath))

    def _verify_permissions(self, version_path: Path, allowed_dir_modes: frozenset, allowed_file_modes: frozenset) -> None:
        """公開済みversion directory配下がpublic supplemental groupから
        read/traverse可能だがwrite不可であることを検証する（第5.1節）。"""
        import stat as _stat

        for dirpath, dirnames, filenames in os.walk(version_path):
            d = Path(dirpath)
            mode = _stat.S_IMODE(os.lstat(d).st_mode)
            if mode not in allowed_dir_modes:
                raise RuntimeAtomicError(f"許可外のdirectory mode: {d} mode={oct(mode)}")
            for fn in filenames:
                fp = d / fn
                st = os.lstat(fp)
                if _stat.S_ISLNK(st.st_mode):
                    raise RuntimeAtomicError(f"version tree内にsymlinkは許可されない: {fp}")
                # CODEX P2B5-CX-006（AT-11#11再修正）対応: hardlink（link count>1）は
                # 別のversion／外部pathと同一inodeを共有し得るため、以後の書換えが
                # 意図しない他fileへ波及する経路になり得る。symlinkと同様に拒否する。
                if st.st_nlink != 1:
                    raise RuntimeAtomicError(
                        f"version tree内にhardlink（link count={st.st_nlink}）は許可されない: {fp}"
                    )
                fmode = _stat.S_IMODE(st.st_mode)
                if fmode not in allowed_file_modes:
                    raise RuntimeAtomicError(f"許可外のfile mode: {fp} mode={oct(fmode)}")
                if fmode & 0o022:
                    raise RuntimeAtomicError(f"group/world writeが許可されているfile: {fp} mode={oct(fmode)}")

    def _current_target(self) -> Optional[str]:
        if not self.current_link.exists() and not self.current_link.is_symlink():
            return None
        if not self.current_link.is_symlink():
            raise RuntimeAtomicError(f"currentがsymlinkでない: {self.current_link}")
        target = os.readlink(self.current_link)
        if target.startswith("/") or ".." in target.split("/"):
            raise RuntimeAtomicError(f"currentのtargetが不正（絶対path/traversal）: {target}")
        return target

    def publish(
        self,
        version_id: str,
        validate_fn: Callable[[Path, Optional[Path]], None],
        allowed_dir_modes: frozenset = frozenset({VERSION_DIR_MODE}),
        allowed_file_modes: frozenset = frozenset({VERSION_FILE_MODE}),
        audit_dir: Optional[Path] = None,
    ) -> PublishResult:
        """第5.3節の公開手順（1〜12）を実行する。"""
        version_id = validate_version_id(version_id)
        started_at = time.time()
        staging_path = self.staging_dir / version_id
        version_path = self.versions_dir / version_id

        if not staging_path.is_dir():
            raise RuntimeAtomicError(f"staging directoryが存在しない: {staging_path}")
        if not same_device(self.staging_dir, self.versions_dir):
            raise RuntimeAtomicError("staging/versionsが別device（cross-filesystem publish拒否）")
        if not same_device(self.versions_dir, self.root):
            raise RuntimeAtomicError("versions/data_runtime rootが別device")

        # 1. writer lock取得（with内で保持し続ける）
        with WriterLock(self.lock_path, self.expect_uid, self.expect_gid):
            # CODEX P2B5-CX-005（第2ラウンド）対応: capacity/inode枯渇時は
            # 新規version公開そのものを拒否する（GC実行時にしか効かない
            # 事前検証では、GCが動かない限り無制限にdiskを消費できてしまう）。
            check_capacity_or_raise(self.root, self.capacity_min_free_bytes, self.min_free_inodes)

            previous_version_id = self._current_target()
            # CODEX P2B5-CX-003（第8ラウンド）対応: 件数整合性検証
            # （validate_fn実装側がmanifest比較に使う）のため、supersedeする
            # 直前versionのpathをvalidate_fnへ渡す。
            #
            # CODEX P2B5-CX-003（第9ラウンド）指摘の実バグ修正:
            # `_current_target()`（＝`os.readlink(current)`の結果）は
            # `rel_target = f"versions/{version_id}"`という、data_runtime
            # root起点の相対path文字列をそのまま返す（`versions/<id>`）。
            # これを誤って`self.versions_dir`（既に`.../versions`を含む）
            # と連結したため、実際には存在しない`.../versions/versions/<id>`
            # を渡していた。独立検証で「本番publisherが前versionを
            # `versions/versions/<id>`として渡すため、50%急減検査が
            # 実際には無効」と再現された（`previous_version_path.is_file()`
            # が常にFalseとなり、比較自体が一度もfireしていなかった）。
            # 正しくは`self.root`（data_runtime root）起点で解決する。
            previous_version_path = (
                self.root / previous_version_id if previous_version_id else None
            )

            # 3. validation（schema/件数/checksum/参照整合性/必須file/permission）
            validate_fn(staging_path, previous_version_path)
            self._verify_permissions(staging_path, allowed_dir_modes, allowed_file_modes)

            # 4. fsync
            self._fsync_tree(staging_path)

            # 5. destination非存在の安全な検証 + 6. no-replaceでversionsへrename
            if version_path.exists() or version_path.is_symlink():
                raise RuntimeAtomicError(f"version ID衝突: {version_path} が既に存在する")
            with open_dir_fd(self.staging_dir) as staging_fd, open_dir_fd(self.versions_dir) as versions_fd:
                try:
                    renameat2_noreplace(staging_fd, version_id, versions_fd, version_id)
                except FileExistsError as exc:
                    raise RuntimeAtomicError(f"version ID衝突（rename時点でEEXIST）: {version_id}") from exc
                fsync_dir(versions_fd)

            # 7. data_runtime dirfd基準で一意な一時symlinkを作成（相対targetのみ）
            tmp_symlink_name = f".current.tmp.{os.getpid()}.{int(time.time() * 1000)}"
            rel_target = f"versions/{version_id}"
            with open_dir_fd(self.root) as root_fd:
                try:
                    os.symlink(rel_target, tmp_symlink_name, dir_fd=root_fd)
                except FileExistsError as exc:
                    raise RuntimeAtomicError(f"一時symlink名が衝突: {tmp_symlink_name}") from exc

                # 8. 再検証（lstat相当）: 一時symlink・target directory・root境界
                try:
                    st = os.lstat(tmp_symlink_name, dir_fd=root_fd)
                    import stat as _stat
                    if not _stat.S_ISLNK(st.st_mode):
                        raise RuntimeAtomicError("作成直後の一時symlinkがsymlinkでない")
                    real_target = self.versions_dir / version_id
                    if not real_target.is_dir() or real_target.is_symlink():
                        raise RuntimeAtomicError(f"symlink target directoryの検証に失敗: {real_target}")
                    if real_target.resolve().parent != self.versions_dir.resolve():
                        raise RuntimeAtomicError("symlink targetがversions/直下から逸脱している（root境界違反）")

                    # 9. 一時symlinkをcurrentへ単一atomic renameで置換
                    os.rename(tmp_symlink_name, "current", src_dir_fd=root_fd, dst_dir_fd=root_fd)
                except BaseException:
                    # renameに至る前の失敗はtmp symlinkを隔離除去する
                    try:
                        os.unlink(tmp_symlink_name, dir_fd=root_fd)
                    except FileNotFoundError:
                        pass
                    raise

                # 10. data_runtime directoryをfsync
                # CODEX P2B5-CX-006（第3ラウンド）対応: renameは既に成功して
                # いるため、fsync失敗時に「currentを元へ戻す」ことはできない
                # （POSIX rename semantics上不可能）。一時的なfsync失敗
                # （transient EIO等）を救えるよう有限回retryし、それでも
                # 失敗する場合は「currentは新versionへ切替済みだが耐久性は
                # 未確認」という状態を隠さず、専用の例外型で明示する。
                last_fsync_exc: Optional[BaseException] = None
                for attempt in range(_POST_SWAP_FSYNC_RETRY):
                    try:
                        fsync_dir(root_fd)
                        last_fsync_exc = None
                        break
                    except OSError as exc:
                        last_fsync_exc = exc
                        if attempt < _POST_SWAP_FSYNC_RETRY - 1:
                            time.sleep(_POST_SWAP_FSYNC_BACKOFF_S)
                if last_fsync_exc is not None:
                    raise PublishDurabilityError(
                        f"current rename後のdirectory fsyncが{_POST_SWAP_FSYNC_RETRY}回とも失敗した"
                        f"（{_POST_SWAP_FSYNC_RETRY - 1}回retry済み）。current symlinkは既に"
                        f"versions/{version_id}へ切り替わっているが、この変更がクラッシュを"
                        "生き延びる耐久性は確認できていない。呼び出し元はこれを「公開失敗」では"
                        "なく「公開はされたが耐久性未確認」として扱い、必要であればoperatorへ"
                        "調査を促すこと。"
                    ) from last_fsync_exc

            # 11. 新currentを再読取・検証
            reread_target = self._current_target()
            if reread_target != rel_target:
                raise RuntimeAtomicError(
                    f"公開後の再読取でtarget不一致: expected={rel_target} actual={reread_target}"
                )

            audit_path = None
            if audit_dir is not None:
                audit_path = self._write_audit(
                    audit_dir, "publish", version_id, previous_version_id, started_at
                )

        # 12. writer lock解放（with終了時）
        finished_at = time.time()
        return PublishResult(version_id, previous_version_id, started_at, finished_at, audit_path)

    def rollback(self, target_version_id: str, audit_dir: Optional[Path] = None) -> PublishResult:
        """第5.4節: 検証済みversions/<id>だけをtargetにしたrollback。"""
        target_version_id = validate_version_id(target_version_id)
        started_at = time.time()
        target_path = self.versions_dir / target_version_id

        with WriterLock(self.lock_path, self.expect_uid, self.expect_gid):
            if not target_path.is_dir() or target_path.is_symlink():
                raise RuntimeAtomicError(f"rollback targetがversions配下の正規directoryでない: {target_path}")
            if target_path.resolve().parent != self.versions_dir.resolve():
                raise RuntimeAtomicError("rollback targetがversions/直下から逸脱している（root境界違反）")

            # CODEX P2B5-CX-003（第2ラウンド）対応: publish時に生成済みの
            # _manifest.jsonと実file内容を再照合し、publish後に改ざん・破損
            # した版へのrollback（current切替）を拒否する。currentと同一
            # targetのno-op応答についても、既に配信中の版の完全性確認として
            # 同様に検証する。
            verify_manifest_matches_disk(target_path)

            previous_version_id = self._current_target()
            rel_target = f"versions/{target_version_id}"
            if previous_version_id == rel_target:
                # currentと同一targetは明示的no-op（曖昧な成功にしない）
                finished_at = time.time()
                audit_path = None
                if audit_dir is not None:
                    audit_path = self._write_audit(
                        audit_dir, "rollback-noop", target_version_id, previous_version_id, started_at
                    )
                return PublishResult(target_version_id, previous_version_id, started_at, finished_at, audit_path)

            tmp_symlink_name = f".current.tmp.{os.getpid()}.{int(time.time() * 1000)}"
            with open_dir_fd(self.root) as root_fd:
                try:
                    os.symlink(rel_target, tmp_symlink_name, dir_fd=root_fd)
                    os.rename(tmp_symlink_name, "current", src_dir_fd=root_fd, dst_dir_fd=root_fd)
                except BaseException:
                    try:
                        os.unlink(tmp_symlink_name, dir_fd=root_fd)
                    except FileNotFoundError:
                        pass
                    raise
                fsync_dir(root_fd)

            reread_target = self._current_target()
            if reread_target != rel_target:
                raise RuntimeAtomicError(
                    f"rollback後の再読取でtarget不一致: expected={rel_target} actual={reread_target}"
                )

            audit_path = None
            if audit_dir is not None:
                audit_path = self._write_audit(
                    audit_dir, "rollback", target_version_id, previous_version_id, started_at
                )

        finished_at = time.time()
        return PublishResult(target_version_id, previous_version_id, started_at, finished_at, audit_path)

    def list_versions(self) -> List[str]:
        if not self.versions_dir.is_dir():
            return []
        return sorted(p.name for p in self.versions_dir.iterdir() if p.is_dir() and not p.is_symlink())

    def _write_audit(
        self, audit_dir: Path, action: str, version_id: str, previous_version_id: Optional[str], started_at: float
    ) -> Path:
        os.makedirs(audit_dir, exist_ok=True)
        audit_path = audit_dir / f"{action}_{int(started_at * 1000)}.json"
        payload = {
            "action": action,
            "version_id": version_id,
            "previous_version_id": previous_version_id,
            "started_at_epoch": started_at,
            "finished_at_epoch": time.time(),
            "pid": os.getpid(),
        }
        tmp_path = audit_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.rename(tmp_path, audit_path)
        fsync_path(audit_dir)
        return audit_path

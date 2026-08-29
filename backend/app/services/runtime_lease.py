"""
runtime_lease.py — Phase 2-B.5 reader lease lifecycle.

tasks/public-release/phase2b5_claude_implementation_instruction.md 第6節。

/run/onhighground2/leases/
  coordination.lock
  clock.state
  active/<lease-id>.json
  locks/<lease-id>.lock
  retired/<lease-id>.tombstone

lease payloadはschema version、version ID、lease ID、instance ID、
acquire/renew/expiry UTC epoch、request/job種別だけを持つ。token、header、
body、credentialは一切保存しない。
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import stat
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional

from .runtime_atomic import (
    RuntimeAtomicError,
    check_capacity_or_raise,
    fsync_dir,
    fsync_path,
    open_dir_fd,
    renameat2_noreplace,
    validate_version_id,
    verify_path_owner_mode,
)

COORDINATION_LOCK_MODE = 0o660

# CODEX P2B5-CX-005（第2ラウンド）対応: RuntimeGcの事前検証と同じ既定値。
DEFAULT_CAPACITY_MIN_FREE_BYTES = 1024 ** 3  # 1 GiB
DEFAULT_MIN_FREE_INODES = 1000
DEFAULT_TOMBSTONE_HARD_LIMIT = 100000

logger = logging.getLogger(__name__)

LEASE_SCHEMA_VERSION = 1

ACTIVE_ENTRY_MODE = 0o660
LOCK_FILE_MODE = 0o660
TOMBSTONE_MODE = 0o440
# scripts/publish/init_lease_volume.pyのSUBDIR_MODEと同値（設定の真実の
# 情報源はinitializer側。ここではruntime側の検証にだけ使う）。
LEASE_SUBDIR_MODE = 0o3770
# 公開済みversion directory自体の期待mode（第5.1節: 原則0750）。
PUBLISHED_VERSION_DIR_MODE = 0o750

# retry上限とbackoff（第6.2節・第7.3節で定数化を要求）。
LEASE_ID_COLLISION_RETRY_LIMIT = 5
LEASE_ID_COLLISION_BACKOFF_BASE_S = 0.05


class LeaseError(RuntimeAtomicError):
    pass


class LeaseExpiredError(LeaseError):
    pass


@dataclass
class LeasePayload:
    schema_version: int
    version_id: str
    lease_id: str
    instance_id: str
    acquired_at_epoch: float
    renewed_at_epoch: float
    expires_at_epoch: float
    request_kind: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def from_json(data: str) -> "LeasePayload":
        obj = json.loads(data)
        if obj.get("schema_version") != LEASE_SCHEMA_VERSION:
            raise LeaseError(f"未知のlease schema_version: {obj.get('schema_version')}")
        return LeasePayload(**obj)


@dataclass
class LeaseHandle:
    leases_root: Path
    payload: LeasePayload
    generation_id: str
    lock_fd: int
    lock_ino: int
    lock_dev: int


class LeaseCoordinator:
    def __init__(
        self,
        leases_root: Path,
        uid: int,
        gid: int,
        lease_ttl_s: float,
        expect_owner_gid: int,
        capacity_min_free_bytes: Optional[int] = DEFAULT_CAPACITY_MIN_FREE_BYTES,
        min_free_inodes: Optional[int] = DEFAULT_MIN_FREE_INODES,
        tombstone_hard_limit: Optional[int] = DEFAULT_TOMBSTONE_HARD_LIMIT,
        leases_owner_uid: Optional[int] = None,
    ):
        self.root = leases_root
        self.active_dir = leases_root / "active"
        self.locks_dir = leases_root / "locks"
        self.retired_dir = leases_root / "retired"
        self.coordination_lock_path = leases_root / "coordination.lock"
        self.uid = uid
        self.gid = gid
        self.lease_ttl_s = lease_ttl_s
        self.expect_owner_gid = expect_owner_gid
        # CODEX P2B5-CX-007（第2ラウンド）対応: expect_owner_gidは従来宣言のみで
        # 未使用だった。leases_owner_uidを明示的に渡した呼び出し元に限り、
        # coordination.lockのowner/mode（volume初期化時に確定する共有infra、
        # public/operator双方から見て常に同一ownerであるべき）を毎回の
        # global lock取得時に実際に検証する。未指定（None）の場合は従来どおり
        # 検証をskipする（test harness等、既存呼び出し元との後方互換のため）。
        self.leases_owner_uid = leases_owner_uid
        # CODEX P2B5-CX-005（第2ラウンド）対応: 既定でfail-closed。GCが
        # 動かない限り新規lease acquireが無制限にdisk/inode/tombstoneを
        # 消費し続けられる問題を、acquire経路自体にも同じ閾値で接続する。
        self.capacity_min_free_bytes = capacity_min_free_bytes
        self.min_free_inodes = min_free_inodes
        self.tombstone_hard_limit = tombstone_hard_limit

    # ── global lock ──────────────────────────────────────────────────
    @contextmanager
    def _global_lock(self, exclusive: bool) -> Iterator[int]:
        if not self.coordination_lock_path.exists():
            raise LeaseError(f"coordination.lockが存在しない（initializer未実行）: {self.coordination_lock_path}")
        if self.leases_owner_uid is not None:
            try:
                verify_path_owner_mode(
                    self.coordination_lock_path, self.leases_owner_uid, self.expect_owner_gid, COORDINATION_LOCK_MODE
                )
            except RuntimeAtomicError as exc:
                raise LeaseError(f"coordination.lockのowner/mode検証に失敗: {exc}") from exc
        fd = os.open(str(self.coordination_lock_path), os.O_RDWR)
        try:
            flag = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(fd, flag)
            yield fd
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    # ── initial acquire（第6.2節） ───────────────────────────────────
    def acquire(self, version_id: str, request_kind: str) -> LeaseHandle:
        """明示的に指定したversion_idへlease発行する低レベルAPI。

        CODEX P2B5-CX-001対応: このmethodはcaller側が既に安全な方法で
        version_idを確定させている場合（例: GC保護の再計算、test harnessの
        既知固定version）だけに使うこと。**HTTPリクエスト処理等の通常reader
        経路からはacquire_current()を使うこと** — こちらは
        `readlink(current)`をacquireと同じglobal shared critical section
        内で行わないため、readlinkとacquireの間にGC(global exclusive)が
        割り込み、選択済みversionが削除されるTOCTOUを避けられない。
        """
        version_id = validate_version_id(version_id)
        return self._acquire_with_retry(lambda: version_id, request_kind)

    def acquire_current(self, data_runtime_root: Path, request_kind: str) -> LeaseHandle:
        """`data_runtime/current`の解決とlease発行を単一のglobal shared
        critical sectionで行う（P2B5-CX-001対応）。

        GCはglobal exclusiveを取得しない限りversion削除を実行できないため、
        本methodがglobal sharedを保持している間はGCが割り込めず、
        「readerが選んだversionが読む前に消える」ことを構造的に防ぐ。
        """

        def _resolve() -> str:
            current_link = data_runtime_root / "current"
            if not current_link.is_symlink():
                raise LeaseError(f"currentがsymlinkでない: {current_link}")
            target = os.readlink(current_link)
            if target.startswith("/") or ".." in target.split("/"):
                raise LeaseError(f"currentのtargetが不正: {target}")
            vid = Path(target).name
            version_root = data_runtime_root / "versions" / vid
            if not version_root.is_dir():
                raise LeaseError(f"currentが指すversion rootが存在しない: {version_root}")
            return vid

        return self._acquire_with_retry(_resolve, request_kind)

    def _acquire_with_retry(self, resolve_version_id, request_kind: str) -> LeaseHandle:
        last_exc: Optional[BaseException] = None
        for attempt in range(LEASE_ID_COLLISION_RETRY_LIMIT):
            try:
                return self._acquire_once(resolve_version_id, request_kind)
            except FileExistsError as exc:
                last_exc = exc
                time.sleep(LEASE_ID_COLLISION_BACKOFF_BASE_S * (2 ** attempt))
                continue
        raise LeaseError(
            f"lease ID衝突のretry上限（{LEASE_ID_COLLISION_RETRY_LIMIT}）に到達"
        ) from last_exc

    def _acquire_once(self, resolve_version_id, request_kind: str) -> LeaseHandle:
        # CODEX P2B5-CX-005（第4ラウンド）対応: capacity/tombstone件数の
        # チェックとtombstone作成をshared lock（複数acquireの同時保持を
        # 許す）の下で行うと、複数processが同じcountを同時に観測してから
        # 並行してtombstoneを作成でき、hard limitを大幅に超過し得る
        # （独立検証: hard_limit=2に対し24並行acquireで20件成功・20
        # tombstone作成、10倍超過を実測）。renew/releaseは新規tombstoneを
        # 作らないためshared lockのままでよいが、_acquire_once()（初回
        # acquire、tombstone/lock/active entryを新規作成する唯一の経路）は
        # exclusiveへ変更し、check-then-createを単一の排他区間にする。
        # GCも同じglobal lockをexclusiveで取得するため、この変更は
        # 「新規acquire同士の直列化」を追加するだけで、GC-vs-reader間の
        # 排他関係（P2B5-CX-001）には影響しない。renew/release後の
        # streaming読み取り自体はこのlockを保持しないため、読み取り
        # scalabilityへの影響はない（影響するのはacquire時点の短い
        # bookkeeping区間のみ）。
        with self._global_lock(exclusive=True):
            # CODEX P2B5-CX-007（第5ラウンド）対応: active/locks/retired
            # directory自体のowner/modeは従来検証されておらず、誤設定でも
            # group権限経由でentry作成が成功してしまっていた（独立検証で
            # 「directoryのowner誤設定後もoperator entry作成成功」がPASSと
            # して許容される不備を指摘された）。新規acquireのたびに
            # 3 directoryすべてのowner/modeを厳密検証し、逸脱があれば
            # acquireそのものをfail-closedにする。
            for d in (self.active_dir, self.locks_dir, self.retired_dir):
                try:
                    verify_path_owner_mode(d, self.leases_owner_uid or self.uid, self.expect_owner_gid, LEASE_SUBDIR_MODE)
                except RuntimeAtomicError as exc:
                    raise LeaseError(f"lease subdirectoryのowner/mode検証に失敗: {d}: {exc}") from exc
            check_capacity_or_raise(self.root, self.capacity_min_free_bytes, self.min_free_inodes)
            if self.tombstone_hard_limit is not None:
                tombstone_count = sum(1 for _ in self.retired_dir.glob("*.tombstone"))
                # CODEX P2B5-CX-005（第3ラウンド）対応: この直後にこのacquire
                # 自身が新しいtombstoneを1件作成するため、判定は「作成後の
                # 件数がlimitを超えないか」でなければならない。旧実装は
                # `tombstone_count > limit`（作成前の件数で判定）だったため、
                # count==limitのときに限度超過となる1件を許可してしまう
                # off-by-oneがあった（独立検証で hard_limit=0 から新規acquire
                # 1件が成功することとして再現された）。`>=`（このacquireが
                # 作れば超過する、を含めて拒否）へ修正する。
                #
                # CODEX P2B5-CX-005（第4ラウンド）対応: このcheckはglobal
                # exclusive lock（上記`with self._global_lock(exclusive=True)`）
                # の下で行われるため、複数acquireが同時にこの区間へ入ることは
                # なく、check-then-createがatomicになっている
                # （独立検証: limit=2・24並行acquireで正確に2件のみ成功
                # することを確認済み）。
                if tombstone_count >= self.tombstone_hard_limit:
                    raise LeaseError(
                        f"tombstone数がhard limitに到達/超過（count={tombstone_count} >= limit={self.tombstone_hard_limit}、"
                        "このacquireが作成する新規tombstone1件を含めると超過するため拒否）"
                    )

            # version_idの解決はglobal shared保持中に行う（P2B5-CX-001対応）。
            # acquire_current()の場合はここでcurrentをreadlinkする。GCは
            # global exclusiveを要求するため、このwithブロックを抜けるまで
            # （active公開完了まで）GCによるversion削除は発生し得ない。
            version_id = validate_version_id(resolve_version_id())

            lease_id = uuid.uuid4().hex
            instance_id = f"{os.getpid()}-{uuid.uuid4().hex[:12]}"

            # 3. active/locks/retired 同一ID不存在をdirfd基準で確認
            for d, suffix in ((self.active_dir, ".json"), (self.locks_dir, ".lock"), (self.retired_dir, ".tombstone")):
                if (d / f"{lease_id}{suffix}").exists():
                    raise FileExistsError(f"lease ID衝突: {lease_id}")

            # 4. locks/<id>.lock を O_CREAT|O_EXCL|O_NOFOLLOW で一度だけ作成
            lock_path = self.locks_dir / f"{lease_id}.lock"
            lock_fd = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NOFOLLOW,
                LOCK_FILE_MODE,
            )
            try:
                os.fchmod(lock_fd, LOCK_FILE_MODE)
                # 5. generation-id書込み・fsync
                generation_id = uuid.uuid4().hex
                os.write(lock_fd, generation_id.encode("utf-8"))
                os.fsync(lock_fd)

                # 6. regular file・owner/group/mode・link count・device/inode検証
                st = os.fstat(lock_fd)
                if not stat.S_ISREG(st.st_mode):
                    raise LeaseError("lock fileがregular fileでない")
                if st.st_nlink != 1:
                    raise LeaseError(f"lock fileのlink countが異常: {st.st_nlink}")

                # 7. immutable tombstoneをatomic create + fsync
                tombstone_path = self.retired_dir / f"{lease_id}.tombstone"
                tombstone_payload = json.dumps(
                    {
                        "lease_id": lease_id,
                        "generation_id": generation_id,
                        "device": st.st_dev,
                        "inode": st.st_ino,
                        "created_at_epoch": time.time(),
                        "schema_version": LEASE_SCHEMA_VERSION,
                    },
                    sort_keys=True,
                ).encode("utf-8")
                tomb_fd = os.open(
                    str(tombstone_path),
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                    TOMBSTONE_MODE,
                )
                try:
                    os.write(tomb_fd, tombstone_payload)
                    os.fsync(tomb_fd)
                finally:
                    os.close(tomb_fd)
                os.chmod(tombstone_path, TOMBSTONE_MODE)

                # 8. locks/retired directory fsync
                with open_dir_fd(self.locks_dir) as lfd:
                    fsync_dir(lfd)
                with open_dir_fd(self.retired_dir) as rfd:
                    fsync_dir(rfd)

                # 9. current解決はversion固定（呼び出し側がversion_idを既に確定して渡す前提。
                #    本メソッドはversion_idの正当性検証だけを担当する）。

                # 10. active tempへlease payloadを書きfsync
                now = time.time()
                payload = LeasePayload(
                    schema_version=LEASE_SCHEMA_VERSION,
                    version_id=version_id,
                    lease_id=lease_id,
                    instance_id=instance_id,
                    acquired_at_epoch=now,
                    renewed_at_epoch=now,
                    expires_at_epoch=now + self.lease_ttl_s,
                    request_kind=request_kind,
                )
                tmp_name = f".active.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
                active_name = f"{lease_id}.json"
                with open_dir_fd(self.active_dir) as active_fd:
                    tmp_fd = os.open(
                        str(self.active_dir / tmp_name),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        ACTIVE_ENTRY_MODE,
                    )
                    try:
                        os.write(tmp_fd, payload.to_json().encode("utf-8"))
                        os.fsync(tmp_fd)
                    finally:
                        os.close(tmp_fd)
                    os.chmod(self.active_dir / tmp_name, ACTIVE_ENTRY_MODE)

                    # 11. 同一active dirfdのrenameat2(..., RENAME_NOREPLACE)だけでpublish
                    try:
                        renameat2_noreplace(active_fd, tmp_name, active_fd, active_name)
                    except FileExistsError:
                        os.unlink(self.active_dir / tmp_name)
                        raise

                    # 12. active directory fsync後に初めて成功を返す
                    fsync_dir(active_fd)

                lock_st = os.fstat(lock_fd)
                return LeaseHandle(
                    leases_root=self.root,
                    payload=payload,
                    generation_id=generation_id,
                    lock_fd=lock_fd,
                    lock_ino=lock_st.st_ino,
                    lock_dev=lock_st.st_dev,
                )
            except BaseException:
                os.close(lock_fd)
                raise

    # ── renewal（第6.4節） ───────────────────────────────────────────
    def renew(self, handle: LeaseHandle) -> LeaseHandle:
        with self._global_lock(exclusive=False):
            fcntl.flock(handle.lock_fd, fcntl.LOCK_EX)
            try:
                self._verify_lock_identity(handle)
                active_path = self.active_dir / f"{handle.payload.lease_id}.json"
                # CODEX P2B5-CX-007（第5ラウンド）対応: active entry自身の
                # owner/group検証（lock fileと同じ理由）。
                self._verify_active_entry_identity(active_path)
                current = LeasePayload.from_json(active_path.read_text(encoding="utf-8"))
                if current.lease_id != handle.payload.lease_id or current.instance_id != handle.payload.instance_id:
                    raise LeaseError("renewal時にinstance ID不一致（他プロセスに再作成された疑い）")
                now = time.time()
                if current.expires_at_epoch < now:
                    raise LeaseExpiredError("期限切れleaseの復活は禁止")

                new_payload = LeasePayload(
                    schema_version=LEASE_SCHEMA_VERSION,
                    version_id=current.version_id,
                    lease_id=current.lease_id,
                    instance_id=current.instance_id,
                    acquired_at_epoch=current.acquired_at_epoch,
                    renewed_at_epoch=now,
                    expires_at_epoch=now + self.lease_ttl_s,
                    request_kind=current.request_kind,
                )
                tmp_name = f".active.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}"
                with open_dir_fd(self.active_dir) as active_fd:
                    tmp_fd = os.open(
                        str(self.active_dir / tmp_name),
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        ACTIVE_ENTRY_MODE,
                    )
                    try:
                        os.write(tmp_fd, new_payload.to_json().encode("utf-8"))
                        os.fsync(tmp_fd)
                    finally:
                        os.close(tmp_fd)
                    os.chmod(self.active_dir / tmp_name, ACTIVE_ENTRY_MODE)
                    os.rename(tmp_name, active_path.name, src_dir_fd=active_fd, dst_dir_fd=active_fd)
                    fsync_dir(active_fd)

                handle.payload = new_payload
                return handle
            finally:
                fcntl.flock(handle.lock_fd, fcntl.LOCK_UN)

    # ── release（第6.4節） ───────────────────────────────────────────
    def release(self, handle: LeaseHandle) -> None:
        with self._global_lock(exclusive=False):
            fcntl.flock(handle.lock_fd, fcntl.LOCK_EX)
            try:
                self._verify_lock_identity(handle)
                active_path = self.active_dir / f"{handle.payload.lease_id}.json"
                if active_path.exists():
                    # releaseがunlinkできるのは自分のactive/<id>.jsonだけ。
                    self._verify_active_entry_identity(active_path)
                    current = LeasePayload.from_json(active_path.read_text(encoding="utf-8"))
                    if current.instance_id != handle.payload.instance_id:
                        raise LeaseError("release時にinstance ID不一致のため自分のentryとして扱えない")
                    with open_dir_fd(self.active_dir) as active_fd:
                        os.unlink(active_path.name, dir_fd=active_fd)
                        fsync_dir(active_fd)
                # release後もlock fileとtombstoneは残す（再作成しない）。
            finally:
                fcntl.flock(handle.lock_fd, fcntl.LOCK_UN)
                os.close(handle.lock_fd)

    def _verify_active_entry_identity(self, active_path: Path) -> None:
        """CODEX P2B5-CX-007（第5ラウンド）対応: active entryのowner/groupを
        検証する。owner不一致自体はUnix group権限経由でrenew/releaseの
        読み取りを妨げない場合があるが（sticky bitはrename-over置換にのみ
        影響する）、application-levelで数値ownershipの逸脱を明示的に検出し
        fail-closedにする。"""
        try:
            verify_path_owner_mode(active_path, self.uid, self.expect_owner_gid, ACTIVE_ENTRY_MODE)
        except RuntimeAtomicError as exc:
            raise LeaseError(f"active entryのowner/mode検証に失敗（改ざん/誤設定の疑い）: {exc}") from exc

    def _verify_lock_identity(self, handle: LeaseHandle) -> None:
        st = os.fstat(handle.lock_fd)
        if st.st_ino != handle.lock_ino or st.st_dev != handle.lock_dev:
            raise LeaseError("lock fileのdevice/inodeが取得時と異なる（差替え検出）")
        if st.st_nlink != 1:
            raise LeaseError(f"lock fileのlink countが異常: {st.st_nlink}")
        # CODEX P2B5-CX-007（第5ラウンド）対応: device/inode/generation ID
        # 一致だけでは「差替え検出」はできるが、「正規の数値ownershipを
        # 保っているか」は別軸として未検証だった（独立検証で「lease lockの
        # owner／group誤設定後もrenew成功」がPASSとして許容される不備を
        # 指摘された）。renew/releaseを呼び出したcoordinatorインスタンス
        # 自身のuid（＝そのleaseを実際に取得したprocessの識別子）と
        # lock fileの実際のownerが一致することを厳密に要求する。
        if st.st_uid != self.uid:
            raise LeaseError(
                f"lock fileのowner UIDが不一致（改ざん/誤設定の疑い）: expected={self.uid} actual={st.st_uid}"
            )
        if st.st_gid != self.expect_owner_gid:
            raise LeaseError(
                f"lock fileのgroup GIDが不一致（改ざん/誤設定の疑い）: expected={self.expect_owner_gid} actual={st.st_gid}"
            )
        os.lseek(handle.lock_fd, 0, os.SEEK_SET)
        stored_generation = os.read(handle.lock_fd, 256).decode("utf-8", errors="strict")
        if stored_generation != handle.generation_id:
            raise LeaseError("lock fileのgeneration IDが不一致（差替え検出）")


@contextmanager
def leased_version_root(
    coordinator: LeaseCoordinator, data_runtime_root: Path, request_kind: str
) -> Iterator[Path]:
    """acquireしてfixed version rootを返し、finally相当でreleaseする（第6.3節）。

    同一処理中にcurrentを再解決しない。取得失敗時は例外を伝播し、
    呼び出し側は読み取り処理を中止する。

    CODEX P2B5-CX-001対応: currentの解決は`acquire_current()`内部の
    global shared critical sectionで行う（readlinkとacquireの間にGCが
    割り込むTOCTOUを避けるため、ここで独立にreadlinkしない）。
    """
    handle = coordinator.acquire_current(data_runtime_root, request_kind)
    try:
        version_root = data_runtime_root / "versions" / handle.payload.version_id
        if not version_root.is_dir():
            # acquire_current()がglobal shared保持中に存在確認済みのため、
            # ここに到達する場合はlease解放後の別異常（例: 手動delete）を示す。
            raise LeaseError(f"lease取得後にversion rootが消失: {version_root}")
        # CODEX P2B5-CX-007（第7ラウンド）対応: published version directory
        # 自体（`versions/<id>/`）は、従来application-levelのownership検証
        # 対象外だった（配下の個別fileだけを検証し、containing directory
        # 自体は検証していなかった）。独立検証で
        # `version-dir-owner-mutated SUCCESS`として、version directory
        # ownerの単独改ざん後もreaderが黙って成功することを実証された。
        # coordinatorが期待するoperator uid・leases gidと厳密一致することを
        # 要求し、逸脱時はfail-closedで拒否する。
        try:
            verify_path_owner_mode(
                version_root, coordinator.leases_owner_uid or coordinator.uid,
                coordinator.expect_owner_gid, PUBLISHED_VERSION_DIR_MODE,
            )
        except RuntimeAtomicError as exc:
            raise LeaseError(
                f"published version directory自体のowner/mode検証に失敗（改ざん/誤設定の疑い）: {exc}"
            ) from exc
        yield version_root
    finally:
        coordinator.release(handle)

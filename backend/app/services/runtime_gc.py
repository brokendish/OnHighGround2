"""
runtime_gc.py — Phase 2-B.5 operator stale lease cleanup / version GC.

tasks/public-release/phase2b5_claude_implementation_instruction.md 第7節。

version GCを伴うoperator処理は writer lock → global exclusive の順で取得し、
同一区間で完了する。stale lease／orphan lockだけのcleanupはglobal exclusive
だけでよい。GCはper-lease lockを取得しない（global exclusiveにより
shared保持中／待機中のreaderが進行していないことをprotocolで保証する）。

fail-closed条件（第7.2節）を満たさない場合、version削除・lock cleanup・
自動修復を0件にする。異常な1 entryだけを無視してGCを継続してはいけない。
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import shutil
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Set

from .runtime_atomic import RuntimeAtomicError, WriterLock, fsync_dir, open_dir_fd, verify_path_owner_mode
from .runtime_lease import LeasePayload

CLOCK_STATE_MODE = 0o660

logger = logging.getLogger(__name__)


class GcFailClosedError(RuntimeAtomicError):
    """fail-closed条件に該当。version削除・lock cleanupを一切行わない。"""


@dataclass
class GcResult:
    stale_leases_removed: List[str]
    orphan_locks_removed: List[str]
    versions_deleted: List[str]
    versions_retained: List[str]
    started_at: float
    finished_at: float
    audit_path: Optional[Path]


class RuntimeGc:
    def __init__(
        self,
        data_runtime_root: Path,
        leases_root: Path,
        expect_writer_uid: int,
        expect_writer_gid: int,
        version_retention_count: int,
        max_future_skew_s: float,
        capacity_min_free_bytes: int,
        tombstone_hard_limit: int = 100000,
        min_free_inodes: Optional[int] = 1000,
        leases_owner_uid: Optional[int] = None,
        leases_gid: Optional[int] = None,
        known_lease_owner_uids: Optional[frozenset] = None,
    ):
        self.data_root = data_runtime_root
        self.versions_dir = data_runtime_root / "versions"
        self.current_link = data_runtime_root / "current"
        self.leases_root = leases_root
        self.active_dir = leases_root / "active"
        self.locks_dir = leases_root / "locks"
        self.retired_dir = leases_root / "retired"
        self.coordination_lock_path = leases_root / "coordination.lock"
        self.clock_state_path = leases_root / "clock.state"
        self.expect_writer_uid = expect_writer_uid
        self.expect_writer_gid = expect_writer_gid
        # CODEX P2B5-CX-007（第4ラウンド）対応: clock.stateのowner/modeは
        # 従来どこからも検証されていなかった（読み書きするだけ）。
        # leases_owner_uid/leases_gidを明示的に渡した呼び出し元に限り、
        # coordination.lockと同じくoperator_uid:leases_gid・mode 0660を
        # fail-closed precheckの一部として検証する（未指定時はNone/None
        # のままskipし、既存呼び出し元・testとの後方互換を保つ）。
        self.leases_owner_uid = leases_owner_uid
        self.leases_gid = leases_gid
        # CODEX P2B5-CX-007（第5ラウンド）対応: tombstoneはpublic/operator
        # いずれのuidでも作成されうる（どちらがそのleaseを取得したかに
        # 依存する）ため単一の期待ownerを固定できないが、groupは常に
        # leases_gid（setgid継承）であり、ownerも「既知の正規識別子の
        # いずれか」であるべきである。未知のuidが所有するtombstoneは
        # 改ざん/誤設定の疑いとして扱いorphan lock cleanupの対象から除外する。
        self.known_lease_owner_uids = known_lease_owner_uids
        self.version_retention_count = version_retention_count
        self.max_future_skew_s = max_future_skew_s
        self.capacity_min_free_bytes = capacity_min_free_bytes
        # CODEX P2B5-CX-005対応: byte容量だけでなくtombstone件数上限・
        # inode空き数下限もfail-closed判定へ加える。
        self.tombstone_hard_limit = tombstone_hard_limit
        self.min_free_inodes = min_free_inodes

    # ── fail-closed事前検証（第7.2節） ─────────────────────────────
    def _fail_closed_precheck(self) -> None:
        now = time.time()

        if not self.leases_root.is_dir() or not self.active_dir.is_dir() \
                or not self.locks_dir.is_dir() or not self.retired_dir.is_dir():
            raise GcFailClosedError("lease coordination volumeのtreeが不完全")

        # CODEX P2B5-CX-007（第4ラウンド）対応: clock.stateのowner/modeを
        # 実際に検証する（従来は読み書きするだけで一切検証していなかった）。
        # clock.stateはinitializer（init_lease_volume.py）が必ず作成する
        # ため、存在しない場合もfail-closed（未初期化環境を正常扱いしない）。
        if self.leases_owner_uid is not None and self.leases_gid is not None:
            if not self.clock_state_path.exists():
                raise GcFailClosedError(f"clock.stateが存在しない（initializer未実行）: {self.clock_state_path}")
            try:
                verify_path_owner_mode(self.clock_state_path, self.leases_owner_uid, self.leases_gid, CLOCK_STATE_MODE)
            except RuntimeAtomicError as exc:
                raise GcFailClosedError(f"clock.stateのowner/mode検証に失敗: {exc}") from exc

        usage = shutil.disk_usage(self.data_root)
        if usage.free < self.capacity_min_free_bytes:
            raise GcFailClosedError(
                f"空き容量不足（free={usage.free} < threshold={self.capacity_min_free_bytes}）"
            )

        # CODEX P2B5-CX-005対応: inode枯渇（Linuxのstatvfsが提供するf_favail）。
        # 非Linux環境やstatvfs非対応filesystemではNoneのまま静かにskipする
        # （fail-closedの過剰検出を避けるが、Linux VPS本番では必ず効く）。
        if self.min_free_inodes is not None and hasattr(os, "statvfs"):
            try:
                vfs = os.statvfs(self.data_root)
                free_inodes = vfs.f_favail
                if free_inodes > 0 and free_inodes < self.min_free_inodes:
                    raise GcFailClosedError(
                        f"空きinode不足（free_inodes={free_inodes} < threshold={self.min_free_inodes}）"
                    )
            except (AttributeError, OSError):
                pass

        # CODEX P2B5-CX-005対応: tombstoneは通常削除されず無期限に増え続ける
        # ため、hard limitを超えたらfail-closedにする（無制限成長を防ぐ）。
        tombstone_count = sum(1 for _ in self.retired_dir.glob("*.tombstone"))
        if tombstone_count > self.tombstone_hard_limit:
            raise GcFailClosedError(
                f"tombstone数がhard limitを超過（count={tombstone_count} > limit={self.tombstone_hard_limit}）"
            )

        # registry（active/*.json）を全件検証。1件でも破損があれば継続しない。
        for entry in sorted(self.active_dir.glob("*.json")):
            try:
                payload = LeasePayload.from_json(entry.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                raise GcFailClosedError(f"active entryのJSON/schema破損: {entry.name}") from exc
            if payload.acquired_at_epoch > now + self.max_future_skew_s:
                raise GcFailClosedError(f"clock skew検出（未来のacquired_at）: {entry.name}")
            if payload.expires_at_epoch > now + self.max_future_skew_s + 86400 * 365:
                raise GcFailClosedError(f"許容外のfuture timestamp: {entry.name}")

        # clock rollback検出（簡易）: clock.stateに前回GC時刻を保持し、現在時刻が
        # それより過去なら拒否する。
        clock_state_path = self.leases_root / "clock.state"
        if clock_state_path.exists():
            try:
                last_seen = float(clock_state_path.read_text(encoding="utf-8").strip())
            except ValueError as exc:
                raise GcFailClosedError("clock.state破損") from exc
            if now + 1.0 < last_seen:
                raise GcFailClosedError(f"clock rollback検出: now={now} last_seen={last_seen}")

    def _update_clock_state(self) -> None:
        clock_state_path = self.leases_root / "clock.state"
        tmp_path = clock_state_path.with_name(f".clock.state.tmp.{os.getpid()}")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(str(time.time()))
            f.flush()
            os.fsync(f.fileno())
        # CODEX P2B5-CX-007（第5ラウンド）検証中に発見した実バグ: open()が
        # 作るtmp fileのmodeは呼び出しprocessのumaskに依存し（container既定
        # ではumask 0022相当で0644になる）、明示的chmodがなかったため、GCが
        # 成功するたびにclock.stateのmodeが正規値0660から劣化していた。
        # 本ラウンドで`_fail_closed_precheck()`へclock.stateの厳密mode検証
        # （owner/mode一致）を新規追加したため、このバグを放置すると
        # 「GCが1回成功すると次回以降は自分自身のmode検証で永続的に
        # fail-closedになる」という自壊的な回帰を引き起こす。他のfile
        # 作成箇所と同様、rename前に明示的chmodでumaskの影響を打ち消す。
        os.chmod(tmp_path, CLOCK_STATE_MODE)
        os.rename(tmp_path, clock_state_path)

    @staticmethod
    def _current_version_id(current_link: Path) -> Optional[str]:
        if not current_link.is_symlink():
            return None
        target = os.readlink(current_link)
        if target.startswith("/") or ".." in target.split("/"):
            raise GcFailClosedError(f"currentのtargetが不正: {target}")
        return Path(target).name

    def run(self, protected_version_ids: Optional[Set[str]] = None, audit_dir: Optional[Path] = None) -> GcResult:
        """1. writer lock取得 → 2. global exclusive取得 → 同一区間で完了する（第7.1節）。"""
        started_at = time.time()
        protected_version_ids = set(protected_version_ids or set())

        writer_lock_path = self.data_root / ".publish.lock"
        with WriterLock(writer_lock_path, self.expect_writer_uid, self.expect_writer_gid):
            if not self.coordination_lock_path.exists():
                raise GcFailClosedError("coordination.lockが存在しない")
            coord_fd = os.open(str(self.coordination_lock_path), os.O_RDWR)
            try:
                fcntl.flock(coord_fd, fcntl.LOCK_EX)
                try:
                    self._fail_closed_precheck()

                    now = time.time()
                    stale_removed: List[str] = []
                    for entry in sorted(self.active_dir.glob("*.json")):
                        payload = LeasePayload.from_json(entry.read_text(encoding="utf-8"))
                        # CODEX P2B5-CX-005対応: expires_at_epoch < now の単純比較は
                        # clock skew margin を考慮しない。複数container間で
                        # わずかにclockがずれていると、実際にはまだ有効な
                        # leaseを早期に破棄しうる。max_future_skew_sをmargin
                        # として使い、「期限＋margin」を過ぎたものだけをstale
                        # と判定する（保護的な側に倒す）。
                        if payload.expires_at_epoch + self.max_future_skew_s < now:
                            with open_dir_fd(self.active_dir) as active_fd:
                                os.unlink(entry.name, dir_fd=active_fd)
                                fsync_dir(active_fd)
                            stale_removed.append(payload.lease_id)

                    # current/leaseで保護されているversionを再計算
                    current_id = self._current_version_id(self.current_link)
                    if current_id:
                        protected_version_ids.add(current_id)
                    for entry in sorted(self.active_dir.glob("*.json")):
                        payload = LeasePayload.from_json(entry.read_text(encoding="utf-8"))
                        protected_version_ids.add(payload.version_id)

                    # CODEX P2B5-CX-005対応: rollback保護をretention countへの
                    # 暗黙依存にせず、明示的なprotected version listを持つ。
                    # `versions/.protected.json`（配列）に列挙されたversion IDは、
                    # 保持世代数の設定に関わらず常に保護する。
                    protected_list_path = self.versions_dir / ".protected.json"
                    if protected_list_path.is_file():
                        try:
                            explicit_protected = json.loads(protected_list_path.read_text(encoding="utf-8"))
                            if not isinstance(explicit_protected, list):
                                raise GcFailClosedError(".protected.jsonの内容がlistでない")
                            protected_version_ids.update(str(v) for v in explicit_protected)
                        except json.JSONDecodeError as exc:
                            raise GcFailClosedError(f".protected.json破損: {exc}") from exc

                    all_versions = sorted(
                        p.name for p in self.versions_dir.iterdir()
                        if p.is_dir() and not p.is_symlink()
                    ) if self.versions_dir.is_dir() else []

                    # 保持世代数・保護versionを反映してGC候補を確定する。
                    # 新しい順に retention_count 件は無条件で保持する。
                    # 注意: Python の list[-0:] は list[0:]（全件）と等価になるため、
                    # retention_count=0（無条件保持なし）を素直に -N スライスへ渡すと
                    # 全versionを誤って保護してしまう。0はここで明示的に空集合とする。
                    if self.version_retention_count > 0:
                        keep_by_retention = set(all_versions[-self.version_retention_count:])
                    else:
                        keep_by_retention = set()
                    retained = set(protected_version_ids) | keep_by_retention
                    candidates = [v for v in all_versions if v not in retained]

                    deleted: List[str] = []
                    for version_id in candidates:
                        version_path = self.versions_dir / version_id
                        # realpathがversions/直下・非symlink・正規directoryであることを再検証
                        if version_path.is_symlink():
                            raise GcFailClosedError(f"削除候補がsymlink: {version_path}")
                        if version_path.resolve().parent != self.versions_dir.resolve():
                            raise GcFailClosedError(f"削除候補がversions/直下から逸脱: {version_path}")
                        if not version_path.is_dir():
                            raise GcFailClosedError(f"削除候補がdirectoryでない: {version_path}")
                        shutil.rmtree(version_path)
                        deleted.append(version_id)
                    if candidates:
                        with open_dir_fd(self.versions_dir) as vfd:
                            fsync_dir(vfd)

                    # 孤立lock fileだけのcleanup: tombstone照合後にoperator-only cleanup
                    orphan_locks_removed: List[str] = []
                    active_ids = {p.stem for p in self.active_dir.glob("*.json")}
                    for lock_entry in sorted(self.locks_dir.glob("*.lock")):
                        lease_id = lock_entry.stem
                        if lease_id in active_ids:
                            continue
                        tombstone_path = self.retired_dir / f"{lease_id}.tombstone"
                        if not tombstone_path.exists():
                            # tombstoneがない孤立lockは安全側に倒し削除しない
                            continue
                        # CODEX P2B5-CX-007（第5ラウンド）対応: tombstone自身の
                        # owner/group/modeを信頼する前に検証する（従来は
                        # 内容をそのまま読み、inode/device比較にしか
                        # 使っていなかった）。groupとmodeは常に固定値の
                        # はずであり、逸脱があれば改ざん/誤設定の疑いとして
                        # 安全側（削除しない）に倒す。
                        tomb_st = os.lstat(tombstone_path)
                        if self.leases_gid is not None and tomb_st.st_gid != self.leases_gid:
                            continue
                        if stat.S_IMODE(tomb_st.st_mode) != 0o440:
                            continue
                        if self.known_lease_owner_uids is not None and tomb_st.st_uid not in self.known_lease_owner_uids:
                            continue
                        try:
                            tomb = json.loads(tombstone_path.read_text(encoding="utf-8"))
                        except json.JSONDecodeError:
                            continue
                        lock_st = os.lstat(lock_entry)
                        if stat.S_ISLNK(lock_st.st_mode):
                            continue
                        if lock_st.st_ino != tomb.get("inode") or lock_st.st_dev != tomb.get("device"):
                            # inode差替えを検出したら削除しない（fail-closed）
                            continue
                        with open_dir_fd(self.locks_dir) as lfd:
                            os.unlink(lock_entry.name, dir_fd=lfd)
                            fsync_dir(lfd)
                        orphan_locks_removed.append(lease_id)

                    self._update_clock_state()

                    audit_path = None
                    if audit_dir is not None:
                        audit_path = self._write_audit(
                            audit_dir, stale_removed, orphan_locks_removed, deleted, sorted(retained), started_at
                        )
                finally:
                    pass
            finally:
                fcntl.flock(coord_fd, fcntl.LOCK_UN)
                os.close(coord_fd)

        finished_at = time.time()
        return GcResult(
            stale_leases_removed=stale_removed,
            orphan_locks_removed=orphan_locks_removed,
            versions_deleted=deleted,
            versions_retained=sorted(retained),
            started_at=started_at,
            finished_at=finished_at,
            audit_path=audit_path,
        )

    def _write_audit(
        self, audit_dir: Path, stale_removed, orphan_locks_removed, deleted, retained, started_at
    ) -> Path:
        os.makedirs(audit_dir, exist_ok=True)
        audit_path = audit_dir / f"gc_{int(started_at * 1000)}.json"
        payload = {
            "action": "version_gc",
            "stale_leases_removed": stale_removed,
            "orphan_locks_removed": orphan_locks_removed,
            "versions_deleted": deleted,
            "versions_retained": retained,
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
        return audit_path

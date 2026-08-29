#!/usr/bin/env python3
"""
phase2b5_permission_matrix_inner.py — CODEX P2B5-CX-007対応。

published version tree・lease coordination volumeを構成する各artifactに
対する単独permission mutation matrixを、Linux-native filesystem（Docker
named volume）上で実行する。data_runtimeのhost bind mountはmacOS Docker
Desktopの制約でcontainer側numeric UIDをhost側へ正しく反映しないため、
この検証だけはnamed volumeをdata_runtime代わりに使う（Linux VPSの実
bind mountはこの制約を持たないため、named volumeでの検証結果はVPS環境の
実際の挙動を代表する）。

CODEX P2B5-CX-007指摘対応（第2〜3ラウンド累積）: 旧実装は`.publish.lock`の
owner/group/mode 3変異だけを対象としていた。本版では指示書第5節が列挙する
root・active/locks/retired directory・coordination.lock・clock.state・
active entry・lease lock・tombstone・published version treeの全項目を
対象に含める。第3ラウンドでは、root baselineが実際には`current` symlinkを
経由せず`versions/<id>/...`を直接参照していた（表示と実体の乖離）ことと、
tombstone testが実運用のowner（public UID経由でのacquireが主要経路）と
異なるownershipで検証していたことも是正した。

本matrixの構築中に、data_runtime直下自身のowner/modeをどのcodeも一切
管理しておらず（.staging/versions/.publish.lockという子artifactだけが
管理されていた）、その結果 (a) operatorがcurrent symlinkを新規作成できない
か、(b) publicがcurrent配下を一切traverseできない、という実害を実Linux
named volumeで発見した（真の原因: data_runtime rootのgroupがoperatorの
primary gidのままで、public/operator共有のsupplemental group（leases_gid）
になっていなかった）。scripts/publish/init_lease_volume.pyとscripts/publish/
deploy_to_runtime_atomic.shを本ラウンドで修正済み（第16節参照）。本script
はこの回帰を継続的に検出するため、data_runtime root自身も単独mutation
対象に含める。

第5ラウンド（CODEX指摘対応）: 従来の多くのtestが、実際のconsumer関数
（LeaseCoordinator._acquire_once()/renew()/release()、RuntimeGcの
orphan lock cleanup、runtime_version_access.stream_versioned_file()等）
を経由しない生のOS-level probe（`open()`直接呼び出し等）で「owner/group
誤設定後もUnix permission bitのfallback経路（他方の軸が正しいまま）で
成功する」ことを、そのまま無条件のPASSとして記録していた。これは
application-levelでの数値ownership検証（fail-closed matrix）の代替には
ならないとCODEXから指摘された。本版では、backend側へ新規実装した
application-level検証（active/locks/retired directoryのowner/mode、
lease lock・active entryのowner/group、tombstoneのowner/group/mode、
published data fileのowner/group/mode）を実際のconsumer関数経由で
exerciseし、owner/group/modeいずれの単独逸脱もfail-closedになることを
直接確認する。OS-level fallbackがそのまま機能する（application-level
checkが存在しない）箇所は、誤ったPASSとして記録せず、その旨を明示する。

root（UID 0）で1回だけ実行し、mutation対象ごとに:
  1. 正常な数値ownership/modeで初期化する
  2. 1項目だけを単独で誤らせる（owner／group／mode）
  3. 対象操作に応じたUIDへforkして降格し、対象操作を試みる
  4. 誤らせた項目が原因でfail-closed（例外送出／権限拒否）することを確認する
を1 processで完結させる（docker execの往復を減らすため）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/app")

from app.services.runtime_atomic import RuntimeAtomicError, WriterLock  # noqa: E402
from app.services.runtime_lease import LeaseCoordinator, LeaseError  # noqa: E402

OPERATOR_UID = 10002
OPERATOR_GID = 10002
PUBLIC_UID = 10001
PUBLIC_GID = 10001
LEASES_GID = 20001

DATA_RUNTIME_ROOT = "/data_runtime"

RESULTS = []


def record(name, passed, detail=""):
    RESULTS.append({"name": name, "pass": bool(passed), "detail": str(detail)[:500]})


def _fork_as(uid, gid, extra_groups, fn):
    """子processをforkし、指定UID/GIDへ降格してfnを実行する。fnが例外を
    送出せず正常終了すればexit 0、例外送出ならexit 1。親processは常にrootの
    まま残り、後続mutationのchown/chmodを継続できる。例外発生時はtraceback
    をstderrへ出力してから終了する（デバッグ容易性のため。以前は
    Exceptionを握り潰しており原因調査が困難だった）。"""
    pid = os.fork()
    if pid == 0:
        try:
            os.setgroups(extra_groups)
            os.setresgid(gid, gid, gid)
            os.setresuid(uid, uid, uid)
            fn()
            os._exit(0)
        except Exception:
            import traceback
            traceback.print_exc()
            os._exit(1)
        except BaseException:
            import traceback
            traceback.print_exc()
            os._exit(2)
    else:
        _, status = os.waitpid(pid, 0)
        exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
        return exit_code == 0, exit_code


# ── 1. .publish.lock（既存、WriterLockが検証） ──────────────────────────

def _reset_publish_lock(path: str) -> None:
    if os.path.lexists(path):
        os.unlink(path)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    os.chown(path, OPERATOR_UID, OPERATOR_GID)
    os.chmod(path, 0o600)


def _try_writerlock(path: str) -> None:
    with WriterLock(Path(path), OPERATOR_UID, OPERATOR_GID, timeout_s=2.0):
        pass


def run_publish_lock_matrix(lock_path: str) -> None:
    _reset_publish_lock(lock_path)
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_writerlock(lock_path))
    record("publish.lock baseline: 正しいowner(10002:10002)/mode(0600)ならWriterLock取得に成功する", ok, f"exit={code}")

    _reset_publish_lock(lock_path)
    os.chown(lock_path, PUBLIC_UID, OPERATOR_GID)
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_writerlock(lock_path))
    record("publish.lock single-mutation: owner UIDのみ不一致 → WriterLock取得がfail-closed", not ok, f"exit={code}")

    _reset_publish_lock(lock_path)
    os.chown(lock_path, OPERATOR_UID, LEASES_GID)
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_writerlock(lock_path))
    record("publish.lock single-mutation: group GIDのみ不一致 → WriterLock取得がfail-closed", not ok, f"exit={code}")

    _reset_publish_lock(lock_path)
    os.chmod(lock_path, 0o644)
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_writerlock(lock_path))
    record("publish.lock single-mutation: modeのみ不一致(0644) → WriterLock取得がfail-closed", not ok, f"exit={code}")

    _reset_publish_lock(lock_path)


# ── 2. coordination.lock（本ラウンド新規: P2B5-CX-007対応の主対象） ──────

def _reset_coordination_lock(path: str) -> None:
    if os.path.lexists(path):
        os.unlink(path)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
    os.close(fd)
    os.chown(path, OPERATOR_UID, LEASES_GID)
    os.chmod(path, 0o660)


def _try_global_lock(leases_root: str) -> None:
    coord = LeaseCoordinator(
        Path(leases_root), uid=PUBLIC_UID, gid=PUBLIC_GID, lease_ttl_s=30.0,
        expect_owner_gid=LEASES_GID, leases_owner_uid=OPERATOR_UID,
    )
    with coord._global_lock(exclusive=False):  # noqa: SLF001
        pass


def run_coordination_lock_matrix(leases_root: str) -> None:
    os.makedirs(leases_root, exist_ok=True)
    os.chown(leases_root, OPERATOR_UID, LEASES_GID)
    os.chmod(leases_root, 0o2770)
    coord_lock_path = os.path.join(leases_root, "coordination.lock")

    _reset_coordination_lock(coord_lock_path)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_global_lock(leases_root))
    record("coordination.lock baseline【新規enforcement】: 正しいowner(10002:20001)/mode(0660)ならglobal shared lock取得に成功する", ok, f"exit={code}")

    _reset_coordination_lock(coord_lock_path)
    os.chown(coord_lock_path, PUBLIC_UID, LEASES_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_global_lock(leases_root))
    record("coordination.lock single-mutation【新規enforcement】: owner UIDのみ不一致 → global lock取得がfail-closed", not ok, f"exit={code}")

    _reset_coordination_lock(coord_lock_path)
    os.chown(coord_lock_path, OPERATOR_UID, OPERATOR_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_global_lock(leases_root))
    record("coordination.lock single-mutation【新規enforcement】: group GIDのみ不一致 → global lock取得がfail-closed", not ok, f"exit={code}")

    _reset_coordination_lock(coord_lock_path)
    os.chmod(coord_lock_path, 0o666)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_global_lock(leases_root))
    record("coordination.lock single-mutation【新規enforcement】: modeのみ不一致(0666) → global lock取得がfail-closed", not ok, f"exit={code}")

    _reset_coordination_lock(coord_lock_path)


# ── 3. data_runtime root自身（本ラウンドで発見した実バグの回帰検出） ──────

def _reset_data_runtime_root(root: str) -> None:
    os.chown(root, OPERATOR_UID, LEASES_GID)
    os.chmod(root, 0o750)


def _try_traverse_and_read(root: str) -> None:
    # CODEX P2B5-CX-007（第3ラウンド）対応: 旧実装は`versions/<id>/...`を
    # 直接参照しており、実際のconsumer（runtime_version_access.py）が
    # 経由する`current` symlinkを一切通っていなかった（「currentを経由して
    # publicがreadできる」という表示と実体が異なっていた）。実際に`current`
    # 経由でreadする。
    target = os.path.join(root, "current", "backend", "hazard", "f.geojson")
    with open(target, "rb") as f:
        f.read()


def run_data_runtime_root_matrix(root: str, leases_root: str) -> None:
    os.makedirs(root, exist_ok=True)
    # 検証対象のfileを一度だけoperatorとして正規のgroup（leases_gid）付きで用意する。
    _reset_data_runtime_root(root)

    def _seed():
        # validate_version_id()の正規表現（^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}$）に
        # 適合する形式にする（acquire_current()経由の実lease取得test
        # （run_real_active_entry_and_lock_matrix）がこのcurrentを解決する
        # ため、任意の文字列では拒否されてしまう）。
        vid = "20260101T000000Z-deadbeef"
        d = os.path.join(root, "versions", vid, "backend", "hazard")
        os.makedirs(d, exist_ok=True, mode=0o750)
        f = os.path.join(d, "f.geojson")
        if os.path.lexists(f):
            os.unlink(f)
        fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
        os.write(fd, b'{"marker": "root-matrix"}')
        os.close(fd)
        # versions配下を再帰的にleases_gidへ（本ラウンドのdeploy_to_runtime_atomic.sh修正と同じ手当て）
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, "versions")):
            os.chown(dirpath, OPERATOR_UID, LEASES_GID)
            for fn in filenames:
                os.chown(os.path.join(dirpath, fn), OPERATOR_UID, LEASES_GID)
        # 実際のpublish()と同じくcurrentをversions/<vid>への相対symlinkにする。
        current_link = os.path.join(root, "current")
        if os.path.lexists(current_link):
            os.unlink(current_link)
        os.symlink(f"versions/{vid}", current_link)

    ok_seed, code_seed = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], _seed)
    record("data_runtime root: 準備段階（operatorによるversion tree作成＋current symlink作成）が成功する", ok_seed, f"exit={code_seed}")

    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_traverse_and_read(root))
    record(
        "data_runtime root baseline【本ラウンドで発見・修正した実バグの回帰検出、current symlink経由】: "
        "root owner=operator/group=leases_gid(20001)/mode=0750ならpublicがcurrent symlink経由でtraverseしread可能",
        ok, f"exit={code}",
    )

    # single-mutation: rootのgroupをoperator自身のprimary gidへ変更（修正前の実バグを再現）
    os.chown(root, OPERATOR_UID, OPERATOR_GID)
    os.chmod(root, 0o750)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_traverse_and_read(root))
    record(
        "data_runtime root single-mutation【修正前の実バグの再現】: rootのgroupをoperator自身のprimary gidへ"
        "誤らせると、publicはcurrent配下をtraverseできない（＝この誤設定が実際にpublic readを壊すことの実証）",
        not ok, f"exit={code}",
    )

    # single-mutation: modeからgroup実行ビットを外す
    _reset_data_runtime_root(root)
    os.chmod(root, 0o740)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_traverse_and_read(root))
    record(
        "data_runtime root single-mutation: modeからgroup実行ビットを外す(0740) → "
        "publicはdirectory traverseができずreadに失敗する",
        not ok, f"exit={code}",
    )

    # CODEX P2B5-CX-007（第7ラウンド）対応: 従来、data_runtime root自身の
    # ownershipを検証するapplication-level checkが存在せず、OS-levelの
    # raw open()（_try_traverse_and_read、直接current/配下を開くだけの
    # probe）ではowner単独mutation後もgroup経由のtraverseがそのまま
    # 成功していた（下のOS-level probeは、その「app-level checkがない」
    # 実態を示す対比としてそのまま残す）。本ラウンドで
    # `runtime_version_access._verify_data_runtime_root_ownership()`を
    # 新設し、`stream_versioned_file()`等の実consumer関数がcurrent解決
    # 前に必ずroot自体のowner/group/modeを検証するようにした。実consumer
    # 経由（OS-level probeではなくapplication-level）で同じmutationを
    # 検証し、今度はfail-closedになることを確認する。
    _reset_data_runtime_root(root)
    os.chown(root, PUBLIC_UID, LEASES_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_traverse_and_read(root))
    record(
        "data_runtime root single-mutation【owner単独、OS-level raw probe、対比用】: "
        "raw open()はownerをpublicへ誤らせても（groupはleases_gidのまま）group経由のtraverse/readが"
        "そのまま成功する（OS-levelのgroup権限だけを見た場合の挙動。下のapp-level testと対比するために"
        "そのまま残す）",
        ok, f"exit={code}",
    )

    ok2, code2 = _fork_as(
        PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
        lambda: _try_stream_versioned_file(root, leases_root, "backend/hazard/f.geojson"),
    )
    record(
        "data_runtime root single-mutation【owner単独、実stream_versioned_file、app-level検証】: "
        "同じroot owner改ざんを実consumer（_verify_data_runtime_root_ownership()経由）で検証すると、"
        "OS-levelのgroup権限に関わらずfail-closedになる",
        not ok2, f"exit={code2}",
    )

    _reset_data_runtime_root(root)


# ── 4. tombstone（mode 0440、owner自身も書けないimmutable設計） ──────────
# CODEX P2B5-CX-007（第3ラウンド）対応: 旧実装はtombstoneをOPERATOR_UID:
# OPERATOR_GIDで作っていたが、実際のtombstoneは`_acquire_once()`実行時の
# 呼び出し元processの euid で所有される。runtime_version_access.pyの
# get_coordinator()はpublic側（hazards.py等）から呼ばれることが主要経路
# であり、そのcoordinatorはuid=PUBLIC_UIDで構築される。したがって
# 実運用で最も典型的なtombstoneの所有者はPUBLIC_UIDであり、groupは
# retired/がsetgid(mode 3770, group=leases_gid)であるため作成processの
# 所属に関わらずleases_gidへ自動継承される。この実際のownershipパターン
# （10001:20001）へ修正する。


def _reset_tombstone(path: str) -> None:
    if os.path.lexists(path):
        os.chmod(path, 0o640)
        os.unlink(path)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o440)
    os.write(fd, b'{"lease_id": "permission-matrix-tombstone"}')
    os.close(fd)
    os.chown(path, PUBLIC_UID, LEASES_GID)
    os.chmod(path, 0o440)


def _try_write(path: str) -> None:
    fd = os.open(path, os.O_WRONLY)
    os.close(fd)


def run_tombstone_matrix(leases_root: str) -> None:
    tomb_path = os.path.join(leases_root, "permission-matrix.tombstone")

    _reset_tombstone(tomb_path)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_write(tomb_path))
    record(
        "tombstone single-mutation【実運用owner(10001:20001)】: mode 0440ではowner自身（chmodなし）もwrite openできない（immutable設計の実証）",
        not ok, f"exit={code}",
    )

    _reset_tombstone(tomb_path)
    os.chmod(tomb_path, 0o640)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_write(tomb_path))
    record(
        "tombstone positive control【実運用owner(10001:20001)】: mode 0640（write bit付与）ならowner自身のwrite openは成功する（0440拒否がmode由来であることの確認）",
        ok, f"exit={code}",
    )
    os.unlink(tomb_path)

    # third party（owner でも leases_gid member でもない第三者、ここではUID 65534
    # nobody相当）は、正しいbaseline mode(0440)でもread可能性すら持たない
    # （other bitsが0であるため）ことを確認する。
    _reset_tombstone(tomb_path)
    ok, code = _fork_as(65534, 65534, [], lambda: _try_write(tomb_path))
    record(
        "tombstone single-mutation【第三者】: owner/group双方に属さない第三者はbaseline状態でもwrite不可（other bits=0）",
        not ok, f"exit={code}",
    )

    # CODEX P2B5-CX-007（第5ラウンド）対応: 旧実装はpublicによる生の
    # open()（raw OS-level probe）で「owner／group誤設定後もreadできて
    # しまう」ことをそのままPASS記録しており、これは実際のconsumer
    # （operator GCのorphan lock cleanup）が対象操作をfail-closedにする
    # ことを検証していなかった（CODEXの指摘: fallback経路の成功を
    # positive testとして記録するのは、numeric ownership逸脱を
    # applicationが検出するnegative testの代替にならない）。本ラウンドで
    # runtime_gc.pyへ新規実装したtombstone owner/group/mode検証
    # （orphan lock cleanup経路）を、実際のRuntimeGc.run()で検証する。
    from app.services.runtime_gc import RuntimeGc

    def _make_orphan_lock_with_tombstone(data_root: str, leases_root: str) -> str:
        """孤立lock（active entryは存在しないがlock/tombstoneは残る状態）を
        実際のacquire→release経由で作る。"""
        coord = LeaseCoordinator(
            Path(leases_root), uid=PUBLIC_UID, gid=PUBLIC_GID, lease_ttl_s=30.0,
            expect_owner_gid=LEASES_GID, leases_owner_uid=OPERATOR_UID,
        )
        handle = coord.acquire_current(Path(data_root), "permmatrix-tombstone-gc")
        lease_id = handle.payload.lease_id
        coord.release(handle)
        return lease_id

    def _try_gc_removes_orphan(data_root: str, leases_root: str, lease_id: str, out_path: str) -> None:
        gc = RuntimeGc(
            data_runtime_root=Path(data_root), leases_root=Path(leases_root),
            expect_writer_uid=OPERATOR_UID, expect_writer_gid=OPERATOR_GID,
            version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1,
            min_free_inodes=None, leases_owner_uid=OPERATOR_UID, leases_gid=LEASES_GID,
            known_lease_owner_uids=frozenset({PUBLIC_UID, OPERATOR_UID}),
        )
        result = gc.run()
        lock_path_after = os.path.join(leases_root, "locks", f"{lease_id}.lock")
        Path(out_path).write_text(json.dumps({
            "lock_removed": lease_id in result.orphan_locks_removed,
            "lock_exists": os.path.lexists(lock_path_after),
        }))

    def _seed_orphan(data_root: str, leases_root: str, out_path: str) -> None:
        lease_id = _make_orphan_lock_with_tombstone(data_root, leases_root)
        Path(out_path).write_text(lease_id)

    seed_out = "/tmp/permmatrix_tombstone_lease_id.txt"
    if os.path.lexists(seed_out):
        os.unlink(seed_out)
    ok_seed, code_seed = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _seed_orphan(DATA_RUNTIME_ROOT, leases_root, seed_out))
    record("tombstone準備: publicとして実際にacquire→releaseし孤立lock+tombstoneを作る", ok_seed, f"exit={code_seed}")
    if not ok_seed or not os.path.lexists(seed_out):
        return
    orphan_lease_id = Path(seed_out).read_text().strip()
    orphan_tomb_path = os.path.join(leases_root, "retired", f"{orphan_lease_id}.tombstone")

    gc_out = "/tmp/permmatrix_tombstone_gc_result.json"

    def run_gc_and_record(label_suffix: str, expect_removed: bool) -> None:
        if os.path.lexists(gc_out):
            os.unlink(gc_out)
        ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID],
                             lambda: _try_gc_removes_orphan(DATA_RUNTIME_ROOT, leases_root, orphan_lease_id, gc_out))
        result = json.loads(Path(gc_out).read_text()) if os.path.lexists(gc_out) else {}
        removed = bool(result.get("lock_removed"))
        record(f"tombstone {label_suffix}【実RuntimeGc app-level検証】",
               ok and removed == expect_removed, f"exit={code} result={result}")

    # baseline: tombstoneが正規owner/group/modeならGCが実際にorphan lockを削除する
    run_gc_and_record("baseline: 正規owner/group/modeならGCがorphan lockを削除する", expect_removed=True)

    # 削除された後は再度作り直す必要がある（GCがlock自体も消費するため）
    ok_seed2, _ = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _seed_orphan(DATA_RUNTIME_ROOT, leases_root, seed_out))
    orphan_lease_id = Path(seed_out).read_text().strip() if os.path.lexists(seed_out) else orphan_lease_id
    orphan_tomb_path = os.path.join(leases_root, "retired", f"{orphan_lease_id}.tombstone")

    # owner単独mutation。65534(nobody相当)は`known_lease_owner_uids`
    # （public/operatorのみ）に含まれない未知の識別子であり、これを
    # 使う（OPERATOR_UIDへ変更すると「別の既知の正規owner」に該当して
    # しまい、意図した検出にならない——実際にこの誤りを標準実行で
    # 検出・修正した）。
    os.chown(orphan_tomb_path, 65534, LEASES_GID)
    run_gc_and_record("single-mutation【owner単独】: tombstoneのownerを未知のUIDへ誤らせてもGCは安全側でlockを削除しない", expect_removed=False)

    _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _seed_orphan(DATA_RUNTIME_ROOT, leases_root, seed_out))
    orphan_lease_id = Path(seed_out).read_text().strip() if os.path.lexists(seed_out) else orphan_lease_id
    orphan_tomb_path = os.path.join(leases_root, "retired", f"{orphan_lease_id}.tombstone")
    os.chown(orphan_tomb_path, PUBLIC_UID, OPERATOR_GID)  # group単独mutation
    run_gc_and_record("single-mutation【group単独】: tombstoneのgroupを誤らせてもGCは安全側でlockを削除しない", expect_removed=False)

    _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _seed_orphan(DATA_RUNTIME_ROOT, leases_root, seed_out))
    orphan_lease_id = Path(seed_out).read_text().strip() if os.path.lexists(seed_out) else orphan_lease_id
    orphan_tomb_path = os.path.join(leases_root, "retired", f"{orphan_lease_id}.tombstone")
    os.chmod(orphan_tomb_path, 0o640)  # mode単独mutation
    run_gc_and_record("single-mutation【mode単独】: tombstoneのmodeを誤らせてもGCは安全側でlockを削除しない", expect_removed=False)
    os.chmod(orphan_tomb_path, 0o440)

    for p in (seed_out, gc_out):
        if os.path.lexists(p):
            os.unlink(p)
    lock_path_leftover = os.path.join(leases_root, "locks", f"{orphan_lease_id}.lock")
    for p in (lock_path_leftover, orphan_tomb_path):
        try:
            os.chmod(p, 0o640)
        except (FileNotFoundError, PermissionError):
            pass
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


# ── 5. active/locks/retired directory（CODEX第3ラウンド指摘で追加） ──────
# mode 3770（setgid+sticky）、owner=operator、group=leases_gid。sticky bit
# のため、他ユーザーが作成したentryを削除できるのはowner本人だけに制限
# される（GC等の安全なcleanupに必要な性質）。ここではpublicが実際に
# 新規entry（自分のlease相当のfile）を作成できること（baseline）と、
# groupが誤っていれば作成できなくなること（single-mutation）を検証する。

def _reset_lease_subdir(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    os.chown(path, OPERATOR_UID, LEASES_GID)
    os.chmod(path, 0o3770)


def _reset_all_lease_subdirs(leases_root: str) -> None:
    for sub in ("active", "locks", "retired"):
        _reset_lease_subdir(os.path.join(leases_root, sub))


def _try_acquire(data_root: str, leases_root: str) -> None:
    coord = LeaseCoordinator(
        Path(leases_root), uid=PUBLIC_UID, gid=PUBLIC_GID, lease_ttl_s=30.0,
        expect_owner_gid=LEASES_GID, leases_owner_uid=OPERATOR_UID,
    )
    handle = coord.acquire_current(Path(data_root), "permmatrix-subdir-acquire")
    coord.release(handle)


def run_lease_subdir_matrix(data_root: str, leases_root: str) -> None:
    """CODEX P2B5-CX-007（第5ラウンド）対応: 旧実装はpublicによる生の
    open()（raw OS-level probe、`_acquire_once()`を経由しない）で
    「owner誤設定後もoperatorがgroup経由でentry作成できる」ことをそのまま
    PASS記録しており、これは実際のconsumer（`LeaseCoordinator._acquire_once()`
    ——本ラウンドでactive/locks/retiredのowner/mode実検証を新規実装した）が
    対象操作をfail-closedにすることを検証していなかった。本版では実際の
    `coord.acquire_current()`をpublic UIDとして呼び出し、application-level
    検証がowner/group/modeいずれの単独逸脱もfail-closedにすることを直接
    確認する。"""
    for sub in ("active", "locks", "retired"):
        subdir = os.path.join(leases_root, sub)

        _reset_all_lease_subdirs(leases_root)
        ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_acquire(data_root, leases_root))
        record(f"{sub}/ baseline【実acquire、app-level検証】: owner=operator/group=leases_gid(20001)/mode=3770なら"
               "publicがacquire_current()を実際に完了できる",
               ok, f"exit={code}")

        _reset_all_lease_subdirs(leases_root)
        os.chown(subdir, PUBLIC_UID, LEASES_GID)  # owner単独mutation
        ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_acquire(data_root, leases_root))
        record(f"{sub}/ single-mutation【owner単独、app-level検証】: ownerをpublicへ誤らせる（groupはleases_gidのまま） → "
               "_acquire_once()のdirectory owner/mode厳密検証によりacquireそのものがfail-closedになる"
               "（Unix permission bit上はgroup経由で新規entry作成が可能な場合でも、application-levelで"
               "数値ownershipの逸脱を検出する）",
               not ok, f"exit={code}")

        _reset_all_lease_subdirs(leases_root)
        os.chown(subdir, OPERATOR_UID, OPERATOR_GID)  # group単独mutation
        ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_acquire(data_root, leases_root))
        record(f"{sub}/ single-mutation【group単独、app-level検証】: groupをoperator自身のprimary gidへ誤らせる"
               "（ownerはoperatorのまま） → acquireがfail-closedになる",
               not ok, f"exit={code}")

        _reset_all_lease_subdirs(leases_root)
        os.chmod(subdir, 0o3750)  # mode単独mutation
        ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _try_acquire(data_root, leases_root))
        record(f"{sub}/ single-mutation【mode単独、app-level検証】: modeからgroup write bitを外す(3750) → "
               "acquireがfail-closedになる",
               not ok, f"exit={code}")

        _reset_all_lease_subdirs(leases_root)


# ── 6. clock.state（GCのclock rollback検出が読み書きするfile） ──────────

def _reset_clock_state(path: str) -> None:
    if os.path.lexists(path):
        os.unlink(path)
    fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
    os.write(fd, b"0")
    os.close(fd)
    os.chown(path, OPERATOR_UID, LEASES_GID)
    os.chmod(path, 0o660)


def _try_read_write(path: str) -> None:
    fd = os.open(path, os.O_RDWR)
    os.close(fd)


def _try_gc_clock_precheck(data_root: str, leases_root: str) -> None:
    """CODEX P2B5-CX-007（第4ラウンド）対応: 「third partyがwrite不可」
    というOS-level確認だけでなく、RuntimeGc自身のapp-level検証（本ラウンドで
    runtime_gc.pyへ新規実装したclock.state owner/mode検証）を実際に実行
    させ、正しいowner/group/modeでなければGCがfail-closedになることを
    実証する。"""
    from app.services.runtime_gc import RuntimeGc

    gc = RuntimeGc(
        data_runtime_root=Path(data_root), leases_root=Path(leases_root),
        expect_writer_uid=OPERATOR_UID, expect_writer_gid=OPERATOR_GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1,
        min_free_inodes=None, leases_owner_uid=OPERATOR_UID, leases_gid=LEASES_GID,
    )
    gc._fail_closed_precheck()  # noqa: SLF001


def run_clock_state_matrix(data_root: str, leases_root: str) -> None:
    clock_path = os.path.join(leases_root, "clock.state")

    _reset_clock_state(clock_path)
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_read_write(clock_path))
    record("clock.state baseline: owner=operator/group=leases_gid/mode=0660ならoperatorがread-write openできる", ok, f"exit={code}")
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_gc_clock_precheck(data_root, leases_root))
    record("clock.state baseline【RuntimeGc実app-level検証】: 正しいowner/group/modeならGCのfail_closed_precheckを通過する",
           ok, f"exit={code}")

    # CODEX P2B5-CX-007（第4ラウンド）対応: owner単独mutation（groupは
    # leases_gidのまま正しく残す）。
    _reset_clock_state(clock_path)
    os.chown(clock_path, PUBLIC_UID, LEASES_GID)
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_gc_clock_precheck(data_root, leases_root))
    record("clock.state single-mutation【owner単独、RuntimeGc実app-level検証】: ownerのみpublicへ誤設定 → "
           "GCのfail_closed_precheckがfail-closedになる（app-levelの厳密一致要求）",
           not ok, f"exit={code}")

    # group単独mutation（ownerはoperatorのまま正しく残す）。
    _reset_clock_state(clock_path)
    os.chown(clock_path, OPERATOR_UID, OPERATOR_GID)
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_gc_clock_precheck(data_root, leases_root))
    record("clock.state single-mutation【group単独、RuntimeGc実app-level検証】: groupのみoperator自身のprimary gidへ誤設定 → "
           "GCのfail_closed_precheckがfail-closedになる",
           not ok, f"exit={code}")

    # mode単独mutation（owner/groupは正しいまま）。OS-levelでは依然
    # operatorはread-write可能だが、app-level検証は「正しいmode(0660)」を
    # 厳密に要求するため、0644等への逸脱もfail-closedになるはず。
    _reset_clock_state(clock_path)
    os.chmod(clock_path, 0o644)
    ok, code = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], lambda: _try_gc_clock_precheck(data_root, leases_root))
    record("clock.state single-mutation【mode単独、RuntimeGc実app-level検証】: modeのみ0644へ誤設定 → "
           "owner/operatorはOS-levelでは依然read-write可能だが、GCのapp-level検証は正しい0660を"
           "厳密に要求するためfail-closedになる（旧実装は「第三者がwrite不可」しか確認しておらず、"
           "0660固定要求そのものは未証明だった）",
           not ok, f"exit={code}")

    _reset_clock_state(clock_path)
    ok, code = _fork_as(65534, 65534, [], lambda: _try_read_write(clock_path))
    record("clock.state single-mutation【第三者、OS-level】: owner/group双方に属さない第三者はbaseline状態でもwrite不可",
           not ok, f"exit={code}")

    _reset_clock_state(clock_path)


# ── 7. active entry / lease lock（実際のacquireで生成された実artifact） ──
# CODEX第3ラウンド指摘: 「active entry」「lease lock」もmatrix対象として
# 明示的に列挙されている。ここでは実際に`LeaseCoordinator.acquire_current()`
# をpublic UIDとして呼び出し、本物のactive/<id>.json・locks/<id>.lockを
# 生成した上で、それぞれのowner/mode単独mutationがrenew()をfail-closedに
# することを確認する。

def run_real_active_entry_and_lock_matrix(data_root: str, leases_root: str) -> None:
    from app.services.runtime_lease import LeaseError as _LeaseError

    def _acquire_and_dump(out_path: str) -> None:
        coord = LeaseCoordinator(
            Path(leases_root), uid=PUBLIC_UID, gid=PUBLIC_GID, lease_ttl_s=30.0,
            expect_owner_gid=LEASES_GID, leases_owner_uid=OPERATOR_UID,
        )
        handle = coord.acquire_current(Path(data_root), "permmatrix-real-entry")
        Path(out_path).write_text(json.dumps({"lease_id": handle.payload.lease_id}))
        # renewできる状態のままlock fd等はprocess終了で自動closeされる
        # （coord.release()は呼ばない — active entry/lock/tombstoneを
        # そのまま残してmutation対象にするため）。

    out_path = "/tmp/permmatrix_real_lease.json"
    if os.path.lexists(out_path):
        os.unlink(out_path)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], lambda: _acquire_and_dump(out_path))
    record("real active entry/lock: publicとして実際にacquire_current()が成功する（以降のmatrix対象artifactを生成）", ok, f"exit={code}")
    if not ok or not os.path.lexists(out_path):
        return
    lease_id = json.loads(Path(out_path).read_text())["lease_id"]
    active_path = os.path.join(leases_root, "active", f"{lease_id}.json")
    lock_path = os.path.join(leases_root, "locks", f"{lease_id}.lock")

    def _try_renew() -> None:
        coord = LeaseCoordinator(
            Path(leases_root), uid=PUBLIC_UID, gid=PUBLIC_GID, lease_ttl_s=30.0,
            expect_owner_gid=LEASES_GID, leases_owner_uid=OPERATOR_UID,
        )
        lock_fd = os.open(lock_path, os.O_RDWR)
        st = os.fstat(lock_fd)
        os.lseek(lock_fd, 0, os.SEEK_SET)
        generation_id = os.read(lock_fd, 256).decode("utf-8")
        payload = json.loads(Path(active_path).read_text())
        from app.services.runtime_lease import LeaseHandle, LeasePayload
        handle = LeaseHandle(
            leases_root=Path(leases_root),
            payload=LeasePayload(**payload),
            generation_id=generation_id,
            lock_fd=lock_fd, lock_ino=st.st_ino, lock_dev=st.st_dev,
        )
        coord.renew(handle)

    # active entry single-mutation【owner単独】: groupはleases_gidのまま残す。
    # CODEX第5ラウンド指摘: 本ラウンドで`LeaseCoordinator._verify_active_
    # entry_identity()`をrenew()/release()へ新規実装し、active entry自身の
    # owner/group/modeをapplication-levelで厳密検証するようになった
    # （従来はUnix permission bitのfallback経路——sticky bit保護等——に
    # 依存しており、「owner不一致でもgroup権限経由なら成功する場合がある」
    # という状態がPASSとして記録されてしまっていた）。owner・group
    # いずれの単独mutationも、いまはapplication-level検証がUnix permission
    # bitより先に働き、確実にfail-closedになる。
    os.chown(active_path, OPERATOR_UID, LEASES_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], _try_renew)
    record("active entry single-mutation【owner単独、app-level検証】: ownerのみoperatorへ誤らせる"
           "（groupはleases_gidのまま） → LeaseCoordinator._verify_active_entry_identity()が"
           "厳密一致を要求するためfail-closedになる（Unix permission bit上はgroup経由で"
           "アクセス可能な場合でも、application-levelで数値ownershipの逸脱を検出する）",
           not ok, f"exit={code}")
    os.chown(active_path, PUBLIC_UID, LEASES_GID)

    # active entry single-mutation【group単独】: ownerはpublicのまま残す。
    os.chown(active_path, PUBLIC_UID, OPERATOR_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], _try_renew)
    record("active entry single-mutation【group単独、app-level検証】: groupのみoperator自身のprimary gidへ"
           "誤らせる（ownerはpublicのまま） → application-level検証がfail-closedになる"
           "（ownerが正しくてもgroup逸脱だけで拒否される）",
           not ok, f"exit={code}")
    os.chown(active_path, PUBLIC_UID, LEASES_GID)

    # active entry single-mutation【mode】: 全アクセス不可(0000)にする
    # （注意: 0600等owner権限を残すmodeへの変異は、実entryのownerが
    # まさにpublic自身であるため、public視点では拒否にならず誤った
    # positiveになる。owner自身のアクセスも含めて確実に拒否させるため
    # 0000を使う）。
    os.chmod(active_path, 0o000)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], _try_renew)
    record("active entry single-mutation【mode】: modeを0000へ変更 → owner自身であるpublicのrenewもOS-levelで拒否される",
           not ok, f"exit={code}")
    os.chmod(active_path, 0o660)

    # lease lock single-mutation【owner単独】: groupはleases_gidのまま。
    # CODEX第5ラウンド指摘対応: 本ラウンドで`_verify_lock_identity()`へ
    # owner/group厳密検証を新規追加した（従来はdevice/inode/generation ID
    # の差替え検出のみで、正規の数値ownershipそのものは検証していなかった）。
    os.chown(lock_path, OPERATOR_UID, LEASES_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], _try_renew)
    record("lease lock single-mutation【owner単独、app-level検証】: ownerのみoperatorへ誤らせる"
           "（groupはleases_gidのまま） → _verify_lock_identity()のowner厳密一致要求により"
           "fail-closedになる",
           not ok, f"exit={code}")
    os.chown(lock_path, PUBLIC_UID, LEASES_GID)

    # lease lock single-mutation【group単独】: ownerはpublicのまま。
    os.chown(lock_path, PUBLIC_UID, OPERATOR_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], _try_renew)
    record("lease lock single-mutation【group単独、app-level検証】: groupのみoperator自身のprimary gidへ"
           "誤らせる（ownerはpublicのまま） → _verify_lock_identity()のgroup厳密一致要求により"
           "fail-closedになる",
           not ok, f"exit={code}")
    os.chown(lock_path, PUBLIC_UID, LEASES_GID)

    # lease lock single-mutation【mode】: modeを読み取り専用にする（generation_id read/write不可）
    os.chmod(lock_path, 0o440)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID], _try_renew)
    record("lease lock single-mutation【mode】: modeをread-onlyへ変更 → renewのlock re-open(O_RDWR)が拒否される",
           not ok, f"exit={code}")
    os.chmod(lock_path, 0o660)

    # cleanup
    try:
        os.unlink(active_path)
    except FileNotFoundError:
        pass
    try:
        os.unlink(lock_path)
    except FileNotFoundError:
        pass
    tomb_path = os.path.join(leases_root, "retired", f"{lease_id}.tombstone")
    try:
        os.chmod(tomb_path, 0o640)
        os.unlink(tomb_path)
    except FileNotFoundError:
        pass


# ── 8. published version directory/normal data file（CODEX第4ラウンド指摘で追加） ──
# 指示書第5節が明示的に列挙する「published version tree」自体のowner/
# group/mode単独mutation matrix。data_runtime rootのmatrix（#3）は
# current symlink経由のtraverse可否を検証していたが、tree内部の個々の
# fileそのものへのowner/group/mode単独mutationは対象化していなかった
# （CODEX指摘: 「published version directory／normal data fileの
# owner／group／modeのmatrixがない」）。

def _reset_published_file(root: str) -> str:
    vid = "20260101T000000Z-cafebabe"
    version_dir = os.path.join(root, "versions", vid)
    d = os.path.join(version_dir, "backend", "hazard")
    os.makedirs(d, exist_ok=True, mode=0o750)
    fp = os.path.join(d, "published_matrix.geojson")
    if os.path.lexists(fp):
        os.unlink(fp)
    fd = os.open(fp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
    os.write(fd, b'{"marker": "published-file-matrix"}')
    os.close(fd)
    os.chown(fp, OPERATOR_UID, LEASES_GID)
    os.chmod(fp, 0o640)
    os.chown(d, OPERATOR_UID, LEASES_GID)
    os.chmod(d, 0o750)
    # CODEX P2B5-CX-007（第7ラウンド）対応: version directory自体
    # （`versions/<vid>/`、backend/hazardの親）も、実運用の
    # deploy_to_runtime_atomic.shの`chgrp -R`が及ぶ範囲と同じくleases_gid
    # へ揃える（本ラウンドで新設したversion directory自体のownership検証
    # のbaselineとして必要）。intermediate directory（backend/）も同様。
    backend_dir = os.path.join(version_dir, "backend")
    for p in (version_dir, backend_dir):
        os.chown(p, OPERATOR_UID, LEASES_GID)
        os.chmod(p, 0o750)
    return fp


def _try_read_published(path: str) -> None:
    with open(path, "rb"):
        pass


def _try_stream_versioned_file(root: str, leases_root: str, relative_path: str) -> None:
    """CODEX P2B5-CX-007（第5ラウンド）対応: 実際のconsumer関数
    （runtime_version_access.stream_versioned_file()、本ラウンドで
    `_verify_served_file_ownership()`を新規実装した読み取りpath）を
    直接呼び出す。raw open()による生のOS-level probeでは、実装の
    application-level検証（正規owner/group/modeの厳密一致要求）を
    経由しないため、CODEXから「fallback成功をPASSと誤記録している」と
    指摘された。"""
    import asyncio
    from app.services import runtime_version_access as rva

    rva.DATA_RUNTIME_ROOT = Path(root)
    rva.LEASES_ROOT = Path(leases_root)
    rva._coordinator = None
    rva._LEASES_OWNER_UID = OPERATOR_UID
    rva._LEASES_GID = LEASES_GID

    async def _run():
        chunks = []
        async for chunk in rva.stream_versioned_file(relative_path, "permmatrix-file-test"):
            chunks.append(chunk)
        return chunks

    asyncio.run(_run())


def run_published_version_file_matrix(root: str, leases_root: str) -> None:
    vid = "20260101T000000Z-cafebabe"
    rel_path = "backend/hazard/published_matrix.geojson"
    current_link = os.path.join(root, "current")

    def _seed_and_point_current():
        _reset_published_file(root)
        if os.path.lexists(current_link):
            os.unlink(current_link)
        os.symlink(f"versions/{vid}", current_link)

    ok_seed, code_seed = _fork_as(OPERATOR_UID, OPERATOR_GID, [LEASES_GID], _seed_and_point_current)
    fp = os.path.join(root, "versions", vid, "backend", "hazard", "published_matrix.geojson")
    record("published version file: 準備（operatorによる実publish同等のfile作成＋current repoint）が成功する", ok_seed, f"exit={code_seed}")

    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
                         lambda: _try_stream_versioned_file(root, leases_root, rel_path))
    record("published version file baseline【実stream_versioned_file、app-level検証】: "
           "owner=operator/group=leases_gid(20001)/mode=0640ならpublicが実際にstreamingできる",
           ok, f"exit={code}")

    # owner単独mutation（groupはleases_gidのまま）。
    os.chown(fp, PUBLIC_UID, LEASES_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
                         lambda: _try_stream_versioned_file(root, leases_root, rel_path))
    record("published version file single-mutation【owner単独、app-level検証】: ownerがpublic自身へ変わる"
           "（groupはleases_gidのまま） → `_verify_served_file_ownership()`が厳密一致（owner=operator固定）を"
           "要求するためfail-closedになる（Unix permission bit上はowner自身のreadとして成功しうる場合でも、"
           "application-levelで期待ownershipからの逸脱を検出する）",
           not ok, f"exit={code}")

    # group単独mutation（ownerはoperatorのまま）。
    os.chown(fp, OPERATOR_UID, OPERATOR_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
                         lambda: _try_stream_versioned_file(root, leases_root, rel_path))
    record("published version file single-mutation【group単独、app-level検証】: groupのみoperator自身の"
           "primary gidへ誤らせる（本ラウンドでdeploy_to_runtime_atomic.shへ追加したchgrp -Rが無効化された"
           "状況の再現） → streamingがfail-closedになる",
           not ok, f"exit={code}")

    # mode単独mutation（owner/groupは正しいまま）。
    os.chown(fp, OPERATOR_UID, LEASES_GID)
    os.chmod(fp, 0o600)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
                         lambda: _try_stream_versioned_file(root, leases_root, rel_path))
    record("published version file single-mutation【mode単独、app-level検証】: modeを0600へ誤らせる → "
           "streamingがfail-closedになる",
           not ok, f"exit={code}")

    os.chmod(fp, 0o640)

    # CODEX P2B5-CX-007（第7ラウンド）対応: 上のmatrixはfile自体のowner/
    # group/modeだけを変異させていた。指示書第5節が要求する「published
    # version directory」自体（backend/hazardの親である`versions/<vid>/`）
    # のownershipに対するsingle-mutation matrixが存在しないと独立検証で
    # 指摘された。本ラウンドで新設した
    # `runtime_lease.leased_version_root()`／
    # `runtime_version_access._verify_version_root_ownership()`が、この
    # version directory自体を検証することを確認する。
    version_dir = os.path.join(root, "versions", vid)

    def _reset_version_dir():
        os.chown(version_dir, OPERATOR_UID, LEASES_GID)
        os.chmod(version_dir, 0o750)

    _reset_version_dir()
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
                         lambda: _try_stream_versioned_file(root, leases_root, rel_path))
    record("published version directory baseline【実stream_versioned_file、app-level検証】: "
           "version directory自体がowner=operator/group=leases_gid(20001)/mode=0750ならpublicが"
           "streamingできる",
           ok, f"exit={code}")

    # owner単独mutation（version directory自体、groupはleases_gidのまま）。
    os.chown(version_dir, PUBLIC_UID, LEASES_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
                         lambda: _try_stream_versioned_file(root, leases_root, rel_path))
    record("published version directory single-mutation【owner単独、app-level検証】: "
           "version directory自体のownerがpublicへ誤る（groupはleases_gidのまま） → "
           "`_verify_version_root_ownership()`がfail-closedになる（OS-levelではgroup経由で"
           "traverse可能な場合でも、application-levelでdirectory自体のowner逸脱を検出する）",
           not ok, f"exit={code}")

    # group単独mutation（version directory自体、ownerはoperatorのまま）。
    _reset_version_dir()
    os.chown(version_dir, OPERATOR_UID, OPERATOR_GID)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
                         lambda: _try_stream_versioned_file(root, leases_root, rel_path))
    record("published version directory single-mutation【group単独、app-level検証】: "
           "version directory自体のgroupをoperator自身のprimary gidへ誤らせる"
           "（deploy_to_runtime_atomic.shのchgrp -Rが対象directory自体には効かなかった状況の再現） → "
           "streamingがfail-closedになる",
           not ok, f"exit={code}")

    # mode単独mutation（version directory自体、owner/groupは正しいまま）。
    _reset_version_dir()
    os.chmod(version_dir, 0o700)
    ok, code = _fork_as(PUBLIC_UID, PUBLIC_GID, [LEASES_GID],
                         lambda: _try_stream_versioned_file(root, leases_root, rel_path))
    record("published version directory single-mutation【mode単独、app-level検証】: "
           "version directory自体のmodeを0700へ誤らせる（group traverse不可） → streamingがfail-closedになる",
           not ok, f"exit={code}")

    _reset_version_dir()
    try:
        os.unlink(fp)
    except FileNotFoundError:
        pass


def main() -> int:
    if os.geteuid() != 0:
        print("FAIL: このscriptはroot(uid 0)で実行する必要がある", file=sys.stderr)
        return 2

    leases_root = "/run/onhighground2/leases"
    os.makedirs(DATA_RUNTIME_ROOT, exist_ok=True)
    run_publish_lock_matrix(os.path.join(DATA_RUNTIME_ROOT, ".publish.lock"))
    run_coordination_lock_matrix(leases_root)
    run_data_runtime_root_matrix(DATA_RUNTIME_ROOT, leases_root)
    # 実行順序の注意: run_tombstone_matrix()（実RuntimeGc.run()を使う）は
    # clock.stateの存在と、active/locks/retiredの正規owner/modeを前提と
    # する（本ラウンドでRuntimeGc._fail_closed_precheck()へ両方の実検証を
    # 追加したため）。run_lease_subdir_matrix()とrun_clock_state_matrix()
    # を先に実行し、それぞれのmutationを正規状態へreset済みにしてから
    # run_tombstone_matrix()を呼ぶ。
    run_lease_subdir_matrix(DATA_RUNTIME_ROOT, leases_root)
    run_clock_state_matrix(DATA_RUNTIME_ROOT, leases_root)
    run_tombstone_matrix(leases_root)
    run_real_active_entry_and_lock_matrix(DATA_RUNTIME_ROOT, leases_root)
    run_published_version_file_matrix(DATA_RUNTIME_ROOT, leases_root)

    print(json.dumps({"results": RESULTS}, ensure_ascii=False))
    failed = [r for r in RESULTS if not r["pass"]]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

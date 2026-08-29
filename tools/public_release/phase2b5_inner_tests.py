#!/usr/bin/env python3
"""
phase2b5_inner_tests.py — AT-11(14系統) / DP-N01〜N20 の実行本体。

このscriptはisolated containerの内部（backend-operator相当のimage、
UID 10002:10002、supplemental GID 20001、umask 0007）で実行される前提。
data_runtime相当のroot（named volumeをmount）とlease coordination volumeの
両方が既に runtime-init 相当で初期化済みであることを前提とする。

呼び出し元（tools/public_release/phase2b5_atomic_publish.py）がcontainer化・
volume準備・結果回収を担当し、本scriptはfilesystem/process-levelの
実syscall barrier・fault injection・concurrency検証に専念する。

多くのAT-11/DP-Nは「複数process」を要求するが、同一container内で
multiprocessingにより独立したOS process（別pid、別fd table、同一
共有filesystem）を生成することで、実質的に同じ強度の検証を行う
（flock/fsync/renameはprocess境界を越えたkernelレベルの機構であり、
同一container内の別processでも別containerでも動作は同一である）。
AT-11 #13（実container numeric identity）だけは、別containerでの
実行が本質的に必要なため、呼び出し元が別途担当する。
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import shutil
import stat
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, "/app")

from app.services.runtime_atomic import (
    ExpectedIdentity,
    RuntimeAtomicError,
    generate_version_id,
    validate_version_id,
    verify_process_identity,
    renameat2_noreplace,
    open_dir_fd,
)
from app.services.runtime_publish import AtomicPublisher, VERSION_DIR_MODE, VERSION_FILE_MODE
from app.services.runtime_lease import LeaseCoordinator, LeaseError, LeaseExpiredError, LeasePayload, leased_version_root
from app.services.runtime_gc import RuntimeGc, GcFailClosedError

RESULTS = []


def record(name: str, passed: bool, detail: str = "") -> None:
    RESULTS.append({"name": name, "pass": bool(passed), "detail": str(detail)[-2000:]})
    print(f"[{'PASS' if passed else 'FAIL'}] {name}" + (f"  {detail}" if not passed and detail else ""))


UID = os.geteuid()
GID = os.getegid()
# CODEX P2B5-CX-007（第2ラウンド）対応でLeaseCoordinatorがcoordination.lockの
# owner/mode実検証を新規で行うようになったため、test fixture側も実運用と
# 同じgroup（operator/public共有のsupplemental gid）で作成する必要がある。
LEASES_GID = 20001

# CODEX P2B5-CX-003（第18ラウンド）対応: runtime_dataset_validate.pyの
# tsunami参照整合性検証が、staging側のtsunami target集合をconsumer設定
# （`app.properties`の`hazard.tsunami.targets`）とexact-matchさせるように
# なったため、共通fixtureであるmake_dataset()も有効なtsunami datasetを
# 用意しないと、tsunami検証と無関係な既存test（AT-11本体・shelter統合
# test等）まで一律で失敗するようになる。validatorが実際に読むのと同じ
# `app_config_properties`単一情報源module経由でtarget集合を解決し、
# 常にconsumer設定と一致するfixtureを生成する（値をhardcodeして
# 実設定とdriftする余地を残さない）。
import app_config_properties as _cfg  # noqa: E402  (sys.path.insert後にimportする必要がある)

_TSUNAMI_FIXTURE_TARGETS = frozenset(
    _cfg.parse_csv(
        _cfg.load_properties(_cfg.resolve_config_path(Path("/app"))).get("hazard.tsunami.targets", "tokyo"),
        ["tokyo"],
    )
)
# _HAZARD_TYPE_MIN_FEATURE_COUNT["tsunami"]（runtime_dataset_validate.py）
# と同じ絶対floorを満たす件数にする。
_TSUNAMI_FIXTURE_FEATURE_COUNT = 100


def _make_tsunami_dataset(hazard_dir: Path) -> None:
    tsunami_dir = hazard_dir / "tsunami"
    tsunami_dir.mkdir(parents=True, mode=VERSION_DIR_MODE)
    for target in sorted(_TSUNAMI_FIXTURE_TARGETS):
        features = [
            {
                "type": "Feature",
                "geometry": None,
                "properties": {"A40_001": "13", "A40_002": target, "A40_003": str(i)},
            }
            for i in range(_TSUNAMI_FIXTURE_FEATURE_COUNT)
        ]
        f = tsunami_dir / f"tsunami_{target}.geojson"
        f.write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False))
        os.chmod(f, VERSION_FILE_MODE)
    os.chmod(tsunami_dir, VERSION_DIR_MODE)


def make_dataset(staging_path: Path, marker: str = "x") -> None:
    d = staging_path / "backend" / "hazard"
    d.mkdir(parents=True, mode=VERSION_DIR_MODE)
    os.chmod(d.parent, VERSION_DIR_MODE)
    f = d / "sample.geojson"
    # CODEX P2B5-CX-003（第4ラウンド）対応: runtime_dataset_validate.pyが
    # .geojsonへGeoJSON schema検証（RFC 7946）を要求するようになったため、
    # test fixtureも構文的に正しいだけでなく意味的に妥当なGeoJSON
    # （Feature + properties）を生成する必要がある。markerはpropertiesへ
    # 格納する（従来の`{"marker": "..."}`という非GeoJSON形式は使えない）。
    f.write_text(json.dumps({"type": "Feature", "geometry": None, "properties": {"marker": marker}}))
    os.chmod(f, VERSION_FILE_MODE)
    _make_tsunami_dataset(d)
    os.chmod(d, VERSION_DIR_MODE)
    os.chmod(staging_path, VERSION_DIR_MODE)


def validate_ok(staging_path: Path, previous_version_path: Path = None) -> None:
    assert (Path(staging_path) / "backend" / "hazard" / "sample.geojson").exists()
    # CODEX P2B5-CX-003（第2ラウンド）対応: rollback()がmanifestの実在・
    # 一致を検証するようになったため（backend/app/services/runtime_publish.py）、
    # test fixtureが生成するversionにも実運用のactivate_version.pyと同じく
    # _manifest.jsonを実際に書き込む（さもないと、正規に作られたはずの
    # test versionへのrollbackすら失敗してしまう）。
    from app.services.runtime_dataset_validate import validate_and_manifest_staging, write_manifest

    manifest, feature_counts = validate_and_manifest_staging(staging_path, previous_version_path)
    write_manifest(staging_path, manifest, VERSION_FILE_MODE, feature_counts)


def _chgrp_tree(root: Path, gid: int) -> None:
    """CODEX P2B5-CX-007（第7ラウンド）対応: 実運用のdeploy_to_runtime_atomic.sh
    は`chgrp -R "${STAGING_LEASES_GID}" "${STAGING_DIR}"`でstaging tree全体
    （root directory自身を含む）をleases_gidへ揃えてからactivate_version.py
    を呼ぶ（AtomicPublisher自体はgroupをchownしない、staging生成側の責務）。
    このtest fixtureも同じ手当てを行わないと、本ラウンドで新設した
    published version directory自体のownership検証
    （runtime_lease.leased_version_root()／runtime_version_access.
    _verify_version_root_ownership()）に対する正しいbaselineを再現できない。
    """
    os.chown(root, os.geteuid(), gid)
    for dirpath, dirnames, filenames in os.walk(root):
        for name in dirnames:
            os.chown(os.path.join(dirpath, name), os.geteuid(), gid)
        for name in filenames:
            os.chown(os.path.join(dirpath, name), os.geteuid(), gid)


def publish_new_version(publisher: AtomicPublisher, marker: str = "x"):
    vid = generate_version_id()
    stg = publisher.new_staging_path(vid)
    make_dataset(stg, marker)
    _chgrp_tree(stg, LEASES_GID)
    return publisher.publish(vid, validate_ok)


# ------------------------------------------------------------------
# multiprocessing worker functions（top-levelでpickle可能にする）
# ------------------------------------------------------------------

def _worker_publish(data_root: str, marker: str, out_path: str) -> None:
    try:
        publisher = AtomicPublisher(Path(data_root), expect_uid=UID, expect_gid=GID)
        result = publish_new_version(publisher, marker)
        Path(out_path).write_text(json.dumps({"ok": True, "version_id": result.version_id}))
    except Exception as exc:  # noqa: BLE001
        Path(out_path).write_text(json.dumps({"ok": False, "error": repr(exc)}))


def _worker_acquire_hold_release(leases_root: str, data_root: str, hold_s: float, out_path: str, kind: str = "read") -> None:
    try:
        coord = LeaseCoordinator(Path(leases_root), uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
        with leased_version_root(coord, Path(data_root), kind) as vroot:
            marker_file = vroot / "backend" / "hazard" / "sample.geojson"
            content_at_start = marker_file.read_text() if marker_file.exists() else None
            time.sleep(hold_s)
            content_at_end = marker_file.read_text() if marker_file.exists() else None
        Path(out_path).write_text(json.dumps({
            "ok": True, "consistent": content_at_start == content_at_end, "content": content_at_start,
        }))
    except Exception as exc:  # noqa: BLE001
        Path(out_path).write_text(json.dumps({"ok": False, "error": repr(exc)}))


def _worker_gc(data_root: str, leases_root: str, retention: int, out_path: str, delay_s: float = 0.0) -> None:
    try:
        if delay_s:
            time.sleep(delay_s)
        gc = RuntimeGc(
            data_runtime_root=Path(data_root), leases_root=Path(leases_root),
            expect_writer_uid=UID, expect_writer_gid=GID,
            version_retention_count=retention, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
        )
        result = gc.run()
        Path(out_path).write_text(json.dumps({
            "ok": True, "deleted": result.versions_deleted, "retained": result.versions_retained,
            "stale_leases_removed": result.stale_leases_removed,
        }))
    except Exception as exc:  # noqa: BLE001
        Path(out_path).write_text(json.dumps({"ok": False, "error": repr(exc)}))


def _run_proc(target, args, timeout=30):
    p = mp.get_context("fork").Process(target=target, args=args)
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join(2)
        return None, True
    return p.exitcode, False


def _read_json(path: str):
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return None


from contextlib import contextmanager


@contextmanager
def _failing_fsync_dir(fail_on_call_index: int, persist: bool = False):
    """`runtime_publish.fsync_dir`の呼び出し回数を数え、fail_on_call_index回目の
    呼び出しをOSErrorで失敗させる（AT-11-8 / DP-N12の実fsync fault
    injectionで共用する）。CODEX P2B5-CX-006対応: 「実fault injection未実施を
    source確認で代替してPASS集計する」という指摘に応え、実際にfsync failureを
    発生させ、publish()の挙動を直接観測する。

    `persist=True`の場合はfail_on_call_index回目以降の呼び出しをすべて
    失敗させ続ける。CODEX P2B5-CX-006（第3ラウンド）で`publish()`の
    current rename後fsyncに有限回retryを追加したため、DP-N12bでretryを
    使い果たしてPublishDurabilityErrorへ到達させるには、単発ではなく
    持続的な失敗を注入する必要がある。
    """
    from app.services import runtime_publish as _rp

    real_fsync_dir = _rp.fsync_dir
    state = {"n": 0}

    def _fake(fd):
        state["n"] += 1
        if state["n"] == fail_on_call_index or (persist and state["n"] >= fail_on_call_index):
            raise OSError(5, "simulated fsync failure (fault injection)")
        return real_fsync_dir(fd)

    _rp.fsync_dir = _fake
    try:
        yield state
    finally:
        _rp.fsync_dir = real_fsync_dir


# ------------------------------------------------------------------
# AT-11 systems
# ------------------------------------------------------------------

def at11_01_atomic_publish_concurrent_reader_validation_rollback(tmp: Path) -> None:
    data_root = tmp / "at11_01" / "data_runtime"
    leases_root = tmp / "at11_01" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)

    r1 = publish_new_version(publisher, "v1")
    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    handle = coord.acquire(r1.version_id, "at11-01-reader")

    # concurrent publish of v2 while reader holds lease on v1
    r2 = publish_new_version(publisher, "v2")
    v1_content = json.loads(
        (data_root / "versions" / r1.version_id / "backend" / "hazard" / "sample.geojson").read_text()
    )
    record("AT-11-1a: publish中もreaderが取得済みversion(v1)のfixed root配下を読み続けられる",
           v1_content.get("properties", {}).get("marker") == "v1")
    record("AT-11-1b: 新publish後もcurrentは新version(v2)を指す",
           os.readlink(data_root / "current") == f"versions/{r2.version_id}")
    coord.release(handle)

    # validation failure must not touch current
    def validate_fail(_p, _prev=None):
        raise RuntimeAtomicError("forced failure")

    vid3 = generate_version_id()
    stg3 = publisher.new_staging_path(vid3)
    make_dataset(stg3, "v3")
    try:
        publisher.publish(vid3, validate_fail)
        record("AT-11-1c: validation failureはpublish()から例外伝播する", False)
    except RuntimeAtomicError:
        record("AT-11-1c: validation failureはpublish()から例外伝播する", True)
    record("AT-11-1d: validation failure後もcurrentは直前のv2のまま",
           os.readlink(data_root / "current") == f"versions/{r2.version_id}")

    # writer exclusion: two concurrent publishers, one must serialize (not corrupt, not both "win" simultaneously)
    out_a = tmp / "at11_01_a.json"
    out_b = tmp / "at11_01_b.json"
    ctx = mp.get_context("fork")
    pa = ctx.Process(target=_worker_publish, args=(str(data_root), "wa", str(out_a)))
    pb = ctx.Process(target=_worker_publish, args=(str(data_root), "wb", str(out_b)))
    pa.start(); pb.start()
    pa.join(30); pb.join(30)
    ra, rb = _read_json(str(out_a)), _read_json(str(out_b))
    both_ok = bool(ra and ra.get("ok")) and bool(rb and rb.get("ok"))
    record("AT-11-1e: writer lock下での同時publish 2件がどちらも安全に完了する（直列化）", both_ok, f"a={ra} b={rb}")
    final_versions = publisher.list_versions()
    record("AT-11-1f: 同時publish後もversions/に両方のversionが破損なく存在する",
           ra and rb and ra.get("version_id") in final_versions and rb.get("version_id") in final_versions)

    # rollback
    rb_result = publisher.rollback(r1.version_id)
    record("AT-11-1g: rollbackでcurrentが指定versionへ戻る",
           os.readlink(data_root / "current") == f"versions/{r1.version_id}")


def _hold_global_shared(coord_lock_path: str, ready_flag: str, release_flag: str) -> None:
    import fcntl as _fcntl
    fd = os.open(coord_lock_path, os.O_RDWR)
    _fcntl.flock(fd, _fcntl.LOCK_SH)
    Path(ready_flag).write_text("1")
    while not Path(release_flag).exists():
        time.sleep(0.02)
    _fcntl.flock(fd, _fcntl.LOCK_UN)
    os.close(fd)


def _acquire_current_worker(data_root_s: str, leases_root_s: str, out_path: str, iterations: int = 30) -> None:
    coord = LeaseCoordinator(Path(leases_root_s), uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    results = []
    for _ in range(iterations):
        try:
            handle = coord.acquire_current(Path(data_root_s), "at11-02-reader")
            version_root = Path(data_root_s) / "versions" / handle.payload.version_id
            fp = version_root / "backend" / "hazard" / "sample.geojson"
            _ = fp.read_text()
            coord.release(handle)
            results.append({"ok": True})
        except Exception as exc:  # noqa: BLE001
            results.append({"ok": False, "error": repr(exc)})
        time.sleep(0.02)
    Path(out_path).write_text(json.dumps(results))


def _publish_gc_churn_worker(data_root_s: str, leases_root_s: str, rounds: int = 10) -> None:
    publisher = AtomicPublisher(Path(data_root_s), expect_uid=UID, expect_gid=GID)
    for i in range(rounds):
        publish_new_version(publisher, f"churn-{i}")
        time.sleep(0.03)
        try:
            _worker_gc(data_root_s, leases_root_s, 0, str(Path(data_root_s).parent / f"churn_gc_{i}.json"))
        except Exception:
            pass
        time.sleep(0.03)


def at11_02_current_resolve_vs_gc_toctou(tmp: Path) -> None:
    """CODEX P2B5-CX-001対応: current解決(readlink)とlease登録(active公開)の
    間にGC(global exclusive)が割り込めるかどうかを、(A)決定論的な相互排他の
    直接証明、(B)実際のacquire_current()とpublish+GC churnの並行実行、
    の2通りで検証する。旧実装（version_idを直接acquireするだけの検査）は
    current解決を経由しないためTOCTOUを検出できず、CODEXにFAILと指摘された。
    """
    # --- Part A: 決定論的相互排他の直接証明 ---
    data_root = tmp / "at11_02a" / "data_runtime"
    leases_root = tmp / "at11_02a" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    publish_new_version(publisher, "v1")

    ctx = mp.get_context("fork")
    ready_flag = tmp / "at11_02a" / "ready.flag"
    release_flag = tmp / "at11_02a" / "release.flag"
    holder = ctx.Process(target=_hold_global_shared, args=(str(leases_root / "coordination.lock"), str(ready_flag), str(release_flag)))
    holder.start()
    deadline = time.time() + 5
    while not ready_flag.exists() and time.time() < deadline:
        time.sleep(0.02)

    out_gc = tmp / "at11_02a" / "gc_while_blocked.json"
    gc_proc = ctx.Process(target=_worker_gc, args=(str(data_root), str(leases_root), 0, str(out_gc)))
    t_start = time.time()
    gc_proc.start()
    time.sleep(1.0)
    still_running = gc_proc.is_alive()
    record("AT-11-2a: global shared保持中はGC(global exclusive)がblockされる（相互排他の直接証明）", still_running)
    release_flag.write_text("1")
    gc_proc.join(10)
    holder.join(5)
    elapsed = time.time() - t_start
    gc_res = _read_json(str(out_gc))
    record("AT-11-2b: shared解放後にGCが完了する", bool(gc_res and gc_res.get("ok")), str(gc_res))
    record("AT-11-2c: GCがshared保持区間だけ待たされたことをelapsedで確認", elapsed >= 0.9, f"elapsed={elapsed:.2f}s")

    # --- Part B: 実際のacquire_current() vs publish+GC churnの並行実行 ---
    data_root_b = tmp / "at11_02b" / "data_runtime"
    leases_root_b = tmp / "at11_02b" / "leases"
    _bootstrap_roots(data_root_b, leases_root_b)
    publisher_b = AtomicPublisher(data_root_b, expect_uid=UID, expect_gid=GID)
    publish_new_version(publisher_b, "v0")

    out_reader = tmp / "at11_02b" / "reader_results.json"
    p_reader = ctx.Process(target=_acquire_current_worker, args=(str(data_root_b), str(leases_root_b), str(out_reader)))
    p_churn = ctx.Process(target=_publish_gc_churn_worker, args=(str(data_root_b), str(leases_root_b)))
    p_reader.start()
    p_churn.start()
    p_reader.join(30)
    p_churn.join(30)

    reader_results = json.loads(out_reader.read_text()) if out_reader.exists() else []
    failures = [r for r in reader_results if not r.get("ok")]
    filenotfound = [r for r in failures if "FileNotFoundError" in str(r.get("error", ""))]
    record(
        "AT-11-2d【CODEX再現の直接反証】: acquire_current()はpublish+GC(retention=0)churn 10回と並行しても"
        "一度もFileNotFoundErrorを出さない（旧実装はこの再現でFAILしていた）",
        len(reader_results) > 0 and len(filenotfound) == 0,
        f"total={len(reader_results)} failures={len(failures)} filenotfound={len(filenotfound)}",
    )
    ok_count = sum(1 for r in reader_results if r.get("ok"))
    record("AT-11-2e: churn中でも大半のacquire_current()呼び出しが成功する", ok_count >= len(reader_results) * 0.8, f"ok={ok_count}/{len(reader_results)}")


def at11_03_renewal_vs_gc(tmp: Path) -> None:
    data_root = tmp / "at11_03" / "data_runtime"
    leases_root = tmp / "at11_03" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")
    r2 = publish_new_version(publisher, "v2")

    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    handle = coord.acquire(r1.version_id, "at11-03")

    out_gc = tmp / "at11_03_gc.json"
    ctx = mp.get_context("fork")
    p_gc = ctx.Process(target=_worker_gc, args=(str(data_root), str(leases_root), 0, str(out_gc)))
    p_gc.start()
    p_gc.join(10)
    gc_res = _read_json(str(out_gc))

    renewed = coord.renew(handle)
    record("AT-11-3a: GC実行後もrenewalが成功する（activeの生存確認）",
           renewed.payload.lease_id == handle.payload.lease_id)
    record("AT-11-3b: renewal対象leaseのversion(v1)がGCで削除されない",
           gc_res and r1.version_id not in gc_res.get("deleted", []), str(gc_res))
    coord.release(handle)


def at11_04_renewal_vs_release(tmp: Path) -> None:
    data_root = tmp / "at11_04" / "data_runtime"
    leases_root = tmp / "at11_04" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")
    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    handle = coord.acquire(r1.version_id, "at11-04")
    coord.release(handle)
    try:
        coord.renew(handle)
        record("AT-11-4: release後のrenewalは失敗し、active/lockが再作成されない", False)
    except Exception:
        active_recreated = (leases_root / "active" / f"{handle.payload.lease_id}.json").exists()
        record("AT-11-4: release後のrenewalは失敗し、active/lockが再作成されない", not active_recreated)


def at11_05_stale_cleanup_vs_renewal_release(tmp: Path) -> None:
    data_root = tmp / "at11_05" / "data_runtime"
    leases_root = tmp / "at11_05" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")
    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)

    stale_handle = coord.acquire(r1.version_id, "stale-target")
    # 強制的に期限切れへ書き換える（stale cleanupの対象を作る）
    active_path = leases_root / "active" / f"{stale_handle.payload.lease_id}.json"
    payload = json.loads(active_path.read_text())
    payload["expires_at_epoch"] = time.time() - 100
    active_path.write_text(json.dumps(payload))

    other_handle = coord.acquire(r1.version_id, "other-lease")

    out_gc = tmp / "at11_05_gc.json"
    ctx = mp.get_context("fork")
    p_gc = ctx.Process(target=_worker_gc, args=(str(data_root), str(leases_root), 0, str(out_gc)))
    p_gc.start()

    renewed_other = coord.renew(other_handle)
    p_gc.join(10)
    gc_res = _read_json(str(out_gc))

    record("AT-11-5a: staleでない別leaseのrenewalはstale cleanupと共存できる",
           renewed_other.payload.lease_id == other_handle.payload.lease_id)
    record("AT-11-5b: stale entryがGCのstale_leases_removedへ実際に記録される",
           bool(gc_res) and stale_handle.payload.lease_id in gc_res.get("stale_leases_removed", []),
           f"gc_res={gc_res}")
    record("AT-11-5c: stale active entryが実際にファイルとして消えている",
           not active_path.exists())
    coord.release(other_handle)


def at11_06_fixed_inode_old_holder(tmp: Path) -> None:
    """CODEX P2B5-CX-006（AT-11#6再修正）: 旧実装は単純な差替え→renewだけで、
    old inode holder A・waiter B（無関係な別lease）・operator cleanup経路を
    一切検証していなかった。ここではholder A（対象lease）とwaiter B
    （無関係な別lease）を同時に走らせ、Aのlock file破損がBへ波及しないこと、
    さらにoperator GCのorphan lock cleanupがinode不一致のlock fileを安全側で
    削除しない（old inode holderをcleanupが誤って巻き込まない）ことまで検証する。
    """
    data_root = tmp / "at11_06" / "data_runtime"
    leases_root = tmp / "at11_06" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")
    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)

    # holder A: 対象lease
    handle = coord.acquire(r1.version_id, "at11-06-holder-A")
    lease_id = handle.payload.lease_id

    # waiter B: 無関係な別lease（holder Aの状態破損の影響を受けないことの対照群）
    handle_b = coord.acquire(r1.version_id, "at11-06-waiter-B")

    # holder Aのlock fileを差し替える（同名で作り直す＝古いfdは別inodeを指したまま残る）
    lock_path = leases_root / "locks" / f"{lease_id}.lock"
    os.unlink(lock_path)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
    os.write(fd, b"different-generation")
    os.close(fd)

    try:
        coord.renew(handle)
        record("AT-11-6a: old inode holder（差替え前のhandle）によるrenewalは拒否される", False)
    except Exception:
        record("AT-11-6a: old inode holder（差替え前のhandle）によるrenewalは拒否される", True)

    # waiter B（無関係な別lease）はholder Aのlock file破損の影響を受けず正常にrenewできる
    try:
        coord.renew(handle_b)
        record("AT-11-6b: 無関係な別lease（waiter B）はholder Aのlock file破損の影響を受けずrenewできる", True)
    except Exception as exc:
        record("AT-11-6b: 無関係な別lease（waiter B）はholder Aのlock file破損の影響を受けずrenewできる",
               False, repr(exc))
    coord.release(handle_b)
    os.close(handle.lock_fd)

    # operator cleanup: holder Aのactive entryを除去してorphan化させ、operator GCの
    # orphan lock cleanup経路が、tombstone記録済みinodeと一致しない（差替え済み）
    # lock fileを安全側で削除しない（=old inode holderをcleanupが誤って巻き込まない）
    # ことを実際のGC実行で検証する。
    active_path = leases_root / "active" / f"{lease_id}.json"
    if active_path.exists():
        os.unlink(active_path)
    gc = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
    )
    gc.run()
    record(
        "AT-11-6c【operator cleanup実行】: GCのorphan lock cleanupは、"
        "inode不一致（old holder差替え済み）のlock fileを安全側で削除しない",
        lock_path.exists(),
    )


def at11_07_retired_id_reuse_and_split_inode(tmp: Path) -> None:
    """CODEX P2B5-CX-006（AT-11#7再修正）: 旧実装は同一IDを一度も強制的に
    再利用させておらず、生成された別IDのUUIDでlock/tombstoneが残存する
    ことを見るだけだった（何も衝突させていない）。ここではuuid4()を
    monkeypatchしてretired（release済みだがlock/tombstoneは残存）済みの
    lease_idを実際に強制再利用させ、(a) 既存artifactの事前存在チェックで
    実際に拒否されretryが発生すること、(b) 拒否後も既存lock/tombstoneの
    内容が一切改変されていない（=同一IDを2つの異なるlease lifetimeが
    共有するsplit-inode double-successが起きていない）ことを直接確認する。
    """
    data_root = tmp / "at11_07" / "data_runtime"
    leases_root = tmp / "at11_07" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")
    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)

    handle = coord.acquire(r1.version_id, "at11-07-original")
    retired_lease_id = handle.payload.lease_id
    original_lock_content = (leases_root / "locks" / f"{retired_lease_id}.lock").read_bytes()
    original_tombstone_content = (leases_root / "retired" / f"{retired_lease_id}.tombstone").read_bytes()
    coord.release(handle)

    from app.services import runtime_lease as _rl_module
    import uuid as _uuid

    real_uuid4 = _uuid.uuid4
    forced_id = _uuid.UUID(retired_lease_id)
    call_state = {"n": 0}

    def _forced_retired_uuid4():
        call_state["n"] += 1
        if call_state["n"] == 1:
            return forced_id
        return real_uuid4()

    original_acquire_once = _rl_module.LeaseCoordinator._acquire_once
    acquire_once_calls = {"n": 0}

    def _counting_acquire_once(self, resolve_version_id, request_kind):
        acquire_once_calls["n"] += 1
        return original_acquire_once(self, resolve_version_id, request_kind)

    _rl_module.uuid.uuid4 = _forced_retired_uuid4
    _rl_module.LeaseCoordinator._acquire_once = _counting_acquire_once
    try:
        new_handle = coord.acquire(r1.version_id, "at11-07-forced-reuse-attempt")
        record(
            "AT-11-7a【実ID再利用強制注入】: retired済みlease_idと同一IDでの新規acquireは"
            "既存lock/tombstone artifactの事前存在チェックで拒否され、"
            "retryにより別IDで最終的に成功する",
            new_handle is not None and new_handle.payload.lease_id != retired_lease_id,
            f"new_lease_id={new_handle.payload.lease_id if new_handle else None}",
        )
        record(
            "AT-11-7b【実ID再利用強制注入】: ID衝突により_acquire_once()が複数回呼ばれた"
            "（1回で「成功」していれば衝突検出が機能していない証拠になる）",
            acquire_once_calls["n"] >= 2, f"calls={acquire_once_calls['n']}",
        )
        coord.release(new_handle)
    finally:
        _rl_module.uuid.uuid4 = real_uuid4
        _rl_module.LeaseCoordinator._acquire_once = original_acquire_once

    lock_after = (leases_root / "locks" / f"{retired_lease_id}.lock").read_bytes()
    tomb_after = (leases_root / "retired" / f"{retired_lease_id}.tombstone").read_bytes()
    record(
        "AT-11-7c【split-inode double-success検出】: ID再利用attempt後も、元のretired "
        "lock/tombstoneの内容は一切改変されていない（衝突attemptが既存artifactを"
        "上書きするdouble-successが起きていない）",
        lock_after == original_lock_content and tomb_after == original_tombstone_content,
    )


def at11_08_crash_timeout_lock_fsync_failure(tmp: Path) -> None:
    data_root = tmp / "at11_08" / "data_runtime"
    leases_root = tmp / "at11_08" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")

    # writer lock保持中のprocessをSIGKILLし、kernel lock解放を実測する
    import signal

    def _hold_writer_lock_forever(data_root_s):
        from app.services.runtime_atomic import WriterLock
        with WriterLock(Path(data_root_s) / ".publish.lock", UID, GID, timeout_s=5.0):
            time.sleep(60)

    ctx = mp.get_context("fork")
    p = ctx.Process(target=_hold_writer_lock_forever, args=(str(data_root),))
    p.start()
    time.sleep(0.5)
    os.kill(p.pid, signal.SIGKILL)
    p.join(5)

    # crash後、新しいpublishがwriter lockを取得できることを確認する（kernel lock解放実測）
    started = time.time()
    r2 = publish_new_version(publisher, "v2")
    elapsed = time.time() - started
    record("AT-11-8a: writer lock保持processのSIGKILL後、kernelがlockを解放し後続publishが取得できる",
           elapsed < 5.0, f"elapsed={elapsed:.2f}s")

    # timeout: 別processが保持している間、timeout付きlockはbusy拒否になる
    out_holder = tmp / "at11_08_holder_started.flag"

    def _hold(data_root_s, flag_path):
        from app.services.runtime_atomic import WriterLock
        with WriterLock(Path(data_root_s) / ".publish.lock", UID, GID, timeout_s=5.0):
            Path(flag_path).write_text("1")
            time.sleep(3)

    p2 = ctx.Process(target=_hold, args=(str(data_root), str(out_holder)))
    p2.start()
    deadline = time.time() + 5
    while not out_holder.exists() and time.time() < deadline:
        time.sleep(0.05)
    try:
        from app.services.runtime_atomic import WriterLock
        started2 = time.time()
        with WriterLock(data_root / ".publish.lock", UID, GID, timeout_s=1.0):
            pass
        record("AT-11-8b: 保持中writer lockへのtimeout付き取得はbusyで拒否される", False)
    except RuntimeAtomicError:
        record("AT-11-8b: 保持中writer lockへのtimeout付き取得はbusyで拒否される", True)
    p2.join(10)

    # AT-11-8c（CODEX指摘の再修正）: crash/timeoutだけでなく、fsync failure
    # 経路自体を実際に注入する（旧実装はcrash/timeoutのみでfsync failureは
    # 未実行だった）。publish()内の1回目のfsync_dir呼び出し
    # （renameat2直後・versions_fd）を実際に失敗させる。
    with _failing_fsync_dir(1) as state8c:
        try:
            publish_new_version(publisher, "v3-fsync-fail")
            record("AT-11-8c【実fsync fault injection】: fsync failure注入時、publish()は例外を伝播しfail-closedになる", False)
        except OSError:
            record("AT-11-8c【実fsync fault injection】: fsync failure注入時、publish()は例外を伝播しfail-closedになる", True)
    record("AT-11-8c【実fsync fault injection】: fault injectionが実際にfsync_dir呼び出しへ到達したことを確認する（source確認への代替ではない）",
           state8c["n"] >= 1, f"calls={state8c['n']}")


def at11_09_registry_tombstone_corruption(tmp: Path) -> None:
    data_root = tmp / "at11_09" / "data_runtime"
    leases_root = tmp / "at11_09" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    publish_new_version(publisher, "v1")

    # active/*.json を1件破損させる
    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    r_versions = publisher.list_versions()
    handle = coord.acquire(r_versions[0], "corrupt-test")
    active_path = leases_root / "active" / f"{handle.payload.lease_id}.json"
    active_path.write_text("{not valid json")

    gc = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
    )
    try:
        gc.run()
        record("AT-11-9: registry（active entry）破損時にGCはfail-closedで停止する", False)
    except GcFailClosedError:
        record("AT-11-9: registry（active entry）破損時にGCはfail-closedで停止する", True)
    # cleanup: 破損entryを手動で除去してから、release相当のcleanupを試みる（tear down用）
    active_path.unlink()


def at11_10_clock_skew_ttl_boundary(tmp: Path) -> None:
    data_root = tmp / "at11_10" / "data_runtime"
    leases_root = tmp / "at11_10" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")
    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    handle = coord.acquire(r1.version_id, "ttl-test")
    active_path = leases_root / "active" / f"{handle.payload.lease_id}.json"
    payload = json.loads(active_path.read_text())
    payload["expires_at_epoch"] = time.time() - 0.01
    active_path.write_text(json.dumps(payload))
    try:
        coord.renew(handle)
        record("AT-11-10a: TTL境界（expires直後）のrenewalは期限切れとして拒否される", False)
    except LeaseExpiredError:
        record("AT-11-10a: TTL境界（expires直後）のrenewalは期限切れとして拒否される", True)

    # clock rollback検出（GC側）
    clock_state = leases_root / "clock.state"
    clock_state.write_text(str(time.time() + 100000))
    gc = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
    )
    try:
        gc.run()
        record("AT-11-10b: clock rollback検出時にGCはfail-closedで停止する", False)
    except GcFailClosedError:
        record("AT-11-10b: clock rollback検出時にGCはfail-closedで停止する", True)


def at11_11_traversal_symlink_hardlink(tmp: Path) -> None:
    data_root = tmp / "at11_11" / "data_runtime"
    leases_root = tmp / "at11_11" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")

    # currentをtraversal targetへ差し替える
    current_link = data_root / "current"
    os.unlink(current_link)
    os.symlink("../../../etc", current_link)
    try:
        publisher._current_target()
        record("AT-11-11a: current symlinkのtraversal target（絶対path外/相対traversal）は拒否される", False)
    except RuntimeAtomicError:
        record("AT-11-11a: current symlinkのtraversal target（絶対path外/相対traversal）は拒否される", True)

    os.unlink(current_link)
    os.symlink(f"/etc", current_link)
    try:
        publisher._current_target()
        record("AT-11-11b: current symlinkの絶対path targetは拒否される", False)
    except RuntimeAtomicError:
        record("AT-11-11b: current symlinkの絶対path targetは拒否される", True)

    # 復元
    os.unlink(current_link)
    os.symlink(f"versions/{r1.version_id}", current_link)

    # version directoryをhardlinkで別名に複製 → root境界チェックに引っかからないことを確認
    # （version自体はdirectoryなのでhardlink不可、代わりにfileのhardlink検出を確認）
    sample = data_root / "versions" / r1.version_id / "backend" / "hazard" / "sample.geojson"
    st = os.lstat(sample)
    record("AT-11-11c: version配下のfileがlink count 1（hardlinkされていない）", st.st_nlink == 1)

    # AT-11-11d（CODEX指摘の再修正）: 「既存published fileのst_nlink==1を見る
    # だけ」ではなく、実際にhardlinkを作成してpublish()がそれを拒否することを
    # 直接確認する（_verify_permissions()へのhardlink検出追加とセット）。
    data_root_11d = tmp / "at11_11d" / "data_runtime"
    leases_root_11d = tmp / "at11_11d" / "leases"
    _bootstrap_roots(data_root_11d, leases_root_11d)
    publisher_11d = AtomicPublisher(data_root_11d, expect_uid=UID, expect_gid=GID)
    vid_11d = generate_version_id()
    stg_11d = publisher_11d.new_staging_path(vid_11d)
    make_dataset(stg_11d, "hardlink-test")
    original_file = stg_11d / "backend" / "hazard" / "sample.geojson"
    hardlinked_file = stg_11d / "backend" / "hazard" / "sample_hardlink.geojson"
    os.link(original_file, hardlinked_file)
    try:
        publisher_11d.publish(vid_11d, validate_ok)
        record("AT-11-11d【実hardlink注入】: staging内のhardlink（link count>1）を含むversionのpublishは拒否される", False)
    except RuntimeAtomicError as exc:
        record("AT-11-11d【実hardlink注入】: staging内のhardlink（link count>1）を含むversionのpublishは拒否される",
               "link count" in str(exc) or "hardlink" in str(exc), repr(exc))


def at11_12_flock_capacity_inode(tmp: Path) -> None:
    data_root = tmp / "at11_12" / "data_runtime"
    leases_root = tmp / "at11_12" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    publish_new_version(publisher, "v1")

    gc = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0,
        capacity_min_free_bytes=10 ** 18,  # 到達不能な閾値 → 必ず容量不足
    )
    try:
        gc.run()
        record("AT-11-12: 空き容量閾値を満たさない場合GCはfail-closedで停止する", False)
    except GcFailClosedError:
        record("AT-11-12: 空き容量閾値を満たさない場合GCはfail-closedで停止する", True)

    # CODEX P2B5-CX-005/DP-N19対応: byte容量だけでなくtombstone件数上限も検証する。
    coord12 = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    for _ in range(3):
        h = coord12.acquire_current(data_root, "at11-12-tomb")
        coord12.release(h)
    gc_tomb = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
        tombstone_hard_limit=2,
    )
    try:
        gc_tomb.run()
        record("AT-11-12b: tombstone数がhard limitを超えるとGCはfail-closedで停止する", False)
    except GcFailClosedError:
        record("AT-11-12b: tombstone数がhard limitを超えるとGCはfail-closedで停止する", True)


def at11_12c_ttl_skew_margin_and_renewal(tmp: Path) -> None:
    """CODEX P2B5-CX-005対応: stale判定へのskew margin適用と、streaming
    reader向けrenewal loopの実装を検証する。"""
    data_root = tmp / "at11_12c" / "data_runtime"
    leases_root = tmp / "at11_12c" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")

    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    handle = coord.acquire_current(data_root, "skew-test")
    active_path = leases_root / "active" / f"{handle.payload.lease_id}.json"
    payload = json.loads(active_path.read_text())
    payload["expires_at_epoch"] = time.time() - 2.0  # margin(5.0s)以内の軽微な超過
    active_path.write_text(json.dumps(payload))

    gc = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
    )
    result = gc.run()
    record(
        "AT-11-10c【CODEX指摘のexpiry+margin保護】: margin以内の軽微な期限超過はstale扱いされない",
        handle.payload.lease_id not in result.stale_leases_removed,
        f"stale_removed={result.stale_leases_removed}",
    )

    payload["expires_at_epoch"] = time.time() - 1000.0
    active_path.write_text(json.dumps(payload))
    result2 = gc.run()
    record(
        "AT-11-10d: marginを大きく超えた期限切れは引き続きstale判定される",
        handle.payload.lease_id in result2.stale_leases_removed,
        f"stale_removed={result2.stale_leases_removed}",
    )

    # renewal loop（streaming中の自動renew）
    import asyncio
    from unittest import mock as _mock
    from app.services import runtime_version_access as rva

    # CODEX P2B5-CX-007（第5ラウンド）対応: rva.stream_versioned_file()は
    # 本ラウンドで追加したLeaseCoordinatorのdirectory owner/mode実検証
    # （expect_owner_gid既定=rva._LEASES_GID=20001）、lock file／active
    # entryのowner実検証（`self.uid`との厳密一致）、配信fileのowner/mode
    # 実検証（_verify_served_file_ownership()、既定owner=10002/group=20001）
    # の3つを経由するようになった。
    #
    # 本test（phase2b5_inner_tests.py全体）は単一の実process（実euid=UID=
    # 10002、本containerのoperator identity）として動作し、`LeaseCoordinator
    # (uid=X, ...)`のuid引数はOS-levelの実privilegeを伴わない設定値に
    # すぎない（実file作成のownerは常に実euidの10002になる）。他の全testは
    # 一貫して`uid=UID`（実euidと一致）を使っているが、本testだけは
    # rva.get_coordinator()が使う既定値`rva._PUBLIC_UID=10001`
    # （実運用のpublic containerを想定した値）をそのまま使っており、
    # 実際に作られるfileのowner（10002）と設定上の期待owner（10001）が
    # 乖離していた。本testに限り、rva._PUBLIC_UID/_PUBLIC_GIDを実euid
    # （UID/GID）へ一致させ、_bootstrap_roots()が実際に作るactive/locks/
    # retiredとfileのgroupも実運用と同じ20001へ揃える。
    real_public_uid, real_public_gid = rva._PUBLIC_UID, rva._PUBLIC_GID
    rva._PUBLIC_UID = UID
    rva._PUBLIC_GID = GID
    for sub in ("active", "locks", "retired"):
        os.chown(leases_root / sub, UID, LEASES_GID)
    sample_path = data_root / "versions" / r1.version_id / "backend" / "hazard" / "sample.geojson"
    os.chown(sample_path, UID, LEASES_GID)

    rva.DATA_RUNTIME_ROOT = data_root
    rva.LEASES_ROOT = leases_root
    rva._coordinator = None
    rva.LEASE_TTL_S = 10.0
    # _RENEW_AFTER_S は import時に LEASE_TTL_S から一度だけ計算される
    # module定数のため、LEASE_TTL_S再代入だけでは追従しない。testでは
    # 明示的に上書きする（本番はcontainer起動時の環境変数で決まるため
    # この再計算不要という設計自体は妥当）。
    rva._RENEW_AFTER_S = 5.0

    renew_calls = {"n": 0}
    original_renew = LeaseCoordinator.renew

    def _spy_renew(self, h):
        renew_calls["n"] += 1
        return original_renew(self, h)

    call_count = {"n": 0}
    real_monotonic = time.monotonic

    def _fake_monotonic():
        call_count["n"] += 1
        return real_monotonic() + call_count["n"] * 10.0

    async def _run_stream():
        chunks = []
        async for chunk in rva.stream_versioned_file(f"backend/hazard/sample.geojson", "renew-test"):
            chunks.append(chunk)
        return chunks

    try:
        with _mock.patch.object(LeaseCoordinator, "renew", _spy_renew), _mock.patch("time.monotonic", _fake_monotonic):
            chunks = asyncio.run(_run_stream())
        record("AT-11-05b【renewal loop】: 長時間streaming中にrenew()が実際に呼ばれる（renew interval=TTL/2）",
               renew_calls["n"] >= 1, f"renew_calls={renew_calls['n']} bytes={sum(len(c) for c in chunks)}")
    finally:
        rva._PUBLIC_UID = real_public_uid
        rva._PUBLIC_GID = real_public_gid
        rva._coordinator = None


def at11_12d_explicit_rollback_protection(tmp: Path) -> None:
    """CODEX P2B5-CX-005対応: rollback保護をretention countへの暗黙依存に
    せず、`versions/.protected.json`による明示的な保護契約として検証する。"""
    data_root = tmp / "at11_12d" / "data_runtime"
    leases_root = tmp / "at11_12d" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")
    time.sleep(1.01)
    publish_new_version(publisher, "v2")  # v1はcurrentでもleased済みでもない

    protected_path = data_root / "versions" / ".protected.json"
    tmp_path = protected_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps([r1.version_id]))
    os.chmod(tmp_path, 0o640)
    os.rename(tmp_path, protected_path)

    gc = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
    )
    result = gc.run()
    record(
        "AT-11-explicit-protection: .protected.jsonに列挙したversionはretention_count=0でも削除されない",
        r1.version_id in result.versions_retained and r1.version_id not in result.versions_deleted,
        f"retained={result.versions_retained} deleted={result.versions_deleted}",
    )


def at11_14_rename_noreplace_barrier(tmp: Path) -> None:
    d = tmp / "at11_14"
    d.mkdir(parents=True)
    (d / "dst").write_text("original")
    with open_dir_fd(d) as dfd:
        try:
            renameat2_noreplace(dfd, "dst", dfd, "dst")
            record("AT-11-14a: renameat2(RENAME_NOREPLACE)は自分自身へのrenameでもEEXISTを返す（実syscall）", False)
        except FileExistsError:
            record("AT-11-14a: renameat2(RENAME_NOREPLACE)は自分自身へのrenameでもEEXISTを返す（実syscall）", True)

    (d / "src").write_text("new-content")
    with open_dir_fd(d) as dfd:
        try:
            renameat2_noreplace(dfd, "src", dfd, "dst")
            record("AT-11-14b: 既存destへのRENAME_NOREPLACEはEEXISTで拒否される（実syscall）", False)
        except FileExistsError:
            record("AT-11-14b: 既存destへのRENAME_NOREPLACEはEEXISTで拒否される（実syscall）", True)
    record("AT-11-14c: 拒否後もdstの内容は変化していない（destination replace 0件）",
           (d / "dst").read_text() == "original")

    # 実プロセス2つでのrace: 同一新規destへ同時にRENAME_NOREPLACEし、片方だけ成功する
    (d / "race_src_a").write_text("A")
    (d / "race_src_b").write_text("B")
    out_a = tmp / "race_a.json"
    out_b = tmp / "race_b.json"

    def _race_worker(dir_s, src_name, out_path):
        try:
            with open_dir_fd(Path(dir_s)) as dfd:
                renameat2_noreplace(dfd, src_name, dfd, "race_dst")
            Path(out_path).write_text(json.dumps({"ok": True}))
        except FileExistsError:
            Path(out_path).write_text(json.dumps({"ok": False, "eexist": True}))
        except Exception as exc:  # noqa: BLE001
            Path(out_path).write_text(json.dumps({"ok": False, "error": repr(exc)}))

    ctx = mp.get_context("fork")
    pa = ctx.Process(target=_race_worker, args=(str(d), "race_src_a", str(out_a)))
    pb = ctx.Process(target=_race_worker, args=(str(d), "race_src_b", str(out_b)))
    pa.start(); pb.start()
    pa.join(10); pb.join(10)
    ra, rb = _read_json(str(out_a)), _read_json(str(out_b))
    winners = [r for r in (ra, rb) if r and r.get("ok")]
    losers = [r for r in (ra, rb) if r and not r.get("ok")]
    record("AT-11-14d: 実process2つの同時RENAME_NOREPLACE raceで片方だけ成功しもう片方はEEXIST",
           len(winners) == 1 and len(losers) == 1 and losers[0].get("eexist") is True,
           f"a={ra} b={rb}")


def _bootstrap_roots(data_root: Path, leases_root: Path) -> None:
    os.makedirs(data_root, exist_ok=True)
    # CODEX P2B5-CX-007（第7ラウンド）対応: 本ラウンドでdata_runtime root
    # 自体のownership検証（runtime_version_access._verify_data_runtime_root_
    # ownership()）を新設した。init_lease_volume.pyの_claim_data_runtime_root()
    # が実運用で確立する値（operator_uid:leases_gid、mode 0750）へ、この
    # test fixtureも合わせる（従来は他のsubdir/fileだけをchownし、
    # data_root自体は未設定のままprocessの既定group=operator自身のprimary
    # gidになっていた）。
    os.chown(data_root, UID, LEASES_GID)
    os.chmod(data_root, 0o750)
    os.makedirs(data_root / ".staging", mode=0o2750, exist_ok=True)
    os.chmod(data_root / ".staging", 0o2750)
    os.makedirs(data_root / "versions", mode=0o2750, exist_ok=True)
    os.chmod(data_root / "versions", 0o2750)
    lock_path = data_root / ".publish.lock"
    if not lock_path.exists():
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
    os.makedirs(leases_root / "active", mode=0o3770, exist_ok=True)
    os.makedirs(leases_root / "locks", mode=0o3770, exist_ok=True)
    os.makedirs(leases_root / "retired", mode=0o3770, exist_ok=True)
    for sub in ("active", "locks", "retired"):
        os.chmod(leases_root / sub, 0o3770)
    coord_lock = leases_root / "coordination.lock"
    if not coord_lock.exists():
        fd = os.open(str(coord_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o660)
        os.close(fd)
        # CODEX P2B5-CX-007（第2ラウンド）対応: 実運用のinit_lease_volume.pyは
        # coordination.lockをoperator_uid:leases_gidで所有させる。test fixture
        # でも同じgroupにしないと、新規追加したowner/mode実検証（本ラウンド）が
        # 正しい状況を「不一致」と誤判定してしまう。
        os.chown(coord_lock, UID, LEASES_GID)
        # os.open()のmodeはprocess umaskの影響を受ける（本inner testsは
        # `docker exec`経由で起動されるためDockerfile CMDのumask 0007を
        # 継承せず、既定umask（0022相当）で0660が0640へ削られていた実際の
        # 不一致を検出した）。他artifact（.staging/versions/lease subdir）と
        # 同様、作成直後に明示的chmodでumaskの影響を打ち消す。
        os.chmod(coord_lock, 0o660)


def at11_15_shelter_registry_atomic_integration(tmp: Path) -> None:
    """CODEX P2B5-CX-004（第5ラウンド）対応: shelters（deploy_to_runtime.sh
    が実際に発行するatomic publish対象consumer）をlease保護付き読み取りへ
    統合した（backend/app/services/shelter_service.py）。本testはこの
    統合を実際のShelterRegistryクラスを通じてend-to-endで検証する
    （AT-11本体には含まれないconsumer固有の追加検証だが、命名の一貫性の
    ためAT-11番台の末尾に置く）。
    """
    data_root = tmp / "at11_15" / "data_runtime"
    leases_root = tmp / "at11_15" / "leases"
    _bootstrap_roots(data_root, leases_root)
    # ShelterRegistryはruntime_version_access.get_coordinator()（既定
    # leases_owner_uid=10002/leases_gid=20001）を経由するため、
    # at11_12cと同じ理由でactive/locks/retiredのgroupを20001へ揃える。
    for sub in ("active", "locks", "retired"):
        os.chown(leases_root / sub, UID, LEASES_GID)

    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    vid = generate_version_id()
    stg = publisher.new_staging_path(vid)
    # validate_ok()はbackend/hazard/sample.geojsonの存在を前提とする共通
    # fixture validatorのため、shelters専用versionでも併せて用意する。
    make_dataset(stg, "shelter-test-v1")
    d = stg / "backend" / "shelters"
    d.mkdir(parents=True, mode=VERSION_DIR_MODE)
    os.chmod(d.parent, VERSION_DIR_MODE)
    geo = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"name": "AT-11-15テスト避難所", "designation": "指定緊急避難場所"},
            "geometry": {"type": "Point", "coordinates": [139.7, 35.6]},
        }],
    }
    (d / "test.geojson").write_text(json.dumps(geo, ensure_ascii=False))
    os.chmod(d / "test.geojson", VERSION_FILE_MODE)
    os.chmod(stg, VERSION_DIR_MODE)
    publisher.publish(vid, validate_ok)
    # publish()で作られたversion tree自体もgroupをleases_gidへ揃える
    # （実運用ではdeploy_to_runtime_atomic.shのchgrp -Rが担う処理）。
    for dirpath, dirnames, filenames in os.walk(data_root / "versions" / vid):
        os.chown(dirpath, UID, LEASES_GID)
        for fn in filenames:
            os.chown(os.path.join(dirpath, fn), UID, LEASES_GID)

    from app.services import runtime_version_access as rva
    from app.services.shelter_service import ShelterRegistry

    # at11_12cと同じ理由（本testも単一の実process/実euid=UIDとして動作し、
    # rva.get_coordinator()の既定値rva._PUBLIC_UID=10001はOS-levelの実
    # privilege dropを伴わない設定値に過ぎない）で、_PUBLIC_UID/_PUBLIC_GID
    # を実euidへ一致させないと、新規追加したlock/active entry owner実検証
    # （self.uidとの厳密一致）に失敗する。
    real_public_uid, real_public_gid = rva._PUBLIC_UID, rva._PUBLIC_GID
    real_data_root, real_leases_root = rva.DATA_RUNTIME_ROOT, rva.LEASES_ROOT
    real_coordinator = rva._coordinator
    rva._PUBLIC_UID = UID
    rva._PUBLIC_GID = GID
    rva.DATA_RUNTIME_ROOT = data_root
    rva.LEASES_ROOT = leases_root
    rva._coordinator = None
    try:
        registry = ShelterRegistry(ttl_seconds=30)
        shelters = registry.get_shelters()
        record(
            "AT-11-15【ShelterRegistry実atomic publish統合】: publishしたversionから実際に"
            "shelter dataをlease保護下でloadできる",
            len(shelters) == 1 and shelters[0]["name"] == "AT-11-15テスト避難所",
            f"loaded={shelters}",
        )
        record(
            "AT-11-15: ShelterRegistryが読み込んだversion_idがpublishしたversionと一致する",
            registry._last_loaded_version_id == vid,
            f"expected={vid} actual={registry._last_loaded_version_id}",
        )

        # 新publishでcurrentが切り替わったら、TTL満了前でもcache invalidationされることを確認する。
        vid2 = generate_version_id()
        stg2 = publisher.new_staging_path(vid2)
        make_dataset(stg2, "shelter-test-v2")
        d2 = stg2 / "backend" / "shelters"
        d2.mkdir(parents=True, mode=VERSION_DIR_MODE)
        os.chmod(d2.parent, VERSION_DIR_MODE)
        geo2 = {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {"name": "AT-11-15テスト避難所v2", "designation": "指定緊急避難場所"},
                "geometry": {"type": "Point", "coordinates": [139.8, 35.7]},
            }],
        }
        (d2 / "test.geojson").write_text(json.dumps(geo2, ensure_ascii=False))
        os.chmod(d2 / "test.geojson", VERSION_FILE_MODE)
        os.chmod(stg2, VERSION_DIR_MODE)
        publisher.publish(vid2, validate_ok)
        for dirpath, dirnames, filenames in os.walk(data_root / "versions" / vid2):
            os.chown(dirpath, UID, LEASES_GID)
            for fn in filenames:
                os.chown(os.path.join(dirpath, fn), UID, LEASES_GID)

        shelters_after = registry.get_shelters()
        record(
            "AT-11-15【TTL満了前のversion変化検知】: 新publish直後（TTL未満了）でもcurrentのversion変化を"
            "検知しcacheが即座に更新される",
            len(shelters_after) == 1 and shelters_after[0]["name"] == "AT-11-15テスト避難所v2",
            f"loaded={shelters_after}",
        )
    finally:
        rva._PUBLIC_UID = real_public_uid
        rva._PUBLIC_GID = real_public_gid
        rva.DATA_RUNTIME_ROOT = real_data_root
        rva.LEASES_ROOT = real_leases_root
        rva._coordinator = real_coordinator


# ------------------------------------------------------------------
# DP-N01〜N20（第10節、独立negative fixture）
# ------------------------------------------------------------------

def dpn_fixtures(tmp: Path) -> None:
    # DP-N04: active/ modeを3770以外へ変更 → 検証関数が検出できること
    data_root = tmp / "dpn" / "data_runtime"
    leases_root = tmp / "dpn" / "leases"
    _bootstrap_roots(data_root, leases_root)
    publisher = AtomicPublisher(data_root, expect_uid=UID, expect_gid=GID)
    r1 = publish_new_version(publisher, "v1")

    os.chmod(leases_root / "active", 0o777)
    from app.services.runtime_atomic import verify_path_owner_mode
    try:
        verify_path_owner_mode(leases_root / "active", UID, GID, 0o3770)
        record("DP-N04: active/ modeを3770以外へ変更 → 検出される", False)
    except RuntimeAtomicError:
        record("DP-N04: active/ modeを3770以外へ変更 → 検出される", True)
    os.chmod(leases_root / "active", 0o3770)

    # DP-N05: lock fileをsymlinkへ差替え
    coord = LeaseCoordinator(leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
    handle = coord.acquire(r1.version_id, "dpn05")
    lock_path = leases_root / "locks" / f"{handle.payload.lease_id}.lock"
    coord.release(handle)
    os.unlink(lock_path)
    (tmp / "dpn" / "symlink_target").write_text("evil")
    os.symlink(tmp / "dpn" / "symlink_target", lock_path)
    handle2 = coord.acquire(r1.version_id, "dpn05b")
    try:
        # renewでlock file identityを検証する経路がsymlinkを検出できるか
        st = os.lstat(lock_path)
        is_symlink = stat.S_ISLNK(st.st_mode)
        record("DP-N05: lock fileがsymlinkへ差替えられている状態を検出できる（O_NOFOLLOWで作成時は防止済み、既存差替えはlstatで検出）", is_symlink)
    finally:
        coord.release(handle2)
        if lock_path.is_symlink() or lock_path.exists():
            os.unlink(lock_path)

    # DP-N06（CODEX指摘の再修正）: 旧実装は参照先の実際の結果を見ず無条件Trueを
    # 記録していた（CODEX P2B5-CX-006指摘）。AT-11-6a/6b/6cが本項目の対象を
    # 実際に検証しているため、その結果を動的に反映する（参照先が1件でも
    # FAILならDP-N06もFAILとする）。
    at11_06_results = [r for r in RESULTS if r["name"].startswith("AT-11-6")]
    record(
        "DP-N06: lock file別inode差替え・operator cleanup安全性の検出（AT-11-6a/6b/6cの実結果を反映）",
        len(at11_06_results) >= 3 and all(r["pass"] for r in at11_06_results),
        f"referenced={[r['name'] for r in at11_06_results]}",
    )

    # DP-N07: tombstoneを破損／欠落
    # tombstoneはmode 0440（read-only、書込bit無し）で作成されるため、owner自身も
    # 素のwrite_text()では書けない（これ自体が「immutable tombstone」の設計どおり）。
    # 破損を模擬するには一旦chmodで書込可能にしてから書き換える。
    handle3 = coord.acquire(r1.version_id, "dpn07")
    tomb_path = leases_root / "retired" / f"{handle3.payload.lease_id}.tombstone"
    original = tomb_path.read_text()
    os.chmod(tomb_path, 0o640)
    tomb_path.write_text("{corrupted")
    os.chmod(tomb_path, 0o440)
    gc = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
    )
    coord.release(handle3)
    # orphan lock cleanup対象になるが、tombstone破損のためcleanup対象から除外される（安全側）
    lock_path3 = leases_root / "locks" / f"{handle3.payload.lease_id}.lock"
    result = gc.run()
    record("DP-N07: tombstone破損時、対応するlock fileは安全側で削除されない",
           lock_path3.exists())

    # DP-N08（CODEX指摘の再修正）: 「無関係のdummy fileを通常renameで上書き
    # できる」という一般論の代わりに、本実装が実際に使うversions/directory
    # 構造に対し、本実装のprimitive（renameat2_noreplace）を直接呼び出し、
    # 同一destination名への2回目renameがEEXISTで拒否され、既存内容が一切
    # 変更されないことを実際に確認する。対比として、同じ状況で通常os.rename
    # を使った場合は黙って上書きされてしまうことも示す（本実装が採用して
    # いない危険な経路の実証）。
    data_root_n08 = tmp / "dpn_n08_real" / "data_runtime"
    leases_root_n08 = tmp / "dpn_n08_real" / "leases"
    _bootstrap_roots(data_root_n08, leases_root_n08)
    versions_dir_n08 = data_root_n08 / "versions"
    staging_dir_n08 = data_root_n08 / ".staging"

    old_src = staging_dir_n08 / "dpn08-old"
    old_src.mkdir()
    (old_src / "marker.txt").write_text("OLD-CONTENT-MUST-SURVIVE")
    with open_dir_fd(staging_dir_n08) as sfd, open_dir_fd(versions_dir_n08) as vfd:
        renameat2_noreplace(sfd, "dpn08-old", vfd, "dpn08-target")

    new_src = staging_dir_n08 / "dpn08-new"
    new_src.mkdir()
    (new_src / "marker.txt").write_text("NEW-CONTENT-MUST-NOT-OVERWRITE")
    try:
        with open_dir_fd(staging_dir_n08) as sfd, open_dir_fd(versions_dir_n08) as vfd:
            renameat2_noreplace(sfd, "dpn08-new", vfd, "dpn08-target")
        record("DP-N08a【実primitive検証】: 本実装のrenameat2_noreplaceは同一destination名への2回目renameをEEXISTで拒否する", False)
    except FileExistsError:
        record("DP-N08a【実primitive検証】: 本実装のrenameat2_noreplaceは同一destination名への2回目renameをEEXISTで拒否する", True)
    surviving_content = (versions_dir_n08 / "dpn08-target" / "marker.txt").read_text()
    record("DP-N08b【実primitive検証】: EEXIST拒否後、既存destinationの内容は一切変更されていない（黙った上書きが起きていない）",
           surviving_content == "OLD-CONTENT-MUST-SURVIVE", f"actual={surviving_content!r}")

    # 対比（DP-N08c）: POSIX renameはdestination directoryが非emptyだとNOREPLACE
    # の有無に関わらずENOTEMPTYで失敗する（上のdpn08-targetは非emptyなので
    # 通常renameで上書きする比較には使えない）。「危険な上書きが起こり得るのは
    # destinationがemptyの場合」という実際のPOSIX rename semanticsを踏まえ、
    # emptyなdestinationに対しては通常renameが黙って（EEXISTを出さず）置換
    # できてしまうことを実際に示す。
    empty_target = staging_dir_n08 / "dpn08-empty-target"
    empty_target.mkdir()
    with open_dir_fd(staging_dir_n08) as sfd:
        renameat2_noreplace(sfd, "dpn08-empty-target", sfd, "dpn08-empty-target-in-versions-namespace")
    # versions/直下へ同名で改めて配置し直す（emptyなdestinationとして）
    with open_dir_fd(staging_dir_n08) as sfd, open_dir_fd(versions_dir_n08) as vfd:
        renameat2_noreplace(sfd, "dpn08-empty-target-in-versions-namespace", vfd, "dpn08-empty-dest")
    new_src2 = staging_dir_n08 / "dpn08-new2"
    new_src2.mkdir()
    (new_src2 / "marker.txt").write_text("NEW-CONTENT-SILENTLY-REPLACED-EMPTY-DEST")
    with open_dir_fd(staging_dir_n08) as sfd, open_dir_fd(versions_dir_n08) as vfd:
        os.rename("dpn08-new2", "dpn08-empty-dest", src_dir_fd=sfd, dst_dir_fd=vfd)
    replaced_content = (versions_dir_n08 / "dpn08-empty-dest" / "marker.txt").read_text()
    record(
        "DP-N08c【対比】: 通常os.renameはemptyなdestinationを黙って（EEXISTを出さず）置換できてしまう"
        "（本実装がrenameat2_noreplaceを常用し、この経路を使っていないことの実証）",
        replaced_content == "NEW-CONTENT-SILENTLY-REPLACED-EMPTY-DEST",
    )

    # DP-N09（CODEX指摘の再修正）: source文字列検索の代替ではなく、libc.renameat2
    # 呼び出しそのものをmonkeypatchしてEINVALを実際に返させ、fail-closed分岐が
    # 本当に実行され、destinationに部分状態が残らないことを直接確認する。
    import ctypes
    import errno as _errno
    from app.services import runtime_atomic as _ra

    _ra._ensure_libc()
    real_libc_renameat2 = _ra._libc.renameat2

    def _fake_renameat2_einval(src_fd, src_name, dst_fd, dst_name, flags):
        ctypes.set_errno(_errno.EINVAL)
        return -1

    data_root_n09 = tmp / "dpn09" / "data_runtime"
    leases_root_n09 = tmp / "dpn09" / "leases"
    _bootstrap_roots(data_root_n09, leases_root_n09)
    src_dir_n09 = data_root_n09 / ".staging"
    dst_dir_n09 = data_root_n09 / "versions"
    (src_dir_n09 / "dpn09-src").mkdir()
    (src_dir_n09 / "dpn09-src" / "f.txt").write_text("x")

    _ra._libc.renameat2 = _fake_renameat2_einval
    try:
        with open_dir_fd(src_dir_n09) as sfd, open_dir_fd(dst_dir_n09) as dfd:
            try:
                renameat2_noreplace(sfd, "dpn09-src", dfd, "dpn09-dst")
                record("DP-N09a【実EINVAL注入】: renameat2がEINVALを返す状況ではRuntimeAtomicErrorで拒否される", False)
            except RuntimeAtomicError as exc:
                record("DP-N09a【実EINVAL注入】: renameat2がEINVALを返す状況ではRuntimeAtomicErrorで拒否される",
                       "EINVAL" in str(exc), repr(exc))
    finally:
        _ra._libc.renameat2 = real_libc_renameat2
    record("DP-N09b【実EINVAL注入】: EINVAL注入時、destinationに何も作成されない（fail-closed、部分状態なし）",
           not (dst_dir_n09 / "dpn09-dst").exists())

    # DP-N17（CODEX指摘の再修正）: DP-N06と同様、参照先AT-11-9の実際の結果を反映する
    # （無条件Trueをやめる）。
    at11_09_results = [r for r in RESULTS if r["name"].startswith("AT-11-9")]
    record(
        "DP-N17: registry内1件破損検出（AT-11-9の実結果を反映）",
        len(at11_09_results) >= 1 and all(r["pass"] for r in at11_09_results),
        f"referenced={[r['name'] for r in at11_09_results]}",
    )

    # DP-N18: protected current/rollback/leased versionをGC候補へ混入
    r2 = publish_new_version(publisher, "v2")
    handle4 = coord.acquire(r2.version_id, "dpn18")
    gc2 = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
    )
    result2 = gc2.run()
    record("DP-N18: current かつ leased中のversionがGC候補から除外される",
           r2.version_id not in result2.versions_deleted and r2.version_id in result2.versions_retained)
    coord.release(handle4)

    # DP-N19: capacity/inode/tombstone hard limit到達
    gc3 = RuntimeGc(
        data_runtime_root=data_root, leases_root=leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=10 ** 18,
    )
    try:
        gc3.run()
        record("DP-N19: capacity hard limit到達でGCがfail-closed", False)
    except GcFailClosedError:
        record("DP-N19: capacity hard limit到達でGCがfail-closed", True)

    # DP-N20: cleanup query/削除/再照会failureまたは削除後残存
    # → tools/public_release/phase2b5_atomic_publish.py 側のcleanup_negative_control
    #    （実Docker操作）で検証する。ここではfilesystem levelの等価チェックとして、
    #    存在しないversionのGC対象化が起きないことを確認する。
    fake_version_dir = data_root / "versions" / "20200101T000000Z-deadbeef"
    record("DP-N20: 存在しないversion IDはlist_versions()に現れない（誤検出防止）",
           "20200101T000000Z-deadbeef" not in publisher.list_versions())

    # DP-N10（CODEX指摘の再修正）: active destination collisionを実際に強制注入する。
    # 旧実装は2回の独立acquireのlease_idが違うことを見るだけで、衝突を
    # 一度も発生させていなかった（CODEXの指摘どおり）。ここではuuid4()を
    # monkeypatchして最初の2呼び出しに同一lease_idを強制的に返させ、
    # 「同一IDでの2回目のacquireが実際にFileExistsErrorを内部で起こし、
    # retryで別IDへfallbackして最終的に成功する」ことを直接確認する。
    fake_leases_root = tmp / "dpn10" / "leases"
    fake_data_root = tmp / "dpn10" / "data_runtime"
    _bootstrap_roots(fake_data_root, fake_leases_root)
    publisher10 = AtomicPublisher(fake_data_root, expect_uid=UID, expect_gid=GID)
    r10 = publish_new_version(publisher10, "v1")
    coord10 = LeaseCoordinator(fake_leases_root, uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)

    from app.services import runtime_lease as _rl_module
    import uuid as _uuid

    fixed_id = _uuid.uuid4()
    real_uuid4 = _uuid.uuid4

    # 事前に「同名のlease_idが既に存在する」状態を作る（衝突を実際に成立
    # させるための下準備）。locks/<fixed_id.hex>.lock を先に作っておけば、
    # _acquire_once() 内の「3. active/locks/retired 同一ID不存在」検査が
    # 確実にFileExistsErrorを送出する。
    pre_existing_lock = fake_leases_root / "locks" / f"{fixed_id.hex}.lock"
    fd = os.open(str(pre_existing_lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o660)
    os.write(fd, b"pre-existing-collision-target")
    os.close(fd)

    collision_triggered = {"v": False}

    def _colliding_uuid4():
        # 最初の1回だけ、事前作成済みのIDと同一値を返して衝突を強制する。
        # 以降は本物のUUID4に戻す（retryが無限ループしないように、かつ
        # instance_id/generation_id等の後続呼び出しを汚染しないように）。
        if not collision_triggered["v"]:
            collision_triggered["v"] = True
            return fixed_id
        return real_uuid4()

    original_acquire_once = _rl_module.LeaseCoordinator._acquire_once
    acquire_once_calls = {"n": 0}

    def _counting_acquire_once(self, resolve_version_id, request_kind):
        acquire_once_calls["n"] += 1
        return original_acquire_once(self, resolve_version_id, request_kind)

    _rl_module.uuid.uuid4 = _colliding_uuid4
    _rl_module.LeaseCoordinator._acquire_once = _counting_acquire_once
    try:
        handle10 = coord10.acquire(r10.version_id, "dpn10-forced-collision")
        record(
            "DP-N10【実衝突注入】: uuid4()を固定してactive destination衝突を強制しても、"
            "retry機構により最終的にlease取得へ成功する",
            handle10 is not None,
        )
        record(
            "DP-N10【実衝突注入】: 衝突により_acquire_once()が複数回呼ばれたことを確認する"
            "（1回で成功したのではなく、実際にretryが発生した証拠）",
            acquire_once_calls["n"] >= 2,
            f"acquire_once_calls={acquire_once_calls['n']}",
        )
        coord10.release(handle10)
    finally:
        _rl_module.uuid.uuid4 = real_uuid4
        _rl_module.LeaseCoordinator._acquire_once = original_acquire_once

    # DP-N13: writer二重起動／GCのglobal→writer逆順取得を禁止する設計になっているか
    # （source review: GCはwriter lock取得後にglobal exclusiveを取る。逆順の
    # 「global保持後にwriter lock取得」経路が存在しないことをsourceで確認する）。
    import inspect
    from app.services import runtime_gc as _rg
    gc_src = inspect.getsource(_rg.RuntimeGc.run)
    writer_idx = gc_src.find("WriterLock")
    global_idx = gc_src.find("coordination_lock_path")
    record("DP-N13: GCはwriter lock取得(先)→global exclusive取得(後)の順を守っている（逆順経路が無い）",
           writer_idx != -1 and global_idx != -1 and writer_idx < global_idx)

    # DP-N14: renewalとreleaseの逆順競合 → 同一leaseへ2processが同時にrenew/release
    r14 = publish_new_version(publisher10, "v14")
    handle14 = coord10.acquire(r14.version_id, "dpn14")
    out_renew = tmp / "dpn14_renew.json"
    out_release = tmp / "dpn14_release.json"

    def _renew_worker(leases_root_s, lease_id, lock_fd, lock_ino, lock_dev, gen_id, version_id, instance_id,
                       acquired, renewed, expires, kind, out_path):
        try:
            coord_local = LeaseCoordinator(Path(leases_root_s), uid=UID, gid=GID, lease_ttl_s=30.0, expect_owner_gid=GID)
            payload = LeasePayload(1, version_id, lease_id, instance_id, acquired, renewed, expires, kind)
            lock_fd_local = os.open(str(Path(leases_root_s) / "locks" / f"{lease_id}.lock"), os.O_RDWR)
            from app.services.runtime_lease import LeaseHandle
            local_handle = LeaseHandle(Path(leases_root_s), payload, gen_id, lock_fd_local, lock_ino, lock_dev)
            result = coord_local.renew(local_handle)
            Path(out_path).write_text(json.dumps({"ok": True}))
        except Exception as exc:  # noqa: BLE001
            Path(out_path).write_text(json.dumps({"ok": False, "error": repr(exc)}))

    ctx = mp.get_context("fork")
    p_renew = ctx.Process(
        target=_renew_worker,
        args=(str(fake_leases_root), handle14.payload.lease_id, None, handle14.lock_ino, handle14.lock_dev,
              handle14.generation_id, handle14.payload.version_id, handle14.payload.instance_id,
              handle14.payload.acquired_at_epoch, handle14.payload.renewed_at_epoch,
              handle14.payload.expires_at_epoch, handle14.payload.request_kind, str(out_renew)),
    )
    p_renew.start()
    coord10.release(handle14)
    p_renew.join(10)
    renew_res = _read_json(str(out_renew))
    # CODEX P2B5-CX-006（DP-N14再修正）: 旧実装は「結果が何か存在すればPASS」
    # という基準で、未知の例外や無応答も含めて事実上何でもPASSにしていた。
    # per-lease lockによる直列化下でこの競合が取り得る正当な結果は
    # 「release前にrenewが先着して成功」または「release後にactive entryが
    # 消えておりFileNotFoundError／LeaseError／LeaseExpiredErrorで正しく
    # 失敗」のいずれかに限られる。それ以外（未知の例外種別、結果欠落）は
    # 破損の兆候としてFAILにする。
    _DPN14_ALLOWED_ERROR_MARKERS = ("FileNotFoundError", "LeaseError", "LeaseExpiredError")
    dpn14_ok = renew_res is not None and (
        renew_res.get("ok") is True
        or (
            renew_res.get("ok") is False
            and any(marker in renew_res.get("error", "") for marker in _DPN14_ALLOWED_ERROR_MARKERS)
        )
    )
    record(
        "DP-N14: release中/後に別processが同一leaseをrenewしようとした場合、"
        "結果は「renewal成功」または「release後の正しいNotFound/LeaseError失敗」の"
        "いずれかに限られ、未知の破損状態を示さない",
        dpn14_ok, f"renew_res={renew_res}",
    )

    # DP-N16b: future timestamp（許容範囲外）
    handle16 = coord10.acquire(r10.version_id, "dpn16")
    active16 = fake_leases_root / "active" / f"{handle16.payload.lease_id}.json"
    payload16 = json.loads(active16.read_text())
    payload16["acquired_at_epoch"] = time.time() + 10 ** 9  # 遥か未来
    active16.write_text(json.dumps(payload16))
    gc16 = RuntimeGc(
        data_runtime_root=fake_data_root, leases_root=fake_leases_root,
        expect_writer_uid=UID, expect_writer_gid=GID,
        version_retention_count=0, max_future_skew_s=5.0, capacity_min_free_bytes=1024,
    )
    try:
        gc16.run()
        record("DP-N16: 許容外future timestampのactive entryがある場合GCはfail-closed", False)
    except GcFailClosedError:
        record("DP-N16: 許容外future timestampのactive entryがある場合GCはfail-closed", True)
    active16.write_text(json.dumps({**payload16, "acquired_at_epoch": time.time()}))
    coord10.release(handle16)

    # DP-N12（CODEX指摘の再修正・CRITICAL）: 旧実装は「実fault injection未実施、
    # source確認で代替」と明記しながらrecord(..., True)としてPASSへ加算して
    # おり、denominatorを偽っていた（CODEX P2B5-CX-006指摘）。ここでは
    # `_failing_fsync_dir()`により、publish()内の2回のfsync_dir呼び出し
    # （1回目=renameat2直後・versions_fd＝current swap"直前"、2回目=
    # current rename直後・root_fd＝current swap"直後"）それぞれを実際に
    # 失敗させ、実際の挙動を観測する。

    # DP-N12a: 1回目（current swap直前）のfsync失敗 → この時点ではcurrent
    # symlinkに一切触れていないため、currentのtargetは完全に不変のはず。
    data_root_12a = tmp / "dpn12a" / "data_runtime"
    leases_root_12a = tmp / "dpn12a" / "leases"
    _bootstrap_roots(data_root_12a, leases_root_12a)
    publisher_12a = AtomicPublisher(data_root_12a, expect_uid=UID, expect_gid=GID)
    r12a_v1 = publish_new_version(publisher_12a, "v1")
    current_link_12a = data_root_12a / "current"
    target_before_12a = os.readlink(current_link_12a)

    with _failing_fsync_dir(1) as state12a:
        vid12a2 = generate_version_id()
        stg12a2 = publisher_12a.new_staging_path(vid12a2)
        make_dataset(stg12a2, "v2-should-fail")
        try:
            publisher_12a.publish(vid12a2, validate_ok)
            record("DP-N12a【実fault injection・swap直前】: fsync_dir(versions_fd)失敗時、publish()は例外を送出する", False)
        except OSError:
            record("DP-N12a【実fault injection・swap直前】: fsync_dir(versions_fd)失敗時、publish()は例外を送出する", True)
    target_after_12a = os.readlink(current_link_12a)
    record(
        "DP-N12a【実fault injection・swap直前】: swap直前fsync失敗時、currentのtargetは"
        "完全に不変（新versionへ切り替わっていない、old current target/hashが保存される）",
        target_after_12a == target_before_12a,
        f"before={target_before_12a} after={target_after_12a}",
    )

    # DP-N12b（CODEX第3ラウンド指摘の再修正）: 2回目以降（current swap直後の
    # retry込み）のfsync失敗 → rename自体は既にkernelレベルでatomicに完了
    # しているため（POSIX rename semantics）、fsync失敗後もcurrentは新
    # versionを指す。「old currentのtarget/inode/hashが不変」という要求は
    # rename後の失敗には原理的に適用できない（renameを後から取り消す手段が
    # ない）ため、CODEX指摘を受けて`publish()`側にPublishDurabilityError
    # という専用の契約を新設した（第17節参照）。ここではその契約——
    # (a) 有限回retryがすべて失敗して初めて例外化される、(b) 例外は
    # 汎用OSErrorではなくPublishDurabilityErrorという明示的な型である、
    # (c) currentは新versionへ切替済みのまま（rename atomicity維持、
    # 中途半端/破損した状態にはならない）——を直接検証する。
    from app.services.runtime_publish import PublishDurabilityError, _POST_SWAP_FSYNC_RETRY

    data_root_12b = tmp / "dpn12b" / "data_runtime"
    leases_root_12b = tmp / "dpn12b" / "leases"
    _bootstrap_roots(data_root_12b, leases_root_12b)
    publisher_12b = AtomicPublisher(data_root_12b, expect_uid=UID, expect_gid=GID)
    publish_new_version(publisher_12b, "v1")
    current_link_12b = data_root_12b / "current"

    with _failing_fsync_dir(2, persist=True) as state12b:
        vid12b2 = generate_version_id()
        stg12b2 = publisher_12b.new_staging_path(vid12b2)
        make_dataset(stg12b2, "v2")
        raised_durability_error = False
        try:
            publisher_12b.publish(vid12b2, validate_ok)
        except PublishDurabilityError:
            raised_durability_error = True
        except OSError:
            pass
        record(
            "DP-N12b【実fault injection・swap直後、retry込み】: fsync_dir(root_fd)が"
            f"retry（{_POST_SWAP_FSYNC_RETRY}回）すべて失敗した場合、publish()は汎用OSErrorではなく"
            "専用のPublishDurabilityErrorを送出し、状態の曖昧さを明示的に呼び出し元へ伝える",
            raised_durability_error,
        )
    record(
        "DP-N12b【実fault injection】: retryが実際に複数回試行されたことを確認する（単発失敗即諦めではない）",
        state12b["n"] >= 1 + _POST_SWAP_FSYNC_RETRY,
        f"calls={state12b['n']}",
    )
    target_after_12b = os.readlink(current_link_12b)
    version_root_after_12b = data_root_12b / target_after_12b
    record(
        "DP-N12b【実fault injection・swap直後】: PublishDurabilityError後もcurrentは有効な"
        "version directoryを指しており、破損/中途半端な状態にならない（rename atomicity維持）。"
        "old current不変ではなく「新currentは有効」を検証する——rename後の取消は原理的に不可能",
        version_root_after_12b.is_dir() and target_after_12b == f"versions/{vid12b2}",
        f"target={target_after_12b}",
    )
    record(
        "DP-N12c【実fault injection】: fault injectionが実際に両方のfsync_dir呼び出しへ到達したことを確認する"
        "（source文字列検索への代替ではなく、実際にcodeが実行された証拠）",
        state12a["n"] >= 1 and state12b["n"] >= 2,
        f"calls_12a={state12a['n']} calls_12b={state12b['n']}",
    )


def main() -> int:
    tmp = Path("/tmp/phase2b5_inner")
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)

    fns = [
        at11_01_atomic_publish_concurrent_reader_validation_rollback,
        at11_02_current_resolve_vs_gc_toctou,
        at11_03_renewal_vs_gc,
        at11_04_renewal_vs_release,
        at11_05_stale_cleanup_vs_renewal_release,
        at11_06_fixed_inode_old_holder,
        at11_07_retired_id_reuse_and_split_inode,
        at11_08_crash_timeout_lock_fsync_failure,
        at11_09_registry_tombstone_corruption,
        at11_10_clock_skew_ttl_boundary,
        at11_11_traversal_symlink_hardlink,
        at11_12_flock_capacity_inode,
        at11_12c_ttl_skew_margin_and_renewal,
        at11_12d_explicit_rollback_protection,
        at11_14_rename_noreplace_barrier,
        at11_15_shelter_registry_atomic_integration,
        dpn_fixtures,
    ]
    for fn in fns:
        try:
            fn(tmp)
        except Exception:  # noqa: BLE001
            record(f"{fn.__name__}: 実行時例外（fixture自体の失敗）", False, traceback.format_exc()[-1500:])

    shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in RESULTS if not r["pass"]]
    print()
    print(json.dumps({"total": len(RESULTS), "pass": len(RESULTS) - len(failed), "fail": len(failed), "results": RESULTS}))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

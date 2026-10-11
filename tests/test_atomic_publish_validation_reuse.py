"""
ATOMIC-PUBLISH-OPTIMIZATION: VALIDATED-CONTENT-REUSE と publish 契約の回帰テスト。

背景（2026-10-11 調査）: VPS（XFS reflink=1）の seed `cp -a` は既に reflink で物理 write ≒ 0。
activate の約 109 秒は、前 version 全量の sha256 再照合・件数 re-parse と、staging 全量の
schema 検証・sha256 で、大半は GeoJSON の Python 側 parse（CPU）。

VALIDATED-CONTENT-REUSE（opt-in）: staging の file の sha256 が「disk と再照合済みの前 manifest」の
同一 path と一致し、validation_contract（検証 module source と ijson の sha256）が同一なら、
schema 再検証と件数 re-parse を省く。sha256 は毎回全 file を計算する。

publisher 層のテスト（renameat2 が要る）は Linux でのみ実行する。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.services import runtime_dataset_validate as rdv  # noqa: E402
from app.services.runtime_atomic import RuntimeAtomicError  # noqa: E402

SURGE = "backend/hazard/storm_surge/tokyo/tokyo-surge-001.geojson"
ROUTING = "backend/hazard/flood/kanagawa/kanagawa-river-001.routing.geojson"
ROUTING2 = "backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson"
PROV = "provenance/KANAGAWA-RIVER-001.json"
TILE = "frontend/tiles/kanagawa/flood/kanagawa_river_001.mbtiles"

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="renameat2 / posix_fadvise は Linux 専用")


def _poly():
    return {"type": "Polygon", "coordinates": [[[139.0, 35.0], [139.1, 35.0], [139.1, 35.1], [139.0, 35.1], [139.0, 35.0]]]}


def _props(rel):
    if "storm_surge" in rel:
        return {"storm_surge_rank": 2}
    return {"flood_rank": 3}


def _write_fc(path: Path, count: int, props: dict, salt: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    feats = [{"type": "Feature", "properties": dict(props, **({"salt": salt} if salt else {})), "geometry": _poly()}
             for _ in range(count)]
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")


def _write_tile(path: Path, marker: str = "a") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()  # 新しい inode で作り直す（tile 差し替え相当）
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metadata (name text, value text)")
    conn.execute("INSERT INTO metadata VALUES ('marker', ?)", (marker,))
    conn.commit()
    conn.close()


def _build(root: Path, counts=None, prov="v1", tile="a", salts=None) -> Path:
    counts = counts or {SURGE: 130, ROUTING: 140, ROUTING2: 120}
    salts = salts or {}
    for rel, n in counts.items():
        _write_fc(root / rel, n, _props(rel), salts.get(rel, ""))
    (root / PROV).parent.mkdir(parents=True, exist_ok=True)
    (root / PROV).write_text(json.dumps({"record": prov}), encoding="utf-8")
    _write_tile(root / TILE, tile)
    return root


def _validate(staging, previous=None, **kw):
    with patch.object(rdv, "_resolve_configured_tsunami_targets", return_value=(frozenset(), None)):
        return rdv.validate_and_manifest_staging(staging, previous, **kw)


def _publish_like(root: Path, **kw) -> Path:
    """manifest 付きの version（前 version 役）を作る。"""
    manifest, counts = _validate(root)
    rdv.write_manifest(root, manifest, 0o640, counts)
    return root


def _seed_from(prev: Path, staging: Path) -> Path:
    shutil.copytree(prev, staging)
    (staging / rdv.MANIFEST_BASENAME).unlink()
    return staging


def _run(staging, prev, reuse):
    st = {}
    out = _validate(staging, prev, reuse_previous_validation=reuse, stats=st)
    return out, st


@pytest.fixture
def prev(tmp_path):
    return _publish_like(_build(tmp_path / "v1"))


# ── 1. 内容一致（reuse と全検証で manifest / 件数が完全一致）─────────────────────────

CASES = {
    "A_provenance_only": lambda s: (s / PROV).write_text(json.dumps({"record": "v2"}), encoding="utf-8"),
    "B_routing_and_tile": lambda s: (_write_fc(s / ROUTING, 141, _props(ROUTING), "new"), _write_tile(s / TILE, "b")),
    "C_multiple_hazards": lambda s: (_write_fc(s / ROUTING, 140, _props(ROUTING), "x"),
                                     _write_fc(s / SURGE, 131, _props(SURGE), "y"),
                                     _write_fc(s / ROUTING2, 122, _props(ROUTING2), "z"),
                                     (s / PROV).write_text("{}", encoding="utf-8")),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_reuse_result_identical_to_full_validation(tmp_path, prev, case):
    staging = _seed_from(prev, tmp_path / "stg")
    CASES[case](staging)
    full, st_full = _run(staging, prev, reuse=False)
    reused, st = _run(staging, prev, reuse=True)
    assert reused == full
    assert st["reuse"] == "enabled" and st_full["reuse"] == "disabled"
    changed = {rel for rel, sha in full[0].items() if json.loads((prev / rdv.MANIFEST_BASENAME).read_text())["files"].get(rel) != sha}
    assert st["validated_files"] == len(changed) and st["reused_files"] == st["files"] - len(changed)
    assert st["previous_parsed_files"] == len({r for r in changed if r.endswith(".geojson")})


def test_reused_files_are_not_reparsed(tmp_path, prev):
    staging = _seed_from(prev, tmp_path / "stg")
    CASES["A_provenance_only"](staging)
    calls = []
    orig = rdv._validate_json_file
    with patch.object(rdv, "_validate_json_file", side_effect=lambda p, **k: calls.append(p.name) or orig(p, **k)), \
            patch.object(rdv, "_count_features_in_file", side_effect=AssertionError("前 version を re-parse した")):
        _run(staging, prev, reuse=True)
    assert calls == ["KANAGAWA-RIVER-001.json"]


# ── 2. reuse しない条件（fail-closed 側へ倒れる）─────────────────────────────────────

def test_same_size_tamper_is_validated_and_rejected(tmp_path, prev):
    staging = _seed_from(prev, tmp_path / "stg")
    raw = (staging / SURGE).read_bytes()
    (staging / SURGE).write_bytes(raw.replace(b'"FeatureCollection"', b'"FeatureCollectioX"', 1))
    assert len((staging / SURGE).read_bytes()) == len(raw)
    with pytest.raises(RuntimeAtomicError):
        _run(staging, prev, reuse=True)


def test_invalid_new_file_still_rejected_under_reuse(tmp_path, prev):
    staging = _seed_from(prev, tmp_path / "stg")
    (staging / ROUTING).write_text('{"type": "FeatureCollection", "features": [{"type": "Feature"}]}')
    with pytest.raises(RuntimeAtomicError):
        _run(staging, prev, reuse=True)


@pytest.mark.parametrize("mutate,reason", [
    (lambda m: m.update(validation_contract="0" * 64), "validation_contract_changed"),
    (lambda m: m.pop("validation_contract"), "validation_contract_changed"),          # 旧形式 manifest
    (lambda m: m.pop("feature_counts"), "previous_manifest_incomplete"),
])
def test_reuse_disabled_when_previous_manifest_not_eligible(tmp_path, prev, mutate, reason):
    mp = prev / rdv.MANIFEST_BASENAME
    m = json.loads(mp.read_text())
    mutate(m)
    mp.write_text(json.dumps(m))
    staging = _seed_from(prev, tmp_path / "stg")
    out, st = _run(staging, prev, reuse=True)
    assert st["reuse"] == reason and st["reused_files"] == 0
    assert out == _run(staging, prev, reuse=False)[0]


def test_missing_recorded_count_falls_back_to_full_validation_for_that_file(tmp_path, prev):
    mp = prev / rdv.MANIFEST_BASENAME
    m = json.loads(mp.read_text())
    del m["feature_counts"][SURGE]
    mp.write_text(json.dumps(m))
    staging = _seed_from(prev, tmp_path / "stg")
    out, st = _run(staging, prev, reuse=True)
    assert st["reuse"] == "enabled" and out[1][SURGE] == 130 and st["validated_files"] == 1


def test_migration_never_reuses(tmp_path, prev):
    staging = _seed_from(prev, tmp_path / "stg")
    with patch.object(rdv, "_plan_flood_routing_migration", return_value=(set(), {"ref": "x"})):
        _, st = _run_mig(staging, prev)
    assert st["reuse"] == "migration" and st["reused_files"] == 0


def _run_mig(staging, prev):
    st = {}
    out = _validate(staging, prev, reuse_previous_validation=True, stats=st,
                    allow_flood_routing_migration=True, owner_approval_ref="test")
    return out, st


# ── 3. 既存 guard は reuse 下でも有効 ──────────────────────────────────────────────

def test_count_drop_on_changed_file_still_detected(tmp_path):
    prev = _publish_like(_build(tmp_path / "v1", counts={SURGE: 130, ROUTING: 1000, ROUTING2: 120}))
    staging = _seed_from(prev, tmp_path / "stg")
    _write_fc(staging / ROUTING, 100, _props(ROUTING))
    with pytest.raises(RuntimeAtomicError, match="壊滅的に減少"):
        _run(staging, prev, reuse=True)


def test_recorded_count_tamper_does_not_weaken_drop_guard(tmp_path):
    """判断根拠は前 version 実 file の re-parse（CX-003 第11ラウンド）。記録値の改ざんでは通らない。"""
    prev = _publish_like(_build(tmp_path / "v1", counts={SURGE: 130, ROUTING: 1000, ROUTING2: 120}))
    mp = prev / rdv.MANIFEST_BASENAME
    m = json.loads(mp.read_text())
    m["feature_counts"][ROUTING] = 100
    mp.write_text(json.dumps(m))
    staging = _seed_from(prev, tmp_path / "stg")
    _write_fc(staging / ROUTING, 100, _props(ROUTING))
    with pytest.raises(RuntimeAtomicError, match="壊滅的に減少"):
        _run(staging, prev, reuse=True)


def test_disappeared_dataset_still_detected(tmp_path, prev):
    staging = _seed_from(prev, tmp_path / "stg")
    (staging / SURGE).unlink()
    with pytest.raises(RuntimeAtomicError, match="消失"):
        _run(staging, prev, reuse=True)


def test_tampered_previous_version_rejected(tmp_path, prev):
    staging = _seed_from(prev, tmp_path / "stg")
    (prev / ROUTING2).write_text((prev / ROUTING2).read_text().replace('"flood_rank": 3', '"flood_rank": 4'))
    with pytest.raises(RuntimeAtomicError, match="改ざん"):
        _run(staging, prev, reuse=True)


def test_manifest_records_contract_and_reuse_summary(tmp_path, prev):
    m = json.loads((prev / rdv.MANIFEST_BASENAME).read_text())
    assert m["validation_contract"] == rdv.VALIDATION_CONTRACT and len(rdv.VALIDATION_CONTRACT) == 64
    staging = _seed_from(prev, tmp_path / "stg")
    (manifest, counts), st = _run(staging, prev, reuse=True)
    rdv.write_manifest(staging, manifest, 0o640, counts, validation_reuse={"reuse": st["reuse"]})
    m2 = json.loads((staging / rdv.MANIFEST_BASENAME).read_text())
    assert m2["validation_reuse"] == {"reuse": "enabled"} and m2["files"] == m["files"]
    rdv.verify_manifest_matches_disk(staging)


def test_contract_changes_when_validator_source_changes(tmp_path):
    """規則の変更（module source の変更）で contract が変わり、旧検証結果は再利用されない。"""
    src = Path(rdv.__file__).read_bytes()
    import ijson
    expect = hashlib.sha256(src)
    expect.update(f"\0ijson={ijson.__version__}/{ijson.backend}".encode())
    assert rdv.VALIDATION_CONTRACT == expect.hexdigest()
    other = hashlib.sha256(src + b"#")
    other.update(f"\0ijson={ijson.__version__}/{ijson.backend}".encode())
    assert other.hexdigest() != rdv.VALIDATION_CONTRACT


def test_reuse_is_opt_in_and_production_wrapper_default_off():
    wrapper = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    assert 'OHG2_PUBLISH_REUSE_VALIDATION:-0}" == "1"' in wrapper
    assert 'cp -a --reflink=auto "${CURRENT_REAL}/." "${STAGING_DIR}/"' in wrapper
    import inspect
    assert inspect.signature(rdv.validate_and_manifest_staging).parameters["reuse_previous_validation"].default is False


# ── 4. publisher 層（Linux）: previous immutable / rollback / crash safety ───────────

def _tree_state(v: Path):
    out = {}
    for p in sorted(v.rglob("*")):
        st = os.lstat(p)
        out[str(p.relative_to(v))] = (st.st_ino, st.st_mode, st.st_uid, st.st_gid, st.st_nlink, st.st_mtime_ns,
                                      hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None)
    return out


def _normalize(staging: Path):
    for p in [staging, *staging.rglob("*")]:
        os.chmod(p, 0o750 if p.is_dir() else 0o640)


@pytest.fixture
def publisher(tmp_path):
    from app.services.runtime_publish import AtomicPublisher
    root = tmp_path / "data_runtime"
    (root / ".staging").mkdir(parents=True)
    (root / "versions").mkdir()
    (root / ".publish.lock").touch(mode=0o600)
    return AtomicPublisher(root, expect_uid=os.geteuid(), expect_gid=os.getegid(),
                           capacity_min_free_bytes=None, min_free_inodes=None), root


def _validator(reuse):
    def fn(staging, previous):
        st = {}
        manifest, counts = _validate(staging, previous, reuse_previous_validation=reuse, stats=st)
        rdv.write_manifest(staging, manifest, 0o640, counts, validation_reuse={"reuse": st["reuse"]})
    return fn


def _stage_from_current(pub, root, mutate=None, vid=None):
    from app.services.runtime_atomic import generate_version_id
    vid = vid or generate_version_id()
    staging = root / ".staging" / vid
    cur = root / "current"
    if cur.is_symlink():
        # 本番 wrapper と同じ seed（reflink 対応 fs では CoW clone、hardlink は作らない）
        subprocess.run(["cp", "-a", "--reflink=auto", f"{os.path.realpath(cur)}/.", str(staging)], check=True,
                       capture_output=True) if staging.mkdir(mode=0o750) is None else None
        (staging / rdv.MANIFEST_BASENAME).unlink()
    else:
        staging.mkdir(mode=0o750)
        _build(staging)
    if mutate:
        mutate(staging)
    _normalize(staging)
    return vid, staging


@linux_only
@pytest.mark.parametrize("case", sorted(CASES))
def test_publish_rollback_previous_immutable(publisher, case):
    pub, root = publisher
    v1, _ = _stage_from_current(pub, root)
    pub.publish(v1, _validator(True))
    before = _tree_state(root / "versions" / v1)
    v2, staging = _stage_from_current(pub, root, CASES[case])
    assert all(os.lstat(p).st_nlink == 1 for p in staging.rglob("*") if p.is_file())
    res = pub.publish(v2, _validator(True))
    assert res.previous_version_id == f"versions/{v1}"
    m2 = json.loads((root / "versions" / v2 / rdv.MANIFEST_BASENAME).read_text())
    assert m2["validation_reuse"] == {"reuse": "enabled"}
    rdv.verify_manifest_matches_disk(root / "versions" / v2)
    assert _tree_state(root / "versions" / v1) == before          # 前 version は inode・mode・内容とも不変
    pub.rollback(v1)
    assert os.readlink(root / "current") == f"versions/{v1}"
    assert _tree_state(root / "versions" / v1) == before
    # full 検証で作った場合と manifest（files / feature_counts）が一致
    v3, staging3 = _stage_from_current(pub, root, None)
    full = _validate(staging3, root / "versions" / v1)
    assert full[0] == json.loads((root / "versions" / v1 / rdv.MANIFEST_BASENAME).read_text())["files"]


@linux_only
@pytest.mark.parametrize("failure", ["validator_crash", "invalid_overlay", "hardlink_overlay", "bad_mode"])
def test_failed_publish_keeps_current_and_previous(publisher, failure):
    pub, root = publisher
    v1, _ = _stage_from_current(pub, root)
    pub.publish(v1, _validator(True))
    before = _tree_state(root / "versions" / v1)

    def mutate(s):
        if failure == "invalid_overlay":
            (s / ROUTING).write_text("{broken")
        elif failure == "hardlink_overlay":
            os.link(s / PROV, s / "provenance/extra.json")
    v2, staging = _stage_from_current(pub, root, mutate)
    validator = _validator(True)
    if failure == "validator_crash":
        def validator(staging, previous):  # noqa: F811 — manifest 書き込み途中の kill 相当
            _validator(True)(staging, previous)
            raise KeyboardInterrupt("simulated kill")
    if failure == "bad_mode":
        os.chmod(staging / PROV, 0o664)
    with pytest.raises((RuntimeAtomicError, KeyboardInterrupt)):
        pub.publish(v2, validator)
    assert os.readlink(root / "current") == f"versions/{v1}"
    assert not (root / "versions" / v2).exists()
    assert _tree_state(root / "versions" / v1) == before

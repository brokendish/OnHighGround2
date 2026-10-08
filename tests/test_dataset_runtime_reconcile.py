"""
RUNTIME-STATE-RECONCILE: CLI publish 後も DatasetState / 管理画面が実 runtime を正として同期されること。

正の優先順位: current → _manifest.json → artifact → sha256 → DatasetState（キャッシュ）。
artifact は manifest 記録 sha256 を使い再ハッシュしない。反映元 sha256 は永続キャッシュ。
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import (  # noqa: E402
    DatasetDefinition, DatasetState, DeployStatus, NormalizeStatus, StorageStatus, ValidationStatus,
)
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from app.services.flood_routing_contract import BUILDER_NAME, CONTRACT_VERSION  # noqa: E402

V1 = "20261006T000000Z-00000001"
V2 = "20261006T010000Z-00000002"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _defn(layer_type, dataset_id, region="tokyo", **kw):
    return DatasetDefinition(
        dataset_id=dataset_id, region=region, category=layer_type, display_name="t", description="t",
        hint_text="t", impact_scope="t", accepted_input_modes=[], accepted_extensions=[],
        max_browser_upload_mb=0, requires_normalize=False, requires_validation=False, requires_deploy=True,
        requires_osrm_rebuild=False, raw_storage_path=f"data_lake/raw/{region}/{layer_type}",
        validated_storage_path=f"data_lake/validated/{region}/{layer_type}",
        runtime_path=f"data_runtime/backend/hazard/{layer_type}", deploy_mode="copy_file",
        layer_type=layer_type, **kw,
    )


class Env:
    """tmp 上の data_lake（validated / derived）と data_runtime（versions + current）。"""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.lake = tmp / "data_lake"
        self.rt = tmp / "runtime"
        self.cache = drr.SourceShaCache(tmp / "cache" / "source_sha256.json")

    def validated(self, layer_type, name, content=b'{"v":1}', region="tokyo") -> Path:
        p = self.lake / "validated" / region / layer_type / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def flood_routing(self, canonical: Path, routing_content: bytes, canonical_sha=None) -> Path:
        d = Path(str(canonical.parent).replace("/validated/", "/derived/"))
        d.mkdir(parents=True, exist_ok=True)
        stem = canonical.name[: -len(".geojson")]
        (d / f"{stem}.routing.geojson").write_bytes(routing_content)
        (d / f"{stem}.routing.meta.json").write_text(json.dumps({
            "contract": CONTRACT_VERSION, "dataset_id": "X", "source_canonical_path": str(canonical),
            "source_canonical_sha256": canonical_sha or _sha(canonical.read_bytes()),
            "routing_artifact_sha256": _sha(routing_content), "builder_name": BUILDER_NAME,
            "builder_version": "1", "tau": 0.85, "min_split_size": 0, "feature_count": 1,
            "generated_at": "2026-10-06T00:00:00Z",
        }))
        return d / f"{stem}.routing.geojson"

    def version(self, vid, files: dict, activate=True):
        """files: rel → bytes。manifest は実 sha256 を記録（activate_version.py と同じ契約）。"""
        v = self.rt / "versions" / vid
        manifest = {}
        for rel, content in files.items():
            (v / rel).parent.mkdir(parents=True, exist_ok=True)
            (v / rel).write_bytes(content)
            manifest[rel] = _sha(content)
        v.mkdir(parents=True, exist_ok=True)
        (v / "_manifest.json").write_text(json.dumps({"files": manifest}))
        if activate:
            self.activate(vid)
        return v

    def activate(self, vid):
        link = self.rt / "current"
        tmp = self.rt / "current.tmp"
        os.symlink(f"versions/{vid}", tmp)
        os.replace(tmp, link)

    def view(self):
        return drr.load_runtime_view(self.rt)


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("OHG2_DATA_RUNTIME_ROOT", str(e.rt))
    monkeypatch.setattr(drr, "_default_cache", e.cache)  # data_lake/admin/cache へ書かない
    drr._view_cache.clear()
    yield e
    drr._view_cache.clear()


def _state(defn, validated: Path | None, **kw):
    base = dict(dataset_id=defn.dataset_id, storage_status=StorageStatus.stored,
                current_validated_path=str(validated) if validated else None)
    base.update(kw)
    return DatasetState(**base)


LANDSLIDE_REL = "backend/hazard/landslide/tokyo/tokyo-landslide-001.geojson"


# ── 1. CLI publish 後の published 化 / 3. flat → versioned path ─────────────────

def test_cli_published_dataset_becomes_published_with_versioned_path(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    v = env.version(V1, {LANDSLIDE_REL: b"L1"})
    # CLI publish 直後: admin 側 state は flat path / deployable のまま（旧問題）
    state = _state(defn, src, deploy_status=DeployStatus.deployable, is_deployable=True,
                   current_runtime_path="/data_runtime/backend/hazard/landslide/tokyo/tokyo-landslide-001.geojson")
    res = drr.reconcile_one(defn, state, persist=False, view=env.view())
    assert res.runtime_status == drr.PUBLISHED and res.matches_source is True
    assert res.current_version == V1 and res.runtime_sha256 == _sha(b"L1")
    assert state.deploy_status == DeployStatus.deployed and state.is_deployable is False
    assert state.current_runtime_path == str(v / LANDSLIDE_REL)
    assert "/versions/" in state.current_runtime_path
    assert state.deployed_at is not None


# ── 2. stale 修復 ────────────────────────────────────────────────────────────────

def test_stale_deployed_state_is_repaired(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    env.version(V1, {"backend/hazard/flood/tokyo/x.routing.geojson": b"F"})
    state = _state(defn, src, deploy_status=DeployStatus.deployed, is_deployable=False,
                   current_runtime_path="/data_runtime/versions/OLD/" + LANDSLIDE_REL)
    res = drr.reconcile_one(defn, state, persist=False, view=env.view())
    assert res.runtime_status == drr.STALE and res.artifact_present is False
    assert state.deploy_status == DeployStatus.deployable and state.is_deployable is True
    assert state.current_runtime_path is None


# ── 4. not_published ─────────────────────────────────────────────────────────────

def test_not_published(env):
    defn = _defn("inland_flood", "TOKYO-URBAN-001")
    src = env.validated("inland_flood", "tokyo-urban-001.geojson")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    state = _state(defn, src)
    res = drr.reconcile_one(defn, state, persist=False, view=env.view())
    assert res.runtime_status == drr.NOT_PUBLISHED
    assert state.deploy_status == DeployStatus.deployable and state.is_deployable is True


# ── 5. mismatch ──────────────────────────────────────────────────────────────────

def test_mismatch_when_source_differs_from_runtime(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"NEW")
    v = env.version(V1, {LANDSLIDE_REL: b"OLD"})
    state = _state(defn, src, deploy_status=DeployStatus.deployed)
    res = drr.reconcile_one(defn, state, persist=False, view=env.view())
    assert res.runtime_status == drr.MISMATCH and res.matches_source is False
    assert state.deploy_status == DeployStatus.deployable and state.is_deployable is True
    assert state.current_runtime_path == str(v / LANDSLIDE_REL)  # 実行中 artifact は報告する


# ── 6. current version 切替の検知 ────────────────────────────────────────────────

def test_current_version_switch_is_detected(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L2")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    state = _state(defn, src)
    assert drr.reconcile_one(defn, state, persist=False).runtime_status == drr.MISMATCH
    v2 = env.version(V2, {LANDSLIDE_REL: b"L2"})  # CLI publish で current 切替
    res = drr.reconcile_one(defn, state, persist=False)
    assert res.current_version == V2 and res.runtime_status == drr.PUBLISHED
    assert state.current_runtime_path == str(v2 / LANDSLIDE_REL)


# ── 7. operator 起動時 reconcile（重い副作用 module は import せず静的確認）─────

def test_operator_startup_runs_reconcile_in_background():
    src = (ROOT / "backend/app_operator.py").read_text(encoding="utf-8")
    startup = src[src.index("def _startup"):src.index("def _start_runtime_state_reconcile")]
    assert "_start_runtime_state_reconcile()" in startup
    body = src[src.index("def _start_runtime_state_reconcile"):]
    body = body[: body.index("\ndef ", 1)] if "\ndef " in body[1:] else body
    assert "threading.Thread" in body and "daemon=True" in body
    assert "reconcile_all(allow_hash=True, persist=True)" in body
    assert "except Exception" in body  # 起動を止めない


# ── 8. publish-status API が reconcile して state を保存 / 9. 管理情報は保持 ─────

def test_publish_status_reconciles_and_persists_preserving_admin_fields(env):
    from app.api import admin_datasets as api
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    state = _state(defn, src, deploy_status=DeployStatus.deployable, is_deployable=True,
                   last_job_id="job-123", backup_path="/backup/x", current_tile_path="/tiles/l.mbtiles")
    ds, ss = Mock(), Mock()
    ds.get.return_value = defn
    ss.init_from_definition.return_value = state
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss):
        st = asyncio.run(api.get_publish_status(defn.dataset_id))
    assert st["runtime_status"] == "published" and st["state_reconciled"] is True
    assert st["deploy_status"] == "deployed" and st["deployable"] is False
    assert st["provenance"]["canonical_path"] == str(src)
    assert st["provenance"]["source_files"] == [] and st["provenance"]["acquisition_date"] is None
    assert st["provenance"]["tile_path"] == "/tiles/l.mbtiles"
    ss.save.assert_called_once()
    saved = ss.save.call_args[0][0]
    assert saved.last_job_id == "job-123" and saved.backup_path == "/backup/x"
    assert saved.current_validated_path == str(src)


def test_dataset_list_uses_no_hash_and_detail_may_hash():
    src = (ROOT / "backend/app/api/admin_datasets.py").read_text(encoding="utf-8")
    summary = src[src.index("def _build_summary"):src.index("def _reconcile_quietly")]
    assert "_reconcile_quietly(defn, state, ss, allow_hash=False)" in summary
    detail = src[src.index("async def get_dataset("):]
    detail = detail[: detail.index("\n@router", 1)]
    assert "_reconcile_quietly(defn, state, ss, allow_hash=True)" in detail
    # /runtime-reconcile は /{dataset_id} に shadow されない位置
    assert src.index('"/runtime-reconcile"') < src.index('"/{dataset_id}"')


# ── 10. 未登録 runtime artifact（A51 / A33 相当）─────────────────────────────────

def test_unregistered_runtime_artifacts_detected_not_deleted(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    a51 = "backend/hazard/inland_flood/tokyo/tokyo_inland_flood_A51.geojson"
    a33 = "backend/hazard/landslide/tokyo/tokyo_landslide_A33.geojson"
    v = env.version(V1, {LANDSLIDE_REL: b"L1", a51: b"A51", a33: b"A33",
                         "backend/shelters/tokyo.geojson": b"S", "frontend/hazard/x.geojson": b"X"})
    ds, ss = Mock(), Mock()
    ds.list_all.return_value = [defn]
    ss.init_from_definition.return_value = _state(defn, src)
    report = drr.reconcile_all(ds, ss, persist=False)
    rels = {u["rel_path"]: u for u in report["unregistered_runtime_artifacts"]}
    assert set(rels) == {a51, a33}  # hazard 配下のみ・登録 dataset の artifact は除外
    assert rels[a51]["hazard_type"] == "inland_flood" and rels[a51]["region"] == "tokyo"
    assert rels[a33]["runtime_status"] == drr.UNREGISTERED_RUNTIME and rels[a33]["sha256"] == _sha(b"A33")
    assert (v / a51).is_file() and (v / a33).is_file()  # 自動削除しない


# ── 11. 既存 type 回帰 ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("layer_type,dataset_id,name", [
    ("inland_flood", "TOKYO-URBAN-001", "tokyo-urban-001.geojson"),
    ("landslide", "TOKYO-LANDSLIDE-001", "tokyo-landslide-001.geojson"),
    ("lowland_poor_drainage", "TOKYO-LOWLAND-POOR-DRAINAGE-001", "lowland_poor_drainage.geojson"),
    ("storm_surge", "TOKYO-STORM-SURGE-001", "tokyo-storm-surge-001.geojson"),
    ("pseudo_inland_flood", "TOKYO-PSEUDO-001", "tokyo-pseudo-001.geojson"),
])
def test_atomic_types_published(env, layer_type, dataset_id, name):
    defn = _defn(layer_type, dataset_id)
    src = env.validated(layer_type, name, b"C")
    rel = f"backend/hazard/{layer_type}/tokyo/{name}"
    env.version(V1, {rel: b"C"})
    state = _state(defn, src)
    res = drr.reconcile_one(defn, state, persist=False, view=env.view())
    assert res.runtime_status == drr.PUBLISHED and res.runtime_rel == rel
    assert state.deploy_status == DeployStatus.deployed


def test_flood_published_via_routing_artifact(env):
    defn = _defn("flood", "TOKYO-FLOOD-001")
    canonical = env.validated("flood", "tokyo-flood-001.geojson", b"CANON")
    routing = env.flood_routing(canonical, b"ROUTING")
    rel = "backend/hazard/flood/tokyo/tokyo-flood-001.routing.geojson"
    env.version(V1, {rel: b"ROUTING"})
    state = _state(defn, canonical)
    res = drr.reconcile_one(defn, state, persist=False, view=env.view())
    assert res.runtime_status == drr.PUBLISHED and res.source_sha256 == _sha(b"ROUTING")
    assert res.provenance["derived_path"] == str(routing)
    assert res.provenance["canonical_path"] == str(canonical)


def test_flood_canonical_updated_but_routing_not_regenerated_is_mismatch(env):
    defn = _defn("flood", "TOKYO-FLOOD-001")
    canonical = env.validated("flood", "tokyo-flood-001.geojson", b"CANON-NEW")
    env.flood_routing(canonical, b"ROUTING", canonical_sha=_sha(b"CANON-OLD"))
    env.version(V1, {"backend/hazard/flood/tokyo/tokyo-flood-001.routing.geojson": b"ROUTING"})
    res = drr.reconcile_one(defn, _state(defn, canonical), persist=False, view=env.view())
    assert res.runtime_status == drr.MISMATCH and res.source_sha256.startswith("stale-derived:")


def test_legacy_layer_untouched(env):
    defn = _defn("road", "TOKYO-ROAD-001")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    state = _state(defn, None, deploy_status=DeployStatus.deployed, current_runtime_path="/x")
    before = state.model_dump()
    res = drr.reconcile_one(defn, state, persist=False, view=env.view())
    assert res.runtime_status == drr.LEGACY and state.model_dump() == before


# ── 12. tsunami は unsupported のまま（存在だけ報告・state 不変）─────────────────

def test_tsunami_stays_unsupported(env):
    defn = _defn("tsunami", "KANAGAWA-TSUNAMI-001", region="kanagawa")
    src = env.validated("tsunami", "kanagawa-tsunami-001.geojson", b"T", region="kanagawa")
    env.version(V1, {"backend/hazard/tsunami/tsunami_kanagawa.geojson": b"LEGACY"})
    state = _state(defn, src, deploy_status=DeployStatus.deployable, is_deployable=True)
    before = state.model_dump()
    with patch.object(drr, "sha256_file", side_effect=AssertionError("tsunami 反映元はハッシュしない")):
        res = drr.reconcile_one(defn, state, persist=False, view=env.view())
    assert res.runtime_status == drr.UNSUPPORTED and res.publish_mode == "unsupported"
    assert res.artifact_present is True and res.matches_source is None
    assert state.model_dump() == before


# ── 13. 再ハッシュしない ─────────────────────────────────────────────────────────

def test_no_rehash_on_repeated_calls(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    calls = []
    real = drr.sha256_file
    with patch.object(drr, "sha256_file", side_effect=lambda p, *a: calls.append(str(p)) or real(p, *a)):
        for _ in range(5):
            assert drr.reconcile_one(defn, _state(defn, src), persist=False).runtime_status == drr.PUBLISHED
        assert calls == [str(src)]  # 反映元 1 回のみ・runtime artifact は manifest 値
        # 永続キャッシュ: 新しい cache instance（=再起動）でもハッシュしない
        cache2 = drr.SourceShaCache(env.tmp / "cache" / "source_sha256.json")
        drr.reconcile_one(defn, _state(defn, src), persist=False, cache=cache2, allow_hash=False)
        assert len(calls) == 1
        # 内容変更（size/mtime 変化）でのみ再計算
        src.write_bytes(b"L1-changed")
        assert drr.reconcile_one(defn, _state(defn, src), persist=False).runtime_status == drr.MISMATCH
        assert len(calls) == 2


def test_allow_hash_false_cache_miss_is_unknown_without_state_change(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    state = _state(defn, src, deploy_status=DeployStatus.deployable, is_deployable=True)
    before = state.model_dump()
    with patch.object(drr, "sha256_file", side_effect=AssertionError("一覧 API でハッシュしない")):
        res = drr.reconcile_one(defn, state, persist=False, allow_hash=False)
    assert res.runtime_status == drr.UNKNOWN and res.artifact_present is True
    assert state.model_dump() == before


def test_manifest_view_is_cached(env):
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    v1 = env.view()
    assert env.view() is v1  # 同一 version / manifest は再読込しない


# ── 14. manifest 破損・current 欠落は unknown（state 不変）──────────────────────

@pytest.mark.parametrize("setup", ["no_current", "no_manifest", "corrupt_manifest", "bad_files"])
def test_broken_runtime_is_unknown_and_state_unchanged(env, setup):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    if setup != "no_current":
        v = env.version(V1, {LANDSLIDE_REL: b"L1"})
        m = v / "_manifest.json"
        if setup == "no_manifest":
            m.unlink()
        elif setup == "corrupt_manifest":
            m.write_text("{broken")
        elif setup == "bad_files":
            m.write_text(json.dumps({"files": [LANDSLIDE_REL]}))
    state = _state(defn, src, deploy_status=DeployStatus.deployed, current_runtime_path="/keep")
    before = state.model_dump()
    ss = Mock()
    res = drr.reconcile_one(defn, state, ss, persist=True)
    assert res.runtime_status == drr.UNKNOWN and res.reason
    assert state.model_dump() == before
    ss.save.assert_not_called()


# ── 15. 反映中・pipeline 未完了の扱い / 個別失敗で全体を止めない ─────────────────

def test_deploying_state_not_overwritten(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    state = _state(defn, src, deploy_status=DeployStatus.deploying)
    drr.reconcile_one(defn, state, persist=False)
    assert state.deploy_status == DeployStatus.deploying


def test_not_published_not_ready_pipeline_is_not_deployable(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001", ).model_copy(update={"requires_validation": True})
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    env.version(V1, {})
    state = _state(defn, src, validation_status=ValidationStatus.failed, deploy_status=DeployStatus.deployed)
    res = drr.reconcile_one(defn, state, persist=False)
    assert res.runtime_status == drr.STALE
    assert state.deploy_status == DeployStatus.not_deployed and state.is_deployable is False


def test_reconcile_all_continues_after_one_failure(env):
    good = _defn("landslide", "TOKYO-LANDSLIDE-001")
    bad = _defn("inland_flood", "TOKYO-URBAN-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    ds, ss = Mock(), Mock()
    ds.list_all.return_value = [bad, good]
    ss.init_from_definition.side_effect = lambda d: (_ for _ in ()).throw(OSError("boom")) if d is bad \
        else _state(good, src)
    report = drr.reconcile_all(ds, ss)
    assert [e["dataset_id"] for e in report["errors"]] == ["TOKYO-URBAN-001"]
    assert [r["runtime_status"] for r in report["results"]] == ["published"]
    ss.save.assert_called_once()


def test_save_failure_does_not_raise(env):
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    env.version(V1, {LANDSLIDE_REL: b"L1"})
    ss = Mock()
    ss.save.side_effect = OSError("read-only")
    assert drr.reconcile_one(defn, _state(defn, src), ss).runtime_status == drr.PUBLISHED


# ── 16. CLI と wrapper hook（publish の成否に影響しない）─────────────────────────

def _cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "reconcile_dataset_state_cli", ROOT / "scripts/publish/reconcile_dataset_state.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("report,rc", [
    ({"current_version": V1, "runtime_error": None, "results": [
        {"dataset_id": "A", "runtime_status": "published"}], "errors": [], "unregistered_runtime_artifacts": []}, 0),
    ({"current_version": None, "runtime_error": "current が未設定です", "results": [], "errors": [],
      "unregistered_runtime_artifacts": []}, 1),
])
def test_cli_reports_and_exit_code(monkeypatch, capsys, tmp_path, report, rc):
    mod = _cli()
    seen = {}

    def fake(**kw):
        seen.update(kw, root=os.environ["OHG2_DATA_RUNTIME_ROOT"])
        return report
    monkeypatch.setattr(drr, "reconcile_all", fake)
    monkeypatch.setattr(sys, "argv", ["x", "--data-runtime-root", str(tmp_path), "--no-hash", "--dry-run"])
    assert mod.main() == rc
    assert seen == {"allow_hash": False, "persist": False, "root": str(tmp_path)}
    assert json.loads(capsys.readouterr().out)["current_version"] == report["current_version"]


def test_wrapper_hook_after_success_and_non_fatal():
    sh = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    ok = sh.index('log_info "publish succeeded: current -> versions/${VERSION_ID}"')
    hook = sh.index('reconcile_dataset_state.py" --data-runtime-root "${DATA_RUNTIME}"')
    assert ok < hook
    block = sh[sh.rindex("\n", 0, hook):sh.index("\nfi\n", hook)]
    assert block.lstrip().startswith("if python3")  # 失敗しても set -e で落ちない
    assert "log_warn" in block and "exit" not in block


def test_no_rewrite_when_result_equals_persisted_state(env, tmp_path):
    """一覧 API は update_deployable（is_deployable=True）→ reconcile（published で False）の順で
    in-memory を往復させる。永続値と同一なら保存しない（5 秒ポーリングごとの書き直し防止）。"""
    from app.services.dataset_state_service import DatasetStateService
    defn = _defn("landslide", "TOKYO-LANDSLIDE-001")
    src = env.validated("landslide", "tokyo-landslide-001.geojson", b"L1")
    v = env.version(V1, {LANDSLIDE_REL: b"L1"})
    svc = DatasetStateService(state_dir=tmp_path / "st", history_dir=tmp_path / "hi")
    st = _state(defn, src, deploy_status=DeployStatus.deployed, is_deployable=False,
                current_runtime_path=str(v / LANDSLIDE_REL), deployed_at=env.view().published_at)
    svc.save(st)
    f = tmp_path / "st" / "TOKYO-LANDSLIDE-001.json"
    before = (f.read_bytes(), f.stat().st_mtime_ns)
    with patch.object(svc, "save", wraps=svc.save) as save:
        for _ in range(3):
            state = svc.load(defn.dataset_id)
            state.is_deployable = True  # update_deployable 相当の in-memory 変更
            drr.reconcile_one(defn, state, svc, persist=True)
            assert state.is_deployable is False
    save.assert_not_called()
    assert (f.read_bytes(), f.stat().st_mtime_ns) == before

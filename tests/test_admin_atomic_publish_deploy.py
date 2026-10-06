"""
管理画面「反映」→ 正式 atomic publish（deploy_to_runtime_atomic.sh）統合のテスト。

wrapper 本体は Linux container 専用（renameat2）のため、pipeline が起動する subprocess を
「wrapper と同じ結果を tmp runtime 上に作る fake」に差し替えて、pipeline / API 側の契約を検証する。

  1. hazard（flood / storm_surge）反映は wrapper を通る（flat path へ書かない）
  2. activation 成功まで deployed にしない
  3. activation 失敗（wrapper exit≠0）時 current 不変・deploy_status=failed
  4. staging 失敗時 current 不変
  5. migration 指定なしの初回 flood routing 移行は reject
  6. owner approval ref なしは reject
  7. 正しい migration 指定で成功（wrapper に flag + 承認参照が渡る）
  8. manifest.migrations に記録が無ければ成功扱いにしない
  9. current が新 version へ切替、current_runtime_path は version 内 artifact
 12/13. 非 atomic hazard（inland_flood）・非 hazard（tide 等）は従来経路のまま
  ＋ 移行済み環境での migration 再指定は reject、rollback は atomic 管理 dataset では拒否
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytest.importorskip("shapely")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts" / "derive"))

import build_flood_routing_artifact as bfr  # noqa: E402
from app.models.admin_dataset import (  # noqa: E402
    DatasetDefinition, DatasetState, DeployStatus, JobStep, StorageStatus,
)
from app.services import admin_atomic_publish as aap  # noqa: E402
from app.services import pipeline_service as ps  # noqa: E402

V0 = "20260905T114335Z-40248243"


# ── fixtures ────────────────────────────────────────────────────────────────────

def _defn(layer_type="flood", dataset_id="TOKYO-RIVER-001", **kw) -> DatasetDefinition:
    base = dict(
        dataset_id=dataset_id, region="tokyo", category=layer_type, display_name="t", description="t",
        hint_text="t", impact_scope="t", accepted_input_modes=[], accepted_extensions=[],
        max_browser_upload_mb=0, requires_normalize=False, requires_validation=False, requires_deploy=True,
        requires_osrm_rebuild=False, raw_storage_path=f"data_lake/raw/tokyo/{layer_type}",
        validated_storage_path=f"data_lake/validated/tokyo/{layer_type}",
        runtime_path=f"data_runtime/backend/hazard/{layer_type}", deploy_mode="copy_file", layer_type=layer_type,
    )
    base.update(kw)
    return DatasetDefinition(**base)


def _write_fc(path: Path, rank_key="flood_rank") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    feat = {"type": "Feature", "properties": {rank_key: 2},
            "geometry": {"type": "Polygon", "coordinates": [[[139.0, 35.0], [139.01, 35.0], [139.01, 35.01],
                                                             [139.0, 35.01], [139.0, 35.0]]]}}
    path.write_text('{"type":"FeatureCollection","features":[\n' + json.dumps(feat, separators=(",", ":"))
                    + "\n]}\n", encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    """canonical + derived routing、legacy flood を持つ current（V0）の tmp runtime。"""
    canonical = _write_fc(tmp_path / "data_lake/validated/tokyo/flood/tokyo-river-001.geojson")
    routing = tmp_path / "data_lake/derived/tokyo/flood/tokyo-river-001.routing.geojson"
    bfr.build(canonical, routing, "TOKYO-RIVER-001")

    rt = tmp_path / "runtime"
    legacy = rt / "versions" / V0 / "backend/hazard/flood/tokyo_flood_check.geojsonl"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("{}\n", encoding="utf-8")
    (rt / "versions" / V0 / "_manifest.json").write_text(json.dumps({"files": {}}), encoding="utf-8")
    os.symlink(f"versions/{V0}", rt / "current")

    monkeypatch.setenv("OHG2_DATA_RUNTIME_ROOT", str(rt))
    monkeypatch.setattr(aap, "publish_regions", lambda: ["kanagawa", "tokyo"])
    monkeypatch.setattr(ps, "_PROJECT_ROOT", tmp_path)
    return {"tmp": tmp_path, "rt": rt, "canonical": canonical, "routing": routing}


def _state(path: Path) -> DatasetState:
    return DatasetState(dataset_id="X", storage_status=StorageStatus.stored, current_validated_path=str(path))


def _job():
    return Mock(job_id="job-1", requested_by="t", actor_id="t", request_id="r")


class FakeWrapper:
    """deploy_to_runtime_atomic.sh の代役。成功時は新 version を作り current を切り替える。"""

    def __init__(self, env, exit_code=0, record_migration=True, layer_type="flood", place=None):
        self.env, self.exit_code, self.record_migration = env, exit_code, record_migration
        self.layer_type, self.place = layer_type, place
        self.calls, self.state_during = [], []

    async def __call__(self, cmd, job, jm, timeout=None):
        self.calls.append(cmd)
        self.state_during.append(getattr(self, "watch_state", None) and self.watch_state.deploy_status)
        rt = self.env["rt"]
        staging = rt / ".staging" / "20261006T000000Z-deadbeef"
        staging.mkdir(parents=True, exist_ok=True)  # staging は作られる（失敗時も current は変えない）
        if self.exit_code not in (0, 4):
            return self.exit_code
        vid = "20261006T000000Z-deadbeef"
        version = rt / "versions" / vid
        shutil.move(str(staging), str(version))
        src, rel = self.place or (self.env["routing"], "backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson")
        (version / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, version / rel)
        manifest = {"files": {rel: "x"}, "file_count": 1, "feature_counts": {}}
        if "--allow-flood-routing-migration" in cmd and self.record_migration:
            ref = cmd[cmd.index("--allow-flood-routing-migration") + 1]
            manifest["migrations"] = [{"type": "flood_routing_migration", "owner_approval_ref": ref}]
        (version / "_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        tmp_link = rt / ".current.tmp"
        os.symlink(f"versions/{vid}", tmp_link)
        os.replace(tmp_link, rt / "current")
        return self.exit_code


def _failed_code(jm):
    for c in jm.update.call_args_list:
        if c.kwargs.get("step") == JobStep.failed:
            return c.kwargs.get("error_code")
    return None


def _deploy(env, wrapper, defn=None, migration_ref=None, state=None):
    defn = defn or _defn()
    state = state or _state(env["canonical"])
    wrapper.watch_state = state
    jm, ss = Mock(), Mock()
    with patch.object(ps, "_run_subprocess", wrapper), patch.object(ps, "_do_tile_build", _noop_async):
        asyncio.run(ps.run_deploy(_job(), defn, state, jm, ss, flood_routing_migration_ref=migration_ref))
    return state, jm


async def _noop_async(*_a, **_k):
    return None


def _current(env):
    return os.readlink(env["rt"] / "current")


# ── tests ───────────────────────────────────────────────────────────────────────

def test_flood_migration_goes_through_atomic_wrapper_and_switches_current(env):
    w = FakeWrapper(env)
    state, jm = _deploy(env, w, migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    assert _failed_code(jm) is None
    cmd = w.calls[0]
    assert cmd[:2] == ["bash", str(ps._SCRIPTS_DIR / "publish" / "deploy_to_runtime_atomic.sh")]
    assert cmd[2:6] == ["--region", "kanagawa", "--region", "tokyo"]
    assert cmd[-2:] == ["--allow-flood-routing-migration", "LOCAL-FLOOD-ROUTING-MIGRATION-20261006"]
    assert _current(env) == "versions/20261006T000000Z-deadbeef"
    assert state.deploy_status == DeployStatus.deployed and state.is_deployable is False
    assert state.current_runtime_path == str(
        env["rt"] / "versions/20261006T000000Z-deadbeef/backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson")
    assert w.state_during == [DeployStatus.deploying]  # activation 前は deployed にしない
    assert not (env["tmp"] / "data_runtime").exists()  # flat path へ書かない


def test_activation_failure_keeps_current_and_marks_failed(env):
    w = FakeWrapper(env, exit_code=1)
    state, jm = _deploy(env, w, migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    assert _failed_code(jm) == "ATOMIC_PUBLISH_FAILED"
    assert _current(env) == f"versions/{V0}"
    assert state.deploy_status == DeployStatus.failed
    assert not (env["tmp"] / "data_runtime").exists()


def test_staging_failure_keeps_current(env):
    w = FakeWrapper(env, exit_code=2)
    state, jm = _deploy(env, w, migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    assert _failed_code(jm) == "ATOMIC_PUBLISH_FAILED"
    assert _current(env) == f"versions/{V0}"
    assert state.deploy_status != DeployStatus.deployed


def test_durability_unknown_is_not_reported_as_success(env):
    w = FakeWrapper(env, exit_code=3)
    state, jm = _deploy(env, w, migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    assert _failed_code(jm) == "ATOMIC_PUBLISH_DURABILITY_UNKNOWN"
    assert state.deploy_status == DeployStatus.failed


def test_initial_migration_without_flag_rejected_before_wrapper(env):
    w = FakeWrapper(env)
    state, jm = _deploy(env, w)
    assert _failed_code(jm) == "FLOOD_ROUTING_MIGRATION_REQUIRED"
    assert w.calls == []  # wrapper を起動しない
    assert _current(env) == f"versions/{V0}"
    assert state.deploy_status == DeployStatus.failed


def test_migration_not_recorded_in_manifest_is_not_success(env):
    w = FakeWrapper(env, record_migration=False)
    state, jm = _deploy(env, w, migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    assert _failed_code(jm) == "ATOMIC_PUBLISH_MIGRATION_NOT_RECORDED"
    assert state.deploy_status == DeployStatus.failed


def test_migration_flag_rejected_after_migration(env):
    # 1 回目: migration 成功（current は routing のみ）
    _deploy(env, FakeWrapper(env), migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    assert aap.legacy_flood_files_in_current() == []
    # 2 回目: 再度 migration 指定 → wrapper 起動前に reject
    w2 = FakeWrapper(env)
    _state2, jm = _deploy(env, w2, migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    assert _failed_code(jm) == "FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE"
    assert w2.calls == []


def test_normal_deploy_after_migration_has_no_flag(env):
    _deploy(env, FakeWrapper(env), migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    w = FakeWrapper(env)
    w2_vid = "20261006T000000Z-deadbeef"
    # 2 回目の publish 用に既存 version を退避（fake の version 名衝突回避）
    shutil.move(str(env["rt"] / "versions" / w2_vid), str(env["rt"] / "versions" / "20261006T000000Z-00000001"))
    os.remove(env["rt"] / "current")
    os.symlink("versions/20261006T000000Z-00000001", env["rt"] / "current")
    state, jm = _deploy(env, w)
    assert _failed_code(jm) is None
    assert "--allow-flood-routing-migration" not in w.calls[0]  # 通常反映では自動付与しない


def test_storm_surge_uses_atomic_wrapper(env):
    # 先に flood migration を済ませた current を用意
    _deploy(env, FakeWrapper(env), migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    shutil.move(str(env["rt"] / "versions/20261006T000000Z-deadbeef"),
                str(env["rt"] / "versions/20261006T000000Z-00000001"))
    os.remove(env["rt"] / "current")
    os.symlink("versions/20261006T000000Z-00000001", env["rt"] / "current")

    surge = _write_fc(env["tmp"] / "data_lake/validated/tokyo/storm_surge/tokyo-surge-001.geojson",
                      rank_key="storm_surge_rank")
    w = FakeWrapper(env, place=(surge, "backend/hazard/storm_surge/tokyo/tokyo-surge-001.geojson"))
    state, jm = _deploy(env, w, defn=_defn("storm_surge", "TOKYO-SURGE-001"), state=_state(surge))
    assert _failed_code(jm) is None
    assert w.calls and w.calls[0][1].endswith("deploy_to_runtime_atomic.sh")
    assert state.current_runtime_path.endswith("backend/hazard/storm_surge/tokyo/tokyo-surge-001.geojson")
    assert "/versions/" in state.current_runtime_path
    assert not (env["tmp"] / "data_runtime").exists()


def test_artifact_missing_in_new_version_is_not_success(env):
    w = FakeWrapper(env, place=(env["routing"], "backend/hazard/flood/tokyo/other.routing.geojson"))
    state, jm = _deploy(env, w, migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    assert _failed_code(jm) == "ATOMIC_PUBLISH_ARTIFACT_MISSING"
    assert state.deploy_status == DeployStatus.failed


def test_non_atomic_hazard_keeps_existing_flat_path(env):
    src = _write_fc(env["tmp"] / "data_lake/validated/tokyo/inland_flood/tokyo-urban-001.geojson")
    state, jm = _deploy(env, _must_not_run_wrapper(), defn=_defn("inland_flood", "TOKYO-URBAN-001"),
                        state=_state(src))
    assert _failed_code(jm) is None
    assert (env["tmp"] / "data_runtime/backend/hazard/inland_flood/tokyo-urban-001.geojson").is_file()


def test_non_hazard_dataset_keeps_existing_flat_path(env):
    src = _write_fc(env["tmp"] / "data_lake/validated/japan/tide/tide.geojson")
    defn = _defn(None, "TIDE-TEST-001", category="tide", runtime_path="data_runtime/backend/tide",
                 validated_storage_path="data_lake/validated/japan/tide")
    with patch("app.services.tide_service.reload", lambda: None):
        state, jm = _deploy(env, _must_not_run_wrapper(), defn=defn, state=_state(src))
    assert _failed_code(jm) is None
    assert (env["tmp"] / "data_runtime/backend/tide/tide.geojson").is_file()


def test_migration_ref_rejected_for_non_atomic_dataset(env):
    src = _write_fc(env["tmp"] / "data_lake/validated/tokyo/inland_flood/x.geojson")
    state, jm = _deploy(env, _must_not_run_wrapper(), defn=_defn("inland_flood", "TOKYO-URBAN-001"),
                        state=_state(src), migration_ref="LOCAL-REF")
    assert _failed_code(jm) == "FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE"


def _must_not_run_wrapper():
    """非 atomic dataset は wrapper を起動しない（起動されたら失敗させる）。"""
    async def _call(cmd, job, jm, timeout=None):
        raise AssertionError(f"wrapper を起動してはいけない: {cmd}")

    return _call


def test_rollback_rejected_for_atomic_dataset(env):
    jm = Mock()
    state = _state(env["canonical"])
    state.backup_path = str(env["routing"])
    asyncio.run(ps.run_rollback(_job(), _defn(), state, jm, Mock()))
    assert _failed_code(jm) == "ROLLBACK_ATOMIC_PUBLISH_MANAGED"


# ── 補助: legacy 判定 / wrapper コマンド / 承認参照 ──────────────────────────────

def test_legacy_detection_and_command(env):
    assert aap.legacy_flood_files_in_current() == ["backend/hazard/flood/tokyo_flood_check.geojsonl"]
    assert aap.build_wrapper_command(Path("/scripts/publish/w.sh"), ["tokyo"], None) == \
        ["bash", "/scripts/publish/w.sh", "--region", "tokyo"]


@pytest.mark.parametrize("ref", [None, "", "  ", "ab", "x" * 201, "bad;rm -rf /", "$(id)"])
def test_owner_approval_ref_validation_rejects(ref):
    with pytest.raises(ValueError):
        aap.validate_owner_approval_ref(ref)


def test_owner_approval_ref_validation_accepts():
    assert aap.validate_owner_approval_ref("  LOCAL-FLOOD-ROUTING-MIGRATION-20261006 ") == \
        "LOCAL-FLOOD-ROUTING-MIGRATION-20261006"


# ── API（deploy_dataset / publish-status）─────────────────────────────────────

def _api_call(env, body=None, defn=None, legacy=True):
    from app.api import admin_datasets as api

    defn = defn or _defn()
    state = _state(env["canonical"])
    state.is_deployable = True
    ds, ss, jm = Mock(), Mock(), Mock()
    ds.get.return_value = defn
    ss.init_from_definition.return_value = state
    jm.has_running_job.return_value = False
    jm.create.return_value = Mock(job_id="job-api")
    if not legacy:
        shutil.rmtree(env["rt"] / "versions" / V0 / "backend/hazard/flood")
    run_deploy = Mock(return_value="coro")
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss), \
         patch.object(api, "get_job_manager", return_value=jm), \
         patch.object(api.pipeline_service, "run_deploy", run_deploy), \
         patch.object(api, "_safe_write_app_log", lambda *_a, **_k: None):
        res = asyncio.run(api.deploy_dataset("TOKYO-RIVER-001", Mock(state=Mock(request_id="r")),
                                             body=body, principal=Mock(actor_id="op")))
    return res, run_deploy


def _code(res):
    return json.loads(res.body)["error_code"] if hasattr(res, "body") else None


def test_api_normal_deploy_rejected_while_migration_required(env):
    res, run = _api_call(env, body=None)
    assert _code(res) == "FLOOD_ROUTING_MIGRATION_REQUIRED"
    run.assert_not_called()


def test_api_migration_requires_owner_approval_ref(env):
    from app.api.admin_datasets import DeployRequest
    res, run = _api_call(env, body=DeployRequest(allow_flood_routing_migration=True))
    assert _code(res) == "FLOOD_ROUTING_MIGRATION_APPROVAL_REQUIRED"
    run.assert_not_called()


def test_api_migration_with_ref_is_accepted_and_passed_through(env):
    from app.api.admin_datasets import DeployRequest
    res, run = _api_call(env, body=DeployRequest(allow_flood_routing_migration=True,
                                                 owner_approval_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006"))
    assert res.accepted is True and "初回移行" in res.message
    assert run.call_args.kwargs["flood_routing_migration_ref"] == "LOCAL-FLOOD-ROUTING-MIGRATION-20261006"


def test_api_migration_rejected_when_already_migrated(env):
    from app.api.admin_datasets import DeployRequest
    res, run = _api_call(env, legacy=False, body=DeployRequest(
        allow_flood_routing_migration=True, owner_approval_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006"))
    assert _code(res) == "FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE"
    run.assert_not_called()


def test_api_normal_deploy_after_migration_has_no_ref(env):
    res, run = _api_call(env, legacy=False, body=None)
    assert res.accepted is True
    assert run.call_args.kwargs["flood_routing_migration_ref"] is None


def test_api_migration_flag_rejected_for_non_flood(env):
    from app.api.admin_datasets import DeployRequest
    res, run = _api_call(env, defn=_defn("storm_surge", "TOKYO-SURGE-001"), body=DeployRequest(
        allow_flood_routing_migration=True, owner_approval_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006"))
    assert _code(res) == "FLOOD_ROUTING_MIGRATION_NOT_APPLICABLE"


def test_api_deploy_request_forbids_unknown_fields():
    from pydantic import ValidationError
    from app.api.admin_datasets import DeployRequest
    with pytest.raises(ValidationError):
        DeployRequest(allow_flood_routing_migration=True, force=True)


def test_api_publish_status_reports_migration_requirement(env):
    from app.api import admin_datasets as api
    ds = Mock()
    ds.get.return_value = _defn()
    with patch.object(api, "get_definition_service", return_value=ds):
        st = asyncio.run(api.get_publish_status("TOKYO-RIVER-001"))
    assert st["publish_mode"] == "atomic"
    assert st["current_version"] == V0
    assert st["flood_routing_migration_required"] is True
    assert st["migration_allowed_for_dataset"] is True
    assert st["legacy_flood_files"] == ["backend/hazard/flood/tokyo_flood_check.geojsonl"]


# ── 10/11. deploy_to_runtime.sh: staging から当該 region の legacy flood を除去 ─────

def _run_purge(runtime_backend: Path, region: str):
    import re
    import subprocess
    src = (ROOT / "scripts/publish/deploy_to_runtime.sh").read_text(encoding="utf-8")
    func = re.search(r"# >>> purge_flood_runtime_for_region\n(.*?)# <<< purge_flood_runtime_for_region",
                     src, re.S).group(1)
    script = ("log_info(){ :; }; log_error(){ echo \"$*\" >&2; }\n" + func
              + f'\npurge_flood_runtime_for_region "{runtime_backend}" "{region}"\n')
    return subprocess.run(["bash", "-c", script], capture_output=True, text=True)


def test_purge_removes_only_target_region_legacy_flood(tmp_path):
    flood = tmp_path / "backend/hazard/flood"
    files = {
        "tokyo_flood_check.geojsonl": True,           # legacy flat（tokyo）→ 削除
        "tokyo-river-001.geojson": True,              # legacy flat canonical（tokyo）→ 削除
        "kanagawa_flood_check.geojsonl": False,       # 別 region → 残す
        "tokyo/tokyo-river-001.geojson": True,        # region dir 内 canonical → 削除
        "tokyo/old.routing.geojson": True,            # region dir は丸ごと置換
        "kanagawa/kanagawa-river-001.routing.geojson": False,
    }
    for rel in files:
        (flood / rel).parent.mkdir(parents=True, exist_ok=True)
        (flood / rel).write_text("x")
    other = tmp_path / "backend/hazard/storm_surge/tokyo/tokyo-surge-001.geojson"
    other.parent.mkdir(parents=True)
    other.write_text("x")

    r = _run_purge(tmp_path / "backend", "tokyo")
    assert r.returncode == 0, r.stderr
    for rel, removed in files.items():
        assert (flood / rel).exists() is (not removed), rel
    assert other.exists()  # 他 hazard type には触れない


@pytest.mark.parametrize("bad", ["", "..", "a/b", "tokyo/.."])
def test_purge_rejects_invalid_region(tmp_path, bad):
    (tmp_path / "backend/hazard/flood").mkdir(parents=True)
    r = _run_purge(tmp_path / "backend", bad)
    assert r.returncode != 0


def test_wrapper_normalizes_staging_owner_group_mode():
    """version 内 artifact の契約（dir 10002:20001 0750 / file 10002:20001 0640）を
    wrapper が staging に適用し、activate_version.py が mode を検証する（Linux 専用のため静的確認）。"""
    src = (ROOT / "scripts/publish/deploy_to_runtime_atomic.sh").read_text(encoding="utf-8")
    assert 'find "${STAGING_DIR}" -type d -exec chmod 0750 {} \;' in src
    assert 'find "${STAGING_DIR}" -type f -exec chmod 0640 {} \;' in src
    assert 'chgrp -R "${STAGING_LEASES_GID}" "${STAGING_DIR}"' in src
    assert 'STAGING_LEASES_GID="${OHG2_LEASES_GID:-20001}"' in src


# ── 5/6. state: flat path を参照しない（PermissionError の再発防止）───────────────

def test_state_ignores_unreadable_flat_path_and_uses_current_version(env, tmp_path):
    """旧 flat copy で記録された current_runtime_path（backend-public から読めない dir）を
    stat せず、current version の artifact から deploy 状態を再推定する。"""
    from app.services.dataset_state_service import DatasetStateService

    # migration 済み current（routing を含む）を用意
    _deploy(env, FakeWrapper(env), migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006")
    flat_dir = tmp_path / "flat" / "data_runtime/backend/hazard/flood"
    flat_dir.mkdir(parents=True)
    flat_file = flat_dir / "tokyo-river-001.routing.geojson"
    flat_file.write_text("{}")
    flat_dir.chmod(0o000)  # backend-public から traverse できない状態を再現
    try:
        defn = _defn(validated_storage_path=str(env["canonical"].parent))
        svc = DatasetStateService(state_dir=tmp_path / "state", history_dir=tmp_path / "history")
        (tmp_path / "state").mkdir(exist_ok=True)
        (tmp_path / "state" / f"{defn.dataset_id}.json").write_text(json.dumps({
            "dataset_id": defn.dataset_id, "deploy_status": "deployed",
            "current_validated_path": str(env["canonical"]), "current_runtime_path": str(flat_file),
        }), encoding="utf-8")
        state = svc.init_from_definition(defn)
    finally:
        flat_dir.chmod(0o755)
    assert state.deploy_status == DeployStatus.deployed
    assert state.current_runtime_path == str(
        env["rt"] / "versions/20261006T000000Z-deadbeef/backend/hazard/flood/tokyo/tokyo-river-001.routing.geojson")


def test_state_flat_deployed_flood_without_current_artifact_is_deployable(env, tmp_path):
    """旧 flat copy の「deployed」は、current version に routing が無ければ deployable に戻す
    （UI 表示と実 runtime の乖離を解消）。"""
    from app.services.dataset_state_service import DatasetStateService

    flat_file = tmp_path / "flat/tokyo-river-001.routing.geojson"
    flat_file.parent.mkdir(parents=True)
    flat_file.write_text("{}")
    defn = _defn(validated_storage_path=str(env["canonical"].parent))
    svc = DatasetStateService(state_dir=tmp_path / "state", history_dir=tmp_path / "history")
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "state" / f"{defn.dataset_id}.json").write_text(json.dumps({
        "dataset_id": defn.dataset_id, "deploy_status": "deployed",
        "current_validated_path": str(env["canonical"]), "current_runtime_path": str(flat_file),
    }), encoding="utf-8")
    state = svc.init_from_definition(defn)
    assert state.deploy_status == DeployStatus.deployable
    assert state.current_runtime_path is None


def test_publish_regions_only_hazard_regions():
    """tide:japan 等の非 hazard mapping の region は publish 対象に含めない
    （含めると deploy_to_runtime.sh が region=japan の data_lake 構成を探して失敗する）。"""
    import importlib
    real = importlib.reload(aap).publish_regions  # env fixture の monkeypatch を受けない実関数
    svc = Mock()
    svc.list_all.return_value = [
        {"layer_type": "flood", "region": "tokyo", "dataset_id": "TOKYO-RIVER-001"},
        {"layer_type": "flood", "region": "kanagawa", "dataset_id": "KANAGAWA-RIVER-001"},
        {"layer_type": "evacuation_shelter", "region": "tokyo", "dataset_id": "TOKYO-SHELTER-001"},
        {"layer_type": "admin_boundary", "region": "chiba", "dataset_id": "CHIBA-BOUNDARY-001"},
        {"layer_type": "tide", "region": "japan", "dataset_id": "TIDE-JMA-JAPAN-2026-001"},
    ]
    with patch("app.services.active_mapping_service.get_active_mapping_service", return_value=svc):
        assert real() == ["kanagawa", "tokyo"]


def test_publish_regions_with_real_registry():
    import importlib
    real = importlib.reload(aap).publish_regions
    path = ROOT / "data_lake/admin/active_mappings.json"
    if not path.exists():
        pytest.skip("local active_mappings.json なし")
    from app.services.active_mapping_service import ActiveMappingService
    with patch("app.services.active_mapping_service.get_active_mapping_service",
               return_value=ActiveMappingService(mappings_path=path)):
        regions = real()
    assert "japan" not in regions
    assert {"tokyo", "kanagawa"} <= set(regions)


def test_tile_build_runs_before_atomic_publish(env):
    """表示 tile は publish 前に data_lake/tiles へ生成し、同じ version に含める。"""
    order = []
    w = FakeWrapper(env)

    async def _wrapper(cmd, job, jm, timeout=None):
        order.append("publish")
        return await w(cmd, job, jm, timeout)

    async def _tile(*_a, **_k):
        order.append("tile_build")

    state = _state(env["canonical"])
    jm = Mock()
    with patch.object(ps, "_run_subprocess", _wrapper), patch.object(ps, "_do_tile_build", _tile):
        asyncio.run(ps.run_deploy(_job(), _defn(requires_tile_build=True), state, jm, Mock(),
                                  flood_routing_migration_ref="LOCAL-FLOOD-ROUTING-MIGRATION-20261006"))
    assert order == ["tile_build", "publish"]
    assert _failed_code(jm) is None

"""
TOKYO-RIVER-001 公式取得元情報の是正（Data Ops Console Phase A）。

repository 内の一次証拠（scripts/download/import_river_flood_manual.py・download_river_flood.sh・
docs/data-setup.md・docs/third-party-inventory.md）:
  - 国土数値情報 A31 の公式配布ページは https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html
  - 配布は HTML フォーム送信経由で、安定した直接 download URL は確認できない（手動 DL → import）
したがって official_source_url（人が開く公式ページ）と source_url（実ダウンロード URL）を分け、
source_url は証拠が無いため null。official_source_url を curl する fetch_official は HTML を
データとして取得するため、このデータセットでは許可しない。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.models.admin_dataset import DatasetState, InputMode  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

KSJ_A31 = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html"
A31 = ["A31a-25_13_10_GML.zip", "A31a-25_13_20_GML.zip", "A31b-25_10_5339_GML.zip", "A31b-25_20_5339_GML.zip"]


def _river():
    return get_definition_service().get("TOKYO-RIVER-001")


def test_01_official_source_url_is_ksj_a31_page():
    d = _river()
    assert d.official_source_url == KSJ_A31
    assert d.source_provider == "国土交通省 国土数値情報" and d.source_dataset_name == "洪水浸水想定区域 A31a/A31b"


def test_01b_official_url_matches_repository_evidence():
    for rel in ("scripts/download/import_river_flood_manual.py", "scripts/download/download_river_flood.sh",
                "docs/data-setup.md", "docs/third-party-inventory.md"):
        assert KSJ_A31 in (ROOT / rel).read_text(encoding="utf-8"), rel


def test_02_disaportal_not_left_as_tokyo_river_source():
    raw = next(x for x in json.loads((ROOT / "data_lake/registry/dataset_definitions.json").read_text(encoding="utf-8"))
               if x["dataset_id"] == "TOKYO-RIVER-001")
    assert "disaportal" not in json.dumps(raw)


def test_03_source_url_not_fabricated():
    d = _river()
    assert d.source_url is None  # 実ダウンロード URL の証拠が無い（フォーム送信配布）


def test_03b_migrated_acquisition_does_not_copy_definition_urls(tmp_path):
    """acquisition record の source_url は job の実取得 URL だけ。定義の URL を流用しない。"""
    import zipfile
    from app.services import acquisition_migration as am
    admin = tmp_path / "admin"
    (admin / "history").mkdir(parents=True)
    (admin / "jobs").mkdir()
    raw = tmp_path / "TOKYO-RIVER-001_bundle_s.zip"
    with zipfile.ZipFile(raw, "w") as zf:
        for n in A31:
            zf.writestr(n, n)
    (admin / "history" / "TOKYO-RIVER-001.jsonl").write_text(json.dumps({
        "operation_type": "ingest", "result": "success", "source_file_name": raw.name, "job_id": "j1",
        "executed_at": "2026-10-05T15:34:55.793531"}) + "\n")
    (admin / "jobs" / "j1.json").write_text(json.dumps({"job_type": "ingest_upload", "fetch_url": None}))
    rec = am.build_migrated_record(_river(), DatasetState(
        dataset_id="TOKYO-RIVER-001", current_raw_path=str(raw), normalize_status="success",
        validation_status="pass"), admin_dir=admin)
    assert rec.acquisition_method.value == "upload"
    assert rec.source_url is None and rec.source_page_url is None and rec.final_url is None
    assert [f.name for f in rec.source_files] == A31  # 7. 原本 4 件


def test_04_05_data_ops_shows_official_url_and_unknown_actual_url(tmp_path):
    from app.services import acquisition_history as ah
    from app.services import data_ops_service as dos
    store = ah.AcquisitionStore(tmp_path / "acq")
    store.add(ah.AcquisitionRecord(dataset_id="TOKYO-RIVER-001", acquisition_method="upload", active=True,
                                   validity="valid", source_files=[ah.SourceFile(name=n) for n in A31]))
    acq = dos.acquisition_section(_river(), store)
    assert acq["official_source_url"] == KSJ_A31 and acq["source_url"] is None
    assert acq["active"]["source_url"] is None and acq["active"]["acquisition_method"] == "upload"
    assert len(acq["active"]["source_files"]) == 4
    js = (ROOT / "operator/frontend-admin/data-ops.js").read_text(encoding="utf-8")
    assert '["公式URL", link(acq.official_source_url)]' in js
    assert '["実取得URL", a && a.source_url ? link(a.source_url) : "—"]' in js  # 公式URLと混同しない


def test_06_08_upload_and_source_group_regression():
    d = _river()
    assert InputMode.upload in d.accepted_input_modes and d.max_browser_upload_mb == 200
    assert d.source_group_mode.value == "all_required" and d.ingest_mode.value == "single_batch"
    assert d.required_source_count == 4 and d.expected_source_files == A31
    from app.services import source_group as sg
    assert sg.evaluate_source_set(d, A31).ok and not sg.evaluate_source_set(d, A31[:3]).ok


def _fetch_official(dataset_id):
    from app.api import admin_datasets as api
    defn = get_definition_service().get(dataset_id)
    ds, ss, jm = Mock(), Mock(), Mock()
    ds.get.return_value = defn
    ss.init_from_definition.return_value = DatasetState(dataset_id=dataset_id)
    jm.has_running_job.return_value = False
    jm.create.return_value = Mock(job_id="job-1")
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss), \
         patch.object(api, "get_job_manager", return_value=jm), \
         patch.object(api.pipeline_service, "run_ingest_fetch_official", Mock(return_value=None)):
        res = asyncio.run(api.fetch_official_dataset(dataset_id, Mock(state=Mock(request_id="r")),
                                                     principal=Mock(actor_id="op")))
    return res, jm


def test_09_fetch_official_rejected_for_tokyo_river():
    d = _river()
    assert InputMode.fetch_official not in d.accepted_input_modes
    res, jm = _fetch_official("TOKYO-RIVER-001")
    assert json.loads(res.body)["error_code"] == "INVALID_INPUT_MODE"
    jm.create.assert_not_called()
    # UI はタブを accepted_input_modes から作る（公式取得タブは出ない）
    js = (ROOT / "operator/frontend-admin/datasets.js").read_text(encoding="utf-8")
    assert "tabsEl.innerHTML = modes.map(" in js


def test_10_other_datasets_keep_fetch_official():
    ds = get_definition_service()
    keep = ["TOKYO-SHELTER-001", "TOKYO-EVAC-001", "ROAD-DRIVING-KANTO-001",
            "TIDE-JMA-JAPAN-2026-001"]
    for did in keep:
        assert InputMode.fetch_official in ds.get(did).accepted_input_modes, did
    res, jm = _fetch_official("TOKYO-SHELTER-001")
    assert res.accepted is True
    jm.create.assert_called_once()


def test_update_modal_shows_official_page_link_safely():
    html = (ROOT / "operator/frontend-admin/datasets.html").read_text(encoding="utf-8")
    js = (ROOT / "operator/frontend-admin/datasets.js").read_text(encoding="utf-8")
    assert 'id="um-official-page"' in html
    assert 'renderSourceUrl(document.getElementById("um-official-page"), defn.official_source_url)' in js

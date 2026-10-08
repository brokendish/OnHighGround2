"""
KANAGAWA-RIVER-001 provenance mismatch（Data Ops Console Phase B）。

確認済み事実: 現 raw KANAGAWA-RIVER-001_bundle_t61diorv.zip の中身は A31a-25_13_10 / A31a-25_13_20
（都道府県コード 13 = 東京）。raw → normalize → canonical → routing meta → current manifest が sha256 で連鎖。

  - 取得履歴が無くても、現在の raw の地域コード照合で PROVENANCE MISMATCH を表示する（validity_source=current_raw_check）
  - active と validity は別軸。修復前は overall ERROR のまま（VALID へ変えない）
  - 更新画面・反映画面で警告（反映は止めない）。atomic publish の範囲内 mismatch を列挙
  - 公式 URL は KSJ A31 配布ページ、実取得 URL は null（推測しない）、fetch_official は不許可
  - 原本構成（patterns / expected files）は未確定のため登録しない
"""
from __future__ import annotations

import asyncio
import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts" / "validate"))

from app.models.admin_dataset import DatasetState, InputMode  # noqa: E402
from app.services import acquisition_history as ah  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from app.services import provenance_validity as pv  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

KSJ_A31 = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html"


def _kanagawa():
    return get_definition_service().get("KANAGAWA-RIVER-001")


def _zip(path: Path, names) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as zf:
        for n in names:
            zf.writestr(n, n)
    return path


def _wrong_raw(tmp_path):
    return _zip(tmp_path / "KANAGAWA-RIVER-001_bundle_t61diorv.zip", ["A31a-25_13_20_GML.zip", "A31a-25_13_10_GML.zip"])


def test_01_expected_region_code_14():
    d = _kanagawa()
    assert d.expected_source_region_code == "14" and d.source_region_code_regex


def test_02_region_13_raw_is_mismatch(tmp_path):
    v, reason, flags = pv.assess_raw_region(_kanagawa(), _wrong_raw(tmp_path))
    assert v == ah.AcquisitionValidity.provenance_mismatch and flags == [pv.REGION_MISMATCH]
    assert "region code 13" in reason and "expects region code 14" in reason
    assert "A31a-25_13_10_GML.zip" in reason and "KANAGAWA-RIVER-001_bundle_t61diorv.zip" in reason


def test_03_correct_region_source_clears_mismatch_condition(tmp_path):
    """修復後の受入条件: 地域コード 14 の原本なら region 照合は通る（ファイル名は fixture 内だけ。registry に登録しない）。"""
    raw = _zip(tmp_path / "fixed_bundle.zip", ["A31a-99_14_10_GML.zip", "A31a-99_14_20_GML.zip", "A31b-99_10_5239_GML.zip"])
    v, reason, flags = pv.assess_raw_region(_kanagawa(), raw)
    assert v == ah.AcquisitionValidity.valid and reason is None and flags == []
    # 地域コードを抽出できない原本だけ（A31b のみ）は判定材料なし
    assert pv.assess_raw_region(_kanagawa(), _zip(tmp_path / "b.zip", ["A31b-99_10_5239_GML.zip"])) is None
    assert pv.assess_raw_region(_kanagawa(), tmp_path / "missing.zip") is None


def test_04_05_official_url_and_no_fabricated_source_url():
    d = _kanagawa()
    assert d.official_source_url == KSJ_A31 and d.source_url is None
    assert d.source_provider == "国土交通省 国土数値情報"
    raw = next(x for x in json.loads((ROOT / "data_lake/registry/dataset_definitions.json").read_text(encoding="utf-8"))
               if x["dataset_id"] == "KANAGAWA-RIVER-001")
    assert "disaportal" not in json.dumps(raw)


def test_source_set_registered_as_owner_approved():
    """2025 年正式 source set（OWNER 承認済み・公式ページで実在確認済みの 10 原本）。"""
    d = _kanagawa()
    assert d.source_group_mode.value == "all_required" and d.ingest_mode.value == "single_batch"
    assert d.required_source_count == 10 and len(d.expected_source_files) == 10
    assert all("_13_" not in p for p in d.source_file_patterns)


def test_06_fetch_official_not_allowed():
    from app.api import admin_datasets as api
    d = _kanagawa()
    assert InputMode.fetch_official not in d.accepted_input_modes and InputMode.upload in d.accepted_input_modes
    ds, ss, jm = Mock(), Mock(), Mock()
    ds.get.return_value = d
    jm.has_running_job.return_value = False
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss), \
         patch.object(api, "get_job_manager", return_value=jm):
        res = asyncio.run(api.fetch_official_dataset(d.dataset_id, Mock(state=Mock(request_id="r")),
                                                     principal=Mock(actor_id="op")))
    assert json.loads(res.body)["error_code"] == "INVALID_INPUT_MODE"
    jm.create.assert_not_called()


def _section(tmp_path, records=(), raw=None):
    store = ah.AcquisitionStore(tmp_path / "acq")
    for r in records:
        store.add(r)
    state = DatasetState(dataset_id="KANAGAWA-RIVER-001", current_raw_path=str(raw) if raw else None)
    return dos.acquisition_section(_kanagawa(), store, state)


def test_mismatch_shown_without_acquisition_history(tmp_path):
    acq = _section(tmp_path, raw=_wrong_raw(tmp_path))
    assert acq["active"] is None
    assert acq["validity"] == "provenance_mismatch" and acq["validity_source"] == "current_raw_check"
    assert acq["validity_flags"] == ["REGION_MISMATCH"] and acq["status"] == dos.ERROR


def test_09_active_with_mismatch_coexist_and_not_promoted(tmp_path):
    rec = ah.AcquisitionRecord(dataset_id="KANAGAWA-RIVER-001", acquisition_method="upload", active=True,
                               validity="valid", source_files=[ah.SourceFile(name="x.zip")])
    acq = _section(tmp_path, [rec], raw=_wrong_raw(tmp_path))
    assert acq["active"]["active"] is True  # active は維持
    assert acq["validity"] == "provenance_mismatch"  # raw 照合の不一致が優先（VALID 表示にしない）
    assert ah.AcquisitionStore(tmp_path / "acq").active("KANAGAWA-RIVER-001").validity == ah.AcquisitionValidity.valid  # 履歴は改変しない


def test_08_overall_error_even_if_runtime_published(tmp_path, monkeypatch):
    monkeypatch.setattr(dos, "_app_properties", lambda: {"hazard.flood.enabled": "true"})
    monkeypatch.setattr(drr, "_default_cache", drr.SourceShaCache(tmp_path / "c.json"))
    view = drr.RuntimeView(root=tmp_path, version_id="V1", files={})
    state = DatasetState(dataset_id="KANAGAWA-RIVER-001", current_raw_path=str(_wrong_raw(tmp_path)))
    row = dos.build_dataset(_kanagawa(), state, view, allow_hash=False, allow_heavy=False,
                            props={"hazard.flood.enabled": "true"}, store=ah.AcquisitionStore(tmp_path / "acq"))
    assert row["integrity"]["components"]["source"]["status"] == dos.ERROR
    assert row["integrity"]["overall"] == dos.ERROR


def test_07_ui_warnings_present():
    js = (ROOT / "operator/frontend-admin/datasets.js").read_text(encoding="utf-8")
    html = (ROOT / "operator/frontend-admin/datasets.html").read_text(encoding="utf-8")
    assert 'id="um-provenance-warning"' in html and 'id="dm-provenance-warning"' in html
    assert "/data-ops/${encodeURIComponent(datasetId)}/provenance" in js
    assert "renderDeployProvenanceWarning(st)" in js
    fn = js[js.index("function renderProvenanceWarning"):js.index("// ── 取得原本セット（source_group_mode）")]
    assert "innerHTML" not in fn and "PROVENANCE MISMATCH" in fn
    # 反映ボタンは provenance で disabled にしない（警告のみ）
    assert "dm-btn-deploy" not in fn
    ops = (ROOT / "operator/frontend-admin/data-ops.js").read_text(encoding="utf-8")
    assert "PROVENANCE MISMATCH" in ops and "REGION MISMATCH" in ops


def test_publish_status_lists_mismatch_in_publish_scope(tmp_path):
    """atomic publish は全 region を積み直すため、TOKYO の反映画面でも KANAGAWA の mismatch を警告する。"""
    from app.api import admin_datasets as api
    defs = get_definition_service()
    tokyo, kanagawa = defs.get("TOKYO-RIVER-001"), defs.get("KANAGAWA-RIVER-001")
    wrong = _wrong_raw(tmp_path)
    ds, ss = Mock(), Mock()
    ds.get.return_value = tokyo
    ds.list_all.return_value = [tokyo, kanagawa]
    ss.init_from_definition.side_effect = lambda d: DatasetState(
        dataset_id=d.dataset_id, current_raw_path=str(wrong) if d.dataset_id == "KANAGAWA-RIVER-001" else None)
    with patch.object(api, "get_definition_service", return_value=ds), \
         patch.object(api, "get_state_service", return_value=ss), \
         patch.object(api.aap, "publish_regions", return_value=["kanagawa", "tokyo"]), \
         patch("app.services.data_ops_service.get_acquisition_store",
               return_value=ah.AcquisitionStore(tmp_path / "acq")):
        out = api._provenance_warnings(tokyo, ss.init_from_definition(tokyo), "atomic")
    assert out["provenance_validity"] == "unknown"  # TOKYO 自体は履歴なし（この fixture では）
    assert [m["dataset_id"] for m in out["provenance_mismatch_in_publish_scope"]] == ["KANAGAWA-RIVER-001"]


def test_10_tokyo_river_regression(tmp_path):
    tokyo = get_definition_service().get("TOKYO-RIVER-001")
    raw = _zip(tmp_path / "TOKYO-RIVER-001_bundle.zip", ["A31a-25_13_10_GML.zip", "A31a-25_13_20_GML.zip",
                                                        "A31b-25_10_5339_GML.zip", "A31b-25_20_5339_GML.zip"])
    assert pv.assess_raw_region(tokyo, raw)[0] == ah.AcquisitionValidity.valid
    assert tokyo.source_group_mode.value == "all_required" and tokyo.official_source_url == KSJ_A31


def test_coverage_checker_reports_bbox_meshes_and_points(tmp_path):
    import check_flood_region_coverage as cov
    def feat(lon, lat):
        d = 0.001
        return {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon", "coordinates": [[
            [lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]]}}
    gj = tmp_path / "f.geojson"
    gj.write_text(json.dumps({"type": "FeatureCollection", "features": [feat(139.70, 35.53), feat(139.64, 35.44)]}))
    bnd = tmp_path / "b.geojson"
    bnd.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {},
        "geometry": {"type": "Polygon", "coordinates": [[[138.92, 35.13], [139.84, 35.13], [139.84, 35.67],
                                                          [138.92, 35.67], [138.92, 35.13]]]}}]}))
    out = cov.check(gj, bnd, cov.PRESETS["kanagawa"], 3.0)
    assert out["feature_count"] == 2 and out["boundary_meshes"] == ["5238", "5239", "5338", "5339"]
    assert out["points"]["川崎"]["features_within_radius"] == 1 and out["points"]["横浜"]["features_within_radius"] == 1
    assert set(out["points_without_coverage"]) == {"藤沢", "鎌倉", "平塚", "小田原"}
    assert cov.mesh1(35.53, 139.70) == "5339" and cov.mesh1(35.26, 139.15) == "5239"
    acc = cov.check(gj, bnd, cov.PRESETS["kanagawa"], 3.0, require_meshes=["5238", "5239", "5338", "5339"])["acceptance"]
    assert acc["pass"] is False and acc["meshes_without_features_inside_boundary"] == ["5238", "5239", "5338"]

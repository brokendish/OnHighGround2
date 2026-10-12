"""
DATA-OPS-WARNING-INVENTORY（2026-10-12）: Data Ops の WARNING を棚卸しし、事実で確定できた出典だけを登録する。

  - KSJ 9 件（A49 / A51 / A33 / G08 / N03）: 公式 zip と raw の sha256 一致、canonical は raw の再正規化と一致
  - KANAGAWA の避難所 2 件: 国土地理院の公式定義（_1 = 指定避難所、_2 = 指定緊急避難場所）と CSV 列・共通 ID で確認。
    KANAGAWA-EVAC-001 の raw の記録（14000_2.zip）が誤りで、canonical は 14000_1.zip と全件一致
  - 東京の避難所 2 件: layer_type / 名称と中身が逆（OWNER 判断）。出典は登録しない
  - 出典を確定できないもの（DEM / TOKYO-BOUNDARY / ROAD / TIDE / RAILWAY / PSEUDO）は推測で埋めない
  - Data Ops の判定は変えず、WARNING の中身を示すラベル（integrity.labels）を加える
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.models.admin_dataset import DatasetState, StorageStatus, ValidationStatus  # noqa: E402
from app.services import build_provenance as bp  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from app.services import runtime_provenance as rp  # noqa: E402
from app.services import source_group as sg  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

KSJ = {  # dataset → (file, year, version, region code, official zip sha256)
    "TOKYO-SURGE-001": ("A49-20_13_GML.zip", "2020", "1.0", "13", "cec46df37c0d8cabc660fc85f8ec6f0cac78b6754a5387f7be21b7a599810390"),
    "KANAGAWA-SURGE-001": ("A49-24_14_GML.zip", "2024", None, "14", "aef39816fa3dc6e473cf70f3153f1b60b7adb0aec7ec36696a97afab19bfdc00"),
    "TOKYO-URBAN-001": ("A51-24_13_GML.zip", "2024", None, "13", "8c82c0b438f9da0b52bd64fdd889d24d0fb924a68ac3da14822b40c5d8a7d0b7"),
    "KANAGAWA-URBAN-001": ("A51-24_14_GML.zip", "2024", None, "14", "a648ba89ab5aaab431155a7e414c2a811e50c6c29da7ff78a984cbc2ff4be935"),
    "TOKYO-LANDSLIDE-001": ("A33-24_13_GML.zip", "2024", "1.0", "13", "bf02d48cd4dad6e429d7f1cc86388cd7c78c593a7e15bd287dd70b0169998789"),
    "KANAGAWA-LANDSLIDE-001": ("A33-24_14_GML.zip", "2024", "1.0", "14", "35c10f5dadadea095ab5ac3604100ffc3b901b3b9a579c77049ba5c453bfd497"),
    "TOKYO-LOWLAND-POOR-DRAINAGE-001": ("G08-15_13_GML.zip", "2015", "1.0", "13", "c1cce92038905c556042fe94a8feff3cbf3092eb9a6cdda032a7f0e1258a80bb"),
    "KANAGAWA-LOWLAND-POOR-DRAINAGE-001": ("G08-15_14_GML.zip", "2015", "1.0", "14", "57af4b08db9fe3eca4a343601a538431b02a5617964b3a1e74a545e5b434a664"),
    "KANAGAWA-BOUNDARY-001": ("N03-20250101_14_GML.zip", "2025", None, "14", "1cf3c1ee08686de1e2685e5f81b9f0eaf6abb94bfffcd0811cc109c84b2e9fb4"),
}
UNRESOLVED = ["TOKYO-DEM-001", "TOKYO-BOUNDARY-001", "ROAD-DRIVING-KANTO-001", "ROAD-WALKING-TOKYO-KANAGAWA-001",
              "TIDE-JMA-JAPAN-2026-001", "RAILWAY-PMTILES-JAPAN-001", "TOKYO-PSEUDO-INLAND-FLOOD-001",
              "TOKYO-SHELTER-001", "TOKYO-EVAC-001"]
TILE_OMITTED = ["TOKYO-SURGE-001", "KANAGAWA-SURGE-001", "TOKYO-URBAN-001", "KANAGAWA-URBAN-001",
                "TOKYO-LOWLAND-POOR-DRAINAGE-001", "KANAGAWA-LOWLAND-POOR-DRAINAGE-001", "TOKYO-PSEUDO-INLAND-FLOOD-001"]


def _d(did):
    return get_definition_service().get(did)


# ── 出典（registry）──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("did", sorted(KSJ))
def test_ksj_source_provenance(did):
    f, year, version, code, sha = KSJ[did]
    d = _d(did)
    assert d.source_provider == "国土交通省 国土数値情報"
    assert d.official_source_url.startswith("https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-")
    assert d.source_url.endswith("/" + f) and (d.source_year, d.source_version) == (year, version)
    assert d.expected_source_files == [f] and d.source_file_patterns == [f] and d.expected_source_region_code == code
    assert any(sha in n for n in d.ingest_notes) and any("canonical" in n and "一致" in n for n in d.ingest_notes)
    assert sg.evaluate_source_set(d, [f]).ok and sg.definition_problems(d) == []
    other = f.replace("_13_", "_14_") if "_13_" in f else f.replace("_14_", "_13_")
    assert not sg.evaluate_source_set(d, [other]).ok  # 別都道府県の原本は取り込めない


def test_lowland_official_page_is_the_existing_one():
    for did in ("TOKYO-LOWLAND-POOR-DRAINAGE-001", "KANAGAWA-LOWLAND-POOR-DRAINAGE-001"):
        assert _d(did).official_source_url.endswith("KsjTmplt-G08-2015.html")  # 旧 KsjTmplt-G08.html は 404


def test_kanagawa_shelter_pair_follows_gsi_definition():
    shelter, evac = _d("KANAGAWA-SHELTER-001"), _d("KANAGAWA-EVAC-001")
    assert shelter.layer_type == "emergency_shelter" and shelter.expected_source_files == ["14000_2.zip"]
    assert evac.layer_type == "evacuation_shelter" and evac.expected_source_files == ["14000_1.zip"]
    assert shelter.source_provider == evac.source_provider == "国土地理院"
    assert any("14000_2.zip" in n and "誤っていたのは raw の記録" in n for n in evac.ingest_notes)


def test_tokyo_shelter_pair_mismatch_is_recorded_not_resolved():
    for did in ("TOKYO-SHELTER-001", "TOKYO-EVAC-001"):
        d = _d(did)
        assert d.source_provider is None  # 定義と中身が逆のまま出典を「正しい」と登録しない
        assert any(n.startswith("要確認（2026-10-12）") and "OWNER 判断" in n for n in d.ingest_notes)


@pytest.mark.parametrize("did", UNRESOLVED)
def test_unresolved_sources_are_not_guessed(did):
    d = _d(did)
    assert d.source_provider is None and d.source_dataset_name is None


# ── Data Ops のラベル（判定は変えない）──────────────────────────────────────────────

def _labels(acq=None, rt=None, comps=None, defn=None):
    acq = {"provenance_missing": [], "acquisition_history": "PRESENT", "validity": "valid", **(acq or {})}
    comps = comps or {"source": {"status": dos.OK}}
    defn = defn or _d("KANAGAWA-RIVER-001")
    return {l["label"]: l["severity"] for l in dos.integrity_labels(acq, rt or {"status": rp.VERIFIED}, comps, defn)}


def test_label_node_absence_is_info_not_warning():
    labels = _labels(acq={"acquisition_history": "NOT PRESENT ON THIS NODE"})
    assert labels == {"ACQUISITION_NOT_PRESENT_ON_THIS_NODE": "INFO"}


def test_label_source_provenance_missing():
    labels = _labels(acq={"provenance_missing": ["取得元組織（source_provider）", "採用中の取得履歴（acquisition history）"],
                          "acquisition_history": "ABSENT", "validity": "unknown"})
    assert labels == {"SOURCE_PROVENANCE_MISSING": dos.WARNING, "ACQUISITION_HISTORY_MISSING": dos.WARNING}


@pytest.mark.parametrize("validity,label,sev", [("provenance_mismatch", "PROVENANCE_MISMATCH", dos.ERROR),
                                                 ("provenance_suspect", "PROVENANCE_SUSPECT", dos.WARNING),
                                                 ("unknown", "PROVENANCE_UNKNOWN", dos.WARNING)])
def test_label_validity(validity, label, sev):
    assert _labels(acq={"validity": validity})[label] == sev


@pytest.mark.parametrize("status,label,sev", [(rp.MISMATCH, "RUNTIME_PROVENANCE_MISMATCH", dos.ERROR),
                                               (rp.INVALID, "RUNTIME_PROVENANCE_MISMATCH", dos.ERROR),
                                               (rp.ABSENT, "RUNTIME_PROVENANCE_UNKNOWN", dos.WARNING)])
def test_label_runtime_provenance(status, label, sev):
    assert _labels(rt={"status": status})[label] == sev


def test_label_observability_legacy_and_tile_note():
    labels = _labels(rt={"status": rp.VERIFIED, "record": {"tile_note": "x"}},
                     comps={"backend": {"status": dos.UNOBSERVED}}, defn=_d("TOKYO-TSUNAMI-001"))
    assert labels == {"TILE_NOT_IN_RUNTIME_RECORD": "INFO", "OBSERVABILITY_LIMITED": "INFO", "LEGACY_HISTORY": "INFO"}


# ── tile を含めない runtime provenance record ─────────────────────────────────────

class _NoStore:
    def active(self, _):
        return None

    def list(self, _):
        return []


def test_record_without_tile_does_not_claim_tile(tmp_path):
    lake = tmp_path / "data_lake"
    canon = lake / "validated/tokyo/storm_surge/tokyo-surge-001.geojson"
    canon.parent.mkdir(parents=True)
    canon.write_text(json.dumps({"type": "FeatureCollection", "features": []}))
    tile = lake / "tiles/tokyo/storm_surge/tokyo_surge_001.mbtiles"
    tile.parent.mkdir(parents=True)
    tile.write_bytes(b"tile")
    state = DatasetState(dataset_id="TOKYO-SURGE-001", storage_status=StorageStatus.stored,
                         current_validated_path=str(canon), validation_status=ValidationStatus.passed)
    full = bp.generate(_d("TOKYO-SURGE-001"), state, store=_NoStore(), cache=drr.SourceShaCache(None), data_lake=lake)
    assert full["tile"]["sha256"]
    rec = bp.generate(_d("TOKYO-SURGE-001"), state, store=_NoStore(), cache=drr.SourceShaCache(None), data_lake=lake,
                      without_tile_reason="runtime node で別 build")
    assert rec["tile"] is None and rec["tile_note"] == "runtime node で別 build"
    assert rec["runtime_artifact"] == full["runtime_artifact"] and rec["canonical"] == full["canonical"]


def test_verify_without_tile_checks_runtime_only():
    import hashlib
    from types import SimpleNamespace
    body = json.dumps({"schema": rp.SCHEMA, "dataset_id": "X", "runtime_artifact": {"rel": "r", "sha256": "a" * 64},
                       "canonical": {"sha256": "a" * 64}, "tile": None, "tile_note": "n"}).encode()
    view = SimpleNamespace(version_id="v", files={"r": "a" * 64, rp.runtime_rel("X"): hashlib.sha256(body).hexdigest()},
                           version_path=lambda rel: SimpleNamespace(read_bytes=lambda: body))
    out = rp.verify_runtime(view, "X", "r")
    assert out["status"] == rp.VERIFIED and [c["check"] for c in out["checks"]] == ["runtime_artifact.sha256"]


@pytest.mark.parametrize("did", TILE_OMITTED)
def test_build_node_records_omit_runtime_node_tiles(did):
    d = _d(did)
    p = rp.build_path(ROOT / "data_lake", d.region, d.layer_type, did)
    if not p.is_file():
        pytest.skip("build node の record が無い環境（data_lake は gitignore）")
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert rec["tile"] is None and "runtime node" in rec["tile_note"]
    assert rec["runtime_artifact"]["sha256"] == rec["canonical"]["sha256"]
    if did != "TOKYO-PSEUDO-INLAND-FLOOD-001":
        assert rec["source"]["validity"] == "valid"

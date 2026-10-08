"""
flood publish の artifact_record 検証方式（canonical 本体なしで routing の出自を検証）。

canonical_file（既定・従来）: sha256(canonical) == meta.source_canonical_sha256 を照合。
artifact_record: build node（trusted）の provenance record を根拠に
  record.canonical.sha256 == meta.source_canonical_sha256
  record.runtime_artifact.sha256 == meta.routing_artifact_sha256 == sha256(routing 実体)
  件数・dataset / region・routing validation（FN=0）
の連鎖を照合する。欠落・不一致は fail-closed。canonical が無いことを理由に skip しない。
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

from app.services import runtime_provenance as rp  # noqa: E402
from app.services.flood_routing_contract import (  # noqa: E402
    BUILDER_NAME, CONTRACT_VERSION, FloodRoutingContractError, verify_routing_with_record,
)
from test_resolve_hazard_sources import _base_defn, _run_resolver, mod  # noqa: E402

DS = "KANAGAWA-RIVER-001"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class Lake:
    """runtime node の data_lake（canonical 本体なし）を再現する。"""

    def __init__(self, tmp: Path, with_canonical=False):
        self.root = tmp / "data_lake"
        self.validated_dir = self.root / "validated/kanagawa/flood"
        self.validated_dir.mkdir(parents=True)
        self.canonical = self.validated_dir / "kanagawa-river-001.geojson"
        if with_canonical:
            self.canonical.write_bytes(b"CANONICAL")
        der = self.root / "derived/kanagawa/flood"
        der.mkdir(parents=True)
        self.routing = der / "kanagawa-river-001.routing.geojson"
        self.routing.write_bytes(b"ROUTING")
        self.meta_path = der / "kanagawa-river-001.routing.meta.json"
        self.meta = {"contract": CONTRACT_VERSION, "dataset_id": DS, "source_canonical_path": str(self.canonical),
                     "source_canonical_sha256": _sha(b"CANONICAL"), "routing_artifact_sha256": _sha(b"ROUTING"),
                     "builder_name": BUILDER_NAME, "builder_version": "1", "tau": 0.85, "min_split_size": 0,
                     "feature_count": 7, "source_feature_count": 9, "generated_at": "2026-10-08T00:00:00Z"}
        self.write_meta()
        self.record = {
            "schema": rp.SCHEMA, "dataset_id": DS, "layer_type": "flood", "region": "kanagawa",
            "source": {"acquisition_id": "a1", "validity": "valid", "source_files": []},
            "canonical": {"sha256": _sha(b"CANONICAL"), "feature_count": 9},
            "runtime_artifact": {"rel": "backend/hazard/flood/kanagawa/kanagawa-river-001.routing.geojson",
                                 "sha256": _sha(b"ROUTING"), "feature_count": 7},
            "tile": None, "validation": {"canonical_validation_status": "pass", "routing_coverage_false_negatives": 0},
        }

    def write_meta(self):
        self.meta_path.write_text(json.dumps(self.meta))

    def write_record(self, record=None):
        rp.write_record(rp.build_path(self.root, "kanagawa", "flood", DS), record or self.record)

    def verify(self, record="default"):
        rec = self.record if record == "default" else record
        return verify_routing_with_record(self.canonical, DS, "kanagawa", rec)


@pytest.fixture
def lake(tmp_path):
    return Lake(tmp_path)


def test_valid_record_passes_without_canonical(lake):
    assert not lake.canonical.exists()
    routing, meta = lake.verify()
    assert routing == lake.routing and meta["feature_count"] == 7


def test_routing_one_byte_tamper_fails(lake):
    lake.routing.write_bytes(b"ROUTINF")
    with pytest.raises(FloodRoutingContractError, match="routing artifact sha256"):
        lake.verify()


def test_meta_canonical_sha_tamper_fails(lake):
    lake.meta["source_canonical_sha256"] = "0" * 64
    lake.write_meta()
    with pytest.raises(FloodRoutingContractError, match="canonical sha256"):
        lake.verify()


@pytest.mark.parametrize("path,value,match", [
    (("canonical", "sha256"), "1" * 64, "canonical sha256"),
    (("runtime_artifact", "sha256"), "2" * 64, "routing sha256"),
    (("runtime_artifact", "feature_count"), 8, "feature_count"),
    (("canonical", "feature_count"), 10, "canonical feature_count"),
    (("validation", "routing_coverage_false_negatives"), 3, "routing validation"),
    (("validation", "routing_coverage_false_negatives"), None, "routing validation"),
    (("runtime_artifact", "rel"), "backend/hazard/flood/tokyo/kanagawa-river-001.routing.geojson", "runtime_artifact.rel"),
])
def test_record_tamper_fails(lake, path, value, match):
    rec = copy.deepcopy(lake.record)
    rec[path[0]][path[1]] = value
    with pytest.raises(FloodRoutingContractError, match=match):
        lake.verify(rec)


@pytest.mark.parametrize("field,value", [("dataset_id", "TOKYO-RIVER-001"), ("region", "tokyo"),
                                         ("layer_type", "inland_flood"), ("schema", "bogus")])
def test_dataset_or_scope_mismatch_fails(lake, field, value):
    rec = dict(lake.record, **{field: value})
    with pytest.raises(FloodRoutingContractError):
        lake.verify(rec)


def test_missing_record_fails_closed(lake):
    with pytest.raises(FloodRoutingContractError, match="provenance record がありません"):
        lake.verify(None)


def test_missing_routing_or_meta_fails(lake):
    lake.meta_path.unlink()
    with pytest.raises(FloodRoutingContractError):
        lake.verify()


def test_canonical_present_is_also_checked(tmp_path):
    lake = Lake(tmp_path, with_canonical=True)
    assert lake.verify()[0] == lake.routing
    lake.canonical.write_bytes(b"CANONICAL-CHANGED")  # この node の canonical が record と違えば拒否（skip しない）
    with pytest.raises(FloodRoutingContractError, match="この node の canonical"):
        lake.verify()


# ── resolver（publish の実経路）──────────────────────────────────────────────────

def _defs(lake, mode):
    extra = {"publish_verification_mode": mode} if mode else {}
    return [_base_defn(dataset_id=DS, layer_type="flood", region="kanagawa",
                       validated_storage_path=str(lake.validated_dir),
                       runtime_path="data_runtime/backend/hazard/flood", **extra)]


def _resolve(tmp_path, lake, mode):
    with patch.object(mod, "_data_lake_root", return_value=lake.root):
        return _run_resolver(tmp_path, "kanagawa", ["flood"], {f"flood:kanagawa": DS}, _defs(lake, mode))


def test_resolver_artifact_record_publishes_routing_without_canonical(tmp_path, lake, capsys):
    lake.write_record()
    assert _resolve(tmp_path, lake, "artifact_record") == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == [f"flood\t{DS}\t{lake.routing}"]


def test_resolver_artifact_record_without_record_fails_closed(tmp_path, lake, capsys):
    assert _resolve(tmp_path, lake, "artifact_record") == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "provenance record がありません" in captured.err


def test_resolver_legacy_canonical_mode_requires_canonical(tmp_path, lake, capsys):
    """既定（canonical_file）は従来どおり: canonical 本体が無ければ解決できず fail-closed。"""
    lake.write_record()
    assert _resolve(tmp_path, lake, None) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "canonical が単一 file ではありません" in captured.err


def test_resolver_legacy_canonical_mode_passes_with_canonical(tmp_path, capsys):
    lake = Lake(tmp_path, with_canonical=True)
    assert _resolve(tmp_path, lake, None) == 0
    assert capsys.readouterr().out.strip() == f"flood\t{DS}\t{lake.routing}"


ARTIFACT_RECORD_DATASETS = {"TOKYO-RIVER-001", "KANAGAWA-RIVER-001"}


def test_registry_modes_are_pinned():
    """artifact_record は OWNER 承認済みの2件だけ。その他は未設定（= canonical_file）のまま（一括変更しない）。"""
    from app.services.dataset_definition_service import get_definition_service
    defs = get_definition_service().list_all()
    got = {d.dataset_id for d in defs if d.publish_verification_mode == "artifact_record"}
    assert got == ARTIFACT_RECORD_DATASETS
    for d in defs:
        if d.dataset_id not in ARTIFACT_RECORD_DATASETS:
            assert d.publish_verification_mode is None, d.dataset_id


def _defn_dict(**kw):
    from app.services.dataset_definition_service import get_definition_service
    return dict(get_definition_service().get(DS).model_dump(), **kw)


def test_unknown_mode_is_rejected():
    from pydantic import ValidationError
    from app.models.admin_dataset import DatasetDefinition
    with pytest.raises(ValidationError):
        DatasetDefinition(**_defn_dict(publish_verification_mode="skip"))


def test_artifact_record_on_non_flood_is_rejected():
    from pydantic import ValidationError
    from app.models.admin_dataset import DatasetDefinition
    with pytest.raises(ValidationError, match="flood 専用"):
        DatasetDefinition(**_defn_dict(layer_type="inland_flood", publish_verification_mode="artifact_record"))
    assert DatasetDefinition(**_defn_dict(layer_type="inland_flood", publish_verification_mode=None))


# ── runtime node（Data Ops / reconcile / rollback）─────────────────────────────────

from app.services import build_provenance as bp  # noqa: E402
from app.services import data_ops_service as dos  # noqa: E402
from app.services import dataset_runtime_reconcile as drr  # noqa: E402
from test_runtime_provenance import World  # noqa: E402


@pytest.fixture
def node(tmp_path, monkeypatch):
    """artifact_record 方式の runtime node: canonical 本体なし・routing/meta/tile/record のみ。"""
    world = World(tmp_path)
    monkeypatch.setattr(drr, "_default_cache", world.cache)
    monkeypatch.setattr(dos, "_tile_cache", dos.TileInfoCache(tmp_path / "tile.json"))
    monkeypatch.setattr(bp, "_data_lake_root", lambda: world.lake)
    world.acquire()
    rec = world.build_record()
    rec["validation"]["routing_coverage_false_negatives"] = 0  # build node の routing validation 結果
    world.record = rec
    rp.write_record(rp.build_path(world.lake, "kanagawa", "flood", DS), rec)
    world.canonical.unlink()
    world.defn = world.defn.model_copy(update={"publish_verification_mode": "artifact_record"})
    return world


def _staged(rec, method):
    return dict(rec, publish_verification={"method": method, "staged_at": "2026-10-08T00:00:00+00:00"})


def test_runtime_node_artifact_mode_is_published_and_verified(node):
    node.publish("V2", record=_staged(node.record, "artifact_record"))
    r = node.row()
    assert r["runtime"]["runtime_status"] == "published"
    assert r["runtime_provenance"]["status"] == rp.VERIFIED
    assert r["runtime_provenance"]["record"]["publish_verification"]["method"] == "artifact_record"
    comps = r["integrity"]["components"]
    assert comps["canonical"]["status"] == dos.NOT_APPLICABLE
    assert comps["derived"]["status"] == dos.OK


def test_runtime_node_artifact_mode_tampered_meta_is_error(node):
    meta_path = node.lake / "derived/kanagawa/flood/kanagawa-river-001.routing.meta.json"
    meta = json.loads(meta_path.read_text())
    meta["source_canonical_sha256"] = "0" * 64
    meta_path.write_text(json.dumps(meta))
    node.publish("V2", record=_staged(node.record, "artifact_record"))
    r = node.row()
    assert r["integrity"]["components"]["derived"]["status"] == dos.ERROR
    assert r["integrity"]["overall"] == dos.ERROR


def test_runtime_node_artifact_mode_without_record_is_not_ok(node):
    rp.build_path(node.lake, "kanagawa", "flood", DS).unlink()
    node.publish("V2", record=_staged(node.record, "artifact_record"))
    r = node.row()
    assert r["integrity"]["components"]["derived"]["status"] == dos.ERROR
    assert r["runtime"]["runtime_status"] != "published" or r["integrity"]["overall"] != dos.OK


def test_runtime_node_canonical_file_mode_without_canonical_is_not_ok(node):
    """artifact_record を宣言していない dataset は従来どおり canonical 欠落を OK 扱いしない。"""
    node.defn = node.defn.model_copy(update={"publish_verification_mode": None})
    node.publish("V2", record=_staged(node.record, "canonical_file"))
    assert node.row()["integrity"]["overall"] != dos.OK


def test_rollback_keeps_each_versions_verification_method(node):
    node.publish("V1", record=_staged(node.record, "canonical_file"))
    node.publish("V2", record=_staged(node.record, "artifact_record"))
    assert node.row()["runtime_provenance"]["record"]["publish_verification"]["method"] == "artifact_record"
    node.switch("V1")
    r = node.row()
    assert r["runtime_provenance"]["version"] == "V1"
    assert r["runtime_provenance"]["record"]["publish_verification"]["method"] == "canonical_file"
    assert r["runtime_provenance"]["status"] == rp.VERIFIED

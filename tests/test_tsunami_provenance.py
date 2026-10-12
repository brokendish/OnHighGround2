"""
TSUNAMI-PROVENANCE（2026-10-11）: TOKYO / KANAGAWA / CHIBA tsunami を source → canonical → runtime → tile まで
Data Ops で説明できるようにする。

  source   : KSJ A40（公式 zip の sha256 と raw が一致、KS-META・掲載表で年 / 版を確認）
  canonical: TOKYO d952540d…（旧 a93df109… は superseded_canonicals）、KANAGAWA f3890b67…（raw の再正規化と
             バイト一致）、CHIBA 1dad9f90…
  runtime  : publish_mode="registry"（validated canonical をそのまま配置）。反映元 sha256 と照合し、
             runtime provenance record（build node 生成）を version に同梱して manifest と照合する
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

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
from test_dataset_runtime_reconcile import Env, _sha  # noqa: E402


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


rts = _load("resolve_tsunami_source", "scripts/publish/resolve_tsunami_source.py")
nt = _load("normalize_tsunami", "scripts/normalize/normalize_tsunami.py")

TOKYO_OLD = "a93df109980375e36ada56072afa2c3aeca50ca112be076086c06d1a71e49d54"
TOKYO_NEW = "d952540d2ca161a3108cf01028a6c62bf040bfecd267a5c2436a6c63194c4c6e"
KSJ_PAGE = "https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A40-2024.html"
SOURCES = {  # dataset → (zip, year, version, region code, official zip sha256)
    "TOKYO-TSUNAMI-001": ("A40-23_13_GML.zip", "2023", None, "13",
                          "b8e24973e5f9b885d481c28211f107587d14597cb3d9674d26c1aa591dacdc5c"),
    "KANAGAWA-TSUNAMI-001": ("A40-20_14_GML.zip", "2020", "1.0", "14",
                             "6b3192e4ed4f8f28d057e4738ecc0d2e7bef232d6adc3022f2d6aec8375f7479"),
    "CHIBA-TSUNAMI-001": ("A40-18_12_GML.zip", "2018", "1.0", "12",
                          "becf21ab28d686cef622e3b26cf56b6782c6fb868dc0ca98d38e7bdb6875689b"),
}


def _defn(did):
    return get_definition_service().get(did)


def _file_sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


# ── 1. source provenance（定義）──────────────────────────────────────────────────

@pytest.mark.parametrize("did", sorted(SOURCES))
def test_source_provenance_is_registered(did):
    zipname, year, version, code, sha = SOURCES[did]
    d = _defn(did)
    assert d.source_provider == "国土交通省 国土数値情報" and d.official_source_url == KSJ_PAGE
    assert d.source_url.endswith("/" + zipname) and d.source_url.startswith("https://nlftp.mlit.go.jp/ksj/gml/data/A40/")
    assert (d.source_year, d.source_version, d.expected_source_region_code) == (year, version, code)
    assert d.expected_source_files == [zipname] and d.required_source_count == 1
    assert sg.evaluate_source_set(d, [zipname]).ok
    assert sg.definition_problems(d) == []
    raw = ROOT / d.raw_storage_path / zipname
    if raw.is_file():  # data_lake は gitignore
        assert _file_sha(raw) == sha
    if did != "CHIBA-TSUNAMI-001":
        assert any(sha in n for n in d.ingest_notes)  # 公式 zip の sha256 を記録


def test_tokyo_version_is_not_guessed():
    # KS-META に data の版は無い（3.2.1 は GML 配布形式の版）。推測で埋めない
    assert _defn("TOKYO-TSUNAMI-001").source_version is None


def test_kanagawa_a40_16_is_not_current_source():
    d = _defn("KANAGAWA-TSUNAMI-001")
    assert not sg.evaluate_source_set(d, ["A40-16_14_GML.zip"]).ok
    assert any("A40-16_14" in n and "current source として扱わない" in n for n in d.ingest_notes)
    disp = {x["rel_path"]: x for x in json.loads((ROOT / "data_lake/registry/tile_dispositions.json").read_text())}
    assert disp["frontend/tiles/tokyo/tsunami/kanagawa_tsunami_A40-16_14.mbtiles"]["disposition"] == "RETIRED"


def test_old_tokyo_canonical_is_recorded_as_superseded():
    d = _defn("TOKYO-TSUNAMI-001")
    [old] = d.superseded_canonicals
    assert (old["sha256"], old["status"], old["superseded_by"]) == (TOKYO_OLD, "SUPERSEDED", TOKYO_NEW)
    assert old["backup"] and "5.0" in old["reason"]
    assert drr.superseded_shas(d) == {TOKYO_OLD: old}
    for did in ("KANAGAWA-TSUNAMI-001", "CHIBA-TSUNAMI-001"):
        assert _defn(did).superseded_canonicals == []


# ── 2. record 生成（build node）──────────────────────────────────────────────────

def _fc(n=3, did="TOKYO-TSUNAMI-001", depth_text="0.5m以上 ～ 1m未満", depth=None):
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"dataset_id": did, "depth_text": depth_text,
                                           "depth": nt._extract_depth_value(depth_text) if depth is None else depth},
         "geometry": {"type": "Polygon", "coordinates": [[[139.8 + i, 35.0], [139.81 + i, 35.0], [139.81 + i, 35.01],
                                                          [139.8 + i, 35.0]]]}} for i in range(n)]}).encode()


def _lake(tmp_path, content: bytes, did="TOKYO-TSUNAMI-001", region="tokyo"):
    lake = tmp_path / "data_lake"
    canon = lake / "validated" / region / "tsunami" / f"{did.lower()}.geojson"
    canon.parent.mkdir(parents=True)
    canon.write_bytes(content)
    d = _defn(did)
    tile = lake / "tiles" / region / "tsunami" / Path(dos.tile_rel(d)).name
    tile.parent.mkdir(parents=True)
    tile.write_bytes(b"tile")
    state = DatasetState(dataset_id=did, storage_status=StorageStatus.stored, current_validated_path=str(canon),
                         validation_status=ValidationStatus.passed)
    return lake, canon, d, state


class _NoStore:
    def active(self, _):
        return None

    def list(self, _):
        return []


def test_record_describes_validated_copy_with_tile(tmp_path):
    lake, canon, d, state = _lake(tmp_path, _fc())
    rec = bp.generate(d, state, store=_NoStore(), cache=drr.SourceShaCache(None), data_lake=lake)
    sha = _sha(canon.read_bytes())
    assert rec["canonical"] == {"sha256": sha, "feature_count": 3}
    assert rec["runtime_artifact"] == {"rel": "backend/hazard/tsunami/tsunami_tokyo.geojson", "sha256": sha, "feature_count": 3}
    assert rec["tile"]["rel"] == dos.tile_rel(d) and rec["tile"]["sha256"] == _sha(b"tile")
    assert rec["validation"]["registry_canonical_check"] == "passed"


def test_record_refuses_superseded_canonical(tmp_path, monkeypatch):
    lake, canon, d, state = _lake(tmp_path, _fc())
    d = d.model_copy(update={"superseded_canonicals": [{"sha256": _sha(canon.read_bytes()), "status": "SUPERSEDED"}]})
    with pytest.raises(ValueError, match="置き換え済み"):
        bp.generate(d, state, store=_NoStore(), cache=drr.SourceShaCache(None), data_lake=lake)


@pytest.mark.parametrize("content,match", [(_fc(did="CHIBA-TSUNAMI-001"), "region 不一致"),
                                           (_fc(depth=5.0), "再生成")])
def test_record_refuses_canonical_failing_publish_checks(tmp_path, content, match):
    lake, canon, d, state = _lake(tmp_path, content)
    with pytest.raises(ValueError, match=match):
        bp.generate(d, state, store=_NoStore(), cache=drr.SourceShaCache(None), data_lake=lake)


def test_publish_resolver_refuses_superseded_canonical(tmp_path):
    lake, canon, d, state = _lake(tmp_path, _fc())
    d = d.model_copy(update={"superseded_canonicals": [{"sha256": _sha(canon.read_bytes()), "status": "SUPERSEDED"}]})
    with pytest.raises(ValueError, match="置き換え済み"):
        rts.resolve("tokyo", ["tokyo"], [d], lake, nt._extract_depth_value)


# ── 3. Data Ops（runtime node）───────────────────────────────────────────────────

REL = "backend/hazard/tsunami/tsunami_kanagawa.geojson"
TILE = "frontend/tiles/kanagawa/tsunami/kanagawa_tsunami_A40-20_14.mbtiles"


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env(tmp_path)
    monkeypatch.setenv("OHG2_DATA_RUNTIME_ROOT", str(e.rt))
    monkeypatch.setattr(drr, "_default_cache", e.cache)
    drr._view_cache.clear()
    yield e
    drr._view_cache.clear()


def _record(runtime: bytes, canonical_sha=None, tile=b"TILE", acquisition=True):
    sha = _sha(runtime)
    return {"schema": rp.SCHEMA, "dataset_id": "KANAGAWA-TSUNAMI-001", "layer_type": "tsunami", "region": "kanagawa",
            "source": {"acquisition_id": "a", "acquisition_method": "upload", "validity": "valid", "validity_reason": None,
                       "validity_flags": [], "bundle": None,
                       "source_files": [{"name": "A40-20_14_GML.zip", "sha256": SOURCES["KANAGAWA-TSUNAMI-001"][4]}]}
            if acquisition else None,
            "canonical": {"sha256": canonical_sha or sha, "feature_count": None},
            "runtime_artifact": {"rel": REL, "sha256": sha, "feature_count": None},
            "tile": {"rel": TILE, "sha256": _sha(tile)}, "build_node": "local-build-node"}


def _dataset(env, record, runtime=b"T", validated=b"T", tile=b"TILE", defn=None):
    defn = defn or _defn("KANAGAWA-TSUNAMI-001")
    src = env.validated("tsunami", "kanagawa-tsunami-001.geojson", validated, region="kanagawa")
    files = {REL: runtime, TILE: tile}
    if record is not None:
        files[rp.runtime_rel(defn.dataset_id)] = json.dumps(record).encode()
    env.version("20261011T000000Z-00000001", files)
    state = DatasetState(dataset_id=defn.dataset_id, storage_status=StorageStatus.stored, current_validated_path=str(src),
                         validation_status=ValidationStatus.passed)
    return dos.build_dataset(defn, state, env.view(), allow_hash=True, allow_heavy=False, props={}, catalog=None,
                             store=_NoStore())


def test_runtime_verified_without_acquisition_on_node(env):
    d = _dataset(env, _record(b"T"))
    assert d["runtime"]["publish_mode"] == "registry" and d["runtime"]["runtime_status"] == drr.PUBLISHED
    assert d["integrity"]["components"]["runtime"]["status"] == dos.OK
    assert d["runtime_provenance"]["status"] == rp.VERIFIED
    assert d["integrity"]["components"]["runtime_provenance"]["status"] == dos.OK
    a = d["acquisition"]
    assert a["acquisition_history"] == "NOT PRESENT ON THIS NODE" and a["validity"] == "valid"
    assert d["integrity"]["components"]["source"]["status"] == dos.OK  # runtime node で取得履歴が無くても正常


def test_runtime_sha_mismatch_is_error(env):
    rec = _record(b"T")
    rec["runtime_artifact"]["sha256"] = _sha(b"OTHER")
    d = _dataset(env, rec)
    assert d["runtime_provenance"]["status"] == rp.MISMATCH
    assert d["integrity"]["components"]["runtime_provenance"]["status"] == dos.ERROR


def test_canonical_relation_mismatch_is_error(env):
    d = _dataset(env, _record(b"T", canonical_sha=_sha(b"SOMETHING ELSE")))
    assert d["runtime_provenance"]["status"] == rp.MISMATCH
    assert any("validated copy" in c["check"] and not c["ok"] for c in d["runtime_provenance"]["checks"])
    assert d["integrity"]["components"]["runtime_provenance"]["status"] == dos.ERROR


def test_tile_mismatch_in_record_is_error(env):
    d = _dataset(env, _record(b"T", tile=b"OLD TILE"))
    assert d["runtime_provenance"]["status"] == rp.MISMATCH
    assert d["integrity"]["components"]["runtime_provenance"]["status"] == dos.ERROR


def test_superseded_runtime_is_error(env):
    defn = _defn("KANAGAWA-TSUNAMI-001").model_copy(
        update={"superseded_canonicals": [{"sha256": _sha(b"T"), "status": "SUPERSEDED"}]})
    d = _dataset(env, _record(b"T"), defn=defn)
    assert d["integrity"]["components"]["runtime"]["status"] == dos.ERROR
    assert d["runtime_provenance"]["status"] == rp.MISMATCH


def test_runtime_not_ok_without_source_or_record(env):
    d = _dataset(env, None)  # record の無い旧 version
    assert d["runtime_provenance"]["status"] == rp.ABSENT
    assert d["integrity"]["components"]["runtime_provenance"]["status"] == dos.UNKNOWN
    assert d["acquisition"]["acquisition_history"] == "ABSENT"  # 推測で VALID にしない


# ── 4. publish が record を同梱する ───────────────────────────────────────────────

def _stage(tmp_path, runtime_present: bool):
    staging, lake = tmp_path / "staging", tmp_path / "data_lake"
    if runtime_present:
        (staging / "backend/hazard/tsunami").mkdir(parents=True)
        (staging / "backend/hazard/tsunami/tsunami_chiba.geojson").write_bytes(b"C")
    staging.mkdir(exist_ok=True)
    rec = _record(b"C")
    rec.update(dataset_id="CHIBA-TSUNAMI-001", region="chiba")
    rec["runtime_artifact"]["rel"] = "backend/hazard/tsunami/tsunami_chiba.geojson"
    p = rp.build_path(lake, "chiba", "tsunami", "CHIBA-TSUNAMI-001")
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(rec))
    out = subprocess.run([sys.executable, str(ROOT / "scripts/publish/stage_runtime_provenance.py"), "--staging",
                          str(staging), "--region", "tokyo", "--data-lake", str(lake)], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return staging / rp.runtime_rel("CHIBA-TSUNAMI-001"), out.stdout


def test_registry_record_is_staged_even_if_region_not_published(tmp_path):
    dst, out = _stage(tmp_path, True)
    assert dst.is_file() and "CHIBA-TSUNAMI-001" in out  # publish region は tokyo だけ
    assert json.loads(dst.read_text())["publish_verification"]["method"] == "validated_copy"


def test_registry_record_is_not_staged_without_runtime(tmp_path):
    dst, _ = _stage(tmp_path, False)
    assert not dst.exists()


# ── 5. 実データ（build node）────────────────────────────────────────────────────

@pytest.mark.parametrize("did,region,canon", [("TOKYO-TSUNAMI-001", "tokyo", TOKYO_NEW),
                                              ("KANAGAWA-TSUNAMI-001", "kanagawa", "f3890b6775d4e1416c3bebfccf6f52bbd13bddc8c550c78ccf0c5a26c95236a0"),
                                              ("CHIBA-TSUNAMI-001", "chiba", "1dad9f90c4ff4cfad73d918a37d7eac85f3edb1dce614f680b47e2e3619178bc")])
def test_build_node_record_matches_current_canonical(did, region, canon):
    p = rp.build_path(ROOT / "data_lake", region, "tsunami", did)
    if not p.is_file():
        pytest.skip("build node の record が無い環境（data_lake は gitignore）")
    rec = json.loads(p.read_text(encoding="utf-8"))
    assert rp.validate_record_shape(rec, did) == []
    assert rec["canonical"]["sha256"] == rec["runtime_artifact"]["sha256"] == canon
    assert rec["source"]["validity"] == "valid"
    assert [f["name"] for f in rec["source"]["source_files"]] == [SOURCES[did][0]]
    assert rec["source"]["source_files"][0]["sha256"] == SOURCES[did][4]
    assert rec["tile"]["rel"] == dos.tile_rel(_defn(did))

"""
TOKYO-SHELTER-EVAC-SEMANTIC-CORRECTION（2026-10-12）: 避難所 dataset の定義を中身に合わせる。

東京都の 2 dataset は定義（layer_type・名称）と原本の中身が逆だった:
  TOKYO-EVAC-001    raw 13000_1.zip（国土地理院 _1 = 指定避難所）     ← 旧定義 emergency_shelter / 指定緊急避難場所
  TOKYO-SHELTER-001 raw 13000_2.zip（国土地理院 _2 = 指定緊急避難場所） ← 旧定義 evacuation_shelter / 指定避難場所
pipeline は layer_type から --designation を決めて全 feature に強制するため、canonical / runtime の designation が
全件逆になり、UI の種別表示・marker と dedupe key に影響していた（避難先の選択・score は列で判定するため不変）。

是正（OWNER 承認: 定義を中身に合わせる。原本は入れ替えない）:
  - dataset_id・保管 path は維持し、layer_type・名称・出典を訂正（Kanagawa と同じく EVAC = _1、SHELTER = _2）
  - canonical は訂正後の定義で正式 pipeline から再生成
  - normalize_shelter: 強制 designation が列で確定する種別と矛盾したら取り込みを止める（再発防止）
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts" / "normalize"))

import normalize_shelter as ns  # noqa: E402
from app.services.dataset_definition_service import get_definition_service  # noqa: E402

NORMALIZER = ROOT / "scripts" / "normalize" / "normalize_shelter.py"
EVAC_COLS = {"NO": 1, "共通ID": "131010001", "施設・場所名": "小学校", "住所": "東京都",
             "指定緊急避難場所との住所同一": "", "その他市町村長が必要と認める事項": "", "受入対象者": "", "備考": ""}
EES_COLS = {"NO": 1, "共通ID": "131010002", "施設・場所名": "公園", "住所": "東京都", "洪水": 1, "地震": 1,
            "津波": "", "高潮": "", "崖崩れ、土石流及び地滑り": "", "大規模な火事": 1, "内水氾濫": "", "火山現象": "",
            "指定避難所との住所同一": "", "備考": ""}
DESIGNATION_BY_SUFFIX = {"_1.zip": "指定避難所", "_2.zip": "指定緊急避難場所"}
LAYER_BY_DESIGNATION = {"指定避難所": "evacuation_shelter", "指定緊急避難場所": "emergency_shelter"}


def _gsi_zip(tmp_path, name, props):
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [139.7, 35.6]}, "properties": props}]}
    z = tmp_path / f"{name}.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(f"{name}.geojson", json.dumps(fc, ensure_ascii=False))
    return z


def _normalize(src, out, designation):
    return subprocess.run([sys.executable, str(NORMALIZER), "--input", str(src), "--output", str(out),
                           "--dataset-id", "TOKYO-EVAC-001", "--designation", designation],
                          capture_output=True, text=True)


# ── 1-3. normalize の矛盾 guard ────────────────────────────────────────────────────

@pytest.mark.parametrize("name,props,wrong", [("13000_1", EVAC_COLS, "指定緊急避難場所"),
                                               ("13000_2", EES_COLS, "指定避難所")])
def test_01_forced_designation_contradicting_columns_is_rejected(tmp_path, name, props, wrong):
    out = tmp_path / "out.geojson"
    r = _normalize(_gsi_zip(tmp_path, name, props), out, wrong)
    assert r.returncode == 1 and "designation の矛盾" in r.stderr
    assert not out.exists()  # canonical の元になる出力を書かない


@pytest.mark.parametrize("name,props,right", [("13000_1", EVAC_COLS, "指定避難所"),
                                               ("13000_2", EES_COLS, "指定緊急避難場所")])
def test_02_consistent_designation_is_applied(tmp_path, name, props, right):
    out = tmp_path / "out.geojson"
    r = _normalize(_gsi_zip(tmp_path, name, props), out, right)
    assert r.returncode == 0, r.stderr
    feats = json.loads(out.read_text(encoding="utf-8"))["features"]
    assert [f["properties"]["designation"] for f in feats] == [right]


def test_03_undetermined_columns_keep_forced_designation(tmp_path):
    """国土地理院の _1 / _2 固有列が無い入力（P20 GML 等）は列で確定できないので従来どおり強制する。"""
    props = {"施設・場所名": "公園", "地震": 1}
    assert ns.content_designation([{"properties": props}]) is None
    assert ns.content_designation([{"properties": EVAC_COLS}, {"properties": EES_COLS}]) is None  # 両方 = 確定しない
    out = tmp_path / "out.geojson"
    assert _normalize(_gsi_zip(tmp_path, "x", props), out, "指定避難所").returncode == 0


# ── 4-6. registry の semantic contract ─────────────────────────────────────────────

def _shelter_definitions():
    return [d for d in get_definition_service().list_all() if d.category == "shelter"]


def test_04_every_gsi_shelter_definition_matches_its_source_file():
    """_1 = 指定避難所 = evacuation_shelter、_2 = 指定緊急避難場所 = emergency_shelter（名称も一致）。"""
    checked = []
    for d in _shelter_definitions():
        files = d.expected_source_files or []
        if d.source_provider != "国土地理院" or not files:
            continue
        (suffix,) = {s for s in DESIGNATION_BY_SUFFIX if files[0].endswith(s)}
        designation = DESIGNATION_BY_SUFFIX[suffix]
        assert d.layer_type == LAYER_BY_DESIGNATION[designation], d.dataset_id
        assert d.display_name.startswith(designation + "（"), d.dataset_id
        checked.append(d.dataset_id)
    assert sorted(checked) == ["KANAGAWA-EVAC-001", "KANAGAWA-SHELTER-001", "TOKYO-EVAC-001", "TOKYO-SHELTER-001"]


def test_05_dataset_ids_and_storage_paths_are_kept():
    evac, shelter = get_definition_service().get("TOKYO-EVAC-001"), get_definition_service().get("TOKYO-SHELTER-001")
    assert evac.validated_storage_path == "data_lake/validated/tokyo/emergency_shelters"
    assert shelter.validated_storage_path == "data_lake/validated/tokyo/shelters"
    assert {evac.layer_type, shelter.layer_type} == {"evacuation_shelter", "emergency_shelter"}


def test_06_pipeline_designation_map_matches_layer_types():
    src = (ROOT / "backend/app/services/pipeline_service.py").read_text(encoding="utf-8")
    assert '"evacuation_shelter": "指定避難所"' in src and '"emergency_shelter":  "指定緊急避難場所"' in src


# ── 7. 実データ（build node の data_lake がある時だけ）──────────────────────────────────

@pytest.mark.parametrize("did", ["TOKYO-EVAC-001", "TOKYO-SHELTER-001", "KANAGAWA-EVAC-001", "KANAGAWA-SHELTER-001"])
def test_07_canonical_designation_matches_content(did):
    d = get_definition_service().get(did)
    canon = ROOT / d.validated_storage_path / f"{did.lower()}.geojson"
    if not canon.is_file():
        pytest.skip("canonical が無い環境")
    feats = json.loads(canon.read_text(encoding="utf-8"))["features"]
    expected = {"evacuation_shelter": "指定避難所", "emergency_shelter": "指定緊急避難場所"}[d.layer_type]
    assert ns.content_designation(feats) == expected
    assert {f["properties"]["designation"] for f in feats} == {expected}

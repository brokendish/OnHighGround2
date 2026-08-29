"""
test_phase2d_gsi_legacy_scripts.py — GSI legacy shelter script（category 1/2）の
fixture test（Phase 2-D Round 3、指示書第9.4節、P2D-SHELTER-LEGACY-001）。

`scripts/download/download_emergency_shelter.sh`（category=2固定）と
`scripts/download/download_shelter.sh`（category=1固定）は、実際のfetch処理を
`scripts/download/download_shelter_gsi_prefecture.sh`（Round 2実装、本Roundの
変更対象外）へ委譲する薄いwrapperである。

実GSIへ毎回アクセスするとformal testの繰り返し負荷になるため（指示書第9.4節
「実GSIへformal testで繰り返し負荷をかけない」）、このtestはwrapper script自体の
実bytesを、`download_shelter_gsi_prefecture.sh`だけをlocal fixture stubへ差し替えた
一時PROJECT_ROOTコピーの中で実行する。wrapper scriptのcontent自体は一切変更しない
（production codeにtest専用分岐を入れない、というこのrepositoryの既存方針
[backend/tests/test_phase2b6_version_binding.py参照] に合わせる）。

実行:
    venv/bin/python -m pytest tools/public_release/test_phase2d_gsi_legacy_scripts.py -v
"""
from __future__ import annotations

import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

EMERGENCY_HAZARD_FIELDS = [
    "洪水", "崖崩れ、土石流及び地滑り", "高潮", "地震", "津波",
    "大規模な火事", "内水氾濫", "火山現象",
]
SHELTER_FIELDS = ["受入対象者", "その他市町村長が必要と認める事項", "指定緊急避難場所との住所同一"]


def _feature(props: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [139.0, 35.0]}}


def _emergency_feature(no: int = 1) -> dict:
    props = {"NO": no, "施設・場所名": f"避難場所{no}", "住所": "東京都千代田区"}
    props.update({k: "1" for k in EMERGENCY_HAZARD_FIELDS})
    return _feature(props)


def _shelter_feature(no: int = 1) -> dict:
    props = {"NO": no, "施設・場所名": f"避難所{no}", "住所": "東京都千代田区"}
    props.update({k: "" for k in SHELTER_FIELDS})
    return _feature(props)


_STUB_TEMPLATE = """#!/usr/bin/env bash
set -euo pipefail
PREF_CODE="${{1:?}}"
CATEGORY="${{2:?}}"
OUTPUT_DIR="${{3:?}}"
mkdir -p "${{OUTPUT_DIR}}"

STUB_MODE="{stub_mode}"

if [[ "${{STUB_MODE}}" == "http_error" ]]; then
    echo "ERROR: simulated HTTP failure" >&2
    exit 1
fi

OUT_FILE="${{OUTPUT_DIR}}/${{PREF_CODE}}_${{CATEGORY}}.geojson"
cat > "${{OUT_FILE}}" <<'GEOJSON'
{geojson_body}
GEOJSON

echo "stubhash" > "${{OUT_FILE}}.sha256"
cat > "${{OUTPUT_DIR}}/${{PREF_CODE}}_${{CATEGORY}}.fetch_metadata.json" <<'META'
{{"source_url": "https://hinanmap.gsi.go.jp/fixture/${{PREF_CODE}}_${{CATEGORY}}.geojson", "sha256": "stubhash"}}
META
echo "OK: stub fetch ${{OUT_FILE}}"
"""


@pytest.fixture()
def fixture_project_root(tmp_path):
    """PROJECT_ROOTの最小構成（scripts/common/log.sh + scripts/download/wrapper実bytes）
    をtmp_path配下へ複製する。wrapper scriptの中身は一切書き換えない。"""
    root = tmp_path / "project_root"
    (root / "scripts" / "common").mkdir(parents=True)
    (root / "scripts" / "download").mkdir(parents=True)

    shutil.copy2(REPO_ROOT / "scripts" / "common" / "log.sh", root / "scripts" / "common" / "log.sh")
    for name in ("download_emergency_shelter.sh", "download_shelter.sh"):
        dst = root / "scripts" / "download" / name
        shutil.copy2(REPO_ROOT / "scripts" / "download" / name, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IEXEC)

    return root


def _install_stub(root: Path, stub_mode: str, geojson_body: dict | None) -> None:
    stub_path = root / "scripts" / "download" / "download_shelter_gsi_prefecture.sh"
    body_text = json.dumps(geojson_body, ensure_ascii=False) if geojson_body is not None else "{}"
    stub_path.write_text(_STUB_TEMPLATE.format(stub_mode=stub_mode, geojson_body=body_text), encoding="utf-8")
    stub_path.chmod(stub_path.stat().st_mode | stat.S_IEXEC)


def _run_wrapper(root: Path, name: str, pref_code: str, output_dir: Path) -> subprocess.CompletedProcess:
    script = root / "scripts" / "download" / name
    return subprocess.run(
        ["bash", str(script), pref_code, str(output_dir)],
        cwd=root, capture_output=True, text=True, timeout=30,
    )


def _fc(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "name": "fixture", "features": features}


# ---------------------------------------------------------------------------
# 1. category 1 shelter success
# ---------------------------------------------------------------------------

def test_gsi_01_category1_shelter_success(fixture_project_root, tmp_path):
    _install_stub(fixture_project_root, "ok", _fc([_shelter_feature()]))
    out_dir = tmp_path / "out1"
    proc = _run_wrapper(fixture_project_root, "download_shelter.sh", "13000", out_dir)
    assert proc.returncode == 0, proc.stderr
    out_file = out_dir / "tokyo_shelters.geojson"
    assert out_file.is_file()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["features"][0]["properties"]["受入対象者"] == ""
    assert (out_dir / "tokyo_shelters.geojson.sha256").is_file()
    assert (out_dir / "tokyo_shelters.fetch_metadata.json").is_file()


# ---------------------------------------------------------------------------
# 2. category 2 emergency site success
# ---------------------------------------------------------------------------

def test_gsi_02_category2_emergency_success(fixture_project_root, tmp_path):
    _install_stub(fixture_project_root, "ok", _fc([_emergency_feature()]))
    out_dir = tmp_path / "out2"
    proc = _run_wrapper(fixture_project_root, "download_emergency_shelter.sh", "13000", out_dir)
    assert proc.returncode == 0, proc.stderr
    out_file = out_dir / "tokyo_emergency_shelters.geojson"
    assert out_file.is_file()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["features"][0]["properties"]["津波"] == "1"


# ---------------------------------------------------------------------------
# 3. category逆転FAIL
# ---------------------------------------------------------------------------

def test_gsi_03_category_reversed_rejected_for_shelter(fixture_project_root, tmp_path):
    # download_shelter.sh (category=1) が実際にはcategory=2 (emergency)相当のデータを
    # 受け取ってしまった場合を模擬する。
    _install_stub(fixture_project_root, "ok", _fc([_emergency_feature()]))
    out_dir = tmp_path / "out3"
    proc = _run_wrapper(fixture_project_root, "download_shelter.sh", "13000", out_dir)
    assert proc.returncode != 0
    assert not (out_dir / "tokyo_shelters.geojson").exists()


def test_gsi_03b_category_reversed_rejected_for_emergency(fixture_project_root, tmp_path):
    _install_stub(fixture_project_root, "ok", _fc([_shelter_feature()]))
    out_dir = tmp_path / "out3b"
    proc = _run_wrapper(fixture_project_root, "download_emergency_shelter.sh", "13000", out_dir)
    assert proc.returncode != 0
    assert not (out_dir / "tokyo_emergency_shelters.geojson").exists()


# ---------------------------------------------------------------------------
# 4. schema不一致FAIL
# ---------------------------------------------------------------------------

def test_gsi_04_schema_mismatch_rejected(fixture_project_root, tmp_path):
    _install_stub(fixture_project_root, "ok", {"type": "NotAFeatureCollection"})
    out_dir = tmp_path / "out4"
    proc = _run_wrapper(fixture_project_root, "download_shelter.sh", "13000", out_dir)
    assert proc.returncode != 0
    assert not (out_dir / "tokyo_shelters.geojson").exists()


# ---------------------------------------------------------------------------
# 5. empty feature FAIL
# ---------------------------------------------------------------------------

def test_gsi_05_empty_features_rejected(fixture_project_root, tmp_path):
    _install_stub(fixture_project_root, "ok", _fc([]))
    out_dir = tmp_path / "out5"
    proc = _run_wrapper(fixture_project_root, "download_emergency_shelter.sh", "13000", out_dir)
    assert proc.returncode != 0
    assert not (out_dir / "tokyo_emergency_shelters.geojson").exists()


# ---------------------------------------------------------------------------
# 6. HTTP error FAIL
# ---------------------------------------------------------------------------

def test_gsi_06_http_error_propagates(fixture_project_root, tmp_path):
    _install_stub(fixture_project_root, "http_error", None)
    out_dir = tmp_path / "out6"
    proc = _run_wrapper(fixture_project_root, "download_shelter.sh", "13000", out_dir)
    assert proc.returncode != 0
    assert not out_dir.exists() or not any(out_dir.iterdir())


# ---------------------------------------------------------------------------
# 7. partial file cleanup
# ---------------------------------------------------------------------------

def test_gsi_07_no_partial_file_left_on_failure(fixture_project_root, tmp_path):
    _install_stub(fixture_project_root, "ok", _fc([]))  # empty -> failure
    out_dir = tmp_path / "out7"
    out_dir.mkdir()
    _run_wrapper(fixture_project_root, "download_shelter.sh", "13000", out_dir)
    leftover = list(out_dir.glob("*.partial"))
    assert leftover == [], f"partial files leaked: {leftover}"


# ---------------------------------------------------------------------------
# 8. manifest生成 (fetch_metadata.json is carried through on success)
# ---------------------------------------------------------------------------

def test_gsi_08_fetch_metadata_manifest_generated(fixture_project_root, tmp_path):
    _install_stub(fixture_project_root, "ok", _fc([_shelter_feature()]))
    out_dir = tmp_path / "out8"
    proc = _run_wrapper(fixture_project_root, "download_shelter.sh", "13000", out_dir)
    assert proc.returncode == 0, proc.stderr
    metadata = json.loads((out_dir / "tokyo_shelters.fetch_metadata.json").read_text(encoding="utf-8"))
    assert "source_url" in metadata
    assert "sha256" in metadata


# ---------------------------------------------------------------------------
# invalid prefecture code rejected
# ---------------------------------------------------------------------------

def test_gsi_09_invalid_prefecture_code_rejected(fixture_project_root, tmp_path):
    out_dir = tmp_path / "out9"
    proc = _run_wrapper(fixture_project_root, "download_shelter.sh", "not-a-code", out_dir)
    assert proc.returncode != 0


# ---------------------------------------------------------------------------
# no legacy local-copy fallback: scripts must not reference the old local raw folder
# ---------------------------------------------------------------------------

def test_gsi_10_no_legacy_local_copy_fallback():
    for name in ("download_emergency_shelter.sh", "download_shelter.sh"):
        text = (REPO_ROOT / "scripts" / "download" / name).read_text(encoding="utf-8")
        assert "国土地理院避難所データ" not in text, f"{name} still references the legacy local-copy fallback folder"

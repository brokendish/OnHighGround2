"""
test_hazard_meta_tileset_region_selection.py —
HAZARD-META-TILESET-REGION-SELECTION-GAP Phase B 回帰テスト。

`_find_tileset_for_region()` は従来 `_TILE_ROOT / region / hazard_type`
配下の全 `*.mbtiles` を候補にし、無条件に最大サイズを選んでいた。
tsunamiはTokyo/Kanagawa(×2)/ChibaのMBTilesが全て物理的に同一directory
（`tokyo/tsunami/`）へ同居しており、`region="tokyo"`の問い合わせに対し
最大サイズのChiba tilesetを誤って返す実バグがあった（実機確認:
`chiba_tsunami_A40-18_12.mbtiles` 34,267,136 bytes が
`tokyo_tsunami_A40-23_13.mbtiles` 7,716,864 bytesより大きいため誤選択）。

Phase Bでは、globした候補をfilenameのregion接頭辞（`{region}_`/
`{region}-`）でfilterしてから、既存の最大サイズselectorを適用する
（Candidate A、region-prefix filter）。MBTiles move/rename・Martin変更・
frontend変更・meta schema変更は一切行わない。

hazards.pyのrouterのみを軽量FastAPI test appへmountし、
_TILE_ROOTをmonkeypatchすることで、実データ読み込みを伴う
app_public.py全体のimportを避ける（既存慣習どおり）。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import hazards  # noqa: E402


def _make_valid_mbtiles(path: Path, vector_layer_id: str = "layer", padding_rows: int = 0) -> None:
    """有効なmbtiles（sqlite、metadataテーブル）を作る。padding_rowsで
    ファイルサイズを意図的に差別化できる（大きいほどpadding_rowsを増やす）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.execute(
            "INSERT INTO metadata (name, value) VALUES (?, ?)",
            ("json", f'{{"vector_layers": [{{"id": "{vector_layer_id}"}}]}}'),
        )
        if padding_rows:
            conn.execute("CREATE TABLE padding (data TEXT)")
            conn.executemany(
                "INSERT INTO padding (data) VALUES (?)", [("x" * 1000,)] * padding_rows
            )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def tile_root(tmp_path, monkeypatch):
    root = tmp_path / "tiles"
    monkeypatch.setattr(hazards, "_TILE_ROOT", root)
    return root


# ── A/B. Tokyo tsunami混在directory → Tokyoのみ選択、Chiba最大でも除外 ─────────

def test_A_B_tokyo_tsunami_mixed_directory_selects_tokyo_only(tile_root):
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    # Chibaを最大サイズにする（実機の実際の事象を再現: Chiba最大）
    _make_valid_mbtiles(tsunami_dir / "tokyo_tsunami_A40-23_13.mbtiles", "tokyo_layer", padding_rows=5)
    _make_valid_mbtiles(tsunami_dir / "kanagawa_tsunami_A40-16_14.mbtiles", "kanagawa_layer_1", padding_rows=10)
    _make_valid_mbtiles(tsunami_dir / "kanagawa_tsunami_A40-20_14.mbtiles", "kanagawa_layer_2", padding_rows=10)
    _make_valid_mbtiles(tsunami_dir / "chiba_tsunami_A40-18_12.mbtiles", "chiba_layer", padding_rows=50)  # 最大

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result is not None
    assert result["tileset_id"] == "tokyo_tsunami_A40-23_13"
    assert result["source_layer"] == "tokyo_layer"


# ── C. Kanagawaが最大でもTokyoでは選ばれない（Bと同一fixtureで別視点の確認） ────

def test_C_kanagawa_largest_file_not_selected_for_tokyo(tile_root):
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "tokyo_tsunami_A40-23_13.mbtiles", "tokyo_layer", padding_rows=1)
    _make_valid_mbtiles(tsunami_dir / "kanagawa_tsunami_A40-16_14.mbtiles", "kanagawa_layer", padding_rows=100)

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result["tileset_id"] == "tokyo_tsunami_A40-23_13"


# ── D. wrong-regionのみ存在 → None（fail-closed） ──────────────────────────────

def test_D_only_wrong_region_files_returns_none(tile_root):
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "kanagawa_tsunami_A40-16_14.mbtiles", "kanagawa_layer")
    _make_valid_mbtiles(tsunami_dir / "chiba_tsunami_A40-18_12.mbtiles", "chiba_layer")
    # tokyo prefixのfileは1つも無い

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result is None


# ── E. same-region複数 → 既存の最大サイズselection維持 ────────────────────────

def test_E_same_region_multiple_candidates_picks_largest(tile_root):
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "tokyo_a.mbtiles", "a_layer", padding_rows=1)
    _make_valid_mbtiles(tsunami_dir / "tokyo_b.mbtiles", "b_layer", padding_rows=50)  # 最大

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result["tileset_id"] == "tokyo_b"


# ── F/G. underscore prefix / hyphen prefix 両対応 ──────────────────────────────

def test_F_underscore_prefix_matches(tile_root):
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "tokyo_underscore_style.mbtiles", "layer")

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result["tileset_id"] == "tokyo_underscore_style"


def test_G_hyphen_prefix_matches(tile_root):
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "tokyo-hyphen-style.mbtiles", "layer")

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result["tileset_id"] == "tokyo-hyphen-style"


def test_F_G_exact_region_name_without_separator_matches(tile_root):
    """`p.stem == region`（separatorすら無い、region名そのままのfilename）も
    正当なcandidateとして扱う（既存selector contractの一部）。"""
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "tokyo.mbtiles", "layer")

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result["tileset_id"] == "tokyo"


# ── H. false substring match（"not_tokyo_xxx"等）を除外 ────────────────────────

def test_H_false_substring_match_excluded(tile_root):
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    # "tokyo"を含むが接頭辞ではない偽陽性候補
    _make_valid_mbtiles(tsunami_dir / "not_tokyo_xxx.mbtiles", "fake_layer")
    _make_valid_mbtiles(tsunami_dir / "faketokyo.mbtiles", "fake_layer_2")
    _make_valid_mbtiles(tsunami_dir / "old_tokyo_backup.mbtiles", "fake_layer_3")

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result is None  # 真のtokyo接頭辞candidateが無いため


def test_H2_false_substring_match_does_not_win_over_real_prefix(tile_root):
    """偽陽性候補が実candidateより大きくても、真のregion接頭辞candidateが
    優先されること（偽陽性はそもそも候補集合に入らない）。"""
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "tokyo_real.mbtiles", "real_layer", padding_rows=1)
    _make_valid_mbtiles(tsunami_dir / "not_tokyo_fake.mbtiles", "fake_layer", padding_rows=100)  # 偽陽性、最大サイズ

    result = hazards._find_tileset_for_region("tsunami", "tokyo")

    assert result["tileset_id"] == "tokyo_real"


# ── I/J/K/L/M. 他hazard typeのregression（既存選択結果が変更されない） ────────

@pytest.mark.parametrize("hazard_type,region,filename", [
    ("flood", "tokyo", "tokyo_flood_max.mbtiles"),
    ("flood", "kanagawa", "kanagawa_river_001.mbtiles"),
    ("storm_surge", "tokyo", "tokyo_surge_001.mbtiles"),
    ("storm_surge", "kanagawa", "kanagawa_surge_001.mbtiles"),
    ("pseudo_inland_flood", "tokyo", "tokyo_pseudo_inland_flood_001.mbtiles"),
    ("lowland_poor_drainage", "tokyo", "tokyo_lowland_poor_drainage_001.mbtiles"),
    ("lowland_poor_drainage", "kanagawa", "kanagawa_lowland_poor_drainage_001.mbtiles"),
    ("inland_flood", "tokyo", "tokyo_urban_001.mbtiles"),
    ("inland_flood", "kanagawa", "kanagawa_urban_001.mbtiles"),
])
def test_IJKLM_other_hazard_types_selection_unchanged(tile_root, hazard_type, region, filename):
    """Phase A実機inventoryで確認した実際の命名規則（region接頭辞）に
    従うfixtureを使い、region-prefix filter追加後も従来通り選択される
    ことを確認する（regressionなし）。"""
    tile_dir = tile_root / region / hazard_type
    _make_valid_mbtiles(tile_dir / filename, "layer")

    result = hazards._find_tileset_for_region(hazard_type, region)

    assert result is not None
    assert result["tileset_id"] == Path(filename).stem


# ── N/O. meta route全体でのChiba 404 / Kanagawa tsunami既存null semantics ──────

@pytest.fixture()
def meta_client():
    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app, raise_server_exceptions=False)


def test_N_chiba_meta_stays_404_not_generated_from_filesystem(meta_client, tile_root):
    """tsunami/chiba用のMBTilesがtile_root上に実在していても、
    get_active_hazard_meta()のregistry check（未登録→KeyError→404）が
    _find_tileset_for_region()より先に走るため、404のまま維持される
    （filesystem selectorだけでChiba metaを生成してはいけない）。"""
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "chiba_tsunami_A40-18_12.mbtiles", "chiba_layer")

    exc = KeyError("Active dataset is not registered: tsunami:chiba")
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", side_effect=exc):
        resp = meta_client.get("/api/hazards/tsunami/chiba/meta")

    assert resp.status_code == 404


def test_O_kanagawa_tsunami_meta_keeps_existing_null_tileset(meta_client, tile_root):
    """productionでは`kanagawa/tsunami/`directory自体が存在しない
    （tsunamiは全regionのMBTilesが`tokyo/tsunami/`に同居する特殊layout）。
    今回のfixはこれを解決しないため、Kanagawaのtileset_idは既存通り
    null/Noneのまま——tokyo/tsunami/へ跨って探索してはいけない。"""
    # tokyo/tsunami/ にのみ全regionのファイルが存在する実際のproduction layoutを再現
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "tokyo_tsunami_A40-23_13.mbtiles", "tokyo_layer")
    _make_valid_mbtiles(tsunami_dir / "kanagawa_tsunami_A40-16_14.mbtiles", "kanagawa_layer_1")
    _make_valid_mbtiles(tsunami_dir / "kanagawa_tsunami_A40-20_14.mbtiles", "kanagawa_layer_2")
    # kanagawa/tsunami/ ディレクトリ自体は意図的に作らない

    fake_meta = {
        "dataset_id": "KANAGAWA-TSUNAMI-001", "layer_type": "tsunami", "region": "kanagawa",
        "display_name": "d", "deploy_status": "deployed", "artifact_path": "/x", "is_active": True,
    }
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=fake_meta):
        resp = meta_client.get("/api/hazards/tsunami/kanagawa/meta")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tileset_id"] is None
    assert data["tileset_source_layer"] is None


def test_tokyo_tsunami_meta_returns_tokyo_tileset_end_to_end(meta_client, tile_root):
    """route levelでのend-to-end確認: Tokyo/Kanagawa/Chiba混在directoryでも
    tsunami/tokyo/metaが正しくTokyo tilesetを返すこと
    （HAZARD-META-TILESET-REGION-SELECTION-GAPの直接的な回帰テスト）。"""
    tsunami_dir = tile_root / "tokyo" / "tsunami"
    _make_valid_mbtiles(tsunami_dir / "tokyo_tsunami_A40-23_13.mbtiles", "tokyo_layer", padding_rows=1)
    _make_valid_mbtiles(tsunami_dir / "chiba_tsunami_A40-18_12.mbtiles", "chiba_layer", padding_rows=100)

    fake_meta = {
        "dataset_id": "TOKYO-TSUNAMI-001", "layer_type": "tsunami", "region": "tokyo",
        "display_name": "d", "deploy_status": "deployed", "artifact_path": "/x", "is_active": True,
    }
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=fake_meta):
        resp = meta_client.get("/api/hazards/tsunami/tokyo/meta")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tileset_id"] == "tokyo_tsunami_A40-23_13"
    assert data["tileset_id"] != "chiba_tsunami_A40-18_12"

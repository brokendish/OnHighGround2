"""
test_hazard_meta_tileset_permission_contract.py —
HAZARD-META-TILESET-READ-PERMISSION-GAP remediation テスト。

root cause: /data_runtime/frontend ディレクトリのgroup ownershipが
兄弟の layers/tiles（既にohg2leases=20001）や親のdata_runtimeと異なり
ohg2operator(10002)のまま取り残されていたため、backend-public
（supplemental group 20001のみ）がこの1階層でtraverseできず、
GET /api/hazards/{type}/{region}/meta が呼ぶ hazards.py::
_find_tileset_for_region() が PermissionError で落ち、500になっていた。

このテストは:
  A/B. deploy_to_runtime.sh に追加した frontend root正規化処理
       （mkdir -p → chgrp leases_gid → chmod 0750）が実際に機能すること。
  C/D. _find_tileset_for_region() 自体が、正しい権限下でmbtilesの
       filename/vector_layer情報を正常に解決できること（tiles subtree
       のlist/readとmbtiles自体のreadonly open）。
  E.   正規化後のmodeがpublicへwrite権限を一切与えないこと（0750、
       group/otherともにw bitなし）を静的に確認。
  F.   _find_tileset_for_region の呼び出しはhazards.pyの既存try/except
       の外にあるため、権限問題が万一再発してもraw pathがpublic
       responseへ漏れないことを回帰的に確認する
       （FastAPI/StarletteのデフォルトServerErrorMiddleware、debug=false
       により定型"Internal Server Error"のみが返ることを実証）。
  G/H. C2 current-priority regression・7type contract regressionは
       既存の test_hazard_dataset_service_current_priority.py /
       test_runtime_dataset_validate_wired_hazard_types.py で継続確認
       （本ファイルでは変更していないため再掲しない）。
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import hazards  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = REPO_ROOT / "scripts" / "publish" / "deploy_to_runtime.sh"


# ── A/B. frontend root正規化（deploy_to_runtime.shの実際の効果） ─────────────

def test_A_B_frontend_root_normalized_by_deploy_script(tmp_path):
    """deploy_to_runtime.shを（--dry-runで、必要ならその後のresolver段階で
    失敗してもよい状態で）部分実行し、frontend root directoryが
    mkdir → chgrp → chmod 0750 されることを確認する。

    実行ユーザーの実gid（os.getgid()）をOHG2_LEASES_GIDへ差し替えることで、
    非特権テスト環境でも実際のchgrp成功を検証できるようにする
    （本番では20001=ohg2leasesだが、ここではテスト実行者自身のgidで
    「指定したgidへ実際に揃える」というロジック自体の正しさを検証する）。
    """
    staging_root = tmp_path / "data_runtime"
    env = os.environ.copy()
    env["OHG2_STAGING_ROOT"] = str(staging_root)
    env["OHG2_LEASES_GID"] = str(os.getgid())

    subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--dry-run", "--region", "tokyo"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    # 後続のresolver/registry依存処理がfixtureデータ不足で失敗しても、
    # frontend root正規化はそれより前段で必ず実行されているはず。

    frontend_dir = staging_root / "frontend"
    assert frontend_dir.is_dir(), "frontend root directoryが作成されていない"

    st = frontend_dir.stat()
    assert st.st_gid == os.getgid(), (
        f"frontend rootのgroupがOHG2_LEASES_GIDへ正規化されていない: "
        f"expected={os.getgid()} actual={st.st_gid}"
    )
    assert stat.S_IMODE(st.st_mode) == 0o750, (
        f"frontend rootのmodeが0750になっていない: actual={oct(stat.S_IMODE(st.st_mode))}"
    )


def test_A_B_frontend_root_normalization_is_idempotent(tmp_path):
    """既にfrontend rootが存在し、意図的にgroup driftさせた状態でも、
    再実行で正しいgroupへ戻ることを確認する（drift再発時の自己修復力）。"""
    staging_root = tmp_path / "data_runtime"
    frontend_dir = staging_root / "frontend"
    frontend_dir.mkdir(parents=True)
    os.chmod(frontend_dir, 0o755)  # 意図的にdriftした状態を模す

    env = os.environ.copy()
    env["OHG2_STAGING_ROOT"] = str(staging_root)
    env["OHG2_LEASES_GID"] = str(os.getgid())

    subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--dry-run", "--region", "tokyo"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=30,
    )

    st = frontend_dir.stat()
    assert st.st_gid == os.getgid()
    assert stat.S_IMODE(st.st_mode) == 0o750


# ── E. write権限が一切付与されていないこと（静的確認） ─────────────────────────

def test_E_normalized_mode_grants_no_write_to_group_or_other(tmp_path):
    staging_root = tmp_path / "data_runtime"
    env = os.environ.copy()
    env["OHG2_STAGING_ROOT"] = str(staging_root)
    env["OHG2_LEASES_GID"] = str(os.getgid())

    subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--dry-run", "--region", "tokyo"],
        cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=30,
    )

    mode = stat.S_IMODE((staging_root / "frontend").stat().st_mode)
    assert mode & stat.S_IWGRP == 0, "group write権限が付与されている（0750契約違反）"
    assert mode & stat.S_IWOTH == 0, "other write権限が付与されている（0750契約違反）"
    assert mode & stat.S_IWUSR != 0, "owner write権限が失われている（既存contract破壊）"


# ── C/D. _find_tileset_for_region: tiles subtree list + mbtiles readonly open ──

def _make_valid_mbtiles(path: Path, vector_layer_id: str = "inland_flood") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.execute(
            "INSERT INTO metadata (name, value) VALUES (?, ?)",
            ("json", f'{{"vector_layers": [{{"id": "{vector_layer_id}"}}]}}'),
        )
        conn.commit()
    finally:
        conn.close()


def test_C_D_find_tileset_lists_and_reads_mbtiles_metadata(tmp_path, monkeypatch):
    tile_dir = tmp_path / "tiles" / "tokyo" / "inland_flood"
    mbtiles_path = tile_dir / "tokyo_urban_001.mbtiles"
    _make_valid_mbtiles(mbtiles_path, vector_layer_id="inland_flood")

    monkeypatch.setattr(hazards, "_TILE_ROOT", tmp_path / "tiles")

    result = hazards._find_tileset_for_region("inland_flood", "tokyo")
    assert result == {"tileset_id": "tokyo_urban_001", "source_layer": "inland_flood"}


def test_C_D_find_tileset_picks_largest_when_multiple_candidates(tmp_path, monkeypatch):
    # HAZARD-META-TILESET-REGION-SELECTION-GAP対応（Phase B）: region-prefix
    # filterの導入により、region接頭辞を持たないfilename（旧: small/large）
    # は候補から除外されるようになったため、実際の命名規則
    # （{region}_...）に沿ったfixtureへ更新する。「同一region内で最大
    # サイズを選ぶ」という検証意図自体は変更しない。
    tile_dir = tmp_path / "tiles" / "tokyo" / "flood"
    small = tile_dir / "tokyo_small.mbtiles"
    large = tile_dir / "tokyo_large.mbtiles"
    _make_valid_mbtiles(small, vector_layer_id="small_layer")
    _make_valid_mbtiles(large, vector_layer_id="large_layer")
    # sizeを明確に差別化する（DBを大きくする）
    conn = sqlite3.connect(str(large))
    conn.execute("CREATE TABLE padding (data TEXT)")
    conn.executemany("INSERT INTO padding (data) VALUES (?)", [("x" * 1000,)] * 50)
    conn.commit()
    conn.close()

    monkeypatch.setattr(hazards, "_TILE_ROOT", tmp_path / "tiles")

    result = hazards._find_tileset_for_region("flood", "tokyo")
    assert result["tileset_id"] == "tokyo_large"


def test_C_D_find_tileset_returns_none_when_no_candidates(tmp_path, monkeypatch):
    monkeypatch.setattr(hazards, "_TILE_ROOT", tmp_path / "tiles")
    result = hazards._find_tileset_for_region("flood", "kanagawa")
    assert result is None


# ── F. tileset lookup中のPermissionErrorがraw pathを漏らさないこと（回帰） ────

@pytest.fixture()
def meta_client():
    from fastapi import FastAPI
    from _testclient_compat import TestClient

    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app, raise_server_exceptions=False)


def test_F_tileset_lookup_permission_error_does_not_leak_raw_path(meta_client, monkeypatch):
    """_find_tileset_for_region()の呼び出しはhazards.py::get_active_hazard_meta()
    の既存try/exceptブロックの外にある（Remediation 04のPUBLIC-ERROR-DETAIL-LEAK
    対策時、この関数だけ見落とされていた——今回の500の真因でもある）。

    権限修正後は実際にはPermissionErrorが起きなくなるが、万一drift再発
    した場合でも、FastAPI/StarletteのデフォルトServerErrorMiddleware
    （debug=false）が定型"Internal Server Error"のみを返し、raw path/
    errnoが漏れないことを回帰的に保証する。"""
    leaked_path = "/data_runtime/frontend/tiles/tokyo/inland_flood"
    exc = OSError(f"[Errno 13] Permission denied: '{leaked_path}'")

    fake_meta = {
        "dataset_id": "TOKYO-URBAN-001", "layer_type": "inland_flood", "region": "tokyo",
        "display_name": "d", "deploy_status": "deployed", "artifact_path": "/x", "is_active": True,
    }
    with patch.object(hazards, "_find_tileset_for_region", side_effect=exc), \
         patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=fake_meta):
        resp = meta_client.get("/api/hazards/inland_flood/tokyo/meta")

    assert resp.status_code == 500
    assert leaked_path not in resp.text
    assert "Permission denied" not in resp.text
    assert "Errno" not in resp.text


def test_F_meta_endpoint_normal_response_unaffected(meta_client, tmp_path, monkeypatch):
    """正規化後の正常系: tileset解決成功時、meta responseにtileset_id/
    source_layerが含まれ、raw filesystem pathはtileset関連フィールドに
    出てこない（artifact_pathフィールド自体は既存の意図された仕様で
    別途pathを含むが、これはC2以前からの既存contractであり本remediation
    のスコープ外）。"""
    tile_dir = tmp_path / "tiles" / "tokyo" / "inland_flood"
    _make_valid_mbtiles(tile_dir / "tokyo_urban_001.mbtiles", vector_layer_id="inland_flood")
    monkeypatch.setattr(hazards, "_TILE_ROOT", tmp_path / "tiles")

    fake_meta = {
        "dataset_id": "TOKYO-URBAN-001", "layer_type": "inland_flood", "region": "tokyo",
        "display_name": "d", "deploy_status": "deployed", "artifact_path": "/x", "is_active": True,
    }
    with patch.object(hazards.hazard_dataset_service, "get_active_hazard_meta", return_value=fake_meta):
        resp = meta_client.get("/api/hazards/inland_flood/tokyo/meta")

    assert resp.status_code == 200
    data = resp.json()
    assert data["tileset_id"] == "tokyo_urban_001"
    assert data["tileset_source_layer"] == "inland_flood"

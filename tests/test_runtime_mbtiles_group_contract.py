"""
test_runtime_mbtiles_group_contract.py — RUNTIME-MBTILES-GROUP-CONTRACT 回帰テスト。

root cause（VPS実測）: operator imageにはrsyncが無く、Martin向けflat mirror
（data_runtime/frontend/tiles）への同期は`cp -r --remove-destination`に縮退していた。
`cp -r`はfileのgroupをoperatorのprimary gid（10002）にするため、flat mirrorの
mbtilesだけが 10002:10002 0640 になり、backend-public（10001、supplemental 20001）が
sqliteで開けず、GET /api/hazards/{type}/{region}/meta の tileset_source_layer が
null になっていた（Martin=rootは配信できるため症状は「meta だけ null」）。

正式契約（init_data_runtime_backend.py が data_runtime/current 側の実機statとして定義）:
  file: owner=operator(10002), group=leases_gid(20001), mode 0640
  dir : owner=operator(10002), group=leases_gid(20001), mode 0750

A. 静的ガード: atomic publishがflat mirror同期を専用scriptへ委譲し、契約を保証する実装が残っている。
B. 観測性: mbtilesを読めない場合にwarningを出す（返り値仕様 source_layer=None は不変）。
C. 実権限の検証（Docker）: 権限matrixを実行し、旧同期の再現・誤group/modeの検出・自動修復・
   backend-public(10001+20001)が公開対象MBTilesを全て読めることを確認する。
   Docker / python:3.11-slim が無い環境ではskipする。
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import hazards  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ATOMIC = REPO_ROOT / "scripts" / "publish" / "deploy_to_runtime_atomic.sh"
MIRROR = REPO_ROOT / "scripts" / "publish" / "sync_frontend_tiles_mirror.sh"
MATRIX = REPO_ROOT / "tools" / "public_release" / "phase2b5_permission_matrix_inner.py"


# ── A. 静的ガード ─────────────────────────────────────────────────────────────

def test_A1_atomic_publish_delegates_mirror_sync_to_helper():
    text = ATOMIC.read_text(encoding="utf-8")
    assert 'sync_frontend_tiles_mirror.sh" "${TILES_SRC}" "${TILES_DST}"' in text
    # 契約を保証しない旧同期（cp -r / rsync -a を atomic script が直接実行）が残っていない
    code_lines = [l for l in text.splitlines() if not l.lstrip().startswith("#")]
    joined = "\n".join(code_lines)
    assert "cp -r --remove-destination" not in joined
    assert not re.search(r"^\s*(if )?rsync -a", joined, re.M)


def test_A2_atomic_publish_fails_loud_on_contract_violation_exit4():
    text = ATOMIC.read_text(encoding="utf-8")
    assert re.search(r'MIRROR_EXIT_CODE.*-eq 4', text)
    assert re.search(r'-eq 4 \]\];\s*then.*?exit 4', text, re.S)


def test_A3_helper_enforces_explicit_group_and_mode():
    text = MIRROR.read_text(encoding="utf-8")
    assert 'FILE_MODE="640"' in text and 'DIR_MODE="750"' in text
    assert 'LEASES_GID="${OHG2_LEASES_GID:-20001}"' in text
    assert 'chgrp "${LEASES_GID}"' in text
    # -a は既存dirのutimeに失敗して同期自体が落ちるため使わない（コメント以外で）
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "cp -a" not in code
    assert MIRROR.stat().st_mode & 0o111, "helperに実行bitが無い"


def test_A4_helper_is_valid_bash():
    r = subprocess.run(["bash", "-n", str(MIRROR)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run(["bash", "-n", str(ATOMIC)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_A5_permission_matrix_covers_flat_mirror_and_is_wired_to_scripts_mount():
    matrix = MATRIX.read_text(encoding="utf-8")
    assert "def run_flat_tiles_mirror_matrix" in matrix
    assert "run_flat_tiles_mirror_matrix(DATA_RUNTIME_ROOT)" in matrix
    launcher = (REPO_ROOT / "tools" / "public_release" / "phase2b5_atomic_publish.py").read_text(encoding="utf-8")
    assert "/scripts:ro" in launcher


# ── B. 観測性: 読めないmbtilesはwarning、返り値は不変 ─────────────────────────

def _tile_root_with(tmp_path: Path, hazard_type: str, fname: str, content: bytes | None, layer: str = "storm_surge"):
    d = tmp_path / "tokyo" / hazard_type
    d.mkdir(parents=True)
    p = d / fname
    if content is None:
        conn = sqlite3.connect(str(p))
        conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
        conn.execute("INSERT INTO metadata VALUES ('json', ?)", (json.dumps({"vector_layers": [{"id": layer}]}),))
        conn.commit(); conn.close()
    else:
        p.write_bytes(content)
    return p


def test_B1_unreadable_mbtiles_logs_warning_and_keeps_return_shape(tmp_path, monkeypatch, caplog):
    _tile_root_with(tmp_path, "storm_surge", "tokyo_storm_surge.mbtiles", b"this is not a sqlite database" * 50)
    monkeypatch.setattr(hazards, "_TILE_ROOT", tmp_path)
    with caplog.at_level(logging.WARNING, logger=hazards.logger.name):
        result = hazards._find_tileset_for_region("storm_surge", "tokyo")
    # 返り値仕様は不変: tileset_idは返し、source_layerだけNone
    assert result == {"tileset_id": "tokyo_storm_surge", "source_layer": None}
    msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("tileset metadata unreadable" in m and "tokyo_storm_surge.mbtiles" in m for m in msgs), msgs


# VPSで tileset_source_layer が null になっていた3系統（実tileset名と実layer名）
@pytest.mark.parametrize("hazard_type,stem", [
    ("storm_surge", "tokyo_storm_surge"),
    ("flood", "tokyo_flood_max"),
    ("tsunami", "tokyo_tsunami_A40-23_13"),
])
def test_B2_readable_mbtiles_resolves_non_null_source_layer(tmp_path, monkeypatch, caplog, hazard_type, stem):
    _tile_root_with(tmp_path, hazard_type, f"{stem}.mbtiles", None, layer=stem)
    monkeypatch.setattr(hazards, "_TILE_ROOT", tmp_path)
    with caplog.at_level(logging.WARNING, logger=hazards.logger.name):
        result = hazards._find_tileset_for_region(hazard_type, "tokyo")
    assert result == {"tileset_id": stem, "source_layer": stem}
    assert result["source_layer"] is not None
    assert not [r for r in caplog.records if "unreadable" in r.getMessage()]


# ── C. 実権限（Docker）: 権限matrix ───────────────────────────────────────────

def _docker_ready() -> bool:
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "image", "inspect", "python:3.11-slim"], capture_output=True)
    return r.returncode == 0


@pytest.mark.skipif(not _docker_ready(), reason="docker / python:3.11-slim が利用できない")
def test_C_permission_matrix_flat_mirror_backend_public_can_read_all_mbtiles():
    vol = f"ohg2-mbtiles-contract-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "volume", "create", vol], check=True, capture_output=True)
    try:
        proc = subprocess.run(
            ["docker", "run", "--rm", "--user", "0:0",
             "-v", f"{vol}:/data_runtime",
             "-v", f"{REPO_ROOT}/backend/app:/app/app:ro",
             "-v", f"{REPO_ROOT}/scripts:/scripts:ro",
             "-v", f"{MATRIX}:/perm_test.py:ro",
             "python:3.11-slim", "python3", "/perm_test.py"],
            capture_output=True, text=True, timeout=300,
        )
    finally:
        subprocess.run(["docker", "volume", "rm", "-f", vol], capture_output=True)
    line = next((l for l in reversed(proc.stdout.splitlines()) if l.strip().startswith("{") and '"results"' in l), None)
    assert line, (proc.stdout + proc.stderr)[-1500:]
    results = json.loads(line)["results"]
    flat = [r for r in results if "flat mirror" in r["name"]]
    assert len(flat) >= 15, f"flat mirror項目が不足: {len(flat)}"
    failed = [(r["name"], r["detail"]) for r in results if not r["pass"]]
    assert not failed, failed
    names = " ".join(r["name"] for r in flat)
    for needle in ("root cause再現", "baseline", "group単独", "mode単独", "自動修復", "新規directory", "fail-loud"):
        assert needle in names, f"matrix項目が欠落: {needle}"

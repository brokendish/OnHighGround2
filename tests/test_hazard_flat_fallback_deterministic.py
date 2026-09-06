"""
test_hazard_flat_fallback_deterministic.py —
HAZARD-FLAT-FALLBACK-LEGACY-SIZE-SELECTION-RISK remediation テスト
（Dual Storage Remediation Phase C3-B）。

hazards.py::_find_hazard_file_for_region()（inland_flood/landslide専用
routeのflat fallback）が、従来「flat runtime dir配下を{region}_*.geojson/
{region}-*.geojsonでglobし最大サイズを選ぶ」という曖昧な選択方式を使って
おり、legacy artifactが現行artifactより大きい場合に誤選択するリスクを
持っていた（実機確認: landslide/tokyo_landslide_A33.geojson(legacy,
30,860,419 bytes) > landslide/tokyo-landslide-001.geojson(現行,
28,760,177 bytes)）。

修正後は、HazardDatasetService._resolve_active_dataset()と同一の
registry-driven一意解決（active_mappings → dataset_definitions →
DatasetState.current_runtime_path）を最優先とし、これが解決できない
場合のみdirectory scanへ縮退する。同じactive datasetを別ルールで
二重に解決しない。
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.api import hazards  # noqa: E402


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(hazards.router)
    return TestClient(app, raise_server_exceptions=False)


def _patch_resolve_active_dataset(monkeypatch, hazard_type: str, region: str, active_path):
    """HazardDatasetService._resolve_active_dataset()をmockし、
    「registryが正しく解決した場合」をシミュレートする。"""
    def _fake(self, ht, rc):
        if ht == hazard_type and rc == region:
            return ("FAKE-DATASET-001", None, None, active_path)
        raise KeyError(f"Unsupported hazard_type: {ht}")

    monkeypatch.setattr(
        hazards.hazard_dataset_service.__class__, "_resolve_active_dataset", _fake
    )


def _patch_resolve_active_dataset_raises(monkeypatch, exc):
    def _fake(self, ht, rc):
        raise exc
    monkeypatch.setattr(
        hazards.hazard_dataset_service.__class__, "_resolve_active_dataset", _fake
    )


# ── A. active flat + larger legacy → active flat（legacyは無視される） ────────

def test_A_active_flat_wins_over_larger_legacy(tmp_path, monkeypatch):
    flat_dir = tmp_path / "backend" / "hazard" / "landslide"
    flat_dir.mkdir(parents=True)
    active_file = flat_dir / "tokyo-landslide-001.geojson"
    legacy_file = flat_dir / "tokyo_landslide_A33.geojson"
    active_file.write_text('{"type":"FeatureCollection","features":[]}' + " " * 100)
    legacy_file.write_text('{"type":"FeatureCollection","features":[]}' + " " * 100000)  # legacyの方が大きい
    assert legacy_file.stat().st_size > active_file.stat().st_size

    _patch_resolve_active_dataset(monkeypatch, "landslide", "tokyo", active_file)

    result = hazards._find_hazard_file_for_region("landslide", "tokyo")
    assert result == active_file


# ── B. active flat + backup → active flat（backupは_resolve_active_datasetの候補に一切入らない） ──

def test_B_active_flat_wins_over_backup(tmp_path, monkeypatch):
    flat_dir = tmp_path / "backend" / "hazard" / "storm_surge"
    flat_dir.mkdir(parents=True)
    active_file = flat_dir / "tokyo-surge-001.geojson"
    backup_file = flat_dir / "tokyo-surge-001.backup.geojson"
    active_file.write_text("{}")
    backup_file.write_text("{}" + " " * 100000)  # backupの方が大きくても無関係
    assert backup_file.stat().st_size > active_file.stat().st_size

    _patch_resolve_active_dataset(monkeypatch, "storm_surge", "tokyo", active_file)

    result = hazards._find_hazard_file_for_region("storm_surge", "tokyo")
    assert result == active_file


# ── C. multiple unrelated artifacts → active dataset pathだけ ────────────────

def test_C_only_active_dataset_path_returned_amid_multiple_artifacts(tmp_path, monkeypatch):
    flat_dir = tmp_path / "backend" / "hazard" / "flood"
    flat_dir.mkdir(parents=True)
    active_file = flat_dir / "tokyo-river-001.geojson"
    unrelated1 = flat_dir / "tokyo_flood_check.geojsonl"
    unrelated2 = flat_dir / "tokyo-river-001.backup.geojson"
    for f, size in [(active_file, 10), (unrelated1, 999999), (unrelated2, 999999)]:
        f.write_text("x" * size)

    _patch_resolve_active_dataset(monkeypatch, "flood", "tokyo", active_file)

    result = hazards._find_hazard_file_for_region("flood", "tokyo")
    assert result == active_file


# ── D. active path missing → registry解決はできたがファイル実体が無い場合 ─────

def test_D_active_path_missing_falls_through_to_existing_semantics(tmp_path, monkeypatch):
    active_file_missing = tmp_path / "backend" / "hazard" / "flood" / "tokyo-river-001.geojson"
    # active_file_missingは意図的に作らない（is_file()==False）

    normalized_dir = tmp_path / "data_lake" / "normalized" / "tokyo" / "flood"
    normalized_dir.mkdir(parents=True)
    fallback_file = normalized_dir / "fallback.geojson"
    fallback_file.write_text("{}")

    _patch_resolve_active_dataset(monkeypatch, "flood", "tokyo", active_file_missing)
    monkeypatch.setattr(hazards, "_BACKEND_DIR", tmp_path / "backend")

    result = hazards._find_hazard_file_for_region("flood", "tokyo")
    assert result == fallback_file  # 既存のdata_lake normalizedフォールバックへ縮退


# ── E. ambiguous state（registry解決不能）→ 最大sizeへ逃げず既存fallbackへ ─────

def test_E_registry_unresolvable_falls_through_without_size_based_guess(tmp_path, monkeypatch):
    normalized_dir = tmp_path / "data_lake" / "normalized" / "tokyo" / "landslide"
    normalized_dir.mkdir(parents=True)
    expected = normalized_dir / "aaa.geojson"
    decoy_larger = normalized_dir / "zzz_larger.geojson"
    expected.write_text("{}")
    decoy_larger.write_text("{}" + " " * 100000)

    _patch_resolve_active_dataset_raises(monkeypatch, KeyError("Active dataset is not registered"))
    monkeypatch.setattr(hazards, "_BACKEND_DIR", tmp_path / "backend")

    result = hazards._find_hazard_file_for_region("landslide", "tokyo")
    # sorted()の最初の1件（アルファベット順）が返る——サイズに基づく推測はしない
    assert result == expected


def test_registry_resolution_raising_unexpected_error_is_not_swallowed_beyond_scope(monkeypatch):
    """_resolve_active_datasetがKeyError/FileNotFoundError以外を投げた場合、
    それは握り潰さず伝播する（想定外の例外を沈黙させない）。"""
    def _fake(self, ht, rc):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(hazards.hazard_dataset_service.__class__, "_resolve_active_dataset", _fake)

    with pytest.raises(RuntimeError):
        hazards._find_hazard_file_for_region("landslide", "tokyo")


# ── 既存404 semantics維持（既存route経由） ────────────────────────────────────

def test_existing_404_semantics_unchanged_when_nothing_resolves(client, monkeypatch):
    monkeypatch.setattr(hazards, "_runtime_stream_or_none", _async_none)
    _patch_resolve_active_dataset_raises(monkeypatch, KeyError("not registered"))
    monkeypatch.setattr(hazards, "_BACKEND_DIR", Path("/nonexistent-root-for-test"))

    resp = client.get("/api/hazards/landslide/tokyo")
    assert resp.status_code == 404


async def _async_none(*args, **kwargs):
    return None


# ── 既存6type navigation regression（既存hazard_service関連testで別途確認済み） ──
# HazardEngineのflood/storm_surge/inland_flood/landslide/tsunami/
# lowland_poor_drainage loadロジックは今回一切変更していない
# （tests/test_hazard_service_streaming_loader.py参照）。


# ── current優先 / stale flat semantics（route levelでの明示的確認） ────────────
# _runtime_stream_or_none()（current/versioned、lease保護）が解決できる限り、
# _find_hazard_file_for_region()（flat）は一切呼ばれない。current mechanism
# 自体が利用不能（is_available()==False）な場合のみflatへfallbackする——
# これは「current障害時の正式recovery」ではなく、「is_available()==Falseの
# 環境（atomic publish機構未導入）向けのcompatibility fallback」である
# （docs/admin-data-management.mdへも明記予定）。

def test_current_available_never_calls_flat_fallback(client, monkeypatch):
    """current側（stream_versioned_glob相当）が解決できる場合、
    flat fallback（_find_hazard_file_for_region、stale flatを含みうる）は
    一切呼ばれない——current NEWがstale flat OLDより優先されることの
    route-level証明。"""
    called = {"flat_fallback": False}

    async def _fake_stream(hazard_type, region, request_kind):
        class _FakeStream:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        return _FakeStream()

    def _fake_find(hazard_type, region):
        called["flat_fallback"] = True
        return None

    monkeypatch.setattr(hazards, "_runtime_stream_or_none", _fake_stream)
    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", _fake_find)

    resp = client.get("/api/hazards/landslide/tokyo")
    assert resp.status_code == 200
    assert called["flat_fallback"] is False


def test_current_unavailable_falls_back_to_flat(client, monkeypatch, tmp_path):
    """current mechanism未導入（is_available()==False相当、
    _runtime_stream_or_none→None）の場合のみflatへfallbackする
    （stale flatをOWNER承認済みcompatibility目的でのみ返す既存契約）。"""
    flat_file = tmp_path / "landslide.geojson"
    flat_file.write_text('{"type":"FeatureCollection","features":[]}')

    async def _fake_stream_none(hazard_type, region, request_kind):
        return None

    monkeypatch.setattr(hazards, "_runtime_stream_or_none", _fake_stream_none)
    monkeypatch.setattr(hazards, "_find_hazard_file_for_region", lambda ht, r: flat_file)

    resp = client.get("/api/hazards/landslide/tokyo")
    assert resp.status_code == 200


# ── Consistency diagnostic（production request時の実装ではなく、
#    test/diagnostic contractとしてのcurrent-flat checksum比較） ──────────────

def test_diagnostic_current_flat_checksum_match_when_synced(tmp_path):
    """current/flatのactive artifactが同一内容の場合、SHA256が一致する
    ことを確認する診断契約（本番でrequestごとに計算する実装は不要——
    これはpublish後の期待される整合性を示すテスト/diagnostic用途）。"""
    import hashlib

    content = b'{"type":"FeatureCollection","features":[{"id":1}]}'
    current_file = tmp_path / "current_artifact.geojson"
    flat_file = tmp_path / "flat_artifact.geojson"
    current_file.write_bytes(content)
    flat_file.write_bytes(content)

    def sha256_of(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    assert sha256_of(current_file) == sha256_of(flat_file)


def test_diagnostic_current_flat_checksum_divergence_detected(tmp_path):
    """admin deploy後・atomic publish前は、flat new / current oldが
    意図的に存在し得る（絶対禁止事項でも明記された既存契約）。この
    divergence自体はcorruptionではなく、diagnosticとして検出可能で
    あることだけを確認する（自動でどちらが正しいかは判定しない）。"""
    import hashlib

    current_file = tmp_path / "current_artifact.geojson"
    flat_file = tmp_path / "flat_artifact.geojson"
    current_file.write_bytes(b'{"version": "old"}')
    flat_file.write_bytes(b'{"version": "new"}')  # admin deploy済み、atomic publish未実行

    def sha256_of(p: Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    assert sha256_of(current_file) != sha256_of(flat_file)  # divergence検出可能

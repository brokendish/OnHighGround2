"""
test_jartic_traffic_service.py — jartic_traffic_service ユニットテスト

外部 API は一切呼ばない（JARTIC_TRAFFIC_USE_MOCK=true を使用）。
- APIキー未設定でも取得処理が実行される
- 取得成功時 status: ok
- 取得失敗時 status: unavailable
- 0台が欠損扱いにならない
- 座標欠損データを除外する
- latest_traffic.json / manifest.json が作成される（最新スナップショット）
- 履歴ファイルが作成されない
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def _run(coro):
    return asyncio.run(coro)


# ── normalize_feature ─────────────────────────────────────────────────────────

def test_normalize_feature_basic():
    from app.services.jartic_traffic_service import normalize_feature
    feature = {
        "geometry": {"type": "MultiPoint", "coordinates": [[139.7, 35.6]]},
        "properties": {
            "常時観測点コード": "X001",
            "観測年月日": 20260629,
            "時間帯": 1000,
            "上り・小型交通量": 200,
            "上り・大型交通量": 50,
            "上り・車種判別不能交通量": 10,
            "下り・小型交通量": 180,
            "下り・大型交通量": 40,
            "下り・車種判別不能交通量": 5,
        },
    }
    result = normalize_feature(feature)
    assert result is not None
    assert result["code"] == "X001"
    assert result["lat"] == 35.6
    assert result["lon"] == 139.7
    assert result["up"]  == 260
    assert result["down"] == 225
    assert result["total"] == 485
    assert result["small"] == 380
    assert result["large"] == 90


def test_normalize_feature_zero_is_valid():
    from app.services.jartic_traffic_service import normalize_feature
    feature = {
        "geometry": {"type": "MultiPoint", "coordinates": [[139.7, 35.6]]},
        "properties": {
            "常時観測点コード": "X002",
            "観測年月日": 20260629,
            "時間帯": 1000,
            "上り・小型交通量": 0,
            "上り・大型交通量": 0,
            "上り・車種判別不能交通量": 0,
            "下り・小型交通量": 0,
            "下り・大型交通量": 0,
            "下り・車種判別不能交通量": 0,
        },
    }
    result = normalize_feature(feature)
    assert result is not None
    assert result["up"]    == 0
    assert result["down"]  == 0
    assert result["total"] == 0
    assert result["small"] == 0
    assert result["large"] == 0


def test_normalize_feature_no_coords_returns_none():
    from app.services.jartic_traffic_service import normalize_feature
    feature = {
        "geometry": {"type": "MultiPoint", "coordinates": []},
        "properties": {"常時観測点コード": "X003"},
    }
    assert normalize_feature(feature) is None


def test_normalize_feature_no_code_returns_none():
    from app.services.jartic_traffic_service import normalize_feature
    feature = {
        "geometry": {"type": "MultiPoint", "coordinates": [[139.7, 35.6]]},
        "properties": {},
    }
    assert normalize_feature(feature) is None


def test_normalize_feature_missing_direction_is_none():
    """上り・欠測=="1" のとき up は None、total も None。"""
    from app.services.jartic_traffic_service import normalize_feature
    feature = {
        "geometry": {"type": "MultiPoint", "coordinates": [[139.7, 35.6]]},
        "properties": {
            "常時観測点コード": "X004",
            "観測年月日": 20260629,
            "時間帯": 1000,
            "上り・欠測": "1",
            "下り・小型交通量": 100,
            "下り・大型交通量": 20,
        },
    }
    result = normalize_feature(feature)
    assert result is not None
    assert result["up"] is None
    assert result["down"] == 120
    assert result["total"] is None


def test_normalize_feature_both_missing_up_down_null():
    """上り・下りともに欠測なら up/down/total すべて None。"""
    from app.services.jartic_traffic_service import normalize_feature
    feature = {
        "geometry": {"type": "MultiPoint", "coordinates": [[139.7, 35.6]]},
        "properties": {
            "常時観測点コード": "X005",
            "観測年月日": 20260629,
            "時間帯": 1000,
            "上り・欠測": "1",
            "下り・欠測": "1",
        },
    }
    result = normalize_feature(feature)
    assert result is not None
    assert result["up"]    is None
    assert result["down"]  is None
    assert result["total"] is None


# ── status 分類（/live の classify_volume を流用） ───────────────────────────────

def test_normalize_feature_status_matches_live_classify_volume():
    """jartic_traffic_service の status は /live の classify_volume と同一結果になる。"""
    from app.services.jartic_traffic_service import normalize_feature
    from app.services.live_road_traffic_service import classify_volume

    feature = {
        "geometry": {"type": "MultiPoint", "coordinates": [[139.7, 35.6]]},
        "properties": {
            "常時観測点コード": "X010",
            "観測年月日": 20260629,
            "時間帯": 1000,
            "上り・小型交通量": 140,
            "上り・大型交通量": 20,
            "上り・車種判別不能交通量": 0,
            "下り・小型交通量": 5,
            "下り・大型交通量": 0,
            "下り・車種判別不能交通量": 0,
        },
    }
    result = normalize_feature(feature)
    assert result is not None
    # 上り = 160台 → very_high、下り = 5台 → low（/live と同一の閾値関数を使用）
    assert result["status_up"]   == classify_volume(160, None)
    assert result["status_down"] == classify_volume(5, None)
    assert result["status_up"]   == "very_high"
    assert result["status_down"] == "low"
    # マーカー色に使う status は severity の高い方（very_high）
    assert result["status"] == "very_high"
    assert result["status_label"] == "交通量非常に多い"


def test_normalize_feature_status_unknown_when_missing():
    """上り・下りとも欠測なら status は unknown（'状態不明'）になる。"""
    from app.services.jartic_traffic_service import normalize_feature
    feature = {
        "geometry": {"type": "MultiPoint", "coordinates": [[139.7, 35.6]]},
        "properties": {
            "常時観測点コード": "X011",
            "観測年月日": 20260629,
            "時間帯": 1000,
            "上り・欠測": "1",
            "下り・欠測": "1",
        },
    }
    result = normalize_feature(feature)
    assert result is not None
    assert result["status"] == "unknown"
    assert result["status_label"] == "状態不明"


def test_mock_items_include_status_fields():
    """モックモードでも status/status_label が付与される。"""
    import app.services.jartic_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0

    with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "true"}):
        result = _run(svc.get_traffic_observations())

    assert result["status"] == "ok"
    for item in result["items"]:
        assert "status" in item
        assert "status_label" in item

    statuses = {it["status"] for it in result["items"]}
    assert len(statuses) >= 2, "モックデータは複数カテゴリを含むこと"


# ── _filter_bbox ──────────────────────────────────────────────────────────────

def test_filter_bbox_inside():
    from app.services.jartic_traffic_service import _filter_bbox
    items = [{"lat": 35.0, "lon": 139.0}, {"lat": 36.0, "lon": 140.0}]
    result = _filter_bbox(items, "138.0,34.0,140.5,36.5")
    assert len(result) == 2


def test_filter_bbox_outside():
    from app.services.jartic_traffic_service import _filter_bbox
    items = [{"lat": 35.0, "lon": 139.0}, {"lat": 40.0, "lon": 145.0}]
    result = _filter_bbox(items, "138.0,34.0,140.0,36.0")
    assert len(result) == 1
    assert result[0]["lat"] == 35.0


def test_filter_bbox_none_returns_all():
    from app.services.jartic_traffic_service import _filter_bbox
    items = [{"lat": 35.0, "lon": 139.0}, {"lat": 40.0, "lon": 145.0}]
    result = _filter_bbox(items, None)
    assert len(result) == 2


# ── get_traffic_observations (mock mode) ─────────────────────────────────────

def test_get_observations_ok_with_mock():
    """APIキー不要: モックモードで status=ok が返る。"""
    import app.services.jartic_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0

    with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "true"}):
        result = _run(svc.get_traffic_observations())

    assert result["status"] == "ok"
    assert isinstance(result["items"], list)
    assert len(result["items"]) > 0


def test_get_observations_no_api_key_still_tries():
    """JARTIC_TRAFFIC_USE_MOCK が false でも APIキー未設定で即 unavailable にならない。"""
    import app.services.jartic_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0

    with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "false"},
                    clear=False):
        env = {k: v for k, v in os.environ.items()}
        env.pop("JARTIC_API_KEY", None)  # 未設定を確認

        from unittest.mock import AsyncMock
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(return_value=[])):
            result = _run(svc.get_traffic_observations())

    # APIキーがなくても取得を試みた結果 status=ok（items=0 でも ok）
    assert result["status"] == "ok"
    assert result["items"] == []


def test_get_observations_fetch_failure_returns_unavailable():
    """通信失敗時のみ unavailable になる。"""
    import app.services.jartic_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0

    from unittest.mock import AsyncMock
    with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "false"}):
        with patch.object(svc, "_fetch_all_items", new=AsyncMock(side_effect=URLError("timeout"))):
            result = _run(svc.get_traffic_observations())

    assert result["status"] == "unavailable"
    assert result["items"] == []


def test_get_observations_bbox_filters():
    """bbox パラメータで BBOX 外の観測点が除外される。"""
    import app.services.jartic_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0

    with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "true"}):
        # M001(lat=35.68, lon=139.77) はこの bbox に入る
        result = _run(svc.get_traffic_observations(bbox="139.5,35.5,140.0,36.0"))

    assert result["status"] == "ok"
    assert all(
        139.5 <= it["lon"] <= 140.0 and 35.5 <= it["lat"] <= 36.0
        for it in result["items"]
    )


def test_mock_zero_traffic_preserved():
    """モックデータに 0台 のデータがあっても欠損扱いにならない。"""
    import app.services.jartic_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0

    with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "true"}):
        result = _run(svc.get_traffic_observations())

    zero_items = [it for it in result["items"] if it.get("up") == 0 and it.get("down") == 0]
    assert len(zero_items) > 0, "0台の観測点がモックに存在するはず"


def test_snapshot_file_created(tmp_path):
    """取得成功時に latest_traffic.json と manifest.json が作成される（履歴ファイルは作らない）。"""
    import app.services.jartic_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0

    snapshot_path = tmp_path / "jartic" / "latest_traffic.json"
    manifest_path = tmp_path / "jartic" / "manifest.json"

    with patch.object(svc, "_SNAPSHOT_PATH", snapshot_path), \
         patch.object(svc, "_MANIFEST_PATH", manifest_path):
        with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "true"}):
            _run(svc.get_traffic_observations())

    assert snapshot_path.exists()
    assert manifest_path.exists()
    data = json.loads(snapshot_path.read_text())
    assert data["status"] == "ok"
    manifest = json.loads(manifest_path.read_text())
    assert manifest["status"] == "ok"
    assert manifest["item_count"] == len(data["items"])

    # 履歴ファイルが存在しないこと（最新スナップショット + manifest のみ）
    jar_dir = snapshot_path.parent
    files = sorted(p.name for p in jar_dir.iterdir())
    assert files == ["latest_traffic.json", "manifest.json"], f"履歴ファイルが増えていない: {files}"


def test_no_history_files_accumulated(tmp_path):
    """複数回呼び出しても latest_traffic.json / manifest.json だけ。"""
    import app.services.jartic_traffic_service as svc
    snapshot_path = tmp_path / "jartic" / "latest_traffic.json"
    manifest_path = tmp_path / "jartic" / "manifest.json"

    with patch.object(svc, "_SNAPSHOT_PATH", snapshot_path), \
         patch.object(svc, "_MANIFEST_PATH", manifest_path):
        with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "true"}):
            for _ in range(3):
                svc._cache = None; svc._cache_at = 0.0
                _run(svc.get_traffic_observations())

    jar_dir = snapshot_path.parent
    files = sorted(p.name for p in jar_dir.iterdir())
    assert files == ["latest_traffic.json", "manifest.json"]


# ── _build_wfs_url（APIキーなし確認） ────────────────────────────────────────

def test_build_wfs_url_no_api_key():
    """構築した URL に x-api-key パラメータが含まれない。"""
    from app.services.jartic_traffic_service import _build_wfs_url
    url = _build_wfs_url("https://api.jartic-open-traffic.org/geoserver")
    assert "x-api-key" not in url
    assert "GetFeature" in url
    assert "t_travospublic_measure_5m" in url


def test_build_wfs_url_has_time_code():
    """URL に 時間コード フィルターが含まれる（URLエンコード済み）。"""
    from urllib.parse import unquote
    from app.services.jartic_traffic_service import _build_wfs_url
    url = _build_wfs_url("https://example.com/geoserver")
    decoded = unquote(url)
    assert "時間コード" in decoded


# ── source フィールド ─────────────────────────────────────────────────────────

# ── data_runtime/cache boundary移行（Residual Finding Remediation 01） ───────────

def test_snapshot_and_manifest_paths_are_absolute():
    """CWD依存を残さない: _SNAPSHOT_PATH / _MANIFEST_PATH は絶対pathで解決される。"""
    import app.services.jartic_traffic_service as svc

    assert svc._SNAPSHOT_PATH.is_absolute()
    assert svc._MANIFEST_PATH.is_absolute()


def test_default_cache_dir_is_under_data_runtime_cache_jartic():
    import app.services.jartic_traffic_service as svc

    assert svc._SNAPSHOT_PATH.parent.parts[-3:] == ("data_runtime", "cache", "jartic")
    assert svc._MANIFEST_PATH.parent == svc._SNAPSHOT_PATH.parent


def test_save_snapshot_write_failure_is_graceful(tmp_path):
    """permission denied相当のwrite失敗でも例外を外へ漏らさない（graceful handling）。"""
    import app.services.jartic_traffic_service as svc

    snapshot_path = tmp_path / "jartic" / "latest_traffic.json"
    manifest_path = tmp_path / "jartic" / "manifest.json"

    with patch.object(svc, "_SNAPSHOT_PATH", snapshot_path), \
         patch.object(svc, "_MANIFEST_PATH", manifest_path), \
         patch.object(Path, "write_text", side_effect=PermissionError("[Errno 13] Permission denied")):
        svc._save_snapshot({"status": "ok", "updated_at": "2026-09-06T00:00:00+09:00", "items": []})

    assert not snapshot_path.exists()


def test_source_in_response():
    import app.services.jartic_traffic_service as svc
    svc._cache = None; svc._cache_at = 0.0

    with patch.dict(os.environ, {"JARTIC_TRAFFIC_USE_MOCK": "true"}):
        result = _run(svc.get_traffic_observations())

    assert "source" in result
    assert "JARTIC" in result["source"]

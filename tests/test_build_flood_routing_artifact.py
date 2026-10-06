"""
build_flood_routing_artifact.py / validate_flood_routing_artifact.py の回帰テスト

不変条件:
  1. false negative なし: canonical 内の点は必ずいずれかの出力 bbox に含まれる
  2. 穴あき Polygon の穴の中心は（充填率条件により）出力 bbox に含まれない
  3. 出力 bbox の総面積が canonical の bbox 総面積より小さい（false positive 抑制）
  4. flood_rank は交差する canonical の最大値
  5. canonical 入力ファイルを変更しない
  6. 決定的: 同じ入力・設定から同一バイト列（meta も generated_at 以外一致）
  7. τ 既定値 0.85、meta 必須項目
  8. 失敗時に既存 derived artifact を壊さず、一時ファイルを残さない
  9. routing validation: 正常系 PASS、bbox 欠落（FN）・sha 不一致を検出
"""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

shapely = pytest.importorskip("shapely")
from shapely.geometry import Point, Polygon, shape  # noqa: E402

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts" / "derive"))
import build_flood_routing_artifact as bfr  # noqa: E402


def _load_validator():
    spec = importlib.util.spec_from_file_location(
        "validate_flood_routing_artifact", ROOT / "scripts" / "validate" / "validate_flood_routing_artifact.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_canonical(path: Path, feats: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write('{"type":"FeatureCollection","name":"flood_merged","features":[\n')
        f.write(",\n".join(json.dumps(x, separators=(",", ":")) for x in feats))
        f.write("\n]}\n")


def _feat(geom: Polygon, rank: int) -> dict:
    return {
        "type": "Feature",
        "properties": {"hazard_type": "flood", "flood_rank": rank, "dataset_id": "T"},
        "geometry": shapely.geometry.mapping(geom),
    }


# 外周 0.01° 四方・中央に 0.008° 四方の穴（充填率 0.36 < 0.85 のドーナツ）＋ 細長い L 字 ＋ 隣接する小矩形
DONUT = Polygon(
    [(139.0, 35.0), (139.01, 35.0), (139.01, 35.01), (139.0, 35.01)],
    [[(139.001, 35.001), (139.009, 35.001), (139.009, 35.009), (139.001, 35.009)]],
)
L_SHAPE = Polygon([(139.02, 35.0), (139.03, 35.0), (139.03, 35.001), (139.021, 35.001),
                   (139.021, 35.01), (139.02, 35.01)])
SMALL_A = Polygon([(139.04, 35.0), (139.0401, 35.0), (139.0401, 35.0001), (139.04, 35.0001)])
SMALL_B = Polygon([(139.0401, 35.0), (139.0402, 35.0), (139.0402, 35.0001), (139.0401, 35.0001)])
ALL = (DONUT, L_SHAPE, SMALL_A, SMALL_B)


def _paths(tmp_path: Path):
    canonical = tmp_path / "data_lake" / "validated" / "tokyo" / "flood" / "t.geojson"
    routing = tmp_path / "data_lake" / "derived" / "tokyo" / "flood" / "t.routing.geojson"
    meta = routing.with_name("t.routing.meta.json")
    return canonical, routing, meta


@pytest.fixture
def built(tmp_path):
    canonical, routing, meta_path = _paths(tmp_path)
    _write_canonical(canonical, [_feat(DONUT, 2), _feat(L_SHAPE, 4), _feat(SMALL_A, 1), _feat(SMALL_B, 3)])
    digest = hashlib.sha256(canonical.read_bytes()).hexdigest()
    meta = bfr.build(canonical, routing, "T")
    feats = json.loads(routing.read_text(encoding="utf-8"))["features"]
    return canonical, digest, routing, meta_path, meta, feats


def _bboxes(feats):
    return [shape(f["geometry"]).bounds for f in feats]


def _in_any(bboxes, x, y):
    return any(x0 <= x <= x1 and y0 <= y <= y1 for x0, y0, x1, y1 in bboxes)


def test_no_false_negative_on_dense_sample(built):
    *_, feats = built
    boxes = _bboxes(feats)
    for poly in ALL:
        x0, y0, x1, y1 = poly.bounds
        n = 60
        for i in range(n + 1):
            for j in range(n + 1):
                x = x0 + (x1 - x0) * i / n
                y = y0 + (y1 - y0) * j / n
                if poly.covers(Point(x, y)):
                    assert _in_any(boxes, x, y), (x, y)


def test_hole_center_is_not_flagged(built):
    *_, feats = built
    assert not _in_any(_bboxes(feats), 139.005, 35.005)


def test_bbox_area_smaller_than_naive(built):
    *_, feats = built
    naive = sum((p.bounds[2] - p.bounds[0]) * (p.bounds[3] - p.bounds[1]) for p in ALL)
    routed = sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in _bboxes(feats))
    assert routed < naive * 0.7


def test_output_is_rectangles_with_valid_rank(built):
    *_, feats = built
    for f in feats:
        ring = f["geometry"]["coordinates"][0]
        assert len(ring) == 5 and ring[0] == ring[-1]
        assert 1 <= f["properties"]["flood_rank"] <= 5
        assert f["properties"]["hazard_type"] == "flood"
        assert f["properties"]["dataset_id"] == "T"


def test_rank_is_max_of_intersecting_canonical(built):
    *_, feats = built
    # 隣接する SMALL_A(rank1)/SMALL_B(rank3) は union されるため最大 rank 3 になる（安全側）
    ranks = [f["properties"]["flood_rank"] for f in feats
             if shape(f["geometry"]).intersects(SMALL_A) or shape(f["geometry"]).intersects(SMALL_B)]
    assert ranks and max(ranks) == 3
    l_ranks = {f["properties"]["flood_rank"] for f in feats if shape(f["geometry"]).within(L_SHAPE.envelope)
               and shape(f["geometry"]).intersects(L_SHAPE)}
    assert l_ranks == {4}


def test_canonical_input_unchanged(built):
    canonical, digest, *_ = built
    assert hashlib.sha256(canonical.read_bytes()).hexdigest() == digest


def test_default_tau_is_085_and_meta_fields(built):
    canonical, digest, routing, meta_path, meta, feats = built
    assert bfr.DEFAULT_TAU == 0.85
    on_disk = json.loads(meta_path.read_text(encoding="utf-8"))
    assert on_disk == meta
    assert meta["tau"] == 0.85
    assert meta["min_split_size"] == bfr.DEFAULT_MIN_SPLIT_SIZE
    assert meta["dataset_id"] == "T"
    assert meta["source_canonical_path"] == str(canonical)
    assert meta["source_canonical_sha256"] == digest
    assert meta["routing_artifact_sha256"] == hashlib.sha256(routing.read_bytes()).hexdigest()
    assert meta["builder_name"] == "build_flood_routing_artifact"
    assert meta["builder_version"]
    assert meta["feature_count"] == len(feats)
    assert meta["generated_at"].endswith("Z")


def test_deterministic_output(tmp_path, built):
    canonical, _, routing, _, meta1, _ = built
    other = tmp_path / "again" / "t.routing.geojson"
    meta2 = bfr.build(canonical, other, "T")
    assert other.read_bytes() == routing.read_bytes()
    strip = lambda m: {k: v for k, v in m.items() if k not in ("generated_at", "build_seconds")}  # noqa: E731
    assert strip(meta1) == strip(meta2)


def test_no_temp_files_left_after_success(built):
    _, _, routing, *_ = built
    assert sorted(p.name for p in routing.parent.iterdir()) == ["t.routing.geojson", "t.routing.meta.json"]


def test_failure_keeps_existing_artifact_and_cleans_up(built, monkeypatch):
    canonical, _, routing, meta_path, _, _ = built
    before = (routing.read_bytes(), meta_path.read_bytes())

    def _boom(*_a, **_k):
        raise ValueError("forced failure")

    monkeypatch.setattr(bfr, "_process_tile", _boom)
    with pytest.raises(ValueError, match="forced failure"):
        bfr.build(canonical, routing, "T")
    assert (routing.read_bytes(), meta_path.read_bytes()) == before
    assert sorted(p.name for p in routing.parent.iterdir()) == ["t.routing.geojson", "t.routing.meta.json"]


def test_output_name_must_be_routing(tmp_path, built):
    canonical, *_ = built
    with pytest.raises(ValueError, match="routing"):
        bfr.build(canonical, tmp_path / "x.geojson", "T")


def test_tile_boundary_crossing_polygon_has_no_false_negative(tmp_path):
    big = Polygon([(138.995, 34.995), (139.025, 34.995), (139.025, 35.025), (138.995, 35.025)],
                  [[(139.0, 35.0), (139.02, 35.0), (139.02, 35.02), (139.0, 35.02)]])
    canonical, routing, _ = _paths(tmp_path)
    _write_canonical(canonical, [_feat(big, 5)])
    bfr.build(canonical, routing, "T", tile_size=0.01)
    boxes = _bboxes(json.loads(routing.read_text(encoding="utf-8"))["features"])
    for i in range(121):
        for j in range(121):
            x = 138.995 + 0.03 * i / 120
            y = 34.995 + 0.03 * j / 120
            if big.covers(Point(x, y)):
                assert _in_any(boxes, x, y), (x, y)
    assert not _in_any(boxes, 139.01, 35.01)  # 穴の中心


def test_empty_input_fails_without_output(tmp_path):
    canonical, routing, meta_path = _paths(tmp_path)
    _write_canonical(canonical, [])
    with pytest.raises(ValueError):
        bfr.build(canonical, routing, "T")
    assert not routing.exists() and not meta_path.exists()
    assert list(routing.parent.iterdir()) == []


def test_clip_failure_falls_back_without_false_negative(tmp_path, monkeypatch):
    """GEOS の clip が失敗しても断片を捨てず、元形状の bbox で出力する（安全側）。"""
    def _always_fail(*_args, **_kwargs):
        raise bfr._ClipFailed("forced")

    monkeypatch.setattr(bfr, "_clip", _always_fail)
    canonical, routing, _ = _paths(tmp_path)
    _write_canonical(canonical, [_feat(DONUT, 2)])
    bfr.build(canonical, routing, "T")
    boxes = _bboxes(json.loads(routing.read_text(encoding="utf-8"))["features"])
    for x, y in [(139.0005, 35.0005), (139.0095, 35.0095), (139.0005, 35.0095)]:
        assert _in_any(boxes, x, y)


# ── routing validation（validate_flood_routing_artifact.py） ───────────────────

def test_routing_validation_passes(built):
    canonical, *_ = built
    result = _load_validator().validate(canonical, "T")
    assert result["coverage_false_negatives"] == 0


def test_routing_validation_detects_false_negative(built):
    canonical, _, routing, meta_path, meta, feats = built
    # DONUT を覆う矩形を取り除き、meta の sha も合わせる（契約は通るが被覆が欠ける）
    kept = [f for f in feats if not shape(f["geometry"]).intersects(DONUT)]
    text = ('{"type":"FeatureCollection","name":"flood_routing","features":[\n'
            + ",\n".join(json.dumps(f, ensure_ascii=False, separators=(",", ":")) for f in kept) + "\n]}\n")
    routing.write_text(text, encoding="utf-8")
    meta.update(feature_count=len(kept), routing_artifact_sha256=hashlib.sha256(text.encode()).hexdigest())
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(ValueError, match="false negative"):
        _load_validator().validate(canonical, "T")


def test_routing_validation_rejects_stale_routing(built):
    canonical, *_ = built
    _write_canonical(canonical, [_feat(DONUT, 2)])  # canonical 更新後に routing を再生成していない
    with pytest.raises(ValueError, match="canonical sha256"):
        _load_validator().validate(canonical, "T")


def test_lossy_clip_is_rejected_by_area_check(tmp_path, monkeypatch):
    """clip が断片の一部を落とす異常（実データで clip_by_rect が起こした false negative）でも、
    面積保存検査により分割を採用せず元断片の bbox で出力する（安全側）。"""
    real_clip = bfr._clip

    def _lossy(geom, x0, y0, x1, y1):
        part = real_clip(geom, x0, y0, x1, y1)
        return part.buffer(-0.0003) if part.area > 1e-7 else part  # 内側を削って面積を失う

    monkeypatch.setattr(bfr, "_clip", _lossy)
    canonical, routing, _ = _paths(tmp_path)
    _write_canonical(canonical, [_feat(DONUT, 2)])
    bfr.build(canonical, routing, "T")
    boxes = _bboxes(json.loads(routing.read_text(encoding="utf-8"))["features"])
    for i in range(41):
        for j in range(41):
            x, y = 139.0 + 0.01 * i / 40, 35.0 + 0.01 * j / 40
            if DONUT.covers(Point(x, y)):
                assert _in_any(boxes, x, y), (x, y)


def test_builder_does_not_use_dirty_clip_by_rect():
    src = (ROOT / "scripts" / "derive" / "build_flood_routing_artifact.py").read_text(encoding="utf-8")
    assert "shapely.clip_by_rect(" not in src

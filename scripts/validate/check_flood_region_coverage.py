#!/usr/bin/env python3
"""
check_flood_region_coverage.py — 洪水 canonical の地域 coverage を読み取り専用で点検する。

KANAGAWA-RIVER-001 provenance mismatch（東京原本 A31a-25_13_* から生成）の修復受入で、
新しい canonical が対象地域を覆うことを数値で確認するための道具。データは一切書き換えない。

出力（JSON）:
  - feature_count / bbox（全 feature の座標範囲）
  - meshes: feature bbox 中心が属する 1 次メッシュ（JIS X 0410、80km）ごとの件数
  - boundary_bbox / boundary_meshes: --boundary 指定時、行政区域の範囲とそれが掛かる 1 次メッシュ
    （A31b はメッシュ単位配布のため、必要な A31b を公式ページで確認する材料）
  - outside_boundary_bbox: feature bbox 中心が行政区域 bbox の外にある件数
  - points: 既知地点ごとに、半径 --radius-km 以内に bbox が掛かる feature 数
  - meshes_inside_boundary: --boundary 指定時、feature bbox 中心が行政区域ポリゴン内にある件数（1 次メッシュ別）
  - acceptance: --require-meshes 指定時の受入判定
      * mesh_results: 指定メッシュごとに
          行政区域内 feature >= 1                              → PASS
          0 件 かつ --allow-empty-meshes で明示指定              → PASS_WITH_EXCEPTION（理由付き）
          0 件 かつ 明示指定なし                                → FAIL
        （0 件だからといって自動で例外にしない。例外指定メッシュに feature があれば通常の PASS）
      * 既知地点すべてで半径内に feature が 1 件以上
  --from-definition <dataset_id>: dataset_definitions.json の coverage_required_meshes /
  coverage_allow_empty_meshes を使う（CLI 引数と同時指定不可）。

使い方:
  python3 scripts/validate/check_flood_region_coverage.py \\
      --geojson data_lake/validated/kanagawa/flood/kanagawa-river-001.geojson \\
      --boundary data_lake/validated/kanagawa/boundary/kanagawa-boundary-001.geojson \\
      --preset kanagawa
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

# 既知地点（各市役所付近の概略座標。coverage 点検用で、境界判定には使わない）
PRESETS = {
    "kanagawa": {
        "川崎": (35.5308, 139.7029), "横浜": (35.4437, 139.6380), "藤沢": (35.3390, 139.4900),
        "鎌倉": (35.3192, 139.5467), "平塚": (35.3350, 139.3493), "小田原": (35.2646, 139.1522),
    },
    "tokyo": {
        "新宿": (35.6938, 139.7034), "足立": (35.7750, 139.8044), "江戸川": (35.7068, 139.8683),
        "八王子": (35.6664, 139.3160),
    },
}


def mesh1(lat: float, lon: float) -> str:
    """JIS X 0410 1 次メッシュコード（緯度 40 分 × 経度 1 度）。"""
    return f"{int(math.floor(lat * 1.5)):02d}{int(math.floor(lon - 100)):02d}"


def _walk(coords, acc):
    if coords and isinstance(coords[0], (int, float)) or (coords and hasattr(coords[0], "as_integer_ratio")):
        x, y = float(coords[0]), float(coords[1])
        acc[0], acc[1] = min(acc[0], x), max(acc[1], x)
        acc[2], acc[3] = min(acc[2], y), max(acc[3], y)
        return
    for c in coords:
        _walk(c, acc)


def iter_feature_bboxes(path: Path):
    import ijson
    with path.open("rb") as f:
        for feat in ijson.items(f, "features.item"):
            geom = feat.get("geometry") or {}
            coords = geom.get("coordinates")
            if not coords:
                continue
            acc = [math.inf, -math.inf, math.inf, -math.inf]
            if geom.get("type") == "GeometryCollection":
                for g in geom.get("geometries", []):
                    _walk(g.get("coordinates") or [], acc)
            else:
                _walk(coords, acc)
            if acc[0] != math.inf:
                yield acc  # lon_min, lon_max, lat_min, lat_max


def _bbox_near(b, lat, lon, radius_km) -> bool:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return b[0] <= lon + dlon and b[1] >= lon - dlon and b[2] <= lat + dlat and b[3] >= lat - dlat


def _boundary_polygon(boundary: Path):
    import json as _json
    from shapely.geometry import shape
    from shapely.ops import unary_union
    from shapely.prepared import prep
    feats = _json.loads(boundary.read_text(encoding="utf-8"))["features"]
    return prep(unary_union([shape(f["geometry"]).buffer(0) for f in feats if f.get("geometry")]))


EXCEPTION_REASON = ("No flood features intersect the boundary area within this mesh in the checked source data; "
                    "accepted only because the mesh is explicitly listed as allow-empty")


def check(geojson: Path, boundary: Path = None, points=None, radius_km: float = 3.0,
          require_meshes=None, allow_empty_meshes=None) -> dict:
    points = points or {}
    bb = [math.inf, -math.inf, math.inf, -math.inf]
    bnd = None
    poly = None
    inside_meshes: dict = {}
    if boundary:
        poly = _boundary_polygon(boundary)
        bnd = [math.inf, -math.inf, math.inf, -math.inf]
        for b in iter_feature_bboxes(boundary):
            bnd = [min(bnd[0], b[0]), max(bnd[1], b[1]), min(bnd[2], b[2]), max(bnd[3], b[3])]
    n, outside, meshes = 0, 0, {}
    hits = {k: 0 for k in points}
    for b in iter_feature_bboxes(geojson):
        n += 1
        bb = [min(bb[0], b[0]), max(bb[1], b[1]), min(bb[2], b[2]), max(bb[3], b[3])]
        cx, cy = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2
        m = mesh1(cy, cx)
        meshes[m] = meshes.get(m, 0) + 1
        if bnd and not (bnd[0] <= cx <= bnd[1] and bnd[2] <= cy <= bnd[3]):
            outside += 1
        elif poly is not None:
            from shapely.geometry import Point
            if poly.contains(Point(cx, cy)):
                inside_meshes[m] = inside_meshes.get(m, 0) + 1
        for k, (lat, lon) in points.items():
            if _bbox_near(b, lat, lon, radius_km):
                hits[k] += 1
    out = {
        "geojson": str(geojson),
        "feature_count": n,
        "bbox": {"lon_min": bb[0], "lon_max": bb[1], "lat_min": bb[2], "lat_max": bb[3]} if n else None,
        "meshes": dict(sorted(meshes.items())),
        "radius_km": radius_km,
        "points": {k: {"lat": lat, "lon": lon, "features_within_radius": hits[k]} for k, (lat, lon) in points.items()},
        "points_without_coverage": [k for k in points if hits[k] == 0],
    }
    if bnd:
        lat_cells = range(int(math.floor(bnd[2] * 1.5)), int(math.floor(bnd[3] * 1.5)) + 1)
        lon_cells = range(int(math.floor(bnd[0] - 100)), int(math.floor(bnd[1] - 100)) + 1)
        out["boundary_bbox"] = {"lon_min": bnd[0], "lon_max": bnd[1], "lat_min": bnd[2], "lat_max": bnd[3]}
        out["boundary_meshes"] = [f"{a:02d}{b:02d}" for a in lat_cells for b in lon_cells]
        out["outside_boundary_bbox"] = outside
        out["meshes_inside_boundary"] = dict(sorted(inside_meshes.items()))
    if require_meshes is not None:
        allow = set(allow_empty_meshes or [])
        mesh_results = {}
        for m in require_meshes:
            n = inside_meshes.get(m, 0)
            if n > 0:
                mesh_results[m] = {"inside_boundary_features": n, "status": "PASS"}
            elif m in allow:
                mesh_results[m] = {"inside_boundary_features": 0, "status": "PASS_WITH_EXCEPTION",
                                   "reason": EXCEPTION_REASON}
            else:
                mesh_results[m] = {"inside_boundary_features": 0, "status": "FAIL",
                                   "reason": "no features inside boundary and mesh is not listed as allow-empty"}
        failed = [m for m, r in mesh_results.items() if r["status"] == "FAIL"]
        out["acceptance"] = {
            "required_meshes": list(require_meshes),
            "allow_empty_meshes": sorted(allow),
            "mesh_results": mesh_results,
            "exceptions": [m for m, r in mesh_results.items() if r["status"] == "PASS_WITH_EXCEPTION"],
            "meshes_without_features_inside_boundary": [m for m in require_meshes if not inside_meshes.get(m)],
            "failed_meshes": failed,
            "points_without_coverage": out["points_without_coverage"],
            "pass": bool(boundary) and not failed and not out["points_without_coverage"],
        }
    return out


def _definition_meshes(dataset_id: str):
    reg = Path(__file__).resolve().parents[2] / "data_lake" / "registry" / "dataset_definitions.json"
    defs = json.loads(reg.read_text(encoding="utf-8"))
    d = next((x for x in defs if x.get("dataset_id") == dataset_id), None)
    if d is None:
        raise SystemExit(f"dataset definition がありません: {dataset_id}")
    req = d.get("coverage_required_meshes")
    if not req:
        raise SystemExit(f"{dataset_id} に coverage_required_meshes が定義されていません")
    return list(req), list(d.get("coverage_allow_empty_meshes") or [])


def main() -> int:
    p = argparse.ArgumentParser(description="洪水 canonical の地域 coverage 点検（読み取り専用）")
    p.add_argument("--geojson", required=True, type=Path)
    p.add_argument("--boundary", type=Path)
    p.add_argument("--preset", choices=sorted(PRESETS))
    p.add_argument("--radius-km", type=float, default=3.0)
    p.add_argument("--require-meshes", default=None,
                   help="受入判定に使う 1 次メッシュ（カンマ区切り。正式 source set の A31b メッシュ）。--boundary 必須")
    p.add_argument("--allow-empty-meshes", default=None,
                   help="公式原本上、境界内 feature 0 件を確認済みとして明示的に例外受入するメッシュ（カンマ区切り）")
    p.add_argument("--from-definition", default=None,
                   help="dataset_definitions.json の coverage_required_meshes / coverage_allow_empty_meshes を使う")
    a = p.parse_args()

    def _csv(v):
        return [m.strip() for m in v.split(",") if m.strip()] if v else None
    req, allow = _csv(a.require_meshes), _csv(a.allow_empty_meshes)
    if a.from_definition:
        if req is not None or allow is not None:
            p.error("--from-definition と --require-meshes / --allow-empty-meshes は同時に指定できません")
        req, allow = _definition_meshes(a.from_definition)
    if allow and (req is None or not set(allow) <= set(req)):
        p.error("--allow-empty-meshes は --require-meshes に含まれるメッシュだけ指定できます")
    out = check(a.geojson, a.boundary, PRESETS.get(a.preset), a.radius_km, req, allow)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("acceptance", {}).get("pass", True) else 1


if __name__ == "__main__":
    sys.exit(main())

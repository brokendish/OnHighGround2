#!/usr/bin/env python3
"""
build_road_geojson.py

OSM PBF から主要道路 GeoJSON を生成する。

出力:
  frontend/layers/roads/kanto_roads_main.geojson
      motorway / trunk / primary / secondary
      幾何的に連続するセグメントのみマージ（非隣接の同名断片は別フィーチャー）

対象タグ:
  highway=motorway, trunk, primary, secondary

除外:
  service=parking_aisle, service=driveway
  access=private
  highway=construction
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# ── 設定 ──────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_PBF = REPO_ROOT / "data" / "kanto-260214.osm.pbf"
OUTPUT_DIR = REPO_ROOT / "frontend" / "layers" / "roads"

MAIN_CLASSES = {"motorway", "trunk", "primary", "secondary"}

EXCLUDE_SERVICE = {"parking_aisle", "driveway"}

KEEP_PROPS = {"highway", "name", "name_ja", "official_name", "alt_name", "ref", "oneway"}

# ── 道路名決定 ─────────────────────────────────────────────────────────────────

def _road_name(props: dict) -> str:
    for key in ("name", "name_ja", "official_name", "alt_name", "ref"):
        v = props.get(key, "")
        if v and str(v).strip():
            return str(v).strip()
    return ""

# ── フィルタ ──────────────────────────────────────────────────────────────────

def _keep(props: dict) -> bool:
    hw = props.get("highway", "")
    if hw not in MAIN_CLASSES:
        return False
    if props.get("service", "") in EXCLUDE_SERVICE:
        return False
    if props.get("access") == "private":
        return False
    return True

# ── プロパティ整形 ─────────────────────────────────────────────────────────────

def _slim_props(props: dict) -> dict:
    slimmed = {k: props[k] for k in KEEP_PROPS if props.get(k)}
    slimmed["_live_road_name"]  = _road_name(slimmed)
    slimmed["_live_road_class"] = slimmed.get("highway", "unknown")
    return slimmed

def _round_coords(coords: list, precision: int = 4) -> list:
    return [round(c, precision) for c in coords]

def _slim_geometry(geometry: dict, precision: int = 4) -> dict | None:
    if not geometry:
        return None
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "LineString":
        return {"type": "LineString",
                "coordinates": [_round_coords(pt, precision) for pt in coords]}
    if gtype == "MultiLineString":
        return {"type": "MultiLineString",
                "coordinates": [[_round_coords(pt, precision) for pt in line] for line in coords]}
    return geometry

# ── 隣接セグメント連結マージ ──────────────────────────────────────────────────

def _merge_connected(raw_features: list[dict]) -> list[dict]:
    """同名の LineString セグメントを、端点が一致する（幾何的に連続する）
    ものだけグループ化してマージする。端点が一致しない断片は別フィーチャー
    として保持するため、異なる場所の同名道路が誤って結合されない。
    無名フィーチャーはそのまま個別フィーチャーとして保持する。"""

    named:       dict[str, list[tuple]] = defaultdict(list)   # name -> segments (tuples)
    named_props: dict[str, dict]        = {}
    unnamed:     list[dict]             = []

    for feat in raw_features:
        props = feat.get("properties") or {}
        geom  = feat.get("geometry")
        if not geom:
            continue
        gtype = geom.get("type")
        if gtype == "LineString":
            raw_lines = [geom.get("coordinates") or []]
        elif gtype == "MultiLineString":
            raw_lines = geom.get("coordinates") or []
        else:
            continue
        # イミュータブルな tuple に変換（端点比較に使用）
        segs = [tuple(tuple(p) for p in ln) for ln in raw_lines if len(ln) >= 2]
        if not segs:
            continue

        name = props.get("_live_road_name", "")
        if name:
            named[name].extend(segs)
            named_props.setdefault(name, props)
        else:
            lines = [list(s) for s in segs]
            geom_out = ({"type": "MultiLineString", "coordinates": lines}
                        if len(lines) > 1
                        else {"type": "LineString", "coordinates": lines[0]})
            unnamed.append({"type": "Feature", "properties": props, "geometry": geom_out})

    result: list[dict] = []

    for name, segs in named.items():
        n = len(segs)
        # Union-Find
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int) -> None:
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        # 端点 → セグメント番号リスト
        ep_index: dict[tuple, list[int]] = defaultdict(list)
        for i, seg in enumerate(segs):
            ep_index[seg[0]].append(i)
            ep_index[seg[-1]].append(i)

        # 端点を共有するセグメントを同グループに
        for indices in ep_index.values():
            for j in range(1, len(indices)):
                union(indices[0], indices[j])

        # グループ別に集約
        components: dict[int, list[int]] = defaultdict(list)
        for i in range(n):
            components[find(i)].append(i)

        rep_props = named_props[name]
        for indices in components.values():
            lines = [list(segs[i]) for i in indices]
            geom_out = ({"type": "MultiLineString", "coordinates": lines}
                        if len(lines) > 1
                        else {"type": "LineString", "coordinates": lines[0]})
            result.append({"type": "Feature", "properties": rep_props, "geometry": geom_out})

    result.extend(unnamed)
    return result

# ── osmium コマンド実行 ───────────────────────────────────────────────────────

def _run(cmd: list[str]) -> None:
    print(f"  $ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)

def _extract_roads() -> Path:
    tmp_pbf     = Path("/tmp/kanto_roads_filtered.osm.pbf")
    tmp_geojson = Path("/tmp/kanto_roads_raw.geojson")

    print("[1/3] osmium tags-filter ...", flush=True)
    _run([
        "osmium", "tags-filter",
        str(SOURCE_PBF),
        "w/highway=motorway,trunk,primary,secondary",
        "-o", str(tmp_pbf),
        "--overwrite",
    ])

    print("[2/3] osmium export ...", flush=True)
    _run([
        "osmium", "export",
        str(tmp_pbf),
        "-o", str(tmp_geojson),
        "--geometry-types=linestring",
        "--overwrite",
    ])

    return tmp_geojson

# ── 書き出し ──────────────────────────────────────────────────────────────────

def _write(features: list[dict], path: Path) -> None:
    fc = {"type": "FeatureCollection", "features": features}
    tmp = path.with_suffix(".geojson.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(fc, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)
    mb = path.stat().st_size / (1024 * 1024)
    print(f"  → {path.name}: {len(features)} features, {mb:.1f} MB")

# ── メイン ────────────────────────────────────────────────────────────────────

def main() -> int:
    if not SOURCE_PBF.exists():
        print(f"ERROR: source PBF not found: {SOURCE_PBF}", file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    raw_path = _extract_roads()

    print("[3/3] post-processing ...", flush=True)
    with raw_path.open(encoding="utf-8") as f:
        fc = json.load(f)

    features = fc.get("features") or []
    total = len(features)
    print(f"  raw features: {total}")

    # フィルタ + プロパティ整形
    cleaned: list[dict] = []
    for feat in features:
        props = feat.get("properties") or {}
        if not _keep(props):
            continue
        slim_props = _slim_props(props)
        prec = 4 if slim_props["_live_road_class"] in ("motorway", "trunk", "primary") else 3
        slim_geom = _slim_geometry(feat.get("geometry"), precision=prec)
        if slim_geom:
            cleaned.append({"type": "Feature", "properties": slim_props, "geometry": slim_geom})

    print(f"  after filter: {len(cleaned)}")

    main_raw = [f for f in cleaned if f["properties"]["_live_road_class"] in MAIN_CLASSES]

    # 隣接セグメントのみ連結マージ（同名の非隣接断片は別フィーチャーに分離）
    print("[3/3] merging connected segments ...")
    main_merged = _merge_connected(main_raw)

    print("[4/4] writing output ...")
    _write(main_merged, OUTPUT_DIR / "kanto_roads_main.geojson")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

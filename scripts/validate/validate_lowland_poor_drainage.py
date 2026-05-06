#!/usr/bin/env python3
"""
低位地帯（低地・排水困難エリア）GeoJSON バリデーション

確認項目:
  - FeatureCollection 形式
  - Geometry が Polygon または MultiPolygon のみ
  - Feature 数が 1 以上
  - Bounding Box が対象都県の範囲内
  - 必須属性の存在: risk, risk_score, region, dataset
  - risk_score が 0 より大きい整数

バウンディングボックス:
  東京:    lon 138.94–139.92  lat 24.22–35.90 (離島含む)
  神奈川:  lon 139.04–139.78  lat 35.13–35.67
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

REQUIRED_FIELDS = ("risk", "risk_score", "region", "dataset")

REGION_BBOX = {
    "tokyo":    (24.22, 138.94, 35.90, 154.00),  # 小笠原諸島含む（東経154°まで）
    "kanagawa": (35.13, 139.04, 35.67, 139.78),
}

VALID_GEOMETRIES = {"Polygon", "MultiPolygon"}


def validate(input_path: Path, region: str) -> int:
    print(f"検証中: {input_path}  (region={region})")

    with input_path.open(encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"[ERROR] JSON 解析失敗: {e}", file=sys.stderr)
            return 1

    if data.get("type") != "FeatureCollection":
        print("[ERROR] type が FeatureCollection ではありません", file=sys.stderr)
        return 1

    features = data.get("features", [])
    if not features:
        print("[ERROR] Feature が 0 件です", file=sys.stderr)
        return 1

    bbox = REGION_BBOX.get(region)
    s_limit, w_limit, n_limit, e_limit = bbox if bbox else (None, None, None, None)

    errors = 0
    min_lon = min_lat = float("inf")
    max_lon = max_lat = float("-inf")

    for i, feat in enumerate(features):
        geom = feat.get("geometry") or {}
        gtype = geom.get("type", "")
        if gtype not in VALID_GEOMETRIES:
            print(f"[WARN] Feature {i}: 不正 geometry type={gtype!r}", file=sys.stderr)
            errors += 1
            continue

        props = feat.get("properties") or {}
        for field in REQUIRED_FIELDS:
            if field not in props:
                print(f"[ERROR] Feature {i}: 必須属性 {field!r} が欠落", file=sys.stderr)
                errors += 1

        rs = props.get("risk_score")
        if rs is not None and (not isinstance(rs, (int, float)) or rs <= 0):
            print(f"[ERROR] Feature {i}: risk_score={rs!r} は 0 より大きい数値でなければなりません", file=sys.stderr)
            errors += 1

        coords = geom.get("coordinates", [])
        def _collect_coords(c):
            if not c:
                return
            if isinstance(c[0], (int, float)):
                yield c
            else:
                for sub in c:
                    yield from _collect_coords(sub)
        for pt in _collect_coords(coords):
            if len(pt) >= 2:
                lon, lat = float(pt[0]), float(pt[1])
                min_lon = min(min_lon, lon)
                min_lat = min(min_lat, lat)
                max_lon = max(max_lon, lon)
                max_lat = max(max_lat, lat)

    print(f"Feature 数: {len(features):,}")
    print(f"BBox: lon=[{min_lon:.4f},{max_lon:.4f}]  lat=[{min_lat:.4f},{max_lat:.4f}]")

    if bbox and min_lon != float("inf"):
        out_of_bounds = (
            min_lon < w_limit - 2 or max_lon > e_limit + 2
            or min_lat < s_limit - 2 or max_lat > n_limit + 2
        )
        if out_of_bounds:
            print(
                f"[WARN] BBox が {region} の期待範囲 "
                f"(lon=[{w_limit},{e_limit}] lat=[{s_limit},{n_limit}]) を大きく逸脱",
                file=sys.stderr,
            )

    if errors > 0:
        print(f"[ERROR] エラー {errors} 件検出", file=sys.stderr)
        return 1

    print("検証 OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="低位地帯 GeoJSON バリデーション")
    parser.add_argument("--input", required=True, help="入力 GeoJSON パス")
    parser.add_argument("--output", help="バリデーション済み出力パス (指定時はコピー)")
    parser.add_argument("--region", required=True, choices=list(REGION_BBOX.keys()))
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"入力ファイルが見つかりません: {input_path}", file=sys.stderr)
        return 1

    rc = validate(input_path, args.region)
    if rc != 0:
        return rc

    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(input_path, out)
        print(f"出力: {out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

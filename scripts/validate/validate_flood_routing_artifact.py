#!/usr/bin/env python3
"""
洪水 routing artifact 検証（pipeline の routing validation 工程）

検証内容（1 つでも不成立なら exit 1 = publish 禁止）:
  1. 契約: meta の必須項目、dataset_id 一致、
     sha256(canonical) == meta.source_canonical_sha256、
     sha256(routing)   == meta.routing_artifact_sha256
     （backend/app/services/flood_routing_contract.verify_routing_for_canonical）
  2. 構造: 全 Feature が閉じた軸平行矩形 Polygon、hazard_type="flood"、flood_rank は 1-5 の int、
     dataset_id 一致、件数 = meta.feature_count > 0
  3. 被覆（false negative 検査）: canonical の各 Polygon の内部点（representative point）が
     いずれかの routing bbox（バッファなし・閉区間）に含まれる

canonical / routing ともストリーム読み。routing の bbox は numpy 配列（件数 × 4 × 8 byte）と
グリッド索引で保持する。

使い方:
  python scripts/validate/validate_flood_routing_artifact.py \\
      --canonical data_lake/validated/tokyo/flood/tokyo-river-001.geojson \\
      --dataset-id TOKYO-RIVER-001
"""

import argparse
import json
import math
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from shapely.geometry import shape


def _import_contract():
    here = Path(__file__).resolve()
    for cand in (here.parents[2] / "backend", Path("/app")):
        if (cand / "app" / "services" / "flood_routing_contract.py").is_file():
            sys.path.insert(0, str(cand))
            break
    from app.services import flood_routing_contract  # noqa: E402
    return flood_routing_contract


_INDEX_CELL = 0.01


def _iter_features(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().rstrip(",")
            if line.startswith('{"type":"Feature"'):
                yield json.loads(line)


def _check_structure(routing_path: Path, dataset_id: str, expected_count: int) -> np.ndarray:
    boxes = []
    for i, feat in enumerate(_iter_features(routing_path)):
        props = feat.get("properties") or {}
        rank = props.get("flood_rank")
        if props.get("hazard_type") != "flood" or not isinstance(rank, int) or isinstance(rank, bool) \
                or not 1 <= rank <= 5 or props.get("dataset_id") != dataset_id:
            raise ValueError(f"routing feature #{i} の properties が契約違反: {props}")
        geom = feat.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") != "Polygon" or len(coords) != 1 or len(coords[0]) != 5:
            raise ValueError(f"routing feature #{i} が矩形 Polygon ではありません")
        (ax, ay), (bx, by), (cx, cy), (dx, dy), (ex, ey) = coords[0]
        if not ((ax, ay) == (ex, ey) and ay == by and bx == cx and cy == dy and dx == ax
                and ax <= bx and ay <= cy):
            raise ValueError(f"routing feature #{i} が閉じた軸平行矩形ではありません: {coords[0]}")
        boxes.append((ax, ay, bx, cy))
    if len(boxes) != expected_count or not boxes:
        raise ValueError(f"routing 件数不一致: 実体={len(boxes)} meta={expected_count}")
    return np.asarray(boxes, dtype=np.float64)


def _build_index(boxes: np.ndarray) -> dict:
    index = defaultdict(list)
    c0 = np.floor(boxes[:, 0] / _INDEX_CELL).astype(np.int64)
    c1 = np.floor(boxes[:, 2] / _INDEX_CELL).astype(np.int64)
    r0 = np.floor(boxes[:, 1] / _INDEX_CELL).astype(np.int64)
    r1 = np.floor(boxes[:, 3] / _INDEX_CELL).astype(np.int64)
    for i in range(len(boxes)):
        for cx in range(c0[i], c1[i] + 1):
            for cy in range(r0[i], r1[i] + 1):
                index[(cx, cy)].append(i)
    return {k: np.asarray(v, dtype=np.int64) for k, v in index.items()}


def _check_coverage(canonical_path: Path, boxes: np.ndarray, index: dict) -> int:
    """canonical 各 Polygon の内部点が routing bbox に含まれない件数（= 検出した FN）を返す。"""
    misses = 0
    checked = 0
    for feat in _iter_features(canonical_path):
        geom = shape(feat["geometry"])
        parts = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        for part in parts:
            p = part.representative_point()
            x, y = p.x, p.y
            cand = index.get((math.floor(x / _INDEX_CELL), math.floor(y / _INDEX_CELL)))
            checked += 1
            if cand is None:
                misses += 1
                continue
            b = boxes[cand]
            if not np.any((b[:, 0] <= x) & (x <= b[:, 2]) & (b[:, 1] <= y) & (y <= b[:, 3])):
                misses += 1
    if checked == 0:
        raise ValueError(f"canonical に Polygon がありません: {canonical_path}")
    return misses


def validate(canonical_path: Path, dataset_id: str) -> dict:
    contract = _import_contract()
    t0 = time.time()
    try:
        routing_path, meta = contract.verify_routing_for_canonical(canonical_path, dataset_id)
    except contract.FloodRoutingContractError as exc:
        raise ValueError(str(exc)) from exc
    boxes = _check_structure(routing_path, dataset_id, meta["feature_count"])
    index = _build_index(boxes)
    misses = _check_coverage(canonical_path, boxes, index)
    if misses:
        raise ValueError(f"false negative 検出: canonical の内部点 {misses} 件が routing bbox に含まれません")
    return {
        "routing": str(routing_path),
        "feature_count": int(len(boxes)),
        "coverage_false_negatives": 0,
        "seconds": round(time.time() - t0, 1),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="洪水 routing artifact 検証")
    p.add_argument("--canonical", required=True, help="validated canonical flood GeoJSON")
    p.add_argument("--dataset-id", required=True)
    a = p.parse_args()
    try:
        result = validate(Path(a.canonical), a.dataset_id)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] routing validation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
    print("Flood routing validation passed", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
洪水 routing artifact 生成

canonical flood GeoJSON（normalize_river_flood.py の出力。公式形状・穴を保持）から、
HazardEngine の bbox 判定（bbox_only=True）専用の routing artifact と provenance meta を生成する。
canonical は読み取りのみで一切変更しない。

契約（backend/app/services/flood_routing_contract.py と一致させること）:
  入力  data_lake/validated/{region}/flood/{dataset}.geojson
  出力  data_lake/derived/{region}/flood/{dataset}.routing.geojson
        data_lake/derived/{region}/flood/{dataset}.routing.meta.json

方式（tile dissolve + kd 分割）:
  1. pass1: canonical を 1 feature ずつストリーム読みし、tile（--tile-size 四方）ごとに clip した
     断片を tile 別の一時 JSONL バケットへ書き出す（全件をメモリに載せない）。
     同時に canonical の sha256 を計算する。
  2. pass2: tile を座標の数値順に処理し、断片を union → 各連結成分を
     「面積 / bbox 面積 >= tau」または「bbox 長辺 <= --min-split-size」になるまで
     bbox の長辺方向に二分割して clip する。
  3. 各断片の bbox を矩形 Polygon として出力する。

false negative を作らない根拠:
  - 断片は canonical の clip であり、tile 内の断片の和集合 = canonical の和集合。
  - 各断片 ⊆ その bbox なので、canonical 上の点は必ずいずれかの出力 bbox に含まれる。
  - clip は厳密な overlay（shapely.intersection）で行う（clip_by_rect は使わない）。
  - GEOS の clip が失敗した場合、または分割前後で面積が保存されない場合は分割をやめ、
    元断片の bbox をそのまま出力する（安全側）。
  - routing validation（scripts/validate/validate_flood_routing_artifact.py）が canonical の全
    Polygon の内部点について被覆を再検査する。
  - flood_rank は断片に交差する canonical 断片の最大値（安全側に上振れしうる）。

決定性: 同じ canonical と同じパラメータからは同一バイト列の routing artifact を生成する
（meta の generated_at のみ実行時刻）。

安全な書き込み:
  - 作業ディレクトリと一時出力は出力先と同じディレクトリに作り、成功・失敗を問わず削除する。
  - routing → meta の順に os.replace する。途中で止まっても meta の routing sha256 と
    実体が一致しないため publish 側で拒否される（既存の derived artifact は失敗時に変更しない）。
  - build 中に canonical が変わった場合（開始時と終了時の sha256 不一致）は失敗にする。

使い方:
  python scripts/derive/build_flood_routing_artifact.py \\
      --input  data_lake/validated/tokyo/flood/tokyo-river-001.geojson \\
      --output data_lake/derived/tokyo/flood/tokyo-river-001.routing.geojson \\
      --dataset-id TOKYO-RIVER-001
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import shapely
from shapely.geometry import box, mapping, shape

# flood_routing_contract.py と同じ値（tests/test_flood_routing_contract.py で一致を固定）
ROUTING_SUFFIX = ".routing.geojson"
META_SUFFIX = ".routing.meta.json"
CONTRACT_VERSION = "flood_routing/v1"
BUILDER_NAME = "build_flood_routing_artifact"
BUILDER_VERSION = "1.1.0"  # 1.1.0: clip_by_rect → 厳密 overlay + 面積保存検査

DEFAULT_TAU = 0.85
DEFAULT_TILE_SIZE = 0.02
DEFAULT_MIN_SPLIT_SIZE = 0.0002  # ≈ 20m（HazardEngine の近傍バッファ 0.000225° 未満）
_MAX_SPLIT_DEPTH = 40
_MAX_OPEN_BUCKETS = 200


class _ClipFailed(Exception):
    pass


def _clip(geom, x0: float, y0: float, x1: float, y1: float):
    """矩形 clip（厳密な overlay = shapely.intersection）。

    shapely.clip_by_rect は「高速だが厳密さを保証しない（dirty）clip」で、実データ
    （A31a/A31b 2025）で断片の一部を落とし false negative を生じた（routing validation で
    検出）。そのため使用しない。入力が不正で overlay が失敗した場合は make_valid して再試行し、
    それも失敗したら _ClipFailed（呼び出し側は分割せず元の断片をそのまま使う = 安全側）。"""
    rect = box(x0, y0, x1, y1)
    try:
        return shapely.intersection(geom, rect)
    except shapely.errors.GEOSException:
        pass
    try:
        return shapely.intersection(shapely.make_valid(geom), rect)
    except shapely.errors.GEOSException as exc:
        raise _ClipFailed(str(exc)) from exc


def _area_conserved(whole_area: float, part_areas) -> bool:
    """分割前後で面積が保存されているか（断片の取りこぼし検出）。"""
    return abs(sum(part_areas) - whole_area) <= 1e-9 * whole_area + 1e-18


def _iter_canonical(path: Path, hasher):
    """canonical GeoJSON（1 行 1 Feature）を 1 feature ずつ返しつつ、全バイトを hasher に通す。"""
    with path.open("rb") as f:
        for raw in f:
            hasher.update(raw)
            line = raw.decode("utf-8").strip().rstrip(",")
            if line.startswith('{"type":"Feature"'):
                yield json.loads(line)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _bucket_canonical(input_path: Path, bucket_dir: Path, tile_size: float) -> dict:
    """pass1: canonical を tile 単位に clip してバケットファイルへ振り分ける。"""
    handles: dict = {}
    hasher = hashlib.sha256()
    stats = {"source_feature_count": 0, "fragments": 0, "clip_fallbacks": 0}
    try:
        for feat in _iter_canonical(input_path, hasher):
            stats["source_feature_count"] += 1
            geom = shape(feat["geometry"])
            rank = int(feat["properties"].get("flood_rank") or 0)
            x0, y0, x1, y1 = geom.bounds
            ix0, ix1 = math.floor(x0 / tile_size), math.floor(x1 / tile_size)
            iy0, iy1 = math.floor(y0 / tile_size), math.floor(y1 / tile_size)
            single = ix0 == ix1 and iy0 == iy1
            for ix in range(ix0, ix1 + 1):
                for iy in range(iy0, iy1 + 1):
                    if single:
                        part = geom
                    else:
                        try:
                            part = _clip(geom, ix * tile_size, iy * tile_size,
                                         (ix + 1) * tile_size, (iy + 1) * tile_size)
                        except _ClipFailed:
                            # clip 不能: tile に切らず元形状のまま入れる（bbox が広がるだけで欠落はしない）
                            part = geom
                            stats["clip_fallbacks"] += 1
                        if part.is_empty or part.area == 0:
                            continue
                    key = (ix, iy)
                    fh = handles.get(key)
                    if fh is None:
                        if len(handles) >= _MAX_OPEN_BUCKETS:
                            for h in handles.values():
                                h.close()
                            handles.clear()
                        fh = handles[key] = (bucket_dir / f"{ix}_{iy}.jsonl").open("a", encoding="utf-8")
                    fh.write(json.dumps({"r": rank, "g": mapping(part)}, separators=(",", ":")) + "\n")
                    stats["fragments"] += 1
    finally:
        for h in handles.values():
            h.close()
    if stats["source_feature_count"] == 0:
        raise ValueError(f"canonical に Feature がありません: {input_path}")
    stats["source_canonical_sha256"] = hasher.hexdigest()
    return stats


def _split(geom, tau: float, min_split_size: float, out: list, depth: int = 0) -> None:
    """geom を充填率または最小分割サイズの条件を満たすまで kd 分割し、断片を out に追加する。"""
    if geom.is_empty or geom.area == 0:
        return
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        for g in geom.geoms:
            if g.geom_type in ("Polygon", "MultiPolygon"):
                _split(g, tau, min_split_size, out, depth)
        return
    if geom.geom_type != "Polygon":
        return
    x0, y0, x1, y1 = geom.bounds
    w, h = x1 - x0, y1 - y0
    if depth >= _MAX_SPLIT_DEPTH or max(w, h) <= min_split_size or geom.area >= tau * w * h:
        out.append(geom)
        return
    if w >= h:
        xm = (x0 + x1) / 2
        halves = ((x0, y0, xm, y1), (xm, y0, x1, y1))
    else:
        ym = (y0 + y1) / 2
        halves = ((x0, y0, x1, ym), (x0, ym, x1, y1))
    try:
        parts = [_clip(geom, *rect) for rect in halves]
    except _ClipFailed:
        out.append(geom)  # 分割不能: bbox が広がるだけで欠落はしない（安全側）
        return
    if not _area_conserved(geom.area, (p.area for p in parts)):
        out.append(geom)  # 分割で面積が欠けた（clip 異常）: 分割を採用しない（安全側）
        return
    for part in parts:
        _split(part, tau, min_split_size, out, depth + 1)


def _process_tile(bucket: Path, tau: float, min_split_size: float):
    """pass2: 1 tile の断片を union → kd 分割し、(bbox, rank) を返す。"""
    geoms, ranks = [], []
    with bucket.open("r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            geoms.append(shape(rec["g"]))
            ranks.append(rec["r"])
    merged = shapely.union_all(shapely.make_valid(geoms))
    pieces: list = []
    _split(merged, tau, min_split_size, pieces)
    if not pieces:
        return []
    tree = shapely.STRtree(geoms)
    results = []
    for piece in pieces:
        hits = tree.query(piece, predicate="intersects")
        rank = max((ranks[i] for i in hits), default=0)
        if rank == 0:
            # 境界接触のみ等で intersects が取れない場合も rank 0 にはしない（安全側）
            near = tree.query(piece.buffer(1e-9))
            rank = max((ranks[i] for i in near), default=1) or 1
        results.append((piece.bounds, rank))
    return results


def _bucket_order(path: Path):
    ix, iy = path.stem.split("_")
    return int(ix), int(iy)


def build(input_path: Path, output_path: Path, dataset_id: str, *,
          tau: float = DEFAULT_TAU, min_split_size: float = DEFAULT_MIN_SPLIT_SIZE,
          tile_size: float = DEFAULT_TILE_SIZE) -> dict:
    """routing artifact と meta を生成し、meta（dict）を返す。失敗時は既存出力を変更しない。"""
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not output_path.name.endswith(ROUTING_SUFFIX):
        raise ValueError(f"出力ファイル名は *{ROUTING_SUFFIX} である必要があります: {output_path}")
    if not dataset_id:
        raise ValueError("--dataset-id は必須です")
    if not (0.0 < tau <= 1.0) or min_split_size <= 0 or tile_size <= 0:
        raise ValueError(f"パラメータ不正: tau={tau} min_split_size={min_split_size} tile_size={tile_size}")
    meta_path = output_path.with_name(output_path.name[: -len(ROUTING_SUFFIX)] + META_SUFFIX)

    t0 = time.time()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{output_path.name}.work-", dir=output_path.parent))
    tmp_out = work / output_path.name
    tmp_meta = work / meta_path.name
    try:
        stats = _bucket_canonical(input_path, work, tile_size)
        t1 = time.time()
        routing_hash = hashlib.sha256()
        count = 0
        with tmp_out.open("wb") as fout:
            def _w(text: str) -> None:
                data = text.encode("utf-8")
                routing_hash.update(data)
                fout.write(data)

            _w('{"type":"FeatureCollection","name":"flood_routing","features":[\n')
            first = True
            for bucket in sorted(work.glob("*.jsonl"), key=_bucket_order):
                for (x0, y0, x1, y1), rank in _process_tile(bucket, tau, min_split_size):
                    feat = {
                        "type": "Feature",
                        "properties": {"hazard_type": "flood", "flood_rank": int(rank), "dataset_id": dataset_id},
                        "geometry": {"type": "Polygon", "coordinates": [[
                            [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0],
                        ]]},
                    }
                    _w(("" if first else ",\n") + json.dumps(feat, ensure_ascii=False, separators=(",", ":")))
                    first = False
                    count += 1
            _w("\n]}\n")
            fout.flush()
            os.fsync(fout.fileno())
        if count == 0:
            raise ValueError("routing artifact の出力が 0 件です")

        # build 中に canonical が書き換えられていないこと
        if _sha256_file(input_path) != stats["source_canonical_sha256"]:
            raise ValueError(f"build 中に canonical が変更されました: {input_path}")

        meta = {
            "contract": CONTRACT_VERSION,
            "dataset_id": dataset_id,
            "source_canonical_path": str(input_path),
            "source_canonical_sha256": stats["source_canonical_sha256"],
            "source_feature_count": stats["source_feature_count"],
            "routing_artifact": output_path.name,
            "routing_artifact_sha256": routing_hash.hexdigest(),
            "builder_name": BUILDER_NAME,
            "builder_version": BUILDER_VERSION,
            "tau": tau,
            "min_split_size": min_split_size,
            "tile_size": tile_size,
            "feature_count": count,
            "output_bytes": tmp_out.stat().st_size,
            "clip_fallbacks": stats["clip_fallbacks"],
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "build_seconds": {"pass1": round(t1 - t0, 1), "pass2": round(time.time() - t1, 1)},
        }
        tmp_meta.write_text(json.dumps(meta, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp_out, output_path)
        os.replace(tmp_meta, meta_path)
        return meta
    finally:
        shutil.rmtree(work, ignore_errors=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="canonical flood GeoJSON → HazardEngine 用 routing artifact")
    p.add_argument("--input", required=True, help="canonical flood GeoJSON（1 行 1 Feature）")
    p.add_argument("--output", required=True, help=f"routing artifact 出力パス（*{ROUTING_SUFFIX}）")
    p.add_argument("--dataset-id", required=True)
    p.add_argument("--tau", type=float, default=DEFAULT_TAU, help=f"充填率しきい値（既定 {DEFAULT_TAU}）")
    p.add_argument("--min-split-size", type=float, default=DEFAULT_MIN_SPLIT_SIZE,
                   help=f"これ以下の長辺は分割しない [deg]（既定 {DEFAULT_MIN_SPLIT_SIZE}）")
    p.add_argument("--tile-size", type=float, default=DEFAULT_TILE_SIZE,
                   help=f"dissolve tile の一辺 [deg]（既定 {DEFAULT_TILE_SIZE}）")
    return p.parse_args()


def main() -> int:
    a = parse_args()
    try:
        meta = build(Path(a.input), Path(a.output), a.dataset_id,
                     tau=a.tau, min_split_size=a.min_split_size, tile_size=a.tile_size)
    except (OSError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(meta, ensure_ascii=False), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

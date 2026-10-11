"""
tsunami_coverage: 「津波 dataset を評価していない地点」を判定するための軽量 coverage index。

背景（TSUNAMI-UNLOADED-REGION-SAFETY、2026-10-11）:
  hazard.tsunami.targets に含まれない region（例: chiba）の津波浸水想定区域内の地点を、
  backend はその region の dataset を読んでいないのに "outside"（区域外）と返していた。
  OUTSIDE は「その region の dataset を評価した結果 polygon 外」だけを意味し、
  未評価の地点は "unknown"（hazard_coverage_status = SOURCE_UNAVAILABLE）にする。

index の中身:
  dataset の各 polygon 外環の bbox（HazardService と同じ _extract_outer_rings / _ring_bbox）が
  重なる CELL_DEG 格子セルを、float32 丸め分の余裕として 1 セル膨らませて記録する。
  index の外にある地点は、その dataset のどの bbox にも入らない（＝評価しても outside）ことが
  保証される。index の中にあり dataset を読んでいない地点だけを unknown にする。

index は dataset registry の tsunami dataset ごとに data_lake/registry/tsunami_coverage/<region>.json
として保持する（git 管理、数十 KB）。backend は起動時に、targets で読まない registry 上の tsunami region の
index を読み込む。index が無い・不正・region 不一致の region がある場合は、その region の範囲を
特定できないため津波判定全体を unknown にする（fail closed）。
"""
from __future__ import annotations

import bisect
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

FORMAT = "ohg2-tsunami-coverage/1"
CELL_DEG = 0.01
DILATE_CELLS = 1


def _cell(v: float) -> int:
    return int(math.floor(v / CELL_DEG))


@dataclass
class CoverageIndex:
    dataset_id: str
    region: str
    rows: Dict[int, List[Tuple[int, int]]] = field(default_factory=dict)
    _starts: Dict[int, List[int]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self._starts = {iy: [a for a, _ in runs] for iy, runs in self.rows.items()}

    def contains(self, lat: float, lon: float) -> bool:
        runs = self.rows.get(_cell(lat))
        if not runs:
            return False
        ix = _cell(lon)
        i = bisect.bisect_right(self._starts[_cell(lat)], ix) - 1
        return i >= 0 and runs[i][0] <= ix <= runs[i][1]

    def cell_count(self) -> int:
        return sum(b - a + 1 for runs in self.rows.values() for a, b in runs)


def _runs(xs: Iterable[int]) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for x in sorted(set(xs)):
        if out and x == out[-1][1] + 1:
            out[-1] = (out[-1][0], x)
        else:
            out.append((x, x))
    return out


def build_index(geojson_path: Path, dataset_id: str, region: str) -> dict:
    """canonical GeoJSON から index（JSON 化できる dict）を作る。HazardService と同じ bbox 計算を使う。"""
    import hashlib

    import ijson

    from hazard_service import _extract_outer_rings, _ring_bbox

    cells: Dict[int, set] = {}
    features = 0
    bounds = [math.inf, math.inf, -math.inf, -math.inf]  # s, w, n, e
    with geojson_path.open("rb") as f:
        for feature in ijson.items(f, "features.item"):
            features += 1
            props = feature.get("properties") or {}
            if props.get("dataset_id") not in (None, dataset_id):
                raise ValueError(f"feature の dataset_id が {dataset_id} ではない: {props.get('dataset_id')}")
            for ring in _extract_outer_rings(feature.get("geometry") or {}):
                bbox = _ring_bbox(ring)
                if bbox is None:
                    continue
                s, w, n, e = bbox
                bounds = [min(bounds[0], s), min(bounds[1], w), max(bounds[2], n), max(bounds[3], e)]
                for iy in range(_cell(s) - DILATE_CELLS, _cell(n) + DILATE_CELLS + 1):
                    row = cells.setdefault(iy, set())
                    row.update(range(_cell(w) - DILATE_CELLS, _cell(e) + DILATE_CELLS + 1))
    if not features or not cells:
        raise ValueError(f"polygon が無い dataset からは coverage を作れない: {geojson_path}")
    h = hashlib.sha256()
    with geojson_path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return {
        "format": FORMAT,
        "dataset_id": dataset_id,
        "region": region,
        "cell_deg": CELL_DEG,
        "dilate_cells": DILATE_CELLS,
        "source_sha256": h.hexdigest(),
        "feature_count": features,
        "bounds": [round(v, 6) for v in bounds],
        "rows": {str(iy): [list(r) for r in _runs(xs)] for iy, xs in sorted(cells.items())},
    }


def load_index(path: Path, dataset_id: str, region: str) -> CoverageIndex:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("format") != FORMAT or raw.get("cell_deg") != CELL_DEG:
        raise ValueError(f"coverage index の形式が不正: {path}")
    if raw.get("dataset_id") != dataset_id or raw.get("region") != region:
        raise ValueError(f"coverage index の dataset/region が registry と一致しない: {path} "
                         f"({raw.get('dataset_id')}/{raw.get('region')} != {dataset_id}/{region})")
    rows: Dict[int, List[Tuple[int, int]]] = {}
    for k, runs in (raw.get("rows") or {}).items():
        parsed = [(int(a), int(b)) for a, b in runs]
        if any(a > b for a, b in parsed) or parsed != sorted(parsed):
            raise ValueError(f"coverage index の run が不正: {path} row={k}")
        rows[int(k)] = parsed
    if not rows:
        raise ValueError(f"coverage index が空: {path}")
    return CoverageIndex(dataset_id=dataset_id, region=region, rows=rows)


def registered_tsunami_datasets(definitions_path: Path) -> List[Tuple[str, str]]:
    """dataset registry 上の tsunami dataset（dataset_id, region）。registry を読めなければ例外。"""
    raw = json.loads(definitions_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"dataset registry が不正: {definitions_path}")
    return sorted((d["dataset_id"], d["region"]) for d in raw
                  if isinstance(d, dict) and d.get("layer_type") == "tsunami" and d.get("region"))


def resolve_unevaluated(definitions_path: Path, coverage_dir: Path,
                        evaluated_regions: Iterable[str]) -> Tuple[List[CoverageIndex], List[str]]:
    """targets で評価しない registry 上の tsunami region について (index 一覧, 範囲を特定できない region 一覧) を返す。

    2 つ目が空でなければ、その region の地点を判別できないため呼び出し側は津波判定全体を unknown にする。"""
    evaluated = set(evaluated_regions)
    try:
        datasets = registered_tsunami_datasets(definitions_path)
    except (OSError, ValueError, KeyError) as exc:
        return [], [f"registry: {exc}"]
    indexes: List[CoverageIndex] = []
    problems: List[str] = []
    for dataset_id, region in datasets:
        if region in evaluated:
            continue
        try:
            indexes.append(load_index(coverage_dir / f"{region}.json", dataset_id, region))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            problems.append(f"{region}: {exc}")
    return indexes, problems


def coverage_dir_for(definitions_path: Path) -> Path:
    return definitions_path.parent / "tsunami_coverage"


def first_containing(indexes: List[CoverageIndex], lat: float, lon: float) -> Optional[str]:
    for idx in indexes:
        if idx.contains(lat, lon):
            return idx.region
    return None

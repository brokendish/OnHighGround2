"""
flood_routing_contract.py — 洪水 canonical / routing artifact 分離の正式契約。

canonical（表示・検証・将来の strict PIP 用。公式形状・穴を保持）:
    data_lake/validated/{region}/flood/{dataset}.geojson

routing artifact（HazardEngine の bbox 判定専用）:
    data_lake/derived/{region}/flood/{dataset}.routing.geojson
    data_lake/derived/{region}/flood/{dataset}.routing.meta.json

runtime（atomic publish version 配下）:
    backend/hazard/flood/{region}/{dataset}.routing.geojson   ← これ以外は置かない

routing のパスは canonical パスから一意に導く（パス中の最後の `validated` 要素を
`derived` に置き換え、拡張子を `.routing.geojson` / `.routing.meta.json` にする）。
state に別フィールドを持たず、publish 可否は毎回ファイル実体（meta と sha256）で判定する。

本モジュールは scripts/derive/build_flood_routing_artifact.py（standalone、backend を import
しない）と定数を共有する。両者の一致は tests/test_flood_routing_contract.py で固定する。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Dict, List, Tuple

ROUTING_SUFFIX = ".routing.geojson"
META_SUFFIX = ".routing.meta.json"
CONTRACT_VERSION = "flood_routing/v1"
BUILDER_NAME = "build_flood_routing_artifact"
DEFAULT_TAU = 0.85

REQUIRED_META_FIELDS: Dict[str, tuple] = {
    "contract": (str,),
    "dataset_id": (str,),
    "source_canonical_path": (str,),
    "source_canonical_sha256": (str,),
    "routing_artifact_sha256": (str,),
    "builder_name": (str,),
    "builder_version": (str,),
    "tau": (int, float),
    "min_split_size": (int, float),
    "feature_count": (int,),
    "generated_at": (str,),
}


class FloodRoutingContractError(Exception):
    """routing artifact が契約を満たさない（publish 禁止）。"""


def is_routing_artifact_name(name: str) -> bool:
    return name.endswith(ROUTING_SUFFIX)


def routing_paths_for_canonical(canonical_path: Path) -> Tuple[Path, Path]:
    """canonical パスから (routing, meta) パスを導く。"""
    canonical_path = Path(canonical_path)
    if canonical_path.suffix != ".geojson" or is_routing_artifact_name(canonical_path.name):
        raise FloodRoutingContractError(f"canonical flood は *.geojson（routing 以外）である必要があります: {canonical_path}")
    parts = list(canonical_path.parent.parts)
    try:
        idx = len(parts) - 1 - parts[::-1].index("validated")
    except ValueError as exc:
        raise FloodRoutingContractError(
            f"canonical flood のパスに 'validated' 要素がなく derived 配置を導けません: {canonical_path}"
        ) from exc
    parts[idx] = "derived"
    derived_dir = Path(*parts)
    stem = canonical_path.name[: -len(".geojson")]
    return derived_dir / f"{stem}{ROUTING_SUFFIX}", derived_dir / f"{stem}{META_SUFFIX}"


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def load_meta(meta_path: Path) -> dict:
    meta_path = Path(meta_path)
    if not meta_path.is_file():
        raise FloodRoutingContractError(f"routing meta が存在しません: {meta_path}")
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FloodRoutingContractError(f"routing meta を読めません: {meta_path}: {exc}") from exc
    if not isinstance(meta, dict):
        raise FloodRoutingContractError(f"routing meta が object ではありません: {meta_path}")
    for key, types in REQUIRED_META_FIELDS.items():
        value = meta.get(key)
        if not isinstance(value, types) or isinstance(value, bool):
            raise FloodRoutingContractError(f"routing meta の必須フィールド不正: {key}={value!r} ({meta_path})")
    if meta["contract"] != CONTRACT_VERSION:
        raise FloodRoutingContractError(f"routing meta の contract が未対応: {meta['contract']!r}")
    if meta["builder_name"] != BUILDER_NAME:
        raise FloodRoutingContractError(f"routing meta の builder_name が不正: {meta['builder_name']!r}")
    if meta["feature_count"] <= 0:
        raise FloodRoutingContractError(f"routing artifact が 0 件です: {meta_path}")
    return meta


def verify_routing_for_canonical(canonical_path: Path, dataset_id: str) -> Tuple[Path, dict]:
    """
    canonical に対応する routing artifact が publish 可能かを検証し、(routing パス, meta) を返す。

    - routing / meta が存在する
    - meta の dataset_id が一致する
    - meta.source_canonical_sha256 == sha256(現在の canonical)（routing が古くない）
    - meta.routing_artifact_sha256 == sha256(routing)（routing が改変・途中書き込みでない）
    いずれか不成立で FloodRoutingContractError（publish 禁止）。
    """
    canonical_path = Path(canonical_path)
    if not canonical_path.is_file():
        raise FloodRoutingContractError(f"canonical flood が存在しません: {canonical_path}")
    routing_path, meta_path = routing_paths_for_canonical(canonical_path)
    if not routing_path.is_file():
        raise FloodRoutingContractError(f"routing artifact が存在しません: {routing_path}")
    meta = load_meta(meta_path)
    if meta["dataset_id"] != dataset_id:
        raise FloodRoutingContractError(
            f"routing meta の dataset_id 不一致: meta={meta['dataset_id']!r} expected={dataset_id!r}"
        )
    canonical_sha = sha256_file(canonical_path)
    if meta["source_canonical_sha256"] != canonical_sha:
        raise FloodRoutingContractError(
            f"canonical sha256 と routing meta の source sha256 が不一致（routing が古い）: "
            f"canonical={canonical_sha} meta={meta['source_canonical_sha256']}"
        )
    routing_sha = sha256_file(routing_path)
    if meta["routing_artifact_sha256"] != routing_sha:
        raise FloodRoutingContractError(
            f"routing artifact sha256 が meta と不一致: actual={routing_sha} meta={meta['routing_artifact_sha256']}"
        )
    return routing_path, meta


def discover_flood_routing_files(flood_dir: Path) -> Tuple[List[Path], List[Path]]:
    """
    HazardEngine 用: flood runtime 配下から routing artifact だけを返す。
    戻り値 (routing_files, ignored_files)。ignored は canonical/legacy 等の誤配置で、
    呼び出し側はロードせずにログへ記録する（二重ロード・canonical 誤読の防止）。
    """
    flood_dir = Path(flood_dir)
    if not flood_dir.is_dir():
        return [], []
    routing, ignored = [], []
    for p in sorted(flood_dir.rglob("*")):
        if not p.is_file():
            continue
        if is_routing_artifact_name(p.name):
            routing.append(p)
        elif p.suffix.lower() in {".geojson", ".geojsonl", ".json"}:
            ignored.append(p)
    return routing, ignored

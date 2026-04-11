#!/usr/bin/env python3
"""
洪水浸水想定区域データ正規化スクリプト

対応入力フォーマット:
  - GeoJSON / JSON (.geojson, .json)
  - ZIP アーカイブ (内部の .geojson / .json を自動検出)

出力: GeoJSON FeatureCollection

正規化プロパティ:
  hazard_type   = "flood"
  dataset_id    = <--dataset-id 引数>
  flood_rank    (int 1-5): 浸水深区分
  depth_text    (str): 区分テキスト
  depth         (float): 代表浸水深 [m]
  river_name    (str): 河川名 (あれば)
  river_number  (str): 河川番号 (あれば)

浸水深ランク対応 (A31a_205 / A31b_205):
  1: 0.5m未満        → depth 0.25
  2: 0.5m以上3m未満  → depth 1.75
  3: 3m以上5m未満    → depth 4.00
  4: 5m以上10m未満   → depth 7.50
  5: 10m以上20m未満  → depth 15.0
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path

# ── ランクルックアップ ─────────────────────────────────────────────────────

# rank → (depth_text, representative_depth_m)
RANK_TABLE: dict[int, tuple[str, float]] = {
    1: ("0.5m未満",       0.25),
    2: ("0.5m以上3m未満", 1.75),
    3: ("3m以上5m未満",   4.00),
    4: ("5m以上10m未満",  7.50),
    5: ("10m以上20m未満", 15.0),
}

# 浸水深テキスト → rank (テキストで入ってくる場合)
TEXT_TO_RANK: dict[str, int] = {v[0]: k for k, v in RANK_TABLE.items()}

# プロパティキー優先順: A31a_205 (都管理), A31b_205 (国管理), flood_rank, water_depth
_RANK_KEYS = ("A31a_205", "A31b_205", "flood_rank", "water_depth")


def _extract_rank(props: dict) -> int:
    """プロパティ辞書から flood_rank (1-5) を抽出する。不明なら 0。"""
    for key in _RANK_KEYS:
        val = props.get(key)
        if val is None:
            continue
        if isinstance(val, int) and val in RANK_TABLE:
            return val
        if isinstance(val, float) and int(val) in RANK_TABLE:
            return int(val)
        if isinstance(val, str):
            try:
                iv = int(float(val))
                if iv in RANK_TABLE:
                    return iv
            except (ValueError, TypeError):
                pass
            if val in TEXT_TO_RANK:
                return TEXT_TO_RANK[val]
    return 0


# ── 入力読み込み ───────────────────────────────────────────────────────────

def _parse_geojson_bytes(raw: bytes, label: str) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON 解析エラー ({label}): {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"GeoJSON ルートはオブジェクト必須 ({label})")
    if data.get("type") not in {"FeatureCollection", "Feature"}:
        raise ValueError(
            f"非対応 GeoJSON タイプ: {data.get('type')!r} ({label})\n"
            f"  対応: FeatureCollection / Feature"
        )
    return data


def load_input(path: Path) -> dict:
    suffix = path.suffix.lower()

    if suffix in {".geojson", ".json"}:
        print(f"読み込み中 (GeoJSON): {path}")
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise FileNotFoundError(f"入力ファイルを開けません: {exc}") from exc
        return _parse_geojson_bytes(raw, str(path))

    if suffix == ".zip":
        print(f"読み込み中 (ZIP): {path}")
        try:
            with zipfile.ZipFile(path, "r") as zf:
                candidates = [
                    n for n in zf.namelist()
                    if n.lower().endswith((".geojson", ".json"))
                    and not n.startswith("__MACOSX")
                ]
                if not candidates:
                    raise ValueError(
                        f"ZIP 内に .geojson / .json ファイルが見つかりません: {path}\n"
                        f"  ZIP 内容: {zf.namelist()[:20]}"
                    )
                chosen = candidates[0]
                if len(candidates) > 1:
                    print(
                        f"  複数候補を検出。先頭を使用: {chosen}\n"
                        f"  全候補: {candidates}",
                        file=sys.stderr,
                    )
                raw = zf.read(chosen)
                print(f"  ZIP 内ファイル: {chosen} ({len(raw):,} bytes)")
                return _parse_geojson_bytes(raw, f"{path}::{chosen}")
        except zipfile.BadZipFile as exc:
            raise ValueError(
                f"ZIP の読み込みに失敗しました: {path}\n"
                f"  ファイルが破損しているか ZIP 形式ではありません: {exc}"
            ) from exc

    raise ValueError(
        f"非対応の入力形式: {suffix!r}\n"
        f"  対応拡張子: .geojson / .json / .zip\n"
        f"  入力: {path}"
    )


# ── 正規化 ────────────────────────────────────────────────────────────────

def normalize(input_path: Path, output_path: Path, dataset_id: str) -> int:
    try:
        data = load_input(input_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    features_in = data.get("features", []) if data["type"] == "FeatureCollection" else [data]
    total_in = len(features_in)

    features_out: list[dict] = []
    skipped_no_geom = 0
    skipped_bad_geom = 0
    unknown_rank_count = 0

    for feat in features_in:
        props = feat.get("properties") or {}
        geom  = feat.get("geometry")

        if not geom:
            skipped_no_geom += 1
            continue

        geom_type = geom.get("type", "")
        if geom_type not in {"Polygon", "MultiPolygon"}:
            skipped_bad_geom += 1
            print(f"[WARN] 非対応ジオメトリをスキップ: {geom_type!r}", file=sys.stderr)
            continue

        rank = _extract_rank(props)
        if rank == 0:
            unknown_rank_count += 1
        rank_info = RANK_TABLE.get(rank)
        depth_text = rank_info[0] if rank_info else ""
        depth      = rank_info[1] if rank_info else None

        out_props: dict = {
            "hazard_type": "flood",
            "flood_rank":  rank,
            "depth_text":  depth_text,
        }
        if depth is not None:
            out_props["depth"] = depth
        for extra in ("river_name", "river_number", "source"):
            if props.get(extra):
                out_props[extra] = props[extra]
        if dataset_id:
            out_props["dataset_id"] = dataset_id

        features_out.append({"type": "Feature", "properties": out_props, "geometry": geom})

    if unknown_rank_count:
        print(
            f"[WARN] flood_rank を特定できなかったフィーチャ: {unknown_rank_count} 件 (rank=0 で出力)",
            file=sys.stderr,
        )

    if not features_out:
        print(
            f"[ERROR] 出力フィーチャが 0 件です。\n"
            f"  入力: {total_in}  ジオメトリなし: {skipped_no_geom}  非対応ジオメトリ: {skipped_bad_geom}",
            file=sys.stderr,
        )
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(
            {"type": "FeatureCollection", "name": "tokyo_flood_max", "features": features_out},
            f, ensure_ascii=False, separators=(",", ":"),
        )
        f.write("\n")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"完了: {output_path}")
    print(f"  入力: {total_in}  出力: {len(features_out)}  スキップ: {skipped_no_geom + skipped_bad_geom}")
    print(f"  ファイルサイズ: {size_mb:.1f} MB")

    rank_counts: dict[int, int] = {}
    for feat in features_out:
        r = feat["properties"]["flood_rank"]
        rank_counts[r] = rank_counts.get(r, 0) + 1
    print("  ランク別件数:")
    for r in sorted(rank_counts):
        label = RANK_TABLE.get(r, ("?",))[0]
        print(f"    rank {r} ({label}): {rank_counts[r]:,}件")

    return 0


# ── エントリポイント ──────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="洪水浸水想定区域データ正規化")
    parser.add_argument("--input",      required=True,  help="入力ファイルパス (.geojson / .json / .zip)")
    parser.add_argument("--output",     required=True,  help="出力 GeoJSON パス")
    parser.add_argument("--dataset-id", default="",     help="データセット ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root   = Path(__file__).resolve().parent.parent.parent
    input_path  = Path(args.input)
    output_path = Path(args.output)
    if not input_path.is_absolute():
        input_path = repo_root / input_path
    if not output_path.is_absolute():
        output_path = repo_root / output_path

    if not input_path.exists():
        print(
            f"[ERROR] 入力ファイルが見つかりません: {input_path}\n"
            f"  data_lake/raw/tokyo/flood/ にデータを配置してください。",
            file=sys.stderr,
        )
        return 1

    return normalize(input_path, output_path, dataset_id=args.dataset_id)


if __name__ == "__main__":
    sys.exit(main())

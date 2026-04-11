#!/usr/bin/env python3
"""
内水浸水想定区域データ正規化スクリプト（国土数値情報 A51）

対応入力フォーマット:
  - 単一 GeoJSON / JSON ファイル (.geojson, .json)
  - ZIP アーカイブ (内部の全 .geojson / .json を自動展開・マージ)
  - ディレクトリ (内部の全 .geojson / .json を再帰的にマージ)

出力: GeoJSON FeatureCollection

正規化プロパティ:
  hazard_type  = "inland_flood"
  dataset_id   = <--dataset-id 引数>
  depth_rank   (int 0-7): 浸水深区分
  depth_min_m  (float): 浸水深下限 [m]
  depth_max_m  (float | null): 浸水深上限 [m]
  depth_label  (str): 元テキスト (例: "1m以上3m未満")
  zone_name    (str): 市区町村名
  city_code    (str): 市区町村コード

浸水深ランク (A51_005):
  1: 0.3m未満          2: 0.3m以上0.5m未満
  3: 0.5m以上1m未満    4: 1m以上3m未満
  5: 3m以上5m未満      6: 5m以上10m未満
  7: 10m以上20m未満
"""

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Optional

# ── 浸水深テーブル ─────────────────────────────────────────────────────────

# label → (depth_min_m, depth_max_m or None, depth_rank)
_DEPTH_MAP: dict[str, tuple] = {
    "0.3m未満":         (0.0,  0.3,  1),
    "0.3m以上0.5m未満": (0.3,  0.5,  2),
    "0.5m以上1m未満":   (0.5,  1.0,  3),
    "1m以上3m未満":     (1.0,  3.0,  4),
    "3m以上5m未満":     (3.0,  5.0,  5),
    "5m以上10m未満":    (5.0, 10.0,  6),
    "10m以上20m未満":  (10.0, 20.0,  7),
}


# ── 入力読み込み ───────────────────────────────────────────────────────────

def _parse_geojson_bytes(raw: bytes, label: str) -> dict:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON 解析エラー ({label}): {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"GeoJSON ルートはオブジェクト必須 ({label})")
    return data


def _load_geojson_file(path: Path) -> dict:
    """単一ファイルを読んで dict を返す。失敗時は ValueError。"""
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"ファイルを開けません: {exc}") from exc
    return _parse_geojson_bytes(raw, str(path))


def iter_features(input_path: Path):
    """
    入力パス（ファイル / ZIP / ディレクトリ）から Feature dict を yield する。
    ValueError: 入力が無効または空の場合。
    """
    suffix = input_path.suffix.lower()

    if input_path.is_dir():
        files = sorted(input_path.rglob("*.geojson")) + sorted(input_path.rglob("*.json"))
        # .json と .geojson が重複しないよう stem でユニーク化
        seen: set[Path] = set()
        files = [f for f in files if not (f in seen or seen.add(f))]  # type: ignore[func-returns-value]
        if not files:
            raise ValueError(f"ディレクトリ内に GeoJSON ファイルが見つかりません: {input_path}")
        print(f"ディレクトリ読み込み: {len(files)} ファイル")
        for fp in files:
            data = _load_geojson_file(fp)
            yield from data.get("features", [])
        return

    if suffix == ".zip":
        print(f"読み込み中 (ZIP): {input_path}")
        try:
            with zipfile.ZipFile(input_path, "r") as zf:
                candidates = sorted(
                    n for n in zf.namelist()
                    if n.lower().endswith((".geojson", ".json"))
                    and not n.startswith("__MACOSX")
                )
                if not candidates:
                    raise ValueError(
                        f"ZIP 内に .geojson / .json が見つかりません: {input_path}\n"
                        f"  ZIP 内容: {zf.namelist()[:20]}"
                    )
                print(f"  ZIP 内 GeoJSON: {len(candidates)} ファイル")
                for name in candidates:
                    raw = zf.read(name)
                    data = _parse_geojson_bytes(raw, f"{input_path}::{name}")
                    yield from data.get("features", [])
        except zipfile.BadZipFile as exc:
            raise ValueError(
                f"ZIP 読み込みエラー: {input_path}\n"
                f"  ファイルが破損しているか ZIP 形式ではありません: {exc}"
            ) from exc
        return

    if suffix in {".geojson", ".json"}:
        print(f"読み込み中 (GeoJSON): {input_path}")
        data = _load_geojson_file(input_path)
        yield from data.get("features", [])
        return

    raise ValueError(
        f"非対応の入力形式: {suffix!r}\n"
        f"  対応: .geojson / .json / .zip / ディレクトリ\n"
        f"  入力: {input_path}"
    )


# ── 正規化 ────────────────────────────────────────────────────────────────

def normalize(input_path: Path, output_path: Path, dataset_id: str) -> int:
    try:
        raw_features = list(iter_features(input_path))
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    total_in = len(raw_features)
    features_out: list[dict] = []
    skipped_no_geom = 0
    skipped_bad_geom = 0
    unknown_labels: dict[str, int] = {}

    for feat in raw_features:
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

        depth_label = props.get("A51_005") or props.get("depth_label") or ""
        depth_info  = _DEPTH_MAP.get(depth_label)

        if depth_info is None:
            unknown_labels[depth_label] = unknown_labels.get(depth_label, 0) + 1
            depth_min_m, depth_max_m, depth_rank = 0.0, None, 0
        else:
            depth_min_m, depth_max_m, depth_rank = depth_info

        out_props: dict = {
            "hazard_type": "inland_flood",
            "depth_rank":  depth_rank,
            "depth_min_m": depth_min_m,
            "depth_label": depth_label,
            "zone_name":   props.get("A51_003") or props.get("zone_name") or "",
            "city_code":   props.get("A51_004") or props.get("city_code") or "",
        }
        if depth_max_m is not None:
            out_props["depth_max_m"] = depth_max_m
        if dataset_id:
            out_props["dataset_id"] = dataset_id

        features_out.append({"type": "Feature", "properties": out_props, "geometry": geom})

    if unknown_labels:
        print(
            f"[WARN] 未知の depth_label が {sum(unknown_labels.values())} 件 (depth_rank=0 で出力):",
            file=sys.stderr,
        )
        for label, cnt in sorted(unknown_labels.items(), key=lambda x: -x[1]):
            print(f"  {cnt:>6}件: {label!r}", file=sys.stderr)

    if not features_out:
        print(
            f"[ERROR] 出力フィーチャが 0 件です。入力データを確認してください。\n"
            f"  入力: {total_in}  ジオメトリなし: {skipped_no_geom}  非対応ジオメトリ: {skipped_bad_geom}",
            file=sys.stderr,
        )
        return 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(
            {"type": "FeatureCollection", "name": "tokyo_inland_flood_A51", "features": features_out},
            f, ensure_ascii=False, separators=(",", ":"),
        )
        f.write("\n")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"完了: {output_path}")
    print(f"  入力: {total_in}  出力: {len(features_out)}  スキップ: {skipped_no_geom + skipped_bad_geom}")
    print(f"  ファイルサイズ: {size_mb:.2f} MB")

    rank_counts: dict[int, int] = {}
    for feat in features_out:
        r = feat["properties"]["depth_rank"]
        rank_counts[r] = rank_counts.get(r, 0) + 1
    print("  ランク別件数:")
    for r in sorted(rank_counts):
        label = next((la for la, (_, _, rk) in _DEPTH_MAP.items() if rk == r), "未知")
        print(f"    rank {r} ({label}): {rank_counts[r]:,}件")

    return 0


# ── エントリポイント ──────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="内水浸水想定区域データ正規化 (A51)")
    parser.add_argument(
        "--input",
        required=True,
        help="入力パス (単一 .geojson / .json / .zip / ディレクトリ)",
    )
    parser.add_argument("--output",     required=True, help="出力 GeoJSON パス")
    parser.add_argument("--dataset-id", default="",    help="データセット ID")
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
            f"[ERROR] 入力が見つかりません: {input_path}\n"
            f"  data_lake/raw/tokyo/inland_flood/ にデータを配置してください。",
            file=sys.stderr,
        )
        return 1

    return normalize(input_path, output_path, dataset_id=args.dataset_id)


if __name__ == "__main__":
    sys.exit(main())

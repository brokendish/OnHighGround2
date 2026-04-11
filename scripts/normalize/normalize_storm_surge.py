#!/usr/bin/env python3
"""
高潮浸水想定区域データ正規化スクリプト

対応入力フォーマット:
  - GeoJSON / JSON (.geojson, .json)
  - ZIP アーカイブ (内部の .geojson / .json を自動検出)

出力: GeoJSON FeatureCollection

正規化プロパティ:
  hazard_type    = "storm_surge"
  dataset_id     = <--dataset-id 引数>
  storm_surge_rank (int 1-7): 浸水深区分
  depth_text     (str): 元テキスト (例: "0.3m以上0.5m未満")
  depth          (float): 代表浸水深 [m] (区間中央値)

浸水深ランク対応:
  1: 0.3m未満          → depth 0.15
  2: 0.3m以上0.5m未満  → depth 0.40
  3: 0.5m以上1m未満    → depth 0.75
  4: 1m以上3m未満      → depth 2.00
  5: 3m以上5m未満      → depth 4.00
  6: 5m以上10m未満     → depth 7.50
  7: 10m以上20m未満    → depth 15.0
"""

import argparse
import io
import json
import sys
import zipfile
from pathlib import Path

# ── 浸水深ルックアップテーブル ─────────────────────────────────────────────

DEPTH_TABLE: dict[str, tuple[int, float]] = {
    # depth_text → (rank, representative depth [m])
    "0.3m未満":         (1, 0.15),
    "0.3m以上0.5m未満": (2, 0.40),
    "0.5m以上1m未満":   (3, 0.75),
    "1m以上3m未満":     (4, 2.00),
    "3m以上5m未満":     (5, 4.00),
    "5m以上10m未満":    (6, 7.50),
    "10m以上20m未満":   (7, 15.0),
}

RAW_DEFAULT = "data_lake/raw/tokyo/storm_surge/A49-20_13.geojson"
OUT_DEFAULT = "data_lake/normalized/tokyo/storm_surge/tokyo_storm_surge.geojson"


# ── 引数解析 ───────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="高潮浸水想定区域データ正規化")
    parser.add_argument("--input",      default=RAW_DEFAULT, help="入力ファイルパス (.geojson / .json / .zip)")
    parser.add_argument("--output",     default=OUT_DEFAULT,  help="出力 GeoJSON パス")
    parser.add_argument("--dataset-id", default="",           help="データセット ID（properties.dataset_id に付加）")
    return parser.parse_args()


# ── 入力読み込み ───────────────────────────────────────────────────────────

def _load_geojson_bytes(raw: bytes, source_label: str) -> dict:
    """バイト列を GeoJSON として解析する。失敗時は ValueError を上げる。"""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"JSON 解析エラー ({source_label}): {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"GeoJSON のルートはオブジェクトである必要があります ({source_label})")
    if data.get("type") not in {"FeatureCollection", "Feature"}:
        raise ValueError(
            f"サポートされていない GeoJSON タイプです: {data.get('type')!r} ({source_label})\n"
            f"  対応: FeatureCollection / Feature"
        )
    return data


def load_input(input_path: Path) -> dict:
    """入力ファイルを読み込み GeoJSON dict を返す。"""
    suffix = input_path.suffix.lower()

    if suffix in {".geojson", ".json"}:
        print(f"読み込み中 (GeoJSON): {input_path}")
        try:
            raw = input_path.read_bytes()
        except OSError as exc:
            raise FileNotFoundError(f"入力ファイルを開けません: {exc}") from exc
        return _load_geojson_bytes(raw, str(input_path))

    if suffix == ".zip":
        print(f"読み込み中 (ZIP): {input_path}")
        try:
            with zipfile.ZipFile(input_path, "r") as zf:
                candidates = [n for n in zf.namelist() if n.lower().endswith((".geojson", ".json"))
                              and not n.startswith("__MACOSX")]
                if not candidates:
                    names = zf.namelist()
                    raise ValueError(
                        f"ZIP 内に .geojson / .json ファイルが見つかりません: {input_path}\n"
                        f"  ZIP 内容: {names[:20]}"
                    )
                # 複数ある場合は最初のものを使用
                chosen = candidates[0]
                if len(candidates) > 1:
                    print(f"  複数の GeoJSON 候補が見つかりました。先頭を使用: {chosen}", file=sys.stderr)
                    print(f"  候補: {candidates}", file=sys.stderr)
                raw = zf.read(chosen)
                print(f"  ZIP 内ファイル: {chosen} ({len(raw):,} bytes)")
                return _load_geojson_bytes(raw, f"{input_path}::{chosen}")
        except zipfile.BadZipFile as exc:
            raise ValueError(
                f"ZIP ファイルの読み込みに失敗しました: {input_path}\n"
                f"  ファイルが破損しているか、ZIP 形式ではない可能性があります: {exc}"
            ) from exc

    raise ValueError(
        f"サポートされていない入力形式です: {suffix!r}\n"
        f"  対応拡張子: .geojson / .json / .zip\n"
        f"  入力パス: {input_path}"
    )


# ── 正規化処理 ────────────────────────────────────────────────────────────

def normalize(input_path: Path, output_path: Path, dataset_id: str) -> int:
    # 入力読み込み
    try:
        data = load_input(input_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    # Feature リストを取得
    if data["type"] == "FeatureCollection":
        features_in = data.get("features") or []
    else:
        # Feature 単体
        features_in = [data]

    total_in = len(features_in)
    features_out = []
    skipped_no_geom = 0
    skipped_bad_geom = 0
    unknown_depth_labels: dict[str, int] = {}

    for feat in features_in:
        props = feat.get("properties") or {}
        geom  = feat.get("geometry")

        if not geom:
            skipped_no_geom += 1
            continue

        geom_type = geom.get("type", "")
        if geom_type not in {"Polygon", "MultiPolygon"}:
            skipped_bad_geom += 1
            print(
                f"[WARN] 非対応ジオメトリをスキップ: {geom_type!r}",
                file=sys.stderr,
            )
            continue

        # 浸水深テキスト (A49_003 または既正規化済みの depth_text / depth_label)
        depth_text = (
            props.get("A49_003")
            or props.get("depth_text")
            or props.get("depth_label")
            or ""
        )

        entry = DEPTH_TABLE.get(depth_text)
        if entry is None:
            unknown_depth_labels[depth_text] = unknown_depth_labels.get(depth_text, 0) + 1
            rank  = 0
            depth = None
        else:
            rank, depth = entry

        out_props: dict = {
            "hazard_type":      "storm_surge",
            "storm_surge_rank": rank,
            "depth_text":       depth_text,
        }
        if depth is not None:
            out_props["depth"] = depth
        if dataset_id:
            out_props["dataset_id"] = dataset_id

        features_out.append({
            "type":       "Feature",
            "properties": out_props,
            "geometry":   geom,
        })

    # 未知ラベル警告
    if unknown_depth_labels:
        print(
            f"[WARN] 未知の depth_text が {sum(unknown_depth_labels.values())} 件ありました。"
            f" storm_surge_rank=0、depth=null で出力します。",
            file=sys.stderr,
        )
        for label, cnt in sorted(unknown_depth_labels.items(), key=lambda x: -x[1]):
            print(f"  {cnt:>6}件: {label!r}", file=sys.stderr)

    if not features_out:
        print(
            "[ERROR] 出力フィーチャが 0 件です。入力データを確認してください。\n"
            f"  入力フィーチャ数: {total_in}\n"
            f"  ジオメトリなし: {skipped_no_geom}\n"
            f"  非対応ジオメトリ: {skipped_bad_geom}",
            file=sys.stderr,
        )
        return 1

    # 出力
    output_path.parent.mkdir(parents=True, exist_ok=True)
    result = {
        "type":     "FeatureCollection",
        "name":     "tokyo_storm_surge",
        "features": features_out,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, separators=(",", ":"))
        f.write("\n")

    size_mb = output_path.stat().st_size / 1024 / 1024
    print(f"完了: {output_path}")
    print(f"  入力フィーチャ数:    {total_in}")
    print(f"  出力フィーチャ数:    {len(features_out)}")
    if skipped_no_geom:
        print(f"  スキップ(ジオメトリなし): {skipped_no_geom}")
    if skipped_bad_geom:
        print(f"  スキップ(非対応ジオメトリ): {skipped_bad_geom}")
    print(f"  ファイルサイズ:      {size_mb:.1f} MB")

    # ランク別集計
    rank_counts: dict[int, int] = {}
    for feat in features_out:
        r = feat["properties"]["storm_surge_rank"]
        rank_counts[r] = rank_counts.get(r, 0) + 1
    print("  ランク別件数:")
    for r in sorted(rank_counts):
        label = next((k for k, (v, _) in DEPTH_TABLE.items() if v == r), "?")
        print(f"    rank {r} ({label}): {rank_counts[r]:,}件")

    return 0


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
            f"  先にデータを data_lake/raw/tokyo/storm_surge/ に配置してください。",
            file=sys.stderr,
        )
        return 1

    return normalize(input_path, output_path, dataset_id=args.dataset_id)


if __name__ == "__main__":
    sys.exit(main())

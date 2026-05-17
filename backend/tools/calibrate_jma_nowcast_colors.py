"""
calibrate_jma_nowcast_colors.py — JMA 降水ナウキャスト PNG タイルから出現色を収集する

使用例:
  python backend/tools/calibrate_jma_nowcast_colors.py \\
    --lat 35.681236 --lon 139.767125 \\
    --radius-tiles 1 \\
    --output data_runtime/backend/weather/jma_nowcast_color_observations.json

  python backend/tools/calibrate_jma_nowcast_colors.py \\
    --lat 35.681236 --lon 139.767125 \\
    --radius-tiles 2 --zoom 8 \\
    --output data_runtime/backend/weather/jma_nowcast_color_observations.json

出力形式:
  {
    "observed_at": "2026-05-17T12:00:00+09:00",
    "zoom": 8,
    "tiles_checked": 9,
    "colors": [
      {
        "rgba": [255, 255, 255, 255],
        "count": 102034,
        "matched_intensity": "none",
        "distance_sq": 0
      },
      {
        "rgba": [123, 123, 123, 255],
        "count": 53,
        "matched_intensity": "unknown",
        "distance_sq": null
      }
    ]
  }
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sys
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_PROJECT_ROOT / "backend"))

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow が必要です。pip install Pillow でインストールしてください。", file=sys.stderr)
    sys.exit(1)

_USER_AGENT = "OnHighGround2/1.0 calibration-tool (https://ohg.brokendish.org/)"
_TARGET_TIMES_N1_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json"
_TILE_SIZE = 256


def _http_get(url: str, timeout: int = 10) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _load_color_table(runtime_path: Path, registry_path: Path) -> tuple[list, int, str]:
    """(entries, threshold_sq, version) を返す。ない場合は fallback。"""
    fallback = [
        (160, 210, 255, "weak",     1),
        ( 33, 140, 255, "weak",     2),
        (  0,  65, 255, "moderate", 3),
        (  0, 200, 200, "moderate", 4),
        (  0, 200,   0, "strong",   5),
        (255, 215,   0, "strong",   6),
        (255, 140,   0, "severe",   7),
        (255,   0,   0, "severe",   8),
        (180,   0, 180, "severe",   9),
    ]
    for path in (runtime_path, registry_path):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            entries = [
                (e["rgb"][0], e["rgb"][1], e["rgb"][2], e["intensity"], e["rain_class"])
                for e in data.get("colors", [])
                if e.get("rain_class", 0) >= 1
            ]
            threshold_sq = int(data.get("distance_threshold", 40)) ** 2
            version = str(data.get("version", "unknown"))
            print(f"[色テーブル] {path.name} (version={version}, entries={len(entries)}, threshold={int(threshold_sq**0.5)})")
            return entries, threshold_sq, version
        except Exception as exc:
            print(f"[警告] 色テーブル読み込み失敗 {path}: {exc}", file=sys.stderr)
    print("[色テーブル] fallback を使用します")
    return fallback, 40 ** 2, "fallback"


def _match_color(r: int, g: int, b: int, entries: list, threshold_sq: int, bg_min: int = 230, alpha_max: int = 50, alpha: int = 255) -> tuple[str, int | None]:
    if alpha < alpha_max:
        return "none", 0
    if r >= bg_min and g >= bg_min and b >= bg_min:
        return "none", 0
    best_intensity = "unknown"
    best_dist_sq: float = float("inf")
    for tr, tg, tb, intensity, _ in entries:
        d = (r - tr) ** 2 + (g - tg) ** 2 + (b - tb) ** 2
        if d < best_dist_sq:
            best_dist_sq = d
            best_intensity = intensity
    if best_dist_sq > threshold_sq:
        return "unknown", None
    return best_intensity, int(best_dist_sq)


def _lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[int, int]:
    n = 2 ** zoom
    tx = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    ty = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n)
    return tx, ty


def _fetch_latest_tile_url_template() -> str:
    raw = _http_get(_TARGET_TIMES_N1_URL)
    entries = json.loads(raw)
    if not isinstance(entries, list) or not entries:
        raise ValueError("targetTimes_N1 が空です")
    latest = entries[-1]
    basetime = str(latest.get("basetime", ""))
    validtime = str(latest.get("validtime", basetime))
    return (
        "https://www.jma.go.jp/bosai/jmatile/data/nowc/"
        + basetime + "/none/" + validtime + "/surf/hrpns/{z}/{x}/{y}.png"
    )


def _fetch_tile_png(url: str) -> bytes:
    return _http_get(url, timeout=10)


def collect_colors(
    lat: float,
    lon: float,
    zoom: int,
    radius_tiles: int,
    color_entries: list,
    threshold_sq: int,
    bg_min: int = 230,
    alpha_max: int = 50,
) -> tuple[list[dict], int]:
    """
    lat/lon 周辺 (2*radius_tiles+1)^2 タイルを取得し、出現 RGBA 色を集計する。

    Returns: (colors_list, tiles_checked)
    """
    if zoom % 2 != 0:
        zoom = max(zoom - 1, 4)

    template = _fetch_latest_tile_url_template()
    print(f"[タイル] {template.split('/hrpns/')[0].split('/')[-1]} @ zoom={zoom}")

    cx, cy = _lat_lon_to_tile(lat, lon, zoom)
    pixel_counter: Counter = Counter()
    tiles_ok = 0
    tiles_fail = 0

    for dy in range(-radius_tiles, radius_tiles + 1):
        for dx in range(-radius_tiles, radius_tiles + 1):
            tx, ty = cx + dx, cy + dy
            url = (
                template
                .replace("{z}", str(zoom))
                .replace("{x}", str(tx))
                .replace("{y}", str(ty))
            )
            try:
                raw = _fetch_tile_png(url)
                img = Image.open(io.BytesIO(raw)).convert("RGBA")
                pixels = img.load()
                w, h = img.size
                for py in range(h):
                    for px in range(w):
                        pixel_counter[pixels[px, py]] += 1
                tiles_ok += 1
                print(f"  取得OK: tile({tx},{ty})")
            except Exception as exc:
                tiles_fail += 1
                print(f"  取得NG: tile({tx},{ty}): {exc}", file=sys.stderr)
            time.sleep(0.2)   # JMA サーバーへの負荷軽減

    print(f"[集計] タイル取得 OK={tiles_ok} NG={tiles_fail}")
    print(f"[集計] ユニーク色数={len(pixel_counter)}")

    colors_sorted = pixel_counter.most_common()
    result = []
    for (r, g, b, a), count in colors_sorted:
        matched, dist_sq = _match_color(r, g, b, color_entries, threshold_sq, bg_min, alpha_max, a)
        result.append({
            "rgba": [r, g, b, a],
            "count": count,
            "matched_intensity": matched,
            "distance_sq": dist_sq,
        })

    return result, tiles_ok + tiles_fail


def main() -> None:
    parser = argparse.ArgumentParser(
        description="JMA 降水ナウキャスト PNG タイルから出現色を収集する"
    )
    parser.add_argument("--lat",  type=float, required=True, help="緯度")
    parser.add_argument("--lon",  type=float, required=True, help="経度")
    parser.add_argument("--zoom", type=int, default=8, help="タイルズームレベル（偶数推奨, default=8）")
    parser.add_argument("--radius-tiles", type=int, default=1, help="中心タイル周辺の取得半径（1=3x3, 2=5x5）")
    parser.add_argument(
        "--output", type=Path,
        default=_PROJECT_ROOT / "data_runtime" / "backend" / "weather" / "jma_nowcast_color_observations.json",
        help="出力 JSON パス",
    )
    parser.add_argument("--color-table-runtime", type=Path,
        default=_PROJECT_ROOT / "data_runtime" / "backend" / "weather" / "jma_nowcast_color_table.json")
    parser.add_argument("--color-table-registry", type=Path,
        default=_PROJECT_ROOT / "data_lake" / "registry" / "weather" / "jma_nowcast_color_table.json")
    args = parser.parse_args()

    color_entries, threshold_sq, version = _load_color_table(
        args.color_table_runtime, args.color_table_registry
    )
    bg_min = 230
    alpha_max = 50

    print(f"\n[観測開始] lat={args.lat} lon={args.lon} zoom={args.zoom} radius={args.radius_tiles}")

    colors, tiles_checked = collect_colors(
        lat=args.lat,
        lon=args.lon,
        zoom=args.zoom,
        radius_tiles=args.radius_tiles,
        color_entries=color_entries,
        threshold_sq=threshold_sq,
        bg_min=bg_min,
        alpha_max=alpha_max,
    )

    # 未知色のサマリー
    unknown_colors = [c for c in colors if c["matched_intensity"] == "unknown"]
    print(f"\n[結果] 全ユニーク色: {len(colors)}")
    print(f"[結果] 未知色: {len(unknown_colors)}")
    if unknown_colors:
        print("[未知色トップ10]")
        for c in unknown_colors[:10]:
            print(f"  rgba={c['rgba']} count={c['count']}")

    now_jst = datetime.now(timezone.utc).astimezone()
    output_data = {
        "observed_at": now_jst.isoformat(),
        "zoom": args.zoom,
        "tiles_checked": tiles_checked,
        "color_table_version": version,
        "colors": colors,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"\n[出力] {args.output}")


if __name__ == "__main__":
    main()

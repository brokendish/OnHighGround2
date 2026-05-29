# /live Phase 2-D 雨雲面スキャン方式 調査レポート

調査日: 2026-05-29 (JST)  
対象: Phase 2-D 雨雲面スキャン方式  
方針: **実装修正なし / コード変更なし / 調査のみ**

## 結論

千葉県（木更津・市原・茂原周辺）の強雨域は、現在の実データ調査では **A: 雨雲面スキャン自体で未検出** だった。

具体的には、Phase 2-D の主 scan は `SCAN_ZOOM=6`, `PIXEL_STRIDE=4`, `STRONG_PIXEL_THRESHOLD=3` で判定している。千葉周辺を含む zoom 6 タイル `(tx=56, ty=25)` は、stride 4 では `strong_count=0`, `severe_count=2` となり、`strong+severe=2` で閾値 3 未満のため candidate area が生成されない。

一方、同じタイルをより細かく見ると強雨ピクセルは存在する。

```text
z6_chiba tile 56/25
stride 1: strong=15 severe=20
stride 2: strong=3  severe=6
stride 4: strong=0  severe=2  ← 現行設定。閾値3未満
stride 8: strong=0  severe=0
```

そのため、千葉は candidate area 生成後の ranking / sort / limit で落ちたのではなく、candidate 生成前に落ちている。

## 調査対象コード整理

対象ファイル:

- `backend/app/services/live_rain_tile_scan_service.py`
- `backend/app/services/live_rain_summary_service.py`

### candidate area 作成箇所

`backend/app/services/live_rain_tile_scan_service.py`

- `_scan_one_tile()` がタイルごとの `strong_count`, `severe_count`, `moderate_count`, `unknown_count` を集計する。
- `scan_rain_tiles()` が各 `tile_results` を見て `all_areas` を作る。
- candidate 条件は `strong + severe >= STRONG_PIXEL_THRESHOLD`。

該当箇所:

```text
live_rain_tile_scan_service.py:254-281
```

### danger / warning 判定箇所

`scan_rain_tiles()` 内:

```text
level = "danger" if severe > 0 else "warning"
```

該当箇所:

```text
live_rain_tile_scan_service.py:269
```

### areas 上限適用箇所

`build_rain_section_from_scan()` が `qualifying_areas[:_MAX_AREAS]` で上限適用する。

該当箇所:

```text
live_rain_summary_service.py:331-335
```

### sort 箇所

`build_rain_section_from_scan()` が danger 優先で sort する。

```text
qualifying_areas.sort(key=lambda a: 0 if a.get("level") == "danger" else 1)
```

該当箇所:

```text
live_rain_summary_service.py:331-333
```

### ラベル生成箇所

`nearest_prefecture()` でタイル中心に最も近い代表点から `prefecture` / `label` を推定する。

該当箇所:

```text
live_rain_tile_scan_service.py:79-84
live_rain_tile_scan_service.py:266-278
```

## 実データ調査

実行環境:

```text
backend container: evacuation-navi-backend
JMA nowcast basetime: 20260529101500
validtime: 20260529101500
scan config:
  zoom=6
  bbox=(24.0, 122.0, 46.5, 146.5)
  max_tiles=64
  stride=4
  threshold=3
```

実行内容:

- `get_rain_tile_latest()` で実 nowcast タイル URL を取得。
- `scan_rain_tiles(tile_url, LIVE_RAIN_SAMPLE_POINTS)` を直接実行。
- `build_rain_section_from_scan()` で採用 area も確認。

## Candidate Area 一覧

実 scan 結果:

```text
scan_status ok
scan_tile_count 36
tile_results 36
candidate_count 2
warning_count 0
danger_count 2
unknown_count 0
```

candidate area:

| # | label | level | lat | lng | tx | ty | strong | severe |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 沖縄県付近 | danger | 24.5271 | 120.9375 | 53 | 27 | 3 | 4 |
| 2 | 沖縄県付近 | danger | 24.5271 | 126.5625 | 54 | 27 | 2 | 1 |

採用 area:

| # | label | level | lat | lng |
| --- | --- | --- | ---: | ---: |
| 1 | 沖縄県付近 | danger | 24.5271 | 120.9375 |
| 2 | 沖縄県付近 | danger | 24.5271 | 126.5625 |

API summary も同じ結果:

```json
"rain": {
  "status": "ok",
  "evaluated": true,
  "reason": "tile_scan",
  "summary": {
    "strong_rain_detected": true,
    "warning_area_count": 0,
    "danger_area_count": 2,
    "sample_count": null,
    "unknown_count": 0,
    "scan_tile_count": 36,
    "scan_pixel_stride": 4
  },
  "areas": [
    {"label": "沖縄県付近", "level": "danger", "lat": 24.5271, "lng": 120.9375},
    {"label": "沖縄県付近", "level": "danger", "lat": 24.5271, "lng": 126.5625}
  ]
}
```

## 千葉周辺の確認

代表確認地点:

- 木更津: `35.3813, 139.9249`
- 市原: `35.4981, 140.1154`
- 茂原: `35.4285, 140.2881`

現行 scan zoom 6 では、木更津・市原・茂原周辺は主に tile `(56,25)` に入る。

```text
tile 56/25 bounds:
lat 31.9522 .. 36.5979
lng 135.0000 .. 140.6250
center 34.3071, 137.8125
```

現行設定での tile `(56,25)`:

```text
zoom=6 tx=56 ty=25
strong=0 severe=2 moderate=4 unknown=0 fetch_failed=False
strong+severe=2 < threshold 3
```

よって candidate area は生成されない。

## 高ズーム / stride 比較

同じ実 nowcast タイル URL で、千葉周辺を別 zoom / stride で観察した。

```text
z6_chiba 6/56/25
  stride 1 strong=15 severe=20 moderate=44 sampled=65536
  stride 2 strong=3  severe=6  moderate=13 sampled=16384
  stride 4 strong=0  severe=2  moderate=4  sampled=4096  ← 現行
  stride 8 strong=0  severe=0  moderate=1  sampled=1024

z8_ichihara 8/227/100
  stride 1 strong=196 severe=129 moderate=369
  stride 2 strong=49  severe=32  moderate=93
  stride 4 strong=10  severe=8   moderate=31
  stride 8 strong=2   severe=2   moderate=9

z10_ichihara 10/910/403
  stride 1 strong=82 severe=4 moderate=322
  stride 2 strong=23 severe=2 moderate=93
  stride 4 strong=7  severe=1 moderate=26
  stride 8 strong=3  severe=0 moderate=9
```

この結果から、千葉周辺に強雨ピクセルは存在するが、現行の `zoom=6 + stride=4 + threshold=3` では候補化されないことが分かる。

## 沖縄周辺の確認

実 scan の candidate に沖縄周辺は存在する。

```text
tx=53 ty=27 label=沖縄県付近 level=danger lat=24.5271 lng=120.9375 strong=3 severe=4
tx=54 ty=27 label=沖縄県付近 level=danger lat=24.5271 lng=126.5625 strong=2 severe=1
```

この2件がそのまま `build_rain_section_from_scan()` で採用され、API summary / Live 危険地域ランキングへ渡っている。

## 千葉 area の脱落段階

分類:

```text
A: 雨雲面スキャン自体で未検出
```

詳細:

- tile fetch は成功している。
- 千葉周辺 tile `(56,25)` に strong/severe は存在する。
- ただし現行の間引き後カウントが `strong+severe=2`。
- `STRONG_PIXEL_THRESHOLD=3` を満たさず、`all_areas.append()` に到達しない。
- したがって candidate area 生成後の sort / limit 以前に脱落している。

## B/C/D の確認

### B: candidate area 生成で脱落

該当するとも言えるが、より正確には candidate 条件判定で脱落しており、candidate area は生成されていない。

### C: ranking / sort / limit で脱落

該当なし。

根拠:

- candidate area は2件のみ。
- 採用 area も2件。
- `_MAX_AREAS` の5件上限には達していない。
- 千葉候補は candidate list に存在しないため、sort/limit で落ちたものではない。

### D: 都道府県ラベル推定誤り

今回の直接原因ではない。ただし潜在リスクはある。

現行方式は tile center を最近傍代表点に割り当てるため、zoom 6 の大きなタイルではラベルが粗くなる。千葉周辺を含む tile `(56,25)` の中心は `34.3071, 137.8125` で、最近傍推定は `静岡県 浜松付近` になる。

```text
z6_chiba_tile_center 34.3071 137.8125 -> 静岡県 浜松付近
ichihara point        35.4981 140.1154 -> 千葉県付近
mobara point          35.4285 140.2881 -> 千葉県付近
z10_ichihara_center   35.6037 140.0977 -> 千葉県付近
```

つまり、仮に現行 zoom 6 tile `(56,25)` が candidate 化されても、「千葉県付近」ではなく「静岡県付近」と表示される可能性がある。これは今回の「沖縄のみ表示」の直接原因ではないが、Phase 2-D の別問題として注意が必要。

## 原因推定

主原因:

```text
zoom=6 の粗いタイルを PIXEL_STRIDE=4 で間引きしているため、
局地的な千葉強雨セルが sampled pixel に十分当たらず、
STRONG_PIXEL_THRESHOLD=3 を下回った。
```

補助的な構造要因:

- zoom 6 tile は地理的に広く、千葉・神奈川・静岡・中部海域まで同一/隣接タイルに入る。
- area 位置は tile center なので、実際の強雨セル位置ではなく広域タイル中心になる。
- prefecture label も tile center 最近傍で推定されるため、局地セルの実所在地とずれる可能性がある。

## まとめ

| 観点 | 結果 |
| --- | --- |
| candidate 数 | 2 |
| 採用 area 数 | 2 |
| 千葉 area の有無 | なし |
| 沖縄 area の有無 | あり、2件 |
| 千葉 area の脱落段階 | A: 面スキャン candidate 化前 |
| ranking / sort / limit 脱落 | なし |
| ラベル誤推定 | 直接原因ではないが潜在リスクあり |
| 原因推定 | zoom 6 + stride 4 + threshold 3 による局地セル取り逃し |

## 補足

この調査では実装ファイルへの変更は行っていない。一時的な観察は `docker exec evacuation-navi-backend python -c ...` と `/private/tmp` 上の一時スクリプト相当のコマンドのみで実施し、リポジトリ内にログ追加やデバッグコードは残していない。

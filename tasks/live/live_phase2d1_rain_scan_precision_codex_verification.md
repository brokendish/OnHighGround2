# Phase 2-D.1 雨雲面スキャン精度調整 Codex 検証レポート

作成日: 2026-05-29

実施日時: 2026-05-29 22:37-22:40 JST

## 結論

Phase 2-D.1 の検証結果は PASS。

実データで `scan_pixel_stride=2` が反映され、千葉県周辺の強雨セルは candidate として検出され、`prefecture=千葉県` / `label=千葉県付近` として `/api/live/summary` の `rain.areas` および `dangerous_areas` に採用されることを確認した。

なお、検証開始時点では Docker backend が古いイメージを参照しており `scan_pixel_stride=4` が返っていたため、`docker compose build` と `docker compose up -d` で作業ツリーの実装を反映してから確認した。

## 対象

- `backend/app/services/live_rain_tile_scan_service.py`
- `backend/app/services/live_rain_summary_service.py`
- `backend/app/services/live_summary_service.py`
- `frontend/js/live/live-danger-summary.js`
- `frontend/js/live/live-alert-panel.js`
- `e2e/live-basic.spec.js`

## 検証環境

- Backend: Docker container `evacuation-navi-backend`
- Frontend: Docker container `evacuation-navi-frontend`
- Backend `/health`: healthy
- Frontend: Up, `/live.html` HTTP 200
- `/api/live/summary`: HTTP 200

## 実装確認

### スキャン設定

`live_rain_tile_scan_service.py` で以下を確認。

| 項目 | 値 |
| --- | --- |
| `SCAN_ZOOM` | `6` |
| `SCAN_BBOX` | `(24.0, 122.0, 46.5, 146.5)` |
| `MAX_SCAN_TILES` | `64` |
| `PIXEL_STRIDE` | `2` |
| `STRONG_PIXEL_THRESHOLD` | `3` |

### 重心算出

`_scan_one_tile()` で強雨・猛烈雨ピクセルの `x/y` 合計を保持し、`scan_rain_tiles()` で `pixel_to_lat_lng()` により candidate の `lat/lng` を算出していることを確認した。

`strong_severe_count > 0` の場合は強雨・猛烈雨ピクセル重心が代表点として使われる。

### 都道府県判定

candidate の代表点 `lat/lng` に対して `nearest_prefecture(lat, lng, sample_points)` が呼ばれており、タイル中心ではなく重心ベースの代表点で都道府県ラベルを推定している。

### 採用上限

`live_rain_summary_service.py` の `_MAX_AREAS = 5` を確認した。

### ranking / sort

`live_rain_summary_service.py` では `danger` を優先して `warning` より前に並べ、`[:_MAX_AREAS]` で上限適用している。

`live_summary_service.py` と `frontend/js/live/live-danger-summary.js` / `frontend/js/live/live-alert-panel.js` に今回の差分はなく、危険地域ランキング側の既存 sort / 表示ロジックは変更されていない。

## 実データ観察

取得した JMA Nowcast:

| 項目 | 値 |
| --- | --- |
| source | `jma_nowcast` |
| basetime | `20260529103500` |
| validtime | `20260529103500` |
| scan_pixel_stride | `2` |

### candidate 一覧

`rain_scan candidate` ログと直接スキャン結果で以下を確認。

| # | label | level | lat | lng | tile | strong | severe |
| --- | --- | --- | ---: | ---: | --- | ---: | ---: |
| 1 | 沖縄県付近 | danger | 23.5932 | 121.3383 | `(53,27)` | 38 | 20 |
| 2 | 沖縄県付近 | danger | 22.8943 | 124.7791 | `(54,27)` | 10 | 2 |
| 3 | 千葉県付近 | danger | 35.6445 | 140.2797 | `(56,25)` | 2 | 5 |

candidate 総数: 3

採用 area 数: 3

千葉 area: あり

千葉 area は candidate 生成後も脱落せず、summary に採用された。

### ログ抜粋

```text
rain_scan candidate: tile=(53,27) strong=38 severe=20 centroid=(23.5932,121.3383) prefecture=沖縄県
rain_scan candidate: tile=(54,27) strong=10 severe=2 centroid=(22.8943,124.7791) prefecture=沖縄県
rain_scan candidate: tile=(56,25) strong=2 severe=5 centroid=(35.6445,140.2797) prefecture=千葉県
rain_scan area: name=沖縄県付近 risk=danger tile=(53,27)
rain_scan area: name=沖縄県付近 risk=danger tile=(54,27)
rain_scan area: name=千葉県付近 risk=danger tile=(56,25)
```

### API 確認

`/api/live/summary` の `rain.areas` に以下が含まれることを確認。

```json
{
  "label": "千葉県付近",
  "prefecture": "千葉県",
  "area_name": "千葉県付近",
  "level": "danger",
  "type": "rain",
  "source": "jma_nowcast_scan",
  "lat": 35.6445,
  "lng": 140.2797
}
```

同じ千葉県 area は `dangerous_areas` にも含まれていた。

## false-safe 確認

合成 scan result で以下を確認。

| ケース | evaluated | strong_rain_detected | areas |
| --- | --- | --- | ---: |
| weak only | true | false | 0 |
| below threshold | true | false | 0 |
| unknown only | true | false | 0 |

弱雨のみ、閾値未満、unknown のみでは危険 area を出さない。

## 回帰確認

実行結果:

```text
venv/bin/python -m compileall backend/app/services/live_rain_tile_scan_service.py backend/app/services/live_rain_summary_service.py
OK

venv/bin/python -c "..."
import_ok 2 3 5

venv/bin/pytest tests/test_live_rain_summary_service.py tests/test_live_summary_api.py
89 passed in 0.44s

node --check e2e/live-basic.spec.js
OK

npx playwright test e2e/live-basic.spec.js
64 passed

git diff --check
OK
```

## 判定

千葉県周辺の強雨セルは以下すべてを通過している。

| 段階 | 判定 |
| --- | --- |
| 雨雲面スキャン | 検出あり |
| candidate area 生成 | 生成あり |
| 都道府県ラベル推定 | `千葉県` |
| summary area 採用 | 採用あり |
| ranking / API 表示 | 表示あり |

今回の実データでは、Phase 2-D で観察された「千葉県付近が表示されない」事象は再現しなかった。

Phase 2-D.1 の精度調整により、当該タイルはタイル中心ではなく強雨ピクセル重心 `(35.6445, 140.2797)` を代表点として扱い、千葉県として分類されている。原因推定としては、Phase 2-D 時点ではタイル中心代表により県境・海上寄りの代表点になり、都道府県推定または上位 area 採用で千葉県として残らなかった可能性が高い。

## コード変更

この検証では実装修正を行っていない。

作成した成果物は本レポートのみ。

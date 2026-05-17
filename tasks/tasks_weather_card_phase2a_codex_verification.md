# OnHighGround2 気象カード Phase2-A Codex 検証結果

## 検証メタデータ

- 検証日時: 2026-05-17 09:47 JST
- 対象ブランチ: `main`
- 対象 commit: `d30a7f18af0a602a2af4c30452f90a8439898182`
- 対象:
  - `backend/services/jma_rain_tile_service.py`
  - `backend/app/services/weather_alert_service.py`
  - `backend/app/api/weather.py`
  - `backend/tools/calibrate_jma_nowcast_colors.py`
  - `data_runtime/backend/weather/jma_nowcast_color_table.json`
  - `data_lake/registry/weather/jma_nowcast_color_table.json`
- 最終判定: **PASS with notes**

## サマリー

Phase2-A の主要要件は通っています。RGB→intensity 色テーブルは外部 JSON 化され、読み込み順は `runtime -> registry -> fallback` で確認できました。`distance_threshold` も JSON から反映され、unknown opaque 色を `none` に倒さない Phase1.5 の安全側挙動も維持されています。

Docker build、backend 起動、precipitation summary API、既存雨雲レイヤー API、weather alerts API、hazard API、E2E、既存テストはいずれも通過しました。実 JMA タイル色収集 CLI も実行でき、観測 JSON を出力できています。

注意点として、`debug=1` は debug 用 cache miss 時には正しく `debug` を返しますが、同一都道府県で通常 API レスポンスが先に precipitation cache に入っている場合、debug リクエストが通常レスポンス cache を返して `debug` が出ません。core API と通常 UI には影響しないため PASS with notes としますが、Phase2-A の debug 検証観点としては修正推奨です。

## 1. 静的確認

### 確認結果

- RGB→intensity テーブルはコード直書きのみではなく、外部 JSON 読み込みになっている。
- 読み込み順は以下:
  - `data_runtime/backend/weather/jma_nowcast_color_table.json`
  - `data_lake/registry/weather/jma_nowcast_color_table.json`
  - hardcoded fallback
- `distance_threshold` は JSON から読み込まれ、二乗距離として使用される。
- JSON がない場合も hardcoded fallback がある。
- unknown opaque 色は `rain_class=-1` として扱われ、`none` に倒されない。
- unknown の warning log は `_maybe_log_unknown_colors()` で抑制付き。
- 通常 precipitation summary API には `debug` は混入しない。

### 静的メモ

- JSON 内の `rain_class=0` は `_load_color_table()` で読み込み対象から除外され、none 判定は `background_rgb_min` と alpha で処理される設計。
- `background_rgb_min` は配列先頭値のみを `_BG_RGB_MIN` として使用している。現在 JSON は `[230, 230, 230]` なので実害はない。

## 2. Docker / 起動確認

### 実施コマンド

```bash
docker compose build backend
docker compose up -d backend frontend martin osrm-walking
docker compose ps backend frontend martin osrm-walking
```

### 結果

- `docker compose build backend`: PASS
- `docker compose up -d backend frontend martin osrm-walking`: PASS
- `docker compose ps`:
  - backend: `healthy`
  - frontend: `up`
  - martin: `healthy`
  - osrm-walking: `up`

## 3. API 回帰確認

### 実施コマンド

```bash
curl -s 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/rain/tile/times'
curl -i 'http://127.0.0.1:8000/api/weather/alerts/current?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/hazards/active'
```

### 結果

- `/api/weather/precipitation/summary`: HTTP 200
  - `status: "ok"`
  - `severity: "none"`
  - `summary: "降水リスクなし"`
  - `current.intensity: "none"`
  - `forecast[]`: +5 分から +30 分まで schema 通り
  - 通常レスポンスに `debug` はなし
- `/api/weather/rain/tile/times`: HTTP 200
- `/api/weather/alerts/current`: HTTP 200
- `/api/hazards/active`: HTTP 200
- API 500 は確認されなかった。

## 4. 色テーブル読み込み確認

### 実施方法

backend container 内で `services.jma_rain_tile_service._COLOR_TABLE_PATHS` を一時 JSON に差し替え、`_load_color_table()` を直接呼び出した。

### 結果

```text
runtime_precedence runtime-test 121 [(1, 2, 3, 'weak', 1)]
registry_fallback registry-test 484 [(4, 5, 6, 'strong', 5)]
hardcoded_fallback fallback 9
```

- runtime 優先: PASS
- registry fallback: PASS
- JSON なし fallback: PASS
- `distance_threshold` 反映:
  - runtime threshold 11 -> `121`
  - registry threshold 22 -> `484`

## 5. mock PNG 検証

backend container 内で Pillow を使い、`_fetch_tile_png()` と `_lat_lon_to_tile_pixel()` を patch して 32x32 PNG を生成した。

| Case | Expected | Actual | Result |
|---|---:|---:|---|
| recognized none only | `none` | `none` | PASS |
| recognized weak | `weak` | `weak` | PASS |
| recognized moderate | `moderate` | `moderate` | PASS |
| recognized strong | `strong` | `strong` | PASS |
| recognized severe | `severe` | `severe` | PASS |
| unknown opaque only | `unknown` | `unknown` | PASS |
| none + unknown opaque | `unknown` | `unknown` | PASS |
| unknown opaque + strong | `strong` | `strong` | PASS |
| 5x5 内 severe | `severe` | `severe` | PASS |
| 5x5 外 severe | `none` | `none` | PASS |
| tile fetch failure | `unknown` | `unknown` | PASS |

unknown opaque 色を `none` に倒さない要件は満たしている。

## 6. 実タイル色収集 CLI 検証

### 実施コマンド

container 内の実パスに合わせて実行した。

```bash
docker exec evacuation-navi-backend python tools/calibrate_jma_nowcast_colors.py \
  --lat 35.681236 \
  --lon 139.767125 \
  --radius-tiles 0 \
  --output /tmp/jma_nowcast_color_observations.json

docker exec evacuation-navi-backend python -m json.tool /tmp/jma_nowcast_color_observations.json
```

### 結果

- CLI 実行: PASS
- タイル取得: `OK=1 NG=0`
- ユニーク色数: `2`
- 未知色: `0`
- 出力 JSON:
  - `observed_at`: あり
  - `zoom`: あり
  - `tiles_checked`: あり
  - `color_table_version`: あり
  - `colors[]`: あり
  - `rgba`: あり
  - `count`: あり
  - `matched_intensity`: あり
  - `distance_sq`: あり

観測された主な色:

```json
{
  "rgba": [255, 255, 255, 0],
  "count": 65534,
  "matched_intensity": "none",
  "distance_sq": 0
}
```

```json
{
  "rgba": [242, 242, 255, 255],
  "count": 2,
  "matched_intensity": "none",
  "distance_sq": 0
}
```

## 7. debug API 確認

### 確認結果

debug cache miss の地点では `debug=1` で debug 情報が返った。

```bash
curl -s 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=34.6937&lon=135.5023&debug=1'
```

確認できた debug 項目:

- `color_table_version: "2026-05-phase2a"`
- `zoom: 8`
- `sample_radius_px: 2`
- `current_tile_debug.color_table_version`
- `current_tile_debug.unknown_pixel_count`
- `current_tile_debug.total_pixel_count`
- `current_tile_debug.tile_url`

通常 API には `debug` が出なかった。

### debug cache 注意点

同一都道府県で通常 API を先に叩いた後に `debug=1` を叩くと、`get_precipitation_summary()` が `_precip_cache[pref_code]` を先に返すため、debug 情報が返らないケースがある。

再現:

```bash
curl -s 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=35.681236&lon=139.767125'
curl -s 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=35.681236&lon=139.767125&debug=1'
```

2 回目の `debug=1` に `debug` が含まれなかった。

推奨修正:

- `debug=True` の場合は precipitation cache を読まない。
- または cache key に `debug` を含める。
- ただし debug レスポンスを通常 cache に保存しない現在の方針は維持する。

## 8. E2E / 回帰

### 実施コマンド

```bash
npx playwright test e2e/info-tab-card-ui.spec.js --reporter=line
venv/bin/python -m pytest tests/test_weather_temperature.py -q
```

### 結果

- `e2e/info-tab-card-ui.spec.js`: 3 passed
- `tests/test_weather_temperature.py`: 34 passed
- 気温 UI 復活は確認されなかった。

## 9. Notes

- 実 JMA タイル取得時点では雨域がなく、rain 色の実測は少なかった。雨天時に追加観測が必要。
- 色テーブルは `source: "jma_nowcast_approximate"` で、完全な実測確定版ではない。継続キャリブレーション前提。
- `zoom=8` の妥当性は、雨域境界や局地的強雨のケースで継続確認が必要。
- 5x5 サンプリング範囲は安全側だが、実地で広すぎ/狭すぎの確認が必要。
- debug API は cache hit 時の挙動に修正余地がある。

## 最終判定

**PASS with notes**

core 要件である外部色テーブル、読み込み優先順位、fallback、distance threshold 設定化、unknown opaque の安全側処理、CLI、API 200、既存回帰は通過した。残りは debug cache 挙動と、実雨域での色テーブル継続キャリブレーション。

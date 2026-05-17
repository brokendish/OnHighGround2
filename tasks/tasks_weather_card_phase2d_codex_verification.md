# OnHighGround2 気象カード Phase2-D Codex 検証結果

## 検証メタデータ

- 検証日時: 2026-05-17 19:27 JST
- 対象ブランチ: `main`
- 対象 commit: `55be8067fae506a3ba0b20d38da4c7337d2cf8f2`
- 対象:
  - `backend/app/api/weather.py`
  - `backend/app/services/weather_route_risk_service.py`
  - `frontend/js/weather-route-service.js`
  - `frontend/js/navigation.js`
  - `frontend/index.html`
- 最終判定: **PASS with notes**

## サマリー

Phase2-D の再検証を実施した。初回検証で FAIL だった request body 形式、route segment schema、unknown UI 表示はいずれも修正済みとして確認できた。

- `POST /api/weather/risk/route` は `route.coordinates` と top-level `coordinates` の両形式で HTTP 200。
- `segments[]` は `index`, `distance_m`, `precip_intensity`, `hazards`, `combined`, `level`, `risk_level` を返す。
- `unknown` は none と同じ非表示ではなく、灰色の小バナーで `進行方向の降水リスクを判定できません` を表示する。
- route sampling、進行済み区間除外、TTL/cooldown、reroute 非介入を確認。
- 既存 weather / hazard API、情報タブ E2E、気温テストは PASS。

`e2e/navigation-debug-layer.spec.js` の timeout は継続して再現したが、Phase2-D 前 commit `d3055a1` でも同一事象が再現済みとの連携を受けたため、Phase2-D のブロッカーではなく既存不安定テストとして notes 扱いにする。

## 1. 静的確認

### PASS

- route weather risk API がある。
  - `backend/app/api/weather.py`
  - `POST /api/weather/risk/route`
- request body は dual format 対応。
  - `route.coordinates`
  - top-level `coordinates`
  - どちらもない場合は 422。
- route sampling がある。
  - `_SAMPLE_INTERVAL_M = 150`
  - `_MAX_SAMPLES = 12`
- route progress aware がある。
  - `current_idx` 以降の座標だけを `_sample_route()` が対象にする。
- route response schema が拡張されている。
  - `index`
  - `distance_m`
  - `precip_intensity`
  - `hazards`
  - `combined`
  - `level`
  - `risk_level`
- 並列評価後に `segments.sort(key=lambda s: s["_idx"])` で順序保証している。
- unknown を none に倒していない。
- unavailable を warning 扱いしていない。
- frontend は 60 秒 fetch TTL と 90 秒 cooldown を持つ。
- `navigation.js` はナビ中のみ `_weatherRouteUpdate(navActiveRoute, lat, lon)` を呼ぶ。
- ルート終了時に `_weatherRouteClear()` を呼ぶ。
- route scoring / reroute / OSRM weighting を変更する実装は確認されなかった。

### Notes

- `frontend/js/weather-route-service.js` のファイル冒頭コメントに `riskLevel=none/unknown はバナー非表示` という古い説明が残っているが、実装は `none` のみ非表示で、`unknown` は表示する。動作上の問題ではないがコメント更新余地あり。

## 2. Docker / 起動確認

### 実施コマンド

```bash
docker compose build backend frontend
docker compose up -d backend frontend martin osrm-walking
docker compose ps backend frontend martin osrm-walking
curl -s http://127.0.0.1:8000/health
```

### 結果

- `docker compose build backend frontend`: PASS
- `docker compose up -d backend frontend martin osrm-walking`: PASS
- backend: 起動後 healthy 応答あり
- frontend: up
- martin: healthy
- osrm-walking: up

## 3. API 確認

### 指示書形式 request

実施:

```bash
curl -i -X POST \
  'http://127.0.0.1:8000/api/weather/risk/route' \
  -H 'Content-Type: application/json' \
  -d '{"route":{"coordinates":[[139.767125,35.681236],[139.768000,35.682000]]}}'
```

結果:

```text
HTTP/1.1 200 OK
```

代表レスポンス:

```json
{
  "status": "ok",
  "risk_level": "none",
  "segments": [
    {
      "index": 0,
      "distance_m": 0,
      "lat": 35.681236,
      "lon": 139.767125,
      "precip_intensity": "none",
      "hazards": {
        "lowland": true,
        "flood": true,
        "inland_flood": false,
        "landslide": false,
        "tsunami": false,
        "storm_surge": true
      },
      "combined": [],
      "level": "none",
      "risk_level": "none"
    }
  ],
  "summary": {
    "headline": null,
    "message": null
  }
}
```

判定: PASS

### top-level coordinates request

実施:

```bash
curl -s -X POST \
  'http://127.0.0.1:8000/api/weather/risk/route' \
  -H 'Content-Type: application/json' \
  -d '{"coordinates":[[139.767125,35.681236],[139.768000,35.682000]]}'
```

結果:

- HTTP 200
- 指示書形式と同等 schema。

判定: PASS

### invalid request

実施:

```bash
curl -i -X POST \
  'http://127.0.0.1:8000/api/weather/risk/route' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

結果:

```text
HTTP/1.1 422 Unprocessable Entity
coordinates required: provide route.coordinates or top-level coordinates
```

判定: PASS

## 4. route sampling 確認

backend container 内で `_sample_route()` を直接確認した。

結果:

```text
input_points=101
samples=12
first=(35.02, 139.02, 0.0)
last=(35.032, 139.032, 1724.6474198236438)
starts_after_current=True
triple_shape=True
max_samples_ok=True
```

判定: PASS

- 全座標総当たりではない。
- 最大 12 点に制限。
- `current_idx` より後方のみ見る。
- `(lat, lon, distance_m)` の triple を返す。

## 5. mock route risk

backend container 内で precipitation と hazard assessment を mock し、`_build_route_risk()` を直接検証した。

| Case | Expected | Actual | Combined | Segment schema | Result |
|---|---:|---:|---|---|---|
| none | `none` | `none` | `[]` | OK | PASS |
| moderate rain | `advisory` | `advisory` | `[]` | OK | PASS |
| weak rain + lowland | `advisory` | `advisory` | `rain_lowland` | OK | PASS |
| strong rain + flood | `warning` | `warning` | `rain_flood` | OK | PASS |
| severe rain + landslide | `emergency` | `emergency` | `rain_landslide` | OK | PASS |
| precip unknown | `unknown` | `unknown` | `[]` | OK | PASS |

判定: PASS

- `strong rain + flood -> warning` を確認。
- `severe rain + landslide -> emergency` を確認。
- unknown は none に倒れていない。
- 全セグメントに `index / distance_m / precip_intensity / hazards / combined / level / risk_level` がある。

## 6. navigation UI 確認

Playwright で `#nav-route-weather-banner` に mock response を投入した。

### none

```text
display: none
text: ""
class: nav-route-weather-banner
innerHTML: ""
```

判定: PASS

### advisory

```text
display: flex
class: nav-route-weather-banner nrw-banner--advisory
text: 進行方向に雨域接近
```

判定: PASS

### warning

```text
display: flex
class: nav-route-weather-banner nrw-banner--warning
text: 進行方向で強雨リスク
```

判定: PASS

### emergency

```text
display: flex
class: nav-route-weather-banner nrw-banner--emergency
text: 進行方向で危険な降水を検出
hasClose: false
```

判定: PASS

### unknown

```text
display: flex
class: nav-route-weather-banner nrw-banner--unknown
text: 進行方向の降水リスクを判定できません
```

判定: PASS

- unknown を warning 扱いしない。
- unknown を none と同じ非表示にしない。
- `.nrw-banner--unknown` の灰色小バナーで表示する。

## 7. cooldown / 状態遷移

### cooldown

同一 warning を短時間で連続投入した。

結果:

```text
cooldownNoFetch: true
```

判定: PASS

### warning -> unknown -> none

結果:

```text
warning:
  display: flex
  text: 進行方向で強雨リスク

unknown:
  display: flex
  text: 進行方向の降水リスクを判定できません
  class: nrw-banner--unknown

none:
  display: none
  text: ""
  innerHTML: ""
```

判定: PASS

- 古い warning 文言は残らない。
- downgrade / unknown への遷移が即時反映される。
- none で DOM 内容までクリアされる。

## 8. API 回帰

### 実施コマンド

```bash
curl -i 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/risk/context?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/alerts/current?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/hazards/active'
```

### 結果

- precipitation summary API: HTTP 200
- weather risk context API: HTTP 200
- weather alerts API: HTTP 200
- hazards active API: HTTP 200
- schema 崩れや 500 は確認されなかった。

## 9. 回帰確認

### 実施コマンド

```bash
npx playwright test e2e/info-tab-card-ui.spec.js --reporter=line
venv/bin/python -m pytest tests/test_weather_temperature.py -q
npx playwright test e2e/navigation*.spec.js --reporter=line
```

### 結果

- `e2e/info-tab-card-ui.spec.js`: 3 passed
- `tests/test_weather_temperature.py`: 34 passed
- `e2e/navigation*.spec.js`: 1 failed, 1 passed
  - Failed: `e2e/navigation-debug-layer.spec.js`
  - Reason: timeout waiting for `#layer-toggle-btn`

判定:

- weather / info-tab / temperature 回帰は PASS。
- navigation suite の timeout は、Phase2-D 前 commit `d3055a1` でも同一 timeout が再現する既存不安定テストとの連携あり。Phase2-D の FAIL 要因にはしない。

## 10. Notes

- 実タイル・実天候では今回の東京駅周辺 API 結果が `precip_intensity: none` だったため、実 API で strong/severe を観測する確認はできなかった。mock では `strong + flood`、`severe + landslide` を確認済み。
- route highlight は任意項目のため未実装でも PASS 条件外。
- 自動 reroute / route score 変更 / OSRM weighting 変更は確認されなかった。
- `e2e/navigation-debug-layer.spec.js` の `#layer-toggle-btn` timeout は別途安定化対象。

## 最終判定

**PASS with notes**

Phase2-D の必須条件である `/api/weather/risk/route`、route segment risk schema、強雨×ハザードの combined 判定、ナビ UI 表示、unknown の非 false-safe 表示、cooldown、none/unavailable 系の旧文言クリア、既存 API 回帰なしを確認した。残る navigation-debug-layer E2E timeout は既存不安定テストとして切り分ける。

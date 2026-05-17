# OnHighGround2 気象ナビ Phase3-A Codex 検証結果

## 検証メタデータ

- 検証日時: 2026-05-17 20:53 JST
- 対象ブランチ: `main`
- 対象 commit: `c1a69331196af9c2cb7ec0c52658010194dfb5bb`
- 対象:
  - `backend/app/api/navigation.py`
  - `backend/app/services/route_comparison_service.py`
  - `backend/app/services/route_risk_scoring.py`
  - `backend/app/services/weather_route_risk_service.py`
  - `frontend/js/route-ui.js`
  - `frontend/js/location-info-panel.js`
  - `frontend/js/navigation.js`
  - `frontend/index.html`
- 最終判定: **PASS with notes**

## サマリー

Phase3-A の再検証を実施した。初回検証で FAIL だった OSRM port mismatch、unknown の `none` 化、unavailable 時の旧カード残存、座標数ベース sampling は修正済みとして確認できた。

- 実 API `/api/navigation/route/compare` は `status: "ok"` を返す。
- route ごとに `risk_level`, `safety_score`, `risk_summary`, `hazards`, `weather.forecast_max_intensity` が返る。
- mock で「短いが risky なルート」より「少し長いが安全寄りのルート」を推奨できる。
- `weather_risk: "unknown"` は route `risk_level: "unknown"` として保持され、`risk_summary` に `気象リスク判定不能` が出る。
- frontend は `status: "unavailable"` で旧比較カードを消去する。
- route comparison UI、cooldown、route churn threshold、manual selection only を確認。
- 自動 reroute / route 強制変更 / OSRM weighting 書き換えは確認されなかった。

`e2e/navigation-debug-layer.spec.js` の timeout は継続して再現するが、Phase2-D 時点から既存不安定テストとして切り分け済みのため、Phase3-A のブロッカーにはしない。

## 1. 静的確認

### PASS

- route comparison API がある。
  - `backend/app/api/navigation.py`
  - `POST /api/navigation/route/compare`
- route comparison service がある。
  - `backend/app/services/route_comparison_service.py`
- OSRM alternatives を使う構造。
  - `alternatives=3`
  - `overview=full`
  - `geometries=geojson`
- OSRM default URL が docker compose と一致している。
  - `http://osrm-walking:5001/route/v1/walking`
- route ごとの model がある。
  - `index`
  - `distance_m`
  - `duration_s`
  - `risk_level`
  - `safety_score`
  - `risk_summary`
  - `hazards`
  - `weather.forecast_max_intensity`
- weather + hazards を `safety_score` に反映している。
  - `_WEATHER_PENALTY`
  - `_COMBINED_EXTRA`
  - `calc_route_risk_score(exposure)`
- recommendation priority が実装されている。
  - `risk_level`
  - `safety_score`
  - `distance`
  - `duration`
- distance-based sampling がある。
  - `_sample_by_distance()`
  - `_SAMPLE_INTERVAL_M = 200`
  - `_MAX_SAMPLES = 8`
- unknown を none に倒していない。
  - `_to_risk_level()` が `weather_risk == "unknown"` で `unknown` を返す。
  - `INTENSITY_LABEL["unknown"] = "気象リスク判定不能"`
- frontend route comparison UI がある。
  - `frontend/js/route-ui.js`
  - `#lip-route-weather-compare`
- frontend は cooldown / churn threshold を持つ。
  - `_RUI_COOLDOWN_MS = 60_000`
  - `_RUI_CHURN_THRESHOLD = 10`
- `status: "unavailable"` 時に `_ruiHide()` と `_ruiComparison = null` を実行する。
- 自動 reroute / route 強制変更 / OSRM weighting 書き換えは確認されなかった。

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
- backend: healthy
- frontend: up
- martin: healthy
- osrm-walking: up

## 3. API 確認

### 実施コマンド

```bash
curl -s -X POST \
  'http://127.0.0.1:8000/api/navigation/route/compare' \
  -H 'Content-Type: application/json' \
  -d '{
    "origin":[139.767125,35.681236],
    "destination":[139.780000,35.690000]
  }'
```

### 結果

```json
{
  "status": "ok",
  "recommended_route_index": 0,
  "routes": [
    {
      "index": 0,
      "distance_m": 1823,
      "duration_s": 1313,
      "risk_level": "advisory",
      "safety_score": 51.0,
      "risk_summary": [
        "低地・排水困難エリア",
        "洪水想定区域",
        "高潮想定区域"
      ],
      "hazards": {
        "lowland": true,
        "flood": true,
        "inland_flood": false,
        "landslide": false,
        "tsunami": false,
        "storm_surge": true
      },
      "weather": {
        "forecast_max_intensity": "none"
      },
      "status": "ok"
    },
    {
      "index": 1,
      "distance_m": 1997,
      "duration_s": 1438,
      "risk_level": "advisory",
      "safety_score": 50.5,
      "risk_summary": [
        "低地・排水困難エリア",
        "洪水想定区域",
        "高潮想定区域"
      ],
      "hazards": {
        "lowland": true,
        "flood": true,
        "inland_flood": false,
        "landslide": false,
        "tsunami": false,
        "storm_surge": true
      },
      "weather": {
        "forecast_max_intensity": "none"
      },
      "status": "ok"
    }
  ]
}
```

判定: PASS

- 実 API が `status: "ok"`。
- `recommended_route_index` がある。
- `routes[]` がある。
- route ごとに `risk_level`, `safety_score`, `risk_summary`, `hazards`, `weather` がある。
- API 500 なし。

## 4. distance sampling 確認

backend container 内で `_sample_by_distance()` を直接確認した。

結果:

```text
samples=[(35.0, 139.0), (35.0, 139.003), (35.0, 139.005)]
count=3
max_ok=True
has_start=True
has_end=True
```

判定: PASS

- 座標数ベースではなく haversine 距離ベース sampling。
- 最大点数制限あり。
- 先頭と終端を含む。

## 5. mock comparison

backend container 内で OSRM / weather / hazard を mock し、`_build_comparison()` を直接確認した。

### shortest but risky

mock:

```text
Route A:
  distance=1000m
  strong rain + flood

Route B:
  distance=1200m
  moderate rain
```

結果:

```text
recommended=1
Route A: risk_level=warning, safety_score=30.0, risk_summary=["強雨域接近", "洪水想定区域"]
Route B: risk_level=advisory, safety_score=95.0, risk_summary=["雨域を通過"]
```

判定: PASS

### all safe

結果:

```text
recommended=0
Route A: risk_level=none, safety_score=100.0
Route B: risk_level=none, safety_score=100.0
```

判定: PASS

### unknown weather

mock:

```text
weather_risk=unknown
forecast_max_intensity=unknown
hazards={}
```

結果:

```text
recommended=0
Route A: risk_level=unknown, safety_score=100.0, risk_summary=["気象リスク判定不能"]
```

判定: PASS

- unknown を none に倒していない。
- UI が扱える summary がある。

### unavailable weather

mock:

```text
weather_risk=unavailable
forecast_max_intensity=unknown
```

結果:

```text
Route A: risk_level=none, safety_score=100.0, risk_summary=["気象リスク判定不能"]
```

判定: PASS with notes

- warning 扱いにはしていない。
- `risk_summary` に判定不能は残る。
- `risk_level` は `none` のため、weather unavailable を route level として別表現したい場合は今後調整余地あり。

## 6. recommendation priority

静的確認と mock 結果から、以下の優先順位を確認した。

```text
1. risk_level
2. safety_score
3. distance
4. duration
```

実装:

```python
return (level, r["safety_score"], -r["distance_m"], -r["duration_s"])
```

判定: PASS

## 7. route churn

frontend mock で推奨 route が変わるが safety score 差が小さいケースを連続投入した。

mock:

```text
1回目:
  recommended=0
  Route A score=80
  Route B score=75

2回目:
  recommended=1
  Route A score=80
  Route B score=85
  score diff=5 < threshold 10
```

結果:

```text
2回目も A: 推奨 を維持
```

判定: PASS

## 8. frontend UI

Playwright で `#lip-route-weather-compare` に mock response を投入した。

### risky shortest

結果:

```text
ルート気象・ハザード比較
A: 最短
安全度 30
警戒
強雨域接近 / 洪水想定区域

B: 推奨
安全度 95
注意
雨域を通過

推奨ルートは最短より200m長いですが、安全寄りです
```

判定: PASS

### unknown

mock:

```json
{
  "risk_level": "unknown",
  "safety_score": 100,
  "risk_summary": ["気象リスク判定不能"]
}
```

結果:

```text
A: 最短
安全度 100
判定不能
気象リスク判定不能
```

判定: PASS

### unavailable

mock:

```json
{
  "status": "unavailable",
  "recommended_route_index": 0,
  "routes": []
}
```

結果:

```text
display: none
text: ""
html: ""
```

判定: PASS

- 旧カードは残らない。

## 9. reroute behavior

静的確認:

- `route-ui.js` は比較カード表示のみ。
- route selection callback は既存の手動選択 UI 経由。
- `route-ui.js` 内に自動 reroute / route 強制切替はない。
- backend service も OSRM weighting を変更しない。

判定: PASS

## 10. route highlight

Phase3-A では任意項目。今回、候補 route の地図上 highlight 変更は明確には確認していない。

判定: Not implemented / optional

## 11. API 回帰

### 実施コマンド

```bash
curl -i -X POST 'http://127.0.0.1:8000/api/weather/risk/route' \
  -H 'Content-Type: application/json' \
  -d '{"route":{"coordinates":[[139.767125,35.681236],[139.768000,35.682000]]}}'
curl -i 'http://127.0.0.1:8000/api/weather/risk/context?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/alerts/current?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/hazards/active'
```

### 結果

- weather route risk API: HTTP 200
- weather risk context API: HTTP 200
- weather alerts API: HTTP 200
- hazards active API: HTTP 200

判定: PASS

## 12. 回帰確認

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

- info-tab / temperature / weather-hazard API 回帰は PASS。
- navigation-debug-layer timeout は Phase2-D 検証時にも Phase2-D 前 commit 由来の既存不安定テストとして切り分け済み。Phase3-A 固有の FAIL 要因にはしない。

## 13. Notes

- 実天候では `forecast_max_intensity: "none"` だったため、実 API で strong/severe を観測する確認はできなかった。mock では `strong + flood` の推奨回避を確認済み。
- `weather_risk: "unavailable"` は warning 扱いされないが、route `risk_level` は `none` になる。`risk_summary` に `気象リスク判定不能` は残るため false warning は避けられている。将来、UI で `気象情報取得不可` を明示したい場合は status フィールド拡張余地あり。
- route highlight は任意項目として未確認。
- `e2e/navigation-debug-layer.spec.js` の `#layer-toggle-btn` timeout は別途安定化対象。

## 最終判定

**PASS with notes**

Phase3-A の必須条件である route comparison API、route ごとの `safety_score`、weather + hazards 統合、risky shortest より safer route を推奨するロジック、unknown 非 false-safe、route churn 抑制、比較 UI、自動 reroute 非発動、既存 API/E2E/pytest 回帰なしを確認した。残る navigation-debug-layer E2E timeout は既存不安定テストとして切り分ける。

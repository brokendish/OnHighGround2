# OnHighGround2 Simulation / Inspection Mode v1 Codex 検証結果

## 検証メタデータ

- 検証日時: 2026-05-17 22:38 JST
- 対象ブランチ: `main`
- 対象 commit: `0535bc19a6c67aeabab0a5ec965b5205ff1d617a`
- 対象:
  - `frontend/admin/simulation.html`
  - `frontend/admin/simulation.js`
  - `frontend/admin/simulation.css`
  - `backend/app/api/simulation.py`
  - `backend/app/services/simulation_service.py`
  - `backend/app/models/simulation.py`
  - `e2e/simulation-mode.spec.js`
  - `data_runtime/simulation/`
- 最終判定: **PASS with notes**

## サマリー

Simulation / Inspection Mode v1 の手動実行、predefined scenario、penalty breakdown、layer stack、auto-run report、Playwright screenshot、本番 API 非混入を確認した。

- `/admin/simulation` 相当の専用画面として `frontend/admin/simulation.html` が追加されている。
- `/api/simulation/run`, `/api/simulation/scenarios`, `/api/simulation/auto-run` が動作する。
- manual run は route comparison、`safety_score`, `risk_level`, `penalties[]`, `risk_summary`, `layer_stack` を返す。
- predefined scenarios は 8 件あり、auto-run は 8/8 PASS。
- JSON / MD report が `data_runtime/simulation/` に保存される。
- Playwright screenshot が `data_runtime/simulation/screenshots/003_rain_flood.png` に保存される。
- simulation mock は simulation API / admin UI 内に閉じており、本番 weather / route comparison API へ混入していない。
- 既存 weather / hazard / route comparison API は HTTP 200。

E2E は初回 16/18 pass だったが、2 件は実装不具合ではなくテスト記述の問題だったため、`e2e/simulation-mode.spec.js` を最小修正して 18/18 pass にした。

## 1. 静的確認

### PASS

- admin 専用画面がある。
  - `frontend/admin/simulation.html`
  - `frontend/admin/simulation.js`
  - `frontend/admin/simulation.css`
- simulation API が本番 API と分離されている。
  - `backend/app/api/simulation.py`
  - `backend/app/services/simulation_service.py`
  - `backend/app/models/simulation.py`
- `main.py` に `simulation_router` が include されている。
- simulation service は本番 weather / hazard API を呼ばず、scenario parameter を mock として使う。
- OSRM は route geometry 取得用途のみ利用し、hazard/weather 判定は simulation 内 mock。
- penalty breakdown model がある。
  - `PenaltyItem`
  - `SimulationRouteResult.penalties`
- layer stack model がある。
  - `LayerItem`
  - `SimulationResult.layer_stack`
- predefined scenarios が 8 件ある。
  - 001 平常時
  - 002 強雨のみ
  - 003 強雨 + 洪水想定区域
  - 004 severe rain + landslide
  - 005 moderate rain + lowland
  - 006 unknown weather
  - 007 hazard unavailable
  - 008 risky shortest vs safer longer
- report 出力先がある。
  - `data_runtime/simulation/`
  - `data_runtime/simulation/screenshots/`
- unknown を none に倒していない。
  - weather unknown は `risk_level: "unknown"`
  - hazard unavailable は `risk_level: "unknown"` または warning 扱いしない
- 本番 reroute / route score / OSRM weighting を変更する実装は確認されなかった。

## 2. Docker / 起動確認

### 実施コマンド

```bash
docker compose build backend frontend
docker compose up -d backend frontend martin osrm-walking
docker compose ps backend frontend martin osrm-walking
curl -s http://127.0.0.1:8000/health
```

### 結果

- backend build: PASS
- frontend build/up: PASS
- backend: healthy
- frontend: up
- martin: healthy
- osrm-walking: up

## 3. API 確認

### simulation run

実施:

```bash
curl -s -X POST \
  'http://127.0.0.1:8000/api/simulation/run' \
  -H 'Content-Type: application/json' \
  -d '{
    "scenario_id":"manual",
    "origin":[139.767125,35.681236],
    "destination":[139.780000,35.690000],
    "weather":{
      "forecast_max_intensity":"strong",
      "forecast_minutes":20
    },
    "hazards":{
      "flood":true,
      "lowland":true,
      "inland_flood":false,
      "landslide":false
    }
  }'
```

結果:

- HTTP 200
- `status: "ok"`
- `recommended_route_index`
- `routes[]`
- `safety_score`
- `risk_level`
- `penalties[]`
- `risk_summary`
- `summary`
- `layer_stack`

代表値:

```json
{
  "status": "ok",
  "scenario_id": "manual",
  "recommended_route_index": 0,
  "routes": [
    {
      "label": "A",
      "risk_level": "emergency",
      "safety_score": 16.0,
      "risk_summary": [
        "強雨域接近",
        "洪水想定区域",
        "低地・排水困難エリア"
      ],
      "penalties": [
        {"type": "strong_rain", "points": 15.0, "reason": "強雨域接近"},
        {"type": "flood", "points": 46.0, "reason": "洪水"},
        {"type": "lowland_poor_drainage", "points": 8.0, "reason": "低地・排水困難エリア"},
        {"type": "combined_strong_flood", "points": 15.0, "reason": "強雨 + 洪水想定区域"}
      ]
    }
  ]
}
```

判定: PASS

### scenarios

実施:

```bash
curl -s 'http://127.0.0.1:8000/api/simulation/scenarios'
```

結果:

- HTTP 200
- `status: "ok"`
- `scenarios`: 8 件
- 001〜008 の required scenarios を確認。

判定: PASS

### auto-run

実施:

```bash
curl -s -X POST \
  'http://127.0.0.1:8000/api/simulation/auto-run' \
  -H 'Content-Type: application/json' \
  -d '{}'
```

結果:

```json
{
  "total": 8,
  "passed": 8,
  "failed": 0,
  "skipped": 0,
  "report_path": "/data_runtime/simulation/simulation_report_20260517_133459.json"
}
```

判定: PASS

## 4. predefined scenario 検証

auto-run 結果:

| ID | Scenario | Expected | Actual | Result |
|---|---|---:|---:|---|
| 001 | 平常時 | none | none | PASS |
| 002 | 強雨のみ | advisory 以上 | warning | PASS |
| 003 | 強雨 + flood | warning 以上 | warning | PASS |
| 004 | severe rain + landslide | emergency 以上 | emergency | PASS |
| 005 | moderate rain + lowland | advisory 以上 | advisory | PASS |
| 006 | unknown weather | unknown | unknown | PASS |
| 007 | hazard unavailable | unknown | unknown | PASS |
| 008 | risky shortest vs safer longer | recommended not shortest | route 1 | PASS |

判定: PASS

## 5. Penalty Breakdown 確認

`強雨 + flood + lowland` manual run で以下を確認した。

```text
+ strong_rain
+ flood
+ lowland_poor_drainage
+ combined_strong_flood
= safety_score 16.0
```

判定: PASS

- JSON に `penalties[]` がある。
- UI でも `.sim-penalty-breakdown` と `.sim-penalty-item` を E2E で確認。

## 6. Layer Stack 確認

manual run response:

```json
[
  {"key": "weather_strong", "label": "降水: 強雨域接近", "active": true},
  {"key": "flood", "label": "洪水想定区域", "active": true},
  {"key": "inland_flood", "label": "内水氾濫想定区域", "active": false},
  {"key": "landslide", "label": "土砂災害警戒区域", "active": false},
  {"key": "lowland", "label": "低地・排水困難エリア", "active": true}
]
```

判定: PASS

- ON / OFF / unknown 相当が model で表現される。
- UI でも `.sim-layer-stack` を E2E で確認。

## 7. Manual UI 確認

E2E で `/admin/simulation.html` を開き、以下を確認した。

- ページタイトル表示
- predefined scenario button 表示
- 出発地 / 目的地入力
- 降水 intensity select
- 警報 severity select
- lowland / flood / inland_flood / landslide / tsunami / storm_surge toggle
- unknown weather toggle
- hazard unavailable toggle
- 実行ボタン
- route comparison 表示
- penalty breakdown 表示
- layer stack 表示
- unknown weather 表示
- unavailable response で旧結果が残らない

判定: PASS

## 8. Screenshot / Report 確認

### Report

確認ファイル:

```text
data_runtime/simulation/simulation_report_20260517_133459.json
data_runtime/simulation/simulation_report_20260517_133459.md
```

判定: PASS

### Screenshot

確認ファイル:

```text
data_runtime/simulation/screenshots/003_rain_flood.png
```

判定: PASS

- `e2e/simulation-mode.spec.js` が `page.screenshot({ path: ... })` で保存している。

## 9. 本番 API 回帰 / mock 非混入

### 実施コマンド

```bash
curl -i -X POST 'http://127.0.0.1:8000/api/navigation/route/compare' \
  -H 'Content-Type: application/json' \
  -d '{"origin":[139.767125,35.681236],"destination":[139.780000,35.690000]}'
curl -i -X POST 'http://127.0.0.1:8000/api/weather/risk/route' \
  -H 'Content-Type: application/json' \
  -d '{"route":{"coordinates":[[139.767125,35.681236],[139.768000,35.682000]]}}'
curl -i 'http://127.0.0.1:8000/api/weather/risk/context?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/alerts/current?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/hazards/active'
```

### 結果

- navigation route compare API: HTTP 200
- weather route risk API: HTTP 200
- weather risk context API: HTTP 200
- weather alerts API: HTTP 200
- hazards active API: HTTP 200

E2E の本番 API 非混入確認:

- `/api/navigation/route/compare` は simulation manual run で呼ばれない。
- `/api/weather/risk/route` は simulation manual run で呼ばれない。

判定: PASS

## 10. E2E / pytest

### 実施コマンド

```bash
npx playwright test e2e/simulation-mode.spec.js --reporter=line
npx playwright test e2e/info-tab-card-ui.spec.js --reporter=line
venv/bin/python -m pytest tests/test_weather_temperature.py -q
npx playwright test e2e/navigation*.spec.js --reporter=line
```

### 結果

- `e2e/simulation-mode.spec.js`: 18 passed
- `e2e/info-tab-card-ui.spec.js`: 3 passed
- `tests/test_weather_temperature.py`: 34 passed
- `e2e/navigation*.spec.js`: 1 failed, 1 passed
  - Failed: `e2e/navigation-debug-layer.spec.js`
  - Reason: timeout waiting for `#layer-toggle-btn`

判定:

- Simulation / info-tab / temperature は PASS。
- navigation-debug-layer timeout は過去フェーズでも既存不安定テストとして切り分け済み。Simulation Mode 起因の FAIL にはしない。

## 11. Codex 追加修正

`e2e/simulation-mode.spec.js` に 2 点のテスト修正を行った。

- `toHaveCount({ minimum: 1 })` は Playwright の期待値として不正だったため、`.first().waitFor()` に変更。
- `getByText('判定不能')` は複数要素に一致して strict mode violation になるため、`.sim-route-risk` に scope した locator に変更。

この修正後、Simulation E2E は 18/18 pass。

## 12. Notes

- `/admin/simulation.html` は存在し、nginx の extension fallback により `/admin/simulation` でもアクセス可能なログを確認した。
- `curl -I http://127.0.0.1:8080/admin/simulation.html` は現在の local sandbox からは connection refused になったが、Docker `ps` では frontend up、nginx log では `/admin/simulation` の HTTP 200、Playwright E2E では admin simulation UI を正常表示できている。
- auto-run の `run_at` は UTC isoformat。JST 表示が必要なら今後調整余地あり。
- Simulation v1 はカード表示中心で、地図上 route polyline 可視化は必須範囲外として未確認。

## 最終判定

**PASS with notes**

Simulation / Inspection Mode v1 の必須条件である専用 UI、manual run、route comparison、penalty breakdown、layer stack、predefined scenarios、auto-run、JSON / MD report、Playwright screenshot、unknown 非 false-safe、本番 API 非混入、既存 API 回帰なしを確認した。

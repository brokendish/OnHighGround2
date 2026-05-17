# OnHighGround2 Simulation / Inspection Mode v1.5 CODEX 検証結果

- 検証日時: 2026-05-17 24:05 JST
- 対象ブランチ: main
- 対象 commit: cdd17fc14a347535c5cb1290056d3be8eb8265e3
- 判定: PASS with notes

## 概要

前回 FAIL の主因だった Leaflet JS の SRI mismatch は解消され、`/admin/simulation` の frontend 初期化、シナリオ一覧、map control、manual run、point inspection、save/load modal、auto-run modal が E2E で通過した。

Backend simulation API、本番 weather/hazard/navigation API、既存情報タブ E2E、気温テストも通過。Simulation mock が本番 API に混入している兆候は確認できなかった。

ただし、hazard overlay toggle、current location marker、完全な route segment 単位 polyline、独立した combined risk panel は v1.5 の理想仕様に対してまだ notes 扱い。

## 実施コマンド

```bash
git status --short
git rev-parse HEAD
rg -n "integrity=|_mapAvailable|try \\{|circleMarker|JSONをダウンロード|runPointInspect\\(" frontend/admin e2e/simulation-mode.spec.js
docker compose build backend frontend
docker compose up -d backend frontend martin osrm-walking
docker compose ps backend frontend martin osrm-walking
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/api/simulation/auto-run ...
curl -s -X POST http://127.0.0.1:8000/api/simulation/point-inspect ...
curl -s -X POST http://127.0.0.1:8000/api/navigation/route/compare ...
curl -s -X POST http://127.0.0.1:8000/api/weather/risk/route ...
curl -s 'http://127.0.0.1:8000/api/weather/risk/context?lat=35.681236&lon=139.767125'
curl -s http://127.0.0.1:8000/api/hazards/active
npx playwright test e2e/simulation-mode.spec.js --reporter=line
npx playwright test e2e/info-tab-card-ui.spec.js --reporter=line
npx playwright test e2e/navigation*.spec.js --reporter=line
venv/bin/python -m pytest tests/test_weather_temperature.py -q
```

## 修正確認

確認できたもの:

- `frontend/admin/simulation.html` から Leaflet CSS/JS の `integrity=` が除去されている。
- `frontend/admin/simulation.js` に `_mapAvailable` が追加され、`SimMap.init()` 失敗時も基本 UI event listener が止まらない構造になっている。
- `SimMap.*` 呼び出しに `_mapAvailable` guard が入っている。
- `e2e/simulation-mode.spec.js` の point-inspect test は `runPointInspect(lat, lon)` 直接呼び出しに簡略化されている。
- `frontend/admin/simulation-map.js` に `L.circleMarker` による route 上の risk marker 表示が追加されている。
- route tooltip に penalty breakdown が含まれる。
- Auto-Run modal に `JSONをダウンロード` ボタンが追加されている。

## Docker / 起動確認

結果:

- `docker compose build backend frontend`: 成功
- `docker compose up -d backend frontend martin osrm-walking`: 成功
- `docker compose ps backend frontend martin osrm-walking`: backend healthy、frontend up、martin healthy、osrm-walking up
- `/health`: `status: healthy`

補足:

- backend 再作成直後は hazard dataset load のため health が `starting` になったが、起動完了後に healthy へ遷移した。

## UI 確認

実ブラウザ確認:

- `/admin/simulation.html` で `L is not defined` は再発しない。
- predefined scenario button が 8 件表示される。
- Start button click で `active` class が付く。

確認ログ:

```text
buttons 8
after click class sim-map-ctrl-btn active
```

## API 確認

### `/api/simulation/auto-run`

結果:

- HTTP 200
- total: 8
- passed: 8
- failed: 0
- unknown weather scenario は `risk_level: unknown`
- hazard unavailable scenario は `risk_level: unknown`
- risky shortest vs safer longer は `recommended_route_index: 1`
- report path: `/data_runtime/simulation/simulation_report_20260517_145928.json`

### `/api/simulation/point-inspect`

結果:

- HTTP 200
- `risk_level`
- `safety_score`
- `penalties[]`
- `combined_risks[]`
- `hazard_union`
- `layer_stack`
- `data_source`

確認例:

- `risk_level: emergency`
- `combined_risks`: 強雨域接近、洪水想定区域、低地・排水困難エリア
- `data_source: real`

### 本番 API 回帰

結果:

- `POST /api/navigation/route/compare`: HTTP 200
- `POST /api/weather/risk/route`: HTTP 200
- `GET /api/weather/risk/context`: HTTP 200
- `GET /api/hazards/active`: HTTP 200

Simulation mock が本番 API に混入している兆候は確認できない。

## E2E / pytest

### `e2e/simulation-mode.spec.js`

結果:

- 28 passed

確認できたもの:

- page render
- predefined scenario load
- manual run
- route comparison display
- penalty breakdown
- layer stack
- recommendation badge
- unavailable response cleanup
- unknown weather display
- screenshot save
- auto-run modal
- PASS/FAIL row rendering
- point inspection
- scenario save/load modal
- map control active state
- 3 pane layout
- production API non-mixing

### `e2e/info-tab-card-ui.spec.js`

結果:

- 3 passed

### `tests/test_weather_temperature.py`

結果:

- 34 passed

### `e2e/navigation*.spec.js`

結果:

- 2 tests
- 1 passed
- 1 failed

失敗:

- `e2e/navigation-debug-layer.spec.js` が `#layer-toggle-btn` 待ちで timeout。

補足:

- この navigation-debug-layer timeout は以前の Phase2-D 検証でも既存不安定として確認済み。今回の Simulation v1.5 変更とは直接関係しない扱い。

## Screenshot / Report

確認:

- `data_runtime/simulation/screenshots/003_rain_flood.png`
- `data_runtime/simulation/simulation_report_20260517_145928.json`
- `data_runtime/simulation/simulation_report_20260517_145928.md`

注意:

- 指示書上は `reports/simulation/` が保存先候補だが、実装は `data_runtime/simulation/` に保存している。運用上どちらを正とするかは整理余地あり。

## 要件別判定

| 要件 | 判定 | メモ |
|---|---:|---|
| 3 ペイン構成 | PASS | 左 parameter、中央 map、右 inspection/result |
| map 表示 | PASS | Leaflet SRI 問題解消 |
| Start / Goal placement | PASS | E2E で mode active、実装上 marker/input sync あり |
| Current Location marker | NOTE | Start / Goal / Inspect はあるが current marker は未確認 |
| Hazard layer toggle | NOTE | scenario parameter checkbox はあるが map overlay toggle は未確認 |
| route line 表示 | PASS | route coordinates + `SimMap.drawRoutes()` |
| route segment risk visualization | PASS with notes | 1/4・1/2・3/4 点 circleMarker による簡易表現。完全な segment polyline 色分けではない |
| route hover/click inspection | PASS with notes | route tooltip に penalty breakdown。segment click popup ではない |
| point inspection | PASS | API/UI/E2E 通過 |
| layer stack | PASS | UI/E2E 通過 |
| combined risk panel | NOTE | point inspection / route card 内表示。独立 panel としては未確認 |
| scenario save/load | PASS | API/UI/E2E 通過 |
| auto-run result panel | PASS | modal/UI/E2E 通過 |
| JSON export | PASS | Auto-Run modal に export button |
| screenshot/report | PASS with notes | data_runtime 配下に保存 |
| unknown を none に倒さない | PASS | unknown scenario / E2E 通過 |
| 本番 API 非混入 | PASS | E2E/API で確認 |

## Notes

- route segment visualization は「区間ごとの polyline 分割」ではなく、route 上の代表点 marker による簡易可視化。防災説明用途では前進しているが、厳密な segment risk 表現は次フェーズで改善余地あり。
- hazard overlay toggle は UI parameter と layer stack には反映されるが、Leaflet 上の flood/inland_flood/landslide/lowland overlay layer の ON/OFF としては未確認。
- current location marker は v1.5 指示に含まれるが、今回の確認範囲では Start / Goal / Inspect のみ。
- report/screenshot 保存先は `data_runtime/simulation/`。指示書の `reports/simulation/` と揺れがある。
- navigation debug layer E2E は既存不安定が継続。

## 最終判定

PASS with notes。

前回 FAIL の blocker は解消され、Simulation / Inspection Mode v1.5 の主要 UI/API/E2E は動作している。残る差分は厳密な segment 表現、hazard overlay、current location marker、保存先整理の改善 notes として扱う。

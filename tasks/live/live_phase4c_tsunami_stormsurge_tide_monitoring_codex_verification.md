# Phase 4-C 津波・高潮・潮位監視表示 検証レポート（Codex）

## 実施日時

- 2026-06-03 00:05:44 JST

## Docker状態

- `docker compose build`: PASS
- `docker compose up -d`: PASS
- `docker compose ps`: PASS
  - backend: Up / healthy
  - frontend: Up
  - martin: Up / healthy
  - osrm-walking: Up
- note: backend は起動直後に hazard データ読み込みで `health: starting` が約 1 分続いたが、その後 healthy になった。

## 構文確認

- `python3 -m compileall backend/app`: PASS
- `node --check frontend/js/live/*.js` 相当の全 live JS 個別確認: PASS
- SyntaxError / ImportError / JS 構文エラーなし。

## 津波確認

- `/api/live/summary`: PASS
  - `tsunami.status`: `ok`
  - `tsunami.evaluated`: `true`
  - `tsunami.summary.active`: `false`
  - `tsunami.summary.warning_area_count`: `0`
  - `tsunami.areas`: `[]`
- `/api/tsunami/warnings/current`: `/live` 実ブラウザ確認中に 200 OK。
- UI:
  - 津波トグル表示: PASS
  - 初期 ON: PASS
  - OFF 操作: PASS
  - 津波警報あり表示: `e2e/live-storm-surge.spec.js` のモックで PASS
  - 津波トグル OFF でマーカー消去: `e2e/live-storm-surge.spec.js` のモックで PASS
- note: 実データでは検証時点で津波警報・注意報は発令なし。

## 高潮確認

- `/api/live/summary`: PASS
  - `storm_surge.status`: `ok`
  - `storm_surge.evaluated`: `true`
  - `storm_surge.summary.active`: `false`
  - `storm_surge.summary.warning_area_count`: `0`
  - `storm_surge.areas`: `[]`
- `/api/live/storm_surge/warnings`: `/live` 実ブラウザ確認中に 200 OK。
- backend log:
  - `live storm surge summary: areas=0`
- UI:
  - 高潮トグル表示: PASS
  - 初期 ON: PASS
  - OFF 操作: PASS
  - 高潮警報なし表示: PASS
  - 高潮警報あり表示: `e2e/live-storm-surge.spec.js` のモックで PASS
  - 高潮トグル OFF でマーカー消去: `e2e/live-storm-surge.spec.js` のモックで PASS
- note: 実データでは検証時点で高潮警報・注意報は発令なし。一部 JMA prefecture fetch が 404 warning になったが、サービス結果は `status: ok` / `areas=0`。

## dangerous_areas確認

- `/api/live/summary`: PASS
  - `dangerous_areas`: 5 件
  - 検証時点では雨雲由来のみ。津波・高潮は実データで 0 件のため反映対象なし。
- 優先順位確認: PASS
  - `_merge_dangerous_areas` にサンプル入力を与え、`tsunami -> storm_surge -> kikikuru -> rain` の順になることを確認。
  - 実装上は既存の地震危険地域も含むため、全体 type priority は `tsunami -> storm_surge -> earthquake -> kikikuru -> rain`。

## Console確認

- 実ブラウザ確認: PASS
  - `http://127.0.0.1:8080/live`: console error 0 / page error 0
  - `http://127.0.0.1:8080/`: console error 0 / page error 0
- `/live` 実ブラウザ確認結果:
  - title: `全国災害ビューア — OnHighGround`
  - 津波トグル表示: true
  - 高潮トグル表示: true
  - 津波 OFF 後 checked: false
  - 高潮 OFF 後 checked: false
- ナビ本体確認結果:
  - title: `避難ナビゲーション OnHighGround - 津波・高潮・洪水対策`
  - body visible: true

## 回帰確認

- `git diff --check`: PASS
- `npx playwright test e2e/live-basic.spec.js`: PASS, 73 passed
- `npx playwright test e2e/live-earthquake-layer.spec.js`: PASS, 12 passed
- `npx playwright test e2e/live-sun-moon-card.spec.js`: PASS, 15 passed
- `npx playwright test e2e/live-tide-layer.spec.js`: PASS, 13 passed
- 追加 E2E:
  - `npx playwright test e2e/live-storm-surge.spec.js`: PASS, 13 passed

## ナビ本体影響確認

- `curl -I http://127.0.0.1:8080/`: PASS, 200 OK
- 実ブラウザ確認: PASS
  - 正常表示
  - console error なし
  - page error なし
- E2E:
  - `live-earthquake-layer`: ナビ本体に市区町村マーカー自動表示なし
  - `live-tide-layer`: ナビ本体が潮位 API を自動呼び出ししない

## スクリーンショット

- `/live`: `tasks/live/live_phase4c_codex_live.png`
- ナビ本体 `/`: `tasks/live/live_phase4c_codex_nav.png`

## 最終判定

PASS with notes

notes:

- 実データでは津波・高潮とも発令なしだったため、警報あり UI とマーカー ON/OFF はモック E2E で検証した。
- backend 起動直後は hazard データ読み込みにより `health: starting` が続くが、最終的に healthy となった。

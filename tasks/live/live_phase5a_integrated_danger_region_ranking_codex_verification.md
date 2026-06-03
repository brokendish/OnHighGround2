# Phase 5-A 危険地域統合ランキング MVP 検証レポート（Codex）

## 実施日時

- 2026-06-03 00:33:41 JST

## Docker状態

- `docker compose build`: PASS
- `docker compose up -d`: PASS
- `docker compose ps`: PASS
  - backend: Up / healthy
  - frontend: Up
  - martin: Up / healthy
  - osrm-walking: Up
- note: backend は hazard データ読み込み中に約 1 分 `health: starting` となり、その後 healthy になった。

## 構文確認

- `python3 -m compileall backend/app`: PASS
- `node --check frontend/js/live/*.js` 相当の live JS 全ファイル個別確認: PASS
- SyntaxError / ImportError / JS 構文エラーなし。

## API確認結果

- `GET /api/live/summary`: PASS, HTTP 200
- `dangerous_areas`: 存在する
- `integrated_dangerous_regions`: 存在する
- 実データ例:
  - `dangerous_areas`: 5 件
  - `integrated_dangerous_regions`: 4 地域
  - `北海道付近` の rain 重複が 1 地域に統合された。
- backend log:
  - `live integrated danger regions: input_areas=5 regions=4`

## 統合確認結果

- サンプル入力で確認: PASS
  - `高知県付近 rain`
  - `高知県付近 kikikuru`
  - `沖縄県付近 rain`
- 出力:
  - `高知県付近` が 1 地域に統合された。
  - `types`: `["kikikuru", "rain"]`
  - `events`: `キキクル（洪水）`, `雨雲`
  - `沖縄県付近` は rain 単独地域として出力された。

## 優先順位確認結果

- サンプル入力で確認: PASS
- 並び順:
  - `tsunami`
  - `storm_surge`
  - `earthquake`
  - `kikikuru`
  - `rain`
- 複数イベントを持つ地域の `types` は優先順で出力される。

## 表示件数確認結果

- サンプル 12 地域入力で確認: PASS
- `integrated_dangerous_regions` は地域単位で 10 件に制限された。
- 追加 E2E で 2 地域表示時のカード崩れなしを確認。

## UI確認結果

- `http://127.0.0.1:8080/live.html`: PASS
- 危険地域カード表示: PASS
- 実データでは `dangerous_areas=5` に対してカード表示は 4 地域。
- 同一地域の重複表示なし: PASS
- 地域内イベント表示: 追加 E2E のモックで PASS
  - `高知県付近`
  - `キキクル（洪水）`
  - `雨雲`
- `rain / kikikuru / tsunami / storm_surge / earthquake` は統合対象としてロジック上確認し、UI 表示は追加 E2E と既存 E2E で確認。
- スクロール表示: 実画面 screenshot でカード下部がスクロール領域内に収まり、レイアウト崩れなし。

## フォールバック確認結果

- 追加 E2E `live-integrated-regions.spec.js`: PASS
- `integrated_dangerous_regions` が空の場合、既存 `dangerous_areas` の地域名が表示される。
- JS error / page error なし。

## false-safe確認結果

- `unknown` / `unavailable` サンプル入力:
  - `level` は `unknown` / `unavailable` のまま出力され、`danger` へ昇格しないことを確認。
- 実データ:
  - threshold 未満の雨雲は `dangerous_areas` に含まれない前提の既存雨雲集計を使用。
  - `tide` / `sun_moon` は `/api/live/summary` の `dangerous_areas` / `integrated_dangerous_regions` に含まれない。
- 既存回帰 E2E:
  - rain evaluated=false / offline で安全断定しない。
  - sun_moon API 失敗時に危険表示へ変換しない。
  - tide は危険地域へ入らず、潮位レイヤーとして独立動作。

## Console確認結果

- 実ブラウザ `/live.html`: PASS
  - console error: 0
  - page error: 0
- 実ブラウザ `/`: PASS
  - console error: 0
  - page error: 0

## 回帰確認結果

- `git diff --check`: PASS
- `npx playwright test e2e/live-basic.spec.js`: PASS, 73 passed
- `npx playwright test e2e/live-earthquake-layer.spec.js`: PASS, 12 passed
- `npx playwright test e2e/live-sun-moon-card.spec.js`: PASS, 15 passed
- `npx playwright test e2e/live-tide-layer.spec.js`: PASS, 13 passed
- `npx playwright test e2e/live-storm-surge.spec.js`: PASS, 13 passed
- 追加 E2E:
  - `npx playwright test e2e/live-integrated-regions.spec.js`: PASS, 12 passed

## ナビ本体影響確認

- `http://127.0.0.1:8080/`: PASS
- 正常表示: PASS
- console error / page error: 0
- `/api/live/*` の不要な自動呼び出し: なし
- note: ナビ本体は既存機能として `/api/tsunami/warnings/current` を呼び出す。これは `/api/live/*` ではなく、Phase 5-A 追加 API でもない。

## スクリーンショット

- `/live.html`: `tasks/live/live_phase5a_codex_live.png`
- ナビ本体 `/`: `tasks/live/live_phase5a_codex_nav.png`

## 最終判定

PASS with notes

notes:

- 実データでは rain の地域重複統合のみ確認できた。rain + kikikuru 等の複数 type 統合は追加 E2E とサンプル入力で確認した。
- backend 起動直後は hazard データ読み込みにより `health: starting` が続くが、最終的に healthy となった。

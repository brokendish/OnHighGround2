# /live/stream Stream Phase 3-A: メイン地図 本番地図基盤化 MVP 検証レポート

検証日: 2026-07-03
担当: Codex
結果: PASS

## 検証対象

- `/live/stream` 中央メイン地図の本番地図基盤化
- 日本全土表示
- 見るだけ地図としての操作 UI 無効化
- 既存パルスの本番地図上表示
- OSM attribution 表示
- 既存 `/live/stream` E2E、通常 `/live`、通常 `/` への影響

## 静的確認

確認コマンド:

```bash
git status --short
git diff --stat
```

確認結果:

- 変更は `/live/stream` 関連の `frontend/live/stream.html`、`frontend/js/live-stream/`、`frontend/css/live/live-stream.css`、追加 E2E に限定されている。
- `frontend/js/live-stream/live-stream-map-view.js` が追加され、`LiveStreamMapView` として中央メイン地図専用の Leaflet ラッパーを持つ。
- 通常 `/live` 本体、通常 `/`、既存ナビ本体、ルート探索、OSRM まわりへの変更はなし。
- 小窓地図は既存 SVG モック描画を維持しており、地震小窓 OSM 化、豪雨小窓 OSM 化、鉄道小窓 OSM 化、鉄道簡略路線図の大規模変更はなし。
- 地震・雨・潮位 adapter には中央地図パルス用の `lat/lon` 追加のみ。

## スコープ逸脱確認

以下は実装されていないことを確認:

- 地震小窓 OSM 化
- 豪雨小窓 OSM 化
- 地震市町村震度マーカー
- 鉄道簡略路線図の本番化
- 鉄道小窓 OSM 化
- 地図クリック/ポップアップ
- YouTube/OBS 連携
- DB 追加

補足: 中央メイン地図では既存カテゴリの rail/tide パルスも維持されているが、対象は中央メイン地図内に限定されている。

## 構文チェック

以下すべて PASS:

```bash
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-clock.js
node --check frontend/js/live-stream/live-stream-ticker.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-map.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check e2e/live-stream.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
node --check e2e/tide-mock-verify.spec.js
node --check e2e/rail-mock-verify.spec.js
node --check e2e/live-stream-main-map.spec.js
```

## Docker 状態

`docker compose ps` で以下を確認:

- `evacuation-navi-frontend`: Up
- `evacuation-navi-backend`: Up, healthy
- `evacuation-navi-martin`: Up, healthy
- `evacuation-navi-osrm-walking`: Up

## HTTP 確認

以下すべて `200 OK`:

- `http://127.0.0.1:8080/live/stream`
- `http://127.0.0.1:8080/live/stream?chrome=off`
- `http://127.0.0.1:8080/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00`
- `http://127.0.0.1:8080/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00`
- `http://127.0.0.1:8080/live`
- `http://127.0.0.1:8080/`

## 中央地図の本番地図化確認

Playwright とスクリーンショットで確認:

- `data-testid="live-stream-center-map"` が表示される。
- 中央メイン地図に `.leaflet-container` が付与される。
- `.leaflet-tile-loaded` が存在し、タイルが読み込まれる。
- モック SVG ではなく Leaflet + CARTO/OSM タイルで表示される。
- OSM/CARTO attribution が表示される。

追加プローブ結果:

```json
{
  "zoomControls": 0,
  "popups": 0,
  "tiles": 20,
  "eqPulse": 1,
  "rainPulse": 1,
  "textBad": false
}
```

## 日本全土表示確認

スクリーンショットで以下を確認:

- 北海道、本州、四国、九州、沖縄本島周辺が中央メイン地図内に収まる。
- 東京周辺だけのズーム、本州のみ表示、海だけ、真っ白表示ではない。

保存先:

- `test-results/live-stream-phase3a-main-map-real-1920.png`

## 操作 UI 無効化確認

確認結果:

- `.leaflet-control-zoom` は存在しない。
- `.leaflet-popup` は存在しない。
- ドラッグ、ホイール、ダブルクリック後も Leaflet map pane の transform は変化しない。

追加プローブ結果:

```json
{
  "before": "translate3d(0px, 0px, 0px)",
  "after": "translate3d(0px, 0px, 0px)",
  "tileBefore": "",
  "tileAfter": "",
  "unchanged": true
}
```

## demo=1 パルス確認

対象 URL:

- `/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00`

確認結果:

- 中央メイン地図は Leaflet 本番地図で表示。
- `live-stream-pulse-earthquake` が本番地図上に表示。
- `live-stream-pulse-rain` が本番地図上に表示。
- パルスは地図外や画面端に飛んでいない。
- テロップ、小窓、カテゴリパネルは既存通り表示。

## state=calm 確認

対象 URL:

- `/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00`

確認結果:

- 中央メイン地図は Leaflet 本番地図で表示。
- 地震/豪雨/潮位パルスは表示されない。
- 監視中文言と平常ステータスが表示される。

## 通常表示の実データ確認

対象 URL:

- `/live/stream?chrome=off`

確認結果:

- 画面は壊れない。
- 通常表示で demo 固定データの混入は確認されない。
- 実データ対象の有無に応じた表示で、パルスなしでも FAIL とはしない条件に合致。

## 既存 E2E

実行コマンド:

```bash
npx playwright test e2e/live-stream.spec.js e2e/eq-mock-verify.spec.js e2e/rain-mock-verify.spec.js e2e/tide-mock-verify.spec.js e2e/rail-mock-verify.spec.js e2e/live-stream-main-map.spec.js
```

結果:

- 75 passed
- 実行時間: 約 1.6 分

## 表示欠損・エラー確認

確認結果:

- `undefined`
- `null`
- `NaN`
- `Invalid Date`
- `[object Object]`

上記の不正表示は検出されず。

また、追加 E2E で page error / console error なしを確認。Leaflet 初期化例外、ポップアップ生成、タイル未読込による真っ白表示は確認されなかった。

## 総合判定

PASS。

Phase 3-A の受け入れ条件である、中央メイン地図の本番地図基盤化、日本全土表示、見るだけ地図化、既存パルス表示、OSM attribution、既存 E2E 回帰なしを満たしている。

# Phase 8-B 雨雲レイヤー視認性改善 検証レポート

## 判定

PASS

弱雨・通常雨は Canvas ピクセル加工で alpha を抑制し、赤系の危険雨域は相対的に濃く残ることを E2E で確認した。
実環境 `/live` の PC/モバイル表示でも、雨雲が地図全面を覆いすぎず、重要地震マーカーとボトムシート表示を確認できた。

## 変更範囲

- `frontend/js/live/live-layers.js`
  - `/live` 専用の雨雲タイルを Canvas タイル化。
  - JMA 降水ナウキャスト色テーブルに基づき、弱雨 0.25、通常雨 0.40、強雨 0.65、危険雨域 0.70-0.90 の alpha 係数を適用。
  - 背景白系と低 alpha ピクセルは透明化。
  - Canvas 読み取り不可時はタイル全体 opacity 0.35 の fallback。
- `e2e/live-rain-visibility.spec.js`
  - 雨雲 ON/OFF、タイムライン、再生ボタン、他レイヤー共存の回帰確認を追加。
  - 疑似 JMA 色タイルを使い、弱雨 < 通常雨 < 危険雨域、背景透明化をピクセル alpha として検証。
- `tasks/live/live_phase8b_rain_visibility_desktop.png`
- `tasks/live/live_phase8b_rain_visibility_mobile.png`

## 実行コマンド

```bash
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-alert-panel.js
node --check e2e/live-rain-visibility.spec.js
node --check e2e/live-eq-important.spec.js
python3 -m compileall backend/app
docker compose ps
npx playwright test e2e/live-rain-visibility.spec.js --project=chromium
npx playwright test e2e/live-eq-important.spec.js e2e/live-rain-timeline.spec.js --project=chromium
npx playwright screenshot --viewport-size=1440,900 --wait-for-selector=#live-alert-card --wait-for-timeout=6000 http://127.0.0.1:8080/live tasks/live/live_phase8b_rain_visibility_desktop.png
npx playwright screenshot --viewport-size=390,844 --wait-for-selector=#live-alert-card --wait-for-timeout=6000 http://127.0.0.1:8080/live tasks/live/live_phase8b_rain_visibility_mobile.png
```

補助 Playwright probe で Docker 実環境 `/live` の `pageerror` / `console.error` / `console.warning` が 0 件であることも確認した。

## 結果

- frontend JS 構文チェック: PASS
- backend compile: PASS
- Docker 環境: 起動済み、backend healthy
- `/live` console/page error: 0 件
- Phase 8-B E2E: 14 passed
- 関連回帰 E2E: `live-eq-important` + `live-rain-timeline` 43 passed

## PC/モバイル確認

- PC: 弱雨の青系は背景情報として薄く、赤・黄の強雨域は災害情報として視認可能。
- PC: 重要地震マーカーが雨雲より前面で見える。
- モバイル: ボトムシート越しでも雨雲が濃すぎず、横スクロールなし。
- モバイル: レイヤー FAB、地震マーカー、強雨域表示に破綻なし。

## スクリーンショット

- `tasks/live/live_phase8b_rain_visibility_desktop.png`
- `tasks/live/live_phase8b_rain_visibility_mobile.png`

## 残課題

- 現地の降水状況により雨雲分布は変動するため、色係数は今後の実観測で微調整余地あり。
- JMA 側 CORS が変化した場合は fallback opacity 0.35 で表示継続するが、色別 alpha 加工は CORS 依存。

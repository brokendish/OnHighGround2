# /live/stream Phase Stream-2-A Codex Verification

## 判定

PASS

`/live/stream` Phase Stream-2-A は、Phase Stream-1 の表示を維持したまま、`demoNow` による時刻固定、実時刻時計更新、`renderTide()` の固定時刻廃止、主要 `data-testid` 追加、nginx 経由の dedicated E2E を確認できた。通常 `/live` および `/` の回帰も問題なし。

## 検証日時

- 2026-07-01 22:09:51 JST

## 対象

- Branch: `main`
- HEAD: `ba6f7bd`
- Target: `http://127.0.0.1:8080/live/stream`

## 追加・変更ファイル

Claude 実装として以下の `/live/stream` 専用ファイル変更を確認した。

- `frontend/live/stream.html`
- `frontend/css/live/live-stream.css`
- `frontend/js/live-stream/live-stream-clock.js`
- `frontend/js/live-stream/live-stream-main.js`
- `frontend/js/live-stream/live-stream-map.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-scene.js`
- `frontend/js/live-stream/live-stream-ticker.js`

Codex 追加:

- `e2e/live-stream.spec.js`
- `tasks/live/live_stream_phase2a_codex_verification.md`

既存ナビ本体 `frontend/index.html`, `frontend/js/navigation.js`, `frontend/js/nav-*.js`, `frontend/js/hazard-layers.js`, `frontend/js/location-info-panel.js` への変更は確認されなかった。

## 静的確認

### renderTide 固定時刻廃止

- `renderTide()` は `function renderTide(el, st, currentHourFloat)` になっている。
- `const cur = currentHourFloat;` により呼び出し元から現在時刻を受け取る。
- `frontend/js/live-stream/live-stream-panels.js` で `LiveStreamClock.getCurrentHourFloat()` を取得し、潮位 current 値と潮位カーブへ渡している。
- `19.42` は `demoNow` の例や説明コメントにのみ残り、処理値としての `const cur = 19.42` は残っていない。

### demoNow

- `frontend/js/live-stream/live-stream-clock.js` に `LiveStreamClock` が追加されている。
- `?demoNow=2026-06-30T19:42:00%2B09:00` を固定時刻として扱う。
- `+` がスペースにデコードされた場合に備え、`.replace(/ /g, '+')` で補正している。
- `demoNow` 指定時は `live-stream-main.js` で時計更新 interval を張らず、初回表示のみ。
- `demoNow` 未指定時は時計が毎秒更新される。

### data-testid

主要静的 DOM の `data-testid` を確認した。

- `live-stream-stage`
- `live-stream-header`
- `live-stream-clock`
- `live-stream-date`
- `live-stream-status-bar`
- `live-stream-center`
- `live-stream-center-map`
- `live-stream-center-time`
- `live-stream-alert-level`
- `live-stream-panel-earthquake`
- `live-stream-panel-rain`
- `live-stream-panel-rail`
- `live-stream-panel-tide`
- `live-stream-ticker`
- `live-stream-ticker-body`
- `live-stream-dev-chrome`
- `live-stream-earthquake-list`
- `live-stream-rain-list`
- `live-stream-rail-list`
- `live-stream-tide-station-list`

動的生成要素の `data-testid` も確認した。

- `live-stream-tide-current-marker`
- `live-stream-tide-curve`
- `live-stream-pulse-earthquake`
- `live-stream-pulse-rain`
- `live-stream-pulse-rail`
- `live-stream-pulse-tide`

### buildScene

- `frontend/js/live-stream/live-stream-scene.js` の `buildScene(rawLiveData, options)` は維持されている。
- 将来の `/live` 正規化済みデータ接続用の JSDoc が追加されている。

## 構文チェック

すべて成功。

- `node --check e2e/live-stream.spec.js`
- `node --check frontend/js/live-stream/live-stream-main.js`
- `node --check frontend/js/live-stream/live-stream-scene.js`
- `node --check frontend/js/live-stream/live-stream-clock.js`
- `node --check frontend/js/live-stream/live-stream-ticker.js`
- `node --check frontend/js/live-stream/live-stream-panels.js`
- `node --check frontend/js/live-stream/live-stream-map.js`

## Docker 状態

`docker compose ps` で以下を確認した。

- `evacuation-navi-backend`: Up, healthy, `8000`
- `evacuation-navi-frontend`: Up, `8080`
- `evacuation-navi-martin`: Up, healthy
- `evacuation-navi-osrm-walking`: Up, `5501`

## HTTP 確認

すべて `HTTP/1.1 200 OK`。

- `/live/stream`
- `/live/stream?state=calm`
- `/live/stream?state=alert`
- `/live/stream?chrome=off`
- `/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00`
- `/live`
- `/`

## Dedicated E2E

`e2e/live-stream.spec.js` を追加した。既存 Playwright 設定は変更せず、テスト内で Docker frontend の nginx 経由 URL `http://127.0.0.1:8080` を直接指定している。

実行結果:

```text
npx playwright test e2e/live-stream.spec.js
8 passed (10.2s)
```

テスト内容:

- calm 表示で stage/header/center/4 panels/ticker と対象なし表示を確認
- alert 表示で地震・豪雨・鉄道・潮位表示とカテゴリ別パルスを確認
- `demoNow=2026-06-30T19:42:00+09:00` でヘッダー時計と中央地図時計が固定されることを確認
- `demoNow` 未指定で時計が2秒後に更新されることを確認
- `demoNow=06:00` と `demoNow=18:00` で `live-stream-tide-current-marker` の `cx` が変わることを確認
- `chrome=off` で開発UIが非表示になることを確認
- `/live` に stream CSS/DOM が漏れていないことを確認
- `/` に stream CSS/DOM が漏れていないことを確認
- 各ページで console/page error なしを確認

## Playwright / 画面確認

E2E とスクリーンショットで以下を確認した。

- page error: なし
- console error: なし
- `?state=calm`: 「現在、表示対象なし」表示
- `?state=alert`: 地震・豪雨・鉄道・潮位の表示
- `?chrome=off`: 開発UI非表示
- `demoNow=19:42`: ヘッダー時計 `19:42:00`、中央地図時計 `19:42`
- `demoNow` 未指定: 2秒待機で `HH:MM:SS` が変化
- `demoNow=06:00` と `demoNow=18:00`: 潮位現在マーカー位置が変化
- 通常 `/live`: title / map 表示、stream CSS/DOM 漏れなし
- `/`: title / map 表示、stream CSS/DOM 漏れなし

## スクリーンショット

- `test-results/live-stream-phase2a-calm-1920.png`
- `test-results/live-stream-phase2a-alert-1920.png`

確認内容:

- stage が 1920x1080 に収まる
- 横スクロールなし
- 縦スクロールなし
- ヘッダー、中央地図、小窓4種、下部テロップが整列
- `demoNow` により時計表示が `19:42:00` / `19:42` に固定

## Notes

- `docs/live/DEVELOPMENT_GUARDRAILS.md` の「触ってよい場所」には `frontend/live/` と `frontend/js/live-stream/` が明記されていない。ただし既存 `/live` 本体やナビ本体を改変せず `/live/stream` を分離する目的には合っているため、今回も注意事項として扱った。
- Google Fonts 外部参照は残っているが、今回の FAIL 条件ではない。
- alert の潮位小窓は2拠点ずつ8秒巡回するため、初期表示では警戒拠点の `高潮警戒` ラベルが出ない場合がある。中央地図の潮位パルスと件数は表示される。

## 修正推奨事項

Phase Stream-2-A の受け入れを妨げる修正必須事項はなし。

次フェーズ候補:

- `/live` 正規化済みデータを `buildScene()` に接続
- earthquake / rain / rain-timeline / rail API から SCENES 形式へ変換
- 小窓地図を簡易 SVG から既存 Leaflet / MapLibre 基盤に置換
- テロップ文言の動的 API 連携
- フォントのセルフホスト化

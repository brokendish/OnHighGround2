# Stream Phase 2-D: モック残存除去・実データ整合性修正 Codex 検証

検証日: 2026-07-02
対象: `tasks/stream/Stream Phase 2-D: モック残存除去・実データ整合性修正_CODEX.md`
結果: PASS（軽微な注記あり）

## 検証サマリ

- 通常表示 `/live/stream` は `state` 未指定で警戒画面になり、旧自動デモ巡回には戻らないことを確認した。
- 開発用 state ボタンは通常表示では非表示で、`?devControls=1` のときのみ表示されることを E2E で確認した。
- `?demo=1` はデモ固定、`?state=calm` は平穏固定として分離されていることを確認した。
- 実データ画面では demo 固有語（例: 岩手県沖、静岡県 中部、中央線快速）が出ず、実 API 由来の地震・大雨・潮位テロップが表示された。
- 情報が存在する実データ画面で、中央の「現在、表示対象なし」相当の空表示が出ないことを確認した。
- 潮位の現在時刻マーカーは JST の `demoNow` に追従し、06:00 / 12:00 / 18:00 で左から右に移動することを確認した。
- 潮位表示は API 値と一致することを代表点で確認した（函館: 画面 56cm / API `HK.current_tide_cm=56`）。
- 東京・横浜 API は詳細 records/high/low を返しており、Phase 2-D 指定例の実データ口として取得可能であることを確認した。
- 豪雨・キキクルの重複対策は `live-stream-rain-adapter.js` の area 名ベース dedupe で確認した。
- API 500 / 不正 JSON / 0 件系は既存 mock E2E でカテゴリ別に確認した。

## 実行結果

### 静的チェック

- `node --check frontend/js/live-stream/live-stream-main.js` PASS
- `node --check frontend/js/live-stream/live-stream-scene.js` PASS
- `node --check frontend/js/live-stream/live-stream-panels.js` PASS
- `node --check frontend/js/live-stream/live-stream-tide-adapter.js` PASS
- `node --check frontend/js/live-stream/live-stream-rain-adapter.js` PASS
- `node --check e2e/live-stream.spec.js` PASS

### HTTP / Docker

- `docker compose ps` PASS
  - backend: healthy
  - frontend: up
  - martin: healthy
  - osrm-walking: up
- `curl -I http://127.0.0.1:8080/live/stream` 200
- `curl -I http://127.0.0.1:8080/live/stream?chrome=off` 200
- `curl -I http://127.0.0.1:8080/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00` 200
- `curl -I http://127.0.0.1:8080/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00` 200
- `curl -I http://127.0.0.1:8080/live` 200

### E2E

- `npx playwright test e2e/live-stream.spec.js`
  - 45/45 PASS
  - Phase 2-D 追加ケース:
    - dev controls hidden without `devControls=1`
    - dev controls visible with `devControls=1`
    - no state param defaults to alert display
    - tide marker 06:00 is left of chart center
    - tide marker 18:00 is right of chart center
    - tide marker 18:00 is further right than 06:00

- `npx playwright test e2e/eq-mock-verify.spec.js`
  - 5/5 PASS

- `npx playwright test e2e/rain-mock-verify.spec.js`
  - 6/6 PASS

- `npx playwright test e2e/tide-mock-verify.spec.js`
  - 6/6 PASS

- `npx playwright test e2e/rail-mock-verify.spec.js`
  - 7/7 PASS

合計: 69/69 PASS

## 追加プローブ

### 潮位マーカー位置

`?state=alert&chrome=off&demo=1&demoNow=...` で SVG current marker の `cx` を確認。

- 06:00 JST: `cx=106.5`
- 12:00 JST: `cx=183`
- 18:00 JST: `cx=259.5`

06:00 < 12:00 < 18:00 で、JST 時刻に応じた位置として整合。

### 通常実データ画面

`/live/stream?chrome=off` を 9 秒待機して確認。

- dev controls visible: `false`
- center empty count: `0`
- tide display: `函館 / 56cm`
- ticker 抜粋: `【地震】20:48 福島県会津 M4.6 最大震度2 - なし ／ 【大雨】宮城県付近 豪雨キキクル「警戒」 ／ 【潮位】稚内 満潮01:00 11cm`
- demo 固有語検出: `false`

### 潮位 API 照合

- `/api/live/tide/stations/HK`
  - `current_tide_cm: 56`
  - 画面表示の函館 `56cm` と一致
- `/api/live/tide/stations/TK`
  - 東京の `current_tide_cm`, `next_high_tide`, `next_low_tide`, `records` を取得
- `/api/live/tide/stations/QS`
  - 横浜の `current_tide_cm`, `next_high_tide`, `next_low_tide`, `records` を取得

## スクリーンショット

- `test-results/live-stream-phase2d-cleanup-real-1920.png`
- `test-results/live-stream-phase2d-cleanup-demo-1920.png`
- `test-results/live-stream-phase2d-cleanup-calm-1920.png`
- `test-results/live-stream-phase2d-tide-0600.png`
- `test-results/live-stream-phase2d-tide-1200.png`
- `test-results/live-stream-phase2d-tide-1800.png`

## 注記

- 開発用ボタンの markup は DOM ソース上に残るが、通常表示では非表示で、`?devControls=1` の明示指定時のみ表示される。Phase 2-D の通常画面要件としては問題なし。
- 潮位の画面/API 値照合は、実画面でその時点に表示された代表拠点（函館）で一致を確認した。東京・横浜は API 取得口と records/high/low の存在確認まで実施。
- 豪雨・キキクル重複除去は adapter の実装確認を含む。現在の mock E2E は危険度優先・watch 除外・0 件/500/不正 JSON を検証しており、重複専用ケースは未追加。


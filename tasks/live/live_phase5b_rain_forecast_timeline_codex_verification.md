# Phase 5-B 雨雲予測タイムライン MVP 検証レポート

## 実施日時

2026-06-03 09:55:52 JST

## Docker状態

`docker compose build`: PASS

`docker compose up -d`: PASS

`docker compose ps`: backend healthy / frontend Up / martin healthy / osrm-walking Up

`/health`: healthy

## 構文確認結果

`python3 -m compileall backend/app`: PASS

`node --check frontend/js/live/*.js`: PASS

`git diff --check`: PASS

## タイムライン確認結果

PASS

- `/live` で `#live-rain-timeline` が表示された。
- スライダー、再生ボタン、現在時刻/予測時刻ラベルが表示された。
- `/api/live/rain/timeline` は 13 フレームを返した。

確認フレーム:

```text
現在, +5分, +10分, +15分, +20分, +25分, +30分,
+35分, +40分, +45分, +50分, +55分, +60分
```

## スライダー確認結果

PASS

- `min=0`, `max=12`, `step=1`
- 0 から 12 まで手動移動可能。
- 各フレームでオフセット表示と時刻表示が更新された。
- 例: `0=現在 00:50`, `6=+30分 01:20`, `12=+60分 01:50`

## 再生確認結果

PASS

- 再生ボタン押下で `▶` から `⏸` に変化。
- 再生中にフレームが進行。
- `+60分` 到達を確認。
- 停止ボタン押下で `⏸` から `▶` に戻る。

## タイル更新確認結果

PASS

現在フレームと予測フレームで Leaflet rain tile layer の URL 変化を確認した。

例:

```text
現在:
https://www.jma.go.jp/bosai/jmatile/data/nowc/20260603005000/none/20260603005000/surf/hrpns/{z}/{x}/{y}.png

+30分:
https://www.jma.go.jp/bosai/jmatile/data/nowc/20260603005000/none/20260603012000/surf/hrpns/{z}/{x}/{y}.png

+60分:
https://www.jma.go.jp/bosai/jmatile/data/nowc/20260603005000/none/20260603015000/surf/hrpns/{z}/{x}/{y}.png
```

## false-safe確認結果

PASS

- スライダー操作中の `/api/live/summary` 追加呼び出しなし。
- 実画面プローブで `summary=1`, `rainTimeline=1`, `rainTileTimes=1`, `earthquakes=1`, `kikikuru=0`。
- 追加 E2E `e2e/live-rain-timeline.spec.js` の false-safe 確認も PASS。
- dangerous_areas / integrated_dangerous_regions / キキクル / 地震の集計変化は検出されなかった。

## Console確認結果

実画面 `/live`: PASS

- console error: 0
- page error: 0

ナビ本体 `/`: PASS

- console error: 0
- page error: 0
- `/api/live/rain/timeline` 自動呼び出し: 0

## 回帰確認結果

`npx playwright test e2e/live-basic.spec.js e2e/live-earthquake-layer.spec.js e2e/live-sun-moon-card.spec.js e2e/live-tide-layer.spec.js e2e/live-storm-surge.spec.js e2e/live-integrated-regions.spec.js e2e/live-rain-timeline.spec.js`

初回結果: FAIL

```text
147 passed
8 failed
```

追加 E2E:

- `e2e/live-rain-timeline.spec.js`: 全 17 件 PASS

失敗内容:

- `e2e/live-basic.spec.js` の console error 確認 7 件
- `e2e/live-earthquake-layer.spec.js` の console error 確認 1 件

共通エラー:

```text
Failed to load resource: the server responded with a status of 404 (Not Found)
```

切り分け:

- 実画面 Docker 環境では `/api/live/rain/timeline` が 200 を返し、console error は発生しなかった。
- 追加 E2E は `/api/live/rain/timeline` を mock しており PASS。
- 既存 E2E の一部 mock は新規 timeline API を mock していないため、Playwright 開発サーバ上で 404 console error が発生している可能性が高い。
- 本タスクは「実装修正禁止」のため、E2E mock 修正は未実施。

再検証:

Claude 修正により、既存 live E2E mock に `/api/live/rain/timeline` が追加された。

修正対象:

- `e2e/live-basic.spec.js`
- `e2e/live-earthquake-layer.spec.js`
- `e2e/live-sun-moon-card.spec.js`
- `e2e/live-tide-layer.spec.js`
- `e2e/live-storm-surge.spec.js`
- `e2e/live-integrated-regions.spec.js`
- `e2e/live-location-gesture.spec.js`
- `e2e/live-entry-button.spec.js`

再実施日時: 2026-06-03 10:04:39 JST

再実行結果: PASS

```text
155 passed
0 failed
```

## ナビ本体影響確認

PASS

- `http://127.0.0.1:8080/` は正常表示。
- console error / page error なし。
- 雨雲タイムライン API の自動呼び出しなし。

## スクリーンショット

- `tasks/live/live_phase5b_rain_timeline.png`
- `tasks/live/live_phase5b_nav_home.png`

## 最終判定

PASS

理由:

- Phase 5-B の実画面機能、追加 E2E、false-safe、ナビ本体影響は PASS。
- 初回は既存 E2E mock が新規 `/api/live/rain/timeline` 呼び出しを受けていないことによる 404 console error で 8 件失敗した。
- Claude 修正後に同一回帰スイートを再実行し、155 件すべて PASS した。

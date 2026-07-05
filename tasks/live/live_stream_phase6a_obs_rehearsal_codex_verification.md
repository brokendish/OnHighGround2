# Live Stream Phase 6-A OBS Rehearsal Codex Verification

検証日: 2026-07-04  
対象: `/live/stream` OBS実配信リハーサル・公開前最終確認  
判定: **PASS with notes**

## 結論

`http://127.0.0.1:8080/live/stream?chrome=off` は、本番リハーサル用URLとして表示可能で、`demo=1` / `focusSpeed=test` / `runtimeSpeed=test` の混入は確認されませんでした。専用E2E、関連live系E2E、10分プローブ、1920x1080スクリーンショット確認はいずれも致命的問題なしです。

ただし、OBS実機プレビュー、YouTube限定/非公開配信、30分以上の連続リハーサルは未実施です。また、直前のPhase 5-C Codex検証はdemo診断プローブ中の `TypeError: Failed to fetch` によりFAIL判定だったため、公開判断ではその既知リスクを別途扱ってください。

## 確認した成果物

- `tasks/live/live_stream_phase6a_obs_rehearsal_runbook.md`
- `tasks/live/live_stream_phase6a_public_preflight_checklist.md`
- `tools/live_stream_obs_rehearsal_probe.js`
- `e2e/live-stream-obs-rehearsal.spec.js`

Runbook/checklistは、production URLとdemo/test URLの境界、OBS設定、30分リハーサル手順、YouTube限定/非公開配信手順、停止・復旧手順を含んでいました。

## 静的確認

以下はすべて成功しました。

```bash
node --check tools/live_stream_obs_rehearsal_probe.js
node --check e2e/live-stream-obs-rehearsal.spec.js
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-event-store.js
```

## URL疎通

Dockerコンテナは起動済みでした。

- `evacuation-navi-backend`: Up / healthy
- `evacuation-navi-frontend`: Up
- `evacuation-navi-martin`: Up / healthy
- `evacuation-navi-osrm-walking`: Up

HTTP確認はいずれも `200 OK` です。

- `http://127.0.0.1:8080/live/stream?chrome=off`
- `http://127.0.0.1:8080/live/stream?state=calm&chrome=off`
- `http://127.0.0.1:8080/live/stream?demo=1&chrome=off`
- `http://127.0.0.1:8080/live/stream`
- `http://127.0.0.1:8080/live`
- `http://127.0.0.1:8080/`

## E2E結果

専用E2E:

```bash
npx playwright test e2e/live-stream-obs-rehearsal.spec.js
```

結果: **13 passed**

関連live系E2E:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-stability.spec.js \
  e2e/live-stream-earthquake-detail.spec.js \
  e2e/live-stream-earthquake-detail-map-sync.spec.js \
  e2e/live-stream-railway-detail.spec.js \
  e2e/live-stream-railway-color-layer.spec.js \
  e2e/live-stream-railway-calm-map.spec.js \
  e2e/live-stream-obs-rehearsal.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

結果: **204 passed**

確認できた主な観点:

- production URLは `dataMode=real` を維持し、demo/calmへ混入しない
- production URLにdev controlsが出ない
- 1920x1080で主要UIが表示領域内に収まる
- 中央地図・小地図・tickerが描画される
- API失敗時にnormal扱い・demo fallbackにならない
- `/live` と `/` に副作用がない
- 地図marker、ticker、railway layerの増殖防止テストが通る

## 10分プローブ

実行:

```bash
node tools/live_stream_obs_rehearsal_probe.js \
  --url 'http://127.0.0.1:8080/live/stream?chrome=off' \
  --minutes 10 \
  --interval 300 \
  --output test-results/live-stream-phase6a-rehearsal-probe.json \
  --screenshot-dir test-results
```

結果:

- `pageerror`: 0
- `consoleError`: 0
- `requestFailed`: 5
- `dataMode`: start/t5min/t10minすべて `real`
- `runtimeState`: start=`loading`, t5min=`healthy`, t10min=`healthy`
- `leafletContainerCount`: start/t5min/t10minすべて `4`

サンプル値:

| sample | dataMode | runtimeState | Leaflet containers | map markers | rail layer count | ticker nodes |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| start | real | loading | 4 | 0 | 2 | 2 |
| t5min | real | healthy | 4 | 7 | 2 | 2 |
| t10min | real | healthy | 4 | 7 | 2 | 2 |

`requestFailed` の内訳は、`railways_japan.pmtiles` とCARTOタイルの `net::ERR_ABORTED` でした。Phase 6-A仕様上、tile/PMTiles系のrequestfailedは非致命の注記扱いです。

## スクリーンショット

すべて1920x1080で保存済みです。

- `test-results/live-stream-phase6a-obs-rehearsal-normal-start-1920.png`
- `test-results/live-stream-phase6a-obs-rehearsal-normal-mid-1920.png`
- `test-results/live-stream-phase6a-obs-rehearsal-normal-end-1920.png`
- `test-results/live-stream-phase6a-obs-rehearsal-calm-1920.png`
- `test-results/live-stream-phase6a-obs-rehearsal-demo-1920.png`

目視確認では、通常終了・calm・demoの各画面で白画面、大きな崩れ、主要UIの明確な重なりは見当たりませんでした。

## 未実施・注記

- OBS実機のBrowser Sourceプレビューは未実施です。
- YouTube限定/非公開配信での実リハーサルは未実施です。
- 今回の連続プローブは10分です。30分以上の本番想定soakは未実施です。
- Phase 5-C Codex検証は、demo診断プローブ中の `TypeError: Failed to fetch` によりFAIL判定でした。今回のproduction URLプローブでは `pageerror=0` / `consoleError=0` でしたが、Phase 5-Cの既知リスクは公開前チェックリストで別途クローズしてください。

## 判定理由

Phase 6-AのFAIL条件である、production URLの表示不能、production URLのdemo/test化、pageerror、重大なUI崩れ、Leaflet/ticker/railway layer増殖、API失敗のnormal扱い、diagnostics不在、`/live`破壊は確認されませんでした。

一方で、OBS実機・YouTube実配信・30分以上soakが未実施であり、前フェーズの既知リスクも残るため、最終判定は **PASS with notes** とします。

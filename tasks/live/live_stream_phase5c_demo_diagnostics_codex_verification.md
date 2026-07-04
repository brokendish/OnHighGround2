# live stream Phase 5-C demo diagnostics verification

## Result

FAIL

## Summary

Phase 5-C の目的である `demo=1` の diagnostics 整理は一部達成されている。

- `demo=1` で `dataMode=demo` / `runtimeState=demo` を確認
- `body[data-stream-data-mode="demo"]` / `body[data-stream-runtime-state="demo"]` を確認
- `demo=1` で `/api/live/*` の不要な periodic fetch が走らないことを確認
- real API failure は `dataMode=real` のまま `error/degraded` として扱われ、demo fallback しないことを確認
- calm は `dataMode=calm` として区別されることを確認
- scoped E2E は 203件 PASS

ただし、必須検証観点の `demo=1 で TypeError: Failed to fetch が出ない` は満たせなかった。5分probeで `TypeError: Failed to fetch` が1件再発したため、指示書のFAIL条件に従い FAIL とする。

また、`frontend/js/live-stream/live-stream-railway-layer.js` に `unhandledrejection` の `Failed to fetch` を `preventDefault()` するガードが入っている。今回の再発は `console.error` として観測されており、このガードでは解消されていない。指示書の「console.error / unhandledrejection を不自然に握りつぶしていないか」の観点でも、追加整理が必要。

## Checked Files

```text
docs/live/DEVELOPMENT_GUARDRAILS.md
tasks/stream/live_stream_phase5c_codex_verification_instruction.md
tasks/live/live_stream_phase5b_obs_soak_codex_verification.md
frontend/js/live-stream/live-stream-runtime.js
frontend/js/live-stream/live-stream-main.js
frontend/js/live-stream/live-stream-railway-layer.js
frontend/js/live-stream/live-stream-rain-layer.js
e2e/live-stream-demo-diagnostics.spec.js
```

## Environment

```text
branch: main
commit: c6d451c
verified_at: 2026-07-04 21:31 JST
docker:
  backend: Up (healthy)
  frontend: Up
  martin: Up (healthy)
  osrm-walking: Up
```

作業ツリーには過去フェーズを含む未コミット差分がある。

## Commands

静的確認:

```text
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-rain-layer.js
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check frontend/js/live-stream/live-stream-earthquake-detail.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check e2e/live-stream-demo-diagnostics.spec.js
```

HTTP確認:

```text
200 /live/stream
200 /live/stream?chrome=off
200 /live/stream?demo=1&chrome=off
200 /live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
200 /live/stream?state=calm&chrome=off
200 /live/stream.html
200 /live
200 /
```

E2E:

```text
npx playwright test e2e/live-stream-demo-diagnostics.spec.js
npx playwright test e2e/live-stream-demo-diagnostics.spec.js ... scoped live-stream suite
```

Probe:

```text
node /private/tmp/live_phase5c_probe.js
```

一時probeは削除済み。成果物は `test-results/live-stream-phase5c-probe.json` に保存済み。

## Test Results

Phase 5-C 追加E2E:

```text
12 passed (15.7s)
```

Phase 5-C 追加E2E + Phase 5-B相当 scoped回帰:

```text
203 passed (5.1m)
```

対象:

```text
e2e/live-stream-demo-diagnostics.spec.js
e2e/live-stream.spec.js
e2e/live-stream-main-map.spec.js
e2e/live-stream-main-map-real-data.spec.js
e2e/live-stream-event-sync.spec.js
e2e/live-stream-status-sync.spec.js
e2e/live-stream-auto-focus.spec.js
e2e/live-stream-stability.spec.js
e2e/live-stream-earthquake-detail.spec.js
e2e/live-stream-earthquake-detail-map-sync.spec.js
e2e/live-stream-railway-detail.spec.js
e2e/live-stream-railway-color-layer.spec.js
e2e/live-stream-railway-calm-map.spec.js
e2e/eq-mock-verify.spec.js
e2e/rain-mock-verify.spec.js
e2e/tide-mock-verify.spec.js
e2e/rail-mock-verify.spec.js
```

## Demo Console Check

5分probe:

URL:

```text
/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
```

結果:

```text
consoleErrors: 1
failedToFetch: 1
pageErrors: 0
liveApiRequests: 0
requestFailed: 17
```

観測された console error:

```text
2026-07-04T12:28:51.631Z  TypeError: Failed to fetch
```

`/api/live/*` request は0件だったため、demo中に本番live API fetchが走っているわけではない。requestfailed は PMTiles/CARTO tile の abort が中心。

## Diagnostics Check

5分probeの snapshots:

```text
start:
  bodyDataMode=demo
  bodyRuntimeState=demo
  diagnostics.dataMode=demo
  diagnostics.runtimeState=demo
  eventCount=10
  leafletContainers=4
  tickerTextNodes=2
  recentFetchFailures=[]

3min:
  bodyDataMode=demo
  bodyRuntimeState=demo
  focusId=eq-demo-iwate
  leafletContainers=4
  tickerTextNodes=2
  eventCount=10

5min:
  bodyDataMode=demo
  bodyRuntimeState=demo
  focusId=eq-demo-iwate
  leafletContainers=4
  tickerTextNodes=2
  eventCount=10
```

`runtimeState=loading` 固定の問題は解消している。Leaflet containers / tickerTextNodes も増殖していない。

## Real Failure Check

追加E2Eで `/api/live/*` 500 をroute mockし、以下を確認済み。

```text
snapshot.dataMode === "real"
snapshot.runtimeState is degraded/error
snapshot.isDemo === false
recentFetchFailures.length > 0
API failure時に demo fallback しない
```

意図的な 500 による browser console の `Failed to load resource` は許容範囲。ただし `TypeError: Failed to fetch` は demo probe で再発しているため別問題。

## Calm Check

追加E2Eとスクリーンショットで以下を確認済み。

```text
snapshot.dataMode === "calm"
snapshot.isCalm === true
snapshot.isDemo === false
body[data-stream-data-mode="calm"]
map markers 0
ticker は監視中
demo表示なし
```

## Screenshots

```text
test-results/live-stream-phase5c-demo-diagnostics-1920.png
test-results/live-stream-phase5c-calm-diagnostics-1920.png
test-results/live-stream-phase5c-real-diagnostics-1920.png
```

目視では demo/calm/real いずれも白画面化・大きなUI崩れはない。

## Findings

1. `demo=1` の `TypeError: Failed to fetch` が5分probeで再発した。
   - Phase 5-C のPASS条件を満たさない。
   - 指示書のFAIL条件「demo=1 で TypeError: Failed to fetch が再発する」に該当。

2. `runtimeState/dataMode` 整理は機能している。
   - `demo`: `dataMode=demo`, `runtimeState=demo`
   - `calm`: `dataMode=calm`, `runtimeState=calm`
   - `real failure`: `dataMode=real`, `runtimeState=error/degraded`

3. demo中の `/api/live/*` fetch 抑制は機能している。
   - 5分probeで `liveApiRequests=0`

4. `unhandledrejection` ガードが広い。
   - `frontend/js/live-stream/live-stream-railway-layer.js` の `_installFetchAbortGuard()` は `Failed to fetch` を含む unhandled rejection を `preventDefault()` している。
   - コメントでは「ナビゲーション由来」としているが、条件は発生元を限定していない。
   - 今回の `TypeError: Failed to fetch` は console error として出ており、このガードでは解決していない。

## Notes

- scoped E2EはすべてPASSしたが、短時間E2Eでは低頻度のconsole errorを十分に拾えない。
- 画面破綻・pageerror・demo表示崩れは確認されなかった。
- PMTiles/CARTO tile の `requestfailed net::ERR_ABORTED` は残るが、これは画面破綻にはつながっていない。

## Final Judgement

FAIL

理由: `demo=1` の5分probeで `TypeError: Failed to fetch` が1件再発したため。Phase 5-Cの目的である demo mode console error 解消は未達。

---

## Disposition（プロダクトオーナー判断）

判定: **PASS with notes として受け入れる**（2026-07-04）

上記FAILの事実(`demo=1` で低頻度に `TypeError: Failed to fetch` が再発する)は正しく、覆さない。その上で、以下の理由から追加対応は行わず現状の実装を受け入れる。

- 発生元は自社コードではなく、CDN読み込み・バージョン固定の `protomaps-leaflet@4.1.1` 内部 (`renderTile()` 内、`reason.name!=="AbortError"` の reject を直接 `console.error` する箇所)。`leafletLayer()` の公開オプションにこの挙動 (`shouldCancelZooms` 等) を無効化する手段がなく、`sourceToViews()` 側で内部的に固定されている。
- 完全解消のためには次のいずれかが必要と判断した。
  1. `protomaps-leaflet` をフォークして当該 `console.error` 呼び出しを削除・改変する（サードパーティ改変、保守コスト増、バージョン追従が困難になる）。
  2. カメラのスムーズな `flyTo` 演出（ズームを連続的に遷移させる、配信画面の見せ場の一つ）をやめて瞬間移動にする（配信の演出価値を損なう）。
  3. `console.error` を選択的に握りつぶす（指示書で明確に禁止）。
  - いずれも費用対効果・指示書の制約・UX上の理由から見送りが妥当と判断した。
- 実施済みの緩和策 (中央地図・鉄道子画面小地図間でのPmtilesSource共有によるfetch重複削減) により、Phase 5-B時点の 4件/10分 から 1件/5分 まで頻度は下がっている。
- `pageerror` は0件、画面・ticker・focus・panel・mapいずれも継続動作しており、配信画面としての実害はない。
- `runtimeState`/`dataMode` 整理、`recentFetchFailures` によるfetch失敗の可視化、demo中の不要な `/api/live/*` fetch抑制など、Phase 5-Cの他の目的は達成できている。

以上を踏まえ、残存する低頻度の `TypeError: Failed to fetch` はサードパーティ地図ライブラリ内部起因の既知の残課題として記録し、これ以上のライブラリ内部対策は行わないことで合意した。

# live stream Phase 5-A stream stability verification

## Result

PASS with notes

## Summary

`/live/stream` Phase 5-A の配信用安定運用対策を検証した。ガードレール確認、差分の静的確認、HTTP疎通、Playwright E2E、追加の失敗系ブラウザプローブ、手動スクリーンショット確認を実施した。

確認した範囲では、timer / fetch / marker / ticker / panel / subscriber の増殖は再現せず、API失敗・timeoutでも pageerror は発生しなかった。失敗継続時は `degraded` または `error` を表現でき、復旧時は `healthy` に戻る。通常 `/live` への明確な副作用も確認されなかった。

## Checked files

- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `frontend/live/stream.html`
- `frontend/js/live-stream/live-stream-runtime.js`
- `frontend/js/live-stream/live-stream-main.js`
- `frontend/js/live-stream/live-stream-event-store.js`
- `frontend/js/live-stream/live-stream-focus-controller.js`
- `frontend/js/live-stream/live-stream-map-view.js`
- `frontend/js/live-stream/live-stream-map-events.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-scene.js`
- `frontend/js/live-stream/live-stream-rain-layer.js`
- `frontend/js/live-stream/live-stream-railway-layer.js`
- `e2e/live-stream-stability.spec.js`
- `e2e/live-stream-auto-focus.spec.js`
- `e2e/live-stream-status-sync.spec.js`
- `e2e/live-stream-event-sync.spec.js`

## Environment

- Local Docker environment
- Frontend: `http://127.0.0.1:8080`
- Backend: `http://127.0.0.1:8000`
- Browser checks: Playwright Chromium
- Date: 2026-07-04 JST

`docker compose ps` confirmed frontend, backend, martin, and osrm-walking containers were up; backend and martin were healthy.

## Commands

Static checks:

```bash
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-focus-policy.js
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-rain-layer.js
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check e2e/live-stream-stability.spec.js
node --check e2e/live-stream-auto-focus.spec.js
node --check e2e/live-stream-status-sync.spec.js
node --check e2e/live-stream-event-sync.spec.js
node --check e2e/live-stream.spec.js
```

HTTP checks:

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?runtimeSpeed=test"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

E2E:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-stability.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

Screenshots:

```bash
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 http://127.0.0.1:8080/live/stream test-results/live-stream-phase5a-stability-normal-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" test-results/live-stream-phase5a-stability-calm-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test&chrome=off" test-results/live-stream-phase5a-stability-demo-1920.png
```

## Test results

- JS syntax checks: PASS
- Python compile: not run, no backend changes identified for Phase 5-A
- HTTP checks: all `200 OK`
- Playwright E2E: PASS, `133 passed (2.5m)`

Key E2E coverage observed:

- diagnostics snapshot is available
- repeated refresh does not accumulate markers
- repeated refresh does not accumulate ticker DOM
- repeated refresh does not accumulate rail cards
- in-flight duplicate refresh is blocked
- continued API 500 does not cause pageerror
- continued failures move runtime to degraded/error
- recovery moves runtime back to healthy
- active class clears after focused event disappears
- calm/demo/real behavior remains valid
- Phase 3-D status sync remains valid
- `/live` regression remains valid

## Diagnostics snapshot

Additional browser probe confirmed `window.__LiveStreamDiagnostics.getSnapshot()` exposes the required operational information:

```json
{
  "runtimeState": "healthy",
  "refreshInFlight": false,
  "refreshCount": 4,
  "successCount": 4,
  "failureCount": 0,
  "consecutiveFailures": 0,
  "eventCount": 0,
  "focusMode": "overview",
  "focusEventId": null,
  "mapInitialized": true,
  "markerCount": 0,
  "subscriberCount": 0,
  "focusSubscribers": 2
}
```

The full snapshot also includes per-category state for `earthquake`, `rain`, `railway`, and `tide`, including `inFlight`, counts, success/failure counts, consecutive failures, status, and timestamps.

## Failure / recovery checks

Playwright E2E verified 500, invalid JSON, partial failure, continued failure, and recovery flows.

An additional route-mocked browser probe verified:

- empty healthy responses: `body[data-stream-runtime-state="healthy"]`, no pageerror
- all live APIs returning 404: `body[data-stream-runtime-state="error"]`, no pageerror
- all live APIs timing out under `runtimeSpeed=test`: `body[data-stream-runtime-state="error"]`, no pageerror

For the 404 case, browser console contained expected resource status messages for 404 responses only. They did not become page errors and did not break map initialization.

## Manual browser check

The generated screenshots were visually inspected:

- normal mode: map, category panels, ticker, counts, event markers, and status badge rendered correctly
- calm mode: no abnormal marker or panel accumulation; calm empty state rendered
- demo mode: focus presentation, panels, ticker, and markers rendered without visible duplication or runaway movement

No visible ticker doubling, panel stacking, marker explosion, or layout collapse was observed.

## Screenshots

- `test-results/live-stream-phase5a-stability-normal-1920.png`
- `test-results/live-stream-phase5a-stability-calm-1920.png`
- `test-results/live-stream-phase5a-stability-demo-1920.png`

## Findings

No blocking defects were found for Phase 5-A.

Implementation notes from verification:

- `LiveStreamRuntime` is implemented as a diagnostics and guard layer over the existing four independent category fetch intervals, rather than replacing them with one unified scheduler.
- Each category fetch path uses an in-flight guard, and the page-level fetch interval starter avoids duplicate interval registration.
- `LiveStreamEventStore` and `LiveStreamFocusController` prevent duplicate subscription of the same function reference.
- Map diagnostics report marker counts from map-event, rain, and railway layers.
- The focus panel logic now avoids re-running `focusOn()` / `fitJapan()` for the same `mode:eventId` key while still updating the HUD.

## Notes

- This verification did not run a 5-15 minute real OBS/YouTube soak. Stability was checked through E2E repeated refreshes, mocked failures, diagnostics snapshots, and screenshot inspection.
- `performance.memory` is environment-dependent and was treated as reference information only.
- `demo=1` intentionally skips live fetch intervals, so runtime fetch diagnostics are not used as the primary judgement for demo mode.
- Phase 4-B was explicitly out of scope / hold in the Phase 5-A instruction and was not used as a failure condition here.
- Tide/water alert focus and railway focus remain subject to the existing MVP behavior described in prior phase notes.

## Final judgement

PASS with notes

Phase 5-A の中心要件である「長時間表示で増殖しにくい」「API失敗で落ちない」「復旧できる」「通常 `/live` を壊さない」は、今回の検証範囲で満たしている。

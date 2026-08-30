# live stream Phase 4-A auto focus verification

## Result

PASS with notes.

`/live/stream` の自動巡回・注目地域フォーカス MVP は、EventStore 起点の候補選定、focus event id の地図・パネル・テロップ同期、calm / demo / empty / failure の安全動作、Phase 3-D のステータス・バッジ・件数同期維持、通常 `/live` への非干渉を確認できた。

## Summary

- `LiveStreamFocusPolicy.selectCandidates(events)` は `LiveStreamEventStore` と同じ正規化 event 配列を入力にし、DOM スクレイピングではなく event severity / 座標 / stale 除外を判断元にしている。
- `LiveStreamFocusController` は `overview` / `focus` / `returning` の状態を持ち、`body[data-stream-focus-mode]` と `body[data-stream-focus-event-id]` へ現在状態を露出している。
- focus 中の event id は中央地図 marker / demo pulse、左右パネル item、テロップの「注目」項目で同期される。
- 複数 event の巡回、active class の入れ替え、focus 対象消滅後の active 残存なしを E2E で確認した。
- `state=calm`、empty、API 500、404、不正 JSON、timeout 相当では focus せず、demo fallback も発生しない。
- Phase 3-D の badge/count/status E2E は維持されている。

## Checked files

- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `tasks/stream/live_stream_phase4a_codex_verification_instruction.md`
- `frontend/live/stream.html`
- `frontend/js/live-stream/live-stream-event-store.js`
- `frontend/js/live-stream/live-stream-focus-policy.js`
- `frontend/js/live-stream/live-stream-focus-controller.js`
- `frontend/js/live-stream/live-stream-main.js`
- `frontend/js/live-stream/live-stream-map-view.js`
- `frontend/js/live-stream/live-stream-map-events.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-scene.js`
- `frontend/js/live-stream/live-stream-earthquake-adapter.js`
- `frontend/js/live-stream/live-stream-rain-adapter.js`
- `frontend/js/live-stream/live-stream-railway-adapter.js`
- `frontend/js/live-stream/live-stream-tide-adapter.js`
- `frontend/css/live/live-stream.css`
- `e2e/live-stream-auto-focus.spec.js`
- `e2e/live-stream-status-sync.spec.js`
- `e2e/live-stream-event-sync.spec.js`
- `e2e/live-stream-main-map.spec.js`
- `e2e/live-stream-main-map-real-data.spec.js`
- `e2e/live-stream.spec.js`
- `e2e/eq-mock-verify.spec.js`
- `e2e/rain-mock-verify.spec.js`
- `e2e/tide-mock-verify.spec.js`
- `e2e/rail-mock-verify.spec.js`

## Environment

- Date: 2026-07-04
- Repository: repository root
- Frontend URL: `http://127.0.0.1:8080/live/stream`
- Docker services confirmed running:
  - `evacuation-navi-frontend`
  - `evacuation-navi-backend`
  - `evacuation-navi-martin`
  - `evacuation-navi-osrm-walking`

## Commands

```bash
git diff --stat
git diff
docker compose ps
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-focus-policy.js
node --check e2e/live-stream-auto-focus.spec.js
node --check e2e/live-stream-status-sync.spec.js
node --check e2e/live-stream-event-sync.spec.js
node --check e2e/live-stream-main-map.spec.js
node --check e2e/live-stream-main-map-real-data.spec.js
node --check e2e/live-stream.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
npx playwright test e2e/live-stream.spec.js e2e/live-stream-main-map.spec.js e2e/live-stream-main-map-real-data.spec.js e2e/live-stream-event-sync.spec.js e2e/live-stream-status-sync.spec.js e2e/live-stream-auto-focus.spec.js e2e/eq-mock-verify.spec.js e2e/rain-mock-verify.spec.js e2e/tide-mock-verify.spec.js e2e/rail-mock-verify.spec.js
node tmp_live_phase4a_failure_probe.js
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 http://127.0.0.1:8080/live/stream test-results/live-stream-phase4a-auto-focus-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" test-results/live-stream-phase4a-calm-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=2400 "http://127.0.0.1:8080/live/stream?state=alert&demo=1&focusSpeed=test&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00" test-results/live-stream-phase4a-demo-focus-1920.png
```

## Test results

- HTTP checks: all target URLs returned `200 OK`.
- JavaScript syntax checks: all checked frontend and E2E files passed `node --check`.
- Backend compile: not run because no backend changes were present.
- Playwright E2E: `121 passed (2.1m)`.

Phase 4-A specific E2E coverage:

- high-priority event becomes focus target.
- `body[data-stream-focus-mode]` and `body[data-stream-focus-event-id]` reflect focus state.
- focus id matches active map marker and panel item.
- ticker includes the focused event as `注目`.
- multiple events cycle from one focused id to another.
- `state=calm` never focuses.
- `demo=1` uses the same focus pipeline.
- empty data stays overview.
- total API failure does not focus and does not fall back to demo.
- active class is cleared when the focused event disappears.
- map remains non-interactive during focus cycling.
- `/live` regression is unaffected.

Additional failure probe:

- 404 all live APIs: focus stayed `overview`, focus event id empty, marker count `0`, ticker showed `取得確認中`, no `pageerror`.
- timeout-equivalent delayed APIs: focus stayed `overview`, focus event id empty, marker count `0`, ticker showed `取得確認中`, no `pageerror`.

## Manual browser check

Normal stream view:

- Real data state at capture time had earthquake/rain fetch unavailable, railway `1`, tide `0`.
- No demo fallback was visible.
- Center map remained visible and showed the active railway event marker.
- Panels, top badges, and ticker matched the available event/failure state.

Calm view:

- Top badges showed `地震 0`, `豪雨 0`, `鉄道 0`, `潮位 0`.
- Overall status showed `平常・監視中`.
- Center map stayed in nationwide overview with no focus label, marker, or pulse.
- Panels and ticker displayed calm monitoring content.

Demo focus view:

- Top badges showed `地震 2`, `豪雨 2`, `鉄道 4`, `潮位 2`.
- Focus label showed the active railway event.
- Center map moved to the focused event area and the active marker was highlighted.
- The matching railway panel card had active styling.
- Ticker included the same event under `注目`.
- The view did not flicker or obscure side panels/ticker.

## Screenshots

- `test-results/live-stream-phase4a-auto-focus-1920.png`
- `test-results/live-stream-phase4a-calm-1920.png`
- `test-results/live-stream-phase4a-demo-focus-1920.png`

## Findings

No blocking issues found.

Notes:

- `focusSpeed=test` exists and was used for fast E2E/manual verification; normal operation keeps the slower production cadence.
- Overview return is intentionally brief in test speed because the controller cycles through focus candidates quickly.
- The ticker prepends the focused event as `注目`; it does not pin every category item simultaneously.
- Tide/water alert events are still effectively out of scope unless `tide` / `water` normalized events exist. Tide station observations can render while badge/focus count remains `0`.
- Railway focus uses representative points, not full route geometry.
- 404 verification produced expected browser console resource failure messages, but no JS `pageerror` and no unhandled failure state in the page.
- The first direct `node tmp_live_phase4a_failure_probe.js` run hit macOS sandbox browser-launch restrictions; the same local probe passed when rerun with escalation. The temporary probe file was deleted after use.

## Notes

The working tree already contained uncommitted Claude implementation changes and prior verification reports before this verification started. This report only adds the Phase 4-A verification record and does not revert or alter unrelated changes.

## Final judgement

PASS with notes. The Phase 4-A implementation satisfies the MVP verification scope: EventStore-based focus selection, synchronized active event id across map/panel/ticker, safe calm/error behavior, Phase 3-D badge/count/status preservation, non-interactive map behavior, and no clear `/live` regression.

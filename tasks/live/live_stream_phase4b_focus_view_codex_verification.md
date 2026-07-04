# live stream Phase 4-B focus view verification

## Result

FAIL.

Phase 4-B 専用 E2E と既存回帰 E2E はすべて PASS したが、追加の demo focus 同期 probe で、focus event id が HUD / ticker には反映される一方、active map marker / active panel item に反映されないケースを確認した。これは検証指示書の FAIL 条件「HUD / marker / panel / ticker の focus id が不一致」に該当する。

## Summary

- Focus HUD は追加されており、`data-testid="stream-focus-hud"`、`data-focus-mode`、`data-focus-event-id`、`data-focus-type`、`data-focus-severity` を持つ。
- HUD は `LiveStreamFocusController` の state 購読から更新され、DOM スクレイピングで focus 対象を作ってはいない。
- `live-stream-focus-view.spec.js` の 13 観点は PASS した。
- calm / empty / 500 / invalid JSON / 404 / timeout 相当では古い focus 表示や active 表示は残らなかった。
- Phase 3-D の badge/count/status 回帰、地図操作不可、通常 `/live` 回帰は E2E で PASS した。
- ただし demo 巡回で `kikikuru-愛知県 東部-land` が focus 対象になったとき、HUD と ticker は同 id を示すが、active marker / active panel item が存在しない。

## Checked files

- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `tasks/stream/live_stream_phase4b_codex_verification_instruction.md`
- `frontend/live/stream.html`
- `frontend/css/live/live-stream.css`
- `frontend/js/live-stream/live-stream-event-store.js`
- `frontend/js/live-stream/live-stream-focus-policy.js`
- `frontend/js/live-stream/live-stream-focus-controller.js`
- `frontend/js/live-stream/live-stream-map-view.js`
- `frontend/js/live-stream/live-stream-map-events.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-main.js`
- `frontend/js/live-stream/live-stream-scene.js`
- `frontend/js/live-stream/live-stream-earthquake-adapter.js`
- `frontend/js/live-stream/live-stream-rain-adapter.js`
- `frontend/js/live-stream/live-stream-railway-adapter.js`
- `frontend/js/live-stream/live-stream-tide-adapter.js`
- `e2e/live-stream-focus-view.spec.js`
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
- Repository: `/Users/hideki/Documents/GitHub/OnHighGround2`
- Frontend URL: `http://127.0.0.1:8080/live/stream`
- Docker services confirmed running:
  - `evacuation-navi-frontend`
  - `evacuation-navi-backend`
  - `evacuation-navi-martin`
  - `evacuation-navi-osrm-walking`

## Commands

```bash
git diff --stat
git diff --name-only
docker compose ps
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-focus-policy.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check e2e/live-stream-focus-view.spec.js
node --check e2e/live-stream-auto-focus.spec.js
node --check e2e/live-stream-status-sync.spec.js
node --check e2e/live-stream-event-sync.spec.js
node --check e2e/live-stream-main-map.spec.js
node --check e2e/live-stream-main-map-real-data.spec.js
node --check e2e/live-stream.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
node --check e2e/tide-mock-verify.spec.js
node --check e2e/rail-mock-verify.spec.js
npx playwright test e2e/live-stream.spec.js e2e/live-stream-main-map.spec.js e2e/live-stream-main-map-real-data.spec.js e2e/live-stream-event-sync.spec.js e2e/live-stream-status-sync.spec.js e2e/live-stream-auto-focus.spec.js e2e/live-stream-focus-view.spec.js e2e/eq-mock-verify.spec.js e2e/rain-mock-verify.spec.js e2e/tide-mock-verify.spec.js e2e/rail-mock-verify.spec.js
node tmp_live_phase4b_failure_probe.js
node tmp_live_phase4b_demo_probe.js
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 http://127.0.0.1:8080/live/stream test-results/live-stream-phase4b-focus-view-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" test-results/live-stream-phase4b-calm-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=3600 "http://127.0.0.1:8080/live/stream?state=alert&demo=1&focusSpeed=test&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00" test-results/live-stream-phase4b-demo-focus-1920.png
```

## Test results

- HTTP checks: all target URLs returned `200 OK`.
- JavaScript syntax checks: all checked frontend and E2E files passed `node --check`.
- Backend compile: not run because no backend changes were present.
- Playwright E2E: `134 passed (2.5m)`.

Phase 4-B E2E coverage passed:

- HUD is shown while focused.
- HUD `data-focus-event-id` matches `body[data-stream-focus-event-id]`.
- focus event id matches active map marker.
- focus event id matches active panel item.
- ticker focus event id matches focus event id.
- no stale active markup remains in overview.
- active markup does not persist after returning to overview.
- calm never shows alert-styled HUD or marker/pulse.
- total API failure does not focus, does not demo fallback, and leaves no stale HUD.
- `focusSpeed=test` cycles HUD / marker / panel / ticker together for the mocked production case.
- map stays non-interactive.
- Phase 3-D badge/count/status sync still works.
- `/live` regression is unaffected.

Additional failure probe:

- 404 all live APIs: `focusMode="overview"`, HUD hidden, HUD event id empty, ticker focus id empty, active count `0`, pulse count `0`, event count `0`, no `pageerror`.
- timeout-equivalent delayed APIs: same safe state as 404, no `pageerror`.
- 404 produced browser resource-failure console messages only.

## Manual browser check

Normal stream view:

- The page rendered without crash.
- Top badges, panels, map markers, and ticker reflected the current real data / partial failure state.
- No stale HUD was visible at the captured overview/returning timing.

Calm view:

- Top badges showed `0`.
- Overall status showed calm monitoring.
- Center map stayed in nationwide overview.
- HUD was hidden.
- No marker/pulse/active focus styling remained.

Demo focus view:

- HUD was visible and readable near the top center of the map.
- HUD did not cover side panels or the bottom ticker.
- Map marker focus was visible for some focus targets.
- A failing demo synchronization case was observed separately via DOM probe: `kikikuru-愛知県 東部-land` had HUD/ticker focus ids but no active marker/panel item.

## Screenshots

- `test-results/live-stream-phase4b-focus-view-1920.png`
- `test-results/live-stream-phase4b-calm-1920.png`
- `test-results/live-stream-phase4b-demo-focus-1920.png`

## Findings

1. FAIL: Demo focus can point to an event that has no active map marker or active panel item.

   Evidence from `tmp_live_phase4b_demo_probe.js`:

   ```json
   {
     "mode": "focus",
     "id": "kikikuru-愛知県 東部-land",
     "hudId": "kikikuru-愛知県 東部-land",
     "tickerId": "kikikuru-愛知県 東部-land",
     "activeIds": []
   }
   ```

   Earlier samples in the same run showed correct sync for `kikikuru-静岡県 中部-land`, `chuo`, and `eq-demo-iwate`, so this appears to be a partial demo-pipeline mismatch rather than a total HUD failure.

   Likely cause: in demo mode, focus candidates are built from the normalized demo event set, but rendered demo pulses/panel popups are still tied to the existing scene cycle/current target. When focus selects a non-current demo rain target, HUD and ticker follow the FocusController, while the active marker/panel cannot find matching rendered DOM.

## Notes

- `prefers-reduced-motion` is handled via CSS for HUD/marker animations and via `LiveStreamMapView` reduced-motion checks for map movement. This was statically confirmed, not exhaustively E2E-asserted.
- Tide/water alert focus remains limited by normalized `tide` / `water` event availability.
- Railway focus remains representative-point based.
- Temporary probe files were added and removed during verification:
  - `tmp_live_phase4b_failure_probe.js`
  - `tmp_live_phase4b_demo_probe.js`
- The working tree already contained uncommitted Claude implementation changes and prior verification reports before this verification started. This report only adds the Phase 4-B verification record.

## Final judgement

FAIL. The implementation is mostly healthy and all E2E passed, but the additional demo focus probe found a focus id synchronization gap where HUD/ticker can focus `kikikuru-愛知県 東部-land` while no active map marker or active panel item exists.

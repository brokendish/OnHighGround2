# live stream Phase 3-C event panel ticker sync verification

## Result

PASS with notes

## Summary

`/live/stream` の中央メイン地図 event、左右パネル、下部テロップが同じ実データ由来 event に基づいて表示されることを検証した。

Phase 3-C の追加 E2E では、地震・キキクル/豪雨・鉄道の event id が地図 marker とパネル表示で一致し、同じ event 内容がテロップへ反映されることを確認した。空データ、API 500、不正 JSON、timeout 相当、`state=calm`、`demo=1`、通常 `/live` 回帰も確認し、通常アクセスで demo 表示へ fallback しないことを確認した。

## Checked files

- `frontend/live/stream.html`
- `frontend/css/live/live-stream.css`
- `frontend/js/live-stream/live-stream-event-store.js`
- `frontend/js/live-stream/live-stream-main.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-scene.js`
- `frontend/js/live-stream/live-stream-map-events.js`
- `frontend/js/live-stream/live-stream-map-view.js`
- `frontend/js/live-stream/live-stream-earthquake-adapter.js`
- `frontend/js/live-stream/live-stream-rain-adapter.js`
- `frontend/js/live-stream/live-stream-railway-adapter.js`
- `frontend/js/live-stream/live-stream-tide-adapter.js`
- `e2e/live-stream-event-sync.spec.js`
- `e2e/live-stream-main-map-real-data.spec.js`
- `e2e/live-stream-main-map.spec.js`
- `e2e/live-stream.spec.js`
- `e2e/eq-mock-verify.spec.js`
- `e2e/rain-mock-verify.spec.js`
- `e2e/tide-mock-verify.spec.js`
- `e2e/rail-mock-verify.spec.js`

## Environment

- Date: 2026-07-03
- App URL: `http://127.0.0.1:8080`
- Docker:
  - `evacuation-navi-frontend`: Up
  - `evacuation-navi-backend`: Up, healthy
  - `evacuation-navi-martin`: Up, healthy
  - `evacuation-navi-osrm-walking`: Up

## Commands

Static checks:

```bash
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js
node --check frontend/js/live-stream/live-stream-rain-adapter.js
node --check frontend/js/live-stream/live-stream-railway-adapter.js
node --check frontend/js/live-stream/live-stream-tide-adapter.js
node --check e2e/live-stream-event-sync.spec.js
node --check e2e/live-stream-main-map-real-data.spec.js
node --check e2e/live-stream-main-map.spec.js
node --check e2e/live-stream.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
```

HTTP checks:

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream
curl -I 'http://127.0.0.1:8080/live/stream?state=calm'
curl -I 'http://127.0.0.1:8080/live/stream?demo=1'
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/live/stream.html
```

E2E:

```bash
npx playwright test e2e/live-stream.spec.js e2e/live-stream-main-map.spec.js e2e/live-stream-main-map-real-data.spec.js e2e/live-stream-event-sync.spec.js e2e/eq-mock-verify.spec.js e2e/rain-mock-verify.spec.js e2e/tide-mock-verify.spec.js e2e/rail-mock-verify.spec.js
```

Screenshots:

```bash
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 http://127.0.0.1:8080/live/stream test-results/live-stream-phase3c-event-sync-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 'http://127.0.0.1:8080/live/stream?state=calm&chrome=off' test-results/live-stream-phase3c-calm-1920.png
npx playwright screenshot --viewport-size=1920,1080 'http://127.0.0.1:8080/live/stream?state=alert&demo=1&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00' test-results/live-stream-phase3c-demo-1920.png
```

## Test results

- JS syntax checks: PASS
- Backend Python compile: not run, no backend changes detected
- HTTP:
  - `/live/stream`: `200 OK`
  - `/live/stream?state=calm`: `200 OK`
  - `/live/stream?demo=1`: `200 OK`
  - `/live/stream.html`: `200 OK`
  - `/live`: `200 OK`
  - `/`: `200 OK`
- Playwright E2E: `96 passed (1.8m)`

Phase 3-C E2E confirmed:

- `eq-sync-001` is reflected on both map marker and earthquake popup.
- Kikikuru/rain event id matches between map marker and rain popup, and the title appears in ticker.
- `rail-sync-001` is reflected on both map marker and railway panel item.
- Store update removes stale content after event no longer qualifies.
- Empty API data produces no markers, calm panels, monitoring ticker, and no demo fallback.
- API 500 produces no crash, no demo fallback, and ticker shows data acquisition check text.
- Invalid JSON from earthquake API produces no crash and no demo fallback.
- `state=calm` suppresses markers and pulses even when mocked data exists.
- `demo=1` keeps demo events synchronized across map pulse, panel, and ticker.
- Map remains non-interactive.
- Normal `/live` remains unaffected.

Timeout probe:

```json
{
  "mapEvents": 0,
  "pulses": 0,
  "ticker": "【監視中】一部データの取得を確認中です。画面は最新取得済み情報をもとに監視を継続しています　／　...",
  "hasMap": true,
  "pageErrors": [],
  "consoleErrors": []
}
```

This confirms timeout-like delayed API responses do not create demo fallback and do not break the map.

## Manual browser check

URLs:

- `http://127.0.0.1:8080/live/stream`
- `http://127.0.0.1:8080/live/stream?state=calm&chrome=off`
- `http://127.0.0.1:8080/live/stream?state=alert&demo=1&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00`

Viewport:

- `1920x1080`

Confirmed:

- Normal access shows production-data map events, production-data panel content, and production-data ticker content.
- Normal access does not show demo pulse markers.
- `state=calm` shows no warning marker/pulse, calm panels, and monitoring ticker.
- `demo=1` shows demo pulse/event content consistently across map, panels, and ticker.
- Left/right panels and bottom ticker remain readable.
- OSM/CARTO/Leaflet attribution remains visible.

## Screenshots

- `test-results/live-stream-phase3c-event-sync-1920.png`
- `test-results/live-stream-phase3c-calm-1920.png`
- `test-results/live-stream-phase3c-demo-1920.png`

## Findings

No blocking findings.

Important implementation observations:

- `LiveStreamEventStore` exposes `setEvents`, `getEvents`, `getEventsByType`, `getHeadlineEvents`, `getSummary`, and `subscribe`.
- `live-stream-main.js` computes normalized stream events for real/demo/calm modes and updates `LiveStreamEventStore` through the same `setEvents()` path.
- In real mode, the central map reads `LiveStreamEventStore.getEvents()` and ticker is generated from the same normalized event array.
- Panels still render from the existing scene sections, but those sections are built from the same adapter models and now carry matching `data-event-id` attributes for earthquake, rain/kikikuru, railway, and tide cells.
- The previous earthquake fetch-failure mismatch was fixed: `buildScene()` now returns empty earthquake targets with `status: 'error'` instead of retaining demo earthquake targets.

## Notes

- Final judgement is PASS with notes because the top-level `.level[data-lv]` visual status remains the existing `calm/high` vocabulary and is not wired to `LiveStreamEventStore.getSummary().overallStatus`. This was explicitly scoped by Claude to avoid broad CSS/E2E churn.
- Tide/water-level map events remain effectively follow-up scope. Tide station coordinates are carried, but alert joining is still not implemented, so current tide events do not normally become central map events.
- `state=calm` remains the correct calm-mode URL. No migration to `calm=1` was observed.
- The first screenshot attempt without wait could capture partially loaded map tiles; final screenshots were captured with wait timeouts for normal/calm views.
- Multiple live events can mean the active panel card and ticker headline are not always the same single event at a given second, because panel focus cycles while ticker uses headline priority. Controlled E2E verifies that when a mocked event is the category focus, its id is synchronized across map/panel/ticker.

## Final judgement

PASS with notes.

The Phase 3-C acceptance criteria are met: `/live/stream` is available, the central map renders, map/panel/ticker content is synchronized from the same event pipeline for the verified categories, normal mode does not fall back to demo display, empty/failure/invalid/timeout cases do not break the page, failure is not mislabeled as ordinary calm, `state=calm` remains intact, map interaction stays disabled, attribution is visible, related E2E passes, and normal `/live` has no clear regression.

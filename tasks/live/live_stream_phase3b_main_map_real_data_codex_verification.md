# live stream Phase 3-B main map real data verification

## Result

PASS with notes

## Summary

`/live/stream` の中央メイン地図が、通常表示で demo pulse ではなく本番 API 由来の正規化イベント (`live-stream-map-event-*`) を描画することを確認した。

空データ、API 失敗、不正 JSON、timeout、座標不正、重複、stale、件数上限、地図操作不可、OSM/CARTO/Leaflet attribution、通常 `/live` 回帰を確認し、配信画面として破綻しないことを確認した。

## Checked files

- `frontend/live/stream.html`
- `frontend/css/live/live-stream.css`
- `frontend/js/live-stream/live-stream-main.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-map-view.js`
- `frontend/js/live-stream/live-stream-map-events.js`
- `frontend/js/live-stream/live-stream-earthquake-adapter.js`
- `frontend/js/live-stream/live-stream-rain-adapter.js`
- `frontend/js/live-stream/live-stream-railway-adapter.js`
- `frontend/js/live-stream/live-stream-tide-adapter.js`
- `frontend/js/live-stream/live-stream-scene.js`
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
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js
node --check frontend/js/live-stream/live-stream-rain-adapter.js
node --check frontend/js/live-stream/live-stream-railway-adapter.js
node --check frontend/js/live-stream/live-stream-tide-adapter.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check e2e/live-stream-main-map-real-data.spec.js
node --check e2e/live-stream-main-map.spec.js
node --check e2e/live-stream.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
node --check e2e/tide-mock-verify.spec.js
node --check e2e/rail-mock-verify.spec.js
```

HTTP checks:

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

E2E:

```bash
npx playwright test e2e/live-stream.spec.js e2e/live-stream-main-map.spec.js e2e/live-stream-main-map-real-data.spec.js e2e/eq-mock-verify.spec.js e2e/rain-mock-verify.spec.js e2e/tide-mock-verify.spec.js e2e/rail-mock-verify.spec.js
```

Screenshot:

```bash
npx playwright screenshot --viewport-size=1920,1080 http://127.0.0.1:8080/live/stream test-results/live-stream-phase3b-main-map-real-data-1920.png
```

## Test results

- JS syntax checks: PASS
- Backend Python compile: not run, no backend changes detected
- HTTP:
  - `/live/stream`: `200 OK`
  - `/live/stream.html`: `200 OK`
  - `/live`: `200 OK`
  - `/`: `200 OK`
- Playwright E2E: `85 passed (2.4m)`

Phase 3-B E2E confirmed:

- Earthquake event renders from mocked production API.
- Rain/Kikikuru representative event renders from mocked production API.
- Railway affected-line event renders from mocked production API.
- Invalid coordinates are excluded.
- Empty API data produces no marker and no crash.
- API 500 produces no page error, keeps the map, and does not fall back to demo markers.
- `demo=1` shows demo pulses and not production events.
- Normal access with empty production data does not show demo pulses.
- Production data mode keeps the map non-interactive.
- Normal `/live` Leaflet map remains unaffected.

Additional probe:

```json
{
  "total": 7,
  "eq": 5,
  "kiki": 1,
  "rail": 1,
  "stale": 1,
  "demoPulses": 0,
  "zoomControls": 0,
  "attribution": " Leaflet | © OpenStreetMap contributors © CARTO",
  "pageErrors": [],
  "consoleErrors": [],
  "transformUnchanged": true
}
```

This confirms:

- Earthquake markers are capped at 5 for the type.
- Duplicate IDs are deduped.
- Stale earthquake/rain are excluded.
- Stale railway remains visible with stale class.
- Demo pulses are not used in normal production-data mode.
- Drag, wheel, double-click, and keyboard operations do not move the map.

Failure scenario probe:

```json
[
  {
    "name": "404",
    "events": 0,
    "demoPulses": 0,
    "pageErrors": [],
    "consoleErrors": [
      "Failed to load resource: the server responded with a status of 404 (Not Found)"
    ],
    "hasMap": true
  },
  {
    "name": "invalid-json",
    "events": 0,
    "demoPulses": 0,
    "pageErrors": [],
    "consoleErrors": [],
    "hasMap": true
  },
  {
    "name": "timeout",
    "events": 0,
    "demoPulses": 0,
    "pageErrors": [],
    "consoleErrors": [],
    "hasMap": true
  }
]
```

The 404 console error is Chromium's resource-load error for mocked 404 responses. It did not produce a page error, map failure, or demo fallback.

## Manual browser check

URL:

- `http://127.0.0.1:8080/live/stream`

Viewport:

- `1920x1080`

Confirmed:

- Central map uses Leaflet/CARTO/OSM production map tiles.
- Normal access displays production-data event marker(s), not demo pulse markers.
- Marker count is restrained and does not obscure the map.
- Marker visibility is acceptable on the dark basemap.
- Left/right panels and bottom ticker are not obstructed.
- OSM/CARTO/Leaflet attribution is visible and unobtrusive.

## Screenshots

- `test-results/live-stream-phase3b-main-map-real-data-1920.png`

## Findings

No blocking findings.

Implementation notes:

- Normal mode uses `StreamMapEvents.build()` and renders `.stream-map-event--*` markers.
- `demo=1` skips production fetch and keeps Phase 3-A demo pulse behavior.
- `state=calm` is the supported calm URL parameter in the existing stream app. The instruction mentioned `calm=1`, but the application and existing tests consistently use `state=calm`.
- Tide/water-level map events are effectively Phase 3-B notes: tide station coordinates are carried, but alert joining is not implemented, so only `alert=true` tide stations would render. Current adapter sets `alert: false`.
- Railway events use coarse representative points or known line fallback points, not route geometry.
- Stale policy is mixed by type:
  - earthquake/rain/kikikuru: stale events are excluded.
  - railway: stale events are displayed with `.stream-map-event--stale`.

## Notes

Scope remained inside `/live/stream` related files and E2E. No changes were detected in normal navigation files such as `frontend/index.html`, `frontend/js/navigation.js`, `frontend/js/nav-*.js`, `frontend/js/location-info-panel.js`, or reroute logic.

The 404 failure probe produces browser-level `Failed to load resource` console errors, which are expected for explicit mocked 404 responses. Application-level JS/page errors were not observed.

## Final judgement

PASS with notes.

The Phase 3-B acceptance criteria are met: `/live/stream` renders the central map, normal mode uses production API-derived events instead of demo fallback, empty/failure/invalid-coordinate cases do not break the page, map interaction remains disabled, attribution remains visible, related E2E passes, and normal `/live` has no clear regression.

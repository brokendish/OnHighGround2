# live stream Phase 5-A bundle detail and railway verification

## Result

PASS with notes

## Summary

`/live/stream` の Phase 5-A bundle 対応を検証した。対象は以下の3点。

- 地震情報 子画面 本番地図化・詳細表示同期
- 鉄道情報 子画面 詳細化
- メイン地図 鉄道路線カラー反映

検証中、ユーザー指摘の「地震情報の小画面で情報が切り替わらず固定化されているように見える」問題を再現した。原因は、実データ用 `EarthquakeStreamAdapter` が `targets` を最重要地震1件だけに絞っており、履歴には複数件出る一方で小画面の巡回対象が1件しかなかったことだった。

修正として、地震子画面用 `targets` を12時間内の地震候補複数件へ広げ、最大震度・M・発生時刻の優先順で並べた。さらに低震度の地震も自動focus候補に残すことで、地図・パネル・テロップの注目ID同期を保ったまま、詳細hold完了後に次の地震へ進むようにした。

## Checked files

- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `frontend/live/stream.html`
- `frontend/js/live-stream/live-stream-earthquake-adapter.js`
- `frontend/js/live-stream/live-stream-earthquake-detail.js`
- `frontend/js/live-stream/live-stream-focus-policy.js`
- `frontend/js/live-stream/live-stream-focus-controller.js`
- `frontend/js/live-stream/live-stream-map-view.js`
- `frontend/js/live-stream/live-stream-panels.js`
- `frontend/js/live-stream/live-stream-railway-adapter.js`
- `frontend/js/live-stream/live-stream-railway-layer.js`
- `frontend/js/live-stream/live-stream-runtime.js`
- `frontend/css/live/live-stream.css`
- `e2e/live-stream-earthquake-detail-map-sync.spec.js`
- `e2e/live-stream-earthquake-detail.spec.js`
- `e2e/live-stream-railway-detail.spec.js`
- `e2e/live-stream-railway-color-layer.spec.js`

## Environment

- Docker: frontend / backend / martin / osrm-walking running
- Frontend: `http://127.0.0.1:8080`
- E2E: Playwright Chromium, 1 worker
- Date: 2026-07-04 JST

## Commands

Static checks:

```bash
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-earthquake-detail.js
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js
node --check frontend/js/live-stream/live-stream-focus-policy.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check e2e/live-stream-earthquake-detail-map-sync.spec.js
node --check e2e/live-stream-earthquake-detail.spec.js
node --check e2e/live-stream-railway-detail.spec.js
node --check e2e/live-stream-railway-color-layer.spec.js
```

HTTP checks:

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test"
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
  e2e/live-stream-earthquake-detail.spec.js \
  e2e/live-stream-earthquake-detail-map-sync.spec.js \
  e2e/live-stream-railway-detail.spec.js \
  e2e/live-stream-railway-color-layer.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

## Test results

- Static checks: PASS
- HTTP checks: all `200 OK`
- E2E: `177 passed (4.2m)`

Additional targeted checks:

- Reproduced earthquake sub-panel fixed display before the fix with a temporary browser probe.
- Added `7b: after the mini-map/list hold is released, the earthquake panel advances to the next target`.
- The new regression test passes under normal focus-enabled mode.
- Re-ran related focus and earthquake tests: `29 passed (1.3m)`.

## Earthquake detail map verification

PASS.

Verified:

- `#eq-map` initializes as a Leaflet/CARTO map, not an SVG-only mock.
- The mini map has attribution and no zoom UI.
- Municipal intensity markers are rendered as compact markers.
- Header, municipal list, mini map, and diagnostics use the same earthquake id.
- Wide-area earthquakes hold while the municipal list / mini-map tour is running.
- After the hold is released, the earthquake panel advances to the next target.
- Empty detail does not demo fallback.
- Repeated refresh does not accumulate mini-map Leaflet instances or markers.

Fix made during verification:

- `EarthquakeStreamAdapter.build()` now exposes multiple prioritized `targets` instead of only the single active earthquake.
- `LiveStreamFocusPolicy.selectCandidates()` keeps low-severity earthquake events as focus candidates so earthquake panel cycling can stay synchronized with focus.

## Railway detail verification

PASS.

Verified:

- Focused affected railway line shows a detail overlay.
- Line name, status, operator, updated time, detail body, and source are displayed.
- Missing operator / updated time are shown as non-committal text.
- Long descriptions auto-scroll.
- Detail hold prevents switching away while the focused detail is still scrolling.
- Train API failure hides the detail overlay without pageerror or demo fallback.
- Railway detail diagnostics report active id, scroll state, and hold state.
- `/live` is unaffected.

## Railway color layer verification

PASS with notes.

Verified:

- Main map initializes the railway PMTiles layer.
- Railway card accents use the same route color table as the stream railway layer.
- Affected lines are emphasized through width/opacity rather than color replacement.
- Repeated refresh does not accumulate railway layer instances.
- Railway summary failure does not crash the center map.
- Main map remains non-interactive and keeps attribution.

Note: individual PMTiles feature colors are canvas/vector-tile rendered and cannot be counted precisely from DOM. Diagnostics therefore verify `loaded`, `layerCount`, `highlightedFeatureCount`, and `lastError`.

## Diagnostics snapshot

E2E verified `window.__LiveStreamDiagnostics.getSnapshot()` includes:

- `earthquakeDetail`: active id, detail status, intensity count, marker count, list scroll state, map tour state, frame index/count, hold state
- `railwayDetail`: active railway id, detail status, scroll state, hold state
- `railwayLayer`: loaded state, layer count, highlighted affected count, last error
- runtime / map / focus / subscriber diagnostics from Phase 5-A

## Failure / recovery checks

PASS.

Covered by E2E:

- earthquake empty detail
- all live APIs 500
- invalid JSON
- train API 500
- railway layer / summary failure
- repeated refresh
- recovery from runtime failure
- calm / demo / real modes
- normal `/live` regression

No pageerror / unhandledrejection was observed in the tested scope.

## Manual browser check

Screenshots were captured and visually inspected:

- normal: earthquake mini map is Leaflet-based, municipal marker visible, `対象 1/4` confirms multiple earthquake targets
- calm: no active disaster marker accumulation; calm state remains readable
- demo: earthquake detail mini map, municipal list, rail cards, route-colored rail map, and ticker render without layout collapse

## Screenshots

- `test-results/live-stream-phase5a-bundle-normal-1920.png`
- `test-results/live-stream-phase5a-bundle-calm-1920.png`
- `test-results/live-stream-phase5a-bundle-demo-1920.png`

## Findings

Fixed during verification:

1. Earthquake sub-panel fixed display:
   - Cause: production earthquake `targets` contained only one active earthquake.
   - Fix: provide up to 8 prioritized earthquake targets for the sub-panel while preserving the highest-priority item first.

2. Focus-enabled cycling could skip low-severity earthquake details:
   - Cause: focus policy filtered out low/info events globally.
   - Fix: keep low-severity earthquake events as focus candidates so post-hold cycling can advance while preserving id synchronization.

No remaining FAIL-level issue was found.

## Notes

- Railway detail fields are limited by the current data source. Impact section / cause are not inferred if unavailable.
- Railway PMTiles feature-level counts are not exposed by protomaps-leaflet, so diagnostics are layer-level.
- Earthquake mini-map tour remains a simple prefecture-grouped tour with an upper frame cap.
- 5-15 minute OBS soak was not run in this verification.

## Final judgement

PASS with notes

Phase 5-A bundle is ready to proceed to Phase 5-B style OBS soak, with the earthquake sub-panel fixed-display issue addressed and covered by regression testing.

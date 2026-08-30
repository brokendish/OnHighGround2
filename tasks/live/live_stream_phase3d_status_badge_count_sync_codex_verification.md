# live stream Phase 3-D status badge count sync verification

## Result

PASS with notes.

Phase 3-D の対象である「全体ステータス・カテゴリバッジ・件数表示の同期」は、実装ファイルの確認、静的構文チェック、Playwright E2E、手動ブラウザ確認の範囲で期待どおりに動作していることを確認した。

## Summary

- `LiveStreamEventStore.getSummary()` を単一の集計元として、カテゴリ別件数・カテゴリ別ステータス・全体ステータス・データ状態が算出されている。
- トップカテゴリバッジは `data-testid` と `data-stream-category` を持ち、地震・豪雨・鉄道・潮位の件数と状態が store summary から同期されている。
- 左右パネルには `data-panel` / `data-count` / `data-status` が付与され、対応カテゴリの集計結果と同期されている。
- 本番データ、デモ、calm、API 500、不正 JSON、古いイベント除外の各ケースで、地図・パネル・テロップ・バッジの表示整合性を E2E で確認した。
- `/live` 既存ページへの回帰がないことを E2E と HTTP 応答で確認した。

## Checked files

- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `tasks/stream/live_stream_phase3d_codex_verification_instruction.md`
- `frontend/live/stream.html`
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
- `frontend/css/live/live-stream.css`
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

- Date: 2026-07-03
- Repository: repository root
- Frontend URL: `http://127.0.0.1:8080/live/stream`
- Docker services confirmed running:
  - `evacuation-navi-frontend`
  - `evacuation-navi-backend`
  - `evacuation-navi-martin`
  - `evacuation-navi-osrm-walking`

## Commands

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
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
node --check e2e/live-stream-status-sync.spec.js
node --check e2e/live-stream-event-sync.spec.js
node --check e2e/live-stream-main-map-real-data.spec.js
node --check e2e/live-stream.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
npx playwright test e2e/live-stream.spec.js e2e/live-stream-main-map.spec.js e2e/live-stream-main-map-real-data.spec.js e2e/live-stream-event-sync.spec.js e2e/live-stream-status-sync.spec.js e2e/eq-mock-verify.spec.js e2e/rain-mock-verify.spec.js e2e/tide-mock-verify.spec.js e2e/rail-mock-verify.spec.js
npx playwright screenshot --wait-for-timeout=7000 http://127.0.0.1:8080/live/stream test-results/live-stream-phase3d-status-sync-1920.png
npx playwright screenshot --wait-for-timeout=5000 "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" test-results/live-stream-phase3d-calm-1920.png
npx playwright screenshot --wait-for-timeout=3000 "http://127.0.0.1:8080/live/stream?state=alert&demo=1&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00" test-results/live-stream-phase3d-demo-1920.png
```

## Test results

- HTTP checks: all target URLs returned `200 OK`.
- JavaScript syntax checks: all checked frontend and E2E files passed `node --check`.
- Playwright E2E: `109 passed (1.9m)`.

The Phase 3-D specific E2E assertions covered:

- earthquake badge count matches qualifying event count.
- rain badge count combines `rain` and `kikikuru`.
- railway badge count matches affected railway events.
- tide badge remains `0` when no `tide` / `water` event exists in the store.
- earthquake map marker count matches earthquake badge count.
- panel `data-count` / `data-status` matches `LiveStreamEventStore` summary.
- high-severity event updates overall level to `data-lv="high"` and raw status to `data-stream-overall-status="alert"`.
- successful empty data renders calm monitoring state.
- total API failure is not rendered as calm; affected counts display `-` and status `error`.
- demo mode keeps badge, panel, map, and ticker in sync.
- calm mode forces counts to `0` and removes map markers.
- stale or invalid events are excluded from badge counts.
- `/live` remains unaffected.

## Manual browser check

Manual screenshot review confirmed:

- Normal stream view: top badges showed `地震 5`, `豪雨 1`, `鉄道 0`, `潮位 0`; overall status showed `警戒レベル 高`; map markers and side panels matched the active event distribution.
- Calm view: all top badges showed `0`; overall status showed `平常・監視中`; map markers were absent and panels/ticker displayed calm monitoring content.
- Demo view: top badges showed `地震 2`, `豪雨 2`, `鉄道 4`, `潮位 2`; left/right panels, map markers, and ticker were all populated from the demo event set.

## Screenshots

- `test-results/live-stream-phase3d-status-sync-1920.png`
- `test-results/live-stream-phase3d-calm-1920.png`
- `test-results/live-stream-phase3d-demo-1920.png`

## Findings

No blocking issues found.

Notes:

- `data-lv` intentionally remains compatible with the existing visual vocabulary (`calm` / `high`). The more granular status is exposed separately through `data-stream-overall-status` and `body[data-stream-status]`.
- The top `豪雨` badge combines `rain` and `kikikuru`; the top `潮位` badge combines `tide` and `water`.
- Tide station panel display and tide/water alert event count are separate concerns. In the current implementation, the tide badge count is normally `0` unless a normalized `tide` or `water` event exists in the event store.
- Map rendering still follows the existing map event caps, while the badge counts follow the normalized active event summary. The current E2E verifies marker and badge parity for the earthquake cases covered by Phase 3-D.
- Backend code was not modified in this phase, so Python compile checks were not run.

## Notes

The working tree already contained uncommitted implementation and prior verification files when this verification started. This report does not revert or modify those unrelated existing changes.

## Final judgement

PASS with notes. The Phase 3-D implementation satisfies the requested MVP verification scope for synchronized overall status, category badges, and count displays across real, demo, calm, and failure states.

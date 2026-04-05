## Reroute Replay Cases

Field issue replay fixtures for `blockAheadAndReroute()`.

Workflow:
1. Add a new case JSON under `testdata/reroute_cases/`.
2. Add fixture JSON files under `testdata/reroute_cases/fixtures/`.
3. Run `npx playwright test e2e/block-ahead-reroute-replay.spec.js --config=playwright.config.js`.
4. Make the logic fix only after the replay test reproduces the issue.

Case files define:
- current location / destination / blocked segment
- original route geometry
- fixture file references
- expectations for replay

Fixture files provide deterministic responses for:
- OSRM alternatives
- OSRM nearest
- escape / long-detour waypoint routes
- PedestrianSafety context

The replay harness uses `window.__OHG_TEST_DEPS__` and `window._blockAheadDebugSummary`
so tests do not need to parse console logs.

## Replay vs Generated Harness

- replay spec: replays known field issues with fixed fixture responses
- generated harness: runs many synthetic invariant-based cases to detect false accepts, over-rejects, and deterministic regressions

Commands:
- `node -c frontend/js/navigation.js`
- `npx playwright test e2e/block-ahead-reroute-replay.spec.js --config=playwright.config.js`
- `node scripts/generate-reroute-matrix.mjs`
- `npx playwright test e2e/block-ahead-reroute-generated.spec.js --config=playwright.config.js`
- `node scripts/run-reroute-harness.mjs`

Generated harness artifacts:
- `artifacts/reroute_harness_summary.json`: per-case invariant results and structured summaries
- `artifacts/reroute_harness_run_summary.json`: aggregate pass/fail thresholds and recommendation
- `artifacts/reroute_snap_empty_breakdown.json`: snap-empty primary causes and mode/side/tier/depth breakdown

Operational rule:
1. add replay fixture for a new field bug
2. add or adjust generated invariant coverage if needed
3. confirm the test fails
4. fix logic
5. confirm replay + generated harness both pass

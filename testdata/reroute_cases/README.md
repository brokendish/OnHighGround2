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

## Reroute Generated Matrix

Synthetic invariant-based harness cases for `blockAheadAndReroute()`.

This layer is different from replay fixtures:
- replay = fixed field issue reproduction
- generated matrix = broad safety / consistency coverage with deterministic mocked inputs

Workflow:
1. Regenerate the matrix with `node scripts/generate-reroute-matrix.mjs`.
2. Run `npx playwright test e2e/block-ahead-reroute-generated.spec.js --config=playwright.config.js`.
3. Inspect `artifacts/reroute_harness_summary.json`.
4. If dangerous false accepts or hard reject accepts appear, treat reroute as degraded.

The generated harness is invariant-first:
- it does not require exact geometry equality
- it checks hard safety, blocked avoidance, unknown handling, and determinism

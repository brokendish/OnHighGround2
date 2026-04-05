#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const ARTIFACTS_DIR = path.join(ROOT, 'artifacts');
const SUMMARY_FILE = path.join(ARTIFACTS_DIR, 'reroute_harness_summary.json');
const RUN_SUMMARY_FILE = path.join(ARTIFACTS_DIR, 'reroute_harness_run_summary.json');
const SNAP_BREAKDOWN_FILE = path.join(ARTIFACTS_DIR, 'reroute_snap_empty_breakdown.json');
const ESCAPE_NEAREST_BREAKDOWN_FILE = path.join(ARTIFACTS_DIR, 'reroute_escape_nearest_breakdown.json');

const thresholds = {
  minGeneratedCases: Number(process.env.REROUTE_HARNESS_MIN_CASES || 100),
  minPassRate: Number(process.env.REROUTE_HARNESS_MIN_PASS_RATE || 0.95),
  maxDangerousCrossingFalseAccepts: Number(process.env.REROUTE_HARNESS_MAX_DANGEROUS_FALSE_ACCEPTS || 0),
  maxHardRejectAccepted: Number(process.env.REROUTE_HARNESS_MAX_HARD_REJECT_ACCEPTED || 0)
};

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: ROOT,
    stdio: 'inherit',
    env: process.env
  });
  return result.status ?? 1;
}

fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });

const steps = [
  { name: 'generate-matrix', command: 'node', args: ['scripts/generate-reroute-matrix.mjs'] },
  { name: 'replay-spec', command: 'npx', args: ['playwright', 'test', 'e2e/block-ahead-reroute-replay.spec.js', '--config=playwright.config.js'] },
  { name: 'generated-spec', command: 'npx', args: ['playwright', 'test', 'e2e/block-ahead-reroute-generated.spec.js', '--config=playwright.config.js'] }
];

const stepResults = [];
let failedStep = null;
for (const step of steps) {
  const code = run(step.command, step.args);
  stepResults.push({ name: step.name, code });
  if (code !== 0 && !failedStep) failedStep = step.name;
  if (code !== 0) break;
}

let generatedSummary = null;
if (fs.existsSync(SUMMARY_FILE)) {
  generatedSummary = JSON.parse(fs.readFileSync(SUMMARY_FILE, 'utf8'));
}
let snapBreakdown = null;
if (fs.existsSync(SNAP_BREAKDOWN_FILE)) {
  snapBreakdown = JSON.parse(fs.readFileSync(SNAP_BREAKDOWN_FILE, 'utf8'));
}
let escapeNearestBreakdown = null;
if (fs.existsSync(ESCAPE_NEAREST_BREAKDOWN_FILE)) {
  escapeNearestBreakdown = JSON.parse(fs.readFileSync(ESCAPE_NEAREST_BREAKDOWN_FILE, 'utf8'));
}

const passRate = Number(generatedSummary?.passRate || 0);
const totalGenerated = Number(generatedSummary?.total || 0);
const dangerousCrossingFalseAccepts = Number(generatedSummary?.dangerousCrossingFalseAccepts || 0);
const hardRejectAccepted = Number(generatedSummary?.hardRejectAccepted || 0);
const snapEmptyRate = Number(snapBreakdown?.snapEmptyRate || 0);
const escapeNearestNullAfterRetryRate = Number(escapeNearestBreakdown?.nearestNullAfterRetryRate || 0);
const escapeNearestNullAfterRetryCount = Number(escapeNearestBreakdown?.nearestNullAfterRetryCount || 0);
const allRetryPointsNullCount = Number(escapeNearestBreakdown?.detailBreakdown?.['nearest-null-after-retry:all-retry-points-null'] || 0);
const retryStrategyExhaustedCount = Object.entries(escapeNearestBreakdown?.retryStrategyExhaustedDetails || {}).reduce((sum, [, count]) => sum + Number(count || 0), 0);
const acceptedAfterRetryCount = Number(escapeNearestBreakdown?.acceptedAfterRetryCount || 0);
const unknownDetailCount = Number(escapeNearestBreakdown?.detailBreakdown?.['nearest-null-after-retry:unknown'] || 0);
const escapeAcceptedAfterRetryRate = ratio(
  Number(escapeNearestBreakdown?.acceptedAfterRetryCount || 0),
  Math.max(1, Number(escapeNearestBreakdown?.totalEscapeCandidates || 0))
);
const escapeAcceptedAfterAdjustmentRate = ratio(
  Number(escapeNearestBreakdown?.acceptedAfterAdjustmentCount || 0),
  Math.max(1, Number(escapeNearestBreakdown?.totalEscapeCandidates || 0))
);
const escapeRescueAcceptanceRate = ratio(
  Number(escapeNearestBreakdown?.acceptedAsRescueCount || 0),
  Math.max(1, Number(escapeNearestBreakdown?.totalEscapeCandidates || 0))
);
const escapeMainlineOnlyRejectRate = ratio(
  Number(escapeNearestBreakdown?.rejectedAsMainlineOnlyCount || 0),
  Math.max(1, Number(escapeNearestBreakdown?.totalEscapeCandidates || 0))
);

const modeSnapEmptyRate = Object.fromEntries(
  Object.entries(snapBreakdown?.modeRates || {}).map(([mode, value]) => [mode, Number(value?.snapEmptyRate || 0)])
);

function ratio(numerator, denominator) {
  return denominator > 0 ? numerator / denominator : 0;
}

const dominantCause = snapBreakdown?.dominantCause || 'none';
const dominantMode = snapBreakdown?.dominantMode || 'none';
const dominantSide = snapBreakdown?.dominantSide || 'none';
const sameCorridorTotal = Object.values(snapBreakdown?.modeTotals || {}).reduce((sum, stats) => (
  sum + Number(stats?.rejectSameCorridorCount || 0) + Number(stats?.rejectSameCorridorSoftCount || 0)
), 0);
const insideBlockedTotal = Object.values(snapBreakdown?.modeTotals || {}).reduce((sum, stats) => (
  sum + Number(stats?.rejectInsideBlockedAreaCount || 0) + Number(stats?.rejectInsideBlockedAreaSoftCount || 0)
), 0);
const nearestSuccessButNoUsableRouteRatio = ratio(
  Object.values(snapBreakdown?.modeTotals || {}).reduce((sum, stats) => sum + ((Number(stats?.nearestSuccessCount || 0) > 0 && Number(stats?.usableRouteCandidateCount || 0) === 0) ? 1 : 0), 0),
  Math.max(1, Object.keys(snapBreakdown?.modeTotals || {}).length)
);

const warnings = [];
if (snapEmptyRate > 0.20) warnings.push('overall-snap-empty-rate');
if (Number(modeSnapEmptyRate['escape-leg'] || 0) > 0.30) warnings.push('escape-leg-snap-empty-rate');
if (dominantCause === 'same-corridor' || ratio(sameCorridorTotal, Math.max(1, sameCorridorTotal + insideBlockedTotal)) > 0.60) warnings.push('same-corridor-dominated');
if (dominantCause === 'inside-blocked-area' || ratio(insideBlockedTotal, Math.max(1, sameCorridorTotal + insideBlockedTotal)) > 0.60) warnings.push('inside-blocked-area-dominated');

function buildRecommendation(cause) {
  if (cause === 'same-corridor') return 'candidate-generation-or-same-corridor-tuning';
  if (cause === 'inside-blocked-area') return 'blocked-area-gating-tuning';
  if (cause === 'nearest-null' || cause === 'nearest-null-after-retry') return 'nearest-snap-reliability';
  if (cause === 'node-build-failure' || cause === 'no-usable-node') return 'node-selection-or-routeability-tuning';
  if (cause === 'too-far-from-candidate') return 'snap-distance-threshold-tuning';
  return 'continue-diagnostics';
}

function buildEscapeRecommendation() {
  const details = escapeNearestBreakdown?.detailBreakdown || {};
  const topDetail = Object.entries(details).sort((a, b) => b[1] - a[1])[0]?.[0] || 'none';
  if (unknownDetailCount > 0) return 'detail-classification-followup';
  if (topDetail.includes('retry-no-strategy-enabled')) return 'pruning-too-aggressive';
  if (topDetail.includes('node-build-failure')) return 'node-build-reliability';
  if (topDetail.includes('rejected-no-side-road') || topDetail.includes('mainline-only')) return 'mainline-only-filter-review';
  if (Number(escapeNearestBreakdown?.detailBreakdown?.['nearest-null-after-retry:all-retry-points-null'] || 0) <= 20
    && escapeAcceptedAfterRetryRate >= 0.06) return 'retry-order-tuning-effective';
  if (escapeAcceptedAfterRetryRate >= 0.06) return 'continue-priority-pruning';
  if (escapeAcceptedAfterAdjustmentRate > escapeAcceptedAfterRetryRate) return 'candidate-adjustment-tuning';
  if (topDetail !== 'none') return 'retry-order-tuning';
  if (passRate < 0.80) return 'consider-disable-reroute';
  return 'retry-order-tuning';
}

function topEntry(map, fallback = 'none') {
  return Object.entries(map || {}).sort((a, b) => b[1] - a[1])[0]?.[0] || fallback;
}

function mostWastefulStrategy(strategyStats = {}) {
  const entries = Object.entries(strategyStats || {}).map(([strategy, stats]) => {
    const executed = Number(stats?.executed || 0);
    const success = Number(stats?.success || 0);
    const nearestReturned = Number(stats?.nearestReturned || 0);
    return { strategy, executed, success, nearestReturned, waste: executed - success };
  }).filter(entry => entry.executed > 0);
  entries.sort((a, b) => (b.waste - a.waste) || (b.executed - a.executed));
  return entries[0]?.strategy || 'none';
}

const thresholdFailures = [];
if (totalGenerated < thresholds.minGeneratedCases) thresholdFailures.push(`generated-cases<${thresholds.minGeneratedCases}`);
if (dangerousCrossingFalseAccepts > thresholds.maxDangerousCrossingFalseAccepts) thresholdFailures.push('dangerous-crossing-false-accept');
if (hardRejectAccepted > thresholds.maxHardRejectAccepted) thresholdFailures.push('hard-reject-accepted');
if (passRate < thresholds.minPassRate) thresholdFailures.push(`pass-rate<${thresholds.minPassRate}`);

const runSummary = {
  steps: stepResults,
  failedStep,
  thresholds,
  generatedSummary,
  snapBreakdown,
  escapeNearestBreakdown,
  snapEmptyRate,
  modeSnapEmptyRate,
  dominantCause,
  dominantMode,
  dominantSide,
  escapeStrategyOrder: escapeNearestBreakdown?.strategyOrderUsed || [],
  escapePrunedStrategies: escapeNearestBreakdown?.prunedStrategies || [],
  escapeMostEffectiveStrategy: topEntry(escapeNearestBreakdown?.acceptedAfterRetryByStrategy),
  escapeMostWastefulStrategy: mostWastefulStrategy(escapeNearestBreakdown?.strategyStats),
  escapeUnknownDetailCount: unknownDetailCount,
  retryStrategyExhaustedCount,
  escapeNearestNullAfterRetryRate,
  escapeNearestNullAfterRetryCount,
  allRetryPointsNullCount,
  acceptedAfterRetryCount,
  escapeAcceptedAfterRetryRate,
  escapeAcceptedAfterAdjustmentRate,
  escapeRescueAcceptanceRate,
  escapeMainlineOnlyRejectRate,
  escapeDominantFailureCombo: escapeNearestBreakdown?.dominantFailureCombo || 'none',
  nearestSuccessButNoUsableRouteRatio,
  warnings,
  recommendation: buildRecommendation(dominantCause),
  escapeRecommendation: buildEscapeRecommendation(),
  thresholdFailures,
  exitCode: failedStep || thresholdFailures.length > 0 ? 1 : 0
};

fs.writeFileSync(RUN_SUMMARY_FILE, JSON.stringify(runSummary, null, 2));

console.log(`[RerouteHarnessRunner] steps=${JSON.stringify(stepResults)}`);
if (generatedSummary) {
  console.log(
    `[RerouteHarnessRunner] total=${generatedSummary.total} passed=${generatedSummary.passed} ` +
    `failed=${generatedSummary.failed} passRate=${passRate.toFixed(3)} ` +
    `dangerousFalseAccepts=${dangerousCrossingFalseAccepts} hardRejectAccepted=${hardRejectAccepted}`
  );
}
if (snapBreakdown) {
  console.log(
    `[RerouteHarnessRunner] snapEmptyRate=${snapEmptyRate.toFixed(3)} dominantCause=${dominantCause} ` +
    `dominantMode=${dominantMode} dominantSide=${dominantSide} recommendation=${runSummary.recommendation}`
  );
}
if (escapeNearestBreakdown) {
  console.log(
    `[RerouteHarnessRunner] escapeNearestNullAfterRetryRate=${escapeNearestNullAfterRetryRate.toFixed(3)} ` +
    `nearestNullAfterRetryCount=${escapeNearestNullAfterRetryCount} retryStrategyExhaustedCount=${retryStrategyExhaustedCount} allRetryPointsNullCount=${allRetryPointsNullCount} ` +
    `acceptedAfterRetryCount=${acceptedAfterRetryCount} unknownDetailCount=${unknownDetailCount} ` +
    `escapeAcceptedAfterRetryRate=${escapeAcceptedAfterRetryRate.toFixed(3)} ` +
    `escapeAcceptedAfterAdjustmentRate=${escapeAcceptedAfterAdjustmentRate.toFixed(3)} ` +
    `escapeRescueAcceptanceRate=${escapeRescueAcceptanceRate.toFixed(3)} ` +
    `escapeMainlineOnlyRejectRate=${escapeMainlineOnlyRejectRate.toFixed(3)}`
  );
  console.log(
    `[RerouteHarnessRunner] escapeStrategyOrder=${JSON.stringify(runSummary.escapeStrategyOrder)} ` +
    `escapePrunedStrategies=${JSON.stringify(runSummary.escapePrunedStrategies)} ` +
    `escapeMostEffectiveStrategy=${runSummary.escapeMostEffectiveStrategy} ` +
    `escapeMostWastefulStrategy=${runSummary.escapeMostWastefulStrategy} ` +
    `escapeUnknownDetailCount=${runSummary.escapeUnknownDetailCount}`
  );
  console.log(
    `[RerouteHarnessRunner] escapeDominantFailureCombo=${runSummary.escapeDominantFailureCombo} ` +
    `escapeRecommendation=${runSummary.escapeRecommendation}`
  );
}
if (thresholdFailures.length > 0) {
  console.log(`[RerouteHarnessRunner] thresholdFailures=${thresholdFailures.join(',')}`);
}

process.exit(runSummary.exitCode);

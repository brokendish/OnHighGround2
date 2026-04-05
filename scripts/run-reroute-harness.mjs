#!/usr/bin/env node

import fs from 'fs';
import path from 'path';
import { spawnSync } from 'child_process';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const ARTIFACTS_DIR = path.join(ROOT, 'artifacts');
const SUMMARY_FILE = path.join(ARTIFACTS_DIR, 'reroute_harness_summary.json');
const RUN_SUMMARY_FILE = path.join(ARTIFACTS_DIR, 'reroute_harness_run_summary.json');
const SNAP_BREAKDOWN_FILE = path.join(ARTIFACTS_DIR, 'reroute_snap_empty_breakdown.json');

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

const passRate = Number(generatedSummary?.passRate || 0);
const totalGenerated = Number(generatedSummary?.total || 0);
const dangerousCrossingFalseAccepts = Number(generatedSummary?.dangerousCrossingFalseAccepts || 0);
const hardRejectAccepted = Number(generatedSummary?.hardRejectAccepted || 0);
const snapEmptyRate = Number(snapBreakdown?.snapEmptyRate || 0);

const modeSnapEmptyRate = Object.fromEntries(
  Object.entries(snapBreakdown?.modeRates || {}).map(([mode, value]) => [mode, Number(value?.snapEmptyRate || 0)])
);

function ratio(numerator, denominator) {
  return denominator > 0 ? numerator / denominator : 0;
}

const dominantCause = snapBreakdown?.dominantCause || 'none';
const dominantMode = snapBreakdown?.dominantMode || 'none';
const dominantSide = snapBreakdown?.dominantSide || 'none';
const sameCorridorTotal = Object.values(snapBreakdown?.modeTotals || {}).reduce((sum, stats) => sum + Number(stats?.rejectSameCorridorCount || 0), 0);
const insideBlockedTotal = Object.values(snapBreakdown?.modeTotals || {}).reduce((sum, stats) => sum + Number(stats?.rejectInsideBlockedAreaCount || 0), 0);
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
  if (cause === 'nearest-null') return 'nearest-snap-reliability';
  if (cause === 'node-build-failure' || cause === 'no-usable-node') return 'node-selection-or-routeability-tuning';
  if (cause === 'too-far-from-candidate') return 'snap-distance-threshold-tuning';
  return 'continue-diagnostics';
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
  snapEmptyRate,
  modeSnapEmptyRate,
  dominantCause,
  dominantMode,
  dominantSide,
  nearestSuccessButNoUsableRouteRatio,
  warnings,
  recommendation: buildRecommendation(dominantCause),
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
if (thresholdFailures.length > 0) {
  console.log(`[RerouteHarnessRunner] thresholdFailures=${thresholdFailures.join(',')}`);
}

process.exit(runSummary.exitCode);

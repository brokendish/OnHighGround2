'use strict';

const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const MATRIX_FILE = path.join(__dirname, '..', 'testdata', 'reroute_matrix', 'generated_matrix.json');
const ARTIFACTS_DIR = path.join(__dirname, '..', 'artifacts');
const SUMMARY_FILE = path.join(ARTIFACTS_DIR, 'reroute_harness_summary.json');
const SNAP_BREAKDOWN_FILE = path.join(ARTIFACTS_DIR, 'reroute_snap_empty_breakdown.json');
const ESCAPE_NEAREST_BREAKDOWN_FILE = path.join(ARTIFACTS_DIR, 'reroute_escape_nearest_breakdown.json');
const HARNESS_FAILURE_PREFIX = 'HARNESS_';

const HARD_BLOCK_REASONS = new Set([
  'slit-line-cross',
  'core-intersection',
  'overlap-hard',
  'slit-body-hard'
]);

function coordsKey(coords) {
  return (Array.isArray(coords) ? coords : [])
    .map(p => `${Number(p.lat).toFixed(6)},${Number(p.lng ?? p.lon).toFixed(6)}`)
    .join('|');
}

function loadMatrixCases() {
  const payload = JSON.parse(fs.readFileSync(MATRIX_FILE, 'utf8'));
  return Array.isArray(payload?.cases) ? payload.cases : [];
}

async function bootstrap(page) {
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.goto('/');
  await page.waitForFunction(() => typeof blockAheadAndReroute === 'function' && typeof map !== 'undefined');
}

async function seedNav(page, caseData) {
  const baseRoute = caseData.routeGeometry.map(([lng, lat]) => ({ lat, lng }));
  await page.evaluate(({ baseRoute, currentLoc, destination }) => {
    window.__voiceCalls = [];
    voiceNav.enabled = false;
    currentLocation = {
      lat: currentLoc.lat,
      lon: currentLoc.lng,
      accuracyMeters: 5
    };
    navDestination = {
      lat: destination.lat,
      lon: destination.lng,
      name: 'Generated Fixture Destination'
    };
    navActiveRoute = {
      coordinates: baseRoute,
      summary: { totalDistance: 500, totalTime: 360 }
    };
    routeCandidateLayers.length = 0;
    _blockAheadLastTiming = null;
    _blockAheadDebugSummary = null;
    _blockAheadRecentSummaries = [];
    _blockAheadAggregateMetrics = {
      totalRuns: 0,
      acceptedRuns: 0,
      failedRuns: 0,
      noChangeRuns: 0,
      statusCounts: {},
      rejectReasonCounts: {},
      avgTotalMs: 0,
      avgOsrmMs: 0,
      avgDisplayPipelineMs: 0
    };
    if (_pedestrianSafetyContextCache?.clear) _pedestrianSafetyContextCache.clear();
    setNavMode('navigation_active');
    _updateRemainingDistanceDisplay(currentLocation.lat, currentLocation.lon, currentLocation.accuracyMeters);
  }, {
    baseRoute,
    currentLoc: caseData.currentLocation,
    destination: caseData.destination
  });
}

async function installMatrixDeps(page, caseData) {
  await page.evaluate(({ mockData }) => {
    const clone = (value) => value == null ? value : JSON.parse(JSON.stringify(value));
    const normalizePedestrianContext = (value) => {
      if (value && typeof value === 'object' && typeof value.status === 'string' && Object.prototype.hasOwnProperty.call(value, 'context')) {
        return clone(value);
      }
      const context = value && typeof value === 'object' ? value : { roads: [], crosswalks: [] };
      return {
        status: 'ready',
        context: {
          roads: Array.isArray(context.roads) ? context.roads : [],
          crosswalks: Array.isArray(context.crosswalks) ? context.crosswalks : []
        },
        source: 'generated-matrix',
        bbox: null,
        fetchedAt: Date.now(),
        failure: {
          kind: 'none',
          detail: 'none',
          message: '',
          aborted: false
        }
      };
    };
    const keyForCoords = (coords) => (Array.isArray(coords) ? coords : [])
      .map(p => `${Number(p.lat).toFixed(6)},${Number((p.lng ?? p.lon)).toFixed(6)}`)
      .join('|');
    const byStage = mockData.osrmAlternatives || {};
    const routesByContext = mockData.osrmRoutesByContext || {};
    const nearest = mockData.osrmNearest || {};
    const pedByLabel = mockData.pedestrianSafetyByLabel || {};
    const conservativeByLabel = mockData.conservativeByLabel || {};
    const blockedStatsByRoute = mockData.routeBlockedAreaStats || {};
    const overlapByRoute = mockData.blockOverlapRatios || {};
    const defaultBlockedStats = mockData.defaultRouteBlockedAreaStats || null;

    window.__OHG_TEST_DEPS__ = {
      fetchOsrmAlternatives: async (_from, _to, _maxAlts, contextLabel) => clone(byStage[contextLabel] || []),
      fetchOsrmNearest: async (_point, contextLabel) => clone(nearest[contextLabel] || null),
      fetchOsrmRoute: async (_waypoints, contextLabel) => clone(routesByContext[contextLabel] || null),
      fetchPedestrianSafetyContext: async () => normalizePedestrianContext(mockData.pedestrianContext),
      generateEscapeLegPoints: async () => clone(mockData.escapeLegPoints || []),
      generateEscapePoints: async () => clone(mockData.escapePoints || []),
      generateLongDetourEscapePoints: async () => clone(mockData.longDetourPoints || []),
      routeBlockedAreaStats: (coords) => clone(blockedStatsByRoute[keyForCoords(coords)] || defaultBlockedStats || null),
      blockOverlapRatio: (coords) => overlapByRoute[keyForCoords(coords)],
      evaluatePedestrianRouteSafety: async (_route, _ctx, contextLabel) => clone(pedByLabel[contextLabel] || null),
      evaluateConservativeUnknownPedestrianSafety: (_route, options = {}) => clone(
        conservativeByLabel[options.label]
        || conservativeByLabel[options.phase]
        || conservativeByLabel[options.mode]
        || null
      )
    };
  }, { mockData: caseData.mockData });
}

async function runSingle(page, caseData) {
  await seedNav(page, caseData);
  await installMatrixDeps(page, caseData);
  await page.evaluate(({ blockedSegment }) => {
    _buildBlockedArea = ((original) => (coords, projection, options = {}) => {
      const built = original(coords, projection, options);
      if (!built) return built;
      built.startPoint = blockedSegment.start;
      built.endPoint = blockedSegment.end;
      return built;
    })(_buildBlockedArea);
  }, { blockedSegment: caseData.blockedSegment });

  await page.evaluate(() => blockAheadAndReroute());
  const result = await page.evaluate(() => ({
    summary: window._blockAheadDebugSummary || _blockAheadDebugSummary || _blockAheadLastTiming?.debugSummary || null,
    timing: window._blockAheadLastTiming || null,
    routeDebug: navActiveRoute?.__debugSummary || null
  }));
  return result.summary || result.routeDebug || null;
}

function normalizeSummaryForDeterminism(summary) {
  return {
    success: !!summary?.success,
    status: summary?.status || 'unknown',
    selectedStage: summary?.selectedStage || null,
    selectedNodeId: summary?.selectedNodeId || null,
    selectedDistance: Math.round(Number(summary?.selectedDistance || 0)),
    pedestrianStatus: summary?.pedestrianSafety?.status || 'unknown',
    conservativeDecision: summary?.pedestrianSafety?.conservativeDecision || 'pass',
    conservativeReason: summary?.pedestrianSafety?.conservativeReason || 'none',
    conservativePenalty: Math.round(Number(summary?.pedestrianSafety?.conservativePenalty || 0)),
    blockedRejectReason: summary?.blockedAreaStats?.rejectReason || 'accepted',
    overlap: Number(Number(summary?.blockedAreaStats?.overlap || 0).toFixed(3)),
    strict: Number(Number(summary?.blockedAreaStats?.strict || 0).toFixed(3)),
    near: Number(Number(summary?.blockedAreaStats?.near || 0).toFixed(3))
  };
}

function judgeInvariants(caseData, summary, runs) {
  const invariantResults = {};
  const failedInvariantIds = [];
  const check = (id, condition) => {
    invariantResults[id] = !!condition;
    if (!condition) failedInvariantIds.push(id);
  };

  const ped = summary?.pedestrianSafety || {};
  const candidatePed = summary?.candidatePedestrianSafety || {};
  const blocked = summary?.blockedAreaStats || {};
  const expectations = caseData.expectations || {};
  const modeStats = summary?.modeStats || {};
  const expectedMode = expectations.expectedSnapMode || summary?.snapEmptyFailureMode || (summary?.selectedStage && modeStats[summary.selectedStage] ? summary.selectedStage : null);

  check('I01_expected_find_route', expectations.mustFindRoute === undefined || !!summary?.success === !!expectations.mustFindRoute);
  check('I02_unsafe_not_accepted', !(summary?.success && ped.status === 'unsafe'));
  check('I03_final_hard_reject_not_accepted', !(summary?.success && ped.conservativeDecision === 'hard-reject'));
  check('I04_dangerous_crossing_expectation', !expectations.mustAvoidDangerousCrossing || !summary?.success || ped.status !== 'unsafe');
  check('I05_hard_intersection_not_accepted', !(summary?.success && !!blocked.hardIntersectionDetected));
  check('I06_hard_block_reason_not_accepted', !(summary?.success && HARD_BLOCK_REASONS.has(blocked.rejectReason)));
  check('I07_avoid_blocked_area', !expectations.mustAvoidBlockedArea || !summary?.success || Number(blocked.overlap || 0) < 0.7);
  check('I08_expectations_view_matches', !expectations.mustAvoidBlockedArea || !summary?.success || summary?.expectationsView?.avoidsBlockedArea === true);
  check('I09_deterministic', runs.length <= 1 || runs.every(run => JSON.stringify(normalizeSummaryForDeterminism(run)) === JSON.stringify(normalizeSummaryForDeterminism(runs[0]))));
  check('I10_failure_has_reasons', summary?.success || Object.keys(summary?.rejectReasonsSummary || {}).length > 0);
  check('I11_success_has_required_summary', !summary?.success || (!!summary?.selectedStage && !!summary?.pedestrianSafety && !!summary?.blockedAreaStats));
  check('I12_unknown_hard_reject_not_accepted', !(summary?.success && ped.status === 'unknown' && ped.conservativeDecision === 'hard-reject'));
  check('I13_unknown_soft_risk_penalty_present', !(summary?.success && ped.status === 'unknown' && ped.conservativeDecision === 'soft-risk') || Number(ped.conservativePenalty || 0) > 0);
  check('I14_candidate_final_consistency', !(summary?.success && ['pass', 'soft-risk'].includes(candidatePed.conservativeDecision) && ped.conservativeDecision === 'hard-reject'));
  check('I15_snap_diagnostics_present', !!summary?.snapDiagnostics && !!summary?.modeStats && !!summary?.sideStats && !!summary?.tierStats && !!summary?.depthStats);
  check('I17_retry_stats_present', typeof summary?.snapDiagnostics?.retryStats === 'object');
  check('I18_same_corridor_stats_present', typeof summary?.snapDiagnostics?.sameCorridorStats === 'object');
  check('I19_inside_blocked_stats_present', typeof summary?.snapDiagnostics?.insideBlockedStats === 'object');
  check('I20_escape_retry_stats_present', typeof summary?.snapDiagnostics?.escapeRetryStats === 'object');
  check('I21_escape_adjustment_stats_present', typeof summary?.snapDiagnostics?.escapeCandidateAdjustmentStats === 'object');
  check('I22_escape_nearest_breakdown_present', typeof summary?.snapDiagnostics?.escapeNearestBreakdown === 'object');

  if (expectedMode && modeStats[expectedMode]) {
    const stats = modeStats[expectedMode];
    check(
      'I16_snap_count_chain',
      Number(stats.rawCandidateCount || 0) >= Number(stats.nearestAttemptCount || 0)
      && Number(stats.nearestAttemptCount || 0) >= Number(stats.nearestSuccessCount || 0)
      && Number(stats.nearestSuccessCount || 0) >= Number(stats.usableSnappedCount || 0)
      && Number(stats.usableSnappedCount || 0) >= Number(stats.usableRouteCandidateCount || 0)
    );
  }

  if (Array.isArray(expectations.allowedSelectedStages) && summary?.success) {
    check('E01_selected_stage_allowed', expectations.allowedSelectedStages.includes(summary.selectedStage));
  }
  if (expectations.mustAllowSoftRisk) {
    check('E02_soft_risk_survives', ped.conservativeDecision === 'soft-risk');
  }
  if (expectations.expectedConservativeDecision) {
    check('E03_expected_conservative_decision', ped.conservativeDecision === expectations.expectedConservativeDecision);
  }
  if (expectations.expectedDangerousReject) {
    check('E04_expected_dangerous_reject', !summary?.success && Object.keys(summary?.rejectReasonsSummary || {}).some(reason => reason.includes('dangerous-crossing')));
  }
  if (expectations.expectedHardBlockedReason) {
    check('E05_expected_hard_block_reason', !summary?.success);
  }
  if (expectations.expectedSnapEmptyPrimaryReason) {
    const primaryReasonSource = expectedMode
      ? summary?.snapDiagnostics?.modePrimaryReasons?.[expectedMode]
        || summary?.snapDiagnostics?.escapeModePrimaryReasons?.[expectedMode]
        || summary?.snapEmptyPrimaryReason
      : summary?.snapEmptyPrimaryReason;
    check('E06_expected_snap_primary_reason', primaryReasonSource === expectations.expectedSnapEmptyPrimaryReason);
  }
  if (expectations.expectedDetailReasonRecorded) {
    check(
      'E07_expected_detail_reason_recorded',
      Object.keys(summary?.rejectReasonsSummary || {}).includes(expectations.expectedDetailReasonRecorded)
    );
  }
  if (expectations.expectedModeStats && expectedMode && modeStats[expectedMode]) {
    const stats = modeStats[expectedMode];
    check(
      'E08_expected_mode_stats_subset',
      Object.entries(expectations.expectedModeStats).every(([key, value]) => Number(stats?.[key] || 0) === Number(value))
    );
  }
  if (expectations.expectedRetryStats) {
    const retrySource = expectedMode && modeStats[expectedMode] ? modeStats[expectedMode] : (summary?.snapDiagnostics?.retryStats || {});
    check(
      'E09_expected_retry_stats',
      Object.entries(expectations.expectedRetryStats).every(([key, value]) => Number(retrySource?.[key] || 0) === Number(value))
    );
  }
  if (expectations.expectedSameCorridorStats) {
    const sameSource = expectedMode && modeStats[expectedMode]
      ? {
          hard: Number(modeStats[expectedMode]?.sameCorridorHardCount || 0),
          soft: Number(modeStats[expectedMode]?.sameCorridorSoftCount || 0),
          pass: Number(modeStats[expectedMode]?.sameCorridorPassCount || 0)
        }
      : (summary?.snapDiagnostics?.sameCorridorStats || {});
    check(
      'E10_expected_same_corridor_stats',
      Object.entries(expectations.expectedSameCorridorStats).every(([key, value]) => Number(sameSource?.[key] || 0) === Number(value))
    );
  }
  if (expectations.expectedInsideBlockedStats) {
    const insideSource = expectedMode && modeStats[expectedMode]
      ? {
          hard: Number(modeStats[expectedMode]?.insideBlockedHardCount || 0),
          soft: Number(modeStats[expectedMode]?.insideBlockedSoftCount || 0),
          pass: Number(modeStats[expectedMode]?.insideBlockedPassCount || 0)
        }
      : (summary?.snapDiagnostics?.insideBlockedStats || {});
    check(
      'E11_expected_inside_blocked_stats',
      Object.entries(expectations.expectedInsideBlockedStats).every(([key, value]) => Number(insideSource?.[key] || 0) === Number(value))
    );
  }
  if (expectations.expectedEscapeAdjustmentStats) {
    check(
      'E12_expected_escape_adjustment_stats',
      Object.entries(expectations.expectedEscapeAdjustmentStats).every(([key, value]) => Number(summary?.snapDiagnostics?.escapeCandidateAdjustmentStats?.[key] || 0) === Number(value))
    );
  }
  if (expectations.expectedEscapeRetrySuccessByStrategy) {
    check(
      'E13_expected_escape_retry_strategy',
      Object.entries(expectations.expectedEscapeRetrySuccessByStrategy).every(([key, value]) => Number(summary?.snapDiagnostics?.escapeRetrySuccessByStrategy?.[key] || 0) === Number(value))
    );
  }
  if (expectations.expectedEscapeNearestDetail) {
    check(
      'E14_expected_escape_nearest_detail',
      Object.entries(expectations.expectedEscapeNearestDetail).every(([key, value]) => Number(summary?.snapDiagnostics?.escapeNearestBreakdown?.nearestNullAfterRetryDetails?.[key] || 0) === Number(value))
    );
  }
  if (expectations.expectedEscapeStrategyStats) {
    check(
      'E15_expected_escape_strategy_stats',
      Object.entries(expectations.expectedEscapeStrategyStats).every(([strategy, expected]) => (
        Object.entries(expected || {}).every(([key, value]) => Number(summary?.snapDiagnostics?.escapeNearestBreakdown?.strategyStats?.[strategy]?.[key] || 0) === Number(value))
      ))
    );
  }
  if (expectations.expectedEscapeAcceptanceCounts) {
    check(
      'E16_expected_escape_acceptance_counts',
      Object.entries(expectations.expectedEscapeAcceptanceCounts).every(([key, value]) => Number(summary?.snapDiagnostics?.escapeNearestBreakdown?.[key] || 0) === Number(value))
    );
  }
  if (expectations.expectedEscapeStrategyOrderUsed) {
    check(
      'E17_expected_escape_strategy_order',
      JSON.stringify(summary?.snapDiagnostics?.escapeNearestBreakdown?.strategyOrderUsed || [])
      === JSON.stringify(expectations.expectedEscapeStrategyOrderUsed)
    );
  }
  if (expectations.expectedEscapePrunedStrategies) {
    check(
      'E18_expected_escape_pruned_strategies',
      JSON.stringify(summary?.snapDiagnostics?.escapeNearestBreakdown?.prunedStrategies || [])
      === JSON.stringify(expectations.expectedEscapePrunedStrategies)
    );
  }
  if (expectations.expectedEscapeUnknownDetailCount !== undefined) {
    check(
      'E19_expected_escape_unknown_detail_count',
      Number(summary?.snapDiagnostics?.escapeNearestBreakdown?.nearestNullAfterRetryDetails?.['nearest-null-after-retry:unknown'] || 0)
      === Number(expectations.expectedEscapeUnknownDetailCount)
    );
  }

  summary.invariantResults = invariantResults;
  summary.failedInvariantIds = failedInvariantIds;
  return { invariantResults, failedInvariantIds };
}

function buildHarnessFailureSummary(caseData, error) {
  return {
    success: false,
    status: 'harness-error',
    selectedStage: null,
    selectedNodeId: null,
    selectedDistance: 0,
    pedestrianSafety: {
      status: 'unknown',
      contextUnavailable: true,
      contextSource: 'harness',
      contextFailureKind: 'harness-error',
      contextFailureDetail: String(error?.message || error || 'unknown-error'),
      failOpenApplied: false,
      conservativeDecision: 'pass',
      conservativeReason: 'none',
      conservativePenalty: 0
    },
    candidatePedestrianSafety: {
      status: 'unknown',
      contextUnavailable: true,
      contextSource: 'harness',
      contextFailureKind: 'harness-error',
      contextFailureDetail: String(error?.message || error || 'unknown-error'),
      failOpenApplied: false,
      conservativeDecision: 'pass',
      conservativeReason: 'none',
      conservativePenalty: 0
    },
    blockedAreaStats: {
      overlap: 0,
      strict: 0,
      near: 0,
      hardIntersectionDetected: false,
      rejectReason: 'harness-error',
      mode: null,
      side: null,
      nearPenaltyMode: false,
      acceptedByNearPenaltyMode: false
    },
    expectationsView: {
      avoidsBlockedArea: false,
      dangerousCrossingRejected: false,
      finalConservativeHardReject: false
    },
    invariantResults: {},
    failedInvariantIds: [`${HARNESS_FAILURE_PREFIX}execution_error`],
    candidateCountByStage: {},
    acceptedCountByStage: {},
    rejectReasonsSummary: {
      'harness-error': 1
    },
    allAcceptedCandidates: [],
    snapDiagnostics: {
      events: [],
      modeStats: {},
      sideStats: {},
      tierStats: {},
      depthStats: {},
      retryStats: { nearestRetryCount: 0, nearestRetrySucceeded: 0, nearestRetryFailed: 0 },
      escapeRetryStats: { nearestRetryCount: 0, nearestRetrySucceeded: 0, nearestRetryFailed: 0 },
      escapeRetrySuccessByStrategy: {},
      escapeRetryFailureByStrategy: {},
      escapeCandidateAdjustmentStats: {},
      escapeNearestNullReasons: {},
      escapeNearestAcceptedAfterAdjustment: 0,
      escapeNearestAcceptedAfterRetry: 0,
      escapeNearestDetailBreakdown: {},
      escapeStrategyStats: {},
      escapeNearestBreakdown: {
        totalCandidates: 0,
        nearestNullAfterRetryCount: 0,
        nearestNullAfterRetryDetails: {},
        strategyStats: {},
        sideStats: {},
        tierStats: {},
        depthStats: {},
        positionCategoryStats: {},
        bearingBucketStats: {},
        corridorLengthBucketStats: {},
        snapDistanceBucketStats: {},
        acceptedAfterRetryCount: 0,
        acceptedAfterAdjustmentCount: 0,
        acceptedAsRescueCount: 0,
        rejectedAsMainlineOnlyCount: 0,
        rejectedAsDuplicateOnlyCount: 0,
        rejectedAsInvalidBearingCount: 0,
        topFailureCombos: []
      },
      sameCorridorStats: { hard: 0, soft: 0, pass: 0 },
      insideBlockedStats: { hard: 0, soft: 0, pass: 0 },
      modePrimaryReasons: {},
      escapeModePrimaryReasons: {}
    },
    modeStats: {},
    sideStats: {},
    tierStats: {},
    depthStats: {},
    snapEmptyPrimaryReason: 'none',
    snapEmptyReasonBreakdown: {},
    snapEmptyFailureMode: null,
    harnessError: {
      caseId: caseData.caseId,
      message: String(error?.message || error || 'unknown-error')
    }
  };
}

function createSnapCounterBucket() {
  return {
    rawCandidateCount: 0,
    nearestAttemptCount: 0,
    nearestSuccessCount: 0,
    nearestNullCount: 0,
    nearestRetryCount: 0,
    nearestRetrySucceeded: 0,
    nearestRetryFailed: 0,
    rejectSameCorridorCount: 0,
    rejectInsideBlockedAreaCount: 0,
    rejectTooFarFromCandidateCount: 0,
    rejectLowCorridorScoreCount: 0,
    rejectDuplicateSnapCount: 0,
    rejectInvalidBearingCount: 0,
    rejectNodeBuildFailureCount: 0,
    rejectSameCorridorSoftCount: 0,
    rejectInsideBlockedAreaSoftCount: 0,
    sameCorridorHardCount: 0,
    sameCorridorSoftCount: 0,
    sameCorridorPassCount: 0,
    insideBlockedHardCount: 0,
    insideBlockedSoftCount: 0,
    insideBlockedPassCount: 0,
    usableSnappedCount: 0,
    usableRouteCandidateCount: 0
  };
}

function mergeSnapBuckets(target, source) {
  const out = target || createSnapCounterBucket();
  Object.keys(out).forEach(key => {
    out[key] += Number(source?.[key] || 0);
  });
  return out;
}

function accumulateSnapBuckets(targetMap, sourceMap) {
  Object.entries(sourceMap || {}).forEach(([key, value]) => {
    targetMap[key] = mergeSnapBuckets(targetMap[key] || createSnapCounterBucket(), value || {});
  });
}

function buildSnapEmptyBreakdown(results) {
  const snapEmptyCases = results.filter(result => String(result.summary?.snapEmptyPrimaryReason || 'none') !== 'none');
  const primaryReasonCounts = {};
  const modeTotals = {};
  const sideTotals = {};
  const tierTotals = {};
  const depthTotals = {};
  const modeSnapEmptyCases = {};
  const sidePrimaryReasonCounts = {};

  results.forEach(result => {
    accumulateSnapBuckets(modeTotals, result.summary?.modeStats || {});
    accumulateSnapBuckets(sideTotals, result.summary?.sideStats || {});
    accumulateSnapBuckets(tierTotals, result.summary?.tierStats || {});
    accumulateSnapBuckets(depthTotals, result.summary?.depthStats || {});
    const failureMode = result.summary?.snapEmptyFailureMode || null;
    const primaryReason = result.summary?.snapEmptyPrimaryReason || 'none';
    if (primaryReason !== 'none') {
      primaryReasonCounts[primaryReason] = (primaryReasonCounts[primaryReason] || 0) + 1;
      if (failureMode) modeSnapEmptyCases[failureMode] = (modeSnapEmptyCases[failureMode] || 0) + 1;
      const sideStats = result.summary?.sideStats || {};
      Object.entries(sideStats).forEach(([side, stats]) => {
        if (Number(stats.rawCandidateCount || 0) <= 0) return;
        if (!sidePrimaryReasonCounts[side]) sidePrimaryReasonCounts[side] = {};
        sidePrimaryReasonCounts[side][primaryReason] = (sidePrimaryReasonCounts[side][primaryReason] || 0) + 1;
      });
    }
  });

  const modeCaseTotals = {};
  results.forEach(result => {
    Object.entries(result.summary?.modeStats || {}).forEach(([mode, stats]) => {
      if (Number(stats.rawCandidateCount || 0) <= 0 && Number(stats.nearestAttemptCount || 0) <= 0) return;
      modeCaseTotals[mode] = (modeCaseTotals[mode] || 0) + 1;
    });
  });

  const modeRates = Object.fromEntries(
    Object.entries(modeCaseTotals).map(([mode, total]) => [mode, {
      totalCases: total,
      snapEmptyCases: Number(modeSnapEmptyCases[mode] || 0),
      snapEmptyRate: total > 0 ? Number(modeSnapEmptyCases[mode] || 0) / total : 0
    }])
  );

  const dominantCause = Object.entries(primaryReasonCounts).sort((a, b) => b[1] - a[1])[0]?.[0] || 'none';
  const dominantMode = Object.entries(modeRates).sort((a, b) => b[1].snapEmptyRate - a[1].snapEmptyRate)[0]?.[0] || 'none';
  const dominantSide = Object.entries(sideTotals).sort((a, b) => Number(b[1].nearestNullCount || 0) + Number(b[1].rejectSameCorridorCount || 0) + Number(b[1].rejectInsideBlockedAreaCount || 0) - (Number(a[1].nearestNullCount || 0) + Number(a[1].rejectSameCorridorCount || 0) + Number(a[1].rejectInsideBlockedAreaCount || 0)))[0]?.[0] || 'none';
  const dominantTier = Object.entries(tierTotals).sort((a, b) => Number(b[1].rejectSameCorridorCount || 0) + Number(b[1].nearestNullCount || 0) - (Number(a[1].rejectSameCorridorCount || 0) + Number(a[1].nearestNullCount || 0)))[0]?.[0] || 'none';
  const dominantDepth = Object.entries(depthTotals).sort((a, b) => Number(b[1].rejectSameCorridorCount || 0) + Number(b[1].rejectInsideBlockedAreaCount || 0) - (Number(a[1].rejectSameCorridorCount || 0) + Number(a[1].rejectInsideBlockedAreaCount || 0)))[0]?.[0] || 'none';

  return {
    totalCases: results.length,
    snapEmptyCases: snapEmptyCases.length,
    snapEmptyRate: results.length > 0 ? snapEmptyCases.length / results.length : 0,
    modeTotals,
    sideTotals,
    tierTotals,
    depthTotals,
    modeRates,
    topPrimaryReasons: Object.entries(primaryReasonCounts).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([reason, count]) => ({ reason, count })),
    snapEmptyCases: snapEmptyCases.map(result => ({
      caseId: result.caseId,
      category: result.category,
      primaryReason: result.summary?.snapEmptyPrimaryReason || 'none',
      mode: result.summary?.snapEmptyFailureMode || 'none',
      failedInvariantIds: result.failedInvariantIds
    })),
    dominantCause,
    dominantMode,
    dominantSide,
    dominantTier,
    dominantDepth,
    sidePrimaryReasonCounts
  };
}

function mergeCountMaps(target, source) {
  Object.entries(source || {}).forEach(([key, value]) => {
    target[key] = Number(target[key] || 0) + Number(value || 0);
  });
}

function mergeStrategyStats(target, source) {
  Object.entries(source || {}).forEach(([strategy, stats]) => {
    if (!target[strategy]) {
      target[strategy] = {
        executed: 0,
        success: 0,
        nearestReturned: 0,
        nearestNull: 0,
        nodeBuildSuccess: 0,
        sideRoadContinuationDetected: 0,
        acceptedAsRescue: 0,
        rejectedAsMainlineOnly: 0,
        rejectedAsDuplicate: 0,
        rejectedAsInvalidBearing: 0
      };
    }
    Object.keys(target[strategy]).forEach((key) => {
      target[strategy][key] += Number(stats?.[key] || 0);
    });
  });
}

function buildEscapeNearestBreakdown(results) {
  const breakdown = {
    totalEscapeCandidates: 0,
    escapeSnapEmptyCount: 0,
    nearestNullAfterRetryCount: 0,
    nearestNullAfterRetryRate: 0,
    strategyStats: {},
    detailBreakdown: {},
    sideBreakdown: {},
    tierBreakdown: {},
    depthBreakdown: {},
    positionCategoryBreakdown: {},
    bearingBucketBreakdown: {},
    corridorLengthBucketBreakdown: {},
    snapDistanceBucketBreakdown: {},
    acceptedAfterRetryCount: 0,
    acceptedAfterAdjustmentCount: 0,
    acceptedAsRescueCount: 0,
    rejectedAsMainlineOnlyCount: 0,
    rejectedAsDuplicateOnlyCount: 0,
    rejectedAsInvalidBearingCount: 0,
    strategyOrderUsed: [],
    prunedStrategies: [],
    enabledStrategies: [],
    disabledStrategies: [],
    strategySkipReasons: {},
    acceptedAfterRetryByStrategy: {},
    firstWinningStrategyBreakdown: {},
    nearestReturnedByStrategy: {},
    allNullByStrategy: {},
    firstWinningStrategy: 'none',
    firstWinningStrategyStats: {},
    retryStrategyExhaustedDetails: {},
    nearestReturnedButRejectedBreakdown: {},
    nearestReturnedButRejectedAsMainlineOnly: 0,
    nearestReturnedButRejectedAsNoSideRoad: 0,
    nearestReturnedButRejectedAsDuplicate: 0,
    backRightEntranceBreakdown: {},
    strategyOrderProfiles: {},
    topFailureCombos: [],
    dominantFailureCombo: 'none',
    recommendation: 'retry-order-tuning'
  };
  const comboCounts = {};
  results.forEach((result) => {
    const escapeSummary = result.summary?.snapDiagnostics?.escapeNearestBreakdown;
    if (!escapeSummary) return;
    breakdown.totalEscapeCandidates += Number(escapeSummary.totalCandidates || 0);
    breakdown.nearestNullAfterRetryCount += Number(escapeSummary.nearestNullAfterRetryCount || 0);
    breakdown.acceptedAfterRetryCount += Number(escapeSummary.acceptedAfterRetryCount || 0);
    breakdown.acceptedAfterAdjustmentCount += Number(escapeSummary.acceptedAfterAdjustmentCount || 0);
    breakdown.acceptedAsRescueCount += Number(escapeSummary.acceptedAsRescueCount || 0);
    breakdown.rejectedAsMainlineOnlyCount += Number(escapeSummary.rejectedAsMainlineOnlyCount || 0);
    breakdown.rejectedAsDuplicateOnlyCount += Number(escapeSummary.rejectedAsDuplicateOnlyCount || 0);
    breakdown.rejectedAsInvalidBearingCount += Number(escapeSummary.rejectedAsInvalidBearingCount || 0);
    breakdown.nearestReturnedButRejectedAsMainlineOnly += Number(escapeSummary.nearestReturnedButRejectedAsMainlineOnly || 0);
    breakdown.nearestReturnedButRejectedAsNoSideRoad += Number(escapeSummary.nearestReturnedButRejectedAsNoSideRoad || 0);
    breakdown.nearestReturnedButRejectedAsDuplicate += Number(escapeSummary.nearestReturnedButRejectedAsDuplicate || 0);
    mergeCountMaps(breakdown.detailBreakdown, escapeSummary.nearestNullAfterRetryDetails);
    mergeCountMaps(breakdown.retryStrategyExhaustedDetails, escapeSummary.retryStrategyExhaustedDetails);
    mergeCountMaps(breakdown.nearestReturnedButRejectedBreakdown, escapeSummary.nearestReturnedButRejectedBreakdown);
    mergeCountMaps(breakdown.sideBreakdown, escapeSummary.sideStats);
    mergeCountMaps(breakdown.tierBreakdown, escapeSummary.tierStats);
    mergeCountMaps(breakdown.depthBreakdown, escapeSummary.depthStats);
    mergeCountMaps(breakdown.positionCategoryBreakdown, escapeSummary.positionCategoryStats);
    mergeCountMaps(breakdown.backRightEntranceBreakdown, escapeSummary.backRightEntranceBreakdown);
    mergeCountMaps(breakdown.bearingBucketBreakdown, escapeSummary.bearingBucketStats);
    mergeCountMaps(breakdown.corridorLengthBucketBreakdown, escapeSummary.corridorLengthBucketStats);
    mergeCountMaps(breakdown.snapDistanceBucketBreakdown, escapeSummary.snapDistanceBucketStats);
    mergeCountMaps(breakdown.acceptedAfterRetryByStrategy, escapeSummary.acceptedAfterRetryByStrategy);
    mergeCountMaps(breakdown.firstWinningStrategyBreakdown, escapeSummary.firstWinningStrategyBreakdown);
    mergeCountMaps(breakdown.nearestReturnedByStrategy, escapeSummary.nearestReturnedByStrategy);
    mergeCountMaps(breakdown.allNullByStrategy, escapeSummary.allNullByStrategy);
    mergeCountMaps(breakdown.strategyOrderProfiles, escapeSummary.strategyOrderProfiles);
    mergeStrategyStats(breakdown.strategyStats, escapeSummary.strategyStats);
    breakdown.strategyOrderUsed = Array.from(new Set(breakdown.strategyOrderUsed.concat(escapeSummary.strategyOrderUsed || [])));
    breakdown.prunedStrategies = Array.from(new Set(breakdown.prunedStrategies.concat(escapeSummary.prunedStrategies || [])));
    breakdown.enabledStrategies = Array.from(new Set(breakdown.enabledStrategies.concat(escapeSummary.enabledStrategies || [])));
    breakdown.disabledStrategies = Array.from(new Set(breakdown.disabledStrategies.concat(escapeSummary.disabledStrategies || [])));
    Object.assign(breakdown.strategySkipReasons, escapeSummary.strategySkipReasons || {});
    (escapeSummary.topFailureCombos || []).forEach((entry) => {
      comboCounts[entry.combo] = Number(comboCounts[entry.combo] || 0) + Number(entry.count || 0);
    });
    if (String(result.summary?.snapEmptyFailureMode || '') === 'escape' && String(result.summary?.snapEmptyPrimaryReason || 'none') !== 'none') {
      breakdown.escapeSnapEmptyCount += 1;
    }
  });
  breakdown.nearestNullAfterRetryRate = breakdown.totalEscapeCandidates > 0
    ? breakdown.nearestNullAfterRetryCount / breakdown.totalEscapeCandidates
    : 0;
  breakdown.topFailureCombos = Object.entries(comboCounts)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)
    .map(([combo, count]) => ({ combo, count }));
  breakdown.dominantFailureCombo = breakdown.topFailureCombos[0]?.combo || 'none';
  breakdown.firstWinningStrategy = Object.entries(breakdown.acceptedAfterRetryByStrategy).sort((a, b) => b[1] - a[1])[0]?.[0] || 'none';
  breakdown.firstWinningStrategyStats = breakdown.firstWinningStrategy !== 'none'
    ? { [breakdown.firstWinningStrategy]: { acceptedAfterRetry: Number(breakdown.acceptedAfterRetryByStrategy?.[breakdown.firstWinningStrategy] || 0) } }
    : {};
  const topDetail = Object.entries(breakdown.detailBreakdown).sort((a, b) => b[1] - a[1])[0]?.[0] || 'none';
  if (topDetail.includes('node-build-failure')) breakdown.recommendation = 'node-build-reliability';
  else if (breakdown.rejectedAsMainlineOnlyCount >= Math.max(1, breakdown.nearestNullAfterRetryCount / 2)) breakdown.recommendation = 'mainline-only-filter-review';
  else if (breakdown.acceptedAfterAdjustmentCount > breakdown.acceptedAfterRetryCount) breakdown.recommendation = 'candidate-adjustment-tuning';
  else if (topDetail !== 'none') breakdown.recommendation = 'retry-order-tuning';
  return breakdown;
}

const matrixCases = loadMatrixCases();
const generatedResults = [];

test.describe('block ahead reroute generated harness', () => {
  for (const caseData of matrixCases) {
    test(caseData.caseId, async ({ page }) => {
      let finalSummary;
      let judged;
      try {
        await bootstrap(page);
        const runs = [];
        const repeatRuns = Math.max(1, Number(caseData.repeatRuns || 1));
        for (let i = 0; i < repeatRuns; i++) {
          const summary = await runSingle(page, caseData);
          if (!summary) {
            throw new Error(`missing summary for run ${i + 1}`);
          }
          runs.push(summary);
        }
        finalSummary = JSON.parse(JSON.stringify(runs[runs.length - 1]));
        judged = judgeInvariants(caseData, finalSummary, runs);
      } catch (error) {
        finalSummary = buildHarnessFailureSummary(caseData, error);
        judged = {
          invariantResults: finalSummary.invariantResults,
          failedInvariantIds: finalSummary.failedInvariantIds
        };
      }
      generatedResults.push({
        caseId: caseData.caseId,
        category: caseData.category,
        passed: judged.failedInvariantIds.length === 0,
        failedInvariantIds: judged.failedInvariantIds,
        summary: finalSummary
      });
    });
  }

  test.afterAll(async () => {
    fs.mkdirSync(ARTIFACTS_DIR, { recursive: true });
    const total = generatedResults.length;
    const passed = generatedResults.filter(item => item.passed).length;
    const failed = total - passed;
    const categoryStats = {};
    const rejectReasonCounts = {};
    const failedInvariantCounts = {};
    let dangerousCrossingFalseAccepts = 0;
    let hardRejectAccepted = 0;
    generatedResults.forEach(result => {
      const category = result.category || 'uncategorized';
      if (!categoryStats[category]) categoryStats[category] = { total: 0, passed: 0, failed: 0 };
      categoryStats[category].total += 1;
      categoryStats[category][result.passed ? 'passed' : 'failed'] += 1;

      Object.entries(result.summary?.rejectReasonsSummary || {}).forEach(([reason, count]) => {
        rejectReasonCounts[reason] = (rejectReasonCounts[reason] || 0) + Number(count || 0);
      });
      result.failedInvariantIds.forEach(id => {
        failedInvariantCounts[id] = (failedInvariantCounts[id] || 0) + 1;
      });
      if (result.summary?.success && result.summary?.pedestrianSafety?.status === 'unsafe') dangerousCrossingFalseAccepts += 1;
      if (result.summary?.success && result.summary?.pedestrianSafety?.conservativeDecision === 'hard-reject') hardRejectAccepted += 1;
    });

    const topRejectReasons = Object.entries(rejectReasonCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 5)
      .map(([reason, count]) => ({ reason, count }));

    const summary = {
      total,
      passed,
      failed,
      failRate: total > 0 ? failed / total : 0,
      passRate: total > 0 ? passed / total : 0,
      categoryStats,
      topRejectReasons,
      topFailedInvariants: Object.entries(failedInvariantCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 10)
        .map(([id, count]) => ({ id, count })),
      dangerousCrossingFalseAccepts,
      hardRejectAccepted,
      failedCaseIds: generatedResults.filter(item => !item.passed).map(item => item.caseId),
      cases: generatedResults
    };
    const snapBreakdown = buildSnapEmptyBreakdown(generatedResults);
    const escapeNearestBreakdown = buildEscapeNearestBreakdown(generatedResults);

    fs.writeFileSync(SUMMARY_FILE, JSON.stringify(summary, null, 2));
    fs.writeFileSync(SNAP_BREAKDOWN_FILE, JSON.stringify(snapBreakdown, null, 2));
    fs.writeFileSync(ESCAPE_NEAREST_BREAKDOWN_FILE, JSON.stringify(escapeNearestBreakdown, null, 2));
    console.log(`[RerouteHarness] total=${summary.total} passed=${summary.passed} failed=${summary.failed} failRate=${summary.failRate.toFixed(3)}`);
    console.log(`[RerouteHarness] topRejectReasons=${JSON.stringify(summary.topRejectReasons)}`);
    console.log(`[RerouteHarness] snapEmptyRate=${snapBreakdown.snapEmptyRate.toFixed(3)} dominantCause=${snapBreakdown.dominantCause} dominantMode=${snapBreakdown.dominantMode}`);
    console.log(
      `[RerouteHarness] escapeNearestNullAfterRetryRate=${escapeNearestBreakdown.nearestNullAfterRetryRate.toFixed(3)} ` +
      `acceptedAfterRetry=${escapeNearestBreakdown.acceptedAfterRetryCount} acceptedAfterAdjustment=${escapeNearestBreakdown.acceptedAfterAdjustmentCount} ` +
      `recommendation=${escapeNearestBreakdown.recommendation}`
    );
    expect(summary.dangerousCrossingFalseAccepts).toBe(0);
    expect(summary.hardRejectAccepted).toBe(0);
  });
});

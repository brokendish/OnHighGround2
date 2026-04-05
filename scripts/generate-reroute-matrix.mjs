#!/usr/bin/env node

import fs from 'fs';
import path from 'path';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const OUT_DIR = path.join(ROOT, 'testdata', 'reroute_matrix');
const OUT_FILE = path.join(OUT_DIR, 'generated_matrix.json');

function round(n, digits = 6) {
  return Number(Number(n).toFixed(digits));
}

function point(lat, lng) {
  return { lat: round(lat), lng: round(lng) };
}

function coordsKey(coords) {
  return (Array.isArray(coords) ? coords : [])
    .map(p => `${round(p.lat, 6)},${round(p.lng ?? p.lon, 6)}`)
    .join('|');
}

function route(coords, totalDistance, extra = {}) {
  return {
    coordinates: coords.map(p => ({ lat: p.lat, lng: p.lng })),
    summary: {
      totalDistance: Number(totalDistance),
      totalTime: Math.max(60, Math.round(Number(totalDistance) / 1.2))
    },
    instructions: [],
    ...extra
  };
}

function mergeRoutes(first, second) {
  const firstCoords = Array.isArray(first?.coordinates) ? first.coordinates : [];
  const secondCoords = Array.isArray(second?.coordinates) ? second.coordinates : [];
  const merged = firstCoords.slice();
  secondCoords.forEach((point, index) => {
    if (index === 0 && merged.length > 0) {
      const last = merged[merged.length - 1];
      if (coordsKey([last, point]) === coordsKey([last, last])) return;
      if (Math.abs(last.lat - point.lat) < 1e-6 && Math.abs((last.lng ?? last.lon) - (point.lng ?? point.lon)) < 1e-6) return;
    }
    merged.push({ lat: point.lat, lng: point.lng ?? point.lon });
  });
  return route(
    merged,
    Number(first?.summary?.totalDistance || 0) + Number(second?.summary?.totalDistance || 0)
  );
}

function buildBase(index) {
  const latOffset = round((index % 12) * 0.00003, 6);
  const lngOffset = round(Math.floor(index / 12) * 0.00004, 6);
  const currentLocation = point(35.0001 + latOffset, 139.0 + lngOffset);
  const destination = point(35.004 + latOffset, 139.0 + lngOffset);
  const blockedSegment = {
    start: point(35.00055 + latOffset, 139.0 + lngOffset),
    end: point(35.00095 + latOffset, 139.0 + lngOffset)
  };
  const routeGeometry = [
    [currentLocation.lng, currentLocation.lat],
    [139.0 + lngOffset, 35.002 + latOffset],
    [destination.lng, destination.lat]
  ];
  return { currentLocation, destination, blockedSegment, routeGeometry };
}

function straightRoute(base) {
  return route([
    point(base.currentLocation.lat, base.currentLocation.lng),
    point(base.currentLocation.lat + 0.0017, base.currentLocation.lng),
    point(base.destination.lat, base.destination.lng)
  ], 430);
}

function branchRoute(base, side = 'right', far = false) {
  const dir = side.includes('left') ? -1 : 1;
  const lateral = far ? 0.0015 : 0.0010;
  return route([
    point(base.currentLocation.lat, base.currentLocation.lng),
    point(base.currentLocation.lat + 0.00025, base.currentLocation.lng + (lateral * dir)),
    point(base.destination.lat - 0.00025, base.currentLocation.lng + (lateral * dir)),
    point(base.destination.lat, base.destination.lng)
  ], far ? 760 : 620);
}

function diagonalShortcutRoute(base, side = 'right') {
  const dir = side.includes('left') ? -1 : 1;
  return route([
    point(base.currentLocation.lat, base.currentLocation.lng),
    point(base.currentLocation.lat + 0.0016, base.currentLocation.lng + (0.00125 * dir)),
    point(base.destination.lat, base.destination.lng)
  ], 510);
}

function rescueRoute(base, side = 'back-right', depth = 90) {
  const dir = side.includes('left') ? -1 : 1;
  const lateral = depth >= 120 ? 0.0016 : depth >= 90 ? 0.0012 : 0.0009;
  return route([
    point(base.currentLocation.lat, base.currentLocation.lng),
    point(base.currentLocation.lat - 0.00018, base.currentLocation.lng + (0.00045 * dir)),
    point(base.currentLocation.lat + 0.0012, base.currentLocation.lng + (lateral * dir)),
    point(base.destination.lat - 0.0002, base.currentLocation.lng + (lateral * dir)),
    point(base.destination.lat, base.destination.lng)
  ], 880 + depth);
}

function escapeLegRoute(base, side = 'back-right') {
  const dir = side.includes('left') ? -1 : 1;
  return route([
    point(base.currentLocation.lat, base.currentLocation.lng),
    point(base.currentLocation.lat - 0.00012, base.currentLocation.lng + (0.00025 * dir)),
    point(base.currentLocation.lat - 0.0002, base.currentLocation.lng + (0.00045 * dir))
  ], 62);
}

function escapeMainRoute(base, side = 'back-right', depth = 90) {
  const dir = side.includes('left') ? -1 : 1;
  const lateral = depth >= 120 ? 0.00155 : depth >= 90 ? 0.0012 : 0.00095;
  return route([
    point(base.currentLocation.lat - 0.0002, base.currentLocation.lng + (0.00045 * dir)),
    point(base.currentLocation.lat + 0.0012, base.currentLocation.lng + (lateral * dir)),
    point(base.destination.lat - 0.0002, base.currentLocation.lng + (lateral * dir)),
    point(base.destination.lat, base.destination.lng)
  ], 790 + depth);
}

function safePed(label, source = 'generated-matrix') {
  return {
    status: 'safe',
    safe: true,
    unsafe: false,
    contextUnavailable: false,
    failOpenApplied: false,
    rejectReason: null,
    label,
    contextSource: source,
    contextFailureKind: 'none',
    contextFailureDetail: 'none',
    contextFailureMessage: ''
  };
}

function unknownPed(label, failureKind = 'timeout') {
  return {
    status: 'unknown',
    safe: false,
    unsafe: false,
    contextUnavailable: true,
    failOpenApplied: true,
    rejectReason: null,
    label,
    contextSource: 'compact-cache',
    contextFailureKind: failureKind,
    contextFailureDetail: `${failureKind}-generated`,
    contextFailureMessage: `${failureKind} generated matrix`
  };
}

function unsafePed(label) {
  return {
    status: 'unsafe',
    safe: false,
    unsafe: true,
    contextUnavailable: false,
    failOpenApplied: false,
    rejectReason: 'dangerous-crossing',
    label,
    contextSource: 'compact-cache',
    contextFailureKind: 'none',
    contextFailureDetail: 'none',
    contextFailureMessage: ''
  };
}

function conservative(decision, reason, penalty = 0, extraMetrics = {}) {
  return {
    conservativeRejectEvaluated: true,
    conservativeRejectApplied: decision === 'hard-reject',
    conservativeDecision: decision,
    conservativeRejectReason: reason,
    conservativePenalty: decision === 'soft-risk' ? penalty : 0,
    suspiciousSegmentIndex: 0,
    suspiciousSegmentLengthM: extraMetrics.longestCrossingSegment || 0,
    metrics: {
      longestCrossingSegment: 0,
      totalCrossingDistance: 0,
      crossingSegmentCount: 0,
      maxCrossingRoadClass: 'unknown',
      wideRoadReturnDetected: false,
      diagonalMainlineShortcutDetected: false,
      sideRoadContinuationDetected: false,
      routeStartsAlongCorridorThenEscapes: false,
      routeEndsWithWideRoadReturn: false,
      forwardProgressRatio: 0.72,
      candidateBearingVsBlockedBearing: 58,
      ...extraMetrics
    }
  };
}

function blockedStatsAccepted(side = 'right') {
  return {
    strictOverlapRatio: 0.04,
    nearBlockedRatio: 0.11,
    minDistanceToAreaM: 22,
    intersects: false,
    nearBlocked: false,
    slitIntersectionDetected: false,
    slitBodyIntersectionDetected: false,
    slitCapIntersectionDetected: false,
    slitNearDetected: false,
    coreIntersectionDetected: false,
    intersectionBufferDetected: false,
    legacyBroadIntersectionDetected: false,
    carveOutAdjustedIntersectionDetected: false,
    softIntersectionBufferDetected: false,
    softSlitBodyIntersectionDetected: false,
    hardIntersectionDetected: false,
    effectiveIntersectionBufferRadius: 18,
    effectiveSlitBodyPolicy: 'accepted',
    candidateSide: side,
    slitBodyOverlapRatio: 0.02,
    slitCapOverlapRatio: 0.01,
    slitNearRatio: 0.04,
    coreOverlapRatio: 0,
    intersectionBufferOverlapRatio: 0
  };
}

function blockedStatsSoft(side = 'back-right', variant = 'intersection-buffer-soft') {
  const base = {
    strictOverlapRatio: 0.22,
    nearBlockedRatio: 0.27,
    minDistanceToAreaM: 7,
    intersects: false,
    nearBlocked: true,
    slitIntersectionDetected: false,
    slitBodyIntersectionDetected: false,
    slitCapIntersectionDetected: false,
    slitNearDetected: true,
    coreIntersectionDetected: false,
    intersectionBufferDetected: false,
    legacyBroadIntersectionDetected: false,
    carveOutAdjustedIntersectionDetected: false,
    softIntersectionBufferDetected: false,
    softSlitBodyIntersectionDetected: false,
    hardIntersectionDetected: false,
    effectiveIntersectionBufferRadius: 20,
    effectiveSlitBodyPolicy: variant,
    candidateSide: side,
    slitBodyOverlapRatio: 0.02,
    slitCapOverlapRatio: 0.02,
    slitNearRatio: 0.17,
    coreOverlapRatio: 0,
    intersectionBufferOverlapRatio: 0.1
  };
  if (variant === 'slit-body-soft') {
    base.slitIntersectionDetected = true;
    base.slitBodyIntersectionDetected = true;
    base.softSlitBodyIntersectionDetected = true;
    base.slitBodyOverlapRatio = 0.2;
  }
  if (variant === 'intersection-buffer-soft') {
    base.intersectionBufferDetected = true;
    base.softIntersectionBufferDetected = true;
    base.intersectionBufferOverlapRatio = 0.24;
  }
  return base;
}

function blockedStatsHard(reason, side = 'right') {
  const stats = {
    strictOverlapRatio: 0.42,
    nearBlockedRatio: 0.46,
    minDistanceToAreaM: -4,
    intersects: true,
    nearBlocked: true,
    slitIntersectionDetected: false,
    slitBodyIntersectionDetected: false,
    slitCapIntersectionDetected: false,
    slitNearDetected: true,
    coreIntersectionDetected: false,
    intersectionBufferDetected: false,
    legacyBroadIntersectionDetected: false,
    carveOutAdjustedIntersectionDetected: false,
    softIntersectionBufferDetected: false,
    softSlitBodyIntersectionDetected: false,
    hardIntersectionDetected: true,
    effectiveIntersectionBufferRadius: 22,
    effectiveSlitBodyPolicy: reason,
    candidateSide: side,
    slitBodyOverlapRatio: 0.2,
    slitCapOverlapRatio: 0.02,
    slitNearRatio: 0.3,
    coreOverlapRatio: 0,
    intersectionBufferOverlapRatio: 0.2
  };
  if (reason === 'slit-line-cross') {
    stats.slitIntersectionDetected = true;
    stats.slitBodyIntersectionDetected = true;
    stats.slitBodyOverlapRatio = 0.1;
  } else if (reason === 'core-intersection') {
    stats.coreIntersectionDetected = true;
    stats.coreOverlapRatio = 0.22;
  } else if (reason === 'overlap-hard') {
    stats.strictOverlapRatio = 0.78;
    stats.nearBlockedRatio = 0.82;
    stats.slitBodyIntersectionDetected = true;
    stats.slitIntersectionDetected = true;
    stats.slitBodyOverlapRatio = 0.25;
  } else if (reason === 'slit-body-hard') {
    stats.slitBodyIntersectionDetected = true;
    stats.slitIntersectionDetected = true;
    stats.slitBodyOverlapRatio = 0.21;
  }
  return stats;
}

function escapePoint(base, side, tier, depthKind, nodeType = 'side-road', nodeScore = 95) {
  const dir = side.includes('left') ? -1 : 1;
  return {
    label: `${side}-${tier}-${depthKind}`,
    side,
    point: point(base.currentLocation.lat - 0.0002, base.currentLocation.lng + (0.00045 * dir)),
    lateralM: tier,
    nodeType,
    nodeScore,
    blockedDistanceM: tier + (depthKind.includes('120') ? 60 : 35),
    distanceTierM: tier,
    depthKind
  };
}

function addRouteMaps(target, routeObj, stats, overlap) {
  const key = coordsKey(routeObj.coordinates);
  target.routeBlockedAreaStats[key] = stats;
  target.blockOverlapRatios[key] = overlap;
}

function baseMockData() {
  return {
    osrmAlternatives: { stage1: [], stage2: [], stage3: [] },
    osrmNearest: {},
    osrmRoutesByContext: {},
    escapeLegPoints: [],
    escapePoints: [],
    longDetourPoints: [],
    pedestrianSafetyByLabel: {},
    conservativeByLabel: {},
    routeBlockedAreaStats: {},
    blockOverlapRatios: {},
    defaultRouteBlockedAreaStats: null
  };
}

function buildBranchSuccessCase(index, stage, side, category, deterministicRuns = 1) {
  const base = buildBase(index);
  const mockData = baseMockData();
  const winner = branchRoute(base, side, stage === 'stage2');
  addRouteMaps(mockData, winner, blockedStatsAccepted(side), 0.03);
  mockData.pedestrianSafetyByLabel[`${stage}-candidate`] = safePed(`${stage}-candidate`);
  mockData.pedestrianSafetyByLabel[`final:${stage}`] = safePed(`final:${stage}`);
  if (stage === 'stage1') {
    mockData.osrmAlternatives.stage1 = [winner];
  } else {
    const blocked = straightRoute(base);
    addRouteMaps(mockData, blocked, blockedStatsHard('slit-line-cross', side), 0.14);
    mockData.osrmAlternatives.stage1 = [blocked];
    mockData.osrmAlternatives.stage2 = [winner];
    mockData.pedestrianSafetyByLabel['stage1-candidate'] = safePed('stage1-candidate');
  }
  return {
    caseId: `${category}-${stage}-${side}-${String(index).padStart(3, '0')}`,
    description: `${category} ${stage} ${side} branch detour should succeed`,
    category,
    repeatRuns: deterministicRuns,
    ...base,
    mockData,
    expectations: {
      mustFindRoute: true,
      mustAvoidBlockedArea: true,
      mustAvoidDangerousCrossing: true,
      mustNotFinalConservativeHardReject: true,
      allowedSelectedStages: [stage]
    }
  };
}

function buildEscapeRescueCase(index, mode, side, decision, category, deterministicRuns = 1) {
  const base = buildBase(index);
  const mockData = baseMockData();
  const tier = mode === 'long-detour' ? 150 : 90;
  const depthKind = mode === 'long-detour' ? 'deeper-120' : 'deeper-90';
  const candidate = escapePoint(base, side, tier, depthKind);
  const rescue = rescueRoute(base, side, depthKind.includes('120') ? 120 : 90);
  if (mode === 'escape') {
    mockData.escapePoints = [candidate];
    mockData.osrmRoutesByContext[`escape:${candidate.label}`] = rescue;
    mockData.pedestrianSafetyByLabel[`escape:${candidate.label}`] = unknownPed(`escape:${candidate.label}`);
    mockData.pedestrianSafetyByLabel['final:escape'] = unknownPed('final:escape');
    mockData.conservativeByLabel[`escape:${candidate.label}`] = decision === 'soft-risk'
      ? conservative('soft-risk', 'unknown-rescue-detour-soft', 180, { longestCrossingSegment: 18, totalCrossingDistance: 24, crossingSegmentCount: 2, sideRoadContinuationDetected: true })
      : conservative('pass', 'unknown-pass-side-road', 0, { sideRoadContinuationDetected: true });
    mockData.conservativeByLabel['final:escape'] = mockData.conservativeByLabel[`escape:${candidate.label}`];
  } else {
    mockData.longDetourPoints = [candidate];
    mockData.osrmRoutesByContext[`long-detour:${candidate.label}`] = rescue;
    mockData.pedestrianSafetyByLabel[`long-detour:${candidate.label}`] = unknownPed(`long-detour:${candidate.label}`);
    mockData.pedestrianSafetyByLabel['final:long-detour'] = unknownPed('final:long-detour');
    mockData.conservativeByLabel[`long-detour:${candidate.label}`] = decision === 'soft-risk'
      ? conservative('soft-risk', 'long-crossing-segment-soft', 220, { longestCrossingSegment: 20, totalCrossingDistance: 28, crossingSegmentCount: 2, sideRoadContinuationDetected: true })
      : conservative('pass', 'unknown-pass-rescue-candidate', 0, { sideRoadContinuationDetected: true });
    mockData.conservativeByLabel['final:long-detour'] = mockData.conservativeByLabel[`long-detour:${candidate.label}`];
  }
  addRouteMaps(
    mockData,
    rescue,
    blockedStatsSoft(side, decision === 'soft-risk' ? 'slit-body-soft' : 'intersection-buffer-soft'),
    0.04
  );
  return {
    caseId: `${category}-${mode}-${side}-${decision}-${String(index).padStart(3, '0')}`,
    description: `${category} ${mode} ${side} unknown ${decision} rescue candidate`,
    category,
    repeatRuns: deterministicRuns,
    ...base,
    mockData,
    expectations: {
      mustFindRoute: true,
      mustAvoidBlockedArea: true,
      mustAvoidDangerousCrossing: true,
      mustNotFinalConservativeHardReject: true,
      mustAllowSoftRisk: decision === 'soft-risk',
      expectedConservativeDecision: decision,
      allowedSelectedStages: [mode]
    }
  };
}

function buildEscapeLegCase(index, side, decision, category, deterministicRuns = 1) {
  const base = buildBase(index);
  const mockData = baseMockData();
  const dir = side.includes('left') ? -1 : 1;
  const candidate = escapePoint(base, side, 60, 'deeper-90');
  candidate.point = point(base.currentLocation.lat - 0.00032, base.currentLocation.lng + (0.00085 * dir));
  const leg = route([
    point(base.currentLocation.lat, base.currentLocation.lng),
    point(base.currentLocation.lat - 0.00018, base.currentLocation.lng + (0.00035 * dir)),
    point(candidate.point.lat, candidate.point.lng)
  ], 96);
  const main = route([
    point(candidate.point.lat, candidate.point.lng),
    point(base.currentLocation.lat + 0.0011, base.currentLocation.lng + (0.00125 * dir)),
    point(base.destination.lat - 0.00025, base.currentLocation.lng + (0.0012 * dir)),
    point(base.destination.lat, base.destination.lng)
  ], 812);
  const merged = mergeRoutes(leg, main);
  mockData.escapeLegPoints = [candidate];
  mockData.osrmRoutesByContext[`escape-leg:leg:${candidate.label}`] = leg;
  mockData.osrmRoutesByContext[`escape-leg:main:${candidate.label}`] = main;
  const acceptedStats = blockedStatsSoft(side, 'intersection-buffer-soft');
  mockData.defaultRouteBlockedAreaStats = acceptedStats;
  addRouteMaps(mockData, main, acceptedStats, 0.05);
  addRouteMaps(mockData, merged, acceptedStats, 0.05);
  mockData.pedestrianSafetyByLabel[`escape-leg:${candidate.label}`] = unknownPed(`escape-leg:${candidate.label}`);
  mockData.pedestrianSafetyByLabel['final:escape-leg'] = unknownPed('final:escape-leg');
  mockData.conservativeByLabel[`escape-leg:${candidate.label}`] = decision === 'soft-risk'
    ? conservative('soft-risk', 'unknown-side-road-continue', 150, { longestCrossingSegment: 12, totalCrossingDistance: 18, crossingSegmentCount: 2, sideRoadContinuationDetected: true })
    : conservative('pass', 'unknown-pass-side-road', 0, { sideRoadContinuationDetected: true });
  mockData.conservativeByLabel['final:escape-leg'] = mockData.conservativeByLabel[`escape-leg:${candidate.label}`];
  return {
    caseId: `${category}-escape-leg-${side}-${decision}-${String(index).padStart(3, '0')}`,
    description: `${category} escape-leg ${side} should survive`,
    category,
    repeatRuns: deterministicRuns,
    ...base,
    mockData,
    expectations: {
      mustFindRoute: true,
      mustAvoidBlockedArea: true,
      mustAvoidDangerousCrossing: true,
      mustNotFinalConservativeHardReject: true,
      mustAllowSoftRisk: decision === 'soft-risk',
      expectedConservativeDecision: decision,
      allowedSelectedStages: ['escape-leg']
    }
  };
}

function buildDangerousRejectCase(index, type, category, deterministicRuns = 1) {
  const base = buildBase(index);
  const mockData = baseMockData();
  const routeObj = type === 'diagonal'
    ? diagonalShortcutRoute(base, 'right')
    : branchRoute(base, 'right', false);
  addRouteMaps(mockData, routeObj, blockedStatsAccepted('right'), 0.03);
  mockData.osrmAlternatives.stage1 = [routeObj];
  if (type === 'unsafe') {
    mockData.pedestrianSafetyByLabel['stage1-candidate'] = unsafePed('stage1-candidate');
  } else {
    mockData.pedestrianSafetyByLabel['stage1-candidate'] = unknownPed('stage1-candidate');
    mockData.conservativeByLabel['stage1-candidate'] = type === 'wide-road-return'
      ? conservative('hard-reject', 'wide-road-return-hard', 0, { longestCrossingSegment: 34, totalCrossingDistance: 34, crossingSegmentCount: 1, wideRoadReturnDetected: true })
      : conservative('hard-reject', 'diagonal-mainline-shortcut-hard', 0, { longestCrossingSegment: 30, totalCrossingDistance: 30, crossingSegmentCount: 1, diagonalMainlineShortcutDetected: true });
  }
  return {
    caseId: `${category}-${type}-${String(index).padStart(3, '0')}`,
    description: `${category} ${type} dangerous candidate must be rejected`,
    category,
    repeatRuns: deterministicRuns,
    ...base,
    mockData,
    expectations: {
      mustFindRoute: false,
      mustAvoidDangerousCrossing: true,
      mustNotFinalConservativeHardReject: false,
      expectedDangerousReject: true
    }
  };
}

function buildHardBlockedCase(index, mode, side, reason, category, deterministicRuns = 1) {
  const base = buildBase(index);
  const mockData = baseMockData();
  const candidate = escapePoint(base, side, mode === 'long-detour' ? 150 : 90, reason === 'overlap-hard' ? 'deeper-120' : 'deeper-90');
  const routeObj = rescueRoute(base, side, reason === 'overlap-hard' ? 120 : 90);
  addRouteMaps(mockData, routeObj, blockedStatsHard(reason, side), reason === 'overlap-hard' ? 0.78 : 0.12);
  if (mode === 'escape') {
    mockData.escapePoints = [candidate];
    mockData.osrmRoutesByContext[`escape:${candidate.label}`] = routeObj;
    mockData.pedestrianSafetyByLabel[`escape:${candidate.label}`] = safePed(`escape:${candidate.label}`);
  } else {
    mockData.longDetourPoints = [candidate];
    mockData.osrmRoutesByContext[`long-detour:${candidate.label}`] = routeObj;
    mockData.pedestrianSafetyByLabel[`long-detour:${candidate.label}`] = safePed(`long-detour:${candidate.label}`);
  }
  return {
    caseId: `${category}-${mode}-${side}-${reason}-${String(index).padStart(3, '0')}`,
    description: `${category} ${mode} ${reason} must remain hard reject`,
    category,
    repeatRuns: deterministicRuns,
    ...base,
    mockData,
    expectations: {
      mustFindRoute: false,
      expectedHardBlockedReason: reason
    }
  };
}

function rawCandidate(base, label, side, tier, depthKind = 'entrance', extra = {}) {
  const dir = side.includes('left') ? -1 : 1;
  const backward = side.startsWith('back-') ? -0.00018 : 0.00008;
  return {
    label,
    side,
    point: point(base.currentLocation.lat + backward, base.currentLocation.lng + (0.00045 * dir)),
    lateralM: tier,
    backwardM: side.startsWith('back-') ? 35 : 0,
    distanceTierM: tier,
    depthKind,
    ...extra
  };
}

function snappedPointForSide(base, side, corridor = false) {
  const dir = side.includes('left') ? -1 : 1;
  if (corridor) {
    return point(base.currentLocation.lat + 0.0016, base.currentLocation.lng);
  }
  return point(base.currentLocation.lat + 0.00035, base.currentLocation.lng + (0.00095 * dir));
}

function buildSnapDetailCase(index, config) {
  const base = buildBase(index);
  const mockData = baseMockData();
  const raw = config.rawCandidates.map(candidate => ({ ...candidate }));
  const modeKey = config.mode;
  const injected = { rawCandidates: raw };
  if (modeKey === 'escape-leg') mockData.escapeLegPoints = injected;
  if (modeKey === 'escape') mockData.escapePoints = injected;
  if (modeKey === 'long-detour') mockData.longDetourPoints = injected;
  (config.nearestEntries || []).forEach(entry => {
    mockData.osrmNearest[`${modeKey}:${entry.label}:point`] = entry.value;
  });

  (config.successRoutes || []).forEach(success => {
    const routeObj = rescueRoute(base, success.side, success.depthMeters || 90);
    if (modeKey === 'escape') {
      mockData.osrmRoutesByContext[`escape:${success.label}`] = routeObj;
      mockData.pedestrianSafetyByLabel[`escape:${success.label}`] = safePed(`escape:${success.label}`);
      mockData.pedestrianSafetyByLabel['final:escape'] = safePed('final:escape');
    } else if (modeKey === 'escape-leg') {
      const leg = route([
        point(base.currentLocation.lat, base.currentLocation.lng),
        point(base.currentLocation.lat - 0.00018, base.currentLocation.lng + (success.side.includes('left') ? -0.00035 : 0.00035)),
        point(base.currentLocation.lat - 0.00032, base.currentLocation.lng + (success.side.includes('left') ? -0.00085 : 0.00085))
      ], 96);
      mockData.osrmRoutesByContext[`escape-leg:leg:${success.label}`] = leg;
      mockData.osrmRoutesByContext[`escape-leg:main:${success.label}`] = routeObj;
      mockData.pedestrianSafetyByLabel[`escape-leg:${success.label}`] = safePed(`escape-leg:${success.label}`);
      mockData.pedestrianSafetyByLabel['final:escape-leg'] = safePed('final:escape-leg');
    } else if (modeKey === 'long-detour') {
      mockData.osrmRoutesByContext[`long-detour:${success.label}`] = routeObj;
      mockData.pedestrianSafetyByLabel[`long-detour:${success.label}`] = safePed(`long-detour:${success.label}`);
      mockData.pedestrianSafetyByLabel['final:long-detour'] = safePed('final:long-detour');
    }
    addRouteMaps(mockData, routeObj, blockedStatsSoft(success.side, 'intersection-buffer-soft'), 0.04);
  });

  if (config.followupEscape) {
    const candidate = rawCandidate(base, config.followupEscape.label, config.followupEscape.side, config.followupEscape.tier, config.followupEscape.depthKind || 'entrance');
    mockData.escapePoints = { rawCandidates: [candidate] };
    mockData.osrmNearest[`escape:${candidate.label}:point`] = { ...snappedPointForSide(base, candidate.side), distanceM: 6 };
    const routeObj = rescueRoute(base, config.followupEscape.side, 90);
    mockData.osrmRoutesByContext[`escape:${candidate.label}`] = routeObj;
    addRouteMaps(mockData, routeObj, blockedStatsSoft(config.followupEscape.side, 'intersection-buffer-soft'), 0.04);
    mockData.pedestrianSafetyByLabel[`escape:${candidate.label}`] = safePed(`escape:${candidate.label}`);
    mockData.pedestrianSafetyByLabel['final:escape'] = safePed('final:escape');
  }

  if (config.followupLongDetour) {
    const candidate = rawCandidate(base, config.followupLongDetour.label, config.followupLongDetour.side, config.followupLongDetour.tier, config.followupLongDetour.depthKind || 'deeper-120');
    mockData.longDetourPoints = { rawCandidates: [candidate], options: { depthSteps: [] } };
    mockData.osrmNearest[`long-detour:${candidate.label}:point`] = { ...snappedPointForSide(base, candidate.side), distanceM: 7 };
    const routeObj = rescueRoute(base, config.followupLongDetour.side, 120);
    mockData.osrmRoutesByContext[`long-detour:${candidate.label}`] = routeObj;
    addRouteMaps(mockData, routeObj, blockedStatsSoft(config.followupLongDetour.side, 'intersection-buffer-soft'), 0.04);
    mockData.pedestrianSafetyByLabel[`long-detour:${candidate.label}`] = safePed(`long-detour:${candidate.label}`);
    mockData.pedestrianSafetyByLabel['final:long-detour'] = safePed('final:long-detour');
  }

  return {
    caseId: `${config.category}-${config.slug}-${String(index).padStart(3, '0')}`,
    description: config.description,
    category: config.category,
    ...base,
    mockData,
    expectations: {
      mustFindRoute: config.mustFindRoute,
      expectedSnapMode: config.expectedSnapMode || null,
      expectedSnapEmptyPrimaryReason: config.expectedSnapEmptyPrimaryReason,
      expectedDetailReasonRecorded: config.expectedDetailReasonRecorded,
      expectedModeStats: config.expectedModeStats,
      allowedSelectedStages: config.allowedSelectedStages
    }
  };
}

const cases = [];

for (let i = 0; i < 8; i++) {
  cases.push(buildBranchSuccessCase(i + 1, 'stage1', i % 2 === 0 ? 'right' : 'left', 'A-no-route-should-not-happen'));
  cases.push(buildBranchSuccessCase(i + 21, 'stage2', i % 2 === 0 ? 'right' : 'left', 'A-no-route-should-not-happen'));
}
for (let i = 0; i < 8; i++) {
  cases.push(buildEscapeRescueCase(i + 41, 'escape', i % 2 === 0 ? 'back-right' : 'back-left', 'pass', 'A-no-route-should-not-happen'));
  cases.push(buildEscapeLegCase(i + 61, i % 2 === 0 ? 'back-right' : 'back-left', 'pass', 'A-no-route-should-not-happen'));
}

for (let i = 0; i < 8; i++) {
  cases.push(buildDangerousRejectCase(i + 81, 'unsafe', 'B-dangerous-crossing-must-reject'));
  cases.push(buildDangerousRejectCase(i + 101, 'diagonal', 'B-dangerous-crossing-must-reject'));
}
for (let i = 0; i < 8; i++) {
  cases.push(buildDangerousRejectCase(i + 121, 'wide-road-return', 'B-dangerous-crossing-must-reject'));
}

for (let i = 0; i < 8; i++) {
  cases.push(buildEscapeRescueCase(i + 141, 'escape', i % 2 === 0 ? 'back-right' : 'back-left', 'soft-risk', 'C-soft-risk-should-survive-comparison'));
  cases.push(buildEscapeRescueCase(i + 161, 'long-detour', i % 2 === 0 ? 'back-right' : 'back-left', 'soft-risk', 'C-soft-risk-should-survive-comparison'));
  cases.push(buildEscapeLegCase(i + 181, i % 2 === 0 ? 'back-right' : 'back-left', 'soft-risk', 'C-soft-risk-should-survive-comparison'));
}

for (let i = 0; i < 6; i++) {
  cases.push(buildHardBlockedCase(i + 201, 'escape', i % 2 === 0 ? 'right' : 'left', 'slit-line-cross', 'D-hard-intersection-must-stay-hard'));
  cases.push(buildHardBlockedCase(i + 221, 'escape', i % 2 === 0 ? 'back-right' : 'back-left', 'core-intersection', 'D-hard-intersection-must-stay-hard'));
  cases.push(buildHardBlockedCase(i + 241, 'long-detour', i % 2 === 0 ? 'back-right' : 'back-left', 'overlap-hard', 'D-hard-intersection-must-stay-hard'));
  cases.push(buildHardBlockedCase(i + 261, 'long-detour', i % 2 === 0 ? 'right' : 'left', 'slit-body-hard', 'D-hard-intersection-must-stay-hard'));
}

for (let i = 0; i < 4; i++) {
  cases.push(buildBranchSuccessCase(i + 281, 'stage1', i % 2 === 0 ? 'right' : 'left', 'E-deterministic-regression', 2));
  cases.push(buildEscapeRescueCase(i + 291, 'escape', i % 2 === 0 ? 'back-right' : 'back-left', 'soft-risk', 'E-deterministic-regression', 2));
  cases.push(buildDangerousRejectCase(i + 301, 'diagonal', 'E-deterministic-regression', 2));
  cases.push(buildHardBlockedCase(i + 311, 'long-detour', i % 2 === 0 ? 'back-right' : 'back-left', 'slit-body-hard', 'E-deterministic-regression', 2));
}

cases.push(buildSnapDetailCase(321, {
  category: 'F-snap-empty-diagnostics',
  slug: 'nearest-null-primary',
  description: 'nearest-null should dominate escape-leg snap-empty',
  mode: 'escape-leg',
  mustFindRoute: true,
  expectedSnapMode: 'escape-leg',
  expectedSnapEmptyPrimaryReason: 'nearest-null',
  expectedDetailReasonRecorded: 'escape-leg-snap-empty:nearest-null',
  expectedModeStats: { rawCandidateCount: 2, nearestAttemptCount: 2, nearestSuccessCount: 0, nearestNullCount: 2, usableSnappedCount: 0, usableRouteCandidateCount: 0 },
  allowedSelectedStages: ['escape'],
  rawCandidates: [
    rawCandidate(buildBase(321), 'diag-leg-right-null', 'right', 60),
    rawCandidate(buildBase(321), 'diag-leg-back-right-null', 'back-right', 60)
  ],
  nearestEntries: [],
  followupEscape: { label: 'diag-escape-recover', side: 'back-right', tier: 90 }
}));

cases.push(buildSnapDetailCase(322, {
  category: 'F-snap-empty-diagnostics',
  slug: 'same-corridor-primary',
  description: 'same corridor should dominate escape snap-empty',
  mode: 'escape',
  mustFindRoute: true,
  expectedSnapMode: 'escape',
  expectedSnapEmptyPrimaryReason: 'same-corridor',
  expectedDetailReasonRecorded: 'escape-snap-empty:same-corridor',
  expectedModeStats: { rawCandidateCount: 2, nearestAttemptCount: 2, nearestSuccessCount: 2, rejectSameCorridorCount: 2, usableSnappedCount: 0, usableRouteCandidateCount: 0 },
  allowedSelectedStages: ['long-detour'],
  rawCandidates: [
    rawCandidate(buildBase(322), 'diag-escape-right-corridor', 'right', 100, 'entrance', { forceRejectReason: 'same-corridor' }),
    rawCandidate(buildBase(322), 'diag-escape-left-corridor', 'left', 100, 'entrance', { forceRejectReason: 'same-corridor' })
  ],
  nearestEntries: [
    { label: 'diag-escape-right-corridor', value: { ...snappedPointForSide(buildBase(322), 'right'), distanceM: 5 } },
    { label: 'diag-escape-left-corridor', value: { ...snappedPointForSide(buildBase(322), 'left'), distanceM: 5 } }
  ],
  followupLongDetour: { label: 'diag-long-recover', side: 'back-left', tier: 150, depthKind: 'deeper-120' }
}));

cases.push(buildSnapDetailCase(323, {
  category: 'F-snap-empty-diagnostics',
  slug: 'inside-blocked-primary',
  description: 'inside blocked area should dominate long-detour snap-empty',
  mode: 'long-detour',
  mustFindRoute: false,
  expectedSnapMode: 'long-detour',
  expectedSnapEmptyPrimaryReason: 'inside-blocked-area',
  expectedDetailReasonRecorded: 'long-detour-snap-empty:inside-blocked-area',
  expectedModeStats: { rawCandidateCount: 2, nearestAttemptCount: 2, nearestSuccessCount: 2, rejectInsideBlockedAreaCount: 2, usableSnappedCount: 0, usableRouteCandidateCount: 0 },
  rawCandidates: [
    rawCandidate(buildBase(323), 'diag-long-right-blocked', 'right', 150, 'deeper-120'),
    rawCandidate(buildBase(323), 'diag-long-back-right-blocked', 'back-right', 150, 'deeper-120')
  ],
  nearestEntries: [
    { label: 'diag-long-right-blocked', value: { lat: buildBase(323).blockedSegment.start.lat, lng: buildBase(323).blockedSegment.start.lng, distanceM: 4 } },
    { label: 'diag-long-back-right-blocked', value: { lat: buildBase(323).blockedSegment.start.lat, lng: buildBase(323).blockedSegment.start.lng, distanceM: 4 } }
  ]
}));

cases.push(buildSnapDetailCase(324, {
  category: 'F-snap-empty-diagnostics',
  slug: 'node-build-failure-primary',
  description: 'node build failure should be reported when nearest succeeds but candidate is rejected',
  mode: 'escape',
  mustFindRoute: true,
  expectedSnapMode: 'escape',
  expectedSnapEmptyPrimaryReason: 'node-build-failure',
  expectedDetailReasonRecorded: 'escape-snap-empty:node-build-failure',
  expectedModeStats: { rawCandidateCount: 1, nearestAttemptCount: 1, nearestSuccessCount: 1, rejectNodeBuildFailureCount: 1, usableSnappedCount: 0, usableRouteCandidateCount: 0 },
  rawCandidates: [
    rawCandidate(buildBase(324), 'diag-node-build-failure', 'right', 100, 'entrance', { forceRejectReason: 'node-build-failure' })
  ],
  nearestEntries: [
    { label: 'diag-node-build-failure', value: { ...snappedPointForSide(buildBase(324), 'right'), distanceM: 5 } }
  ],
  allowedSelectedStages: ['long-detour'],
  followupLongDetour: { label: 'diag-long-after-node-failure', side: 'back-right', tier: 150, depthKind: 'deeper-120' }
}));

cases.push(buildSnapDetailCase(325, {
  category: 'F-snap-empty-diagnostics',
  slug: 'right-biased-failure',
  description: 'right side bias should be visible in side stats when only right candidates fail',
  mode: 'escape',
  mustFindRoute: true,
  expectedSnapMode: 'escape',
  expectedSnapEmptyPrimaryReason: 'nearest-null',
  expectedDetailReasonRecorded: 'escape-snap-empty:nearest-null',
  expectedModeStats: { rawCandidateCount: 3, nearestAttemptCount: 3, nearestSuccessCount: 0, nearestNullCount: 3, usableSnappedCount: 0, usableRouteCandidateCount: 0 },
  rawCandidates: [
    rawCandidate(buildBase(325), 'diag-right-only-1', 'right', 30),
    rawCandidate(buildBase(325), 'diag-right-only-2', 'right', 60),
    rawCandidate(buildBase(325), 'diag-right-only-3', 'right', 100)
  ],
  nearestEntries: [],
  allowedSelectedStages: ['long-detour'],
  followupLongDetour: { label: 'diag-long-after-right-bias', side: 'back-left', tier: 150, depthKind: 'deeper-120' }
}));

cases.push(buildSnapDetailCase(326, {
  category: 'F-snap-empty-diagnostics',
  slug: 'back-right-recovers-right-fails',
  description: 'right fails but back-right survives in escape mode',
  mode: 'escape',
  mustFindRoute: true,
  expectedModeStats: { rawCandidateCount: 2, nearestAttemptCount: 2, nearestSuccessCount: 2, rejectSameCorridorCount: 1, usableSnappedCount: 1, usableRouteCandidateCount: 1 },
  allowedSelectedStages: ['escape'],
  rawCandidates: [
    rawCandidate(buildBase(326), 'diag-right-fails', 'right', 60),
    rawCandidate(buildBase(326), 'diag-back-right-pass', 'back-right', 90)
  ],
  nearestEntries: [
    { label: 'diag-right-fails', value: { ...snappedPointForSide(buildBase(326), 'right', true), distanceM: 4 } },
    { label: 'diag-back-right-pass', value: { ...snappedPointForSide(buildBase(326), 'back-right'), distanceM: 6 } }
  ],
  successRoutes: [
    { label: 'diag-back-right-pass', side: 'back-right', depthMeters: 90 }
  ]
}));

cases.push(buildSnapDetailCase(327, {
  category: 'F-snap-empty-diagnostics',
  slug: 'escape-leg-empty-escape-available',
  description: 'escape-leg empty but escape has usable candidate',
  mode: 'escape-leg',
  mustFindRoute: true,
  expectedSnapMode: 'escape-leg',
  expectedSnapEmptyPrimaryReason: 'nearest-null',
  expectedDetailReasonRecorded: 'escape-leg-snap-empty:nearest-null',
  expectedModeStats: { rawCandidateCount: 1, nearestAttemptCount: 1, nearestSuccessCount: 0, nearestNullCount: 1, usableSnappedCount: 0, usableRouteCandidateCount: 0 },
  allowedSelectedStages: ['escape'],
  rawCandidates: [
    rawCandidate(buildBase(327), 'diag-leg-empty', 'back-left', 60)
  ],
  nearestEntries: [],
  followupEscape: { label: 'diag-escape-after-leg-empty', side: 'back-left', tier: 90 }
}));

cases.push(buildSnapDetailCase(328, {
  category: 'F-snap-empty-diagnostics',
  slug: 'escape-empty-long-detour-available',
  description: 'escape empty but long-detour has usable candidate',
  mode: 'escape',
  mustFindRoute: true,
  expectedSnapMode: 'escape',
  expectedSnapEmptyPrimaryReason: 'same-corridor',
  expectedDetailReasonRecorded: 'escape-snap-empty:same-corridor',
  expectedModeStats: { rawCandidateCount: 1, nearestAttemptCount: 1, nearestSuccessCount: 1, rejectSameCorridorCount: 1, usableSnappedCount: 0, usableRouteCandidateCount: 0 },
  allowedSelectedStages: ['long-detour'],
  rawCandidates: [
    rawCandidate(buildBase(328), 'diag-escape-empty-corridor', 'right', 100, 'entrance', { forceRejectReason: 'same-corridor' })
  ],
  nearestEntries: [
    { label: 'diag-escape-empty-corridor', value: { ...snappedPointForSide(buildBase(328), 'right'), distanceM: 4 } }
  ],
  followupLongDetour: { label: 'diag-long-after-escape-empty', side: 'back-right', tier: 150, depthKind: 'deeper-120' }
}));

fs.mkdirSync(OUT_DIR, { recursive: true });
fs.writeFileSync(OUT_FILE, JSON.stringify({
  version: 1,
  generatedAt: new Date().toISOString(),
  totalCases: cases.length,
  cases
}, null, 2));

console.log(`generated ${cases.length} reroute matrix cases -> ${path.relative(ROOT, OUT_FILE)}`);

'use strict';

const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const CASES_DIR = path.join(__dirname, '..', 'testdata', 'reroute_cases');
const FIXTURES_DIR = path.join(CASES_DIR, 'fixtures');

function loadReplayCases() {
  return fs.readdirSync(CASES_DIR)
    .filter(name => name.endsWith('.json'))
    .sort()
    .map(name => {
      const filePath = path.join(CASES_DIR, name);
      const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
      const fixtures = {
        osrmAlternatives: JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, data.fixtures.osrmAlternatives), 'utf8')),
        osrmNearest: JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, data.fixtures.osrmNearest), 'utf8')),
        osrmEscape: JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, data.fixtures.osrmEscape), 'utf8')),
        pedestrianContext: JSON.parse(fs.readFileSync(path.join(FIXTURES_DIR, data.fixtures.pedestrianContext), 'utf8'))
      };
      return { ...data, fixturesData: fixtures };
    });
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
      name: 'Fixture Destination'
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

async function installFixtureDeps(page, caseData) {
  await page.evaluate(({ fixturesData }) => {
    const clone = (value) => value == null ? value : JSON.parse(JSON.stringify(value));
    const byStage = fixturesData.osrmAlternatives || {};
    const escape = fixturesData.osrmEscape || {};
    const nearest = fixturesData.osrmNearest || {};
    const pedestrian = fixturesData.pedestrianContext || null;
    window.__fixturePedFetchCount = 0;
    window.__OHG_TEST_DEPS__ = {
      fetchOsrmAlternatives: async (_from, _to, _maxAlts, contextLabel) => clone(byStage[contextLabel] || []),
      fetchOsrmNearest: async (_point, contextLabel) => clone(nearest[contextLabel] || null),
      fetchOsrmRoute: async (_waypoints, contextLabel) => clone((escape.routes || {})[contextLabel] || null),
      fetchPedestrianSafetyContext: async () => {
        window.__fixturePedFetchCount += 1;
        return clone(pedestrian);
      },
      generateEscapeLegPoints: async () => clone(escape.escapeLegPoints || []),
      generateEscapePoints: async () => clone(escape.escapePoints || []),
      generateLongDetourEscapePoints: async () => clone(escape.longDetourPoints || [])
    };
  }, { fixturesData: caseData.fixturesData });
}

const cases = loadReplayCases();

test.describe('block ahead reroute fixture replay', () => {
  for (const caseData of cases) {
    test(caseData.name, async ({ page }) => {
      await bootstrap(page);
      await seedNav(page, caseData);
      await installFixtureDeps(page, caseData);

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
        timing: window._blockAheadLastTiming,
        pedFetchCount: window.__fixturePedFetchCount || 0,
        routeDebug: navActiveRoute?.__debugSummary || null
      }));

      const summary = result.summary || result.routeDebug;
      expect(summary).toBeTruthy();

      if (caseData.expectations.mustFindRoute) {
        expect(summary.success).toBe(true);
      } else {
        expect(summary.success).toBe(false);
      }

      if (caseData.expectations.mustFindRoute && caseData.expectations.mustAvoidBlockedArea) {
        expect(summary.expectationsView.avoidsBlockedArea).toBe(true);
      }
      if (caseData.expectations.mustFindRoute && caseData.expectations.mustAvoidDangerousCrossing) {
        expect(summary.pedestrianSafety.status).not.toBe('unsafe');
      }
      if (caseData.expectations.mustNotFinalConservativeHardReject) {
        expect(summary.pedestrianSafety.conservativeDecision).not.toBe('hard-reject');
      }
      if (caseData.expectations.mustAllowSoftRisk) {
        expect(['soft-risk', 'pass']).toContain(summary.pedestrianSafety.conservativeDecision);
      }
      if (Array.isArray(caseData.expectations.allowedSelectedStages) && caseData.expectations.mustFindRoute) {
        expect(caseData.expectations.allowedSelectedStages).toContain(summary.selectedStage);
      }
      if (caseData.expectations.maxRejectReasonCount) {
        for (const [reason, maxValue] of Object.entries(caseData.expectations.maxRejectReasonCount)) {
          expect(Number(summary.rejectReasonsSummary?.[reason] || 0)).toBeLessThanOrEqual(maxValue);
        }
      }
    });
  }
});

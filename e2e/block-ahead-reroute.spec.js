'use strict';

const { test, expect } = require('@playwright/test');

const BASE_ROUTE = [
  { lat: 35.0, lng: 139.0 },
  { lat: 35.002, lng: 139.0 },
  { lat: 35.004, lng: 139.0 },
];

// Route that bypasses the block area (east of lng 139.0, outside the 40m buffer)
const BYPASS_ROUTE = [
  { lat: 35.0001, lng: 139.0 },
  { lat: 35.0001, lng: 139.0045 },
  { lat: 35.0032, lng: 139.0045 },
  { lat: 35.004,  lng: 139.0 },
];

// Route that stays on the original blocked corridor
const BLOCKED_ROUTE = [
  { lat: 35.00055, lng: 139.0 },
  { lat: 35.00065, lng: 139.0 },
  { lat: 35.00075, lng: 139.0 },
  { lat: 35.00085, lng: 139.0 },
  { lat: 35.00095, lng: 139.0 },
  { lat: 35.00105, lng: 139.0 },
];

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

async function bootstrapRouteCandidates(page) {
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
  await page.waitForFunction(() => typeof fetchRouteCandidates === 'function' && typeof map !== 'undefined');
}

async function seedNav(page, { currentLocation = { lat: 35.0001, lon: 139.0, accuracyMeters: 5 } } = {}) {
  await page.evaluate(() => {
    window.__voiceCalls = [];
    window.__voiceClearCount = 0;
    window.__stepClearCount = 0;
    window.__buildWaypointRoute = (start, extraWaypoints, destination, summary = { totalDistance: 321.5, totalTime: 278.4 }) => ({
      coordinates: [
        { lat: start.lat, lng: start.lon ?? start.lng },
        ...(extraWaypoints || []).map(wp => ({ lat: wp.lat, lng: wp.lng ?? wp.lon })),
        { lat: destination.lat, lng: destination.lon ?? destination.lng }
      ],
      summary,
      instructions: [
        { text: '迂回して進む', distance: 100, index: 1 }
      ]
    });
    voiceNav.enabled = true;
    voiceNav.announce = (payload) => { window.__voiceCalls.push(payload); };
    voiceNav.announceApproach = () => {};
    voiceNav.clear = () => { window.__voiceClearCount += 1; };
    clearNavStepHighlight = () => { window.__stepClearCount += 1; };
  });
  await page.evaluate(({ baseRoute, currentLoc }) => {
    currentLocation = currentLoc;
    navDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
    navActiveRoute = {
      coordinates: baseRoute,
      summary: { totalDistance: 500, totalTime: 360 },
    };
    routeCandidateLayers.length = 0;
    setNavMode('navigation_active');
    _updateRemainingDistanceDisplay(currentLocation.lat, currentLocation.lon, currentLocation.accuracyMeters);
  }, { baseRoute: BASE_ROUTE, currentLoc: currentLocation });
}

test.describe('safe crossing runtime config', () => {
  test('radius=0 disables crossing search, scoring, UI features, and route expansion', async ({ page }) => {
    await bootstrapRouteCandidates(page);
    const result = await page.evaluate(async () => {
      appRuntimeConfig = {
        'navigation.safe_crossing_search_radius': 0,
        'navigation.safe_crossing_detour_ratio': 1.5
      };
      let fetchCount = 0;
      let safetyEvalCount = 0;
      const originalFetch = window.fetch;
      const originalDeps = window.__OHG_TEST_DEPS__;
      window.fetch = async (url) => {
        fetchCount += 1;
        return new Response(JSON.stringify({
          code: 'Ok',
          routes: [
            {
              distance: 100,
              duration: 60,
              geometry: { coordinates: [[139.0, 35.0], [139.001, 35.001]] },
              legs: []
            },
            {
              distance: 140,
              duration: 90,
              geometry: { coordinates: [[139.0, 35.0], [139.002, 35.001]] },
              legs: []
            }
          ]
        }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      };
      window.__OHG_TEST_DEPS__ = {
        evaluatePedestrianRouteSafety: async () => {
          safetyEvalCount += 1;
          return { status: 'unsafe', dangerousCrossings: [{ point: { lat: 35.0005, lng: 139.0005 } }] };
        },
        fetchPedestrianSafetyContext: async () => {
          throw new Error('crossing context should not be fetched when disabled');
        },
        fetchOsrmRoute: async () => {
          throw new Error('safe crossing detour should not be fetched when disabled');
        }
      };

      const routes = await fetchRouteCandidates(
        { lat: 35.0, lng: 139.0 },
        { lat: 35.001, lng: 139.001 },
        { transportMode: 'walking', maxCandidates: 3 }
      );

      window.fetch = originalFetch;
      window.__OHG_TEST_DEPS__ = originalDeps;
      return {
        count: routes.length,
        distance: routes[0]?.summary?.totalDistance,
        fetchCount,
        safetyEvalCount,
        risk: routes[0]?.__crossingRisk,
        features: routes[0]?.__routeFeatures,
        displayReason: routes[0]?.__displayReason
      };
    });

    expect(result.count).toBe(1);
    expect(result.distance).toBe(100);
    expect(result.fetchCount).toBe(1);
    expect(result.safetyEvalCount).toBe(0);
    expect(result.risk.disabled).toBe(true);
    expect(result.features.hasCrossing).toBe(false);
    expect(result.features.viaSafeCrossing).toBe(false);
    expect(result.displayReason).toBeNull();
  });

  test('radius>0 enables safe crossing candidate generation and detour ratio control', async ({ page }) => {
    await bootstrapRouteCandidates(page);
    const result = await page.evaluate(async () => {
      appRuntimeConfig = {
        'navigation.safe_crossing_search_radius': 50,
        'navigation.safe_crossing_detour_ratio': 1.5
      };
      const originalFetch = window.fetch;
      const originalDeps = window.__OHG_TEST_DEPS__;
      window.fetch = async () => new Response(JSON.stringify({
        code: 'Ok',
        routes: [{
          distance: 100,
          duration: 60,
          geometry: { coordinates: [[139.0, 35.0], [139.001, 35.001]] },
          legs: []
        }]
      }), { status: 200, headers: { 'Content-Type': 'application/json' } });
      window.__OHG_TEST_DEPS__ = {
        evaluatePedestrianRouteSafety: async (route, cached, label) => {
          if (label === 'route-candidate:0') {
            return {
              status: 'unsafe',
              crossings: [],
              dangerousCrossings: [{
                point: { lat: 35.0005, lng: 139.0005 },
                road: { tags: { highway: 'primary' } },
                classification: { dangerous: true, highway: 'primary' }
              }],
              rejectReason: 'dangerous-crossing'
            };
          }
          return { status: 'safe', crossings: [], dangerousCrossings: [] };
        },
        fetchPedestrianSafetyContext: async () => ({
          status: 'ready',
          context: {
            roads: [],
            crosswalks: [{ lat: 35.00055, lng: 139.00055, tags: { highway: 'crossing' } }]
          },
          source: 'safe-crossing-search',
          bbox: {},
          fetchedAt: Date.now()
        }),
        fetchOsrmRoute: async () => ({
          coordinates: [
            { lat: 35.0, lng: 139.0 },
            { lat: 35.00055, lng: 139.00055 },
            { lat: 35.001, lng: 139.001 }
          ],
          summary: { totalDistance: 120, totalTime: 80 },
          totalDistance: 120,
          totalTime: 80,
          instructions: []
        })
      };

      const routes = await fetchRouteCandidates(
        { lat: 35.0, lng: 139.0 },
        { lat: 35.001, lng: 139.001 },
        { transportMode: 'walking', maxCandidates: 3 }
      );

      window.fetch = originalFetch;
      window.__OHG_TEST_DEPS__ = originalDeps;
      return routes.map(route => ({
        distance: route.summary.totalDistance,
        viaSafeCrossing: route.__routeFeatures?.viaSafeCrossing,
        generatedBy: route.__routeFeatures?.generatedBy,
        hasCrossing: route.__routeFeatures?.hasCrossing
      }));
    });

    expect(result.some(route => route.viaSafeCrossing && route.generatedBy === 'safe-crossing-via')).toBe(true);
    expect(result.some(route => route.distance === 120 && route.hasCrossing)).toBe(true);
  });
});

function makeBypassAlt(overrides = {}) {
  return {
    coordinates: BYPASS_ROUTE,
    summary: { totalDistance: 480, totalTime: 400 },
    instructions: [{ text: '迂回して進む', distance: 100, latLng: { lat: 35.0001, lng: 139.0045 } }],
    totalDistance: 480,
    totalTime: 400,
    turnCount: 2,
    ...overrides
  };
}

function makeBypassDrawRouteTo() {
  return `(lat, lon, options = {}) => {
    window.__drawRouteToArgs = { lat, lon, extraWaypoints: options.extraWaypoints || [] };
    options.onRoutesAvailable({
      routes: [{
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0001, lng: 139.0045 },
          { lat: 35.0032, lng: 139.0045 },
          { lat: 35.004,  lng: 139.0 }
        ],
        summary: { totalDistance: 480, totalTime: 400 },
        instructions: [{ text: '迂回して進む', distance: 100, index: 1 }]
      }],
      selectedRouteIndex: 0,
      routeColors: ['#ff9800'],
      formatter: { formatInstruction: i => i.text, formatDistance: d => String(Math.round(d)) + 'm' },
      transportMode: 'walking',
      selectRouteIndex: () => {}
    });
    return true;
  }`;
}

test.describe('block ahead reroute regression', () => {
  test('route_preview / navigation_active 遷移で ReferenceError が出ない', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(({ baseRoute }) => {
      try {
        navDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
        navActiveRoute = { coordinates: baseRoute, summary: { totalDistance: 500, totalTime: 360 } };
        onNavRouteSelected(navActiveRoute, navDestination);
        setNavMode('navigation_active');
        return { ok: true, mode: navigationMode };
      } catch (err) {
        return { ok: false, error: String(err && err.message ? err.message : err) };
      }
    }, { baseRoute: BASE_ROUTE });
    expect(result.ok).toBe(true);
    expect(result.mode).toBe('navigation_active');
  });

  test('block ahead ボタンは active / warning のみ表示され paused では非表示', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const btn = page.locator('#nav-block-ahead-btn');

    await page.evaluate(() => setNavMode('navigation_active'));
    await expect(btn).toBeVisible();

    await page.evaluate(() => setNavMode('navigation_warning'));
    await expect(btn).toBeVisible();

    await page.evaluate(() => setNavMode('navigation_paused'));
    await expect(btn).toBeHidden();
  });

  test('ルートから 150m 超離れていると中断し元ルートを維持する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page, { currentLocation: { lat: 35.0, lon: 139.003, accuracyMeters: 5 } });
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('ルートから離れすぎています');

    const after = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      inProgress: navBlockAheadInProgress,
      hasLayer: _blockAheadLayer !== null
    }));
    expect(after.route).toBe(before);
    expect(after.inProgress).toBe(false);
    expect(after.hasLayer).toBe(false);
  });

  test('非同期処理中に stopNavigation を呼ぶと成功コールバックが無視される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ bypassAlt, blockedRoute }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => [
        { coordinates: blockedRoute, totalDistance: 320, totalTime: 240, turnCount: 0 },
        bypassAlt
      ];
      const origRenderRouteCandidatesOnMap = renderRouteCandidatesOnMap;
      renderRouteCandidatesOnMap = (...args) => {
        stopNavigation();
        return origRenderRouteCandidatesOnMap(...args);
      };
    }, { bypassAlt: makeBypassAlt(), blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());

    const state = await page.evaluate(() => ({
      mode: navigationMode,
      inProgress: navBlockAheadInProgress
    }));
    expect(state.mode).toBe('browse');
    expect(state.inProgress).toBe(false);
  });

  test('onRoutesAvailable が二重発火しても reroute success は 1 回だけ実行される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ bypassAlt, blockedRoute }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__successCount = 0;
      _fetchOsrmAlternatives = async () => [
        { coordinates: blockedRoute, totalDistance: 320, totalTime: 240, turnCount: 0 },
        bypassAlt
      ];
      const origAnnounce = voiceNav.announce;
      voiceNav.announce = (payload) => {
        if (payload && payload.id === 'block-ahead-reroute') window.__successCount++;
        origAnnounce && origAnnounce(payload);
      };
    }, { bypassAlt: makeBypassAlt(), blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());

    const count = await page.evaluate(() => window.__successCount);
    expect(count).toBe(1);
  });

  test('再ルート成功時に drawRouteTo 経由でガイダンスと音声が更新される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ bypassAlt, blockedRoute }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__renderedRouteCount = null;
      window.__drawRouteToCalled = false;
      const origRenderRouteCandidatesOnMap = renderRouteCandidatesOnMap;
      renderRouteCandidatesOnMap = (routes, routeColors, selectedRouteIndex, selectRouteIndex) => {
        window.__renderedRouteCount = Array.isArray(routes) ? routes.length : -1;
        return origRenderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
      };
      _fetchOsrmAlternatives = async () => [
        { coordinates: blockedRoute, totalDistance: 320, totalTime: 240, turnCount: 0 },
        bypassAlt
      ];
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    }, { bypassAlt: makeBypassAlt({ summary: { totalDistance: 321.5, totalTime: 278.4 } }), blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      mode: navigationMode,
      inProgress: navBlockAheadInProgress,
      remain: document.getElementById('mbc-remain-dist')?.textContent,
      summary: navActiveRoute.summary,
      stepCount: document.querySelectorAll('.route-guidance-steps li').length,
      voiceCalls: window.__voiceCalls,
      drawRouteToCalled: window.__drawRouteToCalled,
      voiceClearCount: window.__voiceClearCount,
      stepClearCount: window.__stepClearCount,
      renderedRouteCount: window.__renderedRouteCount,
      candidateLayerCount: routeCandidateLayers.length,
      hasTempLayer: _blockAheadLayer !== null,
      routeOptionButtons: document.querySelectorAll('.route-option-button').length
    }));

    expect(state.mode).toBe('navigation_active');
    expect(state.inProgress).toBe(false);
    expect(state.remain).not.toBe('—');
    expect(state.summary.totalDistance).toBe(321.5);
    expect(state.summary.totalTime).toBe(278.4);
    expect(state.stepCount).toBeGreaterThan(0);
    expect(state.drawRouteToCalled).toBe(false);
    expect(state.voiceClearCount).toBeGreaterThan(0);
    expect(state.stepClearCount).toBeGreaterThan(0);
    expect(state.renderedRouteCount).toBe(1);
    expect(state.candidateLayerCount).toBe(1);
    expect(state.hasTempLayer).toBe(false);
    expect(state.routeOptionButtons).toBe(0);
    expect(state.voiceCalls.some(v => v && v.id === 'block-ahead-reroute')).toBeTruthy();
  });

  test('最終 route が元ルートと実質同じなら no-op reroute として既存ルートを維持する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(() => {
      window.__drawRouteToCalled = false;
      // _fetchOsrmAlternatives returns same corridor — passes overlap filter but fails meaningful check
      _fetchOsrmAlternatives = async () => ([{
        coordinates: JSON.parse(JSON.stringify(navActiveRoute.coordinates)),
        totalDistance: 500,
        totalTime: 360,
        turnCount: 0
      }]);
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルート');

    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      drawRouteToCalled: window.__drawRouteToCalled,
      hasLayer: _blockAheadLayer !== null,
      inProgress: navBlockAheadInProgress
    }));

    expect(state.route).toBe(before);
    expect(state.drawRouteToCalled).toBe(false);
    expect(state.hasLayer).toBe(false);
    expect(state.inProgress).toBe(false);
  });

  test('同一路線しか返らない候補は overlap 棄却され reroute 失敗になる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate((blockedRoute) => {
      window.__drawRouteToCalled = false;
      // All alternatives overlap the block corridor
      _fetchOsrmAlternatives = async () => ([{
        coordinates: blockedRoute,
        totalDistance: 300,
        totalTime: 240,
        turnCount: 0
      }]);
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    }, BLOCKED_ROUTE);

    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));
    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルートを継続します');

    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      drawRouteToCalled: window.__drawRouteToCalled,
      hasLayer: _blockAheadLayer !== null,
      inProgress: navBlockAheadInProgress
    }));

    expect(state.route).toBe(before);
    expect(state.drawRouteToCalled).toBe(false);
    expect(state.hasLayer).toBe(false);
    expect(state.inProgress).toBe(false);
  });

  test('代替ルート取得が空なら reroute 失敗判定になる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      window.__drawRouteToCalled = false;
      _fetchOsrmAlternatives = async () => [];
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルートを継続します');

    const state = await page.evaluate(() => ({
      drawRouteToCalled: window.__drawRouteToCalled,
      hasLayer: _blockAheadLayer !== null,
      inProgress: navBlockAheadInProgress
    }));

    expect(state.drawRouteToCalled).toBe(false);
    expect(state.hasLayer).toBe(false);
    expect(state.inProgress).toBe(false);
  });

  test('回避ルート採用後にタイミングサマリーが記録される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ bypassAlt, blockedRoute }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => [
        { coordinates: blockedRoute, totalDistance: 320, totalTime: 240, turnCount: 0 },
        bypassAlt
      ];
    }, { bypassAlt: makeBypassAlt(), blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());
    const timing = await page.evaluate(() => _blockAheadLastTiming);

    expect(timing).toBeTruthy();
    expect(timing.status).toBe('success');
    expect(timing.accepted).toBe(true);
    expect(timing.alternativesEvaluated).toBeGreaterThan(0);
    expect(timing.nonBlockedCount).toBeGreaterThan(0);
    expect(timing.geometryComparison.selectedToAdopted.meanDeviationM).toBeLessThan(5);
  });

  test('採用した OSRM alternative をそのまま final route として採用し比較ログを残す', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ bypassAlt, blockedRoute }) => {
      window.__drawRouteToCalled = false;
      _fetchOsrmAlternatives = async () => [
        { coordinates: blockedRoute, totalDistance: 320, totalTime: 240, turnCount: 0 },
        bypassAlt
      ];
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    }, { bypassAlt: makeBypassAlt(), blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      drawRouteToCalled: window.__drawRouteToCalled,
      totalDistance: navActiveRoute.summary.totalDistance,
      geometryComparison: _blockAheadLastTiming.geometryComparison
    }));

    expect(state.drawRouteToCalled).toBe(false);
    expect(state.totalDistance).toBe(480);
    expect(state.geometryComparison.selectedToAdopted.meanDeviationM).toBeLessThan(5);
    expect(state.geometryComparison.adoptedToDisplayed.meanDeviationM).toBeLessThan(25);
  });

  test('複数の代替ルートから最短の非ブロック経路を採用する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      // 1st: shorter but overlaps block; 2nd: longer but avoids block
      _fetchOsrmAlternatives = async () => ([
        {
          coordinates: [
            { lat: 35.00055, lng: 139.0 },
            { lat: 35.00085, lng: 139.0 },
            { lat: 35.00115, lng: 139.0 },
            { lat: 35.004,   lng: 139.0 }
          ],
          totalDistance: 400, totalTime: 320, turnCount: 0
        },
        {
          coordinates: [
            { lat: 35.0001, lng: 139.0 },
            { lat: 35.0001, lng: 139.0045 },
            { lat: 35.0032, lng: 139.0045 },
            { lat: 35.004,  lng: 139.0 }
          ],
          summary: { totalDistance: 520, totalTime: 420 },
          instructions: [{ text: '迂回', distance: 100, latLng: { lat: 35.0001, lng: 139.0045 } }],
          totalDistance: 520, totalTime: 420, turnCount: 2
        }
      ]);
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      mode: navigationMode,
      inProgress: navBlockAheadInProgress,
      totalDistance: navActiveRoute.summary.totalDistance
    }));

    expect(state.mode).toBe('navigation_active');
    expect(state.inProgress).toBe(false);
    expect(state.totalDistance).toBe(520);
  });

  test('stage1 で有効ルートがなくても stage2 で前方コリドーを後方拡張して成功できる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute, bypassAlt }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__altFetchCount = 0;
      _fetchOsrmAlternatives = async () => {
        window.__altFetchCount += 1;
        if (window.__altFetchCount === 1) {
          return [{
            coordinates: blockedRoute,
            totalDistance: 320,
            totalTime: 240,
            turnCount: 0
          }];
        }
        return [bypassAlt];
      };
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = { lat, lon, extraWaypoints: options.extraWaypoints || [] };
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0001, lng: 139.0045 },
              { lat: 35.0032, lng: 139.0045 },
              { lat: 35.004, lng: 139.0 }
            ],
            summary: { totalDistance: 480, totalTime: 400 },
            instructions: [{ text: '迂回して進む', distance: 100, index: 1 }]
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => String(Math.round(d)) + 'm' },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    }, { blockedRoute: BLOCKED_ROUTE, bypassAlt: makeBypassAlt() });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      altFetchCount: window.__altFetchCount,
      timing: _blockAheadLastTiming
    }));

    expect(state.altFetchCount).toBe(2);
    expect(state.timing.acceptedStage).toBe('stage2');
    expect(state.timing.attemptedStages).toEqual(['stage1', 'stage2']);
  });

  test('stage1/stage2 に branch-like な有効 alternative があれば escape fallback に入る前に採用する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      const branchAlt = {
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0010, lng: 139.0045 },
          { lat: 35.0030, lng: 139.0045 },
          { lat: 35.0040, lng: 139.0 }
        ],
        summary: { totalDistance: 430, totalTime: 320 },
        instructions: [{ text: '右の脇道へ進む', distance: 90, latLng: { lat: 35.0010, lng: 139.0045 } }],
        totalDistance: 430,
        totalTime: 320,
        turnCount: 1
      };
      window.__escapeLegCalled = 0;
      window.__escapeCalled = 0;
      _fetchOsrmAlternatives = async () => ([
        { coordinates: blockedRoute, totalDistance: 320, totalTime: 240, turnCount: 0 },
        branchAlt
      ]);
      _generateEscapeLegPoints = async () => {
        window.__escapeLegCalled += 1;
        return [];
      };
      _generateEscapePoints = async () => {
        window.__escapeCalled += 1;
        return [];
      };
    }, { blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      acceptedStage: _blockAheadLastTiming?.acceptedStage,
      attemptedStages: _blockAheadLastTiming?.attemptedStages,
      totalDistance: navActiveRoute.summary.totalDistance,
      escapeLegCalled: window.__escapeLegCalled,
      escapeCalled: window.__escapeCalled
    }));

    expect(state.acceptedStage).toBe('stage1');
    expect(state.attemptedStages).toEqual(['stage1']);
    expect(state.totalDistance).toBe(430);
    expect(state.escapeLegCalled).toBe(0);
    expect(state.escapeCalled).toBe(0);
  });

  test('stage2/stage3 の OSRM alternatives パラメータは 3 に固定される', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(async () => {
      const urls = [];
      const originalFetch = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const url = String(input);
        if (url.includes('/osrm/walking/route/v1/')) {
          urls.push(url);
          return new Response(JSON.stringify({
            code: 'Ok',
            routes: [{
              distance: 100,
              duration: 80,
              geometry: { coordinates: [[139.0, 35.0], [139.001, 35.001]] },
              legs: []
            }]
          }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        return originalFetch(input, init);
      };
      await _fetchOsrmAlternatives({ lat: 35.0, lng: 139.0 }, { lat: 35.001, lng: 139.001 }, 5, 'stage3');
      window.fetch = originalFetch;
      return urls;
    });

    expect(state.length).toBe(1);
    expect(state[0]).toContain('alternatives=3');
    expect(state[0]).not.toContain('alternatives=5');
  });

  test('全 stage 失敗時は escape-point fallback で迂回ルートを直接採用できる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute, bypassAlt }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__altFetchCount = 0;
      window.__escapeLegFetchCount = 0;
      window.__escapeFetchCount = 0;
      window.__drawRouteToCalled = false;
      _fetchOsrmAlternatives = async () => {
        window.__altFetchCount += 1;
        return [{
          coordinates: blockedRoute,
          totalDistance: 320,
          totalTime: 240,
          turnCount: 0
        }];
      };
      _generateEscapeLegPoints = () => ([
        { label: 'leg-left-30', point: { lat: 35.0001, lng: 139.0012 } }
      ]);
      _generateEscapePoints = () => ([
        { label: 'left-60', point: { lat: 35.0001, lng: 139.0012 } },
        { label: 'right-60', point: { lat: 35.0001, lng: 139.0045 } }
      ]);
      _fetchOsrmRouteThroughWaypoints = async (waypoints) => {
        if (Array.isArray(waypoints) && waypoints.length === 2) {
          window.__escapeLegFetchCount += 1;
          return {
            coordinates: blockedRoute,
            totalDistance: 90,
            totalTime: 70,
            turnCount: 0
          };
        }
        window.__escapeFetchCount += 1;
        return bypassAlt;
      };
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    }, { blockedRoute: BLOCKED_ROUTE, bypassAlt: makeBypassAlt() });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      altFetchCount: window.__altFetchCount,
      escapeLegFetchCount: window.__escapeLegFetchCount,
      escapeFetchCount: window.__escapeFetchCount,
      drawRouteToCalled: window.__drawRouteToCalled,
      totalDistance: navActiveRoute.summary.totalDistance,
      timing: _blockAheadLastTiming
    }));

    expect(state.altFetchCount).toBe(3);
    expect(state.escapeLegFetchCount).toBeGreaterThan(0);
    expect(state.escapeFetchCount).toBeGreaterThan(0);
    expect(state.drawRouteToCalled).toBe(false);
    expect(state.totalDistance).toBe(480);
    expect(state.timing.acceptedStage).toBe('escape');
    expect(state.timing.attemptedStages).toEqual(['stage1', 'stage2', 'stage3', 'escape-leg', 'escape']);
  });

  test('async な escape 候補生成を待ってから fallback 判定する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute, bypassAlt }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => ([{
        coordinates: blockedRoute,
        totalDistance: 320,
        totalTime: 240,
        turnCount: 0
      }]);
      _generateEscapeLegPoints = async () => [];
      _generateEscapePoints = async () => {
        await new Promise(resolve => setTimeout(resolve, 30));
        return [{ label: 'right-60', point: { lat: 35.0001, lng: 139.0045 } }];
      };
      _fetchOsrmRouteThroughWaypoints = async () => bypassAlt;
    }, { blockedRoute: BLOCKED_ROUTE, bypassAlt: makeBypassAlt() });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      acceptedStage: _blockAheadLastTiming?.acceptedStage,
      attemptedStages: _blockAheadLastTiming?.attemptedStages
    }));

    expect(state.acceptedStage).toBe('escape');
    expect(state.attemptedStages).toEqual(['stage1', 'stage2', 'stage3', 'escape']);
  });

  test('escape 候補は raw offset ではなく road-node に snap して blocked 外のみ残す', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const state = await page.evaluate(async () => {
      const coords = navActiveRoute.coordinates;
      const blockedArea = {
        centers: [{ lat: 35.0002, lng: 139.0002, radius: 20 }],
        nearRejectMeters: 10
      };
      const rawCandidates = [
        { label: 'good-a', point: { lat: 35.0001, lng: 139.001 } },
        { label: 'good-b', point: { lat: 35.0002, lng: 139.0011 } },
        { label: 'bad-same-corridor', point: { lat: 35.0001, lng: 139.0 } }
      ];
      const originalNearest = _fetchOsrmNearestNode;
      _fetchOsrmNearestNode = async (point) => {
        if ((point.lng ?? point.lon) > 139.00105) {
          return { lat: 35.0001, lng: 139.0062, distanceM: 6 };
        }
        if ((point.lng ?? point.lon) > 139.001) {
          return { lat: 35.0013, lng: 139.00625, distanceM: 7 };
        }
        return { lat: 35.0002, lng: 139.0, distanceM: 4 };
      };
      const snapped = await _snapEscapeCandidatesToRoadNodes(rawCandidates, blockedArea, coords, 'escape-test');
      _fetchOsrmNearestNode = originalNearest;
      return snapped.map(candidate => ({
        label: candidate.label,
        point: candidate.point,
        blockedDistanceM: candidate.blockedDistanceM,
        corridorDistanceM: candidate.corridorDistanceM,
        nodeType: candidate.nodeType,
        nodeScore: candidate.nodeScore
      }));
    });

    expect(state.length).toBeGreaterThan(0);
    expect(state.some(candidate => candidate.label.startsWith('good-b'))).toBeTruthy();
    expect(state.some(candidate => candidate.point.lng > 139.006)).toBeTruthy();
    expect(state.every(candidate => candidate.blockedDistanceM > 0)).toBeTruthy();
    expect(state.every(candidate => candidate.corridorDistanceM >= 18)).toBeTruthy();
    expect(state.some(candidate => candidate.nodeType === 'side-road')).toBeTruthy();
    expect(state.every(candidate => candidate.nodeScore > 0)).toBeTruthy();
  });

  test('snap 後の近接候補でも tier/depth が違えば dedupe で保持される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const state = await page.evaluate(async () => {
      const coords = navActiveRoute.coordinates;
      const blockedArea = {
        centers: [{ lat: 35.0002, lng: 139.0002, radius: 20 }],
        nearRejectMeters: 10
      };
      const rawCandidates = [
        { label: 'right-30', point: { lat: 35.0001, lng: 139.001 }, side: 'right', distanceTierM: 30, lateralM: 30, depthKind: 'entrance' },
        { label: 'right-60', point: { lat: 35.0001, lng: 139.0012 }, side: 'right', distanceTierM: 60, lateralM: 60, depthKind: 'entrance' }
      ];
      const originalNearest = _fetchOsrmNearestNode;
      _fetchOsrmNearestNode = async () => ({ lat: 35.0013, lng: 139.0062, distanceM: 6 });
      const snapped = await _snapEscapeCandidatesToRoadNodes(rawCandidates, blockedArea, coords, 'escape-dedupe-test');
      _fetchOsrmNearestNode = originalNearest;
      return snapped.map(candidate => ({
        label: candidate.label,
        tier: candidate.distanceTierM,
        depth: candidate.depthKind
      }));
    });

    expect(state.length).toBeGreaterThan(1);
    expect(state.some(candidate => candidate.tier === 30)).toBeTruthy();
    expect(state.some(candidate => candidate.tier === 60)).toBeTruthy();
  });

  test('escape spec selection は left/right/back-left/back-right を偏らせずに残す', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const specs = [
        { side: 'left', lateralM: 60, backwardM: 0, label: 'left-60' },
        { side: 'right', lateralM: 60, backwardM: 0, label: 'right-60' },
        { side: 'left', lateralM: 120, backwardM: 0, label: 'left-120' },
        { side: 'right', lateralM: 120, backwardM: 0, label: 'right-120' },
        { side: 'left', lateralM: 60, backwardM: 25, label: 'back-left-60' },
        { side: 'right', lateralM: 60, backwardM: 25, label: 'back-right-60' },
        { side: 'left', lateralM: 150, backwardM: 25, label: 'back-left-150' },
        { side: 'right', lateralM: 150, backwardM: 25, label: 'back-right-150' }
      ];
      const selected = _selectBalancedEscapeSpecs(specs, 6);
      const counts = selected.reduce((acc, spec) => {
        const key = (spec.backwardM || 0) > 0 ? `back-${spec.side}` : spec.side;
        acc[key] = (acc[key] || 0) + 1;
        return acc;
      }, {});
      return { labels: selected.map(spec => spec.label), counts };
    });

    expect(state.labels.length).toBe(6);
    expect(state.counts.left).toBeGreaterThan(0);
    expect(state.counts.right).toBeGreaterThan(0);
    expect(state.counts['back-left']).toBeGreaterThan(0);
    expect(state.counts['back-right']).toBeGreaterThan(0);
  });

  test('escape gate により現在地近くの sideways raw candidate は即 inside 扱いされにくくなる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const state = await page.evaluate(() => {
      const coords = navActiveRoute.coordinates;
      const projection = _navFindClosestOnRoute(coords, currentLocation.lat, currentLocation.lon);
      const blockedArea = _buildBlockedArea(coords, projection, {
        startM: 20,
        endM: 180,
        backwardM: 0,
        baseRadiusM: 50,
        intersectionBufferM: 40
      });
      const gatedArea = _buildEscapeGateBlockedArea(coords, projection, blockedArea, 'escape-gate-test');
      const headingTarget = _walkAlongRoute(coords, projection, 20);
      const headingUnit = _headingUnitVectorMeters(projection.snappedPoint, headingTarget);
      const leftPoint = _buildEscapePoint(projection.snappedPoint, headingUnit, 'left', 30, 0);
      return {
        blockedBefore: _distancePointToBlockedArea(leftPoint, blockedArea, blockedArea.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS),
        blockedAfter: _distancePointToBlockedArea(leftPoint, gatedArea, gatedArea.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS),
        gateCount: Array.isArray(gatedArea.escapeGates) ? gatedArea.escapeGates.length : 0
      };
    });

    expect(state.gateCount).toBeGreaterThan(0);
    expect(state.blockedBefore).toBeLessThanOrEqual(0);
    expect(state.blockedAfter).toBeGreaterThan(0);
  });

  test('escape-leg の先頭 prefix は side-specific gate carve-out で判定し、その後は通常 blocked area に戻す', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const state = await page.evaluate(() => {
      const coords = navActiveRoute.coordinates;
      const projection = _navFindClosestOnRoute(coords, currentLocation.lat, currentLocation.lon);
      const blockedArea = _buildBlockedArea(coords, projection, {
        startM: 20,
        endM: 180,
        backwardM: 0,
        baseRadiusM: 50,
        intersectionBufferM: 40
      });
      const gatedArea = _buildEscapeGateBlockedArea(coords, projection, blockedArea, 'escape-leg-prefix-test');
      const leftGated = _buildSideSpecificEscapeBlockedArea(gatedArea, 'left', 'escape-leg-prefix-left');
      const headingTarget = _walkAlongRoute(coords, projection, 20);
      const headingUnit = _headingUnitVectorMeters(projection.snappedPoint, headingTarget);
      const prefixPoint = _buildEscapePoint(projection.snappedPoint, headingUnit, 'left', 30, 0);
      const rightPoint = _buildEscapePoint(projection.snappedPoint, headingUnit, 'right', 30, 0);
      const prefixRoute = [
        projection.snappedPoint,
        prefixPoint,
        _buildEscapePoint(projection.snappedPoint, headingUnit, 'left', 55, 0)
      ];
      const suffixRoute = [
        _buildEscapePoint(projection.snappedPoint, headingUnit, 'left', 55, 0),
        { lat: projection.snappedPoint.lat + 0.0015, lng: projection.snappedPoint.lng }
      ];
      return {
        leftGateCount: Array.isArray(leftGated.escapeGates) ? leftGated.escapeGates.length : 0,
        rightBlockedInLeftGate: _distancePointToBlockedArea(rightPoint, leftGated, leftGated.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS),
        prefixBefore: _routeBlockedAreaStats(prefixRoute, blockedArea),
        prefixAfter: _routeBlockedAreaStats(prefixRoute, leftGated),
        suffixAfter: _routeBlockedAreaStats(suffixRoute, blockedArea)
      };
    });

    expect(state.leftGateCount).toBeGreaterThan(0);
    expect(state.rightBlockedInLeftGate).toBeLessThanOrEqual(0);
    expect(state.prefixAfter.nearBlockedRatio).toBeLessThanOrEqual(state.prefixBefore.nearBlockedRatio);
    expect(state.prefixAfter.strictOverlapRatio).toBeLessThanOrEqual(state.prefixBefore.strictOverlapRatio);
    expect(state.prefixAfter.nearBlocked).toBeFalsy();
    expect(typeof state.suffixAfter.nearBlocked).toBe('boolean');
  });

  test('全 stage 失敗時でも escape-leg fallback で現在地から即時迂回を採用できる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute, bypassAlt }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__altFetchCount = 0;
      window.__escapeLegFetchCount = 0;
      window.__escapeFetchCount = 0;
      _fetchOsrmAlternatives = async () => {
        window.__altFetchCount += 1;
        return [{
          coordinates: blockedRoute,
          totalDistance: 320,
          totalTime: 240,
          turnCount: 0
        }];
      };
      _generateEscapeLegPoints = () => ([
        { label: 'leg-right-30', point: { lat: 35.0001, lng: 139.0100 }, side: 'right' }
      ]);
      _generateEscapePoints = () => {
        window.__escapePointsCalled = true;
        return [];
      };
      _fetchOsrmRouteThroughWaypoints = async (waypoints) => {
        window.__escapeLegFetchCount += 1;
        if (Array.isArray(waypoints) && waypoints.length === 2 && Math.abs((waypoints[0].lng ?? waypoints[0].lon) - 139.0) < 0.0001) {
          return {
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0001, lng: 139.0070 },
              { lat: 35.0001, lng: 139.0100 }
            ],
            totalDistance: 180,
            totalTime: 130,
            turnCount: 1
          };
        }
        if (Array.isArray(waypoints) && waypoints.length === 2) {
          return {
            coordinates: [
              { lat: 35.0001, lng: 139.0100 },
              { lat: 35.0032, lng: 139.0100 },
              { lat: 35.004,  lng: 139.0 }
            ],
            summary: { totalDistance: 300, totalTime: 250 },
            instructions: [{ text: '迂回して進む', distance: 100, latLng: { lat: 35.0032, lng: 139.0100 } }],
            totalDistance: 300,
            totalTime: 250,
            turnCount: 1
          };
        }
        return bypassAlt;
      };
      const originalStats = _routeBlockedAreaStats;
      const originalDistance = _distancePointToBlockedArea;
      _routeBlockedAreaStats = (coords, blockedArea) => {
        const firstLng = Array.isArray(coords) && coords.length > 0 ? (coords[0].lng ?? coords[0].lon) : null;
        const lastLng = Array.isArray(coords) && coords.length > 0 ? (coords[coords.length - 1].lng ?? coords[coords.length - 1].lon) : null;
        if (Array.isArray(coords)
            && coords.length === 2
            && firstLng != null
            && lastLng != null
            && firstLng < 139.001
            && lastLng < 139.002) {
          return {
            strictOverlapRatio: 0,
            nearBlockedRatio: 0,
            minDistanceToAreaM: 12,
            intersects: false,
            nearBlocked: false
          };
        }
        if (Array.isArray(coords)
            && coords.length >= 2
            && firstLng != null
            && lastLng != null
            && firstLng < 139.001
            && lastLng > 139.006) {
          return {
            strictOverlapRatio: 0,
            nearBlockedRatio: 0,
            minDistanceToAreaM: 12,
            intersects: false,
            nearBlocked: false
          };
        }
        return originalStats(coords, blockedArea);
      };
      _distancePointToBlockedArea = (point, blockedArea, nearRejectMeters) => {
        const lng = point?.lng ?? point?.lon;
        if (typeof lng === 'number' && lng > 139.006) return 12;
        return originalDistance(point, blockedArea, nearRejectMeters);
      };
      window.__restoreBlockedStats = () => {
        _routeBlockedAreaStats = originalStats;
        _distancePointToBlockedArea = originalDistance;
      };
    }, { blockedRoute: BLOCKED_ROUTE, bypassAlt: makeBypassAlt() });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      altFetchCount: window.__altFetchCount,
      escapeLegFetchCount: window.__escapeLegFetchCount,
      escapeFetchCount: window.__escapeFetchCount,
      timing: _blockAheadLastTiming,
      totalDistance: navActiveRoute.summary.totalDistance
    }));
    await page.evaluate(() => window.__restoreBlockedStats && window.__restoreBlockedStats());

    expect(state.altFetchCount).toBe(3);
    expect(state.escapeLegFetchCount).toBeGreaterThan(1);
    expect(state.escapeFetchCount || 0).toBe(0);
    expect(state.totalDistance).toBe(480);
    expect(state.timing.acceptedStage).toBe('escape-leg');
    expect(state.timing.attemptedStages).toEqual(['stage1', 'stage2', 'stage3', 'escape-leg']);
  });

  test('escape-leg は短い距離から試しつつ blocked 脱出できる長さを優先採用する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute, bypassAlt }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => ([{
        coordinates: blockedRoute,
        totalDistance: 320,
        totalTime: 240,
        turnCount: 0
      }]);
      _generateEscapeLegPoints = async () => ([
        { label: 'leg-right-30', point: { lat: 35.0001, lng: 139.0040 }, side: 'right', lateralM: 30, nodeType: 'corridor-like', nodeScore: 20 },
        { label: 'leg-right-90', point: { lat: 35.0001, lng: 139.0108 }, side: 'right', lateralM: 90, nodeType: 'side-road', nodeScore: 120 }
      ]);
      _generateEscapePoints = async () => [];
      _fetchOsrmRouteThroughWaypoints = async (waypoints) => {
        if (Array.isArray(waypoints) && waypoints.length === 2
            && Math.abs((waypoints[0].lng ?? waypoints[0].lon) - 139.0) < 0.0001
            && waypoints[1].lng < 139.005) {
          return {
            coordinates: blockedRoute,
            totalDistance: 120,
            totalTime: 100,
            turnCount: 1
          };
        }
        if (Array.isArray(waypoints) && waypoints.length === 2) {
          if (Math.abs((waypoints[0].lng ?? waypoints[0].lon) - 139.0) < 0.0001) {
            return {
              coordinates: [
                { lat: 35.0001, lng: 139.0 },
                { lat: 35.0001, lng: 139.0080 },
                { lat: 35.0001, lng: 139.0108 }
              ],
              totalDistance: 180,
              totalTime: 150,
              turnCount: 1
            };
          }
          return {
            coordinates: [
              { lat: 35.0001, lng: 139.0108 },
              { lat: 35.0032, lng: 139.0108 },
              { lat: 35.004,  lng: 139.0 }
            ],
            summary: { totalDistance: 300, totalTime: 250 },
            instructions: [{ text: '脇道から進む', distance: 80, latLng: { lat: 35.0032, lng: 139.0108 } }],
            totalDistance: 300,
            totalTime: 250,
            turnCount: 1
          };
        }
        return bypassAlt;
      };
      const originalStats = _routeBlockedAreaStats;
      const originalDistance = _distancePointToBlockedArea;
      _routeBlockedAreaStats = (coords, blockedArea) => {
        const firstLng = Array.isArray(coords) && coords.length > 0 ? (coords[0].lng ?? coords[0].lon) : null;
        const lastLng = Array.isArray(coords) && coords.length > 0 ? (coords[coords.length - 1].lng ?? coords[coords.length - 1].lon) : null;
        if (Array.isArray(coords)
            && coords.length === 2
            && firstLng != null
            && lastLng != null
            && firstLng < 139.001
            && lastLng < 139.002) {
          return {
            strictOverlapRatio: 0,
            nearBlockedRatio: 0,
            minDistanceToAreaM: 12,
            intersects: false,
            nearBlocked: false
          };
        }
        if (Array.isArray(coords)
            && coords.length >= 2
            && firstLng != null
            && lastLng != null
            && firstLng < 139.001
            && lastLng > 139.006) {
          return {
            strictOverlapRatio: 0,
            nearBlockedRatio: 0,
            minDistanceToAreaM: 12,
            intersects: false,
            nearBlocked: false
          };
        }
        return originalStats(coords, blockedArea);
      };
      _distancePointToBlockedArea = (point, blockedArea, nearRejectMeters) => {
        const lng = point?.lng ?? point?.lon;
        if (typeof lng === 'number' && lng > 139.006) return 12;
        return originalDistance(point, blockedArea, nearRejectMeters);
      };
      window.__restoreBlockedStats = () => {
        _routeBlockedAreaStats = originalStats;
        _distancePointToBlockedArea = originalDistance;
      };
    }, { blockedRoute: BLOCKED_ROUTE, bypassAlt: makeBypassAlt() });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      acceptedStage: _blockAheadLastTiming?.acceptedStage,
      routeDistance: navActiveRoute.summary.totalDistance
    }));
    await page.evaluate(() => window.__restoreBlockedStats && window.__restoreBlockedStats());

    expect(state.acceptedStage).toBe('escape-leg');
    expect(state.routeDistance).toBe(480);
  });

  test('escape-leg main-route は overlap=0 かつ strict が低ければ near だけでは棄却しない', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute, bypassAlt }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => ([{
        coordinates: blockedRoute,
        totalDistance: 320,
        totalTime: 240,
        turnCount: 0
      }]);
      _generateEscapeLegPoints = async () => ([
        { label: 'leg-right-60', point: { lat: 35.0001, lng: 139.0100 }, side: 'right', lateralM: 60, distanceTierM: 60, depthKind: 'entrance', nodeType: 'side-road', nodeScore: 120 }
      ]);
      _generateEscapePoints = async () => [];
      _fetchOsrmRouteThroughWaypoints = async (waypoints) => {
        if (Array.isArray(waypoints) && waypoints.length === 2
            && Math.abs((waypoints[0].lng ?? waypoints[0].lon) - 139.0) < 0.0001) {
          return {
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0001, lng: 139.0074 },
              { lat: 35.0001, lng: 139.0100 }
            ],
            totalDistance: 170,
            totalTime: 120,
            turnCount: 1
          };
        }
        return {
          coordinates: [
            { lat: 35.0001, lng: 139.0100 },
            { lat: 35.0015, lng: 139.0100 },
            { lat: 35.0032, lng: 139.0100 },
            { lat: 35.0040, lng: 139.0100 }
          ],
          summary: { totalDistance: 290, totalTime: 240 },
          instructions: [{ text: '脇道を進む', distance: 100, latLng: { lat: 35.0032, lng: 139.0100 } }],
          totalDistance: 290,
          totalTime: 240,
          turnCount: 1
        };
      };
      const originalStats = _routeBlockedAreaStats;
      const originalDistance = _distancePointToBlockedArea;
      _routeBlockedAreaStats = (coords, blockedArea) => {
        const firstLng = Array.isArray(coords) && coords.length > 0 ? (coords[0].lng ?? coords[0].lon) : null;
        const lastLng = Array.isArray(coords) && coords.length > 0 ? (coords[coords.length - 1].lng ?? coords[coords.length - 1].lon) : null;
        if (Array.isArray(coords)
            && coords.length === 2
            && firstLng != null
            && lastLng != null
            && firstLng < 139.001
            && lastLng < 139.002) {
          return {
            strictOverlapRatio: 0,
            nearBlockedRatio: 0,
            minDistanceToAreaM: 12,
            intersects: false,
            nearBlocked: false
          };
        }
        if (Array.isArray(coords)
            && coords.length >= 2
            && firstLng != null
            && lastLng != null
            && firstLng < 139.001
            && lastLng > 139.006) {
          return {
            strictOverlapRatio: 0,
            nearBlockedRatio: 0,
            minDistanceToAreaM: 12,
            intersects: false,
            nearBlocked: false
          };
        }
        if (Array.isArray(coords) && coords.length === 4 && Math.abs((coords[0].lng ?? coords[0].lon) - 139.0100) < 0.0001) {
          return {
            strictOverlapRatio: 0.18,
            nearBlockedRatio: 0.23,
            minDistanceToAreaM: 4,
            intersects: false,
            nearBlocked: true
          };
        }
        return originalStats(coords, blockedArea);
      };
      _distancePointToBlockedArea = (point, blockedArea, nearRejectMeters) => {
        const lng = point?.lng ?? point?.lon;
        if (typeof lng === 'number' && lng > 139.006) return 12;
        return originalDistance(point, blockedArea, nearRejectMeters);
      };
      window.__restoreBlockedStats = () => {
        _routeBlockedAreaStats = originalStats;
        _distancePointToBlockedArea = originalDistance;
      };
    }, { blockedRoute: BLOCKED_ROUTE, bypassAlt: makeBypassAlt() });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      acceptedStage: _blockAheadLastTiming?.acceptedStage,
      totalDistance: navActiveRoute.summary.totalDistance
    }));
    await page.evaluate(() => window.__restoreBlockedStats && window.__restoreBlockedStats());

    expect(state.acceptedStage).toBe('escape-leg');
    expect(state.totalDistance).toBe(460);
  });

  test('escape fallback route も overlap が実質 0 かつ strict が低ければ near だけでは棄却しない', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => ([{
        coordinates: blockedRoute,
        totalDistance: 320,
        totalTime: 240,
        turnCount: 0
      }]);
      _generateEscapeLegPoints = async () => [];
      _generateEscapePoints = async () => ([
        { label: 'escape-right-90', point: { lat: 35.0001, lng: 139.0046 }, distanceTierM: 90, depthKind: 'deeper-30', nodeType: 'side-road', nodeScore: 160 }
      ]);
      _fetchOsrmRouteThroughWaypoints = async () => ({
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0001, lng: 139.0046 },
          { lat: 35.0020, lng: 139.0046 },
          { lat: 35.0040, lng: 139.0046 }
        ],
        summary: { totalDistance: 510, totalTime: 360 },
        instructions: [{ text: '脇道から進む', distance: 120, latLng: { lat: 35.0020, lng: 139.0046 } }],
        totalDistance: 510,
        totalTime: 360,
        turnCount: 1
      });
      const originalStats = _routeBlockedAreaStats;
      _routeBlockedAreaStats = (coords, blockedArea) => {
        if (Array.isArray(coords) && coords.length === 4 && Math.abs((coords[1].lng ?? coords[1].lon) - 139.0046) < 0.0001) {
          return {
            strictOverlapRatio: 0.29,
            nearBlockedRatio: 0.33,
            minDistanceToAreaM: 6,
            intersects: false,
            nearBlocked: true
          };
        }
        return originalStats(coords, blockedArea);
      };
      window.__restoreBlockedStats = () => { _routeBlockedAreaStats = originalStats; };
    }, { blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      acceptedStage: _blockAheadLastTiming?.acceptedStage,
      totalDistance: navActiveRoute.summary.totalDistance
    }));
    await page.evaluate(() => window.__restoreBlockedStats && window.__restoreBlockedStats());

    expect(state.acceptedStage).toBe('escape');
    expect(state.totalDistance).toBe(510);
  });

  test('side-road entrance より deeper node を優先できる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const state = await page.evaluate(async () => {
      const coords = navActiveRoute.coordinates;
      const blockedArea = {
        centers: [{ lat: 35.0002, lng: 139.0002, radius: 20 }],
        nearRejectMeters: 10
      };
      const rawCandidates = [
        { label: 'entrance', point: { lat: 35.0001, lng: 139.0011 }, side: 'right', distanceTierM: 60, lateralM: 60, depthKind: 'entrance' }
      ];
      const originalNearest = _fetchOsrmNearestNode;
      let call = 0;
      _fetchOsrmNearestNode = async () => {
        call += 1;
        if (call === 1) return { lat: 35.0012, lng: 139.0060, distanceM: 4 };
        if (call === 2) return { lat: 35.0015, lng: 139.0063, distanceM: 5 };
        if (call === 3) return { lat: 35.0018, lng: 139.0066, distanceM: 6 };
        if (call === 4) return { lat: 35.0021, lng: 139.0069, distanceM: 7 };
        return { lat: 35.0024, lng: 139.0072, distanceM: 8 };
      };
      const snapped = await _snapEscapeCandidatesToRoadNodes(rawCandidates, blockedArea, coords, 'escape-depth-test');
      _fetchOsrmNearestNode = originalNearest;
      return snapped.map(candidate => ({
        label: candidate.label,
        depth: candidate.depthKind,
        score: candidate.nodeScore
      }));
    });

    expect(state.length).toBeGreaterThan(1);
    expect(state[0].depth).toBe('deeper-120');
    expect(state[0].score).toBeGreaterThan(state[state.length - 1].score);
  });

  test('escape fallback は deeper node に対して hold-waypoint mode を使って side-road を維持できる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__escapeWaypointLengths = [];
      _fetchOsrmAlternatives = async () => ([{
        coordinates: blockedRoute,
        totalDistance: 320,
        totalTime: 240,
        turnCount: 0
      }]);
      _generateEscapeLegPoints = async () => [];
      _generateEscapePoints = async () => ([
        {
          label: 'escape-right-120-deep',
          point: { lat: 35.0001, lng: 139.0054 },
          holdWaypoint: { lat: 35.0001, lng: 139.0046 },
          distanceTierM: 120,
          depthKind: 'deeper-120',
          nodeType: 'side-road',
          nodeScore: 220,
          blockedDistanceM: 55
        }
      ]);
      _fetchOsrmRouteThroughWaypoints = async (waypoints) => {
        window.__escapeWaypointLengths.push(Array.isArray(waypoints) ? waypoints.length : -1);
        return {
          coordinates: [
            { lat: 35.0001, lng: 139.0 },
            { lat: 35.0001, lng: 139.0046 },
            { lat: 35.0001, lng: 139.0054 },
            { lat: 35.0020, lng: 139.0054 },
            { lat: 35.0040, lng: 139.0054 }
          ],
          summary: { totalDistance: 540, totalTime: 380 },
          instructions: [{ text: '脇道を進む', distance: 140, latLng: { lat: 35.0020, lng: 139.0054 } }],
          totalDistance: 540,
          totalTime: 380,
          turnCount: 1
        };
      };
      const originalStats = _routeBlockedAreaStats;
      _routeBlockedAreaStats = (coords, blockedArea) => {
        if (Array.isArray(coords) && coords.length === 5 && Math.abs((coords[2].lng ?? coords[2].lon) - 139.0054) < 0.0001) {
          return {
            strictOverlapRatio: 0.12,
            nearBlockedRatio: 0.20,
            minDistanceToAreaM: 8,
            intersects: false,
            nearBlocked: true
          };
        }
        return originalStats(coords, blockedArea);
      };
      window.__restoreBlockedStats = () => { _routeBlockedAreaStats = originalStats; };
    }, { blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      acceptedStage: _blockAheadLastTiming?.acceptedStage,
      waypointLengths: window.__escapeWaypointLengths,
      totalDistance: navActiveRoute.summary.totalDistance
    }));
    await page.evaluate(() => window.__restoreBlockedStats && window.__restoreBlockedStats());

    expect(state.acceptedStage).toBe('escape');
    expect(state.waypointLengths).toContain(4);
    expect(state.totalDistance).toBe(540);
  });

  test('long-detour escape generation は farther tiers と deeper nodes を含めて探索できる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const state = await page.evaluate(async () => {
      const coords = navActiveRoute.coordinates;
      const projection = _navFindClosestOnRoute(coords, currentLocation.lat, currentLocation.lon);
      const blockedArea = {
        centers: [{ lat: 35.0002, lng: 139.0002, radius: 20 }],
        nearRejectMeters: 10
      };
      const originalNearest = _fetchOsrmNearestNode;
      let call = 0;
      _fetchOsrmNearestNode = async () => {
        call += 1;
        return {
          lat: 35.0010 + (call * 0.00018),
          lng: 139.0060 + (call * 0.00028),
          distanceM: 5
        };
      };
      const points = await _generateLongDetourEscapePoints(coords, projection, blockedArea);
      _fetchOsrmNearestNode = originalNearest;
      return points.map(point => ({
        label: point.label,
        tier: point.distanceTierM,
        depth: point.depthKind,
        side: point.side,
        hasSecondaryHold: !!point.secondaryHoldWaypoint
      }));
    });

    expect(state.some(point => point.tier === 150)).toBeTruthy();
    expect(state.some(point => point.tier === 200)).toBeTruthy();
    expect(state.some(point => point.depth === 'deeper-200')).toBeTruthy();
    expect(state.some(point => point.side === 'left')).toBeTruthy();
    expect(state.some(point => point.side === 'right')).toBeTruthy();
    expect(state.some(point => point.hasSecondaryHold)).toBeTruthy();
  });

  test('holdWaypointMode route は overlap が低く strict が 0.35 未満なら near-penalty で通る', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(({ blockedRoute }) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => ([{
        coordinates: blockedRoute,
        totalDistance: 320,
        totalTime: 240,
        turnCount: 0
      }]);
      _generateEscapeLegPoints = async () => [];
      _generateEscapePoints = async () => ([
        {
          label: 'escape-right-120-deep',
          point: { lat: 35.0001, lng: 139.0054 },
          holdWaypoint: { lat: 35.0001, lng: 139.0046 },
          distanceTierM: 120,
          depthKind: 'deeper-120',
          nodeType: 'side-road',
          nodeScore: 220,
          blockedDistanceM: 55
        }
      ]);
      _fetchOsrmRouteThroughWaypoints = async () => ({
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0001, lng: 139.0046 },
          { lat: 35.0001, lng: 139.0054 },
          { lat: 35.0020, lng: 139.0054 },
          { lat: 35.0040, lng: 139.0054 }
        ],
        summary: { totalDistance: 540, totalTime: 380 },
        instructions: [{ text: '脇道を進む', distance: 140, latLng: { lat: 35.0020, lng: 139.0054 } }],
        totalDistance: 540,
        totalTime: 380,
        turnCount: 1
      });
      const originalStats = _routeBlockedAreaStats;
      _routeBlockedAreaStats = (coords, blockedArea) => {
        if (Array.isArray(coords) && coords.length === 5 && Math.abs((coords[2].lng ?? coords[2].lon) - 139.0054) < 0.0001) {
          return {
            strictOverlapRatio: 0.34,
            nearBlockedRatio: 0.28,
            minDistanceToAreaM: 1,
            intersects: false,
            nearBlocked: true
          };
        }
        return originalStats(coords, blockedArea);
      };
      window.__restoreBlockedStats = () => { _routeBlockedAreaStats = originalStats; };
    }, { blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      acceptedStage: _blockAheadLastTiming?.acceptedStage,
      totalDistance: navActiveRoute.summary.totalDistance
    }));
    await page.evaluate(() => window.__restoreBlockedStats && window.__restoreBlockedStats());

    expect(state.acceptedStage).toBe('escape');
    expect(state.totalDistance).toBe(540);
  });

  test('intersection-buffer 単独は long-detour で hard reject しない', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const blockedStats = {
        strictOverlapRatio: 0.22,
        nearBlockedRatio: 0.21,
        slitBodyOverlapRatio: 0.04,
        slitCapOverlapRatio: 0,
        slitNearRatio: 0.12,
        coreIntersectionDetected: false,
        intersectionBufferDetected: true,
        intersectionBufferOverlapRatio: 0.12,
        legacyBroadIntersectionDetected: false,
        carveOutAdjustedIntersectionDetected: false,
        candidateSide: 'back-right'
      };
      const mode = _assessEscapeNearPenaltyMode(blockedStats, 0.04, { mode: 'long-detour', side: 'back-right' });
      return {
        actualIntersectionDetected: mode.actualIntersectionDetected,
        softIntersectionBufferDetected: mode.softIntersectionBufferDetected,
        eligible: mode.eligible,
        rejectReason: _escapeRejectReason(mode, {
          actualIntersectionDetected: mode.actualIntersectionDetected,
          overlapHard: false,
          strictThresholdExceeded: mode.strictThresholdExceeded,
          nearOnlyReject: !mode.eligible
        })
      };
    });

    expect(state.actualIntersectionDetected).toBe(false);
    expect(state.softIntersectionBufferDetected).toBe(true);
    expect(state.eligible).toBe(true);
    expect(state.rejectReason).toBe('intersection-buffer-soft');
  });

  test('slitBody low-overlap は escape で slit-body-soft 扱いになる', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const blockedStats = {
        strictOverlapRatio: 0.19,
        nearBlockedRatio: 0.17,
        slitBodyOverlapRatio: 0.19,
        slitCapOverlapRatio: 0,
        slitNearRatio: 0.10,
        coreIntersectionDetected: false,
        intersectionBufferDetected: false,
        intersectionBufferOverlapRatio: 0,
        legacyBroadIntersectionDetected: false,
        carveOutAdjustedIntersectionDetected: false,
        candidateSide: 'right'
      };
      const mode = _assessEscapeNearPenaltyMode(blockedStats, 0.03, { mode: 'escape', side: 'right' });
      return {
        actualIntersectionDetected: mode.actualIntersectionDetected,
        softSlitBodyIntersectionDetected: mode.softSlitBodyIntersectionDetected,
        eligible: mode.eligible,
        rejectReason: _escapeRejectReason(mode, {
          actualIntersectionDetected: mode.actualIntersectionDetected,
          overlapHard: false,
          strictThresholdExceeded: mode.strictThresholdExceeded,
          nearOnlyReject: !mode.eligible
        })
      };
    });

    expect(state.actualIntersectionDetected).toBe(false);
    expect(state.softSlitBodyIntersectionDetected).toBe(true);
    expect(state.eligible).toBe(true);
    expect(state.rejectReason).toBe('slit-body-soft');
  });

  test('slitLineCross は従来通り hard reject', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const blockedStats = {
        strictOverlapRatio: 0.18,
        nearBlockedRatio: 0.16,
        slitBodyOverlapRatio: 0.10,
        slitCapOverlapRatio: 0,
        slitNearRatio: 0.12,
        coreIntersectionDetected: false,
        intersectionBufferDetected: false,
        intersectionBufferOverlapRatio: 0,
        legacyBroadIntersectionDetected: false,
        carveOutAdjustedIntersectionDetected: false,
        candidateSide: 'left'
      };
      const mode = _assessEscapeNearPenaltyMode(blockedStats, 0.12, { mode: 'escape', side: 'left' });
      return {
        actualIntersectionDetected: mode.actualIntersectionDetected,
        rejectReason: _escapeRejectReason(mode, {
          actualIntersectionDetected: mode.actualIntersectionDetected,
          overlapHard: false,
          strictThresholdExceeded: mode.strictThresholdExceeded,
          nearOnlyReject: !mode.eligible
        })
      };
    });

    expect(state.actualIntersectionDetected).toBe(true);
    expect(state.rejectReason).toBe('slit-line-cross');
  });

  test('back-right / back-left は right / left より intersection buffer に寛容', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const stats = {
        strictOverlapRatio: 0.24,
        nearBlockedRatio: 0.20,
        slitBodyOverlapRatio: 0.04,
        slitCapOverlapRatio: 0,
        slitNearRatio: 0.11,
        coreIntersectionDetected: false,
        intersectionBufferDetected: true,
        intersectionBufferOverlapRatio: 0.19,
        legacyBroadIntersectionDetected: false,
        carveOutAdjustedIntersectionDetected: false
      };
      const right = _assessEscapeNearPenaltyMode({ ...stats, candidateSide: 'right' }, 0.04, { mode: 'escape', side: 'right' });
      const backRight = _assessEscapeNearPenaltyMode({ ...stats, candidateSide: 'back-right' }, 0.04, { mode: 'escape', side: 'back-right' });
      return {
        rightActual: right.actualIntersectionDetected,
        backRightActual: backRight.actualIntersectionDetected,
        rightSoft: right.softIntersectionBufferDetected,
        backRightSoft: backRight.softIntersectionBufferDetected
      };
    });

    expect(state.rightActual).toBe(true);
    expect(state.backRightActual).toBe(false);
    expect(state.backRightSoft).toBe(true);
  });

  test('failure distribution 用の新 reject reason を区別できる', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const reasons = {};
      _incrementReasonCounter(reasons, _escapeRejectReason({
        slitLineCrossDetected: false,
        slitBodyHard: true,
        softSlitBodyIntersectionDetected: false,
        softIntersectionBufferDetected: false
      }, {}));
      _incrementReasonCounter(reasons, _escapeRejectReason({
        slitLineCrossDetected: false,
        slitBodyHard: false,
        softSlitBodyIntersectionDetected: true,
        softIntersectionBufferDetected: false
      }, {}));
      _incrementReasonCounter(reasons, _escapeRejectReason({
        slitLineCrossDetected: false,
        slitBodyHard: false,
        softSlitBodyIntersectionDetected: false,
        softIntersectionBufferDetected: true
      }, {}));
      return reasons;
    });

    expect(state['slit-body-hard']).toBe(1);
    expect(state['slit-body-soft']).toBe(1);
    expect(state['intersection-buffer-soft']).toBe(1);
  });

  // ── 表示パイプライン ────────────────────────────────────────────────────

  test('確定後の表示用 route は短い初動セグメントをまとめて明確な最初の案内を生成する', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const clarified = _clarifyRouteForNavigation({
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.00012, lng: 139.0 },
          { lat: 35.00017, lng: 139.0 },
          { lat: 35.00055, lng: 139.0 },
          { lat: 35.0040, lng: 139.0 }
        ],
        summary: { totalDistance: 330, totalTime: 290 },
        instructions: [{ text: '直進する', distance: 12, index: 1 }]
      });
      return {
        coordsLen: clarified.coordinates.length,
        firstInstruction: clarified.instructions?.[0]?._displayText || clarified.instructions?.[0]?.text || '',
        secondCoord: clarified.coordinates[1]
      };
    });

    expect(state.coordsLen).toBeLessThan(5);
    expect(state.firstInstruction).toContain('まずは');
    expect(state.secondCoord.lat).not.toBeCloseTo(35.00012, 5);
  });

  test('確定後の表示用 route は中盤の短い鋭角セグメントを全体簡略化で除去する', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const clarified = _clarifyRouteForNavigation({
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0010, lng: 139.0 },
          { lat: 35.00112, lng: 139.00008 },
          { lat: 35.0010, lng: 139.00016 },
          { lat: 35.0020, lng: 139.00016 },
          { lat: 35.0030, lng: 139.00016 }
        ],
        summary: { totalDistance: 380, totalTime: 300 },
        instructions: [{ text: '進む', distance: 20, index: 1 }]
      });
      return {
        coords: clarified.coordinates,
        angles: clarified.coordinates.slice(1, -1).map((point, index) => _turnAngleDeg(
          clarified.coordinates[index],
          point,
          clarified.coordinates[index + 2]
        ))
      };
    });

    expect(state.coords.length).toBeLessThan(6);
    expect(state.angles.some(angle => angle > 100)).toBeFalsy();
  });

  test('確定後の表示用 route は交差点付近の短い out-and-back spur を残さない', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const clarified = _clarifyRouteForNavigation({
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0009, lng: 139.0 },
          { lat: 35.00105, lng: 139.00012 },
          { lat: 35.00092, lng: 139.00002 },
          { lat: 35.0018, lng: 139.00002 },
          { lat: 35.0035, lng: 139.00002 }
        ],
        summary: { totalDistance: 420, totalTime: 320 },
        instructions: [{ text: '進む', distance: 20, index: 1 }]
      });
      return {
        coords: clarified.coordinates,
        hasNearReturn: clarified.coordinates.some((point, index, arr) => {
          if (index < 2) return false;
          return _segmentLengthMeters(arr[index - 2], point) < 12;
        })
      };
    });

    expect(state.coords.length).toBeLessThan(6);
    expect(state.hasNearReturn).toBe(false);
  });

  test('確定後の表示用 route は instruction index を主経路アンカーとして再構成する', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const clarified = _clarifyRouteForNavigation({
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0008, lng: 139.0 },
          { lat: 35.0013, lng: 139.00018 },
          { lat: 35.00085, lng: 139.00002 },
          { lat: 35.0016, lng: 139.00002 },
          { lat: 35.0025, lng: 139.00002 },
          { lat: 35.0035, lng: 139.00002 }
        ],
        summary: { totalDistance: 430, totalTime: 330 },
        instructions: [
          { text: '直進', distance: 90, index: 1 },
          { text: 'さらに進む', distance: 140, index: 5 }
        ]
      });
      return {
        coords: clarified.coordinates,
        instructionPoints: clarified.instructions.map(step => step.latLng || null)
      };
    });

    expect(state.coords.length).toBeLessThan(7);
    expect(state.instructionPoints[0]).toBeTruthy();
    expect(state.instructionPoints[1]).toBeTruthy();
    expect(state.coords.some(point => Math.abs(point.lat - 35.0013) < 0.00001 && Math.abs(point.lng - 139.00018) < 0.00001)).toBe(false);
  });

  test('確定後の表示用 route は近接した重複アンカーを同じ交差点として統合する', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const route = {
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0009, lng: 139.0 },
          { lat: 35.0010, lng: 139.00003 },
          { lat: 35.00105, lng: 139.00005 },
          { lat: 35.0018, lng: 139.00005 },
          { lat: 35.0028, lng: 139.00005 }
        ],
        instructions: [
          { text: '交差点へ', distance: 40, index: 1 },
          { text: 'そのまま', distance: 10, index: 2 },
          { text: 'さらに進む', distance: 12, index: 3 },
          { text: '到着方面へ', distance: 90, index: 4 }
        ]
      };
      return {
        mergedAnchors: _mergeNearbyDisplayAnchors(route),
        clarified: _clarifyRouteForNavigation(route).coordinates
      };
    });

    expect(state.mergedAnchors.length).toBeLessThan(6);
    expect(state.clarified[0]).toBeTruthy();
    expect(state.clarified[state.clarified.length - 1]).toBeTruthy();
  });

  test('確定後の表示用 route は近接・同方向の重複セグメントを 1 本にまとめる', async ({ page }) => {
    await bootstrap(page);
    const state = await page.evaluate(() => {
      const clarified = _clarifyRouteForNavigation({
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0009, lng: 139.0 },
          { lat: 35.0016, lng: 139.00002 },
          { lat: 35.00092, lng: 139.00004 },
          { lat: 35.00162, lng: 139.00006 },
          { lat: 35.0026, lng: 139.00008 }
        ],
        summary: { totalDistance: 450, totalTime: 330 },
        instructions: [
          { text: '直進', distance: 90, index: 1 },
          { text: 'さらに直進', distance: 90, index: 4 }
        ]
      });
      return {
        coords: clarified.coordinates,
        hasParallelDuplicate: clarified.coordinates.some((point, index, arr) => {
          if (index < 3) return false;
          const a1 = arr[index - 3];
          const a2 = arr[index - 2];
          const b1 = arr[index - 1];
          const b2 = point;
          const midpointA = { lat: (a1.lat + a2.lat) / 2, lng: (a1.lng + a2.lng) / 2 };
          const midpointB = { lat: (b1.lat + b2.lat) / 2, lng: (b1.lng + b2.lng) / 2 };
          const bearingA = _segmentBearingDeg(a1, a2);
          const bearingB = _segmentBearingDeg(b1, b2);
          return _segmentLengthMeters(midpointA, midpointB) < 14 && _bearingDiffDeg(bearingA, bearingB) < 20;
        })
      };
    });

    expect(state.coords.length).toBeLessThan(6);
    expect(state.hasParallelDuplicate).toBe(false);
  });

  test('歩行危険横断は横断歩道がない primary 横断を reject する', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      const route = {
        coordinates: [
          { lat: 35.0005, lng: 138.9997 },
          { lat: 35.0005, lng: 139.0003 }
        ]
      };
      const context = {
        roads: [
          {
            id: 1,
            tags: { highway: 'primary', lanes: '4' },
            coordinates: [
              { lat: 35.0002, lng: 139.0 },
              { lat: 35.0008, lng: 139.0 }
            ]
          }
        ],
        crosswalks: []
      };
      const safety = _evaluatePedestrianRouteAgainstContext(route, context);
      return {
        safe: safety.safe,
        rejectReason: safety.rejectReason,
        detail: safety.dangerousCrossings[0]?.classification?.reason || null
      };
    });

    expect(result.safe).toBe(false);
    expect(result.rejectReason).toBe('dangerous-crossing');
    expect(result.detail).toBe('major-no-crosswalk');
  });

  test('歩行危険横断は近くに横断歩道があれば同じ primary 横断を許可する', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      const route = {
        coordinates: [
          { lat: 35.0005, lng: 138.9997 },
          { lat: 35.0005, lng: 139.0003 }
        ]
      };
      const context = {
        roads: [
          {
            id: 1,
            tags: { highway: 'primary', lanes: '4' },
            coordinates: [
              { lat: 35.0002, lng: 139.0 },
              { lat: 35.0008, lng: 139.0 }
            ]
          }
        ],
        crosswalks: [
          { lat: 35.0005, lng: 139.0, tags: { highway: 'crossing' } }
        ]
      };
      const safety = _evaluatePedestrianRouteAgainstContext(route, context);
      return {
        safe: safety.safe,
        rejectReason: safety.rejectReason,
        dangerousCount: safety.dangerousCrossings.length
      };
    });

    expect(result.safe).toBe(true);
    expect(result.rejectReason).toBeNull();
    expect(result.dangerousCount).toBe(0);
  });

  test('歩行危険横断の context unavailable は unknown として fail-open を明示する', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(async () => {
      const originalFetchContext = _fetchPedestrianSafetyContextForBBox;
      _fetchPedestrianSafetyContextForBBox = async () => ({
        status: 'unavailable',
        context: null,
        source: 'compact-cache',
        bbox: { minLat: 35, minLng: 139, maxLat: 35.01, maxLng: 139.01, south: 35, west: 139, north: 35.01, east: 139.01 },
        fetchedAt: Date.now(),
        failure: {
          kind: 'timeout',
          message: 'pedestrian context fetch timed out after 800ms',
          aborted: true,
          abortSource: 'timeout',
          detail: 'core-fetch-timeout'
        }
      });
      const seqContext = {
        seq: 12,
        bbox: { minLat: 35, minLng: 139, maxLat: 35.01, maxLng: 139.01, south: 35, west: 139, north: 35.01, east: 139.01 },
        status: 'pending',
        context: null,
        fetchedAt: 0,
        source: 'compact-cache',
        fetchPhase: 'core',
        expanded: false,
        seedPoints: [],
        failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
      };
      const safety = await _evaluatePedestrianRouteSafety({
        coordinates: [
          { lat: 35.0005, lng: 138.9997 },
          { lat: 35.0005, lng: 139.0003 }
        ]
      }, seqContext, 'final:test');
      _fetchPedestrianSafetyContextForBBox = originalFetchContext;
      return {
        status: safety.status,
        safe: safety.safe,
        contextUnavailable: safety.contextUnavailable,
        failOpenApplied: safety.failOpenApplied,
        rejectReason: safety.rejectReason,
        contextSource: safety.contextSource,
        contextFailureKind: safety.contextFailureKind,
        contextFailureDetail: safety.contextFailureDetail,
        contextSeq: safety.contextSeq
      };
    });

    expect(result.status).toBe('unknown');
    expect(result.safe).toBe(false);
    expect(result.contextUnavailable).toBe(true);
    expect(result.failOpenApplied).toBe(true);
    expect(result.rejectReason).toBeNull();
    expect(result.contextSource).toBe('compact-cache');
    expect(result.contextFailureKind).toBe('timeout');
    expect(result.contextFailureDetail).toBe('core-fetch-timeout');
    expect(result.contextSeq).toBe(12);
  });

  test('同一 seq 内では pedestrian context fetch を 1 回だけ再利用する', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(async () => {
      let fetchCount = 0;
      const originalFetchContext = _fetchPedestrianSafetyContextForBBox;
      _fetchPedestrianSafetyContextForBBox = async (bbox) => {
        fetchCount += 1;
        return {
          status: 'ready',
          context: {
            roads: [
              {
                id: 1,
                tags: { highway: 'residential' },
                coordinates: [
                  { lat: 35.0, lng: 139.0 },
                  { lat: 35.001, lng: 139.001 }
                ]
              }
            ],
            crosswalks: []
          },
          source: 'compact-cache',
          bbox,
          fetchedAt: Date.now(),
          failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
        };
      };
      const seqContext = {
        seq: 77,
        bbox: { minLat: 34.999, minLng: 138.999, maxLat: 35.01, maxLng: 139.01, south: 34.999, west: 138.999, north: 35.01, east: 139.01 },
        status: 'pending',
        context: null,
        fetchedAt: 0,
        source: 'compact-cache',
        fetchPhase: 'core',
        expanded: false,
        seedPoints: [],
        failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
      };
      const candidate = await _evaluatePedestrianRouteSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0005, lng: 139.0005 }
        ]
      }, seqContext, 'stage1-candidate');
      const final = await _evaluatePedestrianRouteSafety({
        coordinates: [
          { lat: 35.0001, lng: 139.0001 },
          { lat: 35.0006, lng: 139.0006 }
        ]
      }, seqContext, 'final:escape');
      _fetchPedestrianSafetyContextForBBox = originalFetchContext;
      return {
        fetchCount,
        candidateSource: candidate.contextSource,
        finalSource: final.contextSource,
        candidateSeq: candidate.contextSeq,
        finalSeq: final.contextSeq
      };
    });

    expect(result.fetchCount).toBe(1);
    expect(result.candidateSource).toBe('compact-cache');
    expect(result.finalSource).toBe('compact-cache');
    expect(result.candidateSeq).toBe(77);
    expect(result.finalSeq).toBe(77);
  });

  test('pedestrian context failure は fetch-error と aborted を区別する', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      return {
        fetchError: _classifyPedestrianContextFailure(null, {
          status: 502,
          message: 'pedestrian context fetch failed with HTTP 502'
        }),
        aborted: _classifyPedestrianContextFailure({ name: 'AbortError', message: 'signal is aborted without reason' }, {
          aborted: true,
          abortSource: 'superseded-request'
        })
      };
    });

    expect(result.fetchError.kind).toBe('fetch-error');
    expect(result.fetchError.aborted).toBe(false);
    expect(result.aborted.kind).toBe('aborted');
    expect(result.aborted.aborted).toBe(true);
    expect(result.aborted.abortSource).toBe('superseded-request');
    expect(result.aborted.detail).toBe('seq-replaced');
  });

  test('candidate と final adopt は同じ cached context を再利用する', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(async () => {
      let fetchCount = 0;
      const originalFetchContext = _fetchPedestrianSafetyContextForBBox;
      _fetchPedestrianSafetyContextForBBox = async (bbox) => {
        fetchCount += 1;
        return {
          status: 'ready',
          context: {
            roads: [
              {
                id: 1,
                tags: { highway: 'secondary' },
                coordinates: [
                  { lat: 35.0, lng: 139.0 },
                  { lat: 35.001, lng: 139.0 }
                ]
              }
            ],
            crosswalks: []
          },
          source: 'compact-cache',
          bbox,
          fetchedAt: Date.now(),
          failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
        };
      };
      const seqContext = {
        seq: 91,
        bbox: { minLat: 34.999, minLng: 138.999, maxLat: 35.01, maxLng: 139.01, south: 34.999, west: 138.999, north: 35.01, east: 139.01 },
        status: 'pending',
        context: null,
        fetchedAt: 0,
        source: 'compact-cache',
        fetchPhase: 'core',
        expanded: false,
        seedPoints: [],
        failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
      };
      await _evaluatePedestrianRouteSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0004, lng: 139.0002 }
        ]
      }, seqContext, 'escape:left-60');
      const final = await _evaluatePedestrianRouteSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0005, lng: 139.0003 }
        ]
      }, seqContext, 'final:escape');
      _fetchPedestrianSafetyContextForBBox = originalFetchContext;
      return {
        fetchCount,
        finalSource: final.contextSource,
        finalSeq: final.contextSeq
      };
    });

    expect(result.fetchCount).toBe(1);
    expect(result.finalSource).toBe('compact-cache');
    expect(result.finalSeq).toBe(91);
  });

  test('compact bbox で足りる場合は expanded fetch しない', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(async () => {
      let expandedCalls = 0;
      const originalExpand = _expandPedestrianSafetyContextBBoxIfNeeded;
      _expandPedestrianSafetyContextBBoxIfNeeded = async (seqContext, route, options) => {
        const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
        const needsExpansion = coords.some(point => !_boundsContainsPoint(seqContext.bbox, point));
        if (needsExpansion) expandedCalls += 1;
        return originalExpand(seqContext, route, options);
      };
      const originalFetchContext = _fetchPedestrianSafetyContextForBBox;
      _fetchPedestrianSafetyContextForBBox = async (bbox, options) => ({
        status: 'ready',
        context: { roads: [{ id: 1, tags: { highway: 'primary' }, coordinates: [{ lat: 35, lng: 139 }, { lat: 35.001, lng: 139.001 }] }], crosswalks: [] },
        source: options?.sourceLabel || 'compact-cache',
        bbox,
        fetchedAt: Date.now(),
        failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
      });
      const seqContext = {
        seq: 101,
        bbox: { minLat: 34.999, minLng: 138.999, maxLat: 35.01, maxLng: 139.01, south: 34.999, west: 138.999, north: 35.01, east: 139.01 },
        status: 'pending',
        context: null,
        fetchedAt: 0,
        source: 'compact-cache',
        fetchPhase: 'core',
        expanded: false,
        seedPoints: [],
        failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
      };
      const safety = await _evaluatePedestrianRouteSafety({
        coordinates: [
          { lat: 35.0002, lng: 139.0002 },
          { lat: 35.0007, lng: 139.0007 }
        ]
      }, seqContext, 'stage1-candidate');
      _expandPedestrianSafetyContextBBoxIfNeeded = originalExpand;
      _fetchPedestrianSafetyContextForBBox = originalFetchContext;
      return { expandedCalls, source: safety.contextSource };
    });

    expect(result.expandedCalls).toBe(0);
    expect(result.source).toBe('compact-cache');
  });

  test('bbox 外候補が出たときだけ expanded-cache を 1 回使う', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(async () => {
      let fetchSources = [];
      const originalFetchContext = _fetchPedestrianSafetyContextForBBox;
      _fetchPedestrianSafetyContextForBBox = async (bbox, options) => {
        fetchSources.push(options?.sourceLabel || 'compact-cache');
        return {
          status: 'ready',
          context: { roads: [{ id: fetchSources.length, tags: { highway: 'secondary' }, coordinates: [{ lat: 35, lng: 139 }, { lat: 35.01, lng: 139.01 }] }], crosswalks: [] },
          source: options?.sourceLabel || 'compact-cache',
          bbox,
          fetchedAt: Date.now(),
          failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
        };
      };
      const seqContext = {
        seq: 102,
        bbox: { minLat: 35.0000, minLng: 139.0000, maxLat: 35.0004, maxLng: 139.0004, south: 35.0000, west: 139.0000, north: 35.0004, east: 139.0004 },
        status: 'pending',
        context: null,
        fetchedAt: 0,
        source: 'compact-cache',
        fetchPhase: 'core',
        expanded: false,
        seedPoints: [{ lat: 35.0, lng: 139.0 }],
        failure: { kind: 'none', message: '', aborted: false, abortSource: 'none', detail: 'none' }
      };
      const safety = await _evaluatePedestrianRouteSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0020, lng: 139.0020 }
        ]
      }, seqContext, 'escape:far');
      _fetchPedestrianSafetyContextForBBox = originalFetchContext;
      return { fetchSources, source: safety.contextSource, expanded: seqContext.expanded };
    });

    expect(result.fetchSources).toEqual(['compact-cache', 'expanded-cache']);
    expect(result.source).toBe('expanded-cache');
    expect(result.expanded).toBe(true);
  });

  test('timeout failure cache TTL は success cache より短い', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      const timeoutRecord = { status: 'unavailable', failure: { kind: 'timeout' } };
      const successRecord = { status: 'ready', failure: { kind: 'none' } };
      return {
        timeoutTtl: _pedestrianSafetyCacheEntryTtl(timeoutRecord),
        successTtl: _pedestrianSafetyCacheEntryTtl(successRecord)
      };
    });

    expect(result.timeoutTtl).toBeLessThan(result.successTtl);
  });

  test('unknown pedestrian safety でも明らかな長い横断ショートカットは conservative reject する', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      return _evaluateConservativeUnknownPedestrianSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0000, lng: 139.0002 },
          { lat: 35.0005, lng: 139.0002 },
          { lat: 35.0005, lng: 139.0008 },
          { lat: 35.0010, lng: 139.0008 }
        ],
        totalDistance: 140
      }, { phase: 'test-unknown', mode: 'stage-candidate', side: 'right' });
    });

    expect(result.conservativeRejectEvaluated).toBe(true);
    expect(result.conservativeRejectApplied).toBe(true);
    expect(result.conservativeDecision).toBe('hard-reject');
    expect(result.conservativeRejectReason).toMatch(/hard$/);
  });

  test('unknown pedestrian safety でも通常の短い進行は conservative reject しない', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      return _evaluateConservativeUnknownPedestrianSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0001, lng: 139.0000 },
          { lat: 35.0002, lng: 139.0000 },
          { lat: 35.0003, lng: 139.0000 }
        ],
        totalDistance: 36
      }, { phase: 'test-unknown-safe', mode: 'escape', side: 'back-right', nearPenaltyMode: { eligible: true } });
    });

    expect(result.conservativeRejectEvaluated).toBe(true);
    expect(result.conservativeRejectApplied).toBe(false);
    expect(result.conservativeDecision).toBe('pass');
    expect(result.conservativeRejectReason).toBeTruthy();
  });

  test('unknown + back-right rescue detour + side-road continuation は hard reject しない', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      return _evaluateConservativeUnknownPedestrianSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0000, lng: 139.00015 },
          { lat: 35.00042, lng: 139.00015 },
          { lat: 35.00055, lng: 139.00015 },
          { lat: 35.00068, lng: 139.00015 }
        ],
        totalDistance: 82
      }, {
        phase: 'escape:back-right-60',
        mode: 'escape',
        side: 'back-right',
        nearPenaltyMode: { eligible: true },
        hardIntersectionDetected: false,
        actualIntersectionDetected: false
      });
    });

    expect(result.conservativeRejectApplied).toBe(false);
    expect(result.conservativeDecision).toBe('soft-risk');
    expect(result.conservativeRejectReason).toMatch(/soft|side-road/);
    expect(result.conservativePenalty).toBeGreaterThan(0);
  });

  test('unknown + long-detour + low-overlap + nearPenaltyMode=true は soft-risk 扱い', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      return _evaluateConservativeUnknownPedestrianSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0000, lng: 139.00015 },
          { lat: 35.00042, lng: 139.00015 },
          { lat: 35.00055, lng: 139.00015 },
          { lat: 35.00068, lng: 139.00015 }
        ],
        totalDistance: 82
      }, {
        phase: 'long-detour:back-left-120',
        mode: 'long-detour',
        side: 'back-left',
        nearPenaltyMode: { eligible: true },
        hardIntersectionDetected: false,
        actualIntersectionDetected: false
      });
    });

    expect(result.conservativeDecision).toBe('soft-risk');
    expect(result.conservativeRejectApplied).toBe(false);
    expect(result.conservativePenalty).toBeGreaterThan(0);
  });

  test('unknown + diagonal shortcut は hard reject', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      return _evaluateConservativeUnknownPedestrianSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0000, lng: 139.00015 },
          { lat: 35.00042, lng: 139.00015 },
          { lat: 35.00042, lng: 139.00030 }
        ],
        totalDistance: 85
      }, {
        phase: 'test-diagonal',
        mode: 'stage-candidate',
        side: 'right'
      });
    });

    expect(result.conservativeDecision).toBe('hard-reject');
    expect(result.conservativeRejectReason).toBe('diagonal-mainline-shortcut-hard');
  });

  test('unknown + final adopt に conservativeDecision / reason が残る', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      return _evaluateConservativeUnknownPedestrianSafety({
        coordinates: [
          { lat: 35.0000, lng: 139.0000 },
          { lat: 35.0000, lng: 139.00015 },
          { lat: 35.00042, lng: 139.00015 },
          { lat: 35.00055, lng: 139.00015 }
        ],
        totalDistance: 76
      }, {
        phase: 'final:escape',
        mode: 'final',
        side: 'back-right',
        nearPenaltyMode: { eligible: true },
        hardIntersectionDetected: false,
        actualIntersectionDetected: false
      });
    });

    expect(result.conservativeDecision).toBeTruthy();
    expect(result.conservativeRejectReason).toBeTruthy();
  });

  test('failure distribution 用に hard / soft reason を区別できる', async ({ page }) => {
    await bootstrap(page);
    const result = await page.evaluate(() => {
      _blockAheadPerfMetrics = { rejectReasons: {} };
      _recordBlockAheadRejectReason('dangerous-crossing-unknown-hard');
      _recordBlockAheadRejectReason('long-crossing-segment-hard');
      _recordBlockAheadRejectReason('dangerous-crossing-unknown-soft');
      _recordBlockAheadRejectReason('long-crossing-segment-soft');
      return { ..._blockAheadPerfMetrics.rejectReasons };
    });

    expect(result['dangerous-crossing-unknown-hard']).toBe(1);
    expect(result['long-crossing-segment-hard']).toBe(1);
    expect(result['dangerous-crossing-unknown-soft']).toBe(1);
    expect(result['long-crossing-segment-soft']).toBe(1);
  });
});

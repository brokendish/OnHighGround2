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
        { label: 'leg-right-30', point: { lat: 35.0001, lng: 139.0045 } }
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
              { lat: 35.0001, lng: 139.0038 },
              { lat: 35.0001, lng: 139.0045 }
            ],
            totalDistance: 120,
            totalTime: 100,
            turnCount: 1
          };
        }
        if (Array.isArray(waypoints) && waypoints.length === 2) {
          return {
            coordinates: [
              { lat: 35.0001, lng: 139.0045 },
              { lat: 35.0032, lng: 139.0045 },
              { lat: 35.004,  lng: 139.0 }
            ],
            summary: { totalDistance: 360, totalTime: 300 },
            instructions: [{ text: '迂回して進む', distance: 100, latLng: { lat: 35.0032, lng: 139.0045 } }],
            totalDistance: 360,
            totalTime: 300,
            turnCount: 1
          };
        }
        return bypassAlt;
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
        { label: 'leg-right-30', point: { lat: 35.0001, lng: 139.0040 }, lateralM: 30, nodeType: 'corridor-like', nodeScore: 20 },
        { label: 'leg-right-90', point: { lat: 35.0001, lng: 139.0068 }, lateralM: 90, nodeType: 'side-road', nodeScore: 120 }
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
                { lat: 35.0001, lng: 139.0056 },
                { lat: 35.0001, lng: 139.0068 }
              ],
              totalDistance: 180,
              totalTime: 150,
              turnCount: 1
            };
          }
          return {
            coordinates: [
              { lat: 35.0001, lng: 139.0068 },
              { lat: 35.0032, lng: 139.0068 },
              { lat: 35.004,  lng: 139.0 }
            ],
            summary: { totalDistance: 300, totalTime: 250 },
            instructions: [{ text: '脇道から進む', distance: 80, latLng: { lat: 35.0032, lng: 139.0068 } }],
            totalDistance: 300,
            totalTime: 250,
            turnCount: 1
          };
        }
        return bypassAlt;
      };
    }, { blockedRoute: BLOCKED_ROUTE, bypassAlt: makeBypassAlt() });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      acceptedStage: _blockAheadLastTiming?.acceptedStage,
      routeDistance: navActiveRoute.summary.totalDistance
    }));

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
        { label: 'leg-right-60', point: { lat: 35.0001, lng: 139.0045 }, lateralM: 60, distanceTierM: 60, depthKind: 'entrance', nodeType: 'side-road', nodeScore: 120 }
      ]);
      _generateEscapePoints = async () => [];
      _fetchOsrmRouteThroughWaypoints = async (waypoints) => {
        if (Array.isArray(waypoints) && waypoints.length === 2
            && Math.abs((waypoints[0].lng ?? waypoints[0].lon) - 139.0) < 0.0001) {
          return {
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0001, lng: 139.0038 },
              { lat: 35.0001, lng: 139.0045 }
            ],
            totalDistance: 120,
            totalTime: 100,
            turnCount: 1
          };
        }
        return {
          coordinates: [
            { lat: 35.0001, lng: 139.0045 },
            { lat: 35.0015, lng: 139.0045 },
            { lat: 35.0032, lng: 139.0045 },
            { lat: 35.0040, lng: 139.0045 }
          ],
          summary: { totalDistance: 340, totalTime: 280 },
          instructions: [{ text: '脇道を進む', distance: 100, latLng: { lat: 35.0032, lng: 139.0045 } }],
          totalDistance: 340,
          totalTime: 280,
          turnCount: 1
        };
      };
      const originalStats = _routeBlockedAreaStats;
      _routeBlockedAreaStats = (coords, blockedArea) => {
        if (Array.isArray(coords) && coords.length === 4 && Math.abs((coords[0].lng ?? coords[0].lon) - 139.0045) < 0.0001) {
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
      window.__restoreBlockedStats = () => { _routeBlockedAreaStats = originalStats; };
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

  test('holdWaypointMode route は overlap が実質 0 かつ strict が低ければ intersects=true でも near-penalty で通る', async ({ page }) => {
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
            strictOverlapRatio: 0.24,
            nearBlockedRatio: 0.28,
            minDistanceToAreaM: -1,
            intersects: true,
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
});

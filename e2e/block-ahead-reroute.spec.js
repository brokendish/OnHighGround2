'use strict';

const { test, expect } = require('@playwright/test');

const BASE_ROUTE = [
  { lat: 35.0, lng: 139.0 },
  { lat: 35.002, lng: 139.0 },
  { lat: 35.004, lng: 139.0 },
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

  test('再ルート成功時に drawRouteTo 経由でガイダンスと音声が更新される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__drawRouteToArgs = null;
      // Mock OSRM eval: return a bypass route clearly outside the block buffer (lng 138.998 ≈ 180m west)
      _fetchOsrmRouteForEval = async () => ({
        coordinates: [
          { lat: 35.0001, lng: 138.998 },
          { lat: 35.003,  lng: 138.998 },
          { lat: 35.004,  lng: 139.0   }
        ],
        totalDistance: 350
      });
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = {
          lat,
          lon,
          extraWaypoints: options.extraWaypoints || []
        };
        const fakeRoute = {
          name: 'fake',
          coordinates: [
            { lat: 35.0001, lng: 139.0 },
            { lat: 35.0012, lng: 138.9994 },
            { lat: 35.0040, lng: 139.0 }
          ],
          summary: { totalDistance: 321.5, totalTime: 278.4 },
          instructions: [
            {
              text: '左に曲がる',
              distance: 100,
              index: 1
            }
          ]
        };
        const formatter = {
          formatInstruction(instruction) { return instruction.text; },
          formatDistance(distance) { return `${Math.round(distance)}m`; }
        };
        options.onRoutesAvailable({
          routes: [fakeRoute],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter,
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      mode: navigationMode,
      inProgress: navBlockAheadInProgress,
      remain: document.getElementById('mbc-remain-dist')?.textContent,
      summary: navActiveRoute.summary,
      stepCount: document.querySelectorAll('.route-guidance-steps li').length,
      voiceCalls: window.__voiceCalls,
      drawRouteToArgs: window.__drawRouteToArgs,
      voiceClearCount: window.__voiceClearCount,
      stepClearCount: window.__stepClearCount
    }));

    expect(state.mode).toBe('navigation_active');
    expect(state.inProgress).toBe(false);
    expect(state.remain).not.toBe('—');
    expect(state.summary.totalDistance).toBe(321.5);
    expect(state.summary.totalTime).toBe(278.4);
    expect(state.stepCount).toBeGreaterThan(0);
    expect(state.drawRouteToArgs.extraWaypoints.length).toBe(3); // blockStart + bypass + rejoin
    expect(state.voiceClearCount).toBeGreaterThan(0);
    expect(state.stepClearCount).toBeGreaterThan(0);
    expect(state.voiceCalls.some(v => v && v.id === 'block-ahead-reroute')).toBeTruthy();
  });

  test('同一路線しか返らない候補は overlap 棄却され reroute 失敗になる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      window.__drawRouteToCalled = false;
      _fetchOsrmRouteForEval = async () => ({
        coordinates: [
          { lat: 35.00055, lng: 139.0 },
          { lat: 35.00065, lng: 139.0 },
          { lat: 35.00075, lng: 139.0 },
          { lat: 35.00085, lng: 139.0 },
          { lat: 35.00095, lng: 139.0 },
          { lat: 35.00105, lng: 139.0 }
        ],
        totalDistance: 300
      });
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    });

    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));
    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートが見つかりませんでした');

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

  test('左候補が棄却されても右バイパス候補が採用される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      window.__drawRouteToArgs = null;
      _fetchOsrmRouteForEval = async (waypoints) => {
        const bypass = waypoints[2];
        const isRight = bypass.lng > 139.0;
        if (isRight) {
          return {
            coordinates: [
              { lat: 35.0001, lng: 139.0018 },
              { lat: 35.0030, lng: 139.0018 },
              { lat: 35.0040, lng: 139.0 }
            ],
            totalDistance: 360
          };
        }
        return {
          coordinates: [
            { lat: 35.00055, lng: 139.0 },
            { lat: 35.00065, lng: 139.0 },
            { lat: 35.00075, lng: 139.0 },
            { lat: 35.00085, lng: 139.0 },
            { lat: 35.00095, lng: 139.0 },
            { lat: 35.00105, lng: 139.0 }
          ],
          totalDistance: 310
        };
      };
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = {
          lat,
          lon,
          extraWaypoints: options.extraWaypoints || []
        };
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0012, lng: 139.0006 },
              { lat: 35.0040, lng: 139.0 }
            ],
            summary: { totalDistance: 360, totalTime: 300 },
            instructions: [{ text: '右に曲がる', distance: 80, index: 1 }]
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: {
            formatInstruction(instruction) { return instruction.text; },
            formatDistance(distance) { return `${Math.round(distance)}m`; }
          },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      extraWaypoints: window.__drawRouteToArgs.extraWaypoints
    }));

    expect(state.extraWaypoints).toHaveLength(3);
    expect(state.extraWaypoints[1].lng).toBeGreaterThan(139.0);
  });

  test('評価 fetch が全候補で失敗しても reroute 失敗判定になる', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      window.__drawRouteToCalled = false;
      _fetchOsrmRouteForEval = async () => null;
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートが見つかりませんでした');

    const state = await page.evaluate(() => ({
      drawRouteToCalled: window.__drawRouteToCalled,
      hasLayer: _blockAheadLayer !== null,
      inProgress: navBlockAheadInProgress
    }));

    expect(state.drawRouteToCalled).toBe(false);
    expect(state.hasLayer).toBe(false);
    expect(state.inProgress).toBe(false);
  });
});

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
  { lat: 35.0004, lng: 139.0014 },
  { lat: 35.0014, lng: 139.0014 },
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
  await page.evaluate(() => {
    _assessRouteCrossingRisk = async () => ({
      available: false,
      crossings: [],
      dangerousCount: 0,
      uncontrolledCount: 0,
      penalty: 0,
      warningText: ''
    });
  });
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
          { lat: 35.0004, lng: 139.0014 },
          { lat: 35.0014, lng: 139.0014 },
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
    await page.evaluate((bypassAlt) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => [bypassAlt];
      drawRouteTo = (_lat, _lon, options = {}) => {
        stopNavigation(); // 非同期完了前に停止
        options.onRoutesAvailable({
          routes: [{
            coordinates: [{ lat: 35.0001, lng: 139.0 }, { lat: 35.004, lng: 139.0 }],
            summary: { totalDistance: 300, totalTime: 200 }
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => d + 'm' },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    }, makeBypassAlt());

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
    await page.evaluate((bypassAlt) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__successCount = 0;
      _fetchOsrmAlternatives = async () => [bypassAlt];
      const fakePayload = {
        routes: [{
          coordinates: [
            { lat: 35.0001, lng: 139.0 },
            { lat: 35.0004, lng: 139.0014 },
            { lat: 35.0014, lng: 139.0014 },
            { lat: 35.004,  lng: 139.0 }
          ],
          summary: { totalDistance: 480, totalTime: 400 },
          instructions: [{ text: '迂回', distance: 100, index: 1 }]
        }],
        selectedRouteIndex: 0,
        routeColors: ['#ff9800'],
        formatter: { formatInstruction: i => i.text, formatDistance: d => d + 'm' },
        transportMode: 'walking',
        selectRouteIndex: () => {}
      };
      drawRouteTo = (_lat, _lon, options = {}) => {
        options.onRoutesAvailable(fakePayload);
        options.onRoutesAvailable(fakePayload); // 二重発火シミュレート
        return true;
      };
      const origAnnounce = voiceNav.announce;
      voiceNav.announce = (payload) => {
        if (payload && payload.id === 'block-ahead-reroute') window.__successCount++;
        origAnnounce && origAnnounce(payload);
      };
    }, makeBypassAlt());

    await page.evaluate(() => blockAheadAndReroute());

    const count = await page.evaluate(() => window.__successCount);
    expect(count).toBe(1);
  });

  test('再ルート成功時に drawRouteTo 経由でガイダンスと音声が更新される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate((bypassAlt) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__drawRouteToArgs = null;
      window.__renderedRouteCount = null;
      const origRenderRouteCandidatesOnMap = renderRouteCandidatesOnMap;
      renderRouteCandidatesOnMap = (routes, routeColors, selectedRouteIndex, selectRouteIndex) => {
        window.__renderedRouteCount = Array.isArray(routes) ? routes.length : -1;
        return origRenderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
      };
      _fetchOsrmAlternatives = async () => [bypassAlt];
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = { lat, lon, extraWaypoints: options.extraWaypoints || [] };
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0004, lng: 139.0014 },
              { lat: 35.0014, lng: 139.0014 },
              { lat: 35.004,  lng: 139.0 }
            ],
            summary: { totalDistance: 321.5, totalTime: 278.4 },
            instructions: [{ text: '迂回して進む', distance: 100, index: 1 }]
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
    }, makeBypassAlt());

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
    expect(state.drawRouteToArgs.extraWaypoints.length).toBeLessThanOrEqual(1); // anchor only (0 or 1)
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
    await page.evaluate((bypassAlt) => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmAlternatives = async () => [bypassAlt];
      drawRouteTo = (lat, lon, options = {}) => {
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0004, lng: 139.0014 },
              { lat: 35.0014, lng: 139.0014 },
              { lat: 35.004,  lng: 139.0 }
            ],
            summary: { totalDistance: 480, totalTime: 400 },
            instructions: [{ text: '迂回', distance: 100, index: 1 }]
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => d + 'm' },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    }, makeBypassAlt());

    await page.evaluate(() => blockAheadAndReroute());
    const timing = await page.evaluate(() => _blockAheadLastTiming);

    expect(timing).toBeTruthy();
    expect(timing.status).toBe('success');
    expect(timing.phasePath).toBe('AVOID_ACCEPT');
    expect(timing.fast.accepted).toBe(true);
    expect(timing.safe.attempted).toBe(false);
  });

  test('drawRouteTo が描画したルートがブロック内なら失敗として元ルートを維持する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(({ bypassAlt, blockedRoute }) => {
      // _fetchOsrmAlternatives returns a bypass route (passes pre-filter)
      // but drawRouteTo renders a blocked route (final overlap check fails)
      _fetchOsrmAlternatives = async () => [bypassAlt];
      drawRouteTo = (_lat, _lon, options = {}) => {
        options.onRoutesAvailable({
          routes: [{
            coordinates: blockedRoute,
            summary: { totalDistance: 300, totalTime: 240 }
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => d + 'm' },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    }, { bypassAlt: makeBypassAlt(), blockedRoute: BLOCKED_ROUTE });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルートを継続します');

    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      inProgress: navBlockAheadInProgress,
      hasLayer: _blockAheadLayer !== null
    }));

    expect(state.route).toBe(before);
    expect(state.inProgress).toBe(false);
    expect(state.hasLayer).toBe(false);
  });

  test('複数の代替ルートから最短の非ブロック経路を採用する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__drawRouteToArgs = null;
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
            { lat: 35.0004, lng: 139.0014 },
            { lat: 35.0014, lng: 139.0014 },
            { lat: 35.004,  lng: 139.0 }
          ],
          totalDistance: 520, totalTime: 420, turnCount: 2
        }
      ]);
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = { lat, lon, extraWaypoints: options.extraWaypoints || [] };
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0004, lng: 139.0014 },
              { lat: 35.0014, lng: 139.0014 },
              { lat: 35.004,  lng: 139.0 }
            ],
            summary: { totalDistance: 520, totalTime: 420 },
            instructions: [{ text: '迂回', distance: 100, index: 1 }]
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => d + 'm' },
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
      totalDistance: navActiveRoute.summary.totalDistance
    }));

    expect(state.mode).toBe('navigation_active');
    expect(state.inProgress).toBe(false);
    expect(state.totalDistance).toBe(520);
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

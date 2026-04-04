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
    await page.evaluate(() => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 350
      });
      // drawRouteTo は成功コールバックを呼ぶが、その前に stopNavigation を実行する
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
    });

    await page.evaluate(() => blockAheadAndReroute());

    const state = await page.evaluate(() => ({
      mode: navigationMode,
      inProgress: navBlockAheadInProgress
    }));
    // stopNavigation が先に走ったので browse のまま、inProgress も false
    expect(state.mode).toBe('browse');
    expect(state.inProgress).toBe(false);
  });

  test('onRoutesAvailable が二重発火しても reroute success は 1 回だけ実行される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__successCount = 0;
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 350
      });
      drawRouteTo = (_lat, _lon, options = {}) => {
        const fakePayload = {
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 321,
            totalTime: 240
          })],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => d + 'm' },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        };
        // routesfound と routeselected に相当する二重呼び出しをシミュレート
        options.onRoutesAvailable(fakePayload);
        options.onRoutesAvailable(fakePayload);
        return true;
      };
      const origAnnounce = voiceNav.announce;
      voiceNav.announce = (payload) => {
        if (payload && payload.id === 'block-ahead-reroute') window.__successCount++;
        origAnnounce && origAnnounce(payload);
      };
    });

    await page.evaluate(() => blockAheadAndReroute());

    const count = await page.evaluate(() => window.__successCount);
    expect(count).toBe(1); // 二重発火しても 1 回だけ
  });

  test('再ルート成功時に drawRouteTo 経由でガイダンスと音声が更新される', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      userDestination = { lat: 35.004, lon: 139.0, name: 'Test Destination' };
      window.__drawRouteToArgs = null;
      window.__renderedRouteCount = null;
      const origRenderRouteCandidatesOnMap = renderRouteCandidatesOnMap;
      renderRouteCandidatesOnMap = (routes, routeColors, selectedRouteIndex, selectRouteIndex) => {
        window.__renderedRouteCount = Array.isArray(routes) ? routes.length : -1;
        return origRenderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
      };
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 350
      });
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = {
          lat,
          lon,
          extraWaypoints: options.extraWaypoints || []
        };
        const fakeRoute = window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination);
        const formatter = {
          formatInstruction(instruction) { return instruction.text; },
          formatDistance(distance) { return `${Math.round(distance)}m`; }
        };
        options.onRoutesAvailable({
          routes: [
            fakeRoute,
            window.__buildWaypointRoute(currentLocation, [
              { lat: 35.00012, lng: 139.0001 },
              { lat: 35.0005, lng: 139.00035 },
              { lat: 35.002, lng: 139.00035 }
            ], navDestination, { totalDistance: 410, totalTime: 320 })
          ],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800', '#1e88e5'],
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
    expect(state.drawRouteToArgs.extraWaypoints.length).toBe(3); // blockStart + bypass + rejoin
    expect(state.voiceClearCount).toBeGreaterThan(0);
    expect(state.stepClearCount).toBeGreaterThan(0);
    expect(state.renderedRouteCount).toBe(1);
    expect(state.candidateLayerCount).toBe(1);
    expect(state.hasTempLayer).toBe(false);
    expect(state.routeOptionButtons).toBe(0);
    expect(state.voiceCalls.some(v => v && v.id === 'block-ahead-reroute')).toBeTruthy();
  });

  test('local stage では危険な大道路横断候補より safer crossing 候補を優先する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      window.__drawRouteToArgs = null;
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 360,
        turnCount: 1,
        sharpTurnCount: 0
      });
      _assessRouteCrossingRisk = async (routeLike) => {
        const hasRightBypass = routeLike.coordinates.some(point => (point.lng ?? point.lon) > 139.0);
        return hasRightBypass
          ? { available: true, dangerousCount: 0, uncontrolledCount: 0, penalty: 15, warningText: '' }
          : { available: true, dangerousCount: 1, uncontrolledCount: 0, penalty: 420, warningText: '途中に信号や明確な横断歩道が確認できない大きな道路横断があります' };
      };
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = { lat, lon, extraWaypoints: options.extraWaypoints || [] };
        options.onRoutesAvailable({
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 360,
            totalTime: 300
          })],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');
    const state = await page.evaluate(() => ({
      extraWaypoints: window.__drawRouteToArgs.extraWaypoints,
      crossingRisk: navActiveRoute.crossingRisk
    }));
    expect(state.extraWaypoints[1].lng).toBeGreaterThan(139.0);
    expect(state.crossingRisk.dangerousCount).toBe(0);
  });

  test('extended/reachability stage では危険横断が残っても到達可能なら採用する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: waypoints.map(wp => ({ lat: wp.lat, lng: wp.lng ?? wp.lon })),
        totalDistance: 980,
        turnCount: 1,
        sharpTurnCount: 0
      });
      _assessRouteCrossingRisk = async (_routeLike, stage) => ({
        available: true,
        dangerousCount: 1,
        uncontrolledCount: 0,
        penalty: 420,
        warningText: '途中に信号や明確な横断歩道が確認できない大きな道路横断があります'
      });
      drawRouteTo = (_lat, _lon, options = {}) => {
        options.onRoutesAvailable({
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 980,
            totalTime: 780
          })],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('大きな道路横断');
    const state = await page.evaluate(() => ({
      crossingRisk: navActiveRoute.crossingRisk,
      totalDistance: navActiveRoute.summary.totalDistance
    }));
    expect(state.crossingRisk.dangerousCount).toBe(1);
    expect(state.totalDistance).toBe(980);
  });

  test('危険横断が残る最終採用 route では warning 音声を追加する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 950,
        turnCount: 1,
        sharpTurnCount: 0
      });
      _assessRouteCrossingRisk = async () => ({
        available: true,
        dangerousCount: 1,
        uncontrolledCount: 0,
        penalty: 420,
        warningText: '途中に信号や明確な横断歩道が確認できない大きな道路横断があります'
      });
      drawRouteTo = (_lat, _lon, options = {}) => {
        options.onRoutesAvailable({
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 950,
            totalTime: 760
          })],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    const voiceIds = await page.evaluate(() => window.__voiceCalls.map(v => v && v.id).filter(Boolean));
    expect(voiceIds).toContain('block-ahead-crossing-warning');
  });

  test('最終 route が元ルートと実質同じなら no-op reroute として既存ルートを維持する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(() => {
      window.__drawRouteToArgs = null;
      window.__renderedRouteCount = 0;
      const origRenderRouteCandidatesOnMap = renderRouteCandidatesOnMap;
      renderRouteCandidatesOnMap = (routes, routeColors, selectedRouteIndex, selectRouteIndex) => {
        window.__renderedRouteCount += 1;
        return origRenderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
      };
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: waypoints.map(wp => ({ lat: wp.lat, lng: wp.lng ?? wp.lon })),
        totalDistance: 505,
        turnCount: 1,
        sharpTurnCount: 0
      });
      _assessRouteCrossingRisk = async () => ({
        available: false,
        crossings: [],
        dangerousCount: 0,
        uncontrolledCount: 0,
        penalty: 0,
        warningText: ''
      });
      drawRouteTo = (_lat, _lon, options = {}) => {
        window.__drawRouteToArgs = {
          preserveCurrentDisplay: options.preserveCurrentDisplay,
          extraWaypoints: options.extraWaypoints || []
        };
        options.onRoutesAvailable({
          routes: [{
            coordinates: JSON.parse(JSON.stringify(navActiveRoute.coordinates)),
            summary: { totalDistance: 500, totalTime: 360 }
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルート');

    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      drawRouteToArgs: window.__drawRouteToArgs,
      renderedRouteCount: window.__renderedRouteCount,
      timingStatus: _blockAheadLastTiming?.status
    }));

    expect(state.route).toBe(before);
    expect(state.drawRouteToArgs.preserveCurrentDisplay).toBe(true);
    expect(state.renderedRouteCount).toBe(0);
    expect(state.timingStatus).toBe('failed');
  });

  test('元の道路コリドーへ戻る候補は preliminary 段階で reject する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(() => {
      window.__drawRouteToCalled = false;
      _fetchOsrmRouteForEval = async (_waypoints) => ({
        coordinates: [
          { lat: 35.0001, lng: 139.0 },
          { lat: 35.0006, lng: 139.0 },
          { lat: 35.0011, lng: 139.0 },
          { lat: 35.0020, lng: 139.0 },
          { lat: 35.0040, lng: 139.0 }
        ],
        totalDistance: 520,
        turnCount: 0,
        sharpTurnCount: 0
      });
      drawRouteTo = () => {
        window.__drawRouteToCalled = true;
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルートを継続します');
    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      drawRouteToCalled: window.__drawRouteToCalled
    }));
    expect(state.route).toBe(before);
    expect(state.drawRouteToCalled).toBe(false);
  });

  test('timing サマリーを残し crossing 評価は shortlisted 候補に絞る', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      window.__crossingAssessCount = 0;
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: waypoints.map(wp => ({ lat: wp.lat, lng: wp.lng ?? wp.lon })),
        totalDistance: 350 + Math.abs((waypoints[2].lng ?? 139.0) - 139.0) * 10000,
        turnCount: 1,
        sharpTurnCount: 0
      });
      _assessRouteCrossingRisk = async (routeLike) => {
        window.__crossingAssessCount += 1;
        const dangerous = routeLike.coordinates.some(point => (point.lng ?? point.lon) < 139.0) ? 1 : 0;
        return {
          available: true,
          crossings: [],
          dangerousCount: dangerous,
          uncontrolledCount: 0,
          penalty: dangerous ? 320 : 0,
          warningText: dangerous ? '途中に信号や明確な横断歩道が確認できない大きな道路横断があります' : ''
        };
      };
      drawRouteTo = (_lat, _lon, options = {}) => {
        options.onRoutesAvailable({
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 360,
            totalTime: 300
          })],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    const state = await page.evaluate(() => ({
      crossingAssessCount: window.__crossingAssessCount,
      timing: _blockAheadLastTiming
    }));
    expect(state.timing.status).toBe('success');
    expect(state.timing.totalMs).toBeGreaterThanOrEqual(0);
    expect(state.timing.stages.length).toBeGreaterThan(0);
    expect(state.timing.stages[0].shortlisted).toBeLessThanOrEqual(state.timing.stages[0].candidates);
    expect(state.timing.stages[0].candidates).toBeLessThanOrEqual(4);
    expect(state.timing.stages[0].shortlisted).toBeLessThanOrEqual(3);
    expect(state.timing.stages[0].finalTried).toBeLessThanOrEqual(2);
    expect(state.crossingAssessCount).toBeGreaterThan(0);
  });

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
              { lat: currentLocation.lat, lng: currentLocation.lon },
              { lat: waypoints[1].lat, lng: waypoints[1].lng },
              { lat: bypass.lat, lng: bypass.lng },
              { lat: waypoints[3].lat, lng: waypoints[3].lng },
              { lat: navDestination.lat, lng: navDestination.lon }
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
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 360,
            totalTime: 300
          })],
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

  test('少し長くても曲がり角の少ない候補を優先する', async ({ page }) => {
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
              { lat: currentLocation.lat, lng: currentLocation.lon },
              { lat: waypoints[1].lat, lng: waypoints[1].lng },
              { lat: bypass.lat, lng: bypass.lng },
              { lat: waypoints[3].lat, lng: waypoints[3].lng },
              { lat: navDestination.lat, lng: navDestination.lon }
            ],
            totalDistance: 330,
            turnCount: 1,
            sharpTurnCount: 0
          };
        }
        return {
          coordinates: [
            { lat: 35.0001, lng: 138.9988 },
            { lat: 35.0008, lng: 138.9991 },
            { lat: 35.0013, lng: 138.9987 },
            { lat: 35.0020, lng: 138.9990 },
            { lat: 35.0040, lng: 139.0 }
          ],
          totalDistance: 300,
          turnCount: 4,
          sharpTurnCount: 1
        };
      };
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = {
          lat,
          lon,
          extraWaypoints: options.extraWaypoints || []
        };
        options.onRoutesAvailable({
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 330,
            totalTime: 300
          })],
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

  test('初動がわかりにくい候補より自然な候補を優先する', async ({ page }) => {
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
              { lat: currentLocation.lat, lng: currentLocation.lon },
              { lat: waypoints[1].lat, lng: waypoints[1].lng },
              { lat: bypass.lat, lng: bypass.lng },
              { lat: waypoints[3].lat, lng: waypoints[3].lng },
              { lat: navDestination.lat, lng: navDestination.lon }
            ],
            totalDistance: 365,
            turnCount: 2,
            sharpTurnCount: 0
          };
        }
        return {
          coordinates: [
            { lat: currentLocation.lat, lng: currentLocation.lon },
            { lat: 35.00015, lng: 139.0 },
            { lat: 35.00015, lng: 138.99945 },
            { lat: 35.0012, lng: 138.99945 },
            { lat: 35.0012, lng: 139.0 },
            { lat: navDestination.lat, lng: navDestination.lon }
          ],
          totalDistance: 320,
          turnCount: 2,
          sharpTurnCount: 1
        };
      };
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = {
          lat,
          lon,
          extraWaypoints: options.extraWaypoints || []
        };
        options.onRoutesAvailable({
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 365,
            totalTime: 310
          })],
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

  test('local detour が失敗しても extended detour で到達可能なら採用する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      window.__drawRouteToArgs = null;
      _fetchOsrmRouteForEval = async (waypoints) => {
        const rejoin = waypoints[3];
        if (waypoints.length === 5 && rejoin && rejoin.lat > 35.0021) {
          return {
            coordinates: [
              { lat: currentLocation.lat, lng: currentLocation.lon },
              { lat: waypoints[1].lat, lng: waypoints[1].lng },
              { lat: waypoints[2].lat, lng: waypoints[2].lng },
              { lat: rejoin.lat, lng: rejoin.lng },
              { lat: navDestination.lat, lng: navDestination.lon }
            ],
            totalDistance: 780,
            turnCount: 2,
            sharpTurnCount: 0
          };
        }
        return null;
      };
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = { lat, lon, extraWaypoints: options.extraWaypoints || [] };
        options.onRoutesAvailable({
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 780,
            totalTime: 620
          })],
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
      extraWaypoints: window.__drawRouteToArgs.extraWaypoints,
      totalDistance: navActiveRoute.summary.totalDistance
    }));
    expect(state.extraWaypoints).toHaveLength(3);
    expect(state.extraWaypoints[2].lat).toBeGreaterThan(35.0021);
    expect(state.totalDistance).toBe(780);
  });

  test('local/extended が失敗しても direct bypass で到達可能なら採用する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    await page.evaluate(() => {
      window.__drawRouteToArgs = null;
      _fetchOsrmRouteForEval = async (waypoints) => {
        if (waypoints.length === 4) {
          return {
            coordinates: [
              { lat: currentLocation.lat, lng: currentLocation.lon },
              { lat: waypoints[1].lat, lng: waypoints[1].lng },
              { lat: waypoints[2].lat, lng: waypoints[2].lng },
              { lat: navDestination.lat, lng: navDestination.lon }
            ],
            totalDistance: 1200,
            turnCount: 2,
            sharpTurnCount: 0
          };
        }
        return null;
      };
      drawRouteTo = (lat, lon, options = {}) => {
        window.__drawRouteToArgs = { lat, lon, extraWaypoints: options.extraWaypoints || [] };
        options.onRoutesAvailable({
          routes: [window.__buildWaypointRoute(currentLocation, options.extraWaypoints || [], navDestination, {
            totalDistance: 1200,
            totalTime: 980
          })],
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
      extraWaypoints: window.__drawRouteToArgs.extraWaypoints,
      totalDistance: navActiveRoute.summary.totalDistance
    }));
    expect(state.extraWaypoints).toHaveLength(2);
    expect(state.totalDistance).toBe(1200);
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

  test('広域でも到達可能な hazard-avoiding ルートは最終段階で採用する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(() => {
      window.__drawAttempts = 0;
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 360,
        turnCount: 1,
        sharpTurnCount: 0
      });
      drawRouteTo = (_lat, _lon, options = {}) => {
        window.__drawAttempts += 1;
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: 35.0001, lng: 139.0 },
              { lat: 35.0005, lng: 139.0001 },
              { lat: 35.0035, lng: 139.0025 },
              { lat: 35.0040, lng: 139.0 }
            ],
            summary: { totalDistance: 900, totalTime: 700 }
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('迂回ルートに切り替えました');

    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      drawAttempts: window.__drawAttempts,
      inProgress: navBlockAheadInProgress,
      hasLayer: _blockAheadLayer !== null,
      totalDistance: navActiveRoute.summary.totalDistance
    }));

    expect(state.route).not.toBe(before);
    expect(state.drawAttempts).toBeGreaterThan(0);
    expect(state.inProgress).toBe(false);
    expect(state.hasLayer).toBe(false);
    expect(state.totalDistance).toBe(900);
  });

  test('確定後の初動が短い枝道と急ターンになるルートは棄却して元ルートを保持する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(() => {
      window.__drawAttempts = 0;
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 360,
        turnCount: 2,
        sharpTurnCount: 0
      });
      drawRouteTo = (_lat, _lon, options = {}) => {
        window.__drawAttempts += 1;
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: currentLocation.lat, lng: currentLocation.lon },
              { lat: 35.00015, lng: 139.0 },
              { lat: 35.00015, lng: 139.00025 },
              { lat: 35.00055, lng: 139.00025 },
              { lat: 35.0040, lng: 139.0 }
            ],
            summary: { totalDistance: 380, totalTime: 320 }
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルートを継続します');

    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      drawAttempts: window.__drawAttempts,
      inProgress: navBlockAheadInProgress,
      hasLayer: _blockAheadLayer !== null
    }));

    expect(state.route).toBe(before);
    expect(state.drawAttempts).toBeGreaterThan(0);
    expect(state.inProgress).toBe(false);
    expect(state.hasLayer).toBe(false);
  });

  test('確定後の初動が折り返して開始点近くへ戻るルートは棄却して元ルートを保持する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(() => {
      window.__drawAttempts = 0;
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 360,
        turnCount: 2,
        sharpTurnCount: 0
      });
      drawRouteTo = (_lat, _lon, options = {}) => {
        window.__drawAttempts += 1;
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: currentLocation.lat, lng: currentLocation.lon },
              { lat: 35.0001, lng: 139.00028 },
              { lat: 35.0001, lng: 139.00004 },
              { lat: 35.00055, lng: 139.00004 },
              { lat: 35.0040, lng: 139.0 }
            ],
            summary: { totalDistance: 385, totalTime: 330 }
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルートを継続します');

    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      drawAttempts: window.__drawAttempts,
      inProgress: navBlockAheadInProgress,
      hasLayer: _blockAheadLayer !== null
    }));

    expect(state.route).toBe(before);
    expect(state.drawAttempts).toBeGreaterThan(0);
    expect(state.inProgress).toBe(false);
    expect(state.hasLayer).toBe(false);
  });

  test('確定後に同じ交差点へ戻る spur 付きルートは棄却して元ルートを保持する', async ({ page }) => {
    await bootstrap(page);
    await seedNav(page);
    const before = await page.evaluate(() => JSON.stringify(navActiveRoute));

    await page.evaluate(() => {
      window.__drawAttempts = 0;
      _fetchOsrmRouteForEval = async (waypoints) => ({
        coordinates: [
          { lat: currentLocation.lat, lng: currentLocation.lon },
          { lat: waypoints[1].lat, lng: waypoints[1].lng },
          { lat: waypoints[2].lat, lng: waypoints[2].lng },
          { lat: waypoints[3].lat, lng: waypoints[3].lng },
          { lat: navDestination.lat, lng: navDestination.lon }
        ],
        totalDistance: 360,
        turnCount: 3,
        sharpTurnCount: 0
      });
      drawRouteTo = (_lat, _lon, options = {}) => {
        window.__drawAttempts += 1;
        const junction = { lat: 35.00042, lng: 138.99975 };
        options.onRoutesAvailable({
          routes: [{
            coordinates: [
              { lat: currentLocation.lat, lng: currentLocation.lon },
              junction,
              { lat: 35.00115, lng: 138.99975 },
              junction,
              { lat: 35.00042, lng: 138.9992 },
              { lat: 35.0040, lng: 139.0 }
            ],
            summary: { totalDistance: 410, totalTime: 350 }
          }],
          selectedRouteIndex: 0,
          routeColors: ['#ff9800'],
          formatter: { formatInstruction: i => i.text, formatDistance: d => `${Math.round(d)}m` },
          transportMode: 'walking',
          selectRouteIndex: () => {}
        });
        return true;
      };
    });

    await page.evaluate(() => blockAheadAndReroute());
    await expect(page.locator('#navBanner')).toContainText('現在のルートを継続します');

    const state = await page.evaluate(() => ({
      route: JSON.stringify(navActiveRoute),
      drawAttempts: window.__drawAttempts,
      inProgress: navBlockAheadInProgress,
      hasLayer: _blockAheadLayer !== null
    }));

    expect(state.route).toBe(before);
    expect(state.drawAttempts).toBeGreaterThan(0);
    expect(state.inProgress).toBe(false);
    expect(state.hasLayer).toBe(false);
  });
});

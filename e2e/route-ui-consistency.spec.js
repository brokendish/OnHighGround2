'use strict';

const { test, expect } = require('@playwright/test');

function makeRoute(index, score, riskLevel) {
  const label = `候補${index + 1}`;
  return {
    route_id: index,
    label,
    safety_score: score,
    risk_level: riskLevel,
    risk_summary: [`${label} summary`],
    recommended: index === 0,
    summary: {
      totalDistance: 1000 + index * 120,
      totalTime: 600 + index * 90,
    },
    __displayLabel: index === 0 ? '推奨' : '',
    __riskSummary: {
      safety_score: score,
      risk_level: riskLevel,
      risk_summary: { notes: [`${label} summary`] },
    },
  };
}

test.describe('Route UI consistency', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('/api/**', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: '{}',
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.goto('/');
  });

  test('route selection and comparison share score, risk, label, and selection', async ({ page }) => {
    const routes = [
      makeRoute(0, 73, 'caution'),
      makeRoute(1, 82, 'safe'),
      makeRoute(2, 82, 'safe'),
    ];

    await page.evaluate((candidateRoutes) => {
      window.setNavMode('route_preview');
      window.__routeUiSelected = 0;
      window.__routeUiRoutes = candidateRoutes;
      window.__routeUiSelect = (selectedRouteIndex) => {
        window.__routeUiSelected = selectedRouteIndex;
        window._lipUpdateRouteSelection({
          selectedRouteIndex,
          routes: window.__routeUiRoutes,
          onSelectRouteIndex: window.__routeUiSelect,
        });
      };
      window._lipUpdateRouteSelection({
        route: candidateRoutes[0],
        selectedRouteIndex: 0,
        transportMode: 'walking',
        mode: 'route_preview',
        routes: candidateRoutes,
        routeColors: ['#1976d2', '#2e7d32', '#f59e0b'],
        onSelectRouteIndex: window.__routeUiSelect,
      });
    }, routes);

    const selectionRows = page.locator('#lip-route-options .route-option-button');
    const comparisonRows = page.locator('#lip-route-weather-compare .rui-compare-row');
    await expect(selectionRows).toHaveCount(3);
    await expect(comparisonRows).toHaveCount(3);

    for (let index = 0; index < 3; index += 1) {
      await expect(selectionRows.nth(index)).toContainText(`候補${index + 1}`);
      await expect(comparisonRows.nth(index)).toContainText(`候補${index + 1}`);
      await expect(selectionRows.nth(index)).toContainText(`安全度 ${routes[index].safety_score}`);
      await expect(comparisonRows.nth(index)).toContainText(`安全度 ${routes[index].safety_score}`);
      await expect(selectionRows.nth(index)).toContainText(routes[index].risk_level === 'safe' ? '安全' : '注意');
      await expect(comparisonRows.nth(index)).toContainText(routes[index].risk_level === 'safe' ? '安全' : '注意');
    }

    await expect(selectionRows.nth(0)).toHaveClass(/active/);
    await expect(comparisonRows.nth(0)).toHaveClass(/rui-compare-row--selected/);

    await selectionRows.nth(1).evaluate(el => el.click());
    await expect(selectionRows.nth(1)).toHaveClass(/active/);
    await expect(comparisonRows.nth(1)).toHaveClass(/rui-compare-row--selected/);
    await expect(selectionRows.nth(0)).not.toHaveClass(/active/);
    await expect(comparisonRows.nth(0)).not.toHaveClass(/rui-compare-row--selected/);
  });
});

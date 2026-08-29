/**
 * location-info-panel-hazard.spec.js — 位置情報パネル（#lip-dest-hazard）の
 * HAZARD_DETECTED / NO_HAZARD_RECORD / SOURCE_UNAVAILABLE 3状態 exact表示テスト
 * (Phase 2-D Round 12D-B1、変更2)。
 *
 * frontend/js/location-info-panel.js の _lipDescribeDestinationHazard() は
 * destinations[].hazard_coverage_status から computeAggregateStatus() 経由で
 * 3状態を判定し、判定あり/空文字へfallbackさせず exact文言を表示する契約。
 *
 * #lip-dest-hazard は「情報タブ」(#mbc-tab-panel-info) 内の
 * #loc-info-route（ルートプレビュー/ナビ中のみ表示）にあるため、
 * 候補カードをクリックして showRoute() → onNavRouteSelected(infoMode:'route_preview')
 * を発火させることで表示させる（navigation.js 自体は一切改変しない）。
 */

'use strict';

const { test, expect } = require('@playwright/test');

const STATUS_MAP = { outside: 'NO_HAZARD_RECORD', unknown: 'SOURCE_UNAVAILABLE', inside: 'HAZARD_DETECTED' };

function makeCoverageStatus(tsunamiStatus, floodStatus = 'outside') {
  return {
    flood: STATUS_MAP[floodStatus] || 'NO_HAZARD_RECORD',
    storm_surge: 'NO_HAZARD_RECORD',
    tsunami: STATUS_MAP[tsunamiStatus] || 'NO_HAZARD_RECORD',
    inland_flood: 'NO_HAZARD_RECORD',
    landslide: 'NO_HAZARD_RECORD',
    lowland_poor_drainage: 'NO_HAZARD_RECORD',
  };
}

function makeEvacuationBody(tsunamiStatus, floodStatus = 'outside') {
  const coverage = makeCoverageStatus(tsunamiStatus, floodStatus);
  const hazardSafe = Object.values(coverage).includes('HAZARD_DETECTED') ? false : null;
  const dest = {
    name: '東雲小学校',
    type: 'emergency_shelter',
    lat: 35.65,
    lon: 139.80,
    elevation: 5.0,
    elevation_gain: 1.5,
    distance: 800,
    estimated_time_minutes: 12,
    safety_score: 45.0,
    hazard_safe: hazardSafe,
    hazard_coverage_status: coverage,
    hazard_assessment: { tsunami: tsunamiStatus, flood: floodStatus },
  };
  return {
    current_location: { lat: 35.6415, lon: 139.7905, elevation: 3.5 },
    hazard_status: { is_danger: false, hazards: [] },
    time_to_impact: { supported: false },
    recommended: { ...dest, reason: 'テスト用' },
    destinations: [dest],
    search_parameters: { transport_mode: 'walking', max_distance: 2000, min_elevation_gain: 10 },
  };
}

async function setupMocks(page, tsunamiStatus, floodStatus = 'outside') {
  await page.route('/api/elevation**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ elevation: 3.5, lat: 35.6415, lon: 139.7905 }),
  }));
  await page.route('/api/hazard-check**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ is_danger: false, hazards: [], hazard_assessment: {} }),
  }));
  await page.route('/api/evacuation', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify(makeEvacuationBody(tsunamiStatus, floodStatus)),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  // showRoute() が発火させる OSRM ルート取得は失敗させてよい
  // (onNavRouteSelected(null, destination, ...) は OSRM 応答より前に同期発火するため
  //  #lip-dest-hazard の表示には影響しない)。
  await page.route('**/osrm/**', route => route.fulfill({ status: 500, body: 'mocked: no route' }));
}

async function openSidebarAndSearch(page) {
  const wrapper = page.locator('#sidebarWrapper');
  const isOpen = await wrapper.evaluate(el => !el.classList.contains('collapsed'));
  if (!isOpen) {
    await page.locator('#sidebarToggle').click();
    await expect(wrapper).not.toHaveClass(/collapsed/, { timeout: 3000 });
  }
  await page.locator('#getCurrentLocation').click();
  await expect(page.locator('#getCurrentLocation')).toHaveText('現在地を取得', { timeout: 8000 });
  const searchBtn = page.locator('#searchDestinations');
  await expect(searchBtn).toBeEnabled({ timeout: 5000 });
  await searchBtn.click();
  await expect(page.locator('#destinationsPanel')).toBeVisible({ timeout: 10000 });
}

async function openInfoTabAndPreviewFirstDestination(page) {
  await page.locator('#mbc-tab-btn-info').click();
  await expect(page.locator('#mbc-tab-panel-info')).toBeVisible({ timeout: 5000 });
  await page.locator('.destination-card').first().click();
  await expect(page.locator('#loc-info-route')).toBeVisible({ timeout: 5000 });
}

const FORBIDDEN_ASCII_TOKENS = ['safe', 'confirmed safe', 'safety confirmed'];
const FORBIDDEN_JP_TOKENS = ['安全', '安全候補', '危険区域外'];

function assertNoForbiddenTokens(text) {
  const lowered = text.casefold ? text.casefold() : text.toLowerCase();
  for (const tok of FORBIDDEN_ASCII_TOKENS) {
    expect(lowered.includes(tok)).toBe(false);
  }
  for (const tok of FORBIDDEN_JP_TOKENS) {
    expect(text.includes(tok)).toBe(false);
  }
}

test.describe('Location Info Panel: #lip-dest-hazard 3状態 exact表示テスト', () => {

  test('HAZARD_DETECTED (tsunami=inside) のとき「⚠️ ハザード検出」を表示する', async ({ page }) => {
    await setupMocks(page, 'inside');
    await page.goto('/');
    await openSidebarAndSearch(page);
    await openInfoTabAndPreviewFirstDestination(page);

    const row = page.locator('#lip-dest-hazard');
    await expect(row).toHaveText('⚠️ ハザード検出');
  });

  test('NO_HAZARD_RECORD (全ハザード該当記録なし) のとき exact表示・禁止token 0件', async ({ page }) => {
    await setupMocks(page, 'outside');
    await page.goto('/');
    await openSidebarAndSearch(page);
    await openInfoTabAndPreviewFirstDestination(page);

    const row = page.locator('#lip-dest-hazard');
    await expect(row).toHaveText('✔ 該当ハザード記録なし（危険がないことを示すものではありません）');
    assertNoForbiddenTokens(await row.textContent());
  });

  test('SOURCE_UNAVAILABLE (tsunami=unknown) のとき exact表示・「判定あり」へfallbackしない・禁止token 0件', async ({ page }) => {
    await setupMocks(page, 'unknown');
    await page.goto('/');
    await openSidebarAndSearch(page);
    await openInfoTabAndPreviewFirstDestination(page);

    const row = page.locator('#lip-dest-hazard');
    await expect(row).toHaveText('❓ ハザード情報を確認できません');
    const text = await row.textContent();
    expect(text).not.toBe('判定あり');
    expect(text.trim()).not.toBe('');
    assertNoForbiddenTokens(text);
  });

});

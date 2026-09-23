'use strict';

/**
 * JMA-2026-WARNING-CODE-UPDATE-AND-UNKNOWN-FAILSAFE
 *
 * - レベル２土砂災害注意報（code 29）が正式名称・注意報として気象カード/バナーに出る
 * - 未分類コード（真の unknown）のみの場合に「警報・注意報なし」/ riskLevel none と扱わない
 * - _computeRiskLevel が unknown を none に落とさない
 */

const { test, expect } = require('@playwright/test');

function alertItem(rawCode, kind, severity, level, status) {
  return {
    area_code: '1336100', area_name: '大島町', source_area_type: null,
    kind, level, severity, status, headline: `${kind} ${status}`,
    issued_at: '2026-09-23T01:52:00+09:00', updated_at: '2026-09-23T01:52:00+09:00',
    source: 'jma', raw_code: rawCode,
  };
}

const CODE29 = alertItem('29', 'レベル２土砂災害注意報', 'advisory', '注意報', '継続');
const UNKNOWN99 = alertItem('99', '警報・注意報（コード99）', 'unknown', '不明', '発表');

async function openInfoTabWithAlerts(page, { severity, alerts, contextRisk }) {
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.route('/api/**', route => route.fulfill({
    status: 200, contentType: 'application/json', body: '{}',
  }));
  await page.route('/api/weather/alerts/current**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      status: 'ok', severity, alerts,
      location: { area_name: '東京都', city: '大島町' },
      updated_at: '2026-09-23T01:52:00+09:00',
      message: null,
    }),
  }));
  await page.route('/api/weather/precipitation/summary**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({
      status: 'ok', severity: 'none',
      current: { intensity: 'none', label: '降水なし' }, forecast: [],
    }),
  }));
  await page.route('/api/weather/risk/context**', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ status: 'ok', risk_level: contextRisk, combined: [], hazards: {} }),
  }));
  await page.goto('/');
  return page.evaluate(async () => {
    switchMbcTab('info');
    _lipUpdateNavMode('browse');
    const r = await _weatherServiceUpdate(34.75, 139.36);
    return r.riskInfo.riskLevel;
  });
}

test.describe('JMA 2026 warning codes / unknown fail-safe', () => {
  test('code 29: レベル２土砂災害注意報が注意報としてカード・バナーに表示される', async ({ page }) => {
    const riskLevel = await openInfoTabWithAlerts(page, {
      severity: 'advisory', alerts: [CODE29], contextRisk: 'advisory',
    });
    expect(riskLevel).toBe('advisory');

    const row = page.locator('#lip-wc-alert-list .wc-alert-row');
    await expect(row).toHaveCount(1);
    await expect(row).toHaveClass(/wc-alert--advisory/);
    await expect(row).toHaveClass(/wc-alert--high-priority/);
    await expect(row.locator('.wc-alert-kind')).toHaveText('レベル２土砂災害注意報');
    await expect(page.locator('#lip-wc-alert-list')).not.toContainText('コード29');
    await expect(page.locator('#lip-wc-status-badge')).toHaveText('注意報');

    const banner = page.locator('#weather-alert-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveClass(/wa-banner--advisory/);
    await expect(banner).toContainText('注意報: レベル２土砂災害注意報');
  });

  test('真の unknown のみ: 「警報・注意報なし」と表示せず riskLevel を none にしない', async ({ page }) => {
    // backend risk context は修正後 unknown を返すが、旧 backend（none）でも frontend 単独で none に落ちないこと
    const riskLevel = await openInfoTabWithAlerts(page, {
      severity: 'unknown', alerts: [UNKNOWN99], contextRisk: 'none',
    });
    expect(riskLevel).toBe('unknown');

    const list = page.locator('#lip-wc-alert-list');
    await expect(list).not.toContainText('警報・注意報なし');
    await expect(list.locator('.wc-alert-row.wc-alert--unknown .wc-alert-kind'))
      .toHaveText('警報・注意報（コード99）');
    await expect(page.locator('#lip-weather-card-header')).toHaveClass(/wc-header--unknown/);
    await expect(page.locator('#lip-weather-card-header')).not.toHaveClass(/wc-header--none/);
  });

  test('_computeRiskLevel: unknown alert は既知リスクを上書きせず none にもならない', async ({ page }) => {
    await page.route('/emergency-shelters**', route => route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('/api/**', route => route.fulfill({
      status: 200, contentType: 'application/json', body: '{}',
    }));
    await page.goto('/');
    const results = await page.evaluate(() => ({
      unknownOnly:      _computeRiskLevel({ severity: 'unknown' }, { severity: 'none' }, { risk_level: 'none' }),
      unknownNoCtx:     _computeRiskLevel({ severity: 'unknown' }, { severity: 'none' }, null),
      code29:           _computeRiskLevel({ severity: 'advisory' }, { severity: 'none' }, { risk_level: 'advisory' }),
      unknownPlusRain:  _computeRiskLevel({ severity: 'unknown' }, { severity: 'warning' }, { risk_level: 'unknown' }),
      unknownPlusCtxEm: _computeRiskLevel({ severity: 'unknown' }, { severity: 'none' }, { risk_level: 'emergency' }),
      noneAll:          _computeRiskLevel({ severity: 'none' }, { severity: 'none' }, { risk_level: 'none' }),
      ctxUnknown:       _computeRiskLevel({ severity: 'none' }, { severity: 'none' }, { risk_level: 'unknown' }),
    }));
    expect(results).toEqual({
      unknownOnly: 'unknown',
      unknownNoCtx: 'unknown',
      code29: 'advisory',
      unknownPlusRain: 'warning',
      unknownPlusCtxEm: 'emergency',
      noneAll: 'none',
      ctxUnknown: 'unknown',
    });
  });
});

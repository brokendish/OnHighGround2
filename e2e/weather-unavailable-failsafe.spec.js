'use strict';

/**
 * WEATHER-ALERTS-UNAVAILABLE-RISK-FAILSAFE
 *
 * - 警報・降水の取得失敗を「なし」・空欄にせず「取得できません」を表示する
 * - 取得失敗時の riskLevel を none にしない（backend _compute_risk_level と同じ判定）
 * - 正常 none は従来どおり
 *
 * API を HTTP 500 / 正常 JSON でモックし、実際の weather-service fetch → 描画経路を通す。
 */

const { test, expect } = require('@playwright/test');

const ALERTS_NONE = {
  status: 'ok', severity: 'none', alerts: [],
  location: { area_name: '東京都', city: '江東区' },
  updated_at: '2026-09-23T01:00:00+09:00', message: '警報・注意報なし',
};
const ALERTS_WARNING = {
  ...ALERTS_NONE, severity: 'warning', message: null,
  alerts: [{
    area_code: '1310800', area_name: '江東区', source_area_type: null,
    kind: '大雨警報', level: '警報', severity: 'warning', status: '発表',
    headline: '大雨警報 発表', issued_at: null, updated_at: null, source: 'jma', raw_code: '03',
  }],
};
const PRECIP_NONE = {
  status: 'ok', severity: 'none', summary: '降水なし',
  current: { intensity: 'none', label: '降水なし' }, forecast: [],
};

function json(body) {
  return route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
}
const fail500 = route => route.fulfill({ status: 500, contentType: 'application/json', body: '{}' });

async function renderWeather(page, { alerts, precip, context }) {
  await page.route('/emergency-shelters**', json({ data: [], count: 0, total_count: 0 }));
  await page.route('/api/**', json({}));
  await page.route('/api/weather/alerts/current**', alerts === 'fail' ? fail500 : json(alerts));
  await page.route('/api/weather/precipitation/summary**', precip === 'fail' ? fail500 : json(precip));
  await page.route('/api/weather/risk/context**', json(context));
  await page.goto('/');
  return page.evaluate(async () => {
    switchMbcTab('info');
    _lipUpdateNavMode('browse');
    const r = await _weatherServiceUpdate(35.6415, 139.7905);
    return r.riskInfo.riskLevel;
  });
}

// backend risk context の修正後レスポンス相当
const CTX = (risk, alertStatus = 'ok', precipStatus = 'ok') => ({
  status: 'ok', risk_level: risk, combined: [], hazards: {},
  weather: { alert_status: alertStatus, precip_status: precipStatus },
});

test.describe('Weather unavailable fail-safe', () => {
  test('警報取得失敗: 「取得できません」を表示し「警報・注意報なし」にしない', async ({ page }) => {
    const risk = await renderWeather(page, {
      alerts: 'fail', precip: PRECIP_NONE, context: CTX('unknown', 'unavailable'),
    });
    expect(risk).toBe('unknown');
    const list = page.locator('#lip-wc-alert-list');
    await expect(list).toContainText('警報・注意報：取得できません');
    await expect(list).not.toContainText('警報・注意報なし');
    await expect(page.locator('#lip-wc-message')).toContainText('気象情報を取得できません');
    await expect(page.locator('#lip-weather-card-header')).not.toHaveClass(/wc-header--none/);
  });

  test('降水取得失敗: 降水欄が空欄にならず「取得できません」を表示する', async ({ page }) => {
    const risk = await renderWeather(page, {
      alerts: ALERTS_NONE, precip: 'fail', context: CTX('unknown', 'ok', 'unavailable'),
    });
    expect(risk).toBe('unknown');
    const precip = page.locator('#lip-wc-precip-summary');
    await expect(precip).toHaveText('取得できません');
    await expect(precip).not.toContainText('降水なし');
    await expect(page.locator('#lip-wc-alert-list')).toContainText('警報・注意報なし');
    await expect(page.locator('#lip-weather-card-header')).toHaveClass(/wc-header--unknown/);
  });

  test('両方取得失敗: 正常 none に見えない', async ({ page }) => {
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    const risk = await renderWeather(page, {
      alerts: 'fail', precip: 'fail', context: CTX('unknown', 'unavailable', 'unavailable'),
    });
    expect(risk).toBe('unknown');
    await expect(page.locator('#lip-wc-alert-list')).toContainText('取得できません');
    await expect(page.locator('#lip-wc-precip-summary')).toHaveText('取得できません');
    await expect(page.locator('#lip-wc-alert-list')).not.toContainText('警報・注意報なし');
    await expect(page.locator('#lip-weather-card-header')).not.toHaveClass(/wc-header--none/);
    expect(errors).toEqual([]);
  });

  test('正常 none: 従来表示・取得失敗文言なし', async ({ page }) => {
    const risk = await renderWeather(page, {
      alerts: ALERTS_NONE, precip: PRECIP_NONE, context: CTX('none'),
    });
    expect(risk).toBe('none');
    await expect(page.locator('#lip-wc-alert-list')).toContainText('警報・注意報なし');
    await expect(page.locator('#lip-wc-precip-summary')).toContainText('現在: 降水なし');
    await expect(page.locator('.lip-accordion-body').filter({ has: page.locator('#lip-wc-alert-list') }))
      .not.toContainText('取得できません');
    await expect(page.locator('#lip-weather-card-header')).toHaveClass(/wc-header--none/);
    await expect(page.locator('#weather-alert-banner')).toBeHidden();
  });

  test('既知 warning + 降水取得失敗: warning 表示を維持', async ({ page }) => {
    const risk = await renderWeather(page, {
      alerts: ALERTS_WARNING, precip: 'fail', context: CTX('warning', 'ok', 'unavailable'),
    });
    expect(risk).toBe('warning');
    await expect(page.locator('#lip-wc-alert-list .wc-alert-kind')).toHaveText('大雨警報');
    await expect(page.locator('#lip-wc-precip-summary')).toHaveText('取得できません');
    await expect(page.locator('#weather-alert-banner')).toHaveClass(/wa-banner--warning/);
    await expect(page.locator('#weather-alert-banner')).toContainText('大雨警報');
  });

  test('_computeRiskLevel: Case A〜H が backend と一致（context が none でも none に落ちない）', async ({ page }) => {
    await page.route('/emergency-shelters**', json({ data: [], count: 0, total_count: 0 }));
    await page.route('/api/**', json({}));
    await page.goto('/');
    const results = await page.evaluate(() => {
      const A = (status, severity) => ({ status, severity });
      const unavailAlerts = { status: 'unavailable', severity: 'none', alerts: [] };  // backend 実失敗形
      const unavailPrecip = { status: 'unavailable', severity: 'none' };               // backend 実失敗形
      const ctxNone = { risk_level: 'none' };  // 旧 backend 相当: frontend 単独でも none に落ちないこと
      const cases = {
        A: [unavailAlerts, A('ok', 'none'), ctxNone],
        B: [A('ok', 'none'), unavailPrecip, ctxNone],
        C: [unavailAlerts, unavailPrecip, ctxNone],
        D: [A('ok', 'none'), A('ok', 'none'), ctxNone],
        E: [A('ok', 'unknown'), A('ok', 'none'), ctxNone],
        F: [A('ok', 'warning'), unavailPrecip, ctxNone],
        G: [A('ok', 'emergency'), unavailPrecip, ctxNone],
        H: [A('ok', 'advisory'), unavailPrecip, ctxNone],
      };
      const out = {};
      for (const [k, args] of Object.entries(cases)) out[k] = _computeRiskLevel(...args);
      return out;
    });
    expect(results).toEqual({
      A: 'unknown', B: 'unknown', C: 'unknown', D: 'none',
      E: 'unknown', F: 'warning', G: 'emergency', H: 'advisory',
    });
  });

  test('状況理解カード: 降水取得失敗で降水行を消さず「取得できません」を表示', async ({ page }) => {
    await renderWeather(page, {
      alerts: ALERTS_NONE, precip: 'fail', context: CTX('unknown', 'ok', 'unavailable'),
    });
    await page.evaluate(() => {
      window.kikikuruGetRiskSnapshot = () => ({
        current: { status: 'off' }, dest: { status: 'off' }, route: { status: 'off' },
      });
      situationCardOnRouteUpdate({
        safety_score: 90, risk_level: 'safe', risk_summary: { notes: [], hazards: [] },
        kikikuru_adjustment: { enabled: false, status: 'off', penalty: 0, max_level: null, matched_hazards: [], summary: [] },
      });
      const tabPanel = document.getElementById('mbc-tab-panel-info');
      if (tabPanel) tabPanel.style.display = '';
      const routeEl = document.getElementById('loc-info-route');
      if (routeEl) routeEl.style.display = '';
    });
    const body = page.locator('#sit-card-body');
    await expect(body).toContainText('降水');
    await expect(body.locator('.sit-row-val.sit-level--unavailable')).toHaveText('取得できません');
  });
});

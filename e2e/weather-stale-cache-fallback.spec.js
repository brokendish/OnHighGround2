'use strict';

/**
 * WEATHER-ALERTS-UNAVAILABLE-RISK-FAILSAFE ROUND 2 — frontend 期限切れ cache fallback
 *
 * 実経路: 正常 fetch → cache 生成 → TTL 経過（ページの Date.now を進める）→ 再 fetch HTTP 500
 *         → weather-service fallback → 気象カード / 状況理解カード描画
 * テスト側から status='stale' を注入しない。
 *
 * contract:
 *   ok          最新取得成功
 *   stale       最新取得失敗 + 同一地点の前回取得データあり（値は保持・最新ではない）
 *   unavailable 最新取得失敗 + 前回データなし
 */

const { test, expect } = require('@playwright/test');

// 位置情報を許可しない: navigation.js の GPS 更新による自動 _weatherServiceUpdate が
// テスト中の cache 状態へ割り込まないようにする（更新はテストから明示的に呼ぶ）
test.use({ permissions: [] });

const LAT = 35.6415;
const LON = 139.7905;

const ALERTS_NONE = {
  status: 'ok', severity: 'none', alerts: [],
  location: { area_name: '東京都', city: '江東区' },
  updated_at: '2026-09-23T01:00:00+09:00', message: '警報・注意報なし',
};
const PRECIP_NONE = {
  status: 'ok', severity: 'none', summary: '降水なし',
  current: { intensity: 'none', label: '降水なし' }, forecast: [],
};
const CTX_NONE = {
  status: 'ok', risk_level: 'none', combined: [], hazards: {},
  weather: { alert_status: 'ok', precip_status: 'ok' },
};

/** API ごとに ok / fail を切り替えられるモック。 */
async function setup(page) {
  const mode = { alerts: 'ok', precip: 'ok', context: 'ok' };
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  const handler = (key, body) => route => (mode[key] === 'fail'
    ? route.fulfill({ status: 500, contentType: 'application/json', body: '{}' })
    : route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.route('/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page.route('/api/weather/alerts/current**', handler('alerts', ALERTS_NONE));
  await page.route('/api/weather/precipitation/summary**', handler('precip', PRECIP_NONE));
  await page.route('/api/weather/risk/context**', handler('context', CTX_NONE));
  await page.goto('/');
  await page.evaluate(() => {
    switchMbcTab('info');
    _lipUpdateNavMode('browse');
    // TTL 経過用: ページの Date.now にオフセットを足せるようにする（cache 内部は触らない）
    const realNow = Date.now.bind(Date);
    window.__wsTimeOffset = 0;
    Date.now = () => realNow() + window.__wsTimeOffset;
  });
  return { mode, errors };
}

async function update(page, lat = LAT, lon = LON) {
  return page.evaluate(async ({ lat, lon }) => {
    const r = await _weatherServiceUpdate(lat, lon);
    return {
      alertsStatus: r.alerts.status,
      precipStatus: r.precip.status,
      contextStatus: r.context.status,
      riskLevel: r.riskInfo.riskLevel,
      precipStale: r.riskInfo.precipInfo.stale,
      contextStale: r.riskInfo.contextStale,
      alertsMessage: r.alerts.message,
      alertsSeverity: r.alerts.severity,
      precipCurrent: r.precip.current,
      contextRisk: r.context.risk_level,
    };
  }, { lat, lon });
}

/** 全 cache の TTL（最大 120 秒）を超えて時間を進める。 */
async function expireCaches(page) {
  await page.evaluate(() => { window.__wsTimeOffset += 10 * 60 * 1000; });
}

async function storedStatuses(page) {
  return page.evaluate(() => ({
    alerts: _wsAlertCache && _wsAlertCache.data.status,
    precip: _wsPrecipCache && _wsPrecipCache.data.status,
    context: _wsContextCache && _wsContextCache.data.status,
    alertsMessage: _wsAlertCache && _wsAlertCache.data.message,
  }));
}

const card = page => ({
  message: page.locator('#lip-wc-message'),
  list: page.locator('#lip-wc-alert-list'),
  precip: page.locator('#lip-wc-precip-summary'),
});

test.describe('Weather stale cache fallback', () => {
  test('正常取得: 全 status=ok・stale 表示なし', async ({ page }) => {
    await setup(page);
    const r = await update(page);
    expect(r).toMatchObject({ alertsStatus: 'ok', precipStatus: 'ok', contextStatus: 'ok', riskLevel: 'none' });
    expect(r.precipStale).toBe(false);
    expect(r.contextStale).toBe(false);
    await expect(card(page).message).toHaveCSS('display', 'none');
    await expect(card(page).precip).not.toContainText('前回取得データ');
  });

  test('S1 alerts stale: 前回値を保持し status=stale・前回取得データ表示', async ({ page }) => {
    const { mode } = await setup(page);
    await update(page);
    await expireCaches(page);
    mode.alerts = 'fail';
    const r = await update(page);
    expect(r.alertsStatus).toBe('stale');
    expect(r.alertsSeverity).toBe('none');  // 前回値は保持
    expect(r.alertsMessage).toBe('最新の気象情報を取得できません（前回取得データを表示中）');
    expect(r.precipStatus).toBe('ok');
    expect(r.contextStatus).toBe('ok');
    await expect(card(page).list).toContainText('警報・注意報なし');
    await expect(card(page).message).toHaveText('⚠ 前回取得データを表示中');
    await expect(card(page).message).not.toHaveCSS('display', 'none');
  });

  test('S2 precip stale: 降水行を残し前回取得データを明示', async ({ page }) => {
    const { mode } = await setup(page);
    await update(page);
    await expireCaches(page);
    mode.precip = 'fail';
    const r = await update(page);
    expect(r.precipStatus).toBe('stale');
    expect(r.precipCurrent).toEqual({ intensity: 'none', label: '降水なし' });
    expect(r.precipStale).toBe(true);
    expect(r.alertsStatus).toBe('ok');
    await expect(card(page).precip).toContainText('現在: 降水なし');
    await expect(card(page).precip.locator('.wc-precip-stale')).toHaveText('⚠ 前回取得データ');
    await expect(card(page).message).toHaveText('⚠ 前回取得データを表示中');
  });

  test('S3 context stale: 前回 risk を保持し status=stale', async ({ page }) => {
    const { mode } = await setup(page);
    await update(page);
    await expireCaches(page);
    mode.context = 'fail';
    const r = await update(page);
    expect(r.contextStatus).toBe('stale');
    expect(r.contextRisk).toBe('none');
    expect(r.contextStale).toBe(true);
    await expect(card(page).message).toHaveText('⚠ 前回取得データを表示中');
  });

  test('S4 三者とも stale: ok に戻らず正常最新 none に見えない・cache 本体は汚染しない', async ({ page }) => {
    const { mode, errors } = await setup(page);
    await update(page);
    const before = await storedStatuses(page);
    await expireCaches(page);
    mode.alerts = mode.precip = mode.context = 'fail';
    const r = await update(page);
    expect(r).toMatchObject({ alertsStatus: 'stale', precipStatus: 'stale', contextStatus: 'stale' });
    // backend stale policy と同じく前回値で評価（前回 none → none）。stale であることは別途表示で明示
    expect(r.riskLevel).toBe('none');
    await expect(card(page).message).toHaveText('⚠ 前回取得データを表示中');
    await expect(card(page).list).toContainText('警報・注意報なし');
    await expect(card(page).precip.locator('.wc-precip-stale')).toHaveText('⚠ 前回取得データ');
    // 保存済み cache は取得時の status=ok のまま（返却用コピーのみ stale）
    expect(await storedStatuses(page)).toEqual(before);
    expect(before).toEqual({ alerts: 'ok', precip: 'ok', context: 'ok', alertsMessage: '警報・注意報なし' });
    // 2 回連続で失敗しても stale のまま
    const r2 = await update(page);
    expect(r2).toMatchObject({ alertsStatus: 'stale', precipStatus: 'stale', contextStatus: 'stale' });
    expect(errors).toEqual([]);
  });

  test('S5 cache なし失敗: unavailable・unknown・取得できません（Round 1 維持）', async ({ page }) => {
    const { mode } = await setup(page);
    mode.alerts = mode.precip = mode.context = 'fail';
    const r = await update(page);
    expect(r).toMatchObject({
      alertsStatus: 'unavailable', precipStatus: 'unavailable', contextStatus: 'unavailable', riskLevel: 'unknown',
    });
    await expect(card(page).list).toContainText('警報・注意報：取得できません');
    await expect(card(page).precip).toHaveText('取得できません');
    await expect(card(page).message).toHaveText('気象情報を取得できません');
  });

  test('別地点の cache は stale に使わず unavailable', async ({ page }) => {
    const { mode } = await setup(page);
    await update(page, 34.75, 139.36);  // 別地点で正常取得
    mode.alerts = mode.precip = mode.context = 'fail';
    const r = await update(page);       // 現在地で失敗
    expect(r).toMatchObject({
      alertsStatus: 'unavailable', precipStatus: 'unavailable', contextStatus: 'unavailable', riskLevel: 'unknown',
    });
  });

  test('S6 stale → 再取得成功: status=ok に戻り stale 表示が残らない', async ({ page }) => {
    const { mode } = await setup(page);
    await update(page);
    await expireCaches(page);
    mode.alerts = mode.precip = mode.context = 'fail';
    await update(page);
    await expect(card(page).message).toHaveText('⚠ 前回取得データを表示中');

    mode.alerts = mode.precip = mode.context = 'ok';
    const r = await update(page);
    expect(r).toMatchObject({ alertsStatus: 'ok', precipStatus: 'ok', contextStatus: 'ok', riskLevel: 'none' });
    expect(r.precipStale).toBe(false);
    expect(r.contextStale).toBe(false);
    await expect(card(page).message).toHaveCSS('display', 'none');
    await expect(card(page).precip.locator('.wc-precip-stale')).toHaveCount(0);
    await expect(card(page).precip).toContainText('現在: 降水なし');
  });

  test('状況理解カード: 降水 stale で前回値と前回取得データ表記を出す', async ({ page }) => {
    const { mode } = await setup(page);
    await update(page);
    await expireCaches(page);
    mode.precip = 'fail';
    await update(page);
    await page.evaluate(() => {
      window.kikikuruGetRiskSnapshot = () => ({
        current: { status: 'off' }, dest: { status: 'off' }, route: { status: 'off' },
      });
      situationCardOnRouteUpdate({
        safety_score: 90, risk_level: 'safe', risk_summary: { notes: [], hazards: [] },
        kikikuru_adjustment: { enabled: false, status: 'off', penalty: 0, max_level: null, matched_hazards: [], summary: [] },
      });
    });
    const body = page.locator('#sit-card-body');
    await expect(body).toContainText('降水なし');
    await expect(body.locator('.sit-precip-stale')).toHaveText('（前回取得データ）');
  });
});

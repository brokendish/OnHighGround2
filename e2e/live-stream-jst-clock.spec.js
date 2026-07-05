'use strict';

const { test, expect } = require('@playwright/test');

const DOCKER_BASE = process.env.LIVE_STREAM_E2E_BASE_URL || 'http://127.0.0.1:8080';

// Stream Phase 5-B.1: /live/stream の画面表示は、ブラウザ/OSのタイムゾーンに関わらず
// 常にJSTでなければならない (streamer container 等、OS timezoneがUTCの環境での配信を想定)。
// timezoneId: 'UTC' でブラウザのローカルタイムゾーンをUTCに固定し、その環境を再現する。
test.describe('/live/stream — Stream Phase 5-B.1 JST時刻固定 (ブラウザtimezone=UTC環境での確認)', () => {
  test.use({ timezoneId: 'UTC' });

  test('1: demoNow (+09:00 付き) がJSTのまま表示され、UTC変換されない', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    expect(await page.locator('#clock').textContent()).toBe('19:42:00');
    expect(await page.locator('#date').textContent()).toContain('2026.06.30');
    expect(await page.locator('#date').textContent()).toContain('JST');
    expect(await page.locator('#clock-short').textContent()).toBe('19:42');
    // UTC変換されていれば 10:42 になってしまうはずの誤りを明示的に否定する
    expect(await page.locator('#clock').textContent()).not.toContain('10:42');
  });

  test('2: real-time clock matches actual JST (not shifted by the browser/OS UTC timezone)', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?chrome=off`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    const displayed = await page.locator('#clock').textContent();
    const expectedJst = new Intl.DateTimeFormat('ja-JP', {
      timeZone: 'Asia/Tokyo', hour: '2-digit', minute: '2-digit', hour12: false,
    }).format(new Date());
    // 秒までは厳密一致させず、時:分だけ突き合わせる (実行タイミングのブレを許容)
    expect(displayed.slice(0, 5)).toBe(expectedJst);
  });

  test('3: date line shows JST-based date, not the UTC-based previous/next day', async ({ page }) => {
    // JST 00:30 は UTC で前日 15:30 になる — タイムゾーン変換ミスがあれば日付がずれて出る典型ケース
    await page.goto(`${DOCKER_BASE}/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T00:30:00%2B09:00`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    expect(await page.locator('#date').textContent()).toContain('2026.06.30');
    expect(await page.locator('#date-short').textContent()).toContain('2026.06.30');
  });

  for (const t of ['06:00:00', '12:00:00', '18:00:00']) {
    test(`4 (${t}): tide graph stays in sync at demoNow=${t}+09:00`, async ({ page }) => {
      await page.goto(`${DOCKER_BASE}/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T${t}%2B09:00`, { waitUntil: 'domcontentloaded' });
      await page.waitForTimeout(500);
      expect(await page.locator('#clock').textContent()).toBe(t);
      // 潮位カーブの中心マーカーは常にチャート中央に固定される既存仕様 (live-stream.spec.js で
      // 別途検証済み)。ここでは時計がずれていないことのみを確認する。
      await expect(page.locator('[data-testid="live-stream-tide-station"]').first()).toBeVisible();
    });
  }

  test('5: earthquake history and rain "updated" times are JST, not shifted', async ({ page }) => {
    const OBSERVED_AT = '2026-06-30T19:42:00+09:00';
    await page.route('**/api/live/earthquakes/history**', route => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ items: [{ event_id: 'eq-jst', lat: 35.0, lng: 139.0, magnitude: 5.0, max_intensity: '3', occurred_at: OBSERVED_AT, epicenter_name: 'x' }] }),
    }));
    await page.route('**/api/live/summary**', route => route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({ rain: { status: 'ok', areas: [] }, kikikuru: { status: 'ok', areas: [{ area_name: '静岡県 中部', prefecture: '静岡県', level: 'danger', type: 'kikikuru', hazard: 'land', lat: 34.9, lng: 138.2, observed_at: OBSERVED_AT }] } }),
    }));
    await page.route('**/api/live/trains/summary**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ items: [] }) }));
    await page.route('**/api/live/tide/stations**', route => route.fulfill({ contentType: 'application/json', body: JSON.stringify({ stations: [] }) }));

    // demoNow を occurred_at と同時刻に揃える (staleness判定の「現在時刻」を一致させ、
    // 過去の固定日時のせいで履歴が古すぎるとみなされデモ表示にフォールバックするのを防ぐ)。
    await page.goto(`${DOCKER_BASE}/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19%3A42%3A00%2B09%3A00`, { waitUntil: 'domcontentloaded' });
    await page.waitForFunction(() => {
      const el = document.querySelector('[data-testid="live-stream-earthquake-history-item"]');
      return !!(el && el.textContent && el.textContent.includes('x')); // epicenter_name: 'x' が反映されるまで待つ
    }, null, { timeout: 8000 });
    const eqRow = await page.locator('[data-testid="live-stream-earthquake-history-item"]').first().textContent();
    expect(eqRow).toContain('19:42');
    expect(eqRow).not.toContain('10:42');
    const rainUpdated = await page.locator('[data-testid="live-stream-rain-updated"]').textContent();
    expect(rainUpdated).toContain('19:42');
    expect(rainUpdated).not.toContain('10:42');
  });

  test('6: no undefined/NaN/Invalid Date leaks anywhere in the header/date/map clock', async ({ page }) => {
    await page.goto(`${DOCKER_BASE}/live/stream?chrome=off`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    for (const id of ['clock', 'date', 'clock-short', 'date-short']) {
      const text = await page.locator(`#${id}`).textContent();
      expect(text).not.toContain('NaN');
      expect(text).not.toContain('undefined');
      expect(text).not.toContain('Invalid Date');
    }
  });

  test('7: /live is unaffected by the JST clock fix', async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(e.message || String(e)));
    await page.goto(`${DOCKER_BASE}/live`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(1000);
    expect(pageErrors).toEqual([]);
  });

  test('8: / (navigation root) is unaffected', async ({ page }) => {
    const pageErrors = [];
    page.on('pageerror', e => pageErrors.push(e.message || String(e)));
    await page.goto(`${DOCKER_BASE}/`, { waitUntil: 'domcontentloaded' });
    await page.waitForTimeout(500);
    expect(pageErrors).toEqual([]);
  });
});

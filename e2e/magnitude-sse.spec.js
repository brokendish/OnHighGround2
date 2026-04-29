'use strict';

const { test, expect } = require('@playwright/test');

const POLL_MS = 10_000;

function quake(id, name, minute, lat, lng, intensity, magnitude = 4) {
  return {
    event_id: id,
    occurred_at: `2026-04-29T10:${String(minute).padStart(2, '0')}:00+09:00`,
    epicenter_name: name,
    lat,
    lng,
    depth_km: 30,
    max_intensity: intensity,
    magnitude,
    tsunami_info: '津波の心配なし',
    source: 'mock',
  };
}

function baseItems() {
  return [
    quake('eq-base-low', '既存震度1', 10, 35.682, 139.768, '1', 2.1),
    quake('eq-base-high', '既存震度4', 9, 40.0, 141.0, '4', 4.1),
  ];
}

async function installMockEventSource(page) {
  await page.addInitScript(() => {
    window.__magnitudeEventSources = [];

    class MockEventSource {
      constructor(url) {
        this.url = url;
        this.readyState = 0;
        this.closed = false;
        this.closeCount = 0;
        this.listeners = new Map();
        window.__magnitudeEventSources.push(this);
        setTimeout(() => {
          if (this.closed) return;
          this.readyState = 1;
          if (typeof this.onopen === 'function') this.onopen(new Event('open'));
        }, 0);
      }

      addEventListener(type, listener) {
        const listeners = this.listeners.get(type) || [];
        listeners.push(listener);
        this.listeners.set(type, listeners);
      }

      close() {
        this.closed = true;
        this.readyState = 2;
        this.closeCount += 1;
      }

      emit(type, data) {
        const event = { type, data: typeof data === 'string' ? data : JSON.stringify(data) };
        for (const listener of this.listeners.get(type) || []) listener(event);
      }

      fail() {
        if (typeof this.onerror === 'function') this.onerror(new Event('error'));
      }
    }

    window.EventSource = MockEventSource;
    window.__magnitudeStreams = () => window.__magnitudeEventSources
      .filter(es => String(es.url).includes('/api/earthquakes/stream'));
    window.__emitMagnitudeSse = (index, type, data) => {
      window.__magnitudeStreams()[index]?.emit(type, data);
    };
    window.__failMagnitudeSse = (index) => {
      window.__magnitudeStreams()[index]?.fail();
    };
  });
}

async function setupPage(page) {
  await installMockEventSource(page);
  await page.addInitScript(interval => {
    window.__MAGNITUDE_POLL_INTERVAL_MS = interval;
  }, POLL_MS);
  await page.route('/favicon.ico', route => route.fulfill({ status: 204, body: '' }));
  await page.route('/api/**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({}),
  }));
  await page.route('/api/admin/config/stream', route => route.fulfill({
    status: 200,
    contentType: 'text/event-stream',
    body: 'retry: 10000\n\n',
  }));
  await page.route('/api/earthquakes**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ items: baseItems(), count: baseItems().length }),
  }));
  await page.route('/api/elevation**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ elevation: 3.5, lat: 35.681236, lon: 139.767125 }),
  }));
  await page.route('/emergency-shelters**', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));

  await page.goto('/');
  await page.waitForFunction(() => typeof window.toggleMagnitudeMode === 'function' && typeof window.map !== 'undefined');
  await page.evaluate(() => {
    currentLocation = { lat: 35.681236, lon: 139.767125, accuracyMeters: 5 };
  });
}

async function openMagnitude(page) {
  await page.locator('#mbc-tab-btn-earthquake').click();
  await expect(page.locator('#magnitude-list .mq-item').first()).toBeVisible({ timeout: 8000 });
  await expect.poll(() => page.evaluate(() => window.__magnitudeStreams().length)).toBe(1);
}

async function listNames(page) {
  return page.locator('#magnitude-list .mq-name').evaluateAll(els => els.map(el => el.textContent));
}

test.describe('Magnitude Phase3-2A: SSE foundation', () => {
  test('EventSource受信をリスト・ピン・NEWへ反映し、同じevent_idを重複させない', async ({ page }) => {
    await setupPage(page);
    await openMagnitude(page);

    await expect(page.locator('#magnitude-sse-status')).toHaveText('リアルタイム: 接続中');

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'earthquake', {
        event_id: 'dev-sse-001',
        occurred_at: '2026-04-29T12:34:56+09:00',
        epicenter_name: '東京湾',
        lat: 35.5,
        lng: 139.8,
        depth_km: 30,
        magnitude: 4.8,
        max_intensity: '4',
        tsunami_info: '津波の心配なし',
        source: 'dev',
      });
    });

    await expect.poll(() => listNames(page)).toEqual(['東京湾', '既存震度1', '既存震度4']);
    await expect(page.locator('.mq-new-badge')).toHaveCount(1);
    await expect(page.locator('#magnitude-new-count')).toHaveText('新着地震 1件');
    await expect(page.locator('.magnitude-ring-new')).toHaveCount(1);

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'earthquake', {
        event_id: 'dev-sse-001',
        occurred_at: '2026-04-29T12:35:56+09:00',
        epicenter_name: '東京湾 更新',
        lat: 35.5,
        lng: 139.8,
        depth_km: 30,
        magnitude: 4.9,
        max_intensity: '4',
        tsunami_info: '津波の心配なし',
        source: 'dev',
      });
    });

    await expect(page.locator('#magnitude-list .mq-item')).toHaveCount(3);
    await expect(page.locator('#magnitude-list .mq-name', { hasText: '東京湾 更新' })).toHaveCount(1);
    await expect(page.locator('.mq-new-badge')).toHaveCount(1);
  });

  test('震度フィルタ・近い順を保ったままSSEイベントを反映する', async ({ page }) => {
    await setupPage(page);
    await openMagnitude(page);

    await page.locator('.mq-filter-button', { hasText: '震度4以上' }).click();
    await page.locator('.mq-sort-button', { hasText: '近い順' }).click();

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'earthquake', {
        event_id: 'dev-sse-low',
        occurred_at: '2026-04-29T12:30:00+09:00',
        epicenter_name: '条件外震度3',
        lat: 35.6815,
        lng: 139.7675,
        magnitude: 3.2,
        max_intensity: '3',
        source: 'dev',
      });
      window.__emitMagnitudeSse(0, 'earthquake', {
        event_id: 'dev-sse-high',
        occurred_at: '2026-04-29T12:31:00+09:00',
        epicenter_name: '近い震度4',
        lat: 35.6816,
        lng: 139.7676,
        magnitude: 4.2,
        max_intensity: '4',
        source: 'dev',
      });
    });

    await expect.poll(() => listNames(page)).toEqual(['近い震度4', '既存震度4']);
    await expect(page.locator('#magnitude-new-count')).toHaveText('新着地震 1件');
    await expect(page.locator('.mq-filter-button', { hasText: '震度4以上' })).toHaveClass(/active/);
    await expect(page.locator('.mq-sort-button', { hasText: '近い順' })).toHaveClass(/active/);
    await expect(page.locator('#magnitude-list .mq-dist').first()).toContainText('約');
  });

  test('ポーリング取得済みevent_idがSSEで届いても重複表示しない', async ({ page }) => {
    await setupPage(page);
    await openMagnitude(page);

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'earthquake', {
        event_id: 'eq-base-high',
        occurred_at: '2026-04-29T12:32:00+09:00',
        epicenter_name: '既存震度4 更新',
        lat: 40.0,
        lng: 141.0,
        magnitude: 4.4,
        max_intensity: '4',
        source: 'p2p_ws',
      });
    });

    await expect(page.locator('#magnitude-list .mq-item')).toHaveCount(2);
    await expect(page.locator('#magnitude-list .mq-name', { hasText: '既存震度4 更新' })).toHaveCount(1);
    await expect(page.locator('.mq-new-badge')).toHaveCount(0);
    await expect(page.locator('#magnitude-new-count')).toBeHidden();
  });

  test('SSE status eventでリアルタイム状態表示を更新し、ポーリング表示を保つ', async ({ page }) => {
    await setupPage(page);
    await openMagnitude(page);

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'status', {
        state: 'reconnecting',
        source: 'p2p_ws',
        next_retry_seconds: 10,
      });
    });
    await expect(page.locator('#magnitude-sse-status')).toHaveText('リアルタイム: 再接続中（10秒ごとに自動更新で継続）');
    await expect(page.locator('#magnitude-status-bar')).toContainText('10秒ごとに自動更新');
    await expect(page.locator('#magnitude-list .mq-item')).toHaveCount(2);

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'status', {
        state: 'disconnected',
        source: 'p2p_ws',
      });
    });
    await expect(page.locator('#magnitude-sse-status')).toHaveText('リアルタイム: 切断中（10秒ごとに自動更新）');

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'status', {
        state: 'connected',
        source: 'p2p_ws',
      });
    });
    await expect(page.locator('#magnitude-sse-status')).toHaveText('リアルタイム: 接続中');
  });

  test('OFFでEventSourceをcloseし、古い接続からの遅延イベントを無視する', async ({ page }) => {
    await setupPage(page);
    await openMagnitude(page);

    await page.locator('#magnitude-btn').click();
    await expect(page.locator('#magnitude-list')).toBeEmpty();
    expect(await page.evaluate(() => window.__magnitudeStreams()[0].closed)).toBe(true);

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'earthquake', {
        event_id: 'dev-after-off',
        occurred_at: '2026-04-29T12:40:00+09:00',
        epicenter_name: 'OFF後イベント',
        lat: 35.5,
        lng: 139.8,
        magnitude: 4.0,
        max_intensity: '4',
        source: 'dev',
      });
    });
    await expect(page.locator('#magnitude-list')).toBeEmpty();

    await page.locator('#mbc-tab-btn-earthquake').click();
    await expect.poll(() => page.evaluate(() => window.__magnitudeStreams().length)).toBe(2);
    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'earthquake', {
        event_id: 'dev-stale',
        occurred_at: '2026-04-29T12:41:00+09:00',
        epicenter_name: '古い接続',
        lat: 35.5,
        lng: 139.8,
        magnitude: 4.0,
        max_intensity: '4',
        source: 'dev',
      });
    });

    await expect(page.locator('#magnitude-list .mq-name', { hasText: '古い接続' })).toHaveCount(0);
    await expect(page.locator('#magnitude-list .mq-item')).toHaveCount(2);
  });

  test('不正JSON・HTML文字列・lat/lng nullでJSエラーを出さない', async ({ page }) => {
    const errors = [];
    page.on('pageerror', err => errors.push(err.message));
    page.on('console', msg => {
      if (msg.type() !== 'error') return;
      const text = msg.text();
      if (text.includes('Failed to load resource')) return;
      errors.push(text);
    });

    await setupPage(page);
    await openMagnitude(page);

    await page.evaluate(() => {
      window.__emitMagnitudeSse(0, 'earthquake', '{bad json');
      window.__emitMagnitudeSse(0, 'earthquake', {
        event_id: 'dev-invalid',
        occurred_at: '2026-04-29T12:50:00+09:00',
        epicenter_name: '<img src=x onerror=alert(1)>',
        lat: null,
        lng: null,
        magnitude: null,
        max_intensity: null,
        tsunami_info: '<img src=x onerror=alert(1)>',
        source: 'dev',
      });
    });

    await expect(page.locator('#magnitude-list .mq-name', { hasText: '<img src=x onerror=alert(1)>' })).toHaveCount(1);
    await expect(page.locator('#magnitude-list img')).toHaveCount(0);
    expect(errors).toEqual([]);
  });
});

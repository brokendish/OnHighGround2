'use strict';

const { test, expect } = require('@playwright/test');
const path = require('path');

const uiScriptPath = path.resolve(__dirname, '../frontend/js/magnitude-ui.js');

const filterQuakes = [
  {
    event_id: 'eq-1',
    occurred_at: '2026-04-29T10:00:00+09:00',
    epicenter_name: '震度1',
    lat: 35.1,
    lng: 139.1,
    max_intensity: '1',
    magnitude: 2.1,
  },
  {
    event_id: 'eq-3',
    occurred_at: '2026-04-29T10:01:00+09:00',
    epicenter_name: '震度3',
    lat: 35.2,
    lng: 139.2,
    max_intensity: '3',
    magnitude: 3.1,
  },
  {
    event_id: 'eq-4',
    occurred_at: '2026-04-29T10:02:00+09:00',
    epicenter_name: '震度4',
    lat: 35.3,
    lng: 139.3,
    max_intensity: '4',
    magnitude: 4.1,
  },
  {
    event_id: 'eq-5w',
    occurred_at: '2026-04-29T10:03:00+09:00',
    epicenter_name: '震度5弱',
    lat: 35.4,
    lng: 139.4,
    max_intensity: '5弱',
    magnitude: 5.1,
  },
];

async function loadMagnitudeUi(page) {
  await page.setContent(`
    <div id="magnitude-new-count"></div>
    <div id="magnitude-filter-bar"></div>
    <div id="magnitude-sort-bar"></div>
    <div id="magnitude-list"></div>
  `);
  await page.evaluate(() => {
    window.renderedPinCounts = [];
    window.renderedPinIds = [];
    window.renderEarthquakePins = items => {
      window.renderedPinCounts.push(items.length);
      window.renderedPinIds = items.map(item => item.event_id);
    };
    window.updateMagnitudeNewCount = count => {
      const el = document.getElementById('magnitude-new-count');
      if (!el) return;
      el.textContent = count > 0 ? `新着地震 ${count}件` : '';
      el.style.display = count > 0 ? 'block' : 'none';
    };
  });
  await page.addScriptTag({ path: uiScriptPath });
}

async function listNames(page) {
  return page.locator('.mq-name').evaluateAll(els => els.map(el => el.textContent));
}

async function pinIds(page) {
  return page.evaluate(() => window.renderedPinIds);
}

test.describe('Magnitude Phase2-4: intensity filter', () => {
  test('初期状態は全件で、震度フィルタがリストとピンに反映される', async ({ page }) => {
    await loadMagnitudeUi(page);

    await page.evaluate(items => {
      window.renderEarthquakeList(items, { lat: 35.681236, lon: 139.767125 }, new Set());
    }, filterQuakes);

    await expect(page.locator('.mq-filter-button', { hasText: '全件' })).toHaveClass(/active/);
    await expect.poll(() => listNames(page)).toEqual(['震度5弱', '震度4', '震度3', '震度1']);
    await expect.poll(() => pinIds(page)).toEqual(['eq-1', 'eq-3', 'eq-4', 'eq-5w']);

    await page.locator('.mq-filter-button', { hasText: '震度3以上' }).click();
    await expect.poll(() => listNames(page)).toEqual(['震度5弱', '震度4', '震度3']);
    await expect.poll(() => pinIds(page)).toEqual(['eq-3', 'eq-4', 'eq-5w']);

    await page.locator('.mq-filter-button', { hasText: '震度4以上' }).click();
    await expect.poll(() => listNames(page)).toEqual(['震度5弱', '震度4']);
    await expect.poll(() => pinIds(page)).toEqual(['eq-4', 'eq-5w']);

    await page.locator('.mq-filter-button', { hasText: '震度5弱以上' }).click();
    await expect.poll(() => listNames(page)).toEqual(['震度5弱']);
    await expect.poll(() => pinIds(page)).toEqual(['eq-5w']);
  });

  test('震度表記の揺れを扱い、不明/nullは条件付きフィルタから除外する', async ({ page }) => {
    await loadMagnitudeUi(page);

    const variants = [
      ['i-5w', '5弱'],
      ['i-5s', '5強'],
      ['i-6w', '6弱'],
      ['i-6s', '6強'],
      ['i-7', '7'],
      ['i-5m', '5-'],
      ['i-5p', '5+'],
      ['i-6m', '6-'],
      ['i-6p', '6+'],
      ['i-null', null],
      ['i-unknown', '不明'],
    ].map(([id, intensity], index) => ({
      event_id: id,
      occurred_at: `2026-04-29T10:${String(index).padStart(2, '0')}:00+09:00`,
      epicenter_name: String(intensity ?? 'null'),
      lat: 35 + index / 100,
      lng: 139 + index / 100,
      max_intensity: intensity,
      magnitude: 4,
    }));

    await page.evaluate(items => {
      window.renderEarthquakeList(items, { lat: 35.681236, lon: 139.767125 }, new Set());
      window.magnitudeFilterSet('5-');
    }, variants);

    await expect.poll(() => listNames(page)).toEqual(['6+', '6-', '5+', '5-', '7', '6強', '6弱', '5強', '5弱']);
    await expect(page.locator('.mq-name', { hasText: 'null' })).toHaveCount(0);
    await expect(page.locator('.mq-name', { hasText: '不明' })).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.renderedPinIds.includes('i-null'))).toBe(false);
    await expect.poll(() => page.evaluate(() => window.renderedPinIds.includes('i-unknown'))).toBe(false);
  });

  test('フィルタ後0件では空表示になり、ピンも0件になる', async ({ page }) => {
    await loadMagnitudeUi(page);

    await page.evaluate(() => {
      window.renderEarthquakeList([
        {
          event_id: 'eq-low',
          occurred_at: '2026-04-29T10:00:00+09:00',
          epicenter_name: '弱い地震',
          lat: 35.1,
          lng: 139.1,
          max_intensity: '2',
          magnitude: 2,
        },
      ], { lat: 35.681236, lon: 139.767125 }, new Set());
      window.magnitudeFilterSet('5-');
    });

    await expect(page.locator('.mq-empty')).toHaveText('条件に一致する地震情報はありません。');
    await expect.poll(() => pinIds(page)).toEqual([]);
  });

  test('フィルタ後の対象だけを新しい順/近い順で並べる', async ({ page }) => {
    await loadMagnitudeUi(page);

    const items = [
      {
        event_id: 'eq-low-new',
        occurred_at: '2026-04-29T11:00:00+09:00',
        epicenter_name: '対象外で新しい',
        lat: 35.6813,
        lng: 139.7671,
        max_intensity: '1',
        magnitude: 2,
      },
      {
        event_id: 'eq-3-far',
        occurred_at: '2026-04-29T10:30:00+09:00',
        epicenter_name: '遠い震度3',
        lat: 40,
        lng: 141,
        max_intensity: '3',
        magnitude: 3,
      },
      {
        event_id: 'eq-4-near',
        occurred_at: '2026-04-29T10:00:00+09:00',
        epicenter_name: '近い震度4',
        lat: 35.682,
        lng: 139.768,
        max_intensity: '4',
        magnitude: 4,
      },
    ];

    await page.evaluate(items => {
      window.renderEarthquakeList(items, { lat: 35.681236, lon: 139.767125 }, new Set());
      window.magnitudeFilterSet('3');
    }, items);

    await expect.poll(() => listNames(page)).toEqual(['遠い震度3', '近い震度4']);
    await page.locator('.mq-sort-button', { hasText: '近い順' }).click();
    await expect.poll(() => listNames(page)).toEqual(['近い震度4', '遠い震度3']);
    await expect(page.locator('.mq-name', { hasText: '対象外で新しい' })).toHaveCount(0);
  });

  test('NEW表示と新着件数はフィルタ後の表示対象に合わせる', async ({ page }) => {
    await loadMagnitudeUi(page);

    await page.evaluate(items => {
      window.renderEarthquakeList(items, { lat: 35.681236, lon: 139.767125 }, new Set(['eq-1', 'eq-5w']));
    }, filterQuakes);

    await expect(page.locator('.mq-new-badge')).toHaveCount(2);
    await expect(page.locator('#magnitude-new-count')).toHaveText('新着地震 2件');

    await page.locator('.mq-filter-button', { hasText: '震度5弱以上' }).click();
    await expect(page.locator('.mq-new-badge')).toHaveCount(1);
    await expect(page.locator('.mq-item-new .mq-name')).toHaveText('震度5弱');
    await expect(page.locator('#magnitude-new-count')).toHaveText('新着地震 1件');

    await page.locator('.mq-filter-button', { hasText: '震度4以上' }).click();
    await expect(page.locator('.mq-new-badge')).toHaveCount(1);
    await expect(page.locator('#magnitude-new-count')).toHaveText('新着地震 1件');
  });

  test('フィルタ切替後もXSS対策が維持される', async ({ page }) => {
    await loadMagnitudeUi(page);
    await page.evaluate(() => {
      window.__xssHit = false;
      window.renderEarthquakeList([
        {
          event_id: 'eq-xss',
          occurred_at: '2026-04-29T10:00:00+09:00',
          epicenter_name: '<img src=x onerror="window.__xssHit=true">',
          lat: 35.7,
          lng: 139.8,
          magnitude: 3,
          max_intensity: '4',
        },
      ], { lat: 35.681236, lon: 139.767125 }, new Set());
      window.magnitudeFilterSet('4');
    });

    await expect(page.locator('.mq-name')).toHaveText('<img src=x onerror="window.__xssHit=true">');
    await expect(page.locator('.mq-name img')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__xssHit)).toBe(false);
  });
});

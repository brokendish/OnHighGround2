'use strict';

const { test, expect } = require('@playwright/test');
const path = require('path');

const uiScriptPath = path.resolve(__dirname, '../frontend/js/magnitude-ui.js');
const layerScriptPath = path.resolve(__dirname, '../frontend/js/magnitude-layer.js');

const quakes = [
  {
    event_id: 'eq-old-near',
    occurred_at: '2026-04-29T09:00:00+09:00',
    epicenter_name: '近い地震',
    lat: 35.7,
    lng: 139.8,
    magnitude: '3.0',
    max_intensity: '2',
  },
  {
    event_id: 'eq-new-far',
    occurred_at: '2026-04-29T10:00:00+09:00',
    epicenter_name: '遠い地震',
    lat: 40.0,
    lng: 141.0,
    magnitude: 4,
    max_intensity: '3',
  },
  {
    event_id: 'eq-no-location',
    occurred_at: '2026-04-29T09:30:00+09:00',
    epicenter_name: '距離不明',
    lat: null,
    lng: null,
    magnitude: null,
    max_intensity: null,
  },
];

async function loadMagnitudeUi(page) {
  await page.setContent(`
    <div id="magnitude-sort-bar"></div>
    <div id="magnitude-list"></div>
  `);
  await page.addScriptTag({ path: uiScriptPath });
}

async function listNames(page) {
  return page.locator('.mq-name').evaluateAll(els => els.map(el => el.textContent));
}

test.describe('Magnitude Phase2-3: distance sort', () => {
  test('初期表示は新しい順で、近い順へ切り替えると距離不明を末尾に回す', async ({ page }) => {
    await loadMagnitudeUi(page);

    await page.evaluate(items => {
      window.renderEarthquakeList(items, { lat: 35.681236, lon: 139.767125 }, new Set(['eq-old-near']));
    }, quakes);

    await expect(page.locator('.mq-sort-button').first()).toHaveClass(/active/);
    await expect(page.locator('.mq-new-badge')).toHaveCount(1);
    await expect.poll(() => listNames(page)).toEqual(['遠い地震', '距離不明', '近い地震']);

    await page.locator('.mq-sort-button', { hasText: '近い順' }).click();
    await expect.poll(() => listNames(page)).toEqual(['近い地震', '遠い地震', '距離不明']);
    await expect(page.locator('.mq-dist')).toHaveCount(2);
  });

  test('現在地なしでは近い順をdisabledにし、新しい順を維持する', async ({ page }) => {
    await loadMagnitudeUi(page);

    await page.evaluate(items => {
      window.renderEarthquakeList(items, null, new Set());
      window.magnitudeSortSet('nearest');
    }, quakes);

    await expect(page.locator('.mq-sort-button', { hasText: '近い順' })).toBeDisabled();
    await expect(page.locator('.mq-sort-hint')).toBeVisible();
    await expect(page.locator('.mq-sort-button', { hasText: '新しい順' })).toHaveClass(/active/);
    await expect.poll(() => listNames(page)).toEqual(['遠い地震', '距離不明', '近い地震']);
  });

  test('API再取得相当の再描画後も近い順とNEW表示を維持する', async ({ page }) => {
    await loadMagnitudeUi(page);

    await page.evaluate(items => {
      window.renderEarthquakeList(items, { lat: 35.681236, lon: 139.767125 }, new Set());
      window.magnitudeSortSet('nearest');
    }, quakes);

    const refreshed = [
      ...quakes,
      {
        event_id: 'eq-new-nearest',
        occurred_at: '2026-04-29T10:30:00+09:00',
        epicenter_name: '新着近距離',
        lat: 35.682,
        lng: 139.768,
        magnitude: 5,
        max_intensity: '4',
      },
    ];

    await page.evaluate(items => {
      window.renderEarthquakeList(items, { lat: 35.681236, lon: 139.767125 }, new Set(['eq-new-nearest']));
    }, refreshed);

    await expect(page.locator('.mq-sort-button', { hasText: '近い順' })).toHaveClass(/active/);
    await expect.poll(() => listNames(page)).toEqual(['新着近距離', '近い地震', '遠い地震', '距離不明']);
    await expect(page.locator('.mq-new-badge')).toHaveCount(1);
    await expect(page.locator('.mq-item-new .mq-name')).toHaveText('新着近距離');
  });

  test('リストクリックは選択状態を1件に保ち、該当event_idをfocusする', async ({ page }) => {
    await loadMagnitudeUi(page);
    await page.evaluate(items => {
      window.focusedIds = [];
      window.focusEarthquakePin = id => window.focusedIds.push(id);
      window.renderEarthquakeList(items, { lat: 35.681236, lon: 139.767125 }, new Set());
      window.magnitudeSortSet('nearest');
    }, quakes);

    await page.locator('.mq-item').nth(0).click();
    await page.locator('.mq-item').nth(1).click();

    await expect(page.locator('.mq-item--selected')).toHaveCount(1);
    await expect(page.locator('.mq-item--selected .mq-name')).toHaveText('遠い地震');
    await expect.poll(() => page.evaluate(() => window.focusedIds)).toEqual(['eq-old-near', 'eq-new-far']);
  });

  test('epicenter_nameはソート切替後もHTMLとして実行されない', async ({ page }) => {
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
          max_intensity: '<b>9</b>',
        },
      ], { lat: 35.681236, lon: 139.767125 }, new Set());
      window.magnitudeSortSet('nearest');
    });

    await expect(page.locator('.mq-name')).toHaveText('<img src=x onerror="window.__xssHit=true">');
    await expect(page.locator('.mq-name img')).toHaveCount(0);
    await expect.poll(() => page.evaluate(() => window.__xssHit)).toBe(false);
  });

  test('ピン描画は再描画で増殖せず、NEWリングとフォーカスを維持する', async ({ page }) => {
    await page.setContent('<div id="magnitude-list"></div>');
    await page.evaluate(() => {
      window.__layers = [];
      window.map = {
        removeLayer(layer) {
          window.__layers = window.__layers.filter(item => item !== layer);
        },
        setView(latlng, zoom) {
          window.__lastView = { latlng, zoom };
        },
      };
      window.L = {
        circleMarker(latlng, options) {
          return {
            latlng,
            options,
            popup: null,
            _quakeId: null,
            addTo() {
              window.__layers.push(this);
              return this;
            },
            bindPopup(html) {
              this.popup = html;
              return this;
            },
            getLatLng() {
              return this.latlng;
            },
            openPopup() {
              window.__openedPopup = this._quakeId;
            },
          };
        },
      };
    });
    await page.addScriptTag({ path: layerScriptPath });

    await page.evaluate(items => {
      window.renderEarthquakePins(items, { lat: 35.681236, lon: 139.767125 }, new Set(['eq-old-near']));
      window.renderEarthquakePins(items, { lat: 35.681236, lon: 139.767125 }, new Set(['eq-old-near']));
      window.focusEarthquakePin('eq-old-near');
    }, quakes);

    await expect.poll(() => page.evaluate(() => window.__layers.length)).toBe(3);
    await expect.poll(() => page.evaluate(() => window.__openedPopup)).toBe('eq-old-near');
    await expect.poll(() => page.evaluate(() => window.__lastView.zoom)).toBe(8);
  });
});

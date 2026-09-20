/**
 * storm-surge-legend-color-match.spec.js — STORM-SURGE-LEGEND-COLOR-MATCH
 *
 * 高潮浸水想定レイヤーについて「同じ浸水深階級は、地図でも凡例でも同じ色」を保証する。
 *
 * Source of Truth:
 *   scripts/normalize/normalize_storm_surge.py の DEPTH_TABLE（国土数値情報 A49_003 → storm_surge_rank 1-7）
 *   → frontend/js/hazard-layers.js の STORM_SURGE_CLASSES（実描画・全凡例の唯一の定義元）
 *
 * 検証観点:
 *   1. STORM_SURGE_CLASSES が normalizer の DEPTH_TABLE と一致（rank / 境界 / 代表深）
 *   2. 階級境界（0.3 / 0.5 / 1 / 3 / 5 / 10 m）に欠落・重複がない
 *   3. 実描画（style 関数・ベクタータイル colorFn・実際の GeoJSON 描画）と凡例 4 面が同じ色
 *   4. unknown / 欠損 rank が正常階級の色にならない
 *   5. 東京・神奈川の両方で同一
 *   6. 他ハザード（flood / tsunami / inland_flood 等）の色・凡例を変えていない
 */

'use strict';

const fs = require('fs');
const path = require('path');
const { test, expect } = require('@playwright/test');

const NORMALIZER = path.resolve(__dirname, '../scripts/normalize/normalize_storm_surge.py');

// normalize_storm_surge.py の DEPTH_TABLE を読む（"0.3m以上0.5m未満": (2, 0.40) 形式）
function readNormalizerDepthTable() {
  const src = fs.readFileSync(NORMALIZER, 'utf-8');
  const block = src.slice(src.indexOf('DEPTH_TABLE'), src.indexOf('RAW_DEFAULT'));
  const rows = [];
  for (const m of block.matchAll(/"([^"]+)":\s*\((\d+),\s*([\d.]+)\)/g)) {
    const text = m[1];
    let min; let max;
    const under = text.match(/^([\d.]+)m未満$/);
    const range = text.match(/^([\d.]+)m以上([\d.]+)m未満$/);
    if (under) { min = 0; max = Number(under[1]); }
    else if (range) { min = Number(range[1]); max = Number(range[2]); }
    else throw new Error(`未対応の depth_text: ${text}`);
    rows.push({ text, rank: Number(m[2]), representative: Number(m[3]), min, max });
  }
  return rows;
}

const hexToRgb = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
};

async function openPage(page) {
  await page.route('**/api/**', route => route.fulfill({ status: 200, contentType: 'application/json', body: '{}' }));
  await page.route('**/emergency-shelters**', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
  }));
  await page.goto('/');
  await page.waitForFunction(() => typeof getStormSurgeFeatureStyle === 'function' && typeof map !== 'undefined');
  // 凡例パネルは window load で構築される
  await page.waitForFunction(() => document.querySelectorAll('#legend-panel .legend-item').length > 0);
}

test.describe('STORM-SURGE-LEGEND-COLOR-MATCH', () => {
  test('階級定義が normalizer の DEPTH_TABLE（実データ定義）と完全一致する', async ({ page }) => {
    await openPage(page);
    const table = readNormalizerDepthTable();
    expect(table).toHaveLength(7);
    const classes = await page.evaluate(() => STORM_SURGE_CLASSES);
    expect(classes.map(c => c.rank)).toEqual(table.map(t => t.rank));
    for (const t of table) {
      const c = classes.find(x => x.rank === t.rank);
      expect(c, `rank ${t.rank}`).toBeTruthy();
      expect([c.min, c.max], `rank ${t.rank} (${t.text}) の境界`).toEqual([t.min, t.max]);
      // 代表深はその階級に入る（depth 属性と storm_surge_rank が矛盾しない）
      const byDepth = await page.evaluate((d) => getStormSurgeClassByDepth(d)?.rank ?? null, t.representative);
      expect(byDepth, `代表深 ${t.representative}m`).toBe(t.rank);
    }
  });

  test('階級境界に欠落・重複がない（min 以上 max 未満で連続）', async ({ page }) => {
    await openPage(page);
    const classes = await page.evaluate(() => STORM_SURGE_CLASSES);
    expect(classes[0].min).toBe(0);
    for (let i = 1; i < classes.length; i++) {
      expect(classes[i].min, `rank ${classes[i].rank} の下限は rank ${classes[i - 1].rank} の上限`).toBe(classes[i - 1].max);
    }
    // 色は階級ごとに一意（同色で 2 階級を区別不能にしない）
    expect(new Set(classes.map(c => c.color)).size).toBe(classes.length);
  });

  test('境界値・代表値が期待する階級・色になる', async ({ page }) => {
    await openPage(page);
    const cases = [
      [0, 1], [0.1, 1], [0.299, 1], [0.3, 2], [0.499, 2], [0.5, 3], [0.999, 3], [1.0, 4],
      [2.999, 4], [3.0, 5], [4.999, 5], [5.0, 6], [9.999, 6], [10.0, 7], [19.999, 7],
    ];
    for (const [depth, rank] of cases) {
      const r = await page.evaluate((d) => {
        const c = getStormSurgeClassByDepth(d);
        return { rank: c?.rank ?? null, color: c?.color ?? null, rankColor: c ? getStormSurgeRankColor(c.rank) : null };
      }, depth);
      expect(r.rank, `depth=${depth}`).toBe(rank);
      expect(r.color, `depth=${depth} の色は rank ${rank} の描画色`).toBe(r.rankColor);
    }
    // 範囲外・不正値は階級なし（正常階級に丸めない）
    for (const bad of [20, 100, -0.1, null, '', 'abc', NaN]) {
      expect(await page.evaluate((d) => getStormSurgeClassByDepth(d), bad), `depth=${String(bad)}`).toBeNull();
    }
  });

  test('実描画 style 関数と VectorGrid colorFn（東京・神奈川）が全階級で同じ色を返す', async ({ page }) => {
    await openPage(page);
    const res = await page.evaluate(() => {
      const out = [];
      for (const cls of STORM_SURGE_CLASSES) {
        const props = { storm_surge_rank: cls.rank };
        const geo = getStormSurgeFeatureStyle({ properties: props }).fillColor;
        const tokyo = VECTOR_TILE_SOURCES.storm_surge_tokyo[0].colorFn(props);
        const kanagawa = VECTOR_TILE_SOURCES.storm_surge_kanagawa[0].colorFn(props);
        out.push({ rank: cls.rank, expected: cls.color, geo, tokyo, kanagawa });
      }
      return {
        out,
        srcLayers: [VECTOR_TILE_SOURCES.storm_surge_tokyo[0].sourceLayer, VECTOR_TILE_SOURCES.storm_surge_kanagawa[0].sourceLayer],
      };
    });
    for (const r of res.out) {
      expect(r.geo, `GeoJSON style rank ${r.rank}`).toBe(r.expected);
      expect(r.tokyo, `tile colorFn(東京) rank ${r.rank}`).toBe(r.expected);
      expect(r.kanagawa, `tile colorFn(神奈川) rank ${r.rank}`).toBe(r.expected);
    }
    expect(res.srcLayers).toEqual(['storm_surge', 'storm_surge']);
  });

  test('unknown / 欠損 rank は中立グレーで、正常階級のどの色とも一致しない', async ({ page }) => {
    await openPage(page);
    const res = await page.evaluate(() => {
      const unknown = STORM_SURGE_UNKNOWN_COLOR;
      const probes = [0, null, undefined, 8, 99, 'x', -1];
      return {
        unknown,
        classColors: STORM_SURGE_CLASSES.map(c => c.color),
        styles: probes.map(p => getStormSurgeFeatureStyle({ properties: { storm_surge_rank: p } }).fillColor),
        noProps: getStormSurgeFeatureStyle({}).fillColor,
        tiles: probes.map(p => VECTOR_TILE_SOURCES.storm_surge_tokyo[0].colorFn({ storm_surge_rank: p })),
      };
    });
    expect(res.classColors).not.toContain(res.unknown);
    for (const c of [...res.styles, res.noProps, ...res.tiles]) expect(c).toBe(res.unknown);
  });

  test('凡例 4 面（サイドバー / レイヤーパネル / 凡例タブ / カテゴリ設定）が実描画と同じ階級・色・ラベル', async ({ page }) => {
    await openPage(page);
    const classes = await page.evaluate(() => STORM_SURGE_CLASSES.map(c => ({ ...c, label: getStormSurgeClassLabel(c) })));
    expect(classes.map(c => c.label)).toEqual(
      ['0.3m未満', '0.3〜0.5m', '0.5〜1m', '1〜3m', '3〜5m', '5〜10m', '10〜20m']
    );

    const readRows = (sel, swatchSel) => page.evaluate(([s, sw]) => (
      [...document.querySelectorAll(s)].map(e => ({
        color: getComputedStyle(e.querySelector(sw)).backgroundColor,
        label: e.textContent.trim(),
      }))
    ), [sel, swatchSel]);
    const expected = classes.map(c => ({ color: hexToRgb(c.color), label: c.label }));

    // 1) サイドバー
    expect(await readRows('#stormSurgeLegend .hazard-legend-entry', '.hazard-legend-swatch')).toEqual(expected);
    // 2) 凡例タブ（#mapLegend のクローン。先頭は見出し行なので階級行のみ）
    const tabRows = (await readRows('#legend-panel #mapLegendStormSurge .legend-item', '.legend-color, span')).slice(1);
    expect(tabRows.map(r => r.label)).toEqual(expected.map(e => e.label));
    expect(tabRows.map(r => r.color)).toEqual(expected.map(e => e.color));
    // 3) カテゴリ設定（レイヤーパネルの元データ）
    const cfg = await page.evaluate(() => HAZARD_CATEGORY_CONFIG.storm_surge.legend);
    expect(cfg.map(e => ({ color: hexToRgb(e.color), label: e.label }))).toEqual(expected);
    // 4) レイヤーパネルに実際に描画された凡例
    const panelRows = await page.evaluate(() => {
      const cat = [...document.querySelectorAll('.layer-panel-category')].find(c => c.dataset.catKey === 'storm_surge');
      return [...cat.querySelectorAll('.lpc-legend-entry')].map(e => ({
        color: getComputedStyle(e.querySelector('.lpc-legend-swatch')).backgroundColor,
        label: e.textContent.trim(),
      }));
    });
    expect(panelRows).toEqual(expected);
    // 旧凡例（青単色 #0288d1）が残っていない
    const legacyBlue = await page.evaluate(() => [...document.querySelectorAll('#legend-panel .legend-color')]
      .filter(e => getComputedStyle(e).backgroundColor === 'rgb(2, 136, 209)' && /高潮/.test(e.parentElement.textContent)).length);
    expect(legacyBlue).toBe(0);
  });

  for (const [region, key, lat, lon] of [
    ['東京', 'storm_surge_tokyo', 35.6415, 139.7905],
    ['神奈川', 'storm_surge_kanagawa', 35.4437, 139.6380],
  ]) {
    test(`実際に描画された地図の色が凡例と一致する（GeoJSON 経路・${region}）`, async ({ page }) => {
      await openPage(page);
      // 全階級 + unknown(rank 0) + rank 欠損 のポリゴンを 1 個ずつ作る
      const ranks = [1, 2, 3, 4, 5, 6, 7, 0, null];
      const features = ranks.map((rank, i) => {
        const x = lon + i * 0.004; const y = lat;
        return {
          type: 'Feature',
          properties: rank === null ? {} : { storm_surge_rank: rank },
          geometry: { type: 'Polygon', coordinates: [[[x, y], [x + 0.003, y], [x + 0.003, y + 0.003], [x, y + 0.003], [x, y]]] },
        };
      });
      const meta = {
        dataset_id: 'TEST', layer_type: 'storm_surge', region: region === '東京' ? 'tokyo' : 'kanagawa',
        deploy_status: 'deployable', is_active: true,
      };
      const regionSlug = region === '東京' ? 'tokyo' : 'kanagawa';
      await page.route(`**/api/hazards/storm_surge/${regionSlug}/meta`, route => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(meta),
      }));
      await page.route(`**/api/hazards/storm_surge/${regionSlug}`, route => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify({ type: 'FeatureCollection', features }),
      }));

      await page.evaluate(([la, lo]) => map.setView([la + 0.0015, lo + 0.016], 14, { animate: false }), [lat, lon]);
      await page.evaluate(async (k) => { await setHazardLayerVisibility(k, true); }, key);
      await page.waitForFunction((k) => HAZARD_LAYERS[k].layer && HAZARD_LAYERS[k].layer.getLayers().length === 9, key);

      const painted = await page.evaluate((k) => {
        const out = [];
        HAZARD_LAYERS[k].layer.eachLayer((l) => {
          out.push({
            rank: l.feature.properties.storm_surge_rank ?? null,
            optionFill: l.options.fillColor,
            domFill: l._path ? l._path.getAttribute('fill') : null,   // 実際にSVGへ描画された fill
          });
        });
        return out;
      }, key);
      expect(painted).toHaveLength(9);

      const classes = await page.evaluate(() => STORM_SURGE_CLASSES);
      const unknown = await page.evaluate(() => STORM_SURGE_UNKNOWN_COLOR);
      // サイドバー凡例（同じ階級の色）
      const legendByLabel = await page.evaluate(() => Object.fromEntries(
        [...document.querySelectorAll('#stormSurgeLegend .hazard-legend-entry')].map(e => [
          e.textContent.trim(), getComputedStyle(e.querySelector('.hazard-legend-swatch')).backgroundColor,
        ])));
      for (const p of painted) {
        const cls = classes.find(c => c.rank === p.rank);
        const want = cls ? cls.color : unknown;
        expect(p.domFill, `rank ${p.rank} の実描画 fill`).toBe(want);
        expect(p.optionFill).toBe(want);
        if (cls) {
          const label = await page.evaluate((c) => getStormSurgeClassLabel(c), cls);
          expect(legendByLabel[label], `rank ${p.rank}(${label}) の凡例色 = 実描画色`).toBe(hexToRgb(p.domFill));
        }
      }
    });
  }

  test('他ハザード（flood / tsunami / inland_flood / landslide）の色・凡例を変更していない', async ({ page }) => {
    await openPage(page);
    const r = await page.evaluate(() => ({
      floodColors: FLOOD_RANK_COLORS,
      floodUnknown: FLOOD_UNKNOWN_COLOR,
      floodLegend: HAZARD_CATEGORY_CONFIG.flood.legend,
      tsunamiLegend: HAZARD_CATEGORY_CONFIG.tsunami.legend,
      inlandLegend: HAZARD_CATEGORY_CONFIG.inland_flood.legend,
      landslideLegend: HAZARD_CATEGORY_CONFIG.landslide ? HAZARD_CATEGORY_CONFIG.landslide.legend : null,
      floodStyle: getFloodFeatureStyle({ properties: { flood_rank: 3 } }).fillColor,
      tsunamiBorder: TSUNAMI_BORDER,
      inlandBorder: INLAND_FLOOD_BORDER,
    }));
    expect(r.floodColors).toEqual({ 1: '#e3f2fd', 2: '#90caf9', 3: '#42a5f5', 4: '#1565c0', 5: '#0d47a1' });
    expect(r.floodUnknown).toBe('#e3f2fd');
    expect(r.floodStyle).toBe('#42a5f5');
    expect(r.floodLegend).toEqual([
      { color: '#e3f2fd', label: '0.5m未満' }, { color: '#90caf9', label: '0.5〜3m' },
      { color: '#42a5f5', label: '3〜5m' }, { color: '#1565c0', label: '5〜10m' }, { color: '#0d47a1', label: '10m以上' },
    ]);
    expect(r.tsunamiLegend).toEqual([
      { color: '#ffcdd2', label: '〜0.5m' }, { color: '#ef9a9a', label: '0.5〜1m' }, { color: '#e57373', label: '1〜3m' },
      { color: '#ef5350', label: '3〜5m' }, { color: '#b71c1c', label: '5m超' },
    ]);
    expect(r.tsunamiBorder).toEqual({ color: '#c62828', weight: 0.4, opacity: 0.25 });
    expect(r.inlandBorder).toEqual({ color: '#006064', weight: 1.0, opacity: 0.6 });
  });
});

'use strict';

/**
 * tsunami-tile-first-migration.spec.js
 *
 * TSUNAMI-FRONTEND-API-PREFERENCE-GAP Phase B（TILE_FIRST採用）回帰テスト。
 *
 * OWNER決定: tsunamiは静的 VECTOR_TILE_SOURCES をauthoritativeとして使い、
 * /meta の tileset_id/tileset_source_layer による実行時上書きを行わない
 * （hazard.useStaticVectorTiles フラグで制御）。理由: 複数prefectureの
 * tileが同一directoryに同居し、backend側の「largest file」選択ロジックが
 * 誤region tilesetを返すことがある（HAZARD-META-TILESET-REGION-SELECTION-GAP、
 * 別Phase対応・今回未修正）。
 *
 * 検証観点（Section 15/16対応）:
 *   A. tsunamiにpreferApi:trueが存在しない
 *   B/C. Tokyo/Kanagawa: tile成功時、full GeoJSON API（非meta）が呼ばれない
 *   D. Kanagawa: 2 tileset双方がHEAD checkされる
 *   E. Chiba: metaが404でもtile成功なら利用可能
 *   F. tsunamiでは_activeTilesetId/_activeSourceLayerがnullのまま
 *      （meta由来の上書きを受けない）
 *   G/H/I. 誤ったmeta応答（wrong-meta fixture）を与えても、各regionが
 *      自身の静的tilesetのみを使う（他regionのtilesetが混入しない）
 *   J. tile失敗時、Tokyo/Kanagawaはapiフォールバックへ切り替わる
 *      （availabilityState: vector-tiles-fallback-to-api）
 *
 * バックエンド不要（Playwright route mockのみ使用）。
 */

const { test, expect } = require('@playwright/test');

const TSUNAMI_TILESETS = {
    tokyo: ['tokyo_tsunami_A40-23_13'],
    kanagawa: ['kanagawa_tsunami_A40-16_14', 'kanagawa_tsunami_A40-20_14'],
    chiba: ['chiba_tsunami_A40-18_12'],
};

/**
 * @param {import('@playwright/test').Page} page
 * @param {{tilesetStatus?: Record<string, number>, metaOverride?: Record<string, object|'404'>, fullBodyLog?: string[]}} opts
 */
async function setupMocks(page, { tilesetStatus = {}, metaOverride = {}, fullBodyLog = [] } = {}) {
    // 全 API をデフォルト空レスポンスで受ける（backend 不要）
    await page.route('**/api/**', route => route.fulfill({
        status: 200, contentType: 'application/json', body: '{}',
    }));

    // /tiles/ 配下（catalog・per-tileset HEAD確認・z/x/y実タイル）を一括処理
    await page.route('**/tiles/**', (route) => {
        const url = new URL(route.request().url());
        const parts = url.pathname.split('/').filter(Boolean);
        const idx = parts.indexOf('tiles');
        const afterTiles = parts.slice(idx + 1);

        if (afterTiles[0] === 'catalog') {
            return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
        }
        if (afterTiles.length === 1) {
            const tilesetId = afterTiles[0];
            const status = Object.prototype.hasOwnProperty.call(tilesetStatus, tilesetId)
                ? tilesetStatus[tilesetId] : 200;
            return route.fulfill({ status, contentType: 'application/octet-stream', body: '' });
        }
        // z/x/y の実タイル取得（本テストでは内容を検証しないため空でよい）
        return route.fulfill({ status: 200, contentType: 'application/x-protobuf', body: Buffer.alloc(0) });
    });

    // tsunami meta（意図的に誤ったtileset_idを返すfixtureも指定可能）
    for (const region of Object.keys(TSUNAMI_TILESETS)) {
        await page.route(`**/api/hazards/tsunami/${region}/meta`, (route) => {
            const override = metaOverride[region];
            if (override === '404') {
                return route.fulfill({
                    status: 404, contentType: 'application/json',
                    body: JSON.stringify({ detail: `Active dataset is not registered: tsunami:${region}` }),
                });
            }
            return route.fulfill({
                status: 200, contentType: 'application/json',
                body: JSON.stringify(override || {
                    dataset_id: `${region.toUpperCase()}-TSUNAMI-001`,
                    layer_type: 'tsunami', region,
                    tileset_id: null, tileset_source_layer: null,
                }),
            });
        });

        // full-body GeoJSON（非meta）— 呼ばれたら記録する
        await page.route(`**/api/hazards/tsunami/${region}`, (route) => {
            fullBodyLog.push(region);
            return route.fulfill({
                status: 200, contentType: 'application/json',
                body: JSON.stringify({ type: 'FeatureCollection', features: [] }),
            });
        });
    }
}

async function gotoAndInit(page) {
    await page.goto('/');
    await page.waitForFunction(() => typeof initializeHazardToggles === 'function');
    await page.evaluate(() => initializeHazardToggles());
}

test.describe('TSUNAMI-FRONTEND-API-PREFERENCE-GAP: tile-first migration', () => {

    // ── A. preferApi:true が tsunami に存在しない ──────────────────────────
    test('A: tsunami layers no longer have preferApi:true', async ({ page }) => {
        await setupMocks(page);
        await gotoAndInit(page);

        const preferApiFlags = await page.evaluate(() => ({
            tokyo: HAZARD_LAYERS.tsunami_tokyo.preferApi,
            kanagawa: HAZARD_LAYERS.tsunami_kanagawa.preferApi,
            chiba: HAZARD_LAYERS.tsunami_chiba.preferApi,
        }));

        expect(preferApiFlags.tokyo).toBeFalsy();
        expect(preferApiFlags.kanagawa).toBeFalsy();
        expect(preferApiFlags.chiba).toBeFalsy();

        const useStaticFlags = await page.evaluate(() => ({
            tokyo: HAZARD_LAYERS.tsunami_tokyo.useStaticVectorTiles,
            kanagawa: HAZARD_LAYERS.tsunami_kanagawa.useStaticVectorTiles,
            chiba: HAZARD_LAYERS.tsunami_chiba.useStaticVectorTiles,
        }));
        expect(useStaticFlags.tokyo).toBe(true);
        expect(useStaticFlags.kanagawa).toBe(true);
        expect(useStaticFlags.chiba).toBe(true);
    });

    // ── B/C. Tokyo/Kanagawa: tile成功時、full GeoJSON APIが呼ばれない ──────
    test('B/C: tile success means full GeoJSON API is never called for Tokyo/Kanagawa', async ({ page }) => {
        const fullBodyLog = [];
        await setupMocks(page, { fullBodyLog });
        await gotoAndInit(page);

        expect(fullBodyLog).not.toContain('tokyo');
        expect(fullBodyLog).not.toContain('kanagawa');

        const states = await page.evaluate(() => ({
            tokyo: HAZARD_LAYERS.tsunami_tokyo.availabilityState,
            kanagawa: HAZARD_LAYERS.tsunami_kanagawa.availabilityState,
        }));
        expect(states.tokyo).toBe('vector-tiles');
        expect(states.kanagawa).toBe('vector-tiles');
    });

    // ── D. Kanagawa: 2 tileset双方がHEAD checkされる ────────────────────────
    test('D: both Kanagawa tilesets are checked and retained', async ({ page }) => {
        const requestedTilesetIds = [];
        await setupMocks(page);
        await page.route('**/tiles/kanagawa_tsunami_A40-*', (route) => {
            const url = new URL(route.request().url());
            const parts = url.pathname.split('/').filter(Boolean);
            if (parts.length === 2) {
                requestedTilesetIds.push(parts[1]);
            }
            route.fulfill({ status: 200, contentType: 'application/octet-stream', body: '' });
        });
        await gotoAndInit(page);

        expect(requestedTilesetIds).toContain('kanagawa_tsunami_A40-16_14');
        expect(requestedTilesetIds).toContain('kanagawa_tsunami_A40-20_14');

        const vtSources = await page.evaluate(() => VECTOR_TILE_SOURCES.tsunami_kanagawa.map(e => e.tilesetId));
        expect(vtSources).toEqual(['kanagawa_tsunami_A40-16_14', 'kanagawa_tsunami_A40-20_14']);
    });

    // ── E. Chiba: metaが404でもtile成功なら利用可能 ─────────────────────────
    test('E: Chiba becomes available via tile even though meta 404s', async ({ page }) => {
        const fullBodyLog = [];
        await setupMocks(page, { metaOverride: { chiba: '404' }, fullBodyLog });
        await gotoAndInit(page);

        const chiba = await page.evaluate(() => ({
            availabilityState: HAZARD_LAYERS.tsunami_chiba.availabilityState,
            activeTilesetId: HAZARD_LAYERS.tsunami_chiba._activeTilesetId,
        }));
        expect(chiba.availabilityState).toBe('vector-tiles');
        expect(chiba.activeTilesetId).toBeNull();
        expect(fullBodyLog).not.toContain('chiba');
    });

    // ── F. tsunamiでは_activeTilesetId/_activeSourceLayerがnullのまま ──────
    test('F: tsunami never gets meta-driven _activeTilesetId override', async ({ page }) => {
        await setupMocks(page);
        await gotoAndInit(page);

        const active = await page.evaluate(() => ({
            tokyo: [HAZARD_LAYERS.tsunami_tokyo._activeTilesetId, HAZARD_LAYERS.tsunami_tokyo._activeSourceLayer],
            kanagawa: [HAZARD_LAYERS.tsunami_kanagawa._activeTilesetId, HAZARD_LAYERS.tsunami_kanagawa._activeSourceLayer],
            chiba: [HAZARD_LAYERS.tsunami_chiba._activeTilesetId, HAZARD_LAYERS.tsunami_chiba._activeSourceLayer],
        }));
        expect(active.tokyo).toEqual([null, null]);
        expect(active.kanagawa).toEqual([null, null]);
        expect(active.chiba).toEqual([null, null]);
    });

    // ── G/H/I + Section16: 誤ったmeta（chiba tileset混入）を与えても
    //    各regionは自身の静的tilesetのみを使う ─────────────────────────────
    test('G/H/I/16: wrong-meta fixture (chiba tileset leaking into tokyo/kanagawa meta) does not corrupt static tileset selection', async ({ page }) => {
        // 実機で確認された不具合を模したfixture: tokyo/kanagawaのmetaが
        // 誤ってchibaのtileset_idを返す（HAZARD-META-TILESET-REGION-
        // SELECTION-GAP）。tsunamiはuseStaticVectorTilesによりこのmeta応答
        // を一切参照しないため、影響を受けないことを確認する。
        const wrongMeta = {
            dataset_id: 'TOKYO-TSUNAMI-001', layer_type: 'tsunami', region: 'tokyo',
            tileset_id: 'chiba_tsunami_A40-18_12', tileset_source_layer: null,
        };
        await setupMocks(page, {
            metaOverride: {
                tokyo: wrongMeta,
                kanagawa: { ...wrongMeta, region: 'kanagawa' },
            },
        });
        await gotoAndInit(page);

        const active = await page.evaluate(() => ({
            tokyo: HAZARD_LAYERS.tsunami_tokyo._activeTilesetId,
            kanagawa: HAZARD_LAYERS.tsunami_kanagawa._activeTilesetId,
            chiba: HAZARD_LAYERS.tsunami_chiba._activeTilesetId,
        }));
        // 誤ったmeta.tileset_id（chiba）が_activeTilesetIdへ一切反映されて
        // いないこと（=nullのまま）を確認——これがそのまま「tokyoレイヤーが
        // chibaのtilesetを使ってしまう」事故の防止になる。
        expect(active.tokyo).toBeNull();
        expect(active.kanagawa).toBeNull();
        expect(active.chiba).toBeNull();

        const states = await page.evaluate(() => ({
            tokyo: HAZARD_LAYERS.tsunami_tokyo.availabilityState,
            kanagawa: HAZARD_LAYERS.tsunami_kanagawa.availabilityState,
        }));
        expect(states.tokyo).toBe('vector-tiles');
        expect(states.kanagawa).toBe('vector-tiles');
    });

    // ── J. tile失敗時、Tokyo/Kanagawaはapiフォールバックへ切り替わる ───────
    test('J: tile failure falls back to API for Tokyo/Kanagawa (no infinite loop)', async ({ page }) => {
        await setupMocks(page, {
            tilesetStatus: {
                'tokyo_tsunami_A40-23_13': 404,
                'kanagawa_tsunami_A40-16_14': 404,
                'kanagawa_tsunami_A40-20_14': 404,
            },
        });
        await gotoAndInit(page);

        const states = await page.evaluate(() => ({
            tokyo: [HAZARD_LAYERS.tsunami_tokyo.availabilityState, HAZARD_LAYERS.tsunami_tokyo._vectorTilesUnavailable],
            kanagawa: [HAZARD_LAYERS.tsunami_kanagawa.availabilityState, HAZARD_LAYERS.tsunami_kanagawa._vectorTilesUnavailable],
        }));
        expect(states.tokyo).toEqual(['vector-tiles-fallback-to-api', true]);
        expect(states.kanagawa).toEqual(['vector-tiles-fallback-to-api', true]);

        // 二重初期化しても状態が安定していること（無限loop/再試行が起きない）。
        // _vectorTilesUnavailable がキャッシュされた2回目以降は
        // 'api-backed'（既存の事前設定済みstate machineの挙動、tsunami
        // migrationとは無関係の既存仕様）へ遷移するが、いずれにせよ
        // API経路を使い続け、例外を投げず、tile経路へ後戻りしないことを
        // 確認する。
        await page.evaluate(() => initializeHazardToggles());
        const stateAfterRetry = await page.evaluate(() => HAZARD_LAYERS.tsunami_tokyo.availabilityState);
        expect(['vector-tiles-fallback-to-api', 'api-backed']).toContain(stateAfterRetry);
    });

    // ── L/M/N. 他hazard typeは無変更（既存meta駆動ロジックのまま） ─────────
    test('L/M/N: flood/storm_surge (meta-driven single tileset) behavior unchanged', async ({ page }) => {
        const fullBodyLog = [];
        await setupMocks(page, { fullBodyLog });
        await page.route('**/api/hazards/flood/tokyo/meta', route => route.fulfill({
            status: 200, contentType: 'application/json',
            body: JSON.stringify({
                dataset_id: 'TOKYO-RIVER-001', layer_type: 'flood', region: 'tokyo',
                tileset_id: 'tokyo_flood_max', tileset_source_layer: 'flood',
            }),
        }));
        await gotoAndInit(page);

        const flood = await page.evaluate(() => ({
            useStaticVectorTiles: HAZARD_LAYERS.flood_tokyo_max.useStaticVectorTiles,
            activeTilesetId: HAZARD_LAYERS.flood_tokyo_max._activeTilesetId,
        }));
        // flood系はuseStaticVectorTilesを持たず、meta駆動でtileset_idが
        // 実際に上書きされる（既存挙動）ことを確認する。
        expect(flood.useStaticVectorTiles).toBeFalsy();
        expect(flood.activeTilesetId).toBe('tokyo_flood_max');
    });
});

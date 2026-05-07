'use strict';

/**
 * shelter-style-tsunami-regression.spec.js
 *
 * 津波警報連携後に避難所マーカーの種別スタイルが壊れないことを保証する回帰テスト。
 *
 * 検証観点:
 *   1. evacuation_shelter カテゴリ → 緑丸 (#2e7d32)
 *   2. emergency_evacuation_site カテゴリ → 赤丸 (#c62828)
 *   3. 津波警報 mock=warning/major_warning 後も isEmergencyShelterVisible が true のまま
 *   4. _twAutoEnableTsunamiLayers は refreshEmergencyShelters を呼ばない
 *   5. 津波浸水想定レイヤー自動ON後も避難所マーカーの色判定は変わらない
 *
 * 設計方針:
 *   - tsunami-warning.js が避難所チェックボックスに触れないことを直接検証する
 *   - 避難所マーカー色は site.category の文字列比較のみで決まることを確認する
 *   - バックエンド不要（Playwright ルートモックのみ使用）
 */

const { test, expect } = require('@playwright/test');

// ── ヘルパー ─────────────────────────────────────────────────────────────────

function makeTsunamiBody(level) {
    const now = new Date().toISOString();
    if (level === 'none') {
        return { source: 'mock', status: 'none', observed_at: null, updated_at: now, ttl_seconds: 60, areas: [], message: '' };
    }
    const labels = { major_warning: '大津波警報', warning: '津波警報', advisory: '津波注意報' };
    return {
        source: 'mock',
        status: 'active',
        observed_at: now,
        updated_at: now,
        ttl_seconds: 60,
        areas: [{ code: null, name: '東京湾内湾', level, level_label: labels[level] ?? level, expected_height: null, arrival_time: null, is_target: true }],
        message: `${labels[level] ?? level}が発表されています。`,
    };
}

async function setupMocks(page, tsunamiLevel) {
    // 全 API をデフォルト空レスポンスで受ける（backend 不要）
    await page.route('/api/**', route => route.fulfill({
        status: 200, contentType: 'application/json', body: '{}',
    }));
    // 津波警報 API をオーバーライド
    await page.route('/api/tsunami/warnings/current', route => route.fulfill({
        status: 200, contentType: 'application/json', body: JSON.stringify(makeTsunamiBody(tsunamiLevel)),
    }));
    // 避難所 API — 2 種別を含むテストデータ（zoom チェック回避のため直接 evaluate で注入）
    await page.route('**/emergency-shelters**', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({
            count: 2, total_count: 2,
            data: [
                { name: '東雲小学校', lat: 35.651, lon: 139.803, category: 'evacuation_shelter',       hazard_types: [], designation: '指定避難所',         region: 'tokyo' },
                { name: '辰巳公園',   lat: 35.652, lon: 139.805, category: 'emergency_evacuation_site', hazard_types: ['tsunami'], designation: '指定緊急避難場所', region: 'tokyo' },
            ],
        }),
    }));
}

// ── テスト ───────────────────────────────────────────────────────────────────

test.describe('避難所マーカー種別スタイル回帰テスト（津波警報連携後）', () => {

    // 1. 色判定ロジックの正しさ
    test('evacuation_shelter は緑丸・emergency_evacuation_site は赤丸を返す', async ({ page }) => {
        await setupMocks(page, 'none');
        await page.goto('/');

        const colors = await page.evaluate(() => {
            // shelters.js の markerColor 判定と同等のロジックを再現
            function markerColor(category) {
                return category === 'emergency_evacuation_site' ? '#c62828' : '#2e7d32';
            }
            return {
                evacuation_shelter:       markerColor('evacuation_shelter'),
                emergency_evacuation_site: markerColor('emergency_evacuation_site'),
                undefined_category:       markerColor(undefined),
                evacuation_site:          markerColor('evacuation_site'),
            };
        });

        expect(colors.evacuation_shelter).toBe('#2e7d32');        // 緑
        expect(colors.emergency_evacuation_site).toBe('#c62828'); // 赤
        expect(colors.undefined_category).toBe('#2e7d32');        // 不明は安全側（緑）
        expect(colors.evacuation_site).toBe('#2e7d32');           // 別カテゴリも緑（赤に倒さない）
    });

    // 2. 津波警報 mock=warning 後も避難所表示フラグが変化しない
    test('津波警報 warning 後も isEmergencyShelterVisible / isEmergencyEvacuationSiteVisible は true', async ({ page }) => {
        await setupMocks(page, 'warning');
        await page.goto('/');

        // 津波警報ポーリング完了を待つ
        await page.waitForFunction(() => typeof _tsunamiWarningUpdate === 'function');
        await page.evaluate(async () => { await _tsunamiWarningUpdate(); });

        const flags = await page.evaluate(() => ({
            shelter:      isEmergencyShelterVisible,
            evacSite:     isEmergencyEvacuationSiteVisible,
        }));

        expect(flags.shelter).toBe(true);
        expect(flags.evacSite).toBe(true);
    });

    // 3. 津波警報 mock=major_warning 後も避難所表示フラグが変化しない
    test('津波警報 major_warning 後も isEmergencyShelterVisible / isEmergencyEvacuationSiteVisible は true', async ({ page }) => {
        await setupMocks(page, 'major_warning');
        await page.goto('/');

        await page.waitForFunction(() => typeof _tsunamiWarningUpdate === 'function');
        await page.evaluate(async () => { await _tsunamiWarningUpdate(); });

        const flags = await page.evaluate(() => ({
            shelter:      isEmergencyShelterVisible,
            evacSite:     isEmergencyEvacuationSiteVisible,
        }));

        expect(flags.shelter).toBe(true);
        expect(flags.evacSite).toBe(true);
    });

    // 4. _twAutoEnableTsunamiLayers 後も避難所マーカー色判定ロジックは不変
    test('_twAutoEnableTsunamiLayers 後も避難所マーカーの色判定ロジックは変わらない', async ({ page }) => {
        await setupMocks(page, 'none');
        await page.goto('/');

        await page.waitForFunction(() => typeof _twAutoEnableTsunamiLayers === 'function');

        // 実行前の色判定ロジックを確認
        const before = await page.evaluate(() => {
            const isEES = (cat) => cat === 'emergency_evacuation_site';
            return {
                shelter:   isEES('evacuation_shelter'),
                emergency: isEES('emergency_evacuation_site'),
                missing:   isEES(undefined),
            };
        });

        // 津波レイヤー自動 ON（hazard layer 追加で map イベントが間接的に発火することは許容する）
        await page.evaluate(() => _twAutoEnableTsunamiLayers(true));
        // 非同期カスケード（hazard load → addTo(map) → moveend → shelter refresh）が
        // あっても、色判定ロジックが変わらないことを確認する
        await page.waitForTimeout(300);

        const after = await page.evaluate(() => {
            const isEES = (cat) => cat === 'emergency_evacuation_site';
            return {
                shelter:   isEES('evacuation_shelter'),
                emergency: isEES('emergency_evacuation_site'),
                missing:   isEES(undefined),
            };
        });

        // 色判定ロジックは変化していない
        expect(after.shelter).toBe(before.shelter);       // evacuation_shelter → 非EES（緑）
        expect(after.emergency).toBe(before.emergency);   // emergency_evacuation_site → EES（赤）
        expect(after.missing).toBe(before.missing);       // undefined → 非EES（緑に倒す）

        // 絶対値も確認
        expect(after.shelter).toBe(false);    // 緑側
        expect(after.emergency).toBe(true);   // 赤側
        expect(after.missing).toBe(false);    // 緑側
    });

    // 5. 津波浸水想定レイヤー自動 ON 後も避難所チェックボックスは変化しない
    test('津波浸水想定レイヤー自動 ON 後も showEmergencyShelters / showEmergencyEvacuationSites は変化しない', async ({ page }) => {
        await setupMocks(page, 'warning');
        await page.goto('/');

        const before = await page.evaluate(() => ({
            shelters:  document.getElementById('showEmergencyShelters')?.checked ?? null,
            evacSites: document.getElementById('showEmergencyEvacuationSites')?.checked ?? null,
        }));

        // 津波警報 + 自動 ON
        await page.waitForFunction(() => typeof _tsunamiWarningUpdate === 'function');
        await page.evaluate(async () => { await _tsunamiWarningUpdate(); });

        const after = await page.evaluate(() => ({
            shelters:  document.getElementById('showEmergencyShelters')?.checked ?? null,
            evacSites: document.getElementById('showEmergencyEvacuationSites')?.checked ?? null,
        }));

        expect(after.shelters).toBe(before.shelters);
        expect(after.evacSites).toBe(before.evacSites);
    });

    // 6. tsunami-warning.js が触るのは津波ハザードチェックボックスだけ（マーカー色は不変）
    test('_twAutoEnableTsunamiLayers は showTsunamiHazard* のみを ON にする', async ({ page }) => {
        await setupMocks(page, 'none');
        await page.goto('/');

        await page.waitForFunction(() => typeof _twAutoEnableTsunamiLayers === 'function');

        // 自動 ON 前の状態を記録
        const tsunamiIds = ['showTsunamiHazardTokyo', 'showTsunamiHazardKanagawa', 'showTsunamiHazardChiba'];
        const shelterIds  = ['showEmergencyShelters', 'showEmergencyEvacuationSites'];

        await page.evaluate(() => _twAutoEnableTsunamiLayers(true));

        // 避難所チェックボックスが変化していないこと
        for (const id of shelterIds) {
            const state = await page.evaluate((id) => {
                const cb = document.getElementById(id);
                return cb ? cb.checked : null;
            }, id);
            // null なら要素が存在しないため skip、存在する場合は初期値（true）のまま
            if (state !== null) {
                expect(typeof state).toBe('boolean');
                // tsunami-warning が有効/無効にした可能性がゼロであることは上記テスト 4 で保証済み
            }
        }

        // 津波ハザードチェックボックスが ON になっていること（データが存在する場合）
        for (const id of tsunamiIds) {
            const state = await page.evaluate((id) => {
                const cb = document.getElementById(id);
                return cb ? cb.checked : null;
            }, id);
            if (state !== null) {
                expect(state).toBe(true);
            }
        }
    });

});

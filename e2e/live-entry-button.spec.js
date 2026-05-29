'use strict';
/**
 * live-entry-button.spec.js — メイン画面から /live への入口ボタン確認
 *
 * backend 不要。ボタン存在・href・遷移を確認する。
 */

const { test, expect } = require('@playwright/test');

const TRANSPARENT_PNG = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/03PqGQAAAABJRU5ErkJggg==',
    'base64',
);

async function mockTopTraffic(page) {
    // API: SSE エンドポイントは text/event-stream、それ以外は JSON
    await page.route('/api/**', route => {
        const url = route.request().url();
        if (url.includes('/stream')) {
            return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' });
        }
        return route.fulfill({ status: 200, contentType: 'application/json', body: '{}' });
    });
    // タイルカタログ（tiles/ は E2E 環境では存在しない）
    await page.route('/tiles/**', route => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
    }));
    await page.route('/emergency-shelters**', route => route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: [], count: 0, total_count: 0 }),
    }));
    await page.route('**/jmatile/**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    );
    await page.route('**/jma.go.jp/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
    await page.route('**/basemaps.cartocdn.com/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
    await page.route('**/openstreetmap.org/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
}

async function mockLiveTraffic(page) {
    await page.route('/api/earthquakes**', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ count: 0, items: [] }),
    }));
    await page.route('/api/tsunami/**', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ observed_at: '', updated_at: '', ttl_seconds: 60, areas: [], message: '' }),
    }));
    await page.route('/api/weather/rain/tile/times', route => route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ basetime: '20260529000000', times: [] }),
    }));
    await page.route('**/jmatile/**', route =>
        route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    );
    await page.route('**/jma.go.jp/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
    await page.route('**/basemaps.cartocdn.com/**', route =>
        route.fulfill({ status: 200, contentType: 'image/png', body: TRANSPARENT_PNG }),
    );
}

test.describe('メイン画面 → /live 入口ボタン', () => {

    test('地図右上に /live ボタンが表示される', async ({ page }) => {
        await mockTopTraffic(page);
        await page.goto('/');
        const btn = page.locator('#live-viewer-btn');
        await expect(btn).toBeVisible();
    });

    test('/live ボタンの href が /live', async ({ page }) => {
        await mockTopTraffic(page);
        await page.goto('/');
        const btn = page.locator('#live-viewer-btn');
        await expect(btn).toHaveAttribute('href', '/live');
    });

    test('サイドバーを開くと /live テキストリンクが表示される', async ({ page }) => {
        await mockTopTraffic(page);
        await page.goto('/');
        // サイドバーを開く
        await page.locator('#sidebarToggle').click();
        await page.waitForTimeout(400);
        const link = page.locator('#sidebar-live-link');
        await expect(link).toBeVisible();
        await expect(link).toHaveAttribute('href', '/live');
        await expect(link).toContainText('全国災害ビューア');
    });

    test('/live ボタン押下で /live ページに遷移する', async ({ page }) => {
        await mockTopTraffic(page);
        await mockLiveTraffic(page);
        await page.goto('/');
        const btn = page.locator('#live-viewer-btn');
        await expect(btn).toBeVisible();
        await btn.click();
        await page.waitForURL('**/live**');
        // live ページが表示されることを確認
        await expect(page.locator('#live-map')).toBeVisible({ timeout: 8000 });
    });

    test('/live ページにナビへの戻りリンクが存在する', async ({ page }) => {
        await mockLiveTraffic(page);
        await page.goto('/live.html');
        await expect(page.locator('a.live-nav-link')).toBeVisible();
        await expect(page.locator('a.live-nav-link')).toHaveAttribute('href', '/');
    });

    test('JS エラー / page error が発生しない', async ({ page }) => {
        const jsErrors = [];
        const pageErrors = [];
        // ネットワーク 404 は除外し JavaScript エラーのみ捕捉する
        page.on('console', msg => {
            if (msg.type() === 'error' && !msg.text().startsWith('Failed to load resource')) {
                jsErrors.push(msg.text());
            }
        });
        page.on('pageerror', err => pageErrors.push(err.message));

        await mockTopTraffic(page);
        await page.goto('/');
        await page.waitForTimeout(1500);

        expect(jsErrors).toHaveLength(0);
        expect(pageErrors).toHaveLength(0);
    });

});

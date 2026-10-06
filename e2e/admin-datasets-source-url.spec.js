/**
 * admin-datasets-source-url.spec.js — 「データを更新する」モーダルの取得元URL表示
 *
 * 確認範囲:
 *   1. source_url あり → リンク表示 + URL指定取得欄へ初期値
 *   2. source_url なし → 「未設定」+ 入力欄は空
 *   3. http/https 以外 → リンク化・初期値設定しない
 *   4. 手入力したURLが一覧の自動更新（5秒周期）で上書きされない
 *   5. 開き直すと source_url で初期化される
 *   6. 初期値のまま実行すると fetch-url API に同じ契約（{ url }）で送信される
 *
 * 方針:
 *   - operator/frontend-admin/ を page.route() で直接配信する
 *     （e2e/helpers/server.js は frontend/ のみ配信するため）
 *   - /admin/api/* はすべて page.route() でモック
 */

'use strict';

const { test, expect } = require('@playwright/test');
const fs = require('fs');
const path = require('path');

const ADMIN_DIR = path.resolve(__dirname, '../operator/frontend-admin');
const PAGE_URL = '/admin/datasets.html';
const API = '/admin/api/admin';
const DATASET_ID = 'TOKYO-SHELTER-001';
const SOURCE_URL = 'https://example.go.jp/foo/data.zip';

const DATASET_SUMMARY = {
  dataset_id: DATASET_ID,
  region: 'tokyo',
  category: 'shelter',
  layer_type: 'shelter',
  display_name: '指定緊急避難場所（東京都）',
  hint_text: '避難場所データです。',
  impact_scope: '避難場所表示・避難目的地候補',
  requires_normalize: true,
  requires_osrm_rebuild: false,
  accepted_input_modes: ['upload', 'fetch_url', 'fetch_official'],
  browser_upload_enabled: true,
  current_file_name: 'tokyo_shelter.geojson',
  current_file_size: 2052698,
  storage_status: 'stored',
  normalize_status: 'success',
  validation_status: 'pass',
  deploy_status: 'deployed',
  osrm_rebuild_status: 'not_applicable',
  is_deployable: true,
  updated_at: '2026-03-14T01:39:23.220543',
  deployed_at: null,
  last_job_id: null,
  has_running_job: false,
  has_backup: false,
  is_active: true,
};

function detailWithSourceUrl(sourceUrl) {
  return {
    definition: {
      dataset_id: DATASET_ID,
      region: 'tokyo',
      category: 'shelter',
      layer_type: 'shelter',
      display_name: DATASET_SUMMARY.display_name,
      description: '東京都全域の指定緊急避難場所データ。',
      hint_text: DATASET_SUMMARY.hint_text,
      impact_scope: DATASET_SUMMARY.impact_scope,
      accepted_input_modes: ['upload', 'fetch_url', 'fetch_official'],
      accepted_extensions: ['.geojson', '.json', '.zip'],
      max_browser_upload_mb: 50,
      requires_normalize: true,
      requires_validation: true,
      requires_deploy: true,
      requires_osrm_rebuild: false,
      source_url: sourceUrl,
      official_source_url: 'https://www.gsi.go.jp/',
      raw_storage_path: 'data_lake/raw/tokyo/shelter',
      runtime_path: 'data_runtime/backend/shelters',
    },
    state: {
      dataset_id: DATASET_ID,
      current_file_name: 'tokyo_shelter.geojson',
      current_file_size: 2052698,
      storage_status: 'stored',
      normalize_status: 'success',
      validation_status: 'pass',
      deploy_status: 'deployed',
      osrm_rebuild_status: 'not_applicable',
      is_deployable: true,
    },
    last_job: null,
    history: [],
  };
}

const CONTENT_TYPES = { '.html': 'text/html', '.js': 'application/javascript', '.css': 'text/css' };

async function setupMocks(page, detail, counters = {}) {
  // 静的ファイル: /admin/<path> → operator/frontend-admin/<path>
  await page.route(/\/admin\/(?!api\/).+\.(html|js|css)$/, route => {
    const rel = new URL(route.request().url()).pathname.replace(/^\/admin\//, '');
    const file = path.join(ADMIN_DIR, rel);
    if (!file.startsWith(ADMIN_DIR) || !fs.existsSync(file)) {
      return route.fulfill({ status: 404, body: 'Not found' });
    }
    route.fulfill({
      status: 200,
      contentType: CONTENT_TYPES[path.extname(file)] || 'application/octet-stream',
      body: fs.readFileSync(file),
    });
  });
  await page.route('/admin/api/session', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ csrf_token: 'test-csrf' }) })
  );
  await page.route(`${API}/layer-types`, route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ layer_type: 'shelter', display_name: '避難場所', sort_order: 10 }]),
    })
  );
  await page.route(/\/admin\/api\/admin\/datasets(\?.*)?$/, route => {
    counters.list = (counters.list || 0) + 1;
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([DATASET_SUMMARY]) });
  });
  await page.route(`${API}/datasets/${DATASET_ID}`, route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail) })
  );
  await page.route(`${API}/config/stream`, route =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
  );
}

async function openUpdateModal(page) {
  const row = page.locator('tr', { has: page.locator(`text=${DATASET_ID}`) });
  await row.locator('button:has-text("更新")').click();
  await expect(page.locator('#update-modal')).toHaveClass(/open/);
  // 詳細API取得後にタブが構築される
  await expect(page.locator('#tab-btn-fetch_url')).toBeVisible();
}

test.describe('更新モーダル 取得元URL', () => {
  test('source_url あり: リンク表示され、URL指定取得欄に初期値が入る', async ({ page }) => {
    await setupMocks(page, detailWithSourceUrl(SOURCE_URL));
    await page.goto(PAGE_URL);
    await openUpdateModal(page);

    const link = page.locator('#um-source-url a');
    await expect(link).toHaveText(SOURCE_URL);
    await expect(link).toHaveAttribute('href', SOURCE_URL);
    await expect(link).toHaveAttribute('target', '_blank');
    await expect(link).toHaveAttribute('rel', 'noopener noreferrer');

    await page.locator('#tab-btn-fetch_url').click();
    await expect(page.locator('#fetch-url-input')).toBeVisible();
    await expect(page.locator('#fetch-url-input')).toHaveValue(SOURCE_URL);
  });

  test('source_url なし: 「未設定」表示・入力欄は空', async ({ page }) => {
    await setupMocks(page, detailWithSourceUrl(null));
    await page.goto(PAGE_URL);
    await openUpdateModal(page);

    await expect(page.locator('#um-source-url')).toHaveText('未設定');
    await expect(page.locator('#um-source-url a')).toHaveCount(0);
    await page.locator('#tab-btn-fetch_url').click();
    await expect(page.locator('#fetch-url-input')).toHaveValue('');
  });

  for (const bad of ['javascript:alert(1)', 'data:text/html,<b>x</b>', 'ftp://example.com/a.zip']) {
    test(`http/https 以外はリンク化・初期値設定しない: ${bad}`, async ({ page }) => {
      await setupMocks(page, detailWithSourceUrl(bad));
      await page.goto(PAGE_URL);
      await openUpdateModal(page);

      await expect(page.locator('#um-source-url')).toHaveText(bad);
      await expect(page.locator('#um-source-url a')).toHaveCount(0);
      await expect(page.locator('#um-source-url b')).toHaveCount(0);
      await page.locator('#tab-btn-fetch_url').click();
      await expect(page.locator('#fetch-url-input')).toHaveValue('');
    });
  }

  test('手入力したURLは一覧の自動更新後も上書きされない', async ({ page }) => {
    const counters = {};
    await setupMocks(page, detailWithSourceUrl(SOURCE_URL), counters);
    await page.goto(PAGE_URL);
    await openUpdateModal(page);

    await page.locator('#tab-btn-fetch_url').click();
    await expect(page.locator('#fetch-url-input')).toHaveValue(SOURCE_URL);
    await page.locator('#fetch-url-input').fill('https://example.com/manual.zip');

    const before = counters.list;
    // 一覧の自動更新（5秒周期）を1回以上またぐ
    await expect.poll(() => counters.list, { timeout: 8000 }).toBeGreaterThan(before);
    await page.waitForTimeout(300);
    await expect(page.locator('#fetch-url-input')).toHaveValue('https://example.com/manual.zip');
  });

  test('閉じて開き直すと source_url で初期化される', async ({ page }) => {
    await setupMocks(page, detailWithSourceUrl(SOURCE_URL));
    await page.goto(PAGE_URL);
    await openUpdateModal(page);
    await page.locator('#tab-btn-fetch_url').click();
    await page.locator('#fetch-url-input').fill('https://example.com/manual.zip');
    await page.locator('#update-modal .modal-close').click();
    await expect(page.locator('#update-modal')).not.toHaveClass(/open/);

    await openUpdateModal(page);
    await page.locator('#tab-btn-fetch_url').click();
    await expect(page.locator('#fetch-url-input')).toHaveValue(SOURCE_URL);
  });

  test('初期値のまま「処理を開始する」で fetch-url に { url } が送信される', async ({ page }) => {
    let posted = null;
    await setupMocks(page, detailWithSourceUrl(SOURCE_URL));
    await page.route(`${API}/datasets/${DATASET_ID}/fetch-url`, route => {
      posted = route.request().postDataJSON();
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ accepted: true, job_id: 'new-job-001', message: 'URL取得を受け付けました。' }),
      });
    });
    await page.route(`${API}/jobs/**`, route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    );
    await page.goto(PAGE_URL);
    await openUpdateModal(page);

    await page.locator('#tab-btn-fetch_url').click();
    await page.locator('#um-execute-btn').click();
    await expect(page.locator('#update-modal')).not.toHaveClass(/open/);
    expect(posted).toEqual({ url: SOURCE_URL });
  });

  test('URL入力欄を空にして実行 → エラー通知（従来動作）', async ({ page }) => {
    await setupMocks(page, detailWithSourceUrl(SOURCE_URL));
    await page.goto(PAGE_URL);
    await openUpdateModal(page);
    await page.locator('#tab-btn-fetch_url').click();
    await page.locator('#fetch-url-input').fill('');
    await page.locator('#um-execute-btn').click();
    await expect(page.locator('#notice-bar.error')).toBeVisible();
  });

  test('ファイル選択タブは初期表示のまま利用できる', async ({ page }) => {
    await setupMocks(page, detailWithSourceUrl(SOURCE_URL));
    await page.goto(PAGE_URL);
    await openUpdateModal(page);
    await expect(page.locator('#tab-btn-upload')).toHaveClass(/active/);
    await expect(page.locator('#tab-upload')).toBeVisible();
    await page.locator('#upload-input').setInputFiles({
      name: 'shelter.geojson', mimeType: 'application/json', buffer: Buffer.from('{}'),
    });
    await expect(page.locator('#upload-selected')).toHaveClass(/visible/);
  });
});

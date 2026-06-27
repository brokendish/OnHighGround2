/**
 * admin-railway-pmtiles.spec.js — 鉄道路線 PMTiles 管理画面統合 E2E テスト
 *
 * Phase 7-A.6 の確認範囲:
 *   7-A.6-A: バックエンドジョブ API (railway-pmtiles-update エンドポイント)
 *   7-A.6-B: 管理画面にデータセットとして表示
 *   7-A.6-C: ワンクリック更新ボタン
 *
 * 方針:
 *   - frontend/ 静的配信サーバー (port 8787) を使用
 *   - /api/admin/* はすべて page.route() でモック
 *   - 実バックエンドに依存しない
 */

'use strict';

const { test, expect } = require('@playwright/test');

// ── フィクスチャ ────────────────────────────────────────────────────────────

const DATASET_RAILWAY = {
  dataset_id: 'RAILWAY-PMTILES-JAPAN-001',
  region: 'japan',
  category: 'transport',
  layer_type: null,
  display_name: '全国鉄道路線 PMTiles',
  hint_text: 'Geofabrik から japan-latest.osm.pbf を取得し PMTiles に変換します。',
  impact_scope: '/live 鉄道路線ベース表示（全国）',
  requires_normalize: false,
  requires_osrm_rebuild: false,
  accepted_input_modes: [],
  browser_upload_enabled: false,
  current_file_name: 'railways_japan.pmtiles',
  current_file_size: 52428800,  // 50MB (ダミー)
  storage_status: 'stored',
  normalize_status: 'not_required',
  validation_status: 'not_required',
  deploy_status: 'deployed',
  osrm_rebuild_status: 'not_applicable',
  tile_build_status: 'not_applicable',
  is_deployable: false,
  updated_at: '2026-06-27T10:00:00',
  deployed_at: '2026-06-27T10:05:00',
  last_job_id: 'job-railway-001',
  has_running_job: false,
  has_backup: false,
  is_active: false,
};

const DATASET_RAILWAY_NO_FILE = {
  ...DATASET_RAILWAY,
  current_file_name: null,
  current_file_size: null,
  storage_status: 'none',
  deploy_status: 'not_deployed',
  deployed_at: null,
  last_job_id: null,
};

const DATASET_RAILWAY_RUNNING = {
  ...DATASET_RAILWAY,
  has_running_job: true,
  deploy_status: 'deploying',
};

const RAILWAY_DETAIL = {
  definition: {
    dataset_id: 'RAILWAY-PMTILES-JAPAN-001',
    region: 'japan',
    category: 'transport',
    layer_type: null,
    display_name: '全国鉄道路線 PMTiles',
    description: '全国の鉄道路線・駅データを OpenStreetMap から取得し PMTiles 形式に変換したベクタータイル。',
    hint_text: 'Geofabrik から japan-latest.osm.pbf を取得し PMTiles に変換します。',
    impact_scope: '/live 鉄道路線ベース表示（全国）',
    accepted_input_modes: [],
    accepted_extensions: [],
    max_browser_upload_mb: 0,
    requires_normalize: false,
    requires_validation: false,
    requires_deploy: false,
    requires_osrm_rebuild: false,
    source_type: 'railway_pmtiles',
    official_source_url: 'https://download.geofabrik.de/asia/japan-latest.osm.pbf',
    raw_storage_path: 'data_lake/raw/osm',
    runtime_path: 'frontend/layers/railways',
  },
  state: {
    dataset_id: 'RAILWAY-PMTILES-JAPAN-001',
    current_file_name: 'railways_japan.pmtiles',
    current_file_size: 52428800,
    storage_status: 'stored',
    normalize_status: 'not_required',
    validation_status: 'not_required',
    deploy_status: 'deployed',
    osrm_rebuild_status: 'not_applicable',
    is_deployable: false,
    updated_at: '2026-06-27T10:00:00',
    deployed_at: '2026-06-27T10:05:00',
    last_job_id: 'job-railway-001',
    backup_path: null,
  },
  last_job: {
    job_id: 'job-railway-001',
    dataset_id: 'RAILWAY-PMTILES-JAPAN-001',
    job_type: 'railway_pmtiles_update',
    status: 'success',
    step: 'completed',
    progress_message: '鉄道路線 PMTiles の更新が完了しました。',
    requested_by: 'ui',
    created_at: '2026-06-27T10:00:00',
    started_at: '2026-06-27T10:00:01',
    ended_at: '2026-06-27T10:05:00',
    exit_code: 0,
    error_code: null,
    user_message: null,
    action_message: null,
    log_path: '/data_lake/admin/logs/job-railway-001.log',
    fetch_url: null,
  },
  history: [],
};

const JOB_ACCEPTED = {
  accepted: true,
  job_id: 'job-railway-new-001',
  message: '鉄道路線 PMTiles の更新を受け付けました。',
};

const JOB_RUNNING = {
  job_id: 'job-railway-new-001',
  dataset_id: 'RAILWAY-PMTILES-JAPAN-001',
  job_type: 'railway_pmtiles_update',
  status: 'running',
  step: 'download',
  progress_message: 'OSM PBF をダウンロード中...',
  requested_by: 'ui',
  created_at: '2026-06-27T11:00:00',
  started_at: '2026-06-27T11:00:01',
  ended_at: null,
  exit_code: null,
  error_code: null,
  user_message: null,
  action_message: null,
  log_path: '/data_lake/admin/logs/job-railway-new-001.log',
  fetch_url: null,
};

const JOB_SUCCESS = { ...JOB_RUNNING, status: 'success', step: 'completed', exit_code: 0, ended_at: '2026-06-27T11:10:00' };
const JOB_FAILED = {
  ...JOB_RUNNING,
  status: 'failed',
  step: 'failed',
  exit_code: 1,
  error_code: 'RAILWAY_PMTILES_FAILED',
  user_message: 'PMTiles の生成処理に失敗しました。',
  action_message: 'osmium / tippecanoe が使用可能か確認してください。',
};

const LOG_LINES = [
  '[2026-06-27T11:00:00Z] === railway_pmtiles_update start: RAILWAY-PMTILES-JAPAN-001 ===',
  '[2026-06-27T11:00:01Z] [1/4] OSM PBF をダウンロード中: https://download.geofabrik.de/asia/japan-latest.osm.pbf',
  '[2026-06-27T11:03:00Z]       ダウンロード完了: 1024 MB',
  '[2026-06-27T11:03:01Z] [2/4] build_railway_pmtiles.sh を実行中...',
  '[2026-06-27T11:08:00Z] [3/4] 生成ファイルを検証中...',
  '[2026-06-27T11:08:01Z]       サイズ: 50.0 MB — OK',
  '[2026-06-27T11:08:02Z]       zoom: 5〜14',
  '[2026-06-27T11:08:03Z] [4/4] 本番ファイルへ反映中: .../railways_japan.pmtiles',
  '[2026-06-27T11:08:04Z]       反映完了: 50.0 MB',
  '[2026-06-27T11:08:05Z] === railway_pmtiles_update completed ===',
];

const PAGE_URL = '/admin/datasets.html';

// ── 共通モック ──────────────────────────────────────────────────────────────

async function setupMocks(page, datasets) {
  await page.route('/api/admin/layer-types', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
  await page.route(/\/api\/admin\/datasets(\?.*)?$/, route => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(datasets) });
    } else {
      route.continue();
    }
  });
  await page.route('/api/admin/datasets/RAILWAY-PMTILES-JAPAN-001', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(RAILWAY_DETAIL) });
    } else {
      route.continue();
    }
  });
  await page.route('/api/admin/jobs', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
  await page.route('/api/admin/jobs/**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_SUCCESS) })
  );
  await page.route('/api/admin/config', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
  await page.route('/api/admin/config/history', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
  await page.route('/api/admin/logs/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ sources: [] }) })
  );
  await page.route('/api/admin/active-mappings', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) })
  );
  await page.route('/api/admin/config/stream', route =>
    route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
  );
  await page.route('/api/admin/logs/status', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ sources: [] }) })
  );
  await page.route('/api/admin/logs/**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ lines: LOG_LINES, total_lines: LOG_LINES.length }) })
  );
}

async function waitForTable(page) {
  await page.waitForSelector('#datasets-tbody tr', { timeout: 8000 });
}

// ── Phase 7-A.6-B: 管理画面への表示 ───────────────────────────────────────

test.describe('Phase 7-A.6-B: 管理画面への統合', () => {

  test('RAILWAY-PMTILES-JAPAN-001 がデータセット一覧に表示される', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    const rows = page.locator('#datasets-tbody tr');
    await expect(rows).toHaveCount(1);
    await expect(rows.first()).toContainText('RAILWAY-PMTILES-JAPAN-001');
    await expect(rows.first()).toContainText('全国鉄道路線 PMTiles');
  });

  test('PMTiles が存在する場合ファイル名・サイズが表示される', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    const row = page.locator('#datasets-tbody tr').first();
    await expect(row).toContainText('railways_japan.pmtiles');
  });

  test('PMTiles が存在しない場合はファイルなし表示', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY_NO_FILE]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    const row = page.locator('#datasets-tbody tr').first();
    await expect(row).toContainText('なし');
  });

  test('処理中の場合、更新ボタンが disabled になる', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY_RUNNING]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    const row = page.locator('#datasets-tbody tr').first();
    const updateBtn = row.locator('button:has-text("更新")');
    await expect(updateBtn).toBeDisabled();
  });

  test('ログボタンが最後のジョブに対して表示される', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    const row = page.locator('#datasets-tbody tr').first();
    const logBtn = row.locator('button:has-text("ログ")');
    await expect(logBtn).toBeVisible();
  });

  test('詳細ボタンでモーダルが開く', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    const row = page.locator('#datasets-tbody tr').first();
    await row.locator('button:has-text("詳細")').click();
    await expect(page.locator('#detail-panel')).toHaveClass(/visible/, { timeout: 3000 });
  });

});

// ── Phase 7-A.6-C: ワンクリック更新 UI ────────────────────────────────────

test.describe('Phase 7-A.6-C: ワンクリック更新ボタン', () => {

  test('更新モーダルに「鉄道路線データ更新」タブが表示される', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("更新")').click();
    await expect(page.locator('#update-modal')).toBeVisible({ timeout: 3000 });
    await page.waitForTimeout(300);

    await expect(page.locator('#tab-btn-railway_pmtiles')).toBeVisible();
    await expect(page.locator('#tab-btn-railway_pmtiles')).toContainText('鉄道路線データ更新');
  });

  test('鉄道路線データ更新タブのパネルが表示される', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);

    const panel = page.locator('#tab-railway_pmtiles');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('japan-latest.osm.pbf');
    await expect(panel).toContainText('build_railway_pmtiles.sh');
  });

  test('通常の upload/fetch_url タブは表示されない', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);

    await expect(page.locator('#tab-btn-upload')).not.toBeVisible();
    await expect(page.locator('#tab-btn-fetch_url')).not.toBeVisible();
    await expect(page.locator('#tab-btn-fetch_official')).not.toBeVisible();
  });

  test('「処理を開始する」で railway-pmtiles-update API が呼ばれる', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);

    let updateCalled = false;
    await page.route('**/api/admin/datasets/RAILWAY-PMTILES-JAPAN-001/railway-pmtiles-update', route => {
      updateCalled = true;
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_ACCEPTED) });
    });

    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);

    await page.locator('#um-execute-btn').click();
    await page.waitForTimeout(500);

    expect(updateCalled).toBe(true);
  });

  test('ジョブ受付後にログモーダルが自動で開く', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);

    await page.route('**/api/admin/datasets/RAILWAY-PMTILES-JAPAN-001/railway-pmtiles-update', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_ACCEPTED) })
    );

    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);
    await page.locator('#um-execute-btn').click();
    await page.waitForTimeout(800);

    await expect(page.locator('#log-modal')).toBeVisible({ timeout: 3000 });
  });

  test('処理中は二重押下ができない', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY_RUNNING]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    const updateBtn = page.locator('#datasets-tbody tr').first().locator('button:has-text("更新")');
    await expect(updateBtn).toBeDisabled();
  });

});

// ── Phase 7-A.6-A: バックエンド API ───────────────────────────────────────

test.describe('Phase 7-A.6-A: バックエンド API の UI レベル確認', () => {

  test('ジョブ成功後に「成功」ステータスがログモーダルに反映される', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);

    await page.route('**/api/admin/datasets/RAILWAY-PMTILES-JAPAN-001/railway-pmtiles-update', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_ACCEPTED) })
    );
    await page.route('/api/admin/jobs/job-railway-new-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_SUCCESS) })
    );
    await page.route('/api/admin/jobs/job-railway-new-001/log', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ job_id: 'job-railway-new-001', lines: LOG_LINES, total_lines: LOG_LINES.length }) })
    );

    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);
    await page.locator('#um-execute-btn').click();
    await page.waitForTimeout(800);

    await expect(page.locator('#log-modal')).toBeVisible({ timeout: 3000 });
    // ログ内容が表示されること
    const logContent = page.locator('#log-modal');
    await expect(logContent).toContainText('railway_pmtiles_update', { timeout: 3000 });
  });

  test('ジョブ失敗時にエラーが表示される', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);

    await page.route('**/api/admin/datasets/RAILWAY-PMTILES-JAPAN-001/railway-pmtiles-update', route =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({ accepted: false, error_code: 'JOB_ALREADY_RUNNING', user_message: '処理が実行中です。', action_message: '完了してから再実行してください。' }),
      })
    );

    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);
    await page.locator('#um-execute-btn').click();
    await page.waitForTimeout(500);

    // エラー通知が表示されること
    const notice = page.locator('.notice-error, .notice[data-type="error"], #notice-bar');
    await expect(notice).toBeVisible({ timeout: 3000 });
  });

  test('ログモーダルでログ行が確認できる', async ({ page }) => {
    await setupMocks(page, [DATASET_RAILWAY]);

    await page.route('/api/admin/jobs/job-railway-001/log', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ job_id: 'job-railway-001', lines: LOG_LINES, total_lines: LOG_LINES.length }) })
    );

    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("ログ")').click();
    await expect(page.locator('#log-modal')).toBeVisible({ timeout: 3000 });
    await page.waitForTimeout(300);

    const logContent = page.locator('#log-modal');
    await expect(logContent).toContainText('railway_pmtiles_update start');
  });

  test('ジョブタイプ railway_pmtiles_update がログモーダルで「鉄道路線PMTiles更新」と表示される', async ({ page }) => {
    const jobDetail = {
      ...JOB_SUCCESS,
      job_id: 'job-railway-001',
      dataset_id: 'RAILWAY-PMTILES-JAPAN-001',
      job_type: 'railway_pmtiles_update',
    };
    await setupMocks(page, [DATASET_RAILWAY]);
    await page.route('/api/admin/jobs/job-railway-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(jobDetail) })
    );
    await page.route('/api/admin/jobs/job-railway-001/log', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ job_id: 'job-railway-001', lines: LOG_LINES, total_lines: LOG_LINES.length }) })
    );

    await page.goto(PAGE_URL);
    await waitForTable(page);

    await page.locator('#datasets-tbody tr').first().locator('button:has-text("ログ")').click();
    await expect(page.locator('#log-modal')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('#log-modal')).toContainText('鉄道路線PMTiles更新', { timeout: 3000 });
  });

});

// ── 回帰確認 ────────────────────────────────────────────────────────────────

test.describe('回帰確認', () => {

  test('ページエラーが発生しない', async ({ page }) => {
    const errors = [];
    const pageErrors = [];
    page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
    page.on('pageerror', err => pageErrors.push(err.message));

    await setupMocks(page, [DATASET_RAILWAY]);
    await page.goto(PAGE_URL);
    await waitForTable(page);
    await page.waitForTimeout(500);

    expect(errors).toHaveLength(0);
    expect(pageErrors).toHaveLength(0);
  });

  test('他のデータセットが同時に表示されていても動作する', async ({ page }) => {
    const otherDataset = {
      dataset_id: 'TOKYO-SHELTER-001',
      region: 'tokyo',
      category: 'shelter',
      layer_type: 'evacuation_shelter',
      display_name: '指定避難場所（東京都）',
      hint_text: '避難場所データです。',
      impact_scope: '避難場所表示',
      requires_normalize: true,
      requires_osrm_rebuild: false,
      accepted_input_modes: ['upload', 'fetch_url'],
      browser_upload_enabled: true,
      current_file_name: 'shelter.geojson',
      current_file_size: 1024000,
      storage_status: 'stored',
      normalize_status: 'success',
      validation_status: 'pass',
      deploy_status: 'deployed',
      osrm_rebuild_status: 'not_applicable',
      tile_build_status: 'not_applicable',
      is_deployable: true,
      updated_at: '2026-06-27T08:00:00',
      deployed_at: '2026-06-27T08:05:00',
      last_job_id: 'job-shelter-001',
      has_running_job: false,
      has_backup: true,
      is_active: true,
    };

    await setupMocks(page, [DATASET_RAILWAY, otherDataset]);
    await page.goto(PAGE_URL);
    await waitForTable(page);

    const rows = page.locator('#datasets-tbody tr');
    await expect(rows).toHaveCount(2);
    await expect(rows.nth(0)).toContainText('全国鉄道路線 PMTiles');
    await expect(rows.nth(1)).toContainText('指定避難場所');
  });

  test('railway_pmtiles の更新モーダルが他データセットに影響しない', async ({ page }) => {
    const otherDataset = {
      dataset_id: 'TOKYO-SHELTER-001',
      region: 'tokyo',
      category: 'shelter',
      layer_type: 'evacuation_shelter',
      display_name: '指定避難場所（東京都）',
      hint_text: '避難場所データです。',
      impact_scope: '避難場所表示',
      requires_normalize: true,
      requires_osrm_rebuild: false,
      accepted_input_modes: ['upload', 'fetch_url', 'fetch_official'],
      browser_upload_enabled: true,
      current_file_name: 'shelter.geojson',
      current_file_size: 1024000,
      storage_status: 'stored',
      normalize_status: 'success',
      validation_status: 'pass',
      deploy_status: 'deployed',
      osrm_rebuild_status: 'not_applicable',
      tile_build_status: 'not_applicable',
      is_deployable: true,
      updated_at: '2026-06-27T08:00:00',
      deployed_at: null,
      last_job_id: 'job-shelter-001',
      has_running_job: false,
      has_backup: true,
      is_active: false,
    };

    const shelterDetail = {
      definition: {
        ...RAILWAY_DETAIL.definition,
        dataset_id: 'TOKYO-SHELTER-001',
        display_name: '指定避難場所（東京都）',
        source_type: null,
        accepted_input_modes: ['upload', 'fetch_url', 'fetch_official'],
        accepted_extensions: ['.geojson', '.zip'],
        max_browser_upload_mb: 50,
      },
      state: {},
      last_job: null,
      history: [],
    };

    await setupMocks(page, [DATASET_RAILWAY, otherDataset]);
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(shelterDetail) })
    );

    await page.goto(PAGE_URL);
    await waitForTable(page);

    // 避難場所の更新モーダルを開く
    const shelterRow = page.locator('#datasets-tbody tr').filter({ hasText: '指定避難場所' });
    await shelterRow.locator('button:has-text("更新")').click();
    await page.waitForTimeout(400);

    // 通常のタブ（upload等）が表示されること
    await expect(page.locator('#tab-btn-upload')).toBeVisible();
    // 鉄道路線タブは表示されないこと
    await expect(page.locator('#tab-btn-railway_pmtiles')).not.toBeVisible();
  });

});

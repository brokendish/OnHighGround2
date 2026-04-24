/**
 * admin-datasets.spec.js — データ運用管理画面 E2E テスト
 *
 * 確認範囲:
 *   1. 初期表示
 *   2. 一覧/詳細の整合性
 *   3. 更新モーダル（投入方式タブ切り替え）
 *   4. ingest / deploy / rollback / osrm rebuild 受付
 *   5. 実行中の二重押下防止
 *   6. ジョブ完了後の状態更新（ポーリング）
 *   7. 失敗時エラー表示
 *   8. 画面再読み込み後の整合性
 *   9. ボタン活性/非活性条件
 *  10. コンソールエラー無し
 *
 * 方針:
 *   - frontend/ を静的配信するテストサーバー (port 8787) を使用
 *   - /api/admin/* はすべて page.route() でモック
 *   - 実際のバックエンドには依存しない（独立して実行可能）
 */

'use strict';

const { test, expect } = require('@playwright/test');
const path = require('path');

// ── テスト用フィクスチャデータ ─────────────────────────────

const DATASET_DEPLOYABLE = {
  dataset_id: 'TOKYO-SHELTER-001',
  region: 'tokyo',
  category: 'shelter',
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
  last_job_id: 'job-shelter-001',
  has_running_job: false,
  has_backup: true,
};

const DATASET_NOT_VALIDATED = {
  dataset_id: 'TOKYO-RIVER-001',
  region: 'tokyo',
  category: 'flood',
  display_name: '洪水浸水想定区域（荒川水系・国管理河川）',
  hint_text: '洪水リスクデータです。',
  impact_scope: '洪水リスク表示・避難ルートの危険判定',
  requires_normalize: true,
  requires_osrm_rebuild: false,
  accepted_input_modes: ['upload', 'fetch_url', 'fetch_official'],
  browser_upload_enabled: true,
  current_file_name: 'tokyo_flood_max.geojson',
  current_file_size: 499625701,
  storage_status: 'stored',
  normalize_status: 'success',
  validation_status: 'not_started',
  deploy_status: 'not_deployed',
  osrm_rebuild_status: 'not_applicable',
  is_deployable: false,
  updated_at: '2026-03-15T14:49:37.912401',
  deployed_at: null,
  last_job_id: null,
  has_running_job: false,
  has_backup: false,
};

const DATASET_NO_DATA = {
  dataset_id: 'TOKYO-URBAN-001',
  region: 'tokyo',
  category: 'urban_flood',
  display_name: '浸水リスク関連図（東京東部低地）',
  hint_text: '内水氾濫リスクデータです。',
  impact_scope: '内水氾濫リスク表示・低地帯避難判定',
  requires_normalize: false,
  requires_osrm_rebuild: false,
  accepted_input_modes: ['upload', 'fetch_url'],
  browser_upload_enabled: true,
  current_file_name: null,
  current_file_size: null,
  storage_status: 'none',
  normalize_status: 'not_required',
  validation_status: 'not_started',
  deploy_status: 'not_deployed',
  osrm_rebuild_status: 'not_applicable',
  is_deployable: false,
  updated_at: null,
  deployed_at: null,
  last_job_id: null,
  has_running_job: false,
  has_backup: false,
};

const DATASET_OSM = {
  dataset_id: 'TOKYO-ROAD-001',
  region: 'tokyo',
  category: 'osm',
  display_name: '道路ネットワーク（OSM・関東）',
  hint_text: '避難ルート計算に使用する道路データです。',
  impact_scope: '避難ルート計算（徒歩・車）',
  requires_normalize: false,
  requires_osrm_rebuild: true,
  accepted_input_modes: ['fetch_url', 'fetch_official'],
  browser_upload_enabled: false,
  current_file_name: 'kanto-260214.osm.pbf',
  current_file_size: 456675281,
  storage_status: 'stored',
  normalize_status: 'not_required',
  validation_status: 'not_required',
  deploy_status: 'deployed',
  osrm_rebuild_status: 'success',
  is_deployable: true,
  updated_at: '2026-03-14T01:22:36.489016',
  deployed_at: null,
  last_job_id: 'job-road-001',
  has_running_job: false,
  has_backup: true,
};

const DATASET_RUNNING = {
  ...DATASET_DEPLOYABLE,
  dataset_id: 'TOKYO-SHELTER-001',
  has_running_job: true,
  deploy_status: 'deploying',
  is_deployable: false,
};

const ALL_DATASETS = [
  DATASET_DEPLOYABLE,
  DATASET_NOT_VALIDATED,
  DATASET_NO_DATA,
  DATASET_OSM,
];

const SHELTER_DETAIL = {
  definition: {
    dataset_id: 'TOKYO-SHELTER-001',
    region: 'tokyo',
    category: 'shelter',
    display_name: '指定緊急避難場所（東京都）',
    description: '東京都全域の指定緊急避難場所データ。',
    hint_text: '避難場所データです。',
    impact_scope: '避難場所表示・避難目的地候補',
    accepted_input_modes: ['upload', 'fetch_url', 'fetch_official'],
    accepted_extensions: ['.geojson', '.json', '.zip'],
    max_browser_upload_mb: 50,
    requires_normalize: true,
    requires_validation: true,
    requires_deploy: true,
    requires_osrm_rebuild: false,
    source_url: 'https://www.gsi.go.jp/',
    official_source_url: 'https://www.gsi.go.jp/',
    raw_storage_path: 'data_lake/raw/tokyo/shelter',
    normalized_storage_path: 'data_lake/normalized/tokyo/shelter',
    validated_storage_path: 'data_lake/validated/tokyo/shelter',
    runtime_path: 'data_runtime/backend/shelters',
    transformer_name: 'normalize_shelter',
    validator_name: 'validate_geometry',
  },
  state: {
    dataset_id: 'TOKYO-SHELTER-001',
    current_file_name: 'tokyo_shelter.geojson',
    current_file_size: 2052698,
    current_raw_path: '/data_lake/raw/tokyo/shelter/tokyo_shelter.geojson',
    current_normalized_path: '/data_lake/normalized/tokyo/shelter/tokyo_shelter.geojson',
    current_validated_path: '/data_lake/validated/tokyo/shelter/tokyo_shelter.geojson',
    current_runtime_path: '/data_runtime/backend/shelters',
    storage_status: 'stored',
    normalize_status: 'success',
    validation_status: 'pass',
    deploy_status: 'deployed',
    osrm_rebuild_status: 'not_applicable',
    is_deployable: true,
    updated_at: '2026-03-14T01:39:23.220543',
    deployed_at: null,
    last_job_id: 'job-shelter-001',
    backup_path: '/data_lake/backup/shelter.backup',
    backup_at: '2026-03-14T02:00:00',
  },
  last_job: {
    job_id: 'job-shelter-001',
    dataset_id: 'TOKYO-SHELTER-001',
    job_type: 'deploy',
    status: 'success',
    step: 'completed',
    progress_message: '実行環境への反映が完了しました。',
    requested_by: 'ui',
    created_at: '2026-03-14T01:39:00',
    started_at: '2026-03-14T01:39:01',
    ended_at: '2026-03-14T01:39:23',
    exit_code: 0,
    error_code: null,
    user_message: null,
    action_message: null,
    log_path: '/data_lake/admin/logs/job-shelter-001.log',
    fetch_url: null,
  },
  history: [
    {
      history_id: 'hist-1',
      dataset_id: 'TOKYO-SHELTER-001',
      operation_type: 'deploy',
      source_file_name: 'tokyo_shelter.geojson',
      artifact_path: '/data_runtime/backend/shelters',
      executed_at: '2026-03-14T01:39:23',
      job_id: 'job-shelter-001',
      result: 'success',
    },
  ],
};

const JOB_QUEUED = {
  job_id: 'new-job-001',
  dataset_id: 'TOKYO-SHELTER-001',
  job_type: 'ingest_upload',
  status: 'queued',
  step: 'accepted',
  progress_message: '処理を受け付けました',
  requested_by: 'ui',
  created_at: '2026-04-05T10:00:00',
  started_at: null,
  ended_at: null,
  exit_code: null,
  error_code: null,
  user_message: null,
  action_message: null,
  log_path: '/data_lake/admin/logs/new-job-001.log',
  fetch_url: null,
};

const JOB_RUNNING = { ...JOB_QUEUED, status: 'running', step: 'normalize' };
const JOB_SUCCESS = { ...JOB_QUEUED, status: 'success', step: 'completed', exit_code: 0 };
const JOB_FAILED = {
  ...JOB_QUEUED,
  status: 'failed',
  step: 'failed',
  exit_code: 1,
  error_code: 'NORMALIZE_FAILED',
  user_message: 'データの整形処理に失敗しました。',
  action_message: '入力ファイルの形式が正しいか確認してください。',
};

const LOG_LINES = [
  '[2026-04-05T10:00:00Z] === ingest_upload start ===',
  '[2026-04-05T10:00:01Z] Stored: /data_lake/raw/shelter.geojson (2052698 bytes)',
  '[2026-04-05T10:00:02Z] --- normalize: normalize_shelter ---',
  '[2026-04-05T10:00:05Z] normalize success: /data_lake/normalized/shelter.geojson',
  '[2026-04-05T10:00:06Z] === pipeline completed successfully ===',
];

const CONFIG_ITEMS = [
  {
    key: 'logging.level',
    category: 'system',
    label: 'ログレベル',
    type: 'string',
    default_value: 'INFO',
    current_value: 'INFO',
    description: 'Logs タブとバックエンドの出力量を制御します。',
    options: ['DEBUG', 'INFO', 'WARNING', 'ERROR'],
    editable: true,
    apply_mode: 'reload',
    ui_order: 500,
    updated_at: null,
  },
  {
    key: 'navigation.arrival_distance_m',
    category: 'navigation',
    label: '到着判定距離',
    type: 'integer',
    default_value: 12,
    current_value: 12,
    description: '目的地またはルート終端からこの距離以内を到着候補とします。',
    min: 1,
    max: 50,
    editable: true,
    apply_mode: 'reload',
    ui_order: 10,
    updated_at: null,
  },
  {
    key: 'navigation.near_goal_off_route_distance_m',
    category: 'navigation',
    label: '目的地近傍逸脱判定距離',
    type: 'integer',
    default_value: 18,
    current_value: 18,
    description: '目的地近傍でルート逸脱候補とする距離です。',
    min: 5,
    max: 50,
    editable: true,
    apply_mode: 'reload',
    ui_order: 40,
    updated_at: '2026-04-23T10:00:00Z',
  },
];

const CONFIG_HISTORY = [
  {
    key: 'navigation.arrival_distance_m',
    old_value: 15,
    new_value: 12,
    updated_at: '2026-04-23T10:00:00Z',
  },
];

const LOG_SOURCES = [
  { key: 'app', label: 'Application' },
  { key: 'jobs', label: 'Jobs' },
];

const LOG_LINES_BY_SOURCE = {
  app: [
    '[2026-04-24T09:00:00Z] [navigation] dist_to_goal=18.4m accuracy=12.0m arrival_counter=1 arrived=false',
    '[2026-04-24T09:00:02Z] [navigation] reroute:start reason=off_route near_goal=true',
  ],
  jobs: [
    '[2026-04-24T09:01:00Z] job=deploy-job-001 status=queued',
    '[2026-04-24T09:01:04Z] job=deploy-job-001 status=success',
  ],
};

// ── URL: テストサーバーは .html 拡張子が必要 ─────────────────
const PAGE_URL = '/admin/datasets.html';

// ── 共通モックセットアップ ─────────────────────────────────

async function setupBasicMocks(page, datasets = ALL_DATASETS) {
  await page.route('/api/admin/layer-types', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { layer_type: 'shelter', display_name: '避難場所', sort_order: 10 },
        { layer_type: 'flood', display_name: '洪水浸水想定', sort_order: 20 },
        { layer_type: 'osm', display_name: '道路ネットワーク', sort_order: 90 },
      ]),
    })
  );
  // datasets 一覧
  await page.route(/\/api\/admin\/datasets(\?.*)?$/, route => {
    if (route.request().method() === 'GET') {
      const url = new URL(route.request().url());
      const region = url.searchParams.get('region');
      const layerType = url.searchParams.get('layer_type');
      const filtered = datasets.filter(d =>
        (!region || d.region === region) &&
        (!layerType || d.layer_type === layerType || d.category === layerType)
      );
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(filtered) });
    } else {
      route.continue();
    }
  });
  // datasets 詳細（SHELTER-001）
  await page.route('/api/admin/datasets/TOKYO-SHELTER-001', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SHELTER_DETAIL) })
  );
  // jobs 一覧
  await page.route('/api/admin/jobs', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([JOB_SUCCESS]) })
  );
  // job 詳細
  await page.route('/api/admin/jobs/**', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_SUCCESS) })
  );
  await page.route('/api/admin/config', route => {
    if (route.request().method() === 'GET') {
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CONFIG_ITEMS) });
    } else {
      route.continue();
    }
  });
  await page.route('/api/admin/config/history', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CONFIG_HISTORY) })
  );
  await page.route('/api/admin/logs/sources', route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(LOG_SOURCES) })
  );
  await page.route(/\/api\/admin\/logs\?source=.*$/, route => {
    const url = new URL(route.request().url());
    const source = url.searchParams.get('source') || 'app';
    if (!LOG_LINES_BY_SOURCE[source]) {
      route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: `invalid source: ${source}` }) });
      return;
    }
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ lines: LOG_LINES_BY_SOURCE[source] }),
    });
  });
  await page.route('/api/admin/config/**', async route => {
    if (route.request().method() === 'GET' && route.request().url().endsWith('/api/admin/config/history')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(CONFIG_HISTORY) });
      return;
    }
    if (route.request().method() !== 'PUT') {
      await route.continue();
      return;
    }
    const body = route.request().postDataJSON();
    if (Number(body.value) > 50) {
      await route.fulfill({ status: 400, contentType: 'application/json', body: JSON.stringify({ detail: '50 以下の値を入力してください。' }) });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        key: 'navigation.arrival_distance_m',
        old_value: 12,
        new_value: body.value,
        updated_at: '2026-04-23T10:10:00Z',
        item: { ...CONFIG_ITEMS[0], current_value: body.value, updated_at: '2026-04-23T10:10:00Z' },
      }),
    });
  });
}

async function installMockEventSource(page) {
  await page.addInitScript(() => {
    const eventSources = [];

    class MockEventSource {
      constructor(url) {
        this.url = url;
        this.readyState = 0;
        this.closed = false;
        this.listeners = {};
        this.onopen = null;
        this.onerror = null;
        eventSources.push(this);
        setTimeout(() => {
          if (this.closed) return;
          this.readyState = 1;
          const evt = { type: 'open' };
          if (typeof this.onopen === 'function') this.onopen(evt);
          (this.listeners.open || []).forEach(listener => listener(evt));
        }, 0);
      }

      addEventListener(type, listener) {
        if (!this.listeners[type]) {
          this.listeners[type] = [];
        }
        this.listeners[type].push(listener);
      }

      close() {
        this.readyState = 2;
        this.closed = true;
      }

      dispatch(type, data) {
        const evt = data === undefined ? { type } : { type, data: JSON.stringify(data) };
        if (type === 'error' && typeof this.onerror === 'function') {
          this.onerror(evt);
        }
        (this.listeners[type] || []).forEach(listener => listener(evt));
      }
    }

    window.EventSource = MockEventSource;
    window.__eventSources = eventSources;
    window.__emitEventSourceEvent = (index, type, data) => {
      const eventSource = eventSources[index];
      if (eventSource) {
        eventSource.dispatch(type, data);
      }
    };
    window.__eventSourceState = index => {
      const eventSource = eventSources[index];
      if (!eventSource) return null;
      return {
        url: eventSource.url,
        readyState: eventSource.readyState,
        closed: eventSource.closed,
      };
    };
  });
}

// コンソールエラーを収集するヘルパー
function collectConsoleErrors(page) {
  const errors = [];
  page.on('console', msg => {
    if (msg.type() === 'error') errors.push(msg.text());
  });
  page.on('pageerror', err => errors.push(err.message));
  return errors;
}

// ════════════════════════════════════════════════════════════
//  1. 初期表示
// ════════════════════════════════════════════════════════════

test.describe('1. 初期表示', () => {
  test('ページタイトルが正しい', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await expect(page).toHaveTitle(/データ管理/);
  });

  test('ヘッダーにシステム名が表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await expect(page.locator('.admin-header h1')).toContainText('OnHighGround2');
  });

  test('データセット一覧が表示される（4件モック）', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    // テーブル行が4件 (+ ヘッダー行) 表示されるまで待つ
    await expect(page.locator('#datasets-tbody tr')).toHaveCount(4, { timeout: 5000 });
  });

  test('各行にデータセットIDが表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await expect(page.locator('text=TOKYO-SHELTER-001')).toBeVisible();
    await expect(page.locator('text=TOKYO-RIVER-001')).toBeVisible();
    await expect(page.locator('text=TOKYO-URBAN-001')).toBeVisible();
    await expect(page.locator('text=TOKYO-ROAD-001')).toBeVisible();
  });

  test('ヒントアイコン（?）が各行に表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const hints = page.locator('.hint-icon');
    await expect(hints).toHaveCount(4);
  });

  test('コンソールエラーが発生しない（初期表示）', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.waitForTimeout(500);
    expect(errors).toHaveLength(0);
  });
});

// ════════════════════════════════════════════════════════════
//  2. 一覧/詳細の整合性
// ════════════════════════════════════════════════════════════

test.describe('2. 一覧/詳細の整合性', () => {
  test('「詳細」ボタンクリックで詳細パネルが開く', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await expect(page.locator('text=TOKYO-SHELTER-001')).toBeVisible();
    // SHELTER-001 行の詳細ボタンをクリック
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("詳細")').click();
    await expect(page.locator('#detail-panel')).toHaveClass(/visible/);
  });

  test('詳細パネルにデータ名が表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("詳細")').click();
    await expect(page.locator('#detail-title')).toContainText('指定緊急避難場所');
  });

  test('詳細パネルに現在ファイル名が表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("詳細")').click();
    await expect(page.locator('#detail-status')).toContainText('tokyo_shelter.geojson');
  });

  test('詳細パネルに履歴が表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("詳細")').click();
    await expect(page.locator('#detail-history')).toContainText('反映');
  });

  test('「×」ボタンで詳細パネルが閉じる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("詳細")').click();
    await expect(page.locator('#detail-panel')).toHaveClass(/visible/);
    await page.locator('.detail-header .close-btn').click();
    await expect(page.locator('#detail-panel')).not.toHaveClass(/visible/);
  });

  test('詳細にバックアップあり表示が出る（backup_path あり）', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("詳細")').click();
    await expect(page.locator('#detail-status')).toContainText('ロールバック可');
  });
});

// ════════════════════════════════════════════════════════════
//  3. 更新モーダル
// ════════════════════════════════════════════════════════════

test.describe('3. 更新モーダル', () => {
  test('「更新」ボタンクリックでモーダルが開く', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("更新")').click();
    await expect(page.locator('#update-modal')).toHaveClass(/open/);
  });

  test('SHELTER-001: upload/URL/公式 の3タブが表示される', async ({ page }) => {
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SHELTER_DETAIL) })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("更新")').click();
    await page.waitForTimeout(300); // 詳細API取得を待つ
    await expect(page.locator('#tab-btn-upload')).toBeVisible();
    await expect(page.locator('#tab-btn-fetch_url')).toBeVisible();
    await expect(page.locator('#tab-btn-fetch_official')).toBeVisible();
  });

  test('OSM(ROAD-001): upload タブが表示されない', async ({ page }) => {
    const osmDetail = {
      ...SHELTER_DETAIL,
      definition: {
        ...SHELTER_DETAIL.definition,
        dataset_id: 'TOKYO-ROAD-001',
        display_name: '道路ネットワーク（OSM・関東）',
        accepted_input_modes: ['fetch_url', 'fetch_official'],
        max_browser_upload_mb: 0,
      },
      state: { ...SHELTER_DETAIL.state, dataset_id: 'TOKYO-ROAD-001' },
    };
    await page.route('/api/admin/datasets/TOKYO-ROAD-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(osmDetail) })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-ROAD-001') });
    await row.locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);
    await expect(page.locator('#tab-btn-upload')).not.toBeVisible();
    await expect(page.locator('#upload-disabled-notice')).toBeVisible();
  });

  test('URL タブ切り替えで URL 入力欄が表示される', async ({ page }) => {
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SHELTER_DETAIL) })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);
    await page.locator('#tab-btn-fetch_url').click();
    await expect(page.locator('#fetch-url-input')).toBeVisible();
  });

  test('「キャンセル」でモーダルが閉じる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("更新")').click();
    await expect(page.locator('#update-modal')).toHaveClass(/open/);
    await page.locator('#update-modal .modal-close').click();
    await expect(page.locator('#update-modal')).not.toHaveClass(/open/);
  });
});

// ════════════════════════════════════════════════════════════
//  4. ingest / deploy / rollback / osrm 受付
// ════════════════════════════════════════════════════════════

test.describe('4. ジョブ受付', () => {
  test('URL取得: ジョブ受付成功 → 通知が出る', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SHELTER_DETAIL) })
    );
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001/fetch-url', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ accepted: true, job_id: 'new-job-001', message: 'URL取得を受け付けました。' }),
      })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);

    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);
    await page.locator('#tab-btn-fetch_url').click();
    await page.locator('#fetch-url-input').fill('https://example.com/shelter.geojson');
    await page.locator('#um-execute-btn').click();

    // 成功通知が表示される
    await expect(page.locator('#notice-bar.success')).toBeVisible({ timeout: 3000 });
    // モーダルが閉じる
    await expect(page.locator('#update-modal')).not.toHaveClass(/open/);
    expect(errors).toHaveLength(0);
  });

  test('URL 未入力で実行 → エラー通知が出る', async ({ page }) => {
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SHELTER_DETAIL) })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("更新")').click();
    await page.waitForTimeout(300);
    await page.locator('#tab-btn-fetch_url').click();
    // URL を入力せずに実行
    await page.locator('#um-execute-btn').click();
    await expect(page.locator('#notice-bar.error')).toBeVisible();
  });

  test('反映確認モーダル: 「反映」ボタンでジョブ受付 → 通知', async ({ page }) => {
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001/deploy', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ accepted: true, job_id: 'deploy-job-001', message: '反映を開始しました。' }),
      })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("反映")').click();
    await expect(page.locator('#deploy-modal')).toHaveClass(/open/);
    await page.locator('#deploy-modal button:has-text("反映する")').click();
    await expect(page.locator('#notice-bar.success')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('#deploy-modal')).not.toHaveClass(/open/);
  });

  test('ロールバック確認モーダル: 「1世代前に戻す」でジョブ受付', async ({ page }) => {
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001/rollback', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ accepted: true, job_id: 'rollback-job-001', message: 'ロールバックを開始しました。' }),
      })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("戻す")').click();
    await expect(page.locator('#rollback-modal')).toHaveClass(/open/);
    await page.locator('#rollback-modal button:has-text("1世代前に戻す")').click();
    await expect(page.locator('#notice-bar.success')).toBeVisible({ timeout: 3000 });
  });

  test('OSRM確認モーダル: 「再構築する」でジョブ受付', async ({ page }) => {
    await page.route('/api/admin/datasets/TOKYO-ROAD-001/rebuild-osrm', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ accepted: true, job_id: 'osrm-job-001', message: '再構築を開始しました。' }),
      })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-ROAD-001') });
    await row.locator('button:has-text("OSRM")').click();
    await expect(page.locator('#osrm-modal')).toHaveClass(/open/);
    await page.locator('#osrm-modal button:has-text("再構築する")').click();
    await expect(page.locator('#notice-bar.success')).toBeVisible({ timeout: 3000 });
  });
});

// ════════════════════════════════════════════════════════════
//  5. 実行中の二重押下防止
// ════════════════════════════════════════════════════════════

test.describe('5. 二重押下防止', () => {
  test('has_running_job=true の行: 更新・反映・戻す が disabled', async ({ page }) => {
    const runningDatasets = [
      DATASET_RUNNING,
      DATASET_NOT_VALIDATED,
      DATASET_NO_DATA,
      DATASET_OSM,
    ];
    // NOTE: Playwright は後から登録したルートが優先される。
    // setupBasicMocks より後に登録したルートが使われるので、先に setupBasicMocks を呼ぶ。
    await setupBasicMocks(page, runningDatasets);
    await page.goto(PAGE_URL);

    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await expect(row.locator('button:has-text("更新")')).toBeDisabled();
    await expect(row.locator('button:has-text("反映")')).toBeDisabled();
    await expect(row.locator('button:has-text("戻す")')).toBeDisabled();
  });

  test('API から JOB_ALREADY_RUNNING エラーが来たらエラー通知表示', async ({ page }) => {
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001/deploy', route =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          accepted: false,
          error_code: 'JOB_ALREADY_RUNNING',
          user_message: 'このデータセットでは現在別の処理が実行中です。',
          action_message: '処理が完了してから再実行してください。',
        }),
      })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("反映")').click();
    await page.locator('#deploy-modal button:has-text("反映する")').click();
    await expect(page.locator('#notice-bar.error')).toBeVisible({ timeout: 3000 });
    await expect(page.locator('#notice-bar')).toContainText('処理が実行中');
  });
});

// ════════════════════════════════════════════════════════════
//  6. ジョブログモーダル / ポーリング
// ════════════════════════════════════════════════════════════

test.describe('6. ジョブログモーダル', () => {
  test('「ログ」ボタンでジョブログモーダルが開く', async ({ page }) => {
    await setupBasicMocks(page);
    // last_job_id を持つ行のため job 詳細を返す
    await page.route('/api/admin/jobs/job-shelter-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_SUCCESS) })
    );
    await page.route('/api/admin/jobs/job-shelter-001/log', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'job-shelter-001', lines: LOG_LINES, total_lines: LOG_LINES.length }),
      })
    );
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("ログ")').click();
    await expect(page.locator('#log-modal')).toHaveClass(/open/);
  });

  test('ログモーダル: ジョブIDが表示される', async ({ page }) => {
    // job-shelter-001 に一致するフィクスチャを使う
    const shelterJob = { ...JOB_SUCCESS, job_id: 'job-shelter-001' };
    await setupBasicMocks(page);
    await page.route('/api/admin/jobs/job-shelter-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(shelterJob) })
    );
    await page.route('/api/admin/jobs/job-shelter-001/log', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'job-shelter-001', lines: LOG_LINES, total_lines: LOG_LINES.length }),
      })
    );
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("ログ")').click();
    // JS側で substring(0,8)+"..." に切り詰めるため 'job-shel...' になる
    await expect(page.locator('#lm-job-id')).toContainText('job-shel');
  });

  test('ログモーダル: ログ行が表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.route('/api/admin/jobs/job-shelter-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_SUCCESS) })
    );
    await page.route('/api/admin/jobs/job-shelter-001/log', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'job-shelter-001', lines: LOG_LINES, total_lines: LOG_LINES.length }),
      })
    );
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("ログ")').click();
    await expect(page.locator('#lm-log-area')).toContainText('pipeline completed');
  });

  test('ログモーダル: 「閉じる」でモーダルが閉じる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.route('/api/admin/jobs/job-shelter-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(JOB_SUCCESS) })
    );
    await page.route('/api/admin/jobs/job-shelter-001/log', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'job-shelter-001', lines: [], total_lines: 0 }),
      })
    );
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("ログ")').click();
    await page.locator('#log-modal .modal-close').click();
    await expect(page.locator('#log-modal')).not.toHaveClass(/open/);
  });

  test('ジョブ完了後: 自動更新が停止する（status=success）', async ({ page }) => {
    // 最初は running、次のポーリングで success に変わることをシミュレート
    let callCount = 0;
    await page.route('/api/admin/datasets', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(ALL_DATASETS) })
    );
    await page.route('/api/admin/jobs/job-shelter-001', route => {
      callCount++;
      const job = callCount < 2 ? JOB_RUNNING : JOB_SUCCESS;
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(job) });
    });
    await page.route('/api/admin/jobs/job-shelter-001/log', route =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: 'job-shelter-001', lines: LOG_LINES, total_lines: 5 }),
      })
    );
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SHELTER_DETAIL) })
    );
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("ログ")').click();

    // 数秒待って「自動更新 OFF」に変わることを確認
    await expect(page.locator('#log-auto-label')).toContainText('OFF', { timeout: 10000 });
  });
});

// ════════════════════════════════════════════════════════════
//  7. 失敗時のエラー表示
// ════════════════════════════════════════════════════════════

test.describe('7. 失敗時エラー表示', () => {
  test('詳細パネル: last_job が failed の場合エラーセクションが表示される', async ({ page }) => {
    const failedDetail = {
      ...SHELTER_DETAIL,
      last_job: JOB_FAILED,
      state: { ...SHELTER_DETAIL.state, normalize_status: 'failed', validation_status: 'not_started' },
    };
    // setupBasicMocks を先に呼び、その後に詳細ルートを上書き登録する（後勝ちのため）
    await setupBasicMocks(page);
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(failedDetail) })
    );
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("詳細")').click();
    // エラーセクションが表示される
    await expect(page.locator('#detail-error-section')).toBeVisible();
    await expect(page.locator('#detail-error')).toContainText('NORMALIZE_FAILED');
    await expect(page.locator('#detail-error')).toContainText('データの整形処理に失敗しました');
    await expect(page.locator('#detail-error')).toContainText('入力ファイルの形式が正しいか確認');
  });

  test('DEPLOY_BLOCKED_VALIDATION_FAILED エラーが人向けメッセージで表示される', async ({ page }) => {
    await page.route('/api/admin/datasets/TOKYO-SHELTER-001/deploy', route =>
      route.fulfill({
        status: 400,
        contentType: 'application/json',
        body: JSON.stringify({
          accepted: false,
          error_code: 'DEPLOY_BLOCKED_VALIDATION_FAILED',
          user_message: '内容確認（バリデーション）が完了していないため、反映できません。',
          action_message: '先にデータの取り込みと内容確認を完了させてください。',
        }),
      })
    );
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("反映")').click();
    await page.locator('#deploy-modal button:has-text("反映する")').click();
    // 非エンジニア向けのメッセージで表示される（技術用語 "VALIDATION" だけでなく日本語も含む）
    await expect(page.locator('#notice-bar')).toContainText('内容確認');
  });

  test('ネットワークエラー時もクラッシュせずエラー通知が出る', async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await page.route('/api/admin/layer-types', route =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' })
    );
    await page.route('/api/admin/datasets', route => route.abort('failed'));
    await page.goto(PAGE_URL);
    await page.waitForTimeout(1000);
    await expect(page.locator('#notice-bar.error')).toBeVisible({ timeout: 3000 });
    // JS クラッシュがないこと
    expect(errors.filter(e => !e.includes('net::ERR'))).toHaveLength(0);
  });
});

// ════════════════════════════════════════════════════════════
//  8. 画面再読み込み後の整合性
// ════════════════════════════════════════════════════════════

test.describe('8. 画面再読み込み', () => {
  test('再読み込み後も一覧が正しく表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await expect(page.locator('#datasets-tbody tr')).toHaveCount(4, { timeout: 5000 });
    await page.reload();
    await expect(page.locator('#datasets-tbody tr')).toHaveCount(4, { timeout: 5000 });
  });

  test('再読み込み後: 詳細パネルは閉じている', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await row.locator('button:has-text("詳細")').click();
    await expect(page.locator('#detail-panel')).toHaveClass(/visible/);
    await page.reload();
    await expect(page.locator('#detail-panel')).not.toHaveClass(/visible/);
  });
});

// ════════════════════════════════════════════════════════════
//  9. ボタン活性/非活性条件
// ════════════════════════════════════════════════════════════

test.describe('9. ボタン活性/非活性条件', () => {
  test('validation_status=pass かつ実行中ジョブなし → 反映ボタンが有効', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await expect(row.locator('button:has-text("反映")')).toBeEnabled();
  });

  test('validation_status=not_started → 反映ボタンが無効', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-RIVER-001') });
    await expect(row.locator('button:has-text("反映")')).toBeDisabled();
  });

  test('storage_status=none → 反映ボタンが無効', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-URBAN-001') });
    await expect(row.locator('button:has-text("反映")')).toBeDisabled();
  });

  test('deploy_status=deployed かつ実行中ジョブなし → 「戻す」が有効', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await expect(row.locator('button:has-text("戻す")')).toBeEnabled();
  });

  test('storage_status=none → 「戻す」が無効', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-URBAN-001') });
    await expect(row.locator('button:has-text("戻す")')).toBeDisabled();
  });

  test('requires_osrm_rebuild=true かつ deployed → OSRM ボタンが有効', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-ROAD-001') });
    await expect(row.locator('button:has-text("OSRM")')).toBeEnabled();
  });

  test('requires_osrm_rebuild=false の行 → OSRM ボタンが存在しない', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await expect(row.locator('button:has-text("OSRM")')).toHaveCount(0);
  });

  test('地域フィルター: "tokyo" で全件表示', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#region-filter').selectOption('tokyo');
    // モック全件が tokyo なので4件のまま
    await expect(page.locator('#datasets-tbody tr')).toHaveCount(4);
  });

  test('種別フィルター: "shelter" で1件に絞り込まれる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#layer-type-filter').selectOption('shelter');
    await expect(page.locator('#datasets-tbody tr')).toHaveCount(1);
    await expect(page.locator('text=TOKYO-SHELTER-001')).toBeVisible();
  });
});

// ════════════════════════════════════════════════════════════
//  10. バッジ表示の正確性
// ════════════════════════════════════════════════════════════

test.describe('10. バッジ表示', () => {
  test('validation_status=pass → 「確認済」バッジ表示', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await expect(row.locator('.badge-pass')).toBeVisible();
    await expect(row.locator('.badge-pass')).toContainText('確認済');
  });

  test('validation_status=not_started → 「未確認」バッジ表示', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-RIVER-001') });
    await expect(row.locator('td').nth(9)).toContainText('未確認');
  });

  test('deploy_status=deployed → 「反映済」バッジ表示', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-SHELTER-001') });
    await expect(row.locator('.badge-success').filter({ hasText: '反映済' })).toBeVisible();
  });

  test('storage_status=none → 「未取込」バッジ表示', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-URBAN-001') });
    await expect(row.locator('.badge-none')).toContainText('未取込');
  });

  test('osrm_rebuild_status=success → 「構築済」バッジ表示', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    const row = page.locator('tr', { has: page.locator('text=TOKYO-ROAD-001') });
    await expect(row.locator('.badge-success').filter({ hasText: '構築済' })).toBeVisible();
  });
});

// ════════════════════════════════════════════════════════════
//  11. Config タブ
// ════════════════════════════════════════════════════════════

test.describe('11. Config タブ', () => {
  test('Config タブで設定一覧が表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-config').click();

    await expect(page.locator('#tab-panel-config')).toHaveClass(/active/);
    await expect(page.locator('#config-tbody')).toContainText('到着判定距離');
    await expect(page.locator('#config-tbody')).toContainText('navigation.arrival_distance_m');
  });

  test('Config を編集して保存できる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-config').click();

    const input = page.locator('#config-input-navigation-arrival_distance_m');
    await input.fill('14');
    await page.locator('tr[data-config-key="navigation.arrival_distance_m"] button').click();

    await expect(page.locator('#notice-bar')).toContainText('設定を保存しました');
  });

  test('ログレベル設定は select で編集できる', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-config').click();

    const input = page.locator('#config-input-logging-level');
    await expect(input).toBeVisible();
    await input.selectOption('ERROR');
    await page.locator('tr[data-config-key="logging.level"] button').click();

    await expect(page.locator('#notice-bar')).toContainText('設定を保存しました');
  });

  test('Config の範囲外値はエラー表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-config').click();

    const input = page.locator('#config-input-navigation-arrival_distance_m');
    await input.fill('100');
    await page.locator('tr[data-config-key="navigation.arrival_distance_m"] button').click();

    await expect(page.locator('#notice-bar')).toContainText('設定の保存に失敗しました');
    await expect(page.locator('#config-status-navigation-arrival_distance_m')).toContainText('50 以下');
  });

  test('Config 履歴モーダルが表示される', async ({ page }) => {
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-config').click();
    await page.getByRole('button', { name: '履歴を見る' }).click();

    await expect(page.locator('#config-history-modal')).toHaveClass(/open/);
    await expect(page.locator('#config-history-list')).toContainText('navigation.arrival_distance_m');
  });

});

// ════════════════════════════════════════════════════════════
//  12. Logs タブ
// ════════════════════════════════════════════════════════════

test.describe('12. Logs タブ', () => {
  test('Logs タブで初期ログとソース一覧が表示される', async ({ page }) => {
    await installMockEventSource(page);
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-logs').click();

    await expect(page.locator('#tab-panel-logs')).toHaveClass(/active/);
    await expect(page.locator('#logs-source-select')).toHaveValue('app');
    await expect(page.locator('#logs-viewer')).toContainText('dist_to_goal=18.4m');
    await expect(page.locator('#logs-line-count')).toContainText('2 / 1000 lines');
  });

  test('ソース切替でログ一覧が切り替わる', async ({ page }) => {
    await installMockEventSource(page);
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-logs').click();

    await page.locator('#logs-source-select').selectOption('jobs');
    await expect(page.locator('#logs-viewer')).toContainText('job=deploy-job-001 status=success');
    await expect(page.locator('#logs-source-meta')).toContainText('source: jobs');
  });

  test('接続と切断で状態表示が切り替わる', async ({ page }) => {
    await installMockEventSource(page);
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-logs').click();

    await expect(page.locator('#logs-connection-status')).toContainText('接続中');
    await expect(page.locator('#logs-connect-btn')).toBeDisabled();
    await page.locator('#logs-disconnect-btn').click();
    await expect(page.locator('#logs-connection-status')).toContainText('未接続');
    await expect(page.locator('#logs-connect-btn')).toBeEnabled();
  });

  test('SSE で新しいログ行が追加される', async ({ page }) => {
    await installMockEventSource(page);
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-logs').click();
    await expect(page.locator('#logs-connection-status')).toContainText('接続中');

    await page.evaluate(() => {
      window.__emitEventSourceEvent(0, 'log', {
        line: '[2026-04-24T09:00:03Z] [navigation] reroute:success duration_ms=842',
        ts: '2026-04-24T09:00:03Z',
      });
    });

    await expect(page.locator('#logs-viewer')).toContainText('reroute:success duration_ms=842');
    await expect(page.locator('#logs-line-count')).toContainText('3 / 1000 lines');
  });

  test('最大1000行を超えると先頭から間引かれる', async ({ page }) => {
    await installMockEventSource(page);
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-logs').click();
    await expect(page.locator('#logs-connection-status')).toContainText('接続中');

    await page.evaluate(() => {
      for (let i = 0; i < 1105; i += 1) {
        window.__emitEventSourceEvent(0, 'log', {
          line: `bulk-line-${i}`,
          ts: '2026-04-24T09:00:03Z',
        });
      }
    });

    await expect(page.locator('#logs-line-count')).toContainText('1000 / 1000 lines');
    await expect(page.locator('#logs-viewer')).toContainText('bulk-line-1104');
    await expect(page.locator('#logs-viewer')).not.toContainText('bulk-line-0');
  });

  test('クリアで表示行が消え、再接続で source を維持できる', async ({ page }) => {
    await installMockEventSource(page);
    await setupBasicMocks(page);
    await page.goto(PAGE_URL);
    await page.locator('#tab-btn-logs').click();
    await page.locator('#logs-source-select').selectOption('jobs');

    await page.locator('#logs-clear-btn').click();
    await expect(page.locator('#logs-viewer')).toContainText('ログがありません');
    await expect(page.locator('#logs-line-count')).toContainText('0 / 1000 lines');

    await page.locator('#logs-disconnect-btn').click();
    await page.locator('#logs-connect-btn').click();
    const sourceState = await page.evaluate(() => window.__eventSourceState(1));
    expect(sourceState.url).toContain('/api/admin/logs/stream?source=jobs');
  });
});

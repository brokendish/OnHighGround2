// playwright.config.js
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  globalSetup:    './e2e/helpers/global-setup.js',
  globalTeardown: './e2e/helpers/global-teardown.js',
  testDir: './e2e',
  timeout: 30_000,
  // 各テストは独立して実行（並列OFF: ローカル http.server と競合しないよう）
  workers: 1,
  // CI での失敗時に自動リトライ
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { open: 'never' }]],

  use: {
    // frontend/ を python -m http.server で配信する想定
    // ポートは e2e/helpers/server.js で起動するローカルサーバーに合わせる
    baseURL: 'http://127.0.0.1:8787',
    headless: true,
    // 東京湾・有明北部サンプル座標（フィールドテスト代表点）
    geolocation: { latitude: 35.6415, longitude: 139.7905 },
    permissions: ['geolocation'],
    locale: 'ja-JP',
    viewport: { width: 1440, height: 900 },
    // ネットワーク失敗は即エラー（モックテストで意図しない外部通信を防ぐ）
    // page.route() を使う個別テストでのみ上書き可
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});

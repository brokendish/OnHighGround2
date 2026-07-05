#!/usr/bin/env node
'use strict';

// /live/stream — Stream Phase 6-A: OBS実配信リハーサル用の長時間監視probe。
//
// OBS実機の代替ではない。Playwright(Chromium)で本番想定URLを一定時間表示し続け、
// 一定間隔で window.__LiveStreamDiagnostics.getSnapshot() 等の状態をJSON/スクリーンショットに
// 記録する。長時間soak・OBS実機・YouTube配信リハーサルの前段の機械的チェックに使う。
//
// 使用例:
//   node tools/live_stream_obs_rehearsal_probe.js \
//     --url "http://127.0.0.1:8080/live/stream?chrome=off" \
//     --minutes 30 \
//     --interval 300 \
//     --output test-results/live-stream-phase6a-obs-rehearsal-diagnostics.json \
//     --screenshot-dir test-results
//
// 環境変数でも指定可能 (引数が優先): URL, DURATION_MINUTES, SAMPLE_INTERVAL_SECONDS,
// OUTPUT_JSON, SCREENSHOT_DIR

const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith('--')) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next !== undefined && !next.startsWith('--')) { out[key] = next; i++; }
    else out[key] = true;
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const URL = args.url || process.env.URL || 'http://127.0.0.1:8080/live/stream?chrome=off';
const DURATION_MINUTES = Number(args.minutes || process.env.DURATION_MINUTES || 10);
const SAMPLE_INTERVAL_SECONDS = Number(args.interval || process.env.SAMPLE_INTERVAL_SECONDS || 300);
const OUTPUT_JSON = args.output || process.env.OUTPUT_JSON
  || 'test-results/live-stream-obs-rehearsal-probe.json';
const SCREENSHOT_DIR = args['screenshot-dir'] || process.env.SCREENSHOT_DIR || 'test-results';

// 本番配信画面に個人情報/APIキー/トークンの類が誤って露出していないかの簡易スキャン。
// マッチした値そのものは記録しない (それ自体が漏洩経路になるため)。パターン名と有無だけを残す。
const BAD_TOKEN_PATTERNS = [
  { name: 'apiKeyLike',   re: /api[_-]?key\s*[:=]\s*['"]?[A-Za-z0-9_\-]{8,}/i },
  { name: 'secretLike',   re: /secret\s*[:=]\s*['"]?[A-Za-z0-9_\-]{8,}/i },
  { name: 'bearerToken',  re: /Bearer\s+[A-Za-z0-9._\-]{10,}/ },
  { name: 'passwordLike', re: /password\s*[:=]\s*['"]?\S{4,}/i },
];

function scanBadTokens(html) {
  const result = {};
  for (const p of BAD_TOKEN_PATTERNS) result[p.name] = p.re.test(html);
  return result;
}

async function takeSnapshot(page, label) {
  const diagnostics = await page.evaluate(() => (
    window.__LiveStreamDiagnostics ? window.__LiveStreamDiagnostics.getSnapshot() : null
  ));
  const bodyAttrs = await page.evaluate(() => Object.assign({}, document.body.dataset));
  const leafletContainerCount = await page.locator('.leaflet-container').count();
  const tickerTextNodes = await page.locator('.ls-ticker .move > *').count();
  const railwayLayerCount = diagnostics && diagnostics.railwayLayer ? diagnostics.railwayLayer.layerCount : null;
  const markerCount = diagnostics ? diagnostics.markerCount : null;
  const html = await page.content();
  const badTokenScan = scanBadTokens(html);

  const screenshotPath = path.join(SCREENSHOT_DIR, `live-stream-phase6a-probe-${label}.png`);
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({ path: screenshotPath });

  return {
    label,
    timestamp: new Date().toISOString(),
    bodyAttrs,
    leafletContainerCount,
    tickerTextNodes,
    railwayLayerCount,
    markerCount,
    diagnostics,
    badTokenScan,
    screenshotPath,
  };
}

async function main() {
  const pageErrors = [];
  const consoleErrors = [];
  const requestFailed = [];

  const browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await context.newPage();

  page.on('pageerror', e => pageErrors.push({ timestamp: new Date().toISOString(), message: e.message || String(e) }));
  page.on('console', m => {
    if (m.type() === 'error') consoleErrors.push({ timestamp: new Date().toISOString(), text: m.text() });
  });
  page.on('requestfailed', r => requestFailed.push({
    timestamp: new Date().toISOString(),
    url: r.url(),
    failure: r.failure() ? r.failure().errorText : null,
  }));

  console.log(`[obs-rehearsal-probe] navigating to ${URL}`);
  await page.goto(URL, { waitUntil: 'domcontentloaded' });

  const samples = [];
  samples.push(await takeSnapshot(page, 'start'));

  const totalSeconds = DURATION_MINUTES * 60;
  let elapsed = 0;
  while (elapsed < totalSeconds) {
    const wait = Math.min(SAMPLE_INTERVAL_SECONDS, totalSeconds - elapsed);
    await page.waitForTimeout(wait * 1000);
    elapsed += wait;
    const label = `t${Math.round(elapsed / 60)}min`;
    console.log(`[obs-rehearsal-probe] sampling at ${label} (${elapsed}/${totalSeconds}s)`);
    samples.push(await takeSnapshot(page, label));
  }

  await browser.close();

  const result = {
    url: URL,
    durationMinutes: DURATION_MINUTES,
    sampleIntervalSeconds: SAMPLE_INTERVAL_SECONDS,
    startedAt: samples[0] ? samples[0].timestamp : null,
    finishedAt: new Date().toISOString(),
    summary: {
      pageErrorCount: pageErrors.length,
      consoleErrorCount: consoleErrors.length,
      requestFailedCount: requestFailed.length,
      failedToFetchCount: consoleErrors.filter(e => e.text.includes('TypeError: Failed to fetch')).length,
      leafletContainerCounts: samples.map(s => s.leafletContainerCount),
      tickerTextNodeCounts: samples.map(s => s.tickerTextNodes),
      railwayLayerCounts: samples.map(s => s.railwayLayerCount),
      markerCounts: samples.map(s => s.markerCount),
    },
    pageErrors,
    consoleErrors,
    requestFailed,
    samples,
  };

  fs.mkdirSync(path.dirname(OUTPUT_JSON), { recursive: true });
  fs.writeFileSync(OUTPUT_JSON, JSON.stringify(result, null, 2));
  console.log(`[obs-rehearsal-probe] wrote ${OUTPUT_JSON}`);
  console.log(`[obs-rehearsal-probe] pageerror=${pageErrors.length} consoleError=${consoleErrors.length} requestFailed=${requestFailed.length}`);
}

main().catch(e => {
  console.error('[obs-rehearsal-probe] failed:', e);
  process.exit(1);
});

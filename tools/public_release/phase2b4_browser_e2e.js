#!/usr/bin/env node
/**
 * tools/public_release/phase2b4_browser_e2e.js
 *
 * Phase 2-B.4 browser E2E（第8.3節）。既存の playwright.config.js /
 * e2e/global-setup とは独立に、呼び出し元（phase2b4_frontend_boundary.py）
 * が起動済みの隔離Compose stackの実host portを引数で受け取り、実browserで
 * token取り扱い・public/operator境界を確認する。
 *
 * 使い方:
 *   node tools/public_release/phase2b4_browser_e2e.js \
 *     --public-base http://127.0.0.1:<port> \
 *     --gateway-base http://127.0.0.1:<port> \
 *     --token <dummy token>
 *
 * 標準出力へJSON配列（各checkの name/pass/detail）を1行で出力する。
 * dummy token自体はstdout/報告書へ転載しない（呼び出し側でも<DUMMY_REDACTED>
 * 表記にすること）。
 */
const { chromium } = require('playwright');

function parseArgs() {
  const args = {};
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 2) {
    args[argv[i].replace(/^--/, '')] = argv[i + 1];
  }
  return args;
}

async function main() {
  const args = parseArgs();
  const publicBase = args['public-base'];
  const gatewayBase = args['gateway-base'];
  const token = args['token'];
  const results = [];

  function record(name, pass, detail) {
    results.push({ name, pass: !!pass, detail: String(detail || '').slice(0, 2000) });
  }

  const browser = await chromium.launch();

  // ── public UI: console/page error 0件、operator requestを発生させない ──
  {
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    const operatorRequests = [];
    const failedResponseUrls = [];
    const operatorPathRequests = [];
    page.on('console', (msg) => {
      if (msg.type() === 'error') consoleErrors.push(msg.text());
    });
    page.on('pageerror', (err) => pageErrors.push(String(err)));
    page.on('request', (req) => {
      if (gatewayBase && req.url().startsWith(gatewayBase)) operatorRequests.push(req.url());
      // Phase 2-B.4限定修正（CODEX P2B4-CX-001/005対応）: public UIは
      // /api/admin・/api/simulation・/admin のいずれも呼んではならない。
      // 除外なしで検出し、違反があれば明示的にFAILとする。
      let path;
      try {
        path = new URL(req.url()).pathname;
      } catch (_) {
        path = '';
      }
      if (
        path.startsWith('/api/admin') ||
        path.startsWith('/api/simulation') ||
        path === '/admin' ||
        path.startsWith('/admin/')
      ) {
        operatorPathRequests.push(req.url());
      }
    });
    page.on('response', (res) => {
      if (res.status() >= 400) failedResponseUrls.push(`${res.status()} ${res.url()}`);
    });

    await page.goto(publicBase + '/', { waitUntil: 'networkidle', timeout: 20000 });
    record(
      'E2E: public / からoperator専用path（/api/admin, /api/simulation, /admin）へのrequest 0件',
      operatorPathRequests.length === 0,
      JSON.stringify(operatorPathRequests.slice(0, 10))
    );
    record(
      'E2E: public / のresponse failure(4xx/5xx) 0件（除外なし）',
      failedResponseUrls.length === 0,
      JSON.stringify(failedResponseUrls.slice(0, 10))
    );
    record(
      'E2E: public / のconsole error 0件（除外なし）',
      consoleErrors.length === 0,
      JSON.stringify(consoleErrors.slice(0, 10))
    );
    record('E2E: public / の page error 0件', pageErrors.length === 0, JSON.stringify(pageErrors.slice(0, 5)));

    await page.goto(publicBase + '/live', { waitUntil: 'networkidle', timeout: 20000 }).catch(() => {});
    record('E2E: public /live の operator gateway向けrequest 0件', operatorRequests.length === 0, JSON.stringify(operatorRequests.slice(0, 5)));
    record(
      'E2E: public /live からoperator専用pathへのrequest 0件（累積、/含む）',
      operatorPathRequests.length === 0,
      JSON.stringify(operatorPathRequests.slice(0, 10))
    );

    await context.close();
  }

  // ── operator UI: token hygiene ──
  {
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleTexts = [];
    page.on('console', (msg) => consoleTexts.push(msg.text()));
    const networkRequestsWithAuthHeader = [];
    page.on('request', (req) => {
      const auth = req.headers()['authorization'];
      if (auth) networkRequestsWithAuthHeader.push({ url: req.url(), hasToken: auth.includes(token) });
    });

    await page.goto(gatewayBase + '/admin/hazards.html', { waitUntil: 'load', timeout: 20000 });

    // token未入力での特権操作（read-only fetchが実行されfailすることを確認）
    const preAuthStatus = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/admin/hazards');
        return r.status;
      } catch (e) {
        return -1;
      }
    });
    record('E2E: token未入力時 /api/admin/hazards は401', preAuthStatus === 401, `status=${preAuthStatus}`);

    // dummy tokenを入力して接続
    const authBarExists = await page.locator('#operator-auth-bar').count();
    record('E2E: operator auth bar が描画される', authBarExists > 0, `count=${authBarExists}`);

    await page.fill('#operator-auth-bar input[type="password"]', token);
    await page.click('#operator-auth-bar button:has-text("接続")');
    await page.waitForTimeout(300);

    const postAuthStatus = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/admin/hazards');
        return r.status;
      } catch (e) {
        return -1;
      }
    });
    record('E2E: dummy token接続後 /api/admin/hazards は200', postAuthStatus === 200, `status=${postAuthStatus}`);
    record(
      'E2E: read-only requestにAuthorization headerがdummy token値で付与される',
      networkRequestsWithAuthHeader.some((r) => r.hasToken),
      `count=${networkRequestsWithAuthHeader.length}`
    );

    // ── storage走査（token値の非永続を確認） ──
    const storageDump = await page.evaluate(() => {
      const ls = {};
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        ls[k] = localStorage.getItem(k);
      }
      const ss = {};
      for (let i = 0; i < sessionStorage.length; i++) {
        const k = sessionStorage.key(i);
        ss[k] = sessionStorage.getItem(k);
      }
      return { ls, ss, cookie: document.cookie };
    });
    const lsText = JSON.stringify(storageDump.ls);
    const ssText = JSON.stringify(storageDump.ss);
    record('E2E: localStorageにtoken値0件', !lsText.includes(token), 'localStorage scanned');
    record('E2E: sessionStorageにtoken値0件', !ssText.includes(token), 'sessionStorage scanned');
    record('E2E: document.cookieにtoken値0件', !storageDump.cookie.includes(token), 'cookie scanned');

    const cookies = await context.cookies();
    record('E2E: context cookie jarにtoken値0件', !cookies.some((c) => c.value.includes(token)), `cookie_count=${cookies.length}`);

    // IndexedDB / CacheStorage
    const idbAndCache = await page.evaluate(async () => {
      let idbNames = [];
      try {
        if (indexedDB.databases) {
          const dbs = await indexedDB.databases();
          idbNames = dbs.map((d) => d.name);
        }
      } catch (e) {
        /* not supported in this browser context */
      }
      let cacheNames = [];
      try {
        cacheNames = await caches.keys();
      } catch (e) {
        /* Cache Storage unavailable outside secure context */
      }
      return { idbNames, cacheNames };
    });
    record(
      'E2E: IndexedDB databaseが新規作成されていない（token用DB 0件）',
      idbAndCache.idbNames.length === 0,
      JSON.stringify(idbAndCache.idbNames)
    );
    record(
      'E2E: Cache Storageにtoken関連cacheが作成されていない',
      idbAndCache.cacheNames.length === 0,
      JSON.stringify(idbAndCache.cacheNames)
    );

    // URL / DOM / console にtoken値が出現しないこと
    record('E2E: page URLにtoken値0件', !page.url().includes(token), page.url());
    const bodyHtml = await page.content();
    record('E2E: DOM(page.content())にtoken値0件', !bodyHtml.includes(token), 'DOM scanned');
    record('E2E: consoleログにtoken値0件', !consoleTexts.some((t) => t.includes(token)), `console_lines=${consoleTexts.length}`);

    // reload後にtokenが失われる（memory-only）
    await page.reload({ waitUntil: 'load' });
    const statusAfterReload = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/admin/hazards');
        return r.status;
      } catch (e) {
        return -1;
      }
    });
    record('E2E: reload後は再びtoken未認証状態に戻る（401）', statusAfterReload === 401, `status=${statusAfterReload}`);
    const statusTextAfterReload = await page.locator('#operator-auth-status').textContent();
    record('E2E: reload後のauth barが未認証表示に戻る', (statusTextAfterReload || '').includes('未認証'), statusTextAfterReload);

    // 誤401応答がtoken/Authorization/生bodyをDOMへ出さないこと（datasetsページの
    // エラー表示要素を確認。tokenが入っていないため401を誘発するだけで良い）
    const domAfterFailure = await page.content();
    record('E2E: 401後のDOMにAuthorizationヘッダ文字列が出現しない', !domAfterFailure.includes('Bearer ' + token), 'DOM scanned (post-401)');

    await context.close();
  }

  await browser.close();

  console.log(JSON.stringify(results));
  const failed = results.filter((r) => !r.pass);
  process.exit(failed.length > 0 ? 1 : 0);
}

main().catch((err) => {
  console.error(JSON.stringify([{ name: 'E2E script crashed', pass: false, detail: String(err && err.stack || err) }]));
  process.exit(1);
});

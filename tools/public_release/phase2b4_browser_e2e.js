#!/usr/bin/env node
/**
 * tools/public_release/phase2b4_browser_e2e.js
 *
 * Phase 2-B.4 browser E2E（第8.3節）。既存の playwright.config.js /
 * e2e/global-setup とは独立に、呼び出し元（phase2b4_frontend_boundary.py）
 * が起動済みの隔離Compose stackの実host portを引数で受け取り、実browserで
 * token取り扱い（session-cookie login）・public/operator境界を確認する。
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
  //
  // PHASE-2D-FINAL-ALIGNMENT（2026-10-12）: 3fb1ead（2026-09-12）で operator UI の認証は「各ページの
  // #operator-auth-bar に Bearer token を貼り、JS メモリだけに保持する」方式から「/admin/login.html の login form で
  // POST /admin/api/login → HttpOnly session cookie（Path=/admin）」方式に置き換わり、operator API の外部 path は
  // /admin/api/admin/* になった。旧 UI 前提の 4 件（auth bar 描画・Authorization header 付与・reload 後 401・
  // reload 後の未認証表示）を OWNER 承認済みの session-cookie 契約（RTE-004 改定と同じ）で置き換え、token 値の
  // 非永続・非露出の走査（storage・cookie・IndexedDB・Cache Storage・URL・DOM・console）は従来どおり維持する。
  // check 数（16）と順序は変えない。
  {
    const context = await browser.newContext();
    const page = await context.newPage();
    const consoleTexts = [];
    page.on('console', (msg) => consoleTexts.push(msg.text()));
    const requestUrls = [];
    const leakingRequestBodies = [];
    const leakingLocations = [];
    page.on('request', (req) => {
      requestUrls.push(req.url());
      const body = req.postData() || '';
      let path = '';
      try {
        path = new URL(req.url()).pathname;
      } catch (_) {
        path = '';
      }
      // login request body に token が入ること自体は許容（契約 4）。それ以外の request body は禁止。
      if (body.includes(token) && !(req.method() === 'POST' && path === '/admin/api/login')) {
        leakingRequestBodies.push(`${req.method()} ${path}`);
      }
    });
    page.on('response', (res) => {
      const loc = res.headers()['location'];
      if (loc && loc.includes(token)) leakingLocations.push(res.url());
    });

    const protectedUrl = '/admin/api/admin/hazards';
    const fetchStatus = () =>
      page.evaluate(async (u) => {
        try {
          const r = await fetch(u, { credentials: 'same-origin' });
          return r.status;
        } catch (e) {
          return -1;
        }
      }, protectedUrl);

    // 未ログインで管理ページを開くと login 画面へ送られる
    await page.goto(gatewayBase + '/admin/hazards.html', { waitUntil: 'load', timeout: 20000 });
    await page.waitForURL('**/admin/login.html', { timeout: 10000 }).catch(() => {});

    const preAuthStatus = await fetchStatus();
    record('E2E: 未ログイン時 /admin/api/admin/hazards は401', preAuthStatus === 401, `status=${preAuthStatus}`);

    const loginFormCount = await page.locator('#login-form input#token[type="password"]').count();
    record(
      'E2E: 未ログインで管理ページを開くと login form（#login-form #token）が描画される',
      loginFormCount === 1 && new URL(page.url()).pathname === '/admin/login.html',
      `count=${loginFormCount} path=${new URL(page.url()).pathname}`
    );

    await page.fill('#login-form input#token', token);
    await Promise.all([
      page.waitForURL((u) => new URL(u).pathname === '/admin/', { timeout: 15000 }),
      page.click('#login-form button#submit-btn'),
    ]).catch(() => {});
    await page.waitForLoadState('load');

    const postAuthStatus = await fetchStatus();
    record('E2E: login 後 /admin/api/admin/hazards は200（session cookie）', postAuthStatus === 200, `status=${postAuthStatus}`);

    const sessionCookies = (await context.cookies()).filter((c) => c.name === 'ohg_admin_session');
    const sc = sessionCookies[0];
    const gatewayHost = new URL(gatewayBase).hostname;
    record(
      'E2E: session cookie は HttpOnly・Secure・SameSite=Strict・Path=/admin・host-only で発行され、値は token と異なる',
      sessionCookies.length === 1 &&
        sc.httpOnly === true &&
        sc.secure === true &&
        sc.sameSite === 'Strict' &&
        sc.path === '/admin' &&
        sc.domain === gatewayHost &&
        !sc.value.includes(token),
      sc
        ? `count=${sessionCookies.length} httpOnly=${sc.httpOnly} secure=${sc.secure} sameSite=${sc.sameSite} path=${sc.path} domain=${sc.domain}`
        : 'session cookie not issued'
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
    record(
      'E2E: document.cookieにtoken値0件（HttpOnly session cookieはJSから読めない）',
      !storageDump.cookie.includes(token) && !storageDump.cookie.includes('ohg_admin_session'),
      'cookie scanned'
    );

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

    // URL / redirect / request body / DOM / console にtoken値が出現しないこと
    const urlLeaks = requestUrls.filter((u) => u.includes(token) || u.includes(encodeURIComponent(token)));
    record(
      'E2E: page URL・全request URL・redirect Location・login以外のrequest bodyにtoken値0件',
      !page.url().includes(token) && urlLeaks.length === 0 && leakingLocations.length === 0 && leakingRequestBodies.length === 0,
      `requests=${requestUrls.length} url_hits=${urlLeaks.length} location_hits=${leakingLocations.length} body_hits=${JSON.stringify(leakingRequestBodies)}`
    );
    const bodyHtml = await page.content();
    record('E2E: DOM(page.content())にtoken値0件', !bodyHtml.includes(token), 'DOM scanned');
    record('E2E: consoleログにtoken値0件', !consoleTexts.some((t) => t.includes(token)), `console_lines=${consoleTexts.length}`);

    // reload後も有効な session cookie がある限り認証状態を維持する（契約 5）
    await page.reload({ waitUntil: 'load' });
    await page.waitForTimeout(500);
    const statusAfterReload = await fetchStatus();
    record(
      'E2E: reload後も session が維持され /admin/api/admin/hazards は200（login画面へ戻されない）',
      statusAfterReload === 200 && new URL(page.url()).pathname !== '/admin/login.html',
      `status=${statusAfterReload} path=${new URL(page.url()).pathname}`
    );

    // logout（admin-shell の「ログアウト」）後は session が無効化され 401（契約 6）
    await Promise.all([
      page.waitForURL('**/admin/login.html', { timeout: 10000 }),
      page.locator('#admin-shell-bar').getByRole('button', { name: 'ログアウト', exact: true }).click(),
    ]).catch(() => {});
    const statusAfterLogout = await fetchStatus();
    const replay = sc
      ? await (async () => {
          const ctx = await browser.newContext();
          await ctx.addCookies([{ name: sc.name, value: sc.value, domain: sc.domain, path: sc.path, secure: sc.secure, httpOnly: true, sameSite: 'Strict' }]);
          const r = await ctx.request.get(gatewayBase + protectedUrl);
          const st = r.status();
          await ctx.close();
          return st;
        })()
      : null;
    record(
      'E2E: logout後は /admin/api/admin/hazards が401・logout前のsession cookieを再送しても401',
      statusAfterLogout === 401 && replay === 401,
      `status=${statusAfterLogout} replay=${replay}`
    );

    // 401後のDOMにtoken/Authorization文字列が出ないこと
    const domAfterFailure = await page.content();
    record(
      'E2E: 401後のDOMにAuthorizationヘッダ文字列・token値が出現しない',
      !domAfterFailure.includes('Bearer ' + token) && !domAfterFailure.includes(token),
      'DOM scanned (post-401)'
    );

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

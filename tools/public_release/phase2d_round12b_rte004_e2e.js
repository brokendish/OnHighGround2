// tools/public_release/phase2d_round12b_rte004_e2e.js
//
// NEW-RTE-004 — Operator Authentication Persistence / Credential Non-Leakage.
//
// PHASE-2D-FINAL-ALIGNMENT（2026-10-12、OWNER 承認済み B6 契約改定）: 3fb1ead（2026-09-12）で operator UI の
// 認証は「各ページの #operator-auth-bar で Bearer token を JS メモリだけに保持（reload で失効）」から
// 「/admin/login.html の login form → POST /admin/api/login → HttpOnly session cookie（Path=/admin）」に変わり、
// operator API の外部 path は /admin/api/admin/* になった。case ID・目的（credential を永続化・再露出させない
// こと、認証を偽装できないこと）は維持し、oracle を現行の session-cookie login 契約へ追従させる:
//
//   1. 未認証の protected API は 401、管理ページは login 画面へ送られる
//   2. login 成功で session cookie が発行される
//   3. credential は URL / query / redirect Location に載らない
//   4. login request（POST /admin/api/login）の body に token が入ることは許容。それ以外の request body、
//      rendered HTML、client JS state、console、storage には再露出しない
//   5. reload 後も有効な session cookie がある限り認証状態を維持する（401 を要求しない）
//   6. logout（session 無効化）後は 401。logout 前の cookie を再送しても 401
//   7. query parameter の token は認証に使えない
//   8. 偽造・無効な cookie（乱数値、token 値そのもの）は認証に使えない
//   9. Bearer contract が残る API で誤 Bearer は 401
//  10. session cookie は HttpOnly・Secure・SameSite=Strict・Path=/admin・host-only（Domain 属性で広げない）
//
// secret derivative の走査対象（Round 12A.1 §10）: raw / URL-encoded / Base64 / URL-safe Base64 を、cookie・
// localStorage・sessionStorage・IndexedDB・Cache Storage・request URL（query / fragment を含む）・login 以外の
// request body・redirect Location・rendered HTML・client JS state・console で検査する。
//
// `regressed` mode は、わざと token を localStorage へ保存する SYNTHETIC negative-control fixture（承認済み
// application bytes は使わない）に対して走査が実際に漏えいを検出することを示す。
//
// Usage:
//   node phase2d_round12b_rte004_e2e.js --mode real --url <operator datasets.html URL> --token <canary>
//   node phase2d_round12b_rte004_e2e.js --mode regressed --url <file:// or http:// regressed fixture URL> --token <canary>
//
// Prints a single line "RTE004_RESULT_JSON=<json>" to stdout. secret 値そのものは出力しない。

const { chromium } = require('@playwright/test');

const SESSION_COOKIE_NAME = 'ohg_admin_session';
const PROTECTED_API = '/admin/api/admin/datasets';
const LOGIN_PATH = '/admin/login.html';

function b64(s) {
  return Buffer.from(s, 'utf-8').toString('base64');
}
function b64url(s) {
  return b64(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function parseArgs(argv) {
  const opts = {};
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith('--')) {
      opts[argv[i].slice(2)] = argv[i + 1];
      i++;
    }
  }
  return opts;
}

function pathOf(u) {
  try {
    return new URL(u).pathname;
  } catch (_) {
    return '';
  }
}

async function dumpStorage(page) {
  return page.evaluate(async () => {
    const cookie = document.cookie;
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
    let idb = {};
    try {
      const dbs = (await indexedDB.databases()) || [];
      for (const dbInfo of dbs) {
        idb[dbInfo.name] = await new Promise((resolve) => {
          const req = indexedDB.open(dbInfo.name);
          req.onsuccess = () => {
            const db = req.result;
            const storeNames = Array.from(db.objectStoreNames);
            if (storeNames.length === 0) {
              resolve({});
              return;
            }
            const tx = db.transaction(storeNames, 'readonly');
            const result = {};
            let remaining = storeNames.length;
            storeNames.forEach((sn) => {
              const store = tx.objectStore(sn);
              const getAllReq = store.getAll();
              getAllReq.onsuccess = () => {
                result[sn] = getAllReq.result;
                remaining--;
                if (remaining === 0) resolve(result);
              };
              getAllReq.onerror = () => {
                result[sn] = null;
                remaining--;
                if (remaining === 0) resolve(result);
              };
            });
          };
          req.onerror = () => resolve({ _error: true });
        });
      }
    } catch (e) {
      idb = { _error: String(e) };
    }
    let cacheStorage = {};
    try {
      const names = await caches.keys();
      for (const n of names) {
        const c = await caches.open(n);
        const keys = await c.keys();
        cacheStorage[n] = keys.map((k) => k.url);
      }
    } catch (e) {
      cacheStorage = { _error: String(e) };
    }
    return { cookie, localStorage: ls, sessionStorage: ss, indexedDB: idb, cacheStorage };
  });
}

// client JS state: window の own property のうち文字列・数値・浅い object を JSON 化したもの（関数・DOM は除く）
async function dumpJsState(page) {
  return page.evaluate(() => {
    const out = {};
    for (const k of Object.getOwnPropertyNames(window)) {
      let v;
      try {
        v = window[k];
      } catch (_) {
        continue;
      }
      if (v === null || v === undefined || typeof v === 'function') continue;
      if (typeof v === 'string' || typeof v === 'number' || typeof v === 'boolean') {
        out[k] = v;
        continue;
      }
      if (typeof v === 'object' && !(v instanceof Node) && v !== window) {
        try {
          const s = JSON.stringify(v);
          if (s && s.length < 200000) out[k] = s;
        } catch (_) {
          /* cyclic / host object */
        }
      }
    }
    return JSON.stringify(out);
  });
}

async function statusOf(page, url) {
  return page.evaluate(async (u) => {
    try {
      const r = await fetch(u, { credentials: 'same-origin' });
      return r.status;
    } catch (e) {
      return 'FETCH_ERROR:' + String(e);
    }
  }, url);
}

// cookie を持たない新しい context から request を送る（cookie を追加する場合は addCookies を使う）
async function isolatedStatus(browser, url, { headers, cookies } = {}) {
  const ctx = await browser.newContext();
  try {
    if (cookies) await ctx.addCookies(cookies);
    const r = await ctx.request.get(url, { headers: headers || {}, maxRedirects: 0 });
    return r.status();
  } finally {
    await ctx.close();
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const mode = opts.mode;
  const url = opts.url;
  const token = opts.token;
  if (!mode || !url || !token) {
    throw new Error('HARNESS_ERROR: --mode, --url, --token are all required');
  }

  const derivatives = {
    raw: token,
    url_encoded: encodeURIComponent(token),
    base64: b64(token),
    base64url: b64url(token),
  };

  const capturedRequests = [];
  const redirectLocations = [];
  const consoleTexts = [];
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('request', (req) => {
    capturedRequests.push({ url: req.url(), postData: req.postData() || null, method: req.method() });
  });
  page.on('response', (res) => {
    const loc = res.headers()['location'];
    if (loc) redirectLocations.push({ url: res.url(), location: loc });
  });
  page.on('console', (msg) => consoleTexts.push(msg.text()));

  await page.goto(url, { waitUntil: 'load' });

  const result = { mode };
  const renderedHtml = [];
  const jsStates = [];

  if (mode === 'real') {
    const origin = new URL(url).origin;
    const apiUrl = origin + PROTECTED_API;

    // 1. 未認証: 管理ページは login 画面へ送られ、protected API は 401
    await page.waitForURL((u) => pathOf(u.toString()) === LOGIN_PATH, { timeout: 10000 }).catch(() => {});
    result.unauthRedirectedToLogin = pathOf(page.url()) === LOGIN_PATH;
    result.unauthStatus = await statusOf(page, PROTECTED_API);

    // 2. login（現行 login form。selector は id で限定）
    await page.fill('#login-form input#token', token);
    await Promise.all([
      page.waitForURL((u) => pathOf(u.toString()) === '/admin/', { timeout: 15000 }),
      page.click('#login-form button#submit-btn'),
    ]).catch(() => {});
    await page.waitForLoadState('load');
    result.postLoginPath = pathOf(page.url());
    result.postAuthFetchStatus = await statusOf(page, PROTECTED_API);

    // 10. session cookie 属性（値そのものは出力しない）
    const sessionCookies = (await context.cookies()).filter((c) => c.name === SESSION_COOKIE_NAME);
    const sc = sessionCookies[0] || null;
    result.sessionCookie = sc
      ? {
          count: sessionCookies.length,
          httpOnly: sc.httpOnly,
          secure: sc.secure,
          sameSite: sc.sameSite,
          path: sc.path,
          hostOnly: sc.domain === new URL(url).hostname,
          valueDiffersFromToken: !Object.values(derivatives).some((d) => sc.value.includes(d)),
        }
      : null;

    renderedHtml.push(['rendered_html:post_login', await page.content()]);
    jsStates.push(['js_state:post_login', await dumpJsState(page)]);
    result.storage = await dumpStorage(page);

    // 5. reload 後も session を維持
    await page.reload({ waitUntil: 'load' });
    await page.waitForTimeout(500);
    result.postReloadPath = pathOf(page.url());
    result.postReloadStatus = await statusOf(page, PROTECTED_API);
    renderedHtml.push(['rendered_html:post_reload', await page.content()]);
    jsStates.push(['js_state:post_reload', await dumpJsState(page)]);

    // 7・8・9. 認証に使えないもの（cookie を持たない別 context から送る）
    result.queryTokenStatus = await isolatedStatus(browser, `${apiUrl}?token=${encodeURIComponent(token)}`);
    result.accessTokenQueryStatus = await isolatedStatus(browser, `${apiUrl}?access_token=${encodeURIComponent(token)}`);
    const host = new URL(url).hostname;
    const forged = (value) => [{ name: SESSION_COOKIE_NAME, value, domain: host, path: '/admin', secure: true, httpOnly: true, sameSite: 'Strict' }];
    result.forgedCookieStatus = await isolatedStatus(browser, apiUrl, { cookies: forged('forged-' + b64url(String(Date.now()))) });
    result.tokenAsCookieStatus = await isolatedStatus(browser, apiUrl, { cookies: forged(token) });
    result.invalidBearerStatus = await isolatedStatus(browser, apiUrl, { headers: { Authorization: 'Bearer RTE004-INVALID-BEARER' } });

    // 6. logout（admin-shell の「ログアウト」ボタン）後は 401、logout 前の cookie を再送しても 401
    await Promise.all([
      page.waitForURL((u) => pathOf(u.toString()) === LOGIN_PATH, { timeout: 10000 }),
      page.locator('#admin-shell-bar').getByRole('button', { name: 'ログアウト', exact: true }).click(),
    ]).catch(() => {});
    result.postLogoutPath = pathOf(page.url());
    result.postLogoutStatus = await statusOf(page, PROTECTED_API);
    result.replayedCookieAfterLogoutStatus = sc ? await isolatedStatus(browser, apiUrl, { cookies: forged(sc.value) }) : null;
    // cookie を削除した場合も 401
    await context.clearCookies();
    result.clearedCookieStatus = await statusOf(page, PROTECTED_API);
    renderedHtml.push(['rendered_html:post_logout', await page.content()]);
  } else if (mode === 'regressed') {
    await page.fill('#tok', token);
    await page.click('#connect');
    await page.waitForTimeout(300);
    result.storage = await dumpStorage(page);
  } else {
    throw new Error('HARNESS_ERROR: unknown --mode ' + mode);
  }

  await browser.close();

  const storageDump = result.storage;
  delete result.storage;
  const haystacks = [];
  haystacks.push(['cookie', storageDump.cookie || '']);
  haystacks.push(['localStorage', JSON.stringify(storageDump.localStorage)]);
  haystacks.push(['sessionStorage', JSON.stringify(storageDump.sessionStorage)]);
  haystacks.push(['indexedDB', JSON.stringify(storageDump.indexedDB)]);
  haystacks.push(['cacheStorage', JSON.stringify(storageDump.cacheStorage)]);
  let allowedLoginBodies = 0;
  for (const r of capturedRequests) {
    haystacks.push(['request_url:' + r.method + ':' + pathOf(r.url), r.url]);
    if (r.postData) {
      // 契約 4: login request の body に token が入ること自体は許容（他の request body は検査対象）
      if (mode === 'real' && r.method === 'POST' && pathOf(r.url) === '/admin/api/login') {
        allowedLoginBodies++;
        continue;
      }
      haystacks.push(['request_body:' + r.method + ':' + pathOf(r.url), r.postData]);
    }
  }
  for (const l of redirectLocations) haystacks.push(['redirect_location:' + pathOf(l.url), l.location]);
  for (const h of renderedHtml) haystacks.push(h);
  for (const h of jsStates) haystacks.push(h);
  haystacks.push(['console', consoleTexts.join('\n')]);

  const findings = [];
  for (const [label, haystack] of haystacks) {
    if (!haystack) continue;
    for (const [derivName, derivValue] of Object.entries(derivatives)) {
      if (derivValue && haystack.includes(derivValue)) {
        findings.push({ surface: label, derivative: derivName });
      }
    }
  }

  result.findings = findings;
  result.capturedRequestCount = capturedRequests.length;
  result.allowedLoginRequestBodies = allowedLoginBodies;
  result.scannedSurfaceCount = haystacks.length;
  console.log('RTE004_RESULT_JSON=' + JSON.stringify(result));
}

main().catch((e) => {
  console.error('HARNESS_ERROR', e && e.stack ? e.stack : e);
  process.exit(2);
});

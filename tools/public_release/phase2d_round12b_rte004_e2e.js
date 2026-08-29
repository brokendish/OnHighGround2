// tools/public_release/phase2d_round12b_rte004_e2e.js
//
// NEW-RTE-004 Playwright driver: operator Bearer token storage/derivative
// scan. Drives the REAL operator-auth.js token-entry UI (the auth bar is
// the only mechanism by which a token enters the closure-scoped
// `_operatorToken` variable in the real application; there is no separate
// login form). Also supports a `regressed` mode against a deliberately
// regressed SYNTHETIC negative-control fixture (never the approved
// application bytes) to prove the scan actually detects a real leak.
//
// Usage:
//   node phase2d_round12b_rte004_e2e.js --mode real --url <operator datasets.html URL> --token <canary>
//   node phase2d_round12b_rte004_e2e.js --mode regressed --url <file:// or http:// regressed fixture URL> --token <canary>
//
// Prints a single line "RTE004_RESULT_JSON=<json>" to stdout.

const { chromium } = require('@playwright/test');

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
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('request', (req) => {
    capturedRequests.push({ url: req.url(), postData: req.postData() || null, method: req.method() });
  });

  await page.goto(url, { waitUntil: 'load' });

  let postAuthFetchStatus = null;
  if (mode === 'real') {
    await page.fill('#operator-auth-bar input[type=password]', token);
    await page.click('#operator-auth-bar button:has-text("接続")');
    postAuthFetchStatus = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/admin/datasets');
        return r.status;
      } catch (e) {
        return 'FETCH_ERROR:' + String(e);
      }
    });
  } else if (mode === 'regressed') {
    await page.fill('#tok', token);
    await page.click('#connect');
  } else {
    throw new Error('HARNESS_ERROR: unknown --mode ' + mode);
  }

  await page.waitForTimeout(300);

  const storageDump = await page.evaluate(async () => {
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

  let postReloadStatus = null;
  if (mode === 'real') {
    await page.reload({ waitUntil: 'load' });
    postReloadStatus = await page.evaluate(async () => {
      try {
        const r = await fetch('/api/admin/datasets');
        return r.status;
      } catch (e) {
        return 'FETCH_ERROR:' + String(e);
      }
    });
  }

  await browser.close();

  const haystacks = [];
  haystacks.push(['cookie', storageDump.cookie || '']);
  haystacks.push(['localStorage', JSON.stringify(storageDump.localStorage)]);
  haystacks.push(['sessionStorage', JSON.stringify(storageDump.sessionStorage)]);
  haystacks.push(['indexedDB', JSON.stringify(storageDump.indexedDB)]);
  haystacks.push(['cacheStorage', JSON.stringify(storageDump.cacheStorage)]);
  for (const r of capturedRequests) {
    haystacks.push(['request_url:' + r.method + ':' + r.url, r.url]);
    if (r.postData) haystacks.push(['request_body:' + r.method + ':' + r.url, r.postData]);
  }

  const findings = [];
  for (const [label, haystack] of haystacks) {
    if (!haystack) continue;
    for (const [derivName, derivValue] of Object.entries(derivatives)) {
      if (derivValue && haystack.includes(derivValue)) {
        findings.push({ surface: label, derivative: derivName });
      }
    }
  }

  console.log(
    'RTE004_RESULT_JSON=' +
      JSON.stringify({
        mode,
        postAuthFetchStatus,
        postReloadStatus,
        findings,
        capturedRequestCount: capturedRequests.length,
      })
  );
}

main().catch((e) => {
  console.error('HARNESS_ERROR', e && e.stack ? e.stack : e);
  process.exit(2);
});

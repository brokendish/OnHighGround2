/**
 * admin-shell.js — OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN Phase B
 *
 * ページ読み込み時にsession状態（`GET /admin/api/session`）を確認し、
 * 未認証ならlogin.htmlへ遷移する。認証済みなら、以後のmutation request
 * （POST/PUT/DELETE）へ自動的に`X-CSRF-Token`を付与するfetch wrapperを
 * 設定し、画面上部に「ログアウト」「管理画面を終了」を配置する。
 *
 * 旧 js/operator-auth.js（Bearer tokenをJSメモリへ手動貼り付ける方式）は
 * このscriptに置き換わる（既存のindex.html/datasets.html/hazards.html/
 * simulation.htmlから読み込みを外す）。Bearer認証自体はAPI層で引き続き
 * 有効（CLI/自動化向けlegacy経路）。
 *
 * csrf_tokenはこのfileのmodule変数にのみ保持する（sessionStorage等の
 * 永続storageへは書かない。reload毎に`/admin/api/session`を再取得する）。
 */
(function () {
  'use strict';

  const LOGIN_PATH = '/admin/login.html';
  const SESSION_PATH = '/admin/api/session';
  const LOGOUT_PATH = '/admin/api/logout';
  const SHUTDOWN_PATH = '/admin/api/system/shutdown';
  // CSRF tokenを自動付与するpath prefix。GET専用pathは含めなくても実害はない
  // （backend側はGET/HEAD/OPTIONSをCSRF検証対象外にしている）が、簡潔さの
  // ため「session cookieで認証される可能性のあるAPI全て」を一括で対象にする。
  const CSRF_PREFIXES = ['/admin/api/admin/', '/admin/api/simulation/', '/admin/api/logout', '/admin/api/system/shutdown'];

  let _csrfToken = null;
  const _nativeFetch = window.fetch.bind(window);

  function _protectedPathOrNull(input) {
    let raw;
    if (typeof input === 'string') {
      raw = input;
    } else if (input && typeof input.url === 'string') {
      raw = input.url;
    } else {
      return null;
    }
    let url;
    try {
      url = new URL(raw, window.location.origin);
    } catch (_) {
      return null;
    }
    if (url.origin !== window.location.origin) return null;
    return CSRF_PREFIXES.some((p) => url.pathname.startsWith(p)) ? url.pathname : null;
  }

  window.fetch = function adminShellFetch(input, init) {
    const mergedInit = Object.assign({}, init);
    if (_csrfToken && _protectedPathOrNull(input)) {
      const headers = new Headers(
        (init && init.headers) || (typeof input !== 'string' && input ? input.headers : undefined)
      );
      headers.set('X-CSRF-Token', _csrfToken);
      mergedInit.headers = headers;
    }
    // session cookieを同一originへ確実に送る（既定でも同一originはsame-origin
    // 扱いだが、明示しておく）。
    if (mergedInit.credentials === undefined) mergedInit.credentials = 'same-origin';
    return _nativeFetch(input, mergedInit);
  };

  function _redirectToLogin() {
    window.location.replace(LOGIN_PATH);
  }

  function _buildBar() {
    const bar = document.createElement('div');
    bar.id = 'admin-shell-bar';
    bar.style.cssText =
      'position:sticky;top:0;z-index:9999;display:flex;align-items:center;justify-content:flex-end;gap:8px;' +
      'padding:6px 14px;background:#1b2430;color:#e8edf3;' +
      'font:12px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;';

    const logoutBtn = document.createElement('button');
    logoutBtn.type = 'button';
    logoutBtn.textContent = 'ログアウト';
    logoutBtn.style.cssText = _btnStyle('#374151');
    logoutBtn.addEventListener('click', _handleLogout);
    bar.appendChild(logoutBtn);

    const shutdownBtn = document.createElement('button');
    shutdownBtn.type = 'button';
    shutdownBtn.textContent = '管理画面を終了';
    shutdownBtn.style.cssText = _btnStyle('#7f1d1d');
    shutdownBtn.addEventListener('click', _openShutdownConfirm);
    bar.appendChild(shutdownBtn);

    return bar;
  }

  function _btnStyle(bg) {
    return `padding:5px 12px;border:none;border-radius:4px;background:${bg};color:#e8edf3;cursor:pointer;font-size:12px;`;
  }

  async function _handleLogout() {
    try {
      await window.fetch(LOGOUT_PATH, { method: 'POST' });
    } catch (_) {
      // network errorでもlogin画面へは戻す（session cookie自体は
      // server側で既に破棄を試みている）。
    }
    _redirectToLogin();
  }

  function _overlay() {
    const el = document.createElement('div');
    el.style.cssText =
      'position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;' +
      'background:rgba(0,0,0,0.55);';
    return el;
  }

  function _openShutdownConfirm() {
    const overlay = _overlay();
    const box = document.createElement('div');
    box.style.cssText =
      'background:#1b2430;color:#e8edf3;padding:24px;border-radius:8px;max-width:360px;' +
      'font:13px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;';

    const title = document.createElement('p');
    title.textContent = '管理用サービスを停止します。';
    title.style.cssText = 'margin:0 0 8px;font-weight:bold;';
    box.appendChild(title);

    const body = document.createElement('p');
    body.textContent =
      '再度利用するにはVPS上で docker compose --profile operator up -d を実行する必要があります。';
    body.style.cssText = 'margin:0 0 20px;color:#94a3b8;';
    box.appendChild(body);

    const row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:flex-end;gap:8px;';

    const cancelBtn = document.createElement('button');
    cancelBtn.type = 'button';
    cancelBtn.textContent = 'キャンセル';
    cancelBtn.style.cssText = _btnStyle('#374151');
    cancelBtn.addEventListener('click', () => overlay.remove());
    row.appendChild(cancelBtn);

    const confirmBtn = document.createElement('button');
    confirmBtn.type = 'button';
    confirmBtn.textContent = '終了する';
    confirmBtn.style.cssText = _btnStyle('#b91c1c');
    confirmBtn.addEventListener('click', () => {
      overlay.remove();
      _performShutdown();
    });
    row.appendChild(confirmBtn);

    box.appendChild(row);
    overlay.appendChild(box);
    document.body.appendChild(overlay);
  }

  async function _performShutdown() {
    const overlay = _overlay();
    const box = document.createElement('div');
    box.style.cssText =
      'background:#1b2430;color:#e8edf3;padding:24px;border-radius:8px;max-width:360px;text-align:center;' +
      'font:13px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;';
    box.textContent = '管理画面を終了しています…';
    overlay.appendChild(box);
    document.body.appendChild(overlay);

    try {
      const res = await window.fetch(SHUTDOWN_PATH, { method: 'POST' });
      if (res.status === 202) {
        const data = await res.json().catch(() => null);
        box.textContent = (data && data.message) || '管理画面を終了しています…';
      } else {
        box.textContent = `終了要求が受理されませんでした（status=${res.status}）。ページを再読み込みしてください。`;
      }
    } catch (_) {
      // 数秒後に接続不能になるのは正常（operator-gatewayが停止するため）。
      box.textContent = '管理画面を終了しました。再開するには VPS 上で docker compose --profile operator up -d を実行してください。';
    }
  }

  async function _initSession() {
    let res;
    try {
      res = await _nativeFetch(SESSION_PATH, { credentials: 'same-origin' });
    } catch (_) {
      _redirectToLogin();
      return;
    }
    if (!res.ok) {
      _redirectToLogin();
      return;
    }
    const data = await res.json().catch(() => null);
    _csrfToken = (data && data.csrf_token) || null;
    if (!_csrfToken) {
      _redirectToLogin();
      return;
    }
    if (document.body) {
      document.body.insertBefore(_buildBar(), document.body.firstChild);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _initSession);
  } else {
    _initSession();
  }
})();

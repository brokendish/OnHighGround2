/**
 * login.js — OPERATOR-ADMIN-WEB-AUTH-AND-SHUTDOWN Phase B
 *
 * `POST /admin/api/login` を叩くだけの最小限のform handler。
 * 供給されたtoken値はこのform submit以外のどこにも保持しない。
 */
(function () {
  'use strict';

  const form = document.getElementById('login-form');
  const tokenInput = document.getElementById('token');
  const submitBtn = document.getElementById('submit-btn');
  const errorEl = document.getElementById('error');

  // 既にsession cookieが有効なら、login画面を経由せず直接管理画面へ。
  fetch('/admin/api/session', { credentials: 'same-origin' })
    .then((res) => {
      if (res.ok) window.location.replace('/admin/');
    })
    .catch(() => {});

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    const token = tokenInput.value;
    tokenInput.value = '';
    errorEl.textContent = '';
    submitBtn.disabled = true;

    try {
      const res = await fetch('/admin/api/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token: token }),
      });
      if (res.ok) {
        window.location.replace('/admin/');
        return;
      }
      errorEl.textContent = 'ログインに失敗しました。トークンを確認してください。';
    } catch (_) {
      errorEl.textContent = '通信に失敗しました。しばらくしてから再試行してください。';
    } finally {
      submitBtn.disabled = false;
    }
  });
})();

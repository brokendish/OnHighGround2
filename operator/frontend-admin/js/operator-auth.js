/**
 * operator-auth.js — Phase 2-B.4 operator frontend Bearer token 取り扱い。
 *
 * tasks/public-release/phase2b4_claude_implementation_instruction.md 第3.4節。
 *
 * token はこのfileのclosure内変数にのみ保持する。Cookie / localStorage /
 * sessionStorage / IndexedDB / Cache Storage / URL / service worker には
 * 一切保存しない。reload・tab closeで失われることを許容する。
 *
 * 既存admin/simulation JS（datasets.js等）は無改造のまま `fetch(...)` を
 * 呼び続ける。本fileは window.fetch を最小限に上書きし、同一origin かつ
 * `/api/admin/` または `/api/simulation/` 配下のrequestにのみ
 * `Authorization: Bearer <token>` を付与する。query/body/form/cookieへ
 * tokenを載せることは行わない。
 */
(function () {
    'use strict';

    let _operatorToken = null;
    const _nativeFetch = window.fetch.bind(window);

    const PROTECTED_PREFIXES = ['/api/admin/', '/api/simulation/'];

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
        const matched = PROTECTED_PREFIXES.some((prefix) => url.pathname.startsWith(prefix));
        return matched ? url.pathname : null;
    }

    window.fetch = function operatorAuthFetch(input, init) {
        if (_operatorToken && _protectedPathOrNull(input)) {
            const mergedInit = Object.assign({}, init);
            const headers = new Headers(
                (init && init.headers) || (typeof input !== 'string' && input ? input.headers : undefined)
            );
            headers.set('Authorization', 'Bearer ' + _operatorToken);
            mergedInit.headers = headers;
            return _nativeFetch(input, mergedInit);
        }
        return _nativeFetch(input, init);
    };

    function setOperatorToken(value) {
        _operatorToken = value || null;
    }

    function clearOperatorToken() {
        _operatorToken = null;
    }

    function hasOperatorToken() {
        return !!_operatorToken;
    }

    // 他ページJSからの直接token参照は許可しない。制御関数のみ公開する。
    window.__operatorAuth = Object.freeze({ setOperatorToken, clearOperatorToken, hasOperatorToken });

    // ── 最小token入力UI（formへは含めない・name属性を持たせない）───────────
    function buildAuthBar() {
        const bar = document.createElement('div');
        bar.id = 'operator-auth-bar';
        bar.style.cssText =
            'position:sticky;top:0;z-index:9999;display:flex;align-items:center;gap:8px;' +
            'padding:6px 10px;background:#1b2430;color:#e8edf3;' +
            'font:12px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;';

        const label = document.createElement('span');
        label.textContent = 'Operator token:';
        bar.appendChild(label);

        const input = document.createElement('input');
        input.type = 'password';
        input.autocomplete = 'off';
        input.spellcheck = false;
        input.placeholder = 'Bearer token（メモリ保持のみ）';
        input.style.cssText = 'flex:0 0 240px;padding:3px 6px;';
        bar.appendChild(input);

        const connectBtn = document.createElement('button');
        connectBtn.type = 'button';
        connectBtn.textContent = '接続';
        bar.appendChild(connectBtn);

        const clearBtn = document.createElement('button');
        clearBtn.type = 'button';
        clearBtn.textContent = '破棄';
        bar.appendChild(clearBtn);

        const status = document.createElement('span');
        status.id = 'operator-auth-status';
        status.textContent = '未認証';
        status.style.cssText = 'margin-left:6px;color:#f2a154;';
        bar.appendChild(status);

        function setStatus(text, color) {
            status.textContent = text;
            status.style.color = color;
        }

        connectBtn.addEventListener('click', () => {
            const value = input.value;
            input.value = '';
            if (!value) {
                setOperatorToken(null);
                setStatus('未認証', '#f2a154');
                return;
            }
            setOperatorToken(value);
            setStatus('接続済み（メモリ保持のみ・reloadで失効）', '#7fd88f');
        });

        clearBtn.addEventListener('click', () => {
            input.value = '';
            clearOperatorToken();
            setStatus('未認証', '#f2a154');
        });

        input.addEventListener('keydown', (ev) => {
            if (ev.key === 'Enter') {
                ev.preventDefault();
                connectBtn.click();
            }
        });

        return bar;
    }

    function mountAuthBar() {
        if (!document.body || document.getElementById('operator-auth-bar')) return;
        document.body.insertBefore(buildAuthBar(), document.body.firstChild);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', mountAuthBar);
    } else {
        mountAuthBar();
    }
})();

'use strict';
// live-road-traffic-panel.js — 🚗 道路交通影響カード
// live-road-traffic-layer.js に依存。navigation.js / state.js には依存しない。

(function () {

    // ── バッジ設定 ────────────────────────────────────────────────────────────

    const _BADGE_CLASS = {
        very_high: 'lrtc-badge-very-high',
        high:      'lrtc-badge-high',
        normal:    'lrtc-badge-normal',
        low:       'lrtc-badge-low',
        very_low:  'lrtc-badge-very-low',
        unknown:   'lrtc-badge-unknown',
    };

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    let _userLat = null;
    let _userLng = null;

    const _card = document.getElementById('live-road-traffic-card');

    // ── レンダリング ─────────────────────────────────────────────────────────

    function _render(data) {
        if (!_card) return;

        const status = data?.status;
        // normal は原則ランキング対象外（目立った影響なし扱い）
        const items  = (data?.items || [])
            .filter(it => it?.status && it.status !== 'normal')
            .slice(0, 5);
        const stale  = data?.stale === true;
        const scope  = data?.scope || {};

        let html = `<div class="lrtc-header"><span class="lrtc-title">🚗 道路交通影響</span></div>`;

        if (status === 'unavailable') {
            html += `<div class="lrtc-unavailable">道路交通量情報を取得できません</div>`;

        } else if (status === 'ok' || stale) {
            if (!items.length) {
                const scopeLabel = _scopeLabel(scope);
                const allItems   = data?.items || [];
                if (!allItems.length) {
                    html += `<div class="lrtc-unavailable">現在地周辺の道路交通量情報はありません</div>`;
                } else {
                    html += `<div class="lrtc-no-issue">${_esc(scopeLabel)}で目立った道路交通影響は確認されていません</div>`;
                }
            } else {
                items.forEach(item => {
                    const badgeClass = _BADGE_CLASS[item.status] || 'lrtc-badge-unknown';
                    const dir = item.direction ? ` <span class="lrtc-dir">${_esc(item.direction)}</span>` : '';
                    html += `
                        <div class="lrtc-item">
                            <span class="lrtc-road">${_esc(item.road_name || '不明')}</span>${dir}
                            <span class="lrtc-badge ${badgeClass}">${_esc(item.status_label)}</span>
                        </div>`;
                });
            }

            if (stale) {
                html += `<div class="lrtc-stale-notice">⚠ 最新の道路交通量情報を取得できません。前回取得情報を表示しています</div>`;
            }

        } else {
            html += `<div class="lrtc-unavailable">道路交通量情報を取得できません</div>`;
        }

        html += `
            <div class="lrtc-legend">
                <span style="background:#dc2626"></span>交通量非常に多い（通行止めではありません）<br>
                <span style="background:#1f6feb"></span>交通量少ない
            </div>`;

        // 地図レイヤーにデータを渡す（全データ）
        window.liveRoadTrafficLayer?.setData?.(data?.items || []);

        _card.innerHTML = html;
    }

    function _scopeLabel(scope) {
        if (scope.mode === 'prefecture' && scope.prefecture) return scope.prefecture;
        if (scope.mode === 'location'   && scope.prefecture) return `${scope.prefecture}周辺`;
        return '現在地周辺';
    }

    function _esc(v) {
        return String(v ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
        }[ch]));
    }

    // ── API 取得 ─────────────────────────────────────────────────────────────

    async function refresh() {
        let url = '/api/live/road-traffic/summary';
        const params = new URLSearchParams();
        if (_userLat != null && _userLng != null) {
            params.set('lat', String(_userLat));
            params.set('lng', String(_userLng));
        }
        if ([...params].length) url += '?' + params.toString();

        try {
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            _render(data);
            return data;
        } catch (e) {
            console.warn('[live-road-traffic] 取得失敗:', e.message);
            _render({ status: 'unavailable', items: [], scope: {}, stale: false });
            throw e;
        }
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    function setLocation(lat, lng) {
        _userLat = lat;
        _userLng = lng;
    }

    window.liveRoadTrafficPanel = { refresh, setLocation };

})();

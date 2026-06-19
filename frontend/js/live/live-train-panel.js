'use strict';
// live-train-panel.js — 🚆 交通影響カード
// live-train-layer.js に依存。navigation.js / state.js には依存しない。

(function () {

    // ── 都道府県リスト ────────────────────────────────────────────────────────

    const _PREFS = [
        '北海道', '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
        '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
        '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県',
        '岐阜県', '静岡県', '愛知県', '三重県',
        '滋賀県', '京都府', '大阪府', '兵庫県', '奈良県', '和歌山県',
        '鳥取県', '島根県', '岡山県', '広島県', '山口県',
        '徳島県', '香川県', '愛媛県', '高知県',
        '福岡県', '佐賀県', '長崎県', '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県',
    ];

    // ── バッジ設定 ────────────────────────────────────────────────────────────

    const _BADGE_CLASS = {
        delay:              'ltc-badge-delay',
        partial_suspension: 'ltc-badge-partial-suspension',
        suspended:          'ltc-badge-suspended',
        unknown:            'ltc-badge-unknown',
    };

    // ── 内部状態 ──────────────────────────────────────────────────────────────

    let _currentPref  = null;   // null = 現在地周辺
    let _lastData     = null;   // 最後に取得した API レスポンス
    let _userLat      = null;
    let _userLng      = null;

    const _card = document.getElementById('live-train-card');

    // ── レンダリング ─────────────────────────────────────────────────────────

    function _render(data) {
        if (!_card) return;
        _lastData = data;

        const status = data?.status;
        const items  = (data?.items || []).filter(item => item?.status && item.status !== 'normal');
        const stale  = data?.stale === true;
        const scope  = data?.scope || {};

        let html = `<div class="ltc-header">
            <span class="ltc-title">🚆 交通影響</span>
            ${_prefSelectHtml()}
        </div>`;

        if (status === 'unavailable') {
            html += `<div class="ltc-unavailable">鉄道運行情報を取得できません</div>`;
        } else if (status === 'ok' || status === 'stale' || stale) {
            // 障害なし
            if (!items.length) {
                const scopeLabel = _scopeLabel(scope);
                html += `<div class="ltc-no-issue">${scopeLabel}で運行障害は確認されていません</div>`;
            } else {
                // 障害あり路線のみ表示
                items.forEach(item => {
                    const badgeClass = _BADGE_CLASS[item.status] || 'ltc-badge-unknown';
                    const rid = String(item.railway_id || '').replace(/"/g, '&quot;');
                    html += `
                        <div class="ltc-item ltc-item-focusable" data-railway-id="${rid}" title="地図で確認">
                            <span class="ltc-badge ${badgeClass}">${item.status_label}</span>
                            <span class="ltc-name">${item.railway_name}</span>
                            <span class="ltc-operator">${item.operator_name}</span>
                        </div>`;
                });
            }

            if (stale) {
                html += `<div class="ltc-stale-notice">⚠ 鉄道運行情報：最新情報を取得できません。前回取得情報を表示しています</div>`;
            }
        } else {
            html += `<div class="ltc-unavailable">鉄道運行情報を取得できません</div>`;
        }

        html += `<div class="ltc-source-note">※ ODPT加盟事業者の路線のみ対応</div>`;

        // 地図レイヤーにデータを渡す
        window.liveTrainLayer?.setData?.(items);

        _card.innerHTML = html;
        _bindPrefChange();
        _bindItemFocus();
    }

    function _scopeLabel(scope) {
        if (scope.mode === 'prefecture' && scope.prefecture) {
            return scope.prefecture;
        }
        if (scope.mode === 'location' && scope.prefecture) {
            return `${scope.prefecture}周辺`;
        }
        return '現在地周辺';
    }

    // ── 都道府県セレクター ──────────────────────────────────────────────────

    function _prefSelectHtml() {
        let opts = `<option value="">${_userLat ? '現在地周辺' : '都道府県を選択'}</option>`;
        _PREFS.forEach(p => {
            const sel = p === _currentPref ? ' selected' : '';
            opts += `<option value="${p}"${sel}>${p}</option>`;
        });
        return `<select class="ltc-pref-select" id="ltc-pref-select">${opts}</select>`;
    }

    function _bindPrefChange() {
        const sel = document.getElementById('ltc-pref-select');
        if (!sel) return;
        sel.addEventListener('change', () => {
            _currentPref = sel.value || null;
            refresh().catch(e => console.warn('[live-train] 更新失敗:', e.message));
        });
    }

    function _bindItemFocus() {
        if (!_card) return;
        _card.querySelectorAll('.ltc-item-focusable').forEach(el => {
            el.addEventListener('click', () => {
                const rid = el.dataset.railwayId;
                if (rid) window.liveTrainOsmLayer?.focusRailway?.(rid);
            });
        });
    }

    // ── API 取得 ─────────────────────────────────────────────────────────────

    async function refresh() {
        let url = '/api/live/trains/summary';
        const params = new URLSearchParams();
        if (_currentPref) {
            params.set('prefecture', _currentPref);
        } else if (_userLat != null && _userLng != null) {
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
            console.warn('[live-train] 取得失敗:', e.message);
            _render({ status: 'unavailable', items: [], scope: {}, stale: false });
            throw e;
        }
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    function setLocation(lat, lng) {
        _userLat = lat;
        _userLng = lng;
    }

    function setPrefecture(pref) {
        _currentPref = pref || null;
    }

    window.liveTrainPanel = { refresh, setLocation, setPrefecture };

})();

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
    const _itemMap    = new Map(); // railway_id → item（詳細モーダル用）

    // アラートパネルに統合されたスロットを動的に取得（innerHTML 再描画に対応）
    function _getCard() {
        return document.getElementById('lac-train-slot');
    }

    // ── レンダリング ─────────────────────────────────────────────────────────

    function _render(data) {
        _lastData = data;
        const card = _getCard();
        if (!card) return;  // スロットがまだ DOM にない → _lastData に保持して待機

        const status = data?.status;
        const items  = (data?.items || []).filter(item => item?.status && item.status !== 'normal');
        const stale  = data?.stale === true;
        const scope  = data?.scope || {};

        // 詳細モーダル用マップを更新
        _itemMap.clear();
        items.forEach(item => _itemMap.set(item.railway_id, item));

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
                            <button class="ltc-detail-btn" data-railway-id="${rid}">詳細</button>
                        </div>`;
                });
            }

            if (stale) {
                html += `<div class="ltc-stale-notice">⚠ 鉄道運行情報：最新情報を取得できません。前回取得情報を表示しています</div>`;
            }
        } else {
            html += `<div class="ltc-unavailable">鉄道運行情報を取得できません</div>`;
        }

        html += `<div class="ltc-source-note">※ <a href="https://developer.odpt.org/terms" target="_blank" rel="noopener">ODPT</a>加盟事業者のうちlicense確認済みの事業者（東京メトロ・都営）の路線のみ対応</div>`;

        // 地図レイヤーにデータを渡す
        window.liveTrainLayer?.setData?.(items);

        if (typeof OHG2Attribution !== 'undefined' && typeof liveMap !== 'undefined') {
            OHG2Attribution.installOdptAttribution(liveMap);
        }

        card.innerHTML = html;
        _bindPrefChange();
        _bindItemFocus(card);
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

    function _esc(v) {
        return String(v ?? '').replace(/[&<>"']/g, c => (
            { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
        ));
    }

    function _closeDetailModal() {
        document.getElementById('ltc-detail-modal')?.remove();
    }

    function _showDetailModal(item) {
        _closeDetailModal();

        const statusClass = _BADGE_CLASS[item.status] || 'ltc-badge-unknown';
        const descRow = item.description
            ? `<div class="ltc-detail-row">
                   <span class="ltc-detail-label">説明</span>
                   <span class="ltc-detail-value ltc-detail-desc">${_esc(item.description)}</span>
               </div>`
            : '';
        const rid = _esc(item.railway_id || '');

        const modal = document.createElement('div');
        modal.id = 'ltc-detail-modal';
        modal.className = 'ltc-detail-overlay';
        modal.innerHTML = `
            <div class="ltc-detail-card">
                <div class="ltc-detail-header">
                    <div class="ltc-detail-title">
                        <span class="ltc-badge ${statusClass}">${_esc(item.status_label)}</span>
                        <span class="ltc-detail-name">${_esc(item.railway_name)}</span>
                    </div>
                    <button class="ltc-detail-close" aria-label="閉じる">✕</button>
                </div>
                <div class="ltc-detail-body">
                    <div class="ltc-detail-row">
                        <span class="ltc-detail-label">事業者</span>
                        <span class="ltc-detail-value">${_esc(item.operator_name)}</span>
                    </div>
                    ${descRow}
                    <div class="ltc-detail-row">
                        <span class="ltc-detail-label">更新時刻</span>
                        <span class="ltc-detail-value">${_esc(item.updated_at || '—')}</span>
                    </div>
                    <div class="ltc-detail-row">
                        <span class="ltc-detail-label">出典</span>
                        <span class="ltc-detail-value">${_esc(item.source || 'ODPT')}</span>
                    </div>
                    ${item.license ? `
                    <div class="ltc-detail-row">
                        <span class="ltc-detail-label">ライセンス</span>
                        <span class="ltc-detail-value">${_esc(item.license)}${item.license_terms_url ? ` (<a href="${_esc(item.license_terms_url)}" target="_blank" rel="noopener">terms</a>)` : ''}</span>
                    </div>` : ''}
                    <div class="ltc-detail-row">
                        <span class="ltc-detail-label">注意</span>
                        <span class="ltc-detail-value ltc-detail-desc">本情報の内容は各事業者・ODPTによって保証されたものではありません。最新・正式な情報は各鉄道事業者の公式発表をご確認ください。</span>
                    </div>
                </div>
                <div class="ltc-detail-footer">
                    <button class="ltc-detail-map-btn" data-railway-id="${rid}">🗺 地図で見る</button>
                </div>
            </div>`;

        document.body.appendChild(modal);

        modal.addEventListener('click', e => { if (e.target === modal) _closeDetailModal(); });
        modal.querySelector('.ltc-detail-close').addEventListener('click', _closeDetailModal);
        modal.querySelector('.ltc-detail-map-btn').addEventListener('click', () => {
            window.liveTrainOsmLayer?.focusRailway?.(item.railway_id);
            _closeDetailModal();
        });
    }

    function _bindItemFocus(card) {
        if (!card) return;
        card.querySelectorAll('.ltc-detail-btn').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                const item = _itemMap.get(btn.dataset.railwayId);
                if (item) _showDetailModal(item);
            });
        });
        card.querySelectorAll('.ltc-item-focusable').forEach(el => {
            el.addEventListener('click', e => {
                if (e.target.closest('.ltc-detail-btn')) return;
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

    // アラートパネルが再描画した後に呼ばれる：_lastData を新しいスロットへ再注入
    function renderInto(_slotId) {
        if (_lastData) _render(_lastData);
    }

    window.liveTrainPanel = { refresh, setLocation, setPrefecture, renderInto };

})();

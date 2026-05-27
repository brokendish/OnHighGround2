'use strict';
// live-alert-panel.js — アクティブ警戒カード（左上）
// liveLayers / liveDangerSummary に依存。navigation.js / state.js には依存しない。

(function () {

    const _card = document.getElementById('live-alert-card');

    // ── 内部状態 ─────────────────────────────────────────────────────────────

    // /api/live/summary のレスポンス（取得失敗時は null）
    let _lastSummary = null;

    // タイル取得ステータス（rain / kikikuru の map 表示用）
    const _tileStatuses = {
        rain:     'unknown',
        kikikuru: 'unknown',
    };

    // フォールバック用データ（summary API 失敗時に使う）
    const _fbStatuses = {
        earthquake: 'unknown',
        tsunami:    'unknown',
    };
    let _fbTsunamiData = null;
    let _fbEqData      = [];

    // ── 津波表示ヘルパー ─────────────────────────────────────────────────────

    const _TSUNAMI_PRIORITY = ['major_warning', 'warning', 'advisory'];

    const _TSUNAMI_LABEL = {
        major_warning: '大津波警報',
        warning:       '津波警報',
        advisory:      '津波注意報',
    };

    const _TSUNAMI_COLOR = {
        major_warning: '#da3633',
        warning:       '#ff6b35',
        advisory:      '#e3b341',
    };

    function _tsunamiSummary(areas) {
        if (!Array.isArray(areas) || !areas.length) return null;
        const levels = areas.map(a => a.level || a.level_label || '');
        const top = _TSUNAMI_PRIORITY.find(l => levels.includes(l));
        if (!top) return null;
        const names = areas.filter(a => a.level === top).map(a => a.name || a.label || '').slice(0, 3);
        return { level: top, label: _TSUNAMI_LABEL[top], color: _TSUNAMI_COLOR[top], areas: names };
    }

    // ── 危険種別ラベル ───────────────────────────────────────────────────────

    const _TYPE_LABEL = {
        tsunami:    '津波',
        earthquake: '地震',
        rain:       '雨雲',
        kikikuru:   'キキクル',
    };

    // ── summary API レンダリング ─────────────────────────────────────────────

    function _renderFromSummary(summary) {
        if (!_card) return;

        const tsAreas    = summary.tsunami?.areas   || [];
        const eqSummary  = summary.earthquake?.summary || {};
        const dangerAreas = summary.dangerous_areas || [];
        const tsm        = _tsunamiSummary(tsAreas);
        const eqCount    = eqSummary.count_24h  ?? 0;
        const bigCount   = eqSummary.m5_count   ?? 0;

        let html = '<div class="lac-title">現在の状況</div>';

        // 津波
        const tsunamiOk = summary.tsunami?.status !== 'offline';
        if (!tsunamiOk) {
            html += `<div class="lac-item lac-offline"><span class="lac-text">津波情報: 取得失敗</span></div>`;
        } else if (tsm) {
            const areaText = tsm.areas.join(' / ');
            html += `
                <div class="lac-item lac-urgent" style="border-left-color:${tsm.color}">
                    <span class="lac-badge" style="background:${tsm.color};color:#fff">${tsm.label}</span>
                    <span class="lac-text"><small>${areaText}</small></span>
                </div>`;
        } else {
            html += `<div class="lac-item" style="border-left-color:#3fb950">
                         <span class="lac-text">津波警報なし</span>
                     </div>`;
        }

        // 地震
        const eqOk = summary.earthquake?.status !== 'offline';
        if (!eqOk) {
            html += `<div class="lac-item lac-offline"><span class="lac-text">地震情報: 取得失敗</span></div>`;
        } else if (bigCount > 0) {
            const recentArea = (dangerAreas.find(a => a.type === 'earthquake') || {}).label || '';
            html += `
                <div class="lac-item lac-warn" style="border-left-color:#ff6b35">
                    <span class="lac-badge" style="background:#ff6b35;color:#fff">M5以上 ${bigCount}件</span>
                    <span class="lac-text"><small>${recentArea}</small></span>
                </div>`;
        } else if (eqCount > 0) {
            html += `<div class="lac-item" style="border-left-color:#e3b341">
                         <span class="lac-text">地震 ${eqCount}件 (24h)</span>
                     </div>`;
        } else {
            html += `<div class="lac-item" style="border-left-color:#3fb950">
                         <span class="lac-text">地震なし (24h)</span>
                     </div>`;
        }

        // 雨雲（evaluated フラグで断定を防ぐ）
        html += _rainHtml(summary.rain);

        // キキクル（evaluated フラグで断定を防ぐ）
        html += _kikikuruHtml(summary.kikikuru);

        // 空状態メッセージ: 評価可能な地震・津波のみで判定
        const evaluableOk = summary.earthquake?.status === 'ok' && summary.tsunami?.status === 'ok';
        const noDanger = !tsm && bigCount === 0 && dangerAreas.length === 0;
        if (evaluableOk && noDanger) {
            html += `<div class="lac-allclear">地震・津波：大きな警戒情報はありません</div>`;
        } else if (!evaluableOk && noDanger) {
            html += `<div class="lac-partial-offline">一部情報を取得できません</div>`;
        }

        // 危険地域ランキング
        html += _dangerListHtml(dangerAreas);

        const now = new Date().toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
        html += `<div class="lac-updated">更新 ${now}</div>`;

        _card.innerHTML = html;
        _bindFocusClicks();
    }

    // ── フォールバックレンダリング（summary API 不使用時）────────────────────

    function _renderFallback() {
        if (!_card) return;

        const tsm      = _tsunamiSummary(_fbTsunamiData?.areas || []);
        const eqItems  = Array.isArray(_fbEqData) ? _fbEqData : [];
        const eqCount  = eqItems.length;
        const bigCount = eqItems.filter(e => (e.magnitude || 0) >= 5.0).length;
        const { dangerousAreas } = liveDangerSummary.buildSummary(
            _fbTsunamiData, eqItems,
            { ..._fbStatuses, ..._tileStatuses }
        );

        let html = '<div class="lac-title">現在の状況</div>';

        if (_fbStatuses.tsunami === 'offline') {
            html += `<div class="lac-item lac-offline"><span class="lac-text">津波情報: 取得失敗</span></div>`;
        } else if (tsm) {
            const areaText = tsm.areas.join(' / ');
            html += `
                <div class="lac-item lac-urgent" style="border-left-color:${tsm.color}">
                    <span class="lac-badge" style="background:${tsm.color};color:#fff">${tsm.label}</span>
                    <span class="lac-text"><small>${areaText}</small></span>
                </div>`;
        } else {
            html += `<div class="lac-item" style="border-left-color:#3fb950">
                         <span class="lac-text">津波警報なし</span>
                     </div>`;
        }

        if (_fbStatuses.earthquake === 'offline') {
            html += `<div class="lac-item lac-offline"><span class="lac-text">地震情報: 取得失敗</span></div>`;
        } else if (bigCount > 0) {
            const recentName = eqItems[0] ? (eqItems[0].epicenter_name || '') : '';
            html += `
                <div class="lac-item lac-warn" style="border-left-color:#ff6b35">
                    <span class="lac-badge" style="background:#ff6b35;color:#fff">M5以上 ${bigCount}件</span>
                    <span class="lac-text"><small>${recentName}</small></span>
                </div>`;
        } else if (eqCount > 0) {
            html += `<div class="lac-item" style="border-left-color:#e3b341">
                         <span class="lac-text">地震 ${eqCount}件 (24h)</span>
                     </div>`;
        } else {
            html += `<div class="lac-item" style="border-left-color:#3fb950">
                         <span class="lac-text">地震なし (24h)</span>
                     </div>`;
        }

        // 雨雲・キキクル（フォールバック時は常に evaluated=false 扱い）
        html += _rainHtml(null);
        html += _kikikuruHtml(null);

        const evaluableOk = _fbStatuses.earthquake === 'ok' && _fbStatuses.tsunami === 'ok';
        const noDanger = !tsm && bigCount === 0 && dangerousAreas.length === 0;
        if (evaluableOk && noDanger) {
            html += `<div class="lac-allclear">地震・津波：大きな警戒情報はありません</div>`;
        } else if (!evaluableOk && noDanger) {
            html += `<div class="lac-partial-offline">一部情報を取得できません</div>`;
        }

        html += _dangerListHtml(dangerousAreas);

        const now = new Date().toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
        html += `<div class="lac-updated">更新 ${now}</div>`;

        _card.innerHTML = html;
        _bindFocusClicks();
    }

    // ── 雨雲・キキクル 表示ヘルパー ─────────────────────────────────────────

    function _rainHtml(rainSection) {
        // タイル取得失敗 または summary API が offline を返した場合
        if (_tileStatuses.rain === 'offline' || rainSection?.status === 'offline') {
            return `<div class="lac-item lac-offline"><span class="lac-text">雨雲情報: 取得失敗</span></div>`;
        }
        // summary API で evaluated=true の場合のみ「なし/あり」を表示可
        if (rainSection && rainSection.evaluated === true) {
            const detected = rainSection.summary?.strong_rain_detected;
            if (detected === false) {
                return `<div class="lac-item" style="border-left-color:#3fb950">
                            <span class="lac-text">強雨域なし</span>
                        </div>`;
            }
            if (detected === true) {
                return `<div class="lac-item lac-warn" style="border-left-color:#ff6b35">
                            <span class="lac-text">強雨域あり</span>
                        </div>`;
            }
        }
        // evaluated=false or no summary → 未判定
        if (_tileStatuses.rain === 'unknown') {
            return `<div class="lac-item lac-dim"><span class="lac-text">雨雲: 確認中</span></div>`;
        }
        return `<div class="lac-item lac-dim"><span class="lac-text">雨雲: 未判定（タイル表示のみ）</span></div>`;
    }

    function _kikikuruHtml(kSection) {
        if (_tileStatuses.kikikuru === 'offline') {
            return `<div class="lac-item lac-offline"><span class="lac-text">キキクル: 取得失敗</span></div>`;
        }
        if (kSection && kSection.evaluated === true) {
            const detected = kSection.summary?.danger_detected;
            if (detected === false) {
                return `<div class="lac-item" style="border-left-color:#3fb950">
                            <span class="lac-text">キキクル危険地域なし</span>
                        </div>`;
            }
            if (detected === true) {
                return `<div class="lac-item lac-warn" style="border-left-color:#ff6b35">
                            <span class="lac-text">キキクル危険地域あり</span>
                        </div>`;
            }
        }
        if (_tileStatuses.kikikuru === 'unknown') {
            return `<div class="lac-item lac-dim"><span class="lac-text">キキクル: 未確認</span></div>`;
        }
        return `<div class="lac-item lac-dim"><span class="lac-text">キキクル: 未判定（タイル表示のみ）</span></div>`;
    }

    // ── 危険地域リスト ───────────────────────────────────────────────────────

    function _dangerListHtml(areas) {
        if (!areas || !areas.length) return '';
        let html = `<div class="lac-section-title">危険地域</div><div class="lac-danger-list">`;
        areas.forEach((area, idx) => {
            const canFocus   = area.lat != null && area.lng != null;
            const typeLabel  = _TYPE_LABEL[area.type] || area.type || '';
            const levelClass = `lac-danger-${area.level}`;
            const focusAttrs = canFocus ? `data-lat="${area.lat}" data-lng="${area.lng}"` : '';
            html += `
                <div class="lac-danger-item ${levelClass}${canFocus ? ' lac-danger-clickable' : ''}"
                     data-id="${area.id}" ${focusAttrs}>
                    <span class="lac-danger-rank">${idx + 1}</span>
                    <div class="lac-danger-info">
                        <div class="lac-danger-label">${area.label}</div>
                        <div class="lac-danger-types">${typeLabel}</div>
                    </div>
                </div>`;
        });
        return html + `</div>`;
    }

    function _bindFocusClicks() {
        if (!_card) return;
        _card.querySelectorAll('.lac-danger-clickable').forEach(el => {
            el.addEventListener('click', () => {
                const lat = parseFloat(el.dataset.lat);
                const lng = parseFloat(el.dataset.lng);
                if (!isNaN(lat) && !isNaN(lng)) liveMap.setView([lat, lng], 7);
            });
        });
    }

    // ── 公開 API ─────────────────────────────────────────────────────────────

    // タイル取得ステータスを更新して再描画（live-main.js から雨雲/キキクル状態を注入）
    function setStatus(partial) {
        if ('rain'     in partial) _tileStatuses.rain     = partial.rain;
        if ('kikikuru' in partial) _tileStatuses.kikikuru = partial.kikikuru;
        if (_lastSummary) {
            _renderFromSummary(_lastSummary);
        } else {
            _renderFallback();
        }
    }

    // 地震・津波・summary API を取得してカードを更新する
    async function update() {
        const [tsunamiResult, eqResult, summaryResult] = await Promise.allSettled([
            liveLayers.tsunami.refresh(),
            liveLayers.earthquake.refresh(),
            fetch('/api/live/summary').then(r => {
                if (!r.ok) throw new Error(`summary HTTP ${r.status}`);
                return r.json();
            }),
        ]);

        // フォールバック用データを更新
        _fbTsunamiData         = tsunamiResult.status === 'fulfilled'
            ? tsunamiResult.value : liveLayers.tsunami.getData();
        _fbEqData              = eqResult.status === 'fulfilled'
            ? eqResult.value : liveLayers.earthquake.getData();
        _fbStatuses.tsunami    = tsunamiResult.status === 'fulfilled' ? 'ok' : 'offline';
        _fbStatuses.earthquake = eqResult.status    === 'fulfilled' ? 'ok' : 'offline';

        // summary API 成功時はそちらを優先
        if (summaryResult.status === 'fulfilled') {
            _lastSummary = summaryResult.value;
            _renderFromSummary(_lastSummary);
        } else {
            console.warn('[live-panel] summary API 失敗、フォールバック:', summaryResult.reason?.message);
            _lastSummary = null;
            _renderFallback();
        }

        return {
            tsunamiOk: tsunamiResult.status === 'fulfilled',
            eqOk:      eqResult.status      === 'fulfilled',
        };
    }

    // 津波データのみ再取得してカードを更新（地震データは既取得分を流用）
    async function refreshTsunami() {
        try {
            _fbTsunamiData     = await liveLayers.tsunami.refresh();
            _fbStatuses.tsunami = 'ok';
        } catch (_) {
            _fbTsunamiData     = liveLayers.tsunami.getData();
            _fbStatuses.tsunami = 'offline';
        }
        if (_lastSummary) {
            _renderFromSummary(_lastSummary);
        } else {
            _renderFallback();
        }
    }

    window.liveAlertPanel = { update, refreshTsunami, setStatus };

})();

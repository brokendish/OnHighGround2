'use strict';
// live-alert-panel.js — アクティブ警戒カード（左上）
// liveLayers / liveDangerSummary に依存。navigation.js / state.js には依存しない。

(function () {

    const _card = document.getElementById('live-alert-card');

    // ── 内部状態 ─────────────────────────────────────────────────────────────

    // /api/live/summary のレスポンス（取得失敗時は null）
    let _lastSummary = null;

    // 地震一覧 展開状態
    let _eqListExpanded = false;

    // パネル最小化状態（デスクトップのみ）
    let _minimized = false;

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
        tsunami:     '津波',
        storm_surge: '高潮',
        earthquake:  '地震',
        rain:        '雨雲',
        kikikuru:    'キキクル',
    };

    const _HAZARD_LABEL = {
        land:       '土砂',
        inund:      '浸水',
        flood_mesh: '洪水',
    };

    // ── summary API レンダリング ─────────────────────────────────────────────

    function _renderFromSummary(summary) {
        if (!_card) return;

        const tsAreas    = summary.tsunami?.areas   || [];
        const eqSummary  = summary.earthquake?.summary || {};
        const dangerAreas = summary.dangerous_areas || [];
        const tsm        = _tsunamiSummary(tsAreas);
        const eqCount24h = eqSummary.count_24h  ?? 0;
        const bigCount   = eqSummary.m5_count   ?? 0;
        // 3日間データから表示件数を取得（地図と一覧の件数を一致させる）
        const eqCount    = Array.isArray(_fbEqData) ? _fbEqData.length : eqCount24h;

        let html = `<div class="lac-header"><span class="lac-title">現在の状況</span><button class="lac-minimize-btn" title="パネルを${_minimized ? '展開' : '最小化'}">${_minimized ? '＋' : '―'}</button></div>`;

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
            const arrow = _eqListExpanded ? '▴' : '▾';
            const listDisplay = _eqListExpanded ? '' : ' style="display:none"';
            html += `
                <div class="lac-item lac-warn lac-eq-toggle" data-action="eq-toggle"
                     style="cursor:pointer; border-left-color:#ff6b35">
                    <span class="lac-badge" style="background:#ff6b35;color:#fff">M5以上 ${bigCount}件</span>
                    <span class="lac-text"><small>${recentArea}</small></span>
                    <span class="lac-expand-arrow">${arrow}</span>
                </div>
                <div class="lac-eq-list-wrap"${listDisplay}>
                    ${_buildEqListHtml()}
                </div>`;
        } else if (eqCount > 0) {
            html += _eqToggleItemHtml(eqCount);
        } else {
            html += `<div class="lac-item" style="border-left-color:#3fb950">
                         <span class="lac-text">地震なし (3日間)</span>
                     </div>`;
        }

        // 高潮
        html += _stormSurgeHtml(summary.storm_surge);

        // 雨雲（evaluated フラグで断定を防ぐ）
        html += _rainHtml(summary.rain);

        // キキクル（evaluated フラグで断定を防ぐ）
        html += _kikikuruHtml(summary.kikikuru);

        // 空状態メッセージ: 評価可能な地震・津波のみで判定（cleared=警報なし確認済み も ok 扱い）
        const tsunamiStatusOk = summary.tsunami?.status === 'ok' || summary.tsunami?.status === 'cleared';
        const evaluableOk = summary.earthquake?.status === 'ok' && tsunamiStatusOk;
        const noDanger = !tsm && bigCount === 0 && dangerAreas.length === 0;
        if (evaluableOk && noDanger) {
            html += `<div class="lac-allclear">地震・津波：大きな警戒情報はありません</div>`;
        } else if (!evaluableOk && noDanger) {
            html += `<div class="lac-partial-offline">一部情報を取得できません</div>`;
        }

        // 危険地域ランキング（統合表示優先、フォールバックは従来表示）
        html += _dangerListHtml(dangerAreas, summary.integrated_dangerous_regions);

        // 交通情報スロット（鉄道・道路）
        html += `<div class="lac-traffic-section"><div id="lac-train-slot"></div><div id="lac-road-slot"></div></div>`;

        const now = new Date().toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
        html += `<div class="lac-updated">更新 ${now}</div>`;

        _card.innerHTML = html;
        _card.classList.toggle('is-minimized', _minimized);
        _bindFocusClicks();
        _refreshTrafficSlots();
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

        let html = `<div class="lac-header"><span class="lac-title">現在の状況</span><button class="lac-minimize-btn" title="パネルを${_minimized ? '展開' : '最小化'}">${_minimized ? '＋' : '―'}</button></div>`;

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
            const arrow = _eqListExpanded ? '▴' : '▾';
            const listDisplay = _eqListExpanded ? '' : ' style="display:none"';
            html += `
                <div class="lac-item lac-warn lac-eq-toggle" data-action="eq-toggle"
                     style="cursor:pointer; border-left-color:#ff6b35">
                    <span class="lac-badge" style="background:#ff6b35;color:#fff">M5以上 ${bigCount}件</span>
                    <span class="lac-text"><small>${recentName}</small></span>
                    <span class="lac-expand-arrow">${arrow}</span>
                </div>
                <div class="lac-eq-list-wrap"${listDisplay}>
                    ${_buildEqListHtml()}
                </div>`;
        } else if (eqCount > 0) {
            html += _eqToggleItemHtml(eqCount);
        } else {
            html += `<div class="lac-item" style="border-left-color:#3fb950">
                         <span class="lac-text">地震なし (3日間)</span>
                     </div>`;
        }

        // 高潮（フォールバック時は summary なし扱い）
        html += _stormSurgeHtml(null);

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

        // 交通情報スロット（鉄道・道路）
        html += `<div class="lac-traffic-section"><div id="lac-train-slot"></div><div id="lac-road-slot"></div></div>`;

        const now = new Date().toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
        html += `<div class="lac-updated">更新 ${now}</div>`;

        _card.innerHTML = html;
        _card.classList.toggle('is-minimized', _minimized);
        _bindFocusClicks();
        _refreshTrafficSlots();
    }

    // ── 地震一覧ヘルパー ─────────────────────────────────────────────────────────

    // 経過日数ラベル（今日/昨日/N日前）
    function _eqDayLabel(occurredAt) {
        if (!occurredAt) return '';
        const ageDays = Math.floor((Date.now() - new Date(occurredAt).getTime()) / (1000 * 60 * 60 * 24));
        if (ageDays === 0) return '今日';
        if (ageDays === 1) return '昨日';
        return `${ageDays}日前`;
    }

    function _buildEqListHtml() {
        const items = Array.isArray(_fbEqData) ? _fbEqData.slice(0, 30) : [];
        if (!items.length) return '<div class="lac-eq-empty">履歴なし</div>';
        let html = '';
        let lastDayLabel = '';
        items.forEach(eq => {
            const name      = eq.epicenter_name || eq.hypocenter_name || '震源不明';
            const mag       = eq.magnitude != null ? `M${Number(eq.magnitude).toFixed(1)}` : 'M-';
            const intensity = eq.max_intensity ? `震度${eq.max_intensity}` : '';
            const occurredAt = eq.occurred_at || eq.origin_time || '';
            const at        = occurredAt ? occurredAt.slice(5, 16).replace('T', ' ') : '';
            const dayLabel  = _eqDayLabel(occurredAt);
            const canFocus  = eq.lat != null && eq.lng != null;
            const focusAttrs = canFocus
                ? `data-lat="${eq.lat}" data-lng="${eq.lng}" data-zoom="8" data-name="${name.replace(/"/g, '&quot;')}" data-detail="${mag}${intensity ? ' / ' + intensity : ''}"` : '';

            // 日付区切り（初回またはラベルが変わったとき）
            if (dayLabel && dayLabel !== lastDayLabel) {
                html += `<div class="lac-eq-day-sep">${dayLabel}</div>`;
                lastDayLabel = dayLabel;
            }

            html += `<div class="lac-eq-item${canFocus ? ' lac-eq-clickable' : ''}" ${focusAttrs}>
                <div class="lac-eq-name">${name}</div>
                <div class="lac-eq-meta">${mag}${intensity ? ' / ' + intensity : ''} <small>${at}</small></div>
            </div>`;
        });
        return html;
    }

    function _eqToggleItemHtml(eqCount) {
        const arrow = _eqListExpanded ? '▴' : '▾';
        const listDisplay = _eqListExpanded ? '' : ' style="display:none"';
        return `<div class="lac-item lac-eq-toggle" data-action="eq-toggle"
                     style="cursor:pointer; border-left-color:#e3b341">
                    <span class="lac-text">地震 ${eqCount}件 (3日間) <span class="lac-expand-arrow">${arrow}</span></span>
                </div>
                <div class="lac-eq-list-wrap"${listDisplay}>
                    ${_buildEqListHtml()}
                </div>`;
    }

    // ── 高潮 表示ヘルパー ────────────────────────────────────────────────────

    const _STORM_SURGE_COLOR = {
        emergency: '#7c3aed',
        warning:   '#dc2626',
        advisory:  '#d97706',
    };
    const _STORM_SURGE_LABEL = {
        emergency: '高潮特別警報',
        warning:   '高潮警報',
        advisory:  '高潮注意報',
    };

    function _stormSurgeHtml(ssSection) {
        if (ssSection?.status === 'offline') {
            return `<div class="lac-item lac-offline"><span class="lac-text">高潮情報: 取得失敗</span></div>`;
        }
        if (ssSection && ssSection.evaluated === true) {
            const areas = ssSection.areas || [];
            if (areas.length === 0) {
                return `<div class="lac-item" style="border-left-color:#3fb950">
                            <span class="lac-text">高潮警報なし</span>
                        </div>`;
            }
            // 最上位レベルを取得
            const topArea = areas[0];
            const level   = topArea.level === 'danger' ? 'warning' : 'advisory';
            const color   = _STORM_SURGE_COLOR[level] || '#dc2626';
            const badge   = topArea.detail || _STORM_SURGE_LABEL[level] || '高潮警報';
            const names   = areas.slice(0, 3).map(a => a.label).join(' / ');
            return `
                <div class="lac-item lac-warn" style="border-left-color:${color}">
                    <span class="lac-badge" style="background:${color};color:#fff">${badge}</span>
                    <span class="lac-text"><small>${names}</small></span>
                </div>`;
        }
        return `<div class="lac-item lac-dim"><span class="lac-text">高潮: 確認中</span></div>`;
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
        if (_tileStatuses.kikikuru === 'offline' || kSection?.status === 'offline') {
            return `<div class="lac-item lac-offline"><span class="lac-text">キキクル情報: 取得失敗</span></div>`;
        }
        if (kSection && kSection.evaluated === true) {
            const detected = kSection.summary?.danger_detected;
            if (detected === false) {
                const watchCount = kSection.summary?.watch_area_count ?? 0;
                if (watchCount > 0) {
                    return `<div class="lac-item" style="border-left-color:#e3b341">
                                <span class="lac-text">キキクル: 注意域あり</span>
                            </div>`;
                }
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

    // integrated_dangerous_regions が存在すれば統合表示、なければ従来表示
    function _dangerListHtml(areas, integratedRegions) {
        const regions = integratedRegions && integratedRegions.length
            ? integratedRegions
            : null;
        if (regions) return _integratedDangerListHtml(regions);
        if (!areas || !areas.length) return '';
        let html = `<div class="lac-section-title">危険地域</div><div class="lac-danger-list">`;
        areas.forEach((area, idx) => {
            const canFocus   = area.lat != null && area.lng != null;
            const typeLabel  = area.type === 'kikikuru' && area.hazard
                ? `${_TYPE_LABEL.kikikuru}（${_HAZARD_LABEL[area.hazard] || area.hazard}）`
                : (_TYPE_LABEL[area.type] || area.type || '');
            const levelClass = `lac-danger-${area.level}`;
            const focusAttrs = canFocus ? `data-lat="${area.lat}" data-lng="${area.lng}" data-label="${(area.label || '').replace(/"/g, '&quot;')}"` : '';
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

    function _integratedDangerListHtml(regions) {
        if (!regions || !regions.length) return '';
        let html = `<div class="lac-section-title">危険地域</div><div class="lac-danger-list">`;
        regions.forEach((region, idx) => {
            const canFocus   = region.lat != null && region.lng != null;
            const levelClass = `lac-danger-${region.level}`;
            const focusAttrs = canFocus ? `data-lat="${region.lat}" data-lng="${region.lng}" data-label="${(region.label || '').replace(/"/g, '&quot;')}"` : '';
            const eventsHtml = (region.events || []).map(ev =>
                `<div class="lac-danger-event">${ev.label}</div>`
            ).join('');
            html += `
                <div class="lac-danger-item ${levelClass}${canFocus ? ' lac-danger-clickable' : ''}"
                     ${focusAttrs}>
                    <span class="lac-danger-rank">${idx + 1}</span>
                    <div class="lac-danger-info">
                        <div class="lac-danger-label">${region.label}</div>
                        <div class="lac-danger-events">${eventsHtml}</div>
                    </div>
                </div>`;
        });
        return html + `</div>`;
    }

    // ── 交通スロット再描画 ───────────────────────────────────────────────────

    function _refreshTrafficSlots() {
        window.liveTrainPanel?.renderInto?.('lac-train-slot');
        window.liveRoadTrafficPanel?.renderInto?.('lac-road-slot');
    }

    // ── 強調リング（CircleMarker、4秒後に自動削除） ─────────────────────────

    function _showFocusHighlight(lat, lng) {
        const ring = L.circleMarker([lat, lng], {
            radius:      28,
            color:       '#ff6b35',
            weight:      3,
            fillColor:   '#ff6b35',
            fillOpacity: 0.18,
        }).addTo(liveMap);
        setTimeout(() => {
            try { liveMap.removeLayer(ring); } catch (_) {}
        }, 4000);
    }

    function _bindFocusClicks() {
        if (!_card) return;
        // 危険地域クリック（flyTo + ハイライト + ポップアップ + ログ）
        _card.querySelectorAll('.lac-danger-clickable').forEach(el => {
            el.addEventListener('click', () => {
                const lat   = parseFloat(el.dataset.lat);
                const lng   = parseFloat(el.dataset.lng);
                const label = el.dataset.label || '危険地域';
                if (!isNaN(lat) && !isNaN(lng)) {
                    const zoom = Math.max(liveMap.getZoom(), 8);
                    console.log(`live danger region focus: label=${label} lat=${lat} lng=${lng}`);
                    liveMap.flyTo([lat, lng], zoom);
                    _showFocusHighlight(lat, lng);

                    // ポップアップ: 統合イベント or 種別ラベルを表示
                    const eventEls  = el.querySelectorAll('.lac-danger-event');
                    const typeEl    = el.querySelector('.lac-danger-types');
                    let content     = `<b>${label}</b>`;
                    if (eventEls.length > 0) {
                        const lines = Array.from(eventEls).map(e => e.textContent.trim()).filter(Boolean);
                        if (lines.length) content += `<br><small>${lines.join('<br>')}</small>`;
                    } else if (typeEl) {
                        const t = typeEl.textContent.trim();
                        if (t) content += `<br><small>${t}</small>`;
                    }
                    L.popup().setLatLng([lat, lng]).setContent(content).openOn(liveMap);
                }
            });
        });
        // 地震リストアイテムクリック（DOM に含まれていれば登録）
        _card.querySelectorAll('.lac-eq-clickable').forEach(el => {
            el.addEventListener('click', () => {
                const lat    = parseFloat(el.dataset.lat);
                const lng    = parseFloat(el.dataset.lng);
                const zoom   = parseInt(el.dataset.zoom) || 8;
                const name   = el.dataset.name   || '震源不明';
                const detail = el.dataset.detail || '';
                if (!isNaN(lat) && !isNaN(lng)) {
                    liveMap.setView([lat, lng], zoom);
                    L.popup()
                        .setLatLng([lat, lng])
                        .setContent(`<b>${name}</b><br><small>${detail}</small>`)
                        .openOn(liveMap);
                }
            });
        });
        // パネル最小化ボタン（デスクトップのみ有効）
        const minBtn = _card.querySelector('.lac-minimize-btn');
        if (minBtn) {
            minBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                _minimized = !_minimized;
                _card.classList.toggle('is-minimized', _minimized);
                minBtn.textContent = _minimized ? '＋' : '―';
                minBtn.title = `パネルを${_minimized ? '展開' : '最小化'}`;
            });
        }
        // 地震リスト 展開/折りたたみ
        const toggle   = _card.querySelector('[data-action="eq-toggle"]');
        const listWrap = _card.querySelector('.lac-eq-list-wrap');
        if (toggle && listWrap) {
            toggle.addEventListener('click', () => {
                _eqListExpanded = !_eqListExpanded;
                listWrap.style.display = _eqListExpanded ? '' : 'none';
                const arrow = toggle.querySelector('.lac-expand-arrow');
                if (arrow) arrow.textContent = _eqListExpanded ? '▴' : '▾';
                if (_eqListExpanded) {
                    const cnt = Array.isArray(_fbEqData) ? _fbEqData.length : 0;
                    console.log(`[live-panel] live earthquake list: count=${cnt}`);
                }
            });
        }
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

    // 地震・津波・高潮・summary API を取得してカードを更新する
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

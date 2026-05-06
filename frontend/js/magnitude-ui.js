/**
 * magnitude-ui.js — 地震情報リストパネル
 *
 * 依存: magnitude-layer.js (renderEarthquakePins, focusEarthquakePin)
 *       earthquake-intensity-layer.js (formatJmaIntensity, extractIntensityPoints,
 *                                      renderEarthquakeIntensityMarkers,
 *                                      clearEarthquakeIntensityMarkers)
 */
(function () {
    let _sortMode   = 'newest';
    let _filterMode = 'all';

    let _lastQuakes  = [];
    let _lastUserPos = null;
    let _lastNewIds  = new Set();
    let _expandedQuakeIds = new Set();
    let _currentLocationMatchesExpanded = false;

    // Phase 3/4: 選択中イベントの震度マーカー描画ステータス
    // { eventId, total, mapped, unmapped } | null
    let _currentIntensityStatus = null;

    // ── 震度ランクテーブル ────────────────────────────────────────────────────
    const INTENSITY_RANK = {
        '1': 10,
        '2': 20,
        '3': 30,
        '4': 40,
        '5弱': 50,
        '5-': 50,
        '5強': 55,
        '5+': 55,
        '6弱': 60,
        '6-': 60,
        '6強': 65,
        '6+': 65,
        '7': 70,
    };

    function _getIntensityRank(value) {
        if (value == null) return null;
        const s = String(value).trim();
        return INTENSITY_RANK[s] ?? null;
    }

    function _passesFilter(q, mode) {
        if (mode === 'all') return true;
        const rank = _getIntensityRank(q.max_intensity);
        if (rank == null) return false;
        if (mode === '3')  return rank >= 30;
        if (mode === '4')  return rank >= 40;
        if (mode === '5-') return rank >= 50;
        return true;
    }

    // ── XSS対策 ──────────────────────────────────────────────────────────────
    function _escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, ch => ({
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;',
        }[ch]));
    }

    // ── 距離計算 ──────────────────────────────────────────────────────────────
    function _distanceKm(lat1, lng1, lat2, lng2) {
        lat1 = Number(lat1);
        lng1 = Number(lng1);
        lat2 = Number(lat2);
        lng2 = Number(lng2);
        if (![lat1, lng1, lat2, lng2].every(Number.isFinite)) return null;

        const R = 6371;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLng = (lng2 - lng1) * Math.PI / 180;
        const a =
            Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * Math.PI / 180) *
            Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLng / 2) ** 2;
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    function _hasUsableLocation(userPos) {
        if (userPos?.lat == null || userPos?.lon == null) return false;
        return !!userPos && Number.isFinite(Number(userPos.lat)) && Number.isFinite(Number(userPos.lon));
    }

    function _hasUsableQuakeLocation(q) {
        if (q?.lat == null || q?.lng == null) return false;
        return Number.isFinite(Number(q?.lat)) && Number.isFinite(Number(q?.lng));
    }

    // ── ソート ────────────────────────────────────────────────────────────────
    function _getQuakeDistance(q, userPos) {
        if (!_hasUsableLocation(userPos) || !_hasUsableQuakeLocation(q)) return null;
        return _distanceKm(userPos.lat, userPos.lon, q.lat, q.lng);
    }

    function _compareByNewest(a, b) {
        const ta = new Date(a?.occurred_at || 0).getTime();
        const tb = new Date(b?.occurred_at || 0).getTime();
        const va = Number.isFinite(ta) ? ta : 0;
        const vb = Number.isFinite(tb) ? tb : 0;
        return vb - va;
    }

    function _sortItems(items, mode, userPos) {
        const arr = [...items];
        if (mode === 'nearest' && userPos) {
            return arr.sort((a, b) => {
                const da = _getQuakeDistance(a, userPos);
                const db = _getQuakeDistance(b, userPos);
                if (da == null && db == null) return _compareByNewest(a, b);
                if (da == null) return 1;
                if (db == null) return -1;
                if (da !== db) return da - db;
                return _compareByNewest(a, b);
            });
        }
        return arr.sort(_compareByNewest);
    }

    // ── フォーマット ──────────────────────────────────────────────────────────
    function _formatTime(isoStr) {
        if (!isoStr) return '—';
        try {
            const d = new Date(isoStr);
            return d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' });
        } catch { return '—'; }
    }

    function _formatDate(isoStr) {
        if (!isoStr) return '';
        try {
            const d = new Date(isoStr);
            const today = new Date();
            if (d.toDateString() === today.toDateString()) return '';
            return `${d.getMonth() + 1}/${d.getDate()} `;
        } catch { return ''; }
    }

    function _getCurrentLocationMunicipality() {
        if (typeof currentReverseGeocodeStatus === 'undefined' || currentReverseGeocodeStatus !== 'ready') return null;
        const reverseGeocode = typeof currentReverseGeocode === 'undefined' ? null : currentReverseGeocode;
        const address = String(reverseGeocode?.address || '').trim();
        if (!address) return null;
        const matched = address.match(/(?:[^都道府県]+[都道府県])?((?:[^市区町村]+(?:市|区|町|村))+)/);
        return matched ? matched[1] : null;
    }

    function _normalizeFallbackIntensityAreas(rawAreas) {
        if (!Array.isArray(rawAreas)) return [];
        return rawAreas.map(area => {
            const name = String(area?.name || area?.addr || '').trim();
            const intensity = String(
                area?.intensity ??
                (typeof formatJmaIntensity === 'function' ? formatJmaIntensity(area?.scale) : '') ??
                ''
            ).trim();
            if (!name || !intensity) return null;
            return { name, intensity };
        }).filter(Boolean);
    }

    // ── Phase 1: 有効震度エリア取得（P2P points 優先、fallback intensity_areas） ──
    // P2P形式の points がある場合は観測点レベルで返す。
    // ない場合は既存の intensity_areas にフォールバック。
    function _getEffectiveIntensityAreas(q) {
        // P2P points が利用可能な場合
        if (Array.isArray(q.points) && q.points.length > 0 &&
            typeof extractIntensityPoints === 'function') {
            const pts = extractIntensityPoints(q);
            if (pts && pts.length > 0) {
                return pts.map(p => ({
                    name:      p.addr ? (p.pref ? `${p.pref} ${p.addr}` : p.addr) : p.pref,
                    intensity: p.intensity,
                }));
            }
        }
        // JMA intensity_areas フォールバック
        const intensityAreas = _normalizeFallbackIntensityAreas(q.intensity_areas);
        if (intensityAreas.length) return intensityAreas;
        // P2P/JMA互換の areas フォールバック
        const areas = _normalizeFallbackIntensityAreas(q.areas);
        if (areas.length) return areas;
        return [];
    }

    function _findCurrentLocationIntensity(q, municipality) {
        if (!municipality) return null;
        const areas = _getEffectiveIntensityAreas(q);
        if (!areas.length) return null;
        const target = String(municipality).trim();
        for (const area of areas) {
            const name = String(area?.name || '').trim();
            if (name === target) return String(area.intensity || '');
        }
        for (const area of areas) {
            const name = String(area?.name || '').trim();
            if (name.endsWith(target)) return String(area.intensity || '');
        }
        for (const area of areas) {
            const name = String(area?.name || '').trim();
            if (name.includes(target)) return String(area.intensity || '');
        }
        return null;
    }

    function _getLatestCurrentLocationIntensity(sorted, municipality) {
        if (!municipality || !Array.isArray(sorted)) return null;
        for (const q of sorted) {
            let maxIntensity = null;
            const areas = _getEffectiveIntensityAreas(q);
            for (const area of areas) {
                const areaName = String(area?.name || '').trim();
                if (!areaName) continue;
                if (areaName === municipality || areaName.endsWith(municipality) || areaName.includes(municipality)) {
                    const rank = _getIntensityRank(area.intensity);
                    const maxRank = maxIntensity ? _getIntensityRank(maxIntensity) : 0;
                    if (rank && rank > (maxRank ?? 0)) {
                        maxIntensity = area.intensity;
                    }
                }
            }
            if (maxIntensity) return maxIntensity;
        }
        return null;
    }

    function _getCurrentLocationIntensityMatches(sorted, municipality) {
        if (!municipality || !Array.isArray(sorted)) return [];
        const matches = [];
        for (const q of sorted) {
            let maxIntensity = null;
            const areas = _getEffectiveIntensityAreas(q);
            for (const area of areas) {
                const areaName = String(area?.name || '').trim();
                if (!areaName) continue;
                if (areaName === municipality || areaName.endsWith(municipality) || areaName.includes(municipality)) {
                    const rank = _getIntensityRank(area.intensity);
                    const maxRank = maxIntensity ? _getIntensityRank(maxIntensity) : 0;
                    if (rank && rank > (maxRank ?? 0)) {
                        maxIntensity = area.intensity;
                    }
                }
            }
            if (maxIntensity) {
                matches.push({
                    event: q,
                    intensity: maxIntensity,
                    occurred_at: q.occurred_at,
                    epicenter_name: q.epicenter_name,
                    magnitude: q.magnitude
                });
            }
        }
        return matches;
    }

    function _renderCurrentLocationIntensityMatches(matches, municipality) {
        if (!matches || !matches.length) return '';

        const displayed = matches.slice(0, 3);
        const remaining = matches.length - 3;

        const matchHtml = displayed.map(m => {
            const timeStr = _formatTime(m.occurred_at);
            return `<div class="mq-current-location-match">
                ${_escapeHtml(timeStr)}　${_escapeHtml(municipality)}　震度${_escapeHtml(m.intensity)}　${_escapeHtml(m.epicenter_name)}　M${m.magnitude}
            </div>`;
        }).join('');

        const expandBtn = remaining > 0
            ? `<div class="mq-current-location-expand-btn-row">
                <button class="mq-current-location-expand-btn" type="button" data-expand="current-location-matches">
                    ${_currentLocationMatchesExpanded ? 'さらに隠す' : `さらに表示（+${remaining}件）`}
                </button>
            </div>`
            : '';

        const hiddenMatches = remaining > 0 && _currentLocationMatchesExpanded
            ? matches.slice(3).map(m => {
                const timeStr = _formatTime(m.occurred_at);
                return `<div class="mq-current-location-match mq-current-location-match--hidden">
                    ${_escapeHtml(timeStr)}　${_escapeHtml(municipality)}　震度${_escapeHtml(m.intensity)}　${_escapeHtml(m.epicenter_name)}　M${m.magnitude}
                </div>`;
            }).join('')
            : '';

        return `<div class="mq-current-location-bar">
            <div class="mq-current-location-bar-title">現在地関連の震度</div>
            ${matchHtml}
            ${hiddenMatches}
            ${expandBtn}
        </div>`;
    }

    function _toggleCurrentLocationMatches() {
        _currentLocationMatchesExpanded = !_currentLocationMatchesExpanded;
        _renderList();
    }

    // ── Phase 1: intensity_areas グルーピング（P2P points 対応済み） ───────────
    function _groupIntensityAreas(q) {
        const areas = _getEffectiveIntensityAreas(q);
        const groups = areas.reduce((g, area) => {
            const intensity = String(area?.intensity || '').trim();
            const name      = String(area?.name      || '').trim();
            if (!intensity || !name) return g;
            if (!g[intensity]) g[intensity] = [];
            if (!g[intensity].includes(name)) g[intensity].push(name);
            return g;
        }, {});
        // Phase 1: 震度グループ内を都道府県・地点名の昇順でソート
        Object.values(groups).forEach(names => names.sort((a, b) => a.localeCompare(b, 'ja')));
        return groups;
    }

    function _sortIntensityGroups(groups) {
        return Object.keys(groups).sort((a, b) => {
            const ra = _getIntensityRank(a) ?? 0;
            const rb = _getIntensityRank(b) ?? 0;
            return rb - ra;
        });
    }

    function _renderIntensitySummary(q) {
        const intensityGroups = _groupIntensityAreas(q);
        if (!Object.keys(intensityGroups).length) return '';

        const groups = _sortIntensityGroups(intensityGroups);
        const summaryParts = groups.map(intensity => {
            const count = intensityGroups[intensity].length;
            return `震度${_escapeHtml(intensity)}（${count}）`;
        });

        return `<div class="mq-intensity-summary">地域震度：${summaryParts.join(' / ')}</div>`;
    }

    // ── Phase 1 + Phase 4: 詳細パネル描画 ────────────────────────────────────
    function _renderEarthquakeDetails(q, municipality, expanded) {
        const intensityGroups = _groupIntensityAreas(q);
        const eventId         = String(q.event_id || '');

        // Phase 4: 震度マーカーステータス行
        let statusHtml = '';
        if (_currentIntensityStatus && _currentIntensityStatus.eventId === eventId) {
            const { total, mapped, unmapped } = _currentIntensityStatus;
            if (total > 0) {
                statusHtml = `<div class="mq-intensity-map-status">観測点: ${total}件 / 地図表示: ${mapped}件 / 座標未登録: ${unmapped}件</div>`;
            }
        }

        if (!Object.keys(intensityGroups).length) {
            return `<div class="mq-detail${expanded ? ' mq-detail--visible' : ''}">${statusHtml}<div class="mq-detail-empty">震度詳細情報はありません。</div></div>`;
        }

        const currentLocationIntensity = municipality ? _findCurrentLocationIntensity(q, municipality) : null;
        const groups = _sortIntensityGroups(intensityGroups);
        const groupHtml = groups.map(intensity => {
            const names = intensityGroups[intensity].map(name => `<span class="mq-detail-item">${_escapeHtml(name)}</span>`).join('');
            return `<div class="mq-detail-group">
                    <div class="mq-detail-group-title">震度${_escapeHtml(intensity)}</div>
                    <div class="mq-detail-group-list">${names}</div>
                </div>`;
        }).join('');

        const currentLocationBlock = currentLocationIntensity
            ? `<div class="mq-current-location-detail-card">
                    <div class="mq-current-location-detail-title">現在地周辺</div>
                    <div class="mq-current-location-detail-area">${_escapeHtml(municipality)}：震度${_escapeHtml(currentLocationIntensity)}</div>
                </div>`
            : '';

        return `<div class="mq-detail${expanded ? ' mq-detail--visible' : ''}">
                ${statusHtml}
                ${currentLocationBlock}
                <div class="mq-detail-list">${groupHtml}</div>
            </div>`;
    }

    // ── Phase 3/4: 震度マーカー描画ヘルパー ──────────────────────────────────
    function _renderIntensityMarkersForEvent(eventId) {
        if (typeof renderEarthquakeIntensityMarkers !== 'function') return;
        const quake = _lastQuakes.find(q => String(q.event_id) === eventId);
        if (!quake) return;
        const status = renderEarthquakeIntensityMarkers(quake);
        _currentIntensityStatus = { eventId, ...status };
    }

    function _toggleQuakeDetails(eventId) {
        if (!_expandedQuakeIds.has(eventId)) {
            _expandedQuakeIds.add(eventId);
            // Phase 3/4: 詳細展開時に震度マーカー描画
            _renderIntensityMarkersForEvent(eventId);
        } else {
            _expandedQuakeIds.delete(eventId);
        }
        _renderList();
    }

    function _ageClass(isoStr) {
        if (!isoStr) return '';
        const h = (Date.now() - new Date(isoStr).getTime()) / 3600000;
        if (h < 1) return 'mq-item--1h';
        if (h < 3) return 'mq-item--3h';
        if (h < 6) return 'mq-item--6h';
        return '';
    }

    // ── UI描画 ────────────────────────────────────────────────────────────────
    function _updateFilterBar() {
        const bar = document.getElementById('magnitude-filter-bar');
        if (!bar) return;
        const filters = [
            { mode: 'all',  label: '全件' },
            { mode: '3',    label: '震度3以上' },
            { mode: '4',    label: '震度4以上' },
            { mode: '5-',   label: '震度5弱以上' },
        ];
        bar.innerHTML =
            `<div class="mq-filter-tabs">` +
            filters.map(f =>
                `<button class="mq-filter-button${_filterMode === f.mode ? ' active' : ''}" ` +
                `onclick="magnitudeFilterSet('${f.mode}')">${f.label}</button>`
            ).join('') +
            `</div>`;
    }

    function _updateSortBar(userPos) {
        const bar = document.getElementById('magnitude-sort-bar');
        if (!bar) return;
        const hasLoc = _hasUsableLocation(userPos);
        const hint = !hasLoc
            ? '<div class="mq-sort-hint">現在地を取得すると、近い順で並び替えできます。</div>'
            : '';
        bar.innerHTML =
            `<div class="mq-sort-tabs">` +
            `<button class="mq-sort-button${_sortMode === 'newest' ? ' active' : ''}" onclick="magnitudeSortSet('newest')">新しい順</button>` +
            `<button class="mq-sort-button${_sortMode === 'nearest' ? ' active' : ''}"${hasLoc ? '' : ' disabled'} onclick="magnitudeSortSet('nearest')">近い順</button>` +
            `</div>${hint}`;
    }

    function _renderList() {
        const panel = document.getElementById('magnitude-list');
        if (!panel) return 0;

        _updateFilterBar();
        _updateSortBar(_lastUserPos);

        // フィルタ適用
        const filtered = _lastQuakes.filter(q => _passesFilter(q, _filterMode));
        const visibleNewCount = filtered.filter(q => _lastNewIds.has(String(q.event_id))).length;

        // ピンを同期（フィルタ済みitemsで更新）
        if (typeof renderEarthquakePins === 'function') {
            renderEarthquakePins(filtered, _lastUserPos, _lastNewIds);
        }

        if (typeof updateMagnitudeNewCount === 'function') {
            updateMagnitudeNewCount(visibleNewCount);
        }

        if (!filtered.length) {
            const msg = _lastQuakes.length > 0
                ? '条件に一致する地震情報はありません。'
                : '地震情報なし';
            panel.innerHTML = `<div class="mq-empty">${msg}</div>`;
            return visibleNewCount;
        }

        // 現在地なし時に近い順が残っていたらneweastに戻す
        if (_sortMode === 'nearest' && !_hasUsableLocation(_lastUserPos)) {
            _sortMode = 'newest';
            _updateSortBar(_lastUserPos);
        }

        const sorted = _sortItems(filtered, _sortMode, _lastUserPos);
        const municipality = _getCurrentLocationMunicipality();
        const currentLocationMatches = _getCurrentLocationIntensityMatches(sorted, municipality);
        const currentLocationBarHtml = _renderCurrentLocationIntensityMatches(currentLocationMatches, municipality);

        const html = sorted.map(q => {
            const isNew    = _lastNewIds.has(String(q.event_id));
            const ageClass = _ageClass(q.occurred_at);
            const newClass = isNew ? ' mq-item-new' : '';
            const timeStr  = _formatDate(q.occurred_at) + _formatTime(q.occurred_at);
            const magValue = Number(q.magnitude);
            const mag      = Number.isFinite(magValue) ? `M${magValue.toFixed(1)}` : 'M—';
            const eventId  = String(q.event_id);
            const badge    = isNew ? '<span class="mq-new-badge">NEW</span>' : '';
            let distHtml   = '';
            if (_hasUsableLocation(_lastUserPos) && _hasUsableQuakeLocation(q)) {
                const d = _distanceKm(_lastUserPos.lat, _lastUserPos.lon, q.lat, q.lng);
                distHtml = `<span class="mq-dist">約${Math.round(d)}km</span>`;
            }
            const expanded = _expandedQuakeIds.has(eventId);
            const detailHtml = _renderEarthquakeDetails(q, municipality, expanded);
            const intensitySummaryHtml = _renderIntensitySummary(q);
            return `<div class="mq-item ${ageClass}${newClass}" data-event-id="${_escapeHtml(eventId)}">
                <div class="mq-main">
                    ${badge}<span class="mq-time">${_escapeHtml(timeStr)}</span>
                    <span class="mq-name">${_escapeHtml(q.epicenter_name)}</span>
                    <span class="mq-scale">震度${_escapeHtml(q.max_intensity || '不明')}</span>
                    <span class="mq-mag">${_escapeHtml(mag)}</span>
                    <button class="mq-detail-toggle-btn" type="button" data-event-id="${_escapeHtml(eventId)}">
                        ${expanded ? '閉じる' : '詳細'}
                    </button>
                </div>
                ${distHtml ? `<div class="mq-sub">${distHtml}</div>` : ''}
                ${intensitySummaryHtml}
                ${detailHtml}
            </div>`;
        }).join('');

        panel.innerHTML = `${currentLocationBarHtml}${html}`;
        panel.querySelectorAll('.mq-current-location-expand-btn').forEach(btn => {
            btn.addEventListener('click', ev => {
                ev.stopPropagation();
                _toggleCurrentLocationMatches();
            });
        });
        panel.querySelectorAll('.mq-detail-toggle-btn').forEach(btn => {
            btn.addEventListener('click', ev => {
                ev.stopPropagation();
                _toggleQuakeDetails(String(btn.dataset.eventId));
            });
        });

        panel.querySelectorAll('.mq-item').forEach(el => {
            el.addEventListener('click', () => {
                const id = el.dataset.eventId;
                panel.querySelectorAll('.mq-item--selected').forEach(item => {
                    item.classList.remove('mq-item--selected');
                });
                el.classList.add('mq-item--selected');
                if (typeof focusEarthquakePin === 'function') focusEarthquakePin(id);
                // Phase 3/4: アイテム選択時に震度分布マーカーを描画
                const isNewEvent = !_currentIntensityStatus || _currentIntensityStatus.eventId !== id;
                _renderIntensityMarkersForEvent(id);
                // 詳細が既に展開されていてかつ新規イベントの場合、ステータス行を更新するため再描画
                if (isNewEvent && _expandedQuakeIds.has(id)) {
                    _renderList();
                }
            });
        });

        return visibleNewCount;
    }

    // ── 公開API ───────────────────────────────────────────────────────────────
    window.renderEarthquakeList = function (quakes, userPos, newEventIds = new Set()) {
        _lastQuakes  = quakes;
        _lastUserPos = userPos;
        _lastNewIds  = newEventIds;
        return _renderList();
    };

    window.magnitudeSortSet = function (mode) {
        if (mode === 'nearest' && !_hasUsableLocation(_lastUserPos)) return;
        if (mode !== 'newest' && mode !== 'nearest') return;
        _sortMode = mode;
        _renderList();
    };

    window.magnitudeFilterSet = function (mode) {
        if (!['all', '3', '4', '5-'].includes(mode)) return;
        _filterMode = mode;
        _renderList();
    };

    window.clearEarthquakeList = function () {
        const panel = document.getElementById('magnitude-list');
        if (panel) panel.innerHTML = '';
        const sortBar = document.getElementById('magnitude-sort-bar');
        if (sortBar) sortBar.innerHTML = '';
        const filterBar = document.getElementById('magnitude-filter-bar');
        if (filterBar) filterBar.innerHTML = '';
        _currentIntensityStatus = null;
        // Phase 3/4: パネルクローズ時に震度マーカーをクリア
        if (typeof clearEarthquakeIntensityMarkers === 'function') {
            clearEarthquakeIntensityMarkers();
        }
    };

    // マーカークリック → リストアイテム選択 + スクロール
    window.selectEarthquakeListItem = function (eventId) {
        const panel = document.getElementById('magnitude-list');
        if (!panel) return;
        panel.querySelectorAll('.mq-item--selected').forEach(el => {
            el.classList.remove('mq-item--selected');
        });
        const id = String(eventId);
        const target = panel.querySelector(`.mq-item[data-event-id="${CSS.escape(id)}"]`);
        if (target) {
            target.classList.add('mq-item--selected');
            target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
        // Phase 3/4: マーカークリックからの選択でも震度分布を描画
        const isNewEvent = !_currentIntensityStatus || _currentIntensityStatus.eventId !== id;
        _renderIntensityMarkersForEvent(id);
        if (isNewEvent && _expandedQuakeIds.has(id)) {
            _renderList();
        }
    };

})();

'use strict';

/**
 * location-info-panel.js — 非ナビ時の現在地情報パネル
 *
 * 情報タブの #loc-info-nonnav を管理する。
 * ナビ中は #loc-info-nav（既存の避難先情報）を表示し、このパネルは非表示。
 * 非ナビ時はこのパネルを表示し、#loc-info-nav を非表示にする。
 *
 * 既存処理を流用（新規watchPosition不要）:
 *   _lipUpdate()        ← fetchCurrentLocInfo() からフック
 *   _lipUpdateHazard()  ← _checkCurrentHazard() 結果からフック
 *   _lipUpdateElev()    ← _fetchElevation() 結果からフック
 *   _lipUpdateNavMode() ← _updateNavUI() 末尾からフック
 */

// ── 状態 ─────────────────────────────────────────────────────────
let _lipLastUpdateAt      = null;  // epoch ms
let _lipHazardAssessment  = null;  // {tsunami, flood, ...} or null
let _lipElevation         = null;  // number or null
let _lipLat               = null;
let _lipLon               = null;
let _lipAcc               = null;
let _lipAgeTimer          = null;  // setInterval ID
let _lipRouteSelection    = {
    route: null,
    destination: null,
    selectedRouteIndex: null,
    transportMode: null,
    mode: 'idle',
    routes: [],
    routeColors: [],
    onSelectRouteIndex: null
};
let _lipDestinationReverseGeocode = null;
let _lipDestinationReverseGeocodeStatus = 'idle';
let _lipDestinationReverseGeocodeInFlight = null;
let _lipDestinationReverseGeocodeKey = null;

// ── 起動時1回のみ実行（watchPosition の初回コールバック前にパネルを埋める） ──

/**
 * 起動時に getCurrentPosition で即時1回取得してパネルを初期表示する。
 * watchPosition の初回 fix 待ちによる空表示を解消する。
 * watchPosition が後から来た場合はそちらが自然に上書きする。
 */
function _lipInit() {
    // 起動時のナビモードでパネル表示状態を初期化（setNavMode()が呼ばれないまま
    // navigationMode='browse'が直接セットされるため、ここで明示的に初期化する）
    const initMode = (typeof navigationMode !== 'undefined') ? navigationMode : 'browse';
    _lipUpdateNavMode(initMode);

    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(
        (position) => {
            const lat      = position.coords.latitude;
            const lon      = position.coords.longitude;
            const accuracy = Number(position.coords.accuracy);

            // fetchCurrentLocInfo が標高・ハザード取得とパネル更新を一括で行う
            if (typeof fetchCurrentLocInfo === 'function') {
                fetchCurrentLocInfo(lat, lon, null, accuracy);
            }

            // currentLocation が未設定なら locate ボタンが使えるようにセットする
            if (typeof currentLocation !== 'undefined' && !currentLocation
                    && typeof updateCurrentLocation === 'function') {
                updateCurrentLocation(lat, lon, '現在地', accuracy, false).catch(() => {});
            }
        },
        (err) => {
            console.warn('[lip] 初回位置取得失敗:', err.message);
        },
        { enableHighAccuracy: false, timeout: 10000, maximumAge: 30000 }
    );
}

// ── エントリーポイント（navigation.js からフック） ────────────────

/**
 * 位置更新時に呼ぶ（fetchCurrentLocInfo から）。
 * @param {number} lat
 * @param {number} lon
 * @param {number|null} accuracy  GPS精度 (m)
 */
function _lipUpdate(lat, lon, accuracy) {
    _lipLat = lat;
    _lipLon = lon;
    _lipAcc = accuracy;
    _lipLastUpdateAt = Date.now();
    _lipRenderPosition();
    _lipRenderShelter();
    _lipStartAgeTimer();
    _tideMaybeRefreshDistance(lat, lon);
}

/**
 * ハザード判定結果を受け取る（_checkCurrentHazard の結果からフック）。
 * @param {object|null} assessment  {tsunami, flood, landslide, ...}
 */
function _lipUpdateHazard(assessment) {
    _lipHazardAssessment = assessment || null;
    _lipRenderHazard();
}

/**
 * 標高更新時に呼ぶ（_fetchElevation の結果からフック）。
 * @param {number|null} elev
 */
function _lipUpdateElev(elev) {
    _lipElevation = elev;
    _lipRenderElev();
}

/**
 * ナビモード変更時に呼ぶ（_updateNavUI 末尾からフック）。
 * @param {string} mode  navigationMode の値
 */
function _lipUpdateNavMode(mode) {
    const elNonNav = document.getElementById('loc-info-nonnav');
    const elRoute  = document.getElementById('loc-info-route');
    const elNav    = document.getElementById('loc-info-nav');
    if (!elNonNav || !elRoute || !elNav) return;

    const showRouteSummary = mode === 'route_preview'
        || mode === 'navigation_active'
        || mode === 'navigation_warning'
        || mode === 'navigation_paused'
        || mode === 'navigation_finished';
    elNonNav.style.display = showRouteSummary ? 'none' : '';
    elNav.style.display = 'none';
    _lipRenderRouteSelection(mode);
    if (_lipLastUpdateAt) _lipStartAgeTimer();
}

// ── 内部レンダリング ───────────────────────────────────────────────

function _lipRenderPosition() {
    _lipSet('lip-lat', _lipLat != null ? _lipLat.toFixed(6) : '--');
    _lipSet('lip-lon', _lipLon != null ? _lipLon.toFixed(6) : '--');
    _lipSet('lip-acc', _lipAcc != null ? `±${Math.round(_lipAcc)} m` : '--');
    _lipRenderAge();
    _lipRenderReverseGeocode();
}

function _lipUpdateRouteSelection(payload = {}) {
    if (Object.prototype.hasOwnProperty.call(payload, 'route')) {
        _lipRouteSelection.route = payload.route || null;
    }
    if (Object.prototype.hasOwnProperty.call(payload, 'destination') && payload.destination) {
        _lipRouteSelection.destination = payload.destination;
    }
    if (Object.prototype.hasOwnProperty.call(payload, 'selectedRouteIndex')) {
        _lipRouteSelection.selectedRouteIndex = Number.isFinite(Number(payload.selectedRouteIndex))
            ? Number(payload.selectedRouteIndex)
            : null;
    }
    if (Object.prototype.hasOwnProperty.call(payload, 'transportMode')) {
        _lipRouteSelection.transportMode = payload.transportMode || null;
    }
    if (Object.prototype.hasOwnProperty.call(payload, 'mode') && payload.mode) {
        _lipRouteSelection.mode = payload.mode;
    }
    if (Object.prototype.hasOwnProperty.call(payload, 'routes')) {
        _lipRouteSelection.routes = Array.isArray(payload.routes) ? payload.routes : [];
    }
    if (Object.prototype.hasOwnProperty.call(payload, 'routeColors')) {
        _lipRouteSelection.routeColors = Array.isArray(payload.routeColors) ? payload.routeColors : [];
    }
    if (Object.prototype.hasOwnProperty.call(payload, 'onSelectRouteIndex')) {
        _lipRouteSelection.onSelectRouteIndex = typeof payload.onSelectRouteIndex === 'function'
            ? payload.onSelectRouteIndex
            : null;
    }
    _lipMaybeRequestDestinationReverseGeocode();
    _lipRenderRouteSelection();
}

function _lipClearRouteSelection() {
    _lipRouteSelection = {
        route: null,
        destination: null,
        selectedRouteIndex: null,
        transportMode: null,
        mode: 'idle',
        routes: [],
        routeColors: [],
        onSelectRouteIndex: null
    };
    _lipDestinationReverseGeocode = null;
    _lipDestinationReverseGeocodeStatus = 'idle';
    _lipDestinationReverseGeocodeInFlight = null;
    _lipDestinationReverseGeocodeKey = null;
    _lipRenderRouteSelection('browse');
}

function _lipFormatDistance(distanceMeters) {
    const value = Number(distanceMeters);
    if (!Number.isFinite(value)) return '--';
    if (value >= 1000) return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)} km`;
    return `${Math.round(value)} m`;
}

function _lipFormatDuration(durationSeconds) {
    const value = Number(durationSeconds);
    if (!Number.isFinite(value)) return '--';
    const totalMinutes = Math.round(value / 60);
    if (totalMinutes < 1) return '1分未満';
    if (totalMinutes >= 60) {
        const hours = Math.floor(totalMinutes / 60);
        const minutes = totalMinutes % 60;
        return `${hours}時間${minutes > 0 ? `${minutes}分` : ''}`;
    }
    return `${totalMinutes}分`;
}

function _lipDescribeDestinationHazard(dest) {
    if (!dest) return '';
    if (dest.hazard_safe === true) return '✅ 危険区域外';
    if (dest.hazard_safe === false) return '⚠️ 危険区域内の可能性';
    if (Array.isArray(dest.hazard_types) && dest.hazard_types.length > 0) {
        return `対応ハザード: ${dest.hazard_types.join(', ')}`;
    }
    if (dest.hazard_assessment) return '判定あり';
    return '';
}

function _lipDescribeRouteCaution(route) {
    const parts = [];
    const safety = route?.__pedestrianSafety || null;
    if (safety) {
        if (Array.isArray(safety.dangerousCrossings) && safety.dangerousCrossings.length > 0) {
            const first = safety.dangerousCrossings[0];
            const highway = first?.classification?.highway || '幹線道路';
            parts.push(`${highway} 横断に注意`);
        } else if (safety.status === 'unknown') {
            parts.push('横断安全性を判定できません');
        }
    }
    const riskNotes = route?.__riskSummary?.risk_summary?.notes || [];
    riskNotes.forEach(note => parts.push(note));
    return parts.join(' / ');
}

function _lipRouteMetric(route, key) {
    const summary = route?.summary || null;
    if (key === 'distance') {
        return Number(summary?.totalDistance ?? route?.totalDistance);
    }
    if (key === 'time') {
        return Number(summary?.totalTime ?? route?.totalTime);
    }
    return NaN;
}

function _lipResolveRouteBadge(route, routeIndex, routes) {
    if (route?.__displayLabel) {
        return route.__displayLabel.replace('ルート', '');
    }
    const routeList = Array.isArray(routes) ? routes : [];
    if (routeList.length === 0) return '候補';
    let shortestIndex = 0;
    let shortestValue = Infinity;
    routeList.forEach((candidate, index) => {
        const timeValue = _lipRouteMetric(candidate, 'time');
        const distanceValue = _lipRouteMetric(candidate, 'distance');
        const metric = Number.isFinite(timeValue) ? timeValue : distanceValue;
        if (Number.isFinite(metric) && metric < shortestValue) {
            shortestValue = metric;
            shortestIndex = index;
        }
    });
    const safety = route?.__pedestrianSafety || null;
    if (routeIndex === 0) return '推奨';
    if (routeIndex === shortestIndex) return '最短';
    if (safety?.status === 'safe') return '回避';
    if (safety?.status === 'unsafe') return '注意';
    return '候補';
}

function _lipRenderRouteSelector(transportMode) {
    const section = document.getElementById('lip-route-selector-section');
    const container = document.getElementById('lip-route-options');
    if (!section || !container) return;

    const routeList = Array.isArray(_lipRouteSelection.routes) ? _lipRouteSelection.routes : [];
    const onSelect = typeof _lipRouteSelection.onSelectRouteIndex === 'function'
        ? _lipRouteSelection.onSelectRouteIndex
        : null;
    if (routeList.length <= 1 || !onSelect) {
        section.style.display = 'none';
        container.innerHTML = '';
        _lipRenderRouteRiskInfo();
        return;
    }

    section.style.display = '';
    container.innerHTML = '';
    routeList.forEach((candidateRoute, routeIndex) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'route-option-button';
        if (routeIndex === _lipRouteSelection.selectedRouteIndex) {
            button.classList.add('active');
        }
        const color = _lipRouteSelection.routeColors[routeIndex]
            || (typeof getRouteColorByIndex === 'function' ? getRouteColorByIndex(routeIndex) : '#1e88e5');
        const distance = _lipFormatDistance(_lipRouteMetric(candidateRoute, 'distance'));
        const duration = _lipFormatDuration(_lipRouteMetric(candidateRoute, 'time'));
        const badge = _lipResolveRouteBadge(candidateRoute, routeIndex, routeList);
        const modeLabel = transportMode === 'walking' ? '徒歩' : transportMode === 'driving' ? '車' : '';
        button.innerHTML = `
            <span class="route-color-chip" style="background: ${color};"></span>
            候補${routeIndex + 1}
            <span style="margin-left:6px;font-size:11px;color:#64748b;">${distance} / ${duration}${modeLabel ? ` / ${modeLabel}` : ''}</span>
            <span style="margin-left:auto;font-size:11px;font-weight:700;color:${routeIndex === _lipRouteSelection.selectedRouteIndex ? '#fff' : '#1d4ed8'};">${badge}</span>
        `;
        button.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            onSelect(routeIndex);
        });
        container.appendChild(button);
    });

    _lipRenderRouteRiskInfo();
}

function _lipRenderRouteRiskInfo() {
    const el = document.getElementById('lip-route-risk-info');
    const section = document.getElementById('lip-route-risk-section');
    if (!el) return;
    el.innerHTML = '';
    if (section) section.style.display = 'none';

    const idx = _lipRouteSelection.selectedRouteIndex;
    const routes = _lipRouteSelection.routes;
    if (!Array.isArray(routes) || idx == null || idx < 0 || idx >= routes.length) return;
    const route = routes[idx];
    if (!route) return;

    const riskSummary = route.__riskSummary;
    if (!riskSummary) {
        const msg = document.createElement('div');
        msg.className = 'route-risk-block safe';
        msg.style.cssText = 'color:#9e9e9e;font-size:12px;';
        msg.textContent = 'ルートリスク情報を取得できませんでした';
        el.appendChild(msg);
        if (section) section.style.display = '';
        return;
    }

    if (typeof _appendRouteRiskBlock === 'function') {
        _appendRouteRiskBlock(el, route);
        if (section) section.style.display = '';
    }
}

function _lipResolveElevationGain(route, dest) {
    const directGain = Number(dest?.elevation_gain);
    if (Number.isFinite(directGain)) {
        return `+${directGain.toFixed(1)} m`;
    }
    const currentElev = Number(_lipElevation);
    const destElev = Number(dest?.elevation);
    if (Number.isFinite(currentElev) && Number.isFinite(destElev)) {
        const diff = destElev - currentElev;
        return `${diff >= 0 ? '+' : ''}${diff.toFixed(1)} m`;
    }
    return '--';
}

function _lipDescribeCurrentHazardSummary() {
    const assessment = _lipHazardAssessment;
    if (!assessment || typeof assessment !== 'object') return '';
    const labels = {
        tsunami: '津波',
        flood: '洪水',
        inland_flood: '内水氾濫',
        inland_flood_l2: '内水氾濫',
        storm_surge: '高潮',
        landslide: '土砂災害'
    };
    const inside = [];
    let hasUnknown = false;
    Object.entries(assessment).forEach(([key, value]) => {
        const status = typeof value === 'string' ? value : value?.status;
        if (status === 'inside') inside.push(labels[key] || key);
        if (status === 'unknown') hasUnknown = true;
    });
    if (inside.length > 0) return `⚠️ ${inside.join('・')} に注意`;
    if (hasUnknown) return '❓ 一部未判定';
    return '✅ 危険区域外';
}

function _lipDestinationKey(dest) {
    if (!dest) return null;
    const lat = Number(dest.lat);
    const lon = Number(dest.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
    return `${lat.toFixed(6)},${lon.toFixed(6)}`;
}

function _lipResolveDestinationAddress(dest) {
    if (_lipDestinationReverseGeocode?.address) return _lipDestinationReverseGeocode.address;
    if (dest?.address) return dest.address;
    if (dest?.display_name) return dest.display_name;
    return '';
}

function _lipResolveDestinationPostcode(dest) {
    if (_lipDestinationReverseGeocode?.postcode) return _lipDestinationReverseGeocode.postcode;
    if (dest?.postcode) return dest.postcode;
    return '';
}

function _lipSetOptionalRow(id, text) {
    const el = document.getElementById(id);
    const row = el ? el.closest('.lip-row') : null;
    if (!el || !row) return;
    const hasValue = text !== null && text !== undefined && String(text).trim() !== '' && String(text).trim() !== '--';
    row.style.display = hasValue ? '' : 'none';
    if (hasValue) {
        el.textContent = text;
    }
}

function _lipMaybeRequestDestinationReverseGeocode() {
    const destination = _lipRouteSelection.destination || navDestination || navOriginalDestination || userDestination || null;
    const key = _lipDestinationKey(destination);
    if (!key) {
        _lipDestinationReverseGeocode = null;
        _lipDestinationReverseGeocodeStatus = 'idle';
        _lipDestinationReverseGeocodeInFlight = null;
        _lipDestinationReverseGeocodeKey = null;
        return null;
    }
    if (_lipDestinationReverseGeocodeKey === key && (
        _lipDestinationReverseGeocodeStatus === 'ready'
        || _lipDestinationReverseGeocodeStatus === 'unknown'
        || _lipDestinationReverseGeocodeStatus === 'loading'
    )) {
        return _lipDestinationReverseGeocodeInFlight;
    }
    const lat = Number(destination.lat);
    const lon = Number(destination.lon);
    _lipDestinationReverseGeocodeKey = key;
    _lipDestinationReverseGeocodeStatus = 'loading';
    _lipDestinationReverseGeocodeInFlight = (async () => {
        try {
            const response = await apiFetch(`/reverse-geocode?lat=${lat}&lon=${lon}`);
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || `HTTP ${response.status}`);
            }
            _lipDestinationReverseGeocode = {
                address: data.address || null,
                postcode: data.postcode || null,
                source: data.source || 'unknown',
                lat: data.lat,
                lon: data.lon
            };
            _lipDestinationReverseGeocodeStatus = data.address ? 'ready' : 'unknown';
        } catch (error) {
            console.warn('[lip] destination reverse geocode failed:', error);
            _lipDestinationReverseGeocode = null;
            _lipDestinationReverseGeocodeStatus = 'error';
        } finally {
            _lipDestinationReverseGeocodeInFlight = null;
            _lipRenderRouteSelection();
        }
        return _lipDestinationReverseGeocode;
    })();
    return _lipDestinationReverseGeocodeInFlight;
}

function _lipRenderRouteSelection(modeOverride = null) {
    const container = document.getElementById('loc-info-route');
    if (!container) return;

    const activeMode = modeOverride || navigationMode || _lipRouteSelection.mode || 'browse';
    const isPreview = activeMode === 'route_preview';
    const isNavigating = activeMode === 'navigation_active'
        || activeMode === 'navigation_warning'
        || activeMode === 'navigation_paused'
        || activeMode === 'navigation_finished';
    const shouldShow = isPreview || isNavigating;
    container.style.display = shouldShow ? '' : 'none';
    if (!shouldShow) return;

    const route = _lipRouteSelection.route || navActiveRoute || null;
    const destination = _lipRouteSelection.destination || navDestination || navOriginalDestination || userDestination || null;
    const transportMode = _lipRouteSelection.transportMode || document.getElementById('transportMode')?.value || null;
    const address = _lipResolveDestinationAddress(destination);
    const postcode = _lipResolveDestinationPostcode(destination);
    const currentElev = Number(_lipElevation);
    const destElev = Number(destination?.elevation);
    const elevDiff = _lipResolveElevationGain(route, destination);

    _lipSet('lip-dest-name', destination?.name || '目的地未設定');
    _lipSetOptionalRow('lip-dest-address', address || (
        _lipDestinationReverseGeocodeStatus === 'loading' ? '取得中...' : ''
    ));
    _lipSetOptionalRow('lip-dest-postcode', postcode);

    const attributionRow = document.getElementById('lip-dest-address-attribution-row');
    if (attributionRow) {
        attributionRow.style.display = address ? '' : 'none';
    }

    _lipRenderRouteSelector(transportMode);
    _lipSetOptionalRow('lip-current-elev', Number.isFinite(currentElev) ? `${Math.round(currentElev)} m` : '');
    _lipSetOptionalRow('lip-dest-elev', Number.isFinite(destElev) ? `${Math.round(destElev)} m` : '');
    _lipSetOptionalRow('lip-elev-diff', elevDiff);
    _lipSetOptionalRow('lip-current-hazard-summary', _lipDescribeCurrentHazardSummary());
    _lipSetOptionalRow('lip-dest-hazard', _lipDescribeDestinationHazard(destination));
    _lipSetOptionalRow('lip-route-caution', _lipDescribeRouteCaution(route));
}

function _lipRenderElev() {
    _lipSet('lip-elev', _lipElevation != null ? `${Math.round(_lipElevation)} m` : '--');
    _lipSet('lip-cs-elev', _lipElevation != null ? `${Math.round(_lipElevation)} m` : '--');
    _lipRenderRouteSelection();
}

function _lipRenderReverseGeocode() {
    const addressEl = document.getElementById('lip-address');
    const postcodeEl = document.getElementById('lip-postcode');
    const attributionEl = document.getElementById('lip-address-attribution');
    if (!addressEl || !postcodeEl || !attributionEl) return;

    if (currentReverseGeocodeStatus === 'disabled') {
        addressEl.textContent = '無効';
        postcodeEl.textContent = '—';
        attributionEl.style.display = 'none';
        return;
    }
    if (currentReverseGeocodeStatus === 'loading') {
        addressEl.textContent = '取得中...';
        postcodeEl.textContent = '取得中...';
        attributionEl.style.display = '';
        return;
    }
    if (currentReverseGeocodeStatus === 'error') {
        addressEl.textContent = '取得失敗';
        postcodeEl.textContent = '—';
        attributionEl.style.display = '';
        return;
    }
    if (currentReverseGeocode && currentReverseGeocode.address) {
        addressEl.textContent = currentReverseGeocode.address;
        postcodeEl.textContent = currentReverseGeocode.postcode || '—';
        attributionEl.style.display = '';
        return;
    }
    if (currentReverseGeocodeStatus === 'unknown') {
        addressEl.textContent = '不明';
        postcodeEl.textContent = '—';
        attributionEl.style.display = '';
        return;
    }
    addressEl.textContent = '--';
    postcodeEl.textContent = '--';
    attributionEl.style.display = 'none';
}

function _lipRenderCompactSummary() {
    _lipSet('lip-cs-elev', _lipElevation != null ? `${Math.round(_lipElevation)} m` : '--');
    _lipSet('lip-cs-hazard', _lipDescribeCurrentHazardSummary() || '--');
    const shelterEl = document.getElementById('lip-nearest-shelter');
    _lipSet('lip-cs-shelter', shelterEl ? shelterEl.textContent : '--');
}

function _lipRenderHazard() {
    const a = _lipHazardAssessment;

    // 津波
    _lipSetHazard('lip-h-tsunami', a ? a.tsunami : undefined, {
        insideLabel: '⚠️ 該当',
        outsideLabel: '✅ 非該当',
    });

    // 洪水（flood / inland_flood / inland_flood_l2 / storm_surge いずれか）
    const floodVal = a
        ? (a.flood ?? a.inland_flood ?? a.inland_flood_l2 ?? a.storm_surge)
        : undefined;
    _lipSetHazard('lip-h-flood', floodVal, {
        insideLabel: '⚠️ 高リスク',
        outsideLabel: '✅ 域外',
    });

    // 土砂
    _lipSetHazard('lip-h-landslide', a ? a.landslide : undefined, {
        insideLabel: '⚠️ 警戒域',
        outsideLabel: '✅ 域外',
    });
    _lipRenderCompactSummary();
    _lipRenderRouteSelection();
}

function _lipSetHazard(id, value, { insideLabel, outsideLabel }) {
    const el = document.getElementById(id);
    if (!el) return;

    if (value === undefined || value === null) {
        el.textContent = '--';
        el.className = 'lip-row-value';
        return;
    }

    const inside = (typeof value === 'string' && value === 'inside') ||
                   (value && typeof value === 'object' && value.status === 'inside');
    const unknown = value === 'unknown' ||
                    (value && typeof value === 'object' && value.status === 'unknown');

    if (inside) {
        el.textContent = insideLabel;
        el.className = 'lip-row-value lip-hazard-danger';
    } else if (unknown) {
        el.textContent = '? 不明';
        el.className = 'lip-row-value lip-hazard-unknown';
    } else {
        el.textContent = outsideLabel;
        el.className = 'lip-row-value lip-hazard-safe';
    }
}

function _lipRenderShelter() {
    const el = document.getElementById('lip-nearest-shelter');
    if (!el) return;

    // destinations は state.js で宣言されたグローバル配列
    if (typeof destinations === 'undefined' || destinations.length === 0) {
        el.textContent = '未検索';
        return;
    }

    // 直線距離が最小のものを選ぶ
    const nearest = destinations.reduce((a, b) => {
        const da = (a.distance != null) ? a.distance : Infinity;
        const db = (b.distance != null) ? b.distance : Infinity;
        return da < db ? a : b;
    });

    if (!nearest) {
        el.textContent = '--';
        return;
    }

    const name = nearest.name || '候補';
    const dist = nearest.distance != null ? `${Math.round(nearest.distance)} m` : '- m';
    const dir  = (_lipLat != null && nearest.lat != null)
        ? _lipBearingLabel(_lipLat, _lipLon, nearest.lat, nearest.lon)
        : '';

    el.textContent = dir ? `${name}（${dist} ${dir}）` : `${name}（${dist}）`;
    _lipSet('lip-cs-shelter', el.textContent);
}

function _lipRenderAge() {
    const el = document.getElementById('lip-age');
    if (!el || _lipLastUpdateAt == null) return;
    const sec = Math.round((Date.now() - _lipLastUpdateAt) / 1000);
    el.textContent = sec < 5 ? 'たった今' : `${sec}秒前`;
}

// ── タイマー ───────────────────────────────────────────────────────

function _lipStartAgeTimer() {
    if (_lipAgeTimer) return;
    _lipAgeTimer = setInterval(_lipRenderAge, 5000);
}

function _lipStopAgeTimer() {
    if (_lipAgeTimer) {
        clearInterval(_lipAgeTimer);
        _lipAgeTimer = null;
    }
}

// ── ユーティリティ ────────────────────────────────────────────────

function _lipSet(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
}

function _lipHaversineMeters(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180;
    const dLat = (lat2 - lat1) * toRad;
    const dLon = (lon2 - lon1) * toRad;
    const a = Math.sin(dLat / 2) ** 2
        + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
    return 6371000 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function _shouldFetchReverseGeocode(lat, lon) {
    if (getRuntimeConfigValue('geocode.enabled', true) === false) {
        currentReverseGeocodeStatus = 'disabled';
        _lipRenderReverseGeocode();
        return false;
    }
    const minMoveDistance = Number(getRuntimeConfigValue('geocode.min_move_distance_m', 50));
    if (!currentReverseGeocodeLastFetchPos) {
        return true;
    }
    const moved = _lipHaversineMeters(
        currentReverseGeocodeLastFetchPos.lat,
        currentReverseGeocodeLastFetchPos.lon,
        lat,
        lon,
    );
    return moved >= minMoveDistance;
}

async function requestCurrentLocationReverseGeocode(lat, lon) {
    if (!_shouldFetchReverseGeocode(lat, lon)) {
        return currentReverseGeocode;
    }
    if (currentReverseGeocodeInFlight) {
        return currentReverseGeocodeInFlight;
    }

    currentReverseGeocodeStatus = 'loading';
    _lipRenderReverseGeocode();

    currentReverseGeocodeInFlight = (async () => {
        try {
            const response = await apiFetch(`/reverse-geocode?lat=${lat}&lon=${lon}`);
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || `HTTP ${response.status}`);
            }

            currentReverseGeocode = {
                address: data.address || null,
                postcode: data.postcode || null,
                source: data.source || 'unknown',
                lat: data.lat,
                lon: data.lon,
            };
            currentReverseGeocodeLastFetchPos = { lat, lon };
            currentReverseGeocodeStatus = data.address ? 'ready' : 'unknown';
            _lipRenderReverseGeocode();
            return currentReverseGeocode;
        } catch (error) {
            console.warn('[reverse-geocode] fetch failed:', error);
            currentReverseGeocodeStatus = 'error';
            _lipRenderReverseGeocode();
            return null;
        } finally {
            currentReverseGeocodeInFlight = null;
        }
    })();

    return currentReverseGeocodeInFlight;
}

/** 2点間の方位を8方位の日本語ラベルで返す。 */
function _lipBearingLabel(lat1, lon1, lat2, lon2) {
    const toRad = Math.PI / 180;
    const dLon  = (lon2 - lon1) * toRad;
    const lat1R = lat1 * toRad;
    const lat2R = lat2 * toRad;
    const y     = Math.sin(dLon) * Math.cos(lat2R);
    const x     = Math.cos(lat1R) * Math.sin(lat2R)
                - Math.sin(lat1R) * Math.cos(lat2R) * Math.cos(dLon);
    const deg   = (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
    const dirs  = ['北', '北東', '東', '南東', '南', '南西', '西', '北西'];
    return dirs[Math.round(deg / 45) % 8];
}

// ── 天体情報 ──────────────────────────────────────────────────────

const _ASTRO_CACHE_TTL_MS = 10 * 60 * 1000;  // 10分
let _astroCache = null;  // { lat, lon, data, fetchedAt }

async function _astroFetch(lat, lon) {
    const now = Date.now();
    if (
        _astroCache &&
        Math.abs(_astroCache.lat - lat) < 0.05 &&
        Math.abs(_astroCache.lon - lon) < 0.05 &&
        now - _astroCache.fetchedAt < _ASTRO_CACHE_TTL_MS
    ) {
        return _astroCache.data;
    }
    try {
        const res = await fetch(`/api/astro/current?lat=${lat}&lon=${lon}`);
        if (!res.ok) return null;
        const data = await res.json();
        _astroCache = { lat, lon, data, fetchedAt: now };
        return data;
    } catch {
        return null;
    }
}

function _astroFmtTime(isoStr) {
    if (!isoStr) return '--';
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) return '--';
    const h = String(d.getHours()).padStart(2, '0');
    const m = String(d.getMinutes()).padStart(2, '0');
    return `${h}:${m}`;
}

/**
 * 月齢から月の形を表すインライン SVG を生成する。
 * phase: Astral の moon phase 値（0〜28、0/28=新月、14=満月）
 *
 * 描画方式:
 *   - 暗い円（月盤）を描く
 *   - 輝面部分だけ明るいパスで上書きする
 *   - 明暗の境界（朔望線）は x 軸方向に変化する楕円弧で表現
 */
function _astroMoonSvg(phase) {
    const r  = 7;
    const sz = r * 2 + 2;
    const cx = sz / 2, cy = sz / 2;
    const dark  = '#4b5563';
    const light = '#fef9c3';
    const base  = `width="${sz}" height="${sz}" viewBox="0 0 ${sz} ${sz}"` +
                  ` style="display:inline-block;vertical-align:middle;margin-right:3px"`;

    const p = ((phase % 28) + 28) % 28 / 28; // 0..1 (0/1=新月, 0.5=満月)

    if (p < 0.03 || p > 0.97) {
        return `<svg ${base}><circle cx="${cx}" cy="${cy}" r="${r}" fill="${dark}" stroke="#6b7280" stroke-width="0.5"/></svg>`;
    }
    if (p > 0.47 && p < 0.53) {
        return `<svg ${base}><circle cx="${cx}" cy="${cy}" r="${r}" fill="${light}" stroke="#9ca3af" stroke-width="0.5"/></svg>`;
    }

    // 朔望線の楕円 x 半径: 新月→r、上弦→0、満月→-r、下弦→0、新月→r
    const termRx   = r * Math.cos(p * Math.PI * 2);
    const termSwp  = termRx > 0 ? 0 : 1;   // 凹（三日月）= 0、凸（十三夜）= 1
    const absRx    = Math.max(Math.abs(termRx), 0.5);
    const litSwp   = p < 0.5 ? 1 : 0;      // 上弦側(右)=1、下弦側(左)=0

    const path = `M ${cx} ${cy - r} A ${r} ${r} 0 0 ${litSwp} ${cx} ${cy + r} A ${absRx} ${r} 0 0 ${termSwp} ${cx} ${cy - r}`;

    return `<svg ${base}>
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="${dark}" stroke="#6b7280" stroke-width="0.5"/>
        <path d="${path}" fill="${light}"/>
    </svg>`;
}

async function _astroUpdate(lat, lon) {
    const data = await _astroFetch(lat, lon);
    const section = document.getElementById('lip-astro-section');
    if (!section) return;

    if (!data) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    _lipSet('lip-astro-sunrise', _astroFmtTime(data.sunrise));
    _lipSet('lip-astro-sunset',  _astroFmtTime(data.sunset));
    _astroSetOptionalTime('lip-astro-moonrise-row', 'lip-astro-moonrise', data.moonrise);
    _astroSetOptionalTime('lip-astro-moonset-row', 'lip-astro-moonset', data.moonset);

    const moonEl = document.getElementById('lip-astro-moon');
    if (moonEl) {
        moonEl.innerHTML = `${_astroMoonSvg(data.moon_phase)}${data.moon_phase} / ${data.moon_label}`;
    }

    const noteEl = document.getElementById('lip-astro-note');
    if (noteEl) {
        if (data.moon_label === '新月') {
            noteEl.innerHTML = '<span style="color:#92400e;background:#fef3c7;border-radius:3px;padding:0 5px;font-size:10px">暗所注意</span>';
            noteEl.style.display = '';
        } else if (data.moon_label === '満月') {
            noteEl.innerHTML = '<span style="color:#166534;background:#dcfce7;border-radius:3px;padding:0 5px;font-size:10px">視界良好</span>';
            noteEl.style.display = '';
        } else {
            noteEl.style.display = 'none';
        }
    }
}

function _astroSetOptionalTime(rowId, valueId, isoStr) {
    const row = document.getElementById(rowId);
    const value = document.getElementById(valueId);
    const label = _astroFmtTime(isoStr);
    if (!row || !value) return;

    if (!isoStr || label === '--') {
        row.style.display = 'none';
        return;
    }

    value.textContent = label;
    row.style.display = '';
}

// ── 潮汐情報 ──────────────────────────────────────────────────────

const _TIDE_CACHE_TTL_MS = 10 * 60 * 1000;
const _TIDE_DIST_UPDATE_M = 100;
let _tideCache = null;          // { lat, lon, data, fetchedAt }
let _tideDistLastPos = null;    // { lat, lon }
let _selectedTideStation = null; // {id, name, lat, lon} or null

async function _tideFetch(lat, lon) {
    const now = Date.now();
    if (
        _tideCache &&
        Math.abs(_tideCache.lat - lat) < 0.05 &&
        Math.abs(_tideCache.lon - lon) < 0.05 &&
        now - _tideCache.fetchedAt < _TIDE_CACHE_TTL_MS
    ) {
        return _tideCache.data;
    }
    const res = await fetch(`/api/tide/current?lat=${lat}&lon=${lon}`);
    if (!res.ok) return null;
    const data = await res.json();
    _tideCache = { lat, lon, data, fetchedAt: now };
    return data;
}

function _tideFmtCm(value) {
    return value == null ? '--' : `${Math.round(Number(value))} cm`;
}

function _tideFmtRemain(minutes) {
    const m = Math.round(Number(minutes));
    if (!Number.isFinite(m) || m < 0) return '';
    const h = Math.floor(m / 60);
    const min = m % 60;
    if (h === 0) return `あと${min}分`;
    if (min === 0) return `あと${h}時間`;
    return `あと${h}時間${min}分`;
}

function _tideFmtExtreme(value) {
    if (!value || !value.time) return '--';
    const d = new Date(value.time);
    if (isNaN(d.getTime())) return '--';
    const time = d.toLocaleTimeString('ja-JP', {
        hour: '2-digit',
        minute: '2-digit',
        timeZone: 'Asia/Tokyo',
    });
    const cm = _tideFmtCm(value.tide_cm);
    const remain = Number.isFinite(Number(value.remaining_minutes))
        ? `  ${_tideFmtRemain(value.remaining_minutes)}`
        : '';
    return `${time}  ${cm}${remain}`;
}

function _tideFmtDistance(meters) {
    if (!Number.isFinite(meters)) return '';
    if (meters >= 1000) {
        const km = Math.round(meters / 100) / 10;
        return `  ${km} km`;
    }
    return `  ${Math.round(meters / 100) * 100} m`;
}

function _tideRenderStation(lat, lon) {
    if (!_tideCache || !_tideCache.data || _tideCache.data.available === false) return;
    const station = _tideCache.data.station || {};
    let distLabel = '';
    if (
        lat != null && lon != null &&
        Number.isFinite(station.lat) && Number.isFinite(station.lon)
    ) {
        const meters = _lipHaversineMeters(lat, lon, station.lat, station.lon);
        distLabel = _tideFmtDistance(meters);
    } else if (station.distance_km != null) {
        distLabel = `  ${station.distance_km} km`;
    }
    _lipSet('lip-tide-station', `${station.name || station.id || '--'}${distLabel}`);
}

function _tideRender(data) {
    const section = document.getElementById('lip-tide-section');
    if (!section) return;

    if (!data || data.available === false) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    _lipSet('lip-tide-current', _tideFmtCm(data.current_tide_cm));
    _lipSet('lip-tide-high', _tideFmtExtreme(data.next_high_tide));
    _lipSet('lip-tide-low', _tideFmtExtreme(data.next_low_tide));
    _tideRenderStation(_lipLat, _lipLon);
    _tideDistLastPos = (_lipLat != null && _lipLon != null)
        ? { lat: _lipLat, lon: _lipLon } : null;

    // 選択地点が確定している場合グラフを更新
    const stationId = _selectedTideStation
        ? _selectedTideStation.id
        : (data.station ? data.station.id : null);
    if (stationId) _tideGraphUpdate(stationId);
}

function _tideMaybeRefreshDistance(lat, lon) {
    if (!_tideCache || !_tideCache.data || _tideCache.data.available === false) return;
    if (lat == null || lon == null) return;
    if (_tideDistLastPos) {
        const moved = _lipHaversineMeters(_tideDistLastPos.lat, _tideDistLastPos.lon, lat, lon);
        if (moved < _TIDE_DIST_UPDATE_M) return;
    }
    _tideRenderStation(lat, lon);
    _tideDistLastPos = { lat, lon };
}

async function _tideUpdate(lat, lon) {
    // マーカーで地点選択中はその地点の lat/lon を使う
    const fetchLat = _selectedTideStation ? _selectedTideStation.lat : lat;
    const fetchLon = _selectedTideStation ? _selectedTideStation.lon : lon;
    try {
        _tideRender(await _tideFetch(fetchLat, fetchLon));
    } catch (err) {
        console.warn('[tide] fetch error:', err);
        _tideRender(null);
    }
}

/** マーカータップ時に外部から呼ばれる — 地点を切り替えてサマリ＋グラフを再取得 */
async function _tideSetStation(station) {
    _selectedTideStation = station;
    _tideCache = null; // キャッシュをクリアして強制再取得
    if (typeof tideMarkersSetSelected === 'function') {
        tideMarkersSetSelected(station.id);
    }
    try {
        _tideRender(await _tideFetch(station.lat, station.lon));
    } catch (err) {
        console.warn('[tide] station fetch error:', err);
        _tideRender(null);
    }
}

/** 全国表示を閉じたときに外部から呼ばれる — 現在地最寄りへ戻す */
function _tideResetToNearest() {
    _selectedTideStation = null;
    _tideCache = null;
    if (_lipLat != null && _lipLon != null) {
        _tideUpdate(_lipLat, _lipLon);
    }
}

// ── 潮位グラフ ────────────────────────────────────────────────────

let _tideGraphCache = {};  // stationId+date → {records, extremes}

async function _tideGraphFetch(stationId) {
    // 現在JSTから24時間分：当日＋翌日を取得して結合する
    const nowMs = Date.now();
    const jstOffMs = 9 * 3600 * 1000;
    const todayJst    = new Date(nowMs + jstOffMs).toISOString().slice(0, 10);
    const tomorrowJst = new Date(nowMs + jstOffMs + 24 * 3600 * 1000).toISOString().slice(0, 10);

    const fetchDay = async (date) => {
        const key = `${stationId}|${date}`;
        if (_tideGraphCache[key]) return _tideGraphCache[key];
        const res = await fetch(`/api/tide/hourly?station=${encodeURIComponent(stationId)}&date=${date}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _tideGraphCache[key] = data;
        return data;
    };

    const [todayData, tomorrowData] = await Promise.all([
        fetchDay(todayJst).catch(() => null),
        todayJst !== tomorrowJst ? fetchDay(tomorrowJst).catch(() => null) : Promise.resolve(null),
    ]);

    return {
        records: [
            ...(todayData?.records   || []),
            ...(tomorrowData?.records || []),
        ],
        extremes: {
            high_tides: [
                ...(todayData?.extremes?.high_tides   || []),
                ...(tomorrowData?.extremes?.high_tides || []),
            ],
            low_tides: [
                ...(todayData?.extremes?.low_tides   || []),
                ...(tomorrowData?.extremes?.low_tides || []),
            ],
        },
    };
}

async function _tideGraphUpdate(stationId) {
    const canvas = document.getElementById('lip-tide-graph');
    if (!canvas) return;
    const data = await _tideGraphFetch(stationId);
    _tideGraphDraw(canvas, data);
}

function _tideGraphDraw(canvas, data) {
    // canvas の論理ピクセルを表示幅に合わせる
    const rect = canvas.getBoundingClientRect();
    if (rect.width > 0) canvas.width = Math.round(rect.width);
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    const PAD = { top: 10, right: 10, bottom: 22, left: 36 };

    ctx.clearRect(0, 0, W, H);

    // 横軸: 現在時刻 → +24時間
    const now  = Date.now();
    const tMin = now;
    const tMax = now + 24 * 3600 * 1000;

    const records = data && data.records && data.records.length > 0 ? data.records : null;
    if (!records) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('データなし', W / 2, H / 2);
        return;
    }

    // 描画範囲に含まれるポイント（前後1hずつバッファ）
    const points = records
        .map(r => ({ t: new Date(r.datetime).getTime(), cm: Number(r.tide_cm) }))
        .filter(p => Number.isFinite(p.t) && Number.isFinite(p.cm)
                  && p.t >= tMin - 3600 * 1000
                  && p.t <= tMax + 3600 * 1000)
        .sort((a, b) => a.t - b.t);

    if (points.length === 0) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '11px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('データなし', W / 2, H / 2);
        return;
    }

    const cmValues = points.map(p => p.cm);
    let cmMin = Math.min(...cmValues);
    let cmMax = Math.max(...cmValues);
    const cmPad = Math.max(20, (cmMax - cmMin) * 0.15);
    cmMin -= cmPad;
    cmMax += cmPad;

    const gW = W - PAD.left - PAD.right;
    const gH = H - PAD.top - PAD.bottom;

    function tx(t)  { return PAD.left + (t - tMin) / (tMax - tMin) * gW; }
    function ty(cm) { return PAD.top  + (1 - (cm - cmMin) / (cmMax - cmMin)) * gH; }

    // 水平グリッド
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 0.5;
    const cmStep = (cmMax - cmMin) > 200 ? 50 : (cmMax - cmMin) > 100 ? 25 : 20;
    const cmBase = Math.ceil(cmMin / cmStep) * cmStep;
    for (let c = cmBase; c <= cmMax; c += cmStep) {
        const y = ty(c);
        ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + gW, y); ctx.stroke();
        ctx.fillStyle = '#94a3b8'; ctx.font = '9px sans-serif'; ctx.textAlign = 'right';
        ctx.fillText(`${c}`, PAD.left - 3, y + 3);
    }

    // 時間グリッド（3h毎） — 次の整数時刻から
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 0.5;
    const hMs = 3600 * 1000;
    const t3hStart = Math.ceil(tMin / (3 * hMs)) * 3 * hMs;
    ctx.fillStyle = '#94a3b8'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
    for (let t = t3hStart; t <= tMax; t += 3 * hMs) {
        const x = tx(t);
        ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + gH); ctx.stroke();
        const jstHour = new Date(t + 9 * hMs).getUTCHours(); // UTC+9h のUTC時刻 = JST時刻
        ctx.fillText(`${String(jstHour).padStart(2, '0')}h`, x, H - 4);
    }

    // 潮位ライン（描画範囲内）
    const visPoints = points.filter(p => p.t >= tMin && p.t <= tMax);
    if (visPoints.length > 0) {
        ctx.strokeStyle = '#2563eb';
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.beginPath();
        visPoints.forEach((p, i) => {
            const x = tx(p.t); const y = ty(p.cm);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // 塗りつぶし
        const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + gH);
        grad.addColorStop(0, 'rgba(37,99,235,0.15)');
        grad.addColorStop(1, 'rgba(37,99,235,0)');
        ctx.fillStyle = grad;
        ctx.beginPath();
        visPoints.forEach((p, i) => {
            const x = tx(p.t); const y = ty(p.cm);
            if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        });
        ctx.lineTo(tx(visPoints[visPoints.length - 1].t), PAD.top + gH);
        ctx.lineTo(tx(visPoints[0].t), PAD.top + gH);
        ctx.closePath();
        ctx.fill();
    }

    // 満潮・干潮マーカー（24h窓内のみ）
    const extremes = data && data.extremes;
    if (extremes) {
        const drawExtremes = (list, color, label) => {
            (list || []).forEach(e => {
                const t = new Date(e.time).getTime();
                if (t < tMin || t > tMax) return;
                const x = tx(t);
                const y = ty(Number(e.tide_cm));
                ctx.beginPath();
                ctx.arc(x, y, 4, 0, Math.PI * 2);
                ctx.fillStyle = color;
                ctx.fill();
                ctx.strokeStyle = '#fff';
                ctx.lineWidth = 1.5;
                ctx.stroke();
                ctx.fillStyle = color;
                ctx.font = 'bold 9px sans-serif';
                ctx.textAlign = 'center';
                ctx.fillText(label, x, label === '満' ? y - 6 : y + 14);
            });
        };
        drawExtremes(extremes.high_tides, '#dc2626', '満');
        drawExtremes(extremes.low_tides,  '#0891b2', '干');
    }

    // 現在時刻ライン（左端・強調表示）
    const x0 = PAD.left;
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 2;
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(x0, PAD.top); ctx.lineTo(x0, PAD.top + gH); ctx.stroke();

    // 現在潮位の丸ドット＋数値ラベル
    const closestPt = points.length > 0
        ? points.reduce((a, b) => Math.abs(b.t - now) < Math.abs(a.t - now) ? b : a)
        : null;
    if (closestPt) {
        const dotY = ty(closestPt.cm);

        // ドット（白縁付き赤丸）
        ctx.beginPath();
        ctx.arc(x0, dotY, 5.5, 0, Math.PI * 2);
        ctx.fillStyle = '#ef4444';
        ctx.fill();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2;
        ctx.stroke();

        // cm ラベル（赤背景・白文字）
        const label = `${Math.round(closestPt.cm)} cm`;
        ctx.font = 'bold 10px sans-serif';
        const lw = ctx.measureText(label).width;
        const lx = x0 + 9;
        const ly = dotY;
        // ラベルが上端に近い場合は下へずらす
        const textY = dotY < PAD.top + 14 ? dotY + 13 : dotY + 4;
        ctx.fillStyle = '#ef4444';
        ctx.beginPath();
        ctx.roundRect(lx - 2, textY - 11, lw + 6, 14, 3);
        ctx.fill();
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'left';
        ctx.fillText(label, lx + 1, textY);
    }

    // 「現在」テキスト（ライン上部）
    ctx.fillStyle = '#ef4444';
    ctx.font = 'bold 9px sans-serif'; ctx.textAlign = 'left';
    ctx.fillText('現在', x0 + 2, PAD.top - 1);
}

// ── 情報タブ折りたたみ ────────────────────────────────────────────

let _lipLevel = 2;  // 1=compact, 2=standard(default), 3=detail

function _lipCycleLevel() {
    _lipLevel = (_lipLevel % 3) + 1;
    _lipApplyLevel();
}

function _lipApplyLevel() {
    const el = document.getElementById('loc-info-nonnav');
    if (!el) return;
    el.setAttribute('data-lip-level', String(_lipLevel));

    const labels = { 1: '最小', 2: '標準', 3: '詳細' };
    const next   = { 1: '標準▾', 2: '詳細▾', 3: '最小▴' };
    _lipSet('lip-level-label', labels[_lipLevel] || '');
    const btn = document.getElementById('lip-level-btn');
    if (btn) btn.textContent = next[_lipLevel] || '詳細▾';

    // レベル切替時にグラフを再描画（キャンバスサイズが変わる場合があるため）
    const stationId = _selectedTideStation
        ? _selectedTideStation.id
        : (_tideCache && _tideCache.data && _tideCache.data.station
            ? _tideCache.data.station.id : null);
    if (stationId) _tideGraphUpdate(stationId);
}

// ── 全国潮位表示 ON/OFF ───────────────────────────────────────────

async function _tidePanelToggleAllNation() {
    const btn = document.getElementById('lip-tide-allnation-btn');
    const isOn = typeof isTideMarkersVisible === 'function' && isTideMarkersVisible();
    if (isOn) {
        if (typeof hideTideMarkers === 'function') hideTideMarkers();
        if (btn) { btn.textContent = '全国潮位 ON'; btn.classList.remove('active'); }
    } else {
        if (btn) { btn.textContent = '全国潮位 OFF'; btn.classList.add('active'); }
        try {
            if (typeof showTideMarkers === 'function') await showTideMarkers();
        } catch (err) {
            console.warn('[tide] showTideMarkers failed:', err);
            if (btn) { btn.textContent = '全国潮位 ON'; btn.classList.remove('active'); }
        }
    }
}

// 起動時1回のみ実行（他のスクリプトがすべてロード済みの状態で実行される）
_lipInit();
// HTML 側の data-lip-level="2" に合わせてボタンラベルを初期化
_lipApplyLevel();

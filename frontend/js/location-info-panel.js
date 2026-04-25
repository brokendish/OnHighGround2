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
    const safety = route?.__pedestrianSafety || null;
    if (!safety) return '';
    if (Array.isArray(safety.dangerousCrossings) && safety.dangerousCrossings.length > 0) {
        const first = safety.dangerousCrossings[0];
        const highway = first?.classification?.highway || '幹線道路';
        return `${highway} 横断に注意`;
    }
    if (safety.status === 'unknown') {
        return '横断安全性を判定できません';
    }
    return '';
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

// 起動時1回のみ実行（他のスクリプトがすべてロード済みの状態で実行される）
_lipInit();

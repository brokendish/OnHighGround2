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
    if (typeof _routeUiClearComparison === 'function') _routeUiClearComparison();
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
    const selectedRoute = routeList[_lipRouteSelection.selectedRouteIndex] || null;
    const selectedModel = typeof createRoutePresentationModel === 'function'
        ? createRoutePresentationModel(selectedRoute, {
            index: _lipRouteSelection.selectedRouteIndex ?? 0,
            selectedRouteIndex: _lipRouteSelection.selectedRouteIndex
        })
        : null;
    const selectedRouteId = selectedModel?.route_id ?? _lipRouteSelection.selectedRouteIndex;
    routeList.forEach((candidateRoute, routeIndex) => {
        const model = typeof createRoutePresentationModel === 'function'
            ? createRoutePresentationModel(candidateRoute, { index: routeIndex, selectedRouteId })
            : null;
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'route-option-button';
        const isSelected = model?.selected ?? (routeIndex === _lipRouteSelection.selectedRouteIndex);
        if (isSelected) {
            button.classList.add('active');
        }
        const color = _lipRouteSelection.routeColors[routeIndex]
            || (typeof getRouteColorByIndex === 'function' ? getRouteColorByIndex(routeIndex) : '#1e88e5');
        const distance = _lipFormatDistance(model?.distance_m ?? _lipRouteMetric(candidateRoute, 'distance'));
        const duration = _lipFormatDuration(model?.duration_s ?? _lipRouteMetric(candidateRoute, 'time'));
        const badge = model?.badge || _lipResolveRouteBadge(candidateRoute, routeIndex, routeList);
        const scoreText = typeof formatRouteSafetyScore === 'function'
            ? formatRouteSafetyScore(model?.safety_score)
            : '';
        const riskText = typeof routeRiskLevelText === 'function'
            ? routeRiskLevelText(model?.risk_level)
            : (model?.risk_level || '');
        const riskLabel = scoreText ? ` / 安全度 ${scoreText} / ${riskText}` : '';
        const modeLabel = transportMode === 'walking' ? '徒歩' : transportMode === 'driving' ? '車' : '';
        console.log('[route-ui]', {
            surface: 'selection',
            route_id: model?.route_id ?? routeIndex,
            label: model?.label || `候補${routeIndex + 1}`,
            score: model?.safety_score ?? null,
            risk_level: model?.risk_level || 'unknown',
            selected: isSelected,
            recommended: model?.recommended ?? routeIndex === 0,
        });
        button.innerHTML = `
            <span class="route-color-chip" style="background: ${color};"></span>
            ${model?.label || `候補${routeIndex + 1}`}
            <span style="margin-left:6px;font-size:11px;color:#64748b;">${distance} / ${duration}${modeLabel ? ` / ${modeLabel}` : ''}${riskLabel}</span>
            <span style="margin-left:auto;font-size:11px;font-weight:700;color:${isSelected ? '#fff' : '#1d4ed8'};">${badge}</span>
        `;
        button.addEventListener('click', (event) => {
            event.preventDefault();
            event.stopPropagation();
            onSelect(routeIndex);
            if (typeof _routeUiOnRouteSelected === 'function') _routeUiOnRouteSelected(routeIndex);
        });
        container.appendChild(button);
    });

    _lipRenderRouteRiskInfo();

    // ルート比較カード: 評価済み route candidates を単一ソースとして使用。
    // 旧: _routeUiFetchAndShow → /api/navigation/route/compare（独立フェッチ）
    // 新: routeUiShowFromCandidates → route.__riskSummary（ルート選択と同一データ）
    if (routeList.length > 1 && typeof routeUiShowFromCandidates === 'function') {
        routeUiShowFromCandidates(routeList, _lipRouteSelection.selectedRouteIndex ?? 0);
    }
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

    // 段階式月相（_tlDrawMoonPhaseIcon と同じ判定）
    const p = ((phase % 28) + 28) % 28;
    let lit, waxing;
    if      (p <  1.0 || p >= 27.5) { lit = 0.00; waxing = true;  }
    else if (p <  3.5)               { lit = 0.08; waxing = true;  }
    else if (p <  6.5)               { lit = 0.28; waxing = true;  }
    else if (p <  8.5)               { lit = 0.50; waxing = true;  }
    else if (p < 12.5)               { lit = 0.72; waxing = true;  }
    else if (p < 16.5)               { lit = 1.00; waxing = true;  }
    else if (p < 20.5)               { lit = 0.72; waxing = false; }
    else if (p < 23.5)               { lit = 0.50; waxing = false; }
    else                             { lit = 0.08; waxing = false; }

    if (lit === 0) {
        return `<svg ${base}><circle cx="${cx}" cy="${cy}" r="${r}" fill="${dark}" stroke="#6b7280" stroke-width="0.5"/></svg>`;
    }
    if (lit === 1) {
        return `<svg ${base}><circle cx="${cx}" cy="${cy}" r="${r}" fill="${light}" stroke="#9ca3af" stroke-width="0.5"/></svg>`;
    }

    // 朔望線の楕円 x 半径を段階値から計算
    // waxing=右側点灯(litSwp=1), waning=左側点灯(litSwp=0)
    const termRx  = r * (1 - 2 * lit);          // 正=凹(三日月), 負=凸(十三夜)
    const termSwp = (termRx > 0) === waxing ? 0 : 1;
    const absRx   = Math.max(Math.abs(termRx), 0.5);
    const litSwp  = waxing ? 1 : 0;

    const path = `M ${cx} ${cy - r} A ${r} ${r} 0 0 ${litSwp} ${cx} ${cy + r} A ${absRx} ${r} 0 0 ${termSwp} ${cx} ${cy - r}`;

    return `<svg ${base}>
        <circle cx="${cx}" cy="${cy}" r="${r}" fill="${dark}" stroke="#6b7280" stroke-width="0.5"/>
        <path d="${path}" fill="${light}"/>
    </svg>`;
}

function _fmtMsHM(ms) {
    return new Date(ms).toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
}

function _computeDarkPeriod(data) {
    if (!data || !data.sunset) return null;
    const sunsetMs   = new Date(data.sunset).getTime();
    const sunriseMs  = data.sunrise  ? new Date(data.sunrise).getTime()  : null;
    const moonriseMs = data.moonrise ? new Date(data.moonrise).getTime() : null;
    const moonsetMs  = data.moonset  ? new Date(data.moonset).getTime()  : null;

    // 暗所開始: sunset と moonset の遅い方（後に消える光源を基準）
    let darkStart = sunsetMs;
    if (moonsetMs && moonsetMs > sunsetMs) darkStart = moonsetMs;

    // 暗所終了: 翌日 sunrise と moonrise（+24h 近似）の早い方
    const nextSunriseMs  = sunriseMs  ? sunriseMs  + 24 * 3600 * 1000 : null;
    const nextMoonriseMs = moonriseMs ? moonriseMs + 24 * 3600 * 1000 : null;
    let darkEnd;
    if (nextSunriseMs && nextMoonriseMs) {
        darkEnd = Math.min(nextSunriseMs, nextMoonriseMs);
    } else {
        darkEnd = nextSunriseMs || null;
    }
    if (!darkEnd) return null;
    return { start: darkStart, end: darkEnd };
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
    _lipSet('lip-astro-moonrise', _astroFmtTime(data.moonrise) || '--');
    _lipSet('lip-astro-moonset',  _astroFmtTime(data.moonset)  || '--');

    // 月齢バッジ（ライトモード）
    const noteEl = document.getElementById('lip-astro-note');
    if (noteEl) {
        if (data.moon_label && data.moon_phase != null) {
            noteEl.innerHTML = `<span class="lip-astro-badge--light">月齢 ${data.moon_phase}（${data.moon_label}）</span>`;
        } else {
            noteEl.innerHTML = '';
        }
    }

    // 昼の長さ
    if (data.sunrise && data.sunset) {
        const dayMin = Math.round((new Date(data.sunset) - new Date(data.sunrise)) / 60000);
        const dh = Math.floor(dayMin / 60), dm = dayMin % 60;
        _lipSet('lip-env-day-length', `昼の長さ ${dh}時間${String(dm).padStart(2, '0')}分`);
    }

    // 暗所注意タイル
    const dark = _computeDarkPeriod(data);
    const darkTile = document.getElementById('lip-env-dark-tile');
    if (darkTile) {
        if (dark) {
            _lipSet('lip-env-dark-start', _fmtMsHM(dark.start));
            _lipSet('lip-env-dark-end',   _fmtMsHM(dark.end));
            darkTile.style.display = '';
        } else {
            darkTile.style.display = 'none';
        }
    }

    _astroMoonCanvasStart(data.moon_phase);
}

let _moonCanvasAnimId = null;
let _moonCanvasPhase  = 0;
let _moonCanvasStart  = 0;

function _astroMoonCanvasStart(phase) {
    _moonCanvasPhase = phase;
    if (_moonCanvasAnimId) { cancelAnimationFrame(_moonCanvasAnimId); _moonCanvasAnimId = null; }
    _moonCanvasStart = performance.now();
    const tick = (ts) => {
        const canvas = document.getElementById('lip-astro-moon-canvas');
        if (!canvas) { _moonCanvasAnimId = null; return; }
        if (!canvas.offsetParent) { _moonCanvasAnimId = requestAnimationFrame(tick); return; }
        const dpr = window.devicePixelRatio || 1;
        const r   = 13;
        const sz  = r * 2 + 6;
        const needW = Math.round(sz * dpr);
        const needH = Math.round(sz * dpr);
        if (canvas.width !== needW || canvas.height !== needH) {
            canvas.width  = needW;
            canvas.height = needH;
            canvas.style.width  = sz + 'px';
            canvas.style.height = sz + 'px';
        }
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, sz, sz);
        const elapsed   = (ts - _moonCanvasStart) / 1000;
        const glowPulse = 0.5 + 0.5 * Math.sin(elapsed * Math.PI * 2 / 3);
        _tlDrawMoonPhaseIcon(ctx, sz / 2, sz / 2, r, _moonCanvasPhase, glowPulse);
        _moonCanvasAnimId = requestAnimationFrame(tick);
    };
    _moonCanvasAnimId = requestAnimationFrame(tick);
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
    if (lat != null && lon != null && Number.isFinite(station.lat) && Number.isFinite(station.lon)) {
        const meters = _lipHaversineMeters(lat, lon, station.lat, station.lon);
        const km = (Math.round(meters / 100) * 100 / 1000).toFixed(1);
        distLabel = `観測地点まで ${km} km`;
    } else if (station.distance_km != null) {
        distLabel = `観測地点まで ${station.distance_km} km`;
    }
    _lipSet('lip-tide-card-name', station.name || station.id || '--');
    _lipSet('lip-tide-card-dist', distLabel);
}

function _tideRender(data) {
    const section = document.getElementById('lip-tide-section');
    if (!section) return;

    if (!data || data.available === false) {
        section.style.display = 'none';
        return;
    }

    section.style.display = '';
    const card = document.getElementById('lip-tide-card');
    if (card) card.style.display = '';

    // 現在潮位
    const num = data.current_tide_cm == null ? '--' : String(Math.round(Number(data.current_tide_cm)));
    _lipSet('lip-tide-card-num', num);

    // 満潮・干潮（時刻とcmを分けて表示）
    _tideSetExtreme('lip-tide-card-high-time', 'lip-tide-card-high-cm', data.next_high_tide);
    _tideSetExtreme('lip-tide-card-low-time',  'lip-tide-card-low-cm',  data.next_low_tide);

    // 現在時刻
    _tideUpdateClock();

    _tideRenderStation(_lipLat, _lipLon);
    _tideDistLastPos = (_lipLat != null && _lipLon != null)
        ? { lat: _lipLat, lon: _lipLon } : null;

    const stationId = _selectedTideStation
        ? _selectedTideStation.id
        : (data.station ? data.station.id : null);
    if (stationId) _tideGraphUpdate(stationId);
}

function _tideSetExtreme(timeId, cmId, value) {
    if (!value || !value.time) { _lipSet(timeId, '--'); _lipSet(cmId, ''); return; }
    const d = new Date(value.time);
    if (isNaN(d.getTime())) { _lipSet(timeId, '--'); _lipSet(cmId, ''); return; }
    const time = d.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
    const cm   = value.tide_cm == null ? '' : `${Math.round(Number(value.tide_cm))} cm`;
    _lipSet(timeId, time);
    _lipSet(cmId, cm);
}

function _tideUpdateClock() {
    const now = new Date();
    const hm  = now.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Tokyo' });
    _lipSet('lip-tide-card-clock', `現在時刻 ${hm}`);
    _lipSet('lip-graph-now-label', `現在 ${hm}`);
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
    // 現在±12h（現在中央）: 前日・当日・翌日を取得して結合する
    const nowMs = Date.now();
    const jstOffMs = 9 * 3600 * 1000;
    const prevJst     = new Date(nowMs + jstOffMs - 24 * 3600 * 1000).toISOString().slice(0, 10);
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

    const dates = [...new Set([prevJst, todayJst, tomorrowJst])];
    const results = await Promise.all(dates.map(d => fetchDay(d).catch(() => null)));

    return {
        records: results.flatMap(d => d?.records || []),
        extremes: {
            high_tides: results.flatMap(d => d?.extremes?.high_tides || []),
            low_tides:  results.flatMap(d => d?.extremes?.low_tides  || []),
        },
    };
}

async function _tideGraphUpdate(stationId) {
    const canvas = document.getElementById('lip-tide-graph');
    if (!canvas) return;
    const nowMs = Date.now();
    const tMin  = nowMs - 12 * 3600 * 1000;
    const tMax  = nowMs + 12 * 3600 * 1000;
    const data = await _tideGraphFetch(stationId);
    _tideGraphDraw(canvas, data, tMin, tMax, nowMs);
    if (_lipLat != null && _lipLon != null) {
        _sunMoonTimelineUpdate(_lipLat, _lipLon, tMin, tMax, nowMs).catch(() => {});
    }
}

function _tideGraphDraw(canvas, data, tMin, tMax, nowMs) {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    // section.style.display='' 直後はリフロー未完で width=0 になる → 次フレームで再試行
    if (rect.width === 0) {
        requestAnimationFrame(() => _tideGraphDraw(canvas, data, tMin, tMax, nowMs));
        return;
    }
    canvas.width  = Math.round(rect.width  * dpr);
    canvas.height = Math.round(rect.height * dpr);
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = canvas.width  / dpr;
    const H = canvas.height / dpr;
    const PAD = { top: 10, right: 10, bottom: 22, left: 68 };

    ctx.clearRect(0, 0, W, H);

    // 横軸: 現在を中央に -12h〜+12h
    const now = nowMs != null ? nowMs : (tMin + tMax) / 2;

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

    // 時間グリッド（6h毎ラベル・3h毎補助線）
    const hMs = 3600 * 1000;
    const t3hStart = Math.ceil(tMin / (3 * hMs)) * 3 * hMs;
    const t6hStart = Math.ceil(tMin / (6 * hMs)) * 6 * hMs;
    // 補助グリッド線（3h、ラベルなし）
    ctx.strokeStyle = '#e2e8f0';
    ctx.lineWidth = 0.5;
    for (let t = t3hStart; t <= tMax; t += 3 * hMs) {
        const x = tx(t);
        ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + gH); ctx.stroke();
    }
    // 時刻ラベル（6h毎）
    ctx.fillStyle = '#94a3b8'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
    for (let t = t6hStart; t <= tMax; t += 6 * hMs) {
        const x = tx(t);
        const jstHour = new Date(t + 9 * hMs).getUTCHours();
        ctx.fillText(`${String(jstHour).padStart(2, '0')}:00`, x, H - 4);
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
                const labelY = Math.max(PAD.top + 9, y - 6);
                ctx.fillText(label, x, labelY);
            });
        };
        drawExtremes(extremes.high_tides, '#dc2626', '満');
        drawExtremes(extremes.low_tides,  '#0891b2', '干');
    }

    // 現在時刻ライン（中央）
    const x0 = tx(now);
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

    // 「現在」テキスト（ライン上部・中央揃え）
    ctx.fillStyle = '#ef4444';
    ctx.font = 'bold 9px sans-serif'; ctx.textAlign = 'center';
    ctx.fillText('現在', x0, PAD.top - 1);
}

// ── 日月タイムライン ─────────────────────────────────────────────────

const _ASTRO_TL_CACHE_TTL_MS = 10 * 60 * 1000;
let _astroTlCache = {};

async function _astroTlFetchDay(lat, lon, dateStr) {
    const key = `${lat.toFixed(3)},${lon.toFixed(3)}|${dateStr}`;
    const now = Date.now();
    const cached = _astroTlCache[key];
    if (cached && now - cached.fetchedAt < _ASTRO_TL_CACHE_TTL_MS) return cached.data;
    try {
        const res = await fetch(`/api/astro/current?lat=${lat}&lon=${lon}&date=${dateStr}`);
        if (!res.ok) return null;
        const data = await res.json();
        _astroTlCache[key] = { data, fetchedAt: now };
        return data;
    } catch {
        return null;
    }
}

async function _sunMoonTimelineUpdate(lat, lon, tMin, tMax, nowMs) {
    const canvas = document.getElementById('lip-sun-moon-timeline');
    if (!canvas) return;
    const centerMs = nowMs != null ? nowMs : (tMin + tMax) / 2;
    const jstOffMs = 9 * 3600 * 1000;
    const prevStr     = new Date(centerMs + jstOffMs - 24 * 3600 * 1000).toISOString().slice(0, 10);
    const todayStr    = new Date(centerMs + jstOffMs).toISOString().slice(0, 10);
    const tomorrowStr = new Date(centerMs + jstOffMs + 24 * 3600 * 1000).toISOString().slice(0, 10);
    const [prevData, todayData, tomorrowData] = await Promise.all([
        _astroTlFetchDay(lat, lon, prevStr),
        _astroTlFetchDay(lat, lon, todayStr),
        todayStr !== tomorrowStr ? _astroTlFetchDay(lat, lon, tomorrowStr) : Promise.resolve(null),
    ]);
    _sunMoonTimelineDraw(canvas, todayData, tomorrowData, tMin, tMax, prevData, centerMs);
}

/**
 * タイムラインのイベントラベルを重なりを避けて描画する。
 * - rise → tick の右側、set → tick の左側を基本とする
 * - 端を超える場合は反転
 * - 隣接ラベルが重なる場合は矢印のみに省略する
 * - labelNames: { rise: '日の出', set: '日の入' } など（省略可）
 */
function _tlDrawEventLabels(ctx, events, bandY, bandH, fillColor, strokeColor, LPAD, gW, labelNames) {
    if (!events || events.length === 0) return;
    const NAMEFONT  = 'bold 9px sans-serif';
    const TIMEFONT  = '9px sans-serif';
    const MARGIN    = 2;
    const NAME_DY   = -22;  // バー上端からの名前行オフセット
    const TIME_DY   = -12;  // バー上端からの時刻行オフセット
    const ARROW_DY  = -3;   // バー上端からの矢印オフセット
    const TICK_TOP  = -24;  // チック線のバー上端からの開始オフセット

    const fmtT = (t) => {
        const d = new Date(t + 9 * 3600 * 1000);
        return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
    };

    const items = events.map(({ t, type, x }) => {
        const nameStr  = labelNames ? labelNames[type] : '';
        const timeStr  = fmtT(t);
        const arrowStr = type === 'rise' ? '↑' : '↓';

        ctx.font = NAMEFONT;
        const nw = nameStr ? ctx.measureText(nameStr).width : 0;
        ctx.font = TIMEFONT;
        const tw = ctx.measureText(timeStr).width;
        const aw = ctx.measureText(arrowStr).width;
        const maxW = Math.max(nw, tw, aw);

        let align = type === 'rise' ? 'left' : 'right';
        let tx    = type === 'rise' ? x + MARGIN : x - MARGIN;

        if (align === 'left'  && tx + maxW > LPAD + gW - 1) { align = 'right'; tx = x - MARGIN; }
        if (align === 'right' && tx - maxW < LPAD + 1)       { align = 'left';  tx = x + MARGIN; }

        const x1 = align === 'left' ? tx         : tx - maxW;
        const x2 = align === 'left' ? tx + maxW  : tx;
        return { t, type, x, nameStr, timeStr, arrowStr, maxW, aw, align, tx, x1, x2, shorten: false };
    });

    items.sort((a, b) => a.x - b.x);
    for (let i = 1; i < items.length; i++) {
        const prev = items[i - 1];
        const curr = items[i];
        if (curr.x1 < prev.x2 + 3) {
            curr.shorten = true;
            curr.x2 = curr.align === 'left' ? curr.tx + curr.aw : curr.tx;
            curr.x1 = curr.align === 'left' ? curr.tx            : curr.tx - curr.aw;
            if (curr.x1 < prev.x2 + 3) {
                prev.shorten = true;
                prev.x2 = prev.align === 'left' ? prev.tx + prev.aw : prev.tx;
                prev.x1 = prev.align === 'left' ? prev.tx            : prev.tx - prev.aw;
            }
        }
    }

    items.forEach(({ t, type, x, nameStr, timeStr, arrowStr, align, tx, shorten }) => {
        // チック線
        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = 1.5;
        ctx.setLineDash([]);
        ctx.beginPath();
        ctx.moveTo(x, bandY + TICK_TOP);
        ctx.lineTo(x, bandY + bandH);
        ctx.stroke();

        ctx.textAlign = align;

        if (shorten) {
            ctx.fillStyle = fillColor;
            ctx.font = TIMEFONT;
            ctx.fillText(arrowStr, tx, bandY + ARROW_DY);
            return;
        }

        // 名前行
        if (nameStr) {
            ctx.fillStyle = fillColor;
            ctx.font = NAMEFONT;
            ctx.fillText(nameStr, tx, bandY + NAME_DY);
        }
        // 時刻行
        ctx.fillStyle = fillColor;
        ctx.font = TIMEFONT;
        ctx.fillText(timeStr, tx, bandY + TIME_DY);
        // 矢印
        ctx.fillText(arrowStr, tx, bandY + ARROW_DY);
    });
}

// ── タイムライン RAF アニメーション ──────────────────────────────────
let _tlAnimId = null;
let _tlAnimParams = null;
let _tlAnimStart = 0;

function _sunMoonTimelineDraw(canvas, todayData, tomorrowData, tMin, tMax, prevData = null, nowMs = null) {
    _tlAnimParams = { canvas, todayData, tomorrowData, tMin, tMax, prevData, nowMs };
    if (_tlAnimId != null) { cancelAnimationFrame(_tlAnimId); _tlAnimId = null; }
    _tlAnimStart = performance.now();
    const tick = (ts) => {
        const p = _tlAnimParams;
        if (!p) { _tlAnimId = null; return; }
        if (!p.canvas.offsetParent) { _tlAnimId = requestAnimationFrame(tick); return; }
        _tlDrawCore(p, (ts - _tlAnimStart) / 1000);
        _tlAnimId = requestAnimationFrame(tick);
    };
    _tlAnimId = requestAnimationFrame(tick);
}

function _tlDrawMoonPhaseIcon(ctx, cx, cy, r, phase, glowPulse) {
    // 段階式月相 — 連続計算は小サイズで sub-pixel になるため段階値を使う
    // phase: Astral 0-28 スケール (0/28=新月, 14=満月)
    const p = ((phase % 28) + 28) % 28;
    let lit, waxing;
    if      (p <  1.0 || p >= 27.5) { lit = 0.00; waxing = true;  } // 新月
    else if (p <  3.5)               { lit = 0.08; waxing = true;  } // 細い右三日月
    else if (p <  6.5)               { lit = 0.28; waxing = true;  } // 右三日月
    else if (p <  8.5)               { lit = 0.50; waxing = true;  } // 上弦
    else if (p < 12.5)               { lit = 0.72; waxing = true;  } // 満ちていく月
    else if (p < 16.5)               { lit = 1.00; waxing = true;  } // 満月
    else if (p < 20.5)               { lit = 0.72; waxing = false; } // 欠けていく月
    else if (p < 23.5)               { lit = 0.50; waxing = false; } // 下弦
    else                             { lit = 0.08; waxing = false; } // 細い左三日月

    const kappa  = 0.5523;
    const sign   = waxing ? 1 : -1;
    const ex     = sign * (1 - 2 * lit) * r;

    const glowR = r + 2 + glowPulse * 3;
    const glowA = (0.15 + glowPulse * 0.25).toFixed(2);
    const grd = ctx.createRadialGradient(cx, cy, r * 0.4, cx, cy, glowR);
    grd.addColorStop(0, `rgba(200,225,255,${glowA})`);
    grd.addColorStop(1, 'rgba(200,225,255,0)');
    ctx.fillStyle = grd;
    ctx.beginPath(); ctx.arc(cx, cy, glowR, 0, Math.PI * 2); ctx.fill();

    ctx.fillStyle = '#0f1e36';
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fill();

    if (lit > 0.01) {
        ctx.save();
        ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.clip();
        ctx.fillStyle = '#d8eaf9';
        ctx.beginPath();
        ctx.arc(cx, cy, r, -Math.PI / 2, Math.PI / 2, !waxing);
        ctx.bezierCurveTo(cx + ex * kappa, cy + r, cx + ex * kappa, cy - r, cx, cy - r);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
    }

    ctx.strokeStyle = 'rgba(148,163,184,0.5)';
    ctx.lineWidth = 0.5;
    ctx.setLineDash([]);
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.stroke();
}

function _tlDrawCore(p, elapsed) {
    const { canvas, todayData, tomorrowData, tMin, tMax, prevData, nowMs } = p;

    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    // リフロー未完（width=0）の場合は描画をスキップし、次フレームで再描画
    if (rect.width === 0) return;
    const needW = Math.round(rect.width  * dpr);
    const needH = Math.round(rect.height * dpr);
    if (canvas.width !== needW || canvas.height !== needH) {
        canvas.width  = needW;
        canvas.height = needH;
    }
    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const W = needW / dpr;
    const H = needH / dpr;
    ctx.clearRect(0, 0, W, H);

    if (!todayData && !tomorrowData) {
        ctx.fillStyle = '#94a3b8';
        ctx.font = '10px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('天体データなし', W / 2, H / 2 + 4);
        return;
    }

    const LPAD = 68;
    const RPAD = 10;
    const gW   = W - LPAD - RPAD;

    const SUN_Y  = 30;
    const SUN_H  = 26;
    const MOON_Y = SUN_Y + SUN_H + 28;  // = 84: 2行ラベル分の余白
    const MOON_H = 26;
    const AXIS_Y = MOON_Y + MOON_H + 5; // = 115

    const centerMs = nowMs != null ? nowMs : (tMin + tMax) / 2;
    const toX    = (t) => LPAD + (t - tMin) / (tMax - tMin) * gW;
    const clampX = (x) => Math.max(LPAD, Math.min(LPAD + gW, x));

    const parseMs = (iso) => {
        if (!iso) return null;
        const d = new Date(iso);
        return isNaN(d.getTime()) ? null : d.getTime();
    };

    const previous = prevData     || {};
    const today    = todayData    || {};
    const tomorrow = tomorrowData || {};

    const sunEvents = [];
    for (const [iso, type] of [
        [previous.sunrise, 'rise'], [previous.sunset, 'set'],
        [today.sunrise, 'rise'], [today.sunset, 'set'],
        [tomorrow.sunrise, 'rise'], [tomorrow.sunset, 'set'],
    ]) {
        const t = parseMs(iso);
        if (t != null) sunEvents.push({ t, type });
    }
    sunEvents.sort((a, b) => a.t - b.t);

    const moonEvents = [];
    for (const [iso, type] of [
        [previous.moonrise, 'rise'], [previous.moonset, 'set'],
        [today.moonrise, 'rise'], [today.moonset, 'set'],
        [tomorrow.moonrise, 'rise'], [tomorrow.moonset, 'set'],
    ]) {
        const t = parseMs(iso);
        if (t != null) moonEvents.push({ t, type });
    }
    moonEvents.sort((a, b) => a.t - b.t);

    // ── 太陽グラデーション帯 ──────────────────────────────────────
    const NIGHT    = '#0f172a';
    const TWILIGHT = '#f97316';
    const DAY      = '#fef9c3';
    const TRANS_MS = 40 * 60 * 1000;

    const sunBefore    = sunEvents.filter(e => e.t <= tMin);
    const isDayAtStart = sunBefore.filter(e => e.type === 'rise').length
                       > sunBefore.filter(e => e.type === 'set').length;

    const sunGrad = ctx.createLinearGradient(LPAD, 0, LPAD + gW, 0);
    const addSunStop = (t, color) => {
        sunGrad.addColorStop(Math.max(0, Math.min(1, (t - tMin) / (tMax - tMin))), color);
    };

    sunGrad.addColorStop(0, isDayAtStart ? DAY : NIGHT);
    const sunWin = sunEvents.filter(e => e.t > tMin && e.t < tMax);
    let lastSunState = isDayAtStart;
    sunWin.forEach(({ t, type }) => {
        if (type === 'rise') {
            addSunStop(Math.max(tMin, t - TRANS_MS), NIGHT);
            addSunStop(t, TWILIGHT);
            addSunStop(Math.min(tMax, t + TRANS_MS), DAY);
            lastSunState = true;
        } else {
            addSunStop(Math.max(tMin, t - TRANS_MS), DAY);
            addSunStop(t, TWILIGHT);
            addSunStop(Math.min(tMax, t + TRANS_MS), NIGHT);
            lastSunState = false;
        }
    });
    sunGrad.addColorStop(1, lastSunState ? DAY : NIGHT);

    ctx.fillStyle = sunGrad;
    ctx.beginPath();
    ctx.roundRect(LPAD, SUN_Y, gW, SUN_H, 3);
    ctx.fill();

    // ── 夜帯に星を散らす ─────────────────────────────────────────
    const nightSegs = [];
    let nightStart = isDayAtStart ? null : tMin;
    sunWin.forEach(({ t, type }) => {
        if (type === 'rise') {
            if (nightStart != null) nightSegs.push([nightStart, t]);
            nightStart = null;
        } else {
            nightStart = t;
        }
    });
    if (nightStart != null) nightSegs.push([nightStart, tMax]);

    ctx.fillStyle = 'rgba(255,255,255,0.65)';
    nightSegs.forEach(([tS, tE]) => {
        const xS = Math.max(LPAD, toX(tS));
        const xE = Math.min(LPAD + gW, toX(tE));
        const w  = xE - xS;
        if (w < 5) return;
        const n = Math.max(2, Math.floor(w / 9));
        for (let i = 0; i < n; i++) {
            const h1 = Math.sin(xS * 0.31 + i * 7.13) * 43758.5453;
            const h2 = Math.sin(xS * 0.17 + i * 13.73) * 97531.843;
            const rx = xS + (h1 - Math.floor(h1)) * w;
            const ry = SUN_Y + 2 + (h2 - Math.floor(h2)) * (SUN_H - 4);
            ctx.beginPath();
            ctx.arc(rx, ry, i % 5 === 0 ? 1.0 : 0.55, 0, Math.PI * 2);
            ctx.fill();
        }
    });

    // ── 昼帯の中央に太陽アイコン ──────────────────────────────────
    const daytimeSegs = [];
    let dayStart = isDayAtStart ? tMin : null;
    sunWin.forEach(({ t, type }) => {
        if (type === 'rise') { dayStart = t; }
        else { if (dayStart != null) daytimeSegs.push([dayStart, t]); dayStart = null; }
    });
    if (dayStart != null) daytimeSegs.push([dayStart, tMax]);

    daytimeSegs.forEach(([tS, tE]) => {
        const xMid = toX((tS + tE) / 2);
        if (xMid < LPAD || xMid > LPAD + gW) return;
        const cy = SUN_Y + SUN_H / 2;
        const r  = 3;
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        ctx.beginPath();
        ctx.arc(xMid, cy, r + 1.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#f59e0b';
        ctx.beginPath();
        ctx.arc(xMid, cy, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = '#f59e0b';
        ctx.lineWidth = 1;
        for (let i = 0; i < 8; i++) {
            const a = (i / 8) * Math.PI * 2;
            ctx.beginPath();
            ctx.moveTo(xMid + Math.cos(a) * (r + 2), cy + Math.sin(a) * (r + 2));
            ctx.lineTo(xMid + Math.cos(a) * (r + 4), cy + Math.sin(a) * (r + 4));
            ctx.stroke();
        }
    });

    // 日の出・日の入マーカー（2行ラベル）
    _tlDrawEventLabels(ctx,
        sunWin.map(({ t, type }) => ({ t, type, x: clampX(toX(t)) })),
        SUN_Y, SUN_H, '#fb923c', 'rgba(251,146,60,0.85)', LPAD, gW,
        { rise: '日の出', set: '日の入' });

    // ── 月バー背景 ────────────────────────────────────────────────
    ctx.fillStyle = '#1e293b';
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.roundRect(LPAD, MOON_Y, gW, MOON_H, 3);
    ctx.fill();

    const moonBefore = moonEvents.filter(e => e.t <= tMin);
    const moonR0 = moonBefore.filter(e => e.type === 'rise').length;
    const moonS0 = moonBefore.filter(e => e.type === 'set').length;
    let moonUpAtStart;
    if (moonR0 > moonS0) {
        moonUpAtStart = true;
    } else if (moonR0 > 0) {
        moonUpAtStart = false;
    } else {
        const firstWin = moonEvents.find(e => e.t > tMin);
        moonUpAtStart = firstWin ? firstWin.type === 'set' : false;
    }

    const moonWin = moonEvents.filter(e => e.t > tMin && e.t < tMax);
    let moonPeriodStart = moonUpAtStart ? tMin : null;

    const drawMoonPeriod = (x1, x2, fromEdge) => {
        if (x2 <= x1) return;
        const fade = Math.min(0.15, 12 / Math.max(1, x2 - x1));
        const hg = ctx.createLinearGradient(x1, 0, x2, 0);
        hg.addColorStop(0, fromEdge ? 'rgba(148,163,184,0.7)' : 'rgba(148,163,184,0)');
        hg.addColorStop(fromEdge ? 0 : fade, 'rgba(148,163,184,0.7)');
        hg.addColorStop(1 - fade, 'rgba(148,163,184,0.7)');
        hg.addColorStop(1, 'rgba(148,163,184,0)');
        ctx.fillStyle = hg;
        ctx.fillRect(x1, MOON_Y, x2 - x1, MOON_H);
        const vg = ctx.createLinearGradient(0, MOON_Y, 0, MOON_Y + MOON_H);
        vg.addColorStop(0,    'rgba(235,245,255,0.45)');
        vg.addColorStop(0.35, 'rgba(160,185,210,0.1)');
        vg.addColorStop(1,    'rgba(30,55,90,0.3)');
        ctx.fillStyle = vg;
        ctx.fillRect(x1, MOON_Y, x2 - x1, MOON_H);
        const hx1 = x1 + (fromEdge ? 0 : (x2 - x1) * fade);
        const hx2 = x2 - (x2 - x1) * fade;
        if (hx2 > hx1) {
            ctx.strokeStyle = 'rgba(210,230,250,0.75)';
            ctx.lineWidth = 1;
            ctx.setLineDash([]);
            ctx.beginPath();
            ctx.moveTo(hx1, MOON_Y + 1);
            ctx.lineTo(hx2, MOON_Y + 1);
            ctx.stroke();
        }
        // 月が出ている期間が十分広い場合にラベルを表示
        if (x2 - x1 > 90) {
            ctx.save();
            ctx.font = '8px sans-serif';
            ctx.fillStyle = 'rgba(200,220,240,0.6)';
            ctx.textAlign = 'center';
            ctx.fillText('月が出ている時間帯', (x1 + x2) / 2, MOON_Y + MOON_H - 4);
            ctx.restore();
        }
    };

    moonWin.forEach(({ t, type }) => {
        if (type === 'rise') {
            moonPeriodStart = t;
        } else {
            if (moonPeriodStart != null) {
                drawMoonPeriod(clampX(toX(moonPeriodStart)), clampX(toX(t)), moonPeriodStart <= tMin);
            }
            moonPeriodStart = null;
        }
    });
    if (moonPeriodStart != null) {
        drawMoonPeriod(clampX(toX(moonPeriodStart)), LPAD + gW, moonPeriodStart <= tMin);
    }

    // 月の出・月の入マーカー（2行ラベル）
    _tlDrawEventLabels(ctx,
        moonWin.map(({ t, type }) => ({ t, type, x: clampX(toX(t)) })),
        MOON_Y, MOON_H, '#94a3b8', 'rgba(148,163,184,0.9)', LPAD, gW,
        { rise: '月の出', set: '月の入' });

    // ── 月齢アイコン（バー中央・グロー アニメーション） ──────────
    const moonPhase  = (todayData || {}).moon_phase ?? (tomorrowData || {}).moon_phase ?? 0;
    const glowPulse  = 0.5 + 0.5 * Math.sin(elapsed * Math.PI * 2 / 3);
    _tlDrawMoonPhaseIcon(ctx, LPAD + gW / 2, MOON_Y + MOON_H / 2, Math.floor(MOON_H / 2) - 1, moonPhase, glowPulse);

    // ── 左側ラベル（太陽の明るさ / 月の状態） ───────────────────
    ctx.font = '8px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillStyle = 'rgba(251,146,60,0.85)';
    ctx.fillText('太陽の明るさ', LPAD - 6, SUN_Y + SUN_H / 2 + 3);
    ctx.fillStyle = 'rgba(148,163,184,0.85)';
    ctx.fillText('月の状態', LPAD - 6, MOON_Y + MOON_H / 2 + 3);

    // ── 現在時刻ライン（破線・中央） ────────────────────────────
    const nowX = clampX(toX(centerMs));
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 3]);
    ctx.beginPath();
    ctx.moveTo(nowX, 4);
    ctx.lineTo(nowX, AXIS_Y + 4);
    ctx.stroke();
    ctx.setLineDash([]);

    // ── 時間軸（±12h 相対ラベル） ───────────────────────────────
    const hMs = 3600 * 1000;
    const t6Start = Math.ceil(tMin / (6 * hMs)) * 6 * hMs;
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 0.5;
    ctx.setLineDash([]);
    ctx.font = '9px sans-serif';
    for (let t = t6Start; t <= tMax; t += 6 * hMs) {
        const x = toX(t);
        if (x < LPAD || x > LPAD + gW) continue;
        ctx.beginPath();
        ctx.moveTo(x, AXIS_Y);
        ctx.lineTo(x, AXIS_Y + 3);
        ctx.stroke();
        const diffH = Math.round((t - centerMs) / hMs);
        const lbl = diffH === 0 ? '現在' : (diffH > 0 ? `+${diffH}h` : `${diffH}h`);
        ctx.fillStyle = diffH === 0 ? '#ef4444' : '#94a3b8';
        ctx.textAlign = 'center';
        ctx.fillText(lbl, x, AXIS_Y + 11);
    }
}

// ── 情報タブ折りたたみ ────────────────────────────────────────────

let _lipLevel = 2;  // 1=compact, 2=standard(default), 3=detail

function _lipAccordionToggle(headerEl) {
    const section = headerEl.closest('.lip-accordion');
    if (!section) return;
    const collapsed = section.classList.toggle('lip-accordion-collapsed');
    const arrow = headerEl.querySelector('.lip-accordion-arrow');
    if (arrow) arrow.textContent = collapsed ? '▾' : '▴';
}

function _lipCycleLevel() {
    _lipLevel = (_lipLevel % 3) + 1;
    _lipApplyLevel();
}

// パネル高さ変化後にグラフ再描画（map-overlay-ui.js の mbc-info-resize イベントで呼ばれる）
window.addEventListener('mbc-info-resize', () => {
    setTimeout(() => {
        const stationId = _selectedTideStation
            ? _selectedTideStation.id
            : (_tideCache && _tideCache.data && _tideCache.data.station
                ? _tideCache.data.station.id : null);
        if (stationId) _tideGraphUpdate(stationId);
    }, 280);
});

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

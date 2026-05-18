/**
 * shelters.js — 指定緊急避難場所 / 指定避難所
 *
 * - refreshEmergencyShelters: 現在の地図範囲内の避難場所を取得・表示
 * - scheduleEmergencyShelterRefresh: デバウンスつき更新スケジューラ
 * - showRouteToEmergencyShelter: 避難場所へのルート表示 + 地図カード表示
 * - clearEmergencyShelterMarkers: 避難場所マーカーのクリア
 * - triggerShelterRoute: ポップアップボタンからルートを起動（グローバル）
 */

// ── 定数 ─────────────────────────────────────────────────────────────────
const SHELTER_CLUSTER_DISABLE_ZOOM = 15;  // これ以上のズームでは個別表示
const SHELTER_CLUSTER_RADIUS       = 50;  // クラスタリング半径(px)
const SHELTER_NEAR_COUNT           = 5;   // 近傍強調件数
const SHELTER_NEAR_MAX_M           = 3000; // 近傍強調上限距離(m)

const SHELTER_ZOOM_SIZE = [
    { maxZoom: 10, size: 14 },
    { maxZoom: 12, size: 18 },
    { maxZoom: 14, size: 22 },
    { maxZoom: 16, size: 28 },
    { maxZoom: Infinity, size: 34 },
];

// ── SVGアイコン ───────────────────────────────────────────────────────────
// 指定緊急避難場所（EES）: 緑の円背景 + 白い走り人形 + 楕円（地面）
const _SVG_EES = `<svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg">
  <circle cx="20" cy="20" r="19" fill="#43a047"/>
  <circle cx="25.5" cy="7.5" r="3.5" fill="white"/>
  <line x1="23.5" y1="11" x2="16.5" y2="20.5" stroke="white" stroke-width="2.8" stroke-linecap="round"/>
  <line x1="21.5" y1="13" x2="28.5" y2="10" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="21.5" y1="13" x2="13.5" y2="16.5" stroke="white" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="16.5" y1="20.5" x2="25" y2="28.5" stroke="white" stroke-width="2.8" stroke-linecap="round"/>
  <line x1="16.5" y1="20.5" x2="10" y2="27.5" stroke="white" stroke-width="2.8" stroke-linecap="round"/>
  <ellipse cx="17" cy="33.5" rx="9.5" ry="3.5" fill="white" opacity="0.88"/>
</svg>`;

// 指定避難所（ES）: 濃い緑の角丸四角形背景 + 白い家の形（屋根＋壁＋扉）
const _SVG_ES = `<svg viewBox="0 0 40 40" xmlns="http://www.w3.org/2000/svg">
  <rect x="0.5" y="0.5" width="39" height="39" rx="6" fill="#2e7d32"/>
  <polygon points="20,3.5 36.5,18 3.5,18" fill="white"/>
  <rect x="5" y="18" width="30" height="18.5" fill="white"/>
  <rect x="15" y="23" width="10" height="13.5" fill="#2e7d32"/>
</svg>`;

// ── ヘルパー関数 ──────────────────────────────────────────────────────────

function _getShelterIconSize() {
    const zoom = (typeof map !== 'undefined' && map) ? map.getZoom() : 14;
    const entry = SHELTER_ZOOM_SIZE.find(e => zoom <= e.maxZoom)
               || SHELTER_ZOOM_SIZE[SHELTER_ZOOM_SIZE.length - 1];
    return entry.size;
}

function _makeShelterIcon(isEES, extraClasses) {
    const size = _getShelterIconSize();
    const cls  = ['shelter-icon',
                  isEES ? 'shelter-icon--eee' : 'shelter-icon--es',
                  ...(extraClasses || [])].join(' ');
    return L.divIcon({
        className:   '',
        html:        `<div class="${cls}" style="width:${size}px;height:${size}px;">${isEES ? _SVG_EES : _SVG_ES}</div>`,
        iconSize:    [size, size],
        iconAnchor:  [size / 2, size],
        popupAnchor: [0, -size],
    });
}

// ハーバーサイン距離（メートル）
function _distM(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2
            + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
            * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// 近傍強調: 現在地から近い SHELTER_NEAR_COUNT 件を near、残りを far にする。
// 現在地未取得時はどちらのクラスも付けない（通常表示に戻す）。
// 将来: 災害種別による適性判定はここに追加できる。
function _applyProximityHighlight() {
    if (_shelterEntries.length === 0) return;

    const loc = (typeof currentLocation !== 'undefined' && currentLocation)
        ? currentLocation : null;

    if (!loc) {
        _shelterEntries.forEach(({ marker }) => {
            const el = marker.getElement();
            if (!el) return;
            el.querySelector('.shelter-icon')?.classList.remove('shelter-icon--near', 'shelter-icon--far');
        });
        return;
    }

    const withDist = _shelterEntries.map(e => ({
        ...e,
        dist: _distM(loc.lat, loc.lon, e.site.lat, e.site.lon),
    })).sort((a, b) => a.dist - b.dist);

    const nearSet = new Set(
        withDist.slice(0, SHELTER_NEAR_COUNT)
                .filter(e => e.dist <= SHELTER_NEAR_MAX_M)
                .map(e => e.marker)
    );

    _shelterEntries.forEach(({ marker }) => {
        const el = marker.getElement();
        if (!el) return;  // クラスター内では DOM がない（ズームで展開時に再適用）
        const icon = el.querySelector('.shelter-icon');
        if (!icon) return;
        if (nearSet.has(marker)) {
            icon.classList.add('shelter-icon--near');
            icon.classList.remove('shelter-icon--far');
        } else {
            icon.classList.remove('shelter-icon--near');
            icon.classList.add('shelter-icon--far');
        }
    });
}

// 選択状態をDOMに反映（前の選択を解除 → 新しい選択にクラス付与）
function _selectShelterMarker(marker) {
    if (selectedEmergencyShelterMarker && selectedEmergencyShelterMarker !== marker) {
        const prevEl = selectedEmergencyShelterMarker.getElement();
        prevEl?.querySelector('.shelter-icon')?.classList.remove('shelter-icon--selected');
    }
    selectedEmergencyShelterMarker = marker;
    const el = marker.getElement();
    el?.querySelector('.shelter-icon')?.classList.add('shelter-icon--selected');
}

// ── クラスタリング ────────────────────────────────────────────────────────
let _shelterClusterGroup = null;
let _shelterEntries      = [];  // [{site, marker}] 近傍強調の計算に使う

function _getOrCreateShelterCluster() {
    if (_shelterClusterGroup) return _shelterClusterGroup;
    _shelterClusterGroup = L.markerClusterGroup({
        showCoverageOnHover:     false,
        maxClusterRadius:        SHELTER_CLUSTER_RADIUS,
        disableClusteringAtZoom: SHELTER_CLUSTER_DISABLE_ZOOM,
        spiderfyOnMaxZoom:       true,
        iconCreateFunction: (cluster) => {
            const count = cluster.getChildCount();
            return L.divIcon({
                className:  '',
                html:       `<div class="shelter-cluster-icon"><span class="shelter-cluster-count">${count}</span></div>`,
                iconSize:   [36, 36],
                iconAnchor: [18, 18],
            });
        },
    });
    map.addLayer(_shelterClusterGroup);
    return _shelterClusterGroup;
}

// ── 既存API ───────────────────────────────────────────────────────────────

function _resolveShelterRegion(site) {
    if (site.region && site.region !== 'unknown') return site.region;
    const src = (site.source_file || '').toLowerCase();
    return Object.keys(shelterRegionVisible).find(r => src.includes(r)) || 'unknown';
}

function _shouldHideEmergencyShelterCandidatesForBrowse() {
    if (!isShelterBrowseLayerVisible || !map || typeof map.getZoom !== 'function') return false;
    const browseZoomMin = typeof SHELTER_BROWSE_CONFIG !== 'undefined'
        ? SHELTER_BROWSE_CONFIG.ZOOM_SHOW_MIN : 11;
    const individualZoom = typeof SHELTER_BROWSE_CONFIG !== 'undefined'
        ? SHELTER_BROWSE_CONFIG.DISABLE_CLUSTERING_ZOOM : 14;
    const zoom = map.getZoom();
    return zoom >= browseZoomMin && zoom < individualZoom;
}

function clearEmergencyShelterMarkers() {
    if (_shelterClusterGroup) {
        _shelterClusterGroup.clearLayers();
    } else {
        emergencyShelterMarkers.forEach(marker => map.removeLayer(marker));
    }
    emergencyShelterMarkers = [];
    _shelterEntries         = [];
}

function scheduleEmergencyShelterRefresh() {
    if (shelterRefreshTimer) clearTimeout(shelterRefreshTimer);
    shelterRefreshTimer = setTimeout(() => { refreshEmergencyShelters(); }, 250);
}

async function refreshEmergencyShelters() {
    if (typeof isMagnitudeModeActive === 'function' && isMagnitudeModeActive()) return;

    const _zoomMin = typeof SHELTER_BROWSE_CONFIG !== 'undefined'
        ? SHELTER_BROWSE_CONFIG.ZOOM_SHOW_MIN : 11;
    if (map.getZoom() < _zoomMin) {
        clearEmergencyShelterMarkers();
        return;
    }

    if (_shouldHideEmergencyShelterCandidatesForBrowse()) {
        clearEmergencyShelterMarkers();
        setShelterStatus('近傍避難候補は広域ブラウズ中のため zoom 14以上で表示されます。');
        return;
    }

    const bounds = map.getBounds();
    const params = new URLSearchParams({
        south: bounds.getSouth().toString(),
        west:  bounds.getWest().toString(),
        north: bounds.getNorth().toString(),
        east:  bounds.getEast().toString(),
        limit: '5000',
    });

    try {
        setShelterStatus('指定緊急避難場所を読み込み中...');
        const response = await apiFetch(`/emergency-shelters?${params.toString()}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
        if (typeof isMagnitudeModeActive === 'function' && isMagnitudeModeActive()) return;

        const cluster = _getOrCreateShelterCluster();
        clearEmergencyShelterMarkers();
        let reopenMarker = null;

        (data.data || []).forEach((site) => {
            const isEES = site.category === 'emergency_evacuation_site';

            if (isEES  && !isEmergencyEvacuationSiteVisible) return;
            if (!isEES && !isEmergencyShelterVisible)        return;

            const siteRegion = _resolveShelterRegion(site);
            if (!shelterRegionVisible[siteRegion]) return;

            const marker = L.marker([site.lat, site.lon], {
                icon:                _makeShelterIcon(isEES),
                bubblingMouseEvents: false,
            });

            marker.bindPopup(_buildShelterPopupHtml(site), { maxWidth: 240 });
            marker.on('click', () => {
                if (selectedEmergencyShelterSite &&
                    Math.abs(site.lat - selectedEmergencyShelterSite.lat) < 1e-8 &&
                    Math.abs(site.lon - selectedEmergencyShelterSite.lon) < 1e-8) {
                    marker.openPopup();
                    return;
                }
                selectedEmergencyShelterSite = site;
                _selectShelterMarker(marker);
                showRouteToEmergencyShelter(site, marker);
            });

            cluster.addLayer(marker);
            emergencyShelterMarkers.push(marker);
            _shelterEntries.push({ site, marker });

            if (selectedEmergencyShelterSite &&
                Math.abs(site.lat - selectedEmergencyShelterSite.lat) < 1e-8 &&
                Math.abs(site.lon - selectedEmergencyShelterSite.lon) < 1e-8) {
                reopenMarker = marker;
            }
        });

        // 再選択状態の復元
        if (reopenMarker) {
            selectedEmergencyShelterMarker = reopenMarker;
            const el = reopenMarker.getElement();
            el?.querySelector('.shelter-icon')?.classList.add('shelter-icon--selected');
        }

        // 近傍強調
        _applyProximityHighlight();

        const totalCount = data.total_count ?? data.count ?? 0;
        setShelterStatus(`表示中: ${data.count || 0} 件（範囲内合計: ${totalCount} 件）`);

        // 避難先マーカー（①②③）を前面に戻す
        if (typeof destinationMarkers !== 'undefined') {
            destinationMarkers.forEach(m => { if (typeof m.bringToFront === 'function') m.bringToFront(); });
        }
    } catch (error) {
        console.error('指定緊急避難場所の取得エラー:', error);
        setShelterStatus(`取得失敗: ${error.message}`);
    }
}

// ── ポップアップ HTML ─────────────────────────────────────────────────────
const _HAZARD_LABEL_JP = {
    tsunami:      '🌊 津波',
    flood:        '🌧 洪水',
    storm_surge:  '🌬 高潮',
    earthquake:   '🏚 地震',
    landslide:    '🏔 崖崩れ',
    fire:         '🔥 大規模火事',
    inland_flood: '💧 内水氾濫',
    volcano:      '🌋 火山',
};

function _buildShelterPopupHtml(site) {
    const isEES = site.category === 'emergency_evacuation_site';
    const nameColor     = isEES ? '#b71c1c' : '#1b5e20';
    const btnColor      = isEES ? '#c62828' : '#2e7d32';
    const categoryLabel = isEES ? '指定緊急避難場所' : '指定避難所';
    const icon          = isEES ? '🚨' : '🏠';

    const addrHtml = site.address
        ? `<div style="font-size:11px;color:#333;margin-bottom:6px;">📍 ${site.address}</div>`
        : '';

    const hazardTypes = Array.isArray(site.hazard_types) ? site.hazard_types : [];
    const hazardHtml  = hazardTypes.length > 0
        ? `<div style="margin-bottom:6px;line-height:1.8;">
               ${hazardTypes.map(h =>
                   `<span style="display:inline-block;padding:1px 7px;border-radius:999px;
                                 font-size:11px;font-weight:600;background:#e3f2fd;color:#1565c0;
                                 margin-right:3px;">${_HAZARD_LABEL_JP[h] || h}</span>`
               ).join('')}
           </div>`
        : '';

    return `
        <div style="font-size:13px;font-weight:700;color:${nameColor};margin-bottom:3px;">
            ${icon} ${site.name || categoryLabel}
        </div>
        <div style="font-size:11px;color:#555;margin-bottom:4px;">${categoryLabel}</div>
        ${addrHtml}
        ${hazardHtml}
        <div style="font-size:11px;color:#888;margin-bottom:8px;">
            ${Number(site.lat).toFixed(5)}, ${Number(site.lon).toFixed(5)}
        </div>
        <button onclick="triggerShelterRoute()"
                style="width:100%;padding:7px;background:${btnColor};color:white;border:none;
                       border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;">
            🗺️ ルートを表示
        </button>
    `;
}

// ポップアップ内ボタンから呼ばれるグローバル関数
function triggerShelterRoute() {
    if (!selectedEmergencyShelterSite || !selectedEmergencyShelterMarker) return;
    map.closePopup();
    showRouteToEmergencyShelter(selectedEmergencyShelterSite, selectedEmergencyShelterMarker);
}

function showRouteToEmergencyShelter(site, marker) {
    if (typeof navigationMode !== 'undefined' &&
        (navigationMode === 'navigation_active' ||
         navigationMode === 'navigation_warning' ||
         navigationMode === 'navigation_paused')) {
        if (typeof stopNavigation === 'function') stopNavigation();
    }
    if (typeof updateNavigatingState === 'function') updateNavigatingState(null);

    showSelectedEmergencyShelter(site);

    if (typeof onNavRouteSelected === 'function') {
        onNavRouteSelected(null, { lat: site.lat, lon: site.lon, name: site.name }, {
            selectedRouteIndex: null,
            transportMode:      null,
            routes:             [],
            routeColors:        [],
            onSelectRouteIndex: null,
            infoMode:           'route_preview',
        });
    }

    const routed = drawRouteTo(site.lat, site.lon, {
        onRoutesAvailable: ({ routes, selectedRouteIndex, routeColors, formatter, transportMode, selectRouteIndex }) => {
            const selectedRoute = Array.isArray(routes) ? routes[selectedRouteIndex] : null;
            if (selectedRoute && selectedRoute.summary) {
                updateSelectedEmergencyShelterRouteInfo(
                    selectedRoute.summary.totalDistance,
                    selectedRoute.summary.totalTime,
                    transportMode
                );
            }
            if (typeof onNavRouteSelected === 'function') {
                onNavRouteSelected(routes[selectedRouteIndex], null, {
                    selectedRouteIndex,
                    transportMode,
                    routes,
                    routeColors,
                    onSelectRouteIndex: selectRouteIndex,
                    infoMode:           'route_preview',
                });
            }
            renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
            renderSelectedEmergencyShelterRouteGuidance(
                routes,
                selectedRouteIndex,
                formatter,
                transportMode,
                selectRouteIndex,
                routeColors
            );
        },
        onRouteError: () => {
            document.getElementById('selectedShelterDistance').textContent = '計算失敗';
            document.getElementById('selectedShelterDuration').textContent = '計算失敗';
            document.getElementById('shelter-card-distance').textContent   = '計算失敗';
            document.getElementById('shelter-card-duration').textContent   = '計算失敗';
            clearSelectedEmergencyShelterRouteGuidance();
        },
    });
    if (!routed) return;
}

'use strict';

/**
 * destination.js — 日常目的地設定
 *
 * Phase 1: 地図クリック・長押しによる仮目的地設定 → 確定 → ルート表示
 * Phase 2: テキスト検索（Nominatim）→ 候補選択 → 確定
 * Phase 3: 目的地クリア
 */

const NOMINATIM_SEARCH_URL = 'https://nominatim.openstreetmap.org/search';
const GSI_GEOCODER_URL     = 'https://msearch.gsi.go.jp/address-search/AddressSearch';

// ── Phase 1: 仮目的地マーカー設定（地図クリック時） ───────────────────────
function setDestinationCandidate(lat, lon, name) {
    userDestinationCandidate = { lat, lon, name: name || `${lat.toFixed(5)}, ${lon.toFixed(5)}` };

    if (userDestinationCandidateMarker) {
        map.removeLayer(userDestinationCandidateMarker);
        userDestinationCandidateMarker = null;
    }

    userDestinationCandidateMarker = L.marker([lat, lon], {
        icon: L.divIcon({
            className: '',
            html: '<div style="font-size:28px;line-height:1;filter:drop-shadow(0 2px 3px rgba(0,0,0,.4));">📍</div>',
            iconSize: [28, 28],
            iconAnchor: [14, 28],
            popupAnchor: [0, -30]
        })
    }).addTo(map);

    const popup = document.createElement('div');
    popup.style.cssText = 'text-align:center; min-width:160px; padding:2px 0;';
    popup.innerHTML = `
        <div style="font-size:12px; color:#555; margin-bottom:6px; word-break:break-all; max-width:200px;">
            ${userDestinationCandidate.name}
        </div>
        <button onclick="confirmUserDestination()"
                style="background:#1976d2;color:#fff;border:none;border-radius:6px;
                       padding:7px 18px;font-size:13px;font-weight:600;cursor:pointer;width:100%;">
            🗺 ここへ行く
        </button>
    `;
    userDestinationCandidateMarker.bindPopup(popup).openPopup();
}

// ── Phase 1: 仮目的地を確定 ───────────────────────────────────────────────
function confirmUserDestination() {
    if (!userDestinationCandidate) return;

    userDestination = {
        lat:    userDestinationCandidate.lat,
        lon:    userDestinationCandidate.lon,
        name:   userDestinationCandidate.name,
        type:   'normal',
        source: 'map_click'
    };

    if (userDestinationCandidateMarker) {
        map.removeLayer(userDestinationCandidateMarker);
        userDestinationCandidateMarker = null;
    }
    userDestinationCandidate = null;

    _applyUserDestination();
}

// ── Phase 2: テキスト検索（GSI住所検索 → Nominatimフォールバック） ─────────
async function searchUserDestination() {
    const input = document.getElementById('destinationSearchInput');
    const query = input ? input.value.trim() : '';
    if (!query) return;

    userDestinationSearchLoading = true;
    userDestinationSearchError   = null;
    userDestinationSearchResults = [];
    _renderSearchResults();

    const loc = (typeof currentLocation !== 'undefined') ? currentLocation : null;

    try {
        // ── Step 1: 国土地理院ジオコーダーで住所検索 ────────────────────────
        let results = await _searchGsi(query, loc);

        // ── Step 2: 結果が空なら Nominatim にフォールバック ─────────────────
        if (results.length === 0) {
            results = await _searchNominatim(query, loc);
        }

        userDestinationSearchResults = results;
        if (userDestinationSearchResults.length === 0) {
            userDestinationSearchError = '候補が見つかりません';
        }
    } catch (e) {
        console.error('[Destination] search error:', e);
        userDestinationSearchError = '検索に失敗しました';
    } finally {
        userDestinationSearchLoading = false;
        _renderSearchResults();
    }
}

async function _searchGsi(query, loc) {
    const res = await fetch(`${GSI_GEOCODER_URL}?q=${encodeURIComponent(query)}`);
    if (!res.ok) return [];
    const data = await res.json();
    if (!Array.isArray(data)) return [];
    return data.map(item => {
        const [lon, lat] = item.geometry.coordinates;
        return {
            lat,
            lon,
            name:     item.properties.title,
            distance: loc ? _calcDistance(loc.lat, loc.lon, lat, lon) : null
        };
    });
}

async function _searchNominatim(query, loc) {
    const params = new URLSearchParams({
        q: query, format: 'json', limit: '20', 'accept-language': 'ja',
        addressdetails: '1'
    });
    if (loc) {
        const R = 0.1; // 約10km
        params.set('viewbox', `${loc.lon - R},${loc.lat + R},${loc.lon + R},${loc.lat - R}`);
        params.set('bounded', '1');
    }
    const res = await fetch(`${NOMINATIM_SEARCH_URL}?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return data.map(item => ({
        lat:      parseFloat(item.lat),
        lon:      parseFloat(item.lon),
        name:     item.display_name,
        distance: loc ? _calcDistance(loc.lat, loc.lon, parseFloat(item.lat), parseFloat(item.lon)) : null
    }));
}

// ── Phase 2: 検索結果から目的地確定 ──────────────────────────────────────
function selectUserDestinationResult(index) {
    const result = userDestinationSearchResults[index];
    if (!result) return;

    userDestination = {
        lat:    result.lat,
        lon:    result.lon,
        name:   result.name,
        type:   'normal',
        source: 'search'
    };
    userDestinationSearchResults = [];
    userDestinationSearchError   = null;

    if (userDestinationCandidateMarker) {
        map.removeLayer(userDestinationCandidateMarker);
        userDestinationCandidateMarker = null;
    }
    userDestinationCandidate = null;

    _renderSearchResults();
    _applyUserDestination();
    map.setView([result.lat, result.lon], 15, { animate: true });
}

// ── Phase 3: 目的地クリア ─────────────────────────────────────────────────
function clearUserDestination() {
    userDestination          = null;
    userDestinationCandidate = null;
    userDestinationSearchResults = [];
    userDestinationSearchError   = null;

    if (userDestinationMarker) {
        map.removeLayer(userDestinationMarker);
        userDestinationMarker = null;
    }
    if (userDestinationCandidateMarker) {
        map.removeLayer(userDestinationCandidateMarker);
        userDestinationCandidateMarker = null;
    }

    clearRouteCandidateLayers();
    clearSelectedRouteHighlight();
    if (typeof clearUserDestRouteGuidance === 'function') clearUserDestRouteGuidance();

    const input = document.getElementById('destinationSearchInput');
    if (input) input.value = '';

    _renderSearchResults();
    _updateDestinationUI();

    // route_preview / finished のナビ状態をリセット
    if (typeof setNavMode === 'function' &&
        typeof navigationMode !== 'undefined' &&
        (navigationMode === 'route_preview' || navigationMode === 'navigation_finished')) {
        setNavMode('browse');
    }
}

// ── 確定後の共通処理 ──────────────────────────────────────────────────────
function _applyUserDestination() {
    _setUserDestinationMarker(userDestination.lat, userDestination.lon, userDestination.name);
    _updateDestinationUI();
    _drawRouteToUserDestination();
}

// ── 確定マーカー設定 ──────────────────────────────────────────────────────
function _setUserDestinationMarker(lat, lon, name) {
    if (userDestinationMarker) {
        map.removeLayer(userDestinationMarker);
    }
    userDestinationMarker = L.marker([lat, lon], {
        icon: L.divIcon({
            className: '',
            html: '<div style="font-size:28px;line-height:1;filter:drop-shadow(0 2px 3px rgba(0,0,0,.4));">🏁</div>',
            iconSize: [28, 28],
            iconAnchor: [14, 28],
            popupAnchor: [0, -30]
        })
    }).bindPopup(`<strong>${name}</strong>`).addTo(map);

    userDestinationMarker.on('click', () => {
        showUserDestInFloatCard();
    });
}

// ── ルート表示（既存 routing/navigation を再利用） ────────────────────────
function _drawRouteToUserDestination() {
    if (!userDestination) return;

    clearRouteCandidateLayers();
    clearSelectedRouteHighlight();

    if (typeof onNavRouteSelected === 'function') {
        onNavRouteSelected(null, {
            lat:  userDestination.lat,
            lon:  userDestination.lon,
            name: userDestination.name
        });
    }

    drawRouteTo(userDestination.lat, userDestination.lon, {
        onRoutesAvailable: ({ routes, selectedRouteIndex, routeColors, formatter, transportMode, selectRouteIndex }) => {
            if (typeof onNavRouteSelected === 'function') {
                onNavRouteSelected(routes[selectedRouteIndex], null);
            }
            renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
            if (typeof renderUserDestRouteGuidance === 'function') {
                renderUserDestRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, (newIndex) => {
                    if (typeof selectRouteIndex === 'function') selectRouteIndex(newIndex);
                }, routeColors);
            }
            // フロートウィンドウに目的地情報・経路案内を表示しナビボタンを注入
            if (typeof showUserDestInFloatCard === 'function') {
                showUserDestInFloatCard();
            }
        },
        onRouteError: () => {
            _showDestinationStatusMsg('ルートを取得できませんでした');
        }
    });
}

// ── 検索結果描画 ──────────────────────────────────────────────────────────
function _renderSearchResults() {
    const list = document.getElementById('destinationSearchResults');
    if (!list) return;

    if (userDestinationSearchLoading) {
        list.innerHTML = '<div class="dest-status-msg">検索中...</div>';
        list.style.display = 'block';
        return;
    }
    if (userDestinationSearchError) {
        list.innerHTML = `<div class="dest-status-msg dest-status-error">${userDestinationSearchError}</div>`;
        list.style.display = 'block';
        return;
    }
    if (userDestinationSearchResults.length > 0) {
        list.innerHTML = userDestinationSearchResults.map((r, i) =>
            `<div class="dest-result-item" onclick="selectUserDestinationResult(${i})">
                <div class="dest-result-name">${r.name}</div>
                ${r.distance !== null ? `<div class="dest-result-distance">${r.distance}</div>` : ''}
            </div>`
        ).join('');
        list.style.display = 'block';
        return;
    }
    list.innerHTML = '';
    list.style.display = 'none';
}

// ── 目的地パネル更新 ──────────────────────────────────────────────────────
function _updateDestinationUI() {
    const nameEl = document.getElementById('destConfirmedName');
    const infoEl = document.getElementById('destConfirmedInfo');
    const hintEl = document.getElementById('destHint');

    if (userDestination) {
        if (nameEl) nameEl.textContent = userDestination.name;
        if (infoEl) infoEl.style.display = 'flex';
        if (hintEl) hintEl.style.display = 'none';
    } else {
        if (infoEl) infoEl.style.display = 'none';
        if (hintEl) hintEl.style.display = 'block';
    }
}

function _showDestinationStatusMsg(msg) {
    const list = document.getElementById('destinationSearchResults');
    if (!list) return;
    list.innerHTML = `<div class="dest-status-msg dest-status-error">${msg}</div>`;
    list.style.display = 'block';
}

// ── 長押し検出（モバイル・デスクトップ共通） ──────────────────────────────
(function _setupDestinationLongPress() {
    const mapEl   = document.getElementById('map');
    const DURATION = 600;
    const MOVE_PX  = 10;

    let _timer             = null;
    let _startPos          = null;
    let _suppressNextClick = false;

    const cancel = () => {
        if (_timer) { clearTimeout(_timer); _timer = null; }
        _startPos = null;
    };

    const fireFromClient = (clientX, clientY) => {
        _timer    = null;
        _startPos = null;
        _suppressNextClick = true;
        // iOS では長押し後に click が発火しないため自動リセット
        setTimeout(() => { _suppressNextClick = false; }, 300);
        const rect   = mapEl.getBoundingClientRect();
        const latlng = map.containerPointToLatLng(
            L.point(clientX - rect.left, clientY - rect.top)
        );
        setDestinationCandidate(latlng.lat, latlng.lng);
    };

    // 長押し後に発火する click でポップアップが閉じないよう抑制
    mapEl.addEventListener('click', (e) => {
        if (_suppressNextClick) { e.stopPropagation(); _suppressNextClick = false; }
    }, true);

    // ── モバイル: Leaflet 内蔵の長押し検出（tap: true がデフォルト）
    // Leaflet は touchstart/touchend のタイミングを管理して
    // contextmenu イベントを発火する。iOS 含む全環境で安定動作。
    map.on('contextmenu', (e) => {
        setDestinationCandidate(e.latlng.lat, e.latlng.lng);
        // 指が離れた瞬間（pointerup）に抑制フラグを立てる。
        // contextmenu 時点で立てると 300ms 後にリセットされ、
        // 指が離れた際の synthetic click を抑制できない。
        mapEl.addEventListener('pointerup', function onUp() {
            mapEl.removeEventListener('pointerup', onUp);
            _suppressNextClick = true;
            setTimeout(() => { _suppressNextClick = false; }, 300);
        }, { once: true, passive: true });
    });

    // ── デスクトップ: マウス長押し（左ボタン 600ms）
    mapEl.addEventListener('mousedown', (e) => {
        if (e.button !== 0) return;
        _startPos = { x: e.clientX, y: e.clientY };
        _timer = setTimeout(() => fireFromClient(e.clientX, e.clientY), DURATION);
    });
    mapEl.addEventListener('mousemove', (e) => {
        if (!_timer || !_startPos) return;
        const dx = e.clientX - _startPos.x;
        const dy = e.clientY - _startPos.y;
        if (Math.sqrt(dx * dx + dy * dy) > MOVE_PX) cancel();
    });
    mapEl.addEventListener('mouseup', cancel);
})();

// ── 現在地からの距離計算（ハバーサイン） ─────────────────────────────────
function _calcDistance(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2
            + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
            * Math.sin(dLon / 2) ** 2;
    const d = R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return d < 1000
        ? `${Math.round(d / 10) * 10}m`
        : `${(d / 1000).toFixed(1)}km`;
}

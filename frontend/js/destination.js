'use strict';

/**
 * destination.js — 日常目的地設定
 *
 * Phase 1: 地図クリック・長押しによる仮目的地設定 → 確定 → ルート表示
 * Phase 2: テキスト検索（Nominatim）→ 候補選択 → 確定
 * Phase 3: 目的地クリア
 */

const NOMINATIM_SEARCH_URL = 'https://nominatim.openstreetmap.org/search';

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

// ── Phase 2: テキスト検索 ─────────────────────────────────────────────────
async function searchUserDestination() {
    const input = document.getElementById('destinationSearchInput');
    const query = input ? input.value.trim() : '';
    if (!query) return;

    userDestinationSearchLoading = true;
    userDestinationSearchError   = null;
    userDestinationSearchResults = [];
    _renderSearchResults();

    try {
        const params = new URLSearchParams({
            q: query, format: 'json', limit: '5', 'accept-language': 'ja'
        });
        const res = await fetch(`${NOMINATIM_SEARCH_URL}?${params}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();

        userDestinationSearchResults = data.map(item => ({
            lat:  parseFloat(item.lat),
            lon:  parseFloat(item.lon),
            name: item.display_name
        }));
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
            renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex);
            if (typeof renderUserDestRouteGuidance === 'function') {
                renderUserDestRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, (newIndex) => {
                    if (typeof selectRouteIndex === 'function') selectRouteIndex(newIndex);
                }, routeColors);
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
            `<div class="dest-result-item" onclick="selectUserDestinationResult(${i})">${r.name}</div>`
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

// ── 長押し検出（Pointer Events API — タッチ・マウス共通） ────────────────
// touchstart/touchcancel の代わりに Pointer Events を使用。
// #map に touch-action: none が設定されている環境では pointercancel が
// 発生しにくく、iOS Safari の touchcancel 問題を回避できる。
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

    const fire = (clientX, clientY) => {
        _timer    = null;
        _startPos = null;
        _suppressNextClick = true;
        const rect   = mapEl.getBoundingClientRect();
        const latlng = map.containerPointToLatLng(
            L.point(clientX - rect.left, clientY - rect.top)
        );
        setDestinationCandidate(latlng.lat, latlng.lng);
    };

    // 長押し後の click でポップアップが閉じないよう捕捉フェーズで抑制
    mapEl.addEventListener('click', (e) => {
        if (_suppressNextClick) { e.stopPropagation(); _suppressNextClick = false; }
    }, true);

    mapEl.addEventListener('pointerdown', (e) => {
        if (isManualLocationMode) return;
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        _startPos = { x: e.clientX, y: e.clientY };
        _timer = setTimeout(() => fire(e.clientX, e.clientY), DURATION);
    }, { passive: true });

    mapEl.addEventListener('pointermove', (e) => {
        if (!_timer || !_startPos) return;
        const dx = e.clientX - _startPos.x;
        const dy = e.clientY - _startPos.y;
        if (Math.sqrt(dx * dx + dy * dy) > MOVE_PX) cancel();
    });

    mapEl.addEventListener('pointerup',     cancel);
    mapEl.addEventListener('pointercancel', cancel);
})();

/**
 * shelters.js — 指定緊急避難場所
 *
 * - refreshEmergencyShelters: 現在の地図範囲内の避難場所を取得・表示
 * - scheduleEmergencyShelterRefresh: デバウンスつき更新スケジューラ
 * - showRouteToEmergencyShelter: 避難場所へのルート表示 + 地図カード表示
 * - clearEmergencyShelterMarkers: 避難場所マーカーのクリア
 * - triggerShelterRoute: ポップアップボタンからルートを起動（グローバル）
 */

function clearEmergencyShelterMarkers() {
    emergencyShelterMarkers.forEach(marker => map.removeLayer(marker));
    emergencyShelterMarkers = [];
}

function scheduleEmergencyShelterRefresh() {
    if (shelterRefreshTimer) {
        clearTimeout(shelterRefreshTimer);
    }
    shelterRefreshTimer = setTimeout(() => {
        refreshEmergencyShelters();
    }, 250);
}

async function refreshEmergencyShelters() {
    const bounds = map.getBounds();
    const params = new URLSearchParams({
        south: bounds.getSouth().toString(),
        west: bounds.getWest().toString(),
        north: bounds.getNorth().toString(),
        east: bounds.getEast().toString(),
        limit: '5000'
    });

    try {
        setShelterStatus('指定緊急避難場所を読み込み中...');
        const response = await apiFetch(`/emergency-shelters?${params.toString()}`);
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || `HTTP ${response.status}`);
        }

        clearEmergencyShelterMarkers();
        let reopenMarker = null;
        (data.data || []).forEach((site) => {
            // 視覚マーカー（小さい緑丸・非インタラクティブ）
            const visMarker = L.circleMarker([site.lat, site.lon], {
                color: '#2e7d32',
                fillColor: '#2e7d32',
                fillOpacity: 0.75,
                radius: 7,
                weight: 1.5,
                interactive: false
            }).addTo(map);

            // ヒットエリア（大きい透明円・タップ判定用）
            const marker = L.circleMarker([site.lat, site.lon], {
                color: 'transparent',
                fillColor: 'transparent',
                fillOpacity: 0,
                radius: 30,
                weight: 0,
                bubblingMouseEvents: false
            }).addTo(map);

            marker.bindPopup(_buildShelterPopupHtml(site), { maxWidth: 240 });
            marker.on('click', () => {
                selectedEmergencyShelterSite   = site;
                selectedEmergencyShelterMarker = marker;
            });
            emergencyShelterMarkers.push(visMarker);
            emergencyShelterMarkers.push(marker);

            // リフレッシュ前に選択されていた避難場所のマーカーを再取得
            if (selectedEmergencyShelterSite &&
                Math.abs(site.lat - selectedEmergencyShelterSite.lat) < 1e-8 &&
                Math.abs(site.lon - selectedEmergencyShelterSite.lon) < 1e-8) {
                reopenMarker = marker;
                selectedEmergencyShelterMarker = marker;
            }
        });

        // 選択中の避難場所が範囲内にあれば、地図カードはそのまま維持（ポップアップは再開しない）
        if (reopenMarker && document.getElementById('shelter-map-card').style.display !== 'none') {
            // カードが開いていた場合はマーカー参照のみ更新（ポップアップは開かない）
        }

        const totalCount = data.total_count ?? data.count ?? 0;
        setShelterStatus(`表示中: ${data.count || 0} 件（範囲内合計: ${totalCount} 件）`);
    } catch (error) {
        console.error('指定緊急避難場所の取得エラー:', error);
        setShelterStatus(`取得失敗: ${error.message}`);
    }
}

function _buildShelterPopupHtml(site) {
    const addrHtml = site.address
        ? `<div style="font-size:11px;color:#333;margin-bottom:6px;">📍 ${site.address}</div>`
        : '';
    return `
        <div style="font-size:13px;font-weight:700;color:#1b5e20;margin-bottom:3px;">
            🏠 ${site.name || '指定緊急避難場所'}
        </div>
        <div style="font-size:11px;color:#555;margin-bottom:4px;">
            ${site.designation || '指定緊急避難場所'}
        </div>
        ${addrHtml}
        <div style="font-size:11px;color:#888;margin-bottom:8px;">
            ${Number(site.lat).toFixed(5)}, ${Number(site.lon).toFixed(5)}
        </div>
        <button onclick="triggerShelterRoute()"
                style="width:100%;padding:7px;background:#2e7d32;color:white;border:none;
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
    // 避難先候補ナビが動いていれば停止し、カード状態をリセット
    if (typeof navigationMode !== 'undefined' &&
        (navigationMode === 'navigation_active' ||
         navigationMode === 'navigation_warning' ||
         navigationMode === 'navigation_paused')) {
        if (typeof stopNavigation === 'function') stopNavigation();
    }
    if (typeof updateNavigatingState === 'function') {
        updateNavigatingState(null);
    }

    // 地図カードに情報を表示
    showSelectedEmergencyShelter(site);

    // ナビモードに目的地を即時通知（navPanel 表示・navDestination 設定）
    if (typeof onNavRouteSelected === 'function') {
        onNavRouteSelected(null, { lat: site.lat, lon: site.lon, name: site.name });
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
            // ナビモードにルートを通知
            if (typeof onNavRouteSelected === 'function') {
                onNavRouteSelected(routes[selectedRouteIndex], null);
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
            document.getElementById('shelter-card-distance').textContent = '計算失敗';
            document.getElementById('shelter-card-duration').textContent = '計算失敗';
            clearSelectedEmergencyShelterRouteGuidance();
        }
    });
    if (!routed) {
        return;
    }
}

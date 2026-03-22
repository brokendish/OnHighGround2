/**
 * shelters.js — 指定緊急避難場所
 *
 * - refreshEmergencyShelters: 現在の地図範囲内の避難場所を取得・表示
 * - scheduleEmergencyShelterRefresh: デバウンスつき更新スケジューラ
 * - showRouteToEmergencyShelter: 避難場所へのルート表示
 * - clearEmergencyShelterMarkers: 避難場所マーカーのクリア
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
        (data.data || []).forEach((site) => {
            const marker = L.circleMarker([site.lat, site.lon], {
                color: '#2e7d32',
                fillColor: '#2e7d32',
                fillOpacity: 0.65,
                radius: 6,
                weight: 1
            }).addTo(map);

            marker.bindPopup(`
                <strong>${site.name || '指定緊急避難場所'}</strong><br>
                区分: ${site.designation || '指定緊急避難場所'}<br>
                ${site.address ? `住所: ${site.address}<br>` : ''}
                緯度: ${Number(site.lat).toFixed(6)}<br>
                経度: ${Number(site.lon).toFixed(6)}
            `);
            marker.on('click', () => {
                showRouteToEmergencyShelter(site, marker);
            });
            emergencyShelterMarkers.push(marker);
        });

        const totalCount = data.total_count ?? data.count ?? 0;
        setShelterStatus(`表示中: ${data.count || 0} 件（範囲内合計: ${totalCount} 件）`);
    } catch (error) {
        console.error('指定緊急避難場所の取得エラー:', error);
        setShelterStatus(`取得失敗: ${error.message}`);
    }
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
            renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex);
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
            clearSelectedEmergencyShelterRouteGuidance();
        }
    });
    if (!routed) {
        return;
    }

    marker.openPopup();
}

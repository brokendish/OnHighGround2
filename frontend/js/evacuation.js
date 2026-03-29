/**
 * evacuation.js — 避難先検索
 *
 * - searchDestinations: /api/evacuation を呼び出し、結果を地図・リストに表示する
 */

async function searchDestinations(isAutoRefresh = false) {
    if (!currentLocation) {
        if (!isAutoRefresh) {
            alert('先に現在地を取得してください');
        }
        return;
    }

    hideSearchMessage();
    hideSelectedEmergencyShelter();

    const btn = document.getElementById('searchDestinations');
    btn.disabled = true;
    btn.textContent = isAutoRefresh ? '再検索中...' : '検索中...';

    // 既存のマーカーをクリア
    clearDestinationMarkers();

    if (routingControl) {
        map.removeControl(routingControl);
        routingControl = null;
    }

    const transportMode = document.getElementById('transportMode').value;
    const maxDistance = parseInt(document.getElementById('maxDistance').value);
    const minElevationGain = parseFloat(document.getElementById('minElevationGain').value);

    try {
        const response = await apiFetch(`/evacuation`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                lat: currentLocation.lat,
                lon: currentLocation.lon,
                transport_mode: transportMode,
                max_distance: maxDistance,
                min_elevation_gain: minElevationGain
            })
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || `HTTP ${response.status}`);
        }
        destinations = data.destinations || [];
        evacuationRecommended = data.recommended || null;
        evacuationHazardStatus = data.hazard_status || null;
        evacuationMeta = data.recommendation_meta || null;
        hasSearchedDestinations = true;

        // 危険判定を表示
        if (evacuationHazardStatus) {
            displayHazardStatus(evacuationHazardStatus);
        }

        // 避難可能エリア (RSA) を表示
        displayRsa(data.reachable_safe_area || null);

        if (destinations.length === 0) {
            showSearchMessage('指定条件で避難先が見つかりませんでした。条件を変更してください。', 'info');
            if (typeof showMapToast === 'function') {
                showMapToast('対象が見つかりませんでした。\n最大距離、高低差のスライダーを見直してください', { warn: true, durationMs: 8000 });
            }
            document.getElementById('destinationsPanel').style.display = 'none';
            document.getElementById('recommendedPanel').style.display = 'none';
            document.getElementById('rsaPanel').style.display = 'none';
        } else {
            // 避難先を地図に表示
            displayDestinations(destinations, evacuationRecommended);

            // リストに表示
            displayDestinationsList(destinations, evacuationRecommended);

            // 推奨避難先カードを表示
            if (evacuationRecommended) {
                displayRecommended(evacuationRecommended, evacuationMeta);
            }

            document.getElementById('destinationsPanel').style.display = 'block';
            hideSearchMessage();
        }

    } catch (error) {
        console.error('検索エラー:', error);
        showSearchMessage(`避難先の検索に失敗しました: ${error.message}`, 'error');
        alert(`避難先の検索に失敗しました: ${error.message}`);
    }

    btn.disabled = false;
    btn.textContent = '避難先を検索';
}

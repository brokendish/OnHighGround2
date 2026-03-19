/**
 * map.js — Leaflet マップ初期化と現在地管理
 *
 * - Leaflet マップの初期化（グローバル変数 `map` を生成）
 * - updateCurrentLocation: 現在地の更新とハザード判定の即時取得
 */

// ── マップ初期化 ──────────────────────────────────────────────────────────
const map = L.map('map').setView([35.6762, 139.6503], 13); // 東京都心を初期位置

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors',
    maxZoom: 19
}).addTo(map);

// ── 現在地更新 ────────────────────────────────────────────────────────────

async function updateCurrentLocation(lat, lon, sourceLabel = '現在地', accuracyMeters = null) {
    currentLocation = { lat, lon, accuracyMeters };

    const response = await apiFetch(
        `/elevation?lat=${lat}&lon=${lon}`
    );
    const data = await response.json();

    if (!response.ok) {
        throw new Error(data.detail || `HTTP ${response.status}`);
    }

    if (typeof data.elevation !== 'number') {
        throw new Error('標高レスポンス形式が不正です');
    }

    document.getElementById('currentLat').textContent = lat.toFixed(6);
    document.getElementById('currentLon').textContent = lon.toFixed(6);
    document.getElementById('currentElev').textContent = data.elevation.toFixed(1);
    document.getElementById('currentAccuracy').textContent = Number.isFinite(accuracyMeters)
        ? `約 ${Math.round(accuracyMeters)} m`
        : '不明';
    document.getElementById('currentLocationInfo').style.display = 'block';

    if (currentMarker) {
        map.removeLayer(currentMarker);
    }
    if (currentAccuracyCircle) {
        map.removeLayer(currentAccuracyCircle);
    }

    currentMarker = L.circleMarker([lat, lon], {
        color: '#2196f3',
        fillColor: '#2196f3',
        fillOpacity: 0.8,
        radius: 10
    }).addTo(map);

    currentMarker.bindPopup(`
        <strong>${sourceLabel}</strong><br>
        標高: ${data.elevation.toFixed(1)} m<br>
        位置精度: ${Number.isFinite(accuracyMeters) ? `約 ${Math.round(accuracyMeters)} m` : '不明'}
    `).openPopup();

    if (Number.isFinite(accuracyMeters) && accuracyMeters > 0) {
        currentAccuracyCircle = L.circle([lat, lon], {
            radius: accuracyMeters,
            color: '#1e88e5',
            weight: 1,
            opacity: 0.7,
            fillColor: '#90caf9',
            fillOpacity: 0.16
        }).addTo(map);
    } else {
        currentAccuracyCircle = null;
    }

    map.setView([lat, lon], 15);
    document.getElementById('searchDestinations').disabled = false;

    // ハザード判定を取得して即時表示
    try {
        const hazardRes = await apiFetch(`/hazard-check?lat=${lat}&lon=${lon}`);
        if (hazardRes.ok) {
            const hazardData = await hazardRes.json();
            displayHazardStatus({
                is_danger: hazardData.is_danger,
                hazards: hazardData.hazards,
            });
        }
    } catch (e) {
        // ハザード判定失敗は非致命的 — サイレントに無視
        console.warn('ハザード判定取得エラー:', e);
    }
}

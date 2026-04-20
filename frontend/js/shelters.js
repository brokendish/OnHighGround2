/**
 * shelters.js — 指定緊急避難場所
 *
 * - refreshEmergencyShelters: 現在の地図範囲内の避難場所を取得・表示
 * - scheduleEmergencyShelterRefresh: デバウンスつき更新スケジューラ
 * - showRouteToEmergencyShelter: 避難場所へのルート表示 + 地図カード表示
 * - clearEmergencyShelterMarkers: 避難場所マーカーのクリア
 * - triggerShelterRoute: ポップアップボタンからルートを起動（グローバル）
 */

/**
 * サイトデータからリージョン識別子を返す共有ヘルパー。
 * バックエンドが region フィールドを持つ場合はそれを優先する。
 * 持たない場合は source_file の部分一致でフォールバックする（後方互換）。
 * どちらにもマッチしない場合は 'unknown' を返す（'tokyo' への暗黙デフォルトを廃止）。
 */
function _resolveShelterRegion(site) {
    if (site.region && site.region !== 'unknown') return site.region;
    const src = (site.source_file || '').toLowerCase();
    return Object.keys(shelterRegionVisible).find(r => src.includes(r)) || 'unknown';
}

function _shouldHideEmergencyShelterCandidatesForBrowse() {
    if (!isShelterBrowseLayerVisible || !map || typeof map.getZoom !== 'function') return false;
    const browseZoomMin = typeof SHELTER_BROWSE_CONFIG !== 'undefined'
        ? SHELTER_BROWSE_CONFIG.ZOOM_SHOW_MIN
        : 11;
    const individualZoom = typeof SHELTER_BROWSE_CONFIG !== 'undefined'
        ? SHELTER_BROWSE_CONFIG.DISABLE_CLUSTERING_ZOOM
        : 14;
    const zoom = map.getZoom();
    return zoom >= browseZoomMin && zoom < individualZoom;
}

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
    if (_shouldHideEmergencyShelterCandidatesForBrowse()) {
        clearEmergencyShelterMarkers();
        setShelterStatus('近傍避難候補は広域ブラウズ中のため zoom 14以上で表示されます。');
        return;
    }

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
            // カテゴリ別に色を分ける
            // emergency_evacuation_site（指定緊急避難場所・13000_2）→ 赤系
            // evacuation_site（指定避難所・13000_1）→ 緑系
            const isEES = site.category === 'emergency_evacuation_site';

            // カテゴリ別表示フラグのチェック
            if (isEES && !isEmergencyEvacuationSiteVisible) return;
            if (!isEES && !isEmergencyShelterVisible) return;

            // 都道府県別表示フラグのチェック
            // region フィールドを優先し、なければ source_file の部分一致で判定する
            const siteRegion = _resolveShelterRegion(site);
            if (!shelterRegionVisible[siteRegion]) return;

            const markerColor = isEES ? '#c62828' : '#2e7d32';

            // 視覚マーカー（小さい丸・非インタラクティブ）
            const visMarker = L.circleMarker([site.lat, site.lon], {
                color: markerColor,
                fillColor: markerColor,
                fillOpacity: 0.75,
                radius: 7,
                weight: 1.5,
                interactive: false
            }).addTo(map);

            // ヒットエリア（透明円・タップ判定用）
            // 以前は広すぎて近傍クリックを拾いやすかったため少し縮小する。
            const marker = L.circleMarker([site.lat, site.lon], {
                color: 'transparent',
                fillColor: 'transparent',
                fillOpacity: 0,
                radius: 32,
                weight: 0,
                bubblingMouseEvents: false
            }).addTo(map);

            marker.bindPopup(_buildShelterPopupHtml(site), { maxWidth: 240 });
            marker.on('click', () => {
                // 同じ避難場所を再タップ → ポップアップで確認
                if (selectedEmergencyShelterSite &&
                    Math.abs(site.lat - selectedEmergencyShelterSite.lat) < 1e-8 &&
                    Math.abs(site.lon - selectedEmergencyShelterSite.lon) < 1e-8) {
                    marker.openPopup();
                    return;
                }
                // 新しい避難場所 → 即ルート計算 + フロートウィンドウ表示
                selectedEmergencyShelterSite   = site;
                selectedEmergencyShelterMarker = marker;
                showRouteToEmergencyShelter(site, marker);
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

        // 選択中の避難場所が範囲内にあれば情報タブはそのまま維持
        if (reopenMarker) {
            // マーカー参照のみ更新（タブは再描画しない）
        }

        const totalCount = data.total_count ?? data.count ?? 0;
        setShelterStatus(`表示中: ${data.count || 0} 件（範囲内合計: ${totalCount} 件）`);

        // 避難先マーカー（①②③）を前面に戻す（避難場所の大きいヒットエリアに隠れないよう）
        if (typeof destinationMarkers !== 'undefined') {
            destinationMarkers.forEach(m => { if (typeof m.bringToFront === 'function') m.bringToFront(); });
        }
    } catch (error) {
        console.error('指定緊急避難場所の取得エラー:', error);
        setShelterStatus(`取得失敗: ${error.message}`);
    }
}

// ハザードキー → 絵文字＋日本語ラベル
const _HAZARD_LABEL_JP = {
    tsunami:     '🌊 津波',
    flood:       '🌧 洪水',
    storm_surge: '🌬 高潮',
    earthquake:  '🏚 地震',
    landslide:   '🏔 崖崩れ',
    fire:        '🔥 大規模火事',
    inland_flood:'💧 内水氾濫',
    volcano:     '🌋 火山',
};

function _buildShelterPopupHtml(site) {
    const isEES = site.category === 'emergency_evacuation_site';
    const nameColor  = isEES ? '#b71c1c' : '#1b5e20';
    const btnColor   = isEES ? '#c62828' : '#2e7d32';
    const categoryLabel = isEES ? '指定緊急避難場所' : '指定避難所';
    const icon = isEES ? '🚨' : '🏠';

    const addrHtml = site.address
        ? `<div style="font-size:11px;color:#333;margin-bottom:6px;">📍 ${site.address}</div>`
        : '';

    // 対応ハザード一覧（アイコンタグ）
    const hazardTypes = Array.isArray(site.hazard_types) ? site.hazard_types : [];
    const hazardHtml = hazardTypes.length > 0
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

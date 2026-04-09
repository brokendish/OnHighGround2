/**
 * app.js — アプリケーション初期化・イベントバインディング
 *
 * すべてのモジュールがロードされた後に実行される初期化コード。
 * イベントリスナーの登録と起動時の初期化呼び出しをここに集約する。
 */

// ── DOM 参照 ──────────────────────────────────────────────────────────────
const manualLocationModeCheckbox = document.getElementById('manualLocationMode');
const manualLocationHint = document.getElementById('manualLocationHint');
const autoRefreshOnManualUpdateCheckbox = document.getElementById('autoRefreshOnManualUpdate');
const showEmergencySheltersCheckbox = document.getElementById('showEmergencyShelters');
const showEmergencyEvacuationSitesCheckbox = document.getElementById('showEmergencyEvacuationSites');

// ── UI コントロールのイベント ──────────────────────────────────────────────

manualLocationModeCheckbox.addEventListener('change', (event) => {
    isManualLocationMode = event.target.checked;
    manualLocationHint.style.display = isManualLocationMode ? 'block' : 'none';
    if (typeof _updateNavUI === 'function') _updateNavUI();
});

/**
 * 手動現在地選択モードを解除する。
 * 明示的にモードを抜ける必要がある場合だけ呼ぶ。
 */
function exitManualLocationMode() {
    if (!isManualLocationMode) return;
    isManualLocationMode = false;
    manualLocationModeCheckbox.checked = false;
    manualLocationHint.style.display = 'none';
    if (typeof _updateNavUI === 'function') _updateNavUI();
}

/**
 * 次の map.click 1回だけ手動現在地更新を抑止する。
 * 長押し目的地設定やポップアップ操作と manual mode の競合回避に使う。
 */
function suppressNextManualLocationSelection() {
    suppressNextManualLocationClick = true;
    setTimeout(() => {
        suppressNextManualLocationClick = false;
    }, 400);
}

/**
 * 指定イベントで発生する次の map.click だけ手動現在地更新を抑止する。
 * 長押し継続中のように click 発生時刻が読めないケース用。
 */
function suppressManualLocationSelectionUntil(eventName, timeoutMs = 1500) {
    let timeoutId = null;
    const release = () => {
        window.removeEventListener(eventName, onEvent, true);
        if (timeoutId) clearTimeout(timeoutId);
    };
    const onEvent = () => {
        suppressNextManualLocationSelection();
        release();
    };

    window.addEventListener(eventName, onEvent, true);
    timeoutId = setTimeout(release, timeoutMs);
}

autoRefreshOnManualUpdateCheckbox.addEventListener('change', (event) => {
    isAutoRefreshOnManualUpdate = event.target.checked;
});

// ── 下部パネル タブ切り替え ───────────────────────────────────────────────
function switchMbcTab(tab) {
    const controls  = document.getElementById('map-bottom-controls');
    const panelAct  = document.getElementById('mbc-tab-panel-action');
    const panelInfo = document.getElementById('mbc-tab-panel-info');
    const btnAct    = document.getElementById('mbc-tab-btn-action');
    const btnInfo   = document.getElementById('mbc-tab-btn-info');
    if (!controls || !panelAct || !panelInfo) return;

    if (tab === 'info') {
        panelAct.style.display  = 'none';
        panelInfo.style.display = 'block';
        btnAct.classList.remove('mbc-tab-btn--active');
        btnInfo.classList.add('mbc-tab-btn--active');
        // 折りたたまれていれば展開
        controls.classList.remove('mbc-collapsed');
    } else {
        panelAct.style.display  = 'block';
        panelInfo.style.display = 'none';
        btnAct.classList.add('mbc-tab-btn--active');
        btnInfo.classList.remove('mbc-tab-btn--active');
    }
}

// タブボタン
document.getElementById('mbc-tab-btn-action').addEventListener('click', () => switchMbcTab('action'));
document.getElementById('mbc-tab-btn-info').addEventListener('click',   () => switchMbcTab('info'));

// 情報タブ内スクロールが地図パンに伝播しないようにする
const mbcInfoPanel = document.getElementById('mbc-tab-panel-info');
if (mbcInfoPanel && typeof L !== 'undefined') {
    L.DomEvent.disableScrollPropagation(mbcInfoPanel);
}

showEmergencySheltersCheckbox.addEventListener('change', (event) => {
    isEmergencyShelterVisible = event.target.checked;
    clearEmergencyShelterMarkers();
    if (!isEmergencyShelterVisible && !isEmergencyEvacuationSiteVisible) {
        setShelterStatus('避難場所の表示をOFFにしています。');
        hideSelectedEmergencyShelter();
        return;
    }
    scheduleEmergencyShelterRefresh();
});

showEmergencyEvacuationSitesCheckbox.addEventListener('change', (event) => {
    isEmergencyEvacuationSiteVisible = event.target.checked;
    clearEmergencyShelterMarkers();
    if (!isEmergencyShelterVisible && !isEmergencyEvacuationSiteVisible) {
        setShelterStatus('避難場所の表示をOFFにしています。');
        hideSelectedEmergencyShelter();
        return;
    }
    scheduleEmergencyShelterRefresh();
});

// ── 地図イベント ──────────────────────────────────────────────────────────

map.on('moveend', () => {
    if (!isEmergencyShelterVisible && !isEmergencyEvacuationSiteVisible) {
        return;
    }
    scheduleEmergencyShelterRefresh();
});

map.on('zoomend', () => {
    if (!isEmergencyShelterVisible && !isEmergencyEvacuationSiteVisible) {
        return;
    }
    scheduleEmergencyShelterRefresh();
});


map.on('click', async (event) => {
    const { lat, lng } = event.latlng;

    if (!isManualLocationMode) {
        // 手動選択モードでなければ何もしない（目的地ピン立ては長押しで行う）
        return;
    }
    if (suppressNextManualLocationClick) {
        suppressNextManualLocationClick = false;
        return;
    }

    const shouldRefreshDestinations = hasSearchedDestinations;

    try {
        await updateCurrentLocation(lat, lng, '現在地（手動選択）');
        if (typeof fetchCurrentLocInfo === 'function') {
            fetchCurrentLocInfo(lat, lng, currentLocation && currentLocation.elevation);
        }
    } catch (error) {
        console.error('手動選択位置の標高取得エラー:', error);
        alert(`手動選択した地点の標高データ取得に失敗しました: ${error.message}`);
        return;
    }

    if (shouldRefreshDestinations && isAutoRefreshOnManualUpdate) {
        try {
            await searchDestinations(true);
        } catch (error) {
            console.error('手動選択後の自動再検索エラー:', error);
        }
    } else if (shouldRefreshDestinations) {
        clearSearchResults();
    }
});

// ── ボタンのイベント ──────────────────────────────────────────────────────

document.getElementById('getCurrentLocation').addEventListener('click', async () => {
    const btn = document.getElementById('getCurrentLocation');
    btn.disabled = true;
    btn.textContent = '位置情報を取得中...';

    if (!navigator.geolocation) {
        alert('お使いのブラウザは位置情報に対応していません。手動選択モードをONにして地図から現在地を選択してください。');
        btn.disabled = false;
        btn.textContent = '現在地を取得';
        return;
    }

    navigator.geolocation.getCurrentPosition(
        async (position) => {
            const lat = position.coords.latitude;
            const lon = position.coords.longitude;
            const accuracyMeters = Number(position.coords.accuracy);

            try {
                await updateCurrentLocation(lat, lon, '現在地', accuracyMeters);
                if (typeof fetchCurrentLocInfo === 'function') {
                    fetchCurrentLocInfo(lat, lon, currentLocation && currentLocation.elevation);
                }
            } catch (error) {
                console.error('標高取得エラー:', error);
                alert(`標高データの取得に失敗しました: ${error.message}`);
            }

            btn.disabled = false;
            btn.textContent = '現在地を取得';
        },
        (error) => {
            console.error('位置情報取得エラー:', error);
            alert('位置情報の取得に失敗しました。設定を確認するか、手動選択モードをONにして地図から現在地を選択してください。');
            btn.disabled = false;
            btn.textContent = '現在地を取得';
        },
        {
            enableHighAccuracy: true,
            timeout: 10000,
            maximumAge: 0
        }
    );
});

document.getElementById('searchDestinations').addEventListener('click', async () => {
    await searchDestinations(false);
});

document.getElementById('clearMap').addEventListener('click', () => {
    clearSearchResults();
});

// ── 起動時の初期化 ────────────────────────────────────────────────────────

scheduleEmergencyShelterRefresh();
initializeHazardToggles();

// ── 起動時の自動現在地取得 ────────────────────────────────────────────────
if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
        async (position) => {
            try {
                const lat = position.coords.latitude;
                const lon = position.coords.longitude;
                await updateCurrentLocation(lat, lon, '現在地', Number(position.coords.accuracy));
                if (typeof fetchCurrentLocInfo === 'function') {
                    fetchCurrentLocInfo(lat, lon, currentLocation && currentLocation.elevation);
                }
            } catch (e) {
                console.warn('起動時の現在地取得エラー:', e);
            }
        },
        (error) => {
            console.warn('起動時の位置情報取得失敗:', error.message);
        },
        { enableHighAccuracy: true, timeout: 10000, maximumAge: 0 }
    );
}

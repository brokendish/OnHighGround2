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

// 「現在地を取得」ボタン（サイドバー）→ 地図を現在地にセンタリング
document.getElementById('getCurrentLocation').addEventListener('click', () => {
    if (currentLocation) {
        map.setView([currentLocation.lat, currentLocation.lon], 15, { animate: true });
    }
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

// ── 常時 GPS 追跡（watchPosition） ────────────────────────────────────────
// アプリ起動時から継続的に位置を追跡する。
// 初回フィックスは地図を自動センタリング。以降はマーカー＋ハンドルバーのみ更新。
let _gpsWatchId = null;
let _isFirstLocationFix = true;
let _gpsHighAccuracy = false; // 現在の精度モード（ナビ中は true）

function _startLocationWatch(highAccuracy = false) {
    if (!navigator.geolocation) {
        console.warn('[GPS] Geolocation not supported');
        return;
    }
    if (_gpsWatchId !== null) return; // 二重登録防止

    _gpsHighAccuracy = highAccuracy;
    console.info('[GPS] high accuracy:', highAccuracy);

    const options = highAccuracy
        ? { enableHighAccuracy: true,  timeout: 10000, maximumAge: 0 }
        : { enableHighAccuracy: false, timeout: 10000, maximumAge: 15000 };

    _gpsWatchId = navigator.geolocation.watchPosition(
        async (position) => {
            // 手動選択モード中は自動更新しない
            if (isManualLocationMode) return;

            const lat      = position.coords.latitude;
            const lon      = position.coords.longitude;
            const accuracy = Number(position.coords.accuracy);
            const recenter = _isFirstLocationFix;
            _isFirstLocationFix = false;

            try {
                await updateCurrentLocation(lat, lon, '現在地', accuracy, recenter);
                if (typeof fetchCurrentLocInfo === 'function') {
                    fetchCurrentLocInfo(lat, lon, currentLocation && currentLocation.elevation, accuracy);
                }
            } catch (e) {
                console.warn('[GPS] 位置更新エラー:', e);
            }
        },
        (error) => {
            console.warn('[GPS] 位置情報取得失敗:', error.message);
        },
        options
    );
}

_startLocationWatch();

// ── 画面非表示時に GPS 追跡を停止して電池消費を抑える ────────────────────
document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
        if (_gpsWatchId !== null) {
            navigator.geolocation.clearWatch(_gpsWatchId);
            _gpsWatchId = null;
            console.log('[GPS] 画面非表示 → 追跡停止');
        }
    } else {
        _startLocationWatch(_gpsHighAccuracy); // 復帰時は停止前と同じ精度モードで再開
        console.log('[GPS] 画面復帰 → 追跡再開');
    }
});

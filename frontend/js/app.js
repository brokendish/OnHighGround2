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

// ── UI コントロールのイベント ──────────────────────────────────────────────

manualLocationModeCheckbox.addEventListener('change', (event) => {
    isManualLocationMode = event.target.checked;
    manualLocationHint.style.display = isManualLocationMode ? 'block' : 'none';
    if (typeof _updateNavUI === 'function') _updateNavUI();
});

autoRefreshOnManualUpdateCheckbox.addEventListener('change', (event) => {
    isAutoRefreshOnManualUpdate = event.target.checked;
});

showEmergencySheltersCheckbox.addEventListener('change', (event) => {
    isEmergencyShelterVisible = event.target.checked;
    if (!isEmergencyShelterVisible) {
        clearEmergencyShelterMarkers();
        setShelterStatus('指定緊急避難場所の表示をOFFにしています。');
        hideSelectedEmergencyShelter();
        return;
    }
    scheduleEmergencyShelterRefresh();
});

// ── 地図イベント ──────────────────────────────────────────────────────────

map.on('moveend', () => {
    if (!isEmergencyShelterVisible) {
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

    const shouldRefreshDestinations = hasSearchedDestinations;

    try {
        await updateCurrentLocation(lat, lng, '現在地（手動選択）');
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
                await updateCurrentLocation(
                    position.coords.latitude,
                    position.coords.longitude,
                    '現在地',
                    Number(position.coords.accuracy)
                );
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

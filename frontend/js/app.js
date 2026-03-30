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

const shelterMapCard = document.getElementById('shelter-map-card');
document.getElementById('shelter-map-card-close').addEventListener('click', () => {
    hideSelectedEmergencyShelter();
});

// ── フロートカード コンパクト/展開 トグル ─────────────────────────────────
function setShelterCardCompact(compact) {
    if (compact) {
        shelterMapCard.classList.add('shelter-card--compact');
    } else {
        shelterMapCard.classList.remove('shelter-card--compact');
        // 展開時は height をリセット（CSS の 55vh に戻す）
        shelterMapCard.style.height = '';
    }
}

// ヘッダータップ: コンパクト時のみ展開する
document.getElementById('shelter-map-card-header').addEventListener('click', (e) => {
    // ×ボタン・展開ボタン自体のクリックは個別に処理するのでヘッダーエリアのみ
    if (e.target.closest('#shelter-map-card-close')) return;
    if (shelterMapCard.classList.contains('shelter-card--compact')) {
        setShelterCardCompact(false);
    }
});

// 展開ボタン（「詳細 ∨」）
document.getElementById('shelter-card-expand-btn').addEventListener('click', (e) => {
    e.stopPropagation();
    setShelterCardCompact(false);
});
// カード内スクロールが地図に伝播しないようにする
L.DomEvent.disableScrollPropagation(shelterMapCard);
// リサイズハンドル
(function makeResizable(card) {
    const handle = card.querySelector('#shelter-card-resize-handle');
    if (!handle) return;
    let resizing = false;
    let startY, startH;

    function resizeStart(cy) {
        resizing = true;
        startY = cy;
        startH = card.offsetHeight;
    }
    function resizeMove(cy) {
        if (!resizing) return;
        const dy = cy - startY;
        const newH = Math.min(Math.max(startH + dy, 140), window.innerHeight * 0.85);
        card.style.height = newH + 'px';
    }
    function resizeEnd() { resizing = false; }

    handle.addEventListener('mousedown',  (e) => { e.preventDefault(); resizeStart(e.clientY); });
    document.addEventListener('mousemove', (e) => resizeMove(e.clientY));
    document.addEventListener('mouseup',   resizeEnd);

    handle.addEventListener('touchstart',  (e) => { resizeStart(e.touches[0].clientY); }, { passive: true });
    document.addEventListener('touchmove',  (e) => { if (!resizing) return; e.preventDefault(); resizeMove(e.touches[0].clientY); }, { passive: false });
    document.addEventListener('touchend',   resizeEnd);
})(shelterMapCard);
// カードをドラッグ可能にする（ヘッダー部分をつかんで移動）
(function makeDraggable(card) {
    const header = card.querySelector('#shelter-map-card-header');
    if (!header) return;
    header.style.cursor = 'grab';

    let dragging = false;
    let startX, startY, origLeft, origTop;

    function dragStart(cx, cy) {
        dragging = true;
        const parentRect = card.parentElement.getBoundingClientRect();
        const cardRect   = card.getBoundingClientRect();
        // 親要素基準の座標に変換して top/left で固定（bottom 基準を解除）
        origLeft = cardRect.left - parentRect.left;
        origTop  = cardRect.top  - parentRect.top;
        card.style.transform = 'none';
        card.style.left      = origLeft + 'px';
        card.style.top       = origTop  + 'px';
        card.style.bottom    = 'auto';
        startX = cx;
        startY = cy;
        header.style.cursor = 'grabbing';
        L.DomEvent.disableClickPropagation(card);
    }

    function dragMove(cx, cy) {
        if (!dragging) return;
        const dx = cx - startX;
        const dy = cy - startY;
        const parent  = card.parentElement;
        const newLeft = Math.max(0, Math.min(origLeft + dx, parent.offsetWidth  - card.offsetWidth));
        const newTop  = Math.max(0, Math.min(origTop  + dy, parent.offsetHeight - card.offsetHeight));
        card.style.left = newLeft + 'px';
        card.style.top  = newTop  + 'px';
    }

    function dragEnd() {
        dragging = false;
        header.style.cursor = 'grab';
    }

    // マウス（コンパクト時はドラッグしない）
    header.addEventListener('mousedown', (e) => {
        if (card.classList.contains('shelter-card--compact')) return;
        e.preventDefault();
        dragStart(e.clientX, e.clientY);
    });
    document.addEventListener('mousemove', (e) => dragMove(e.clientX, e.clientY));
    document.addEventListener('mouseup',   dragEnd);

    // タッチ（コンパクト時はドラッグしない）
    header.addEventListener('touchstart', (e) => {
        if (card.classList.contains('shelter-card--compact')) return;
        const t = e.touches[0];
        dragStart(t.clientX, t.clientY);
    }, { passive: true });
    document.addEventListener('touchmove', (e) => {
        if (!dragging) return;
        e.preventDefault();
        const t = e.touches[0];
        dragMove(t.clientX, t.clientY);
    }, { passive: false });
    document.addEventListener('touchend', dragEnd);
})(shelterMapCard);

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

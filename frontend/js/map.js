/**
 * map.js — Leaflet マップ初期化と現在地管理
 *
 * - Leaflet マップの初期化（グローバル変数 `map` を生成）
 * - updateCurrentLocation: 現在地の更新とハザード判定の即時取得
 */

// ── マップ初期化 ──────────────────────────────────────────────────────────
const map = L.map('map').setView([35.6762, 139.6503], 13); // 東京都心を初期位置

// ── ダブルタップ / ダブルタップ＋ドラッグズーム（Google Maps 風） ──────────
// 短いダブルタップ → 1 段階ズームイン（既存動作）
// 2 回目タップを HOLD_THRESHOLD_MS 以上保持してからドラッグ →
//   下方向ドラッグで拡大 / 上方向ドラッグで縮小
(function _setupDoubleTapZoom() {
    // ── 定数（閾値はここだけで調整） ─────────────────────────────────────
    const DOUBLE_TAP_MS     = 300;    // ダブルタップとみなす最大間隔 (ms)
    const TAP_RADIUS_PX     = 30;     // 同一場所とみなす最大距離 (px)
    const HOLD_THRESHOLD_MS = 200;    // ドラッグズーム起動までの保持時間 (ms)
    const DRAG_SENSITIVITY  = 0.025;  // ズーム変化量 / px（下ドラッグ = 拡大）
    const MOVE_CANCEL_PX    = 8;      // 保持中にこれ以上動いたらドラッグズーム中断 (px)

    // ── 状態変数 ──────────────────────────────────────────────────────────
    let firstTapTime    = 0;
    let firstTapPos     = null;
    let inSecondTap     = false;   // 2 回目タップ保持中
    let secondTapPos    = null;    // 2 回目タップ位置（ズームの中心点）
    let holdTimer       = null;
    let dragZoomActive  = false;   // ドラッグズームモード中
    let dragStartY      = 0;
    let dragStartZoom   = 0;

    const mapEl = document.getElementById('map');

    /** ドラッグズーム関連の全状態をリセットし、map ドラッグを復元する */
    function _reset() {
        clearTimeout(holdTimer);
        holdTimer      = null;
        inSecondTap    = false;
        secondTapPos   = null;
        dragZoomActive = false;
        if (map.dragging && !map.dragging.enabled()) {
            map.dragging.enable();
        }
    }

    // ── touchstart: 2 回目タップ検出とホールドタイマー起動 ──────────────
    // オーバーレイ要素上の touchstart は stopPropagation() で遮断済みのため
    // mapEl まで届かない。追加チェックは保険として残す。
    mapEl.addEventListener('touchstart', function(e) {
        // 複数指タッチ → ピンチ操作 → リセットして抜ける
        if (e.touches.length !== 1) { _reset(); return; }

        const touch = e.touches[0];
        const now   = Date.now();
        const pos   = { x: touch.clientX, y: touch.clientY };

        if (firstTapPos && now - firstTapTime < DOUBLE_TAP_MS) {
            const dx = pos.x - firstTapPos.x;
            const dy = pos.y - firstTapPos.y;
            if (Math.sqrt(dx * dx + dy * dy) < TAP_RADIUS_PX) {
                // 2 回目タップ確定
                inSecondTap   = true;
                secondTapPos  = pos;
                dragStartY    = touch.clientY;
                dragStartZoom = map.getZoom();

                // ホールド中の地図パンを即時抑制
                map.dragging.disable();

                // HOLD_THRESHOLD_MS 後にドラッグズームモード開始
                holdTimer = setTimeout(function() {
                    dragZoomActive = true;
                }, HOLD_THRESHOLD_MS);

                // ブラウザのデフォルト動作（スクロール等）を抑制
                e.preventDefault();
                return;
            }
        }

        // 2 回目タップでなかった場合は 1 回目タップの位置のみ更新
        // （firstTapTime/firstTapPos は touchend 側で正式記録）
    }, { passive: false });

    // ── touchmove: ドラッグズーム処理 / 保持中の誤移動キャンセル ────────
    mapEl.addEventListener('touchmove', function(e) {
        if (dragZoomActive) {
            // ドラッグズームモード: 下方向ドラッグ = 拡大
            if (e.touches.length !== 1) { _reset(); return; }
            e.preventDefault();

            const touch   = e.touches[0];
            const deltaY  = touch.clientY - dragStartY;  // 下 = 正 = 拡大
            const newZoom = dragStartZoom + deltaY * DRAG_SENSITIVITY;
            const rect    = mapEl.getBoundingClientRect();
            const pt      = L.point(
                secondTapPos.x - rect.left,
                secondTapPos.y - rect.top
            );
            map.setZoomAround(pt, newZoom, { animate: false });
            return;
        }

        if (inSecondTap) {
            // ホールドタイマー待機中に指が動きすぎた → ドラッグズームを中断
            if (e.touches.length === 1) {
                const dy = Math.abs(e.touches[0].clientY - dragStartY);
                const dx = Math.abs(e.touches[0].clientX - secondTapPos.x);
                if (dx > MOVE_CANCEL_PX || dy > MOVE_CANCEL_PX) {
                    _reset();
                    firstTapTime = 0;
                    firstTapPos  = null;
                }
            }
        }
    }, { passive: false });

    // ── touchend: ドラッグズーム終了 or 短いダブルタップ → 1 段階ズーム ─
    mapEl.addEventListener('touchend', function(e) {
        if (dragZoomActive) {
            // ドラッグズーム終了 → リセットのみ（ズーム値はそのまま維持）
            _reset();
            e.preventDefault();
            return;
        }

        if (inSecondTap) {
            // ホールド前に離した → 通常ダブルタップ（1 段階ズームイン）
            clearTimeout(holdTimer);
            holdTimer   = null;
            inSecondTap = false;

            if (e.changedTouches.length === 1 && e.touches.length === 0) {
                e.preventDefault();
                const touch = e.changedTouches[0];
                const rect  = mapEl.getBoundingClientRect();
                const pt    = L.point(
                    touch.clientX - rect.left,
                    touch.clientY - rect.top
                );
                map.setZoomAround(pt, map.getZoom() + 1, { animate: true });
            }
            secondTapPos = null;
            firstTapTime = 0;
            firstTapPos  = null;
            map.dragging.enable();
            return;
        }

        // 通常タップ終了 → 1 回目タップとして記録
        if (e.changedTouches.length !== 1 || e.touches.length > 0) return;

        const touch  = e.changedTouches[0];
        firstTapTime = Date.now();
        firstTapPos  = { x: touch.clientX, y: touch.clientY };
    }, { passive: false });

    // ── touchcancel: 予期しない中断 → 全状態リセット ────────────────────
    mapEl.addEventListener('touchcancel', function() {
        _reset();
        firstTapTime = 0;
        firstTapPos  = null;
    });
})();

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors',
    maxZoom: 19
}).addTo(map);

// ── 現在地マーカー（矢印アイコン共通） ───────────────────────────────────

let _currentHeading = null; // コンパス or GPS heading（北を0°として時計回り）

/** GPS精度状態からパルスのCSSクラスを返す */
function _getAccuracyClass(accuracyMeters, highAccuracy) {
    if (!accuracyMeters) return 'accuracy-none';
    if (highAccuracy)    return 'accuracy-high';
    if (accuracyMeters > 100) return 'accuracy-low';
    return 'accuracy-normal';
}

/** 現在の heading を使って divIcon を生成する */
function _makeCurrentLocationIcon(accuracyClass = 'accuracy-none') {
    return L.divIcon({
        className: 'user-arrow-marker',
        html: `<div class="pulse-ring ${accuracyClass}"></div><div class="arrow"></div>`,
        iconSize: [48, 48],
        iconAnchor: [24, 24]
    });
}

/** heading を更新してマーカーの矢印を回転させる（再生成不要） */
function updateUserMarkerHeading(heading) {
    _currentHeading = heading;
    if (!currentMarker) return;
    const el = currentMarker.getElement ? currentMarker.getElement() : null;
    if (!el) return;
    const arrow = el.querySelector('.arrow');
    if (arrow) arrow.style.transform = `rotate(${heading}deg)`;
}

/** DeviceOrientation イベントハンドラ */
function _handleOrientation(event) {
    let heading = null;
    if (event.webkitCompassHeading != null) {
        // iOS: 磁北から時計回り（そのまま使用）
        heading = event.webkitCompassHeading;
    } else if (event.alpha != null) {
        // Android 等: alpha は反時計回りなので変換
        heading = (360 - event.alpha + 360) % 360;
    }
    if (heading === null) return;
    updateUserMarkerHeading(heading);
}

/**
 * コンパス（DeviceOrientation）取得を初期化する。
 * iOS は必ずユーザー操作後（ナビ開始ボタン押下時）に呼ぶこと。
 */
function initOrientation() {
    if (typeof DeviceOrientationEvent !== 'undefined' &&
        typeof DeviceOrientationEvent.requestPermission === 'function') {
        // iOS 13+: ユーザー許可が必要
        DeviceOrientationEvent.requestPermission()
            .then(state => {
                if (state === 'granted') {
                    window.addEventListener('deviceorientation', _handleOrientation, true);
                    console.log('[Orientation] iOS compass enabled');
                }
            })
            .catch(err => console.warn('[Orientation] permission error:', err));
    } else if ('ondeviceorientationabsolute' in window) {
        // Android: absolute（真北基準）を優先
        window.addEventListener('deviceorientationabsolute', _handleOrientation, true);
        console.log('[Orientation] absolute compass enabled');
    } else {
        // フォールバック
        window.addEventListener('deviceorientation', _handleOrientation, true);
        console.log('[Orientation] relative compass enabled');
    }
}

// ── 現在地更新 ────────────────────────────────────────────────────────────

async function updateCurrentLocation(lat, lon, sourceLabel = '現在地', accuracyMeters = null, recenter = true) {
    currentLocation = { lat, lon, accuracyMeters, elevation: null };

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

    currentLocation.elevation = data.elevation;

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

    const _accClass = _getAccuracyClass(accuracyMeters,
        typeof _gpsHighAccuracy !== 'undefined' ? _gpsHighAccuracy : false);
    currentMarker = L.marker([lat, lon], { icon: _makeCurrentLocationIcon(_accClass) }).addTo(map);

    // 直前の heading があれば即時反映
    if (_currentHeading !== null) updateUserMarkerHeading(_currentHeading);

    // Leaflet popup の代わりに上部バナーで一時表示
    _showLocationBanner(
        `標高 ${data.elevation.toFixed(1)} m ｜ 精度 ${Number.isFinite(accuracyMeters) ? `約 ${Math.round(accuracyMeters)} m` : '不明'}`
    );

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

    if (recenter) map.setView([lat, lon], 15);
    document.getElementById('searchDestinations').disabled = false;
    // STEP 1 完了 → STEP 2 をアクティブ化（map-overlay-ui.js）
    if (typeof markStep1Done === 'function') markStep1Done();

    // ハザード判定を取得して即時表示
    try {
        const hazardRes = await apiFetch(`/hazard-check?lat=${lat}&lon=${lon}`);
        if (hazardRes.ok) {
            const hazardData = await hazardRes.json();
            displayHazardStatus({
                is_danger: hazardData.is_danger,
                hazards: hazardData.hazards,
                assessment: hazardData.hazard_assessment,
            });
        }
    } catch (e) {
        // ハザード判定失敗は非致命的 — サイレントに無視
        console.warn('ハザード判定取得エラー:', e);
    }
}

// ── 現在地情報バナー（3秒でフェードアウト） ──────────────────────────────
let _locationBannerTimer = null;
function _showLocationBanner(text) {
    const el = document.getElementById('location-banner');
    if (!el) return;

    clearTimeout(_locationBannerTimer);
    el.textContent = text;
    el.classList.add('visible');

    _locationBannerTimer = setTimeout(() => {
        el.classList.remove('visible');
    }, 3000);
}

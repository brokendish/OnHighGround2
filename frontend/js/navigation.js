'use strict';

/**
 * navigation.js — ナビゲーションモード
 *
 * Phase 1: watchPosition による現在地継続取得・マーカー更新・地図追従
 * Phase 2: ルート逸脱判定・警告バナー・再検索ボタン
 */

// ── 定数 ──────────────────────────────────────────────────────────────────
const NAV_OFF_ROUTE_M      = 40;  // 逸脱判定しきい値（メートル）
const NAV_CONSECUTIVE      = 3;   // 連続 N 回外れたら warning
const NAV_ARRIVAL_M        = 20;  // 到達判定しきい値（メートル）
const NAV_MIN_DELTA_M      = 8;   // 移動量がこれ以下なら更新スキップ
const NAV_LOW_ACCURACY_M   = 50;  // GPS 精度がこれ以上なら精度警告

// ── Haversine 距離（メートル） ─────────────────────────────────────────────
function _navHaversine(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const toRad = x => x * Math.PI / 180;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2
            + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// ── ルートへの最近傍距離 ──────────────────────────────────────────────────
function _distanceToRoute(lat, lon) {
    if (!navActiveRoute || !Array.isArray(navActiveRoute.coordinates)) return Infinity;
    let min = Infinity;
    for (const c of navActiveRoute.coordinates) {
        const d = _navHaversine(lat, lon, c.lat, c.lng);
        if (d < min) min = d;
    }
    return min;
}

// ── モード変更 ────────────────────────────────────────────────────────────
function setNavMode(mode) {
    navigationMode = mode;
    _updateNavUI();
}

// ── ナビ開始 ──────────────────────────────────────────────────────────────
function startNavigation() {
    // navDestination が未設定の場合、案内中の避難先から補完
    if (!navDestination && typeof activeNavigatingIndex !== 'undefined'
            && activeNavigatingIndex !== null
            && typeof destinations !== 'undefined' && destinations[activeNavigatingIndex]) {
        const d = destinations[activeNavigatingIndex];
        navDestination = { lat: d.lat, lon: d.lon };
    }
    if (!navDestination) {
        alert('先にルートを表示してからナビを開始してください。');
        return;
    }
    if (!navigator.geolocation) {
        alert('このブラウザは位置情報に対応していません。');
        return;
    }
    navOffRouteCount = 0;
    navIsAutoFollow  = true;
    navWatchId = navigator.geolocation.watchPosition(
        _onNavPosition,
        _onNavPositionError,
        { enableHighAccuracy: true, maximumAge: 3000, timeout: 10000 }
    );
    setNavMode('navigation_active');
    _showNavBanner('🧭 ナビを開始しました。現在地を追跡中です。', 'info', 3000);
}

// ── ナビ停止 ──────────────────────────────────────────────────────────────
function stopNavigation() {
    if (navWatchId !== null) {
        navigator.geolocation.clearWatch(navWatchId);
        navWatchId = null;
    }
    navOffRouteCount = 0;
    setNavMode('browse');
}

// ── 自動追従トグル ────────────────────────────────────────────────────────
function toggleNavFollow() {
    navIsAutoFollow = !navIsAutoFollow;
    _updateNavUI();
    _showNavBanner(
        navIsAutoFollow ? '📍 地図の自動追従をONにしました' : '🗺 地図の自動追従をOFFにしました',
        'info', 2500
    );
}

// ── ルート選択時に呼ばれる（routing.js から） ─────────────────────────────
function onNavRouteSelected(route, destination) {
    if (route) navActiveRoute = route;       // null の場合は上書きしない
    if (destination) navDestination = destination;
    if (navigationMode === 'browse') {
        setNavMode('route_preview');
    }
}

// ── 位置更新ハンドラ ──────────────────────────────────────────────────────
function _onNavPosition(position) {
    const { latitude: lat, longitude: lon, accuracy } = position.coords;

    // 微小移動は無視
    if (currentLocation) {
        const moved = _navHaversine(currentLocation.lat, currentLocation.lon, lat, lon);
        if (moved < NAV_MIN_DELTA_M) return;
    }

    // マーカー更新（軽量版：elevation/hazard API は呼ばない）
    _updateNavMarker(lat, lon, accuracy);

    // 自動追従
    if (navIsAutoFollow) {
        map.setView([lat, lon], map.getZoom());
    }

    // GPS 精度警告
    if (accuracy > NAV_LOW_ACCURACY_M) {
        _showNavBanner('⚠ 位置情報の精度が低下しています（±' + Math.round(accuracy) + 'm）', 'warning');
        return; // 精度が低い時は逸脱・到達判定しない
    }

    // 到達判定
    if (navDestination) {
        const arrDist = _navHaversine(lat, lon, navDestination.lat, navDestination.lon);
        if (arrDist <= NAV_ARRIVAL_M) {
            _onNavArrival();
            return;
        }
    }

    // 逸脱判定
    if (navActiveRoute) {
        const routeDist = _distanceToRoute(lat, lon);
        if (routeDist > NAV_OFF_ROUTE_M) {
            navOffRouteCount++;
            if (navOffRouteCount >= NAV_CONSECUTIVE && navigationMode === 'navigation_active') {
                setNavMode('navigation_warning');
                _showNavBanner('🔴 ルートから外れた可能性があります。再検索してください。', 'danger');
            }
        } else {
            if (navOffRouteCount > 0) {
                navOffRouteCount = 0;
                if (navigationMode === 'navigation_warning') {
                    setNavMode('navigation_active');
                    _showNavBanner('✅ ルートに戻りました', 'success', 3000);
                }
            }
        }
    }
}

function _onNavPositionError(err) {
    console.warn('[Nav] GPS error:', err.message);
    _showNavBanner('⚠ 位置情報の取得に失敗しました', 'warning');
}

// ── 軽量マーカー更新 ─────────────────────────────────────────────────────
function _updateNavMarker(lat, lon, accuracy) {
    currentLocation = { lat, lon, accuracyMeters: accuracy };

    // UI 座標表示を更新
    const el = id => document.getElementById(id);
    if (el('currentLat'))      el('currentLat').textContent      = lat.toFixed(6);
    if (el('currentLon'))      el('currentLon').textContent      = lon.toFixed(6);
    if (el('currentAccuracy')) el('currentAccuracy').textContent = '±' + Math.round(accuracy) + 'm';
    if (el('currentLocationInfo')) el('currentLocationInfo').style.display = 'block';

    // 既存マーカー削除
    if (currentMarker)        { map.removeLayer(currentMarker);        currentMarker        = null; }
    if (currentAccuracyCircle){ map.removeLayer(currentAccuracyCircle); currentAccuracyCircle = null; }

    // 新マーカー描画
    currentMarker = L.circleMarker([lat, lon], {
        radius: 10, fillColor: '#2196f3', color: '#fff',
        weight: 3, opacity: 1, fillOpacity: 0.9
    }).bindPopup('🧭 現在地（ナビ中）<br>精度: ±' + Math.round(accuracy) + 'm').addTo(map);

    if (accuracy) {
        currentAccuracyCircle = L.circle([lat, lon], {
            radius: accuracy, color: '#2196f3',
            fillColor: '#2196f3', fillOpacity: 0.1, weight: 1
        }).addTo(map);
    }
}

// ── 到達処理 ─────────────────────────────────────────────────────────────
function _onNavArrival() {
    stopNavigation();
    setNavMode('navigation_finished');
    _showNavBanner('🏁 避難先に到達しました！お疲れさまでした。', 'success');
}

// ── バナー表示 ────────────────────────────────────────────────────────────
let _bannerTimer = null;
function _showNavBanner(message, type, autoDismissMs) {
    const banner = document.getElementById('navBanner');
    if (!banner) return;
    banner.textContent = message;
    banner.className   = 'nav-banner nav-banner-' + type;
    banner.style.display = 'block';
    if (_bannerTimer) { clearTimeout(_bannerTimer); _bannerTimer = null; }
    if (autoDismissMs) {
        _bannerTimer = setTimeout(() => { banner.style.display = 'none'; }, autoDismissMs);
    }
}

// ── UI 更新 ───────────────────────────────────────────────────────────────
function _updateNavUI() {
    const el = id => document.getElementById(id);
    const mode = navigationMode;

    // ナビパネルの表示制御
    const navPanel = el('navPanel');
    if (navPanel) {
        navPanel.style.display = (mode === 'browse') ? 'none' : 'block';
    }

    // 各ボタンの表示制御
    const isActive = mode === 'navigation_active' || mode === 'navigation_warning' || mode === 'navigation_paused';
    if (el('navStartBtn'))      el('navStartBtn').style.display      = isActive ? 'none'  : 'block';
    if (el('navStopBtn'))       el('navStopBtn').style.display       = isActive ? 'block' : 'none';
    if (el('navStopFloating'))  el('navStopFloating').style.display  = isActive ? 'block' : 'none';
    if (el('navFollowBtn'))  el('navFollowBtn').style.display = isActive ? 'inline-block' : 'none';
    if (el('navRerouteBtn')) el('navRerouteBtn').style.display = (mode === 'navigation_warning') ? 'block' : 'none';

    // 追従ボタンの状態
    const followBtn = el('navFollowBtn');
    if (followBtn) {
        followBtn.textContent = navIsAutoFollow ? '📍 追従 ON' : '🗺 追従 OFF';
        followBtn.className   = 'btn btn-small ' + (navIsAutoFollow ? 'btn-follow-on' : 'btn-follow-off');
    }

    // ステータステキスト
    const statusMap = {
        'browse':               '',
        'route_preview':        'ルート確認中',
        'navigation_active':    '🧭 ナビ中',
        'navigation_warning':   '⚠ 警告あり',
        'navigation_paused':    '⏸ 一時停止中',
        'navigation_finished':  '🏁 到達完了',
    };
    if (el('navStatus')) el('navStatus').textContent = statusMap[mode] || '';

    // バナーをブラウズ時は隠す
    if (mode === 'browse') {
        const banner = el('navBanner');
        if (banner) banner.style.display = 'none';
    }
}

// ── 地図ドラッグで自動追従を一時解除 ─────────────────────────────────────
(function _setupMapDragListener() {
    // map は map.js で定義済み（同期読み込み）
    if (typeof map !== 'undefined') {
        map.on('dragstart', function () {
            if (navigationMode === 'navigation_active' || navigationMode === 'navigation_warning') {
                if (navIsAutoFollow) {
                    navIsAutoFollow = false;
                    _updateNavUI();
                }
            }
        });
    }
})();

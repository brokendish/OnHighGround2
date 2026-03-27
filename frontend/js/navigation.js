'use strict';

/**
 * navigation.js — ナビゲーションモード
 *
 * Phase 1: watchPosition による現在地継続取得・マーカー更新・地図追従
 * Phase 2: ルート逸脱判定・警告バナー
 * Phase 3: オフルート時の再ルート・避難先再検索
 */

// ── 定数 ──────────────────────────────────────────────────────────────────
const NAV_OFF_ROUTE_M      = 40;    // 逸脱判定しきい値（メートル）
const NAV_CONSECUTIVE      = 3;     // 連続 N 回外れたら warning
const NAV_ARRIVAL_M        = 20;    // 到達判定しきい値（メートル）
const NAV_MIN_DELTA_M      = 8;     // 移動量がこれ以下なら更新スキップ
const NAV_LOW_ACCURACY_M   = 50;    // GPS 精度がこれ以上なら精度警告
const NAV_REROUTE_COOLDOWN = 10000; // 再ルート連打防止（ms）

// ── オート再ルート定数 ─────────────────────────────────────────────────────
const NAV_AUTO_REROUTE_COOLDOWN_MS = 20000; // クールダウン（ms）
const NAV_AUTO_REROUTE_ACCURACY_M  = 30;    // 精度ガード（30m以内なら実行）
const NAV_AUTO_REROUTE_MAX_COUNT   = 3;     // ウィンドウ内最大回数
const NAV_AUTO_REROUTE_WINDOW_MS   = 120000;// 回数カウントウィンドウ（ms）

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
    navOffRouteCount              = 0;
    navIsAutoFollow               = true;
    navAutoRerouteInProgress      = false;
    navAutoRerouteSuspended       = false;
    navAutoRerouteCount           = 0;
    navAutoRerouteWindowStartedAt = 0;
    navLastAutoRerouteAt          = 0;
    // コンパス初期化（iOS はユーザー操作後でないと許可ダイアログが出ないためここで呼ぶ）
    if (typeof initOrientation === 'function') initOrientation();
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
    navOffRouteCount         = 0;
    navRerouteInProgress     = false;
    navAutoRerouteInProgress = false;
    if (typeof clearNavStepHighlight === 'function') clearNavStepHighlight();
    setNavMode('browse');
}

// ── 自動再ルート ON/OFF トグル ────────────────────────────────────────────
function toggleNavAutoReroute() {
    navAutoRerouteEnabled   = !navAutoRerouteEnabled;
    navAutoRerouteSuspended = false; // 一時停止も解除
    _updateNavUI();
    _showNavBanner(
        navAutoRerouteEnabled ? '🔄 自動再ルートをONにしました' : '⏸ 自動再ルートをOFFにしました',
        'info', 2500
    );
}

// ── ルート選択時に呼ばれる（routing.js から） ─────────────────────────────
function onNavRouteSelected(route, destination) {
    if (route) navActiveRoute = route;
    if (destination) {
        navDestination = destination;
        if (!navOriginalDestination) navOriginalDestination = destination;
    }
    if (navigationMode === 'browse' || navigationMode === 'navigation_finished') {
        setNavMode('route_preview');
    }
}

// ── Phase 3-A: 同じ避難先へ再ルート ─────────────────────────────────────
function rerouteToSameDestination() {
    if (navRerouteInProgress || navAutoRerouteInProgress) return;
    if (Date.now() - navLastRerouteAt < NAV_REROUTE_COOLDOWN) {
        _showNavBanner('⏳ 少し待ってから再試行してください', 'warning', 3000);
        return;
    }
    if (!navDestination) {
        _showNavBanner('❌ 目的地が設定されていません', 'danger', 3000);
        return;
    }

    navRerouteInProgress = true;
    navLastRerouteAt     = Date.now();
    _updateNavUI();
    _showNavBanner('🔄 現在地からルートを再計算しています...', 'info');

    // 古いルートレイヤーを消してから再描画
    if (typeof clearRouteCandidateLayers === 'function') clearRouteCandidateLayers();
    if (typeof clearSelectedRouteHighlight === 'function') clearSelectedRouteHighlight();

    drawRouteTo(navDestination.lat, navDestination.lon, {
        onRoutesAvailable: ({ routes, selectedRouteIndex, routeColors, formatter, transportMode, selectRouteIndex }) => {
            navActiveRoute       = routes[selectedRouteIndex];
            navOffRouteCount     = 0;
            navRerouteInProgress = false;
            // 地図上に新しいルートを描画
            if (typeof renderRouteCandidatesOnMap === 'function') {
                renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex);
            }
            // サイドバーの経路ステップを更新
            if (typeof activeNavigatingIndex !== 'undefined' && activeNavigatingIndex !== null) {
                // 避難先カードナビ
                if (typeof renderDestinationRouteGuidance === 'function') {
                    renderDestinationRouteGuidance(activeNavigatingIndex, routes, selectedRouteIndex, formatter, transportMode, selectRouteIndex, routeColors);
                }
            } else if (typeof userDestination !== 'undefined' && userDestination) {
                // 「ここへ行く」ナビ
                if (typeof renderUserDestRouteGuidance === 'function') {
                    renderUserDestRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, selectRouteIndex, routeColors);
                }
            } else {
                // 緊急避難場所ナビ
                if (typeof renderSelectedEmergencyShelterRouteGuidance === 'function') {
                    renderSelectedEmergencyShelterRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, selectRouteIndex, routeColors);
                }
            }
            // GPS 追跡が停止していた場合は再開、継続中ならモードだけ更新
            if (navWatchId === null) {
                startNavigation();
            } else {
                setNavMode('navigation_active');
            }
            _showNavBanner('✅ ルートを更新しました。このまま避難を続けてください。', 'success', 4000);
        },
        onRouteError: () => {
            navRerouteInProgress = false;
            _updateNavUI();
            _showNavBanner('⚠ 同じ避難先へのルートが見つかりません。別の避難先を再検索してください。', 'danger');
        }
    });
}

// ── Phase 3-B: 避難先を再検索 ───────────────────────────────────────────
function rerouteWithNewSearch() {
    stopNavigation();
    navOriginalDestination = null;
    if (typeof searchDestinations === 'function') {
        searchDestinations();
    }
}

// ── 位置更新ハンドラ ──────────────────────────────────────────────────────
function _onNavPosition(position) {
    const { latitude: lat, longitude: lon, accuracy, heading } = position.coords;

    // 微小移動は無視
    if (currentLocation) {
        const moved = _navHaversine(currentLocation.lat, currentLocation.lon, lat, lon);
        if (moved < NAV_MIN_DELTA_M) return;
    }

    _updateNavMarker(lat, lon, accuracy, heading);

    if (navIsAutoFollow) {
        map.setView([lat, lon], map.getZoom());
    }

    // 経路ステップハイライト更新（精度に関わらず実施）
    if (typeof updateNavStepHighlight === 'function') {
        updateNavStepHighlight(lat, lon);
    }

    // GPS 精度警告（逸脱・到達判定はスキップ）
    if (accuracy > NAV_LOW_ACCURACY_M) {
        _showNavBanner('⚠ 位置情報の精度が低下しています（±' + Math.round(accuracy) + 'm）', 'warning');
        return;
    }

    // 到達判定
    if (navDestination) {
        const arrDist = _navHaversine(lat, lon, navDestination.lat, navDestination.lon);
        if (arrDist <= NAV_ARRIVAL_M) {
            _onNavArrival();
            return;
        }
    }

    // 逸脱判定（再ルート処理中はスキップ）
    if (navActiveRoute && !navRerouteInProgress && !navAutoRerouteInProgress) {
        const routeDist = _distanceToRoute(lat, lon);
        if (routeDist > NAV_OFF_ROUTE_M) {
            navOffRouteCount++;
            if (navOffRouteCount >= NAV_CONSECUTIVE) {
                if (navigationMode === 'navigation_active') {
                    setNavMode('navigation_warning');
                    _showNavBanner('⚠ ルートから外れました。自動で見直しています...', 'danger');
                }
                // オート再ルート試行（warning 継続中も毎 GPS 更新で試みる）
                _tryAutoReroute(accuracy);
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

// ── Phase 4-A: オート再ルート判定 ────────────────────────────────────────
function _tryAutoReroute(accuracy) {
    if (!navAutoRerouteEnabled) return;
    if (navAutoRerouteSuspended) {
        console.log('[Nav] auto-reroute skipped: suspended');
        return;
    }
    if (navAutoRerouteInProgress || navRerouteInProgress) {
        console.log('[Nav] auto-reroute skipped: in progress');
        return;
    }

    const now = Date.now();

    // クールダウン
    if (now - navLastAutoRerouteAt < NAV_AUTO_REROUTE_COOLDOWN_MS) {
        console.log('[Nav] auto-reroute skipped: cooldown');
        return;
    }

    // 精度ガード
    if (accuracy > NAV_AUTO_REROUTE_ACCURACY_M) {
        console.log('[Nav] auto-reroute skipped: low accuracy', accuracy);
        _showNavBanner(`⚠ 位置精度が低いため自動再ルートを保留しています（±${Math.round(accuracy)}m）`, 'warning');
        return;
    }

    if (!navDestination) {
        console.log('[Nav] auto-reroute skipped: no destination');
        return;
    }

    // ウィンドウ内回数チェック
    if (navAutoRerouteWindowStartedAt === 0 || now - navAutoRerouteWindowStartedAt > NAV_AUTO_REROUTE_WINDOW_MS) {
        navAutoRerouteCount           = 0;
        navAutoRerouteWindowStartedAt = now;
    }
    if (navAutoRerouteCount >= NAV_AUTO_REROUTE_MAX_COUNT) {
        navAutoRerouteSuspended = true;
        console.warn('[Nav] auto-reroute suspended: too many retries');
        _showNavBanner('⚠ 自動再ルートを一時停止しました。手動で再ルートしてください。', 'danger');
        _updateNavUI();
        return;
    }

    _executeAutoReroute();
}

function _executeAutoReroute() {
    console.log('[Nav] auto-reroute started');
    navAutoRerouteInProgress = true;
    navAutoRerouteCount++;
    navLastAutoRerouteAt = Date.now();
    _updateNavUI();
    _showNavBanner('🔄 現在地からルートを自動で見直しています...', 'info');

    if (typeof clearRouteCandidateLayers === 'function') clearRouteCandidateLayers();
    if (typeof clearSelectedRouteHighlight === 'function') clearSelectedRouteHighlight();

    drawRouteTo(navDestination.lat, navDestination.lon, {
        onRoutesAvailable: ({ routes, selectedRouteIndex, routeColors, formatter, transportMode, selectRouteIndex }) => {
            navActiveRoute           = routes[selectedRouteIndex];
            navOffRouteCount         = 0;
            navAutoRerouteInProgress = false;

            if (typeof renderRouteCandidatesOnMap === 'function') {
                renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex);
            }
            // サイドバー経路ステップ更新
            if (typeof activeNavigatingIndex !== 'undefined' && activeNavigatingIndex !== null) {
                if (typeof renderDestinationRouteGuidance === 'function') {
                    renderDestinationRouteGuidance(activeNavigatingIndex, routes, selectedRouteIndex, formatter, transportMode, selectRouteIndex, routeColors);
                }
            } else if (typeof userDestination !== 'undefined' && userDestination) {
                if (typeof renderUserDestRouteGuidance === 'function') {
                    renderUserDestRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, selectRouteIndex, routeColors);
                }
            } else {
                if (typeof renderSelectedEmergencyShelterRouteGuidance === 'function') {
                    renderSelectedEmergencyShelterRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, selectRouteIndex, routeColors);
                }
            }

            setNavMode('navigation_active');
            _showNavBanner('✅ ルートを自動更新しました。このまま避難を続けてください。', 'success', 4000);
            console.log('[Nav] auto-reroute success');
        },
        onRouteError: () => {
            navAutoRerouteInProgress = false;
            _updateNavUI();
            console.warn('[Nav] auto-reroute failed');
            _showNavBanner('⚠ 自動再ルートに失敗しました。手動で再ルートしてください。', 'danger');
        }
    });
}

function _onNavPositionError(err) {
    console.warn('[Nav] GPS error:', err.message);
    _showNavBanner('⚠ 位置情報の取得に失敗しました', 'warning');
}

// ── 軽量マーカー更新 ─────────────────────────────────────────────────────
function _updateNavMarker(lat, lon, accuracy, heading) {
    currentLocation = { lat, lon, accuracyMeters: accuracy };

    const el = id => document.getElementById(id);
    if (el('currentLat'))      el('currentLat').textContent      = lat.toFixed(6);
    if (el('currentLon'))      el('currentLon').textContent      = lon.toFixed(6);
    if (el('currentAccuracy')) el('currentAccuracy').textContent = '±' + Math.round(accuracy) + 'm';
    if (el('currentLocationInfo')) el('currentLocationInfo').style.display = 'block';

    if (currentMarker)        { map.removeLayer(currentMarker);        currentMarker        = null; }
    if (currentAccuracyCircle){ map.removeLayer(currentAccuracyCircle); currentAccuracyCircle = null; }

    // 共通の矢印アイコン（map.js の _makeCurrentLocationIcon を使用）
    currentMarker = L.marker([lat, lon], { icon: _makeCurrentLocationIcon() })
        .bindPopup(`🧭 現在地（ナビ中）<br>精度: ±${Math.round(accuracy)}m`)
        .addTo(map);

    // GPS heading をコンパス未取得時のフォールバックとして使用
    const hasHeading = heading !== null && heading !== undefined && !isNaN(heading);
    if (hasHeading) {
        updateUserMarkerHeading(heading);
    } else if (_currentHeading !== null) {
        updateUserMarkerHeading(_currentHeading);
    }

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
    _showNavBanner('🏁 目的地に到達しました！お疲れさまでした。', 'success');
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

    const isActive = mode === 'navigation_active' || mode === 'navigation_warning' || mode === 'navigation_paused';
    const isWarning = mode === 'navigation_warning';

    // 手動位置選択モード中はナビ開始不可
    const canStartNav = !isManualLocationMode;

    // 下部オーバーレイ ナビ開始/停止ボタン（常時表示・disabled で活性制御）
    const navStartOverlay = el('nav-start-overlay-btn');
    const navStopOverlay  = el('nav-stop-overlay-btn');
    if (navStartOverlay) navStartOverlay.disabled = !(mode === 'route_preview' && canStartNav);
    if (navStopOverlay)  navStopOverlay.disabled  = !isActive;

    // カード内ボタン（動的注入）
    document.querySelectorAll('.nav-start-in-card').forEach(btn => {
        btn.style.display = (!isActive && canStartNav) ? 'block' : 'none';
    });
    document.querySelectorAll('.nav-stop-in-card').forEach(btn => {
        btn.style.display = isActive ? 'block' : 'none';
    });

    // 自動再ルートON/OFFボタン
    if (el('navFollowBtn')) {
        el('navFollowBtn').style.display = isActive ? 'inline-block' : 'none';
        el('navFollowBtn').textContent   = navAutoRerouteEnabled ? '🔄 自動再ルート ON' : '⏸ 自動再ルート OFF';
        el('navFollowBtn').className     = 'btn btn-small ' + (navAutoRerouteEnabled ? 'btn-follow-on' : 'btn-follow-off');
    }

    // 再ルートパネル（地図上）
    const reroutePanel = el('navReroutePanel');
    if (reroutePanel) {
        reroutePanel.style.display = isWarning ? 'block' : 'none';
    }

    // 現在の避難先名を表示
    const destNameEl = el('navRerouteDestName');
    if (destNameEl) {
        const name = navDestination && navDestination.name ? '避難先: ' + navDestination.name : '';
        destNameEl.textContent = name;
    }

    // オート再ルートステータスメッセージ
    const autoMsg = el('navAutoRerouteMsg');
    if (autoMsg) {
        if (navAutoRerouteInProgress) {
            autoMsg.textContent   = '🔄 現在地からルートを自動で見直しています...';
            autoMsg.style.display = 'block';
        } else if (navAutoRerouteSuspended) {
            autoMsg.textContent   = '⚠ 自動再ルートを一時停止しました';
            autoMsg.style.display = 'block';
        } else {
            autoMsg.style.display = 'none';
        }
    }

    // 再ルート中はボタンを無効化（両方・地図パネル）
    const anyRerouting = navRerouteInProgress || navAutoRerouteInProgress;
    const rerouteSameBtn = el('navRerouteSameBtn');
    if (rerouteSameBtn) {
        rerouteSameBtn.disabled    = anyRerouting;
        rerouteSameBtn.textContent = anyRerouting ? '🔄 再ルート中...' : '🔄 同じ避難先へ再ルート';
    }
    const rerouteNewBtn = el('navRerouteNewBtn');
    if (rerouteNewBtn) {
        rerouteNewBtn.disabled = anyRerouting;
    }

    // カード内再ルートボタン（逸脱時のみ表示）
    document.querySelectorAll('.nav-reroute-same-in-card').forEach(btn => {
        btn.style.display  = isWarning ? 'block' : 'none';
        btn.disabled       = anyRerouting;
        btn.textContent    = anyRerouting ? '🔄 再ルート中...' : '🔄 同じ避難先へ再ルート';
    });
    document.querySelectorAll('.nav-reroute-new-in-card').forEach(btn => {
        btn.style.display = isWarning ? 'block' : 'none';
        btn.disabled      = anyRerouting;
    });

    // 緊急避難場所カードのナビボタン
    // activeNavigatingIndex が null = 避難先候補ナビ非使用 → shelter がナビ対象
    const shelterIsTarget = (typeof activeNavigatingIndex === 'undefined' || activeNavigatingIndex === null);
    const shelterStartBtn = el('shelterNavStartBtn');
    if (shelterStartBtn) shelterStartBtn.style.display = (!isActive && mode !== 'browse' && shelterIsTarget && canStartNav) ? 'block' : 'none';
    const shelterStopBtn = el('shelterNavStopBtn');
    if (shelterStopBtn) shelterStopBtn.style.display = (isActive && shelterIsTarget) ? 'block' : 'none';
    const shelterRerouteSameBtn = el('shelterRerouteSameBtn');
    if (shelterRerouteSameBtn) {
        shelterRerouteSameBtn.style.display = (isWarning && shelterIsTarget) ? 'block' : 'none';
        shelterRerouteSameBtn.disabled     = anyRerouting;
        shelterRerouteSameBtn.textContent  = anyRerouting ? '🔄 再ルート中...' : '🔄 同じ避難先へ再ルート';
    }
    const shelterRerouteNewBtn = el('shelterRerouteNewBtn');
    if (shelterRerouteNewBtn) {
        shelterRerouteNewBtn.style.display = (isWarning && shelterIsTarget) ? 'block' : 'none';
        shelterRerouteNewBtn.disabled      = anyRerouting;
    }

    // ステータステキスト
    const statusMap = {
        'browse':              '',
        'route_preview':       'ルート確認中',
        'navigation_active':   '🧭 ナビ中',
        'navigation_warning':  '⚠ ルートから外れています',
        'navigation_paused':   '⏸ 一時停止中',
        'navigation_finished': '🏁 到達完了',
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

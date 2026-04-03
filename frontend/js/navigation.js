'use strict';

/**
 * navigation.js — ナビゲーションモード
 *
 * Phase 1: watchPosition による現在地継続取得・マーカー更新・地図追従
 * Phase 2: ルート逸脱判定・警告バナー
 * Phase 3: オフルート時の再ルート・避難先再検索
 */

// ── 定数 ──────────────────────────────────────────────────────────────────
const NAV_OFF_ROUTE_M      = 20;    // 逸脱表示しきい値（メートル）
const NAV_REROUTE_THRESHOLD_M  = 30; // 再ルートしきい値（メートル）
const NAV_MAX_GPS_ACCURACY_M   = 30; // これ以上の誤差なら逸脱判定を保留
const NAV_CONSECUTIVE      = 3;     // 連続 N 回外れたら warning
const NAV_ARRIVAL_M        = 10;    // 到達判定しきい値（メートル）
const NAV_MIN_DELTA_M      = 8;     // 移動量がこれ以下なら更新スキップ
const NAV_LOW_ACCURACY_M   = 50;    // GPS 精度がこれ以上なら精度警告
const NAV_REROUTE_COOLDOWN = 10000; // 再ルート連打防止（ms）

// ── オート再ルート定数 ─────────────────────────────────────────────────────
const NAV_AUTO_REROUTE_COOLDOWN_MS = 20000; // クールダウン（ms）
const NAV_AUTO_REROUTE_ACCURACY_M  = 30;    // 精度ガード（30m以内なら実行）
const NAV_AUTO_REROUTE_MAX_COUNT   = 3;     // ウィンドウ内最大回数
const NAV_AUTO_REROUTE_WINDOW_MS   = 120000;// 回数カウントウィンドウ（ms）

// ── 標高・表示更新定数（将来の設定画面から変更予定） ────────────────────────
const NAV_ELEV_UPDATE_M    = 10; // 標高再取得の移動距離しきい値（メートル）
const NAV_HAZARD_UPDATE_M  = 10; // ハザード再取得の移動距離しきい値（メートル）

// ── 前方ブロック再ルート定数 ──────────────────────────────────────────────
const BLOCK_AHEAD_START_METERS  = 30;   // ブロック開始距離（現在地前方 m）
const BLOCK_AHEAD_END_METERS    = 120;  // ブロック終了距離（現在地前方 m）
const BLOCK_BUFFER_METERS       = 25;   // バッファ幅（m）
const BLOCK_AHEAD_MAX_OFFSET_M  = 150;  // 現在地がルートからこれ以上離れていたら異常扱い（m）
const BLOCK_BYPASS_OFFSETS_M    = [75, 120]; // バイパス経由点の横方向オフセット距離候補（m）
const REJOIN_OFFSET_CANDIDATES_M = [20, 50, 90]; // ブロック終端の先で再合流を試す距離候補（m）
const BLOCK_OVERLAP_REJECT      = 0.7;  // ルート座標のブロックバッファ内占有率がこれ以上なら棄却
const BLOCK_TURN_PENALTY_M      = 60;   // 曲がり角 1 回あたりのペナルティ（m相当）
const BLOCK_SHARP_TURN_PENALTY_M = 120; // 急な折れ曲がり 1 回あたりの追加ペナルティ（m相当）
const MAX_REROUTE_EXTRA_DISTANCE_M = 250; // 元ルート残距離に対して許容する追加距離（m）
const MAX_REROUTE_DISTANCE_RATIO = 1.45;  // 元ルート残距離に対する許容倍率
const MAX_REJOIN_DEVIATION_M = 35;        // rejoin / blockStart / bypass への再スナップ許容距離（m）
const MAX_LOCAL_DETOUR_SPAN_M = 300;      // blockStart→rejoin の局所迂回区間として許容する最大長（m）
const MIN_FIRST_LEG_METERS = 10;          // 出だしが短すぎる枝道なら棄却
const MIN_FIRST_TURN_DISTANCE_M = 18;     // 最初の大きな曲がりまで最低限ほしい距離
const MAX_INITIAL_TURN_ANGLE_DEG = 120;   // 開始直後の急角度ターンは棄却
const MAX_INITIAL_STUB_RATIO = 3.2;       // 最初の角の前後の線分長バランスがこれを超えると不自然
const MAX_INITIAL_ZIGZAG_SCORE = 150;     // 開始直後の折れ曲がり総量
const INITIAL_QUALITY_WINDOW_M = 55;      // 初動品質を評価する距離窓
const SIGNIFICANT_INITIAL_TURN_DEG = 30;  // 「最初のターン」とみなす閾値
const MAX_INITIAL_DETOUR_FACTOR = 2.3;    // 初動窓内での経路長/実変位が大きすぎると枝分かれ的
const MAX_RETURN_NEAR_START_M = 12;       // 進行後に開始点近傍へ戻るような初動は棄却
const INITIAL_SELF_APPROACH_WINDOW_M = 220; // 初動〜局所迂回前半で自己再接近を見る距離窓
const MAX_INITIAL_SELF_APPROACH_M = 10;     // 先行区間へ戻りすぎたら枝分かれ的
const MIN_SELF_APPROACH_PATH_GAP_M = 25;    // 自己再接近判定に必要な経路上の離隔

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

// ── 標高取得（/elevation API） ────────────────────────────────────────────
async function _fetchElevation(lat, lon) {
    try {
        const res = await apiFetch(`/elevation?lat=${lat}&lon=${lon}`);
        if (!res.ok) return null;
        const data = await res.json();
        return typeof data.elevation === 'number' ? data.elevation : null;
    } catch {
        return null;
    }
}

// ── 現在地情報（ハザード+標高）を下部バーに表示 ──────────────────────────────
// browse モードの locate ボタン押下後や route_preview 移行時に呼ぶ。
function fetchCurrentLocInfo(lat, lon, elevation) {
    const rowHazard = document.getElementById('mbc-row-hazard');
    if (rowHazard) rowHazard.style.display = '';

    const elevEl = document.getElementById('mbc-current-elev');
    if (elevEl) {
        if (elevation != null) {
            elevEl.textContent = `${Number(elevation).toFixed(0)}m`;
        } else {
            elevEl.textContent = '—';
            _fetchElevation(lat, lon).then(elev => {
                if (elev !== null && elevEl) elevEl.textContent = `${elev.toFixed(0)}m`;
            });
        }
    }

    const hazardEl = document.getElementById('mbc-current-hazard');
    if (hazardEl) hazardEl.textContent = '確認中...';
    _checkCurrentHazard(lat, lon);
}

// ── 現在地ハザードチェック ──────────────────────────────────────────────────
async function _checkCurrentHazard(lat, lon) {
    try {
        const res = await apiFetch(`/hazard-check?lat=${lat}&lon=${lon}`);
        if (!res.ok) return;
        const data = await res.json();
        _updateHazardRow(data.is_danger, data.hazard_assessment);
    } catch {
        // ネットワークエラー等は無視
    }
}

function _updateHazardRow(isDanger, assessment) {
    const el = document.getElementById('mbc-current-hazard');
    if (!el) return;
    if (!isDanger) {
        el.innerHTML = '<span class="mbc-hazard-safe">✅ 安全</span>';
        return;
    }
    const dangerLabels = [];
    if (assessment && typeof assessment === 'object') {
        for (const [key, value] of Object.entries(assessment)) {
            const isInside = (typeof value === 'string' && value === 'inside') ||
                             (value && typeof value === 'object' && value.status === 'inside');
            if (isInside && typeof getHazardLabel === 'function') {
                dangerLabels.push(getHazardLabel(key));
            }
        }
    }
    const labelText = dangerLabels.length > 0 ? dangerLabels.join(' / ') : '危険区域内';
    el.innerHTML = `<span class="mbc-hazard-danger">⚠️ ${labelText}</span>`;
}

// ── 距離フォーマット（ナビ用） ────────────────────────────────────────────
function _fmtNavDist(meters) {
    if (!Number.isFinite(meters)) return '—';
    return meters < 1000
        ? `${Math.round(meters / 10) * 10}m`
        : `${(meters / 1000).toFixed(1)}km`;
}

// ── 線分への投影（緯度経度平面近似） ──────────────────────────────────────
// coords は {lat, lng} オブジェクト
function _navProjectOnSegment(p, a, b) {
    const dx = b.lng - a.lng, dy = b.lat - a.lat;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) return { point: a, t: 0 };
    const t = Math.max(0, Math.min(1,
        ((p.lng - a.lng) * dx + (p.lat - a.lat) * dy) / len2
    ));
    return { point: { lat: a.lat + t * dy, lng: a.lng + t * dx }, t };
}

// ── ルート上の最近点探索（線分ベース） ────────────────────────────────────
// 戻り値: { snappedPoint, segmentIndex, routeOffsetMeters } | null
function _navFindClosestOnRoute(coords, lat, lon) {
    if (!coords || coords.length < 2) return null;
    const p = { lat, lng: lon };
    let minDist = Infinity, best = null;
    for (let i = 0; i < coords.length - 1; i++) {
        const proj = _navProjectOnSegment(p, coords[i], coords[i + 1]);
        const d = _navHaversine(lat, lon, proj.point.lat, proj.point.lng);
        if (d < minDist) {
            minDist = d;
            best = { snappedPoint: proj.point, segmentIndex: i, routeOffsetMeters: d };
        }
    }
    return best;
}

// ── ルート沿い残距離（線分投影ベース） ────────────────────────────────────
// 戻り値: { remainingDistanceMeters, routeOffsetMeters } | null
function _remainingRouteDistance(lat, lon) {
    if (!navActiveRoute || !Array.isArray(navActiveRoute.coordinates)) return null;
    const coords = navActiveRoute.coordinates;
    if (coords.length < 2) return null;

    const closest = _navFindClosestOnRoute(coords, lat, lon);
    if (!closest) return null;

    // スナップ点 → 当該線分終点 + 以降の線分を積算
    let remaining = _navHaversine(
        closest.snappedPoint.lat, closest.snappedPoint.lng,
        coords[closest.segmentIndex + 1].lat, coords[closest.segmentIndex + 1].lng
    );
    for (let i = closest.segmentIndex + 1; i < coords.length - 1; i++) {
        remaining += _navHaversine(
            coords[i].lat, coords[i].lng,
            coords[i + 1].lat, coords[i + 1].lng
        );
    }
    return { remainingDistanceMeters: remaining, routeOffsetMeters: closest.routeOffsetMeters };
}

// ── 残距離・逸脱状態の UI 更新（共通） ────────────────────────────────────
function _updateRemainingDistanceDisplay(lat, lon, accuracy = 0) {
    const routeResult = _remainingRouteDistance(lat, lon);
    const remEl    = document.getElementById('mbc-remain-dist');
    const offsetEl = document.getElementById('mbc-offset-status');

    if (!remEl) return;

    if (routeResult === null) {
        remEl.textContent = '—';
        if (offsetEl) offsetEl.textContent = '';
        return;
    }

    remEl.textContent = _fmtNavDist(routeResult.remainingDistanceMeters);

    if (offsetEl) {
        if (accuracy > NAV_MAX_GPS_ACCURACY_M) {
            offsetEl.textContent = '';
        } else if (routeResult.routeOffsetMeters >= NAV_REROUTE_THRESHOLD_M) {
            offsetEl.textContent = '| 再ルートが必要です';
        } else if (routeResult.routeOffsetMeters >= NAV_OFF_ROUTE_M) {
            offsetEl.textContent = '| ルートから外れています';
        } else {
            offsetEl.textContent = '';
        }
    }

    return routeResult; // 逸脱判定で再利用できるよう返す
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
    // 開始地点の標高を取得
    navStartElevation     = null;
    navCurrentElevation   = null;
    navLastElevFetchPos   = null;
    navLastHazardFetchPos = null;
    const hazardEl = document.getElementById('mbc-current-hazard');
    if (hazardEl) hazardEl.textContent = '確認中...';
    if (currentLocation) {
        _fetchElevation(currentLocation.lat, currentLocation.lon).then(elev => {
            navStartElevation = elev;
        });
        _checkCurrentHazard(currentLocation.lat, currentLocation.lon);
        navLastHazardFetchPos = { lat: currentLocation.lat, lon: currentLocation.lon };
    }

    navWatchId = navigator.geolocation.watchPosition(
        _onNavPosition,
        _onNavPositionError,
        { enableHighAccuracy: true, maximumAge: 3000, timeout: 10000 }
    );
    setNavMode('navigation_active');

    // watchPosition の初回更新を待たず、開始直後に残距離を即表示する
    if (currentLocation) {
        _updateRemainingDistanceDisplay(
            currentLocation.lat,
            currentLocation.lon,
            currentLocation.accuracyMeters ?? 0
        );
    }

    _showNavBanner('🧭 ナビを開始しました。現在地を追跡中です。', 'info', 3000);
    if (typeof voiceNav !== 'undefined') {
        voiceNav.announce({ id: 'nav-start', text: '案内を開始します', category: 'start', priority: 'high' });
    }
    // ナビ開始時に情報タブを表示（ルート案内が見えるよう）
    if (typeof switchMbcTab === 'function') switchMbcTab('info');
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
    navBlockAheadInProgress  = false;
    ++_blockAheadSeq; // pending callback を無効化（非同期完了後の復帰を防ぐ）
    navStartElevation        = null;
    navCurrentElevation      = null;
    navLastElevFetchPos      = null;
    navLastHazardFetchPos    = null;
    _clearBlockAheadLayer();
    if (typeof clearNavStepHighlight === 'function') clearNavStepHighlight();
    setNavMode('browse');
    // 処理中バナー（再計算中・再ルート中など）が残らないよう停止時に非表示化
    const banner = document.getElementById('navBanner');
    if (banner) banner.style.display = 'none';
    if (typeof voiceNav !== 'undefined') voiceNav.clear();

    // 停止直後に現在地のハザード情報・標高を再取得して表示
    if (currentLocation) {
        fetchCurrentLocInfo(currentLocation.lat, currentLocation.lon, currentLocation.elevation ?? null);
    }
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
        setNavMode('route_preview'); // 内部で _updateNavUI() を呼ぶ
        // route_preview 移行時に現在地ハザード+標高を下部バーに表示
        if (typeof currentLocation !== 'undefined' && currentLocation) {
            fetchCurrentLocInfo(currentLocation.lat, currentLocation.lon, currentLocation.elevation);
        }
    } else {
        _updateNavUI(); // route_preview / ナビ中に再ルートされた場合も残距離を更新
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
                renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
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

    // 接近通知: 次の曲がり角まで 40m 以内で予告（voiceNav があれば）
    if (typeof voiceNav !== 'undefined' && navigationMode === 'navigation_active') {
        const stepEl = document.querySelector('li.nav-step-current[data-step-lat]');
        if (stepEl) {
            const sLat   = parseFloat(stepEl.dataset.stepLat);
            const sLon   = parseFloat(stepEl.dataset.stepLon);
            const stepId = stepEl.dataset.stepLat + ',' + stepEl.dataset.stepLon;
            const distToStep = _navHaversine(lat, lon, sLat, sLon);
            if (distToStep <= 40) {
                const rawText = stepEl.textContent.split('（')[0].trim();
                voiceNav.announceApproach(rawText, stepId);
            }
        }
    }

    // 残距離・逸脱ステータス更新（共通関数）
    const routeResult = _updateRemainingDistanceDisplay(lat, lon, accuracy);
    const offsetEl    = document.getElementById('mbc-offset-status');

    // 現在標高更新（NAV_ELEV_UPDATE_M 以上移動した場合のみAPIを叩く）
    if (!navLastElevFetchPos ||
        _navHaversine(navLastElevFetchPos.lat, navLastElevFetchPos.lon, lat, lon) >= NAV_ELEV_UPDATE_M) {
        navLastElevFetchPos = { lat, lon };
        _fetchElevation(lat, lon).then(elev => {
            if (elev === null) return;
            navCurrentElevation = elev;
            const el = document.getElementById('mbc-current-elev');
            if (el) el.textContent = `${elev.toFixed(0)}m`;
        });
    }

    // 現在地ハザード更新（NAV_HAZARD_UPDATE_M 以上移動した場合のみAPIを叩く）
    if (!navLastHazardFetchPos ||
        _navHaversine(navLastHazardFetchPos.lat, navLastHazardFetchPos.lon, lat, lon) >= NAV_HAZARD_UPDATE_M) {
        navLastHazardFetchPos = { lat, lon };
        _checkCurrentHazard(lat, lon);
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

    // 逸脱判定（再ルート処理中・GPS精度不良はスキップ）
    if (navActiveRoute && !navRerouteInProgress && !navAutoRerouteInProgress
            && routeResult !== null && accuracy <= NAV_MAX_GPS_ACCURACY_M) {
        const offsetM = routeResult.routeOffsetMeters;
        if (offsetM >= NAV_OFF_ROUTE_M) {
            navOffRouteCount++;
            if (navOffRouteCount >= NAV_CONSECUTIVE) {
                if (navigationMode === 'navigation_active') {
                    setNavMode('navigation_warning');
                    _showNavBanner('⚠ ルートから外れました。自動で見直しています...', 'danger');
                    if (typeof voiceNav !== 'undefined') {
                        voiceNav.announce({ id: 'nav-off-route', text: 'ルートから外れています', category: 'warning', priority: 'high' });
                    }
                }
                // 再ルートしきい値を超えている場合のみオート再ルートを試みる
                if (offsetM >= NAV_REROUTE_THRESHOLD_M) {
                    _tryAutoReroute(accuracy);
                }
            }
        } else {
            if (navOffRouteCount > 0) {
                navOffRouteCount = 0;
                if (offsetEl) offsetEl.textContent = '';
                if (navigationMode === 'navigation_warning') {
                    setNavMode('navigation_active');
                    _showNavBanner('✅ ルートに戻りました', 'success', 3000);
                    if (typeof voiceNav !== 'undefined') {
                        voiceNav.announce({ id: 'nav-back-on-route', text: 'ルートに戻りました', category: 'start', priority: 'normal' });
                    }
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
                renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
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

// ── 前方ブロック再ルート ──────────────────────────────────────────────────

// ルート上の投影点から distM メートル先の座標を返す
// projection: _navFindClosestOnRoute の戻り値
function _walkAlongRoute(coords, projection, distM) {
    let remaining = distM;
    let curLat = projection.snappedPoint.lat;
    let curLng = projection.snappedPoint.lng;
    for (let i = projection.segmentIndex + 1; i < coords.length; i++) {
        const nextLat = coords[i].lat;
        const nextLng = coords[i].lng;
        const segDist = _navHaversine(curLat, curLng, nextLat, nextLng);
        if (segDist >= remaining) {
            const t = remaining / segDist;
            return {
                lat: curLat + t * (nextLat - curLat),
                lng: curLng + t * (nextLng - curLng)
            };
        }
        remaining -= segDist;
        curLat = nextLat;
        curLng = nextLng;
    }
    return { lat: curLat, lng: curLng }; // ルート末端に達した場合
}

// p1→p2 の中点を起点に、進行方向の垂直方向へ offsetMeters ずらした座標を返す
// side: +1 = 左側, -1 = 右側。メートル空間で計算して度単位に変換する。
function _perpendicularOffsetPoint(p1, p2, offsetMeters, side = 1) {
    const midLat = (p1.lat + p2.lat) / 2;
    const midLng = (p1.lng + p2.lng) / 2;
    const cosLat = Math.cos(midLat * Math.PI / 180);
    // 方向ベクトルをメートル空間に変換
    const dY = (p2.lat - p1.lat) * 111111;           // 北方向成分（m）
    const dX = (p2.lng - p1.lng) * 111111 * cosLat;  // 東方向成分（m）
    const len = Math.sqrt(dX * dX + dY * dY);
    if (len < 0.1) {
        // 縮退セグメント：side 方向（北 or 南）にオフセット
        return { lat: midLat + side * offsetMeters / 111111, lng: midLng };
    }
    // 左側 90° 回転：perpNorth = dX/len, perpEast = -dY/len。右側は符号反転。
    const perpNorth = side * dX / len;
    const perpEast  = side * (-dY / len);
    return {
        lat: midLat + perpNorth * offsetMeters / 111111,
        lng: midLng + perpEast  * offsetMeters / (111111 * cosLat)
    };
}

// 経路座標の中でブロックバッファ（円）内に入っている点の割合を返す
function _calcBlockOverlapRatio(coords, centerLat, centerLng, radiusM) {
    if (!coords || coords.length === 0) return 0;
    let inside = 0;
    for (const c of coords) {
        if (_navHaversine(c.lat, c.lng ?? c.lon, centerLat, centerLng) <= radiusM) inside++;
    }
    return inside / coords.length;
}

// バイパス候補の評価用に OSRM へ直接ルートクエリを投げる（LRM を使わず評価専用）
// waypoints: [{lat, lng}|{lat, lon}] の配列
async function _fetchOsrmRouteForEval(waypoints) {
    const transportMode = document.getElementById('transportMode')?.value ?? 'walking';
    const profile       = transportMode === 'walking' ? 'walking' : 'driving';
    const serviceUrl    = OSRM_SERVICE_URLS[profile];
    const coordStr      = waypoints.map(wp => `${wp.lng ?? wp.lon},${wp.lat}`).join(';');
    const url           = `${serviceUrl}/${profile}/${coordStr}?overview=full&geometries=geojson&alternatives=false&steps=true`;
    try {
        const res = await fetch(url);
        if (!res.ok) return null;
        const data = await res.json();
        if (data.code !== 'Ok' || !data.routes?.length) return null;
        const r = data.routes[0];
        const coordinates = r.geometry.coordinates.map(c => ({ lat: c[1], lng: c[0] }));
        const steps = Array.isArray(r.legs)
            ? r.legs.flatMap(leg => Array.isArray(leg.steps) ? leg.steps : [])
            : [];
        const turnSteps = steps.filter(step => {
            const type = step?.maneuver?.type;
            return type && type !== 'depart' && type !== 'arrive';
        });
        const sharpTurnSteps = turnSteps.filter(step => {
            const modifier = step?.maneuver?.modifier || '';
            return modifier === 'sharp left'
                || modifier === 'sharp right'
                || modifier === 'uturn';
        });
        return {
            coordinates,
            totalDistance: r.distance,
            turnCount: turnSteps.length,
            sharpTurnCount: sharpTurnSteps.length
        };
    } catch (e) {
        console.warn('[BlockAhead][eval] fetch error:', e);
        return null;
    }
}

function _routePolylineLength(coords) {
    if (!Array.isArray(coords) || coords.length < 2) return 0;
    let total = 0;
    for (let i = 0; i < coords.length - 1; i++) {
        total += _navHaversine(
            coords[i].lat, coords[i].lng ?? coords[i].lon,
            coords[i + 1].lat, coords[i + 1].lng ?? coords[i + 1].lon
        );
    }
    return total;
}

function _routeSpanBetweenPoints(coords, fromPoint, toPoint) {
    if (!Array.isArray(coords) || coords.length < 2 || !fromPoint || !toPoint) return Infinity;
    const fromProj = _navFindClosestOnRoute(coords, fromPoint.lat, fromPoint.lng ?? fromPoint.lon);
    const toProj   = _navFindClosestOnRoute(coords, toPoint.lat, toPoint.lng ?? toPoint.lon);
    if (!fromProj || !toProj) return Infinity;

    if (toProj.segmentIndex < fromProj.segmentIndex) return Infinity;
    if (toProj.segmentIndex === fromProj.segmentIndex) {
        return _navHaversine(
            fromProj.snappedPoint.lat, fromProj.snappedPoint.lng,
            toProj.snappedPoint.lat, toProj.snappedPoint.lng
        );
    }

    let total = _navHaversine(
        fromProj.snappedPoint.lat, fromProj.snappedPoint.lng,
        coords[fromProj.segmentIndex + 1].lat, coords[fromProj.segmentIndex + 1].lng
    );
    for (let i = fromProj.segmentIndex + 1; i < toProj.segmentIndex; i++) {
        total += _navHaversine(
            coords[i].lat, coords[i].lng,
            coords[i + 1].lat, coords[i + 1].lng
        );
    }
    total += _navHaversine(
        coords[toProj.segmentIndex].lat, coords[toProj.segmentIndex].lng,
        toProj.snappedPoint.lat, toProj.snappedPoint.lng
    );
    return total;
}

function _segmentLengthMeters(a, b) {
    if (!a || !b) return 0;
    return _navHaversine(a.lat, a.lng ?? a.lon, b.lat, b.lng ?? b.lon);
}

function _turnAngleDeg(a, b, c) {
    if (!a || !b || !c) return 0;
    const v1x = (b.lng ?? b.lon) - (a.lng ?? a.lon);
    const v1y = b.lat - a.lat;
    const v2x = (c.lng ?? c.lon) - (b.lng ?? b.lon);
    const v2y = c.lat - b.lat;
    const len1 = Math.hypot(v1x, v1y);
    const len2 = Math.hypot(v2x, v2y);
    if (len1 < 1e-9 || len2 < 1e-9) return 0;
    const dot = (v1x * v2x) + (v1y * v2y);
    const cos = Math.max(-1, Math.min(1, dot / (len1 * len2)));
    return Math.acos(cos) * 180 / Math.PI;
}

function _analyzeInitialMovement(routeLike) {
    const coords = Array.isArray(routeLike?.coordinates) ? routeLike.coordinates : [];
    if (coords.length < 2) {
        return {
            firstLegMeters: 0,
            distanceToFirstTurnMeters: Infinity,
            firstTurnAngleDeg: 0,
            initialStubRatio: 0,
            initialZigzagScore: 0,
            initialDetourFactor: 1,
            returnNearStartMeters: Infinity,
            selfApproachDistanceM: Infinity
        };
    }

    const firstLegMeters = _segmentLengthMeters(coords[0], coords[1]);
    let distanceToFirstTurnMeters = Infinity;
    let firstTurnAngleDeg = 0;
    let secondLegMeters = 0;
    let initialZigzagScore = 0;
    let walkedBeforeVertex = 0;
    let windowPathLength = 0;
    let windowEndPoint = coords[0];
    let returnNearStartMeters = Infinity;
    const sampledPoints = [{ point: coords[0], pathDistance: 0 }];
    const analysisWindowM = Math.max(INITIAL_QUALITY_WINDOW_M, INITIAL_SELF_APPROACH_WINDOW_M);

    for (let i = 1; i < coords.length - 1; i++) {
        const incomingLen = _segmentLengthMeters(coords[i - 1], coords[i]);
        const outgoingLen = _segmentLengthMeters(coords[i], coords[i + 1]);
        const turnAngle = _turnAngleDeg(coords[i - 1], coords[i], coords[i + 1]);
        const vertexDistance = walkedBeforeVertex + incomingLen;
        windowPathLength = vertexDistance;
        windowEndPoint = coords[i];

        if (vertexDistance <= INITIAL_QUALITY_WINDOW_M && turnAngle >= SIGNIFICANT_INITIAL_TURN_DEG) {
            initialZigzagScore += turnAngle;
        }
        if (vertexDistance >= MIN_FIRST_TURN_DISTANCE_M) {
            const distToStart = _segmentLengthMeters(coords[0], coords[i]);
            if (distToStart < returnNearStartMeters) {
                returnNearStartMeters = distToStart;
            }
        }
        if (distanceToFirstTurnMeters === Infinity && turnAngle >= SIGNIFICANT_INITIAL_TURN_DEG) {
            distanceToFirstTurnMeters = vertexDistance;
            firstTurnAngleDeg = turnAngle;
            secondLegMeters = outgoingLen;
        }

        walkedBeforeVertex += incomingLen;
        if (vertexDistance <= INITIAL_SELF_APPROACH_WINDOW_M) {
            sampledPoints.push({ point: coords[i], pathDistance: vertexDistance });
        }
        if (walkedBeforeVertex > analysisWindowM) break;
    }

    if (coords.length >= 2 && walkedBeforeVertex <= INITIAL_QUALITY_WINDOW_M) {
        const lastLen = _segmentLengthMeters(coords[coords.length - 2], coords[coords.length - 1]);
        windowPathLength = Math.min(INITIAL_QUALITY_WINDOW_M, walkedBeforeVertex + lastLen);
        windowEndPoint = coords[Math.min(coords.length - 1, 1)];
    }

    let progressed = 0;
    for (let i = 1; i < coords.length; i++) {
        const segLen = _segmentLengthMeters(coords[i - 1], coords[i]);
        if (progressed + segLen >= INITIAL_QUALITY_WINDOW_M) {
            const remain = Math.max(0, INITIAL_QUALITY_WINDOW_M - progressed);
            if (segLen > 0) {
                const t = remain / segLen;
                windowEndPoint = {
                    lat: coords[i - 1].lat + (coords[i].lat - coords[i - 1].lat) * t,
                    lng: (coords[i - 1].lng ?? coords[i - 1].lon) + ((coords[i].lng ?? coords[i].lon) - (coords[i - 1].lng ?? coords[i - 1].lon)) * t
                };
                windowPathLength = INITIAL_QUALITY_WINDOW_M;
            }
            break;
        }
        progressed += segLen;
        windowPathLength = progressed;
        windowEndPoint = coords[i];
    }

    const initialStubRatio = (firstTurnAngleDeg > 0 && firstLegMeters > 0 && secondLegMeters > 0)
        ? Math.max(firstLegMeters, secondLegMeters) / Math.max(1, Math.min(firstLegMeters, secondLegMeters))
        : 1;
    const initialWindowDisplacement = _segmentLengthMeters(coords[0], windowEndPoint);
    const initialDetourFactor = initialWindowDisplacement > 1
        ? windowPathLength / initialWindowDisplacement
        : Infinity;
    let selfApproachDistanceM = Infinity;
    for (let i = 0; i < sampledPoints.length; i++) {
        for (let j = i + 1; j < sampledPoints.length; j++) {
            const pathGap = sampledPoints[j].pathDistance - sampledPoints[i].pathDistance;
            if (pathGap < MIN_SELF_APPROACH_PATH_GAP_M) continue;
            const spatialGap = _segmentLengthMeters(sampledPoints[i].point, sampledPoints[j].point);
            if (spatialGap < selfApproachDistanceM) {
                selfApproachDistanceM = spatialGap;
            }
        }
    }

    return {
        firstLegMeters,
        distanceToFirstTurnMeters,
        firstTurnAngleDeg,
        initialStubRatio,
        initialZigzagScore,
        initialDetourFactor,
        returnNearStartMeters,
        selfApproachDistanceM
    };
}

function _assessBlockAheadRoute(routeLike, context) {
    const coords = Array.isArray(routeLike?.coordinates) ? routeLike.coordinates : [];
    if (coords.length < 2) {
        return { valid: false, reasons: ['no-coordinates'] };
    }

    const totalDistance = Number.isFinite(Number(routeLike?.summary?.totalDistance))
        ? Number(routeLike.summary.totalDistance)
        : (Number.isFinite(Number(routeLike?.totalDistance))
            ? Number(routeLike.totalDistance)
            : _routePolylineLength(coords));
    const overlap = _calcBlockOverlapRatio(coords, context.bufMid.lat, context.bufMid.lng, context.overlapRadius);
    const extraDistance = Math.max(0, totalDistance - context.baseRemainingDistance);
    const distanceRatio = context.baseRemainingDistance > 0
        ? totalDistance / context.baseRemainingDistance
        : 1;
    const localDetourSpan = _routeSpanBetweenPoints(coords, context.blockStart, context.rejoin);
    const blockStartDeviation = _navFindClosestOnRoute(coords, context.blockStart.lat, context.blockStart.lng)?.routeOffsetMeters ?? Infinity;
    const bypassDeviation = _navFindClosestOnRoute(coords, context.bypass.lat, context.bypass.lng)?.routeOffsetMeters ?? Infinity;
    const rejoinDeviation = _navFindClosestOnRoute(coords, context.rejoin.lat, context.rejoin.lng)?.routeOffsetMeters ?? Infinity;
    const initialMovement = _analyzeInitialMovement(routeLike);

    const reasons = [];
    if (overlap > BLOCK_OVERLAP_REJECT) reasons.push(`overlap=${overlap.toFixed(2)}`);
    if (extraDistance > MAX_REROUTE_EXTRA_DISTANCE_M) reasons.push(`extra=${Math.round(extraDistance)}m`);
    if (distanceRatio > MAX_REROUTE_DISTANCE_RATIO) reasons.push(`ratio=${distanceRatio.toFixed(2)}`);
    if (localDetourSpan > MAX_LOCAL_DETOUR_SPAN_M) reasons.push(`local-span=${Math.round(localDetourSpan)}m`);
    if (blockStartDeviation > MAX_REJOIN_DEVIATION_M) reasons.push(`block-start-dev=${Math.round(blockStartDeviation)}m`);
    if (bypassDeviation > MAX_REJOIN_DEVIATION_M) reasons.push(`bypass-dev=${Math.round(bypassDeviation)}m`);
    if (rejoinDeviation > MAX_REJOIN_DEVIATION_M) reasons.push(`rejoin-dev=${Math.round(rejoinDeviation)}m`);
    if (initialMovement.firstLegMeters < MIN_FIRST_LEG_METERS) reasons.push(`first-leg=${Math.round(initialMovement.firstLegMeters)}m`);
    if (Number.isFinite(initialMovement.distanceToFirstTurnMeters)
            && initialMovement.distanceToFirstTurnMeters < MIN_FIRST_TURN_DISTANCE_M
            && initialMovement.firstTurnAngleDeg >= SIGNIFICANT_INITIAL_TURN_DEG) {
        reasons.push(`first-turn-dist=${Math.round(initialMovement.distanceToFirstTurnMeters)}m`);
    }
    if (Number.isFinite(initialMovement.distanceToFirstTurnMeters)
            && initialMovement.distanceToFirstTurnMeters <= INITIAL_QUALITY_WINDOW_M
            && initialMovement.firstTurnAngleDeg > MAX_INITIAL_TURN_ANGLE_DEG) {
        reasons.push(`first-turn-angle=${Math.round(initialMovement.firstTurnAngleDeg)}deg`);
    }
    if (Number.isFinite(initialMovement.distanceToFirstTurnMeters)
            && initialMovement.distanceToFirstTurnMeters <= INITIAL_QUALITY_WINDOW_M
            && initialMovement.initialStubRatio > MAX_INITIAL_STUB_RATIO) {
        reasons.push(`stub-ratio=${initialMovement.initialStubRatio.toFixed(2)}`);
    }
    if (initialMovement.initialZigzagScore > MAX_INITIAL_ZIGZAG_SCORE) {
        reasons.push(`zigzag=${Math.round(initialMovement.initialZigzagScore)}`);
    }
    if (Number.isFinite(initialMovement.initialDetourFactor)
            && initialMovement.initialDetourFactor > MAX_INITIAL_DETOUR_FACTOR) {
        reasons.push(`detour-factor=${initialMovement.initialDetourFactor.toFixed(2)}`);
    }
    if (Number.isFinite(initialMovement.returnNearStartMeters)
            && initialMovement.returnNearStartMeters < MAX_RETURN_NEAR_START_M) {
        reasons.push(`return-start=${Math.round(initialMovement.returnNearStartMeters)}m`);
    }
    if (Number.isFinite(initialMovement.selfApproachDistanceM)
            && initialMovement.selfApproachDistanceM < MAX_INITIAL_SELF_APPROACH_M) {
        reasons.push(`self-approach=${Math.round(initialMovement.selfApproachDistanceM)}m`);
    }

    return {
        valid: reasons.length === 0,
        reasons,
        totalDistance,
        overlap,
        extraDistance,
        distanceRatio,
        localDetourSpan,
        blockStartDeviation,
        bypassDeviation,
        rejoinDeviation,
        firstLegMeters: initialMovement.firstLegMeters,
        distanceToFirstTurnMeters: initialMovement.distanceToFirstTurnMeters,
        firstTurnAngleDeg: initialMovement.firstTurnAngleDeg,
        initialStubRatio: initialMovement.initialStubRatio,
        initialZigzagScore: initialMovement.initialZigzagScore,
        initialDetourFactor: initialMovement.initialDetourFactor,
        returnNearStartMeters: initialMovement.returnNearStartMeters,
        selfApproachDistanceM: initialMovement.selfApproachDistanceM
    };
}

function _restoreBlockAheadOriginalRoute(originalRoute) {
    if (!originalRoute || !Array.isArray(originalRoute.coordinates) || originalRoute.coordinates.length < 2) return;
    if (typeof clearRouteCandidateLayers === 'function') clearRouteCandidateLayers();
    if (typeof clearSelectedRouteHighlight === 'function') clearSelectedRouteHighlight();
    const restored = L.polyline(
        originalRoute.coordinates.map(c => [c.lat, c.lng]),
        { color: ROUTE_COLOR_PALETTE[0], weight: 7, opacity: 0.95 }
    ).addTo(map);
    routeCandidateLayers.push(restored);
    if (currentLocation) {
        _updateRemainingDistanceDisplay(
            currentLocation.lat,
            currentLocation.lon,
            currentLocation.accuracyMeters ?? 0
        );
    }
}

function _selectSingleRouteBundle(routes, selectedRouteIndex, routeColors, formatter, transportMode) {
    const routeList = Array.isArray(routes) ? routes : [];
    if (routeList.length === 0) {
        return {
            routes: [],
            selectedRouteIndex: 0,
            routeColors: [],
            formatter,
            transportMode,
            selectRouteIndex: () => {}
        };
    }
    const safeIndex = Math.max(0, Math.min(Number(selectedRouteIndex) || 0, routeList.length - 1));
    const selectedRoute = routeList[safeIndex];
    const selectedColor = Array.isArray(routeColors) && routeColors.length > 0
        ? (routeColors[safeIndex] || routeColors[0] || getRouteColorByIndex(0))
        : getRouteColorByIndex(0);
    return {
        routes: [selectedRoute],
        selectedRouteIndex: 0,
        routeColors: [selectedColor],
        formatter,
        transportMode,
        selectRouteIndex: () => {}
    };
}

// Leaflet レイヤー（前方ブロック可視化）のモジュール内状態
let _blockAheadLayer = null;
// キャンセルトークン: stopNavigation 呼び出しと routesfound/routeselected 二重発火を両方防ぐ
let _blockAheadSeq = 0;

function _clearBlockAheadLayer() {
    if (_blockAheadLayer && typeof map !== 'undefined') {
        map.removeLayer(_blockAheadLayer);
    }
    _blockAheadLayer = null;
}

// 「この先を避けて再ルート」— メイン関数（マルチ候補評価版）
async function blockAheadAndReroute() {
    // ── ガード ────────────────────────────────────────────────────────────
    if (!navActiveRoute || !Array.isArray(navActiveRoute.coordinates)) {
        console.warn('[BlockAhead] no active route');
        return;
    }
    if (!navDestination) {
        console.warn('[BlockAhead] no destination');
        return;
    }
    if (!currentLocation) {
        console.warn('[BlockAhead] no current location');
        return;
    }
    if (navBlockAheadInProgress) {
        console.log('[BlockAhead] already in progress');
        return;
    }

    navBlockAheadInProgress = true;
    const mySeq = ++_blockAheadSeq; // このリクエストのトークン
    _updateNavUI();
    _showNavBanner('🚧 前方ルートを回避してルートを再計算しています...', 'info');
    console.log('[BlockAhead] start seq=' + mySeq);

    const coords = navActiveRoute.coordinates;
    const originalRouteSnapshot = JSON.parse(JSON.stringify(navActiveRoute));
    const baseRemaining = _remainingRouteDistance(currentLocation.lat, currentLocation.lon);
    const baseRemainingDistance = baseRemaining?.remainingDistanceMeters
        ?? Number(navActiveRoute?.summary?.totalDistance)
        ?? _routePolylineLength(coords);

    // ── 現在地をルート上に投影 ─────────────────────────────────────────────
    const projection = _navFindClosestOnRoute(coords, currentLocation.lat, currentLocation.lon);
    if (!projection) {
        console.warn('[BlockAhead] projection failed');
        navBlockAheadInProgress = false;
        _updateNavUI();
        _showNavBanner('⚠ 現在地をルート上に特定できませんでした', 'danger', 4000);
        return;
    }
    if (projection.routeOffsetMeters > BLOCK_AHEAD_MAX_OFFSET_M) {
        console.warn('[BlockAhead] too far off route:', projection.routeOffsetMeters, 'm');
        navBlockAheadInProgress = false;
        _updateNavUI();
        _showNavBanner(
            `⚠ 現在地がルートから離れすぎています（${Math.round(projection.routeOffsetMeters)}m）。先に再ルートしてください。`,
            'danger', 5000
        );
        return;
    }

    // ── 前方 30m〜120m のセグメントを抽出 ───────────────────────────────
    const blockStart = _walkAlongRoute(coords, projection, BLOCK_AHEAD_START_METERS);
    const blockEnd   = _walkAlongRoute(coords, projection, BLOCK_AHEAD_END_METERS);
    console.log('[BlockAhead] blocked segment:', blockStart, '->', blockEnd);

    // ── 補助線は表示しない。既存の一時描画が残っていればクリアだけ行う ─────
    _clearBlockAheadLayer();
    const bufMid = {
        lat: (blockStart.lat + blockEnd.lat) / 2,
        lng: (blockStart.lng + blockEnd.lng) / 2
    };
    const overlapRadius = BLOCK_BUFFER_METERS + 15;

    // ── バイパス候補生成（左右 × オフセット × 再合流候補） ──────────────────
    const candidateDefs = [];
    for (const side of [1, -1]) {
        for (const offsetM of BLOCK_BYPASS_OFFSETS_M) {
            const bypass = _perpendicularOffsetPoint(blockStart, blockEnd, offsetM, side);
            for (const rejoinOffsetM of REJOIN_OFFSET_CANDIDATES_M) {
                const rejoin = _walkAlongRoute(coords, projection, BLOCK_AHEAD_END_METERS + rejoinOffsetM);
                candidateDefs.push({
                    bypass,
                    rejoin,
                    offsetM,
                    rejoinOffsetM,
                    side: side === 1 ? 'left' : 'right'
                });
            }
        }
    }
    console.log('[BlockAhead] candidates:', candidateDefs.map(c => `${c.side}/${c.offsetM}m/rejoin+${c.rejoinOffsetM}`));

    // ── 各候補を OSRM で並行評価（escape → bypass → rejoin の 3 点中継） ──
    // currentLocation と navDestination を lat/lng 形式に統一
    const startWp = { lat: currentLocation.lat, lng: currentLocation.lon };
    const destWp  = { lat: navDestination.lat,  lng: navDestination.lon  };

    const evalResults = await Promise.all(candidateDefs.map(async (c) => {
        const waypoints = [startWp, blockStart, c.bypass, c.rejoin, destWp];
        const route = await _fetchOsrmRouteForEval(waypoints);
        const assessment = route
            ? _assessBlockAheadRoute(route, {
                baseRemainingDistance,
                bufMid,
                overlapRadius,
                blockStart,
                bypass: c.bypass,
                rejoin: c.rejoin
            })
            : null;
        return { ...c, route, assessment };
    }));

    // ── ログ出力 ─────────────────────────────────────────────────────────
    evalResults.forEach(r => {
        console.log(`[BlockAhead][eval] ${r.side}/${r.offsetM}m/rejoin+${r.rejoinOffsetM}:`,
            r.route
                ? `dist=${Math.round(r.route.totalDistance)}m pts=${r.route.coordinates.length}`
                : 'fetch failed'
        );
    });

    // ── 評価・棄却・スコアリング ──────────────────────────────────────────
    const scored = evalResults
        .filter(r => r.route !== null)
        .map(r => {
            const turnCount = Number(r.route.turnCount) || 0;
            const sharpTurnCount = Number(r.route.sharpTurnCount) || 0;
            const score = r.route.totalDistance
                + (turnCount * BLOCK_TURN_PENALTY_M)
                + (sharpTurnCount * BLOCK_SHARP_TURN_PENALTY_M)
                + (Math.max(0, r.assessment?.extraDistance || 0) * 2)
                + (Math.max(0, (r.assessment?.localDetourSpan || 0) - 120) * 2)
                + (Math.max(0, MIN_FIRST_TURN_DISTANCE_M - (r.assessment?.distanceToFirstTurnMeters ?? Infinity)) * 8)
                + (Math.max(0, (r.assessment?.firstTurnAngleDeg || 0) - 75) * 3)
                + ((r.assessment?.initialZigzagScore || 0) * 1.2);
            console.log(
                `[BlockAhead][score] ${r.side}/${r.offsetM}m/rejoin+${r.rejoinOffsetM}: overlap=${(r.assessment?.overlap ?? 0).toFixed(2)} dist=${Math.round(r.route.totalDistance)}m turns=${turnCount} sharp=${sharpTurnCount} extra=${Math.round(r.assessment?.extraDistance ?? 0)}m span=${Math.round(r.assessment?.localDetourSpan ?? 0)}m firstLeg=${Math.round(r.assessment?.firstLegMeters ?? 0)}m firstTurn=${Number.isFinite(r.assessment?.distanceToFirstTurnMeters) ? Math.round(r.assessment.distanceToFirstTurnMeters) : 'none'}m angle=${Math.round(r.assessment?.firstTurnAngleDeg ?? 0)} zigzag=${Math.round(r.assessment?.initialZigzagScore ?? 0)} detour=${Number.isFinite(r.assessment?.initialDetourFactor) ? r.assessment.initialDetourFactor.toFixed(2) : 'inf'} return=${Number.isFinite(r.assessment?.returnNearStartMeters) ? Math.round(r.assessment.returnNearStartMeters) : 'inf'}m self=${Number.isFinite(r.assessment?.selfApproachDistanceM) ? Math.round(r.assessment.selfApproachDistanceM) : 'inf'}m score=${Math.round(score)}${r.assessment?.valid ? '' : ` reject=${(r.assessment?.reasons || []).join(',')}`}`
            );
            return { ...r, score, turnCount, sharpTurnCount };
        })
        .filter(r => r.assessment && r.assessment.valid)
        .sort((a, b) => a.score - b.score);

    if (scored.length === 0) {
        console.warn('[BlockAhead] all candidates rejected (eval invalid or fetch failure)');
        navBlockAheadInProgress = false;
        _clearBlockAheadLayer();
        _updateNavUI();
        _showNavBanner('⚠ 局所的な迂回ルートが見つかりませんでした。現在のルートを継続します。', 'danger', 5000);
        return;
    }
    const tryCandidate = (candidate) => new Promise((resolve) => {
        let settled = false;
        const finish = (result) => {
            if (settled) return;
            settled = true;
            resolve(result);
        };
        const routed = drawRouteTo(navDestination.lat, navDestination.lon, {
            extraWaypoints: [blockStart, candidate.bypass, candidate.rejoin],
            onRoutesAvailable: ({ routes, selectedRouteIndex, routeColors, formatter, transportMode, selectRouteIndex }) => {
                if (_blockAheadSeq !== mySeq) {
                    console.log('[BlockAhead] stale callback ignored (seq mismatch)');
                    finish({ status: 'stale' });
                    return;
                }
                const selectedRoute = routes?.[selectedRouteIndex];
                const finalAssessment = _assessBlockAheadRoute(selectedRoute, {
                    baseRemainingDistance,
                    bufMid,
                    overlapRadius,
                    blockStart,
                    bypass: candidate.bypass,
                    rejoin: candidate.rejoin
                });
                console.log(
                    `[BlockAhead][final] ${candidate.side}/${candidate.offsetM}m/rejoin+${candidate.rejoinOffsetM}: valid=${finalAssessment.valid} overlap=${(finalAssessment.overlap ?? 0).toFixed(2)} extra=${Math.round(finalAssessment.extraDistance ?? 0)}m span=${Math.round(finalAssessment.localDetourSpan ?? 0)}m firstLeg=${Math.round(finalAssessment.firstLegMeters ?? 0)}m firstTurn=${Number.isFinite(finalAssessment.distanceToFirstTurnMeters) ? Math.round(finalAssessment.distanceToFirstTurnMeters) : 'none'}m angle=${Math.round(finalAssessment.firstTurnAngleDeg ?? 0)} zigzag=${Math.round(finalAssessment.initialZigzagScore ?? 0)} detour=${Number.isFinite(finalAssessment.initialDetourFactor) ? finalAssessment.initialDetourFactor.toFixed(2) : 'inf'} return=${Number.isFinite(finalAssessment.returnNearStartMeters) ? Math.round(finalAssessment.returnNearStartMeters) : 'inf'}m self=${Number.isFinite(finalAssessment.selfApproachDistanceM) ? Math.round(finalAssessment.selfApproachDistanceM) : 'inf'}m reasons=${finalAssessment.reasons.join(',') || 'ok'}`
                );
                if (!finalAssessment.valid) {
                    finish({ status: 'invalid-final', finalAssessment });
                    return;
                }
                ++_blockAheadSeq;
                finish({
                    status: 'success',
                    finalAssessment,
                    routes,
                    selectedRouteIndex,
                    routeColors,
                    formatter,
                    transportMode,
                    selectRouteIndex
                });
            },
            onRouteError: () => {
                console.warn(`[BlockAhead] reroute failed (LRM error) ${candidate.side}/${candidate.offsetM}m/rejoin+${candidate.rejoinOffsetM}`);
                finish({ status: 'route-error' });
            }
        });
        if (!routed) finish({ status: 'route-error' });
    });

    let accepted = null;
    for (const candidate of scored) {
        if (_blockAheadSeq !== mySeq) {
            navBlockAheadInProgress = false;
            _clearBlockAheadLayer();
            _updateNavUI();
            return;
        }
        console.log(
            `[BlockAhead] trying: ${candidate.side}/${candidate.offsetM}m/rejoin+${candidate.rejoinOffsetM} dist=${Math.round(candidate.route.totalDistance)}m score=${Math.round(candidate.score)}`
        );
        const result = await tryCandidate(candidate);
        if (result.status === 'success') {
            accepted = { candidate, result };
            break;
        }
        if (result.status === 'stale') {
            navBlockAheadInProgress = false;
            _clearBlockAheadLayer();
            _updateNavUI();
            return;
        }
        console.warn(
            `[BlockAhead] rejected final route: ${candidate.side}/${candidate.offsetM}m/rejoin+${candidate.rejoinOffsetM} (${result.finalAssessment?.reasons?.join(',') || result.status})`
        );
    }

    if (!accepted) {
        navBlockAheadInProgress = false;
        _restoreBlockAheadOriginalRoute(originalRouteSnapshot);
        _clearBlockAheadLayer();
        _updateNavUI();
        _showNavBanner('⚠ 局所的な迂回ルートが見つかりませんでした。現在のルートを継続します。', 'danger', 5000);
        return;
    }

    const { candidate, result } = accepted;
    const selectedBundle = _selectSingleRouteBundle(
        result.routes,
        result.selectedRouteIndex,
        result.routeColors,
        result.formatter,
        result.transportMode
    );
    console.log(
        `[BlockAhead] best: ${candidate.side}/${candidate.offsetM}m/rejoin+${candidate.rejoinOffsetM} dist=${Math.round(candidate.route.totalDistance)}m overlap=${candidate.assessment.overlap.toFixed(2)} turns=${candidate.turnCount} sharp=${candidate.sharpTurnCount} score=${Math.round(candidate.score)}`
    );

    navActiveRoute          = selectedBundle.routes[0];
    navOffRouteCount        = 0;
    navBlockAheadInProgress = false;

    if (typeof renderRouteCandidatesOnMap === 'function') {
        renderRouteCandidatesOnMap(selectedBundle.routes, selectedBundle.routeColors, 0, selectedBundle.selectRouteIndex);
    }

    if (typeof clearNavStepHighlight === 'function') clearNavStepHighlight();
    if (typeof voiceNav !== 'undefined') voiceNav.clear();

    if (typeof activeNavigatingIndex !== 'undefined' && activeNavigatingIndex !== null) {
        if (typeof renderDestinationRouteGuidance === 'function') {
            renderDestinationRouteGuidance(activeNavigatingIndex, selectedBundle.routes, 0, selectedBundle.formatter, selectedBundle.transportMode, selectedBundle.selectRouteIndex, selectedBundle.routeColors);
        }
    } else if (typeof userDestination !== 'undefined' && userDestination) {
        if (typeof renderUserDestRouteGuidance === 'function') {
            renderUserDestRouteGuidance(selectedBundle.routes, 0, selectedBundle.formatter, selectedBundle.transportMode, selectedBundle.selectRouteIndex, selectedBundle.routeColors);
        }
    } else {
        if (typeof renderSelectedEmergencyShelterRouteGuidance === 'function') {
            renderSelectedEmergencyShelterRouteGuidance(selectedBundle.routes, 0, selectedBundle.formatter, selectedBundle.transportMode, selectedBundle.selectRouteIndex, selectedBundle.routeColors);
        }
    }

    setNavMode('navigation_active');
    if (currentLocation) {
        _updateRemainingDistanceDisplay(
            currentLocation.lat,
            currentLocation.lon,
            currentLocation.accuracyMeters ?? 0
        );
    }
    _showNavBanner('✅ 迂回ルートに切り替えました。このまま避難を続けてください。', 'success', 5000);
    if (typeof voiceNav !== 'undefined') {
        voiceNav.announce({
            id: 'block-ahead-reroute',
            text: '前方を迂回するルートに切り替えました',
            category: 'start',
            priority: 'high'
        });
    }
    console.log('[BlockAhead] reroute success seq=' + mySeq);
    _clearBlockAheadLayer();
}

// ── 到達処理 ─────────────────────────────────────────────────────────────
function _onNavArrival() {
    stopNavigation();
    setNavMode('navigation_finished');
    _showNavBanner('🏁 目的地に到達しました！お疲れさまでした。', 'success');
    if (typeof voiceNav !== 'undefined') {
        voiceNav.announce({ id: 'nav-arrival', text: '目的地に到着しました', category: 'arrival', priority: 'high' });
    }
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

    // 下部オーバーレイ ボタン行・スライダーの表示切り替え
    // browse:          現在地/検索行＋スライダー表示、ナビ行非表示
    // route_preview:   現在地/検索行＋スライダー＋ナビ行すべて表示（停止は非活性）
    // ナビ中:          ナビ行のみ表示、現在地/検索行＋スライダー非表示
    const rowNormal  = el('mbc-row-normal');
    const rowNav     = el('mbc-row-nav');
    const rowSliders = el('mbc-row-sliders');
    const showNavRow    = isActive || mode === 'route_preview';
    const showNormalRow = !isActive;
    if (rowNormal)  rowNormal.style.display  = showNormalRow ? '' : 'none';
    if (rowNav)     rowNav.style.display     = showNavRow    ? '' : 'none';
    if (rowSliders) rowSliders.style.display = (mode === 'browse') ? '' : 'none';

    // 残距離行: ルート確認中・ナビ中に表示
    const rowDist   = el('mbc-row-dist');
    const rowHazard = el('mbc-row-hazard');
    if (rowDist) rowDist.style.display = showNavRow ? '' : 'none';
    if (!showNavRow) {
        const rd = el('mbc-remain-dist');
        if (rd) rd.textContent = '—';
        const os = el('mbc-offset-status');
        if (os) os.textContent = '';
    }

    // ハザード+現在標高行: route_preview とナビ中に表示、navigation_finished は非表示
    // browse モードは locate ボタンが表示を制御するため変更しない
    if (rowHazard) {
        if (isActive || mode === 'route_preview') {
            rowHazard.style.display = '';
        } else if (mode === 'navigation_finished') {
            rowHazard.style.display = 'none';
        }
    }

    // ナビ開始: route_preview のみ表示 / ナビ停止: ナビ中のみ表示
    const navStartOverlay = el('nav-start-overlay-btn');
    const navStopOverlay  = el('nav-stop-overlay-btn');
    if (navStartOverlay) {
        navStartOverlay.style.display = (mode === 'route_preview') ? '' : 'none';
        navStartOverlay.disabled = !canStartNav;
    }
    if (navStopOverlay) {
        navStopOverlay.style.display = isActive ? '' : 'none';
        navStopOverlay.disabled = !isActive;
    }

    // カード内ボタン（動的注入）
    document.querySelectorAll('.nav-start-in-card').forEach(btn => {
        btn.style.display = (!isActive && canStartNav) ? 'block' : 'none';
    });
    document.querySelectorAll('.nav-stop-in-card').forEach(btn => {
        btn.style.display = isActive ? 'block' : 'none';
    });

    // 再ルート処理中フラグ（前方回避も含む） — 以降の全ボタン制御で参照するため先に宣言
    const anyRerouting = navRerouteInProgress || navAutoRerouteInProgress || navBlockAheadInProgress;

    // 前方回避ボタン（navigation_active / navigation_warning のみ表示）
    const blockAheadBtn    = el('nav-block-ahead-btn');
    const blockAheadTextEl = el('nav-block-ahead-btn-text');
    if (blockAheadBtn) {
        blockAheadBtn.style.display = (mode === 'navigation_active' || mode === 'navigation_warning') ? '' : 'none';
        blockAheadBtn.disabled = anyRerouting;
    }
    if (blockAheadTextEl) {
        blockAheadTextEl.textContent = navBlockAheadInProgress ? '回避中...' : 'この先を避けて再ルート';
    }

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

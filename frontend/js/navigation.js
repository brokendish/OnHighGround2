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
const BLOCK_AHEAD_START_METERS  = 20;   // ブロック開始距離（現在地前方 m）
const BLOCK_AHEAD_END_METERS    = 180;  // ブロック終了距離（現在地前方 m）
const BLOCK_BUFFER_METERS       = 50;   // 前方コリドーの基本バッファ幅（m）
const BLOCK_AHEAD_MAX_OFFSET_M  = 150;  // 現在地がルートからこれ以上離れていたら異常扱い（m）
const BLOCK_OVERLAP_REJECT      = 0.7;  // ルート座標のブロックバッファ内占有率がこれ以上なら棄却
const BLOCK_NEAR_REJECT_METERS  = 10;   // ブロック領域からこの距離以内も棄却
const BLOCK_SAMPLE_STEP_METERS  = 20;   // 前方コリドー中心線サンプル間隔
const BLOCK_INTERSECTION_TURN_DEG = 25; // 交差点候補とみなす進路変化角
const BLOCK_INTERSECTION_BUFFER_METERS = 40; // 交差点付近の追加ブロック半径
const BLOCK_MAIN_SLIT_RADIUS_RATIO = 0.46; // 前方スリット本体は細く保つ
const BLOCK_CORE_RADIUS_RATIO = 0.62;      // start/end 付近のコアは少し太め
const BLOCK_INTERSECTION_RADIUS_RATIO = 0.58; // 交差点入口は飲み込みすぎないよう抑える
const BLOCK_MIN_SLIT_RADIUS_M = 18;
const BLOCK_MIN_CORE_RADIUS_M = 22;
const BLOCK_OSRM_ALTERNATIVES = 3; // OSRM alternatives は 3 までに固定（4/5 は 400 を返す環境がある）
const BLOCK_BRANCH_MIN_BEARING_DIFF_DEG = 20;
const BLOCK_BRANCH_MIN_LATERAL_DIVERGENCE_M = 16;
const BLOCK_BRANCH_NEAR_PENALTY_STRICT_MAX = 0.22;
const BLOCK_BRANCH_NEAR_PENALTY_OVERLAP_EPS = 0.01;
const BLOCK_STAGE_CONFIGS = [
    {
        key: 'stage1',
        startM: 20,
        endM: 180,
        backwardM: 0,
        baseRadiusM: 50,
        intersectionBufferM: 40,
        alternativeCount: BLOCK_OSRM_ALTERNATIVES
    },
    {
        key: 'stage2',
        startM: 10,
        endM: 240,
        backwardM: 60,
        baseRadiusM: 65,
        intersectionBufferM: 50,
        alternativeCount: BLOCK_OSRM_ALTERNATIVES
    },
    {
        key: 'stage3',
        startM: 0,
        endM: 320,
        backwardM: 120,
        baseRadiusM: 80,
        intersectionBufferM: 60,
        alternativeCount: BLOCK_OSRM_ALTERNATIVES
    }
];
const BLOCK_ESCAPE_LATERAL_OFFSETS_M = [60, 100];
const BLOCK_ESCAPE_BACKWARD_M = 25;
const BLOCK_ESCAPE_MAX_POINTS = 6;
const BLOCK_ESCAPE_MAX_LATERAL_M = 200;
const BLOCK_ESCAPE_PUSH_STEP_M = 20;
const BLOCK_ESCAPE_IGNORE_METERS = 40;
const BLOCK_ESCAPE_LEG_LATERAL_OFFSETS_M = [30, 60, 90, 120];
const BLOCK_ESCAPE_LEG_BACKWARD_M = 15;
const BLOCK_ESCAPE_LEG_MAX_POINTS = 6;
const BLOCK_ESCAPE_CORRIDOR_DIFF_M = 18;
const BLOCK_ESCAPE_SIDE_BEARING_DEG = 35;
const BLOCK_ESCAPE_DEEPER_STEPS_M = [30, 60, 90, 120];
const BLOCK_ESCAPE_GATE_LENGTH_M = 60;
const BLOCK_ESCAPE_GATE_WIDTH_M = 16;
const BLOCK_ESCAPE_GATE_STEPS_M = [15, 30, 45, 60];
const BLOCK_ESCAPE_LEG_PREFIX_GATE_M = 55;
const BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX = 0.35;
const BLOCK_ESCAPE_NEAR_PENALTY_OVERLAP_EPS = 0.08;
const PEDESTRIAN_SAFETY_OVERPASS_URL = 'https://overpass-api.de/api/interpreter';
const PEDESTRIAN_SAFETY_BBOX_PADDING_M = 45;
const PEDESTRIAN_SAFETY_CROSSWALK_RADIUS_M = 25;
const PEDESTRIAN_SAFETY_FETCH_TIMEOUT_MS = 800;
const PEDESTRIAN_SAFETY_MAJOR_HIGHWAYS = new Set(['trunk', 'trunk_link', 'primary', 'primary_link']);
const PEDESTRIAN_SAFETY_FORBIDDEN_HIGHWAYS = new Set(['motorway', 'motorway_link']);
const PEDESTRIAN_SAFETY_MIN_CROSSING_BEARING_DEG = 35;
const PEDESTRIAN_SAFETY_CACHE_TTL_MS = 5 * 60 * 1000;
const SIGNIFICANT_INITIAL_TURN_DEG = 30;  // 「最初のターン」とみなす閾値
const MIN_INITIAL_CLARITY_SEGMENT_M = 18;   // これ未満の初動折れは表示上まとめる
const MAX_INITIAL_CLARITY_WINDOW_M = 40;    // 初動簡略化を適用する最大距離窓
const DISPLAY_SIMPLIFY_MIN_SEGMENT_M = 2;   // 表示用に重複同然の点を間引く閾値
const DISPLAY_SIMPLIFY_SHORT_SEGMENT_M = 28; // 枝に見えやすい短いセグメント閾値
const DISPLAY_SIMPLIFY_SHARP_TURN_DEG = 100; // 短いセグメント同士で潰す鋭角ターン
const DISPLAY_SIMPLIFY_UTURN_DEG = 155;      // out-and-back とみなす折り返し角度
const DISPLAY_SIMPLIFY_PROGRESS_RATIO = 0.55; // 2辺に対して直線距離が短すぎる屈曲を潰す
const DISPLAY_SIMPLIFY_RETURN_GAP_M = 12;     // 戻り先が近すぎる spur を潰す
const DISPLAY_SIMPLIFY_MAX_PASSES = 6;        // 安全のための最大反復回数
const DISPLAY_REVISIT_DISTANCE_M = 14;        // 以前通った地点への再接近を同一点扱いする閾値
const DISPLAY_LOOP_PATH_MIN_M = 24;           // ループ切り落とし対象の最小経路長
const DISPLAY_LOOP_DESTINATION_SLACK_M = 10;  // ループ終端が目的地から多少遠くても許容する余裕
const DISPLAY_ANCHOR_MERGE_RADIUS_M = 12;     // 同じ交差点とみなすアンカー統合半径
const DISPLAY_DUPLICATE_SEGMENT_DISTANCE_M = 14; // 近接重複セグメントとみなす距離
const DISPLAY_DUPLICATE_SEGMENT_ANGLE_DEG = 20;  // 同方向セグメントとみなす角度差
const DISPLAY_DUPLICATE_SEGMENT_MIN_PATH_M = 20; // 重複除去対象にする最小経路長
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

function _perfNowMs() {
    if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
        return performance.now();
    }
    return Date.now();
}

let _blockAheadPerfMetrics = null;
let _blockAheadLastTiming = null;
let _blockAheadRecentSummaries = [];
let _blockAheadAggregateMetrics = {
    totalRuns: 0,
    acceptedRuns: 0,
    failedRuns: 0,
    noChangeRuns: 0,
    statusCounts: {},
    rejectReasonCounts: {},
    avgTotalMs: 0,
    avgOsrmMs: 0,
    avgDisplayPipelineMs: 0
};

function _recordBlockAheadTiming(bucket, durationMs, extra = {}) {
    if (!_blockAheadPerfMetrics) return;
    if (!_blockAheadPerfMetrics[bucket]) {
        _blockAheadPerfMetrics[bucket] = { totalMs: 0, count: 0 };
    }
    _blockAheadPerfMetrics[bucket].totalMs += durationMs;
    _blockAheadPerfMetrics[bucket].count += 1;
    Object.assign(_blockAheadPerfMetrics[bucket], extra);
}

function _incrementReasonCounter(target, reason) {
    if (!target || !reason) return;
    target[reason] = (target[reason] || 0) + 1;
}

function _recordBlockAheadRejectReason(reason) {
    if (!_blockAheadPerfMetrics || !reason) return;
    if (!_blockAheadPerfMetrics.rejectReasons) {
        _blockAheadPerfMetrics.rejectReasons = {};
    }
    _incrementReasonCounter(_blockAheadPerfMetrics.rejectReasons, reason);
}

function _updateRollingAverage(prevAvg, prevCount, nextValue) {
    const value = Number(nextValue) || 0;
    return ((prevAvg * prevCount) + value) / Math.max(1, prevCount + 1);
}

function _recordBlockAheadExecutionSummary(summary) {
    if (!summary) return;
    _blockAheadRecentSummaries.push(summary);
    if (_blockAheadRecentSummaries.length > 20) {
        _blockAheadRecentSummaries = _blockAheadRecentSummaries.slice(-20);
    }

    const agg = _blockAheadAggregateMetrics;
    const prevCount = agg.totalRuns;
    agg.totalRuns += 1;
    if (summary.accepted) agg.acceptedRuns += 1;
    else agg.failedRuns += 1;
    if (summary.status === 'no-change') agg.noChangeRuns += 1;
    if (summary.status) {
        agg.statusCounts[summary.status] = (agg.statusCounts[summary.status] || 0) + 1;
    }
    [summary.rejectReason].filter(Boolean).forEach(reason => {
        _incrementReasonCounter(agg.rejectReasonCounts, reason);
    });
    agg.avgTotalMs = _updateRollingAverage(agg.avgTotalMs, prevCount, summary.totalMs);
    agg.avgOsrmMs = _updateRollingAverage(agg.avgOsrmMs, prevCount, summary.osrmMs);
    agg.avgDisplayPipelineMs = _updateRollingAverage(agg.avgDisplayPipelineMs, prevCount, summary.displayPipelineMs);

    if (typeof window !== 'undefined') {
        window._blockAheadRecentSummaries = _blockAheadRecentSummaries;
        window._blockAheadAggregateMetrics = _blockAheadAggregateMetrics;
    }
}

function _routeCoordsCacheKey(coords) {
    if (!Array.isArray(coords) || coords.length === 0) return '';
    return coords.map(point => `${Number(point.lat).toFixed(5)},${Number(point.lng ?? point.lon).toFixed(5)}`).join('|');
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

function _walkAlongRouteBackward(coords, projection, distM) {
    let remaining = distM;
    let curLat = projection.snappedPoint.lat;
    let curLng = projection.snappedPoint.lng;
    for (let i = projection.segmentIndex; i >= 0; i--) {
        const prevLat = coords[i].lat;
        const prevLng = coords[i].lng;
        const segDist = _navHaversine(curLat, curLng, prevLat, prevLng);
        if (segDist >= remaining) {
            const t = remaining / segDist;
            return {
                lat: curLat + t * (prevLat - curLat),
                lng: curLng + t * (prevLng - curLng)
            };
        }
        remaining -= segDist;
        curLat = prevLat;
        curLng = prevLng;
    }
    return { lat: curLat, lng: curLng };
}

function _walkAlongRouteRelative(coords, projection, offsetM) {
    return offsetM >= 0
        ? _walkAlongRoute(coords, projection, offsetM)
        : _walkAlongRouteBackward(coords, projection, Math.abs(offsetM));
}

function _headingUnitVectorMeters(fromPoint, toPoint) {
    if (!fromPoint || !toPoint) return null;
    const avgLatRad = (((fromPoint.lat || 0) + (toPoint.lat || 0)) / 2) * Math.PI / 180;
    const eastM = ((toPoint.lng ?? toPoint.lon) - (fromPoint.lng ?? fromPoint.lon)) * 111111 * Math.cos(avgLatRad);
    const northM = (toPoint.lat - fromPoint.lat) * 111111;
    const length = Math.hypot(eastM, northM);
    if (length < 1e-6) return null;
    return { east: eastM / length, north: northM / length };
}

function _offsetPointByMeters(origin, eastM, northM) {
    const lat = Number(origin?.lat);
    const lng = Number(origin?.lng ?? origin?.lon);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return null;
    const latOffset = northM / 111111;
    const lngOffset = eastM / (111111 * Math.max(0.2, Math.cos(lat * Math.PI / 180)));
    return { lat: lat + latOffset, lng: lng + lngOffset };
}

function _buildEscapePoint(origin, headingUnit, side, lateralM, backwardM = 0) {
    if (!origin || !headingUnit) return null;
    const headingEast = headingUnit.east;
    const headingNorth = headingUnit.north;
    const leftEast = -headingNorth;
    const leftNorth = headingEast;
    const signedLateral = side === 'left' ? lateralM : -lateralM;
    const eastM = (leftEast * signedLateral) - (headingEast * backwardM);
    const northM = (leftNorth * signedLateral) - (headingNorth * backwardM);
    return _offsetPointByMeters(origin, eastM, northM);
}

function _pushEscapePointOutsideBlockedArea(origin, headingUnit, side, lateralM, blockedArea, backwardM = 0) {
    const nearRejectMeters = blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS;
    let currentLateralM = lateralM;
    let point = _buildEscapePoint(origin, headingUnit, side, currentLateralM, backwardM);
    while (point && currentLateralM < BLOCK_ESCAPE_MAX_LATERAL_M
            && _distancePointToBlockedArea(point, blockedArea, nearRejectMeters) <= 0) {
        currentLateralM += BLOCK_ESCAPE_PUSH_STEP_M;
        point = _buildEscapePoint(origin, headingUnit, side, currentLateralM, backwardM);
    }
    if (!point) return null;
    if (_distancePointToBlockedArea(point, blockedArea, nearRejectMeters) <= 0) {
        return null;
    }
    return { point, lateralM: currentLateralM };
}

function _buildEscapeGateBlockedArea(coords, projection, blockedArea, logPrefix = 'escape-gate') {
    if (!blockedArea || !projection?.snappedPoint || !Array.isArray(coords) || coords.length < 2) return blockedArea;
    const headingTarget = _walkAlongRoute(coords, projection, 20);
    const headingUnit = _headingUnitVectorMeters(projection.snappedPoint, headingTarget);
    if (!headingUnit) return blockedArea;
    const gateCenters = [];
    for (const side of ['left', 'right']) {
        for (const lateralM of BLOCK_ESCAPE_GATE_STEPS_M) {
            const point = _buildEscapePoint(projection.snappedPoint, headingUnit, side, lateralM, 0);
            if (point) {
                gateCenters.push({
                    lat: point.lat,
                    lng: point.lng,
                    radius: BLOCK_ESCAPE_GATE_WIDTH_M,
                    side,
                    kind: 'escape-gate'
                });
            }
        }
    }
    const gatedArea = {
        ...blockedArea,
        escapeGates: gateCenters,
        escapeGateLengthM: BLOCK_ESCAPE_GATE_LENGTH_M,
        escapeGateWidthM: BLOCK_ESCAPE_GATE_WIDTH_M
    };
    console.log(
        `[BlockAhead][${logPrefix}] escape gate applied length=${BLOCK_ESCAPE_GATE_LENGTH_M}m width=${BLOCK_ESCAPE_GATE_WIDTH_M}m ` +
        `centers=${gateCenters.length}`
    );
    return gatedArea;
}

function _buildSideSpecificEscapeBlockedArea(blockedArea, side, logPrefix = 'escape-gate-side') {
    const gates = Array.isArray(blockedArea?.escapeGates)
        ? blockedArea.escapeGates.filter(gate => !side || gate.side === side)
        : [];
    const sideArea = {
        ...blockedArea,
        escapeGates: gates
    };
    console.log(
        `[BlockAhead][${logPrefix}] gate applied side=${side || 'both'} length=${Number(blockedArea?.escapeGateLengthM || BLOCK_ESCAPE_GATE_LENGTH_M)}m ` +
        `width=${Number(blockedArea?.escapeGateWidthM || BLOCK_ESCAPE_GATE_WIDTH_M)}m centers=${gates.length}`
    );
    return sideArea;
}

function _routeCoordsPrefix(coords, maxDistanceM) {
    const points = Array.isArray(coords) ? coords : [];
    if (points.length <= 1) return points.slice();
    const out = [points[0]];
    let walked = 0;
    for (let i = 1; i < points.length; i++) {
        const a = points[i - 1];
        const b = points[i];
        const segLen = _segmentLengthMeters(a, b);
        if (segLen <= 0) continue;
        if (walked + segLen <= maxDistanceM) {
            out.push(b);
            walked += segLen;
            continue;
        }
        const remain = Math.max(0, maxDistanceM - walked);
        const t = Math.max(0, Math.min(1, remain / segLen));
        out.push({
            lat: a.lat + ((b.lat - a.lat) * t),
            lng: (a.lng ?? a.lon) + (((b.lng ?? b.lon) - (a.lng ?? a.lon)) * t)
        });
        break;
    }
    return out;
}

function _routeCoordsSuffix(coords, skipDistanceM) {
    const points = Array.isArray(coords) ? coords : [];
    if (points.length <= 1) return points.slice();
    let walked = 0;
    for (let i = 1; i < points.length; i++) {
        const a = points[i - 1];
        const b = points[i];
        const segLen = _segmentLengthMeters(a, b);
        if (segLen <= 0) continue;
        if (walked + segLen < skipDistanceM) {
            walked += segLen;
            continue;
        }
        const remain = Math.max(0, skipDistanceM - walked);
        const t = Math.max(0, Math.min(1, remain / segLen));
        const startPoint = {
            lat: a.lat + ((b.lat - a.lat) * t),
            lng: (a.lng ?? a.lon) + (((b.lng ?? b.lon) - (a.lng ?? a.lon)) * t)
        };
        return [startPoint, ...points.slice(i)];
    }
    return [points[points.length - 1]];
}

function _buildRawEscapeCandidates(coords, projection, blockedArea, escapeSpecs, logPrefix, maxPoints) {
    const headingTarget = _walkAlongRoute(coords, projection, 20);
    const headingUnit = _headingUnitVectorMeters(projection?.snappedPoint, headingTarget);
    if (!headingUnit) return [];

    const deduped = [];
    for (const spec of escapeSpecs.slice(0, maxPoints)) {
        const beforeDistance = _distancePointToBlockedArea(
            _buildEscapePoint(projection.snappedPoint, headingUnit, spec.side, spec.lateralM, spec.backwardM),
            blockedArea,
            blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS
        );
        const pushed = _pushEscapePointOutsideBlockedArea(
            projection.snappedPoint,
            headingUnit,
            spec.side,
            spec.lateralM,
            blockedArea,
            spec.backwardM
        );
        if (!pushed?.point) {
            console.log(`[BlockAhead][${logPrefix}] rejected point ${spec.label}: inside blocked area`);
            continue;
        }
        const point = pushed.point;
        const afterDistance = _distancePointToBlockedArea(point, blockedArea, blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS);
        console.log(
            `[BlockAhead][${logPrefix}] raw ${spec.label}: blocked-before=${Math.round(beforeDistance)}m blocked-after=${Math.round(afterDistance)}m`
        );
        if (deduped.some(existing =>
            _segmentLengthMeters(existing.point, point) < 12
            && existing.side === spec.side
            && Number(existing.distanceTierM || 0) === Number(spec.lateralM || 0)
            && String(existing.depthKind || 'entrance') === String(spec.depthKind || 'entrance')
            && Number(existing.backwardM || 0) === Number(spec.backwardM || 0)
        )) continue;
        deduped.push({
            label: spec.label,
            point,
            lateralM: pushed.lateralM,
            backwardM: spec.backwardM,
            side: spec.side,
            distanceTierM: spec.lateralM,
            depthKind: spec.depthKind || 'entrance'
        });
    }
    return deduped;
}

function _escapeDepthRank(depthKind) {
    const label = String(depthKind || 'entrance');
    if (label === 'deeper-120') return 4;
    if (label === 'deeper-90') return 3;
    if (label === 'deeper-60') return 2;
    if (label === 'deeper-30') return 1;
    return 0;
}

async function _fetchOsrmNearestNode(point) {
    const transportMode = document.getElementById('transportMode')?.value ?? 'walking';
    const profile = transportMode === 'walking' ? 'walking' : 'driving';
    const routeServiceUrl = OSRM_SERVICE_URLS[profile];
    const nearestServiceUrl = routeServiceUrl.replace('/route/v1', '/nearest/v1');
    const url = `${nearestServiceUrl}/${profile}/${point.lng ?? point.lon},${point.lat}?number=1`;
    const startedAt = _perfNowMs();
    try {
        const res = await fetch(url);
        if (!res.ok) return null;
        const data = await res.json();
        const waypoint = Array.isArray(data?.waypoints) ? data.waypoints[0] : null;
        const snapped = Array.isArray(waypoint?.location) ? waypoint.location : null;
        if (!snapped || snapped.length < 2) return null;
        return {
            lat: snapped[1],
            lng: snapped[0],
            distanceM: Number(waypoint?.distance || 0)
        };
    } catch (error) {
        console.warn('[BlockAhead][escape-snap] nearest fetch error:', error);
        return null;
    } finally {
        const durationMs = _perfNowMs() - startedAt;
        _recordBlockAheadTiming('osrmEval', durationMs);
        console.log(`[BlockAhead][timing] osrm nearest ${Math.round(durationMs)}ms`);
    }
}

async function _snapEscapeCandidatesToRoadNodes(rawCandidates, blockedArea, originalCoords, logPrefix) {
    const rawList = Array.isArray(rawCandidates) ? rawCandidates : [];
    console.log(`[BlockAhead][${logPrefix}] raw-candidates=${rawList.length}`);
    const origin = Array.isArray(originalCoords) && originalCoords.length > 0 ? originalCoords[0] : null;
    const forwardRef = Array.isArray(originalCoords) && originalCoords.length > 1 ? originalCoords[Math.min(1, originalCoords.length - 1)] : null;
    const forwardBearing = origin && forwardRef ? _segmentBearingDeg(origin, forwardRef) : 0;
    const evaluateCandidate = async (candidate) => {
        const snappedPoint = await _fetchOsrmNearestNode(candidate.point);
        if (!snappedPoint) {
            console.log(`[BlockAhead][${logPrefix}] reject ${candidate.label}: no-nearest`);
            return null;
        }
        const blockedDistance = _distancePointToBlockedArea(snappedPoint, blockedArea, blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS);
        if (blockedDistance <= 0) {
            console.log(`[BlockAhead][${logPrefix}] reject ${candidate.label}: snapped inside blocked area`);
            return null;
        }
        const corridorDistance = _distancePointToRoute(snappedPoint, originalCoords);
        if (corridorDistance < BLOCK_ESCAPE_CORRIDOR_DIFF_M) {
            console.log(`[BlockAhead][${logPrefix}] reject ${candidate.label}: snapped same corridor ${Math.round(corridorDistance)}m`);
            return null;
        }
        const bearingToNode = origin ? _segmentBearingDeg(origin, snappedPoint) : 0;
        const bearingDiff = _bearingDiffDeg(forwardBearing, bearingToNode);
        const nodeType = bearingDiff >= BLOCK_ESCAPE_SIDE_BEARING_DEG ? 'side-road' : 'corridor-like';
        const depthBonus = _escapeDepthRank(candidate.depthKind) * 80;
        const typeBonus = nodeType === 'side-road' ? 120 : 0;
        const score = depthBonus + typeBonus + (corridorDistance * 1.8) + (bearingDiff * 1.2) + ((candidate.lateralM || 0) * 0.2) - (Number(snappedPoint.distanceM || 0) * 0.5);
        return {
            ...candidate,
            rawPoint: candidate.point,
            point: { lat: snappedPoint.lat, lng: snappedPoint.lng },
            snapDistanceM: snappedPoint.distanceM,
            corridorDistanceM: corridorDistance,
            blockedDistanceM: blockedDistance,
            bearingDiffDeg: bearingDiff,
            nodeType,
            nodeScore: score,
            entrancePoint: candidate.entrancePoint || candidate.point,
            holdWaypoint: candidate.holdWaypoint || null,
            depthRank: _escapeDepthRank(candidate.depthKind)
        };
    };

    const entranceCandidates = (await Promise.all(rawList.map(evaluateCandidate))).filter(Boolean);
    const deeperRawCandidates = [];
    for (const candidate of entranceCandidates) {
        if (candidate.nodeType !== 'side-road' || !origin) continue;
        const unit = _headingUnitVectorMeters(origin, candidate.point);
        if (!unit) continue;
        for (const depthM of BLOCK_ESCAPE_DEEPER_STEPS_M) {
            const deeperPoint = _offsetPointByMeters(candidate.point, unit.east * depthM, unit.north * depthM);
            if (!deeperPoint) continue;
            deeperRawCandidates.push({
                ...candidate,
                label: `${candidate.label}-deep-${depthM}`,
                point: deeperPoint,
                depthKind: `deeper-${depthM}`,
                depthMeters: depthM,
                entrancePoint: candidate.point,
                holdWaypoint: candidate.point
            });
        }
    }
    console.log(
        `[BlockAhead][${logPrefix}] generated-tiers=${[...new Set(rawList.map(candidate => candidate.distanceTierM).filter(Number.isFinite))].join('/')} ` +
        `depths=${['entrance', ...BLOCK_ESCAPE_DEEPER_STEPS_M.map(step => `deeper-${step}`)].join('/')} ` +
        `entrance=${entranceCandidates.length} deeper=${deeperRawCandidates.length}`
    );
    const deeperCandidates = deeperRawCandidates.length > 0
        ? (await Promise.all(deeperRawCandidates.map(evaluateCandidate))).filter(Boolean)
        : [];
    const snapped = entranceCandidates.concat(deeperCandidates);

    const deduped = [];
    for (const candidate of snapped.filter(Boolean)) {
        if (deduped.some(existing =>
            _segmentLengthMeters(existing.point, candidate.point) < 12
            && existing.side === candidate.side
            && Number(existing.distanceTierM || 0) === Number(candidate.distanceTierM || 0)
            && String(existing.depthKind || 'entrance') === String(candidate.depthKind || 'entrance')
        )) continue;
        deduped.push(candidate);
    }
    deduped.sort((a, b) => (b.nodeScore - a.nodeScore) || (b.corridorDistanceM - a.corridorDistanceM));
    console.log(`[BlockAhead][${logPrefix}] snapped-candidates=${deduped.length}`);
    deduped.forEach(candidate => {
        console.log(
            `[BlockAhead][${logPrefix}] node ${candidate.label}: tier=${candidate.distanceTierM || '-'} depth=${candidate.depthKind || 'entrance'} type=${candidate.nodeType} ` +
            `score=${candidate.nodeScore.toFixed(1)} corridor=${Math.round(candidate.corridorDistanceM)}m ` +
            `bearing=${Math.round(candidate.bearingDiffDeg)}deg snap=${Math.round(candidate.snapDistanceM)}m`
        );
    });
    return deduped;
}

async function _generateEscapePoints(coords, projection, blockedArea) {
    const escapeBlockedArea = _buildEscapeGateBlockedArea(coords, projection, blockedArea, 'escape');
    const escapeSpecs = [
        { side: 'left', lateralM: 60, backwardM: 0, label: 'left-60' },
        { side: 'right', lateralM: 60, backwardM: 0, label: 'right-60' },
        { side: 'left', lateralM: 100, backwardM: 0, label: 'left-100' },
        { side: 'right', lateralM: 100, backwardM: 0, label: 'right-100' },
        { side: 'left', lateralM: 60, backwardM: BLOCK_ESCAPE_BACKWARD_M, label: 'back-left-60' },
        { side: 'right', lateralM: 60, backwardM: BLOCK_ESCAPE_BACKWARD_M, label: 'back-right-60' }
    ];
    const rawCandidates = _buildRawEscapeCandidates(coords, projection, escapeBlockedArea, escapeSpecs, 'escape', BLOCK_ESCAPE_MAX_POINTS);
    return _snapEscapeCandidatesToRoadNodes(rawCandidates, escapeBlockedArea, coords, 'escape');
}

async function _generateEscapeLegPoints(coords, projection, blockedArea) {
    const escapeBlockedArea = _buildEscapeGateBlockedArea(coords, projection, blockedArea, 'escape-leg');
    const legSpecs = [
        { side: 'left', lateralM: 30, backwardM: 0, label: 'leg-left-30' },
        { side: 'right', lateralM: 30, backwardM: 0, label: 'leg-right-30' },
        { side: 'left', lateralM: 60, backwardM: 0, label: 'leg-left-60' },
        { side: 'right', lateralM: 60, backwardM: 0, label: 'leg-right-60' },
        { side: 'left', lateralM: 90, backwardM: 0, label: 'leg-left-90' },
        { side: 'right', lateralM: 90, backwardM: 0, label: 'leg-right-90' },
        { side: 'left', lateralM: 120, backwardM: 0, label: 'leg-left-120' },
        { side: 'right', lateralM: 120, backwardM: 0, label: 'leg-right-120' },
        { side: 'left', lateralM: 30, backwardM: BLOCK_ESCAPE_LEG_BACKWARD_M, label: 'leg-back-left-30' },
        { side: 'right', lateralM: 30, backwardM: BLOCK_ESCAPE_LEG_BACKWARD_M, label: 'leg-back-right-30' }
    ];
    const rawCandidates = _buildRawEscapeCandidates(coords, projection, escapeBlockedArea, legSpecs, 'escape-leg', BLOCK_ESCAPE_LEG_MAX_POINTS);
    const snapped = await _snapEscapeCandidatesToRoadNodes(rawCandidates, escapeBlockedArea, coords, 'escape-leg');
    return snapped.sort((a, b) => (a.lateralM - b.lateralM) || (b.nodeScore - a.nodeScore));
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

function _dedupeBlockedAreaCenters(centers, mergeDistanceM = 12) {
    const deduped = [];
    for (const center of Array.isArray(centers) ? centers : []) {
        if (!center) continue;
        const existing = deduped.find(item => _segmentLengthMeters(item, center) <= mergeDistanceM);
        if (!existing) {
            deduped.push({ ...center });
            continue;
        }
        existing.radius = Math.max(existing.radius || 0, center.radius || 0);
    }
    return deduped;
}

function _buildBlockedArea(coords, projection, options = {}) {
    const startM = Number(options.startM ?? BLOCK_AHEAD_START_METERS);
    const endM = Number(options.endM ?? BLOCK_AHEAD_END_METERS);
    const backwardM = Math.max(0, Number(options.backwardM || 0));
    const baseRadiusM = Number(options.baseRadiusM ?? BLOCK_BUFFER_METERS);
    const extraRadiusM = Number(options.extraRadiusM || 0);
    const intersectionBufferM = Number(options.intersectionBufferM ?? BLOCK_INTERSECTION_BUFFER_METERS);
    const logKey = options.logKey || 'blocked-shape';
    const centers = [];
    const effectiveRadius = Math.max(1, baseRadiusM + extraRadiusM);
    const slitRadiusM = Math.max(BLOCK_MIN_SLIT_RADIUS_M, (baseRadiusM * BLOCK_MAIN_SLIT_RADIUS_RATIO) + (extraRadiusM * 0.35));
    const coreRadiusM = Math.max(BLOCK_MIN_CORE_RADIUS_M, (baseRadiusM * BLOCK_CORE_RADIUS_RATIO) + (extraRadiusM * 0.45));
    const intersectionRadiusM = Math.max(
        coreRadiusM,
        (intersectionBufferM * BLOCK_INTERSECTION_RADIUS_RATIO) + (extraRadiusM * 0.35)
    );
    const slitDistances = [];
    for (let dist = -backwardM; dist <= endM; dist += BLOCK_SAMPLE_STEP_METERS) {
        slitDistances.push(dist);
    }
    for (let idx = 0; idx < slitDistances.length; idx++) {
        const dist = slitDistances[idx];
        const point = _walkAlongRouteRelative(coords, projection, dist);
        const isCap = idx === 0 || idx === slitDistances.length - 1;
        centers.push({
            lat: point.lat,
            lng: point.lng,
            radius: slitRadiusM,
            kind: isCap ? 'corridor-slit-cap' : 'corridor-slit-body'
        });
    }
    const startPoint = _walkAlongRouteRelative(coords, projection, Math.max(-backwardM, 0));
    centers.push({ lat: projection.snappedPoint.lat, lng: projection.snappedPoint.lng, radius: coreRadiusM, kind: 'core-start' });
    centers.push({ lat: startPoint.lat, lng: startPoint.lng, radius: coreRadiusM, kind: 'core-forward-start' });
    const endPoint = _walkAlongRoute(coords, projection, endM);
    centers.push({ lat: endPoint.lat, lng: endPoint.lng, radius: coreRadiusM, kind: 'core-end' });
    if (backwardM > 0) {
        const backPoint = _walkAlongRouteBackward(coords, projection, backwardM);
        centers.push({ lat: backPoint.lat, lng: backPoint.lng, radius: coreRadiusM, kind: 'core-back' });
    }

    let progressedForward = 0;
    let prev = projection.snappedPoint;
    for (let i = projection.segmentIndex + 1; i < coords.length - 1; i++) {
        const curr = coords[i];
        progressedForward += _segmentLengthMeters(prev, curr);
        if (progressedForward < startM - BLOCK_SAMPLE_STEP_METERS) {
            prev = curr;
            continue;
        }
        if (progressedForward > endM + BLOCK_SAMPLE_STEP_METERS) break;
        const next = coords[i + 1];
        const angle = _turnAngleDeg(prev, curr, next);
        if (angle >= BLOCK_INTERSECTION_TURN_DEG) {
            centers.push({
                lat: curr.lat,
                lng: curr.lng ?? curr.lon,
                radius: intersectionRadiusM,
                kind: 'intersection'
            });
        }
        prev = curr;
    }

    let progressedBackward = 0;
    let next = projection.snappedPoint;
    for (let i = projection.segmentIndex; i >= 1; i--) {
        const curr = coords[i];
        progressedBackward += _segmentLengthMeters(next, curr);
        if (progressedBackward > backwardM + BLOCK_SAMPLE_STEP_METERS) break;
        const prevPoint = coords[i - 1];
        const angle = _turnAngleDeg(prevPoint, curr, next);
        if (angle >= BLOCK_INTERSECTION_TURN_DEG) {
            centers.push({
                lat: curr.lat,
                lng: curr.lng ?? curr.lon,
                radius: intersectionRadiusM,
                kind: 'intersection-back'
            });
        }
        next = curr;
    }
    const dedupedCenters = _dedupeBlockedAreaCenters(centers);
    const overlapRadiusM = Math.max(BLOCK_MIN_SLIT_RADIUS_M + 6, slitRadiusM + 8);
    console.log(
        `[BlockAhead][${logKey}] slit=${Math.round(slitRadiusM)}m core=${Math.round(coreRadiusM)}m ` +
        `intersection=${Math.round(intersectionRadiusM)}m overlapRadius=${Math.round(overlapRadiusM)}m ` +
        `legacyRadius=${Math.round(effectiveRadius)}m centers=${dedupedCenters.length}`
    );
    return {
        centers: dedupedCenters,
        baseRadiusM: effectiveRadius,
        slitRadiusM,
        coreRadiusM,
        intersectionRadiusM,
        overlapRadiusM,
        broadOverlapRadiusM: effectiveRadius + 15,
        nearRejectMeters: BLOCK_NEAR_REJECT_METERS,
        // Always allow an initial escape zone near the current position so the
        // user can first get off the blocked corridor before strict filtering.
        // Keep at least 30-50m ignored, but do not start filtering until the
        // route has had a chance to exit the widened corridor + near-reject band.
        ignoreUntilM: Math.max(
            0,
            Math.min(endM, Math.max(
                BLOCK_ESCAPE_IGNORE_METERS,
                startM,
                coreRadiusM + BLOCK_NEAR_REJECT_METERS
            ))
        )
    };
}

function _distancePointToBlockedArea(point, blockedArea, extraM = 0) {
    const centers = Array.isArray(blockedArea?.centers) ? blockedArea.centers : [];
    if (!point || centers.length === 0) return Infinity;
    let minDistance = Infinity;
    for (const center of centers) {
        const edgeDistance = _segmentLengthMeters(point, center) - ((center.radius || 0) + extraM);
        if (edgeDistance < minDistance) minDistance = edgeDistance;
    }
    const gates = Array.isArray(blockedArea?.escapeGates) ? blockedArea.escapeGates : [];
    for (const gate of gates) {
        const gateDistance = _segmentLengthMeters(point, gate) - ((gate.radius || 0) + extraM);
        if (gateDistance <= 0) {
            return Math.max(1, Math.abs(gateDistance));
        }
    }
    return minDistance;
}

function _blockedCenterComponentKind(center) {
    const kind = String(center?.kind || '');
    if (kind.startsWith('corridor-slit-body')) return 'slitBody';
    if (kind.startsWith('corridor-slit-cap')) return 'slitCap';
    if (kind.startsWith('core-')) return 'core';
    if (kind.startsWith('intersection')) return 'intersectionBuffer';
    return 'other';
}

function _pointBlockedAreaComponentDistances(point, blockedArea, extraM = 0) {
    const centers = Array.isArray(blockedArea?.centers) ? blockedArea.centers : [];
    const gates = Array.isArray(blockedArea?.escapeGates) ? blockedArea.escapeGates : [];
    const baseRadiusM = Number(blockedArea?.baseRadiusM || 0);
    const result = {
        gateActive: false,
        minDistance: Infinity,
        slitBodyDistance: Infinity,
        slitCapDistance: Infinity,
        coreDistance: Infinity,
        intersectionBufferDistance: Infinity,
        legacyBroadDistance: Infinity,
        slitNearDistance: Infinity
    };
    if (!point || centers.length === 0) return result;

    for (const gate of gates) {
        const gateDistance = _segmentLengthMeters(point, gate) - ((gate.radius || 0) + extraM);
        if (gateDistance <= 0) {
            result.gateActive = true;
            break;
        }
    }

    for (const center of centers) {
        const centerDistance = _segmentLengthMeters(point, center);
        const edgeDistance = centerDistance - ((center.radius || 0) + extraM);
        if (edgeDistance < result.minDistance) result.minDistance = edgeDistance;
        const broadDistance = centerDistance - (baseRadiusM + extraM);
        if (broadDistance < result.legacyBroadDistance) result.legacyBroadDistance = broadDistance;
        switch (_blockedCenterComponentKind(center)) {
        case 'slitBody':
            if (edgeDistance < result.slitBodyDistance) result.slitBodyDistance = edgeDistance;
            if (broadDistance < result.slitNearDistance) result.slitNearDistance = broadDistance;
            break;
        case 'slitCap':
            if (edgeDistance < result.slitCapDistance) result.slitCapDistance = edgeDistance;
            if (broadDistance < result.slitNearDistance) result.slitNearDistance = broadDistance;
            break;
        case 'core':
            if (edgeDistance < result.coreDistance) result.coreDistance = edgeDistance;
            break;
        case 'intersectionBuffer':
            if (edgeDistance < result.intersectionBufferDistance) result.intersectionBufferDistance = edgeDistance;
            break;
        default:
            break;
        }
    }
    if (result.gateActive) {
        result.minDistance = Math.max(1, Math.abs(result.minDistance));
    }
    return result;
}

function _routeBlockedAreaStats(coords, blockedArea) {
    const sampled = [];
    const ignoreUntilM = Number(blockedArea?.ignoreUntilM || 0);
    if (!Array.isArray(coords) || coords.length === 0) {
        return {
            strictOverlapRatio: 0, nearBlockedRatio: 0, minDistanceToAreaM: Infinity, intersects: false, nearBlocked: false,
            slitIntersectionDetected: false, coreIntersectionDetected: false, intersectionBufferDetected: false,
            legacyBroadIntersectionDetected: false, carveOutAdjustedIntersectionDetected: false
        };
    }
    let walked = 0;
    sampled.push({ point: coords[0], walked: 0 });
    for (let i = 1; i < coords.length; i++) {
        const a = coords[i - 1];
        const b = coords[i];
        const segLen = _segmentLengthMeters(a, b);
        if (segLen <= 0) continue;
        let dist = 8;
        while (dist < segLen) {
            const t = dist / segLen;
            sampled.push({
                point: {
                    lat: a.lat + (b.lat - a.lat) * t,
                    lng: (a.lng ?? a.lon) + ((b.lng ?? b.lon) - (a.lng ?? a.lon)) * t
                },
                walked: walked + dist
            });
            dist += 8;
        }
        walked += segLen;
        sampled.push({ point: b, walked });
    }
    let effectiveSamples = sampled.filter(sample => sample.walked >= ignoreUntilM);
    if (effectiveSamples.length === 0 && sampled.length > 0) {
        effectiveSamples = [sampled[sampled.length - 1]];
    }
    if (effectiveSamples.length === 0) {
        return {
            strictOverlapRatio: 0, nearBlockedRatio: 0, minDistanceToAreaM: Infinity, intersects: false, nearBlocked: false,
            slitIntersectionDetected: false, coreIntersectionDetected: false, intersectionBufferDetected: false,
            legacyBroadIntersectionDetected: false, carveOutAdjustedIntersectionDetected: false
        };
    }
    let strictHits = 0;
    let nearHits = 0;
    let slitBodyHits = 0;
    let slitCapHits = 0;
    let slitNearHits = 0;
    let coreHits = 0;
    let intersectionHits = 0;
    let legacyBroadHits = 0;
    let carveOutAdjustedHits = 0;
    let minDistanceToAreaM = Infinity;
    for (const sample of effectiveSamples) {
        const point = sample.point;
        const strictComponents = _pointBlockedAreaComponentDistances(point, blockedArea, 0);
        const nearComponents = _pointBlockedAreaComponentDistances(point, blockedArea, blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS);
        const strictDistance = strictComponents.minDistance;
        const nearDistance = nearComponents.minDistance;
        if (strictDistance <= 0) strictHits++;
        if (nearDistance <= 0) nearHits++;
        if (strictComponents.slitBodyDistance <= 0) slitBodyHits++;
        if (strictComponents.slitCapDistance <= 0) slitCapHits++;
        if (nearComponents.slitNearDistance <= 0) slitNearHits++;
        if (strictComponents.coreDistance <= 0) coreHits++;
        if (strictComponents.intersectionBufferDistance <= 0) intersectionHits++;
        if (strictComponents.legacyBroadDistance <= 0) legacyBroadHits++;
        if (strictComponents.gateActive && strictComponents.legacyBroadDistance <= 0) carveOutAdjustedHits++;
        minDistanceToAreaM = Math.min(minDistanceToAreaM, strictDistance);
    }
    const slitBodyIntersectionDetected = slitBodyHits > 0;
    const slitCapIntersectionDetected = slitCapHits > 0;
    const slitNearDetected = slitNearHits > 0;
    const coreIntersectionDetected = coreHits > 0;
    const intersectionBufferDetected = intersectionHits > 0;
    const legacyBroadIntersectionDetected = legacyBroadHits > 0;
    const carveOutAdjustedIntersectionDetected = carveOutAdjustedHits > 0;
    return {
        strictOverlapRatio: strictHits / effectiveSamples.length,
        nearBlockedRatio: nearHits / effectiveSamples.length,
        minDistanceToAreaM,
        intersects: slitBodyIntersectionDetected || slitCapIntersectionDetected || coreIntersectionDetected || intersectionBufferDetected,
        nearBlocked: nearHits > 0,
        slitIntersectionDetected: slitBodyIntersectionDetected || slitCapIntersectionDetected,
        slitBodyIntersectionDetected,
        slitCapIntersectionDetected,
        slitNearDetected,
        coreIntersectionDetected,
        intersectionBufferDetected,
        legacyBroadIntersectionDetected,
        carveOutAdjustedIntersectionDetected,
        slitBodyOverlapRatio: slitBodyHits / effectiveSamples.length,
        slitCapOverlapRatio: slitCapHits / effectiveSamples.length,
        slitNearRatio: slitNearHits / effectiveSamples.length,
        coreOverlapRatio: coreHits / effectiveSamples.length,
        intersectionBufferOverlapRatio: intersectionHits / effectiveSamples.length
    };
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

function _metersToLat(meters) {
    return Number(meters || 0) / 111111;
}

function _metersToLng(meters, lat) {
    return Number(meters || 0) / (111111 * Math.max(0.2, Math.cos(Number(lat || 0) * Math.PI / 180)));
}

function _routeBoundsWithPadding(coords, paddingM = PEDESTRIAN_SAFETY_BBOX_PADDING_M) {
    const points = Array.isArray(coords) ? coords : [];
    if (points.length === 0) return null;
    let minLat = Infinity;
    let maxLat = -Infinity;
    let minLng = Infinity;
    let maxLng = -Infinity;
    for (const point of points) {
        const lat = Number(point?.lat);
        const lng = Number(point?.lng ?? point?.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
        minLng = Math.min(minLng, lng);
        maxLng = Math.max(maxLng, lng);
    }
    if (!Number.isFinite(minLat) || !Number.isFinite(minLng)) return null;
    const centerLat = (minLat + maxLat) / 2;
    const latPad = _metersToLat(paddingM);
    const lngPad = _metersToLng(paddingM, centerLat);
    return {
        minLat: minLat - latPad,
        minLng: minLng - lngPad,
        maxLat: maxLat + latPad,
        maxLng: maxLng + lngPad
    };
}

function _pedestrianSafetyCacheKey(bounds) {
    if (!bounds) return 'empty';
    return [
        bounds.minLat.toFixed(4),
        bounds.minLng.toFixed(4),
        bounds.maxLat.toFixed(4),
        bounds.maxLng.toFixed(4)
    ].join(':');
}

function _dedupeNearbyPoints(points, thresholdM = 10) {
    const deduped = [];
    for (const point of Array.isArray(points) ? points : []) {
        if (!point) continue;
        const exists = deduped.find(item => _segmentLengthMeters(item, point) <= thresholdM);
        if (!exists) deduped.push(point);
    }
    return deduped;
}

function _segmentIntersectionPoint(a, b, c, d) {
    if (!a || !b || !c || !d) return null;
    const x1 = Number(a.lng ?? a.lon);
    const y1 = Number(a.lat);
    const x2 = Number(b.lng ?? b.lon);
    const y2 = Number(b.lat);
    const x3 = Number(c.lng ?? c.lon);
    const y3 = Number(c.lat);
    const x4 = Number(d.lng ?? d.lon);
    const y4 = Number(d.lat);
    const denom = ((x1 - x2) * (y3 - y4)) - ((y1 - y2) * (x3 - x4));
    if (Math.abs(denom) < 1e-12) return null;
    const t = (((x1 - x3) * (y3 - y4)) - ((y1 - y3) * (x3 - x4))) / denom;
    const u = -((((x1 - x2) * (y1 - y3)) - ((y1 - y2) * (x1 - x3))) / denom);
    if (t < 0 || t > 1 || u < 0 || u > 1) return null;
    return {
        lat: y1 + (t * (y2 - y1)),
        lng: x1 + (t * (x2 - x1))
    };
}

function _parseNumericTag(value, fallback = 0) {
    if (Number.isFinite(Number(value))) return Number(value);
    if (typeof value === 'string') {
        const matched = value.match(/\d+(\.\d+)?/);
        if (matched) return Number(matched[0]);
    }
    return fallback;
}

function _isTruthyTag(value) {
    return value === true || value === 'yes' || value === 'true' || value === 1 || value === '1';
}

function _findCrosswalkNearby(point, context, radiusM = PEDESTRIAN_SAFETY_CROSSWALK_RADIUS_M) {
    const crosswalks = Array.isArray(context?.crosswalks) ? context.crosswalks : [];
    return crosswalks.some(item => _segmentLengthMeters(point, item) <= radiusM);
}

function _parsePedestrianSafetyContext(data) {
    const elements = Array.isArray(data?.elements) ? data.elements : [];
    const nodeMap = new Map();
    elements.forEach((element) => {
        if (element?.type === 'node' && Number.isFinite(Number(element.lat)) && Number.isFinite(Number(element.lon))) {
            nodeMap.set(element.id, { lat: Number(element.lat), lng: Number(element.lon), tags: element.tags || {} });
        }
    });

    const roads = [];
    const crosswalks = [];
    elements.forEach((element) => {
        if (element?.type === 'node') {
            const tags = element.tags || {};
            if (tags.highway === 'crossing' || tags.crossing || tags.highway === 'traffic_signals') {
                crosswalks.push({ lat: Number(element.lat), lng: Number(element.lon), tags });
            }
            return;
        }
        if (element?.type !== 'way') return;
        const tags = element.tags || {};
        const coords = Array.isArray(element.nodes)
            ? element.nodes.map(id => nodeMap.get(id)).filter(Boolean).map(node => ({ lat: node.lat, lng: node.lng }))
            : [];
        if (coords.length < 2) return;
        if (tags.highway === 'footway' && tags.footway === 'crossing') {
            coords.forEach(point => crosswalks.push({ ...point, tags }));
            return;
        }
        if (tags.highway || tags.motorroad || tags.foot || tags.lanes) {
            roads.push({
                id: element.id,
                tags,
                coordinates: coords
            });
        }
    });

    return {
        roads,
        crosswalks: _dedupeNearbyPoints(crosswalks, 8)
    };
}

async function _fetchPedestrianSafetyContextForRoute(route) {
    const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    const bounds = _routeBoundsWithPadding(coords, PEDESTRIAN_SAFETY_BBOX_PADDING_M);
    if (!bounds) return null;
    const cacheKey = _pedestrianSafetyCacheKey(bounds);
    const cached = _pedestrianSafetyContextCache.get(cacheKey);
    if (cached && (Date.now() - cached.at) < PEDESTRIAN_SAFETY_CACHE_TTL_MS) {
        return cached.value;
    }
    if (typeof navigator !== 'undefined' && navigator.webdriver) {
        return null;
    }

    const query = `
[out:json][timeout:8];
(
  way["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link"](${bounds.minLat},${bounds.minLng},${bounds.maxLat},${bounds.maxLng});
  way["motorroad"="yes"](${bounds.minLat},${bounds.minLng},${bounds.maxLat},${bounds.maxLng});
  node["highway"="crossing"](${bounds.minLat},${bounds.minLng},${bounds.maxLat},${bounds.maxLng});
  node["crossing"](${bounds.minLat},${bounds.minLng},${bounds.maxLat},${bounds.maxLng});
  node["highway"="traffic_signals"](${bounds.minLat},${bounds.minLng},${bounds.maxLat},${bounds.maxLng});
  way["highway"="footway"]["footway"="crossing"](${bounds.minLat},${bounds.minLng},${bounds.maxLat},${bounds.maxLng});
);
(._;>;);
out body;
`.trim();

    const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
    const timeoutId = controller ? setTimeout(() => controller.abort(), PEDESTRIAN_SAFETY_FETCH_TIMEOUT_MS) : null;
    try {
        const res = await fetch(PEDESTRIAN_SAFETY_OVERPASS_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
            body: query,
            signal: controller?.signal
        });
        if (!res.ok) return null;
        const data = await res.json();
        const parsed = _parsePedestrianSafetyContext(data);
        _pedestrianSafetyContextCache.set(cacheKey, { at: Date.now(), value: parsed });
        return parsed;
    } catch (error) {
        console.warn('[PedestrianSafety] context fetch failed:', error?.message || error);
        _pedestrianSafetyContextCache.set(cacheKey, { at: Date.now(), value: null });
        return null;
    } finally {
        if (timeoutId) clearTimeout(timeoutId);
    }
}

function _detectPedestrianCrossings(route, context) {
    const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    const roads = Array.isArray(context?.roads) ? context.roads : [];
    const crossings = [];
    for (let i = 1; i < coords.length; i++) {
        const from = coords[i - 1];
        const to = coords[i];
        const routeBearing = _segmentBearingDeg(from, to);
        for (const road of roads) {
            const roadCoords = Array.isArray(road.coordinates) ? road.coordinates : [];
            for (let j = 1; j < roadCoords.length; j++) {
                const roadFrom = roadCoords[j - 1];
                const roadTo = roadCoords[j];
                const intersectionPoint = _segmentIntersectionPoint(from, to, roadFrom, roadTo);
                if (!intersectionPoint) continue;
                const roadBearing = _segmentBearingDeg(roadFrom, roadTo);
                const bearingDiff = _bearingDiffDeg(routeBearing, roadBearing);
                if (bearingDiff < PEDESTRIAN_SAFETY_MIN_CROSSING_BEARING_DEG) continue;
                const exists = crossings.find(item => _segmentLengthMeters(item.point, intersectionPoint) <= 8);
                if (exists) continue;
                crossings.push({
                    point: intersectionPoint,
                    routeSegment: { from, to },
                    roadSegment: { from: roadFrom, to: roadTo },
                    road,
                    bearingDiff
                });
            }
        }
    }
    return crossings;
}

function _classifyDangerousCrossing(crossing, context, options = {}) {
    const tags = crossing?.road?.tags || {};
    const highway = String(tags.highway || '');
    const lanes = _parseNumericTag(tags.lanes, 0);
    const crosswalkNearby = _findCrosswalkNearby(crossing?.point, context, PEDESTRIAN_SAFETY_CROSSWALK_RADIUS_M);
    const motorroad = _isTruthyTag(tags.motorroad);
    const footNo = String(tags.foot || '') === 'no';
    const divided = _isTruthyTag(tags.divided) || _isTruthyTag(tags.divider) || _isTruthyTag(tags.dual_carriageway);
    const lessStrictMode = !!options.lessStrictMode;

    let dangerous = false;
    let reason = null;
    if (PEDESTRIAN_SAFETY_FORBIDDEN_HIGHWAYS.has(highway) || motorroad) {
        dangerous = true;
        reason = 'motorroad';
    } else if (footNo) {
        dangerous = true;
        reason = 'foot-no';
    } else if (divided) {
        dangerous = true;
        reason = 'divided-road';
    } else if (!lessStrictMode && PEDESTRIAN_SAFETY_MAJOR_HIGHWAYS.has(highway) && !crosswalkNearby) {
        dangerous = true;
        reason = 'major-no-crosswalk';
    } else if (!lessStrictMode && lanes >= 3 && !crosswalkNearby) {
        dangerous = true;
        reason = 'multi-lane-no-crosswalk';
    }

    return {
        dangerous,
        reason,
        highway,
        lanes,
        crosswalkNearby,
        motorroad,
        footNo,
        divided
    };
}

function _evaluatePedestrianRouteAgainstContext(route, context, options = {}) {
    const crossings = _detectPedestrianCrossings(route, context);
    const dangerousCrossings = crossings
        .map(crossing => ({
            ...crossing,
            classification: _classifyDangerousCrossing(crossing, context, options)
        }))
        .filter(item => item.classification.dangerous);

    if (dangerousCrossings.length === 0) {
        console.log('[PedestrianSafety] crossingDetected=false dangerous=false rejectReason=none');
        return { safe: true, crossings, dangerousCrossings: [], rejectReason: null };
    }

    const first = dangerousCrossings[0];
    console.log(
        `[PedestrianSafety] crossingDetected=true dangerous=true roadType=${first.classification.highway || 'unknown'} ` +
        `lanes=${first.classification.lanes || 0} crosswalkNearby=${!!first.classification.crosswalkNearby} ` +
        `rejectReason=dangerous-crossing detail=${first.classification.reason || 'unknown'}`
    );
    return {
        safe: false,
        crossings,
        dangerousCrossings,
        rejectReason: 'dangerous-crossing'
    };
}

async function _evaluatePedestrianRouteSafety(route, contextLabel = 'route', options = {}) {
    const context = await _fetchPedestrianSafetyContextForRoute(route);
    if (!context || !Array.isArray(context.roads) || context.roads.length === 0) {
        console.log(`[PedestrianSafety] contextUnavailable=true label=${contextLabel}`);
        return { safe: true, crossings: [], dangerousCrossings: [], rejectReason: null, contextUnavailable: true };
    }
    return _evaluatePedestrianRouteAgainstContext(route, context, options);
}

function _distancePointToRoute(point, coords) {
    if (!point || !Array.isArray(coords) || coords.length < 2) return Infinity;
    const projection = _navFindClosestOnRoute(coords, point.lat, point.lng ?? point.lon);
    if (!projection?.snappedPoint) return Infinity;
    return _segmentLengthMeters(point, projection.snappedPoint);
}

function _sampleRoutePoints(coords, stepM = 25) {
    if (!Array.isArray(coords) || coords.length === 0) return [];
    if (coords.length === 1) return [coords[0]];
    const sampled = [coords[0]];
    let carry = 0;
    for (let i = 1; i < coords.length; i++) {
        const a = coords[i - 1];
        const b = coords[i];
        const segLen = _segmentLengthMeters(a, b);
        if (segLen <= 0) continue;
        let dist = stepM - carry;
        while (dist < segLen) {
            const t = dist / segLen;
            sampled.push({
                lat: a.lat + (b.lat - a.lat) * t,
                lng: (a.lng ?? a.lon) + ((b.lng ?? b.lon) - (a.lng ?? a.lon)) * t
            });
            dist += stepM;
        }
        carry = Math.max(0, segLen - (dist - stepM));
    }
    sampled.push(coords[coords.length - 1]);
    return sampled;
}

function _routeDifferenceMetrics(newCoords, originalCoords, context = {}) {
    if (!Array.isArray(newCoords) || newCoords.length < 2 || !Array.isArray(originalCoords) || originalCoords.length < 2) {
        return { overallMeanDeviationM: Infinity, blockedMeanDeviationM: Infinity, blockedSamePathRatio: 1 };
    }
    const allSamples = _sampleRoutePoints(newCoords, 25);
    const overallDistances = allSamples.map(point => _distancePointToRoute(point, originalCoords)).filter(Number.isFinite);
    const overallMeanDeviationM = overallDistances.length
        ? overallDistances.reduce((sum, d) => sum + d, 0) / overallDistances.length
        : Infinity;

    const blockMid = context.bufMid || null;
    const blockRadius = Math.max((context.overlapRadius || 0) * 1.4, 45);
    const blockedArea = context.blockedArea || null;
    const blockedSamples = blockedArea
        ? allSamples.filter(point => _distancePointToBlockedArea(point, blockedArea, blockedArea.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS) <= 0)
        : (blockMid
            ? allSamples.filter(point => _segmentLengthMeters(point, blockMid) <= blockRadius)
            : []);
    const blockedDistances = blockedSamples.map(point => _distancePointToRoute(point, originalCoords)).filter(Number.isFinite);
    const blockedMeanDeviationM = blockedDistances.length
        ? blockedDistances.reduce((sum, d) => sum + d, 0) / blockedDistances.length
        : overallMeanDeviationM;
    const blockedSamePathRatio = blockedDistances.length
        ? blockedDistances.filter(d => d <= 12).length / blockedDistances.length
        : 1;
    return { overallMeanDeviationM, blockedMeanDeviationM, blockedSamePathRatio };
}

function _assessEscapeNearPenaltyMode(blockedStats, overlap) {
    const strict = Number(blockedStats?.strictOverlapRatio || 0);
    const near = Number(blockedStats?.nearBlockedRatio || 0);
    const overlapValue = Number(overlap || 0);
    const slitBodyOverlapRatio = Number(blockedStats?.slitBodyOverlapRatio || 0);
    const slitCapOverlapRatio = Number(blockedStats?.slitCapOverlapRatio || 0);
    const slitNearRatio = Number(blockedStats?.slitNearRatio || 0);
    const slitLineCrossDetected = overlapValue > BLOCK_ESCAPE_NEAR_PENALTY_OVERLAP_EPS
        && slitBodyOverlapRatio >= 0.08;
    const slitBodyIntersectionDetected = slitBodyOverlapRatio >= 0.18;
    const slitCapIntersectionDetected = slitCapOverlapRatio >= 0.18;
    const slitNearDetected = slitNearRatio > 0;
    const coreIntersectionDetected = !!blockedStats?.coreIntersectionDetected;
    const intersectionBufferDetected = !!blockedStats?.intersectionBufferDetected;
    const legacyBroadIntersectionDetected = !!blockedStats?.legacyBroadIntersectionDetected;
    const carveOutAdjustedIntersectionDetected = !!blockedStats?.carveOutAdjustedIntersectionDetected;
    const actualIntersectionDetected = slitLineCrossDetected
        || slitBodyIntersectionDetected
        || coreIntersectionDetected
        || intersectionBufferDetected;
    const strictThresholdExceeded = strict >= BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX;
    const shouldUseNearPenaltyMode = overlapValue <= BLOCK_ESCAPE_NEAR_PENALTY_OVERLAP_EPS
        && !actualIntersectionDetected
        && !strictThresholdExceeded;
    const eligible = shouldUseNearPenaltyMode;
    const penalty = eligible ? ((overlapValue * 600) + (strict * 800) + (near * 400)) : Infinity;
    return {
        eligible,
        penalty,
        strict,
        near,
        overlap: overlapValue,
        actualIntersection: actualIntersectionDetected,
        actualIntersectionDetected,
        slitIntersectionDetected: blockedStats?.slitIntersectionDetected,
        slitLineCrossDetected,
        slitBodyIntersectionDetected,
        slitCapIntersectionDetected,
        slitNearDetected,
        coreIntersectionDetected,
        intersectionBufferDetected,
        legacyBroadIntersectionDetected,
        carveOutAdjustedIntersectionDetected,
        strictThresholdExceeded,
        shouldUseNearPenaltyMode,
        overlapEpsilon: BLOCK_ESCAPE_NEAR_PENALTY_OVERLAP_EPS,
        strictNearPenaltyMax: BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX
    };
}

function _assessBranchNearPenaltyMode(blockedStats, overlap) {
    const strict = Number(blockedStats?.strictOverlapRatio || 0);
    const near = Number(blockedStats?.nearBlockedRatio || 0);
    const overlapValue = Number(overlap || 0);
    const shouldUseNearPenaltyMode = overlapValue <= BLOCK_BRANCH_NEAR_PENALTY_OVERLAP_EPS
        && strict < BLOCK_BRANCH_NEAR_PENALTY_STRICT_MAX;
    const actualIntersection = overlapValue > BLOCK_BRANCH_NEAR_PENALTY_OVERLAP_EPS
        || strict >= BLOCK_BRANCH_NEAR_PENALTY_STRICT_MAX;
    const eligible = shouldUseNearPenaltyMode && !actualIntersection;
    const penalty = eligible ? ((strict * 700) + (near * 350)) : Infinity;
    return {
        eligible,
        penalty,
        strict,
        near,
        overlap: overlapValue,
        actualIntersection,
        shouldUseNearPenaltyMode
    };
}

function _assessBranchLikeRoute(route, originalCoords) {
    const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    const origin = Array.isArray(originalCoords) && originalCoords.length > 0 ? originalCoords[0] : null;
    const forwardRef = Array.isArray(originalCoords) && originalCoords.length > 1 ? originalCoords[Math.min(1, originalCoords.length - 1)] : null;
    const forwardBearing = origin && forwardRef ? _segmentBearingDeg(origin, forwardRef) : 0;
    const branchAnchor = coords.find((point, idx) => idx > 0 && _segmentLengthMeters(origin, point) >= 20) || coords[coords.length - 1];
    const branchBearing = origin && branchAnchor ? _segmentBearingDeg(origin, branchAnchor) : 0;
    const bearingDiff = _bearingDiffDeg(forwardBearing, branchBearing);
    const lateralDivergenceM = branchAnchor ? _distancePointToRoute(branchAnchor, originalCoords) : 0;
    const branchLike = bearingDiff >= BLOCK_BRANCH_MIN_BEARING_DIFF_DEG
        && lateralDivergenceM >= BLOCK_BRANCH_MIN_LATERAL_DIVERGENCE_M;
    return { branchLike, bearingDiff, lateralDivergenceM };
}

function _logEscapeNearPenaltyDecision(prefix, meta = {}) {
    const nearPenaltyMode = meta.nearPenaltyMode || {};
    const rejectReason = meta.rejectReason || 'none';
    console.log(
        `${prefix} holdWaypointMode=${!!meta.holdWaypointMode} ` +
        `overlapRaw=${Number(nearPenaltyMode.overlap || 0).toFixed(2)} ` +
        `strictRaw=${Number(nearPenaltyMode.strict || 0).toFixed(2)} ` +
        `nearRaw=${Number(nearPenaltyMode.near || 0).toFixed(2)} ` +
        `slitLineCrossDetected=${!!nearPenaltyMode.slitLineCrossDetected} ` +
        `slitBodyIntersectionDetected=${!!nearPenaltyMode.slitBodyIntersectionDetected} ` +
        `slitCapIntersectionDetected=${!!nearPenaltyMode.slitCapIntersectionDetected} ` +
        `slitNearDetected=${!!nearPenaltyMode.slitNearDetected} ` +
        `coreIntersectionDetected=${!!nearPenaltyMode.coreIntersectionDetected} ` +
        `intersectionBufferDetected=${!!nearPenaltyMode.intersectionBufferDetected} ` +
        `legacyBroadIntersectionDetected=${!!nearPenaltyMode.legacyBroadIntersectionDetected} ` +
        `carveOutAdjustedIntersectionDetected=${!!nearPenaltyMode.carveOutAdjustedIntersectionDetected} ` +
        `overlapEpsilon=${Number(nearPenaltyMode.overlapEpsilon || 0).toFixed(2)} ` +
        `strictNearPenaltyMax=${Number(nearPenaltyMode.strictNearPenaltyMax || 0).toFixed(2)} ` +
        `actualIntersectionDetected=${!!nearPenaltyMode.actualIntersectionDetected} ` +
        `strictThresholdExceeded=${!!nearPenaltyMode.strictThresholdExceeded} ` +
        `shouldUseNearPenaltyMode=${!!nearPenaltyMode.shouldUseNearPenaltyMode} ` +
        `nearPenaltyMode=${!!nearPenaltyMode.eligible} ` +
        `nearPenalty=${Number.isFinite(nearPenaltyMode.penalty) ? nearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
        `rejectReason=${rejectReason}`
    );
}

function _escapeRejectReason(nearPenaltyMode, flags = {}) {
    if (nearPenaltyMode?.slitLineCrossDetected) return 'slit-line-cross';
    if (nearPenaltyMode?.slitBodyIntersectionDetected) return 'slit-body-intersection';
    if (nearPenaltyMode?.slitCapIntersectionDetected) return 'slit-cap-intersection';
    if (nearPenaltyMode?.slitNearDetected && flags.nearOnlyReject) return 'slit-near';
    if (nearPenaltyMode?.coreIntersectionDetected) return 'core-intersection';
    if (nearPenaltyMode?.intersectionBufferDetected) return 'intersection-buffer';
    if (flags.actualIntersectionDetected) return 'actual-intersection';
    if (flags.overlapHard) return 'overlap-hard';
    if (flags.strictThresholdExceeded) return 'strict-threshold';
    if (flags.nearOnlyReject) return 'near-only';
    return 'blocked';
}

function _isMeaningfullyDifferentReroute(newRoute, originalRoute, context = {}) {
    const newCoords = Array.isArray(newRoute?.coordinates) ? newRoute.coordinates : [];
    const originalCoords = Array.isArray(originalRoute?.coordinates) ? originalRoute.coordinates : [];
    const metrics = _routeDifferenceMetrics(newCoords, originalCoords, context);
    const totalDistance = Number(newRoute?.summary?.totalDistance || newRoute?.totalDistance || _routePolylineLength(newCoords));
    const originalDistance = Number(originalRoute?.summary?.totalDistance || originalRoute?.totalDistance || _routePolylineLength(originalCoords));
    const distanceDelta = Math.abs(totalDistance - originalDistance);
    const meaningful = !(
        metrics.overallMeanDeviationM < 8
        && metrics.blockedMeanDeviationM < 12
        && metrics.blockedSamePathRatio > 0.78
        && distanceDelta < 60
    );
    return { meaningful, ...metrics, distanceDelta };
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

function _cloneRoute(route) {
    return route ? JSON.parse(JSON.stringify(route)) : route;
}

function _normalizeAlternativeRouteShape(route) {
    const cloned = _cloneRoute(route) || {};
    const totalDistance = Number(cloned?.summary?.totalDistance ?? cloned?.totalDistance ?? _routePolylineLength(cloned.coordinates));
    const totalTime = Number(cloned?.summary?.totalTime ?? cloned?.totalTime ?? 0);
    cloned.summary = {
        totalDistance: Number.isFinite(totalDistance) ? totalDistance : 0,
        totalTime: Number.isFinite(totalTime) ? totalTime : 0
    };
    if (!Array.isArray(cloned.instructions)) {
        cloned.instructions = [];
    }
    return cloned;
}

function _mergeAlternativeRoutes(firstRoute, secondRoute) {
    const first = _normalizeAlternativeRouteShape(firstRoute);
    const second = _normalizeAlternativeRouteShape(secondRoute);
    const firstCoords = Array.isArray(first.coordinates) ? first.coordinates : [];
    const secondCoords = Array.isArray(second.coordinates) ? second.coordinates : [];
    const mergedCoords = firstCoords.slice();
    secondCoords.forEach((point, index) => {
        if (index === 0 && mergedCoords.length > 0 && _segmentLengthMeters(mergedCoords[mergedCoords.length - 1], point) < 2) return;
        mergedCoords.push(point);
    });

    const firstInstructions = Array.isArray(first.instructions) ? first.instructions.map(item => ({ ...item })) : [];
    const secondInstructions = Array.isArray(second.instructions) ? second.instructions.map(item => ({ ...item })) : [];
    const indexOffset = Math.max(0, firstCoords.length - 1);
    const mergedInstructions = firstInstructions.concat(secondInstructions.map((instruction) => {
        const cloned = { ...instruction };
        if (Number.isFinite(Number(cloned.index))) cloned.index = Number(cloned.index) + indexOffset;
        return cloned;
    }));

    return _normalizeAlternativeRouteShape({
        coordinates: mergedCoords,
        summary: {
            totalDistance: Number(first.summary?.totalDistance || 0) + Number(second.summary?.totalDistance || 0),
            totalTime: Number(first.summary?.totalTime || 0) + Number(second.summary?.totalTime || 0)
        },
        instructions: mergedInstructions,
        totalDistance: Number(first.totalDistance || first.summary?.totalDistance || 0) + Number(second.totalDistance || second.summary?.totalDistance || 0),
        totalTime: Number(first.totalTime || first.summary?.totalTime || 0) + Number(second.totalTime || second.summary?.totalTime || 0),
        turnCount: Number(first.turnCount || 0) + Number(second.turnCount || 0)
    });
}

function _resolveRoutePoint(route, pointIndex) {
    if (!route || !Array.isArray(route.coordinates) || !Number.isFinite(Number(pointIndex))) return null;
    const index = Number(pointIndex);
    if (index < 0 || index >= route.coordinates.length) return null;
    const point = route.coordinates[index];
    if (!point) return null;
    return {
        lat: Number(point.lat),
        lng: Number(point.lng ?? point.lon)
    };
}

function _materializeInstructionLatLngs(route) {
    const instructions = Array.isArray(route?.instructions) ? route.instructions : [];
    return instructions.map((instruction) => {
        if (instruction?.latLng && Number.isFinite(Number(instruction.latLng.lat)) && Number.isFinite(Number(instruction.latLng.lng))) {
            return { ...instruction };
        }
        const point = _resolveRoutePoint(route, instruction?.index);
        return point ? { ...instruction, latLng: point } : { ...instruction };
    });
}

function _segmentBearingDeg(a, b) {
    if (!a || !b) return 0;
    const dx = (b.lng ?? b.lon) - (a.lng ?? a.lon);
    const dy = b.lat - a.lat;
    if (Math.abs(dx) < 1e-9 && Math.abs(dy) < 1e-9) return 0;
    let deg = Math.atan2(dy, dx) * 180 / Math.PI;
    if (deg < 0) deg += 360;
    return deg;
}

function _bearingDiffDeg(a, b) {
    const diff = Math.abs(a - b) % 360;
    return diff > 180 ? 360 - diff : diff;
}

function _compactDisplayCoords(coords) {
    if (!Array.isArray(coords) || coords.length < 2) return Array.isArray(coords) ? coords.slice() : [];
    const compacted = [coords[0]];
    for (let i = 1; i < coords.length; i++) {
        if (_segmentLengthMeters(compacted[compacted.length - 1], coords[i]) >= DISPLAY_SIMPLIFY_MIN_SEGMENT_M || i === coords.length - 1) {
            compacted.push(coords[i]);
        }
    }
    return compacted;
}

function _shouldDropDisplayVertex(prev, curr, next, destination) {
    if (!prev || !curr || !next) return false;
    const segIn = _segmentLengthMeters(prev, curr);
    const segOut = _segmentLengthMeters(curr, next);
    const direct = _segmentLengthMeters(prev, next);
    const pathLen = segIn + segOut;
    const angle = _turnAngleDeg(prev, curr, next);
    const progressRatio = pathLen > 0 ? direct / pathLen : 1;
    const shortTurn = segIn <= DISPLAY_SIMPLIFY_SHORT_SEGMENT_M || segOut <= DISPLAY_SIMPLIFY_SHORT_SEGMENT_M;
    const distPrevToDest = destination ? _segmentLengthMeters(prev, destination) : 0;
    const distCurrToDest = destination ? _segmentLengthMeters(curr, destination) : 0;
    const distNextToDest = destination ? _segmentLengthMeters(next, destination) : 0;
    const awayThenBack = destination
        ? (distCurrToDest > distPrevToDest + 3 && distCurrToDest > distNextToDest + 3)
        : false;

    if (shortTurn && angle >= DISPLAY_SIMPLIFY_UTURN_DEG) return true;
    if (shortTurn && angle >= DISPLAY_SIMPLIFY_SHARP_TURN_DEG && progressRatio <= DISPLAY_SIMPLIFY_PROGRESS_RATIO) return true;
    if (shortTurn && awayThenBack && angle >= 90) return true;
    if (Math.min(segIn, segOut) <= 12 && angle >= 85 && progressRatio <= 0.75) return true;
    return false;
}

function _pruneDisplayLoops(coords, destination) {
    if (!Array.isArray(coords) || coords.length < 3) return Array.isArray(coords) ? coords.slice() : [];
    let simplified = coords.slice();

    for (let pass = 0; pass < DISPLAY_SIMPLIFY_MAX_PASSES; pass++) {
        let changed = false;
        for (let i = 0; i < simplified.length - 2; i++) {
            let pathDistance = 0;
            for (let j = i + 1; j < simplified.length; j++) {
                pathDistance += _segmentLengthMeters(simplified[j - 1], simplified[j]);
                if (j <= i + 1 || pathDistance < DISPLAY_LOOP_PATH_MIN_M) continue;
                const revisitDistance = _segmentLengthMeters(simplified[i], simplified[j]);
                if (revisitDistance > DISPLAY_REVISIT_DISTANCE_M) continue;
                const startToDestination = destination ? _segmentLengthMeters(simplified[i], destination) : 0;
                const endToDestination = destination ? _segmentLengthMeters(simplified[j], destination) : 0;
                if (destination && endToDestination > startToDestination + DISPLAY_LOOP_DESTINATION_SLACK_M) continue;
                simplified.splice(i + 1, j - i - 1);
                changed = true;
                break;
            }
            if (changed) break;
        }
        if (!changed) break;
        simplified = _compactDisplayCoords(simplified);
    }

    return simplified;
}

function _mergeNearbyDisplayAnchors(route) {
    const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    if (coords.length < 2) return [];
    const rawAnchors = _buildDisplayAnchorIndices(route);
    if (rawAnchors.length === 0) return [];

    const merged = [rawAnchors[0]];
    for (let i = 1; i < rawAnchors.length - 1; i++) {
        const prevAnchorIndex = merged[merged.length - 1];
        const currentIndex = rawAnchors[i];
        const nextIndex = rawAnchors[i + 1];
        const currentPoint = coords[currentIndex];
        const prevPoint = coords[prevAnchorIndex];
        const nextPoint = coords[nextIndex];
        if (!currentPoint || !prevPoint || !nextPoint) {
            merged.push(currentIndex);
            continue;
        }
        const distFromPrev = _segmentLengthMeters(prevPoint, currentPoint);
        const distToNext = _segmentLengthMeters(currentPoint, nextPoint);
        if (distFromPrev <= DISPLAY_ANCHOR_MERGE_RADIUS_M || distToNext <= DISPLAY_ANCHOR_MERGE_RADIUS_M) {
            continue;
        }
        merged.push(currentIndex);
    }
    const lastAnchor = rawAnchors[rawAnchors.length - 1];
    if (merged[merged.length - 1] !== lastAnchor) merged.push(lastAnchor);
    return merged;
}

function _mergeDuplicateDisplaySegments(coords) {
    if (!Array.isArray(coords) || coords.length < 4) return Array.isArray(coords) ? coords.slice() : [];
    let simplified = coords.slice();

    for (let pass = 0; pass < DISPLAY_SIMPLIFY_MAX_PASSES; pass++) {
        let changed = false;
        for (let i = 0; i < simplified.length - 2; i++) {
            let pathDistance = 0;
            const baseBearing = _segmentBearingDeg(simplified[i], simplified[i + 1]);
            for (let j = i + 2; j < simplified.length - 1; j++) {
                pathDistance += _segmentLengthMeters(simplified[j - 1], simplified[j]);
                if (pathDistance < DISPLAY_DUPLICATE_SEGMENT_MIN_PATH_M) continue;

                const startDistance = _segmentLengthMeters(simplified[i], simplified[j]);
                const endDistance = _segmentLengthMeters(simplified[i + 1], simplified[j + 1]);
                if (startDistance > DISPLAY_DUPLICATE_SEGMENT_DISTANCE_M || endDistance > DISPLAY_DUPLICATE_SEGMENT_DISTANCE_M) continue;

                const candidateBearing = _segmentBearingDeg(simplified[j], simplified[j + 1]);
                if (_bearingDiffDeg(baseBearing, candidateBearing) > DISPLAY_DUPLICATE_SEGMENT_ANGLE_DEG) continue;

                const midpointA = {
                    lat: (simplified[i].lat + simplified[i + 1].lat) / 2,
                    lng: ((simplified[i].lng ?? simplified[i].lon) + (simplified[i + 1].lng ?? simplified[i + 1].lon)) / 2
                };
                const midpointB = {
                    lat: (simplified[j].lat + simplified[j + 1].lat) / 2,
                    lng: ((simplified[j].lng ?? simplified[j].lon) + (simplified[j + 1].lng ?? simplified[j + 1].lon)) / 2
                };
                if (_segmentLengthMeters(midpointA, midpointB) > DISPLAY_DUPLICATE_SEGMENT_DISTANCE_M) continue;

                simplified.splice(i + 1, j - i - 1);
                changed = true;
                break;
            }
            if (changed) break;
        }
        if (!changed) break;
        simplified = _compactDisplayCoords(simplified);
    }

    return simplified;
}

function _buildDisplayAnchorIndices(route) {
    const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    if (coords.length < 2) return [];
    const anchors = new Set([0, coords.length - 1]);
    const instructions = Array.isArray(route?.instructions) ? route.instructions : [];
    instructions.forEach((instruction) => {
        const index = Number(instruction?.index);
        if (Number.isFinite(index) && index > 0 && index < coords.length - 1) {
            anchors.add(index);
        }
    });
    return Array.from(anchors).sort((a, b) => a - b);
}

function _reconstructDisplayRoute(route) {
    const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    if (coords.length < 3) return coords.slice();

    const anchors = _mergeNearbyDisplayAnchors(route);
    const destination = coords[coords.length - 1];
    if (anchors.length < 2) {
        return _mergeDuplicateDisplaySegments(_pruneDisplayLoops(coords, destination));
    }

    const reconstructed = [];
    for (let i = 0; i < anchors.length - 1; i++) {
        const startIndex = anchors[i];
        const endIndex = anchors[i + 1];
        if (endIndex <= startIndex) continue;
        const slice = coords.slice(startIndex, endIndex + 1);
        const pruned = _pruneDisplayLoops(slice, destination);
        if (reconstructed.length === 0) {
            reconstructed.push(...pruned);
        } else if (pruned.length > 0) {
            reconstructed.push(...pruned.slice(1));
        }
    }

    const rebuilt = reconstructed.length >= 2 ? reconstructed : _pruneDisplayLoops(coords, destination);
    return _mergeDuplicateDisplaySegments(rebuilt);
}

function _simplifyRouteGeometryForDisplay(coords) {
    if (!Array.isArray(coords) || coords.length < 3) return Array.isArray(coords) ? coords.slice() : [];
    let simplified = _compactDisplayCoords(coords);
    const destination = simplified[simplified.length - 1];

    for (let pass = 0; pass < DISPLAY_SIMPLIFY_MAX_PASSES; pass++) {
        let changed = false;

        for (let i = 1; i < simplified.length - 2; i++) {
            const prev = simplified[i - 1];
            const curr = simplified[i];
            const next = simplified[i + 1];
            const segIn = _segmentLengthMeters(prev, curr);
            const segOut = _segmentLengthMeters(curr, next);
            const returnGap = _segmentLengthMeters(prev, next);
            const angle = _turnAngleDeg(prev, curr, next);
            if (segIn <= DISPLAY_SIMPLIFY_SHORT_SEGMENT_M
                    && segOut <= DISPLAY_SIMPLIFY_SHORT_SEGMENT_M
                    && angle >= DISPLAY_SIMPLIFY_UTURN_DEG
                    && returnGap <= DISPLAY_SIMPLIFY_RETURN_GAP_M) {
                simplified.splice(i, 1);
                changed = true;
                break;
            }
        }
        if (changed) {
            simplified = _compactDisplayCoords(simplified);
            continue;
        }

        for (let i = 1; i < simplified.length - 1; i++) {
            if (_shouldDropDisplayVertex(simplified[i - 1], simplified[i], simplified[i + 1], destination)) {
                simplified.splice(i, 1);
                changed = true;
                break;
            }
        }
        if (!changed) break;
        simplified = _compactDisplayCoords(simplified);
    }

    return simplified.length >= 2 ? simplified : coords.slice();
}

function _simplifyInitialRouteForClarity(coords) {
    if (!Array.isArray(coords) || coords.length < 3) return Array.isArray(coords) ? coords.slice() : [];
    const simplified = coords.slice();
    const start = simplified[0];
    let cumulative = 0;
    let anchorIndex = 1;

    for (let i = 1; i < simplified.length; i++) {
        cumulative += _segmentLengthMeters(simplified[i - 1], simplified[i]);
        const displacement = _segmentLengthMeters(start, simplified[i]);
        anchorIndex = i;
        if (cumulative >= MIN_INITIAL_CLARITY_SEGMENT_M && displacement >= MIN_INITIAL_CLARITY_SEGMENT_M * 0.8) {
            break;
        }
        if (cumulative >= MAX_INITIAL_CLARITY_WINDOW_M) {
            break;
        }
    }

    if (anchorIndex <= 1) return simplified;

    const merged = [simplified[0], simplified[anchorIndex], ...simplified.slice(anchorIndex + 1)];
    const compacted = [merged[0]];
    for (let i = 1; i < merged.length; i++) {
        if (_segmentLengthMeters(compacted[compacted.length - 1], merged[i]) >= 2 || i === merged.length - 1) {
            compacted.push(merged[i]);
        }
    }
    return compacted;
}

function _inferInitialInstructionFromCoords(coords) {
    if (!Array.isArray(coords) || coords.length < 2) return null;
    let walked = 0;
    for (let i = 1; i < coords.length - 1; i++) {
        walked += _segmentLengthMeters(coords[i - 1], coords[i]);
        const angle = _turnAngleDeg(coords[i - 1], coords[i], coords[i + 1]);
        if (angle >= SIGNIFICANT_INITIAL_TURN_DEG) {
            const ax = (coords[i].lng ?? coords[i].lon) - (coords[i - 1].lng ?? coords[i - 1].lon);
            const ay = coords[i].lat - coords[i - 1].lat;
            const bx = (coords[i + 1].lng ?? coords[i + 1].lon) - (coords[i].lng ?? coords[i].lon);
            const by = coords[i + 1].lat - coords[i].lat;
            const cross = (ax * by) - (ay * bx);
            const turnText = cross > 0 ? '左へ進む' : '右へ進む';
            return {
                _displayText: walked <= 25 ? `まずは${turnText}` : `まずは${Math.round(walked / 5) * 5}m先を${turnText.replace('進む', '')}`,
                distance: Math.max(walked, MIN_INITIAL_CLARITY_SEGMENT_M),
                latLng: { lat: coords[i].lat, lng: coords[i].lng ?? coords[i].lon },
                index: i
            };
        }
        if (walked > 60) break;
    }
    return {
        _displayText: 'まずはそのまま直進',
        distance: Math.max(_segmentLengthMeters(coords[0], coords[1]), MIN_INITIAL_CLARITY_SEGMENT_M),
        latLng: { lat: coords[Math.min(1, coords.length - 1)].lat, lng: coords[Math.min(1, coords.length - 1)].lng ?? coords[Math.min(1, coords.length - 1)].lon },
        index: Math.min(1, coords.length - 1)
    };
}

function _recordDisplayPipelineStage(meta, stageName, beforeCount, afterCount) {
    if (!meta) return;
    meta.stages.push({
        stage: stageName,
        beforeCount,
        afterCount
    });
    console.log(`[BlockAhead][display] ${meta.context} ${stageName}: ${beforeCount} -> ${afterCount}`);
}

function _runDisplayRoutePipeline(route, contextLabel = 'generic') {
    const startedAt = _perfNowMs();
    const cloned = _cloneRoute(route);
    if (!cloned || !Array.isArray(cloned.coordinates) || cloned.coordinates.length < 2) return cloned;

    const pipelineMeta = {
        context: contextLabel,
        stages: []
    };

    const rawCount = cloned.coordinates.length;
    cloned.instructions = _materializeInstructionLatLngs(cloned);
    _recordDisplayPipelineStage(pipelineMeta, 'materialize-anchors', rawCount, cloned.coordinates.length);

    const reconstructed = _reconstructDisplayRoute(cloned);
    _recordDisplayPipelineStage(pipelineMeta, 'reconstruct-main-path', cloned.coordinates.length, reconstructed.length);
    cloned.coordinates = reconstructed;

    const mergedAnchorsCount = _mergeNearbyDisplayAnchors(cloned).length;
    _recordDisplayPipelineStage(
        pipelineMeta,
        'merge-nearby-anchors',
        Array.isArray(cloned.instructions) ? cloned.instructions.length : 0,
        mergedAnchorsCount
    );

    const deduped = _mergeDuplicateDisplaySegments(cloned.coordinates);
    _recordDisplayPipelineStage(pipelineMeta, 'merge-duplicate-segments', cloned.coordinates.length, deduped.length);
    cloned.coordinates = deduped;

    const loopPruned = _pruneDisplayLoops(cloned.coordinates, cloned.coordinates[cloned.coordinates.length - 1]);
    _recordDisplayPipelineStage(pipelineMeta, 'remove-loops-and-spurs', cloned.coordinates.length, loopPruned.length);
    cloned.coordinates = loopPruned;

    const simplified = _simplifyRouteGeometryForDisplay(cloned.coordinates);
    _recordDisplayPipelineStage(pipelineMeta, 'simplify-geometry', cloned.coordinates.length, simplified.length);
    cloned.coordinates = simplified;

    const clarityAdjusted = _simplifyInitialRouteForClarity(cloned.coordinates);
    _recordDisplayPipelineStage(pipelineMeta, 'apply-initial-clarity', cloned.coordinates.length, clarityAdjusted.length);
    cloned.coordinates = clarityAdjusted;

    const firstInstruction = _inferInitialInstructionFromCoords(cloned.coordinates);
    const existingInstructions = Array.isArray(cloned.instructions) ? cloned.instructions.slice() : [];
    if (firstInstruction) {
        if (existingInstructions.length > 0 && String(existingInstructions[0]?._displayText || existingInstructions[0]?.text || '').includes(firstInstruction._displayText)) {
            cloned.instructions = existingInstructions;
        } else {
            cloned.instructions = [firstInstruction, ...existingInstructions];
        }
    } else {
        cloned.instructions = existingInstructions;
    }
    cloned._displayPipeline = pipelineMeta;
    cloned._displayPipeline.context = contextLabel;
    if (_blockAheadPerfMetrics) {
        if (!Array.isArray(_blockAheadPerfMetrics.displayPipelineRuns)) {
            _blockAheadPerfMetrics.displayPipelineRuns = [];
        }
        _blockAheadPerfMetrics.displayPipelineRuns.push({
            context: contextLabel,
            stages: pipelineMeta.stages.map(stage => stage.stage)
        });
    }
    _recordBlockAheadTiming('routeReconstruction', _perfNowMs() - startedAt);
    return cloned;
}

function _clarifyRouteForNavigation(route, contextLabel = 'generic') {
    return _runDisplayRoutePipeline(route, contextLabel);
}

function _selectSingleRouteBundle(routes, selectedRouteIndex, routeColors, formatter, transportMode, contextLabel = 'block-ahead-final') {
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
    const selectedRoute = _clarifyRouteForNavigation(routeList[safeIndex], contextLabel);
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
const _pedestrianSafetyContextCache = new Map();

function _clearBlockAheadLayer() {
    if (_blockAheadLayer && typeof map !== 'undefined') {
        map.removeLayer(_blockAheadLayer);
    }
    _blockAheadLayer = null;
}

// ── OSRM 代替ルート一括取得 ─────────────────────────────────────────────
async function _fetchOsrmAlternatives(from, to, maxAlts = 3, contextLabel = 'alternatives') {
    const transportMode = document.getElementById('transportMode')?.value ?? 'walking';
    const profile    = transportMode === 'walking' ? 'walking' : 'driving';
    const serviceUrl = OSRM_SERVICE_URLS[profile];
    const coordStr   = `${from.lng ?? from.lon},${from.lat};${to.lng ?? to.lon},${to.lat}`;
    const safeAlternatives = Math.max(1, Math.min(BLOCK_OSRM_ALTERNATIVES, Number(maxAlts) || BLOCK_OSRM_ALTERNATIVES));
    const url = `${serviceUrl}/${profile}/${coordStr}?overview=full&geometries=geojson&alternatives=${safeAlternatives}&steps=true`;
    const startedAt = _perfNowMs();
    try {
        const res = await fetch(url);
        if (!res.ok) {
            console.warn(`[BlockAhead][${contextLabel}] fetch failed status=${res.status} alts=${safeAlternatives}`);
            _recordBlockAheadRejectReason(`${contextLabel}-route-${res.status}`);
            return [];
        }
        const data = await res.json();
        if (data.code !== 'Ok' || !Array.isArray(data.routes) || data.routes.length === 0) {
            _recordBlockAheadRejectReason(`${contextLabel}-route-empty`);
            return [];
        }
        return data.routes.map(r => _normalizeAlternativeRouteShape(_fetchOsrmAlternativesResultToRoute(r)));
    } catch (e) {
        console.warn('[BlockAhead][alternatives] fetch error:', e);
        return [];
    } finally {
        const durationMs = _perfNowMs() - startedAt;
        _recordBlockAheadTiming('osrmEval', durationMs);
        console.log(`[BlockAhead][timing] osrm alternatives ${Math.round(durationMs)}ms`);
    }
}

async function _fetchOsrmRouteThroughWaypoints(waypoints) {
    const transportMode = document.getElementById('transportMode')?.value ?? 'walking';
    const profile = transportMode === 'walking' ? 'walking' : 'driving';
    const serviceUrl = OSRM_SERVICE_URLS[profile];
    const coordStr = (Array.isArray(waypoints) ? waypoints : [])
        .map(wp => `${wp.lng ?? wp.lon},${wp.lat}`)
        .join(';');
    const url = `${serviceUrl}/${profile}/${coordStr}?overview=full&geometries=geojson&alternatives=false&steps=true`;
    const startedAt = _perfNowMs();
    try {
        const res = await fetch(url);
        if (!res.ok) return null;
        const data = await res.json();
        if (data.code !== 'Ok' || !Array.isArray(data.routes) || data.routes.length === 0) return null;
        return _normalizeAlternativeRouteShape(_fetchOsrmAlternativesResultToRoute(data.routes[0]));
    } catch (error) {
        console.warn('[BlockAhead][escape] fetch error:', error);
        return null;
    } finally {
        const durationMs = _perfNowMs() - startedAt;
        _recordBlockAheadTiming('osrmEval', durationMs);
        console.log(`[BlockAhead][timing] osrm escape ${Math.round(durationMs)}ms`);
    }
}

function _fetchOsrmAlternativesResultToRoute(r) {
    const coordinates = r.geometry.coordinates.map(c => ({ lat: c[1], lng: c[0] }));
    const steps = Array.isArray(r.legs)
        ? r.legs.flatMap(leg => Array.isArray(leg.steps) ? leg.steps : [])
        : [];
    const turnSteps = steps.filter(step => {
        const type = step?.maneuver?.type;
        return type && type !== 'depart' && type !== 'arrive';
    });
    const instructions = steps.map((step) => {
        const location = Array.isArray(step?.maneuver?.location) ? step.maneuver.location : null;
        return {
            text: _describeOsrmStep(step),
            distance: Number(step?.distance) || 0,
            latLng: location && location.length >= 2
                ? { lat: Number(location[1]), lng: Number(location[0]) }
                : null
        };
    }).filter(instruction => instruction && instruction.text);
    return {
        coordinates,
        summary: {
            totalDistance: r.distance,
            totalTime: r.duration
        },
        instructions,
        totalDistance: r.distance,
        totalTime: r.duration,
        turnCount: turnSteps.length
    };
}

function _describeOsrmStep(step) {
    const type = String(step?.maneuver?.type || '');
    const modifier = String(step?.maneuver?.modifier || '');
    const roadName = String(step?.name || '').trim();
    let text = '';
    if (type === 'depart') {
        text = '出発して進む';
    } else if (type === 'arrive') {
        text = '目的地に到着';
    } else if (modifier === 'left') {
        text = '左へ進む';
    } else if (modifier === 'right') {
        text = '右へ進む';
    } else if (modifier === 'slight left') {
        text = 'やや左へ進む';
    } else if (modifier === 'slight right') {
        text = 'やや右へ進む';
    } else if (modifier === 'sharp left') {
        text = '鋭く左へ進む';
    } else if (modifier === 'sharp right') {
        text = '鋭く右へ進む';
    } else if (modifier === 'straight') {
        text = 'そのまま直進';
    } else if (type === 'roundabout') {
        text = 'ロータリーを進む';
    } else {
        text = 'そのまま進む';
    }
    return roadName ? `${text} (${roadName})` : text;
}

function _buildBlockAheadFormatter() {
    return {
        formatInstruction(instruction) {
            return String(instruction?._displayText || instruction?.displayText || instruction?.text || '');
        },
        formatDistance(distance) {
            const value = Number(distance);
            if (!Number.isFinite(value)) return '';
            return value < 1000 ? `${Math.round(value)}m` : `${(value / 1000).toFixed(1)}km`;
        }
    };
}

function _compareRouteGeometries(sourceCoords, targetCoords, label) {
    const source = Array.isArray(sourceCoords) ? sourceCoords : [];
    const target = Array.isArray(targetCoords) ? targetCoords : [];
    const samples = _sampleRoutePoints(source, 20);
    const distances = samples.map(point => _distancePointToRoute(point, target)).filter(Number.isFinite);
    const meanDeviationM = distances.length
        ? distances.reduce((sum, value) => sum + value, 0) / distances.length
        : Infinity;
    const maxDeviationM = distances.length ? Math.max(...distances) : Infinity;
    console.log(
        `[BlockAhead][compare] ${label}: sourcePts=${source.length} targetPts=${target.length} ` +
        `mean=${Math.round(meanDeviationM)}m max=${Math.round(maxDeviationM)}m`
    );
    return { meanDeviationM, maxDeviationM, sourceCount: source.length, targetCount: target.length };
}

// ── 代替ルートから逸脱アンカー点を抽出 ─────────────────────────────────
// searchWindowM 以内で original から最も離れた点を返す（LRM 強制経由点として使用）
function _findDeviationAnchor(altCoords, originalCoords, searchWindowM = 250) {
    if (!Array.isArray(altCoords) || altCoords.length < 2
            || !Array.isArray(originalCoords) || originalCoords.length < 2) return null;
    let walked = 0;
    let maxDev = 0;
    let anchor = null;
    for (let i = 1; i < altCoords.length; i++) {
        walked += _segmentLengthMeters(altCoords[i - 1], altCoords[i]);
        if (walked > searchWindowM) break;
        const dev = _distancePointToRoute(altCoords[i], originalCoords);
        if (Number.isFinite(dev) && dev > maxDev) {
            maxDev = dev;
            anchor = altCoords[i];
        }
    }
    return anchor;
}

// 「この先を避けて再ルート」— 前方ブロック区間を避ける代替ルートを選択
async function blockAheadAndReroute() {
    const rerouteStartedAt = _perfNowMs();
    _blockAheadPerfMetrics = {
        startedAt: rerouteStartedAt,
        alternativesEvaluated: 0,
        rejectReasons: {},
        stages: []
    };
    // ── ガード ────────────────────────────────────────────────────────────
    if (!navActiveRoute || !Array.isArray(navActiveRoute.coordinates)) {
        console.warn('[BlockAhead] no active route');
        _blockAheadPerfMetrics = null;
        return;
    }
    if (!navDestination) {
        console.warn('[BlockAhead] no destination');
        _blockAheadPerfMetrics = null;
        return;
    }
    if (!currentLocation) {
        console.warn('[BlockAhead] no current location');
        _blockAheadPerfMetrics = null;
        return;
    }
    if (navBlockAheadInProgress) {
        console.log('[BlockAhead] already in progress');
        _blockAheadPerfMetrics = null;
        return;
    }

    navBlockAheadInProgress = true;
    const mySeq = ++_blockAheadSeq; // このリクエストのトークン
    _updateNavUI();
    _showNavBanner('🚧 前方ルートを回避してルートを再計算しています...', 'info');
    console.log('[BlockAhead] start seq=' + mySeq);

    const coords = navActiveRoute.coordinates;
    const originalRouteSnapshot = JSON.parse(JSON.stringify(navActiveRoute));
    // ── 現在地をルート上に投影 ─────────────────────────────────────────────
    const projection = _navFindClosestOnRoute(coords, currentLocation.lat, currentLocation.lon);
    if (!projection) {
        console.warn('[BlockAhead] projection failed');
        navBlockAheadInProgress = false;
        _updateNavUI();
        _showNavBanner('⚠ 現在地をルート上に特定できませんでした', 'danger', 4000);
        _blockAheadLastTiming = { ..._blockAheadPerfMetrics, totalMs: _perfNowMs() - rerouteStartedAt, status: 'projection-failed' };
        console.log('[BlockAhead][timing][total]', _blockAheadLastTiming);
        _blockAheadPerfMetrics = null;
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
        _blockAheadLastTiming = { ..._blockAheadPerfMetrics, totalMs: _perfNowMs() - rerouteStartedAt, status: 'off-route-too-far' };
        console.log('[BlockAhead][timing][total]', _blockAheadLastTiming);
        _blockAheadPerfMetrics = null;
        return;
    }

    // ── 前方コリドーを blocked area として構築 ────────────────────────────
    const blockStart = _walkAlongRoute(coords, projection, BLOCK_AHEAD_START_METERS);
    const blockEnd   = _walkAlongRoute(coords, projection, BLOCK_AHEAD_END_METERS);
    console.log('[BlockAhead] blocked segment:', blockStart, '->', blockEnd);

    // ── 補助線は表示しない。既存の一時描画が残っていればクリアだけ行う ─────
    _clearBlockAheadLayer();
    const defaultBufMid = {
        lat: (blockStart.lat + blockEnd.lat) / 2,
        lng: (blockStart.lng + blockEnd.lng) / 2
    };
    const defaultOverlapRadius = Math.max(BLOCK_MIN_SLIT_RADIUS_M + 6, (BLOCK_BUFFER_METERS * BLOCK_MAIN_SLIT_RADIUS_RATIO) + 8);

    const startWp = { lat: currentLocation.lat, lng: currentLocation.lon };
    const destWp  = { lat: navDestination.lat,  lng: navDestination.lon  };
    let alternatives = [];
    let activeBlockedArea = null;
    let selectedStage = null;
    let nonBlocked = [];
    let meaningful = [];
    let lastStageResult = null;
    let dangerousCrossingRejected = false;

    for (const stage of BLOCK_STAGE_CONFIGS) {
        const stageStartedAt = _perfNowMs();
        const stageBlockedArea = _buildBlockedArea(coords, projection, {
            startM: stage.startM,
            endM: stage.endM,
            backwardM: stage.backwardM,
            baseRadiusM: stage.baseRadiusM,
            intersectionBufferM: stage.intersectionBufferM,
            logKey: stage.key
        });
        const stageBufStart = _walkAlongRouteRelative(coords, projection, Math.max(0, stage.startM));
        const stageBufEnd = _walkAlongRoute(coords, projection, stage.endM);
        const stageBufMid = {
            lat: (stageBufStart.lat + stageBufEnd.lat) / 2,
            lng: (stageBufStart.lng + stageBufEnd.lng) / 2
        };
        const stageOverlapRadius = stageBlockedArea?.overlapRadiusM || (stage.baseRadiusM + 15);
        const stageBroadOverlapRadius = stageBlockedArea?.broadOverlapRadiusM || (stage.baseRadiusM + 15);
        const stageAlternatives = await _fetchOsrmAlternatives(startWp, destWp, stage.alternativeCount, stage.key);
        _blockAheadPerfMetrics.alternativesEvaluated += stageAlternatives.length;

        if (_blockAheadSeq !== mySeq) {
            navBlockAheadInProgress = false;
            _blockAheadPerfMetrics = null;
            return;
        }

        const stageBlockedPassed = stageAlternatives.filter(route => {
            const blockedStats = _routeBlockedAreaStats(route.coordinates, stageBlockedArea);
            const overlap = _calcBlockOverlapRatio(route.coordinates, stageBufMid.lat, stageBufMid.lng, stageOverlapRadius);
            const overlapBroad = _calcBlockOverlapRatio(route.coordinates, stageBufMid.lat, stageBufMid.lng, stageBroadOverlapRadius);
            const branchSignals = _assessBranchLikeRoute(route, coords);
            const branchNearPenaltyMode = _assessBranchNearPenaltyMode(blockedStats, overlap);
            const branchFastEligible = (stage.key === 'stage1' || stage.key === 'stage2')
                && branchSignals.branchLike
                && !branchNearPenaltyMode.actualIntersection
                && (!blockedStats.nearBlocked || branchNearPenaltyMode.eligible);
            console.log(
                `[BlockAhead][${stage.key}][alt] dist=${Math.round(route.totalDistance)}m overlap=${overlap.toFixed(2)} ` +
                `overlapBroad=${overlapBroad.toFixed(2)} ` +
                `strict=${blockedStats.strictOverlapRatio.toFixed(2)} near=${blockedStats.nearBlockedRatio.toFixed(2)} ` +
                `minDist=${Math.round(blockedStats.minDistanceToAreaM)}m branchLike=${branchSignals.branchLike} ` +
                `bearingDiff=${Math.round(branchSignals.bearingDiff)} lateral=${Math.round(branchSignals.lateralDivergenceM)}m`
            );
            route.__blockedStats = blockedStats;
            route.__overlap = overlap;
            route.__overlapBroad = overlapBroad;
            route.__branchLike = branchSignals.branchLike;
            route.__branchBearingDiff = branchSignals.bearingDiff;
            route.__branchLateralDivergenceM = branchSignals.lateralDivergenceM;
            route.__branchNearPenaltyMode = branchNearPenaltyMode.eligible;
            route.__branchPenalty = branchNearPenaltyMode.penalty;
            route.__branchFastEligible = branchFastEligible;
            return !branchNearPenaltyMode.actualIntersection
                && overlap < BLOCK_OVERLAP_REJECT
                && (!blockedStats.nearBlocked || branchNearPenaltyMode.eligible);
        });
        const stagePedestrianChecked = await Promise.all(stageBlockedPassed.map(async (route) => {
            const pedestrianSafety = await _evaluatePedestrianRouteSafety(route, `${stage.key}-candidate`);
            route.__pedestrianSafety = pedestrianSafety;
            if (!pedestrianSafety.safe) {
                dangerousCrossingRejected = true;
                _recordBlockAheadRejectReason('dangerous-crossing');
                console.log(`[BlockAhead][${stage.key}][alt] reject dangerous-crossing dist=${Math.round(route.totalDistance)}m`);
                return null;
            }
            return route;
        }));
        const stageNonBlocked = stagePedestrianChecked.filter(Boolean);

        const stageMeaningful = stageNonBlocked
            .filter(route => {
                const diff = _isMeaningfullyDifferentReroute(route, originalRouteSnapshot, {
                    bufMid: stageBufMid,
                    overlapRadius: stageOverlapRadius,
                    blockedArea: stageBlockedArea
                });
                route.__routeDiff = diff;
                return diff.meaningful;
            })
            .sort((a, b) => a.totalDistance - b.totalDistance);

        const branchFastPathCandidates = (stage.key === 'stage1' || stage.key === 'stage2')
            ? stageMeaningful
                .filter(route => route.__branchFastEligible)
                .sort((a, b) => {
                    const overlapDiff = Number(a.__overlap || 0) - Number(b.__overlap || 0);
                    if (overlapDiff !== 0) return overlapDiff;
                    const penaltyDiff = Number(a.__branchPenalty || 0) - Number(b.__branchPenalty || 0);
                    if (penaltyDiff !== 0) return penaltyDiff;
                    const lateralDiff = Number(b.__branchLateralDivergenceM || 0) - Number(a.__branchLateralDivergenceM || 0);
                    if (lateralDiff !== 0) return lateralDiff;
                    const bearingDiff = Number(b.__branchBearingDiff || 0) - Number(a.__branchBearingDiff || 0);
                    if (bearingDiff !== 0) return bearingDiff;
                    return a.totalDistance - b.totalDistance;
                })
            : [];

        const stageDurationMs = _perfNowMs() - stageStartedAt;
        const stageSummary = {
            key: stage.key,
            durationMs: stageDurationMs,
            alternatives: stageAlternatives.length,
            nonBlocked: stageNonBlocked.length,
            meaningful: stageMeaningful.length,
            branchFastPathCandidates: branchFastPathCandidates.length
        };
        if (stageAlternatives.length === 0) stageSummary.failureReason = `${stage.key}-route-empty`;
        _blockAheadPerfMetrics.stages.push(stageSummary);
        console.log(
            `[BlockAhead][${stage.key}] alternatives=${stageAlternatives.length} nonBlocked=${stageNonBlocked.length} ` +
            `meaningful=${stageMeaningful.length} branch-fast-path=${branchFastPathCandidates.length} ${Math.round(stageDurationMs)}ms`
        );
        if (stage.key === 'stage1' || stage.key === 'stage2') {
            if (branchFastPathCandidates.length > 0) {
                const top = branchFastPathCandidates[0];
                console.log(
                    `[BlockAhead][${stage.key}] branch-fast-path accepted ` +
                    `dist=${Math.round(top.totalDistance)}m overlap=${Number(top.__overlap || 0).toFixed(2)} ` +
                    `strict=${Number(top.__blockedStats?.strictOverlapRatio || 0).toFixed(2)} ` +
                    `near=${Number(top.__blockedStats?.nearBlockedRatio || 0).toFixed(2)} ` +
                    `branchLike=${!!top.__branchLike}`
                );
            } else {
                console.log(`[BlockAhead][${stage.key}] branch-fast-path none -> continue to escape fallback`);
            }
        }

        lastStageResult = {
            stage,
            blockedArea: stageBlockedArea,
            bufMid: stageBufMid,
            overlapRadius: stageOverlapRadius,
            alternatives: stageAlternatives,
            nonBlocked: stageNonBlocked,
            meaningful: stageMeaningful,
            branchFastPathCandidates
        };
        if (branchFastPathCandidates.length > 0) {
            selectedStage = stage;
            activeBlockedArea = stageBlockedArea;
            alternatives = stageAlternatives;
            nonBlocked = stageNonBlocked;
            meaningful = branchFastPathCandidates;
            break;
        }
        if (stageMeaningful.length > 0) {
            selectedStage = stage;
            activeBlockedArea = stageBlockedArea;
            alternatives = stageAlternatives;
            nonBlocked = stageNonBlocked;
            meaningful = stageMeaningful;
            break;
        }
    }

    if (!selectedStage && lastStageResult) {
        activeBlockedArea = lastStageResult.blockedArea;
        alternatives = lastStageResult.alternatives;
        nonBlocked = lastStageResult.nonBlocked;
        meaningful = lastStageResult.meaningful;
    }

    // ── 失敗共通ハンドラ ──────────────────────────────────────────────────
    const fail = (reason, bannerMsg, bannerType) => {
        navBlockAheadInProgress = false;
        _restoreBlockAheadOriginalRoute(originalRouteSnapshot);
        _clearBlockAheadLayer();
        _updateNavUI();
        _showNavBanner(bannerMsg, bannerType, 5000);
        const totalMs = _perfNowMs() - rerouteStartedAt;
        const summary = {
            status: reason,
            accepted: false,
            rejectReason: reason,
            totalMs,
            osrmMs: _blockAheadPerfMetrics?.osrmEval?.totalMs || 0,
            displayPipelineMs: 0,
            alternativesEvaluated: alternatives.length,
            nonBlockedCount: nonBlocked.length,
            attemptedStages: Array.isArray(_blockAheadPerfMetrics?.stages) ? _blockAheadPerfMetrics.stages.map(stage => stage.key) : []
        };
        _recordBlockAheadExecutionSummary(summary);
        _blockAheadLastTiming = { ..._blockAheadPerfMetrics, ...summary, totalMs, status: reason };
        console.log('[BlockAhead][timing][total]', _blockAheadLastTiming);
        _blockAheadPerfMetrics = null;
    };

    if (meaningful.length === 0 && activeBlockedArea) {
        const escapeLegPoints = await _generateEscapeLegPoints(coords, projection, activeBlockedArea);
        console.log(`[BlockAhead][escape-leg] candidates=${escapeLegPoints.length}`);
        if (escapeLegPoints.length > 0) {
            const escapeLegStartedAt = _perfNowMs();
            const legBlockedAreaBase = {
                ...activeBlockedArea,
                ignoreUntilM: Math.max(
                    BLOCK_ESCAPE_IGNORE_METERS,
                    (activeBlockedArea?.baseRadiusM || 0) + (activeBlockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS)
                )
            };
            const escapeLegResults = await Promise.all(escapeLegPoints.map(async (escapeLeg) => {
                console.log(
                    `[BlockAhead][escape-leg] try ${escapeLeg.label}: distance=${Math.round(escapeLeg.lateralM || 0)}m ` +
                    `type=${escapeLeg.nodeType || 'unknown'} score=${Number(escapeLeg.nodeScore || 0).toFixed(1)}`
                );
                const legRoute = await _fetchOsrmRouteThroughWaypoints([startWp, escapeLeg.point]);
                if (!legRoute) {
                    console.log(`[BlockAhead][escape-leg] reject ${escapeLeg.label}: leg-route-empty`);
                    return null;
                }
                const legBlockedArea = _buildSideSpecificEscapeBlockedArea(legBlockedAreaBase, escapeLeg.side, `escape-leg:${escapeLeg.label}`);
                const prefixCoords = _routeCoordsPrefix(legRoute.coordinates, BLOCK_ESCAPE_LEG_PREFIX_GATE_M);
                const suffixCoords = _routeCoordsSuffix(legRoute.coordinates, BLOCK_ESCAPE_LEG_PREFIX_GATE_M);
                const prefixStatsBefore = _routeBlockedAreaStats(prefixCoords, legBlockedAreaBase);
                const prefixStatsAfter = _routeBlockedAreaStats(prefixCoords, legBlockedArea);
                const suffixStats = _routeBlockedAreaStats(suffixCoords, activeBlockedArea);
                const legStats = prefixStatsAfter;
                const legExitDistance = _distancePointToBlockedArea(escapeLeg.point, activeBlockedArea, activeBlockedArea.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS);
                const legEndPoint = Array.isArray(legRoute.coordinates) && legRoute.coordinates.length > 0
                    ? legRoute.coordinates[legRoute.coordinates.length - 1]
                    : null;
                const legEndDistance = legEndPoint
                    ? _distancePointToBlockedArea(legEndPoint, activeBlockedArea, activeBlockedArea.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS)
                    : -Infinity;
                console.log(
                    `[BlockAhead][escape-leg] prefix ${escapeLeg.label}: routePrefix=${BLOCK_ESCAPE_LEG_PREFIX_GATE_M}m ` +
                    `overlap-before=${prefixStatsBefore.strictOverlapRatio.toFixed(2)} overlap-after=${prefixStatsAfter.strictOverlapRatio.toFixed(2)} ` +
                    `near-before=${prefixStatsBefore.nearBlockedRatio.toFixed(2)} near-after=${prefixStatsAfter.nearBlockedRatio.toFixed(2)}`
                );
                const prefixFailed = prefixStatsAfter.intersects || prefixStatsAfter.nearBlocked;
                const suffixFailed = suffixStats.intersects || suffixStats.nearBlocked;
                if (legExitDistance <= 0 || legEndDistance <= 0 || prefixFailed || suffixFailed) {
                    console.log(
                        `[BlockAhead][escape-leg] reject ${escapeLeg.label}: leg rejected ` +
                        `strict=${legStats.strictOverlapRatio.toFixed(2)} near=${legStats.nearBlockedRatio.toFixed(2)} ` +
                        `exit=${Math.round(legExitDistance)}m end=${Math.round(legEndDistance)}m ` +
                        `failurePart=${prefixFailed ? 'prefix' : (suffixFailed ? 'after-prefix' : 'exit')}`
                    );
                    return null;
                }
                console.log(
                    `[BlockAhead][escape-leg] accepted ${escapeLeg.label}: exit=${Math.round(legExitDistance)}m ` +
                    `end=${Math.round(legEndDistance)}m prefix=${BLOCK_ESCAPE_LEG_PREFIX_GATE_M}m`
                );
                const mainRoute = await _fetchOsrmRouteThroughWaypoints([escapeLeg.point, destWp]);
                if (!mainRoute) {
                    console.log(`[BlockAhead][escape-leg] reject ${escapeLeg.label}: main-route-empty`);
                    return null;
                }
                const blockedStats = _routeBlockedAreaStats(mainRoute.coordinates, activeBlockedArea);
                const escapeBufMid = lastStageResult?.bufMid || defaultBufMid;
                const escapeOverlapRadius = lastStageResult?.overlapRadius || defaultOverlapRadius;
                const overlap = _calcBlockOverlapRatio(mainRoute.coordinates, escapeBufMid.lat, escapeBufMid.lng, escapeOverlapRadius);
                const nearPenaltyMode = _assessEscapeNearPenaltyMode(blockedStats, overlap);
                const overlapHard = overlap >= BLOCK_OVERLAP_REJECT;
                const strictThresholdExceeded = !!nearPenaltyMode.strictThresholdExceeded;
                const actualIntersectionDetected = !!nearPenaltyMode.actualIntersectionDetected;
                const nearOnlyReject = !nearPenaltyMode.eligible
                    && blockedStats.nearBlocked
                    && !actualIntersectionDetected
                    && !strictThresholdExceeded
                    && !overlapHard;
                const hardReject = actualIntersectionDetected
                    || overlapHard
                    || strictThresholdExceeded
                    || nearOnlyReject;
                _logEscapeNearPenaltyDecision(`[BlockAhead][escape-leg][debug] ${escapeLeg.label}:`, {
                    holdWaypointMode: false,
                    nearPenaltyMode,
                    rejectReason: hardReject
                        ? _escapeRejectReason(nearPenaltyMode, { actualIntersectionDetected, overlapHard, strictThresholdExceeded, nearOnlyReject })
                        : 'accepted'
                });
                if (hardReject) {
                    console.log(
                        `[BlockAhead][escape-leg] reject ${escapeLeg.label}: main-route blocked strict=${blockedStats.strictOverlapRatio.toFixed(2)} ` +
                        `near=${blockedStats.nearBlockedRatio.toFixed(2)} overlap=${overlap.toFixed(2)} ` +
                        `nearPenaltyMode=${nearPenaltyMode.eligible} nearPenalty=${Number.isFinite(nearPenaltyMode.penalty) ? nearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
                        `acceptedByNearPenaltyMode=${nearPenaltyMode.eligible && blockedStats.nearBlocked}`
                    );
                    return null;
                }
                const pedestrianSafety = await _evaluatePedestrianRouteSafety(mainRoute, `escape-leg:${escapeLeg.label}`);
                if (!pedestrianSafety.safe) {
                    dangerousCrossingRejected = true;
                    _recordBlockAheadRejectReason('dangerous-crossing');
                    console.log(`[BlockAhead][escape-leg] reject ${escapeLeg.label}: dangerous-crossing`);
                    return null;
                }
                console.log(
                    `[BlockAhead][escape-leg] main-route accepted ${escapeLeg.label}: ` +
                    `strict=${blockedStats.strictOverlapRatio.toFixed(2)} near=${blockedStats.nearBlockedRatio.toFixed(2)} ` +
                    `overlap=${overlap.toFixed(2)} nearPenaltyMode=${nearPenaltyMode.eligible} ` +
                    `nearPenalty=${Number.isFinite(nearPenaltyMode.penalty) ? nearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
                    `acceptedByNearPenaltyMode=${nearPenaltyMode.eligible && blockedStats.nearBlocked}`
                );
                const mergedRoute = _mergeAlternativeRoutes(legRoute, mainRoute);
                const diff = _isMeaningfullyDifferentReroute(mergedRoute, originalRouteSnapshot, {
                    bufMid: lastStageResult?.bufMid || defaultBufMid,
                    overlapRadius: lastStageResult?.overlapRadius || defaultOverlapRadius,
                    blockedArea: activeBlockedArea
                });
                if (!diff.meaningful) {
                    console.log(`[BlockAhead][escape-leg] reject ${escapeLeg.label}: no-change`);
                    return null;
                }
                mergedRoute.__routeDiff = diff;
                mergedRoute.__blockedStats = blockedStats;
                mergedRoute.__escapeLabel = escapeLeg.label;
                mergedRoute.__escapeLegDistance = escapeLeg.lateralM;
                mergedRoute.__escapeExitDistanceM = legExitDistance;
                mergedRoute.__escapeNodeType = escapeLeg.nodeType;
                mergedRoute.__escapeNodeScore = escapeLeg.nodeScore;
                mergedRoute.__distanceTierM = escapeLeg.distanceTierM;
                mergedRoute.__escapeDepthKind = escapeLeg.depthKind || 'entrance';
                mergedRoute.__escapeMainPenalty = nearPenaltyMode.penalty;
                mergedRoute.__escapeNearPenaltyMode = nearPenaltyMode.eligible;
                mergedRoute.__escapeOverlap = overlap;
                mergedRoute.__escapeStrict = Number(blockedStats.strictOverlapRatio || 0);
                mergedRoute.__escapeNear = Number(blockedStats.nearBlockedRatio || 0);
                mergedRoute.__acceptedByHoldWaypointMode = false;
                mergedRoute.__pedestrianSafety = pedestrianSafety;
                return mergedRoute;
            }));
            const validEscapeLegRoutes = escapeLegResults.filter(Boolean).sort((a, b) => {
                const overlapDiff = Number(a.__escapeOverlap || 0) - Number(b.__escapeOverlap || 0);
                if (overlapDiff !== 0) return overlapDiff;
                const strictDiff = Number(a.__escapeStrict || 0) - Number(b.__escapeStrict || 0);
                if (strictDiff !== 0) return strictDiff;
                const penaltyDiff = Number(a.__escapeMainPenalty || 0) - Number(b.__escapeMainPenalty || 0);
                if (penaltyDiff !== 0) return penaltyDiff;
                const exitDiff = Number(b.__escapeExitDistanceM || 0) - Number(a.__escapeExitDistanceM || 0);
                if (exitDiff !== 0) return exitDiff;
                const depthDiff = Number(b.depthRank || _escapeDepthRank(b.__escapeDepthKind)) - Number(a.depthRank || _escapeDepthRank(a.__escapeDepthKind));
                if (depthDiff !== 0) return depthDiff;
                const scoreDiff = Number(b.__escapeNodeScore || 0) - Number(a.__escapeNodeScore || 0);
                if (scoreDiff !== 0) return scoreDiff;
                return a.totalDistance - b.totalDistance;
            });
            const escapeLegDurationMs = _perfNowMs() - escapeLegStartedAt;
            _blockAheadPerfMetrics.stages.push({
                key: 'escape-leg',
                durationMs: escapeLegDurationMs,
                alternatives: escapeLegPoints.length,
                nonBlocked: validEscapeLegRoutes.length,
                meaningful: validEscapeLegRoutes.length
            });
            console.log(`[BlockAhead][escape-leg] valid=${validEscapeLegRoutes.length}/${escapeLegPoints.length} ${Math.round(escapeLegDurationMs)}ms`);
            if (validEscapeLegRoutes.length > 0) {
                console.log(
                    `[BlockAhead][escape-leg] selected distance=${Math.round(validEscapeLegRoutes[0].__escapeLegDistance || 0)}m ` +
                    `exit=${Math.round(validEscapeLegRoutes[0].__escapeExitDistanceM || 0)}m ` +
                    `tier=${validEscapeLegRoutes[0].__distanceTierM || Math.round(validEscapeLegRoutes[0].__escapeLegDistance || 0)}m ` +
                    `depth=${validEscapeLegRoutes[0].__escapeDepthKind || 'entrance'} ` +
                    `node=${validEscapeLegRoutes[0].__escapeLabel} type=${validEscapeLegRoutes[0].__escapeNodeType || 'unknown'} ` +
                    `score=${Number(validEscapeLegRoutes[0].__escapeNodeScore || 0).toFixed(1)} ` +
                    `overlap=${Number(validEscapeLegRoutes[0].__escapeOverlap || 0).toFixed(2)} ` +
                    `strict=${Number(validEscapeLegRoutes[0].__escapeStrict || 0).toFixed(2)} ` +
                    `near=${Number(validEscapeLegRoutes[0].__escapeNear || 0).toFixed(2)} ` +
                    `acceptedByHoldWaypointMode=false route=${Math.round(validEscapeLegRoutes[0].totalDistance)}m`
                );
                selectedStage = { key: 'escape-leg' };
                alternatives = validEscapeLegRoutes;
                nonBlocked = validEscapeLegRoutes;
                meaningful = validEscapeLegRoutes;
                console.log('[BlockAhead][escape-leg] road-node fallback succeeded');
            } else {
                _recordBlockAheadRejectReason('escape-leg-route-blocked');
            }
        } else {
            _recordBlockAheadRejectReason('escape-leg-snap-empty');
        }
    }

    if (meaningful.length === 0 && activeBlockedArea) {
        const escapePoints = await _generateEscapePoints(coords, projection, activeBlockedArea);
        console.log(`[BlockAhead][escape] candidates=${escapePoints.length}`);
        if (escapePoints.length > 0) {
            const escapeStartedAt = _perfNowMs();
            const escapeResults = await Promise.all(escapePoints.map(async (escape) => {
                const useHoldWaypointMode = !!escape.holdWaypoint && _escapeDepthRank(escape.depthKind) > 0;
                const waypoints = useHoldWaypointMode
                    ? [startWp, escape.holdWaypoint, escape.point, destWp]
                    : [startWp, escape.point, destWp];
                console.log(
                    `[BlockAhead][escape] try ${escape.label}: tier=${escape.distanceTierM || '-'} depth=${escape.depthKind || 'entrance'} ` +
                    `holdWaypointMode=${useHoldWaypointMode} score=${Number(escape.nodeScore || 0).toFixed(1)}`
                );
                const route = await _fetchOsrmRouteThroughWaypoints(waypoints);
                if (!route) {
                    console.log(`[BlockAhead][escape] reject ${escape.label}: route-empty holdWaypointMode=${useHoldWaypointMode}`);
                    return null;
                }
                const blockedStats = _routeBlockedAreaStats(route.coordinates, activeBlockedArea);
                const escapeBufMid = lastStageResult?.bufMid || defaultBufMid;
                const escapeOverlapRadius = lastStageResult?.overlapRadius || defaultOverlapRadius;
                const overlap = _calcBlockOverlapRatio(route.coordinates, escapeBufMid.lat, escapeBufMid.lng, escapeOverlapRadius);
                const nearPenaltyMode = _assessEscapeNearPenaltyMode(blockedStats, overlap);
                const overlapHard = overlap >= BLOCK_OVERLAP_REJECT;
                const strictThresholdExceeded = !!nearPenaltyMode.strictThresholdExceeded;
                const actualIntersectionDetected = !!nearPenaltyMode.actualIntersectionDetected;
                const nearOnlyReject = !nearPenaltyMode.eligible
                    && blockedStats.nearBlocked
                    && !actualIntersectionDetected
                    && !strictThresholdExceeded
                    && !overlapHard;
                const hardReject = actualIntersectionDetected
                    || overlapHard
                    || strictThresholdExceeded
                    || nearOnlyReject;
                _logEscapeNearPenaltyDecision(`[BlockAhead][escape][debug] ${escape.label}:`, {
                    holdWaypointMode: useHoldWaypointMode,
                    nearPenaltyMode,
                    rejectReason: hardReject
                        ? _escapeRejectReason(nearPenaltyMode, { actualIntersectionDetected, overlapHard, strictThresholdExceeded, nearOnlyReject })
                        : 'accepted'
                });
                if (hardReject) {
                    console.log(
                        `[BlockAhead][escape] reject ${escape.label}: blocked strict=${blockedStats.strictOverlapRatio.toFixed(2)} ` +
                        `near=${blockedStats.nearBlockedRatio.toFixed(2)} overlap=${overlap.toFixed(2)} ` +
                        `nearPenaltyMode=${nearPenaltyMode.eligible} nearPenalty=${Number.isFinite(nearPenaltyMode.penalty) ? nearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
                        `acceptedByNearPenaltyMode=${nearPenaltyMode.eligible && blockedStats.nearBlocked} ` +
                        `holdWaypointMode=${useHoldWaypointMode}`
                    );
                    return null;
                }
                const pedestrianSafety = await _evaluatePedestrianRouteSafety(route, `escape:${escape.label}`);
                if (!pedestrianSafety.safe) {
                    dangerousCrossingRejected = true;
                    _recordBlockAheadRejectReason('dangerous-crossing');
                    console.log(`[BlockAhead][escape] reject ${escape.label}: dangerous-crossing`);
                    return null;
                }
                console.log(
                    `[BlockAhead][escape] accepted ${escape.label}: strict=${blockedStats.strictOverlapRatio.toFixed(2)} ` +
                    `near=${blockedStats.nearBlockedRatio.toFixed(2)} overlap=${overlap.toFixed(2)} ` +
                    `nearPenaltyMode=${nearPenaltyMode.eligible} nearPenalty=${Number.isFinite(nearPenaltyMode.penalty) ? nearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
                    `acceptedByNearPenaltyMode=${nearPenaltyMode.eligible && blockedStats.nearBlocked} ` +
                    `holdWaypointMode=${useHoldWaypointMode}`
                );
                const diff = _isMeaningfullyDifferentReroute(route, originalRouteSnapshot, {
                    bufMid: lastStageResult?.bufMid || defaultBufMid,
                    overlapRadius: lastStageResult?.overlapRadius || defaultOverlapRadius,
                    blockedArea: activeBlockedArea
                });
                if (!diff.meaningful) {
                    console.log(`[BlockAhead][escape] reject ${escape.label}: no-change`);
                    return null;
                }
                route.__routeDiff = diff;
                route.__blockedStats = blockedStats;
                route.__escapeLabel = escape.label;
                route.__escapeNodeType = escape.nodeType;
                route.__escapeNodeScore = escape.nodeScore;
                route.__distanceTierM = escape.distanceTierM;
                route.__escapeDepthKind = escape.depthKind || 'entrance';
                route.__escapeMainPenalty = nearPenaltyMode.penalty;
                route.__escapeNearPenaltyMode = nearPenaltyMode.eligible;
                route.__escapeExitDistanceM = Number(escape.blockedDistanceM || 0);
                route.__escapeOverlap = overlap;
                route.__escapeStrict = Number(blockedStats.strictOverlapRatio || 0);
                route.__escapeNear = Number(blockedStats.nearBlockedRatio || 0);
                route.__acceptedByHoldWaypointMode = useHoldWaypointMode;
                route.__pedestrianSafety = pedestrianSafety;
                return route;
            }));
            const validEscapeRoutes = escapeResults.filter(Boolean).sort((a, b) => {
                const overlapDiff = Number(a.__escapeOverlap || 0) - Number(b.__escapeOverlap || 0);
                if (overlapDiff !== 0) return overlapDiff;
                const strictDiff = Number(a.__escapeStrict || 0) - Number(b.__escapeStrict || 0);
                if (strictDiff !== 0) return strictDiff;
                const penaltyDiff = Number(a.__escapeMainPenalty || 0) - Number(b.__escapeMainPenalty || 0);
                if (penaltyDiff !== 0) return penaltyDiff;
                const exitDiff = Number(b.__escapeExitDistanceM || 0) - Number(a.__escapeExitDistanceM || 0);
                if (exitDiff !== 0) return exitDiff;
                const depthDiff = _escapeDepthRank(b.__escapeDepthKind) - _escapeDepthRank(a.__escapeDepthKind);
                if (depthDiff !== 0) return depthDiff;
                const scoreDiff = Number(b.__escapeNodeScore || 0) - Number(a.__escapeNodeScore || 0);
                if (scoreDiff !== 0) return scoreDiff;
                return a.totalDistance - b.totalDistance;
            });
            const escapeDurationMs = _perfNowMs() - escapeStartedAt;
            _blockAheadPerfMetrics.stages.push({
                key: 'escape',
                durationMs: escapeDurationMs,
                alternatives: escapePoints.length,
                nonBlocked: validEscapeRoutes.length,
                meaningful: validEscapeRoutes.length
            });
            console.log(`[BlockAhead][escape] valid=${validEscapeRoutes.length}/${escapePoints.length} ${Math.round(escapeDurationMs)}ms`);
            if (validEscapeRoutes.length > 0) {
                console.log(
                    `[BlockAhead][escape] selected node=${validEscapeRoutes[0].__escapeLabel} ` +
                    `tier=${validEscapeRoutes[0].__distanceTierM || '-'} depth=${validEscapeRoutes[0].__escapeDepthKind || 'entrance'} ` +
                    `type=${validEscapeRoutes[0].__escapeNodeType || 'unknown'} ` +
                    `score=${Number(validEscapeRoutes[0].__escapeNodeScore || 0).toFixed(1)} ` +
                    `nearPenalty=${Number.isFinite(validEscapeRoutes[0].__escapeMainPenalty) ? Number(validEscapeRoutes[0].__escapeMainPenalty).toFixed(1) : 'inf'} ` +
                    `overlap=${Number(validEscapeRoutes[0].__escapeOverlap || 0).toFixed(2)} ` +
                    `strict=${Number(validEscapeRoutes[0].__escapeStrict || 0).toFixed(2)} ` +
                    `near=${Number(validEscapeRoutes[0].__escapeNear || 0).toFixed(2)} ` +
                    `acceptedByHoldWaypointMode=${!!validEscapeRoutes[0].__acceptedByHoldWaypointMode} ` +
                    `dist=${Math.round(validEscapeRoutes[0].totalDistance)}m`
                );
                selectedStage = { key: 'escape' };
                alternatives = validEscapeRoutes;
                nonBlocked = validEscapeRoutes;
                meaningful = validEscapeRoutes;
                console.log('[BlockAhead][escape] road-node fallback succeeded');
            } else {
                _recordBlockAheadRejectReason('escape-route-blocked');
            }
        } else {
            _recordBlockAheadRejectReason('escape-snap-empty');
        }
    }

    const selectedBufMid = lastStageResult?.bufMid || defaultBufMid;
    const selectedOverlapRadius = lastStageResult?.overlapRadius || defaultOverlapRadius;

    if (meaningful.length === 0) {
        const sawNoChange = nonBlocked.length > 0;
        fail(
            sawNoChange ? 'no-change' : (dangerousCrossingRejected ? 'dangerous-crossing' : 'failed'),
            sawNoChange
                ? 'ℹ 現在のルートと実質同じ経路しか見つからなかったため、既存ルートを継続します。'
                : (dangerousCrossingRejected
                    ? '⚠ 危険な道路横断を含むため、迂回ルートを採用できませんでした。現在のルートを継続します。'
                    : '⚠ 目的地まで到達できる迂回ルートが見つかりませんでした。現在のルートを継続します。'),
            sawNoChange ? 'info' : 'danger'
        );
        return;
    }

    // ── 最短代替ルートをそのまま最終ルートとして採用 ────────────────────
    const winnerRoute = _normalizeAlternativeRouteShape(meaningful[0]);
    console.log(`[BlockAhead] winner stage=${selectedStage?.key || 'unknown'} dist=${Math.round(winnerRoute.totalDistance)}m`);

    if (_blockAheadSeq !== mySeq) {
        navBlockAheadInProgress = false;
        _blockAheadPerfMetrics = null;
        return;
    }

    const adoptStartedAt = _perfNowMs();
    const finalOverlap = _calcBlockOverlapRatio(winnerRoute.coordinates, selectedBufMid.lat, selectedBufMid.lng, selectedOverlapRadius);
    const finalBlockedStats = _routeBlockedAreaStats(winnerRoute.coordinates, activeBlockedArea);
    const routeDiff = _isMeaningfullyDifferentReroute(winnerRoute, originalRouteSnapshot, {
        bufMid: selectedBufMid,
        overlapRadius: selectedOverlapRadius,
        blockedArea: activeBlockedArea
    });
    const finalPedestrianSafety = await _evaluatePedestrianRouteSafety(winnerRoute, `final:${selectedStage?.key || 'unknown'}`);
    const finalNearPenaltyMode = (selectedStage?.key === 'escape-leg' || selectedStage?.key === 'escape')
        ? _assessEscapeNearPenaltyMode(finalBlockedStats, finalOverlap)
        : { eligible: false, penalty: Infinity };
    const finalOverlapHard = finalOverlap >= BLOCK_OVERLAP_REJECT;
    const finalActualIntersectionDetected = !!finalNearPenaltyMode.actualIntersectionDetected;
    const finalStrictThresholdExceeded = !!finalNearPenaltyMode.strictThresholdExceeded;
    const finalNearOnlyReject = !finalNearPenaltyMode.eligible
        && finalBlockedStats.nearBlocked
        && !finalActualIntersectionDetected
        && !finalStrictThresholdExceeded
        && !finalOverlapHard;
    _logEscapeNearPenaltyDecision('[BlockAhead][final][debug]', {
        holdWaypointMode: !!winnerRoute.__acceptedByHoldWaypointMode,
        nearPenaltyMode: finalNearPenaltyMode,
        rejectReason: _escapeRejectReason(finalNearPenaltyMode, {
            actualIntersectionDetected: finalActualIntersectionDetected,
            overlapHard: finalOverlapHard,
            strictThresholdExceeded: finalStrictThresholdExceeded,
            nearOnlyReject: finalNearOnlyReject
        })
    });
    console.log(
        `[BlockAhead][final] overlap=${finalOverlap.toFixed(2)} strict=${finalBlockedStats.strictOverlapRatio.toFixed(2)} ` +
        `near=${finalBlockedStats.nearBlockedRatio.toFixed(2)} minDist=${Math.round(finalBlockedStats.minDistanceToAreaM)}m ` +
        `meaningful=${routeDiff.meaningful} nearPenaltyMode=${finalNearPenaltyMode.eligible} ` +
        `nearPenalty=${Number.isFinite(finalNearPenaltyMode.penalty) ? finalNearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
        `acceptedByNearPenaltyMode=${finalNearPenaltyMode.eligible && finalBlockedStats.nearBlocked} ` +
        `pedestrianSafe=${finalPedestrianSafety.safe}`
    );

    const finalBlockedReject = finalActualIntersectionDetected
        || finalOverlapHard
        || finalStrictThresholdExceeded
        || finalNearOnlyReject;
    if (finalBlockedReject || !routeDiff.meaningful || !finalPedestrianSafety.safe) {
        fail(
            !finalPedestrianSafety.safe ? 'dangerous-crossing' : (finalBlockedReject ? 'failed' : 'no-change'),
            !finalPedestrianSafety.safe
                ? '⚠ 危険な道路横断を含むため、迂回ルートを採用できませんでした。現在のルートを継続します。'
                : finalBlockedReject
                ? '⚠ 目的地まで到達できる迂回ルートが見つかりませんでした。現在のルートを継続します。'
                : 'ℹ 現在のルートと実質同じ経路しか見つからなかったため、既存ルートを継続します。',
            (!finalPedestrianSafety.safe || finalBlockedReject) ? 'danger' : 'info'
        );
        return;
    }

    ++_blockAheadSeq; // consume token — prevents duplicate completion
    const formatter = _buildBlockAheadFormatter();
    const selectedBundle = _selectSingleRouteBundle(
        [winnerRoute],
        0,
        [getRouteColorByIndex(0)],
        formatter,
        document.getElementById('transportMode')?.value ?? 'walking',
        'block-ahead-final:avoid'
    );
    const adoptedRoute = selectedBundle.routes[0];
    adoptedRoute.__pedestrianSafety = finalPedestrianSafety;
    const geometryComparison = {
        selectedToAdopted: _compareRouteGeometries(winnerRoute.coordinates, adoptedRoute.coordinates, 'selected->adopted'),
        selectedToDisplayed: _compareRouteGeometries(winnerRoute.coordinates, selectedBundle.routes[0].coordinates, 'selected->displayed'),
        adoptedToDisplayed: _compareRouteGeometries(adoptedRoute.coordinates, selectedBundle.routes[0].coordinates, 'adopted->displayed')
    };
    const displayPipelineMs = _perfNowMs() - adoptStartedAt;

    navActiveRoute          = adoptedRoute;
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

    if (_blockAheadSeq !== mySeq + 1) {
        console.log('[BlockAhead] stale callback ignored after direct adoption (seq mismatch)');
        navBlockAheadInProgress = false;
        _blockAheadPerfMetrics = null;
        return;
    }

    setNavMode('navigation_active');
    if (currentLocation) {
        _updateRemainingDistanceDisplay(currentLocation.lat, currentLocation.lon, currentLocation.accuracyMeters ?? 0);
    }
    _showNavBanner('✅ 迂回ルートに切り替えました。このまま避難を続けてください。', 'success', 5000);
    if (typeof voiceNav !== 'undefined') {
        voiceNav.announce({ id: 'block-ahead-reroute', text: '前方を迂回するルートに切り替えました', category: 'start', priority: 'high' });
    }

    _clearBlockAheadLayer();
    console.log('[BlockAhead] reroute success seq=' + mySeq);

    const totalMs = _perfNowMs() - rerouteStartedAt;
    const summary = {
        status: 'success',
        accepted: true,
        rejectReason: null,
        totalMs,
        osrmMs: _blockAheadPerfMetrics?.osrmEval?.totalMs || 0,
        displayPipelineMs,
        acceptedStage: selectedStage?.key || 'stage-unknown',
        alternativesEvaluated: alternatives.length,
        nonBlockedCount: nonBlocked.length,
        attemptedStages: Array.isArray(_blockAheadPerfMetrics?.stages) ? _blockAheadPerfMetrics.stages.map(stage => stage.key) : [],
        geometryComparison
    };
    _recordBlockAheadExecutionSummary(summary);
    _blockAheadLastTiming = { ..._blockAheadPerfMetrics, ...summary, totalMs, status: 'success' };
    console.log('[BlockAhead][timing][total]', _blockAheadLastTiming);
    _blockAheadPerfMetrics = null;
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

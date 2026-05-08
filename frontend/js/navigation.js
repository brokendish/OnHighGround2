'use strict';

/**
 * navigation.js — ナビゲーションモード
 *
 * Phase 1: watchPosition による現在地継続取得・マーカー更新・地図追従
 * Phase 2: ルート逸脱判定・警告バナー
 * Phase 3: オフルート時の再ルート・避難先再検索
 */

// ── 定数 ──────────────────────────────────────────────────────────────────
const NAV_OFF_ROUTE_M      = 15;    // 通常時の逸脱候補しきい値（メートル）
const NAV_OFF_ROUTE_NEAR_GOAL_M = 18; // 目的地近傍の逸脱候補しきい値（メートル）
const NAV_NEAR_GOAL_M      = 15;    // 目的地近傍とみなす距離（メートル）
const NAV_MAX_GPS_ACCURACY_M   = 50; // これ以上の誤差なら逸脱判定を保留
const NAV_CONSECUTIVE      = 2;     // 連続 N 回外れたら warning
const NAV_ARRIVAL_M        = 12;    // 到達判定しきい値（メートル）
const NAV_ARRIVAL_CONSECUTIVE = 2;  // 到達判定に必要な連続成立回数
const NAV_NEAR_ARRIVAL_M   = 20;    // まもなく到着表示を出す距離
const NAV_ARRIVAL_RADIUS_MIN_M = 12;
const NAV_ARRIVAL_RADIUS_MAX_M = 25;
const NAV_ARRIVAL_ACCURACY_FACTOR = 0.8;
const NAV_GPS_STALL_DISTANCE_EPS_M = 1;
const NAV_GPS_STALL_DURATION_MS = 5000;
const NAV_GPS_STALL_NEAR_GOAL_M = 30;
const NAV_MIN_DELTA_M      = 3;     // 移動量がこれ以下なら地図UI更新スキップ（逸脱判定・ステップ同期は除外）
const NAV_LOW_ACCURACY_M   = 50;    // GPS 精度がこれ以上なら精度警告
const NAV_REROUTE_COOLDOWN = 10000; // 再ルート連打防止（ms）

// ── オート再ルート定数 ─────────────────────────────────────────────────────
const NAV_AUTO_REROUTE_COOLDOWN_MS = 8000;  // クールダウン（ms、デフォルト8秒）
const NAV_AUTO_REROUTE_ACCURACY_M  = 50;    // 精度ガード（50m以内なら実行）
const NAV_AUTO_REROUTE_MAX_COUNT   = 5;     // ウィンドウ内最大回数
const NAV_AUTO_REROUTE_WINDOW_MS   = 180000;// 回数カウントウィンドウ（ms）
const NAV_AUTO_REROUTE_SUSPEND_RESET_MS = 180000; // suspension 自動リセット（3分）
const NAV_REROUTE_WATCHDOG_MS = 15000; // callback 未達時も再ルート中フラグを戻す

// ── ルート候補・安全横断優先ランキング ───────────────────────────────────
const MAX_ROUTE_CANDIDATES = 3;
// 道路種別ごとの危険横断ペナルティ（safetyScore から減算）
const CROSSING_PENALTY_BY_HIGHWAY = {
    motorway: 300, motorway_link: 300,
    trunk: 200,    trunk_link: 200,
    primary: 150,  primary_link: 150,
    secondary: 80, secondary_link: 80,
};
const CROSSING_UNKNOWN_PENALTY = 30;
const CROSSING_SAFE_BONUS = 20;
// ハザードゾーン危険度ランキング（大きい値ほど安全）
const RISK_LEVEL_RANK = { safe: 3, caution: 2, danger: 1, unknown: 0 };
// safety_score 差がこの値未満なら距離・時間でtiebreak
const HAZARD_SCORE_DIFF_THRESHOLD = 5;
const SAFE_CROSSING_SEARCH_RADIUS_FALLBACK_M = 50;
const SAFE_CROSSING_DETOUR_RATIO_FALLBACK = 1.5;

// ── 標高・表示更新定数（将来の設定画面から変更予定） ────────────────────────
const NAV_ELEV_UPDATE_M        = 10;   // 標高再取得の移動距離しきい値（メートル）
const NAV_HAZARD_UPDATE_M      = 10;   // ハザード再取得の移動距離しきい値（メートル）
const NAV_STATUS_BAR_THROTTLE  = 1000; // ステータスバー精度表示の更新間隔（ms）

// ── ステータスバー更新スロットル ──────────────────────────────────────────
let _statusBarLastUpdateAt = 0;
let _navLogLastSentAt = 0;
let _navLogLastSignature = '';
let _navLogInFlight = false;
let _lastSafeCrossingConfigSignature = null;
let _lastSafeCrossingLogSignature = null;

// ── 逸脱デバウンスタイマー ────────────────────────────────────────────────
const NAV_OFF_ROUTE_DEBOUNCE_MS    = 1000; // 1秒待って誤検知を防ぐ
const NAV_START_GRACE_PERIOD_MS    = 6000; // ナビ開始直後の逸脱判定抑制期間（ms）
let _offRouteDebounceTimer = null;
let _navNearArrival = false;
let _navGpsUnstable = false;
let _navArrivalLastDistanceM = null;
let _navArrivalStallStartedAt = null;

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
const BLOCK_ESCAPE_LATERAL_OFFSETS_M = [60, 100, 120, 150, 200];
const BLOCK_ESCAPE_BACKWARD_LATERAL_OFFSETS_M = [60, 120, 150];
const BLOCK_ESCAPE_BACKWARD_M = 25;
const BLOCK_ESCAPE_MAX_POINTS = 6;
const BLOCK_ESCAPE_LONG_MAX_POINTS = 10;
const BLOCK_ESCAPE_MAX_LATERAL_M = 200;
const BLOCK_ESCAPE_PUSH_STEP_M = 20;
const BLOCK_ESCAPE_IGNORE_METERS = 40;
const BLOCK_ESCAPE_LEG_LATERAL_OFFSETS_M = [30, 60, 90, 120, 150, 200];
const BLOCK_ESCAPE_LEG_BACKWARD_M = 15;
const BLOCK_ESCAPE_LEG_MAX_POINTS = 6;
const BLOCK_ESCAPE_CORRIDOR_DIFF_M = 18;
const BLOCK_ESCAPE_SIDE_BEARING_DEG = 35;
const BLOCK_ESCAPE_NEAREST_RETRY_DISTANCES_M = [5, 10, 15];
const BLOCK_ESCAPE_ADJUSTMENT_DISTANCES_M = [8, 14];
const BLOCK_ESCAPE_DEEPER_STEPS_M = [30, 60, 90, 120];
const BLOCK_ESCAPE_LONG_DEEPER_STEPS_M = [30, 60, 90, 120, 150, 200];
const BLOCK_ESCAPE_GATE_LENGTH_M = 60;
const BLOCK_ESCAPE_GATE_WIDTH_M = 16;
const BLOCK_ESCAPE_GATE_STEPS_M = [15, 30, 45, 60];
const BLOCK_ESCAPE_LEG_PREFIX_GATE_M = 55;
const BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX = 0.35;
const BLOCK_ESCAPE_NEAR_PENALTY_OVERLAP_EPS = 0.08;
const BLOCK_DESTINATION_NEAR_RELAX_ROUTE_DISTANCE_M = 180;
const BLOCK_DESTINATION_NEAR_RELAX_STRICT_BONUS = 0.08;
const PEDESTRIAN_SAFETY_OVERPASS_URL = 'https://overpass-api.de/api/interpreter';
const PEDESTRIAN_SAFETY_BBOX_PADDING_M = 45;
const PEDESTRIAN_SAFETY_COMPACT_BBOX_PADDING_M = 30;
const PEDESTRIAN_SAFETY_EXPANDED_BBOX_PADDING_M = 80;
const PEDESTRIAN_SAFETY_CROSSWALK_RADIUS_M = 20;
const PEDESTRIAN_SAFETY_CROSSING_BIND_RADIUS_M = 20;
const PEDESTRIAN_SAFETY_FETCH_TIMEOUT_MS = 800;
const PEDESTRIAN_SAFETY_MAJOR_HIGHWAYS = new Set(['trunk', 'trunk_link', 'primary', 'primary_link', 'secondary', 'secondary_link']);
const PEDESTRIAN_SAFETY_FORBIDDEN_HIGHWAYS = new Set(['motorway', 'motorway_link']);
const PEDESTRIAN_SAFETY_MIN_CROSSING_BEARING_DEG = 35;
const PEDESTRIAN_SAFETY_SUCCESS_CACHE_TTL_MS = 5 * 60 * 1000;
const PEDESTRIAN_SAFETY_FAILURE_CACHE_TTL_MS = 20 * 1000;
const PEDESTRIAN_SAFETY_TIMEOUT_CACHE_TTL_MS = 8 * 1000;
const PEDESTRIAN_SAFETY_UNKNOWN_CROSS_SEGMENT_M = 32;
const PEDESTRIAN_SAFETY_UNKNOWN_WIDE_CROSS_SEGMENT_M = 45;
const PEDESTRIAN_SAFETY_UNKNOWN_TURN_DIFF_DEG = 40;
const PEDESTRIAN_SAFETY_UNKNOWN_FINAL_RETURN_M = 35;
const PEDESTRIAN_SAFETY_UNKNOWN_SOFT_PENALTY = 180;
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

function _getFrontendLogLevel() {
    const level = String(getRuntimeConfigValue('logging.level', 'INFO') || 'INFO').toUpperCase();
    return ['DEBUG', 'INFO', 'WARNING', 'ERROR'].includes(level) ? level : 'INFO';
}

function _shouldSendNavigationLog(level = 'INFO') {
    const normalized = String(level || 'INFO').toUpperCase();
    const rank = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40 };
    const current = _getFrontendLogLevel();
    return (rank[normalized] || rank.INFO) >= (rank[current] || rank.INFO);
}

function _sendNavigationLog(level, message, context = null) {
    if (!_shouldSendNavigationLog(level)) return;
    const now = Date.now();
    const safeContext = context && typeof context === 'object' ? context : null;
    const signature = JSON.stringify({
        level: String(level || 'INFO').toUpperCase(),
        message,
        context: safeContext
    });
    if (signature === _navLogLastSignature) return;
    if (now - _navLogLastSentAt < 1000) return;
    if (_navLogInFlight) return;

    _navLogLastSentAt = now;
    _navLogLastSignature = signature;
    _navLogInFlight = true;

    fetch('/api/admin/logs/navigation', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            level: String(level || 'INFO').toUpperCase(),
            message,
            context: safeContext
        })
    }).catch(() => {
        // best-effort: logging failure must not affect navigation flow
    }).finally(() => {
        _navLogInFlight = false;
    });
}

function _navDebugLog(message, context = null, level = 'INFO') {
    console.log(`[navigation] ${message}`);
    _sendNavigationLog(level, message, context);
}

function _addNavigationDebugEvent(type, message, context = null, options = {}) {
    try {
        const lat = Number(
            Number.isFinite(options.lat) ? options.lat : currentLocation?.lat
        );
        const lon = Number(
            Number.isFinite(options.lon) ? options.lon : currentLocation?.lon
        );
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
        window.addNavigationDebugEvent?.({
            type,
            lat,
            lon,
            message,
            level: String(options.level || 'INFO').toUpperCase(),
            context: context && typeof context === 'object' ? context : {}
        });
    } catch (_) {
        // debug visualization must never block navigation
    }
}

function _setNavRerouteInProgress(value, reason = '') {
    navRerouteInProgress = value;
    _navDebugLog(`isRerouting=${value}${reason ? ` reason=${reason}` : ''}`);
}

function _setNavAutoRerouteInProgress(value, reason = '') {
    navAutoRerouteInProgress = value;
    _navDebugLog(`isRerouting=${value}${reason ? ` reason=${reason}` : ''}`);
}

function _resetNavArrivalTracking() {
    navArrivalConsecutiveCount = 0;
    navHasArrived = false;
    _navNearArrival = false;
    _navGpsUnstable = false;
    _navArrivalLastDistanceM = null;
    _navArrivalStallStartedAt = null;
}

function _resetNavigationStateOnReroute() {
    _resetNavArrivalTracking();
    if (typeof clearNavStepHighlight === 'function') clearNavStepHighlight();
    if (typeof voiceNav !== 'undefined') voiceNav.clear();
    _navDebugLog('reroute:reset navigation state');
}

function _getArrivalRequirement(accuracy) {
    const arrivalConsecutive = Number(getRuntimeConfigValue(
        'navigation.arrival_consecutive_count',
        NAV_ARRIVAL_CONSECUTIVE
    ));
    const minR = _getNavigationConfigNumber('navigation.arrival_radius_min',          NAV_ARRIVAL_RADIUS_MIN_M);
    const maxR = _getNavigationConfigNumber('navigation.arrival_radius_max',          NAV_ARRIVAL_RADIUS_MAX_M);
    const mul  = _getNavigationConfigNumber('navigation.arrival_accuracy_multiplier', NAV_ARRIVAL_ACCURACY_FACTOR);
    const dynamicRadius = Math.max(minR, Math.min(maxR, Number(accuracy || 0) * mul));
    return {
        radiusM: dynamicRadius,
        consecutive: Number.isFinite(arrivalConsecutive) ? arrivalConsecutive : NAV_ARRIVAL_CONSECUTIVE,
        lowAccuracy: Number(accuracy || 0) > NAV_MAX_GPS_ACCURACY_M
    };
}

function _updateArrivalStability(distToGoal, accuracy) {
    const now = Date.now();
    const previousDistance = _navArrivalLastDistanceM;
    const delta = Number.isFinite(previousDistance) ? Math.abs(distToGoal - previousDistance) : Infinity;
    _navArrivalLastDistanceM = distToGoal;

    if (distToGoal > NAV_GPS_STALL_NEAR_GOAL_M || delta >= NAV_GPS_STALL_DISTANCE_EPS_M) {
        _navArrivalStallStartedAt = now;
        _navGpsUnstable = false;
        return false;
    }
    if (_navArrivalStallStartedAt === null) {
        _navArrivalStallStartedAt = now;
        return false;
    }
    _navGpsUnstable = (now - _navArrivalStallStartedAt) >= NAV_GPS_STALL_DURATION_MS;
    if (_navGpsUnstable) {
        console.log(`[arrival] gps_unstable=true dist=${Math.round(distToGoal)} accuracy=${Math.round(Number(accuracy || 0))}`);
    }
    return _navGpsUnstable;
}

function _getNavigationConfigNumber(key, fallback) {
    const raw = typeof getRuntimeConfigValue === 'function'
        ? getRuntimeConfigValue(key, fallback)
        : fallback;
    const value = Number(raw);
    return Number.isFinite(value) ? value : fallback;
}

function _clearSafeCrossingCaches(reason = 'config-change') {
    if (typeof _pedestrianSafetyContextCache !== 'undefined'
            && _pedestrianSafetyContextCache
            && typeof _pedestrianSafetyContextCache.clear === 'function') {
        _pedestrianSafetyContextCache.clear();
    }
    console.log(`[crossing-config] cache_cleared reason=${reason}`);
}

function _getSafeCrossingRuntimeConfig(options = {}) {
    const searchRadius = _getNavigationConfigNumber(
        'navigation.safe_crossing_search_radius',
        SAFE_CROSSING_SEARCH_RADIUS_FALLBACK_M
    );
    const detourRatio = _getNavigationConfigNumber(
        'navigation.safe_crossing_detour_ratio',
        SAFE_CROSSING_DETOUR_RATIO_FALLBACK
    );
    const radiusM = Math.max(0, searchRadius);
    const maxDetourRatio = Math.max(1, detourRatio);
    const enabled = radiusM > 0;
    const signature = `${radiusM}:${maxDetourRatio}:${enabled}`;

    if (_lastSafeCrossingConfigSignature !== null && _lastSafeCrossingConfigSignature !== signature) {
        _clearSafeCrossingCaches('safe-crossing-config-change');
    }
    _lastSafeCrossingConfigSignature = signature;

    if (options.log && _lastSafeCrossingLogSignature !== signature) {
        console.log(enabled
            ? `[crossing-config] radius=${radiusM} detour=${maxDetourRatio} enabled=true`
            : `[crossing-config] radius=${radiusM} enabled=false`);
        _lastSafeCrossingLogSignature = signature;
    }

    return {
        searchRadius,
        detourRatio,
        radiusM,
        maxDetourRatio,
        enabled,
        disableCrossingLogic: !enabled
    };
}

if (typeof window !== 'undefined') {
    window.addEventListener('ohg:runtime-config-updated', (event) => {
        const key = event?.detail?.key;
        if (key === 'navigation.safe_crossing_search_radius'
                || key === 'navigation.safe_crossing_detour_ratio') {
            _lastSafeCrossingConfigSignature = null;
            _lastSafeCrossingLogSignature = null;
            _clearSafeCrossingCaches('runtime-config-updated');
        }
    });
}

function _getAutoRerouteCooldownMs() {
    return _getNavigationConfigNumber('navigation.auto_reroute_cooldown_ms', NAV_AUTO_REROUTE_COOLDOWN_MS);
}

function _getNearGoalDistanceM() {
    return _getNavigationConfigNumber('navigation.near_goal_distance_m', NAV_NEAR_GOAL_M);
}

function _getOffRouteThresholdM(nearGoal) {
    return nearGoal
        ? _getNavigationConfigNumber('navigation.near_goal_off_route_distance_m', NAV_OFF_ROUTE_NEAR_GOAL_M)
        : _getNavigationConfigNumber('navigation.off_route_distance_m', NAV_OFF_ROUTE_M);
}

function _distanceToRouteEndpoint(lat, lon) {
    if (!navActiveRoute || !Array.isArray(navActiveRoute.coordinates) ||
            navActiveRoute.coordinates.length < 1) {
        return null;
    }
    const lastCoord = navActiveRoute.coordinates[navActiveRoute.coordinates.length - 1];
    return _navHaversine(lat, lon, lastCoord.lat, lastCoord.lng);
}

function _completeReroute({ auto = false, success = false, reason = 'finished', startedAt = null } = {}) {
    const durationMs = startedAt === null ? null : Math.round(_perfNowMs() - startedAt);
    if (success) {
        _addNavigationDebugEvent('reroute_success', 'reroute success', durationMs === null ? {} : {
            duration_ms: durationMs
        });
        _navDebugLog(
            `reroute:success${durationMs === null ? '' : ` duration_ms=${durationMs}`}`,
            durationMs === null ? null : { duration_ms: durationMs }
        );
    } else {
        _navDebugLog(
            `reroute:failed reason=${reason}${durationMs === null ? '' : ` duration_ms=${durationMs}`}`,
            durationMs === null ? { reason } : { reason, duration_ms: durationMs },
            reason === 'timeout' ? 'WARNING' : 'INFO'
        );
    }
    if (auto) {
        _setNavAutoRerouteInProgress(false, reason);
    } else {
        _setNavRerouteInProgress(false, reason);
    }
    // 再ルート完了後クールダウン期間中はoff_route判定をスキップする（成功・失敗問わず）
    navOffRouteSkipUntilMs = Date.now() + _getAutoRerouteCooldownMs();
    _navDebugLog(`reroute:finally isRerouting=false skip_off_route_until=${navOffRouteSkipUntilMs}`);
    _updateNavUI();
}

function _createRerouteWatchdog({ auto = false, startedAt = null, onTimeout = null } = {}) {
    let completed = false;
    const timer = setTimeout(() => {
        if (completed) return;
        completed = true;
        if (typeof onTimeout === 'function') onTimeout();
        _completeReroute({ auto, success: false, reason: 'timeout', startedAt });
    }, NAV_REROUTE_WATCHDOG_MS);

    return (callback) => {
        if (completed) return false;
        completed = true;
        clearTimeout(timer);
        if (typeof callback === 'function') callback();
        return true;
    };
}

let _blockAheadPerfMetrics = null;
let _blockAheadLastTiming = null;
let _blockAheadDebugSummary = null;
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
        window._blockAheadDebugSummary = _blockAheadDebugSummary;
    }
}

function _getBlockAheadTestDeps() {
    if (typeof window === 'undefined') return null;
    return window.__OHG_TEST_DEPS__ || null;
}

async function _callBlockAheadTestDep(name, ...args) {
    const deps = _getBlockAheadTestDeps();
    const fn = deps && deps[name];
    if (typeof fn !== 'function') return undefined;
    return await fn(...args);
}

function _setBlockAheadDebugSummary(summary) {
    _blockAheadDebugSummary = summary || null;
    if (typeof window !== 'undefined') {
        window._blockAheadDebugSummary = _blockAheadDebugSummary;
    }
}

function _createSnapDebugBucket() {
    return {
        rawCandidateCount: 0,
        nearestAttemptCount: 0,
        nearestSuccessCount: 0,
        nearestNullCount: 0,
        nearestRetryCount: 0,
        nearestRetrySucceeded: 0,
        nearestRetryFailed: 0,
        rejectSameCorridorCount: 0,
        rejectInsideBlockedAreaCount: 0,
        rejectTooFarFromCandidateCount: 0,
        rejectLowCorridorScoreCount: 0,
        rejectDuplicateSnapCount: 0,
        rejectInvalidBearingCount: 0,
        rejectNodeBuildFailureCount: 0,
        rejectSameCorridorSoftCount: 0,
        rejectInsideBlockedAreaSoftCount: 0,
        sameCorridorHardCount: 0,
        sameCorridorSoftCount: 0,
        sameCorridorPassCount: 0,
        insideBlockedHardCount: 0,
        insideBlockedSoftCount: 0,
        insideBlockedPassCount: 0,
        usableSnappedCount: 0,
        usableRouteCandidateCount: 0
    };
}

function _createSnapDecisionBucket() {
    return {
        hard: 0,
        soft: 0,
        pass: 0
    };
}

function _createCountMap() {
    return {};
}

function _createEscapeStrategyStat() {
    return {
        executed: 0,
        success: 0,
        nearestReturned: 0,
        nearestNull: 0,
        nodeBuildSuccess: 0,
        sideRoadContinuationDetected: 0,
        acceptedAsRescue: 0,
        rejectedAsMainlineOnly: 0,
        rejectedAsDuplicate: 0,
        rejectedAsInvalidBearing: 0
    };
}

function _bucketNumericRange(value, steps = [], fallback = 'unknown') {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) return fallback;
    const normalizedSteps = Array.isArray(steps) ? steps.filter(step => Number.isFinite(Number(step))).map(Number).sort((a, b) => a - b) : [];
    if (!normalizedSteps.length) return fallback;
    if (numeric <= normalizedSteps[0]) return `0-${normalizedSteps[0]}`;
    for (let i = 1; i < normalizedSteps.length; i++) {
        if (numeric <= normalizedSteps[i]) return `${normalizedSteps[i - 1]}-${normalizedSteps[i]}`;
    }
    return `${normalizedSteps[normalizedSteps.length - 1]}+`;
}

function _bucketBearingDiff(value) {
    return _bucketNumericRange(value, [30, 60, 90, 120, 150, 180], 'unknown');
}

function _bucketCorridorLength(value) {
    return _bucketNumericRange(value, [15, 30, 60, 90, 120, 180], 'unknown');
}

function _bucketSnapDistance(value) {
    return _bucketNumericRange(value, [5, 10, 15, 20, 30, 50], 'unknown');
}

function _getEscapeNearestRetryMode(candidate) {
    const injected = (typeof window !== 'undefined' && window.__OHG_TEST_DEPS__ && window.__OHG_TEST_DEPS__.escapeNearestRetryMode)
        || null;
    return candidate?.escapeRetryMode || injected || ESCAPE_NEAREST_RETRY_DEFAULT_MODE;
}

function _orderEscapeNearestRetryStrategies(candidate) {
    const mode = _getEscapeNearestRetryMode(candidate);
    const retryProfile = _classifyEscapeRetryProfile(candidate);
    let ordered = ESCAPE_NEAREST_RETRY_STRATEGIES
        .filter(strategy => strategy.enabled !== false)
        .slice()
        .sort((a, b) => Number(b.priority || 0) - Number(a.priority || 0));
    if (retryProfile === 'back-right-entrance') {
        const profileOrder = [
            'escape-lateral-right-5',
            'escape-right-forward-10',
            'escape-right-forward-15',
            'escape-right-backward-10',
            'escape-forward-5',
            'escape-forward-10'
        ];
        ordered.sort((a, b) => {
            const ai = profileOrder.indexOf(a.id);
            const bi = profileOrder.indexOf(b.id);
            if (ai >= 0 && bi >= 0) return ai - bi;
            if (ai >= 0) return -1;
            if (bi >= 0) return 1;
            return Number(b.priority || 0) - Number(a.priority || 0);
        });
    }
    return { mode, ordered, retryProfile };
}

function _shouldSkipEscapeNearestStrategy(strategy, candidate, mode) {
    if (!strategy) return { skipped: true, reason: 'missing-strategy' };
    if (mode === 'full' || mode === 'priority-only') return { skipped: false, reason: null };
    const candidateSide = String(candidate?.side || '');
    const retryProfile = _classifyEscapeRetryProfile(candidate);
    if (mode === 'priority-pruned') {
        const keep = retryProfile === 'back-right-entrance'
            ? new Set(['escape-lateral-right-5', 'escape-right-forward-10', 'escape-right-forward-15', 'escape-right-backward-10', 'escape-forward-5', 'escape-forward-10'])
            : new Set(['escape-lateral-right-5', 'escape-right-forward-10', 'escape-right-backward-10']);
        if (!keep.has(strategy.id)) {
            if (retryProfile === 'back-right-entrance') {
                if (strategy.family?.startsWith('left')) return { skipped: true, reason: 'pruned-back-right-policy' };
                if (strategy.family === 'backward') return { skipped: true, reason: 'pruned-low-value-strategy' };
                return { skipped: true, reason: 'pruned-entrance-policy' };
            }
            return { skipped: true, reason: 'pruned-low-value-strategy' };
        }
        if (candidateSide && !candidateSide.includes('right')) {
            return { skipped: true, reason: 'pruned-non-right-dominant' };
        }
        if (retryProfile !== 'back-right-entrance' && String(strategy.family || '').startsWith('left')) {
            return { skipped: true, reason: 'pruned-unsafe-direction' };
        }
    }
    return { skipped: false, reason: null };
}

function _buildEscapeRetryPointFromStrategy(candidatePoint, headingUnit, strategyId) {
    if (!candidatePoint || !headingUnit || !strategyId) return null;
    const forward = { east: headingUnit.east, north: headingUnit.north };
    const left = { east: -headingUnit.north, north: headingUnit.east };
    const right = { east: -left.east, north: -left.north };
    const builders = {
        'escape-lateral-right-5': { distanceM: 5, east: right.east * 5, north: right.north * 5 },
        'escape-lateral-left-5': { distanceM: 5, east: left.east * 5, north: left.north * 5 },
        'escape-forward-5': { distanceM: 5, east: forward.east * 5, north: forward.north * 5 },
        'escape-forward-10': { distanceM: 10, east: forward.east * 10, north: forward.north * 10 },
        'escape-backward-5': { distanceM: 5, east: -forward.east * 5, north: -forward.north * 5 },
        'escape-right-forward-10': { distanceM: 10, east: (right.east * 6) + (forward.east * 8), north: (right.north * 6) + (forward.north * 8) },
        'escape-right-forward-15': { distanceM: 15, east: (right.east * 8) + (forward.east * 12), north: (right.north * 8) + (forward.north * 12) },
        'escape-left-forward-10': { distanceM: 10, east: (left.east * 6) + (forward.east * 8), north: (left.north * 6) + (forward.north * 8) },
        'escape-right-backward-10': { distanceM: 10, east: (right.east * 6) - (forward.east * 8), north: (right.north * 6) - (forward.north * 8) },
        'escape-left-backward-10': { distanceM: 10, east: (left.east * 6) - (forward.east * 8), north: (left.north * 6) - (forward.north * 8) }
    };
    const spec = builders[strategyId];
    if (!spec) return null;
    const point = _offsetPointByMeters(candidatePoint, spec.east, spec.north);
    if (!point) return null;
    return {
        label: strategyId,
        distanceM: spec.distanceM,
        point
    };
}

function _createEscapeNearestBreakdown() {
    return {
        totalCandidates: 0,
        nearestNullAfterRetryCount: 0,
        nearestNullAfterRetryDetails: {},
        strategyStats: {},
        strategyOrderUsed: [],
        prunedStrategies: [],
        enabledStrategies: [],
        disabledStrategies: [],
        strategySkipReasons: {},
        acceptedAfterRetryByStrategy: {},
        firstWinningStrategyBreakdown: {},
        nearestReturnedByStrategy: {},
        allNullByStrategy: {},
        firstWinningStrategy: 'none',
        firstWinningStrategyStats: {},
        retryStrategyExhaustedDetails: {},
        nearestReturnedButRejectedBreakdown: {},
        nearestReturnedButRejectedAsMainlineOnly: 0,
        nearestReturnedButRejectedAsNoSideRoad: 0,
        nearestReturnedButRejectedAsDuplicate: 0,
        backRightEntranceBreakdown: {},
        strategyOrderProfiles: {},
        sideStats: {},
        tierStats: {},
        depthStats: {},
        positionCategoryStats: {},
        bearingBucketStats: {},
        corridorLengthBucketStats: {},
        snapDistanceBucketStats: {},
        acceptedAfterRetryCount: 0,
        acceptedAfterAdjustmentCount: 0,
        acceptedAsRescueCount: 0,
        rejectedAsMainlineOnlyCount: 0,
        rejectedAsDuplicateOnlyCount: 0,
        rejectedAsInvalidBearingCount: 0,
        topFailureCombos: []
    };
}

const ESCAPE_NEAREST_RETRY_DEFAULT_MODE = 'priority-pruned';
const ESCAPE_NEAREST_RETRY_STRATEGIES = [
    { id: 'escape-lateral-right-5', priority: 100, enabled: true, family: 'right-lateral', distanceM: 5 },
    { id: 'escape-right-forward-10', priority: 90, enabled: true, family: 'right-diagonal', distanceM: 10 },
    { id: 'escape-right-forward-15', priority: 88, enabled: true, family: 'right-diagonal', distanceM: 15 },
    { id: 'escape-right-backward-10', priority: 85, enabled: true, family: 'right-diagonal', distanceM: 10 },
    { id: 'escape-forward-5', priority: 60, enabled: true, family: 'forward', distanceM: 5 },
    { id: 'escape-forward-10', priority: 58, enabled: true, family: 'forward', distanceM: 10 },
    { id: 'escape-backward-5', priority: 55, enabled: true, family: 'backward', distanceM: 5 },
    { id: 'escape-lateral-left-5', priority: 40, enabled: true, family: 'left-lateral', distanceM: 5 },
    { id: 'escape-left-forward-10', priority: 30, enabled: true, family: 'left-diagonal', distanceM: 10 },
    { id: 'escape-left-backward-10', priority: 25, enabled: true, family: 'left-diagonal', distanceM: 10 }
];

function _classifyEscapeRetryProfile(candidate = {}) {
    const mode = String(candidate?.mode || candidate?.retryMode || 'escape');
    const side = String(candidate?.side || '');
    const depth = String(candidate?.depthKind || candidate?.depth || 'entrance');
    const tier = Number(candidate?.distanceTierM || candidate?.tier || candidate?.lateralM || 0);
    const rawPosition = String(candidate?.positionCategory || candidate?.candidatePositionCategory || '');
    const backwardEntryLike = rawPosition === 'backward-entry' || Number(candidate?.backwardM || 0) > 0 || side.startsWith('back-');
    if (mode === 'escape' && (side === 'right' || side === 'back-right') && depth === 'entrance' && backwardEntryLike && tier >= 60 && tier <= 100) {
        return 'back-right-entrance';
    }
    if (mode === 'escape' && (side === 'right' || side === 'back-right') && depth === 'entrance') {
        return 'right-entrance';
    }
    return 'default';
}

function _createSnapDebugCollector() {
    return {
        events: [],
        modeStats: {},
        sideStats: {},
        tierStats: {},
        depthStats: {},
        retryStats: {
            nearestRetryCount: 0,
            nearestRetrySucceeded: 0,
            nearestRetryFailed: 0
        },
        escapeRetryStats: {
            nearestRetryCount: 0,
            nearestRetrySucceeded: 0,
            nearestRetryFailed: 0
        },
        escapeRetrySuccessByStrategy: _createCountMap(),
        escapeRetryFailureByStrategy: _createCountMap(),
        escapeCandidateAdjustmentStats: _createCountMap(),
        escapeNearestNullReasons: _createCountMap(),
        escapeNearestAcceptedAfterAdjustment: 0,
        escapeNearestAcceptedAfterRetry: 0,
        escapeNearestDetailBreakdown: _createCountMap(),
        escapeStrategyStats: {},
        sameCorridorStats: _createSnapDecisionBucket(),
        insideBlockedStats: _createSnapDecisionBucket(),
        snapEmptyFailureMode: null,
        snapEmptyPrimaryReason: 'none',
        snapEmptyReasonBreakdown: {}
    };
}

function _normalizeSnapDebugKey(value, fallback = 'unknown') {
    if (value === null || typeof value === 'undefined' || value === '') return fallback;
    return String(value);
}

function _ensureSnapDebugBucket(target, key) {
    if (!target[key]) target[key] = _createSnapDebugBucket();
    return target[key];
}

function _applySnapDebugCounter(target, key, counterName, amount = 1) {
    const bucket = _ensureSnapDebugBucket(target, key);
    bucket[counterName] = Number(bucket[counterName] || 0) + amount;
}

function _incrementSnapDecisionBucket(bucket, decision) {
    if (!bucket) return;
    const key = decision === 'hard' || decision === 'soft' ? decision : 'pass';
    bucket[key] = Number(bucket[key] || 0) + 1;
}

function _incrementCountMap(map, key, amount = 1) {
    if (!map || !key) return;
    map[key] = Number(map[key] || 0) + amount;
}

function _recordSnapDebugCounters(event = {}, counterName, amount = 1) {
    const collector = _blockAheadPerfMetrics?.snapDebugCollector;
    if (!collector || !counterName) return;
    const modeKey = _normalizeSnapDebugKey(event.mode, 'unknown');
    _applySnapDebugCounter(collector.modeStats, modeKey, counterName, amount);
    if (event.side) _applySnapDebugCounter(collector.sideStats, _normalizeSnapDebugKey(event.side), counterName, amount);
    if (Number.isFinite(Number(event.tier))) _applySnapDebugCounter(collector.tierStats, _normalizeSnapDebugKey(Number(event.tier)), counterName, amount);
    if (event.depth) _applySnapDebugCounter(collector.depthStats, _normalizeSnapDebugKey(event.depth), counterName, amount);
}

function _recordSnapDebugEvent(event = {}) {
    const collector = _blockAheadPerfMetrics?.snapDebugCollector;
    if (!collector) return;
    const normalized = {
        type: event.type || null,
        mode: _normalizeSnapDebugKey(event.mode),
        side: event.side ? _normalizeSnapDebugKey(event.side) : null,
        tier: Number.isFinite(Number(event.tier)) ? Number(event.tier) : null,
        depth: event.depth ? _normalizeSnapDebugKey(event.depth, 'entrance') : null,
        candidateId: event.candidateId || null,
        rawPoint: event.rawPoint || null,
        snappedPoint: event.snappedPoint || null,
        nearestRequested: !!event.nearestRequested,
        nearestReturned: !!event.nearestReturned,
        snapDistanceM: Number.isFinite(Number(event.snapDistanceM)) ? Number(event.snapDistanceM) : null,
        corridorDistanceM: Number.isFinite(Number(event.corridorDistanceM)) ? Number(event.corridorDistanceM) : null,
        blockedDistanceM: Number.isFinite(Number(event.blockedDistanceM)) ? Number(event.blockedDistanceM) : null,
        bearingDiffDeg: Number.isFinite(Number(event.bearingDiffDeg)) ? Number(event.bearingDiffDeg) : null,
        lateralM: Number.isFinite(Number(event.lateralM)) ? Number(event.lateralM) : null,
        nodeScore: Number.isFinite(Number(event.nodeScore)) ? Number(event.nodeScore) : null,
        nearestRetryCount: Number.isFinite(Number(event.nearestRetryCount)) ? Number(event.nearestRetryCount) : 0,
        nearestRetrySuccess: !!event.nearestRetrySuccess,
        nearestStrategyUsed: event.nearestStrategyUsed || null,
        nearestStrategiesTried: Array.isArray(event.nearestStrategiesTried) ? event.nearestStrategiesTried.slice() : [],
        nearestStrategyAttempts: Array.isArray(event.nearestStrategyAttempts) ? event.nearestStrategyAttempts.slice() : [],
        strategyOrderUsed: Array.isArray(event.strategyOrderUsed) ? event.strategyOrderUsed.slice() : [],
        strategiesEnabled: Array.isArray(event.strategiesEnabled) ? event.strategiesEnabled.slice() : [],
        strategiesPruned: Array.isArray(event.strategiesPruned) ? event.strategiesPruned.slice() : [],
        strategiesDisabled: Array.isArray(event.strategiesDisabled) ? event.strategiesDisabled.slice() : [],
        strategySkipReasons: event.strategySkipReasons ? { ...event.strategySkipReasons } : {},
        retryProfile: event.retryProfile || null,
        firstNearestReturnedStrategy: event.firstNearestReturnedStrategy || null,
        firstAcceptedStrategy: event.firstAcceptedStrategy || null,
        firstWinningStrategy: event.firstWinningStrategy || null,
        winningStrategyIndex: Number.isFinite(Number(event.winningStrategyIndex)) ? Number(event.winningStrategyIndex) : null,
        allStrategiesNull: !!event.allStrategiesNull,
        allStrategiesRejected: !!event.allStrategiesRejected,
        finalRetryOutcome: event.finalRetryOutcome || null,
        candidateAdjusted: !!event.candidateAdjusted,
        candidateAdjustmentType: event.candidateAdjustmentType || null,
        candidateAdjustmentDistance: Number.isFinite(Number(event.candidateAdjustmentDistance)) ? Number(event.candidateAdjustmentDistance) : null,
        nearestFailureReason: event.nearestFailureReason || null,
        nearestReturnedButRejectedReason: event.nearestReturnedButRejectedReason || null,
        nearestAcceptedAsRescue: !!event.nearestAcceptedAsRescue,
        nearestReturnedByRetry: !!event.nearestReturnedByRetry,
        nodeBuildSuccess: typeof event.nodeBuildSuccess === 'boolean' ? event.nodeBuildSuccess : null,
        sameCorridorDecision: event.sameCorridorDecision || 'pass',
        insideBlockedDecision: event.insideBlockedDecision || 'pass',
        sideRoadContinuationDetected: !!event.sideRoadContinuationDetected,
        sideRoadContinuationDetectedAtSnap: !!event.sideRoadContinuationDetectedAtSnap,
        mainlineReturnDetected: !!event.mainlineReturnDetected,
        holdWaypointMode: !!event.holdWaypointMode,
        blockedBearing: Number.isFinite(Number(event.blockedBearing)) ? Number(event.blockedBearing) : null,
        blockedBearingBucket: event.blockedBearingBucket || null,
        corridorLength: Number.isFinite(Number(event.corridorLength)) ? Number(event.corridorLength) : null,
        corridorLengthBucket: event.corridorLengthBucket || null,
        snapDistanceBucket: event.snapDistanceBucket || null,
        effectiveRadiusM: Number.isFinite(Number(event.effectiveRadiusM)) ? Number(event.effectiveRadiusM) : null,
        candidatePositionCategory: event.candidatePositionCategory || null,
        usable: !!event.usable,
        nearestRejectedReason: event.nearestRejectedReason || null,
        snapEmptyPrimaryReason: event.snapEmptyPrimaryReason || null,
        snapEmptyDetail: event.snapEmptyDetail || null,
        rejectedReason: event.rejectedReason || null,
        detail: event.detail || null
    };
    collector.events.push(normalized);
    if (collector.events.length > 400) {
        collector.events = collector.events.slice(-400);
    }

    if (event.type === 'raw-candidate') {
        _recordSnapDebugCounters(normalized, 'rawCandidateCount');
        return;
    }
    if (event.type === 'nearest-attempt') {
        _recordSnapDebugCounters(normalized, 'nearestAttemptCount');
        return;
    }
    if (event.type === 'nearest-success') {
        _recordSnapDebugCounters(normalized, 'nearestSuccessCount');
        return;
    }
    if (event.type === 'nearest-null') {
        _recordSnapDebugCounters(normalized, 'nearestNullCount');
        if (normalized.mode === 'escape') {
            _incrementCountMap(collector.escapeNearestNullReasons, normalized.nearestFailureReason || normalized.rejectedReason || 'unknown');
        }
        return;
    }
    if (event.type === 'nearest-retry') {
        const retryCount = Math.max(0, Number(event.nearestRetryCount || 0));
        const attemptedRetryFlow = retryCount > 0 || !!event.finalRetryOutcome;
        if (retryCount > 0) {
            _recordSnapDebugCounters(normalized, 'nearestRetryCount', retryCount);
            collector.retryStats.nearestRetryCount += retryCount;
        }
        if (event.nearestRetrySuccess) {
            _recordSnapDebugCounters(normalized, 'nearestRetrySucceeded');
            collector.retryStats.nearestRetrySucceeded += 1;
        } else if (attemptedRetryFlow) {
            _recordSnapDebugCounters(normalized, 'nearestRetryFailed');
            collector.retryStats.nearestRetryFailed += 1;
        }
        if (normalized.mode === 'escape' && attemptedRetryFlow) {
            collector.escapeRetryStats.nearestRetryCount += retryCount;
            if (event.nearestRetrySuccess) {
                collector.escapeRetryStats.nearestRetrySucceeded += 1;
                _incrementCountMap(collector.escapeRetrySuccessByStrategy, normalized.nearestStrategyUsed || 'retry-unknown');
            } else {
                collector.escapeRetryStats.nearestRetryFailed += 1;
                _incrementCountMap(collector.escapeRetryFailureByStrategy, normalized.nearestStrategyUsed || 'retry-exhausted');
            }
        }
        return;
    }
    if (event.type === 'candidate-adjustment') {
        if (normalized.mode === 'escape') {
            _incrementCountMap(
                collector.escapeCandidateAdjustmentStats,
                normalized.candidateAdjustmentType || 'adjustment-unknown'
            );
        }
        return;
    }
    if (event.type === 'usable-snapped') {
        _recordSnapDebugCounters(normalized, 'usableSnappedCount');
        if (normalized.mode === 'escape') {
            if (normalized.candidateAdjusted) collector.escapeNearestAcceptedAfterAdjustment += 1;
            if (normalized.nearestRetrySuccess) collector.escapeNearestAcceptedAfterRetry += 1;
        }
        return;
    }
    if (event.type === 'usable-route-candidate') {
        _recordSnapDebugCounters(normalized, 'usableRouteCandidateCount');
        return;
    }
    if (event.type === 'reject') {
        const counterByReason = {
            'same-corridor': 'rejectSameCorridorCount',
            'inside-blocked-area': 'rejectInsideBlockedAreaCount',
            'too-far-from-candidate': 'rejectTooFarFromCandidateCount',
            'low-corridor-score': 'rejectLowCorridorScoreCount',
            'duplicate-snap': 'rejectDuplicateSnapCount',
            'invalid-bearing': 'rejectInvalidBearingCount',
            'node-build-failure': 'rejectNodeBuildFailureCount',
            'same-corridor-soft': 'rejectSameCorridorSoftCount',
            'inside-blocked-area-soft': 'rejectInsideBlockedAreaSoftCount'
        };
        const counterName = counterByReason[event.rejectedReason];
        if (counterName) _recordSnapDebugCounters(normalized, counterName);
        return;
    }
    if (event.type === 'decision') {
        if (event.sameCorridorDecision) {
            const sameCounter = `sameCorridor${event.sameCorridorDecision === 'hard' ? 'Hard' : (event.sameCorridorDecision === 'soft' ? 'Soft' : 'Pass')}Count`;
            _recordSnapDebugCounters(normalized, sameCounter);
            _incrementSnapDecisionBucket(collector.sameCorridorStats, event.sameCorridorDecision);
        }
        if (event.insideBlockedDecision) {
            const blockedCounter = `insideBlocked${event.insideBlockedDecision === 'hard' ? 'Hard' : (event.insideBlockedDecision === 'soft' ? 'Soft' : 'Pass')}Count`;
            _recordSnapDebugCounters(normalized, blockedCounter);
            _incrementSnapDecisionBucket(collector.insideBlockedStats, event.insideBlockedDecision);
        }
    }
}

function _deriveEscapeNearestDetail(candidate = {}) {
    if (!candidate || candidate.mode !== 'escape') return 'none';
    if (!candidate.rawPoint) return 'nearest-null-after-retry:no-candidate-point';
    if (Number(candidate.nearestRetryCount || 0) <= 0) return 'none';
    if (candidate.nearestFailureReason === 'all-pruned-by-policy') return 'nearest-null-after-retry:retry-strategy-exhausted:all-pruned-by-policy';
    if (!candidate.nearestReturned) {
        if (candidate.nearestFailureReason === 'retry-strategy-exhausted:no-nearest-returned') {
            return 'nearest-null-after-retry:retry-strategy-exhausted:no-nearest-returned';
        }
        return 'nearest-null-after-retry:all-retry-points-null';
    }
    if (candidate.nearestFailureReason === 'retry-strategy-exhausted:only-duplicate-candidates') {
        return 'nearest-null-after-retry:retry-strategy-exhausted:only-duplicate-candidates';
    }
    if (candidate.nearestFailureReason === 'retry-strategy-exhausted:only-mainline-continuation') {
        return 'nearest-null-after-retry:retry-strategy-exhausted:only-mainline-continuation';
    }
    if (candidate.nearestFailureReason === 'retry-strategy-exhausted:nearest-returned-but-all-rejected') {
        return 'nearest-null-after-retry:retry-strategy-exhausted:nearest-returned-but-all-rejected';
    }
    if (candidate.nearestRejectedReason === 'node-build-failure') return 'nearest-null-after-retry:retry-node-build-failure';
    if (candidate.nearestRejectedReason === 'invalid-bearing') return 'nearest-null-after-retry:retry-invalid-bearing';
    if (candidate.nearestRejectedReason === 'duplicate-snap') return 'nearest-null-after-retry:retry-duplicate-only';
    if (candidate.nearestRejectedReason === 'too-far-from-candidate') return 'nearest-null-after-retry:retry-too-far';
    if (candidate.nearestRejectedReason === 'same-corridor') {
        return candidate.sideRoadContinuationDetectedAtSnap
            ? 'nearest-null-after-retry:retry-strategy-exhausted:only-mainline-continuation'
            : 'nearest-null-after-retry:retry-rejected-no-side-road';
    }
    if (candidate.nearestFailureReason === 'retry-no-strategy-enabled') return 'nearest-null-after-retry:retry-no-strategy-enabled';
    if (candidate.nearestFailureReason === 'all-retry-points-null') return 'nearest-null-after-retry:all-retry-points-null';
    if (String(candidate.nearestFailureReason || '').startsWith('retry-strategy-exhausted:')) {
        return `nearest-null-after-retry:${candidate.nearestFailureReason}`;
    }
    return `nearest-null-after-retry:${candidate.nearestFailureReason || 'retry-strategy-exhausted:nearest-returned-but-all-rejected'}`;
}

function _buildEscapeNearestBreakdown(collector) {
    const breakdown = _createEscapeNearestBreakdown();
    const candidateMap = {};
    const strategyStats = {};
    const events = Array.isArray(collector?.events) ? collector.events : [];
    const ensureStrategyStat = (strategy) => {
        const key = strategy || 'unknown';
        if (!strategyStats[key]) strategyStats[key] = _createEscapeStrategyStat();
        return strategyStats[key];
    };
    const ensureCount = (target, key) => {
        const normalizedKey = _normalizeSnapDebugKey(key);
        target[normalizedKey] = Number(target[normalizedKey] || 0) + 1;
    };
    const candidateKeyFor = (event) => [
        _normalizeSnapDebugKey(event.mode),
        _normalizeSnapDebugKey(event.candidateId),
        _normalizeSnapDebugKey(event.side),
        _normalizeSnapDebugKey(event.tier),
        _normalizeSnapDebugKey(event.depth, 'entrance')
    ].join('|');

    events.forEach((event) => {
        if (event.mode !== 'escape') return;
        const candidateKey = candidateKeyFor(event);
        if (!candidateMap[candidateKey]) {
            candidateMap[candidateKey] = {
                mode: 'escape',
                candidateId: event.candidateId,
                side: event.side,
                tier: event.tier,
                depth: event.depth || 'entrance',
                holdWaypointMode: !!event.holdWaypointMode,
                candidatePositionCategory: event.candidatePositionCategory || 'unknown',
                blockedBearing: event.blockedBearing,
                blockedBearingBucket: event.blockedBearingBucket || 'unknown',
                corridorLength: event.corridorLength,
                corridorLengthBucket: event.corridorLengthBucket || 'unknown',
                snapDistanceM: event.snapDistanceM,
                snapDistanceBucket: event.snapDistanceBucket || 'unknown',
                nearestStrategyUsed: null,
                nearestStrategiesTried: [],
                nearestStrategyAttempts: [],
                retryProfile: event.retryProfile || 'default',
                strategyOrderUsed: [],
                strategiesEnabled: [],
                strategiesPruned: [],
                strategiesDisabled: [],
                strategySkipReasons: {},
                firstNearestReturnedStrategy: null,
                firstAcceptedStrategy: null,
                winningStrategyIndex: null,
                allStrategiesNull: false,
                allStrategiesRejected: false,
                finalRetryOutcome: null,
                nearestRetryCount: 0,
                nearestRetrySuccess: false,
                nearestReturned: false,
                nodeBuildSuccess: false,
                sideRoadContinuationDetectedAtSnap: false,
                nearestAcceptedAsRescue: false,
                nearestRejectedReason: null,
                nearestFailureReason: null,
                nearestReturnedButRejectedReason: null,
                candidateAdjusted: false,
                acceptedAfterRetry: false,
                acceptedAfterAdjustment: false
            };
            breakdown.totalCandidates += 1;
        }
        const candidate = candidateMap[candidateKey];
        if (event.rawPoint) candidate.rawPoint = event.rawPoint;
        if (event.side) candidate.side = event.side;
        if (Number.isFinite(Number(event.tier))) candidate.tier = Number(event.tier);
        if (event.depth) candidate.depth = event.depth;
        if (event.candidatePositionCategory) candidate.candidatePositionCategory = event.candidatePositionCategory;
        if (Number.isFinite(Number(event.blockedBearing))) candidate.blockedBearing = Number(event.blockedBearing);
        if (event.blockedBearingBucket) candidate.blockedBearingBucket = event.blockedBearingBucket;
        if (Number.isFinite(Number(event.corridorLength))) candidate.corridorLength = Number(event.corridorLength);
        if (event.corridorLengthBucket) candidate.corridorLengthBucket = event.corridorLengthBucket;
        if (Number.isFinite(Number(event.snapDistanceM))) candidate.snapDistanceM = Number(event.snapDistanceM);
        if (event.snapDistanceBucket) candidate.snapDistanceBucket = event.snapDistanceBucket;
        if (typeof event.holdWaypointMode === 'boolean') candidate.holdWaypointMode = event.holdWaypointMode;
        if (event.nearestStrategyUsed) candidate.nearestStrategyUsed = event.nearestStrategyUsed;
        if (Array.isArray(event.nearestStrategiesTried) && event.nearestStrategiesTried.length) {
            candidate.nearestStrategiesTried = Array.from(new Set(candidate.nearestStrategiesTried.concat(event.nearestStrategiesTried)));
        }
        if (Array.isArray(event.nearestStrategyAttempts) && event.nearestStrategyAttempts.length) {
            candidate.nearestStrategyAttempts = event.nearestStrategyAttempts.slice();
        }
        if (event.retryProfile) {
            candidate.retryProfile = event.retryProfile;
            breakdown.strategyOrderProfiles[event.retryProfile] = Number(breakdown.strategyOrderProfiles[event.retryProfile] || 0) + (event.type === 'nearest-retry' ? 1 : 0);
        }
        if (Array.isArray(event.strategyOrderUsed) && event.strategyOrderUsed.length) {
            candidate.strategyOrderUsed = event.strategyOrderUsed.slice();
            breakdown.strategyOrderUsed = event.strategyOrderUsed.slice();
        }
        if (Array.isArray(event.strategiesEnabled) && event.strategiesEnabled.length) {
            candidate.strategiesEnabled = event.strategiesEnabled.slice();
            breakdown.enabledStrategies = Array.from(new Set(breakdown.enabledStrategies.concat(event.strategiesEnabled)));
        }
        if (Array.isArray(event.strategiesPruned) && event.strategiesPruned.length) {
            candidate.strategiesPruned = event.strategiesPruned.slice();
            breakdown.prunedStrategies = Array.from(new Set(breakdown.prunedStrategies.concat(event.strategiesPruned)));
        }
        if (Array.isArray(event.strategiesDisabled) && event.strategiesDisabled.length) {
            candidate.strategiesDisabled = event.strategiesDisabled.slice();
            breakdown.disabledStrategies = Array.from(new Set(breakdown.disabledStrategies.concat(event.strategiesDisabled)));
        }
        if (event.strategySkipReasons && typeof event.strategySkipReasons === 'object') {
            candidate.strategySkipReasons = { ...candidate.strategySkipReasons, ...event.strategySkipReasons };
            Object.entries(event.strategySkipReasons).forEach(([strategy, reason]) => {
                if (strategy && reason) breakdown.strategySkipReasons[strategy] = reason;
            });
        }
        if (event.firstNearestReturnedStrategy) candidate.firstNearestReturnedStrategy = event.firstNearestReturnedStrategy;
        if (event.firstAcceptedStrategy) candidate.firstAcceptedStrategy = event.firstAcceptedStrategy;
        if (Number.isFinite(Number(event.winningStrategyIndex))) candidate.winningStrategyIndex = Number(event.winningStrategyIndex);
        candidate.allStrategiesNull = candidate.allStrategiesNull || !!event.allStrategiesNull;
        candidate.allStrategiesRejected = candidate.allStrategiesRejected || !!event.allStrategiesRejected;
        if (event.finalRetryOutcome) candidate.finalRetryOutcome = event.finalRetryOutcome;
        candidate.nearestRetryCount = Math.max(candidate.nearestRetryCount, Number(event.nearestRetryCount || 0));
        candidate.nearestRetrySuccess = candidate.nearestRetrySuccess || !!event.nearestRetrySuccess;
        candidate.nearestReturned = candidate.nearestReturned || !!event.nearestReturned || !!event.nearestReturnedByRetry || !!event.snappedPoint;
        candidate.nodeBuildSuccess = candidate.nodeBuildSuccess || !!event.nodeBuildSuccess || !!event.usable;
        candidate.sideRoadContinuationDetectedAtSnap = candidate.sideRoadContinuationDetectedAtSnap || !!event.sideRoadContinuationDetectedAtSnap;
        candidate.nearestAcceptedAsRescue = candidate.nearestAcceptedAsRescue || !!event.nearestAcceptedAsRescue;
        candidate.nearestFailureReason = event.nearestFailureReason || candidate.nearestFailureReason;
        candidate.nearestReturnedButRejectedReason = event.nearestReturnedButRejectedReason || candidate.nearestReturnedButRejectedReason;
        candidate.candidateAdjusted = candidate.candidateAdjusted || !!event.candidateAdjusted;
        if (event.rejectedReason) candidate.nearestRejectedReason = event.rejectedReason;
        if (event.type === 'usable-snapped') {
            candidate.acceptedAfterRetry = candidate.acceptedAfterRetry || !!event.nearestRetrySuccess;
            candidate.acceptedAfterAdjustment = candidate.acceptedAfterAdjustment || !!event.candidateAdjusted;
        }
        if (Array.isArray(event.nearestStrategyAttempts)) {
            event.nearestStrategyAttempts.forEach((attempt) => {
                const stat = ensureStrategyStat(attempt?.strategy);
                stat.executed += 1;
                if (attempt?.nearestReturned) {
                    stat.nearestReturned += 1;
                } else {
                    stat.nearestNull += 1;
                }
            });
        }
    });

    Object.values(candidateMap).forEach((candidate) => {
        const strategyUsed = candidate.nearestStrategyUsed || (candidate.candidateAdjusted ? 'escape-adjusted-candidate' : 'point');
        const usedStat = ensureStrategyStat(strategyUsed);
        if (candidate.nearestRetrySuccess || candidate.acceptedAfterAdjustment) usedStat.success += 1;
        if (candidate.nodeBuildSuccess) usedStat.nodeBuildSuccess += 1;
        if (candidate.sideRoadContinuationDetectedAtSnap) usedStat.sideRoadContinuationDetected += 1;
        if (candidate.nearestAcceptedAsRescue) usedStat.acceptedAsRescue += 1;
        if (candidate.nearestRejectedReason === 'same-corridor') usedStat.rejectedAsMainlineOnly += 1;
        if (candidate.nearestRejectedReason === 'duplicate-snap') usedStat.rejectedAsDuplicate += 1;
        if (candidate.nearestRejectedReason === 'invalid-bearing') usedStat.rejectedAsInvalidBearing += 1;

        if (candidate.acceptedAfterRetry) breakdown.acceptedAfterRetryCount += 1;
        if (candidate.acceptedAfterAdjustment) breakdown.acceptedAfterAdjustmentCount += 1;
        if (candidate.nearestAcceptedAsRescue) breakdown.acceptedAsRescueCount += 1;
        if (candidate.nearestRejectedReason === 'same-corridor') breakdown.rejectedAsMainlineOnlyCount += 1;
        if (candidate.nearestRejectedReason === 'duplicate-snap') breakdown.rejectedAsDuplicateOnlyCount += 1;
        if (candidate.nearestRejectedReason === 'invalid-bearing') breakdown.rejectedAsInvalidBearingCount += 1;

        const detail = _deriveEscapeNearestDetail(candidate);
        if (candidate.firstAcceptedStrategy) {
            breakdown.acceptedAfterRetryByStrategy[candidate.firstAcceptedStrategy] = Number(breakdown.acceptedAfterRetryByStrategy[candidate.firstAcceptedStrategy] || 0) + 1;
            breakdown.firstWinningStrategyBreakdown[candidate.firstAcceptedStrategy] = Number(breakdown.firstWinningStrategyBreakdown[candidate.firstAcceptedStrategy] || 0) + 1;
        }
        if (candidate.firstNearestReturnedStrategy) {
            breakdown.nearestReturnedByStrategy[candidate.firstNearestReturnedStrategy] = Number(breakdown.nearestReturnedByStrategy[candidate.firstNearestReturnedStrategy] || 0) + 1;
        }
        if (candidate.allStrategiesNull) {
            const nullKey = candidate.strategyOrderUsed?.[0] || candidate.nearestStrategyUsed || 'retry-exhausted';
            breakdown.allNullByStrategy[nullKey] = Number(breakdown.allNullByStrategy[nullKey] || 0) + 1;
        }
        if (detail !== 'none') {
            breakdown.nearestNullAfterRetryCount += 1;
            ensureCount(breakdown.nearestNullAfterRetryDetails, detail);
            if (detail.includes('retry-strategy-exhausted')) ensureCount(breakdown.retryStrategyExhaustedDetails, detail);
            if (candidate.nearestReturnedButRejectedReason) ensureCount(breakdown.nearestReturnedButRejectedBreakdown, candidate.nearestReturnedButRejectedReason);
            if (candidate.nearestReturnedButRejectedReason === 'mainline-only') breakdown.nearestReturnedButRejectedAsMainlineOnly += 1;
            if (candidate.nearestReturnedButRejectedReason === 'no-side-road') breakdown.nearestReturnedButRejectedAsNoSideRoad += 1;
            if (candidate.nearestReturnedButRejectedReason === 'duplicate') breakdown.nearestReturnedButRejectedAsDuplicate += 1;
            ensureCount(breakdown.sideStats, candidate.side);
            ensureCount(breakdown.tierStats, Number.isFinite(Number(candidate.tier)) ? Number(candidate.tier) : 'unknown');
            ensureCount(breakdown.depthStats, candidate.depth || 'entrance');
            ensureCount(breakdown.positionCategoryStats, candidate.candidatePositionCategory || 'unknown');
            ensureCount(breakdown.bearingBucketStats, candidate.blockedBearingBucket || 'unknown');
            ensureCount(breakdown.corridorLengthBucketStats, candidate.corridorLengthBucket || 'unknown');
            ensureCount(breakdown.snapDistanceBucketStats, candidate.snapDistanceBucket || 'unknown');
            if (candidate.retryProfile === 'back-right-entrance') ensureCount(breakdown.backRightEntranceBreakdown, detail);
        }
    });

    breakdown.strategyStats = strategyStats;
    const comboCounts = {};
    Object.values(candidateMap).forEach((candidate) => {
        const detail = _deriveEscapeNearestDetail(candidate);
        if (detail === 'none') return;
        const combo = [
            detail,
            candidate.side || 'unknown',
            Number.isFinite(Number(candidate.tier)) ? Number(candidate.tier) : 'unknown',
            candidate.depth || 'entrance',
            candidate.candidatePositionCategory || 'unknown'
        ].join('|');
        comboCounts[combo] = Number(comboCounts[combo] || 0) + 1;
    });
    breakdown.topFailureCombos = Object.entries(comboCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 5)
        .map(([combo, count]) => ({ combo, count }));
    const firstWinningEntries = Object.entries(breakdown.acceptedAfterRetryByStrategy).sort((a, b) => b[1] - a[1]);
    breakdown.firstWinningStrategy = firstWinningEntries[0]?.[0] || 'none';
    breakdown.firstWinningStrategyStats = firstWinningEntries.reduce((acc, [strategy, count]) => {
        acc[strategy] = { acceptedAfterRetry: count };
        return acc;
    }, {});
    return breakdown;
}

function _deriveSnapEmptyPrimaryReason(modeStats = {}) {
    const stats = modeStats || {};
    const hasRetryFlow = Number(stats.nearestRetryCount || 0) > 0
        || Number(stats.nearestRetrySucceeded || 0) > 0
        || Number(stats.nearestRetryFailed || 0) > 0;
    const candidates = [
        [hasRetryFlow ? 'nearest-null-after-retry' : 'nearest-null', Number(stats.nearestNullCount || 0)],
        ['same-corridor', Number(stats.rejectSameCorridorCount || 0) + Number(stats.rejectSameCorridorSoftCount || 0)],
        ['inside-blocked-area', Number(stats.rejectInsideBlockedAreaCount || 0) + Number(stats.rejectInsideBlockedAreaSoftCount || 0)],
        ['too-far-from-candidate', Number(stats.rejectTooFarFromCandidateCount || 0)],
        ['low-corridor-score', Number(stats.rejectLowCorridorScoreCount || 0)],
        ['duplicate-snap', Number(stats.rejectDuplicateSnapCount || 0)],
        ['invalid-bearing', Number(stats.rejectInvalidBearingCount || 0)],
        ['node-build-failure', Number(stats.rejectNodeBuildFailureCount || 0)]
    ];
    const noUsableNodeCount = Number(stats.nearestSuccessCount || 0) > 0 && Number(stats.usableRouteCandidateCount || 0) === 0
        ? Math.max(1, Number(stats.usableSnappedCount || 0), Number(stats.nearestSuccessCount || 0) - Number(stats.usableRouteCandidateCount || 0))
        : 0;
    candidates.push(['no-usable-node', noUsableNodeCount]);
    candidates.sort((a, b) => b[1] - a[1]);
    return candidates[0]?.[1] > 0 ? candidates[0][0] : 'none';
}

function _buildSnapEmptyReasonBreakdown(modeStats = {}) {
    const stats = modeStats || {};
    const hasRetryFlow = Number(stats.nearestRetryCount || 0) > 0
        || Number(stats.nearestRetrySucceeded || 0) > 0
        || Number(stats.nearestRetryFailed || 0) > 0;
    return {
        'nearest-null': hasRetryFlow ? 0 : Number(stats.nearestNullCount || 0),
        'nearest-null-after-retry': hasRetryFlow ? Number(stats.nearestNullCount || 0) : 0,
        'same-corridor': Number(stats.rejectSameCorridorCount || 0),
        'same-corridor-soft': Number(stats.rejectSameCorridorSoftCount || 0),
        'inside-blocked-area': Number(stats.rejectInsideBlockedAreaCount || 0),
        'inside-blocked-area-soft': Number(stats.rejectInsideBlockedAreaSoftCount || 0),
        'too-far-from-candidate': Number(stats.rejectTooFarFromCandidateCount || 0),
        'low-corridor-score': Number(stats.rejectLowCorridorScoreCount || 0),
        'duplicate-snap': Number(stats.rejectDuplicateSnapCount || 0),
        'invalid-bearing': Number(stats.rejectInvalidBearingCount || 0),
        'node-build-failure': Number(stats.rejectNodeBuildFailureCount || 0),
        'no-usable-node': Number(stats.nearestSuccessCount || 0) > 0 && Number(stats.usableRouteCandidateCount || 0) === 0
            ? Math.max(1, Number(stats.usableSnappedCount || 0), Number(stats.nearestSuccessCount || 0) - Number(stats.usableRouteCandidateCount || 0))
            : 0
    };
}

function _markSnapEmptyFailure(mode) {
    const collector = _blockAheadPerfMetrics?.snapDebugCollector;
    if (!collector || !mode) return null;
    const modeKey = _normalizeSnapDebugKey(mode);
    const modeStats = collector.modeStats?.[modeKey] || _createSnapDebugBucket();
    const primaryReason = _deriveSnapEmptyPrimaryReason(modeStats);
    const breakdown = _buildSnapEmptyReasonBreakdown(modeStats);
    collector.snapEmptyFailureMode = modeKey;
    collector.snapEmptyPrimaryReason = primaryReason;
    collector.snapEmptyReasonBreakdown = breakdown;
    return { mode: modeKey, primaryReason, breakdown };
}

function _summarizeSnapDebugCollector(collector) {
    if (!collector) {
        return {
            snapDiagnostics: {
                events: [],
                modeStats: {},
                sideStats: {},
                tierStats: {},
                depthStats: {},
                retryStats: { nearestRetryCount: 0, nearestRetrySucceeded: 0, nearestRetryFailed: 0 },
                escapeRetryStats: { nearestRetryCount: 0, nearestRetrySucceeded: 0, nearestRetryFailed: 0 },
                escapeRetrySuccessByStrategy: {},
                escapeRetryFailureByStrategy: {},
                escapeCandidateAdjustmentStats: {},
                escapeNearestNullReasons: {},
                escapeNearestAcceptedAfterAdjustment: 0,
                escapeNearestAcceptedAfterRetry: 0,
                escapeNearestDetailBreakdown: {},
                escapeStrategyStats: {},
                escapeNearestBreakdown: _createEscapeNearestBreakdown(),
                sameCorridorStats: _createSnapDecisionBucket(),
                insideBlockedStats: _createSnapDecisionBucket(),
                modePrimaryReasons: {}
            },
            snapEmptyPrimaryReason: 'none',
            snapEmptyReasonBreakdown: {},
            snapEmptyFailureMode: null
        };
    }
    const modePrimaryReasons = {};
    Object.entries(collector.modeStats || {}).forEach(([mode, stats]) => {
        modePrimaryReasons[mode] = _deriveSnapEmptyPrimaryReason(stats);
    });
    const escapeNearestBreakdown = _buildEscapeNearestBreakdown(collector);
    return {
        snapDiagnostics: {
            events: Array.isArray(collector.events) ? collector.events.slice() : [],
            modeStats: { ...(collector.modeStats || {}) },
            sideStats: { ...(collector.sideStats || {}) },
            tierStats: { ...(collector.tierStats || {}) },
            depthStats: { ...(collector.depthStats || {}) },
            retryStats: { ...(collector.retryStats || {}) },
            escapeRetryStats: { ...(collector.escapeRetryStats || {}) },
            escapeRetrySuccessByStrategy: { ...(collector.escapeRetrySuccessByStrategy || {}) },
            escapeRetryFailureByStrategy: { ...(collector.escapeRetryFailureByStrategy || {}) },
            escapeCandidateAdjustmentStats: { ...(collector.escapeCandidateAdjustmentStats || {}) },
            escapeNearestNullReasons: { ...(collector.escapeNearestNullReasons || {}) },
            escapeNearestAcceptedAfterAdjustment: Number(collector.escapeNearestAcceptedAfterAdjustment || 0),
            escapeNearestAcceptedAfterRetry: Number(collector.escapeNearestAcceptedAfterRetry || 0),
            escapeNearestDetailBreakdown: { ...(collector.escapeNearestDetailBreakdown || {}) },
            escapeStrategyStats: { ...(collector.escapeStrategyStats || {}) },
            escapeNearestBreakdown,
            sameCorridorStats: { ...(collector.sameCorridorStats || {}) },
            insideBlockedStats: { ...(collector.insideBlockedStats || {}) },
            modePrimaryReasons,
            escapeModePrimaryReasons: Object.fromEntries(
                Object.entries(modePrimaryReasons).filter(([mode]) => mode === 'escape')
            )
        },
        snapEmptyPrimaryReason: collector.snapEmptyPrimaryReason || 'none',
        snapEmptyReasonBreakdown: { ...(collector.snapEmptyReasonBreakdown || {}) },
        snapEmptyFailureMode: collector.snapEmptyFailureMode || null
    };
}

function _buildBlockAheadDebugSummary(summary = {}, extras = {}) {
    const selectedRoute = extras.route || navActiveRoute || null;
    const ped = extras.pedestrianSafety || selectedRoute?.__pedestrianSafety || {};
    const candidatePed = extras.candidatePedestrianSafety || selectedRoute?.__candidatePedestrianSafety || {};
    const blocked = extras.blockedAreaStats || {};
    const snapSummary = extras.snapSummary || _summarizeSnapDebugCollector(_blockAheadPerfMetrics?.snapDebugCollector);
    const stageStats = Array.isArray(_blockAheadPerfMetrics?.stages) ? _blockAheadPerfMetrics.stages : [];
    const candidateCountByStage = {};
    const acceptedCountByStage = {};
    stageStats.forEach(stage => {
        if (!stage?.key) return;
        candidateCountByStage[stage.key] = Number(stage.alternatives || 0);
        acceptedCountByStage[stage.key] = Number(stage.meaningful || stage.nonBlocked || 0);
    });
    return {
        success: !!summary.accepted,
        status: summary.status || 'unknown',
        selectedStage: summary.acceptedStage || extras.selectedStage || null,
        selectedNodeId: extras.selectedNodeId || selectedRoute?.__escapeLabel || null,
        selectedDistance: Number(extras.selectedDistance ?? selectedRoute?.totalDistance ?? selectedRoute?.summary?.totalDistance ?? 0),
        pedestrianSafety: {
            status: ped.status || 'unknown',
            contextUnavailable: !!ped.contextUnavailable,
            contextSource: ped.contextSource || 'unknown',
            contextFailureKind: ped.contextFailureKind || 'none',
            contextFailureDetail: ped.contextFailureDetail || 'none',
            failOpenApplied: !!ped.failOpenApplied,
            conservativeDecision: ped.conservativeDecision || 'pass',
            conservativeReason: ped.conservativeRejectReason || 'none',
            conservativePenalty: Number(ped.conservativePenalty || 0)
        },
        candidatePedestrianSafety: {
            status: candidatePed.status || 'unknown',
            contextUnavailable: !!candidatePed.contextUnavailable,
            contextSource: candidatePed.contextSource || 'unknown',
            contextFailureKind: candidatePed.contextFailureKind || 'none',
            contextFailureDetail: candidatePed.contextFailureDetail || 'none',
            failOpenApplied: !!candidatePed.failOpenApplied,
            conservativeDecision: candidatePed.conservativeDecision || 'pass',
            conservativeReason: candidatePed.conservativeRejectReason || 'none',
            conservativePenalty: Number(candidatePed.conservativePenalty || 0)
        },
        blockedAreaStats: {
            overlap: Number(blocked.overlap || 0),
            strict: Number(blocked.strict || 0),
            near: Number(blocked.near || 0),
            hardIntersectionDetected: !!blocked.hardIntersectionDetected,
            rejectReason: blocked.rejectReason || 'accepted',
            mode: blocked.mode || extras.selectedStage || null,
            side: blocked.side || selectedRoute?.__blockedSide || null,
            nearPenaltyMode: !!blocked.nearPenaltyMode,
            acceptedByNearPenaltyMode: !!blocked.acceptedByNearPenaltyMode
        },
        expectationsView: {
            avoidsBlockedArea: Number(blocked.overlap || 0) < BLOCK_OVERLAP_REJECT,
            dangerousCrossingRejected: ped.status === 'unsafe',
            finalConservativeHardReject: ped.conservativeDecision === 'hard-reject'
        },
        invariantResults: extras.invariantResults || {},
        failedInvariantIds: Array.isArray(extras.failedInvariantIds) ? extras.failedInvariantIds : [],
        candidateCountByStage,
        acceptedCountByStage,
        rejectReasonsSummary: { ...((_blockAheadPerfMetrics && _blockAheadPerfMetrics.rejectReasons) || {}) },
        allAcceptedCandidates: Array.isArray(extras.allAcceptedCandidates) ? extras.allAcceptedCandidates : [],
        snapDiagnostics: snapSummary.snapDiagnostics,
        modeStats: snapSummary.snapDiagnostics.modeStats,
        sideStats: snapSummary.snapDiagnostics.sideStats,
        tierStats: snapSummary.snapDiagnostics.tierStats,
        depthStats: snapSummary.snapDiagnostics.depthStats,
        snapEmptyPrimaryReason: snapSummary.snapEmptyPrimaryReason,
        snapEmptyReasonBreakdown: snapSummary.snapEmptyReasonBreakdown,
        snapEmptyFailureMode: snapSummary.snapEmptyFailureMode
    };
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

// ── GPS 精度ラベル変換 ────────────────────────────────────────────────────
function _fmtAccuracy(meters) {
    if (!Number.isFinite(meters) || meters <= 0) return null;
    return `±${Math.round(meters)}m`;
}

// ── 現在地情報（ハザード+標高+精度）を下部バーに表示 ─────────────────────────
// watchPosition コールバック・route_preview 移行時に呼ぶ。
function fetchCurrentLocInfo(lat, lon, elevation, accuracyMeters) {
    const rowHazard = document.getElementById('mbc-row-hazard');
    if (rowHazard) rowHazard.style.display = '';

    // 非ナビ時の現在地情報パネルを更新
    if (typeof _lipUpdate === 'function') _lipUpdate(lat, lon, accuracyMeters);

    // 標高表示
    const elevEl = document.getElementById('mbc-current-elev');
    if (elevEl) {
        if (elevation != null) {
            elevEl.textContent = `標高 ${Number(elevation).toFixed(0)}m`;
            if (typeof _lipUpdateElev === 'function') _lipUpdateElev(Number(elevation));
        } else {
            elevEl.textContent = '—';
            _fetchElevation(lat, lon).then(elev => {
                if (elev !== null && elevEl) elevEl.textContent = `標高 ${elev.toFixed(0)}m`;
                if (elev !== null && typeof _lipUpdateElev === 'function') _lipUpdateElev(elev);
            });
        }
    }

    // 精度表示（常時表示・display トグルなし）
    const accEl = document.getElementById('mbc-current-accuracy');
    if (accEl) {
        const accLabel = _fmtAccuracy(accuracyMeters);
        accEl.textContent = accLabel ? `精度${accLabel}` : '—';
    }

    const hazardEl = document.getElementById('mbc-current-hazard');
    if (hazardEl) {
        hazardEl.textContent = '確認中...';
        hazardEl.className   = 'mbc-status-cell mbc-status-hazard';
    }
    if (typeof requestCurrentLocationReverseGeocode === 'function') {
        requestCurrentLocationReverseGeocode(lat, lon);
    }
    _checkCurrentHazard(lat, lon);
    if (typeof _weatherUpdate === 'function') _weatherUpdate(lat, lon);
}

// ── 現在地ハザードチェック ──────────────────────────────────────────────────
async function _checkCurrentHazard(lat, lon) {
    try {
        const res = await apiFetch(`/hazard-check?lat=${lat}&lon=${lon}`);
        if (!res.ok) return;
        const data = await res.json();
        _updateHazardRow(data.is_danger, data.hazard_assessment);
        if (typeof _lipUpdateHazard === 'function') _lipUpdateHazard(data.hazard_assessment);
    } catch {
        // ネットワークエラー等は無視
    }
}

function _updateHazardRow(isDanger, assessment) {
    const el = document.getElementById('mbc-current-hazard');
    if (!el) return;
    el.className = 'mbc-status-cell mbc-status-hazard';
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
    const labelText = dangerLabels.length > 0 ? dangerLabels.join('/') : '危険';
    el.innerHTML = `<span class="mbc-hazard-danger">⚠ ${labelText}</span>`;
}

// ── 距離フォーマット（ナビ用） ────────────────────────────────────────────
function _fmtNavDist(meters) {
    if (!Number.isFinite(meters)) return '—';
    if (meters < 30) return `${Math.round(meters)}m`;
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
        const distToDestination = navDestination
            ? _navHaversine(lat, lon, navDestination.lat, navDestination.lon)
            : null;
        const isNearGoal = distToDestination !== null && distToDestination <= _getNearGoalDistanceM();
        const offRouteThresholdM = _getOffRouteThresholdM(isNearGoal);
        if (accuracy > NAV_MAX_GPS_ACCURACY_M) {
            offsetEl.textContent = '';
        } else if (routeResult.routeOffsetMeters >= offRouteThresholdM
                && navigationMode === 'navigation_warning') {
            offsetEl.textContent = '| 再ルートが必要です';
        } else {
            offsetEl.textContent = '';
        }
    }

    if (typeof _navSheetUpdateDistance === 'function') _navSheetUpdateDistance(routeResult);
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
    _resetNavArrivalTracking();
    navIsAutoFollow               = true;
    _setNavAutoRerouteInProgress(false, 'navigation-start');
    navAutoRerouteSuspended       = false;
    navAutoRerouteCount           = 0;
    navAutoRerouteWindowStartedAt = 0;
    navLastAutoRerouteAt          = 0;
    navOffRouteSkipUntilMs        = Date.now() + NAV_START_GRACE_PERIOD_MS;
    // コンパス初期化（iOS はユーザー操作後でないと許可ダイアログが出ないためここで呼ぶ）
    if (typeof initOrientation === 'function') initOrientation();
    // 開始地点の標高を取得
    navStartElevation     = null;
    navCurrentElevation   = null;
    navLastElevFetchPos   = null;
    navLastHazardFetchPos = null;
    const hazardEl = document.getElementById('mbc-current-hazard');
    if (hazardEl) {
        hazardEl.textContent = '確認中...';
        hazardEl.className   = 'mbc-status-cell mbc-status-hazard';
    }
    if (currentLocation) {
        _fetchElevation(currentLocation.lat, currentLocation.lon).then(elev => {
            navStartElevation   = elev;
            navCurrentElevation = elev; // 初期標高をナビシートにも反映
            navLastElevFetchPos = { lat: currentLocation.lat, lon: currentLocation.lon };
            if (typeof _navSheetUpdateElev === 'function') _navSheetUpdateElev();
        });
        _checkCurrentHazard(currentLocation.lat, currentLocation.lon);
        navLastHazardFetchPos = { lat: currentLocation.lat, lon: currentLocation.lon };
    }

    navWatchId = navigator.geolocation.watchPosition(
        _onNavPosition,
        _onNavPositionError,
        { enableHighAccuracy: true, maximumAge: 3000, timeout: 10000 }
    );
    // 常時追跡も高精度モードに切り替え
    if (typeof _gpsWatchId !== 'undefined' && _gpsWatchId !== null) {
        navigator.geolocation.clearWatch(_gpsWatchId);
        _gpsWatchId = null;
    }
    if (typeof _startLocationWatch === 'function') _startLocationWatch(true);
    setNavMode('navigation_active');

    // ナビシート表示後すぐに可視領域中央へセンタリング（GPS コールバックを待たない）
    if (currentLocation) {
        _navCenterOnGPS(currentLocation.lat, currentLocation.lon);
    }

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
        voiceNav.unlockSpeech(); // iOS Safari 音声ロック解除（ユーザー操作タイミング）
        voiceNav.announce({ id: 'nav-start', text: '避難経路の案内を開始します', category: 'start', priority: 'high' });
    }
    // タブ自動遷移は行わない（ユーザーが手動で情報タブに切り替える）
}

// ── ナビ停止 ──────────────────────────────────────────────────────────────
function stopNavigation() {
    if (navWatchId !== null) {
        navigator.geolocation.clearWatch(navWatchId);
        navWatchId = null;
    }
    // 常時追跡を低精度モードに戻す
    if (typeof _gpsWatchId !== 'undefined' && _gpsWatchId !== null) {
        navigator.geolocation.clearWatch(_gpsWatchId);
        _gpsWatchId = null;
    }
    if (typeof _startLocationWatch === 'function') _startLocationWatch(false);
    navOffRouteCount         = 0;
    navArrivalConsecutiveCount = 0;
    _setNavRerouteInProgress(false, 'navigation-stop');
    _setNavAutoRerouteInProgress(false, 'navigation-stop');
    navBlockAheadInProgress  = false;
    ++_blockAheadSeq; // pending callback を無効化（非同期完了後の復帰を防ぐ）
    navStartElevation        = null;
    navCurrentElevation      = null;
    navLastElevFetchPos      = null;
    navLastHazardFetchPos    = null;
    if (_offRouteDebounceTimer !== null) {
        clearTimeout(_offRouteDebounceTimer);
        _offRouteDebounceTimer = null;
    }
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
    if (typeof _lipClearRouteSelection === 'function') {
        _lipClearRouteSelection();
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
function onNavRouteSelected(route, destination, meta = {}) {
    if (route) navActiveRoute = route;
    if (destination) {
        navDestination = destination;
        if (!navOriginalDestination) navOriginalDestination = destination;
    }
    if (typeof _lipUpdateRouteSelection === 'function') {
        _lipUpdateRouteSelection({
            route: route === null ? null : (route || navActiveRoute || null),
            destination: destination || navDestination || navOriginalDestination || null,
            selectedRouteIndex: meta.selectedRouteIndex,
            transportMode: meta.transportMode,
            routes: meta.routes,
            routeColors: meta.routeColors,
            onSelectRouteIndex: meta.onSelectRouteIndex,
            mode: meta.infoMode || (
                navigationMode === 'browse' || navigationMode === 'navigation_finished'
                    ? 'route_preview'
                    : 'navigation_active'
            )
        });
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

    const rerouteStartedAt = _perfNowMs();
    _addNavigationDebugEvent('reroute_start', 'reroute start', {
        reason: 'manual_same_destination',
        near_goal: false
    });
    _navDebugLog('reroute:start reason=manual_same_destination near_goal=false');
    _setNavRerouteInProgress(true, 'manual-start');
    navLastRerouteAt     = Date.now();
    _updateNavUI();
    _showNavBanner('🔄 現在地からルートを再計算しています...', 'info');

    // 古いルートレイヤーを消してから再描画
    if (typeof clearRouteCandidateLayers === 'function') clearRouteCandidateLayers();
    if (typeof clearSelectedRouteHighlight === 'function') clearSelectedRouteHighlight();

    const finishReroute = _createRerouteWatchdog({
        auto: false,
        startedAt: rerouteStartedAt,
        onTimeout: () => _showNavBanner('⚠ 再ルートがタイムアウトしました。もう一度お試しください。', 'danger')
    });

    try {
        drawRouteTo(navDestination.lat, navDestination.lon, {
            onRoutesAvailable: ({ routes, selectedRouteIndex, routeColors, formatter, transportMode, selectRouteIndex }) => {
                if (!finishReroute()) return;
                if (!routes || !routes[selectedRouteIndex]) {
                    _navDebugLog('reroute:failed reason=invalid-route');
                    _completeReroute({ auto: false, success: false, reason: 'manual-invalid-route', startedAt: rerouteStartedAt });
                    return;
                }
                _resetNavigationStateOnReroute();
                navActiveRoute       = routes[selectedRouteIndex];
                const _stepCount = navActiveRoute?.legs?.[0]?.steps?.length ?? '?';
                _navDebugLog(`reroute:new route applied steps=${_stepCount}`);
                if (typeof onNavRouteSelected === 'function') {
                    onNavRouteSelected(routes[selectedRouteIndex], null, {
                        selectedRouteIndex,
                        transportMode,
                        routes,
                        routeColors,
                        onSelectRouteIndex: selectRouteIndex,
                        infoMode: 'navigation_active'
                    });
                }
                navOffRouteCount     = 0;
                if (_offRouteDebounceTimer !== null) {
                    clearTimeout(_offRouteDebounceTimer);
                    _offRouteDebounceTimer = null;
                }
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
                _completeReroute({ auto: false, success: true, reason: 'manual-success', startedAt: rerouteStartedAt });
            },
            onRouteError: () => {
                if (!finishReroute()) return;
                _showNavBanner('⚠ 同じ避難先へのルートが見つかりません。別の避難先を再検索してください。', 'danger');
                _completeReroute({ auto: false, success: false, reason: 'manual-route-error', startedAt: rerouteStartedAt });
            }
        });
    } catch (err) {
        finishReroute();
        console.warn('[navigation] reroute:exception', err);
        _showNavBanner('⚠ 再ルート中にエラーが発生しました。もう一度お試しください。', 'danger');
        _completeReroute({ auto: false, success: false, reason: 'manual-exception', startedAt: rerouteStartedAt });
    }
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
    let distToGoal = null;
    let nearGoal = false;

    // 到達判定（移動量チェック・精度チェックより前に必ず実施）
    if (navDestination && !navHasArrived) {
        const destinationDist = _navHaversine(lat, lon, navDestination.lat, navDestination.lon);
        const endpointDist = _distanceToRouteEndpoint(lat, lon);
        distToGoal = endpointDist === null ? destinationDist : Math.min(destinationDist, endpointDist);
        nearGoal = distToGoal <= _getNearGoalDistanceM();
        const nearArrival = distToGoal <= _getNavigationConfigNumber('navigation.near_arrival_distance', NAV_NEAR_ARRIVAL_M);
        if (nearArrival && !_navNearArrival) {
            _showNavBanner('まもなく到着です', 'info', 3000);
        }
        _navNearArrival = nearArrival;
        const gpsUnstable = _updateArrivalStability(distToGoal, accuracy);
        if (gpsUnstable) {
            _showNavBanner('位置精度が低い可能性があります', 'warning', 3000);
        }
        const arrivalRequirement = _getArrivalRequirement(accuracy);
        const arrivalCandidate = distToGoal <= arrivalRequirement.radiusM;
        navArrivalConsecutiveCount = arrivalCandidate ? navArrivalConsecutiveCount + 1 : 0;
        const arrived = navArrivalConsecutiveCount >= arrivalRequirement.consecutive;
        console.log(
            `[arrival] dist=${Math.round(distToGoal)} accuracy=${Math.round(Number(accuracy || 0))} ` +
            `radius=${Math.round(arrivalRequirement.radiusM)} near=${nearArrival} ` +
            `counter=${navArrivalConsecutiveCount} arrived=${arrived} gpsUnstable=${gpsUnstable}`
        );
        _navDebugLog(
            `dist_to_goal=${distToGoal.toFixed(1)}m accuracy=${accuracy.toFixed(1)}m ` +
            `arrival_counter=${navArrivalConsecutiveCount} near_arrival=${nearArrival} arrived=${arrived} ` +
            `arrival_radius=${arrivalRequirement.radiusM} low_accuracy=${arrivalRequirement.lowAccuracy}`,
            {
                dist_to_goal: Number(distToGoal.toFixed(1)),
                accuracy: Number(accuracy.toFixed(1)),
                arrival_counter: navArrivalConsecutiveCount,
                near_arrival: nearArrival,
                arrived,
                arrival_radius: arrivalRequirement.radiusM,
                low_accuracy: arrivalRequirement.lowAccuracy,
                gps_unstable: gpsUnstable
            }
        );

        if (arrived) {
            _addNavigationDebugEvent('arrival_detected', 'arrival detected', {
                distance_to_goal: Number(distToGoal.toFixed(1)),
                arrival_counter: navArrivalConsecutiveCount
            }, { lat, lon });
            _navDebugLog('arrival:confirmed', {
                dist_to_goal: Number(distToGoal.toFixed(1)),
                accuracy: Number(accuracy.toFixed(1)),
                arrival_counter: navArrivalConsecutiveCount
            });
            _onNavArrival();
            return;
        }
    } else if (navDestination) {
        distToGoal = _navHaversine(lat, lon, navDestination.lat, navDestination.lon);
        nearGoal = distToGoal <= _getNearGoalDistanceM();
    }

    // 微小移動フィルタ: 地図描画・重いUI更新は間引くが逸脱判定・ステップ同期は常に実行
    let _doFullUpdate = true;
    if (currentLocation) {
        const moved = _navHaversine(currentLocation.lat, currentLocation.lon, lat, lon);
        console.log(`[gps] lat=${lat.toFixed(6)} lon=${lon.toFixed(6)} ts=${new Date().toISOString()} moved=${moved.toFixed(1)}m accuracy=${accuracy.toFixed(1)}m`);
        if (moved < NAV_MIN_DELTA_M && !_navNearArrival && !_navGpsUnstable) {
            console.log(`[gps] skip-ui moved=${moved.toFixed(1)}m < min_delta=${NAV_MIN_DELTA_M}m nearArrival=${_navNearArrival} gpsUnstable=${_navGpsUnstable}`);
            _doFullUpdate = false;
        }
    } else {
        console.log(`[gps] lat=${lat.toFixed(6)} lon=${lon.toFixed(6)} ts=${new Date().toISOString()} accuracy=${accuracy.toFixed(1)}m first_fix`);
    }

    if (_doFullUpdate) {
        _updateNavMarker(lat, lon, accuracy, heading);
    }

    // 精度は常に保存（_doFullUpdate 外・静止中も最新値を維持）
    navLastKnownAccuracy = accuracy;

    // 精度表示（1秒スロットル・テキスト差し替えのみ）
    if (_doFullUpdate) {
        const _nowAcc = Date.now();
        if (_nowAcc - _statusBarLastUpdateAt >= NAV_STATUS_BAR_THROTTLE) {
            _statusBarLastUpdateAt = _nowAcc;
            const _accEl = document.getElementById('mbc-current-accuracy');
            if (_accEl) {
                const _accLabel = _fmtAccuracy(accuracy);
                const _newText = _accLabel ? `精度${_accLabel}` : '—';
                if (_accEl.textContent !== _newText) _accEl.textContent = _newText;
            }
            if (typeof _navSheetUpdateElev === 'function') _navSheetUpdateElev();
        }
    }

    // オートフォロー: _doFullUpdate の外（微小移動でも毎回センタリング）
    // ナビ開始直後は stationary でも正しい可視領域中央に表示する必要があるため
    if (navIsAutoFollow) {
        _navCenterOnGPS(lat, lon);
    }

    // 音声優先順位用コンテキスト: 横断案内をターン案内より優先する
    if (typeof voiceNav !== 'undefined' &&
        (navigationMode === 'navigation_active' || navigationMode === 'navigation_warning')) {
        voiceNav.setInstructionContext({ lat, lon }, navActiveRoute);
    }

    // 経路ステップハイライト更新（精度に関わらず実施）
    if (typeof updateNavStepHighlight === 'function') {
        updateNavStepHighlight(lat, lon);
        if (typeof _navSheetUpdateStep === 'function') _navSheetUpdateStep(lat, lon);
    }

    // 接近通知: 次の操作/横断を音声案内（voiceNav があれば）
    // navigation_warning（逸脱中）でも目的地接近は案内する
    if (typeof voiceNav !== 'undefined' &&
        (navigationMode === 'navigation_active' || navigationMode === 'navigation_warning')) {
        voiceNav.checkNextInstruction({ lat, lon }, navActiveRoute);
    }

    // 残距離・逸脱ステータス更新（共通関数）
    const routeResult = _updateRemainingDistanceDisplay(lat, lon, accuracy);
    const offsetEl    = document.getElementById('mbc-offset-status');

    // 現在標高更新（NAV_ELEV_UPDATE_M 以上移動した場合のみAPIを叩く）
    if (_doFullUpdate && (!navLastElevFetchPos ||
            _navHaversine(navLastElevFetchPos.lat, navLastElevFetchPos.lon, lat, lon) >= NAV_ELEV_UPDATE_M)) {
        navLastElevFetchPos = { lat, lon };
        _fetchElevation(lat, lon).then(elev => {
            if (elev === null) return;
            navCurrentElevation = elev;
            const el = document.getElementById('mbc-current-elev');
            if (el) el.textContent = `標高 ${elev.toFixed(0)}m`;
            if (typeof _navSheetUpdateElev === 'function') _navSheetUpdateElev();
        });
    }

    // 現在地ハザード更新（NAV_HAZARD_UPDATE_M 以上移動した場合のみAPIを叩く）
    if (_doFullUpdate && (!navLastHazardFetchPos ||
            _navHaversine(navLastHazardFetchPos.lat, navLastHazardFetchPos.lon, lat, lon) >= NAV_HAZARD_UPDATE_M)) {
        navLastHazardFetchPos = { lat, lon };
        _checkCurrentHazard(lat, lon);
    }

    // GPS 精度警告（バナー表示のみ、逸脱判定はスキップしない）
    if (_doFullUpdate && accuracy > NAV_LOW_ACCURACY_M) {
        _showNavBanner('⚠ 位置情報の精度が低下しています（±' + Math.round(accuracy) + 'm）', 'warning');
    }

    // 逸脱判定（再ルート処理中・クールダウン中はスキップ、精度条件は除去）
    // routeResult != null で undefined も弾く（undefined !== null は true になるバグ対策）
    if (navActiveRoute && !navHasArrived && !navRerouteInProgress && !navAutoRerouteInProgress
            && Date.now() >= navOffRouteSkipUntilMs
            && routeResult != null) {
        const offsetM = routeResult.routeOffsetMeters;
        if (distToGoal === null && navDestination) {
            distToGoal = _navHaversine(lat, lon, navDestination.lat, navDestination.lon);
        }
        nearGoal = distToGoal !== null && distToGoal <= _getNearGoalDistanceM();
        const offRouteThresholdM = _getOffRouteThresholdM(nearGoal);
        const offRoute = offsetM >= offRouteThresholdM;
        console.log(`[off-route] dist=${offsetM.toFixed(1)} threshold=${offRouteThresholdM} accuracy=${accuracy.toFixed(1)} effective_threshold=${offRouteThresholdM} off_route=${offRoute} count=${navOffRouteCount} nearGoal=${nearGoal}`);
        _navDebugLog(
            `off_route_distance=${offsetM.toFixed(1)}m threshold=${offRouteThresholdM}m ` +
            `near_goal=${nearGoal} off_route=${offRoute} accuracy=${accuracy.toFixed(1)}m`,
            {
                off_route_distance: Number(offsetM.toFixed(1)),
                threshold: offRouteThresholdM,
                near_goal: nearGoal,
                off_route: offRoute,
                accuracy: Number(accuracy.toFixed(1))
            }
        );
        if (offRoute) {
            if (navOffRouteCount === 0) {
                _addNavigationDebugEvent('offroute_detected', `offroute detected distance=${offsetM.toFixed(1)}m`, {
                    off_route_distance: Number(offsetM.toFixed(1)),
                    threshold: offRouteThresholdM,
                    near_goal: nearGoal
                }, { lat, lon });
            }
            navOffRouteCount++;
            console.log(`[off-route] off_route=true count=${navOffRouteCount} required=${NAV_CONSECUTIVE}`);
            // ① 連続 N 回カウント判定（即時 warning 遷移用）
            if (navOffRouteCount >= NAV_CONSECUTIVE) {
                if (navigationMode === 'navigation_active') {
                    setNavMode('navigation_warning');
                    _showNavBanner('⚠ ルートから外れました。自動で見直しています...', 'danger');
                    if (typeof voiceNav !== 'undefined') {
                        voiceNav.announce({ id: 'nav-off-route', text: 'ルートから外れています', category: 'warning', priority: 'high' });
                    }
                }
            }
            // ② デバウンス方式：3秒後もまだ逸脱していたら再ルートを実行
            if (offsetM >= offRouteThresholdM && _offRouteDebounceTimer === null) {
                console.log(`[reroute] debounce_start debounce=${NAV_OFF_ROUTE_DEBOUNCE_MS}ms count=${navOffRouteCount}`);
                const _capturedAccuracy = accuracy;
                const _capturedNearGoal = nearGoal;
                _offRouteDebounceTimer = setTimeout(() => {
                    _offRouteDebounceTimer = null;
                    // 到着確定前なら目的地近傍でも再ルートを許可する
                    if (navOffRouteCount >= NAV_CONSECUTIVE &&
                            !navHasArrived && !navRerouteInProgress && !navAutoRerouteInProgress) {
                        console.log(`[reroute] start reason=off_route count=${navOffRouteCount} nearGoal=${_capturedNearGoal}`);
                        _tryAutoReroute(_capturedAccuracy, {
                            reason: 'off_route',
                            nearGoal: _capturedNearGoal
                        });
                    } else {
                        console.log(`[reroute] debounce_skip count=${navOffRouteCount} required=${NAV_CONSECUTIVE} arrived=${navHasArrived} rerouting=${navRerouteInProgress} autoRerouting=${navAutoRerouteInProgress}`);
                    }
                }, NAV_OFF_ROUTE_DEBOUNCE_MS);
            }
        } else {
            // ルートに戻った → カウントとデバウンスタイマーをリセット
            if (navOffRouteCount > 0) {
                navOffRouteCount = 0;
                if (_offRouteDebounceTimer !== null) {
                    clearTimeout(_offRouteDebounceTimer);
                    _offRouteDebounceTimer = null;
                }
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
    } else if (navActiveRoute && !navHasArrived && routeResult != null) {
        const _cooldownRemMs = Math.max(0, navOffRouteSkipUntilMs - Date.now());
        console.log(`[off-route] guard rerouting=${navRerouteInProgress} autoRerouting=${navAutoRerouteInProgress} arrived=${navHasArrived} cooldown_remain=${_cooldownRemMs}ms`);
    }

}

// ── Phase 4-A: オート再ルート判定 ────────────────────────────────────────
function _tryAutoReroute(accuracy, context = {}) {
    if (!navAutoRerouteEnabled) {
        console.log('[reroute] skip reason=disabled');
        return;
    }
    if (navHasArrived) {
        console.log('[reroute] skip reason=arrived');
        _navDebugLog('reroute:skip reason=arrived');
        return;
    }
    if (navAutoRerouteSuspended) {
        console.log('[reroute] skip reason=suspended');
        _navDebugLog('reroute:skip reason=suspended');
        return;
    }
    if (navAutoRerouteInProgress || navRerouteInProgress) {
        console.log(`[reroute] skip reason=in_progress autoRerouting=${navAutoRerouteInProgress} rerouting=${navRerouteInProgress}`);
        _navDebugLog('reroute:skip reason=in_progress');
        return;
    }

    const now = Date.now();

    // クールダウン（config から取得、デフォルト15秒）
    if (now - navLastAutoRerouteAt < _getAutoRerouteCooldownMs()) {
        const _cdRemMs = _getAutoRerouteCooldownMs() - (now - navLastAutoRerouteAt);
        const _lastAt  = navLastAutoRerouteAt ? new Date(navLastAutoRerouteAt).toISOString() : 'never';
        console.log(`[reroute] skip reason=cooldown remain=${Math.round(_cdRemMs / 1000)}s last=${_lastAt}`);
        _navDebugLog('reroute:skip reason=cooldown');
        return;
    }

    if (!navDestination) {
        console.log('[reroute] skip reason=no_destination');
        _navDebugLog('reroute:skip reason=no_destination');
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
        // 3分後に自動リセット
        setTimeout(() => {
            if (navAutoRerouteSuspended) {
                navAutoRerouteSuspended = false;
                navAutoRerouteCount     = 0;
                navAutoRerouteWindowStartedAt = 0;
                console.log('[Nav] auto-reroute suspension reset');
                _showNavBanner('🔄 自動再ルートを再開しました', 'info', 3000);
                _updateNavUI();
            }
        }, NAV_AUTO_REROUTE_SUSPEND_RESET_MS);
        return;
    }

    _executeAutoReroute(context);
}

function _executeAutoReroute(context = {}) {
    const rerouteStartedAt = _perfNowMs();
    _addNavigationDebugEvent('reroute_start', 'reroute start', {
        reason: context.reason || 'auto',
        near_goal: !!context.nearGoal
    });
    _navDebugLog(`reroute:start reason=${context.reason || 'auto'} near_goal=${!!context.nearGoal}`, {
        reason: context.reason || 'auto',
        near_goal: !!context.nearGoal
    });
    _setNavAutoRerouteInProgress(true, 'auto-start');
    navAutoRerouteCount++;
    navLastAutoRerouteAt = Date.now();
    _updateNavUI();
    _showNavBanner('🔄 現在地からルートを自動で見直しています...', 'info');

    if (typeof clearRouteCandidateLayers === 'function') clearRouteCandidateLayers();
    if (typeof clearSelectedRouteHighlight === 'function') clearSelectedRouteHighlight();

    const finishReroute = _createRerouteWatchdog({
        auto: true,
        startedAt: rerouteStartedAt,
        onTimeout: () => {
            _showNavBanner('⚠ 自動再ルートがタイムアウトしました。次の位置更新で再試行します。', 'danger', 4000);
        }
    });

    try {
        drawRouteTo(navDestination.lat, navDestination.lon, {
            onRoutesAvailable: ({ routes, selectedRouteIndex, routeColors, formatter, transportMode, selectRouteIndex }) => {
                if (!finishReroute()) return;
                if (!routes || !routes[selectedRouteIndex]) {
                    _navDebugLog('reroute:failed reason=invalid-route');
                    _completeReroute({ auto: true, success: false, reason: 'auto-invalid-route', startedAt: rerouteStartedAt });
                    return;
                }
                _resetNavigationStateOnReroute();
                navActiveRoute           = routes[selectedRouteIndex];
                const _stepCount = navActiveRoute?.legs?.[0]?.steps?.length ?? '?';
                _navDebugLog(`reroute:new route applied steps=${_stepCount}`);
                if (typeof onNavRouteSelected === 'function') {
                    onNavRouteSelected(routes[selectedRouteIndex], null, {
                        selectedRouteIndex,
                        transportMode,
                        routes,
                        routeColors,
                        onSelectRouteIndex: selectRouteIndex,
                        infoMode: 'navigation_active'
                    });
                }
                navOffRouteCount         = 0;
                if (_offRouteDebounceTimer !== null) {
                    clearTimeout(_offRouteDebounceTimer);
                    _offRouteDebounceTimer = null;
                }

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
                _completeReroute({ auto: true, success: true, reason: 'auto-success', startedAt: rerouteStartedAt });
            },
            onRouteError: () => {
                if (!finishReroute()) return;
                _showNavBanner('⚠ 自動再ルートに失敗しました。次の位置更新で再試行します。', 'danger', 4000);
                _completeReroute({ auto: true, success: false, reason: 'auto-route-error', startedAt: rerouteStartedAt });
            }
        });
    } catch (err) {
        finishReroute();
        console.warn('[navigation] reroute:exception', err);
        _showNavBanner('⚠ 自動再ルート中にエラーが発生しました。次の位置更新で再試行します。', 'danger', 4000);
        _completeReroute({ auto: true, success: false, reason: 'auto-exception', startedAt: rerouteStartedAt });
    }
}

function _onNavPositionError(err) {
    console.warn('[Nav] GPS error:', err.message);
    _showNavBanner('⚠ 位置情報の取得に失敗しました', 'warning');
}

// ── GPS オートフォロー センタリング ──────────────────────────────────────
// ナビシートパネルの実高を DOM から読み、GPS が可視領域中央に来るよう地図中心をずらす。
// _doFullUpdate の外から呼べるよう独立関数化。
function _navCenterOnGPS(lat, lon) {
    const _navSheetEl = document.getElementById('nav-bottom-sheet');
    const _panelH = (_navSheetEl && _navSheetEl.offsetHeight > 0)
        ? _navSheetEl.offsetHeight : 0;
    const _zoom = map.getZoom();
    const _gpsPx = map.project([lat, lon], _zoom);
    if (_panelH > 0) {
        // GPS がパネル上の可視領域中央に来るよう地図中心を panelH/2 分だけ南にずらす
        const _adjPx = L.point(_gpsPx.x, _gpsPx.y + _panelH / 2);
        map.setView(map.unproject(_adjPx, _zoom), _zoom);
    } else {
        map.setView([lat, lon], _zoom);
    }
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
    const _accClass = typeof _getAccuracyClass === 'function'
        ? _getAccuracyClass(accuracy, typeof _gpsHighAccuracy !== 'undefined' ? _gpsHighAccuracy : true)
        : 'accuracy-high';
    currentMarker = L.marker([lat, lon], { icon: _makeCurrentLocationIcon(_accClass) })
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

function _countBy(items, bucketFn) {
    const counts = {};
    for (const item of Array.isArray(items) ? items : []) {
        const key = bucketFn ? bucketFn(item) : item;
        if (!key) continue;
        counts[key] = (counts[key] || 0) + 1;
    }
    return counts;
}

function _formatCountMap(counts) {
    return Object.entries(counts || {})
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(([key, value]) => `${key}:${value}`)
        .join(' ');
}

function _selectBalancedEscapeSpecs(specs, maxPoints) {
    const list = Array.isArray(specs) ? specs.slice() : [];
    if (!Number.isFinite(maxPoints) || maxPoints <= 0 || list.length <= maxPoints) return list;
    const bucketOrder = ['left', 'right', 'back-left', 'back-right'];
    const buckets = new Map();
    for (const spec of list) {
        const bucketKey = Number(spec.backwardM || 0) > 0 ? `back-${spec.side}` : String(spec.side || 'other');
        if (!buckets.has(bucketKey)) buckets.set(bucketKey, []);
        buckets.get(bucketKey).push(spec);
    }
    const orderedKeys = [
        ...bucketOrder.filter(key => buckets.has(key)),
        ...Array.from(buckets.keys()).filter(key => !bucketOrder.includes(key))
    ];
    const selected = [];
    while (selected.length < maxPoints) {
        let progressed = false;
        for (const key of orderedKeys) {
            const bucket = buckets.get(key);
            if (!bucket || bucket.length === 0) continue;
            selected.push(bucket.shift());
            progressed = true;
            if (selected.length >= maxPoints) break;
        }
        if (!progressed) break;
    }
    return selected;
}

function _buildRawEscapeCandidates(coords, projection, blockedArea, escapeSpecs, logPrefix, maxPoints) {
    const headingTarget = _walkAlongRoute(coords, projection, 20);
    const headingUnit = _headingUnitVectorMeters(projection?.snappedPoint, headingTarget);
    if (!headingUnit) {
        _recordSnapDebugEvent({
            type: 'reject',
            mode: logPrefix,
            rejectedReason: 'node-build-failure',
            detail: 'missing-heading-unit'
        });
        return [];
    }

    const balancedSpecs = _selectBalancedEscapeSpecs(escapeSpecs, maxPoints);
    console.log(
        `[BlockAhead][${logPrefix}] candidate-balance raw=${_formatCountMap(_countBy(escapeSpecs, spec => Number(spec.backwardM || 0) > 0 ? `back-${spec.side}` : spec.side))} ` +
        `selected=${_formatCountMap(_countBy(balancedSpecs, spec => Number(spec.backwardM || 0) > 0 ? `back-${spec.side}` : spec.side))}`
    );

    const deduped = [];
    for (const spec of balancedSpecs) {
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
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: spec.side,
                tier: spec.lateralM,
                depth: spec.depthKind || 'entrance',
                candidateId: spec.label,
                rejectedReason: 'inside-blocked-area'
            });
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
        )) {
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: spec.side,
                tier: spec.lateralM,
                depth: spec.depthKind || 'entrance',
                candidateId: spec.label,
                rawPoint: point,
                rejectedReason: 'duplicate-snap'
            });
            continue;
        }
        _recordSnapDebugEvent({
            type: 'raw-candidate',
            mode: logPrefix,
            side: spec.side,
            tier: spec.lateralM,
            depth: spec.depthKind || 'entrance',
            candidateId: spec.label,
            rawPoint: point
        });
        deduped.push({
            label: spec.label,
            point,
            lateralM: pushed.lateralM,
            backwardM: spec.backwardM,
            side: spec.side,
            distanceTierM: spec.lateralM,
            depthKind: spec.depthKind || 'entrance',
            __snapRawRecorded: true
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

async function _fetchOsrmNearestNode(point, contextLabel = 'nearest') {
    const injected = await _callBlockAheadTestDep('fetchOsrmNearest', point, contextLabel);
    if (typeof injected !== 'undefined') return injected;
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

function _buildEscapeNearestRetryPoints(candidatePoint, headingUnit) {
    if (!candidatePoint || !headingUnit) return [];
    const forward = { east: headingUnit.east, north: headingUnit.north };
    const left = { east: -headingUnit.north, north: headingUnit.east };
    const diagonals = [
        { east: forward.east + left.east, north: forward.north + left.north },
        { east: forward.east - left.east, north: forward.north - left.north },
        { east: -forward.east + left.east, north: -forward.north + left.north },
        { east: -forward.east - left.east, north: -forward.north - left.north }
    ].map(vec => {
        const len = Math.hypot(vec.east, vec.north) || 1;
        return { east: vec.east / len, north: vec.north / len };
    });
    const attempts = [
        { distanceM: 5, label: 'forward-5', east: forward.east * 5, north: forward.north * 5 },
        { distanceM: 5, label: 'backward-5', east: -forward.east * 5, north: -forward.north * 5 },
        { distanceM: 5, label: 'left-5', east: left.east * 5, north: left.north * 5 },
        { distanceM: 5, label: 'right-5', east: -left.east * 5, north: -left.north * 5 },
        { distanceM: 10, label: 'diag-fl-10', east: diagonals[0].east * 10, north: diagonals[0].north * 10 },
        { distanceM: 10, label: 'diag-fr-10', east: diagonals[1].east * 10, north: diagonals[1].north * 10 },
        { distanceM: 10, label: 'diag-bl-10', east: diagonals[2].east * 10, north: diagonals[2].north * 10 },
        { distanceM: 10, label: 'diag-br-10', east: diagonals[3].east * 10, north: diagonals[3].north * 10 },
        { distanceM: 15, label: 'forward-15', east: forward.east * 15, north: forward.north * 15 },
        { distanceM: 15, label: 'backward-15', east: -forward.east * 15, north: -forward.north * 15 }
    ];
    return attempts
        .map(spec => ({
            ...spec,
            point: _offsetPointByMeters(candidatePoint, spec.east, spec.north)
        }))
        .filter(spec => !!spec.point);
}

function _buildEscapeModeNearestRetryPoints(candidatePoint, headingUnit, candidate = {}) {
    if (!candidatePoint || !headingUnit) {
        return {
            mode: _getEscapeNearestRetryMode(candidate),
            retryProfile: _classifyEscapeRetryProfile(candidate),
            retryPoints: [],
            strategyOrderUsed: [],
            enabledStrategies: [],
            disabledStrategies: [],
            prunedStrategies: [],
            strategySkipReasons: {}
        };
    }
    const { mode, ordered, retryProfile } = _orderEscapeNearestRetryStrategies(candidate);
    const retryPoints = [];
    const strategyOrderUsed = [];
    const enabledStrategies = [];
    const disabledStrategies = [];
    const prunedStrategies = [];
    const strategySkipReasons = {};
    ordered.forEach((strategy) => {
        strategyOrderUsed.push(strategy.id);
        const skip = _shouldSkipEscapeNearestStrategy(strategy, candidate, mode);
        if (skip.skipped) {
            prunedStrategies.push(strategy.id);
            disabledStrategies.push(strategy.id);
            strategySkipReasons[strategy.id] = skip.reason || 'pruned';
            console.log(`[PedestrianSafety][escape-nearest][prune] strategy=${strategy.id} skipped=true reason=${skip.reason || 'pruned'}`);
            return;
        }
        const built = _buildEscapeRetryPointFromStrategy(candidatePoint, headingUnit, strategy.id);
        if (!built?.point) {
            disabledStrategies.push(strategy.id);
            strategySkipReasons[strategy.id] = 'point-build-failed';
            console.log(`[PedestrianSafety][escape-nearest][prune] strategy=${strategy.id} skipped=true reason=point-build-failed`);
            return;
        }
        enabledStrategies.push(strategy.id);
        retryPoints.push(built);
    });
    return {
        mode,
        retryProfile,
        retryPoints,
        strategyOrderUsed,
        enabledStrategies,
        disabledStrategies,
        prunedStrategies,
        strategySkipReasons
    };
}

function _distancePointToRouteSafe(point, coords) {
    return point ? _distancePointToRoute(point, coords) : Infinity;
}

function _adjustEscapeCandidateForNearest(candidate, blockedArea, originalCoords, headingUnit) {
    if (!candidate?.point || !headingUnit) {
        return {
            candidate,
            adjusted: false,
            adjustmentType: null,
            adjustmentDistance: 0
        };
    }
    const rawBlockedDistance = _distancePointToBlockedArea(candidate.point, blockedArea, blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS);
    const rawCorridorDistance = _distancePointToRouteSafe(candidate.point, originalCoords);
    const needsAdjustment = rawBlockedDistance <= 8
        || rawCorridorDistance < (BLOCK_ESCAPE_CORRIDOR_DIFF_M - 2)
        || (!!candidate.sideRoadContinuationDetected && rawCorridorDistance < (BLOCK_ESCAPE_CORRIDOR_DIFF_M + 6));
    if (!needsAdjustment) {
        return {
            candidate,
            adjusted: false,
            adjustmentType: null,
            adjustmentDistance: 0
        };
    }
    const left = { east: -headingUnit.north, north: headingUnit.east };
    const signed = candidate.side === 'left' ? 1 : -1;
    const variants = [];
    BLOCK_ESCAPE_ADJUSTMENT_DISTANCES_M.forEach(distanceM => {
        variants.push({
            label: 'lateral-release',
            distanceM,
            point: _offsetPointByMeters(candidate.point, left.east * signed * distanceM, left.north * signed * distanceM)
        });
        variants.push({
            label: 'lateral-forward-release',
            distanceM,
            point: _offsetPointByMeters(
                candidate.point,
                (left.east * signed * distanceM) + (headingUnit.east * 4),
                (left.north * signed * distanceM) + (headingUnit.north * 4)
            )
        });
    });
    for (const variant of variants) {
        if (!variant.point) continue;
        const variantBlockedDistance = _distancePointToBlockedArea(variant.point, blockedArea, blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS);
        const variantCorridorDistance = _distancePointToRouteSafe(variant.point, originalCoords);
        if (variantBlockedDistance <= 0) continue;
        if (variantCorridorDistance <= rawCorridorDistance && variantBlockedDistance <= rawBlockedDistance) continue;
        return {
            candidate: {
                ...candidate,
                point: variant.point,
                originalPoint: candidate.point,
                candidateAdjusted: true,
                candidateAdjustmentType: variant.label,
                candidateAdjustmentDistance: variant.distanceM
            },
            adjusted: true,
            adjustmentType: variant.label,
            adjustmentDistance: variant.distanceM
        };
    }
    return {
        candidate,
        adjusted: false,
        adjustmentType: null,
        adjustmentDistance: 0
    };
}

function _classifySnapPositionCategory(candidate, blockedComponents = {}) {
    if (candidate?.positionCategory) return String(candidate.positionCategory);
    if (Number(candidate?.backwardM || 0) > 0) return 'backward-entry';
    if (Number(blockedComponents.coreDistance || Infinity) <= 0) return 'blocked-core';
    if (Number(blockedComponents.intersectionBufferDistance || Infinity) <= 0) return 'intersection-buffer';
    if (Number(blockedComponents.slitBodyDistance || Infinity) <= 0) return 'slit-body';
    if (Number(blockedComponents.slitNearDistance || Infinity) <= 0) return 'near-boundary';
    return 'open-side-entry';
}

function _evaluateSameCorridorDecision(candidate, corridorDistance, bearingDiff, mode) {
    if (candidate?.forceSameCorridorDecision) return String(candidate.forceSameCorridorDecision);
    if (candidate?.forceRejectReason === 'same-corridor') return 'hard';
    if (candidate?.forceRejectReason === 'same-corridor-soft') return 'soft';
    if (!Number.isFinite(Number(corridorDistance)) || corridorDistance >= BLOCK_ESCAPE_CORRIDOR_DIFF_M) return 'pass';
    const lateralM = Number(candidate?.lateralM || candidate?.distanceTierM || 0);
    const backwardM = Number(candidate?.backwardM || 0);
    const continuationDetected = !!candidate?.sideRoadContinuationDetected || backwardM > 0 || String(candidate?.side || '').startsWith('back-');
    const mainlineReturnDetected = !!candidate?.mainlineReturnDetected;
    const bearingEnough = Number.isFinite(Number(bearingDiff)) && Number(bearingDiff) >= Math.max(28, BLOCK_ESCAPE_SIDE_BEARING_DEG - 7);
    const lateralEnough = lateralM >= 60;
    const farEnough = Number(corridorDistance) >= Math.max(10, BLOCK_ESCAPE_CORRIDOR_DIFF_M - 6);
    if (mode === 'escape-leg' && !mainlineReturnDetected && (continuationDetected || bearingEnough || lateralEnough || farEnough)) {
        return 'soft';
    }
    if (!mainlineReturnDetected && continuationDetected && (bearingEnough || lateralEnough)) {
        return 'soft';
    }
    return 'hard';
}

function _evaluateInsideBlockedDecision(candidate, blockedArea, snappedPoint, mode) {
    if (candidate?.forceInsideBlockedDecision) return { decision: String(candidate.forceInsideBlockedDecision), strictComponents: null, nearComponents: null };
    if (candidate?.forceRejectReason === 'inside-blocked-area') return { decision: 'hard', strictComponents: null, nearComponents: null };
    if (candidate?.forceRejectReason === 'inside-blocked-area-soft') return { decision: 'soft', strictComponents: null, nearComponents: null };
    const nearRejectMeters = blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS;
    const strictComponents = _pointBlockedAreaComponentDistances(snappedPoint, blockedArea, 0);
    const nearComponents = _pointBlockedAreaComponentDistances(snappedPoint, blockedArea, nearRejectMeters);
    if (Number(nearComponents.minDistance) > 0) {
        return { decision: 'pass', strictComponents, nearComponents };
    }
    const hardInside = Number(strictComponents.coreDistance) <= 0
        || Number(strictComponents.slitBodyDistance) <= 0
        || Number(strictComponents.intersectionBufferDistance) <= 0
        || Number(strictComponents.minDistance) <= 0;
    if (!hardInside && mode === 'escape-leg') {
        return { decision: 'soft', strictComponents, nearComponents };
    }
    return { decision: 'hard', strictComponents, nearComponents };
}

async function _fetchNearestNodeWithRetry(candidate, logPrefix, headingUnit, mode) {
    const contextBase = `${logPrefix}:${candidate.label}`;
    const attempts = [];
    const defaultOrder = mode === 'escape' ? _orderEscapeNearestRetryStrategies(candidate).ordered.map(strategy => strategy.id) : [];
    const defaultResult = {
        retryProfile: _classifyEscapeRetryProfile(candidate),
        strategyOrderUsed: defaultOrder,
        enabledStrategies: [],
        disabledStrategies: [],
        prunedStrategies: [],
        strategySkipReasons: {},
        firstNearestReturnedStrategy: null,
        firstAcceptedStrategy: null,
        allStrategiesNull: false,
        allStrategiesRejected: false,
        finalRetryOutcome: 'point-success'
    };
    const first = await _fetchOsrmNearestNode(candidate.point, `${contextBase}:point`);
    attempts.push({
        strategy: 'point',
        nearestReturned: !!first,
        snapDistanceM: Number(first?.distanceM || 0)
    });
    if (first) {
        return {
            snappedPoint: first,
            retryCount: 0,
            retrySucceeded: false,
            retryFailed: false,
            usedRetry: false,
            finalLabel: 'point',
            strategyUsed: 'point',
            failureReason: 'none',
            attempts,
            ...defaultResult
        };
    }
    const fallbackRetryPoints = mode === 'escape' ? [] : _buildEscapeNearestRetryPoints(candidate.point, headingUnit);
    const retryConfig = mode === 'escape'
        ? _buildEscapeModeNearestRetryPoints(candidate.point, headingUnit, candidate)
        : {
            mode: 'full',
            retryPoints: fallbackRetryPoints,
            strategyOrderUsed: fallbackRetryPoints.map(point => point.label),
            enabledStrategies: fallbackRetryPoints.map(point => point.label),
            disabledStrategies: [],
            prunedStrategies: [],
            strategySkipReasons: {}
        };
    const retryPoints = Array.isArray(retryConfig.retryPoints) ? retryConfig.retryPoints : [];
    console.log(
        `[PedestrianSafety][escape-nearest][order] candidate=${candidate.label} mode=${mode} profile=${retryConfig.retryProfile || 'default'} strategies=${(retryConfig.strategyOrderUsed || []).join(',') || 'none'}`
    );
    let retryCount = 0;
    let firstNearestReturnedStrategy = null;
    for (let i = 0; i < retryPoints.length; i++) {
        const retry = retryPoints[i];
        retryCount += 1;
        const snapped = await _fetchOsrmNearestNode(retry.point, `${contextBase}:retry-${retryCount}`);
        attempts.push({
            strategy: retry.label,
            nearestReturned: !!snapped,
            snapDistanceM: Number(snapped?.distanceM || 0)
        });
        console.log(
            `[PedestrianSafety][escape-nearest] candidate=${candidate.label} strategy=${retry.label} attempt=${retryCount} distance=${retry.distanceM}m ` +
            `result=${snapped ? 'success' : 'fail'}`
        );
        if (snapped) {
            firstNearestReturnedStrategy = retry.label;
            console.log(`[PedestrianSafety][escape-nearest][winner] candidate=${candidate.label} strategy=${retry.label}`);
            return {
                snappedPoint: snapped,
                retryCount,
                retrySucceeded: true,
                retryFailed: false,
                usedRetry: true,
                finalLabel: retry.label,
                strategyUsed: retry.label,
                failureReason: 'resolved-by-retry',
                attempts,
                retryProfile: retryConfig.retryProfile || 'default',
                strategyOrderUsed: retryConfig.strategyOrderUsed || [],
                enabledStrategies: retryConfig.enabledStrategies || [],
                disabledStrategies: retryConfig.disabledStrategies || [],
                prunedStrategies: retryConfig.prunedStrategies || [],
                strategySkipReasons: retryConfig.strategySkipReasons || {},
                firstNearestReturnedStrategy,
                firstAcceptedStrategy: retry.label,
                winningStrategyIndex: Math.max(0, (retryConfig.strategyOrderUsed || []).indexOf(retry.label)),
                allStrategiesNull: false,
                allStrategiesRejected: false,
                finalRetryOutcome: 'retry-success'
            };
        }
    }
    const failureReason = retryConfig.enabledStrategies?.length === 0 && retryConfig.prunedStrategies?.length > 0
        ? 'all-pruned-by-policy'
        : retryPoints.length === 0
            ? 'retry-no-strategy-enabled'
            : attempts.some(attempt => attempt.strategy !== 'point' && attempt.nearestReturned)
                ? 'retry-strategy-exhausted:no-nearest-returned'
                : 'all-retry-points-null';
    console.log(`[PedestrianSafety][escape-nearest] candidate=${candidate.label} final=nearest-null-after-retry detail=${failureReason} mode=${mode}`);
    return {
        snappedPoint: null,
        retryCount,
        retrySucceeded: false,
        retryFailed: retryCount > 0 || (mode === 'escape' && Array.isArray(retryConfig.strategyOrderUsed) && retryConfig.strategyOrderUsed.length > 0),
        usedRetry: retryCount > 0 || (mode === 'escape' && Array.isArray(retryConfig.strategyOrderUsed) && retryConfig.strategyOrderUsed.length > 0),
        finalLabel: null,
        strategyUsed: retryPoints[retryPoints.length - 1]?.label || 'retry-exhausted',
        failureReason,
        attempts,
        retryProfile: retryConfig.retryProfile || 'default',
        strategyOrderUsed: retryConfig.strategyOrderUsed || [],
        enabledStrategies: retryConfig.enabledStrategies || [],
        disabledStrategies: retryConfig.disabledStrategies || [],
        prunedStrategies: retryConfig.prunedStrategies || [],
        strategySkipReasons: retryConfig.strategySkipReasons || {},
        firstNearestReturnedStrategy,
        firstAcceptedStrategy: null,
        winningStrategyIndex: null,
        allStrategiesNull: !attempts.some(attempt => attempt.strategy !== 'point' && attempt.nearestReturned),
        allStrategiesRejected: retryPoints.length > 0 && !!attempts.some(attempt => attempt.strategy !== 'point'),
        finalRetryOutcome: failureReason
    };
}

async function _snapEscapeCandidatesToRoadNodes(rawCandidates, blockedArea, originalCoords, logPrefix, options = {}) {
    const rawList = Array.isArray(rawCandidates) ? rawCandidates : [];
    console.log(`[BlockAhead][${logPrefix}] raw-candidates=${rawList.length}`);
    const origin = Array.isArray(originalCoords) && originalCoords.length > 0 ? originalCoords[0] : null;
    const forwardRef = Array.isArray(originalCoords) && originalCoords.length > 1 ? originalCoords[Math.min(1, originalCoords.length - 1)] : null;
    const forwardBearing = origin && forwardRef ? _segmentBearingDeg(origin, forwardRef) : 0;
    const headingUnit = origin && forwardRef ? _headingUnitVectorMeters(origin, forwardRef) : null;
    const depthSteps = Array.isArray(options.depthSteps)
        ? options.depthSteps
        : BLOCK_ESCAPE_DEEPER_STEPS_M;
    rawList.forEach(candidate => {
        if (candidate?.__snapRawRecorded) return;
        _recordSnapDebugEvent({
            type: 'raw-candidate',
            mode: logPrefix,
            side: candidate.side,
            tier: candidate.distanceTierM || candidate.lateralM,
            depth: candidate.depthKind || 'entrance',
            candidateId: candidate.label,
            rawPoint: candidate.point
        });
    });
    const evaluateCandidate = async (candidate) => {
        const adjustedResult = logPrefix === 'escape'
            ? _adjustEscapeCandidateForNearest(candidate, blockedArea, originalCoords, headingUnit)
            : { candidate, adjusted: false, adjustmentType: null, adjustmentDistance: 0 };
        const workingCandidate = adjustedResult.candidate || candidate;
        if (adjustedResult.adjusted) {
            console.log(
                `[BlockAhead][${logPrefix}] adjusted ${candidate.label}: type=${adjustedResult.adjustmentType} ` +
                `distance=${Math.round(adjustedResult.adjustmentDistance)}m`
            );
            _recordSnapDebugEvent({
                type: 'candidate-adjustment',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: candidate.point,
                snappedPoint: workingCandidate.point,
                candidateAdjusted: true,
                candidateAdjustmentType: adjustedResult.adjustmentType,
                candidateAdjustmentDistance: adjustedResult.adjustmentDistance
            });
        }
        _recordSnapDebugEvent({
            type: 'nearest-attempt',
            mode: logPrefix,
            side: candidate.side,
            tier: candidate.distanceTierM,
            depth: candidate.depthKind || 'entrance',
            candidateId: candidate.label,
            rawPoint: workingCandidate.point,
            nearestRequested: true
        });
        const nearestResult = await _fetchNearestNodeWithRetry(workingCandidate, logPrefix, headingUnit, logPrefix);
        const nearestStrategiesTried = (nearestResult.attempts || []).map(attempt => attempt.strategy);
        const nearestStrategyAttempts = (nearestResult.attempts || []).map(attempt => ({
            strategy: attempt.strategy,
            nearestReturned: !!attempt.nearestReturned,
            snapDistanceM: Number(attempt.snapDistanceM || 0)
        }));
        const snappedPoint = nearestResult.snappedPoint;
        _recordSnapDebugEvent({
            type: 'nearest-retry',
            mode: logPrefix,
            side: candidate.side,
            tier: candidate.distanceTierM,
            depth: candidate.depthKind || 'entrance',
            candidateId: candidate.label,
            rawPoint: workingCandidate.point,
            nearestRetryCount: nearestResult.retryCount,
            nearestRetrySuccess: nearestResult.retrySucceeded,
            nearestStrategyUsed: nearestResult.strategyUsed,
            nearestStrategiesTried,
            nearestStrategyAttempts,
            retryProfile: nearestResult.retryProfile,
            strategyOrderUsed: nearestResult.strategyOrderUsed,
            strategiesEnabled: nearestResult.enabledStrategies,
            strategiesPruned: nearestResult.prunedStrategies,
            strategiesDisabled: nearestResult.disabledStrategies,
            strategySkipReasons: nearestResult.strategySkipReasons,
            firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
            firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
            winningStrategyIndex: nearestResult.winningStrategyIndex,
            allStrategiesNull: nearestResult.allStrategiesNull,
            allStrategiesRejected: nearestResult.allStrategiesRejected,
            finalRetryOutcome: nearestResult.finalRetryOutcome,
            candidateAdjusted: adjustedResult.adjusted,
            candidateAdjustmentType: adjustedResult.adjustmentType,
            candidateAdjustmentDistance: adjustedResult.adjustmentDistance
        });
        if (!snappedPoint) {
            console.log(`[BlockAhead][${logPrefix}] reject ${candidate.label}: no-nearest`);
        _recordSnapDebugEvent({
            type: 'nearest-null',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: workingCandidate.point,
                nearestRequested: true,
                nearestRetryCount: nearestResult.retryCount,
                nearestRetrySuccess: false,
                nearestStrategyUsed: nearestResult.strategyUsed,
                nearestStrategiesTried,
                nearestStrategyAttempts,
                retryProfile: nearestResult.retryProfile,
                strategyOrderUsed: nearestResult.strategyOrderUsed,
                strategiesEnabled: nearestResult.enabledStrategies,
                strategiesPruned: nearestResult.prunedStrategies,
                strategiesDisabled: nearestResult.disabledStrategies,
                strategySkipReasons: nearestResult.strategySkipReasons,
                firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
                firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
                winningStrategyIndex: nearestResult.winningStrategyIndex,
                allStrategiesNull: nearestResult.allStrategiesNull,
                allStrategiesRejected: nearestResult.allStrategiesRejected,
                finalRetryOutcome: nearestResult.finalRetryOutcome,
                candidateAdjusted: adjustedResult.adjusted,
                candidateAdjustmentType: adjustedResult.adjustmentType,
                candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
                nearestFailureReason: nearestResult.failureReason,
                snapEmptyDetail: nearestResult.usedRetry
                    ? `nearest-null-after-retry:${nearestResult.failureReason || 'retry-strategy-exhausted'}`
                    : 'nearest-null-after-retry:no-candidate-point',
                nearestRejectedReason: nearestResult.usedRetry ? 'nearest-null-after-retry' : 'nearest-null',
                rejectedReason: nearestResult.usedRetry ? 'nearest-null-after-retry' : 'nearest-null'
            });
            return null;
        }
        _recordSnapDebugEvent({
            type: 'nearest-success',
            mode: logPrefix,
            side: candidate.side,
            tier: candidate.distanceTierM,
            depth: candidate.depthKind || 'entrance',
            candidateId: candidate.label,
            rawPoint: workingCandidate.point,
            snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
            snapDistanceM: snappedPoint.distanceM,
            nearestRequested: true,
            nearestReturned: true,
            nearestRetryCount: nearestResult.retryCount,
            nearestRetrySuccess: nearestResult.retrySucceeded,
            nearestStrategyUsed: nearestResult.strategyUsed,
            nearestStrategiesTried,
            nearestStrategyAttempts,
            retryProfile: nearestResult.retryProfile,
            strategyOrderUsed: nearestResult.strategyOrderUsed,
            strategiesEnabled: nearestResult.enabledStrategies,
            strategiesPruned: nearestResult.prunedStrategies,
            strategiesDisabled: nearestResult.disabledStrategies,
            strategySkipReasons: nearestResult.strategySkipReasons,
            firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
            firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
            winningStrategyIndex: nearestResult.winningStrategyIndex,
            allStrategiesNull: nearestResult.allStrategiesNull,
            allStrategiesRejected: nearestResult.allStrategiesRejected,
            finalRetryOutcome: nearestResult.finalRetryOutcome,
            candidateAdjusted: adjustedResult.adjusted,
            candidateAdjustmentType: adjustedResult.adjustmentType,
            candidateAdjustmentDistance: adjustedResult.adjustmentDistance
        });
        let secondaryHoldWaypoint = null;
        if (workingCandidate.midHoldRawPoint) {
            const snappedMid = await _fetchOsrmNearestNode(workingCandidate.midHoldRawPoint, `${logPrefix}:${candidate.label}:mid-hold`);
            if (snappedMid) {
                secondaryHoldWaypoint = { lat: snappedMid.lat, lng: snappedMid.lng };
            }
        }
        const blockedDistance = _distancePointToBlockedArea(snappedPoint, blockedArea, blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS);
        const blockedDecisionResult = _evaluateInsideBlockedDecision(workingCandidate, blockedArea, snappedPoint, logPrefix);
        const blockedDecision = blockedDecisionResult.decision || 'pass';
        const strictComponents = blockedDecisionResult.strictComponents || _pointBlockedAreaComponentDistances(snappedPoint, blockedArea, 0);
        const positionCategory = _classifySnapPositionCategory(workingCandidate, strictComponents);
        const corridorDistance = _distancePointToRoute(snappedPoint, originalCoords);
        const bearingToNode = origin ? _segmentBearingDeg(origin, snappedPoint) : 0;
        const bearingDiff = _bearingDiffDeg(forwardBearing, bearingToNode);
        const blockedBearing = (blockedArea?.startPoint && blockedArea?.endPoint)
            ? _segmentBearingDeg(blockedArea.startPoint, blockedArea.endPoint)
            : null;
        const blockedBearingBucket = _bucketBearingDiff(
            Number.isFinite(Number(blockedBearing)) ? _bearingDiffDeg(Number(blockedBearing), Number(bearingToNode)) : null
        );
        const lateralM = Number(workingCandidate.lateralM || workingCandidate.distanceTierM || 0);
        const continuationDetected = !!workingCandidate.sideRoadContinuationDetected || Number(workingCandidate.backwardM || 0) > 0 || String(workingCandidate.side || '').startsWith('back-');
        const sameCorridorDecision = _evaluateSameCorridorDecision(workingCandidate, corridorDistance, bearingDiff, logPrefix);
        const escapeRescueAccepted = logPrefix === 'escape'
            && (adjustedResult.adjusted || nearestResult.retrySucceeded)
            && continuationDetected
            && !workingCandidate.mainlineReturnDetected
            && corridorDistance >= Math.max(8, BLOCK_ESCAPE_CORRIDOR_DIFF_M - 4)
            && bearingDiff >= 24;
        if (!Number.isFinite(bearingDiff)) {
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: workingCandidate.point,
                snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
                nearestRetryCount: nearestResult.retryCount,
                nearestRetrySuccess: nearestResult.retrySucceeded,
                nearestStrategyUsed: nearestResult.strategyUsed,
                nearestStrategiesTried,
                nearestStrategyAttempts,
                strategyOrderUsed: nearestResult.strategyOrderUsed,
                strategiesEnabled: nearestResult.enabledStrategies,
                strategiesPruned: nearestResult.prunedStrategies,
                strategiesDisabled: nearestResult.disabledStrategies,
                strategySkipReasons: nearestResult.strategySkipReasons,
                firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
                firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
                allStrategiesNull: nearestResult.allStrategiesNull,
                allStrategiesRejected: nearestResult.allStrategiesRejected,
                finalRetryOutcome: nearestResult.finalRetryOutcome,
                candidateAdjusted: adjustedResult.adjusted,
                candidateAdjustmentType: adjustedResult.adjustmentType,
                candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
                nearestFailureReason: 'invalid-bearing',
                nearestReturnedButRejectedReason: 'invalid-bearing',
                blockedBearing,
                blockedBearingBucket,
                corridorLength: corridorDistance,
                corridorLengthBucket: _bucketCorridorLength(corridorDistance),
                snapDistanceBucket: _bucketSnapDistance(snappedPoint.distanceM),
                nearestRejectedReason: 'invalid-bearing',
                snapEmptyDetail: nearestResult.retrySucceeded ? 'nearest-null-after-retry:retry-invalid-bearing' : null,
                candidatePositionCategory: positionCategory,
                rejectedReason: 'invalid-bearing'
            });
            return null;
        }
        _recordSnapDebugEvent({
            type: 'decision',
            mode: logPrefix,
            side: candidate.side,
            tier: candidate.distanceTierM,
            depth: candidate.depthKind || 'entrance',
            candidateId: candidate.label,
            rawPoint: workingCandidate.point,
            snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
            snapDistanceM: snappedPoint.distanceM,
            corridorDistanceM: corridorDistance,
            blockedDistanceM: blockedDistance,
            bearingDiffDeg: bearingDiff,
            lateralM,
            nearestRetryCount: nearestResult.retryCount,
            nearestRetrySuccess: nearestResult.retrySucceeded,
            nearestStrategyUsed: nearestResult.strategyUsed,
            nearestStrategiesTried,
            nearestStrategyAttempts,
            retryProfile: nearestResult.retryProfile,
            strategyOrderUsed: nearestResult.strategyOrderUsed,
            strategiesEnabled: nearestResult.enabledStrategies,
            strategiesPruned: nearestResult.prunedStrategies,
            strategiesDisabled: nearestResult.disabledStrategies,
            strategySkipReasons: nearestResult.strategySkipReasons,
            firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
            firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
            winningStrategyIndex: nearestResult.winningStrategyIndex,
            allStrategiesNull: nearestResult.allStrategiesNull,
            allStrategiesRejected: nearestResult.allStrategiesRejected,
            finalRetryOutcome: nearestResult.finalRetryOutcome,
            candidateAdjusted: adjustedResult.adjusted,
            candidateAdjustmentType: adjustedResult.adjustmentType,
            candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
            sameCorridorDecision,
            insideBlockedDecision: blockedDecision,
            sideRoadContinuationDetected: continuationDetected,
            sideRoadContinuationDetectedAtSnap: continuationDetected,
            nearestAcceptedAsRescue: escapeRescueAccepted,
            mainlineReturnDetected: !!candidate.mainlineReturnDetected,
            holdWaypointMode: !!workingCandidate.holdWaypoint,
            blockedBearing,
            blockedBearingBucket,
            corridorLength: corridorDistance,
            corridorLengthBucket: _bucketCorridorLength(corridorDistance),
            snapDistanceBucket: _bucketSnapDistance(snappedPoint.distanceM),
            effectiveRadiusM: Number(blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS),
            candidatePositionCategory: positionCategory
        });
        console.log(
            `[BlockAhead][${logPrefix}] same corridor ${candidate.label}: decision=${sameCorridorDecision} corridor=${Math.round(corridorDistance)}m ` +
            `bearing=${Math.round(bearingDiff)}deg lateral=${Math.round(lateralM)}m continuation=${continuationDetected}`
        );
        console.log(
            `[BlockAhead][${logPrefix}] inside blocked ${candidate.label}: decision=${blockedDecision} blocked=${Math.round(blockedDistance)}m ` +
            `effectiveRadius=${Math.round(Number(blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS))}m position=${positionCategory}`
        );
        if (blockedDecision === 'hard') {
            console.log(`[BlockAhead][${logPrefix}] reject ${candidate.label}: snapped inside blocked area`);
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: workingCandidate.point,
                snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
                snapDistanceM: snappedPoint.distanceM,
                corridorDistanceM: corridorDistance,
                blockedDistanceM: blockedDistance,
                bearingDiffDeg: bearingDiff,
                lateralM,
                nearestRetryCount: nearestResult.retryCount,
                nearestRetrySuccess: nearestResult.retrySucceeded,
                nearestStrategyUsed: nearestResult.strategyUsed,
                nearestStrategiesTried,
                nearestStrategyAttempts,
                strategyOrderUsed: nearestResult.strategyOrderUsed,
                strategiesEnabled: nearestResult.enabledStrategies,
                strategiesPruned: nearestResult.prunedStrategies,
                strategiesDisabled: nearestResult.disabledStrategies,
                strategySkipReasons: nearestResult.strategySkipReasons,
                firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
                firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
                allStrategiesNull: nearestResult.allStrategiesNull,
                allStrategiesRejected: nearestResult.allStrategiesRejected,
                finalRetryOutcome: nearestResult.finalRetryOutcome,
                candidateAdjusted: adjustedResult.adjusted,
                candidateAdjustmentType: adjustedResult.adjustmentType,
                candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
                nearestFailureReason: blockedDecision === 'hard' ? 'blocked-after-snap' : 'blocked-soft',
                nearestReturnedButRejectedReason: 'inside-blocked-area',
                sameCorridorDecision,
                insideBlockedDecision: blockedDecision,
                holdWaypointMode: !!workingCandidate.holdWaypoint,
                blockedBearing,
                blockedBearingBucket,
                corridorLength: corridorDistance,
                corridorLengthBucket: _bucketCorridorLength(corridorDistance),
                snapDistanceBucket: _bucketSnapDistance(snappedPoint.distanceM),
                nearestRejectedReason: 'inside-blocked-area',
                effectiveRadiusM: Number(blockedArea?.nearRejectMeters ?? BLOCK_NEAR_REJECT_METERS),
                candidatePositionCategory: positionCategory,
                rejectedReason: 'inside-blocked-area'
            });
            return null;
        }
        if (sameCorridorDecision === 'hard') {
            console.log(`[BlockAhead][${logPrefix}] reject ${candidate.label}: snapped same corridor ${Math.round(corridorDistance)}m`);
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: workingCandidate.point,
                snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
                snapDistanceM: snappedPoint.distanceM,
                corridorDistanceM: corridorDistance,
                blockedDistanceM: blockedDistance,
                bearingDiffDeg: bearingDiff,
                lateralM,
                nearestRetryCount: nearestResult.retryCount,
                nearestRetrySuccess: nearestResult.retrySucceeded,
                nearestStrategyUsed: nearestResult.strategyUsed,
                nearestStrategiesTried,
                nearestStrategyAttempts,
                strategyOrderUsed: nearestResult.strategyOrderUsed,
                strategiesEnabled: nearestResult.enabledStrategies,
                strategiesPruned: nearestResult.prunedStrategies,
                strategiesDisabled: nearestResult.disabledStrategies,
                strategySkipReasons: nearestResult.strategySkipReasons,
                firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
                firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
                allStrategiesNull: nearestResult.allStrategiesNull,
                allStrategiesRejected: nearestResult.allStrategiesRejected,
                finalRetryOutcome: nearestResult.finalRetryOutcome,
                candidateAdjusted: adjustedResult.adjusted,
                candidateAdjustmentType: adjustedResult.adjustmentType,
                candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
                nearestFailureReason: continuationDetected
                    ? 'retry-strategy-exhausted:only-mainline-continuation'
                    : 'retry-strategy-exhausted:nearest-returned-but-all-rejected',
                nearestReturnedButRejectedReason: continuationDetected ? 'mainline-only' : 'no-side-road',
                sameCorridorDecision,
                insideBlockedDecision: blockedDecision,
                holdWaypointMode: !!workingCandidate.holdWaypoint,
                blockedBearing,
                blockedBearingBucket,
                corridorLength: corridorDistance,
                corridorLengthBucket: _bucketCorridorLength(corridorDistance),
                snapDistanceBucket: _bucketSnapDistance(snappedPoint.distanceM),
                nearestRejectedReason: 'same-corridor',
                snapEmptyDetail: nearestResult.retrySucceeded
                    ? (continuationDetected
                        ? 'nearest-null-after-retry:retry-strategy-exhausted:only-mainline-continuation'
                        : 'nearest-null-after-retry:retry-rejected-no-side-road')
                    : null,
                candidatePositionCategory: positionCategory,
                rejectedReason: 'same-corridor'
            });
            return null;
        }
        if (Number.isFinite(Number(candidate.maxSnapDistanceM)) && Number(snappedPoint.distanceM || 0) > Number(candidate.maxSnapDistanceM)) {
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: workingCandidate.point,
                snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
                snapDistanceM: snappedPoint.distanceM,
                nearestRetryCount: nearestResult.retryCount,
                nearestRetrySuccess: nearestResult.retrySucceeded,
                nearestStrategyUsed: nearestResult.strategyUsed,
                nearestStrategiesTried,
                nearestStrategyAttempts,
                strategyOrderUsed: nearestResult.strategyOrderUsed,
                strategiesEnabled: nearestResult.enabledStrategies,
                strategiesPruned: nearestResult.prunedStrategies,
                strategiesDisabled: nearestResult.disabledStrategies,
                strategySkipReasons: nearestResult.strategySkipReasons,
                firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
                firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
                allStrategiesNull: nearestResult.allStrategiesNull,
                allStrategiesRejected: nearestResult.allStrategiesRejected,
                finalRetryOutcome: nearestResult.finalRetryOutcome,
                candidateAdjusted: adjustedResult.adjusted,
                candidateAdjustmentType: adjustedResult.adjustmentType,
                candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
                nearestFailureReason: 'snap-too-far',
                nearestReturnedButRejectedReason: 'too-far-from-candidate',
                sameCorridorDecision,
                insideBlockedDecision: blockedDecision,
                holdWaypointMode: !!workingCandidate.holdWaypoint,
                blockedBearing,
                blockedBearingBucket,
                corridorLength: corridorDistance,
                corridorLengthBucket: _bucketCorridorLength(corridorDistance),
                snapDistanceBucket: _bucketSnapDistance(snappedPoint.distanceM),
                nearestRejectedReason: 'too-far-from-candidate',
                snapEmptyDetail: nearestResult.retrySucceeded ? 'nearest-null-after-retry:retry-too-far' : null,
                rejectedReason: 'too-far-from-candidate'
            });
            return null;
        }
        if (candidate.forceRejectReason) {
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: workingCandidate.point,
                snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
                snapDistanceM: snappedPoint.distanceM,
                corridorDistanceM: corridorDistance,
                blockedDistanceM: blockedDistance,
                bearingDiffDeg: bearingDiff,
                lateralM,
                nearestRetryCount: nearestResult.retryCount,
                nearestRetrySuccess: nearestResult.retrySucceeded,
                nearestStrategyUsed: nearestResult.strategyUsed,
                nearestStrategiesTried,
                nearestStrategyAttempts,
                candidateAdjusted: adjustedResult.adjusted,
                candidateAdjustmentType: adjustedResult.adjustmentType,
                candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
                sameCorridorDecision,
                insideBlockedDecision: blockedDecision,
                holdWaypointMode: !!workingCandidate.holdWaypoint,
                blockedBearing,
                blockedBearingBucket,
                corridorLength: corridorDistance,
                corridorLengthBucket: _bucketCorridorLength(corridorDistance),
                snapDistanceBucket: _bucketSnapDistance(snappedPoint.distanceM),
                nearestRejectedReason: candidate.forceRejectReason,
                nearestFailureReason: candidate.forceRejectReason === 'duplicate-snap'
                    ? 'retry-strategy-exhausted:only-duplicate-candidates'
                    : candidate.forceRejectReason === 'same-corridor'
                        ? 'retry-strategy-exhausted:only-mainline-continuation'
                        : candidate.forceRejectReason,
                nearestReturnedButRejectedReason: candidate.forceRejectReason === 'duplicate-snap'
                    ? 'duplicate'
                    : candidate.forceRejectReason === 'same-corridor'
                        ? 'mainline-only'
                        : candidate.forceRejectReason,
                snapEmptyDetail: nearestResult.retrySucceeded && candidate.forceRejectReason === 'node-build-failure'
                    ? 'nearest-null-after-retry:retry-node-build-failure'
                    : nearestResult.retrySucceeded && candidate.forceRejectReason === 'duplicate-snap'
                        ? 'nearest-null-after-retry:retry-strategy-exhausted:only-duplicate-candidates'
                        : nearestResult.retrySucceeded && candidate.forceRejectReason === 'invalid-bearing'
                            ? 'nearest-null-after-retry:retry-invalid-bearing'
                            : null,
                candidatePositionCategory: positionCategory,
                rejectedReason: candidate.forceRejectReason
            });
            return null;
        }
        const nodeType = (bearingDiff >= BLOCK_ESCAPE_SIDE_BEARING_DEG || sameCorridorDecision === 'soft' || continuationDetected)
            ? 'side-road'
            : 'corridor-like';
        const depthBonus = _escapeDepthRank(candidate.depthKind) * 80;
        const typeBonus = nodeType === 'side-road' ? 120 : 0;
        const sameCorridorPenalty = sameCorridorDecision === 'soft' ? 70 : 0;
        const blockedPenalty = blockedDecision === 'soft' ? 95 : 0;
        const score = depthBonus + typeBonus + (corridorDistance * 1.8) + (bearingDiff * 1.2) + (lateralM * 0.2)
            - (Number(snappedPoint.distanceM || 0) * 0.5) - sameCorridorPenalty - blockedPenalty;
        if (Number.isFinite(Number(candidate.minNodeScore)) && score < Number(candidate.minNodeScore)) {
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: workingCandidate.point,
                snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
                snapDistanceM: snappedPoint.distanceM,
                corridorDistanceM: corridorDistance,
                blockedDistanceM: blockedDistance,
                bearingDiffDeg: bearingDiff,
                lateralM,
                nodeScore: score,
                nearestRetryCount: nearestResult.retryCount,
                nearestRetrySuccess: nearestResult.retrySucceeded,
                nearestStrategyUsed: nearestResult.strategyUsed,
                nearestStrategiesTried,
                nearestStrategyAttempts,
                candidateAdjusted: adjustedResult.adjusted,
                candidateAdjustmentType: adjustedResult.adjustmentType,
                candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
                nearestFailureReason: 'low-corridor-score',
                nearestReturnedButRejectedReason: 'low-corridor-score',
                sameCorridorDecision,
                insideBlockedDecision: blockedDecision,
                holdWaypointMode: !!workingCandidate.holdWaypoint,
                blockedBearing,
                blockedBearingBucket,
                corridorLength: corridorDistance,
                corridorLengthBucket: _bucketCorridorLength(corridorDistance),
                snapDistanceBucket: _bucketSnapDistance(snappedPoint.distanceM),
                nearestRejectedReason: 'low-corridor-score',
                candidatePositionCategory: positionCategory,
                rejectedReason: 'low-corridor-score'
            });
            return null;
        }
        _recordSnapDebugEvent({
            type: 'usable-snapped',
            mode: logPrefix,
            side: candidate.side,
            tier: candidate.distanceTierM,
            depth: candidate.depthKind || 'entrance',
            candidateId: candidate.label,
            rawPoint: workingCandidate.point,
            snappedPoint: { lat: snappedPoint.lat, lng: snappedPoint.lng },
            snapDistanceM: snappedPoint.distanceM,
            corridorDistanceM: corridorDistance,
            blockedDistanceM: blockedDistance,
            bearingDiffDeg: bearingDiff,
            lateralM,
            nodeScore: score,
            nearestRetryCount: nearestResult.retryCount,
            nearestRetrySuccess: nearestResult.retrySucceeded,
            nearestStrategyUsed: nearestResult.strategyUsed,
            nearestStrategiesTried,
            nearestStrategyAttempts,
            strategyOrderUsed: nearestResult.strategyOrderUsed,
            strategiesEnabled: nearestResult.enabledStrategies,
            strategiesPruned: nearestResult.prunedStrategies,
            strategiesDisabled: nearestResult.disabledStrategies,
            strategySkipReasons: nearestResult.strategySkipReasons,
            firstNearestReturnedStrategy: nearestResult.firstNearestReturnedStrategy,
            firstAcceptedStrategy: nearestResult.firstAcceptedStrategy,
            allStrategiesNull: nearestResult.allStrategiesNull,
            allStrategiesRejected: nearestResult.allStrategiesRejected,
            finalRetryOutcome: nearestResult.finalRetryOutcome,
            candidateAdjusted: adjustedResult.adjusted,
            candidateAdjustmentType: adjustedResult.adjustmentType,
            candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
            nearestAcceptedAsRescue: escapeRescueAccepted,
            sameCorridorDecision,
            insideBlockedDecision: blockedDecision,
            sideRoadContinuationDetectedAtSnap: continuationDetected,
            holdWaypointMode: !!workingCandidate.holdWaypoint,
            blockedBearing,
            blockedBearingBucket,
            corridorLength: corridorDistance,
            corridorLengthBucket: _bucketCorridorLength(corridorDistance),
            snapDistanceBucket: _bucketSnapDistance(snappedPoint.distanceM),
            nearestReturnedByRetry: nearestResult.retrySucceeded,
            nodeBuildSuccess: true,
            candidatePositionCategory: positionCategory,
            usable: true
        });
        if (logPrefix === 'escape') {
            console.log(
                `[PedestrianSafety][escape-nearest][summary] candidate=${candidate.label} strategy=${nearestResult.strategyUsed || 'point'} ` +
                `retryCount=${nearestResult.retryCount} adjusted=${adjustedResult.adjusted} accepted=${true} rescue=${escapeRescueAccepted}`
            );
        }
        return {
            ...workingCandidate,
            rawPoint: workingCandidate.originalPoint || candidate.point,
            point: { lat: snappedPoint.lat, lng: snappedPoint.lng },
            snapDistanceM: snappedPoint.distanceM,
            corridorDistanceM: corridorDistance,
            blockedDistanceM: blockedDistance,
            bearingDiffDeg: bearingDiff,
            nodeType,
            nodeScore: score,
            nearestRetryCount: nearestResult.retryCount,
            nearestRetrySuccess: nearestResult.retrySucceeded,
            nearestStrategyUsed: nearestResult.strategyUsed,
            retryProfile: nearestResult.retryProfile,
            firstWinningStrategy: nearestResult.firstAcceptedStrategy || nearestResult.strategyUsed,
            winningStrategyIndex: nearestResult.winningStrategyIndex,
            candidateAdjusted: adjustedResult.adjusted,
            candidateAdjustmentType: adjustedResult.adjustmentType,
            candidateAdjustmentDistance: adjustedResult.adjustmentDistance,
            nearestAcceptedAsRescue: escapeRescueAccepted,
            sideRoadContinuationDetectedAtSnap: continuationDetected,
            sameCorridorDecision,
            insideBlockedDecision: blockedDecision,
            candidatePositionCategory: positionCategory,
            positionCategory,
            entrancePoint: workingCandidate.entrancePoint || workingCandidate.point,
            holdWaypoint: workingCandidate.holdWaypoint || null,
            secondaryHoldWaypoint,
            depthRank: _escapeDepthRank(workingCandidate.depthKind)
        };
    };

    const entranceCandidates = (await Promise.all(rawList.map(evaluateCandidate))).filter(Boolean);
    const deeperRawCandidates = [];
    for (const candidate of entranceCandidates) {
        if (candidate.nodeType !== 'side-road' || !origin) continue;
        const unit = _headingUnitVectorMeters(origin, candidate.point);
        if (!unit) continue;
        for (const depthM of depthSteps) {
            const deeperPoint = _offsetPointByMeters(candidate.point, unit.east * depthM, unit.north * depthM);
            if (!deeperPoint) continue;
            const midHoldRawPoint = depthM >= 120
                ? _offsetPointByMeters(candidate.point, unit.east * Math.min(60, depthM / 2), unit.north * Math.min(60, depthM / 2))
                : null;
            deeperRawCandidates.push({
                ...candidate,
                label: `${candidate.label}-deep-${depthM}`,
                point: deeperPoint,
                depthKind: `deeper-${depthM}`,
                depthMeters: depthM,
                entrancePoint: candidate.point,
                holdWaypoint: candidate.point,
                midHoldRawPoint
            });
        }
    }
    console.log(
        `[BlockAhead][${logPrefix}] generated-tiers=${[...new Set(rawList.map(candidate => candidate.distanceTierM).filter(Number.isFinite))].join('/')} ` +
        `depths=${['entrance', ...depthSteps.map(step => `deeper-${step}`)].join('/')} ` +
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
        )) {
            _recordSnapDebugEvent({
                type: 'reject',
                mode: logPrefix,
                side: candidate.side,
                tier: candidate.distanceTierM,
                depth: candidate.depthKind || 'entrance',
                candidateId: candidate.label,
                rawPoint: candidate.rawPoint || candidate.point,
                snappedPoint: candidate.point,
                snapDistanceM: candidate.snapDistanceM,
                corridorDistanceM: candidate.corridorDistanceM,
                blockedDistanceM: candidate.blockedDistanceM,
                bearingDiffDeg: candidate.bearingDiffDeg,
                nearestRetryCount: candidate.nearestRetryCount,
                nearestRetrySuccess: candidate.nearestRetrySuccess,
                sameCorridorDecision: candidate.sameCorridorDecision,
                insideBlockedDecision: candidate.insideBlockedDecision,
                rejectedReason: 'duplicate-snap'
            });
            continue;
        }
        deduped.push(candidate);
    }
    deduped.sort((a, b) => (b.nodeScore - a.nodeScore) || (b.corridorDistanceM - a.corridorDistanceM));
    console.log(`[BlockAhead][${logPrefix}] snapped-candidates=${deduped.length}`);
    console.log(`[BlockAhead][${logPrefix}] candidate-balance snapped=${_formatCountMap(_countBy(deduped, candidate => Number(candidate.backwardM || 0) > 0 ? `back-${candidate.side}` : candidate.side))}`);
    deduped.forEach(candidate => {
        console.log(
            `[BlockAhead][${logPrefix}] node ${candidate.label}: tier=${candidate.distanceTierM || '-'} depth=${candidate.depthKind || 'entrance'} type=${candidate.nodeType} ` +
            `score=${candidate.nodeScore.toFixed(1)} corridor=${Math.round(candidate.corridorDistanceM)}m ` +
            `bearing=${Math.round(candidate.bearingDiffDeg)}deg snap=${Math.round(candidate.snapDistanceM)}m ` +
            `retry=${Number(candidate.nearestRetryCount || 0)} same=${candidate.sameCorridorDecision || 'pass'} blocked=${candidate.insideBlockedDecision || 'pass'}`
        );
    });
    return deduped;
}

async function _generateEscapePoints(coords, projection, blockedArea) {
    const injected = await _callBlockAheadTestDep('generateEscapePoints', coords, projection, blockedArea);
    if (typeof injected !== 'undefined') {
        if (Array.isArray(injected)) return injected;
        if (injected && Array.isArray(injected.rawCandidates)) {
            return _snapEscapeCandidatesToRoadNodes(injected.rawCandidates, blockedArea, coords, 'escape', injected.options || {});
        }
        return injected;
    }
    const escapeBlockedArea = _buildEscapeGateBlockedArea(coords, projection, blockedArea, 'escape');
    const escapeSpecs = [
        ...BLOCK_ESCAPE_LATERAL_OFFSETS_M.flatMap(lateralM => ([
            { side: 'left', lateralM, backwardM: 0, label: `left-${lateralM}` },
            { side: 'right', lateralM, backwardM: 0, label: `right-${lateralM}` }
        ])),
        ...BLOCK_ESCAPE_BACKWARD_LATERAL_OFFSETS_M.flatMap(lateralM => ([
            { side: 'left', lateralM, backwardM: BLOCK_ESCAPE_BACKWARD_M, label: `back-left-${lateralM}` },
            { side: 'right', lateralM, backwardM: BLOCK_ESCAPE_BACKWARD_M, label: `back-right-${lateralM}` }
        ]))
    ];
    const rawCandidates = _buildRawEscapeCandidates(coords, projection, escapeBlockedArea, escapeSpecs, 'escape', BLOCK_ESCAPE_MAX_POINTS);
    return _snapEscapeCandidatesToRoadNodes(rawCandidates, escapeBlockedArea, coords, 'escape');
}

async function _generateEscapeLegPoints(coords, projection, blockedArea) {
    const injected = await _callBlockAheadTestDep('generateEscapeLegPoints', coords, projection, blockedArea);
    if (typeof injected !== 'undefined') {
        if (Array.isArray(injected)) return injected;
        if (injected && Array.isArray(injected.rawCandidates)) {
            const snappedInjected = await _snapEscapeCandidatesToRoadNodes(injected.rawCandidates, blockedArea, coords, 'escape-leg', injected.options || {});
            return snappedInjected.sort((a, b) => (a.lateralM - b.lateralM) || (b.nodeScore - a.nodeScore));
        }
        return injected;
    }
    const escapeBlockedArea = _buildEscapeGateBlockedArea(coords, projection, blockedArea, 'escape-leg');
    const legSpecs = [
        ...BLOCK_ESCAPE_LEG_LATERAL_OFFSETS_M.flatMap(lateralM => ([
            { side: 'left', lateralM, backwardM: 0, label: `leg-left-${lateralM}` },
            { side: 'right', lateralM, backwardM: 0, label: `leg-right-${lateralM}` }
        ])),
        ...[30, 60].flatMap(lateralM => ([
            { side: 'left', lateralM, backwardM: BLOCK_ESCAPE_LEG_BACKWARD_M, label: `leg-back-left-${lateralM}` },
            { side: 'right', lateralM, backwardM: BLOCK_ESCAPE_LEG_BACKWARD_M, label: `leg-back-right-${lateralM}` }
        ]))
    ];
    const rawCandidates = _buildRawEscapeCandidates(coords, projection, escapeBlockedArea, legSpecs, 'escape-leg', BLOCK_ESCAPE_LEG_MAX_POINTS);
    const snapped = await _snapEscapeCandidatesToRoadNodes(rawCandidates, escapeBlockedArea, coords, 'escape-leg');
    return snapped.sort((a, b) => (a.lateralM - b.lateralM) || (b.nodeScore - a.nodeScore));
}

async function _generateLongDetourEscapePoints(coords, projection, blockedArea) {
    const injected = await _callBlockAheadTestDep('generateLongDetourEscapePoints', coords, projection, blockedArea);
    if (typeof injected !== 'undefined') {
        if (Array.isArray(injected)) return injected;
        if (injected && Array.isArray(injected.rawCandidates)) {
            return _snapEscapeCandidatesToRoadNodes(injected.rawCandidates, blockedArea, coords, 'long-detour', injected.options || {});
        }
        return injected;
    }
    const escapeBlockedArea = _buildEscapeGateBlockedArea(coords, projection, blockedArea, 'long-detour');
    const longLateralOffsets = [...BLOCK_ESCAPE_LATERAL_OFFSETS_M].sort((a, b) => b - a);
    const longBackwardOffsets = [200, 150, 120, 60];
    const longSpecs = [
        ...longLateralOffsets.flatMap(lateralM => ([
            { side: 'left', lateralM, backwardM: 0, label: `long-left-${lateralM}` },
            { side: 'right', lateralM, backwardM: 0, label: `long-right-${lateralM}` }
        ])),
        ...longBackwardOffsets.flatMap(lateralM => ([
            { side: 'left', lateralM, backwardM: BLOCK_ESCAPE_BACKWARD_M, label: `long-back-left-${lateralM}` },
            { side: 'right', lateralM, backwardM: BLOCK_ESCAPE_BACKWARD_M, label: `long-back-right-${lateralM}` }
        ]))
    ];
    const rawCandidates = _buildRawEscapeCandidates(coords, projection, escapeBlockedArea, longSpecs, 'long-detour', BLOCK_ESCAPE_LONG_MAX_POINTS);
    return _snapEscapeCandidatesToRoadNodes(rawCandidates, escapeBlockedArea, coords, 'long-detour', {
        depthSteps: BLOCK_ESCAPE_LONG_DEEPER_STEPS_M
    });
}

// 経路座標の中でブロックバッファ（円）内に入っている点の割合を返す
function _calcBlockOverlapRatio(coords, centerLat, centerLng, radiusM) {
    const injected = _getBlockAheadTestDeps();
    if (injected && typeof injected.blockOverlapRatio === 'function') {
        const mocked = injected.blockOverlapRatio(coords, centerLat, centerLng, radiusM);
        if (Number.isFinite(Number(mocked))) return Number(mocked);
    }
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
    const injected = _getBlockAheadTestDeps();
    if (injected && typeof injected.routeBlockedAreaStats === 'function') {
        const mocked = injected.routeBlockedAreaStats(coords, blockedArea);
        if (mocked && typeof mocked === 'object') {
            return {
                strictOverlapRatio: 0,
                nearBlockedRatio: 0,
                minDistanceToAreaM: Infinity,
                intersects: false,
                nearBlocked: false,
                slitIntersectionDetected: false,
                slitBodyIntersectionDetected: false,
                slitCapIntersectionDetected: false,
                slitNearDetected: false,
                coreIntersectionDetected: false,
                intersectionBufferDetected: false,
                legacyBroadIntersectionDetected: false,
                carveOutAdjustedIntersectionDetected: false,
                softIntersectionBufferDetected: false,
                softSlitBodyIntersectionDetected: false,
                hardIntersectionDetected: false,
                effectiveIntersectionBufferRadius: Number(blockedArea?.intersectionRadiusM || blockedArea?.intersectionBufferM || 0),
                effectiveSlitBodyPolicy: 'default',
                candidateSide: null,
                slitBodyOverlapRatio: 0,
                slitCapOverlapRatio: 0,
                slitNearRatio: 0,
                coreOverlapRatio: 0,
                intersectionBufferOverlapRatio: 0,
                ...mocked
            };
        }
    }
    const sampled = [];
    const ignoreUntilM = Number(blockedArea?.ignoreUntilM || 0);
    if (!Array.isArray(coords) || coords.length === 0) {
        return {
            strictOverlapRatio: 0, nearBlockedRatio: 0, minDistanceToAreaM: Infinity, intersects: false, nearBlocked: false,
            slitIntersectionDetected: false, coreIntersectionDetected: false, intersectionBufferDetected: false,
            legacyBroadIntersectionDetected: false, carveOutAdjustedIntersectionDetected: false,
            softIntersectionBufferDetected: false,
            softSlitBodyIntersectionDetected: false,
            hardIntersectionDetected: false,
            effectiveIntersectionBufferRadius: Number(blockedArea?.intersectionRadiusM || blockedArea?.intersectionBufferM || 0),
            effectiveSlitBodyPolicy: 'default',
            candidateSide: null
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
            legacyBroadIntersectionDetected: false, carveOutAdjustedIntersectionDetected: false,
            softIntersectionBufferDetected: false,
            softSlitBodyIntersectionDetected: false,
            hardIntersectionDetected: false,
            effectiveIntersectionBufferRadius: Number(blockedArea?.intersectionRadiusM || blockedArea?.intersectionBufferM || 0),
            effectiveSlitBodyPolicy: 'default',
            candidateSide: null
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
        softIntersectionBufferDetected: false,
        softSlitBodyIntersectionDetected: false,
        hardIntersectionDetected: slitBodyIntersectionDetected || coreIntersectionDetected || intersectionBufferDetected,
        effectiveIntersectionBufferRadius: Number(blockedArea?.intersectionRadiusM || blockedArea?.intersectionBufferM || 0),
        effectiveSlitBodyPolicy: 'default',
        candidateSide: null,
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

function _normalizePedestrianSafetyBounds(bounds) {
    if (!bounds) return null;
    const minLat = Number(bounds.minLat ?? bounds.south);
    const minLng = Number(bounds.minLng ?? bounds.west);
    const maxLat = Number(bounds.maxLat ?? bounds.north);
    const maxLng = Number(bounds.maxLng ?? bounds.east);
    if (![minLat, minLng, maxLat, maxLng].every(Number.isFinite)) return null;
    return {
        minLat,
        minLng,
        maxLat,
        maxLng,
        south: minLat,
        west: minLng,
        north: maxLat,
        east: maxLng
    };
}

function _boundsContainsPoint(bounds, point) {
    const normalized = _normalizePedestrianSafetyBounds(bounds);
    const lat = Number(point?.lat);
    const lng = Number(point?.lng ?? point?.lon);
    if (!normalized || !Number.isFinite(lat) || !Number.isFinite(lng)) return false;
    return lat >= normalized.minLat && lat <= normalized.maxLat && lng >= normalized.minLng && lng <= normalized.maxLng;
}

function _clonePedestrianSafetyFailure(extra = {}) {
    return {
        kind: 'none',
        message: '',
        aborted: false,
        abortSource: 'none',
        detail: 'none',
        ...extra
    };
}

function _buildPedestrianSafetyContextBBox(params = {}) {
    const points = [];
    const pushPoint = (point) => {
        const lat = Number(point?.lat);
        const lng = Number(point?.lng ?? point?.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
        points.push({ lat, lng });
    };
    const pushPoints = (items) => {
        for (const item of Array.isArray(items) ? items : []) pushPoint(item);
    };

    pushPoints(params.points);
    pushPoint(params.currentLocation);
    pushPoint(params.startWp);
    pushPoint(params.destWp);
    pushPoint(params.blockStart);
    pushPoint(params.blockEnd);
    pushPoints(params.blockedCenters);
    pushPoints(params.stageEndpoints);
    pushPoints(params.rawCandidates);
    pushPoints(params.snappedCandidates);
    pushPoints(params.routeCoords);

    const baseBounds = _routeBoundsWithPadding(points, Number(params.paddingM ?? PEDESTRIAN_SAFETY_BBOX_PADDING_M));
    return _normalizePedestrianSafetyBounds(baseBounds);
}

function _classifyPedestrianContextFailure(error, meta = {}) {
    const status = Number(meta.status);
    const aborted = !!meta.aborted || error?.name === 'AbortError';
    const abortSource = meta.abortSource || (aborted ? 'reroute-cancel' : 'none');
    const message = String(meta.message || error?.message || error || '').trim();
    if (meta.kind === 'empty-result') {
        return _clonePedestrianSafetyFailure({
            kind: 'empty-result',
            message: message || 'pedestrian context fetch returned empty result',
            aborted: false,
            abortSource: 'none',
            detail: meta.detail || 'empty-overpass-result'
        });
    }
    if (meta.kind === 'invalid-response') {
        return _clonePedestrianSafetyFailure({
            kind: 'invalid-response',
            message: message || 'pedestrian context response was invalid',
            aborted: false,
            abortSource: 'none',
            detail: meta.detail || 'invalid-json-structure'
        });
    }
    if (aborted && abortSource === 'timeout') {
        return _clonePedestrianSafetyFailure({
            kind: 'timeout',
            message: message || `pedestrian context fetch timed out after ${PEDESTRIAN_SAFETY_FETCH_TIMEOUT_MS}ms`,
            aborted: true,
            abortSource: 'timeout',
            detail: meta.detail || 'core-fetch-timeout'
        });
    }
    if (aborted) {
        return _clonePedestrianSafetyFailure({
            kind: 'aborted',
            message: message || 'pedestrian context fetch aborted by reroute cancellation',
            aborted: true,
            abortSource,
            detail: meta.detail || (abortSource === 'superseded-request' ? 'seq-replaced' : 'manual-abort')
        });
    }
    if (Number.isFinite(status) && status >= 400) {
        return _clonePedestrianSafetyFailure({
            kind: 'fetch-error',
            message: message || `pedestrian context fetch failed with HTTP ${status}`,
            aborted: false,
            abortSource: 'none',
            detail: meta.detail || `http-${status}`
        });
    }
    return _clonePedestrianSafetyFailure({
        kind: 'fetch-error',
        message: message || 'pedestrian context fetch failed',
        aborted: false,
        abortSource: 'none',
        detail: meta.detail || 'network-error'
    });
}

function _pedestrianSafetyCacheEntryTtl(record) {
    if (!record) return 0;
    if (record.status === 'ready') return PEDESTRIAN_SAFETY_SUCCESS_CACHE_TTL_MS;
    if (record.failure?.kind === 'timeout') return PEDESTRIAN_SAFETY_TIMEOUT_CACHE_TTL_MS;
    return PEDESTRIAN_SAFETY_FAILURE_CACHE_TTL_MS;
}

function _buildPedestrianSafetyOverpassQuery(bounds, phase = 'core') {
    const normalizedBounds = _normalizePedestrianSafetyBounds(bounds);
    if (!normalizedBounds) return '';
    const area = `${normalizedBounds.minLat},${normalizedBounds.minLng},${normalizedBounds.maxLat},${normalizedBounds.maxLng}`;
    const body = phase === 'extended'
        ? `
  way["highway"~"tertiary|tertiary_link|residential|service|living_street|footway|path|pedestrian"](${area});
  node["crossing"="traffic_signals"](${area});
  node["crossing"="marked"](${area});
  node["highway"="crossing"](${area});
  way["highway"="footway"]["footway"="crossing"](${area});
`
        : `
  way["highway"~"motorway|motorway_link|trunk|trunk_link|primary|primary_link|secondary|secondary_link|tertiary|tertiary_link"](${area});
  way["motorroad"="yes"](${area});
  node["highway"="crossing"](${area});
  node["crossing"](${area});
  node["highway"="traffic_signals"](${area});
  way["highway"="footway"]["footway"="crossing"](${area});
`;
    return `
[out:json][timeout:8];
(
${body}
);
(._;>;);
out body;
`.trim();
}

function _mergePedestrianSafetyContexts(baseContext, extraContext) {
    const baseRoads = Array.isArray(baseContext?.roads) ? baseContext.roads : [];
    const extraRoads = Array.isArray(extraContext?.roads) ? extraContext.roads : [];
    const mergedRoads = [];
    const seenRoadIds = new Set();
    for (const road of [...baseRoads, ...extraRoads]) {
        const id = String(road?.id ?? '');
        if (id && seenRoadIds.has(id)) continue;
        if (id) seenRoadIds.add(id);
        mergedRoads.push(road);
    }
    return {
        roads: mergedRoads,
        crosswalks: _dedupeNearbyPoints([
            ...(Array.isArray(baseContext?.crosswalks) ? baseContext.crosswalks : []),
            ...(Array.isArray(extraContext?.crosswalks) ? extraContext.crosswalks : [])
        ], 8)
    };
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
    let found = null;
    let minDist = Infinity;
    for (const item of crosswalks) {
        const dist = _segmentLengthMeters(point, item);
        if (dist <= radiusM && dist < minDist) { minDist = dist; found = item; }
    }
    if (!found) return null;
    const tags = found.tags || {};
    const signalized = tags.crossing === 'traffic_signals' || tags.highway === 'traffic_signals';
    const marked = tags.highway === 'crossing'
        || tags.footway === 'crossing'
        || tags.crossing === 'marked'
        || tags.crossing === 'zebra'
        || signalized;
    return {
        type: signalized ? 'signalized' : 'marked',
        tags,
        point: found,
        distM: minDist,
        signalized,
        marked
    };
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

async function _fetchPedestrianSafetyContextForBBox(bbox, options = {}) {
    const injected = await _callBlockAheadTestDep('fetchPedestrianSafetyContext', bbox, options);
    if (typeof injected !== 'undefined') return injected;
    const normalizedBounds = _normalizePedestrianSafetyBounds(bbox);
    const fetchPhase = options.fetchPhase || 'core';
    const sourceLabel = options.sourceLabel || 'compact-cache';
    if (!normalizedBounds) {
        return {
            status: 'unavailable',
            context: null,
            source: sourceLabel,
            bbox: null,
            fetchedAt: Date.now(),
            failure: _classifyPedestrianContextFailure(null, {
                kind: 'invalid-response',
                message: 'pedestrian context bbox was invalid',
                detail: 'bbox-invalid'
            })
        };
    }
    const cacheKey = _pedestrianSafetyCacheKey(normalizedBounds);
    const cached = _pedestrianSafetyContextCache.get(cacheKey);
    if (cached && (Date.now() - cached.at) < _pedestrianSafetyCacheEntryTtl(cached)) {
        return {
            status: cached.status,
            context: cached.value,
            source: cached.source || sourceLabel,
            bbox: normalizedBounds,
            fetchedAt: cached.at,
            failure: cached.failure || _clonePedestrianSafetyFailure()
        };
    }
    if (typeof navigator !== 'undefined' && navigator.webdriver) {
        return {
            status: 'unavailable',
            context: null,
            source: sourceLabel,
            bbox: normalizedBounds,
            fetchedAt: Date.now(),
            failure: _classifyPedestrianContextFailure(null, {
                kind: 'aborted',
                message: 'pedestrian context fetch disabled under webdriver',
                aborted: true,
                abortSource: 'webdriver',
                detail: 'webdriver-disabled'
            })
        };
    }

    const pedestrianController = typeof AbortController !== 'undefined' ? new AbortController() : null;
    let timeoutTriggered = false;
    const timeoutId = pedestrianController ? setTimeout(() => {
        timeoutTriggered = true;
        pedestrianController.abort('timeout');
    }, PEDESTRIAN_SAFETY_FETCH_TIMEOUT_MS) : null;

    try {
        const fetchPhaseOnce = async (phase) => {
            console.log(`[PedestrianSafety][fetch] phase=${phase} bbox=${JSON.stringify(normalizedBounds)}`);
            const res = await fetch(PEDESTRIAN_SAFETY_OVERPASS_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
                body: _buildPedestrianSafetyOverpassQuery(normalizedBounds, phase),
                signal: pedestrianController?.signal
            });
            if (!res.ok) {
                throw Object.assign(new Error(`pedestrian context fetch failed with HTTP ${res.status}`), {
                    __pedestrianStatus: res.status,
                    __pedestrianDetail: `${phase}-http-${res.status}`
                });
            }
            const data = await res.json();
            const parsed = _parsePedestrianSafetyContext(data);
            if (!parsed || !Array.isArray(parsed.roads) || !Array.isArray(parsed.crosswalks)) {
                throw Object.assign(new Error('pedestrian context response structure was invalid'), {
                    __pedestrianKind: 'invalid-response',
                    __pedestrianDetail: `${phase}-invalid-structure`
                });
            }
            return parsed;
        };

        const coreContext = await fetchPhaseOnce(fetchPhase);
        let parsed = coreContext;
        const shouldFetchExtended = options.allowExtendedFetch !== false
            && ((Array.isArray(coreContext?.roads) ? coreContext.roads.length : 0) < 3)
            && (Array.isArray(coreContext?.crosswalks) ? coreContext.crosswalks.length : 0) < 2;
        if (shouldFetchExtended) {
            try {
                const extendedContext = await fetchPhaseOnce('extended');
                parsed = _mergePedestrianSafetyContexts(coreContext, extendedContext);
            } catch (extendedError) {
                console.warn(`[PedestrianSafety][fetch] phase=extended skipped message=${extendedError?.message || extendedError}`);
            }
        }

        if (parsed.roads.length === 0 && parsed.crosswalks.length === 0) {
            const failure = _classifyPedestrianContextFailure(null, {
                kind: 'empty-result',
                message: 'pedestrian context fetch returned empty result',
                detail: `${fetchPhase}-empty-result`
            });
            _pedestrianSafetyContextCache.set(cacheKey, {
                at: Date.now(),
                status: 'unavailable',
                value: null,
                failure,
                source: sourceLabel
            });
            return {
                status: 'unavailable',
                context: null,
                source: sourceLabel,
                bbox: normalizedBounds,
                fetchedAt: Date.now(),
                failure
            };
        }
        const fetchedAt = Date.now();
        _pedestrianSafetyContextCache.set(cacheKey, {
            at: fetchedAt,
            status: 'ready',
            value: parsed,
            failure: _clonePedestrianSafetyFailure(),
            source: sourceLabel
        });
        return {
            status: 'ready',
            context: parsed,
            source: sourceLabel,
            bbox: normalizedBounds,
            fetchedAt,
            failure: _clonePedestrianSafetyFailure()
        };
    } catch (error) {
        const failure = _classifyPedestrianContextFailure(error, {
            aborted: !!pedestrianController?.signal?.aborted,
            abortSource: timeoutTriggered ? 'timeout' : (options.abortSource || 'manual-abort'),
            status: error?.__pedestrianStatus,
            detail: error?.__pedestrianDetail || (timeoutTriggered ? `${fetchPhase}-fetch-timeout` : `${fetchPhase}-fetch-error`)
        });
        _pedestrianSafetyContextCache.set(cacheKey, {
            at: Date.now(),
            status: 'unavailable',
            value: null,
            failure,
            source: sourceLabel
        });
        return {
            status: 'unavailable',
            context: null,
            source: sourceLabel,
            bbox: normalizedBounds,
            fetchedAt: Date.now(),
            failure
        };
    } finally {
        if (timeoutId) clearTimeout(timeoutId);
    }
}

async function _getOrCreatePedestrianSafetyContextForSeq(seqContext, options = {}) {
    const contextLabel = options.contextLabel || 'route';
    if (!seqContext) {
        return {
            seq: null,
            status: 'unavailable',
            context: null,
            source: 'cache',
            bbox: null,
            fetchedAt: Date.now(),
            failure: _classifyPedestrianContextFailure(null, {
                kind: 'invalid-response',
                message: 'pedestrian safety seq context was missing'
            })
        };
    }
    if (seqContext.status === 'ready' || seqContext.status === 'unavailable') {
        console.log(`[PedestrianSafety][context] seq=${seqContext.seq} source=${seqContext.source} reused=true`);
        return seqContext;
    }
    const fetched = await _fetchPedestrianSafetyContextForBBox(seqContext.bbox, {
        ...options,
        sourceLabel: seqContext.source || 'compact-cache',
        fetchPhase: seqContext.fetchPhase || 'core'
    });
    seqContext.status = fetched.status;
    seqContext.context = fetched.context;
    seqContext.fetchedAt = fetched.fetchedAt;
    seqContext.failure = fetched.failure || _clonePedestrianSafetyFailure();
    seqContext.source = fetched.source;
    console.log(
        `[PedestrianSafety][context] seq=${seqContext.seq} bbox=${JSON.stringify(seqContext.bbox)} source=${seqContext.source}`
    );
    if (seqContext.status !== 'ready') {
        console.warn(
            `[PedestrianSafety][context] seq=${seqContext.seq} failed kind=${seqContext.failure.kind} ` +
            `detail=${seqContext.failure.detail || 'none'} aborted=${!!seqContext.failure.aborted} message=${seqContext.failure.message || ''}`
        );
    }
    return seqContext;
}

async function _expandPedestrianSafetyContextBBoxIfNeeded(seqContext, route, options = {}) {
    if (!seqContext || seqContext.expanded) return seqContext;
    const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    const needsExpansion = coords.some(point => !_boundsContainsPoint(seqContext.bbox, point));
    if (!needsExpansion) return seqContext;
    const expandedBBox = _buildPedestrianSafetyContextBBox({
        points: [...(seqContext.seedPoints || []), ...coords],
        paddingM: Number(options.paddingM ?? PEDESTRIAN_SAFETY_EXPANDED_BBOX_PADDING_M)
    });
    if (!expandedBBox) return seqContext;
    const fetched = await _fetchPedestrianSafetyContextForBBox(expandedBBox, {
        ...options,
        sourceLabel: 'expanded-cache',
        fetchPhase: 'core'
    });
    seqContext.bbox = expandedBBox;
    seqContext.status = fetched.status;
    seqContext.context = fetched.context;
    seqContext.fetchedAt = fetched.fetchedAt;
    seqContext.failure = fetched.failure || _clonePedestrianSafetyFailure();
    seqContext.source = 'expanded-cache';
    seqContext.expanded = true;
    console.log(`[PedestrianSafety][context] seq=${seqContext.seq} source=expanded-cache bbox=${JSON.stringify(expandedBBox)}`);
    if (seqContext.status !== 'ready') {
        console.warn(
            `[PedestrianSafety][context] seq=${seqContext.seq} failed kind=${seqContext.failure.kind} ` +
            `detail=${seqContext.failure.detail || 'none'} aborted=${!!seqContext.failure.aborted} message=${seqContext.failure.message || ''}`
        );
    }
    return seqContext;
}

async function _fetchPedestrianSafetyContextForRoute(route, contextLabel = 'route') {
    const bbox = _buildPedestrianSafetyContextBBox({
        routeCoords: Array.isArray(route?.coordinates) ? route.coordinates : [],
        paddingM: PEDESTRIAN_SAFETY_BBOX_PADDING_M
    });
    const result = await _fetchPedestrianSafetyContextForBBox(bbox, { contextLabel });
    return result?.context || null;
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
    const crosswalkResult = _findCrosswalkNearby(crossing?.point, context, PEDESTRIAN_SAFETY_CROSSWALK_RADIUS_M);
    const crosswalkNearby = !!crosswalkResult;               // 後方互換 bool
    const crossingType = crosswalkResult?.type || null;       // 'signalized' | 'marked' | null
    const signalizedCrossing = !!crosswalkResult?.signalized;
    const markedCrossing = !!crosswalkResult?.marked;
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
        crossingType,
        signalizedCrossing,
        markedCrossing,
        safeCrossingPoint: crosswalkResult?.point || null,
        safeCrossingDistanceM: Number(crosswalkResult?.distM || 0),
        motorroad,
        footNo,
        divided
    };
}

function _makePedestrianSafetyResult(status, extra = {}) {
    const normalizedStatus = ['safe', 'unsafe', 'unknown'].includes(status) ? status : 'unknown';
    return {
        status: normalizedStatus,
        safe: normalizedStatus === 'safe',
        unsafe: normalizedStatus === 'unsafe',
        contextUnavailable: normalizedStatus === 'unknown',
        failOpenApplied: normalizedStatus === 'unknown',
        crossings: [],
        dangerousCrossings: [],
        rejectReason: null,
        ...extra
    };
}

function _evaluatePedestrianRouteAgainstContext(route, context, options = {}) {
    const crossings = _detectPedestrianCrossings(route, context);
    const classifiedCrossings = crossings
        .map(crossing => ({
            ...crossing,
            classification: _classifyDangerousCrossing(crossing, context, options)
        }));
    const dangerousCrossings = classifiedCrossings.filter(item => item.classification.dangerous);

    if (dangerousCrossings.length === 0) {
        console.log('[PedestrianSafety] status=safe crossingDetected=false dangerous=false rejectReason=none failOpenApplied=false');
        return _makePedestrianSafetyResult('safe', {
            crossings: classifiedCrossings,
            dangerousCrossings: [],
            contextUnavailable: false,
            failOpenApplied: false,
            rejectReason: null
        });
    }

    const first = dangerousCrossings[0];
    console.log(
        `[PedestrianSafety] status=unsafe crossingDetected=true dangerous=true roadType=${first.classification.highway || 'unknown'} ` +
        `lanes=${first.classification.lanes || 0} crosswalkNearby=${!!first.classification.crosswalkNearby} ` +
        `crossingType=${first.classification.crossingType || 'none'} ` +
        `rejectReason=dangerous-crossing detail=${first.classification.reason || 'unknown'} failOpenApplied=false`
    );
    return _makePedestrianSafetyResult('unsafe', {
        crossings: classifiedCrossings,
        dangerousCrossings,
        contextUnavailable: false,
        failOpenApplied: false,
        rejectReason: 'dangerous-crossing'
    });
}

async function _evaluatePedestrianRouteSafety(route, cachedContext, contextLabel = 'route', options = {}) {
    const injected = await _callBlockAheadTestDep('evaluatePedestrianRouteSafety', route, cachedContext, contextLabel, options);
    if (injected && typeof injected === 'object') {
        return {
            status: 'unknown',
            safe: false,
            unsafe: false,
            contextUnavailable: true,
            failOpenApplied: true,
            crossings: [],
            dangerousCrossings: [],
            rejectReason: null,
            label: contextLabel,
            contextSource: cachedContext?.source || 'unknown',
            contextFailureKind: cachedContext?.failure?.kind || 'none',
            contextFailureDetail: cachedContext?.failure?.detail || 'none',
            contextFailureMessage: cachedContext?.failure?.message || '',
            contextBBox: cachedContext?.bbox || null,
            contextSeq: cachedContext?.seq || null,
            ...injected
        };
    }
    let seqContext = cachedContext;
    if (!seqContext || typeof seqContext !== 'object' || !('seq' in seqContext || 'status' in seqContext)) {
        seqContext = {
            seq: null,
            bbox: _buildPedestrianSafetyContextBBox({
                routeCoords: Array.isArray(route?.coordinates) ? route.coordinates : [],
                paddingM: PEDESTRIAN_SAFETY_COMPACT_BBOX_PADDING_M
            }),
            status: 'pending',
            context: null,
            fetchedAt: 0,
            source: 'compact-cache',
            fetchPhase: 'core',
            expanded: false,
            seedPoints: Array.isArray(route?.coordinates) ? route.coordinates : [],
            failure: _clonePedestrianSafetyFailure()
        };
    }
    const hadExistingContext = seqContext.status === 'ready' || seqContext.status === 'unavailable';
    await _getOrCreatePedestrianSafetyContextForSeq(seqContext, { contextLabel });
    if (seqContext.status !== 'ready') {
        const routeContextSource = seqContext.source === 'expanded-cache'
            ? 'expanded-cache'
            : (seqContext.source === 'compact-cache' ? 'compact-cache' : (hadExistingContext ? 'compact-cache' : (seqContext.source || 'compact-cache')));
        const failure = seqContext.failure || _clonePedestrianSafetyFailure();
        console.log(
            `[PedestrianSafety] status=unknown label=${contextLabel} contextSource=${routeContextSource} ` +
            `contextFailureKind=${failure.kind} contextFailureDetail=${failure.detail || 'none'} failOpenApplied=true contextUnavailable=true`
        );
        if (String(contextLabel || '').startsWith('final:')) {
            console.log(
                `[PedestrianSafety] final-check unavailable -> fail-open applied label=${contextLabel} ` +
                `contextSource=${routeContextSource} contextFailureKind=${failure.kind} contextFailureDetail=${failure.detail || 'none'}`
            );
        }
        return _makePedestrianSafetyResult('unknown', {
            contextUnavailable: true,
            failOpenApplied: true,
            rejectReason: null,
            label: contextLabel,
            contextSource: routeContextSource,
            contextFailureKind: failure.kind,
            contextFailureDetail: failure.detail || 'none',
            contextFailureMessage: failure.message,
            contextBBox: seqContext.bbox,
            contextSeq: seqContext.seq
        });
    }
    if (Array.isArray(route?.coordinates) && route.coordinates.length > 0) {
        await _expandPedestrianSafetyContextBBoxIfNeeded(seqContext, route, { contextLabel });
    }
    const routeContextSource = seqContext.source === 'expanded-cache'
        ? 'expanded-cache'
        : (seqContext.source === 'compact-cache' ? 'compact-cache' : (hadExistingContext ? 'compact-cache' : (seqContext.source || 'compact-cache')));
    if (seqContext.status !== 'ready' || !seqContext.context || !Array.isArray(seqContext.context.roads) || seqContext.context.roads.length === 0) {
        const failure = seqContext.failure || _clonePedestrianSafetyFailure({
            kind: 'empty-result',
            message: 'pedestrian context had no usable roads'
        });
        console.log(
            `[PedestrianSafety] status=unknown label=${contextLabel} contextSource=${routeContextSource} ` +
            `contextFailureKind=${failure.kind} contextFailureDetail=${failure.detail || 'none'} failOpenApplied=true contextUnavailable=true`
        );
        return _makePedestrianSafetyResult('unknown', {
            contextUnavailable: true,
            failOpenApplied: true,
            rejectReason: null,
            label: contextLabel,
            contextSource: routeContextSource,
            contextFailureKind: failure.kind,
            contextFailureDetail: failure.detail || 'none',
            contextFailureMessage: failure.message,
            contextBBox: seqContext.bbox,
            contextSeq: seqContext.seq
        });
    }
    const result = _evaluatePedestrianRouteAgainstContext(route, seqContext.context, options);
    return {
        ...result,
        contextUnavailable: false,
        failOpenApplied: false,
        label: contextLabel,
        contextSource: routeContextSource,
        contextFailureKind: seqContext.failure?.kind || 'none',
        contextFailureDetail: seqContext.failure?.detail || 'none',
        contextFailureMessage: seqContext.failure?.message || '',
        contextBBox: seqContext.bbox,
        contextSeq: seqContext.seq
    };
}

function _evaluateConservativeUnknownPedestrianSafety(route, options = {}) {
    const injected = _getBlockAheadTestDeps();
    if (injected && typeof injected.evaluateConservativeUnknownPedestrianSafety === 'function') {
        const mocked = injected.evaluateConservativeUnknownPedestrianSafety(route, options);
        if (mocked && typeof mocked === 'object') {
            return {
                conservativeRejectEvaluated: true,
                conservativeRejectApplied: false,
                conservativeDecision: 'pass',
                conservativeRejectReason: null,
                conservativePenalty: 0,
                suspiciousSegmentIndex: -1,
                suspiciousSegmentLengthM: 0,
                phase: options.phase || options.mode || 'candidate',
                mode: options.mode || options.phase || 'candidate',
                side: options.side || 'unknown',
                metrics: {
                    longestCrossingSegment: 0,
                    totalCrossingDistance: 0,
                    crossingSegmentCount: 0,
                    maxCrossingRoadClass: 'unknown',
                    wideRoadReturnDetected: false,
                    diagonalMainlineShortcutDetected: false,
                    sideRoadContinuationDetected: false,
                    routeStartsAlongCorridorThenEscapes: false,
                    routeEndsWithWideRoadReturn: false,
                    forwardProgressRatio: 0,
                    candidateBearingVsBlockedBearing: null
                },
                ...mocked
            };
        }
    }
    const coords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    const totalDistance = Number(route?.totalDistance || route?.summary?.totalDistance || 0);
    const mode = options.mode || options.phase || 'candidate';
    const side = options.side || 'unknown';
    const nearPenaltyMode = options.nearPenaltyMode || {};
    const hardIntersectionDetected = !!options.hardIntersectionDetected;
    const actualIntersectionDetected = !!options.actualIntersectionDetected;
    const blockedBearing = Number.isFinite(options.blockedBearing) ? options.blockedBearing : null;
    const result = {
        conservativeRejectEvaluated: true,
        conservativeRejectApplied: false,
        conservativeDecision: 'pass',
        conservativeRejectReason: null,
        conservativePenalty: 0,
        suspiciousSegmentIndex: -1,
        suspiciousSegmentLengthM: 0,
        phase: options.phase || mode,
        mode,
        side,
        metrics: {
            longestCrossingSegment: 0,
            totalCrossingDistance: 0,
            crossingSegmentCount: 0,
            maxCrossingRoadClass: 'unknown',
            wideRoadReturnDetected: false,
            diagonalMainlineShortcutDetected: false,
            sideRoadContinuationDetected: false,
            routeStartsAlongCorridorThenEscapes: false,
            routeEndsWithWideRoadReturn: false,
            forwardProgressRatio: 0,
            candidateBearingVsBlockedBearing: null
        }
    };
    if (coords.length < 2) return result;

    const netDisplacement = _segmentLengthMeters(coords[0], coords[coords.length - 1]);
    result.metrics.forwardProgressRatio = totalDistance > 0 ? netDisplacement / totalDistance : 0;

    const firstBearing = coords.length >= 2 ? _segmentBearingDeg(coords[0], coords[1]) : null;
    const finalBearing = coords.length >= 2 ? _segmentBearingDeg(coords[Math.max(0, coords.length - 2)], coords[coords.length - 1]) : null;
    result.metrics.candidateBearingVsBlockedBearing = Number.isFinite(blockedBearing) && Number.isFinite(firstBearing)
        ? _bearingDiffDeg(firstBearing, blockedBearing)
        : null;
    result.metrics.routeStartsAlongCorridorThenEscapes = Number.isFinite(blockedBearing)
        && Number.isFinite(firstBearing)
        && Number.isFinite(finalBearing)
        && _bearingDiffDeg(firstBearing, blockedBearing) <= 28
        && _bearingDiffDeg(finalBearing, blockedBearing) >= 35;

    const rescueLikeMode = mode === 'escape-leg' || mode === 'escape' || mode === 'long-detour' || mode.startsWith('final:');
    const rescueLikeSide = side === 'back-left' || side === 'back-right';
    const rescueLike = rescueLikeMode && (rescueLikeSide || (!!nearPenaltyMode.eligible && !hardIntersectionDetected && !actualIntersectionDetected));

    for (let i = 1; i < coords.length; i++) {
        const prev = coords[i - 1];
        const curr = coords[i];
        const segmentLength = _segmentLengthMeters(prev, curr);
        const prevSegmentLength = i >= 2 ? _segmentLengthMeters(coords[i - 2], prev) : Infinity;
        const nextSegmentLength = i + 1 < coords.length ? _segmentLengthMeters(curr, coords[i + 1]) : Infinity;
        const segmentBearing = _segmentBearingDeg(prev, curr);
        const prevBearing = i >= 2 ? _segmentBearingDeg(coords[i - 2], prev) : null;
        const nextBearing = i + 1 < coords.length ? _segmentBearingDeg(curr, coords[i + 1]) : null;
        const prevDiff = Number.isFinite(prevBearing) ? _bearingDiffDeg(prevBearing, segmentBearing) : 0;
        const nextDiff = Number.isFinite(nextBearing) ? _bearingDiffDeg(segmentBearing, nextBearing) : 0;
        const isFinalSegment = i === coords.length - 1;
        const suspiciousWideCross = segmentLength >= PEDESTRIAN_SAFETY_UNKNOWN_WIDE_CROSS_SEGMENT_M
            && (prevDiff >= PEDESTRIAN_SAFETY_UNKNOWN_TURN_DIFF_DEG || nextDiff >= PEDESTRIAN_SAFETY_UNKNOWN_TURN_DIFF_DEG)
            && (prevSegmentLength <= 25 || nextSegmentLength <= 25);
        const suspiciousShortcutCross = segmentLength >= Math.max(PEDESTRIAN_SAFETY_UNKNOWN_CROSS_SEGMENT_M, totalDistance * 0.18)
            && prevDiff >= (PEDESTRIAN_SAFETY_UNKNOWN_TURN_DIFF_DEG + 10)
            && nextDiff >= (PEDESTRIAN_SAFETY_UNKNOWN_TURN_DIFF_DEG + 10)
            && prevSegmentLength <= 25
            && nextSegmentLength <= 25;
        const suspiciousFinalReturn = isFinalSegment
            && segmentLength >= PEDESTRIAN_SAFETY_UNKNOWN_FINAL_RETURN_M
            && prevDiff >= (PEDESTRIAN_SAFETY_UNKNOWN_TURN_DIFF_DEG + 15)
            && prevSegmentLength <= 25;
        if (!suspiciousWideCross && !suspiciousShortcutCross && !suspiciousFinalReturn) continue;

        result.metrics.crossingSegmentCount += 1;
        result.metrics.totalCrossingDistance += segmentLength;
        result.metrics.longestCrossingSegment = Math.max(result.metrics.longestCrossingSegment, segmentLength);
        result.metrics.maxCrossingRoadClass = suspiciousShortcutCross ? 'major' : (suspiciousWideCross ? 'wide' : result.metrics.maxCrossingRoadClass);
        if (suspiciousFinalReturn) {
            result.metrics.wideRoadReturnDetected = true;
            result.metrics.routeEndsWithWideRoadReturn = true;
        }
        if (suspiciousShortcutCross) {
            result.metrics.diagonalMainlineShortcutDetected = true;
        }
        if (rescueLike && !suspiciousShortcutCross && !suspiciousFinalReturn && segmentLength <= (PEDESTRIAN_SAFETY_UNKNOWN_WIDE_CROSS_SEGMENT_M + 8)) {
            result.metrics.sideRoadContinuationDetected = true;
        }
        if (result.suspiciousSegmentIndex === -1) {
            result.suspiciousSegmentIndex = i - 1;
            result.suspiciousSegmentLengthM = segmentLength;
        }
    }

    const longestCrossingSegment = result.metrics.longestCrossingSegment;
    const totalCrossingDistanceM = result.metrics.totalCrossingDistance;
    const crossingCount = result.metrics.crossingSegmentCount;
    const diagonalMainlineShortcutDetected = result.metrics.diagonalMainlineShortcutDetected;
    const wideRoadReturnDetected = result.metrics.wideRoadReturnDetected;
    const sideRoadContinuationDetected = result.metrics.sideRoadContinuationDetected;

    let decision = 'pass';
    let reason = null;
    let penalty = 0;

    if (wideRoadReturnDetected) {
        decision = 'hard-reject';
        reason = 'wide-road-return-hard';
    } else if (diagonalMainlineShortcutDetected) {
        decision = 'hard-reject';
        reason = 'diagonal-mainline-shortcut-hard';
    } else if (crossingCount > 0) {
        const forwardMainlineLike = !rescueLike
            && (mode === 'stage-candidate' || mode === 'stage1-candidate' || mode === 'stage2-candidate' || mode === 'stage3-candidate' || side === 'left' || side === 'right' || side === 'unknown')
            && !sideRoadContinuationDetected;
        const longCrossingHard = longestCrossingSegment >= PEDESTRIAN_SAFETY_UNKNOWN_WIDE_CROSS_SEGMENT_M
            || totalCrossingDistanceM >= Math.max(PEDESTRIAN_SAFETY_UNKNOWN_WIDE_CROSS_SEGMENT_M + 8, totalDistance * 0.25);

        if (forwardMainlineLike && longCrossingHard) {
            decision = 'hard-reject';
            reason = 'long-crossing-segment-hard';
        } else if (rescueLike && !hardIntersectionDetected && !actualIntersectionDetected
            && !!nearPenaltyMode.eligible
            && (sideRoadContinuationDetected || rescueLikeSide || result.metrics.routeStartsAlongCorridorThenEscapes)
            && longestCrossingSegment <= (PEDESTRIAN_SAFETY_UNKNOWN_WIDE_CROSS_SEGMENT_M + 8)) {
            decision = 'soft-risk';
            reason = sideRoadContinuationDetected
                ? 'unknown-side-road-continue'
                : 'unknown-rescue-detour-soft';
            penalty = PEDESTRIAN_SAFETY_UNKNOWN_SOFT_PENALTY;
        } else if (rescueLike && !hardIntersectionDetected && !actualIntersectionDetected) {
            decision = 'soft-risk';
            reason = 'long-crossing-segment-soft';
            penalty = PEDESTRIAN_SAFETY_UNKNOWN_SOFT_PENALTY + 40;
        } else {
            decision = 'hard-reject';
            reason = 'long-crossing-segment-hard';
        }
    } else if (rescueLike && !hardIntersectionDetected && !actualIntersectionDetected) {
        decision = 'pass';
        reason = sideRoadContinuationDetected ? 'unknown-pass-side-road' : 'unknown-pass-rescue-candidate';
    } else {
        decision = 'pass';
        reason = 'unknown-pass-low-crossing';
    }

    result.conservativeDecision = decision;
    result.conservativeRejectApplied = decision === 'hard-reject';
    result.conservativeRejectReason = reason;
    result.conservativePenalty = decision === 'soft-risk' ? penalty : 0;

    console.log(
        `[PedestrianSafety][unknown-conservative] label=${options.label || mode} mode=${mode} side=${side} ` +
        `decision=${decision} reason=${reason || 'none'} longestCrossing=${Math.round(longestCrossingSegment)}m ` +
        `totalCrossing=${Math.round(totalCrossingDistanceM)}m crossingCount=${crossingCount} ` +
        `wideRoadReturnDetected=${wideRoadReturnDetected} ` +
        `diagonalMainlineShortcutDetected=${diagonalMainlineShortcutDetected} ` +
        `sideRoadContinuationDetected=${sideRoadContinuationDetected} ` +
        `nearPenaltyMode=${!!nearPenaltyMode.eligible} hardIntersectionDetected=${hardIntersectionDetected}`
    );
    return result;
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

function _assessEscapeNearPenaltyMode(blockedStats, overlap, options = {}) {
    const strict = Number(blockedStats?.strictOverlapRatio || 0);
    const near = Number(blockedStats?.nearBlockedRatio || 0);
    const overlapValue = Number(overlap || 0);
    const mode = options.mode || 'escape';
    const candidateSide = String(options.side || blockedStats?.candidateSide || '');
    const strictNearPenaltyMax = Number.isFinite(Number(options.strictNearPenaltyMax))
        ? Number(options.strictNearPenaltyMax)
        : BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX;
    const slitBodyOverlapRatio = Number(blockedStats?.slitBodyOverlapRatio || 0);
    const slitCapOverlapRatio = Number(blockedStats?.slitCapOverlapRatio || 0);
    const slitNearRatio = Number(blockedStats?.slitNearRatio || 0);
    const sideBufferScale = /^back-/.test(candidateSide) ? 0.65 : 1;
    const slitLineCrossDetected = overlapValue > BLOCK_ESCAPE_NEAR_PENALTY_OVERLAP_EPS
        && slitBodyOverlapRatio >= 0.08;
    const slitBodyIntersectionDetected = slitBodyOverlapRatio >= 0.18;
    const slitCapIntersectionDetected = slitCapOverlapRatio >= 0.18;
    const slitNearDetected = slitNearRatio > 0;
    const coreIntersectionDetected = !!blockedStats?.coreIntersectionDetected;
    const rawIntersectionBufferDetected = !!blockedStats?.intersectionBufferDetected;
    const intersectionBufferDetected = rawIntersectionBufferDetected
        && (Number(blockedStats?.intersectionBufferOverlapRatio || 0) * sideBufferScale) >= 0.18;
    const legacyBroadIntersectionDetected = !!blockedStats?.legacyBroadIntersectionDetected;
    const carveOutAdjustedIntersectionDetected = !!blockedStats?.carveOutAdjustedIntersectionDetected;
    const slitBodyHard = slitBodyIntersectionDetected
        && (overlapValue >= 0.08 || strict >= 0.35);
    const softSlitBodyIntersectionDetected = slitBodyIntersectionDetected && !slitBodyHard;
    const softIntersectionBufferDetected = rawIntersectionBufferDetected && !intersectionBufferDetected;
    const actualIntersectionDetected = slitLineCrossDetected
        || slitBodyHard
        || coreIntersectionDetected
        || intersectionBufferDetected;
    const strictThresholdExceeded = strict >= strictNearPenaltyMax;
    const shouldUseNearPenaltyMode = overlapValue <= BLOCK_ESCAPE_NEAR_PENALTY_OVERLAP_EPS
        && !actualIntersectionDetected
        && !strictThresholdExceeded;
    const eligible = shouldUseNearPenaltyMode;
    const penalty = eligible
        ? ((overlapValue * 600) + (strict * 800) + (near * 400)
            + (softSlitBodyIntersectionDetected ? 80 : 0)
            + (softIntersectionBufferDetected ? 55 : 0))
        : Infinity;
    return {
        eligible,
        penalty,
        mode,
        side: candidateSide,
        strict,
        near,
        overlap: overlapValue,
        actualIntersection: actualIntersectionDetected,
        actualIntersectionDetected,
        slitIntersectionDetected: blockedStats?.slitIntersectionDetected,
        slitLineCrossDetected,
        slitBodyIntersectionDetected,
        softSlitBodyIntersectionDetected,
        slitBodyHard,
        slitCapIntersectionDetected,
        slitNearDetected,
        coreIntersectionDetected,
        intersectionBufferDetected,
        softIntersectionBufferDetected,
        legacyBroadIntersectionDetected,
        carveOutAdjustedIntersectionDetected,
        hardIntersectionDetected: actualIntersectionDetected,
        strictThresholdExceeded,
        shouldUseNearPenaltyMode,
        overlapEpsilon: BLOCK_ESCAPE_NEAR_PENALTY_OVERLAP_EPS,
        strictNearPenaltyMax,
        effectiveIntersectionBufferRadius: Number(blockedStats?.effectiveIntersectionBufferRadius || 0) * sideBufferScale,
        effectiveSlitBodyPolicy: slitBodyHard ? 'hard' : (softSlitBodyIntersectionDetected ? 'soft' : 'none')
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
        `${prefix} holdWaypointMode=${!!meta.holdWaypointMode} mode=${nearPenaltyMode.mode || 'escape'} side=${nearPenaltyMode.side || 'unknown'} ` +
        `overlapRaw=${Number(nearPenaltyMode.overlap || 0).toFixed(2)} ` +
        `strictRaw=${Number(nearPenaltyMode.strict || 0).toFixed(2)} ` +
        `nearRaw=${Number(nearPenaltyMode.near || 0).toFixed(2)} ` +
        `slitLineCrossDetected=${!!nearPenaltyMode.slitLineCrossDetected} ` +
        `slitBodyIntersectionDetected=${!!nearPenaltyMode.slitBodyIntersectionDetected} ` +
        `softSlitBodyIntersectionDetected=${!!nearPenaltyMode.softSlitBodyIntersectionDetected} ` +
        `slitCapIntersectionDetected=${!!nearPenaltyMode.slitCapIntersectionDetected} ` +
        `slitNearDetected=${!!nearPenaltyMode.slitNearDetected} ` +
        `coreIntersectionDetected=${!!nearPenaltyMode.coreIntersectionDetected} ` +
        `intersectionBufferDetected=${!!nearPenaltyMode.intersectionBufferDetected} ` +
        `softIntersectionBufferDetected=${!!nearPenaltyMode.softIntersectionBufferDetected} ` +
        `legacyBroadIntersectionDetected=${!!nearPenaltyMode.legacyBroadIntersectionDetected} ` +
        `carveOutAdjustedIntersectionDetected=${!!nearPenaltyMode.carveOutAdjustedIntersectionDetected} ` +
        `hardIntersectionDetected=${!!nearPenaltyMode.hardIntersectionDetected} ` +
        `overlapEpsilon=${Number(nearPenaltyMode.overlapEpsilon || 0).toFixed(2)} ` +
        `strictNearPenaltyMax=${Number(nearPenaltyMode.strictNearPenaltyMax || 0).toFixed(2)} ` +
        `effectiveIntersectionBufferRadius=${Number(nearPenaltyMode.effectiveIntersectionBufferRadius || 0).toFixed(1)} ` +
        `effectiveSlitBodyPolicy=${nearPenaltyMode.effectiveSlitBodyPolicy || 'none'} ` +
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
    if (nearPenaltyMode?.slitBodyHard) return 'slit-body-hard';
    if (nearPenaltyMode?.softSlitBodyIntersectionDetected) return 'slit-body-soft';
    if (nearPenaltyMode?.slitCapIntersectionDetected) return 'slit-cap-intersection';
    if (nearPenaltyMode?.slitNearDetected && flags.nearOnlyReject) return 'slit-near';
    if (nearPenaltyMode?.coreIntersectionDetected) return 'core-intersection';
    if (nearPenaltyMode?.intersectionBufferDetected) return 'intersection-buffer';
    if (nearPenaltyMode?.softIntersectionBufferDetected) return 'intersection-buffer-soft';
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
    const injected = await _callBlockAheadTestDep('fetchOsrmAlternatives', from, to, maxAlts, contextLabel);
    if (typeof injected !== 'undefined') return injected;
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

/**
 * ルート座標列を /api/route-risk に送信してハザード危険度を評価する。
 * @param {object} route - OSRM ルートオブジェクト (route.coordinates が必要)
 * @returns {object|null} {safety_score, risk_level, risk_summary} または null
 */
async function _assessRouteHazardRisk(route) {
    const rawCoords = Array.isArray(route?.coordinates) ? route.coordinates : [];
    if (rawCoords.length < 2) return null;

    const coordPairs = rawCoords
        .map(c => {
            const lat = Number(c?.lat ?? c?.[0]);
            const lon = Number(c?.lng ?? c?.lon ?? c?.[1]);
            return [lat, lon];
        })
        .filter(([lat, lon]) => Number.isFinite(lat) && Number.isFinite(lon));

    if (coordPairs.length < 2) return null;

    try {
        const res = await apiFetch('/api/route-risk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ coordinates: coordPairs, sample_count: 40 })
        });
        if (!res.ok) return null;
        return await res.json();
    } catch (e) {
        return null;
    }
}

async function fetchRouteCandidates(origin, destination, options = {}) {
    const transportMode = options.transportMode || document.getElementById('transportMode')?.value || 'walking';
    const profile = transportMode === 'walking' ? 'walking' : 'driving';
    const serviceUrl = OSRM_SERVICE_URLS[profile];
    const crossingConfig = _getSafeCrossingRuntimeConfig({ log: true });
    const requestedMaxCandidates = Math.max(1, Math.min(MAX_ROUTE_CANDIDATES, Number(options.maxCandidates) || MAX_ROUTE_CANDIDATES));
    const maxCandidates = crossingConfig.enabled ? requestedMaxCandidates : 1;
    const from = { lat: Number(origin?.lat), lng: Number(origin?.lng ?? origin?.lon) };
    const to = { lat: Number(destination?.lat), lng: Number(destination?.lng ?? destination?.lon) };
    if (!Number.isFinite(from.lat) || !Number.isFinite(from.lng) || !Number.isFinite(to.lat) || !Number.isFinite(to.lng)) {
        return [];
    }

    const coordStr = `${from.lng},${from.lat};${to.lng},${to.lat}`;
    const buildUrl = (alternatives) => `${serviceUrl}/${profile}/${coordStr}?overview=full&geometries=geojson&alternatives=${alternatives}&steps=true`;
    let data = null;
    let usedFallback = false;

    for (const alternatives of [String(maxCandidates), 'true']) {
        try {
            const res = await fetch(buildUrl(alternatives));
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            data = await res.json();
            if (data?.code === 'Ok' && Array.isArray(data.routes)) break;
            throw new Error(`OSRM ${data?.code || 'invalid-response'}`);
        } catch (error) {
            if (alternatives === 'true') {
                console.warn(`[route-candidates] fetch failed alternatives=${alternatives}`, error);
                data = null;
            } else {
                usedFallback = true;
                console.warn(`[route-candidates] alternatives=${alternatives} failed; retrying alternatives=true`, error);
            }
        }
    }

    const rawRoutes = Array.isArray(data?.routes) ? data.routes : [];
    console.log(
        `[route-candidates] requested_alternatives=${maxCandidates} returned=${rawRoutes.length}` +
        (usedFallback ? ' fallback=alternatives=true' : '')
    );
    const routes = rawRoutes
        .slice(0, maxCandidates)
        .map((route, index) => _normalizeAlternativeRouteShape({
            ..._fetchOsrmAlternativesResultToRoute(route),
            __osrmOriginalIndex: index
        }));
    if (routes.length === 0) return [];

    if (crossingConfig.disableCrossingLogic) {
        const route = routes[0];
        route.__routeCandidateIndex = 0;
        route.__crossingRisk = _buildDisabledCrossingRisk();
        route.__safetyScore = null;
        route.__displayLabel = '推奨';
        route.__displayReason = null;
        route.__routeFeatures = _buildRouteCandidateFeatures(route, route.__crossingRisk, {
            distance: Number(route?.summary?.totalDistance ?? route?.totalDistance),
            baseDistance: Number(route?.summary?.totalDistance ?? route?.totalDistance),
            safeCrossingEnabled: false
        });
        route.__pedestrianSafety = _makePedestrianSafetyResult('safe', {
            crossings: [],
            dangerousCrossings: [],
            contextUnavailable: false,
            failOpenApplied: false
        });
        route.__riskSummary = null;
        route.__riskSampledPoints = null;
        try {
            const riskResult = await _assessRouteHazardRisk(route);
            route.__riskSummary = riskResult;
            if (riskResult && Array.isArray(riskResult.sampled_points)) {
                route.__riskSampledPoints = riskResult.sampled_points;
            }
        } catch (e) {
            console.warn('[route-risk] assessment failed (crossing-disabled):', e);
        }
        console.log('[route-candidates] safe_crossing disabled; selected shortest route only');
        return [route];
    }

    const baseDistance = routes
        .map(route => Number(route?.summary?.totalDistance ?? route?.totalDistance))
        .filter(Number.isFinite)
        .reduce((min, value) => Math.min(min, value), Infinity);

    const evaluated = await Promise.all(routes.map(async (route, index) => {
        const candidate = await evaluateRouteSafety(route, {
            ...options,
            index,
            origin: from,
            destination: to,
            transportMode,
            baseDistance
        });
        console.log(
            `[route-candidates] candidate=${index} distance=${Math.round(candidate.distance)} ` +
            `duration=${Math.round(candidate.duration)} unsafe_crossings=${candidate.crossingRisk.unsafeMajorRoadCrossings} ` +
            `score=${Math.round(candidate.safetyScore)}`
        );
        return candidate;
    }));

    const safeCrossingRoute = await _tryBuildSafeCrossingDetourCandidate(evaluated, {
        ...options,
        origin: from,
        destination: to,
        transportMode,
        baseDistance,
        nextIndex: routes.length,
        canAppend: routes.length < maxCandidates,
        crossingConfig
    });
    if (safeCrossingRoute) {
        const candidate = await evaluateRouteSafety(safeCrossingRoute, {
            ...options,
            index: routes.length,
            origin: from,
            destination: to,
            transportMode,
            baseDistance
        });
        console.log(
            `[route-candidates] via_safe_crossing distance=${Math.round(candidate.distance)} ` +
            `duration=${Math.round(candidate.duration)} unsafe_crossings=${candidate.crossingRisk.unsafeMajorRoadCrossings} ` +
            `score=${Math.round(candidate.safetyScore)}`
        );
        evaluated.push(candidate);
    }

    return rankRouteCandidates(evaluated);
}

function _safeCrossingHasSignal(point) {
    const tags = point?.tags || {};
    return tags.crossing === 'traffic_signals' || tags.highway === 'traffic_signals';
}

function _safeCrossingIsMarked(point) {
    const tags = point?.tags || {};
    return tags.highway === 'crossing'
        || tags.footway === 'crossing'
        || tags.crossing === 'marked'
        || tags.crossing === 'zebra'
        || _safeCrossingHasSignal(point);
}

function _findNearbySafeCrossingPoint(dangerousCrossing, context, options = {}) {
    const radiusM = Math.max(0, Number(options.radiusM) || 0);
    const maxDetourRatio = Math.max(1, Number(options.maxDetourRatio) || SAFE_CROSSING_DETOUR_RATIO_FALLBACK);
    const origin = options.origin || null;
    const destination = options.destination || null;
    const point = dangerousCrossing?.point;
    const crosswalks = Array.isArray(context?.crosswalks) ? context.crosswalks : [];
    if (radiusM <= 0) return null;
    if (!point || crosswalks.length === 0) return null;

    const directDist = (origin && destination) ? _segmentLengthMeters(origin, destination) : null;

    const candidates = crosswalks
        .map(crossing => {
            const distM = _segmentLengthMeters(point, crossing);
            const signalized = _safeCrossingHasSignal(crossing);
            const marked = _safeCrossingIsMarked(crossing);
            let detourM = 0;
            let detourRatio = null;
            if (origin && destination && directDist > 0) {
                const via = _segmentLengthMeters(origin, crossing) + _segmentLengthMeters(crossing, destination);
                detourM = via - directDist;
                detourRatio = via / directDist;
            }
            const score = -distM * 2
                + (signalized ? 100 : 0)
                + (marked ? 40 : 0)
                - detourM * 0.5;
            return { ...crossing, distanceM: distM, signalized, marked, detourM, detourRatio, score };
        })
        .filter(c =>
            c.distanceM <= radiusM &&
            (c.signalized || c.marked) &&
            (c.detourRatio === null || c.detourRatio <= maxDetourRatio)
        )
        .sort((a, b) => b.score - a.score);

    if (candidates.length === 0) return null;

    const best = candidates[0];
    console.log(
        `[crossing-select] candidates=${candidates.length} ` +
        `best=${best.signalized ? 'signalized' : 'marked'} ` +
        `dist=${Math.round(best.distanceM)}m detour=+${Math.round(best.detourM)}m`
    );
    return best;
}

async function _tryBuildSafeCrossingDetourCandidate(evaluatedCandidates, options = {}) {
    const crossingConfig = options.crossingConfig || _getSafeCrossingRuntimeConfig({ log: true });
    if (crossingConfig.disableCrossingLogic) {
        return null;
    }
    if (options.transportMode && options.transportMode !== 'walking') return null;
    if (!options.canAppend) {
        console.log('[route-candidates] safe_crossing_detour skipped reason=max_candidates_already_returned');
        return null;
    }
    const candidates = Array.isArray(evaluatedCandidates) ? evaluatedCandidates : [];
    const source = candidates.find(candidate => {
        const dangerous = candidate.route?.__pedestrianSafety?.dangerousCrossings;
        return Array.isArray(dangerous) && dangerous.length > 0;
    });
    const dangerousCrossing = source?.route?.__pedestrianSafety?.dangerousCrossings?.[0] || null;
    if (!source || !dangerousCrossing?.point) return null;

    const bbox = _buildPedestrianSafetyContextBBox({
        points: [dangerousCrossing.point],
        paddingM: crossingConfig.radiusM
    });
    const contextResult = await _fetchPedestrianSafetyContextForBBox(bbox, {
        contextLabel: 'route-candidate:safe-crossing-search',
        sourceLabel: 'safe-crossing-search',
        allowExtendedFetch: true
    });
    const searchContext = contextResult?.context || (
        Array.isArray(contextResult?.crosswalks) || Array.isArray(contextResult?.roads)
            ? contextResult
            : null
    );
    const safeCrossing = _findNearbySafeCrossingPoint(dangerousCrossing, searchContext, {
        radiusM: crossingConfig.radiusM,
        maxDetourRatio: crossingConfig.maxDetourRatio,
        origin: options.origin,
        destination: options.destination
    });
    if (!safeCrossing) {
        console.log(
            `[route-candidates] safe_crossing_detour skipped reason=no_safe_crossing_nearby ` +
            `source_raw=${source.index} radius=${crossingConfig.radiusM}`
        );
        return null;
    }

    const route = await _fetchOsrmRouteThroughWaypoints([
        options.origin,
        safeCrossing,
        options.destination
    ], 'route-candidate:safe-crossing-via');
    if (!route) {
        console.log('[route-candidates] safe_crossing_detour skipped reason=osrm_empty');
        return null;
    }

    const baseDistance = Number(options.baseDistance);
    const detourDistance = Number(route?.summary?.totalDistance ?? route?.totalDistance);
    if (Number.isFinite(baseDistance) && baseDistance > 0 && Number.isFinite(detourDistance)
            && detourDistance / baseDistance > crossingConfig.maxDetourRatio) {
        console.log(
            `[route-candidates] safe_crossing_detour skipped reason=too_long ` +
            `distance=${Math.round(detourDistance)} base=${Math.round(baseDistance)} ratio=${crossingConfig.maxDetourRatio}`
        );
        return null;
    }

    route.__osrmOriginalIndex = options.nextIndex;
    route.__viaSafeCrossing = {
        lat: safeCrossing.lat,
        lng: safeCrossing.lng ?? safeCrossing.lon,
        distanceFromDangerM: safeCrossing.distanceM,
        signalized: !!safeCrossing.signalized,
        marked: !!safeCrossing.marked,
        tags: safeCrossing.tags || {}
    };
    route.__candidateGeneratedBy = 'safe-crossing-via';
    console.log(
        `[route-candidates] safe_crossing_detour added source_raw=${source.index} ` +
        `crossing_distance=${Math.round(safeCrossing.distanceM)}m ` +
        `signalized=${!!safeCrossing.signalized} distance=${Math.round(detourDistance)}`
    );
    return route;
}

async function evaluateRouteSafety(route, options = {}) {
    const index = Number(options.index) || 0;
    const distance = Number(route?.summary?.totalDistance ?? route?.totalDistance ?? 0);
    const duration = Number(route?.summary?.totalTime ?? route?.totalTime ?? 0);
    let pedestrianSafety = null;
    let conservativeSafety = null;

    if ((options.transportMode || 'walking') === 'walking') {
        pedestrianSafety = await _evaluatePedestrianRouteSafety(route, null, `route-candidate:${index}`, {
            lessStrictMode: false
        });
        conservativeSafety = pedestrianSafety.status === 'unknown'
            ? _evaluateConservativeUnknownPedestrianSafety(route, {
                phase: 'route-candidate',
                mode: 'route-candidate',
                side: 'unknown',
                label: `route-candidate:${index}`
            })
            : null;
    }

    const crossingRisk = _buildRouteCrossingRisk(pedestrianSafety, conservativeSafety);
    const safetyScore = _scoreRouteCandidate({
        route,
        index,
        distance,
        duration,
        crossingRisk,
        pedestrianSafety,
        conservativeSafety
    });
    const displayLabel = _buildRouteCandidateLabel(index, crossingRisk, pedestrianSafety, conservativeSafety);
    const reason = _buildRouteCandidateReason(crossingRisk, pedestrianSafety, conservativeSafety);

    route.__routeCandidateIndex = index;
    route.__crossingRisk = crossingRisk;
    route.__safetyScore = safetyScore;
    route.__displayLabel = displayLabel;
    route.__displayReason = reason;
    route.__routeFeatures = _buildRouteCandidateFeatures(route, crossingRisk, {
        distance,
        baseDistance: options.baseDistance
    });
    route.__pedestrianSafety = pedestrianSafety || {
        status: 'unknown',
        contextUnavailable: true,
        dangerousCrossings: [],
        crossings: []
    };
    if (conservativeSafety) {
        route.__pedestrianSafety = { ...route.__pedestrianSafety, ...conservativeSafety };
    }

    // ハザードゾーン通過率に基づくルート危険度評価
    route.__riskSummary = null;
    route.__riskSampledPoints = null;
    try {
        const riskResult = await _assessRouteHazardRisk(route);
        route.__riskSummary = riskResult;
        if (riskResult && Array.isArray(riskResult.sampled_points)) {
            route.__riskSampledPoints = riskResult.sampled_points;
        }
    } catch (e) {
        console.warn('[route-risk] assessment failed:', e);
    }

    return {
        index,
        distance,
        duration,
        geometry: route.geometry || null,
        route,
        crossingRisk,
        safetyScore,
        displayLabel,
        reason
    };
}

function _buildRouteCrossingRisk(pedestrianSafety, conservativeSafety) {
    const crossings = Array.isArray(pedestrianSafety?.crossings) ? pedestrianSafety.crossings : [];
    const dangerousCrossings = Array.isArray(pedestrianSafety?.dangerousCrossings) ? pedestrianSafety.dangerousCrossings : [];
    const conservativeHard = !!conservativeSafety?.conservativeRejectApplied;
    const conservativeSoft = conservativeSafety?.conservativeDecision === 'soft-risk';

    // 道路種別ごとに危険横断を分類
    // conservativeHard（Overpass失敗時の保守的判定）は unsafe カウントに含めない
    // → crossingPoint が検出できた場合のみ unsafe とする
    const unsafeMajorRoadCrossings = dangerousCrossings.filter(item => {
        const hw = String(item?.road?.tags?.highway || '');
        return ['motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link'].includes(hw);
    }).length;

    const unsafeSecondaryCrossings = dangerousCrossings.filter(item => {
        const hw = String(item?.road?.tags?.highway || '');
        return hw === 'secondary' || hw === 'secondary_link';
    }).length;

    // 安全な横断（危険でない ＋ 横断歩道または信号あり）
    const dangerousSet = new Set(dangerousCrossings);
    const safeCrossings = crossings.filter(item =>
        !dangerousSet.has(item) &&
        (!!item?.classification?.signalizedCrossing ||
         !!item?.classification?.markedCrossing ||
         !!item?.classification?.crosswalkNearby ||
         item?.classification?.crossingType === 'signalized' ||
         item?.road?.tags?.crossing === 'traffic_signals' ||
         !!item?.road?.tags?.crossing)
    ).length;

    // 評価不能横断（conservative soft-risk or hard は小さなペナルティのみ）
    const unknownCrossings = (conservativeSoft || conservativeHard) ? 1 : 0;

    // 危険横断ペナルティ合計（道路種別ごとに重み付け）
    let crossingPenaltyTotal = 0;
    dangerousCrossings.forEach(item => {
        const hw = String(item?.road?.tags?.highway || '');
        crossingPenaltyTotal += CROSSING_PENALTY_BY_HIGHWAY[hw] ?? CROSSING_UNKNOWN_PENALTY;
    });

    const hasUnsafeCrossing = (unsafeMajorRoadCrossings + unsafeSecondaryCrossings) > 0;
    const worstSeverity = hasUnsafeCrossing
        ? 'unsafe'
        : (unknownCrossings > 0 || pedestrianSafety?.status === 'unknown' ? 'unknown' : 'none');

    // 後方互換のため majorRoadCrossings / signalizedCrossings / markedCrossings は維持
    const majorRoadCrossings = crossings.filter(item => {
        const hw = String(item?.road?.tags?.highway || '');
        return PEDESTRIAN_SAFETY_MAJOR_HIGHWAYS.has(hw) || PEDESTRIAN_SAFETY_FORBIDDEN_HIGHWAYS.has(hw);
    }).length;
    const signalizedCrossings = crossings.filter(item => {
        const tags = item?.road?.tags || {};
        return !!item?.classification?.signalizedCrossing
            || tags.crossing === 'traffic_signals'
            || tags.highway === 'traffic_signals';
    }).length;
    const markedCrossings = crossings.filter(item =>
        !!item?.classification?.markedCrossing
            || !!item?.classification?.crosswalkNearby
            || !!item?.road?.tags?.crossing
    ).length;

    return {
        majorRoadCrossings,
        unsafeMajorRoadCrossings,
        unsafeSecondaryCrossings,
        signalizedCrossings,
        markedCrossings,
        safeCrossings,
        unknownCrossings,
        crossingPenaltyTotal,
        hasUnsafeCrossing,
        worstSeverity,
        contextUnavailable: !!pedestrianSafety?.contextUnavailable,
        conservativeDecision: conservativeSafety?.conservativeDecision || null,
    };
}

function _buildDisabledCrossingRisk() {
    return {
        majorRoadCrossings: 0,
        unsafeMajorRoadCrossings: 0,
        unsafeSecondaryCrossings: 0,
        signalizedCrossings: 0,
        markedCrossings: 0,
        safeCrossings: 0,
        unknownCrossings: 0,
        crossingPenaltyTotal: 0,
        hasUnsafeCrossing: false,
        worstSeverity: 'none',
        contextUnavailable: false,
        conservativeDecision: null,
        disabled: true
    };
}

function _buildRouteCandidateFeatures(route, crossingRisk, options = {}) {
    if (options.safeCrossingEnabled === false || crossingRisk?.disabled) {
        return {
            hasCrossing: false,
            hasSignalizedCrossing: false,
            hasMarkedCrossing: false,
            addedDistanceM: 0,
            viaSafeCrossing: false,
            generatedBy: null
        };
    }
    const viaSafeCrossing = route?.__viaSafeCrossing || null;
    const baseDistance = Number(options.baseDistance);
    const distance = Number(options.distance ?? route?.summary?.totalDistance ?? route?.totalDistance);
    const addedDistanceM = Number.isFinite(baseDistance) && Number.isFinite(distance)
        ? Math.max(0, distance - baseDistance)
        : 0;
    const signalized = Number(crossingRisk?.signalizedCrossings || 0) > 0 || !!viaSafeCrossing?.signalized;
    const marked = Number(crossingRisk?.markedCrossings || 0) > 0 || !!viaSafeCrossing?.marked;
    return {
        hasCrossing: Number(crossingRisk?.majorRoadCrossings || 0) > 0 || marked || signalized || !!viaSafeCrossing,
        hasSignalizedCrossing: signalized,
        hasMarkedCrossing: marked,
        addedDistanceM,
        viaSafeCrossing: !!viaSafeCrossing,
        generatedBy: route?.__candidateGeneratedBy || null
    };
}

function _scoreRouteCandidate(candidate) {
    const risk = candidate.crossingRisk || {};
    return 1000
        - Number(candidate.distance || 0) / 40
        - Number(candidate.duration || 0) / 12
        - Number(risk.crossingPenaltyTotal || 0)
        - Number(risk.unknownCrossings || 0) * CROSSING_UNKNOWN_PENALTY
        + Number(risk.safeCrossings || 0) * CROSSING_SAFE_BONUS;
}

function _buildRouteCandidateLabel(index, crossingRisk, pedestrianSafety, conservativeSafety) {
    if (index === 0 && !crossingRisk?.hasUnsafeCrossing) return '推奨ルート';
    if (!crossingRisk?.hasUnsafeCrossing && pedestrianSafety?.status === 'safe') return '安全優先ルート';
    if (crossingRisk?.hasUnsafeCrossing) return '注意ルート';
    if (conservativeSafety?.conservativeDecision === 'soft-risk') return '慎重確認ルート';
    return index === 0 ? '推奨ルート' : `候補${index + 1}`;
}

function _buildRouteCandidateReason(crossingRisk, pedestrianSafety, conservativeSafety) {
    if (crossingRisk?.hasUnsafeCrossing) {
        return '横断歩道なしの幹線道路横断を含む可能性があります';
    }
    if (pedestrianSafety?.status === 'safe' && Number(crossingRisk?.majorRoadCrossings || 0) > 0) {
        return '幹線道路横断は検出されましたが、横断歩道や信号の手掛かりがあります';
    }
    if (pedestrianSafety?.status === 'safe') {
        return '横断歩道なしの幹線道路横断は検出されていません';
    }
    if (conservativeSafety?.conservativeDecision === 'soft-risk') {
        return '安全情報が不足しているため慎重に確認してください';
    }
    return '安全横断情報を確認中です';
}

function rankRouteCandidates(candidates) {
    const list = Array.isArray(candidates) ? candidates : [];

    const sorted = list.slice().sort((a, b) => {
        const aSum = a.route.__riskSummary;
        const bSum = b.route.__riskSummary;
        const aLevel = RISK_LEVEL_RANK[aSum?.risk_level] ?? RISK_LEVEL_RANK.unknown;
        const bLevel = RISK_LEVEL_RANK[bSum?.risk_level] ?? RISK_LEVEL_RANK.unknown;

        // 1. risk_level 優先（safe > caution > danger > unknown）
        if (aLevel !== bLevel) return bLevel - aLevel;

        // 2. 同レベル内は safety_score（ハザードゾーン評価）、なければ crossing ベーススコアで代替
        const aScore = typeof aSum?.safety_score === 'number' ? aSum.safety_score : a.safetyScore;
        const bScore = typeof bSum?.safety_score === 'number' ? bSum.safety_score : b.safetyScore;
        const scoreDiff = bScore - aScore;
        if (Math.abs(scoreDiff) >= HAZARD_SCORE_DIFF_THRESHOLD) return scoreDiff;

        // 3. スコア差が小さい場合は距離→時間
        if (a.distance !== b.distance) return a.distance - b.distance;
        return a.duration - b.duration;
    });

    sorted.forEach((candidate, rankIndex) => {
        candidate.route.__rankedRouteIndex = rankIndex;
        candidate.route.__displayLabel = _buildRankedRouteLabel(candidate, rankIndex, sorted);
        const totalUnsafe = (candidate.crossingRisk?.unsafeMajorRoadCrossings ?? 0)
            + (candidate.crossingRisk?.unsafeSecondaryCrossings ?? 0);
        console.log(
            `[route-candidates] raw=${candidate.index} rank=${rankIndex} distance=${Math.round(candidate.distance)} ` +
            `risk_level=${candidate.route.__riskSummary?.risk_level ?? 'n/a'} ` +
            `hazard_score=${candidate.route.__riskSummary?.safety_score != null ? Math.round(candidate.route.__riskSummary.safety_score) : 'n/a'} ` +
            `unsafe=${totalUnsafe} crossing_score=${Math.round(candidate.safetyScore)} label=${candidate.route.__displayLabel}`
        );
    });

    const selected = sorted[0];
    if (selected) {
        const riskLevel = selected.route.__riskSummary?.risk_level ?? 'unknown';
        const reason = riskLevel === 'danger' ? 'least_dangerous'
            : selected.crossingRisk?.hasUnsafeCrossing ? 'least_unsafe'
            : 'safety_priority';
        console.log(`[route-candidates] selected_raw_index=${selected.index} selected_rank=0 risk_level=${riskLevel} reason=${reason}`);
    }
    if (sorted.length > 0 && sorted.every(c => (RISK_LEVEL_RANK[c.route.__riskSummary?.risk_level] ?? 0) <= RISK_LEVEL_RANK.danger)) {
        console.warn('[route-candidates] warning=no_safe_or_caution_route_found');
    }
    return sorted.map(candidate => candidate.route).slice(0, MAX_ROUTE_CANDIDATES);
}

function _buildRankedRouteLabel(candidate, rankIndex, allSorted) {
    const riskLevel = candidate.route.__riskSummary?.risk_level;
    const hasUnsafeCrossing = candidate.crossingRisk?.hasUnsafeCrossing;

    // 明確な danger は順位に関わらず注意
    if (riskLevel === 'danger') return '注意';

    // rank 0 → 推奨
    if (rankIndex === 0) return '推奨';

    // 安全横断経由で生成したルート
    if (candidate.route?.__routeFeatures?.viaSafeCrossing) return '安全横断候補';

    const top = allSorted[0];
    const topRiskPriority = RISK_LEVEL_RANK[top.route.__riskSummary?.risk_level] ?? RISK_LEVEL_RANK.unknown;
    const myRiskPriority  = RISK_LEVEL_RANK[riskLevel] ?? RISK_LEVEL_RANK.unknown;

    // 全候補中で最短かつ推奨より短い → 最短
    const isOverallShortest = allSorted.every(c => c.distance >= candidate.distance);
    if (isOverallShortest && candidate.distance < top.distance) return '最短';

    // 推奨と同等以上の安全レベルで unsafe 横断なし → 安全優先
    if (myRiskPriority >= topRiskPriority && !hasUnsafeCrossing) return '安全優先';

    return '注意';
}

function renderRouteCandidates(candidates) {
    return Array.isArray(candidates) ? candidates.slice(0, MAX_ROUTE_CANDIDATES) : [];
}

async function _fetchOsrmRouteThroughWaypoints(waypoints, contextLabel = 'route') {
    const injected = await _callBlockAheadTestDep('fetchOsrmRoute', waypoints, contextLabel);
    if (typeof injected !== 'undefined') return injected;
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

/* REMOVED: この先を避けて再ルート ボタン廃止により無効化
// 「この先を避けて再ルート」— 前方ブロック区間を避ける代替ルートを選択
async function blockAheadAndReroute() {
    const rerouteStartedAt = _perfNowMs();
    _setBlockAheadDebugSummary(null);
    _blockAheadPerfMetrics = {
        startedAt: rerouteStartedAt,
        alternativesEvaluated: 0,
        rejectReasons: {},
        stages: [],
        snapDebugCollector: _createSnapDebugCollector()
    };
    // ── ガード ────────────────────────────────────────────────────────────
    if (!navActiveRoute || !Array.isArray(navActiveRoute.coordinates)) {
        console.warn('[BlockAhead] no active route');
        _setBlockAheadDebugSummary(_buildBlockAheadDebugSummary({ status: 'no-active-route', accepted: false }, {
            blockedAreaStats: { rejectReason: 'no-active-route', hardIntersectionDetected: false }
        }));
        _blockAheadPerfMetrics = null;
        return;
    }
    if (!navDestination) {
        console.warn('[BlockAhead] no destination');
        _setBlockAheadDebugSummary(_buildBlockAheadDebugSummary({ status: 'no-destination', accepted: false }, {
            blockedAreaStats: { rejectReason: 'no-destination', hardIntersectionDetected: false }
        }));
        _blockAheadPerfMetrics = null;
        return;
    }
    if (!currentLocation) {
        console.warn('[BlockAhead] no current location');
        _setBlockAheadDebugSummary(_buildBlockAheadDebugSummary({ status: 'no-current-location', accepted: false }, {
            blockedAreaStats: { rejectReason: 'no-current-location', hardIntersectionDetected: false }
        }));
        _blockAheadPerfMetrics = null;
        return;
    }
    if (navBlockAheadInProgress) {
        console.log('[BlockAhead] already in progress');
        _setBlockAheadDebugSummary(_buildBlockAheadDebugSummary({ status: 'already-in-progress', accepted: false }, {
            blockedAreaStats: { rejectReason: 'already-in-progress', hardIntersectionDetected: false }
        }));
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
        if (typeof window !== 'undefined') window._blockAheadLastTiming = _blockAheadLastTiming;
        _setBlockAheadDebugSummary(_buildBlockAheadDebugSummary(_blockAheadLastTiming, {
            blockedAreaStats: { rejectReason: 'projection-failed', hardIntersectionDetected: false }
        }));
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
        if (typeof window !== 'undefined') window._blockAheadLastTiming = _blockAheadLastTiming;
        _setBlockAheadDebugSummary(_buildBlockAheadDebugSummary(_blockAheadLastTiming, {
            blockedAreaStats: { rejectReason: 'off-route-too-far', hardIntersectionDetected: false }
        }));
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
    const pedestrianSafetySeedPoints = [
        startWp,
        destWp,
        blockStart,
        blockEnd,
        ...coords
    ];
    const pedestrianSafetySeqContext = {
        seq: mySeq,
        bbox: _buildPedestrianSafetyContextBBox({
            points: pedestrianSafetySeedPoints,
            paddingM: PEDESTRIAN_SAFETY_COMPACT_BBOX_PADDING_M
        }),
        status: 'pending',
        context: null,
        fetchedAt: 0,
        source: 'compact-cache',
        fetchPhase: 'core',
        expanded: false,
        seedPoints: [...pedestrianSafetySeedPoints],
        failure: _clonePedestrianSafetyFailure()
    };
    let alternatives = [];
    let activeBlockedArea = null;
    let selectedStage = null;
    let nonBlocked = [];
    let meaningful = [];
    let lastStageResult = null;
    let dangerousCrossingRejected = false;

    console.log(`[PedestrianSafety][prefetch] seq=${mySeq} bbox=${JSON.stringify(pedestrianSafetySeqContext.bbox)} started`);
    await _getOrCreatePedestrianSafetyContextForSeq(pedestrianSafetySeqContext, { contextLabel: 'prefetch:block-ahead' });
    console.log(
        `[PedestrianSafety][prefetch] seq=${mySeq} status=${pedestrianSafetySeqContext.status === 'ready' ? 'ready' : 'unknown'} ` +
        `source=${pedestrianSafetySeqContext.source} failureKind=${pedestrianSafetySeqContext.failure?.kind || 'none'}`
    );

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
            const pedestrianSafety = await _evaluatePedestrianRouteSafety(route, pedestrianSafetySeqContext, `${stage.key}-candidate`);
            const conservativeSafety = pedestrianSafety.status === 'unknown'
                ? _evaluateConservativeUnknownPedestrianSafety(route, {
                    phase: `${stage.key}-candidate`,
                    mode: 'stage-candidate',
                    side: route.__branchBearingDiff > 0 ? 'unknown' : 'unknown',
                    label: `${stage.key}-candidate`,
                    blockedBearing: (blockStart && blockEnd) ? _segmentBearingDeg(blockStart, blockEnd) : null
                })
                : {
                    conservativeRejectEvaluated: false,
                    conservativeRejectApplied: false,
                    conservativeRejectReason: null,
                    conservativeDecision: 'pass',
                    conservativePenalty: 0
                };
            route.__pedestrianSafety = { ...pedestrianSafety, ...conservativeSafety };
            route.__pedestrianConservativePenalty = Number(conservativeSafety.conservativePenalty || 0);
            console.log(
                `[BlockAhead][${stage.key}][alt] pedestrianSafety status=${pedestrianSafety.status} ` +
                `contextUnavailable=${!!pedestrianSafety.contextUnavailable} failOpenApplied=${!!pedestrianSafety.failOpenApplied} ` +
                `contextSource=${pedestrianSafety.contextSource || 'unknown'} contextFailureKind=${pedestrianSafety.contextFailureKind || 'none'} ` +
                `contextFailureDetail=${pedestrianSafety.contextFailureDetail || 'none'} ` +
                `conservativeRejectEvaluated=${!!conservativeSafety.conservativeRejectEvaluated} ` +
                `conservativeDecision=${conservativeSafety.conservativeDecision || 'pass'} ` +
                `conservativeRejectApplied=${!!conservativeSafety.conservativeRejectApplied} ` +
                `conservativeRejectReason=${conservativeSafety.conservativeRejectReason || 'none'} ` +
                `conservativePenalty=${Number(conservativeSafety.conservativePenalty || 0).toFixed(1)}`
            );
            if (pedestrianSafety.status === 'unsafe') {
                dangerousCrossingRejected = true;
                _recordBlockAheadRejectReason('dangerous-crossing');
                console.log(`[BlockAhead][${stage.key}][alt] reject dangerous-crossing dist=${Math.round(route.totalDistance)}m`);
                return null;
            }
            if (conservativeSafety.conservativeRejectApplied) {
                dangerousCrossingRejected = true;
                _recordBlockAheadRejectReason('dangerous-crossing-unknown-hard');
                _recordBlockAheadRejectReason(conservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-hard');
                console.log(`[BlockAhead][${stage.key}][alt] reject dangerous-crossing-unknown reason=${conservativeSafety.conservativeRejectReason}`);
                return null;
            }
            if (conservativeSafety.conservativeDecision === 'soft-risk') {
                _recordBlockAheadRejectReason('dangerous-crossing-unknown-soft');
                _recordBlockAheadRejectReason(conservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-soft');
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
            .sort((a, b) => {
                const conservativePenaltyDiff = Number(a.__pedestrianConservativePenalty || 0) - Number(b.__pedestrianConservativePenalty || 0);
                if (conservativePenaltyDiff !== 0) return conservativePenaltyDiff;
                return a.totalDistance - b.totalDistance;
            });

        const branchFastPathCandidates = (stage.key === 'stage1' || stage.key === 'stage2')
            ? stageMeaningful
                .filter(route => route.__branchFastEligible)
                .sort((a, b) => {
                    const overlapDiff = Number(a.__overlap || 0) - Number(b.__overlap || 0);
                    if (overlapDiff !== 0) return overlapDiff;
                    const penaltyDiff = Number(a.__branchPenalty || 0) - Number(b.__branchPenalty || 0);
                    if (penaltyDiff !== 0) return penaltyDiff;
                    const conservativePenaltyDiff = Number(a.__pedestrianConservativePenalty || 0) - Number(b.__pedestrianConservativePenalty || 0);
                    if (conservativePenaltyDiff !== 0) return conservativePenaltyDiff;
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
        _recordBlockAheadRejectReason(reason);
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
        if (typeof window !== 'undefined') window._blockAheadLastTiming = _blockAheadLastTiming;
        const debugSummary = _buildBlockAheadDebugSummary(summary, {
            selectedStage: selectedStage?.key || null,
            route: originalRouteSnapshot,
            pedestrianSafety: originalRouteSnapshot?.__pedestrianSafety || null,
            blockedAreaStats: {
                overlap: 1,
                strict: 1,
                near: 1,
                hardIntersectionDetected: reason === 'failed' || reason === 'dangerous-crossing',
                rejectReason: reason
            }
        });
        _blockAheadLastTiming.debugSummary = debugSummary;
        _setBlockAheadDebugSummary(debugSummary);
        console.log('[BlockAhead] failure distribution', _blockAheadPerfMetrics?.rejectReasons || {});
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
                const legRoute = await _fetchOsrmRouteThroughWaypoints([startWp, escapeLeg.point], `escape-leg:leg:${escapeLeg.label}`);
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
                const mainRoute = await _fetchOsrmRouteThroughWaypoints([escapeLeg.point, destWp], `escape-leg:main:${escapeLeg.label}`);
                if (!mainRoute) {
                    console.log(`[BlockAhead][escape-leg] reject ${escapeLeg.label}: main-route-empty`);
                    return null;
                }
                const blockedStats = _routeBlockedAreaStats(mainRoute.coordinates, activeBlockedArea);
                const escapeBufMid = lastStageResult?.bufMid || defaultBufMid;
                const escapeOverlapRadius = lastStageResult?.overlapRadius || defaultOverlapRadius;
                const overlap = _calcBlockOverlapRatio(mainRoute.coordinates, escapeBufMid.lat, escapeBufMid.lng, escapeOverlapRadius);
                blockedStats.candidateSide = escapeLeg.side;
                const nearPenaltyMode = _assessEscapeNearPenaltyMode(blockedStats, overlap, {
                    mode: 'escape-leg',
                    side: escapeLeg.side
                });
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
                    _recordBlockAheadRejectReason(_escapeRejectReason(nearPenaltyMode, {
                        actualIntersectionDetected,
                        overlapHard,
                        strictThresholdExceeded,
                        nearOnlyReject
                    }));
                    console.log(
                        `[BlockAhead][escape-leg] reject ${escapeLeg.label}: main-route blocked strict=${blockedStats.strictOverlapRatio.toFixed(2)} ` +
                        `near=${blockedStats.nearBlockedRatio.toFixed(2)} overlap=${overlap.toFixed(2)} ` +
                        `nearPenaltyMode=${nearPenaltyMode.eligible} nearPenalty=${Number.isFinite(nearPenaltyMode.penalty) ? nearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
                        `acceptedByNearPenaltyMode=${nearPenaltyMode.eligible && blockedStats.nearBlocked}`
                    );
                    return null;
                }
                const pedestrianSafety = await _evaluatePedestrianRouteSafety(mainRoute, pedestrianSafetySeqContext, `escape-leg:${escapeLeg.label}`);
                const conservativeSafety = pedestrianSafety.status === 'unknown'
                    ? _evaluateConservativeUnknownPedestrianSafety(mainRoute, {
                        phase: `escape-leg:${escapeLeg.label}`,
                        mode: 'escape-leg',
                        side: escapeLeg.side,
                        label: `escape-leg:${escapeLeg.label}`,
                        nearPenaltyMode,
                        hardIntersectionDetected: actualIntersectionDetected,
                        actualIntersectionDetected,
                        blockedBearing: (blockStart && blockEnd) ? _segmentBearingDeg(blockStart, blockEnd) : null
                    })
                    : {
                        conservativeRejectEvaluated: false,
                        conservativeRejectApplied: false,
                        conservativeRejectReason: null,
                        conservativeDecision: 'pass',
                        conservativePenalty: 0
                    };
                console.log(
                    `[BlockAhead][escape-leg] pedestrianSafety ${escapeLeg.label}: status=${pedestrianSafety.status} ` +
                    `contextUnavailable=${!!pedestrianSafety.contextUnavailable} failOpenApplied=${!!pedestrianSafety.failOpenApplied} ` +
                    `contextSource=${pedestrianSafety.contextSource || 'unknown'} contextFailureKind=${pedestrianSafety.contextFailureKind || 'none'} ` +
                    `contextFailureDetail=${pedestrianSafety.contextFailureDetail || 'none'} ` +
                    `conservativeRejectEvaluated=${!!conservativeSafety.conservativeRejectEvaluated} ` +
                    `conservativeDecision=${conservativeSafety.conservativeDecision || 'pass'} ` +
                    `conservativeRejectApplied=${!!conservativeSafety.conservativeRejectApplied} ` +
                    `conservativeRejectReason=${conservativeSafety.conservativeRejectReason || 'none'} ` +
                    `conservativePenalty=${Number(conservativeSafety.conservativePenalty || 0).toFixed(1)}`
                );
                if (pedestrianSafety.status === 'unsafe') {
                    dangerousCrossingRejected = true;
                    _recordBlockAheadRejectReason('dangerous-crossing');
                    console.log(`[BlockAhead][escape-leg] reject ${escapeLeg.label}: dangerous-crossing`);
                    return null;
                }
                if (conservativeSafety.conservativeRejectApplied) {
                    dangerousCrossingRejected = true;
                    _recordBlockAheadRejectReason('dangerous-crossing-unknown-hard');
                    _recordBlockAheadRejectReason(conservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-hard');
                    console.log(`[BlockAhead][escape-leg] reject ${escapeLeg.label}: dangerous-crossing-unknown reason=${conservativeSafety.conservativeRejectReason}`);
                    return null;
                }
                if (conservativeSafety.conservativeDecision === 'soft-risk') {
                    _recordBlockAheadRejectReason('dangerous-crossing-unknown-soft');
                    _recordBlockAheadRejectReason(conservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-soft');
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
                mergedRoute.__pedestrianConservativePenalty = Number(conservativeSafety.conservativePenalty || 0);
                mergedRoute.__pedestrianSafety = { ...pedestrianSafety, ...conservativeSafety };
                _recordSnapDebugEvent({
                    type: 'usable-route-candidate',
                    mode: 'escape-leg',
                    side: escapeLeg.side,
                    tier: escapeLeg.distanceTierM || escapeLeg.lateralM,
                    depth: escapeLeg.depthKind || 'entrance',
                    candidateId: escapeLeg.label,
                    rawPoint: escapeLeg.rawPoint || escapeLeg.point,
                    snappedPoint: escapeLeg.point,
                    snapDistanceM: escapeLeg.snapDistanceM,
                    corridorDistanceM: escapeLeg.corridorDistanceM,
                    nodeScore: escapeLeg.nodeScore,
                    usable: true
                });
                return mergedRoute;
            }));
            const validEscapeLegRoutes = escapeLegResults.filter(Boolean).sort((a, b) => {
                const overlapDiff = Number(a.__escapeOverlap || 0) - Number(b.__escapeOverlap || 0);
                if (overlapDiff !== 0) return overlapDiff;
                const strictDiff = Number(a.__escapeStrict || 0) - Number(b.__escapeStrict || 0);
                if (strictDiff !== 0) return strictDiff;
                const penaltyDiff = Number(a.__escapeMainPenalty || 0) - Number(b.__escapeMainPenalty || 0);
                if (penaltyDiff !== 0) return penaltyDiff;
                const conservativePenaltyDiff = Number(a.__pedestrianConservativePenalty || 0) - Number(b.__pedestrianConservativePenalty || 0);
                if (conservativePenaltyDiff !== 0) return conservativePenaltyDiff;
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
            const snapFailure = _markSnapEmptyFailure('escape-leg');
            if (snapFailure?.primaryReason && snapFailure.primaryReason !== 'none') {
                _recordBlockAheadRejectReason(`escape-leg-snap-empty:${snapFailure.primaryReason}`);
            }
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
                const route = await _fetchOsrmRouteThroughWaypoints(waypoints, `escape:${escape.label}`);
                if (!route) {
                    console.log(`[BlockAhead][escape] reject ${escape.label}: route-empty holdWaypointMode=${useHoldWaypointMode}`);
                    return null;
                }
                const blockedStats = _routeBlockedAreaStats(route.coordinates, activeBlockedArea);
                const escapeBufMid = lastStageResult?.bufMid || defaultBufMid;
                const escapeOverlapRadius = lastStageResult?.overlapRadius || defaultOverlapRadius;
                const overlap = _calcBlockOverlapRatio(route.coordinates, escapeBufMid.lat, escapeBufMid.lng, escapeOverlapRadius);
                blockedStats.candidateSide = escape.side;
                const nearPenaltyMode = _assessEscapeNearPenaltyMode(blockedStats, overlap, {
                    mode: 'escape',
                    side: escape.side
                });
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
                    _recordBlockAheadRejectReason(_escapeRejectReason(nearPenaltyMode, {
                        actualIntersectionDetected,
                        overlapHard,
                        strictThresholdExceeded,
                        nearOnlyReject
                    }));
                    console.log(
                        `[BlockAhead][escape] reject ${escape.label}: blocked strict=${blockedStats.strictOverlapRatio.toFixed(2)} ` +
                        `near=${blockedStats.nearBlockedRatio.toFixed(2)} overlap=${overlap.toFixed(2)} ` +
                        `nearPenaltyMode=${nearPenaltyMode.eligible} nearPenalty=${Number.isFinite(nearPenaltyMode.penalty) ? nearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
                        `acceptedByNearPenaltyMode=${nearPenaltyMode.eligible && blockedStats.nearBlocked} ` +
                        `holdWaypointMode=${useHoldWaypointMode}`
                    );
                    return null;
                }
                const pedestrianSafety = await _evaluatePedestrianRouteSafety(route, pedestrianSafetySeqContext, `escape:${escape.label}`);
                const conservativeSafety = pedestrianSafety.status === 'unknown'
                    ? _evaluateConservativeUnknownPedestrianSafety(route, {
                        phase: `escape:${escape.label}`,
                        mode: 'escape',
                        side: escape.side,
                        label: `escape:${escape.label}`,
                        nearPenaltyMode,
                        hardIntersectionDetected: actualIntersectionDetected,
                        actualIntersectionDetected,
                        blockedBearing: (blockStart && blockEnd) ? _segmentBearingDeg(blockStart, blockEnd) : null
                    })
                    : {
                        conservativeRejectEvaluated: false,
                        conservativeRejectApplied: false,
                        conservativeRejectReason: null,
                        conservativeDecision: 'pass',
                        conservativePenalty: 0
                    };
                console.log(
                    `[BlockAhead][escape] pedestrianSafety ${escape.label}: status=${pedestrianSafety.status} ` +
                    `contextUnavailable=${!!pedestrianSafety.contextUnavailable} failOpenApplied=${!!pedestrianSafety.failOpenApplied} ` +
                    `contextSource=${pedestrianSafety.contextSource || 'unknown'} contextFailureKind=${pedestrianSafety.contextFailureKind || 'none'} ` +
                    `contextFailureDetail=${pedestrianSafety.contextFailureDetail || 'none'} ` +
                    `conservativeRejectEvaluated=${!!conservativeSafety.conservativeRejectEvaluated} ` +
                    `conservativeDecision=${conservativeSafety.conservativeDecision || 'pass'} ` +
                    `conservativeRejectApplied=${!!conservativeSafety.conservativeRejectApplied} ` +
                    `conservativeRejectReason=${conservativeSafety.conservativeRejectReason || 'none'} ` +
                    `conservativePenalty=${Number(conservativeSafety.conservativePenalty || 0).toFixed(1)}`
                );
                if (pedestrianSafety.status === 'unsafe') {
                    dangerousCrossingRejected = true;
                    _recordBlockAheadRejectReason('dangerous-crossing');
                    console.log(`[BlockAhead][escape] reject ${escape.label}: dangerous-crossing`);
                    return null;
                }
                if (conservativeSafety.conservativeRejectApplied) {
                    dangerousCrossingRejected = true;
                    _recordBlockAheadRejectReason('dangerous-crossing-unknown-hard');
                    _recordBlockAheadRejectReason(conservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-hard');
                    console.log(`[BlockAhead][escape] reject ${escape.label}: dangerous-crossing-unknown reason=${conservativeSafety.conservativeRejectReason}`);
                    return null;
                }
                if (conservativeSafety.conservativeDecision === 'soft-risk') {
                    _recordBlockAheadRejectReason('dangerous-crossing-unknown-soft');
                    _recordBlockAheadRejectReason(conservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-soft');
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
                route.__pedestrianConservativePenalty = Number(conservativeSafety.conservativePenalty || 0);
                route.__pedestrianSafety = { ...pedestrianSafety, ...conservativeSafety };
                _recordSnapDebugEvent({
                    type: 'usable-route-candidate',
                    mode: 'escape',
                    side: escape.side,
                    tier: escape.distanceTierM,
                    depth: escape.depthKind || 'entrance',
                    candidateId: escape.label,
                    rawPoint: escape.rawPoint || escape.point,
                    snappedPoint: escape.point,
                    snapDistanceM: escape.snapDistanceM,
                    corridorDistanceM: escape.corridorDistanceM,
                    nodeScore: escape.nodeScore,
                    usable: true
                });
                return route;
            }));
            const validEscapeRoutes = escapeResults.filter(Boolean).sort((a, b) => {
                const overlapDiff = Number(a.__escapeOverlap || 0) - Number(b.__escapeOverlap || 0);
                if (overlapDiff !== 0) return overlapDiff;
                const strictDiff = Number(a.__escapeStrict || 0) - Number(b.__escapeStrict || 0);
                if (strictDiff !== 0) return strictDiff;
                const penaltyDiff = Number(a.__escapeMainPenalty || 0) - Number(b.__escapeMainPenalty || 0);
                if (penaltyDiff !== 0) return penaltyDiff;
                const conservativePenaltyDiff = Number(a.__pedestrianConservativePenalty || 0) - Number(b.__pedestrianConservativePenalty || 0);
                if (conservativePenaltyDiff !== 0) return conservativePenaltyDiff;
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
            const snapFailure = _markSnapEmptyFailure('escape');
            if (snapFailure?.primaryReason && snapFailure.primaryReason !== 'none') {
                _recordBlockAheadRejectReason(`escape-snap-empty:${snapFailure.primaryReason}`);
            }
        }
    }

    if (meaningful.length === 0 && activeBlockedArea) {
        const longDetourPoints = await _generateLongDetourEscapePoints(coords, projection, activeBlockedArea);
        console.log(`[BlockAhead][long-detour] candidates=${longDetourPoints.length}`);
        if (longDetourPoints.length > 0) {
            const longDetourStartedAt = _perfNowMs();
            const longDetourResults = await Promise.all(longDetourPoints.map(async (escape) => {
                const useHoldWaypointMode = !!escape.holdWaypoint && _escapeDepthRank(escape.depthKind) > 0;
                const useMultiHoldWaypointMode = !!escape.secondaryHoldWaypoint && _escapeDepthRank(escape.depthKind) >= 3;
                const waypointSequence = [startWp];
                const maybePushWaypoint = (point) => {
                    if (!point) return;
                    const last = waypointSequence[waypointSequence.length - 1];
                    if (last && _segmentLengthMeters(last, point) < 3) return;
                    waypointSequence.push(point);
                };
                if (useMultiHoldWaypointMode) maybePushWaypoint(escape.entrancePoint || escape.holdWaypoint);
                if (useHoldWaypointMode) maybePushWaypoint(escape.holdWaypoint);
                if (useMultiHoldWaypointMode) maybePushWaypoint(escape.secondaryHoldWaypoint);
                maybePushWaypoint(escape.point);
                maybePushWaypoint(destWp);
                console.log(
                    `[BlockAhead][long-detour] try ${escape.label}: tier=${escape.distanceTierM || '-'} depth=${escape.depthKind || 'entrance'} ` +
                    `holdWaypointMode=${useHoldWaypointMode} multiHoldWaypointMode=${useMultiHoldWaypointMode} score=${Number(escape.nodeScore || 0).toFixed(1)}`
                );
                const route = await _fetchOsrmRouteThroughWaypoints(waypointSequence, `long-detour:${escape.label}`);
                if (!route) {
                    console.log(`[BlockAhead][long-detour] reject ${escape.label}: route-empty holdWaypointMode=${useHoldWaypointMode} multiHoldWaypointMode=${useMultiHoldWaypointMode}`);
                    return null;
                }
                const blockedStats = _routeBlockedAreaStats(route.coordinates, activeBlockedArea);
                const escapeBufMid = lastStageResult?.bufMid || defaultBufMid;
                const escapeOverlapRadius = lastStageResult?.overlapRadius || defaultOverlapRadius;
                const overlap = _calcBlockOverlapRatio(route.coordinates, escapeBufMid.lat, escapeBufMid.lng, escapeOverlapRadius);
                const destinationNearRelax = Number(route.totalDistance || 0) <= BLOCK_DESTINATION_NEAR_RELAX_ROUTE_DISTANCE_M;
                blockedStats.candidateSide = escape.side;
                const nearPenaltyMode = _assessEscapeNearPenaltyMode(blockedStats, overlap, {
                    mode: 'long-detour',
                    side: escape.side,
                    strictNearPenaltyMax: destinationNearRelax
                        ? (BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX + BLOCK_DESTINATION_NEAR_RELAX_STRICT_BONUS)
                        : BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX
                });
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
                _logEscapeNearPenaltyDecision(`[BlockAhead][long-detour][debug] ${escape.label}:`, {
                    holdWaypointMode: useHoldWaypointMode || useMultiHoldWaypointMode,
                    nearPenaltyMode,
                    rejectReason: hardReject
                        ? _escapeRejectReason(nearPenaltyMode, { actualIntersectionDetected, overlapHard, strictThresholdExceeded, nearOnlyReject })
                        : 'accepted'
                });
                if (hardReject) {
                    _recordBlockAheadRejectReason(_escapeRejectReason(nearPenaltyMode, {
                        actualIntersectionDetected,
                        overlapHard,
                        strictThresholdExceeded,
                        nearOnlyReject
                    }));
                    console.log(
                        `[BlockAhead][long-detour] reject ${escape.label}: blocked strict=${blockedStats.strictOverlapRatio.toFixed(2)} ` +
                        `near=${blockedStats.nearBlockedRatio.toFixed(2)} overlap=${overlap.toFixed(2)} ` +
                        `nearPenaltyMode=${nearPenaltyMode.eligible} nearPenalty=${Number.isFinite(nearPenaltyMode.penalty) ? nearPenaltyMode.penalty.toFixed(1) : 'inf'} ` +
                        `destinationNearRelax=${destinationNearRelax} holdWaypointMode=${useHoldWaypointMode} multiHoldWaypointMode=${useMultiHoldWaypointMode}`
                    );
                    return null;
                }
                const pedestrianSafety = await _evaluatePedestrianRouteSafety(route, pedestrianSafetySeqContext, `long-detour:${escape.label}`);
                const conservativeSafety = pedestrianSafety.status === 'unknown'
                    ? _evaluateConservativeUnknownPedestrianSafety(route, {
                        phase: `long-detour:${escape.label}`,
                        mode: 'long-detour',
                        side: escape.side,
                        label: `long-detour:${escape.label}`,
                        nearPenaltyMode,
                        hardIntersectionDetected: actualIntersectionDetected,
                        actualIntersectionDetected,
                        blockedBearing: (blockStart && blockEnd) ? _segmentBearingDeg(blockStart, blockEnd) : null
                    })
                    : {
                        conservativeRejectEvaluated: false,
                        conservativeRejectApplied: false,
                        conservativeRejectReason: null,
                        conservativeDecision: 'pass',
                        conservativePenalty: 0
                    };
                console.log(
                    `[BlockAhead][long-detour] pedestrianSafety ${escape.label}: status=${pedestrianSafety.status} ` +
                    `contextUnavailable=${!!pedestrianSafety.contextUnavailable} failOpenApplied=${!!pedestrianSafety.failOpenApplied} ` +
                    `contextSource=${pedestrianSafety.contextSource || 'unknown'} contextFailureKind=${pedestrianSafety.contextFailureKind || 'none'} ` +
                    `contextFailureDetail=${pedestrianSafety.contextFailureDetail || 'none'} ` +
                    `conservativeRejectEvaluated=${!!conservativeSafety.conservativeRejectEvaluated} ` +
                    `conservativeDecision=${conservativeSafety.conservativeDecision || 'pass'} ` +
                    `conservativeRejectApplied=${!!conservativeSafety.conservativeRejectApplied} ` +
                    `conservativeRejectReason=${conservativeSafety.conservativeRejectReason || 'none'} ` +
                    `conservativePenalty=${Number(conservativeSafety.conservativePenalty || 0).toFixed(1)}`
                );
                if (pedestrianSafety.status === 'unsafe') {
                    dangerousCrossingRejected = true;
                    _recordBlockAheadRejectReason('dangerous-crossing');
                    console.log(`[BlockAhead][long-detour] reject ${escape.label}: dangerous-crossing`);
                    return null;
                }
                if (conservativeSafety.conservativeRejectApplied) {
                    dangerousCrossingRejected = true;
                    _recordBlockAheadRejectReason('dangerous-crossing-unknown-hard');
                    _recordBlockAheadRejectReason(conservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-hard');
                    console.log(`[BlockAhead][long-detour] reject ${escape.label}: dangerous-crossing-unknown reason=${conservativeSafety.conservativeRejectReason}`);
                    return null;
                }
                if (conservativeSafety.conservativeDecision === 'soft-risk') {
                    _recordBlockAheadRejectReason('dangerous-crossing-unknown-soft');
                    _recordBlockAheadRejectReason(conservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-soft');
                }
                const diff = _isMeaningfullyDifferentReroute(route, originalRouteSnapshot, {
                    bufMid: lastStageResult?.bufMid || defaultBufMid,
                    overlapRadius: lastStageResult?.overlapRadius || defaultOverlapRadius,
                    blockedArea: activeBlockedArea
                });
                if (!diff.meaningful) {
                    console.log(`[BlockAhead][long-detour] reject ${escape.label}: no-change`);
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
                route.__acceptedByHoldWaypointMode = useHoldWaypointMode || useMultiHoldWaypointMode;
                route.__acceptedByMultiHoldWaypointMode = useMultiHoldWaypointMode;
                route.__destinationNearRelax = destinationNearRelax;
                route.__pedestrianConservativePenalty = Number(conservativeSafety.conservativePenalty || 0);
                route.__pedestrianSafety = { ...pedestrianSafety, ...conservativeSafety };
                _recordSnapDebugEvent({
                    type: 'usable-route-candidate',
                    mode: 'long-detour',
                    side: escape.side,
                    tier: escape.distanceTierM,
                    depth: escape.depthKind || 'entrance',
                    candidateId: escape.label,
                    rawPoint: escape.rawPoint || escape.point,
                    snappedPoint: escape.point,
                    snapDistanceM: escape.snapDistanceM,
                    corridorDistanceM: escape.corridorDistanceM,
                    nodeScore: escape.nodeScore,
                    usable: true
                });
                return route;
            }));
            const validLongDetours = longDetourResults.filter(Boolean).sort((a, b) => {
                const overlapDiff = Number(a.__escapeOverlap || 0) - Number(b.__escapeOverlap || 0);
                if (overlapDiff !== 0) return overlapDiff;
                const strictDiff = Number(a.__escapeStrict || 0) - Number(b.__escapeStrict || 0);
                if (strictDiff !== 0) return strictDiff;
                const exitDiff = Number(b.__escapeExitDistanceM || 0) - Number(a.__escapeExitDistanceM || 0);
                if (exitDiff !== 0) return exitDiff;
                const depthDiff = _escapeDepthRank(b.__escapeDepthKind) - _escapeDepthRank(a.__escapeDepthKind);
                if (depthDiff !== 0) return depthDiff;
                const penaltyDiff = Number(a.__escapeMainPenalty || 0) - Number(b.__escapeMainPenalty || 0);
                if (penaltyDiff !== 0) return penaltyDiff;
                const conservativePenaltyDiff = Number(a.__pedestrianConservativePenalty || 0) - Number(b.__pedestrianConservativePenalty || 0);
                if (conservativePenaltyDiff !== 0) return conservativePenaltyDiff;
                const scoreDiff = Number(b.__escapeNodeScore || 0) - Number(a.__escapeNodeScore || 0);
                if (scoreDiff !== 0) return scoreDiff;
                return a.totalDistance - b.totalDistance;
            });
            const longDetourDurationMs = _perfNowMs() - longDetourStartedAt;
            _blockAheadPerfMetrics.stages.push({
                key: 'long-detour',
                durationMs: longDetourDurationMs,
                alternatives: longDetourPoints.length,
                nonBlocked: validLongDetours.length,
                meaningful: validLongDetours.length
            });
            console.log(`[BlockAhead][long-detour] valid=${validLongDetours.length}/${longDetourPoints.length} ${Math.round(longDetourDurationMs)}ms`);
            if (validLongDetours.length > 0) {
                console.log(
                    `[BlockAhead][long-detour] selected node=${validLongDetours[0].__escapeLabel} ` +
                    `tier=${validLongDetours[0].__distanceTierM || '-'} depth=${validLongDetours[0].__escapeDepthKind || 'entrance'} ` +
                    `type=${validLongDetours[0].__escapeNodeType || 'unknown'} score=${Number(validLongDetours[0].__escapeNodeScore || 0).toFixed(1)} ` +
                    `overlap=${Number(validLongDetours[0].__escapeOverlap || 0).toFixed(2)} strict=${Number(validLongDetours[0].__escapeStrict || 0).toFixed(2)} ` +
                    `near=${Number(validLongDetours[0].__escapeNear || 0).toFixed(2)} destinationNearRelax=${!!validLongDetours[0].__destinationNearRelax} ` +
                    `acceptedByHoldWaypointMode=${!!validLongDetours[0].__acceptedByHoldWaypointMode} acceptedByMultiHoldWaypointMode=${!!validLongDetours[0].__acceptedByMultiHoldWaypointMode} ` +
                    `dist=${Math.round(validLongDetours[0].totalDistance)}m`
                );
                selectedStage = { key: 'long-detour' };
                alternatives = validLongDetours;
                nonBlocked = validLongDetours;
                meaningful = validLongDetours;
                console.log('[BlockAhead][long-detour] road-node fallback succeeded');
            } else {
                _recordBlockAheadRejectReason('long-detour-route-blocked');
            }
        } else {
            _recordBlockAheadRejectReason('long-detour-snap-empty');
            const snapFailure = _markSnapEmptyFailure('long-detour');
            if (snapFailure?.primaryReason && snapFailure.primaryReason !== 'none') {
                _recordBlockAheadRejectReason(`long-detour-snap-empty:${snapFailure.primaryReason}`);
            }
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
    winnerRoute.__candidatePedestrianSafety = winnerRoute.__pedestrianSafety ? { ...winnerRoute.__pedestrianSafety } : null;
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
    const finalPedestrianSafety = await _evaluatePedestrianRouteSafety(winnerRoute, pedestrianSafetySeqContext, `final:${selectedStage?.key || 'unknown'}`);
    console.log(
        `[PedestrianSafety][final] source=${finalPedestrianSafety.contextSource || 'unknown'} ` +
        `status=${finalPedestrianSafety.status} contextFailureKind=${finalPedestrianSafety.contextFailureKind || 'none'} ` +
        `contextFailureDetail=${finalPedestrianSafety.contextFailureDetail || 'none'}`
    );
    finalBlockedStats.candidateSide = winnerRoute?.__escapeLabel?.includes('back-right') ? 'back-right'
        : winnerRoute?.__escapeLabel?.includes('back-left') ? 'back-left'
        : winnerRoute?.__escapeLabel?.includes('right') ? 'right'
        : winnerRoute?.__escapeLabel?.includes('left') ? 'left'
        : null;
    const finalNearPenaltyMode = (selectedStage?.key === 'escape-leg' || selectedStage?.key === 'escape' || selectedStage?.key === 'long-detour')
        ? _assessEscapeNearPenaltyMode(finalBlockedStats, finalOverlap, {
            mode: selectedStage?.key || 'escape',
            side: finalBlockedStats.candidateSide,
            strictNearPenaltyMax: (selectedStage?.key === 'long-detour' && Number(winnerRoute?.__destinationNearRelax))
                ? (BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX + BLOCK_DESTINATION_NEAR_RELAX_STRICT_BONUS)
                : BLOCK_ESCAPE_NEAR_PENALTY_STRICT_MAX
        })
        : { eligible: false, penalty: Infinity };
    const finalOverlapHard = finalOverlap >= BLOCK_OVERLAP_REJECT;
    const finalActualIntersectionDetected = !!finalNearPenaltyMode.actualIntersectionDetected;
    const finalStrictThresholdExceeded = !!finalNearPenaltyMode.strictThresholdExceeded;
    const finalNearOnlyReject = !finalNearPenaltyMode.eligible
        && finalBlockedStats.nearBlocked
        && !finalActualIntersectionDetected
        && !finalStrictThresholdExceeded
        && !finalOverlapHard;
    const finalConservativeSafety = finalPedestrianSafety.status === 'unknown'
        ? _evaluateConservativeUnknownPedestrianSafety(winnerRoute, {
            phase: `final:${selectedStage?.key || 'unknown'}`,
            mode: 'final',
            side: finalBlockedStats.candidateSide || 'unknown',
            label: `final:${selectedStage?.key || 'unknown'}`,
            nearPenaltyMode: finalNearPenaltyMode,
            hardIntersectionDetected: finalActualIntersectionDetected,
            actualIntersectionDetected: finalActualIntersectionDetected,
            blockedBearing: (blockStart && blockEnd) ? _segmentBearingDeg(blockStart, blockEnd) : null
        })
        : {
            conservativeRejectEvaluated: false,
            conservativeRejectApplied: false,
            conservativeRejectReason: null,
            conservativeDecision: 'pass',
            conservativePenalty: 0
        };
    if (winnerRoute.__pedestrianSafety?.status === 'unknown' && finalPedestrianSafety.status === 'unknown') {
        console.log(`[PedestrianSafety] final-check unavailable -> fail-open applied label=final:${selectedStage?.key || 'unknown'} candidateStatus=unknown`);
    }
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
        `pedestrianStatus=${finalPedestrianSafety.status} contextUnavailable=${!!finalPedestrianSafety.contextUnavailable} ` +
        `failOpenApplied=${!!finalPedestrianSafety.failOpenApplied} contextSource=${finalPedestrianSafety.contextSource || 'unknown'} ` +
        `contextFailureKind=${finalPedestrianSafety.contextFailureKind || 'none'} contextFailureDetail=${finalPedestrianSafety.contextFailureDetail || 'none'} ` +
        `conservativeRejectEvaluated=${!!finalConservativeSafety.conservativeRejectEvaluated} ` +
        `conservativeDecision=${finalConservativeSafety.conservativeDecision || 'pass'} ` +
        `conservativeRejectApplied=${!!finalConservativeSafety.conservativeRejectApplied} ` +
        `conservativeRejectReason=${finalConservativeSafety.conservativeRejectReason || 'none'} ` +
        `conservativePenalty=${Number(finalConservativeSafety.conservativePenalty || 0).toFixed(1)}`
    );

    const finalBlockedReject = finalActualIntersectionDetected
        || finalOverlapHard
        || finalStrictThresholdExceeded
        || finalNearOnlyReject;
    if (finalBlockedReject || !routeDiff.meaningful || finalPedestrianSafety.status === 'unsafe' || finalConservativeSafety.conservativeRejectApplied) {
        if (finalConservativeSafety.conservativeRejectApplied) {
            _recordBlockAheadRejectReason('dangerous-crossing-unknown-hard');
            _recordBlockAheadRejectReason(finalConservativeSafety.conservativeRejectReason || 'dangerous-crossing-unknown-hard');
        }
        fail(
            (finalPedestrianSafety.status === 'unsafe' || finalConservativeSafety.conservativeRejectApplied)
                ? 'dangerous-crossing'
                : (finalBlockedReject ? 'failed' : 'no-change'),
            (finalPedestrianSafety.status === 'unsafe' || finalConservativeSafety.conservativeRejectApplied)
                ? '⚠ 危険な道路横断を含むため、迂回ルートを採用できませんでした。現在のルートを継続します。'
                : finalBlockedReject
                ? '⚠ 目的地まで到達できる迂回ルートが見つかりませんでした。現在のルートを継続します。'
                : 'ℹ 現在のルートと実質同じ経路しか見つからなかったため、既存ルートを継続します。',
            ((finalPedestrianSafety.status === 'unsafe') || finalConservativeSafety.conservativeRejectApplied || finalBlockedReject) ? 'danger' : 'info'
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
    adoptedRoute.__pedestrianSafety = { ...finalPedestrianSafety, ...finalConservativeSafety };
    adoptedRoute.__candidatePedestrianSafety = winnerRoute.__candidatePedestrianSafety ? { ...winnerRoute.__candidatePedestrianSafety } : null;
    adoptedRoute.__blockedMode = selectedStage?.key || null;
    adoptedRoute.__blockedSide = finalBlockedStats.candidateSide || null;
    adoptedRoute.__nearPenaltyMode = !!finalNearPenaltyMode.eligible;
    adoptedRoute.__acceptedByNearPenaltyMode = !!(finalNearPenaltyMode.eligible && finalBlockedStats.nearBlocked);
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
    if (typeof onNavRouteSelected === 'function') {
        onNavRouteSelected(adoptedRoute, null, {
            selectedRouteIndex: 0,
            transportMode: selectedBundle.transportMode,
            routes: selectedBundle.routes,
            routeColors: selectedBundle.routeColors,
            onSelectRouteIndex: selectedBundle.selectRouteIndex,
            infoMode: 'navigation_active'
        });
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
        pedestrianStatus: finalPedestrianSafety.status,
        pedestrianContextFailureKind: finalPedestrianSafety.contextFailureKind || 'none',
        conservativeDecision: finalConservativeSafety.conservativeDecision || 'pass',
        conservativeReason: finalConservativeSafety.conservativeRejectReason || 'none',
        conservativePenalty: Number(finalConservativeSafety.conservativePenalty || 0),
        alternativesEvaluated: alternatives.length,
        nonBlockedCount: nonBlocked.length,
        attemptedStages: Array.isArray(_blockAheadPerfMetrics?.stages) ? _blockAheadPerfMetrics.stages.map(stage => stage.key) : [],
        geometryComparison
    };
    _recordBlockAheadExecutionSummary(summary);
    _blockAheadLastTiming = { ..._blockAheadPerfMetrics, ...summary, totalMs, status: 'success' };
    if (typeof window !== 'undefined') window._blockAheadLastTiming = _blockAheadLastTiming;
    const finalRejectReason = _escapeRejectReason(finalNearPenaltyMode, {
        actualIntersectionDetected: finalActualIntersectionDetected,
        overlapHard: finalOverlapHard,
        strictThresholdExceeded: finalStrictThresholdExceeded,
        nearOnlyReject: finalNearOnlyReject
    });
    const debugSummary = _buildBlockAheadDebugSummary(summary, {
        selectedStage: selectedStage?.key || 'stage-unknown',
        selectedNodeId: adoptedRoute.__escapeLabel || null,
        selectedDistance: adoptedRoute.totalDistance,
        route: adoptedRoute,
        pedestrianSafety: adoptedRoute.__pedestrianSafety,
        candidatePedestrianSafety: adoptedRoute.__candidatePedestrianSafety,
        blockedAreaStats: {
            overlap: finalOverlap,
            strict: finalBlockedStats.strictOverlapRatio,
            near: finalBlockedStats.nearBlockedRatio,
            hardIntersectionDetected: finalActualIntersectionDetected,
            rejectReason: finalRejectReason,
            mode: selectedStage?.key || 'stage-unknown',
            side: finalBlockedStats.candidateSide || null,
            nearPenaltyMode: !!finalNearPenaltyMode.eligible,
            acceptedByNearPenaltyMode: !!(finalNearPenaltyMode.eligible && finalBlockedStats.nearBlocked)
        },
        allAcceptedCandidates: meaningful.slice(0, 5).map(route => ({
            stage: selectedStage?.key || 'stage-unknown',
            nodeId: route.__escapeLabel || null,
            pedestrianSafety: {
                status: route.__pedestrianSafety?.status || 'unknown',
                conservativeDecision: route.__pedestrianSafety?.conservativeDecision || 'pass',
                conservativeReason: route.__pedestrianSafety?.conservativeRejectReason || 'none',
                conservativePenalty: Number(route.__pedestrianSafety?.conservativePenalty || 0)
            },
            overlap: Number(route.__escapeOverlap ?? route.__overlap ?? finalOverlap ?? 0),
            strict: Number(route.__escapeStrict ?? route.__blockedStats?.strictOverlapRatio ?? 0),
            near: Number(route.__escapeNear ?? route.__blockedStats?.nearBlockedRatio ?? 0)
        }))
    });
    adoptedRoute.__debugSummary = debugSummary;
    _blockAheadLastTiming.debugSummary = debugSummary;
    _setBlockAheadDebugSummary(debugSummary);
    console.log('[BlockAhead][timing][total]', _blockAheadLastTiming);
    _blockAheadPerfMetrics = null;
}

*/
// ── 到達処理 ─────────────────────────────────────────────────────────────
function _onNavArrival() {
    navHasArrived = true;
    navArrivalConsecutiveCount = 0;
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

    // 非ナビ時情報パネルの表示切り替え
    if (typeof _lipUpdateNavMode === 'function') _lipUpdateNavMode(mode);
    // ナビ ボトムシートの表示切り替え
    if (typeof _navSheetUpdateMode === 'function') _navSheetUpdateMode(mode);
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

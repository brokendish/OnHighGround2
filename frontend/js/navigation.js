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
const DANGEROUS_CROSSING_EVIDENCE_RADIUS_M = 18;
const DANGEROUS_CROSSING_DEDUP_M = 14;
const DANGEROUS_CROSSING_OVERPASS_PADDING_M = 80;
const DANGEROUS_CROSSING_MAJOR_CLASSES = new Set(['trunk', 'trunk_link', 'primary', 'primary_link', 'secondary', 'secondary_link']);
const DANGEROUS_CROSSING_PENALTY_BY_CLASS = {
    trunk: 520,
    trunk_link: 420,
    primary: 380,
    primary_link: 320,
    secondary: 220,
    secondary_link: 180
};
const DANGEROUS_CROSSING_SIGNAL_FACTOR = 0.05;
const DANGEROUS_CROSSING_MARKED_FACTOR = 0.22;
const DANGEROUS_CROSSING_UNCONTROLLED_FACTOR = 0.48;
const BLOCK_FAST_REROUTE_CONFIG = {
    key: 'fast',
    label: 'PhaseA-Fast',
    bypassOffsetsM: [75],
    rejoinOffsetsM: [50],
    maxCandidates: 1,
    allowDirectToDestination: false,
    overlapReject: BLOCK_OVERLAP_REJECT,
    maxExtraDistanceM: 1200,
    maxDistanceRatio: 3.2,
    maxLocalDetourSpanM: 1200,
    maxRejoinDeviationM: 100,
    requireRejoin: true,
    rejectDangerousCrossings: false,
    crossingPenaltyMultiplier: 0,
    sameCorridorRejectRatio: 0.98,
    minBlockedDeviationM: 4,
    rejectBlockedAreaReentry: false,
    maxAllowedBlockedAreaReentryCount: 1,
    skipInitialMovementChecks: true,
    earlyAcceptBlockedDeviationM: 12,
    earlyAcceptSamePathRatio: 0.82,
    earlyAcceptExtraDistanceM: 700,
    earlyAcceptDistanceRatio: 2.4
};
const BLOCK_REROUTE_STAGE_TOP_CANDIDATES = {
    local: 3,
    extended: 3,
    reachability: 2
};
const BLOCK_REROUTE_STAGE_MAX_FINAL_TRIES = {
    local: 2,
    extended: 2,
    reachability: 1
};
const BLOCK_REROUTE_STAGES = [
    {
        key: 'local',
        label: 'Stage1-Local',
        bypassOffsetsM: [75],
        rejoinOffsetsM: [20, 50],
        allowDirectToDestination: false,
        overlapReject: BLOCK_OVERLAP_REJECT,
        maxExtraDistanceM: 250,
        maxDistanceRatio: 1.45,
        maxLocalDetourSpanM: 300,
        maxRejoinDeviationM: 35,
        requireRejoin: true,
        rejectDangerousCrossings: true,
        crossingPenaltyMultiplier: 2.2,
        sameCorridorRejectRatio: 0.72,
        minBlockedDeviationM: 18,
        rejectBlockedAreaReentry: true
    },
    {
        key: 'extended',
        label: 'Stage2-Extended',
        bypassOffsetsM: [75, 120, 170],
        rejoinOffsetsM: [120, 220, 320, 450],
        allowDirectToDestination: false,
        overlapReject: BLOCK_OVERLAP_REJECT,
        maxExtraDistanceM: 900,
        maxDistanceRatio: 2.6,
        maxLocalDetourSpanM: 900,
        maxRejoinDeviationM: 80,
        requireRejoin: true,
        rejectDangerousCrossings: false,
        crossingPenaltyMultiplier: 1.25,
        sameCorridorRejectRatio: 0.82,
        minBlockedDeviationM: 12,
        rejectBlockedAreaReentry: true
    },
    {
        key: 'reachability',
        label: 'Stage3-Reachability',
        bypassOffsetsM: [75, 120, 170, 240],
        rejoinOffsetsM: [220, 420, 700],
        allowDirectToDestination: true,
        overlapReject: BLOCK_OVERLAP_REJECT,
        maxExtraDistanceM: 2500,
        maxDistanceRatio: 6.0,
        maxLocalDetourSpanM: 2500,
        maxRejoinDeviationM: 160,
        requireRejoin: false,
        rejectDangerousCrossings: false,
        crossingPenaltyMultiplier: 0.7,
        sameCorridorRejectRatio: 0.9,
        minBlockedDeviationM: 8,
        rejectBlockedAreaReentry: false
    }
];

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
    fastAcceptedRuns: 0,
    fastRejectedRuns: 0,
    safeAttemptedRuns: 0,
    safeAcceptedRuns: 0,
    safeFailedRuns: 0,
    phasePathCounts: {},
    rejectReasonCounts: {},
    avgTotalMs: 0,
    avgFastMs: 0,
    avgSafeMs: 0,
    avgOsrmMs: 0,
    avgOverpassMs: 0,
    avgDisplayPipelineMs: 0
};
let _osrmEvalCache = new Map();
let _crossingRiskCache = new Map();
let _crossingContextInflight = new Map();

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

function _noteBlockAheadRejectReason(metric, reason) {
    if (!metric || !reason) return;
    if (!metric.rejectReasons) metric.rejectReasons = {};
    _incrementReasonCounter(metric.rejectReasons, reason);
}

function _topBlockAheadRejectReason(reasonMap) {
    if (!reasonMap) return null;
    const entries = Object.entries(reasonMap);
    if (entries.length === 0) return null;
    entries.sort((a, b) => b[1] - a[1]);
    return entries[0][0];
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
    if (summary.fast?.accepted) agg.fastAcceptedRuns += 1;
    else agg.fastRejectedRuns += 1;
    if (summary.safe?.attempted) agg.safeAttemptedRuns += 1;
    if (summary.safe?.accepted) agg.safeAcceptedRuns += 1;
    if (summary.safe?.attempted && !summary.safe?.accepted) agg.safeFailedRuns += 1;
    if (summary.phasePath) {
        agg.phasePathCounts[summary.phasePath] = (agg.phasePathCounts[summary.phasePath] || 0) + 1;
    }
    [summary.fast?.rejectReason, summary.safe?.rejectReason].filter(Boolean).forEach(reason => {
        _incrementReasonCounter(agg.rejectReasonCounts, reason);
    });
    agg.avgTotalMs = _updateRollingAverage(agg.avgTotalMs, prevCount, summary.totalMs);
    agg.avgFastMs = _updateRollingAverage(agg.avgFastMs, prevCount, summary.fast?.timeMs);
    agg.avgSafeMs = _updateRollingAverage(agg.avgSafeMs, prevCount, summary.safe?.timeMs);
    agg.avgOsrmMs = _updateRollingAverage(agg.avgOsrmMs, prevCount, summary.osrmMs);
    agg.avgOverpassMs = _updateRollingAverage(agg.avgOverpassMs, prevCount, summary.overpassMs);
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

function _waypointCacheKey(waypoints) {
    if (!Array.isArray(waypoints) || waypoints.length === 0) return '';
    return waypoints.map(wp => `${Number(wp.lat).toFixed(5)},${Number(wp.lng ?? wp.lon).toFixed(5)}`).join('|');
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
    const cacheKey = _waypointCacheKey(waypoints);
    const cached = cacheKey ? _osrmEvalCache.get(cacheKey) : null;
    if (cached) {
        if (_blockAheadPerfMetrics) _blockAheadPerfMetrics.osrmCacheHits = (_blockAheadPerfMetrics.osrmCacheHits || 0) + 1;
        return cached instanceof Promise ? await cached : cached;
    }
    const transportMode = document.getElementById('transportMode')?.value ?? 'walking';
    const profile       = transportMode === 'walking' ? 'walking' : 'driving';
    const serviceUrl    = OSRM_SERVICE_URLS[profile];
    const coordStr      = waypoints.map(wp => `${wp.lng ?? wp.lon},${wp.lat}`).join(';');
    const url           = `${serviceUrl}/${profile}/${coordStr}?overview=full&geometries=geojson&alternatives=false&steps=true`;
    const startedAt = _perfNowMs();
    const fetchPromise = (async () => {
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
        } finally {
            const durationMs = _perfNowMs() - startedAt;
            _recordBlockAheadTiming('osrmEval', durationMs);
            console.log(`[BlockAhead][timing] osrm eval ${Math.round(durationMs)}ms`);
        }
    })();
    if (cacheKey) _osrmEvalCache.set(cacheKey, fetchPromise);
    const result = await fetchPromise;
    if (cacheKey) _osrmEvalCache.set(cacheKey, result);
    return result;
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

function _countBlockedAreaReentries(coords, center, radiusM) {
    if (!Array.isArray(coords) || coords.length === 0 || !center || !Number.isFinite(radiusM)) return 0;
    let segmentsInside = 0;
    let wasInside = false;
    for (const point of coords) {
        const inside = _segmentLengthMeters(point, center) <= radiusM;
        if (inside && !wasInside) segmentsInside++;
        wasInside = inside;
    }
    return Math.max(0, segmentsInside - 1);
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
    const blockedSamples = blockMid
        ? allSamples.filter(point => _segmentLengthMeters(point, blockMid) <= blockRadius)
        : [];
    const blockedDistances = blockedSamples.map(point => _distancePointToRoute(point, originalCoords)).filter(Number.isFinite);
    const blockedMeanDeviationM = blockedDistances.length
        ? blockedDistances.reduce((sum, d) => sum + d, 0) / blockedDistances.length
        : overallMeanDeviationM;
    const blockedSamePathRatio = blockedDistances.length
        ? blockedDistances.filter(d => d <= 12).length / blockedDistances.length
        : 1;
    const blockAreaReentryCount = blockMid
        ? _countBlockedAreaReentries(newCoords, blockMid, blockRadius)
        : 0;
    return { overallMeanDeviationM, blockedMeanDeviationM, blockedSamePathRatio, blockAreaReentryCount };
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

function _candidateCorridorMetrics(routeLike, originalRoute, context = {}) {
    const coords = Array.isArray(routeLike?.coordinates) ? routeLike.coordinates : [];
    const originalCoords = Array.isArray(originalRoute?.coordinates) ? originalRoute.coordinates : [];
    if (coords.length < 2 || originalCoords.length < 2) {
        return {
            overallMeanDeviationM: Infinity,
            blockedMeanDeviationM: Infinity,
            blockedSamePathRatio: 0,
            blockAreaReentryCount: 0
        };
    }
    return _routeDifferenceMetrics(coords, originalCoords, context);
}

function _pushUniqueBlockAheadCandidate(target, candidate) {
    const duplicate = target.some((existing) => {
        if (existing.directToDestination !== candidate.directToDestination) return false;
        if (existing.side !== candidate.side) return false;
        if (_segmentLengthMeters(existing.bypass, candidate.bypass) > 12) return false;
        if (!existing.directToDestination) {
            if (!existing.rejoin || !candidate.rejoin) return false;
            if (_segmentLengthMeters(existing.rejoin, candidate.rejoin) > 22) return false;
        }
        return true;
    });
    if (!duplicate) target.push(candidate);
}

function _isFastRerouteEarlyAcceptCandidate(candidate, thresholds = {}) {
    const assessment = candidate?.assessment || null;
    const corridorMetrics = candidate?.corridorMetrics || null;
    if (!assessment?.valid || !corridorMetrics) return false;
    const blockedDeviation = corridorMetrics.blockedMeanDeviationM ?? Infinity;
    const blockedSamePathRatio = corridorMetrics.blockedSamePathRatio ?? 1;
    const extraDistance = assessment.extraDistance ?? Infinity;
    const distanceRatio = assessment.distanceRatio ?? Infinity;
    return blockedDeviation >= (thresholds.earlyAcceptBlockedDeviationM ?? 20)
        && blockedSamePathRatio <= (thresholds.earlyAcceptSamePathRatio ?? 0.58)
        && extraDistance <= (thresholds.earlyAcceptExtraDistanceM ?? 180)
        && distanceRatio <= (thresholds.earlyAcceptDistanceRatio ?? 1.35);
}

function _estimateFastCandidateScore(candidate, destination) {
    if (!candidate?.bypass || !candidate?.rejoin || !destination) return Infinity;
    const blockStart = candidate.blockStart;
    const startToBypass = _segmentLengthMeters(blockStart, candidate.bypass);
    const bypassToRejoin = _segmentLengthMeters(candidate.bypass, candidate.rejoin);
    const rejoinToDest = _segmentLengthMeters(candidate.rejoin, destination);
    const headingPenalty = (() => {
        const routeBearing = _segmentBearingDeg(blockStart, candidate.rejoin);
        const bypassBearing = _segmentBearingDeg(blockStart, candidate.bypass);
        return _bearingDiffDeg(routeBearing, bypassBearing) * 1.5;
    })();
    const destinationPenalty = (() => {
        const destBearing = _segmentBearingDeg(candidate.bypass, destination);
        const rejoinBearing = _segmentBearingDeg(candidate.bypass, candidate.rejoin);
        return _bearingDiffDeg(destBearing, rejoinBearing) * 1.2;
    })();
    return startToBypass + bypassToRejoin + rejoinToDest + headingPenalty + destinationPenalty;
}

function _pickFastRerouteCandidate(stage, context) {
    const offsetM = stage.bypassOffsetsM[0];
    const rejoinOffsetM = stage.rejoinOffsetsM[0];
    const rejoin = _walkAlongRoute(context.coords, context.projection, BLOCK_AHEAD_END_METERS + rejoinOffsetM);
    const candidates = [1, -1].map((side) => {
        const bypass = _perpendicularOffsetPoint(context.blockStart, context.blockEnd, offsetM, side);
        const candidate = {
            phaseKey: 'fast',
            stage,
            bypass,
            rejoin,
            blockStart: context.blockStart,
            offsetM,
            rejoinOffsetM,
            directToDestination: false,
            side: side === 1 ? 'left' : 'right'
        };
        const heuristicScore = _estimateFastCandidateScore(candidate, context.destWp);
        return { ...candidate, heuristicScore };
    }).sort((a, b) => a.heuristicScore - b.heuristicScore);
    const picked = candidates[0] || null;
    console.log('[BlockAhead][FAST_REROUTE][pick]', candidates.map(c => `${c.side}:${Math.round(c.heuristicScore)}`), '=>', picked ? picked.side : 'none');
    return picked ? [picked] : [];
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

    const thresholds = context?.thresholds || {};
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
    const localDetourSpan = context.rejoin
        ? _routeSpanBetweenPoints(coords, context.blockStart, context.rejoin)
        : _routePolylineLength(coords);
    const blockStartDeviation = _navFindClosestOnRoute(coords, context.blockStart.lat, context.blockStart.lng)?.routeOffsetMeters ?? Infinity;
    const bypassDeviation = _navFindClosestOnRoute(coords, context.bypass.lat, context.bypass.lng)?.routeOffsetMeters ?? Infinity;
    const rejoinDeviation = context.rejoin
        ? (_navFindClosestOnRoute(coords, context.rejoin.lat, context.rejoin.lng)?.routeOffsetMeters ?? Infinity)
        : 0;
    const initialMovement = _analyzeInitialMovement(routeLike);

    const reasons = [];
    const overlapReject = thresholds.overlapReject ?? BLOCK_OVERLAP_REJECT;
    const maxExtraDistanceM = thresholds.maxExtraDistanceM ?? MAX_REROUTE_EXTRA_DISTANCE_M;
    const maxDistanceRatio = thresholds.maxDistanceRatio ?? MAX_REROUTE_DISTANCE_RATIO;
    const maxLocalDetourSpanM = thresholds.maxLocalDetourSpanM ?? MAX_LOCAL_DETOUR_SPAN_M;
    const maxRejoinDeviationM = thresholds.maxRejoinDeviationM ?? MAX_REJOIN_DEVIATION_M;
    const requireRejoin = thresholds.requireRejoin !== false;
    const crossingAssessment = context?.crossingAssessment || null;
    const corridorMetrics = context?.corridorMetrics || null;

    if (overlap > overlapReject) reasons.push(`overlap=${overlap.toFixed(2)}`);
    if (extraDistance > maxExtraDistanceM) reasons.push(`extra=${Math.round(extraDistance)}m`);
    if (distanceRatio > maxDistanceRatio) reasons.push(`ratio=${distanceRatio.toFixed(2)}`);
    if (requireRejoin && localDetourSpan > maxLocalDetourSpanM) reasons.push(`local-span=${Math.round(localDetourSpan)}m`);
    if (blockStartDeviation > maxRejoinDeviationM) reasons.push(`block-start-dev=${Math.round(blockStartDeviation)}m`);
    if (bypassDeviation > maxRejoinDeviationM) reasons.push(`bypass-dev=${Math.round(bypassDeviation)}m`);
    if (requireRejoin && rejoinDeviation > maxRejoinDeviationM) reasons.push(`rejoin-dev=${Math.round(rejoinDeviation)}m`);
    if (!thresholds.skipInitialMovementChecks) {
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
    } // end skipInitialMovementChecks guard
    if (thresholds.rejectDangerousCrossings && (crossingAssessment?.dangerousCount || 0) > 0) {
        reasons.push(`dangerous-crossing=${crossingAssessment.dangerousCount}`);
    }
    if (corridorMetrics) {
        const sameCorridorRejectRatio = thresholds.sameCorridorRejectRatio ?? 1;
        const minBlockedDeviationM = thresholds.minBlockedDeviationM ?? 0;
        if (corridorMetrics.blockedSamePathRatio >= sameCorridorRejectRatio
                && corridorMetrics.blockedMeanDeviationM < minBlockedDeviationM) {
            reasons.push(`same-corridor=${corridorMetrics.blockedSamePathRatio.toFixed(2)}`);
        }
        const maxAllowedBlockedAreaReentryCount = thresholds.rejectBlockedAreaReentry
            ? (thresholds.maxAllowedBlockedAreaReentryCount ?? 0)
            : (thresholds.maxAllowedBlockedAreaReentryCount ?? Infinity);
        if (corridorMetrics.blockAreaReentryCount > maxAllowedBlockedAreaReentryCount) {
            reasons.push(`block-reentry=${corridorMetrics.blockAreaReentryCount}`);
        }
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
        selfApproachDistanceM: initialMovement.selfApproachDistanceM,
        crossingPenalty: crossingAssessment?.penalty || 0,
        dangerousCrossingCount: crossingAssessment?.dangerousCount || 0,
        uncontrolledCrossingCount: crossingAssessment?.uncontrolledCount || 0,
        crossingWarningText: crossingAssessment?.warningText || '',
        blockedMeanDeviationM: corridorMetrics?.blockedMeanDeviationM ?? Infinity,
        blockedSamePathRatio: corridorMetrics?.blockedSamePathRatio ?? 0,
        blockAreaReentryCount: corridorMetrics?.blockAreaReentryCount ?? 0
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

function _cloneRoute(route) {
    return route ? JSON.parse(JSON.stringify(route)) : route;
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

function _metersToLat(meters) {
    return meters / 111111;
}

function _metersToLng(meters, lat) {
    const cosLat = Math.max(0.2, Math.cos((lat || 0) * Math.PI / 180));
    return meters / (111111 * cosLat);
}

function _routeBoundsWithPadding(coords, paddingM = 0) {
    if (!Array.isArray(coords) || coords.length === 0) return null;
    let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
    coords.forEach((point) => {
        const lat = Number(point?.lat);
        const lng = Number(point?.lng ?? point?.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) return;
        minLat = Math.min(minLat, lat);
        maxLat = Math.max(maxLat, lat);
        minLng = Math.min(minLng, lng);
        maxLng = Math.max(maxLng, lng);
    });
    if (!Number.isFinite(minLat) || !Number.isFinite(minLng)) return null;
    const midLat = (minLat + maxLat) / 2;
    return {
        minLat: minLat - _metersToLat(paddingM),
        maxLat: maxLat + _metersToLat(paddingM),
        minLng: minLng - _metersToLng(paddingM, midLat),
        maxLng: maxLng + _metersToLng(paddingM, midLat)
    };
}

function _segmentIntersectionPoint(a, b, c, d) {
    const ax = Number(a?.lng ?? a?.lon), ay = Number(a?.lat);
    const bx = Number(b?.lng ?? b?.lon), by = Number(b?.lat);
    const cx = Number(c?.lng ?? c?.lon), cy = Number(c?.lat);
    const dx = Number(d?.lng ?? d?.lon), dy = Number(d?.lat);
    const denom = ((bx - ax) * (dy - cy)) - ((by - ay) * (dx - cx));
    if (Math.abs(denom) < 1e-12) return null;
    const t = (((cx - ax) * (dy - cy)) - ((cy - ay) * (dx - cx))) / denom;
    const u = (((cx - ax) * (by - ay)) - ((cy - ay) * (bx - ax))) / denom;
    if (t < 0 || t > 1 || u < 0 || u > 1) return null;
    return {
        lat: ay + t * (by - ay),
        lng: ax + t * (bx - ax)
    };
}

let _crossingContextCache = new Map();

function _crossingContextCacheKey(bounds) {
    if (!bounds) return null;
    return [
        bounds.minLat.toFixed(4),
        bounds.minLng.toFixed(4),
        bounds.maxLat.toFixed(4),
        bounds.maxLng.toFixed(4)
    ].join(':');
}

function _pushCrossingEvidenceFromWay(target, way) {
    const geom = Array.isArray(way?.geometry) ? way.geometry : [];
    geom.forEach((p, index) => {
        if (!Number.isFinite(Number(p?.lat)) || !Number.isFinite(Number(p?.lon))) return;
        target.push({
            lat: Number(p.lat),
            lng: Number(p.lon),
            kind: way?.tags?.crossing === 'traffic_signals' ? 'signals'
                : (way?.tags?.crossing === 'marked' ? 'marked'
                    : ((way?.tags?.highway === 'footway' && way?.tags?.footway === 'crossing') ? 'marked' : 'uncontrolled')),
            tags: way?.tags || {},
            source: `way:${way?.id ?? index}`
        });
    });
}

async function _fetchCrossingContextForRoute(coords) {
    const bounds = _routeBoundsWithPadding(coords, DANGEROUS_CROSSING_OVERPASS_PADDING_M);
    if (!bounds || typeof fetch !== 'function') return null;
    const cacheKey = _crossingContextCacheKey(bounds);
    if (cacheKey && _crossingContextCache.has(cacheKey)) {
        if (_blockAheadPerfMetrics) _blockAheadPerfMetrics.crossingContextCacheHits = (_blockAheadPerfMetrics.crossingContextCacheHits || 0) + 1;
        return _crossingContextCache.get(cacheKey);
    }
    if (cacheKey && _crossingContextInflight.has(cacheKey)) {
        if (_blockAheadPerfMetrics) _blockAheadPerfMetrics.crossingContextInflightHits = (_blockAheadPerfMetrics.crossingContextInflightHits || 0) + 1;
        return await _crossingContextInflight.get(cacheKey);
    }

    const bbox = `${bounds.minLat},${bounds.minLng},${bounds.maxLat},${bounds.maxLng}`;
    const query = `[out:json][timeout:8];
(
  way["highway"~"^(trunk|trunk_link|primary|primary_link|secondary|secondary_link)$"](${bbox});
  node["highway"="crossing"](${bbox});
  node["crossing"](${bbox});
  node["highway"="traffic_signals"](${bbox});
  way["highway"="footway"]["footway"="crossing"](${bbox});
);
out geom;`;

    const startedAt = _perfNowMs();
    const inflight = (async () => {
        try {
            const res = await fetch('https://overpass-api.de/api/interpreter', {
                method: 'POST',
                headers: { 'Content-Type': 'text/plain;charset=UTF-8' },
                body: query
            });
            if (!res.ok) return null;
            const data = await res.json();
            const elements = Array.isArray(data?.elements) ? data.elements : [];
            const majorRoads = [];
            const crossingEvidence = [];
            elements.forEach((el) => {
                const tags = el?.tags || {};
                if (el?.type === 'way' && DANGEROUS_CROSSING_MAJOR_CLASSES.has(tags.highway) && Array.isArray(el.geometry) && el.geometry.length >= 2) {
                    majorRoads.push({
                        id: el.id,
                        highway: tags.highway,
                        geometry: el.geometry.map(p => ({ lat: Number(p.lat), lng: Number(p.lon) }))
                    });
                }
                if (el?.type === 'node') {
                    const kind = tags.highway === 'traffic_signals' || tags.crossing === 'traffic_signals'
                        ? 'signals'
                        : (tags.crossing === 'marked' || tags.crossing_ref === 'zebra' ? 'marked'
                            : ((tags.highway === 'crossing' || tags.crossing) ? 'uncontrolled' : null));
                    if (kind && Number.isFinite(Number(el.lat)) && Number.isFinite(Number(el.lon))) {
                        crossingEvidence.push({
                            lat: Number(el.lat),
                            lng: Number(el.lon),
                            kind,
                            tags,
                            source: `node:${el.id}`
                        });
                    }
                } else if (el?.type === 'way' && tags.highway === 'footway' && tags.footway === 'crossing') {
                    _pushCrossingEvidenceFromWay(crossingEvidence, el);
                }
            });

            const parsed = { majorRoads, crossingEvidence };
            if (cacheKey) _crossingContextCache.set(cacheKey, parsed);
            return parsed;
        } catch (error) {
            console.warn('[BlockAhead][crossing] context fetch failed:', error);
            return null;
        } finally {
            const durationMs = _perfNowMs() - startedAt;
            _recordBlockAheadTiming('overpass', durationMs);
            console.log(`[BlockAhead][timing] overpass ${Math.round(durationMs)}ms`);
            if (cacheKey) _crossingContextInflight.delete(cacheKey);
        }
    })();
    if (cacheKey) _crossingContextInflight.set(cacheKey, inflight);
    return await inflight;
}

function _classifyCrossingEvidence(point, context) {
    const evidence = Array.isArray(context?.crossingEvidence) ? context.crossingEvidence : [];
    let nearest = null;
    for (const item of evidence) {
        const distance = _segmentLengthMeters(point, item);
        if (distance > DANGEROUS_CROSSING_EVIDENCE_RADIUS_M) continue;
        if (!nearest || distance < nearest.distance) {
            nearest = { ...item, distance };
        }
    }
    if (!nearest) return { kind: 'none', distance: Infinity };
    return nearest;
}

async function _assessRouteCrossingRisk(routeLike, stage) {
    const coords = Array.isArray(routeLike?.coordinates) ? routeLike.coordinates : [];
    if (coords.length < 2) {
        return { available: false, crossings: [], dangerousCount: 0, penalty: 0 };
    }
    const routeKey = `${stage?.key || 'na'}:${_routeCoordsCacheKey(coords)}`;
    if (routeKey && _crossingRiskCache.has(routeKey)) {
        if (_blockAheadPerfMetrics) _blockAheadPerfMetrics.crossingRiskCacheHits = (_blockAheadPerfMetrics.crossingRiskCacheHits || 0) + 1;
        return _crossingRiskCache.get(routeKey);
    }
    const startedAt = _perfNowMs();
    const context = await _fetchCrossingContextForRoute(coords);
    if (!context || !Array.isArray(context.majorRoads) || context.majorRoads.length === 0) {
        const empty = { available: false, crossings: [], dangerousCount: 0, penalty: 0 };
        if (routeKey) _crossingRiskCache.set(routeKey, empty);
        _recordBlockAheadTiming('crossingRisk', _perfNowMs() - startedAt);
        return empty;
    }

    const crossings = [];
    for (let i = 0; i < coords.length - 1; i++) {
        const routeA = coords[i];
        const routeB = coords[i + 1];
        for (const road of context.majorRoads) {
            const roadGeom = Array.isArray(road.geometry) ? road.geometry : [];
            for (let j = 0; j < roadGeom.length - 1; j++) {
                const hit = _segmentIntersectionPoint(routeA, routeB, roadGeom[j], roadGeom[j + 1]);
                if (!hit) continue;
                const duplicate = crossings.find(existing =>
                    existing.roadClass === road.highway && _segmentLengthMeters(existing.point, hit) < DANGEROUS_CROSSING_DEDUP_M
                );
                if (duplicate) continue;
                const evidence = _classifyCrossingEvidence(hit, context);
                const roadPenalty = DANGEROUS_CROSSING_PENALTY_BY_CLASS[road.highway] || 180;
                const factor = evidence.kind === 'signals'
                    ? DANGEROUS_CROSSING_SIGNAL_FACTOR
                    : (evidence.kind === 'marked'
                        ? DANGEROUS_CROSSING_MARKED_FACTOR
                        : (evidence.kind === 'uncontrolled' ? DANGEROUS_CROSSING_UNCONTROLLED_FACTOR : 1));
                const severity = evidence.kind === 'signals'
                    ? 'safe'
                    : (evidence.kind === 'marked'
                        ? 'marked'
                        : (evidence.kind === 'uncontrolled' ? 'uncontrolled' : 'dangerous'));
                crossings.push({
                    point: hit,
                    roadClass: road.highway,
                    evidence: evidence.kind,
                    severity,
                    penalty: roadPenalty * factor
                });
            }
        }
    }

    const dangerousCount = crossings.filter(c => c.severity === 'dangerous').length;
    const uncontrolledCount = crossings.filter(c => c.severity === 'uncontrolled').length;
    const result = {
        available: true,
        crossings,
        dangerousCount,
        uncontrolledCount,
        penalty: crossings.reduce((sum, c) => sum + c.penalty, 0),
        warningText: dangerousCount > 0
            ? '途中に信号や明確な横断歩道が確認できない大きな道路横断があります'
            : (uncontrolledCount > 0 ? '途中に注意が必要な大きな道路横断があります' : '')
    };
    if (routeKey) _crossingRiskCache.set(routeKey, result);
    _recordBlockAheadTiming('crossingRisk', _perfNowMs() - startedAt);
    return result;
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

function _clearBlockAheadLayer() {
    if (_blockAheadLayer && typeof map !== 'undefined') {
        map.removeLayer(_blockAheadLayer);
    }
    _blockAheadLayer = null;
}

// 「この先を避けて再ルート」— メイン関数（マルチ候補評価版）
async function blockAheadAndReroute() {
    const rerouteStartedAt = _perfNowMs();
    _blockAheadPerfMetrics = {
        startedAt: rerouteStartedAt,
        osrmCacheHits: 0,
        crossingContextCacheHits: 0,
        crossingContextInflightHits: 0,
        crossingRiskCacheHits: 0,
        phases: [],
        stages: [],
        phasePath: [],
        fast: { attempted: true, accepted: false, rejectReasons: {} },
        safe: { attempted: false, accepted: false, rejectReasons: {} }
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

    const startWp = { lat: currentLocation.lat, lng: currentLocation.lon };
    const destWp  = { lat: navDestination.lat,  lng: navDestination.lon  };
    const tryCandidate = (candidate) => new Promise((resolve) => {
        let settled = false;
        const finish = (result) => {
            if (settled) return;
            settled = true;
            resolve(result);
        };
        const extraWaypoints = candidate.directToDestination
            ? [blockStart, candidate.bypass]
            : [blockStart, candidate.bypass, candidate.rejoin];
        const routed = drawRouteTo(navDestination.lat, navDestination.lon, {
            preserveCurrentDisplay: true,
            extraWaypoints,
            onRoutesAvailable: async ({ routes, selectedRouteIndex, routeColors, formatter, transportMode, selectRouteIndex }) => {
                if (_blockAheadSeq !== mySeq) {
                    console.log('[BlockAhead] stale callback ignored (seq mismatch)');
                    finish({ status: 'stale' });
                    return;
                }
                const selectedRoute = routes?.[selectedRouteIndex];
                const crossingAssessment = candidate.skipCrossingEvaluation
                    ? null
                    : await _assessRouteCrossingRisk(selectedRoute, candidate.stage);
                const corridorMetrics = _candidateCorridorMetrics(selectedRoute, originalRouteSnapshot, {
                    bufMid,
                    overlapRadius
                });
                const finalAssessment = _assessBlockAheadRoute(selectedRoute, {
                    baseRemainingDistance,
                    bufMid,
                    overlapRadius,
                    blockStart,
                    bypass: candidate.bypass,
                    rejoin: candidate.rejoin,
                    thresholds: candidate.stage,
                    crossingAssessment,
                    corridorMetrics
                });
                const routeDifference = _isMeaningfullyDifferentReroute(selectedRoute, originalRouteSnapshot, {
                    bufMid,
                    overlapRadius
                });
                console.log(
                    `[BlockAhead][final][${candidate.stage.label}] ${candidate.side}/${candidate.offsetM}m/${candidate.directToDestination ? 'direct' : `rejoin+${candidate.rejoinOffsetM}`}: valid=${finalAssessment.valid} overlap=${(finalAssessment.overlap ?? 0).toFixed(2)} extra=${Math.round(finalAssessment.extraDistance ?? 0)}m span=${Math.round(finalAssessment.localDetourSpan ?? 0)}m crossingPenalty=${Math.round(finalAssessment.crossingPenalty ?? 0)} dangerousCrossings=${finalAssessment.dangerousCrossingCount ?? 0} overallDiff=${Math.round(routeDifference.overallMeanDeviationM)}m blockedDiff=${Math.round(finalAssessment.blockedMeanDeviationM ?? Infinity)}m blockedSame=${(finalAssessment.blockedSamePathRatio ?? 0).toFixed(2)} reentry=${finalAssessment.blockAreaReentryCount ?? 0} delta=${Math.round(routeDifference.distanceDelta)}m firstLeg=${Math.round(finalAssessment.firstLegMeters ?? 0)}m firstTurn=${Number.isFinite(finalAssessment.distanceToFirstTurnMeters) ? Math.round(finalAssessment.distanceToFirstTurnMeters) : 'none'}m angle=${Math.round(finalAssessment.firstTurnAngleDeg ?? 0)} zigzag=${Math.round(finalAssessment.initialZigzagScore ?? 0)} detour=${Number.isFinite(finalAssessment.initialDetourFactor) ? finalAssessment.initialDetourFactor.toFixed(2) : 'inf'} return=${Number.isFinite(finalAssessment.returnNearStartMeters) ? Math.round(finalAssessment.returnNearStartMeters) : 'inf'}m self=${Number.isFinite(finalAssessment.selfApproachDistanceM) ? Math.round(finalAssessment.selfApproachDistanceM) : 'inf'}m reasons=${finalAssessment.reasons.join(',') || 'ok'}`
                );
                if (!finalAssessment.valid) {
                    finish({ status: 'invalid-final', finalAssessment, crossingAssessment });
                    return;
                }
                if (!routeDifference.meaningful) {
                    finish({ status: 'no-change', finalAssessment, crossingAssessment, routeDifference });
                    return;
                }
                ++_blockAheadSeq;
                finish({
                    status: 'success',
                    finalAssessment,
                    crossingAssessment,
                    routeDifference,
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
    let sawNoChange = false;
    const finalizeExecution = (status, extra = {}) => {
        const perf = _blockAheadPerfMetrics || {};
        const fastPhase = (perf.phases || []).find(phase => phase.key === 'fast') || {};
        const safePhase = (perf.phases || []).find(phase => phase.key === 'safe-refinement') || {};
        const summary = {
            status,
            phasePath: Array.isArray(perf.phasePath) ? perf.phasePath.join('>') : '',
            fast: {
                attempted: perf.fast?.attempted === true,
                accepted: perf.fast?.accepted === true,
                rejectReason: perf.fast?.rejectReason || _topBlockAheadRejectReason(perf.fast?.rejectReasons),
                timeMs: fastPhase.durationMs || 0
            },
            safe: {
                attempted: perf.safe?.attempted === true,
                accepted: perf.safe?.accepted === true,
                rejectReason: perf.safe?.rejectReason || _topBlockAheadRejectReason(perf.safe?.rejectReasons),
                timeMs: safePhase.durationMs || 0
            },
            totalMs: (_perfNowMs() - rerouteStartedAt),
            osrmMs: perf.osrmEval?.totalMs || 0,
            overpassMs: perf.overpass?.totalMs || 0,
            displayPipelineMs: perf.routeReconstruction?.totalMs || 0,
            fastRejected: perf.fast?.accepted !== true,
            safeAttempted: perf.safe?.attempted === true,
            safeFailed: perf.safe?.attempted === true && perf.safe?.accepted !== true,
            ...extra
        };
        _recordBlockAheadExecutionSummary(summary);
        console.log(`[BlockAhead][summary] path=${summary.phasePath || 'none'} status=${summary.status} fast=${summary.fast.accepted ? 'accepted' : `rejected(${summary.fast.rejectReason || 'unknown'})`} safe=${summary.safe.attempted ? (summary.safe.accepted ? 'accepted' : `failed(${summary.safe.rejectReason || 'unknown'})`) : 'skipped'} total=${Math.round(summary.totalMs)}ms fastMs=${Math.round(summary.fast.timeMs)} safeMs=${Math.round(summary.safe.timeMs)} osrm=${Math.round(summary.osrmMs)} overpass=${Math.round(summary.overpassMs)} display=${Math.round(summary.displayPipelineMs)}ms`);
        return summary;
    };
    const finalizeStale = () => {
        navBlockAheadInProgress = false;
        _clearBlockAheadLayer();
        _updateNavUI();
        const summary = finalizeExecution('stale');
        _blockAheadLastTiming = { ..._blockAheadPerfMetrics, ...summary, totalMs: summary.totalMs, status: 'stale' };
        console.log('[BlockAhead][timing][total]', _blockAheadLastTiming);
        _blockAheadPerfMetrics = null;
    };
    const scorePreliminaryCandidate = (candidate, stage) => {
        const turnCount = Number(candidate.route.turnCount) || 0;
        const sharpTurnCount = Number(candidate.route.sharpTurnCount) || 0;
        const score = candidate.route.totalDistance
            + (turnCount * BLOCK_TURN_PENALTY_M)
            + (sharpTurnCount * BLOCK_SHARP_TURN_PENALTY_M)
            + (Math.max(0, candidate.assessment?.extraDistance || 0) * (stage.key === 'reachability' ? 0.8 : 2))
            + (Math.max(0, (candidate.assessment?.localDetourSpan || 0) - 120) * (stage.key === 'local' ? 2 : 0.6))
            + (Math.max(0, MIN_FIRST_TURN_DISTANCE_M - (candidate.assessment?.distanceToFirstTurnMeters ?? Infinity)) * 8)
            + (Math.max(0, (candidate.assessment?.firstTurnAngleDeg || 0) - 75) * 3)
            + ((candidate.assessment?.initialZigzagScore || 0) * 1.2)
            + (candidate.directToDestination ? 120 : 0);
        console.log(
            `[BlockAhead][score-pre][${stage.label}] ${candidate.side}/${candidate.offsetM}m/${candidate.directToDestination ? 'direct' : `rejoin+${candidate.rejoinOffsetM}`}: overlap=${(candidate.assessment?.overlap ?? 0).toFixed(2)} dist=${Math.round(candidate.route.totalDistance)}m turns=${turnCount} sharp=${sharpTurnCount} blockedDiff=${Math.round(candidate.corridorMetrics?.blockedMeanDeviationM ?? Infinity)}m blockedSame=${(candidate.corridorMetrics?.blockedSamePathRatio ?? 0).toFixed(2)} reentry=${candidate.corridorMetrics?.blockAreaReentryCount ?? 0} extra=${Math.round(candidate.assessment?.extraDistance ?? 0)}m span=${Math.round(candidate.assessment?.localDetourSpan ?? 0)}m firstLeg=${Math.round(candidate.assessment?.firstLegMeters ?? 0)}m firstTurn=${Number.isFinite(candidate.assessment?.distanceToFirstTurnMeters) ? Math.round(candidate.assessment.distanceToFirstTurnMeters) : 'none'}m score=${Math.round(score)}${candidate.assessment?.valid ? '' : ` reject=${(candidate.assessment?.reasons || []).join(',')}`}`
        );
        return { ...candidate, score, turnCount, sharpTurnCount, preliminaryScore: score };
    };
    const buildCandidateDefs = (stage, phaseKey) => {
        if (phaseKey === 'fast') {
            return _pickFastRerouteCandidate(stage, {
                coords,
                projection,
                blockStart,
                blockEnd,
                destWp
            });
        }
        const candidateDefs = [];
        for (const side of [1, -1]) {
            for (const offsetM of stage.bypassOffsetsM) {
                const bypass = _perpendicularOffsetPoint(blockStart, blockEnd, offsetM, side);
                for (const rejoinOffsetM of stage.rejoinOffsetsM) {
                    const rejoin = _walkAlongRoute(coords, projection, BLOCK_AHEAD_END_METERS + rejoinOffsetM);
                    _pushUniqueBlockAheadCandidate(candidateDefs, {
                        phaseKey,
                        stage,
                        bypass,
                        rejoin,
                        offsetM,
                        rejoinOffsetM,
                        directToDestination: false,
                        side: side === 1 ? 'left' : 'right'
                    });
                }
                if (stage.allowDirectToDestination) {
                    _pushUniqueBlockAheadCandidate(candidateDefs, {
                        phaseKey,
                        stage,
                        bypass,
                        rejoin: null,
                        offsetM,
                        rejoinOffsetM: null,
                        directToDestination: true,
                        side: side === 1 ? 'left' : 'right'
                    });
                }
            }
        }
        if (Number.isFinite(stage.maxCandidates) && stage.maxCandidates > 0) {
            return candidateDefs.slice(0, stage.maxCandidates);
        }
        return candidateDefs;
    };
    const evaluateCandidates = async (candidateDefs, stage, stageMetric) => {
        const evalResults = await Promise.all(candidateDefs.map(async (c) => {
            const waypoints = c.directToDestination
                ? [startWp, blockStart, c.bypass, destWp]
                : [startWp, blockStart, c.bypass, c.rejoin, destWp];
            const route = await _fetchOsrmRouteForEval(waypoints);
            const corridorMetrics = route
                ? _candidateCorridorMetrics(route, originalRouteSnapshot, { bufMid, overlapRadius })
                : null;
            const assessment = route
                ? _assessBlockAheadRoute(route, {
                    baseRemainingDistance,
                    bufMid,
                    overlapRadius,
                    blockStart,
                    bypass: c.bypass,
                    rejoin: c.rejoin,
                    thresholds: { ...stage, rejectDangerousCrossings: false },
                    crossingAssessment: null,
                    corridorMetrics
                })
                : null;
            if (!route) {
                _noteBlockAheadRejectReason(stageMetric, 'fetch-failed');
            } else if (assessment && !assessment.valid) {
                (assessment.reasons || []).forEach(reason => _noteBlockAheadRejectReason(stageMetric, reason));
            }
            return { ...c, route, assessment, crossingAssessment: null, corridorMetrics };
        }));
        stageMetric.osrmEvaluated = evalResults.filter(r => r.route !== null).length;
        evalResults.forEach(r => {
            console.log(
                `[BlockAhead][eval][${stage.label}] ${r.side}/${r.offsetM}m/${r.directToDestination ? 'direct' : `rejoin+${r.rejoinOffsetM}`}:`,
                r.route ? `dist=${Math.round(r.route.totalDistance)}m pts=${r.route.coordinates.length}` : 'fetch failed'
            );
        });
        return evalResults
            .filter(r => r.route !== null)
            .map(r => scorePreliminaryCandidate(r, stage))
            .filter(r => r.assessment && r.assessment.valid)
            .sort((a, b) => a.score - b.score);
    };
    const tryScoredCandidates = async (scored, stage, stageMetric, options = {}) => {
        const finalTryLimit = options.finalTryLimit ?? scored.length;
        for (const candidate of scored.slice(0, finalTryLimit)) {
            stageMetric.finalTried += 1;
            if (_blockAheadSeq !== mySeq) {
                finalizeStale();
                return 'stale';
            }
            candidate.skipCrossingEvaluation = options.skipCrossingEvaluation === true;
            console.log(
                `[BlockAhead] trying [${stage.label}]: ${candidate.side}/${candidate.offsetM}m/${candidate.directToDestination ? 'direct' : `rejoin+${candidate.rejoinOffsetM}`} dist=${Math.round(candidate.route.totalDistance)}m score=${Math.round(candidate.score)}`
            );
            const result = await tryCandidate(candidate);
            if (result.status === 'success') {
                accepted = { candidate, result };
                return 'success';
            }
            if (result.status === 'no-change') {
                sawNoChange = true;
                _noteBlockAheadRejectReason(stageMetric, 'no-change');
            }
            if (result.status === 'stale') {
                finalizeStale();
                return 'stale';
            }
            _noteBlockAheadRejectReason(stageMetric, result.status === 'invalid-final'
                ? ((result.finalAssessment?.reasons || [])[0] || 'invalid-final')
                : result.status);
            console.warn(
                `[BlockAhead] rejected final route [${stage.label}]: ${candidate.side}/${candidate.offsetM}m/${candidate.directToDestination ? 'direct' : `rejoin+${candidate.rejoinOffsetM}`} (${result.status === 'no-change' ? 'no-change' : (result.finalAssessment?.reasons?.join(',') || result.status)})`
            );
        }
        return 'continue';
    };

    const fastPhaseStartedAt = _perfNowMs();
    const fastPhaseMetric = { key: 'fast', label: 'FAST_REROUTE', candidates: 0, osrmEvaluated: 0, shortlisted: 0, finalTried: 0, durationMs: 0 };
    _blockAheadPerfMetrics.phases.push(fastPhaseMetric);
    _blockAheadPerfMetrics.stages.push(fastPhaseMetric);
    const fastCandidates = buildCandidateDefs(BLOCK_FAST_REROUTE_CONFIG, 'fast');
    fastPhaseMetric.candidates = fastCandidates.length;
    console.log('[BlockAhead][FAST_REROUTE] candidates:', fastCandidates.map(c => `${c.side}/${c.offsetM}m/rejoin+${c.rejoinOffsetM}`));
    const fastPreliminary = await evaluateCandidates(fastCandidates, BLOCK_FAST_REROUTE_CONFIG, fastPhaseMetric);
    const fastScored = fastPreliminary.slice(0, BLOCK_FAST_REROUTE_CONFIG.maxCandidates);
    fastPhaseMetric.shortlisted = fastScored.length;
    const earlyAccept = fastScored.find(candidate => _isFastRerouteEarlyAcceptCandidate(candidate, BLOCK_FAST_REROUTE_CONFIG));
    const fastTryOrder = earlyAccept
        ? [earlyAccept, ...fastScored.filter(candidate => candidate !== earlyAccept)]
        : fastScored;
    const fastStatus = await tryScoredCandidates(fastTryOrder, BLOCK_FAST_REROUTE_CONFIG, fastPhaseMetric, {
        finalTryLimit: BLOCK_FAST_REROUTE_CONFIG.maxCandidates,
        skipCrossingEvaluation: true
    });
    fastPhaseMetric.durationMs = _perfNowMs() - fastPhaseStartedAt;
    if (fastStatus === 'stale') return;
    _blockAheadPerfMetrics.fast.accepted = fastStatus === 'success';
    _blockAheadPerfMetrics.fast.rejectReasons = fastPhaseMetric.rejectReasons || {};
    if (fastStatus === 'success') {
        _blockAheadPerfMetrics.phasePath.push('FAST_ACCEPT');
    } else {
        _blockAheadPerfMetrics.phasePath.push('FAST_REJECT');
        _blockAheadPerfMetrics.fast.rejectReason = _topBlockAheadRejectReason(fastPhaseMetric.rejectReasons) || (fastPreliminary.length === 0 ? 'no-valid-candidate' : 'needs-safe-refinement');
    }
    console.log(`[BlockAhead][timing][phase] FAST_REROUTE: ${Math.round(fastPhaseMetric.durationMs)}ms candidates=${fastPhaseMetric.candidates} osrm=${fastPhaseMetric.osrmEvaluated} shortlisted=${fastPhaseMetric.shortlisted} finalTried=${fastPhaseMetric.finalTried} earlyAccept=${Boolean(earlyAccept)}`);
    if (!accepted) {
        const safePhaseStartedAt = _perfNowMs();
        const safePhaseMetric = { key: 'safe-refinement', label: 'SAFE_REFINEMENT', candidates: 0, osrmEvaluated: 0, shortlisted: 0, finalTried: 0, durationMs: 0 };
        _blockAheadPerfMetrics.phases.push(safePhaseMetric);
        _blockAheadPerfMetrics.safe.attempted = true;
        for (const stage of BLOCK_REROUTE_STAGES) {
            const stageStartedAt = _perfNowMs();
            const stageMetric = { key: stage.key, label: stage.label, candidates: 0, osrmEvaluated: 0, shortlisted: 0, finalTried: 0, durationMs: 0 };
            _blockAheadPerfMetrics.stages.push(stageMetric);
            const candidateDefs = buildCandidateDefs(stage, 'safe');
            stageMetric.candidates = candidateDefs.length;
            safePhaseMetric.candidates += candidateDefs.length;
            console.log(`[BlockAhead][${stage.label}] candidates:`, candidateDefs.map(c => `${c.side}/${c.offsetM}m/${c.directToDestination ? 'direct' : `rejoin+${c.rejoinOffsetM}`}`));

            const preliminary = await evaluateCandidates(candidateDefs, stage, stageMetric);
            safePhaseMetric.osrmEvaluated += stageMetric.osrmEvaluated;
            Object.entries(stageMetric.rejectReasons || {}).forEach(([reason, count]) => {
                _blockAheadPerfMetrics.safe.rejectReasons[reason] = (_blockAheadPerfMetrics.safe.rejectReasons[reason] || 0) + count;
            });
            if (preliminary.length === 0) {
                stageMetric.durationMs = _perfNowMs() - stageStartedAt;
                console.warn(`[BlockAhead][${stage.label}] no valid candidates, trying next stage`);
                console.log(`[BlockAhead][timing][stage] ${stage.label}: ${Math.round(stageMetric.durationMs)}ms`);
                continue;
            }

            const shortlistLimit = BLOCK_REROUTE_STAGE_TOP_CANDIDATES[stage.key] || preliminary.length;
            const shortlisted = preliminary.slice(0, shortlistLimit);
            stageMetric.shortlisted = shortlisted.length;
            safePhaseMetric.shortlisted += shortlisted.length;
            await Promise.all(shortlisted.map(async (candidate) => {
                const crossingAssessment = await _assessRouteCrossingRisk(candidate.route, stage);
                candidate.crossingAssessment = crossingAssessment;
                candidate.assessment = _assessBlockAheadRoute(candidate.route, {
                    baseRemainingDistance,
                    bufMid,
                    overlapRadius,
                    blockStart,
                    bypass: candidate.bypass,
                    rejoin: candidate.rejoin,
                    thresholds: stage,
                    crossingAssessment,
                    corridorMetrics: candidate.corridorMetrics
                });
                candidate.score = candidate.preliminaryScore + ((crossingAssessment?.penalty || 0) * (stage.crossingPenaltyMultiplier || 1));
                console.log(
                    `[BlockAhead][score-final][${stage.label}] ${candidate.side}/${candidate.offsetM}m/${candidate.directToDestination ? 'direct' : `rejoin+${candidate.rejoinOffsetM}`}: crossingPenalty=${Math.round(crossingAssessment?.penalty || 0)} dangerousCrossings=${crossingAssessment?.dangerousCount || 0} score=${Math.round(candidate.score)}${candidate.assessment?.valid ? '' : ` reject=${(candidate.assessment?.reasons || []).join(',')}`}`
                );
            }));

            const scored = shortlisted
                .filter(r => r.assessment && r.assessment.valid)
                .sort((a, b) => a.score - b.score);

            if (scored.length === 0) {
                stageMetric.durationMs = _perfNowMs() - stageStartedAt;
                console.warn(`[BlockAhead][${stage.label}] no crossing-safe candidates, trying next stage`);
                console.log(`[BlockAhead][timing][stage] ${stage.label}: ${Math.round(stageMetric.durationMs)}ms`);
                continue;
            }

            const stageStatus = await tryScoredCandidates(scored, stage, stageMetric, {
                finalTryLimit: BLOCK_REROUTE_STAGE_MAX_FINAL_TRIES[stage.key] || scored.length,
                skipCrossingEvaluation: false
            });
            safePhaseMetric.finalTried += stageMetric.finalTried;
            Object.entries(stageMetric.rejectReasons || {}).forEach(([reason, count]) => {
                _blockAheadPerfMetrics.safe.rejectReasons[reason] = (_blockAheadPerfMetrics.safe.rejectReasons[reason] || 0) + count;
            });
            stageMetric.durationMs = _perfNowMs() - stageStartedAt;
            console.log(`[BlockAhead][timing][stage] ${stage.label}: ${Math.round(stageMetric.durationMs)}ms candidates=${stageMetric.candidates} osrm=${stageMetric.osrmEvaluated} shortlist=${stageMetric.shortlisted} finalTried=${stageMetric.finalTried}`);
            if (stageStatus === 'stale') return;
            if (accepted) break;
        }
        safePhaseMetric.durationMs = _perfNowMs() - safePhaseStartedAt;
        _blockAheadPerfMetrics.safe.accepted = Boolean(accepted);
        _blockAheadPerfMetrics.safe.rejectReason = _topBlockAheadRejectReason(_blockAheadPerfMetrics.safe.rejectReasons) || (accepted ? null : 'safe-no-valid-route');
        _blockAheadPerfMetrics.phasePath.push(accepted ? 'SAFE_ACCEPT' : 'SAFE_FAILED');
        console.log(`[BlockAhead][timing][phase] SAFE_REFINEMENT: ${Math.round(safePhaseMetric.durationMs)}ms candidates=${safePhaseMetric.candidates} osrm=${safePhaseMetric.osrmEvaluated} shortlist=${safePhaseMetric.shortlisted} finalTried=${safePhaseMetric.finalTried}`);
    }

    if (!accepted) {
        navBlockAheadInProgress = false;
        _restoreBlockAheadOriginalRoute(originalRouteSnapshot);
        _clearBlockAheadLayer();
        _updateNavUI();
        _showNavBanner(
            sawNoChange
                ? 'ℹ 現在のルートと実質同じ経路しか見つからなかったため、既存ルートを継続します。'
                : '⚠ 目的地まで到達できる迂回ルートが見つかりませんでした。現在のルートを継続します。',
            sawNoChange ? 'info' : 'danger',
            5000
        );
        if (sawNoChange) {
            _noteBlockAheadRejectReason(_blockAheadPerfMetrics.fast, 'no-change');
            if (_blockAheadPerfMetrics.safe.attempted) _noteBlockAheadRejectReason(_blockAheadPerfMetrics.safe, 'no-change');
        }
        const summary = finalizeExecution('failed');
        _blockAheadLastTiming = { ..._blockAheadPerfMetrics, ...summary, totalMs: summary.totalMs, status: 'failed' };
        console.log('[BlockAhead][timing][total]', _blockAheadLastTiming);
        _blockAheadPerfMetrics = null;
        return;
    }

    const { candidate, result } = accepted;
    const selectedBundle = _selectSingleRouteBundle(
        result.routes,
        result.selectedRouteIndex,
        result.routeColors,
        result.formatter,
        result.transportMode,
        `block-ahead-final:${candidate.phaseKey || candidate.stage?.key || 'unknown'}`
    );
    console.log(
        `[BlockAhead] best: ${candidate.side}/${candidate.offsetM}m/rejoin+${candidate.rejoinOffsetM} dist=${Math.round(candidate.route.totalDistance)}m overlap=${candidate.assessment.overlap.toFixed(2)} turns=${candidate.turnCount} sharp=${candidate.sharpTurnCount} dangerousCrossings=${candidate.crossingAssessment?.dangerousCount || 0} score=${Math.round(candidate.score)}`
    );

    navActiveRoute          = selectedBundle.routes[0];
    navActiveRoute.crossingRisk = result.crossingAssessment || candidate.crossingAssessment || null;
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
    const finalCrossingRisk = navActiveRoute.crossingRisk || null;
    if ((finalCrossingRisk?.dangerousCount || 0) > 0 || (finalCrossingRisk?.uncontrolledCount || 0) > 0) {
        _showNavBanner(`⚠ 迂回ルートに切り替えました。${finalCrossingRisk.warningText || '大きな道路の横断に注意してください。'}`, 'warning', 6500);
    } else {
        _showNavBanner('✅ 迂回ルートに切り替えました。このまま避難を続けてください。', 'success', 5000);
    }
    if (typeof voiceNav !== 'undefined') {
        voiceNav.announce({
            id: 'block-ahead-reroute',
            text: '前方を迂回するルートに切り替えました',
            category: 'start',
            priority: 'high'
        });
        if ((finalCrossingRisk?.dangerousCount || 0) > 0 || (finalCrossingRisk?.uncontrolledCount || 0) > 0) {
            voiceNav.announce({
                id: 'block-ahead-crossing-warning',
                text: finalCrossingRisk.warningText || '途中の大きな道路横断に注意してください',
                category: 'warning',
                priority: 'high'
            });
        }
    }
    console.log('[BlockAhead] reroute success seq=' + mySeq);
    if (!_blockAheadPerfMetrics.safe.attempted) {
        _blockAheadPerfMetrics.phasePath = ['FAST_ACCEPT'];
    }
    if (_blockAheadPerfMetrics.safe.attempted && accepted?.candidate?.stage?.key) {
        _blockAheadPerfMetrics.safe.accepted = true;
        _noteBlockAheadRejectReason(_blockAheadPerfMetrics.safe, `accepted:${accepted.candidate.stage.key}`);
    }
    const summary = finalizeExecution('success', { acceptedStage: accepted?.candidate?.stage?.key || 'fast' });
    _blockAheadLastTiming = { ..._blockAheadPerfMetrics, ...summary, totalMs: summary.totalMs, status: 'success' };
    console.log('[BlockAhead][timing][total]', _blockAheadLastTiming);
    _blockAheadPerfMetrics = null;
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

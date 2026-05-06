/**
 * route-risk-outline.js — ルート危険区間アウトライン表示
 *
 * ルート座標列と /api/route-risk の sampled_points を受け取り、
 * 危険区間（赤）・注意区間（黄）のアウトラインを Leaflet polyline として描画する。
 *
 * 依存: map, L (Leaflet) — state.js / index.html でグローバルに公開済み
 */

// ── 定数 ────────────────────────────────────────────────────────────────────

const ROUTE_RISK_PREVIEW_M  = 30;  // 危険区間手前の注意バッファ (m)
const ROUTE_RISK_RECOVERY_M = 15;  // 危険区間直後の注意バッファ (m)

const ROUTE_RISK_OUTLINE = {
    caution: { color: '#facc15', weightOffset: 8, opacity: 0.90 },
    danger:  { color: '#ef4444', weightOffset: 9, opacity: 0.95 },
};

// danger 扱いにするハザードタイプ（lowland_poor_drainage は caution 扱い）
const _DANGER_HAZARDS = new Set([
    'flood', 'tsunami', 'storm_surge', 'landslide',
    'inland_flood', 'pseudo_inland_flood',
]);

// ── Leaflet ペイン ──────────────────────────────────────────────────────────

let _riskPanesReady = false;

function _ensureRiskPanes() {
    if (_riskPanesReady || !map) return;
    try {
        if (!map.getPane('routeRiskDanger')) {
            map.createPane('routeRiskDanger');
            map.getPane('routeRiskDanger').style.zIndex = '397';
        }
        if (!map.getPane('routeRiskCaution')) {
            map.createPane('routeRiskCaution');
            map.getPane('routeRiskCaution').style.zIndex = '398';
        }
        _riskPanesReady = true;
    } catch (e) {
        console.warn('[route-risk-outline] pane init failed:', e);
    }
}

// ── レイヤー管理 ────────────────────────────────────────────────────────────

let _riskOutlineLayers = [];

function clearRouteRiskOutlines() {
    _riskOutlineLayers.forEach(layer => {
        if (layer && map && map.hasLayer(layer)) map.removeLayer(layer);
    });
    _riskOutlineLayers = [];
}

// ── ユーティリティ ─────────────────────────────────────────────────────────

function _haversineM(a, b) {
    const R = 6371000;
    const lat1 = a.lat * Math.PI / 180;
    const lat2 = b.lat * Math.PI / 180;
    const dLat = (b.lat - a.lat) * Math.PI / 180;
    const dLon = ((b.lng ?? b.lon ?? 0) - (a.lng ?? a.lon ?? 0)) * Math.PI / 180;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(Math.min(1, h)));
}

function _pointRiskState(hazards) {
    if (!hazards) return 'normal';
    for (const h of _DANGER_HAZARDS) {
        if (hazards[h] === 'inside') return 'danger';
    }
    if (hazards.lowland_poor_drainage === 'inside') return 'caution';
    return 'normal';
}

function _routeRiskDebugEnabled() {
    if (typeof getRuntimeConfigValue !== 'function') return false;
    const level = String(getRuntimeConfigValue('logging.level', 'INFO') || 'INFO').toUpperCase();
    return level === 'DEBUG';
}

// ── セグメント生成 ──────────────────────────────────────────────────────────

/**
 * ルート座標列とサンプリング済みハザードデータからリスクセグメントを生成する。
 *
 * @param {Array<{lat, lng|lon}>} routeCoords  - OSRM ルート座標列
 * @param {Array<{lat, lon, hazards}>} sampledPoints - API の sampled_points
 * @returns {Array<{coords, riskState, startDistanceM, endDistanceM}>}
 */
function buildRouteRiskSegments(routeCoords, sampledPoints) {
    if (!Array.isArray(routeCoords) || routeCoords.length < 2) return [];
    if (!Array.isArray(sampledPoints) || sampledPoints.length === 0) return [];

    const n = routeCoords.length;

    // 1. 各サンプル点を最近傍ルート座標インデックスにスナップ（L2 近似）
    const sampleIndices = sampledPoints.map(sp => {
        const spLat = Number(sp.lat);
        const spLon = Number(sp.lon ?? sp.lng ?? 0);
        let minSq = Infinity, minIdx = 0;
        for (let i = 0; i < n; i++) {
            const c = routeCoords[i];
            const dLat = spLat - Number(c.lat);
            const dLon = spLon - Number(c.lng ?? c.lon ?? 0);
            const sq = dLat * dLat + dLon * dLon;
            if (sq < minSq) { minSq = sq; minIdx = i; }
        }
        return minIdx;
    });

    // 2. 各ルート座標にハザード状態を割り当て（Voronoi 分割）
    const coordStates = new Array(n).fill('normal');
    const sorted = sampledPoints
        .map((sp, i) => ({ state: _pointRiskState(sp.hazards), idx: sampleIndices[i] }))
        .sort((a, b) => a.idx - b.idx);

    if (sorted.length > 0) {
        // 先頭ブロック
        for (let i = 0; i <= sorted[0].idx; i++) coordStates[i] = sorted[0].state;

        // 中間ブロック（前後サンプル間の中間インデックスで切り替え）
        for (let k = 1; k < sorted.length; k++) {
            const prev = sorted[k - 1];
            const curr = sorted[k];
            const mid  = Math.floor((prev.idx + curr.idx) / 2);
            for (let i = prev.idx; i <= mid; i++)      coordStates[i] = prev.state;
            for (let i = mid + 1; i <= curr.idx; i++) coordStates[i] = curr.state;
        }

        // 末尾ブロック
        const last = sorted[sorted.length - 1];
        for (let i = last.idx; i < n; i++) coordStates[i] = last.state;
    }

    // 3. 累積距離
    const cumDist = new Array(n);
    cumDist[0] = 0;
    for (let i = 1; i < n; i++) {
        cumDist[i] = cumDist[i - 1] + _haversineM(routeCoords[i - 1], routeCoords[i]);
    }

    // 4. danger 前後に caution バッファを展開（original状態を基準に拡張）
    const expanded = coordStates.slice();

    // 前方バッファ: danger 開始点の ROUTE_RISK_PREVIEW_M 手前を caution に
    for (let i = 1; i < n; i++) {
        if (coordStates[i] === 'danger' && coordStates[i - 1] !== 'danger') {
            const dangerDist = cumDist[i];
            for (let j = i - 1; j >= 0; j--) {
                if (dangerDist - cumDist[j] > ROUTE_RISK_PREVIEW_M) break;
                if (expanded[j] === 'normal') expanded[j] = 'caution';
            }
        }
    }

    // 後方バッファ: danger 終了点の ROUTE_RISK_RECOVERY_M 後ろを caution に
    for (let i = n - 2; i >= 0; i--) {
        if (coordStates[i] === 'danger' && coordStates[i + 1] !== 'danger') {
            const endDist = cumDist[i];
            for (let j = i + 1; j < n; j++) {
                if (cumDist[j] - endDist > ROUTE_RISK_RECOVERY_M) break;
                if (expanded[j] === 'normal') expanded[j] = 'caution';
            }
        }
    }

    // 5. 連続状態ごとにセグメント化
    const segments = [];
    let segStart = 0;
    for (let i = 1; i < n; i++) {
        if (expanded[i] !== expanded[segStart]) {
            if (expanded[segStart] !== 'normal') {
                segments.push({
                    coords: routeCoords.slice(segStart, i + 1).map(c => [Number(c.lat), Number(c.lng ?? c.lon ?? 0)]),
                    riskState: expanded[segStart],
                    startDistanceM: Math.round(cumDist[segStart]),
                    endDistanceM:   Math.round(cumDist[i]),
                });
            }
            segStart = i;
        }
    }
    if (segStart < n - 1 && expanded[segStart] !== 'normal') {
        segments.push({
            coords: routeCoords.slice(segStart).map(c => [Number(c.lat), Number(c.lng ?? c.lon ?? 0)]),
            riskState: expanded[segStart],
            startDistanceM: Math.round(cumDist[segStart]),
            endDistanceM:   Math.round(cumDist[n - 1]),
        });
    }

    return segments;
}

// ── 描画 ────────────────────────────────────────────────────────────────────

/**
 * 選択中ルートの危険区間アウトラインを描画する。
 *
 * @param {Array<{lat, lng|lon}>} routeCoords
 * @param {Array<{lat, lon, hazards}>} sampledPoints
 * @param {number} baseWeight - ルート本体の weight（アウトライン幅の基準）
 */
function drawRouteRiskOutlines(routeCoords, sampledPoints, baseWeight) {
    clearRouteRiskOutlines();

    if (!routeCoords || !sampledPoints) return;
    if (!Array.isArray(routeCoords) || routeCoords.length < 2) return;
    if (!Array.isArray(sampledPoints) || sampledPoints.length === 0) return;

    _ensureRiskPanes();

    const segments = buildRouteRiskSegments(routeCoords, sampledPoints);
    const dangerSegs  = segments.filter(s => s.riskState === 'danger');
    const cautionSegs = segments.filter(s => s.riskState === 'caution');

    if (_routeRiskDebugEnabled()) {
        console.debug('[route-risk-outline]', {
            segmentCount:       segments.length,
            dangerSegmentCount: dangerSegs.length,
            cautionSegmentCount: cautionSegs.length,
        });
    }

    if (segments.length === 0) return;

    const bw = Number(baseWeight) || 7;

    // danger を先に描画（routeRiskDanger pane = zIndex 397、ルート本体より下）
    dangerSegs.forEach(seg => {
        const s = ROUTE_RISK_OUTLINE.danger;
        const layer = L.polyline(seg.coords, {
            pane: 'routeRiskDanger',
            color: s.color,
            weight: bw + s.weightOffset,
            opacity: s.opacity,
            lineCap: 'round',
            lineJoin: 'round',
            interactive: false,
        }).addTo(map);
        _riskOutlineLayers.push(layer);
    });

    // caution を上に描画（routeRiskCaution pane = zIndex 398）
    cautionSegs.forEach(seg => {
        const s = ROUTE_RISK_OUTLINE.caution;
        const layer = L.polyline(seg.coords, {
            pane: 'routeRiskCaution',
            color: s.color,
            weight: bw + s.weightOffset,
            opacity: s.opacity,
            lineCap: 'round',
            lineJoin: 'round',
            interactive: false,
        }).addTo(map);
        _riskOutlineLayers.push(layer);
    });
}

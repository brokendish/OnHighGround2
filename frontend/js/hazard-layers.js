/**
 * hazard-layers.js — ハザードレイヤー管理
 *
 * - HAZARD_LAYERS: GeoJSON / Vector Tile レイヤー定義
 * - VECTOR_TILE_SOURCES: Martin タイルセット定義
 * - レイヤーの読み込み・表示切り替え・カラースタイリング
 * - ハザードチェックボックスの初期化
 */

// ── ハザードレイヤー定義 ──────────────────────────────────────────────────
// [Phase 1] path は /hazard/ からの GeoJSON フォールバック（legacy 配信）。
// [Phase 2] LAYER_BASE_PATH を '/layers' に切替済み。frontend/layers/ が公式配置先。
// primary 配信は Martin vector tiles (/tiles/)。GeoJSON はフォールバック。
const HAZARD_LAYERS = {
    tsunami_tokyo: {
        name: "津波浸水想定（東京都）",
        apiUrl: '/api/hazards/tsunami/tokyo',
        metaUrl: '/api/hazards/tsunami/tokyo/meta',
        path: `${LAYER_BASE_PATH}/tsunami_tokyo.geojson`,
        checkboxId: "showTsunamiHazardTokyo",
        layer: null,
        loaded: false,
        visible: false,
        rawData: null,
        lastError: null,
        type: 'tsunami'
    },
    tsunami_kanagawa: {
        name: "津波浸水想定（神奈川県）",
        path: `${LAYER_BASE_PATH}/tsunami_kanagawa.geojson`,
        checkboxId: "showTsunamiHazardKanagawa",
        layer: null,
        loaded: false,
        visible: false,
        rawData: null,
        lastError: null,
        type: 'tsunami'
    },
    tsunami_chiba: {
        name: "津波浸水想定（千葉県）",
        path: `${LAYER_BASE_PATH}/tsunami_chiba.geojson`,
        checkboxId: "showTsunamiHazardChiba",
        layer: null,
        loaded: false,
        visible: false,
        rawData: null,
        lastError: null,
        type: 'tsunami'
    },
    flood_tokyo_max: {
        name: "洪水浸水想定（東京都・想定最大規模）",
        apiUrl: '/api/hazards/flood/tokyo',
        metaUrl: '/api/hazards/flood/tokyo/meta',
        path: `${LAYER_BASE_PATH}/tokyo_flood_max.geojson`,
        checkboxId: "showFloodTokyoMax",
        layer: null,
        loaded: false,
        visible: false,
        rawData: null,
        lastError: null,
        type: 'flood'
    },
    storm_surge_tokyo: {
        name: "高潮浸水想定（東京都）",
        apiUrl: '/api/hazards/storm_surge/tokyo',
        metaUrl: '/api/hazards/storm_surge/tokyo/meta',
        path: `${LAYER_BASE_PATH}/tokyo_storm_surge.geojson`,
        checkboxId: "showStormSurgeTokyo",
        layer: null,
        loaded: false,
        visible: false,
        rawData: null,
        lastError: null,
        type: 'storm_surge'
    },
    inland_flood_tokyo: {
        name: "内水氾濫（東京都）",
        path: `${LAYER_BASE_PATH}/inland_flood_tokyo.geojson`,
        checkboxId: "showInlandFloodTokyo",
        layer: null,
        loaded: false,
        visible: false,
        rawData: null,
        lastError: null,
        type: 'inland_flood'
    },
    landslide_tokyo: {
        name: "土砂災害（東京都）",
        apiUrl: '/api/hazards/landslide/tokyo',
        metaUrl: '/api/hazards/landslide/tokyo/meta',
        path: `${LAYER_BASE_PATH}/landslide_tokyo.geojson`,
        checkboxId: "showLandslideTokyo",
        layer: null,
        loaded: false,
        visible: false,
        rawData: null,
        lastError: null,
        type: 'landslide'
    }
};

// ── カラー定数（VECTOR_TILE_SOURCES の colorFn / borderStyle から参照するため先に定義）────
const FLOOD_RANK_COLORS = { 1: '#ffe082', 2: '#ffca28', 3: '#ff8f00', 4: '#f4511e', 5: '#b71c1c' };
const FLOOD_UNKNOWN_COLOR = '#ffe0b2';
function getFloodRankColor(rank) { return FLOOD_RANK_COLORS[rank] || FLOOD_UNKNOWN_COLOR; }
const FLOOD_BORDER = { color: '#b71c1c', weight: 0.4, opacity: 0.35, dashArray: '4,4' };
const STORM_SURGE_RANK_COLORS = {
    1: '#b3e5fc', 2: '#4fc3f7', 3: '#0288d1', 4: '#01579b',
    5: '#7b1fa2', 6: '#4a148c', 7: '#1a0033',
};
const STORM_SURGE_UNKNOWN_COLOR = '#e1f5fe';
const STORM_SURGE_BORDER = { color: '#01579b', weight: 0.4, opacity: 0.35, dashArray: '4,4' };

// ── Martin ベクタータイルソース定義 ──────────────────────────────────────
// キー: HAZARD_LAYERS と同じ
// source-layer 名は tippecanoe の --layer オプションで指定した名前（= MBTiles ファイル名の stem）
const VECTOR_TILE_SOURCES = {
    tsunami_tokyo: [
        { tilesetId: 'tokyo_tsunami_A40-23_13', sourceLayer: 'tokyo_tsunami_A40-23_13' }
    ],
    tsunami_kanagawa: [
        { tilesetId: 'kanagawa_tsunami_A40-16_14', sourceLayer: 'kanagawa_tsunami_A40-16_14' },
        { tilesetId: 'kanagawa_tsunami_A40-20_14', sourceLayer: 'kanagawa_tsunami_A40-20_14' }
    ],
    tsunami_chiba: [
        { tilesetId: 'chiba_tsunami_A40-18_12', sourceLayer: 'chiba_tsunami_A40-18_12' }
    ],
    flood_tokyo_max: [
        {
            tilesetId: 'tokyo_flood_max',
            sourceLayer: 'tokyo_flood_max',
            colorFn: (props) => getFloodRankColor(props['A31a_205']),
            borderStyle: FLOOD_BORDER,
            maxNativeZoom: 16
        }
    ],
    storm_surge_tokyo: [
        {
            tilesetId: 'tokyo_storm_surge',
            sourceLayer: 'tokyo_storm_surge',
            colorFn: (props) => STORM_SURGE_RANK_COLORS[props['storm_surge_rank']] || STORM_SURGE_UNKNOWN_COLOR,
            borderStyle: STORM_SURGE_BORDER,
            maxNativeZoom: 16
        }
    ]
};

let useMartinTiles = false;
const DEBUG_HAZARD_LAYERS = false;

function debugHazardLayer(stage, layerKey, payload = {}) {
    if (!DEBUG_HAZARD_LAYERS) {
        return;
    }
    console.info(`[hazard:${stage}] ${layerKey}`, payload);
}

function shouldUseVectorTiles(layerKey, hazard) {
    if (!useMartinTiles || !VECTOR_TILE_SOURCES[layerKey]) {
        return false;
    }

    // flood / storm_surge は Martin タイル優先。タイルが存在しない場合は
    // _vectorTilesUnavailable フラグで API フォールバックに切り替える。
    if (hazard?._vectorTilesUnavailable) {
        return false;
    }

    return layerKey === 'flood_tokyo_max' || layerKey === 'storm_surge_tokyo' || !hazard?.apiUrl;
}

// ── GeoJSON 正規化 ────────────────────────────────────────────────────────

function normalizeToFeatureCollection(geojson) {
    if (!geojson || typeof geojson !== 'object') {
        return { type: 'FeatureCollection', features: [] };
    }

    if (geojson.type === 'FeatureCollection') {
        return {
            type: 'FeatureCollection',
            features: Array.isArray(geojson.features) ? geojson.features : []
        };
    }

    if (geojson.type === 'Feature') {
        return { type: 'FeatureCollection', features: [geojson] };
    }

    if (Array.isArray(geojson.features)) {
        return { type: 'FeatureCollection', features: geojson.features };
    }

    if (Array.isArray(geojson)) {
        return { type: 'FeatureCollection', features: geojson };
    }

    if (geojson.type && geojson.coordinates) {
        return {
            type: 'FeatureCollection',
            features: [{ type: 'Feature', geometry: geojson, properties: {} }]
        };
    }

    return { type: 'FeatureCollection', features: [] };
}

// ── 浸水深プロパティキー検出 ──────────────────────────────────────────────

function detectDepthPropertyKey(featureCollection) {
    const sampleFeatures = (featureCollection.features || [])
        .filter((feature) => feature && feature.properties && typeof feature.properties === 'object')
        .slice(0, 40);
    if (sampleFeatures.length === 0) {
        return null;
    }

    const keys = Object.keys(sampleFeatures[0].properties || {});
    const preferredTokens = ['depth', '浸水', '水深', 'rank', 'level', 'a40_003'];
    let bestKey = null;
    let bestScore = -1;

    for (const key of keys) {
        let score = 0;
        const keyLower = key.toLowerCase();

        preferredTokens.forEach((token, index) => {
            if (keyLower.includes(token.toLowerCase())) {
                score += 20 - index;
            }
        });

        if (/a40_\d{3}/i.test(key)) {
            score += 8;
        }

        let parseableCount = 0;
        sampleFeatures.forEach((feature) => {
            if (parseDepthValue(feature.properties[key]) !== null) {
                parseableCount += 1;
            }
        });
        score += parseableCount;

        if (score > bestScore) {
            bestScore = score;
            bestKey = key;
        }
    }

    return bestScore > 0 ? bestKey : null;
}

function parseDepthValue(rawValue) {
    if (typeof rawValue === 'number' && Number.isFinite(rawValue)) {
        return rawValue;
    }
    if (typeof rawValue === 'string') {
        const match = rawValue.match(/-?\d+(?:\.\d+)?/);
        if (!match) {
            return null;
        }
        const parsed = Number.parseFloat(match[0]);
        return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
}

// ── カラースタイル定義 ────────────────────────────────────────────────────

function getDepthColor(depthMeters) {
    if (depthMeters <= 0.5) return '#ffe082';
    if (depthMeters <= 1.0) return '#ffca28';
    if (depthMeters <= 3.0) return '#ff8f00';
    if (depthMeters <= 5.0) return '#f4511e';
    return '#b71c1c';
}

// 内水氾濫スタイル（深度ベース青系グラデーション）
// level: safe → caution → danger → critical
const INLAND_FLOOD_BORDER = {
    color: '#0277bd',
    weight: 0.4,
    opacity: 0.35,
    dashArray: '4,4'
};

function getInlandFloodDepthColor(depthM) {
    if (depthM >= 3.0) return '#b71c1c';   // critical — 濃赤（3m以上）
    if (depthM >= 1.0) return '#f4511e';   // danger   — オレンジ（1〜3m）
    if (depthM > 0)    return '#29b6f6';   // caution  — 水色（0〜1m）
    return '#b3e5fc';                      // safe/不明 — 薄水色
}

function getInlandFloodFeatureStyle(feature) {
    const depthM = feature?.properties?.depth_min_m ?? feature?.properties?.depth ?? 0;
    return {
        ...INLAND_FLOOD_BORDER,
        fillColor: getInlandFloodDepthColor(depthM),
        fillOpacity: 0.45
    };
}

// 土砂災害スタイル（茶色系）
const LANDSLIDE_BORDER = {
    color: '#6d4c41',
    weight: 0.4,
    opacity: 0.35,
    dashArray: '4,4'
};

function getLandslideFeatureStyle(feature) {
    // 特別警戒区域は濃い色、警戒区域は薄い色
    const zoneType = feature?.properties?.zone_type || feature?.properties?.区分 || '';
    const isSpecial = zoneType.includes('特別');
    return {
        ...LANDSLIDE_BORDER,
        fillColor: isSpecial ? '#bf360c' : '#a1887f',
        fillOpacity: 0.45
    };
}

function getStormSurgeFeatureStyle(feature) {
    const rank = feature?.properties?.['storm_surge_rank'];
    const fillColor = STORM_SURGE_RANK_COLORS[rank] || STORM_SURGE_UNKNOWN_COLOR;
    return {
        ...STORM_SURGE_BORDER,
        fillColor,
        fillOpacity: 0.38
    };
}

function getFloodFeatureStyle(feature) {
    const rank = feature?.properties?.['A31a_205'];
    const fillColor = getFloodRankColor(rank);
    return {
        ...FLOOD_BORDER,
        fillColor,
        fillOpacity: 0.38
    };
}

function getTsunamiFeatureStyle(feature, depthKey) {
    const defaultStyle = {
        color: '#1565c0',
        weight: 0.4,
        opacity: 0.35,
        dashArray: '4,4',
        fillColor: '#42a5f5',
        fillOpacity: 0.32
    };

    if (!depthKey) {
        return defaultStyle;
    }

    const rawValue = feature?.properties?.[depthKey];
    const depthMeters = parseDepthValue(rawValue);
    if (depthMeters === null) {
        return defaultStyle;
    }

    return {
        color: '#1565c0',
        weight: 0.4,
        opacity: 0.35,
        dashArray: '4,4',
        fillColor: getDepthColor(depthMeters),
        fillOpacity: 0.38
    };
}

// ── Martin ベクタータイル ─────────────────────────────────────────────────

async function checkMartinAvailable() {
    try {
        const response = await fetch('/tiles/catalog', { cache: 'no-cache' });
        return response.ok;
    } catch {
        return false;
    }
}

// Martin ベクタータイル用の L.vectorGrid.protobuf レイヤーを生成する
// colorFn: (properties) => colorString  省略時は津波デフォルト（深度テキスト解析）
function createVectorTileLayer(tilesetId, sourceLayer, colorFn, borderStyle, maxNativeZoom = 14) {
    const url = `/tiles/${tilesetId}/{z}/{x}/{y}`;
    const depthKeys = ['a40_003', 'A40_003', 'depth', 'rank', 'level'];
    const border = borderStyle || FLOOD_BORDER;
    return L.vectorGrid.protobuf(url, {
        vectorTileLayerStyles: {
            [sourceLayer]: function(properties) {
                let depthColor;
                if (colorFn) {
                    depthColor = colorFn(properties);
                } else {
                    depthColor = FLOOD_UNKNOWN_COLOR;
                    for (const key of depthKeys) {
                        const val = parseDepthValue(properties[key]);
                        if (val !== null) {
                            depthColor = getDepthColor(val);
                            break;
                        }
                    }
                }
                return {
                    fill: true,
                    fillColor: depthColor,
                    fillOpacity: 0.38,
                    weight: border.weight,
                    color: border.color,
                    opacity: border.opacity,
                    dashArray: border.dashArray
                };
            }
        },
        interactive: false,
        maxNativeZoom  // 指定ズームまでタイル取得し、それ以上はオーバーズーム描画
    });
}

// ── レイヤー読み込み・表示 ────────────────────────────────────────────────

async function loadHazardLayer(layerKey) {
    const hazard = HAZARD_LAYERS[layerKey];
    if (!hazard) {
        throw new Error(`未知のハザードレイヤーです: ${layerKey}`);
    }
    debugHazardLayer('load:start', layerKey, {
        hasLayer: Boolean(hazard.layer),
        loaded: hazard.loaded,
        apiUrl: hazard.apiUrl || null,
        path: hazard.path || null,
        useMartinTiles,
        prefersVectorTiles: shouldUseVectorTiles(layerKey, hazard),
    });
    if (hazard.layer) {
        return hazard.layer;
    }

    if (shouldUseVectorTiles(layerKey, hazard)) {
        const vtLayers = VECTOR_TILE_SOURCES[layerKey].map(({ tilesetId, sourceLayer, colorFn, borderStyle, maxNativeZoom }) =>
            createVectorTileLayer(tilesetId, sourceLayer, colorFn, borderStyle, maxNativeZoom)
        );
        hazard.layer = L.layerGroup(vtLayers);
        hazard.loaded = true;
        return hazard.layer;
    }

    const response = hazard.apiUrl
        ? await apiFetch(hazard.apiUrl, { cache: 'no-cache' })
        : await fetch(hazard.path, { cache: 'no-cache' });
    if (!response.ok) {
        hazard.lastError = `${hazard.name}データの取得に失敗しました (HTTP ${response.status})`;
        throw new Error(hazard.lastError);
    }

    const rawGeoJson = await response.json();
    const featureCollection = normalizeToFeatureCollection(rawGeoJson);
    const depthKey = detectDepthPropertyKey(featureCollection);
    hazard.rawData = featureCollection;
    hazard.lastError = null;
    const styleFn = hazard.type === 'flood'
        ? (feature) => getFloodFeatureStyle(feature)
        : hazard.type === 'storm_surge'
        ? (feature) => getStormSurgeFeatureStyle(feature)
        : hazard.type === 'inland_flood'
        ? (feature) => getInlandFloodFeatureStyle(feature)
        : hazard.type === 'landslide'
        ? (feature) => getLandslideFeatureStyle(feature)
        : (feature) => getTsunamiFeatureStyle(feature, depthKey);
    hazard.layer = L.geoJSON(featureCollection, {
        style: styleFn
    });
    hazard.loaded = true;
    return hazard.layer;
}

async function setHazardLayerVisibility(layerKey, visible) {
    const hazard = HAZARD_LAYERS[layerKey];
    if (!hazard) {
        return;
    }
    hazard.visible = visible;

    if (!visible) {
        if (hazard.layer && map.hasLayer(hazard.layer)) {
            map.removeLayer(hazard.layer);
        }
        updateHazardStatusSummary();
        return;
    }

    const layer = await loadHazardLayer(layerKey);
    if (!layer || typeof layer.addTo !== 'function') {
        throw new Error(`${hazard.name}レイヤーの生成結果が Leaflet Layer ではありません`);
    }
    if (!map.hasLayer(layer)) {
        layer.addTo(map);
    }
    if (typeof layer.bringToFront === 'function') {
        layer.bringToFront();
    }
    updateHazardStatusSummary();
}

// ── データ存在確認・チェックボックス初期化 ───────────────────────────────

async function hazardDataExists(hazard) {
    try {
        const response = hazard.metaUrl
            ? await apiFetch(hazard.metaUrl, { cache: 'no-cache' })
            : await fetch(hazard.path, { method: 'HEAD', cache: 'no-cache' });
        if (!response.ok) {
            hazard.lastError = `${hazard.name}データの存在確認に失敗しました (HTTP ${response.status})`;
            console.warn(hazard.lastError);
            return false;
        }
        hazard.lastError = null;
        return response.ok;
    } catch (error) {
        hazard.lastError = `${hazard.name}データの存在確認に失敗しました`;
        console.warn('ハザードデータ存在確認に失敗:', hazard.apiUrl || hazard.path, error);
        return false;
    }
}

function attachHazardToggle(checkbox, layerKey) {
    if (checkbox.dataset.hazardToggleBound === 'true') {
        return;
    }
    checkbox.dataset.hazardToggleBound = 'true';
    checkbox.addEventListener('change', async (event) => {
        try {
            await setHazardLayerVisibility(layerKey, event.target.checked);
        } catch (error) {
            console.error(`${HAZARD_LAYERS[layerKey].name}レイヤーの処理エラー:`, error);
            alert(`${HAZARD_LAYERS[layerKey].name}の表示に失敗しました: ${error.message}`);
            event.target.checked = false;
            HAZARD_LAYERS[layerKey].visible = false;
        }
    });
}

async function initializeHazardToggles() {
    useMartinTiles = await checkMartinAvailable();
    console.info('Martin タイルサーバー:', useMartinTiles ? '利用可能（ベクタータイル使用）' : '利用不可（GeoJSON フォールバック）');

    const availabilityChecks = await Promise.all(
        Object.entries(HAZARD_LAYERS).map(async ([layerKey, hazard]) => {
            const checkbox = document.getElementById(hazard.checkboxId);
            if (!checkbox) {
                return { layerKey, enabled: false, reason: 'checkbox-not-found' };
            }
            attachHazardToggle(checkbox, layerKey);

            if (shouldUseVectorTiles(layerKey, hazard)) {
                const firstTileset = VECTOR_TILE_SOURCES[layerKey][0];
                const checkPath = `/tiles/${firstTileset.tilesetId}`;
                const tilesExist = await hazardDataExists({ ...hazard, path: checkPath, metaUrl: null, apiUrl: null });
                if (!tilesExist) {
                    if (hazard.apiUrl) {
                        // タイルが未整備 → API フォールバックで有効化
                        hazard._vectorTilesUnavailable = true;
                        console.info(`[hazard:init] ${layerKey}: tiles not found, falling back to API`);
                        checkbox.disabled = false;
                        checkbox.title = '';
                        return { layerKey, enabled: true, reason: 'vector-tiles-fallback-to-api' };
                    }
                    checkbox.disabled = true;
                    checkbox.checked = false;
                    checkbox.title = `${checkPath} が見つかりません`;
                    return { layerKey, enabled: false, reason: 'tiles-not-found' };
                }

                checkbox.disabled = false;
                checkbox.title = '';
                return { layerKey, enabled: true, reason: 'vector-tiles' };
            }

            // API 配信レイヤーは起動時の事前確認で無効化しない。
            // 実際の読込失敗はチェック時に処理し、UI を触れる状態に保つ。
            if (hazard.apiUrl) {
                checkbox.disabled = false;
                checkbox.title = '';
                return { layerKey, enabled: true, reason: 'api-backed' };
            }

            const exists = await hazardDataExists(hazard);
            if (!exists) {
                checkbox.disabled = true;
                checkbox.checked = false;
                checkbox.title = hazard.lastError || `${hazard.path} が見つかりません`;
                return { layerKey, enabled: false, reason: 'data-not-found' };
            }

            checkbox.disabled = false;
            checkbox.title = '';
            return { layerKey, enabled: true, reason: 'ok' };
        })
    );

    const enabledLayers = availabilityChecks.filter((item) => item.enabled);
    if (DEBUG_HAZARD_LAYERS) {
        console.info('[hazard:init] availability check results:', availabilityChecks);
        console.info('[hazard:init] enabled layers:', enabledLayers.map((x) => `${x.layerKey}(${x.reason})`));
    }
    updateHazardStatusSummary();
    if (enabledLayers.length === 0) {
        return;
    }
}

function updateHazardStatusSummary() {
    const tsunamiVisible = Object.values(HAZARD_LAYERS)
        .filter((h) => h.type === 'tsunami' && h.visible)
        .map((h) => h.name);
    const floodVisible = Object.values(HAZARD_LAYERS)
        .filter((h) => h.type === 'flood' && h.visible)
        .map((h) => h.name);

    const tsunamiLegend = document.getElementById('hazardLegend');
    if (tsunamiVisible.length === 0) {
        setHazardStatus('津波浸水想定レイヤー: OFF');
        if (tsunamiLegend) tsunamiLegend.style.display = 'none';
    } else {
        setHazardStatus(`津波浸水想定レイヤー: ON（${tsunamiVisible.join(' / ')}）`);
        if (tsunamiLegend) tsunamiLegend.style.display = 'block';
    }

    const floodLegend = document.getElementById('floodLegend');
    if (floodVisible.length === 0) {
        setFloodStatus('洪水浸水想定レイヤー: OFF');
        if (floodLegend) floodLegend.style.display = 'none';
    } else {
        setFloodStatus(`洪水浸水想定レイヤー: ON（${floodVisible.join(' / ')}）`);
        if (floodLegend) floodLegend.style.display = 'block';
    }

    const stormSurgeVisible = Object.values(HAZARD_LAYERS)
        .filter((h) => h.type === 'storm_surge' && h.visible)
        .map((h) => h.name);
    const stormSurgeLegend = document.getElementById('stormSurgeLegend');
    const stormSurgeStatusEl = document.getElementById('stormSurgeStatus');
    if (stormSurgeVisible.length === 0) {
        if (stormSurgeStatusEl) stormSurgeStatusEl.textContent = '高潮浸水想定レイヤー: OFF';
        if (stormSurgeLegend) stormSurgeLegend.style.display = 'none';
    } else {
        if (stormSurgeStatusEl) stormSurgeStatusEl.textContent = `高潮浸水想定レイヤー: ON（${stormSurgeVisible.join(' / ')}）`;
        if (stormSurgeLegend) stormSurgeLegend.style.display = 'block';
    }

    const inlandFloodVisible = Object.values(HAZARD_LAYERS)
        .filter((h) => h.type === 'inland_flood' && h.visible)
        .map((h) => h.name);
    const inlandFloodStatusEl = document.getElementById('inlandFloodStatus');
    if (inlandFloodVisible.length === 0) {
        if (inlandFloodStatusEl) inlandFloodStatusEl.textContent = '内水氾濫レイヤー: OFF';
    } else {
        if (inlandFloodStatusEl) inlandFloodStatusEl.textContent = `内水氾濫レイヤー: ON（${inlandFloodVisible.join(' / ')}）`;
    }

    const landslideVisible = Object.values(HAZARD_LAYERS)
        .filter((h) => h.type === 'landslide' && h.visible)
        .map((h) => h.name);
    const landslideStatusEl = document.getElementById('landslideStatus');
    if (landslideVisible.length === 0) {
        if (landslideStatusEl) landslideStatusEl.textContent = '土砂災害レイヤー: OFF';
    } else {
        if (landslideStatusEl) landslideStatusEl.textContent = `土砂災害レイヤー: ON（${landslideVisible.join(' / ')}）`;
    }
}

function setInlandFloodStatus(msg) {
    const el = document.getElementById('inlandFloodStatus');
    if (el) el.textContent = msg;
}

function setLandslideStatus(msg) {
    const el = document.getElementById('landslideStatus');
    if (el) el.textContent = msg;
}

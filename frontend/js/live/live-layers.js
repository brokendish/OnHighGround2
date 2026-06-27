'use strict';
// live-layers.js — /live 専用レイヤー管理（雨雲・キキクル・地震・津波）
// navigation.js / state.js に一切依存しない。

(function () {

    // ─────────────────────────────────────────────────────────────────────────
    // 雨雲レイヤー（JMA 降水ナウキャスト）
    // ─────────────────────────────────────────────────────────────────────────

    // JMA 降水ナウキャスト色テーブル（data_lake/registry/weather/jma_nowcast_color_table.json に準拠）
    // alphaScale: 元 alpha に乗算する係数。弱雨ほど低く、強雨ほど高く設定する。
    const _RAIN_PIXEL_TABLE = [
        { r: 160, g: 210, b: 255, s: 0.25 }, // weak 弱い雨（薄青）
        { r:  33, g: 140, b: 255, s: 0.25 }, // weak 弱い雨（青）
        { r:   0, g:  65, b: 255, s: 0.40 }, // moderate 雨（濃青）
        { r:   0, g: 200, b: 200, s: 0.40 }, // moderate 雨（シアン）
        { r:   0, g: 200, b:   0, s: 0.65 }, // strong 強い雨（緑）
        { r: 255, g: 215, b:   0, s: 0.65 }, // strong 強い雨（黄）
        { r: 255, g: 140, b:   0, s: 0.70 }, // severe 非常に激しい雨（橙）
        { r: 255, g:   0, b:   0, s: 0.82 }, // severe 非常に激しい雨（赤）
        { r: 180, g:   0, b: 180, s: 0.90 }, // severe 猛烈な雨（紫）
    ];
    const _RAIN_THRESHOLD_SQ = 1600; // 距離 40 の 2 乗（バックエンド distance_threshold: 40 と同値）
    const _RAIN_BG_MIN       = 230;  // R/G/B がすべてこの値以上なら背景（降水なし）
    const _RAIN_ALPHA_MIN    = 50;   // alpha がこの値未満なら透明ピクセル

    function _rainAlphaScale(r, g, b, a) {
        if (a < _RAIN_ALPHA_MIN) return 0;
        if (r >= _RAIN_BG_MIN && g >= _RAIN_BG_MIN && b >= _RAIN_BG_MIN) return 0;
        let bestScale = 0.25;
        let bestDist  = Infinity;
        for (const c of _RAIN_PIXEL_TABLE) {
            const d = (r - c.r) * (r - c.r) + (g - c.g) * (g - c.g) + (b - c.b) * (b - c.b);
            if (d < bestDist) { bestDist = d; bestScale = c.s; }
        }
        return bestDist <= _RAIN_THRESHOLD_SQ ? bestScale : 0.35;
    }

    function _rainProcessPixels(data) {
        for (let i = 0; i < data.length; i += 4) {
            data[i + 3] = Math.round(data[i + 3] * _rainAlphaScale(data[i], data[i + 1], data[i + 2], data[i + 3]));
        }
    }

    // JMA hrpns タイルは偶数ズームにのみデータがある（kikikuru-layer.js と同様の理由）
    // createTile を override し Canvas でピクセルごとに alpha を調整する（案A）。
    // CORS でピクセル読み取り不可の場合は opacity 0.35 の描画にフォールバック（案B）。
    const _RainTileLayer = L.TileLayer.extend({
        _clampZoom(zoom) {
            let z = L.TileLayer.prototype._clampZoom.call(this, zoom);
            if (z % 2 !== 0) z = Math.max(z - 1, 2);
            return z;
        },
        createTile(coords, done) {
            const canvas = document.createElement('canvas');
            canvas.width = canvas.height = 256;
            const ctx = canvas.getContext('2d');
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.onload = function () {
                ctx.drawImage(img, 0, 0);
                try {
                    const imageData = ctx.getImageData(0, 0, 256, 256);
                    _rainProcessPixels(imageData.data);
                    ctx.putImageData(imageData, 0, 0);
                } catch (_) {
                    // CORS fallback: タイル全体を opacity 0.35 で描画
                    ctx.clearRect(0, 0, 256, 256);
                    ctx.globalAlpha = 0.35;
                    ctx.drawImage(img, 0, 0);
                }
                done(null, canvas);
            };
            img.onerror = function (e) { done(e, canvas); };
            img.src = this.getTileUrl(coords);
            return canvas;
        },
    });

    let _rainLayer   = null;
    let _rainEnabled = true;

    const _RAIN_LAYER_OPTIONS = {
        attribution:   '気象庁 降水ナウキャスト',
        minZoom:       1,
        maxNativeZoom: 10,
        maxZoom:       19,
        tileSize:      256,
        zIndex:        450,
    };

    function _rainSetFrame(tileUrlTemplate) {
        if (_rainLayer) {
            liveMap.removeLayer(_rainLayer);
            _rainLayer = null;
        }
        if (!_rainEnabled || !tileUrlTemplate) return;
        _rainLayer = new _RainTileLayer(tileUrlTemplate, _RAIN_LAYER_OPTIONS).addTo(liveMap);
    }

    async function _rainRefresh() {
        const res = await fetch('/api/weather/rain/tile/times');
        if (!res.ok) throw new Error(`[live-rain] HTTP ${res.status}`);
        const data = await res.json();
        if (!data || !Array.isArray(data.times) || !data.times.length) return;

        const current = data.times.find(t => t.offset_minutes === 0) || data.times[0];
        if (!current || !current.tile_url_template) return;

        if (_rainLayer) {
            liveMap.removeLayer(_rainLayer);
            _rainLayer = null;
        }
        if (!_rainEnabled) return;

        console.log('[live-rain] live rain layer updated (canvas pixel processing)');
        _rainLayer = new _RainTileLayer(current.tile_url_template, _RAIN_LAYER_OPTIONS).addTo(liveMap);
    }

    function _rainSetVisible(visible) {
        _rainEnabled = visible;
        if (visible) {
            _rainRefresh()
                .then(() => window.liveUI?.updateRainStatus?.(true))
                .catch((e) => {
                    console.warn('[live-rain] toggle ON 失敗:', e.message);
                    window.liveUI?.updateRainStatus?.(false);
                });
        } else {
            if (_rainLayer) {
                liveMap.removeLayer(_rainLayer);
                _rainLayer = null;
            }
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // キキクルレイヤー（気象庁 危険度分布タイル）
    // ─────────────────────────────────────────────────────────────────────────

    const _KIKIKURU_TIMES_URL = 'https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json';
    const _KIKIKURU_TILE_BASE = 'https://www.jma.go.jp/bosai/jmatile/data/risk';

    const _KIKIKURU_KINDS = {
        land:  { elem: 'land',       zIndex: 441 },
        flood: { elem: 'flood_mesh', zIndex: 442 },
        inund: { elem: 'inund',      zIndex: 440 },
    };

    const _KikikuruTileLayer = L.TileLayer.extend({
        _clampZoom(zoom) {
            let z = L.TileLayer.prototype._clampZoom.call(this, zoom);
            if (z % 2 !== 0) z = Math.max(z - 1, 4);
            return z;
        },
    });

    let _kikikuruEntry   = null;
    let _kikikuruEnabled = false;
    const _kikikuruLayers      = { land: null, flood: null, inund: null };
    const _kikikuruKindEnabled = { land: true,  flood: true,  inund: true  };

    async function _kikikuruFetchEntry() {
        const res = await fetch(_KIKIKURU_TIMES_URL);
        if (!res.ok) throw new Error(`kikikuru times HTTP ${res.status}`);
        const arr = await res.json();
        if (!Array.isArray(arr) || !arr.length) throw new Error('kikikuru times empty');
        return arr[0];
    }

    function _kikikuruTileUrl(entry, elem) {
        return `${_KIKIKURU_TILE_BASE}/${entry.basetime}/${entry.member}/${entry.validtime}/surf/${elem}/{z}/{x}/{y}.png`;
    }

    function _kikikuruAddKind(kind) {
        if (!_kikikuruEntry) return;
        if (!_kikikuruKindEnabled[kind]) return;
        const def = _KIKIKURU_KINDS[kind];
        _kikikuruLayers[kind] = new _KikikuruTileLayer(_kikikuruTileUrl(_kikikuruEntry, def.elem), {
            opacity:       0.65,
            attribution:   '気象庁 危険度分布',
            minZoom:       1,
            maxNativeZoom: 10,
            maxZoom:       19,
            tileSize:      256,
            zIndex:        def.zIndex,
        }).addTo(liveMap);
    }

    function _kikikuruRemoveKind(kind) {
        if (_kikikuruLayers[kind]) {
            liveMap.removeLayer(_kikikuruLayers[kind]);
            _kikikuruLayers[kind] = null;
        }
    }

    function _kikikuruRemoveAll() {
        Object.keys(_kikikuruLayers).forEach(_kikikuruRemoveKind);
    }

    async function _kikikuruSetVisible(visible) {
        _kikikuruEnabled = visible;
        _kikikuruRemoveAll();
        if (!visible) return;
        try {
            _kikikuruEntry = await _kikikuruFetchEntry();
            Object.keys(_KIKIKURU_KINDS).forEach(_kikikuruAddKind);
            window.liveUI?.updateKikikuruStatus?.(true);
            window.liveAlertPanel?.setStatus?.({ kikikuru: 'ok' });
        } catch (e) {
            console.warn('[live-kikikuru] 取得失敗:', e);
            window.liveUI?.updateKikikuruStatus?.(false);
            window.liveAlertPanel?.setStatus?.({ kikikuru: 'offline' });
        }
    }

    function _kikikuruSetKindVisible(kind, visible) {
        if (!(kind in _kikikuruKindEnabled)) return;
        _kikikuruKindEnabled[kind] = visible;
        if (!_kikikuruEnabled) return;
        if (visible) {
            _kikikuruAddKind(kind);
        } else {
            _kikikuruRemoveKind(kind);
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 地震マーカー
    // ─────────────────────────────────────────────────────────────────────────

    const _eqLayerGroup = L.layerGroup().addTo(liveMap);
    let _eqEnabled       = true;
    let _eqData          = [];
    let _eqSource        = 'p2p';
    let _eqFallback      = false;
    let _eqMuniAvailable = true;
    let _eqSelectedId    = null; // 選択中の event_id

    function _isImportantEq(eq) {
        if (eq.isImportant !== undefined) return eq.isImportant;
        if ((eq.magnitude || 0) >= 5.0) return true;
        return ['5弱', '5強', '6弱', '6強', '7'].includes(eq.max_intensity || '');
    }

    function _eqMagColor(mag) {
        if (mag >= 6.0) return '#cc0000';
        if (mag >= 5.0) return '#ff4444';
        if (mag >= 4.0) return '#ff8800';
        if (mag >= 3.0) return '#e3b341';
        return '#8b949e';
    }

    function _eqMagRadius(mag) {
        if (mag >= 6.0) return 18;
        if (mag >= 5.0) return 13;
        if (mag >= 4.0) return 9;
        if (mag >= 3.0) return 6;
        return 4;
    }

    // 経過時間に応じた透明度（古いほど薄く）
    function _eqAgeOpacity(occurredAt) {
        if (!occurredAt) return 0.4;
        const ageMs   = Date.now() - new Date(occurredAt).getTime();
        const ageDays = ageMs / (1000 * 60 * 60 * 24);
        if (ageDays < 1) return 0.85;
        if (ageDays < 2) return 0.60;
        return 0.38;
    }

    function _renderEqMarker(eq, isImportant, isSelected) {
        const lat = eq.lat;
        const lng = eq.lng;
        if (lat == null || lng == null) return;

        const mag        = eq.magnitude || 0;
        const intensityRaw = eq.max_intensity || '-';
        const intensity  = intensityRaw === 'unknown' ? '不明' : intensityRaw;
        const name       = eq.epicenter_name || eq.hypocenter_name || '不明';
        const occurredAt = eq.occurred_at || eq.origin_time || '';
        const at         = occurredAt ? occurredAt.slice(0, 16).replace('T', ' ') : '';
        const opacity    = _eqAgeOpacity(occurredAt);

        let dayLabel = '';
        if (occurredAt) {
            const ageDays = Math.floor((Date.now() - new Date(occurredAt).getTime()) / (1000 * 60 * 60 * 24));
            if (ageDays === 0) dayLabel = '今日';
            else if (ageDays === 1) dayLabel = '昨日';
            else dayLabel = `${ageDays}日前`;
        }

        const baseRadius  = _eqMagRadius(mag);
        const radius      = isSelected
            ? Math.max(baseRadius + 6, 18)
            : (isImportant ? Math.max(baseRadius + 5, 16) : baseRadius);
        const weight      = isSelected ? 3 : (isImportant ? 2.5 : (opacity < 0.6 ? 0.5 : 1));
        const borderColor = isSelected ? '#58a6ff' : (isImportant ? '#ff4444' : '#fff');
        const fillOpacity = (isSelected || isImportant) ? Math.max(opacity, 0.75) : opacity;

        const fallbackLine = isImportant && _eqFallback
            ? '<br><small style="color:#ff9944">JMA fallback / 市区町村震度なし</small>'
            : '';

        L.circleMarker([lat, lng], {
            radius,
            color:       borderColor,
            weight,
            fillColor:   _eqMagColor(mag),
            fillOpacity,
        }).bindPopup(
            `${isImportant ? '<b>重要地震</b><br>' : ''}<b>${name}</b>${dayLabel ? ` <small>(${dayLabel})</small>` : ''}<br>`
            + `M ${mag != null ? mag.toFixed(1) : '-'} / 震度 ${intensity}<br>`
            + `<small>${at}</small>${fallbackLine}`
        ).addTo(_eqLayerGroup);
    }

    function _eqRender() {
        _eqLayerGroup.clearLayers();
        // 前回の市区町村マーカーを先にクリア（選択切替前に必ず消す）
        window.liveEarthquakeLayer?.clear?.();

        if (!_eqEnabled || !_eqData.length) return;

        // 初期選択: 選択が未設定 or データに存在しない場合は最新重要地震 or 最新地震
        const existsSelected = _eqSelectedId !== null && _eqData.some(eq => eq.event_id === _eqSelectedId);
        if (!existsSelected) {
            const firstImportant = _eqData.find(_isImportantEq);
            _eqSelectedId = (firstImportant ?? _eqData[0]).event_id ?? null;
        }

        // 選択地震の市区町村震度マーカー描画（1件のみ・全件描画禁止）
        const selected = _eqData.find(eq => eq.event_id === _eqSelectedId) ?? _eqData[0];
        // 選択地震の市区町村マーカーのみ描画（全件描画禁止）
        if (selected) window.liveEarthquakeLayer?.render?.(selected, true);

        // 震源マーカーを描画（全件・市区町村マーカーとは別レイヤー）
        _eqData.forEach(eq => {
            if (!_isImportantEq(eq)) _renderEqMarker(eq, false, eq.event_id === _eqSelectedId);
        });
        _eqData.forEach(eq => {
            if (_isImportantEq(eq)) _renderEqMarker(eq, true, eq.event_id === _eqSelectedId);
        });
    }

    function _eqSelectById(eventId) {
        _eqSelectedId = eventId;
        // 前回の市区町村マーカーを必ずクリア（event_id 不一致でも残さない）
        window.liveEarthquakeLayer?.clear?.();

        const eq = _eqData.find(e => e.event_id === eventId);
        if (!eq || !_eqEnabled) return;

        // 選択地震の市区町村震度マーカーを描画
        window.liveEarthquakeLayer?.render?.(eq, true);

        // 地図フォーカス
        if (eq.lat != null && eq.lng != null) {
            liveMap.flyTo([eq.lat, eq.lng], Math.max(liveMap.getZoom(), 7));
        }

        // 震源マーカーの選択状態を更新（全件描画：市区町村マーカーとは別レイヤー）
        _eqLayerGroup.clearLayers();
        _eqData.forEach(e => {
            if (!_isImportantEq(e)) _renderEqMarker(e, false, e.event_id === _eqSelectedId);
        });
        _eqData.forEach(e => {
            if (_isImportantEq(e)) _renderEqMarker(e, true, e.event_id === _eqSelectedId);
        });
    }

    async function _eqRefresh() {
        // 新エンドポイント（3日間履歴・fallback情報付き）、未デプロイ時は旧エンドポイントにフォールバック
        try {
            const res = await fetch('/api/live/earthquakes/history?days=3');
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            _eqData          = (data.items || []).slice(0, 300);
            _eqSource        = data.source        || 'p2p';
            _eqFallback      = data.fallback      === true;
            _eqMuniAvailable = data.municipalityIntensityAvailable !== false;
        } catch (e) {
            console.warn('[live-eq] history endpoint unavailable, fallback to /api/earthquakes:', e.message);
            const res = await fetch('/api/earthquakes?days=1');
            if (!res.ok) throw new Error(`[live-eq] HTTP ${res.status}`);
            const data = await res.json();
            _eqData          = (data.items || []).slice(0, 50);
            _eqSource        = 'p2p';
            _eqFallback      = false;
            _eqMuniAvailable = true;
        }
        _eqRender();
        return _eqData;
    }

    function _eqSetVisible(visible) {
        _eqEnabled = visible;
        if (!visible) window.liveEarthquakeLayer?.clear?.();
        _eqRender();
    }

    function _eqGetData()       { return _eqData; }
    function _eqGetSelectedId() { return _eqSelectedId; }

    // ─────────────────────────────────────────────────────────────────────────
    // 津波情報（データ取得 + マップレイヤー連携）
    // ─────────────────────────────────────────────────────────────────────────

    let _tsunamiData    = null;
    let _tsunamiEnabled = true;

    async function _tsunamiRefresh() {
        const res = await fetch('/api/tsunami/warnings/current');
        if (!res.ok) throw new Error(`[live-tsunami] HTTP ${res.status}`);
        _tsunamiData = await res.json();
        // マップレイヤーにデータを渡す（ON 時のみ描画）
        window.liveTsunamiLayer?.setData?.(_tsunamiData);
        const count = (_tsunamiData.areas || []).filter(
            a => ['major_warning', 'warning', 'advisory'].includes(a.level)
        ).length;
        console.info(`live tsunami summary: areas=${count}`);
        return _tsunamiData;
    }

    function _tsunamiSetVisible(visible) {
        _tsunamiEnabled = visible;
        window.liveTsunamiLayer?.setVisible?.(visible);
    }

    function _tsunamiGetData() { return _tsunamiData; }

    // ─────────────────────────────────────────────────────────────────────────
    // 高潮情報（マップレイヤー連携）
    // ─────────────────────────────────────────────────────────────────────────

    let _stormSurgeData    = null;
    let _stormSurgeEnabled = true;

    async function _stormSurgeRefresh() {
        const data = await window.liveStormSurgeLayer?.refresh?.();
        _stormSurgeData = data || null;
        return _stormSurgeData;
    }

    function _stormSurgeSetVisible(visible) {
        _stormSurgeEnabled = visible;
        window.liveStormSurgeLayer?.setVisible?.(visible);
    }

    function _stormSurgeGetData() { return _stormSurgeData; }

    // ─────────────────────────────────────────────────────────────────────────
    // 公開 API
    // ─────────────────────────────────────────────────────────────────────────

    window.liveLayers = {
        rain: {
            setVisible: _rainSetVisible,
            refresh:    _rainRefresh,
            setFrame:   _rainSetFrame,
        },
        kikikuru: {
            setVisible:     _kikikuruSetVisible,
            setKindVisible: _kikikuruSetKindVisible,
        },
        earthquake: {
            setVisible:       _eqSetVisible,
            refresh:          _eqRefresh,
            getData:          _eqGetData,
            getSource:        () => _eqSource,
            getFallback:      () => _eqFallback,
            getMuniAvailable: () => _eqMuniAvailable,
            getSelectedId:    _eqGetSelectedId,
            getSelected:      () => _eqData.find(e => e.event_id === _eqSelectedId) ?? null,
            selectById:       _eqSelectById,
        },
        tsunami: {
            setVisible: _tsunamiSetVisible,
            refresh:    _tsunamiRefresh,
            getData:    _tsunamiGetData,
        },
        stormSurge: {
            setVisible: _stormSurgeSetVisible,
            refresh:    _stormSurgeRefresh,
            getData:    _stormSurgeGetData,
        },
        train: {
            setVisible: (v) => {
                window.liveTrainLayer?.setVisible?.(v);
                window.liveTrainOsmLayer?.setVisible?.(v);
            },
        },
        roadTraffic: {
            setVisible: (v) => {
                window.liveRoadOsmLayer?.setVisible?.(v);
                window.liveRoadTrafficLayer?.setVisible?.(v);
            },
        },
    };

})();

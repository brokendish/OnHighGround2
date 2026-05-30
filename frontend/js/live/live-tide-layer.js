'use strict';
// live-tide-layer.js — /live 専用 潮位観測点レイヤー
// navigation.js / state.js に一切依存しない。
// 既存 tide_service の /api/live/tide/* エンドポイントを使用する。

(function () {

    // ─────────────────────────────────────────────────────────────────────────
    // 状態
    // ─────────────────────────────────────────────────────────────────────────

    let _layerGroup  = null;
    let _enabled     = false;
    let _stations    = null;   // [{id, name, lat, lon, prefecture, has_data}]
    let _markers     = {};     // station_id → L.Marker
    let _selectedId  = null;

    // ─────────────────────────────────────────────────────────────────────────
    // アイコン（波形 SVG）
    // ─────────────────────────────────────────────────────────────────────────

    function _buildIcon(selected) {
        const size  = selected ? 32 : 22;
        const fill  = selected ? '#1e40af' : '#2563eb';
        const ring  = selected
            ? 'stroke="#ffffff" stroke-width="2.5"'
            : 'stroke="#93c5fd" stroke-width="1"';
        const wave1 = 'M3 15 Q5.5 11.5 8 15 Q10.5 18.5 13 15 Q15.5 11.5 18 15 Q20.5 18.5 23 15';
        const wave2 = 'M3 11 Q5.5 7.5 8 11 Q10.5 14.5 13 11 Q15.5 7.5 18 11 Q20.5 14.5 23 11';
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 26 26">
            <circle cx="13" cy="13" r="12" fill="${fill}" ${ring}/>
            <path d="${wave1}" stroke="white" stroke-width="2.2" fill="none" stroke-linecap="round"/>
            <path d="${wave2}" stroke="white" stroke-width="1.4" fill="none" stroke-linecap="round" opacity="0.55"/>
        </svg>`;
        return L.divIcon({
            html:        svg,
            className:   '',
            iconSize:    [size, size],
            iconAnchor:  [size / 2, size / 2],
            popupAnchor: [0, -(size / 2 + 4)],
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // データ取得
    // ─────────────────────────────────────────────────────────────────────────

    async function _fetchStations() {
        if (_stations !== null) return _stations;
        const res = await fetch('/api/live/tide/stations');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        _stations = data.stations || [];
        console.info(`live tide stations loaded: count=${_stations.length}`);
        return _stations;
    }

    async function _fetchDetail(stationId) {
        const res = await fetch(`/api/live/tide/stations/${encodeURIComponent(stationId)}`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 潮位グラフ描画（location-info-panel.js の _tideGraphDraw を流用）
    // ─────────────────────────────────────────────────────────────────────────

    function _drawGraph(canvas, data, nowMs) {
        const tMin = nowMs - 12 * 3600 * 1000;
        const tMax = nowMs + 12 * 3600 * 1000;

        const dpr  = window.devicePixelRatio || 1;
        const rect = canvas.getBoundingClientRect();
        if (rect.width === 0) {
            requestAnimationFrame(() => _drawGraph(canvas, data, nowMs));
            return;
        }
        canvas.width  = Math.round(rect.width  * dpr);
        canvas.height = Math.round(rect.height * dpr);
        const ctx = canvas.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const W = canvas.width  / dpr;
        const H = canvas.height / dpr;
        const PAD = { top: 10, right: 10, bottom: 22, left: 42 };

        ctx.clearRect(0, 0, W, H);

        const records = data && data.records && data.records.length ? data.records : null;
        if (!records) {
            ctx.fillStyle = '#94a3b8';
            ctx.font = '11px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('データなし', W / 2, H / 2);
            return;
        }

        const points = records
            .map(r => ({ t: new Date(r.datetime).getTime(), cm: Number(r.tide_cm) }))
            .filter(p => Number.isFinite(p.t) && Number.isFinite(p.cm)
                      && p.t >= tMin - 3600 * 1000
                      && p.t <= tMax + 3600 * 1000)
            .sort((a, b) => a.t - b.t);

        if (points.length === 0) {
            ctx.fillStyle = '#94a3b8';
            ctx.font = '11px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('データなし', W / 2, H / 2);
            return;
        }

        const cmValues = points.map(p => p.cm);
        let cmMin = Math.min(...cmValues);
        let cmMax = Math.max(...cmValues);
        const cmPad = Math.max(20, (cmMax - cmMin) * 0.15);
        cmMin -= cmPad;
        cmMax += cmPad;

        const gW = W - PAD.left - PAD.right;
        const gH = H - PAD.top - PAD.bottom;

        const tx = t  => PAD.left + (t  - tMin) / (tMax - tMin) * gW;
        const ty = cm => PAD.top  + (1 - (cm - cmMin) / (cmMax - cmMin)) * gH;

        // 水平グリッド
        const cmStep = (cmMax - cmMin) > 200 ? 50 : (cmMax - cmMin) > 100 ? 25 : 20;
        const cmBase = Math.ceil(cmMin / cmStep) * cmStep;
        ctx.strokeStyle = '#e2e8f0'; ctx.lineWidth = 0.5;
        for (let c = cmBase; c <= cmMax; c += cmStep) {
            const y = ty(c);
            ctx.beginPath(); ctx.moveTo(PAD.left, y); ctx.lineTo(PAD.left + gW, y); ctx.stroke();
            ctx.fillStyle = '#94a3b8'; ctx.font = '9px sans-serif'; ctx.textAlign = 'right';
            ctx.fillText(`${c}`, PAD.left - 3, y + 3);
        }

        // 時間グリッド + ラベル
        const hMs = 3600 * 1000;
        const t3hStart = Math.ceil(tMin / (3 * hMs)) * 3 * hMs;
        const t6hStart = Math.ceil(tMin / (6 * hMs)) * 6 * hMs;
        ctx.strokeStyle = '#e2e8f0'; ctx.lineWidth = 0.5;
        for (let t = t3hStart; t <= tMax; t += 3 * hMs) {
            const x = tx(t);
            ctx.beginPath(); ctx.moveTo(x, PAD.top); ctx.lineTo(x, PAD.top + gH); ctx.stroke();
        }
        ctx.fillStyle = '#94a3b8'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
        for (let t = t6hStart; t <= tMax; t += 6 * hMs) {
            const x = tx(t);
            const jstHour = new Date(t + 9 * hMs).getUTCHours();
            ctx.fillText(`${String(jstHour).padStart(2, '0')}:00`, x, H - 4);
        }

        // 潮位ライン
        const visPoints = points.filter(p => p.t >= tMin && p.t <= tMax);
        if (visPoints.length > 0) {
            ctx.strokeStyle = '#2563eb'; ctx.lineWidth = 2; ctx.lineJoin = 'round';
            ctx.beginPath();
            visPoints.forEach((p, i) => {
                const x = tx(p.t); const y = ty(p.cm);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            });
            ctx.stroke();

            const grad = ctx.createLinearGradient(0, PAD.top, 0, PAD.top + gH);
            grad.addColorStop(0, 'rgba(37,99,235,0.15)');
            grad.addColorStop(1, 'rgba(37,99,235,0)');
            ctx.fillStyle = grad;
            ctx.beginPath();
            visPoints.forEach((p, i) => {
                const x = tx(p.t); const y = ty(p.cm);
                if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
            });
            ctx.lineTo(tx(visPoints[visPoints.length - 1].t), PAD.top + gH);
            ctx.lineTo(tx(visPoints[0].t), PAD.top + gH);
            ctx.closePath();
            ctx.fill();
        }

        // 満潮・干潮マーカー
        const extremes = data && data.extremes;
        if (extremes) {
            const drawEx = (list, color, label) => {
                (list || []).forEach(e => {
                    const t = new Date(e.time).getTime();
                    if (t < tMin || t > tMax) return;
                    const x = tx(t);
                    const y = ty(Number(e.tide_cm));
                    ctx.beginPath(); ctx.arc(x, y, 4, 0, Math.PI * 2);
                    ctx.fillStyle = color; ctx.fill();
                    ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke();
                    ctx.fillStyle = color; ctx.font = 'bold 9px sans-serif'; ctx.textAlign = 'center';
                    ctx.fillText(label, x, Math.max(PAD.top + 9, y - 6));
                });
            };
            drawEx(extremes.high_tides, '#dc2626', '満');
            drawEx(extremes.low_tides,  '#0891b2', '干');
        }

        // 現在時刻ライン
        const x0 = tx(nowMs);
        ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 2; ctx.setLineDash([]);
        ctx.beginPath(); ctx.moveTo(x0, PAD.top); ctx.lineTo(x0, PAD.top + gH); ctx.stroke();

        // 現在潮位ドット
        const closest = points.length
            ? points.reduce((a, b) => Math.abs(b.t - nowMs) < Math.abs(a.t - nowMs) ? b : a)
            : null;
        if (closest) {
            const dotY = ty(closest.cm);
            ctx.beginPath(); ctx.arc(x0, dotY, 5.5, 0, Math.PI * 2);
            ctx.fillStyle = '#ef4444'; ctx.fill();
            ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // ポップアップ
    // ─────────────────────────────────────────────────────────────────────────

    function _fmtCm(v) {
        return v == null ? '--' : `${Math.round(Number(v))} cm`;
    }

    function _fmtTime(iso) {
        if (!iso) return '--';
        const d = new Date(iso);
        const h = String(d.getUTCHours() + 9 > 23 ? d.getUTCHours() + 9 - 24 : d.getUTCHours() + 9).padStart(2, '0');
        const m = String(d.getUTCMinutes()).padStart(2, '0');
        return `${h}:${m}`;
    }

    function _buildPopupHtml(detail) {
        const current = _fmtCm(detail.current_tide_cm);
        const highCm  = detail.next_high_tide ? _fmtCm(detail.next_high_tide.tide_cm) : '--';
        const highT   = detail.next_high_tide ? _fmtTime(detail.next_high_tide.time)  : '--';
        const lowCm   = detail.next_low_tide  ? _fmtCm(detail.next_low_tide.tide_cm)  : '--';
        const lowT    = detail.next_low_tide  ? _fmtTime(detail.next_low_tide.time)   : '--';
        const canvasId = `live-tide-graph-${detail.station_id}`;
        return `
            <div class="live-tide-popup">
                <div class="live-tide-popup-name">${detail.name}</div>
                <div class="live-tide-popup-current">現在潮位: <b>${current}</b></div>
                <div class="live-tide-popup-extremes">
                    <span class="live-tide-high">満潮 ${highT} ${highCm}</span>
                    <span class="live-tide-low">干潮 ${lowT} ${lowCm}</span>
                </div>
                <canvas id="${canvasId}" class="live-tide-graph-canvas" width="260" height="100"></canvas>
            </div>
        `;
    }

    function _attachGraph(detail) {
        const canvasId = `live-tide-graph-${detail.station_id}`;
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        _drawGraph(canvas, detail, Date.now());
    }

    // ─────────────────────────────────────────────────────────────────────────
    // マーカー生成
    // ─────────────────────────────────────────────────────────────────────────

    function _createMarker(station) {
        const marker = L.marker([station.lat, station.lon], {
            icon:        _buildIcon(station.id === _selectedId),
            title:       station.name,
            zIndexOffset: 200,
        });
        marker.bindTooltip(station.name, { permanent: false, direction: 'top', offset: [0, -14] });

        // bindPopup を先に呼んでおく。Leaflet の _openPopup ハンドラーが登録される。
        // その後 on('click', ...) を追加することで、Leaflet のハンドラーが先に走り
        // ポップアップを開いてから、自分のハンドラーで詳細を fetch する。
        marker.bindPopup(
            '<div class="live-tide-popup">'
                + '<div class="live-tide-popup-name">' + station.name + '</div>'
                + '<div style="color:#94a3b8;font-size:12px">読み込み中...</div>'
            + '</div>',
            { maxWidth: 300 },
        );

        marker.on('click', async () => {
            _setSelected(station.id);
            // ここでは openPopup を呼ばない（bindPopup による _openPopup が既に処理）
            try {
                const detail = await _fetchDetail(station.id);
                console.info(`live tide station: id=${detail.station_id} current=${detail.current_tide_cm ?? 'N/A'}`);
                const popup = marker.getPopup();
                if (popup) {
                    popup.setContent(_buildPopupHtml(detail));
                    // ポップアップが閉じていた場合は再度開く
                    if (!popup.isOpen()) marker.openPopup();
                    requestAnimationFrame(() => _attachGraph(detail));
                }
            } catch (err) {
                console.warn('[live-tide] 詳細取得失敗:', err);
            }
        });

        return marker;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 選択状態
    // ─────────────────────────────────────────────────────────────────────────

    function _setSelected(id) {
        const prev = _selectedId;
        _selectedId = id;
        if (prev && _markers[prev]) _markers[prev].setIcon(_buildIcon(false));
        if (id  && _markers[id])   _markers[id].setIcon(_buildIcon(true));
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 公開 API
    // ─────────────────────────────────────────────────────────────────────────

    async function _setVisible(visible) {
        _enabled = visible;

        if (!visible) {
            if (_layerGroup) liveMap.removeLayer(_layerGroup);
            _selectedId = null;
            return;
        }

        try {
            const stations = await _fetchStations();

            if (!_layerGroup) _layerGroup = L.layerGroup();
            _layerGroup.clearLayers();
            _markers = {};

            stations.forEach(station => {
                const marker = _createMarker(station);
                _markers[station.id] = marker;
                _layerGroup.addLayer(marker);
            });

            _layerGroup.addTo(liveMap);
            window.liveUI?.updateTideStatus?.(true);
        } catch (err) {
            console.warn('[live-tide] 観測点ロード失敗:', err);
            window.liveUI?.updateTideStatus?.(false);
        }
    }

    window.liveTideLayer = {
        setVisible: _setVisible,
    };

})();

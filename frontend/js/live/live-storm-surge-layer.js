'use strict';
// live-storm-surge-layer.js — /live 高潮警報マップレイヤー
// /api/live/storm_surge/warnings のデータを地図上に表示する。
// navigation.js / state.js に一切依存しない。

(function () {

    // ── 定数 ─────────────────────────────────────────────────────────────────

    const _LEVEL_COLOR = {
        emergency: '#7c3aed',
        warning:   '#dc2626',
        advisory:  '#d97706',
    };

    const _LEVEL_LABEL = {
        emergency: '高潮特別警報',
        warning:   '高潮警報',
        advisory:  '高潮注意報',
    };

    const _LEVEL_RADIUS = {
        emergency: 22,
        warning:   18,
        advisory:  14,
    };

    // Phase A: 都道府県ごとの海岸線ハイライト円半径（メートル）
    // 都道府県の規模・海岸線の形状に応じて調整した概略半径
    const _PREF_COAST_RADIUS = {
        "010000": 130000, // 北海道（広大な海岸線）
        "020000":  70000, // 青森県
        "030000":  70000, // 岩手県
        "040000":  55000, // 宮城県
        "050000":  60000, // 秋田県
        "060000":  40000, // 山形県（狭い日本海側）
        "070000":  55000, // 福島県
        "080000":  55000, // 茨城県
        "120000":  60000, // 千葉県
        "130000":  35000, // 東京都（コンパクト）
        "140000":  35000, // 神奈川県
        "150000":  80000, // 新潟県（長い海岸線）
        "160000":  45000, // 富山県
        "170000":  60000, // 石川県
        "180000":  40000, // 福井県
        "220000":  70000, // 静岡県
        "230000":  55000, // 愛知県
        "240000":  70000, // 三重県
        "270000":  35000, // 大阪府
        "280000":  65000, // 兵庫県
        "300000":  55000, // 和歌山県
        "310000":  40000, // 鳥取県
        "320000":  70000, // 島根県
        "330000":  50000, // 岡山県
        "340000":  55000, // 広島県
        "350000":  65000, // 山口県
        "360000":  50000, // 徳島県
        "370000":  40000, // 香川県
        "380000":  55000, // 愛媛県
        "390000":  70000, // 高知県（長い太平洋岸）
        "400000":  55000, // 福岡県
        "410000":  40000, // 佐賀県
        "420000":  65000, // 長崎県（複雑な海岸線）
        "430000":  55000, // 熊本県
        "440000":  55000, // 大分県
        "450000":  65000, // 宮崎県
        "460000":  80000, // 鹿児島県（複雑な海岸線）
        "470000":  80000, // 沖縄県（島嶼）
    };
    const _DEFAULT_COAST_RADIUS = 60000;

    // ── 状態 ─────────────────────────────────────────────────────────────────
    // toggle-storm-surge の初期状態（checked）に合わせて enabled=true で開始する

    // preferCanvas: true 環境でも className を DOM に付与するため SVG を強制使用
    const _svgRenderer = L.svg();

    let _layerGroup  = null;
    let _enabled     = true;
    let _lastData    = null;

    // ── アイコン生成 ─────────────────────────────────────────────────────────

    function _buildIcon(level) {
        const color = _LEVEL_COLOR[level] || '#dc2626';
        const size  = _LEVEL_RADIUS[level] || 18;
        const r     = size / 2;
        const short = level === 'emergency' ? '特別' : level === 'warning' ? '高潮警' : '高潮注';
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size * 2}" height="${size * 2}" viewBox="0 0 ${size * 2} ${size * 2}">
            <polygon points="${size},2 ${size * 2 - 2},${size * 2 - 2} 2,${size * 2 - 2}"
                     fill="${color}" stroke="white" stroke-width="2"/>
            <text x="${size}" y="${size * 2 - 5}" text-anchor="middle" fill="white"
                  font-size="${Math.max(7, r - 3)}" font-weight="bold" font-family="sans-serif">${short}</text>
        </svg>`;
        return L.divIcon({
            html:        svg,
            className:   '',
            iconSize:    [size * 2, size * 2],
            iconAnchor:  [size, size],
            popupAnchor: [0, -(size + 4)],
        });
    }

    // ── Phase A/B: 海岸線ハイライト（L.circle） ─────────────────────────────

    function _buildCoastPopup(area) {
        const isWarning = area.level === 'danger';
        const color     = isWarning ? '#ef4444' : '#f97316';
        const affected  = area.affected_areas || [];

        // Phase B: class20 / 市区町村単位のエリア名を収集
        const muniNames = [...new Set(affected.map(a => a.area_name))]
            .filter(n => n)
            .join('、');

        return [
            `<div style="min-width:180px">`,
            `<div style="font-weight:bold;color:${color}">高潮警報対象の沿岸部</div>`,
            `<div>${area.label}</div>`,
            muniNames
                ? `<div style="font-size:11px;color:#8b949e;margin-top:4px">対象区域: ${muniNames}</div>`
                : '',
            `<div style="font-size:10px;color:#6e7681;margin-top:6px">行政区域単位の警報発令エリアです。<br>高潮浸水範囲とは異なります。</div>`,
            `</div>`,
        ].join('');
    }

    function _renderCoastHighlight(areas) {
        const targetAreas = areas.filter(
            a => (a.level === 'danger' || a.level === 'warning') &&
                 a.lat != null && a.lng != null
        );
        targetAreas.forEach(area => {
            const prefCode = area.pref_code || '';
            const radius   = _PREF_COAST_RADIUS[prefCode] || _DEFAULT_COAST_RADIUS;
            const color    = area.level === 'danger' ? '#ef4444' : '#f97316';

            L.circle([area.lat, area.lng], {
                renderer:    _svgRenderer,
                radius,
                color,
                weight:      3,
                opacity:     0.85,
                dashArray:   '10 6',
                fillColor:   color,
                fillOpacity: 0.05,
                className:   'storm-surge-coast-ring',
            })
            .bindPopup(_buildCoastPopup(area))
            .addTo(_layerGroup);
        });
    }

    // ── Phase C: 浸水想定区域案内ヒント ─────────────────────────────────────

    function _updatePhaseC(areas) {
        const hint = document.getElementById('storm-surge-coast-hint');
        if (!hint) return;
        const hasWarning = areas.some(a => a.level === 'danger');
        if (hasWarning) {
            hint.classList.remove('hidden');
        } else {
            hint.classList.add('hidden');
        }
    }

    // ── データ取得 ────────────────────────────────────────────────────────────

    async function _fetchData() {
        const res = await fetch('/api/live/storm_surge/warnings');
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.json();
    }

    // ── レンダリング ─────────────────────────────────────────────────────────

    function _render(data) {
        if (!_layerGroup) _layerGroup = L.layerGroup();
        _layerGroup.clearLayers();

        const areas = (data && data.areas) || [];

        // Phase A/B: 沿岸部ハイライト（警報エリア概略）
        _renderCoastHighlight(areas);

        // 都道府県マーカー（三角アイコン）
        areas.forEach(area => {
            const lat = area.lat;
            const lng = area.lng;
            if (lat == null || lng == null) return;

            const level = area.level === 'danger' ? 'warning' : 'advisory';
            const detail = area.detail || _LEVEL_LABEL[level] || '高潮情報';
            const color = _LEVEL_COLOR[level] || '#dc2626';

            const marker = L.marker([lat, lng], {
                icon:         _buildIcon(level),
                zIndexOffset: 600,
                title:        area.label,
            });
            marker.bindPopup(
                `<div style="min-width:160px">` +
                `<div style="font-weight:bold;color:${color}">${detail}</div>` +
                `<div>${area.label}</div>` +
                `</div>`
            );
            _layerGroup.addLayer(marker);
        });

        // Phase C: 浸水想定区域ヒント更新
        _updatePhaseC(areas);

        if (_enabled) _layerGroup.addTo(liveMap);
    }

    // ── 公開 API ──────────────────────────────────────────────────────────────

    async function refresh() {
        const data = await _fetchData();
        _lastData = data;
        if (_enabled) _render(data);
        const count = (data.areas || []).length;
        console.info(`live storm surge summary: areas=${count}`);
        return data;
    }

    function setData(data) {
        _lastData = data;
        if (_enabled) _render(data);
    }

    function setVisible(visible) {
        _enabled = visible;
        if (!_layerGroup) _layerGroup = L.layerGroup();
        if (visible) {
            if (_lastData) {
                _render(_lastData);
            } else {
                refresh()
                    .then(() => window.liveUI?.updateStormSurgeStatus?.(true))
                    .catch(e => {
                        console.warn('[live-storm-surge] 取得失敗:', e);
                        window.liveUI?.updateStormSurgeStatus?.(false);
                    });
            }
        } else {
            liveMap.removeLayer(_layerGroup);
            // Phase C ヒントも非表示
            const hint = document.getElementById('storm-surge-coast-hint');
            if (hint) hint.classList.add('hidden');
        }
    }

    window.liveStormSurgeLayer = { setVisible, refresh, setData };

})();

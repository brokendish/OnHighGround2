'use strict';
// live-tsunami-layer.js — /live 津波警報マップレイヤー
// 既存 /api/tsunami/warnings/current のデータを地図上に表示する。
// navigation.js / state.js に一切依存しない。

(function () {

    // ── 定数 ─────────────────────────────────────────────────────────────────

    const _LEVEL_COLOR = {
        major_warning: '#cc0000',
        warning:       '#ef4444',
        advisory:      '#f59e0b',
    };

    const _LEVEL_LABEL = {
        major_warning: '大津波警報',
        warning:       '津波警報',
        advisory:      '津波注意報',
    };

    const _LEVEL_RADIUS = {
        major_warning: 22,
        warning:       18,
        advisory:      14,
    };

    // JMA津波警報区域の代表座標（name → [lat, lng]）
    // API から lat/lng が返らない場合のフォールバック
    const _AREA_COORDS = {
        '根室地方':               [43.33, 145.58],
        '十勝地方':               [42.89, 143.81],
        '釧路・根室地方':          [43.20, 144.65],
        '釧路地方':               [43.05, 144.36],
        '日高地方':               [42.26, 142.59],
        '胆振・日高地方':          [42.60, 141.90],
        '胆振地方':               [42.77, 141.58],
        '渡島・檜山地方':          [41.72, 140.62],
        '渡島地方':               [41.82, 140.73],
        '檜山地方':               [42.14, 139.94],
        '宗谷地方':               [45.40, 141.67],
        '留萌・天売・焼尻地方':    [44.03, 141.64],
        'オホーツク海沿岸':        [44.07, 144.07],
        '北海道日本海沿岸南部':    [42.70, 140.00],
        '北海道日本海沿岸北部':    [44.37, 141.73],
        '青森県太平洋沿岸':        [40.95, 141.38],
        '青森県日本海沿岸':        [40.84, 140.28],
        '岩手県':                  [39.52, 141.96],
        '宮城県':                  [38.27, 141.02],
        '福島県':                  [37.44, 141.17],
        '茨城県':                  [36.34, 140.45],
        '千葉県九十九里・外房':    [35.46, 140.35],
        '千葉県内房':              [35.15, 139.92],
        '東京湾内湾':              [35.46, 139.76],
        '伊豆諸島':                [34.37, 139.26],
        '小笠原諸島':              [27.09, 142.19],
        '相模湾・三浦半島':        [35.24, 139.58],
        '静岡県':                  [34.97, 138.38],
        '愛知県外海':              [34.72, 137.48],
        '伊勢・三河湾':            [34.68, 136.85],
        '三重県南部':              [33.87, 136.25],
        '和歌山県':                [33.72, 135.44],
        '徳島県':                  [33.81, 134.56],
        '高知県':                  [33.42, 133.59],
        '宮崎県':                  [32.00, 131.59],
        '鹿児島県東部':            [31.58, 131.00],
        '種子島・屋久島地方':      [30.39, 130.66],
        '奄美群島・トカラ列島':    [28.34, 129.55],
        '沖縄本島地方':            [26.21, 127.68],
        '大東島地方':              [25.83, 131.23],
        '宮古島地方':              [24.80, 125.28],
        '八重山地方':              [24.33, 124.15],
        '豊後水道':                [33.09, 132.03],
        '有明・八代海':            [32.51, 130.50],
        '長崎県':                  [32.74, 129.88],
        '大分県':                  [33.24, 131.61],
        '愛媛県':                  [33.84, 132.77],
        '山口県':                  [34.18, 131.47],
        '広島県':                  [34.40, 132.46],
        '岡山県':                  [34.66, 133.93],
        '兵庫県南部':              [34.69, 135.19],
        '大阪府':                  [34.69, 135.50],
        '日向灘':                  [31.50, 131.60],
        '土佐湾':                  [33.08, 133.52],
        '紀伊水道':                [33.97, 135.02],
        '遠州灘':                  [34.64, 137.83],
        '三陸沿岸':                [39.00, 142.00],
        '北海道太平洋沿岸東部':    [43.00, 145.00],
        '北海道太平洋沿岸中部':    [42.50, 143.00],
        '北海道太平洋沿岸西部':    [42.10, 141.00],
        '千葉県':                  [35.46, 140.35],
        '神奈川県':                [35.45, 139.64],
        '新潟県':                  [37.90, 139.00],
        '石川県':                  [36.59, 136.63],
        '福井県':                  [35.95, 136.18],
    };

    // ── 状態 ─────────────────────────────────────────────────────────────────
    // toggle-tsunami の初期状態（checked）に合わせて enabled=true で開始する

    let _layerGroup  = null;
    let _enabled     = true;
    let _lastData    = null;

    // ── アイコン生成 ─────────────────────────────────────────────────────────

    function _buildIcon(level) {
        const color  = _LEVEL_COLOR[level]  || '#ef4444';
        const label  = _LEVEL_LABEL[level]  || '津波';
        const size   = _LEVEL_RADIUS[level] || 18;
        const r      = size / 2;
        const short  = level === 'major_warning' ? '大津波' : level === 'warning' ? '津波警報' : '注意報';
        const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${size * 2}" height="${size * 2}" viewBox="0 0 ${size * 2} ${size * 2}">
            <circle cx="${size}" cy="${size}" r="${r - 1}" fill="${color}" stroke="white" stroke-width="2"/>
            <text x="${size}" y="${size + 4}" text-anchor="middle" fill="white" font-size="${Math.max(8, r - 2)}" font-weight="bold" font-family="sans-serif">${short.slice(0, 3)}</text>
        </svg>`;
        return L.divIcon({
            html:        svg,
            className:   '',
            iconSize:    [size * 2, size * 2],
            iconAnchor:  [size, size],
            popupAnchor: [0, -(size + 4)],
        });
    }

    // ── レンダリング ─────────────────────────────────────────────────────────

    function _render(data) {
        if (!_layerGroup) _layerGroup = L.layerGroup();
        _layerGroup.clearLayers();

        const areas = (data && data.areas) || [];
        const active = areas.filter(a =>
            ['major_warning', 'warning', 'advisory'].includes(a.level)
        );

        active.forEach(area => {
            const lat = area.lat ?? _AREA_COORDS[area.name]?.[0];
            const lng = area.lng ?? _AREA_COORDS[area.name]?.[1];
            if (lat == null || lng == null) return;

            const label = _LEVEL_LABEL[area.level] || area.level_label || '津波情報';
            const color = _LEVEL_COLOR[area.level] || '#ef4444';
            const height = area.expected_height ? `  予想高さ: ${area.expected_height}` : '';

            const marker = L.marker([lat, lng], {
                icon:         _buildIcon(area.level),
                zIndexOffset: 800,
                title:        area.name,
            });
            marker.bindPopup(
                `<div style="min-width:180px">` +
                `<div style="font-weight:bold;color:${color}">${label}</div>` +
                `<div>${area.name}</div>` +
                `${height ? `<div style="font-size:12px;color:#475569">${height}</div>` : ''}` +
                `</div>`
            );
            _layerGroup.addLayer(marker);
        });

        if (_enabled) _layerGroup.addTo(liveMap);
    }

    // ── 公開 API ──────────────────────────────────────────────────────────────

    function setData(data) {
        _lastData = data;
        if (_enabled) _render(data);
    }

    function setVisible(visible) {
        _enabled = visible;
        if (!_layerGroup) _layerGroup = L.layerGroup();
        if (visible) {
            _render(_lastData);
        } else {
            liveMap.removeLayer(_layerGroup);
        }
    }

    window.liveTsunamiLayer = { setVisible, setData };

})();

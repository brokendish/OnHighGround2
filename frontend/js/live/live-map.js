'use strict';
// live-map.js — /live 専用 Leaflet 地図初期化

(function () {
    const JAPAN_CENTER = [36.5, 137.0];
    const JAPAN_ZOOM   = 5;

    const map = L.map('live-map', {
        center:           JAPAN_CENTER,
        zoom:             JAPAN_ZOOM,
        zoomControl:      true,
        attributionControl: true,
        preferCanvas:     true,
    });

    // 背景地図: CARTO Basemaps は API キー必須（2026-08〜）。キー未設定時は
    // キー不要の OpenStreetMap ラスタタイルへフォールバックする（frontend/js/shared/basemap.js）。
    const OSM_ATTRIBUTION_LIVE =
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OSM</a> contributors (<a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener">ODbL</a>)';
    const CARTO_ATTRIBUTION_LIVE = OSM_ATTRIBUTION_LIVE +
        ' &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>';

    if (typeof OHG2Basemap !== 'undefined') {
        OHG2Basemap.createBaseLayer(L, {
            maxZoom:          19,
            opacity:          1.0,
            zIndex:           1,
            cartoAttribution: CARTO_ATTRIBUTION_LIVE,
            osmAttribution:   OSM_ATTRIBUTION_LIVE,
        }).layer.addTo(map);
    } else {
        // ヘルパー未ロード時の最小フォールバック（キー不要）。
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: OSM_ATTRIBUTION_LIVE,
            maxZoom:     19,
            opacity:     1.0,
            zIndex:      1,
        }).addTo(map);
    }

    if (typeof OHG2Attribution !== 'undefined') {
        OHG2Attribution.installBaseAttribution(map);
    }

    window.liveMap = map;
})();

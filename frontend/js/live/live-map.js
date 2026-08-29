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

    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OSM</a> contributors (<a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener">ODbL</a>) &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>',
        subdomains:  'abcd',
        maxZoom:     19,
        opacity:     1.0,
        zIndex:      1,
    }).addTo(map);

    if (typeof OHG2Attribution !== 'undefined') {
        OHG2Attribution.installBaseAttribution(map);
    }

    window.liveMap = map;
})();

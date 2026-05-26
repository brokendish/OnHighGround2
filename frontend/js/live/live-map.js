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
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
        subdomains:  'abcd',
        maxZoom:     19,
        opacity:     1.0,
        zIndex:      1,
    }).addTo(map);

    window.liveMap = map;
})();

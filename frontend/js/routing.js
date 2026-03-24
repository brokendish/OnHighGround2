/**
 * routing.js — ルーティング・経路案内
 *
 * - Leaflet Routing Machine の日本語ロケール設定
 * - drawRouteTo: OSRM を使ったルート描画
 * - showRoute: 避難先候補のルート表示（地図 + カード連動）
 * - 経路ステップのレンダリング・フォーカス
 */

// ── 日本語ロケール ────────────────────────────────────────────────────────

function ensureJapaneseRoutingLocalization() {
    if (!L.Routing) {
        return;
    }
    if (!L.Routing.Localization) {
        L.Routing.Localization = {};
    }
    if (L.Routing.Localization.ja) {
        return;
    }

    L.Routing.Localization.ja = {
        directions: {
            N: '北',
            NE: '北東',
            E: '東',
            SE: '南東',
            S: '南',
            SW: '南西',
            W: '西',
            NW: '北西'
        },
        instructions: {
            Head: ['{dir}へ進む', ' {road}'],
            Continue: ['{dir}へ直進', ' {road}'],
            SlightRight: ['やや右へ', ' {road}'],
            Right: ['右折', ' {road}'],
            SharpRight: ['鋭く右折', ' {road}'],
            TurnAround: ['Uターン', ''],
            SlightLeft: ['やや左へ', ' {road}'],
            Left: ['左折', ' {road}'],
            SharpLeft: ['鋭く左折', ' {road}'],
            WaypointReached: ['経由地に到着', ''],
            Roundabout: ['ロータリーを{exitStr}番目の出口へ', ' {road}'],
            DestinationReached: ['目的地に到着', '']
        },
        formatOrder: function(n) {
            return `${n}番目`;
        },
        ui: {
            startPlaceholder: '出発地',
            viaPlaceholder: '経由地',
            endPlaceholder: '目的地',
            addWaypoint: '経由地を追加',
            route: 'ルート検索'
        },
        units: {
            meters: 'm',
            kilometers: 'km',
            yards: 'yd',
            miles: 'mi',
            hours: '時間',
            minutes: '分',
            seconds: '秒'
        }
    };
}

ensureJapaneseRoutingLocalization();

function translateInstructionToJapanese(text) {
    if (!text || typeof text !== 'string') {
        return text;
    }

    const replacements = [
        [/\bHead north\b/gi, '北へ進む'],
        [/\bHead northeast\b/gi, '北東へ進む'],
        [/\bHead east\b/gi, '東へ進む'],
        [/\bHead southeast\b/gi, '南東へ進む'],
        [/\bHead south\b/gi, '南へ進む'],
        [/\bHead southwest\b/gi, '南西へ進む'],
        [/\bHead west\b/gi, '西へ進む'],
        [/\bHead northwest\b/gi, '北西へ進む'],
        [/\bContinue\b/gi, '直進'],
        [/\bSlight right\b/gi, 'やや右へ'],
        [/\bTurn right\b/gi, '右折'],
        [/\bSharp right\b/gi, '鋭く右折'],
        [/\bTurn around\b/gi, 'Uターン'],
        [/\bSlight left\b/gi, 'やや左へ'],
        [/\bTurn left\b/gi, '左折'],
        [/\bSharp left\b/gi, '鋭く左折'],
        [/\bWaypoint reached\b/gi, '経由地に到着'],
        [/\bDestination reached\b/gi, '目的地に到着'],
        [/\bonto\b/gi, 'へ'],
        [/\bon\b/gi, 'を進む']
    ];

    let translated = text;
    replacements.forEach(([pattern, value]) => {
        translated = translated.replace(pattern, value);
    });

    translated = translated.replace(
        /At the roundabout, take the (\d+)(st|nd|rd|th) exit/gi,
        'ロータリーを$1番目の出口へ'
    );

    return translated;
}

// ── ルートカラー・クリア ──────────────────────────────────────────────────

function getRouteColorByIndex(routeIndex) {
    const index = Math.max(0, Number(routeIndex) || 0);
    return ROUTE_COLOR_PALETTE[index % ROUTE_COLOR_PALETTE.length];
}

function clearSelectedRouteHighlight() {
    selectedRouteHighlightLayers.forEach((layer) => {
        if (layer && map && map.hasLayer(layer)) {
            map.removeLayer(layer);
        }
    });
    selectedRouteHighlightLayers = [];
}

function clearRouteCandidateLayers() {
    routeCandidateLayers.forEach((layer) => {
        if (layer && map && map.hasLayer(layer)) {
            map.removeLayer(layer);
        }
    });
    routeCandidateLayers = [];
}

function clearRouteStepFocusMarker() {
    if (routeStepFocusMarker && map && map.hasLayer(routeStepFocusMarker)) {
        map.removeLayer(routeStepFocusMarker);
    }
    routeStepFocusMarker = null;
}

// ── ルート描画 ────────────────────────────────────────────────────────────

function formatDurationText(seconds) {
    const totalSeconds = Math.round(Number(seconds) || 0);
    const minutes = Math.floor(totalSeconds / 60);
    const remainSeconds = totalSeconds % 60;
    if (minutes <= 0) {
        return `${remainSeconds}秒`;
    }
    return `${minutes}分${remainSeconds > 0 ? ` ${remainSeconds}秒` : ''}`;
}

function detectStepDirection(stepText) {
    const text = String(stepText || '').toLowerCase();
    if (!text) {
        return { icon: '↑', label: '進行方向' };
    }
    if (text.includes('uターン') || text.includes('uturn') || text.includes('u-turn')) {
        return { icon: '↩', label: 'Uターン' };
    }
    if (text.includes('左折') || text.includes('left')) {
        return { icon: '←', label: '左方向' };
    }
    if (text.includes('右折') || text.includes('right')) {
        return { icon: '→', label: '右方向' };
    }
    if (text.includes('やや左') || text.includes('slight left')) {
        return { icon: '↖', label: 'やや左' };
    }
    if (text.includes('やや右') || text.includes('slight right')) {
        return { icon: '↗', label: 'やや右' };
    }
    if (text.includes('鋭く左') || text.includes('sharp left')) {
        return { icon: '↙', label: '鋭く左' };
    }
    if (text.includes('鋭く右') || text.includes('sharp right')) {
        return { icon: '↘', label: '鋭く右' };
    }
    if (text.includes('ロータリー') || text.includes('roundabout')) {
        return { icon: '⟳', label: 'ロータリー' };
    }
    return { icon: '↑', label: '直進' };
}

function focusRouteStepOnMap(step, routeColor) {
    if (!step || !step.latLng) {
        return;
    }
    clearRouteStepFocusMarker();

    const direction = detectStepDirection(step.text);

    routeStepFocusMarker = L.circleMarker(step.latLng, {
        color: routeColor || '#ff9800',
        fillColor: routeColor || '#ff9800',
        fillOpacity: 0.9,
        radius: 8,
        weight: 3
    }).addTo(map);
    const popupHtml = `
        <div style="min-width: 180px;">
            <div style="font-size: 18px; font-weight: 700; margin-bottom: 4px;">
                ${direction.icon} ${direction.label}
            </div>
            <div style="font-size: 13px;">
                ${step.distanceLabel ? `${step.text}（${step.distanceLabel}）` : step.text}
            </div>
        </div>
    `;
    routeStepFocusMarker.bindPopup(popupHtml, {
        className: 'step-focus-popup',
        autoPan: false,
        offset: L.point(0, -16)
    }).openPopup();
    map.flyTo(step.latLng, Math.max(map.getZoom(), 17), { duration: 0.45 });
}

function renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex) {
    clearRouteCandidateLayers();
    clearSelectedRouteHighlight();

    const routeList = Array.isArray(routes) ? routes : [];
    const colors = Array.isArray(routeColors) ? routeColors : [];
    if (routeList.length === 0) {
        return;
    }

    routeList.forEach((route, routeIndex) => {
        if (!route || !Array.isArray(route.coordinates) || route.coordinates.length === 0) {
            return;
        }
        const isSelected = routeIndex === selectedRouteIndex;
        const color = colors[routeIndex] || getRouteColorByIndex(routeIndex);

        const baseLine = L.polyline(route.coordinates, {
            color,
            weight: isSelected ? 7 : 5,
            opacity: isSelected ? 0.95 : 0.55,
            lineCap: 'round',
            lineJoin: 'round'
        }).addTo(map);
        routeCandidateLayers.push(baseLine);
    });

    const selectedRoute = routeList[selectedRouteIndex];
    if (selectedRoute && Array.isArray(selectedRoute.coordinates) && selectedRoute.coordinates.length > 0) {
        const selectedColor = colors[selectedRouteIndex] || getRouteColorByIndex(selectedRouteIndex);
        const outline = L.polyline(selectedRoute.coordinates, {
            color: '#ffffff',
            weight: 10,
            opacity: 0.9,
            lineCap: 'round',
            lineJoin: 'round'
        }).addTo(map);
        const line = L.polyline(selectedRoute.coordinates, {
            color: selectedColor,
            weight: 7,
            opacity: 0.98,
            lineCap: 'round',
            lineJoin: 'round'
        }).addTo(map);
        outline.bringToFront();
        line.bringToFront();
        selectedRouteHighlightLayers = [outline, line];
    }
}

function resolveInstructionLatLng(route, instruction) {
    if (!route || !instruction) {
        return null;
    }
    if (instruction.latLng && Number.isFinite(Number(instruction.latLng.lat)) && Number.isFinite(Number(instruction.latLng.lng))) {
        return L.latLng(Number(instruction.latLng.lat), Number(instruction.latLng.lng));
    }

    const pointIndex = Number(instruction.index);
    if (!Array.isArray(route.coordinates) || !Number.isFinite(pointIndex) || pointIndex < 0 || pointIndex >= route.coordinates.length) {
        return null;
    }
    const point = route.coordinates[pointIndex];
    if (!point) {
        return null;
    }
    if (Number.isFinite(Number(point.lat)) && Number.isFinite(Number(point.lng))) {
        return L.latLng(Number(point.lat), Number(point.lng));
    }
    if (Array.isArray(point) && point.length >= 2) {
        return L.latLng(Number(point[0]), Number(point[1]));
    }
    return null;
}

function buildRouteInstructionItems(route, formatter) {
    const routeInstructions = (route && Array.isArray(route.instructions)) ? route.instructions : [];
    return routeInstructions
        .map((instruction, index) => {
            const text = formatter && typeof formatter.formatInstruction === 'function'
                ? formatter.formatInstruction(instruction, index)
                : translateInstructionToJapanese(instruction && instruction.text ? instruction.text : '');
            const distanceMeters = Number(instruction && instruction.distance);
            if (!text) {
                return null;
            }
            return {
                text,
                distanceLabel: Number.isFinite(distanceMeters) && distanceMeters > 0
                    ? (formatter && typeof formatter.formatDistance === 'function'
                        ? formatter.formatDistance(distanceMeters)
                        : `${Math.round(distanceMeters)}m`)
                    : '',
                latLng: resolveInstructionLatLng(route, instruction)
            };
        })
        .filter(Boolean);
}

function renderDestinationRouteGuidance(index, routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors = []) {
    document.querySelectorAll('.destination-card').forEach((card, cardIndex) => {
        const panel = card.querySelector('[data-route-guidance]');
        if (!panel) {
            return;
        }
        if (cardIndex !== index) {
            panel.innerHTML = '';
            panel.classList.remove('active');
            return;
        }

        const routeList = Array.isArray(routes) ? routes : [];
        const hasRoutes = routeList.length > 0;
        const safeSelectedRouteIndex = hasRoutes
            ? Math.max(0, Math.min(Number(selectedRouteIndex) || 0, routeList.length - 1))
            : -1;
        const route = hasRoutes ? routeList[safeSelectedRouteIndex] : null;
        const selectedRouteColor = routeColors[safeSelectedRouteIndex] || getRouteColorByIndex(safeSelectedRouteIndex);
        const summary = route && route.summary ? route.summary : null;
        const distanceLabel = summary && Number.isFinite(Number(summary.totalDistance))
            ? (formatter && typeof formatter.formatDistance === 'function'
                ? formatter.formatDistance(Number(summary.totalDistance))
                : `${Math.round(Number(summary.totalDistance))}m`)
            : '-';
        const durationLabel = summary && Number.isFinite(Number(summary.totalTime))
            ? formatDurationText(Number(summary.totalTime))
            : '-';
        const steps = buildRouteInstructionItems(route, formatter);

        const title = document.createElement('div');
        title.className = 'route-guidance-title';
        title.textContent = `経路案内（${transportMode === 'walking' ? '徒歩' : '車'}）`;

        const summaryEl = document.createElement('div');
        summaryEl.className = 'route-guidance-summary';
        summaryEl.textContent = `距離: ${distanceLabel} / 所要時間: ${durationLabel}`;

        const selectedLabel = document.createElement('div');
        selectedLabel.className = 'route-selected-label';
        selectedLabel.textContent = hasRoutes
            ? `現在選択: 候補${safeSelectedRouteIndex + 1}`
            : '現在選択: なし';

        const buttons = document.createElement('div');
        buttons.className = 'route-option-buttons';
        if (routeList.length > 1) {
            routeList.forEach((_, routeIndex) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'route-option-button';
                if (routeIndex === safeSelectedRouteIndex) {
                    button.classList.add('active');
                }
                const color = routeColors[routeIndex] || getRouteColorByIndex(routeIndex);
                button.innerHTML = `<span class="route-color-chip" style="background: ${color};"></span>候補${routeIndex + 1}`;
                button.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    if (typeof onSelectRouteIndex === 'function') {
                        onSelectRouteIndex(routeIndex);
                    }
                });
                buttons.appendChild(button);
            });
        }

        const list = document.createElement('ol');
        list.className = 'route-guidance-steps';
        if (steps.length === 0) {
            const emptyItem = document.createElement('li');
            emptyItem.textContent = '案内情報を取得できませんでした。';
            list.appendChild(emptyItem);
        } else {
            steps.forEach((step) => {
                const item = document.createElement('li');
                item.textContent = step.distanceLabel ? `${step.text}（${step.distanceLabel}）` : step.text;
                if (step.latLng) {
                    item.dataset.stepLat = step.latLng.lat;
                    item.dataset.stepLon = step.latLng.lng;
                    item.classList.add('route-guidance-step-clickable');
                    item.title = 'クリックすると地図上の位置を表示';
                    item.addEventListener('click', (event) => {
                        event.preventDefault();
                        event.stopPropagation();
                        list.querySelectorAll('.route-guidance-step-clickable').forEach((el) => {
                            el.classList.remove('selected');
                        });
                        item.classList.add('selected');
                        focusRouteStepOnMap(step, selectedRouteColor);
                    });
                }
                list.appendChild(item);
            });
        }

        panel.innerHTML = '';
        panel.appendChild(title);
        panel.appendChild(selectedLabel);
        panel.appendChild(summaryEl);
        if (routeList.length > 1) {
            panel.appendChild(buttons);
        }
        panel.appendChild(list);
        panel.classList.add('active');
    });
}

function clearSelectedEmergencyShelterRouteGuidance() {
    const panel = document.getElementById('selectedShelterRouteGuidance');
    if (!panel) { return; }
    panel.innerHTML = '';
    panel.classList.remove('active');
}

function clearUserDestRouteGuidance() {
    const panel = document.getElementById('userDestRouteGuidance');
    if (!panel) { return; }
    panel.innerHTML = '';
    panel.classList.remove('active');
}

// ── 共通: ルート案内を指定パネルへ描画 ────────────────────────────────────
function _renderRouteGuidanceToPanelId(panelId, routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors = []) {
    const panel = document.getElementById(panelId);
    if (!panel) { return; }

    const routeList = Array.isArray(routes) ? routes : [];
    const hasRoutes = routeList.length > 0;
    const safeSelectedRouteIndex = hasRoutes
        ? Math.max(0, Math.min(Number(selectedRouteIndex) || 0, routeList.length - 1))
        : -1;
    const route = hasRoutes ? routeList[safeSelectedRouteIndex] : null;
    const selectedRouteColor = routeColors[safeSelectedRouteIndex] || getRouteColorByIndex(safeSelectedRouteIndex);
    const summary = route && route.summary ? route.summary : null;
    const distanceLabel = summary && Number.isFinite(Number(summary.totalDistance))
        ? (formatter && typeof formatter.formatDistance === 'function'
            ? formatter.formatDistance(Number(summary.totalDistance))
            : `${Math.round(Number(summary.totalDistance))}m`)
        : '-';
    const durationLabel = summary && Number.isFinite(Number(summary.totalTime))
        ? formatDurationText(Number(summary.totalTime))
        : '-';
    const steps = buildRouteInstructionItems(route, formatter);

    const title = document.createElement('div');
    title.className = 'route-guidance-title';
    title.textContent = `経路案内（${transportMode === 'walking' ? '徒歩' : '車'}）`;

    const selectedLabel = document.createElement('div');
    selectedLabel.className = 'route-selected-label';
    selectedLabel.textContent = hasRoutes
        ? `現在選択: 候補${safeSelectedRouteIndex + 1}`
        : '現在選択: なし';

    const summaryEl = document.createElement('div');
    summaryEl.className = 'route-guidance-summary';
    summaryEl.textContent = `距離: ${distanceLabel} / 所要時間: ${durationLabel}`;

    const buttons = document.createElement('div');
    buttons.className = 'route-option-buttons';
    if (routeList.length > 1) {
        routeList.forEach((_, routeIndex) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'route-option-button';
            if (routeIndex === safeSelectedRouteIndex) {
                button.classList.add('active');
            }
            const color = routeColors[routeIndex] || getRouteColorByIndex(routeIndex);
            button.innerHTML = `<span class="route-color-chip" style="background: ${color};"></span>候補${routeIndex + 1}`;
            button.addEventListener('click', (event) => {
                event.preventDefault();
                event.stopPropagation();
                if (typeof onSelectRouteIndex === 'function') {
                    onSelectRouteIndex(routeIndex);
                }
            });
            buttons.appendChild(button);
        });
    }

    const list = document.createElement('ol');
    list.className = 'route-guidance-steps';
    if (steps.length === 0) {
        const emptyItem = document.createElement('li');
        emptyItem.textContent = '案内情報を取得できませんでした。';
        list.appendChild(emptyItem);
    } else {
        steps.forEach((step) => {
            const item = document.createElement('li');
            item.textContent = step.distanceLabel ? `${step.text}（${step.distanceLabel}）` : step.text;
            if (step.latLng) {
                item.dataset.stepLat = step.latLng.lat;
                item.dataset.stepLon = step.latLng.lng;
                item.classList.add('route-guidance-step-clickable');
                item.title = 'クリックすると地図上の位置を表示';
                item.addEventListener('click', (event) => {
                    event.preventDefault();
                    event.stopPropagation();
                    list.querySelectorAll('.route-guidance-step-clickable').forEach((el) => {
                        el.classList.remove('selected');
                    });
                    item.classList.add('selected');
                    focusRouteStepOnMap(step, selectedRouteColor);
                });
            }
            list.appendChild(item);
        });
    }

    panel.innerHTML = '';
    panel.appendChild(title);
    panel.appendChild(selectedLabel);
    panel.appendChild(summaryEl);
    if (routeList.length > 1) {
        panel.appendChild(buttons);
    }
    panel.appendChild(list);
    panel.classList.add('active');
}

function renderSelectedEmergencyShelterRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors = []) {
    _renderRouteGuidanceToPanelId('selectedShelterRouteGuidance', routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors);
}

function renderUserDestRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors = []) {
    _renderRouteGuidanceToPanelId('userDestRouteGuidance', routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors);
}

// ── ナビ中ステップハイライト ───────────────────────────────────────────────
function _highlightNavStepInPanel(panelEl, lat, lon) {
    if (!panelEl) return;
    const items = panelEl.querySelectorAll('li[data-step-lat]');
    if (items.length === 0) return;

    let minDist = Infinity;
    let closestItem = null;
    items.forEach((item) => {
        const sLat = parseFloat(item.dataset.stepLat);
        const sLon = parseFloat(item.dataset.stepLon);
        const dlat = (lat - sLat) * 111000;
        const dlon = (lon - sLon) * 111000 * Math.cos(lat * Math.PI / 180);
        const dist = Math.sqrt(dlat * dlat + dlon * dlon);
        if (dist < minDist) { minDist = dist; closestItem = item; }
    });
    if (!closestItem) return;
    if (closestItem.classList.contains('nav-step-current')) return; // 変化なし
    items.forEach(el => el.classList.remove('nav-step-current'));
    closestItem.classList.add('nav-step-current');
    closestItem.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function updateNavStepHighlight(lat, lon) {
    let panelEl = null;
    if (typeof activeNavigatingIndex !== 'undefined' && activeNavigatingIndex !== null) {
        const cards = document.querySelectorAll('.destination-card');
        const card = cards[activeNavigatingIndex];
        if (card) panelEl = card.querySelector('[data-route-guidance]');
    } else if (typeof userDestination !== 'undefined' && userDestination) {
        panelEl = document.getElementById('userDestRouteGuidance');
    } else {
        panelEl = document.getElementById('selectedShelterRouteGuidance');
    }
    _highlightNavStepInPanel(panelEl, lat, lon);
}

function clearNavStepHighlight() {
    document.querySelectorAll('li.nav-step-current').forEach(el => el.classList.remove('nav-step-current'));
}

function drawRouteTo(lat, lon, options = {}) {
    if (!currentLocation) {
        alert('先に現在地を取得してください');
        return false;
    }

    const transportMode = document.getElementById('transportMode').value;
    const routeProfile = transportMode === 'walking' ? 'walking' : 'driving';
    const serviceUrl = OSRM_SERVICE_URLS[routeProfile];
    const useCustomRouteRendering = typeof options.onRoutesAvailable === 'function';
    let routeDrawIndex = 0;
    let routeFormatter = null;

    // 既存のルートを削除
    if (routingControl) {
        map.removeControl(routingControl);
    }
    clearSelectedRouteHighlight();
    clearRouteCandidateLayers();
    clearRouteStepFocusMarker();

    const routingOptions = {
        waypoints: [
            L.latLng(currentLocation.lat, currentLocation.lon),
            L.latLng(lat, lon)
        ],
        language: 'ja',
        showAlternatives: true,
        addWaypoints: false,
        routeWhileDragging: false,
        fitSelectedRoutes: true,
        show: false,  // ルート説明パネルを非表示
        routeLine: (route, lineOptions) => {
            const color = ROUTE_COLOR_PALETTE[routeDrawIndex % ROUTE_COLOR_PALETTE.length];
            routeDrawIndex += 1;
            const isAlternative = Boolean(lineOptions && lineOptions.isAlternative);
            const weight = isAlternative ? 5 : 7;
            const opacity = isAlternative ? 0.68 : 0.86;

            return L.Routing.line(route, {
                ...lineOptions,
                addWaypoints: false,
                extendToWaypoints: true,
                // 避難先候補カード連動時のみ既定線を透明化し、自前描画を使う
                styles: [{ color, weight, opacity: useCustomRouteRendering ? 0 : opacity }],
                missingRouteStyles: [{
                    color,
                    weight: weight - 1,
                    opacity: useCustomRouteRendering ? 0 : Math.max(0.35, opacity - 0.2),
                    dashArray: '4,8'
                }]
            });
        }
    };

    if (L.Routing && typeof L.Routing.Formatter === 'function') {
        const formatter = new L.Routing.Formatter({
            language: 'ja',
            units: 'metric'
        });
        if (typeof formatter.formatInstruction === 'function') {
            const originalFormatInstruction = formatter.formatInstruction.bind(formatter);
            formatter.formatInstruction = function(instruction, i) {
                const message = originalFormatInstruction(instruction, i);
                return translateInstructionToJapanese(message);
            };
        }
        routingOptions.formatter = formatter;
        routeFormatter = formatter;
    }

    try {
        const optionsWithRouter = {
            ...routingOptions,
            router: L.Routing.osrmv1({
                serviceUrl,
                profile: routeProfile
            })
        };
        routingControl = L.Routing.control(optionsWithRouter).addTo(map);
    } catch (error) {
        console.error(`Routing control initialization failed (serviceUrl=${serviceUrl}):`, error);
        return false;
    }

    if ((options.onRouteSummary || options.onRouteFound || options.onRoutesAvailable || options.onRouteError) && routingControl && typeof routingControl.on === 'function') {
        let latestRoutes = [];
        let selectedRouteIndexState = 0;
        const routeColorLookup = new Map();
        const getRouteColor = (route, routeIndex) => {
            if (!routeColorLookup.has(route)) {
                routeColorLookup.set(route, getRouteColorByIndex(routeColorLookup.size || routeIndex));
            }
            return routeColorLookup.get(route);
        };
        const emitRouteState = (event) => {
            const routeCandidates = event && Array.isArray(event.routes) ? event.routes : latestRoutes;
            latestRoutes = routeCandidates;
            routeCandidates.forEach((route, routeIndex) => {
                getRouteColor(route, routeIndex);
            });
            const selectedRoute = (event && event.route) || routeCandidates[0];
            if (!selectedRoute || !selectedRoute.summary) {
                return;
            }
            const internalRoutes = (routingControl && Array.isArray(routingControl._routes))
                ? routingControl._routes
                : routeCandidates;
            let selectedRouteIndex = Number.isFinite(Number(event && event.routeIndex))
                ? Number(event.routeIndex)
                : internalRoutes.indexOf(selectedRoute);
            if (!Number.isFinite(selectedRouteIndex) || selectedRouteIndex < 0) {
                selectedRouteIndex = routeCandidates.indexOf(selectedRoute);
            }
            if (!Number.isFinite(selectedRouteIndex) || selectedRouteIndex < 0) {
                selectedRouteIndex = selectedRouteIndexState;
            }
            selectedRouteIndex = Math.max(0, Math.min(selectedRouteIndex, routeCandidates.length - 1));
            selectedRouteIndexState = selectedRouteIndex;
            const selectRouteIndex = (routeIndex) => {
                if (!routingControl) {
                    return;
                }
                const normalizedRouteIndex = Math.max(0, Math.min(routeIndex, routeCandidates.length - 1));
                selectedRouteIndexState = normalizedRouteIndex;

                // Leaflet Routing Machine の selectRoute 呼び出しで線が消える環境があるため、
                // カード表示のみ切り替えて地図描画は維持する。
                if (options.onRoutesAvailable) {
                    const routeColors = routeCandidates.map((route, idx) => getRouteColor(route, idx));
                    options.onRoutesAvailable({
                        routes: routeCandidates,
                        selectedRouteIndex: normalizedRouteIndex,
                        selectedRouteColor: routeColors[normalizedRouteIndex] || getRouteColorByIndex(normalizedRouteIndex),
                        routeColors,
                        formatter: routeFormatter,
                        transportMode,
                        selectRouteIndex
                    });
                }
            };

            if (options.onRouteSummary) {
                options.onRouteSummary({
                    distanceMeters: selectedRoute.summary.totalDistance,
                    durationSeconds: selectedRoute.summary.totalTime,
                    transportMode
                });
            }
            if (options.onRouteFound) {
                options.onRouteFound({
                    route: selectedRoute,
                    formatter: routeFormatter,
                    transportMode
                });
            }
            if (options.onRoutesAvailable) {
                const routeColors = routeCandidates.map((route, idx) => getRouteColor(route, idx));
                options.onRoutesAvailable({
                    routes: routeCandidates,
                    selectedRouteIndex,
                    selectedRouteColor: routeColors[selectedRouteIndex] || getRouteColorByIndex(selectedRouteIndex),
                    routeColors,
                    formatter: routeFormatter,
                    transportMode,
                    selectRouteIndex
                });
            }
        };

        routingControl.on('routesfound', (event) => {
            emitRouteState(event);
        });
        routingControl.on('routeselected', (event) => {
            emitRouteState(event);
        });
        routingControl.on('routingerror', () => {
            if (options.onRouteError) {
                options.onRouteError();
            }
        });
    }

    return true;
}

function scrollDestinationCardIntoView(index) {
    const card = document.querySelector(`.destination-card[data-index="${index}"]`);
    if (!card) {
        return;
    }
    card.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
        inline: 'nearest'
    });
}

function showRoute(destination, index, options = {}) {
    setSelectedDestinationCard(index);
    updateNavigatingState(index);
    if (options.ensureCardVisible) {
        scrollDestinationCardIntoView(index);
    }

    // ルート取得前にナビモードへ目的地を即時通知（navPanel を即表示）
    if (typeof onNavRouteSelected === 'function') {
        onNavRouteSelected(null, destination);
    }

    const routed = drawRouteTo(destination.lat, destination.lon, {
        onRoutesAvailable: ({ routes, selectedRouteIndex, selectedRouteColor, routeColors, formatter, transportMode, selectRouteIndex }) => {
            // ナビモードにルート・目的地を通知
            if (typeof onNavRouteSelected === 'function') {
                onNavRouteSelected(routes[selectedRouteIndex], destination);
            }
            renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex);
            renderDestinationRouteGuidance(
                index,
                routes,
                selectedRouteIndex,
                formatter,
                transportMode,
                selectRouteIndex,
                routeColors
            );
            // 現在地〜目的地が見えるように地図範囲を調整
            if (currentLocation) {
                const selectedRoute = routes[selectedRouteIndex];
                if (selectedRoute && Array.isArray(selectedRoute.coordinates) && selectedRoute.coordinates.length > 0) {
                    const bounds = L.latLngBounds([[currentLocation.lat, currentLocation.lon]]);
                    selectedRoute.coordinates.forEach(coord => bounds.extend(coord));
                    map.fitBounds(bounds, { padding: [60, 60], animate: true });
                } else {
                    map.fitBounds([
                        [currentLocation.lat, currentLocation.lon],
                        [destination.lat, destination.lon]
                    ], { padding: [60, 60], animate: true });
                }
            }
        },
        onRouteError: () => {
            clearSelectedRouteHighlight();
            clearRouteCandidateLayers();
            clearRouteStepFocusMarker();
            renderDestinationRouteGuidance(index, [], 0, null, document.getElementById('transportMode').value);
        }
    });
    if (!routed) {
        return;
    }

    // 案内中マーカーを強調 — 基本色（意味色）は維持し、外枠とサイズで選択状態を表現
    destinationMarkers.forEach((marker, i) => {
        const base = destinationMarkerBaseStyles[i];
        if (!base) return;
        if (i === index) {
            marker.setStyle({
                color: '#ffffff',          // 白い選択リング
                fillColor: base.fillColor, // 意味色（金/緑/オレンジ/赤）をそのまま保持
                fillOpacity: 0.95,
                radius: base.radius + 4,   // 少し大きく
                weight: 5                  // 太い外枠
            });
            if (typeof marker.bringToFront === 'function') {
                marker.bringToFront();
            }
            marker.openPopup();
        } else {
            // 他のマーカー: 元の意味色・サイズに戻す
            marker.setStyle(base);
        }
    });
}

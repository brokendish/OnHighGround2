/**
 * routing.js — ルーティング・経路案内
 *
 * - Leaflet Routing Machine の日本語ロケール設定
 * - drawRouteTo: OSRM を使ったルート描画
 * - showRoute: 避難先候補のルート表示（地図 + カード連動）
 * - 経路ステップのレンダリング・フォーカス
 */

// ── 経路タップ選択用マップクリックハンドラ ────────────────────────────────
// Leaflet のレイヤーイベントに依存せず、マップクリック時にピクセル距離で
// 最近傍の非選択経路を検出して選択する。
let _routeSelectHandler = null; // 登録中のハンドラ参照

function _clearRouteSelectHandler() {
    if (_routeSelectHandler) {
        map.off('click', _routeSelectHandler);
        map.getContainer().style.cursor = '';
        _routeSelectHandler = null;
    }
    map.off('mousemove', _routeHoverHandler);
}

let _routeHoverHandler = null; // カーソル変更用

function _setupRouteSelectHandler(routeList, selectedRouteIndex, onSelect) {
    _clearRouteSelectHandler();
    if (!onSelect || routeList.length <= 1) return;

    const CLICK_PX = 12;

    // 非選択経路の座標リスト
    const candidates = routeList
        .map((r, i) => ({ coords: r.coordinates, index: i }))
        .filter(c => c.index !== selectedRouteIndex);

    function nearestCandidateIndex(containerPt) {
        let minDist = Infinity;
        let found = -1;
        for (const cand of candidates) {
            for (let i = 0; i < cand.coords.length - 1; i++) {
                const a = map.latLngToContainerPoint(cand.coords[i]);
                const b = map.latLngToContainerPoint(cand.coords[i + 1]);
                const d = _pointToSegmentDist(containerPt, a, b);
                if (d < minDist) { minDist = d; found = cand.index; }
            }
        }
        return minDist <= CLICK_PX ? found : -1;
    }

    _routeHoverHandler = (e) => {
        const pt = map.latLngToContainerPoint(e.latlng);
        let minDist = Infinity;
        for (const cand of candidates) {
            for (let i = 0; i < cand.coords.length - 1; i++) {
                const a = map.latLngToContainerPoint(cand.coords[i]);
                const b = map.latLngToContainerPoint(cand.coords[i + 1]);
                const d = _pointToSegmentDist(pt, a, b);
                if (d < minDist) minDist = d;
            }
        }
        map.getContainer().style.cursor = minDist <= CLICK_PX ? 'pointer' : '';
    };

    _routeSelectHandler = (e) => {
        const pt = map.latLngToContainerPoint(e.latlng);
        const idx = nearestCandidateIndex(pt);
        if (idx >= 0) onSelect(idx);
    };

    map.on('mousemove', _routeHoverHandler);
    map.on('click',     _routeSelectHandler);
}

// 点P から線分AB への最短距離（ピクセル）
function _pointToSegmentDist(p, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const lenSq = dx * dx + dy * dy;
    if (lenSq === 0) return Math.hypot(p.x - a.x, p.y - a.y);
    let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy));
}

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
        // 方角
        [/\bHead north\b/gi, '北へ進む'],
        [/\bHead northeast\b/gi, '北東へ進む'],
        [/\bHead east\b/gi, '東へ進む'],
        [/\bHead southeast\b/gi, '南東へ進む'],
        [/\bHead south\b/gi, '南へ進む'],
        [/\bHead southwest\b/gi, '南西へ進む'],
        [/\bHead west\b/gi, '西へ進む'],
        [/\bHead northwest\b/gi, '北西へ進む'],
        // 直進・カーブ
        [/\bContinue\b/gi, '直進'],
        [/\bBear slight right\b/gi, 'やや右へ'],
        [/\bBear slight left\b/gi, 'やや左へ'],
        [/\bBear right\b/gi, 'やや右へ'],
        [/\bBear left\b/gi, 'やや左へ'],
        [/\bSlight right\b/gi, 'やや右へ'],
        [/\bSlight left\b/gi, 'やや左へ'],
        [/\bKeep right\b/gi, '右側を進む'],
        [/\bKeep left\b/gi, '左側を進む'],
        // 折れ
        [/\bTurn right\b/gi, '右折'],
        [/\bSharp right\b/gi, '鋭く右折'],
        [/\bTurn left\b/gi, '左折'],
        [/\bSharp left\b/gi, '鋭く左折'],
        [/\bTurn around\b/gi, 'Uターン'],
        // 合流・ランプ
        [/\bMerge\b/gi, '合流'],
        [/\bTake the ramp on the right\b/gi, '右のランプへ'],
        [/\bTake the ramp on the left\b/gi, '左のランプへ'],
        [/\bTake the ramp\b/gi, 'ランプへ'],
        [/\bTake exit\b/gi, '出口へ'],
        // 到着
        [/\bYou have arrived at your destination, on the right\b/gi, '目的地は右側です'],
        [/\bYou have arrived at your destination, on the left\b/gi, '目的地は左側です'],
        [/\bYou have arrived at your destination\b/gi, '目的地に到着しました'],
        [/\bWaypoint reached\b/gi, '経由地に到着'],
        [/\bDestination reached\b/gi, '目的地に到着'],
        // 接続詞
        [/\bonto\b/gi, 'へ'],
        [/\bon\b/gi, 'を進む'],
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
    _clearRouteSelectHandler();
    routeCandidateLayers.forEach((layer) => {
        if (layer && map && map.hasLayer(layer)) {
            map.removeLayer(layer);
        }
    });
    routeCandidateLayers = [];
    if (typeof clearRouteRiskOutlines === 'function') clearRouteRiskOutlines();
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

function renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, onSelect) {
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
            weight: isSelected ? 7 : 6,
            opacity: isSelected ? 0.95 : 0.45,
            lineCap: 'round',
            lineJoin: 'round',
            interactive: false  // クリックはマップハンドラで一元管理
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
            lineJoin: 'round',
            interactive: false   // クリックを非選択経路に通過させる
        }).addTo(map);
        const line = L.polyline(selectedRoute.coordinates, {
            color: selectedColor,
            weight: 7,
            opacity: 0.98,
            lineCap: 'round',
            lineJoin: 'round',
            interactive: false   // クリックを非選択経路に通過させる
        }).addTo(map);
        outline.bringToFront();
        line.bringToFront();
        selectedRouteHighlightLayers = [outline, line];
    }

    // マップクリックで非選択経路をタップ選択
    _setupRouteSelectHandler(routeList, selectedRouteIndex, onSelect);

    // 選択中ルートの危険区間アウトラインを描画
    if (typeof drawRouteRiskOutlines === 'function') {
        const selRoute = routeList[selectedRouteIndex];
        if (selRoute
                && Array.isArray(selRoute.coordinates) && selRoute.coordinates.length >= 2
                && Array.isArray(selRoute.__riskSampledPoints) && selRoute.__riskSampledPoints.length > 0) {
            drawRouteRiskOutlines(selRoute.coordinates, selRoute.__riskSampledPoints, 7);
        }
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
            const forcedText = instruction && (instruction._displayText || instruction.displayText);
            const text = forcedText || (formatter && typeof formatter.formatInstruction === 'function'
                ? formatter.formatInstruction(instruction, index)
                : translateInstructionToJapanese(instruction && instruction.text ? instruction.text : ''));
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

function buildRouteCandidateSummary(route, routeIndex, formatter) {
    const label = route?.__displayLabel || `候補${routeIndex + 1}`;
    const reason = route?.__displayReason || '';
    const score = Number(route?.__safetyScore);
    const distance = Number(route?.summary?.totalDistance ?? route?.totalDistance);
    const duration = Number(route?.summary?.totalTime ?? route?.totalTime);
    const distanceLabel = Number.isFinite(distance)
        ? (formatter && typeof formatter.formatDistance === 'function'
            ? formatter.formatDistance(distance)
            : `${Math.round(distance)}m`)
        : '-';
    const durationLabel = Number.isFinite(duration) ? formatDurationText(duration) : '-';
    const featureLabels = buildRouteFeatureLabels(route, formatter);
    const safetyLabel = featureLabels.join(' / ');
    const riskLabel = _buildRiskLabel(route?.__riskSummary);
    return {
        label,
        reason,
        scoreLabel: Number.isFinite(score) ? `安全スコア ${Math.round(score)}` : '',
        safetyLabel,
        riskLabel,
        metricLabel: `${distanceLabel} / ${durationLabel}`
    };
}

function buildRouteFeatureLabels(route, formatter) {
    const features = route?.__routeFeatures || {};
    const labels = [];
    if (features.hasCrossing) labels.push('横断あり');
    if (features.hasSignalizedCrossing) {
        labels.push('信号横断あり');
    } else if (features.hasMarkedCrossing) {
        labels.push('横断歩道あり');
    }
    const addedDistance = Number(features.addedDistanceM || 0);
    if (addedDistance >= 15) {
        labels.push(`+${formatter && typeof formatter.formatDistance === 'function'
            ? formatter.formatDistance(addedDistance)
            : `${Math.round(addedDistance)}m`}`);
    }
    return labels;
}

// ── ルート危険度表示 ──────────────────────────────────────────────────────────

const ROUTE_RISK_LEVEL_TEXT = { safe: '安全', caution: '注意', danger: '危険' };
const ROUTE_RISK_LEVEL_ICON = { safe: '🟢', caution: '🟡', danger: '🔴' };

function _buildRiskLabel(riskSummary) {
    if (!riskSummary || typeof riskSummary.safety_score !== 'number') return '';
    const score = Math.round(riskSummary.safety_score);
    const level = riskSummary.risk_level || 'safe';
    const text = ROUTE_RISK_LEVEL_TEXT[level] || level;
    return `安全度 ${score}（${text}）`;
}

function _appendRouteRiskBlock(panel, route) {
    const riskSummary = route?.__riskSummary;
    if (!riskSummary) return;

    const notes = riskSummary.risk_summary?.notes || [];
    const score = Math.round(riskSummary.safety_score ?? 100);
    const level = riskSummary.risk_level || 'safe';

    const block = document.createElement('div');
    block.className = `route-risk-block ${level}`;

    const icon = ROUTE_RISK_LEVEL_ICON[level] || '';
    const text = ROUTE_RISK_LEVEL_TEXT[level] || level;
    const header = document.createElement('div');
    header.className = 'route-risk-header';
    header.innerHTML =
        `${icon} ルート危険度: <span class="route-risk-score">${text}（安全度 ${score}）</span>`;
    block.appendChild(header);

    if (notes.length > 0) {
        const list = document.createElement('ul');
        list.className = 'route-risk-notes';
        notes.forEach(note => {
            const li = document.createElement('li');
            li.textContent = note;
            list.appendChild(li);
        });
        block.appendChild(list);
    }

    // 危険・注意区間がある場合のみ凡例を表示（安全ルートでは地図上に色線が出ないため省略）
    if (level !== 'safe') {
        const legend = document.createElement('div');
        legend.className = 'route-risk-outline-legend';
        legend.innerHTML =
            '<span><span class="risk-outline-swatch danger"></span>赤＝危険区間</span>' +
            '<span><span class="risk-outline-swatch caution"></span>黄＝この先／通過直後に注意</span>';
        block.appendChild(legend);
    }

    panel.appendChild(block);
}

function appendRouteSafetyNotice(panel, routes) {
    const routeList = Array.isArray(routes) ? routes : [];
    if (routeList.length === 0) return;
    if (!routeList.every(route => route?.__crossingRisk?.hasUnsafeCrossing)) return;
    const notice = document.createElement('div');
    notice.className = 'route-safety-warning';
    notice.textContent = '安全な横断を含む代替ルートが見つかりませんでした';
    panel.appendChild(notice);
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
            routeList.forEach((candidateRoute, routeIndex) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'route-option-button';
                if (routeIndex === safeSelectedRouteIndex) {
                    button.classList.add('active');
                }
                const color = routeColors[routeIndex] || getRouteColorByIndex(routeIndex);
                const routeSummary = buildRouteCandidateSummary(candidateRoute, routeIndex, formatter);
                const subText = [routeSummary.metricLabel, routeSummary.safetyLabel, routeSummary.riskLabel].filter(Boolean).join(' / ');
                button.innerHTML = `
                    <span class="route-color-chip" style="background: ${color};"></span>
                    <span class="route-option-main">${routeSummary.label}</span>
                    <span class="route-option-sub">${subText}</span>
                `;
                button.title = [routeSummary.reason, routeSummary.scoreLabel, routeSummary.riskLabel].filter(Boolean).join(' / ');
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
        if (route?.__displayReason) {
            const reasonEl = document.createElement('div');
            reasonEl.className = route?.__crossingRisk?.hasUnsafeCrossing ? 'route-safety-warning' : 'route-safety-reason';
            reasonEl.textContent = route.__displayReason;
            panel.appendChild(reasonEl);
        }
        _appendRouteRiskBlock(panel, route);
        appendRouteSafetyNotice(panel, routeList);
        if (routeList.length > 1) {
            panel.appendChild(buttons);
        }
        panel.appendChild(list);
        panel.classList.add('active');

        // フロートウィンドウにも同じ経路案内を表示
        _renderRouteGuidanceToPanelId('shelter-card-route-guidance', routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors);
    });
}

function clearSelectedEmergencyShelterRouteGuidance() {
    const panel = document.getElementById('selectedShelterRouteGuidance');
    if (panel) { panel.innerHTML = ''; panel.classList.remove('active'); }
    const cardPanel = document.getElementById('shelter-card-route-guidance');
    if (cardPanel) { cardPanel.innerHTML = ''; cardPanel.classList.remove('active'); }
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
    const isCompactInfoPanel = panelId === 'shelter-card-route-guidance';

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
        routeList.forEach((candidateRoute, routeIndex) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'route-option-button';
            if (routeIndex === safeSelectedRouteIndex) {
                button.classList.add('active');
            }
            const color = routeColors[routeIndex] || getRouteColorByIndex(routeIndex);
            const routeSummary = buildRouteCandidateSummary(candidateRoute, routeIndex, formatter);
            const subText = [routeSummary.metricLabel, routeSummary.safetyLabel, routeSummary.riskLabel].filter(Boolean).join(' / ');
            button.innerHTML = `
                <span class="route-color-chip" style="background: ${color};"></span>
                <span class="route-option-main">${routeSummary.label}</span>
                <span class="route-option-sub">${subText}</span>
            `;
            button.title = [routeSummary.reason, routeSummary.scoreLabel, routeSummary.riskLabel].filter(Boolean).join(' / ');
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
    if (!isCompactInfoPanel) {
        panel.appendChild(title);
        panel.appendChild(selectedLabel);
        panel.appendChild(summaryEl);
        if (route?.__displayReason) {
            const reasonEl = document.createElement('div');
            reasonEl.className = route?.__crossingRisk?.hasUnsafeCrossing ? 'route-safety-warning' : 'route-safety-reason';
            reasonEl.textContent = route.__displayReason;
            panel.appendChild(reasonEl);
        }
        _appendRouteRiskBlock(panel, route);
        appendRouteSafetyNotice(panel, routeList);
        if (routeList.length > 1) {
            panel.appendChild(buttons);
        }
    }
    panel.appendChild(list);
    panel.classList.add('active');

    // パネル再描画後にナビ中なら保存済みステップを即時復元（開閉時のズレ防止）
    const _navMode = (typeof navigationMode !== 'undefined') ? navigationMode : null;
    if (_navMode === 'navigation_active' || _navMode === 'navigation_warning' || _navMode === 'navigation_paused') {
        _applyStoredNavStep(panel);
    }
}

function renderSelectedEmergencyShelterRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors = []) {
    _renderRouteGuidanceToPanelId('selectedShelterRouteGuidance', routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors);
    _renderRouteGuidanceToPanelId('shelter-card-route-guidance', routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors);
}

// 最後の renderUserDestRouteGuidance 呼び出しパラメータを保持（再描画用）
let _lastUserDestRenderParams = null;

function renderUserDestRouteGuidance(routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors = []) {
    _lastUserDestRenderParams = { routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors };
    _renderRouteGuidanceToPanelId('userDestRouteGuidance', routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors);
    _renderRouteGuidanceToPanelId('shelter-card-route-guidance', routes, selectedRouteIndex, formatter, transportMode, onSelectRouteIndex, routeColors);
}

/** shelter-card-route-guidance を最後の userDest パラメータで再描画する */
function rerenderUserDestFloatCard() {
    if (!_lastUserDestRenderParams) return;
    const p = _lastUserDestRenderParams;
    _renderRouteGuidanceToPanelId('shelter-card-route-guidance', p.routes, p.selectedRouteIndex, p.formatter, p.transportMode, p.onSelectRouteIndex, p.routeColors);
}

// ── ナビ中ステップハイライト ───────────────────────────────────────────────

// 保存済みステップキーをパネルに即時適用（パネル再描画後の復元用・音声なし）
function _applyStoredNavStep(panelEl) {
    const key = (typeof navCurrentStepKey !== 'undefined') ? navCurrentStepKey : null;
    if (!panelEl || !key) return;
    const items = panelEl.querySelectorAll('li[data-step-lat]');
    let target = null;
    items.forEach(item => {
        if (`${item.dataset.stepLat},${item.dataset.stepLon}` === key) target = item;
    });
    if (!target) return;
    items.forEach(el => el.classList.remove('nav-step-current'));
    target.classList.add('nav-step-current');
    target.scrollIntoView({ behavior: 'instant', block: 'nearest' });
    console.log(`[nav-sync] restored stepKey=${key}`);
}

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
    // ステップ変化時に navCurrentStepKey を更新（パネル再描画後の同期用）
    const newKey = `${closestItem.dataset.stepLat},${closestItem.dataset.stepLon}`;
    if (typeof navCurrentStepKey !== 'undefined' && navCurrentStepKey !== newKey) {
        navCurrentStepKey = newKey;
        console.log(`[nav-sync] stepKey=${newKey} dist=${Number.isFinite(minDist) ? Math.round(minDist) : '?'}m`);
    }
    // ステップ変化時に音声・テキスト案内（minDist を距離として渡す）
    if (typeof voiceNav !== 'undefined') {
        const rawText = closestItem.textContent.split('（')[0].trim();
        const stepId  = (closestItem.dataset.stepLat || '') + ',' + (closestItem.dataset.stepLon || '');
        voiceNav.announceStep(rawText, stepId, Number.isFinite(minDist) ? minDist : null);
    }
}

function updateNavStepHighlight(lat, lon) {
    let panelEl = null;
    if (typeof activeNavigatingIndex !== 'undefined' && activeNavigatingIndex !== null) {
        const cards = document.querySelectorAll('.destination-card');
        const card = cards[activeNavigatingIndex];
        if (card) panelEl = card.querySelector('[data-route-guidance]');
        // フロートウィンドウも同時ハイライト
        _highlightNavStepInPanel(document.getElementById('shelter-card-route-guidance'), lat, lon);
    } else if (typeof userDestination !== 'undefined' && userDestination) {
        panelEl = document.getElementById('userDestRouteGuidance');
        // フロートウィンドウも同時ハイライト
        _highlightNavStepInPanel(document.getElementById('shelter-card-route-guidance'), lat, lon);
    } else {
        panelEl = document.getElementById('selectedShelterRouteGuidance');
        // 地図カードのルート案内も同時にハイライト
        _highlightNavStepInPanel(document.getElementById('shelter-card-route-guidance'), lat, lon);
    }
    _highlightNavStepInPanel(panelEl, lat, lon);
}

function clearNavStepHighlight() {
    document.querySelectorAll('li.nav-step-current').forEach(el => el.classList.remove('nav-step-current'));
    if (typeof navCurrentStepKey !== 'undefined') navCurrentStepKey = null;
}

function _createRouteFormatter() {
    if (!(L.Routing && typeof L.Routing.Formatter === 'function')) {
        return null;
    }
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
    return formatter;
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

    const preserveCurrentDisplay = options.preserveCurrentDisplay === true;

    // 既存のルートを削除
    if (routingControl) {
        map.removeControl(routingControl);
    }
    if (!preserveCurrentDisplay) {
        clearSelectedRouteHighlight();
        clearRouteCandidateLayers();
    }
    clearRouteStepFocusMarker();

    const extraWps = (options.extraWaypoints || []).map(wp => L.latLng(wp.lat, wp.lng));
    routeFormatter = _createRouteFormatter();

    if (typeof options.onRoutesAvailable === 'function'
            && extraWps.length === 0
            && typeof fetchRouteCandidates === 'function') {
        let latestRoutes = [];
        let selectedRouteIndexState = 0;
        const emitRouteState = (routeCandidates, selectedRouteIndex = selectedRouteIndexState) => {
            latestRoutes = renderRouteCandidates(routeCandidates);
            if (latestRoutes.length === 0) {
                if (typeof options.onRouteError === 'function') options.onRouteError();
                return;
            }
            selectedRouteIndexState = Math.max(0, Math.min(Number(selectedRouteIndex) || 0, latestRoutes.length - 1));
            const routeColors = latestRoutes.map((route, idx) => getRouteColorByIndex(idx));
            const selectedRoute = latestRoutes[selectedRouteIndexState];
            const selectRouteIndex = (routeIndex) => emitRouteState(latestRoutes, routeIndex);

            if (typeof options.onRouteSummary === 'function') {
                options.onRouteSummary({
                    distanceMeters: selectedRoute.summary?.totalDistance,
                    durationSeconds: selectedRoute.summary?.totalTime,
                    transportMode
                });
            }
            if (typeof options.onRouteFound === 'function') {
                options.onRouteFound({
                    route: selectedRoute,
                    formatter: routeFormatter,
                    transportMode
                });
            }
            options.onRoutesAvailable({
                routes: latestRoutes,
                selectedRouteIndex: selectedRouteIndexState,
                selectedRouteColor: routeColors[selectedRouteIndexState] || getRouteColorByIndex(selectedRouteIndexState),
                routeColors,
                formatter: routeFormatter,
                transportMode,
                selectRouteIndex
            });
        };

        fetchRouteCandidates(
            { lat: currentLocation.lat, lon: currentLocation.lon },
            { lat, lon },
            { transportMode, maxCandidates: MAX_ROUTE_CANDIDATES }
        ).then(routes => {
            emitRouteState(routes, 0);
        }).catch(error => {
            console.warn('[route-candidates] route fetch/evaluation failed', error);
            if (typeof options.onRouteError === 'function') options.onRouteError();
        });
        return true;
    }

    const routingOptions = {
        waypoints: [
            L.latLng(currentLocation.lat, currentLocation.lon),
            ...extraWps,
            L.latLng(lat, lon)
        ],
        language: 'ja',
        showAlternatives: true,
        addWaypoints: false,
        draggableWaypoints: false,
        routeWhileDragging: false,
        createMarker: () => null,  // LRM の waypoint マーカー（draggable IMG）を生成しない
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

    if (routeFormatter) {
        routingOptions.formatter = routeFormatter;
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
        onNavRouteSelected(null, destination, {
            selectedRouteIndex: null,
            transportMode: null,
            routes: [],
            routeColors: [],
            onSelectRouteIndex: null,
            infoMode: 'route_preview'
        });
    }

    const routed = drawRouteTo(destination.lat, destination.lon, {
        onRoutesAvailable: ({ routes, selectedRouteIndex, selectedRouteColor, routeColors, formatter, transportMode, selectRouteIndex }) => {
            // ナビモードにルート・目的地を通知
            if (typeof onNavRouteSelected === 'function') {
                onNavRouteSelected(routes[selectedRouteIndex], destination, {
                    selectedRouteIndex,
                    transportMode,
                    routes,
                    routeColors,
                    onSelectRouteIndex: selectRouteIndex,
                    infoMode: 'route_preview'
                });
            }
            renderRouteCandidatesOnMap(routes, routeColors, selectedRouteIndex, selectRouteIndex);
            renderDestinationRouteGuidance(
                index,
                routes,
                selectedRouteIndex,
                formatter,
                transportMode,
                selectRouteIndex,
                routeColors
            );
            // フロートカードの距離・時間・危険度を実ルート値に統一
            const _sr = routes[selectedRouteIndex];
            if (_sr && _sr.summary && typeof updateShelterCardRouteInfo === 'function') {
                updateShelterCardRouteInfo(_sr.summary.totalDistance, _sr.summary.totalTime);
            }
            if (typeof updateShelterCardRiskInfo === 'function') {
                updateShelterCardRiskInfo(routes[selectedRouteIndex] ?? null);
            }
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

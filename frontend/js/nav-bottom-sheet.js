'use strict';

/**
 * nav-bottom-sheet.js — ナビ中ボトムシート
 *
 * navigation_active / navigation_warning / navigation_paused の間だけ表示される
 * 3段階スナップ型ドラッグシート。
 * #map-bottom-controls を非表示にして代替表示する。
 *
 * 公開フック（navigation.js から呼ぶ）:
 *   _navSheetUpdateMode(mode)       モード変更時
 *   _navSheetUpdateDistance(result) 残距離更新時
 *   _navSheetUpdateStep()           ステップハイライト変更後
 *   _navSheetUpdateElev()           標高更新後
 */

const _navSheet = (() => {

    // ── 定数 ─────────────────────────────────────────────────────────────────
    const SNAP_H = { PEEK: 96, MID: 340, FULL: 500 };
    const FULL_THRESH = (SNAP_H.MID + SNAP_H.FULL) / 2; // 420px — MID/FULL の中間
    const ACCENT      = '#10b981';
    const C_PRIMARY   = '#1e293b';
    const C_SECONDARY = '#64748b';
    const C_MUTED     = '#94a3b8';

    // ── 内部状態 ──────────────────────────────────────────────────────────────
    let snap = 'MID';
    let liveH = SNAP_H.MID;
    let dragState = null;
    let _visible = false;
    let _sheet = null;
    let _handle = null;
    let _currentPos = null;       // 最新GPS位置 { lat, lng }
    let _activeTab = 'nav';       // 現在選択中のタブ
    let _displacedPanel = null;   // 移動中のMBCパネル { el, parent, nextSibling }

    // ── DOM ヘルパー ──────────────────────────────────────────────────────────
    const $ = id => document.getElementById(id);

    // ── ターン方向判定 ─────────────────────────────────────────────────────────
    function _maneuverType(text) {
        if (!text) return 'straight';
        if (/到着|目的地/.test(text)) return 'destination';
        if (/右/.test(text)) return 'right';
        if (/左/.test(text)) return 'left';
        return 'straight';
    }

    function _maneuverLabel(text) {
        if (!text) return '直進';
        if (/到着|目的地/.test(text)) return '到着';
        if (/右/.test(text)) return '右折';
        if (/左/.test(text)) return '左折';
        return '直進';
    }

    function _streetName(text) {
        const m = text && text.match(/\(([^)]+)\)/);
        return m ? m[1] : '';
    }

    function _distLabel(fullText) {
        const m = fullText && fullText.match(/（([^）]+)）/);
        return m ? m[1] : '';
    }

    function _fmtDist(m) {
        if (!Number.isFinite(m) || m < 0) return '—';
        return m < 1000 ? `${Math.round(m)}m` : `${(m / 1000).toFixed(1)}km`;
    }

    function _haversine(lat1, lon1, lat2, lon2) {
        const R = 6371000;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) ** 2
                + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180)
                * Math.sin(dLon / 2) ** 2;
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    // 現在GPS位置から次の分岐点（次ステップのlatLng）までの直線距離(m)
    function _distToNextTurnM() {
        if (!_currentPos) return null;
        const cur = _currentStepEl();
        const next = _nextStepEl(cur);
        if (!next) return null;
        const tLat = parseFloat(next.dataset.stepLat);
        const tLon = parseFloat(next.dataset.stepLon);
        if (!Number.isFinite(tLat) || !Number.isFinite(tLon)) return null;
        return _haversine(_currentPos.lat, _currentPos.lng, tLat, tLon);
    }

    // ── SVG ──────────────────────────────────────────────────────────────��───
    function _arrowSVG(type, size, color) {
        const s = size;
        if (type === 'right') return (
            `<svg width="${s}" height="${s}" viewBox="0 0 48 48" fill="none">` +
            `<path d="M16 36V20C16 15.6 19.6 12 24 12H32" stroke="${color}" stroke-width="4" stroke-linecap="round"/>` +
            `<path d="M27 7L32 12L27 17" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>` +
            `</svg>`
        );
        if (type === 'left') return (
            `<svg width="${s}" height="${s}" viewBox="0 0 48 48" fill="none">` +
            `<path d="M32 36V20C32 15.6 28.4 12 24 12H16" stroke="${color}" stroke-width="4" stroke-linecap="round"/>` +
            `<path d="M21 7L16 12L21 17" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>` +
            `</svg>`
        );
        if (type === 'destination') return (
            `<svg width="${s}" height="${s}" viewBox="0 0 48 48" fill="none">` +
            `<circle cx="24" cy="20" r="8" stroke="${color}" stroke-width="4"/>` +
            `<path d="M24 28C24 28 14 37 14 42H34C34 37 24 28 24 28Z" stroke="${color}" stroke-width="3" stroke-linejoin="round"/>` +
            `</svg>`
        );
        return (
            `<svg width="${s}" height="${s}" viewBox="0 0 48 48" fill="none">` +
            `<path d="M24 38V12" stroke="${color}" stroke-width="4" stroke-linecap="round"/>` +
            `<path d="M18 18L24 12L30 18" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>` +
            `</svg>`
        );
    }

    function _ringSVG(score, color) {
        const r = 18, circ = 2 * Math.PI * r;
        const dash = (score / 100) * circ;
        return (
            `<svg width="50" height="50" viewBox="0 0 50 50">` +
            `<circle cx="25" cy="25" r="${r}" fill="none" stroke="rgba(0,0,0,0.08)" stroke-width="4"/>` +
            `<circle cx="25" cy="25" r="${r}" fill="none" stroke="${color}" stroke-width="4"` +
            ` stroke-dasharray="${dash.toFixed(1)} ${circ.toFixed(1)}" stroke-dashoffset="${(circ * 0.25).toFixed(1)}"` +
            ` stroke-linecap="round" style="transition:stroke-dasharray 1s ease"/>` +
            `<text x="25" y="30" text-anchor="middle" fill="${C_PRIMARY}" font-size="11" font-weight="700">${score}</text>` +
            `</svg>`
        );
    }

    // ── データ取得 ────────────────────────────────────────────────────────────
    function _currentStepEl() {
        return (
            document.querySelector('#shelter-card-route-guidance li.nav-step-current[data-step-lat]') ||
            document.querySelector('#shelter-card-route-guidance li[data-step-lat]')
        );
    }

    function _nextStepEl(current) {
        if (!current) return null;
        const sib = current.nextElementSibling;
        return (sib && sib.matches('li[data-step-lat]')) ? sib : null;
    }

    function _allStepEls() {
        return Array.from(document.querySelectorAll('#shelter-card-route-guidance li[data-step-lat]'));
    }

    function _remainingDistM() {
        const el = $('mbc-remain-dist');
        if (!el) return null;
        const t = el.textContent.trim();
        if (t === '—' || !t) return null;
        if (t.endsWith('km')) return parseFloat(t) * 1000;
        return parseFloat(t);
    }

    function _calcETA(remainDistM) {
        const route = (typeof navActiveRoute !== 'undefined') ? navActiveRoute : null;
        if (!route || !Number.isFinite(remainDistM)) return null;
        const totalDist = Number(route?.summary?.totalDistance ?? route?.totalDistance);
        const totalTime = Number(route?.summary?.totalTime ?? route?.totalTime);
        if (!totalDist || !totalTime) return null;
        const ratio = Math.max(0, Math.min(1, remainDistM / totalDist));
        const remainSec = ratio * totalTime;
        const eta = new Date(Date.now() + remainSec * 1000);
        return {
            time: `${String(eta.getHours()).padStart(2, '0')}:${String(eta.getMinutes()).padStart(2, '0')}`,
            mins: Math.round(remainSec / 60),
        };
    }

    function _safetyInfo() {
        const route = (typeof navActiveRoute !== 'undefined') ? navActiveRoute : null;
        const riskSummary = route?.__riskSummary;
        if (riskSummary && typeof riskSummary.safety_score === 'number') {
            const score = Math.round(riskSummary.safety_score);
            const level = riskSummary.risk_level || 'safe';
            const color = level === 'danger' ? '#ef4444'
                : level === 'caution' ? '#f59e0b'
                : ACCENT;
            return { score, color, notes: riskSummary.risk_summary?.notes || [] };
        }
        if (route?.__crossingRisk?.hasUnsafeCrossing) return { score: 45, color: '#ef4444', notes: [] };
        return { score: 87, color: ACCENT, notes: [] };
    }

    function _elevText() {
        const v = (typeof navCurrentElevation !== 'undefined') ? navCurrentElevation : null;
        return (v != null) ? `${Math.round(v)}m` : '—';
    }

    function _accText() {
        const v = (typeof navLastKnownAccuracy !== 'undefined') ? navLastKnownAccuracy : null;
        return (v != null) ? `±${Math.round(v)}m` : '—';
    }

    // ── レンダリング ──────────────────────────────────────────────────────────
    const CARD_BG     = 'rgba(255,255,255,0.45)';
    const CARD_BORDER = '1px solid rgba(255,255,255,0.65)';

    function _renderPeek() {
        const el = $('nav-sheet-peek-row');
        if (!el) return;
        const cur = _currentStepEl();
        const text = cur ? cur.textContent.split('（')[0].trim() : '';
        const gpsDistM = _distToNextTurnM();
        const dist = gpsDistM !== null ? _fmtDist(gpsDistM) : (cur ? _distLabel(cur.textContent) : '');
        const totalDistText = (() => { const e = $('mbc-remain-dist'); return e ? e.textContent : '—'; })();
        const type = _maneuverType(text);
        const label = _maneuverLabel(text);
        const street = _streetName(text);

        el.innerHTML =
            `<div style="width:40px;height:40px;flex-shrink:0;background:${ACCENT}22;border-radius:12px;` +
            `border:1px solid ${ACCENT}55;display:flex;align-items:center;justify-content:center;">` +
            _arrowSVG(type, 26, ACCENT) +
            `</div>` +
            `<div style="flex:1;min-width:0;">` +
            `<span style="color:${C_PRIMARY};font-size:16px;font-weight:800;">${dist}</span>` +
            (label || street ? `<span style="color:${C_SECONDARY};font-size:13px;margin-left:6px;">${label}${street ? ' · ' + street : ''}</span>` : '') +
            `</div>` +
            `<div style="color:${C_MUTED};font-size:11px;flex-shrink:0;">${totalDistText}</div>`;
    }

    function _renderTurnCard() {
        const el = $('nav-sheet-turn-card');
        if (!el) return;
        const cur = _currentStepEl();
        const text = cur ? cur.textContent.split('（')[0].trim() : '';
        const gpsDistM = _distToNextTurnM();
        const dist = gpsDistM !== null ? _fmtDist(gpsDistM) : (cur ? _distLabel(cur.textContent) : '');
        const type = _maneuverType(text);
        const label = _maneuverLabel(text);
        const street = _streetName(text);

        const next = _nextStepEl(cur);
        const nextText = next ? next.textContent.split('（')[0].trim() : '';
        const nextDist = next ? _distLabel(next.textContent) : '';
        const nextHtml = next
            ? `<div style="display:flex;flex-direction:column;align-items:center;gap:3px;opacity:0.7;flex-shrink:0;">` +
              _arrowSVG(_maneuverType(nextText), 20, C_SECONDARY) +
              `<div style="color:${C_MUTED};font-size:10px;">${nextDist}</div></div>`
            : '';

        el.innerHTML =
            `<div style="width:64px;height:64px;flex-shrink:0;` +
            `background:linear-gradient(135deg,${ACCENT}33,${ACCENT}10);` +
            `border-radius:16px;border:1.5px solid ${ACCENT}55;` +
            `display:flex;align-items:center;justify-content:center;` +
            `box-shadow:0 0 14px ${ACCENT}22;">` +
            _arrowSVG(type, 40, ACCENT) +
            `</div>` +
            `<div style="flex:1;min-width:0;">` +
            `<div style="color:${C_PRIMARY};font-size:26px;font-weight:900;line-height:1;margin-bottom:5px;">` +
            `${dist}<span style="font-size:13px;font-weight:500;color:${C_SECONDARY};margin-left:4px;">先</span></div>` +
            `<div style="display:flex;align-items:center;gap:6px;">` +
            `<span style="background:${ACCENT};color:#fff;font-size:11px;font-weight:700;` +
            `padding:2px 9px;border-radius:20px;">${label}</span>` +
            (street ? `<span style="color:#475569;font-size:11px;overflow:hidden;` +
                `text-overflow:ellipsis;white-space:nowrap;">${street}</span>` : '') +
            `</div></div>` +
            nextHtml;
    }

    function _renderInfoRow(remainDistM) {
        const el = $('nav-sheet-info-row');
        if (!el) return;

        const rm = remainDistM ?? _remainingDistM();
        const eta = _calcETA(rm);
        const safety = _safetyInfo();
        const remainTxt = _fmtDist(rm ?? NaN);
        const etaHtml = eta
            ? `${eta.time}<span style="font-size:10px;font-weight:500;color:${C_MUTED};margin-left:3px;">約${eta.mins}分</span>`
            : '—';

        const firstNote = safety.notes && safety.notes.length > 0 ? safety.notes[0] : '';
        const noteHtml = firstNote
            ? `<div style="color:${safety.color};font-size:8px;max-width:76px;text-align:center;` +
              `line-height:1.3;margin-top:1px;overflow:hidden;display:-webkit-box;` +
              `-webkit-line-clamp:2;-webkit-box-orient:vertical;">${firstNote}</div>`
            : '';

        el.innerHTML =
            `<div style="flex:1;background:${CARD_BG};border-radius:14px;padding:11px 14px;border:${CARD_BORDER};">` +
            `<div style="color:${C_SECONDARY};font-size:10px;letter-spacing:0.06em;` +
            `text-transform:uppercase;margin-bottom:2px;">残り距離</div>` +
            `<div style="color:${C_PRIMARY};font-size:20px;font-weight:700;line-height:1;">${remainTxt}</div></div>` +
            `<div style="flex:1;background:${CARD_BG};border-radius:14px;padding:11px 14px;border:${CARD_BORDER};">` +
            `<div style="color:${C_SECONDARY};font-size:10px;letter-spacing:0.06em;` +
            `text-transform:uppercase;margin-bottom:2px;">到着予想</div>` +
            `<div style="color:${C_PRIMARY};font-size:20px;font-weight:700;line-height:1;">${etaHtml}</div></div>` +
            `<div style="background:${CARD_BG};border-radius:14px;padding:8px 10px;border:${CARD_BORDER};` +
            `display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;">` +
            _ringSVG(safety.score, safety.color) +
            `<div style="color:${C_SECONDARY};font-size:9px;">安全度</div>` +
            noteHtml +
            `</div>`;
    }

    function _renderStepPills() {
        const el = $('nav-sheet-steps');
        if (!el) return;
        const all = _allStepEls();
        const cur = _currentStepEl();
        el.innerHTML = '';

        all.forEach(stepEl => {
            const text = stepEl.textContent.split('（')[0].trim();
            const distTxt = _distLabel(stepEl.textContent);
            const isActive = (cur === null && stepEl === all[0]) || stepEl === cur;
            const type = _maneuverType(text);
            const label = _maneuverLabel(text);

            const pill = document.createElement('div');
            pill.style.cssText =
                `display:flex;align-items:center;gap:10px;padding:8px 14px;border-radius:20px;` +
                `background:${isActive ? ACCENT + '22' : 'rgba(0,0,0,0.04)'};` +
                `border:1px solid ${isActive ? ACCENT : 'rgba(0,0,0,0.07)'};` +
                `flex-shrink:0;cursor:pointer;transition:all 0.3s ease;`;
            pill.innerHTML =
                _arrowSVG(type, 20, isActive ? ACCENT : C_SECONDARY) +
                `<div>` +
                `<div style="color:${isActive ? C_PRIMARY : C_SECONDARY};font-size:11px;font-weight:700;">${distTxt}</div>` +
                `<div style="color:${isActive ? ACCENT : C_MUTED};font-size:10px;">${label}</div>` +
                `</div>`;

            pill.addEventListener('click', () => {
                const lat = parseFloat(stepEl.dataset.stepLat);
                const lon = parseFloat(stepEl.dataset.stepLon);
                if (!Number.isFinite(lat) || !Number.isFinite(lon)) return;
                const stepText = stepEl.textContent.split('（')[0].trim();
                const stepDist = _distLabel(stepEl.textContent);
                if (typeof focusRouteStepOnMap === 'function') {
                    focusRouteStepOnMap(
                        { latLng: L.latLng(lat, lon), text: stepText, distanceLabel: stepDist },
                        ACCENT
                    );
                } else if (typeof map !== 'undefined') {
                    map.setView([lat, lon], 17, { animate: true });
                }
            });

            if (isActive) {
                setTimeout(() => pill.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'center' }), 80);
            }
            el.appendChild(pill);
        });
    }

    function _renderFullExtras() {
        const el = $('nav-sheet-full-extras');
        if (!el) return;
        const items = [
            { icon: '▲', label: '標高', value: _elevText() },
            { icon: '◎', label: '精度', value: _accText() },
        ];

        const safety = _safetyInfo();
        const riskNotes = safety.notes || [];
        const riskNotesHtml = riskNotes.length > 0
            ? `<div style="padding:0 16px 8px;">` +
              `<div style="background:${CARD_BG};border-radius:12px;padding:10px 12px;border:${CARD_BORDER};">` +
              `<div style="color:${safety.color};font-size:10px;font-weight:700;margin-bottom:5px;">` +
              `⚠ ルート危険度: 安全度 ${safety.score}</div>` +
              `<ul style="margin:0;padding-left:14px;font-size:10px;color:${C_PRIMARY};line-height:1.6;">` +
              riskNotes.map(n => `<li>${n}</li>`).join('') +
              `</ul></div></div>`
            : '';

        el.innerHTML =
            `<div style="display:flex;gap:8px;padding:0 16px 8px;">` +
            items.map(item =>
                `<div style="flex:1;background:${CARD_BG};border-radius:12px;` +
                `padding:10px 12px;border:${CARD_BORDER};text-align:center;">` +
                `<div style="color:${ACCENT};font-size:16px;margin-bottom:3px;">${item.icon}</div>` +
                `<div style="color:${C_PRIMARY};font-size:14px;font-weight:700;">${item.value}</div>` +
                `<div style="color:${C_SECONDARY};font-size:10px;">${item.label}</div>` +
                `</div>`
            ).join('') +
            `</div>` +
            riskNotesHtml;
    }

    // ── 高さ・スナップ管理 ────────────────────────────────────────────────────
    function _applyHeight(h, animate) {
        if (!_sheet) return;
        liveH = h;
        _sheet.style.transition = animate
            ? 'height 0.38s cubic-bezier(0.32,0.72,0,1)'
            : 'none';
        _sheet.style.height = h + 'px';
        _syncVisibility();
    }

    function _snapTo(key, animate) {
        snap = key;
        _applyHeight(SNAP_H[key], animate);
    }

    function _syncVisibility() {
        const isPeek   = (snap === 'PEEK' && dragState === null);
        const isFull   = liveH > FULL_THRESH;
        const isNavTab = (_activeTab === 'nav');

        const tabBar   = $('nav-sheet-tab-bar');
        const peekRow  = $('nav-sheet-peek-row');
        const turnCard = $('nav-sheet-turn-card');
        const body     = $('nav-sheet-body');
        const steps    = $('nav-sheet-steps');
        const extras   = $('nav-sheet-full-extras');
        const alt      = $('nav-sheet-alt-content');

        // タブバー: PEEK 時は非表示
        if (tabBar) tabBar.style.display = isPeek ? 'none' : 'flex';

        if (isNavTab) {
            if (alt)      alt.style.display      = 'none';
            if (peekRow)  peekRow.style.display  = isPeek ? 'flex' : 'none';
            if (turnCard) turnCard.style.display  = isPeek ? 'none' : '';
            if (body) {
                body.style.display   = isPeek ? 'none' : 'flex';
                body.style.overflowY = isFull ? 'auto' : 'hidden';
            }
            if (steps)  steps.style.display  = isFull ? 'flex' : 'none';
            if (extras) extras.style.display  = isFull ? 'block' : 'none';
            if (isFull) _renderFullExtras();
        } else {
            // 非ナビタブ: ターンカードはハンドル内にそのまま表示、bodyは非表示
            if (peekRow)  peekRow.style.display  = 'none';
            if (turnCard) turnCard.style.display  = '';
            if (body)     body.style.display      = 'none';
            if (alt) {
                // 地震タブは flex:1/min-height:0 チェーンが必要なので flex コンテナとして開く
                if (_activeTab === 'earthquake') {
                    alt.style.display        = 'flex';
                    alt.style.flexDirection  = 'column';
                    alt.style.overflowY      = 'hidden';
                } else {
                    alt.style.display        = 'block';
                    alt.style.flexDirection  = '';
                    alt.style.overflowY      = 'auto';
                }
            }
        }
    }

    // ── タブ ─────────────────────────────────────────────────────────────────
    function _initTabs() {
        const bar = $('nav-sheet-tab-bar');
        if (!bar) return;
        bar.querySelectorAll('.nsb-tab[data-nstab]').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                _switchToTab(btn.dataset.nstab);
            });
        });
    }

    function _switchToTab(tabId) {
        if (tabId === _activeTab) return;

        // 移動済みパネルを元の場所に戻す
        if (_displacedPanel) {
            const { el, parent, nextSibling } = _displacedPanel;
            parent.insertBefore(el, nextSibling);
            el.style.display = 'none';
            _displacedPanel = null;
        }

        _activeTab = tabId;

        // タブボタンのアクティブ状態を更新
        const bar = $('nav-sheet-tab-bar');
        if (bar) {
            bar.querySelectorAll('.nsb-tab[data-nstab]').forEach(btn => {
                btn.classList.toggle('nsb-tab--active', btn.dataset.nstab === tabId);
            });
        }

        if (tabId !== 'nav') {
            const panel = $('mbc-tab-panel-' + tabId);
            const alt   = $('nav-sheet-alt-content');
            if (panel && alt) {
                const origParent = panel.parentNode;
                const origNext   = panel.nextSibling;
                alt.innerHTML    = '';
                alt.appendChild(panel);
                // earthquake パネルは flex レイアウトを要求する
                panel.style.display = (tabId === 'earthquake') ? 'flex' : 'block';
                _displacedPanel = { el: panel, parent: origParent, nextSibling: origNext };
            }
            // タブ固有の初期化（app.js の switchMbcTab に相当する後処理）
            if (tabId === 'earthquake') {
                if (typeof isMagnitudeModeActive === 'function' && !isMagnitudeModeActive()) {
                    if (typeof toggleMagnitudeMode === 'function') toggleMagnitudeMode();
                }
            } else if (tabId === 'layer') {
                if (typeof _ensureHazardTogglesInitialized === 'function') {
                    _ensureHazardTogglesInitialized();
                }
            }
            // PEEK のままでは閲覧しにくいので MID へ
            if (snap === 'PEEK') _snapTo('MID', true);
        }

        _syncVisibility();
    }

    function _restoreDisplacedPanel() {
        if (!_displacedPanel) return;
        const { el, parent, nextSibling } = _displacedPanel;
        parent.insertBefore(el, nextSibling);
        el.style.display = 'none';
        _displacedPanel  = null;
        _activeTab       = 'nav';
    }

    // ── ドラッグ ──────────────────────────────────────────────────────────────
    function _initDrag() {
        if (!_handle) return;

        function _start(e) {
            const y = e.touches ? e.touches[0].clientY : e.clientY;
            dragState = { startY: y, startH: liveH };
            e.preventDefault();
        }

        function _move(e) {
            if (!dragState) return;
            const y = e.touches ? e.touches[0].clientY : e.clientY;
            const dy = y - dragState.startY;
            const newH = Math.max(SNAP_H.PEEK - 8, Math.min(SNAP_H.FULL + 20, dragState.startH - dy));
            liveH = newH;
            if (_sheet) { _sheet.style.transition = 'none'; _sheet.style.height = newH + 'px'; }
            _syncVisibility();
        }

        function _end(e) {
            if (!dragState) return;
            const y = e.changedTouches ? e.changedTouches[0].clientY : e.clientY;
            const dy = y - dragState.startY;
            const finalH = Math.max(SNAP_H.PEEK - 8, Math.min(SNAP_H.FULL + 20, dragState.startH - dy));
            const dists = Object.entries(SNAP_H).map(([k, h]) => ({ k, d: Math.abs(h - finalH) }));
            dists.sort((a, b) => a.d - b.d);
            dragState = null;
            _snapTo(dists[0].k, true);
        }

        _handle.addEventListener('mousedown', _start);
        _handle.addEventListener('touchstart', _start, { passive: false });
        window.addEventListener('mousemove', _move);
        window.addEventListener('mouseup', _end);
        window.addEventListener('touchmove', _move, { passive: false });
        window.addEventListener('touchend', _end);
    }

    // ── 公開 API ──────────────────────────────────────────────────────────────
    function init() {
        _sheet  = $('nav-bottom-sheet');
        _handle = $('nav-sheet-handle');
        if (!_sheet) return;
        _initDrag();
        _initTabs();
        if (typeof L !== 'undefined') {
            try { L.DomEvent.disableClickPropagation(_sheet); } catch (_) {}
            try { L.DomEvent.disableScrollPropagation(_sheet); } catch (_) {}
        }
        _sheet.addEventListener('touchstart', e => e.stopPropagation(), { passive: true });
        _sheet.addEventListener('mousedown',  e => e.stopPropagation());
        _sheet.addEventListener('touchmove',  e => e.stopPropagation(), { passive: true });
    }

    function show() {
        _sheet = $('nav-bottom-sheet');
        if (!_sheet) return;

        const controls = $('map-bottom-controls');
        if (controls) controls.style.display = 'none';

        if (!_visible) {
            // ナビ開始のたびにタブをリセット
            _restoreDisplacedPanel();
            const bar = $('nav-sheet-tab-bar');
            if (bar) {
                bar.querySelectorAll('.nsb-tab[data-nstab]').forEach(btn => {
                    btn.classList.toggle('nsb-tab--active', btn.dataset.nstab === 'nav');
                });
            }
            snap = 'MID';
            _applyHeight(SNAP_H.MID, false);
        }
        _visible = true;
        _sheet.style.display = 'flex';
        _refreshAll();
    }

    function hide() {
        // 非ナビタブで移動していたパネルを元に戻す
        _restoreDisplacedPanel();

        _visible = false;
        _sheet = $('nav-bottom-sheet');
        if (_sheet) _sheet.style.display = 'none';

        const controls = $('map-bottom-controls');
        if (controls) controls.style.display = '';
    }

    function _refreshAll() {
        const rm = _remainingDistM();
        _renderPeek();
        _renderTurnCard();
        _renderInfoRow(rm);
        _renderStepPills();
        _syncVisibility();
    }

    function updateDistance(routeResult) {
        if (!_visible) return;
        const rm = routeResult?.remainingDistanceMeters ?? _remainingDistM();
        _renderInfoRow(rm);
        if (snap === 'PEEK') _renderPeek();
    }

    function updateStep(lat, lon) {
        if (!_visible) return;
        if (Number.isFinite(lat) && Number.isFinite(lon)) {
            _currentPos = { lat, lng: lon };
        }
        _renderTurnCard();
        _renderPeek();
        _renderStepPills();
    }

    function updateElev() {
        if (!_visible || liveH <= FULL_THRESH) return;
        _renderFullExtras();
    }

    function getHeight() { return _visible ? liveH : 0; }

    return { init, show, hide, updateDistance, updateStep, updateElev, getHeight };
})();

// ── 公開フック（navigation.js・routing.js から呼ぶ） ─────────────────────────

function _navSheetUpdateMode(mode) {
    const active = mode === 'navigation_active'
                || mode === 'navigation_warning'
                || mode === 'navigation_paused';
    if (active) _navSheet.show();
    else        _navSheet.hide();
}

function _navSheetUpdateDistance(routeResult) {
    _navSheet.updateDistance(routeResult);
}

function _navSheetUpdateStep(lat, lon) {
    _navSheet.updateStep(lat, lon);
}

function _navSheetUpdateElev() {
    _navSheet.updateElev();
}

function _navSheetGetHeight() {
    return _navSheet.getHeight ? _navSheet.getHeight() : 0;
}

window.addEventListener('load', () => { _navSheet.init(); });

/**
 * ui.js — UI 表示・レンダリング関数
 *
 * - hazard_assessment ブロックのレンダリング
 * - Time Margin ブロックのレンダリング
 * - 避難先候補の地図表示・リスト表示
 * - 危険判定パネル・推奨避難先カード
 * - RSA（到達可能安全エリア）の表示
 * - 検索結果のクリア
 * - ステータステキスト更新
 */

// ── hazard_assessment ヘルパー ────────────────────────────────────────────
// 表示順: flood → tsunami → storm_surge → inland_flood → landslide → その他
const HAZARD_DISPLAY_ORDER = ['flood', 'tsunami', 'storm_surge', 'inland_flood', 'landslide', 'urban_flood'];

// safe 表示の文言（一元管理）
const SAFE_HAZARD_TEXT    = '✔ 安全（全ハザード外）';
// unknown 表示の文言（一元管理）— inside 無しでも unknown が1件でもあれば使う
const UNKNOWN_HAZARD_TEXT = '❓ 未判定（安全確認不可）';

/**
 * severity レベルを数値ランクに変換する（ソート用）。
 * critical > danger > caution > safe > unknown
 *
 * @param {string} level
 * @returns {number}
 */
function getSeverityRank(level) {
    switch (level) {
        case 'critical': return 4;
        case 'danger':   return 3;
        case 'caution':  return 2;
        case 'safe':     return 1;
        default:         return 0;
    }
}

/**
 * severity レベルから表示情報を返す。
 *
 * @param {string} level - "critical" | "danger" | "caution" | "safe"
 * @returns {{ text: string, icon: string, color: string }}
 */
function getSeverityInfo(level) {
    switch (level) {
        case 'critical': return { text: '非常に危険', icon: '🚨', color: '#c62828' };
        case 'danger':   return { text: '危険',       icon: '⚠️', color: '#e65100' };
        case 'caution':  return { text: '注意',       icon: '⚡', color: '#f57f17' };
        default:         return { text: '安全',       icon: '✅', color: '#2e7d32' };
    }
}

function getHazardLabel(key) {
    const map = {
        flood: '洪水', tsunami: '津波', storm_surge: '高潮',
        inland_flood: '内水氾濫', landslide: '土砂災害', urban_flood: '内水'
    };
    return map[key] || key;
}

// 文字列または構造化 dict から表示ラベルを生成する
function getAssessmentValueLabel(value) {
    // 既存ハザード: 文字列
    if (typeof value === 'string') {
        const map = { inside: '危険区域内', outside: '区域外', unknown: '未判定' };
        return map[value] || value;
    }
    // severity 付き: 構造化 dict
    if (value && typeof value === 'object') {
        const status = value.status;
        if (status === 'outside') return '区域外';
        if (status === 'unknown') return '未判定';
        // inside + level
        const levelMap = { critical: '非常に危険', danger: '危険', caution: '注意', safe: '安全' };
        const levelLabel = levelMap[value.level] || value.level || '';
        const extra = value.depth_m != null
            ? `（${value.depth_m}m）`
            : value.zone_type === 'special' ? '（特別警戒区域）'
            : value.zone_type === 'warning' ? '（警戒区域）'
            : '';
        return `危険区域内・${levelLabel}${extra}`;
    }
    return String(value);
}

// 文字列または構造化 dict から CSS クラス用の文字列を返す
// inside + level がある場合は level (caution/danger/critical) を返し色分けに使用する
function getAssessmentStatusClass(value) {
    if (typeof value === 'string') return value;
    if (value && typeof value === 'object') {
        const status = value.status || 'unknown';
        if (status === 'inside' && value.level) return value.level;
        return status;
    }
    return 'unknown';
}

function sortedAssessmentEntries(assessment) {
    if (!assessment || typeof assessment !== 'object') return [];
    const keys = Object.keys(assessment);
    const ordered = HAZARD_DISPLAY_ORDER.filter(k => keys.includes(k));
    const rest = keys.filter(k => !HAZARD_DISPLAY_ORDER.includes(k)).sort();
    return [...ordered, ...rest].map(k => ({ key: k, value: assessment[k] }));
}

function renderHazardAssessmentBlock(assessment) {
    const entries = sortedAssessmentEntries(assessment);
    if (entries.length === 0) return '';
    const rows = entries.map(({ key, value }) => {
        const statusClass = getAssessmentStatusClass(value);
        return `
        <div class="ha-row">
            <span class="ha-name">${getHazardLabel(key)}</span>
            <span class="ha-value ${statusClass}">${getAssessmentValueLabel(value)}</span>
        </div>`;
    }).join('');
    return `<div class="hazard-assessment-block">
        <div class="ha-title">ハザード判定</div>
        ${rows}
    </div>`;
}

function renderHazardAssessmentPopup(assessment) {
    const entries = sortedAssessmentEntries(assessment);
    if (entries.length === 0) return '';
    const rows = entries.map(({ key, value }) => {
        const statusClass = getAssessmentStatusClass(value);
        const color = statusClass === 'inside' ? '#c62828' : statusClass === 'outside' ? '#2e7d32' : '#78909c';
        return `・${getHazardLabel(key)}: <span style="font-weight:700;color:${color}">${getAssessmentValueLabel(value)}</span>`;
    }).join('<br>');
    return `<div class="popup-ha-block">
        <div class="ha-title">ハザード判定</div>
        ${rows}
    </div>`;
}

// ── Time Margin ブロック ──────────────────────────────────────────────────

function renderTimeMarginBlock(dest) {
    const status = dest.time_margin_status;
    if (!status) return '';

    const tm  = dest.time_margin_minutes;
    const tti = dest.time_to_impact_minutes;
    const et  = dest.evacuation_time_minutes;

    if (status === 'danger') {
        const detail = (tti != null && et != null)
            ? `<div class="tm-detail">余裕時間: ${tm?.toFixed(1)}分<br>⏱ 津波到達: ${tti.toFixed(1)}分<br>🚶 避難時間: ${et.toFixed(1)}分</div>`
            : '';
        return `<div class="time-margin danger">
            <div class="tm-warning">🚨 避難が間に合わない可能性</div>
            ${detail}
        </div>`;
    }

    let iconLabel;
    if      (status === 'safe')  iconLabel = `🟢 余裕: +${tm?.toFixed(1)}分`;
    else if (status === 'tight') iconLabel = `🟡 余裕: +${tm?.toFixed(1)}分`;
    else                         iconLabel = '⚪ 時間余裕: 未判定';

    const detail = (tti != null && et != null)
        ? `<div class="tm-detail">⏱ 津波到達: ${tti.toFixed(1)}分 ／ 🚶 避難時間: ${et.toFixed(1)}分</div>`
        : '';

    return `<div class="time-margin ${status}">
        <span class="tm-icon-label">${iconLabel}</span>
        ${detail}
    </div>`;
}

function renderTimeMarginPopup(dest) {
    const status = dest.time_margin_status;
    if (!status) return '';

    const tm  = dest.time_margin_minutes;
    const tti = dest.time_to_impact_minutes;
    const et  = dest.evacuation_time_minutes;

    const colors = { safe: '#2e7d32', tight: '#f57f17', danger: '#c62828', unknown: '#9e9e9e' };
    const color = colors[status] || '#9e9e9e';

    if (status === 'danger') {
        const detail = (tti != null && et != null)
            ? `<div style="font-size:10px;color:#b71c1c;margin-top:2px;">余裕時間: ${tm?.toFixed(1)}分 ／ ⏱ 津波: ${tti.toFixed(1)}分 ／ 🚶 避難: ${et.toFixed(1)}分</div>`
            : '';
        return `<div style="margin-top:5px;padding:5px 7px;border-top:1px solid #e0e0e0;border-left:4px solid #c62828;background:#ffebee;border-radius:3px;font-size:11px;">
            <span style="font-weight:700;color:#b71c1c;">🚨 避難が間に合わない可能性</span>
            ${detail}
        </div>`;
    }

    let label;
    if      (status === 'safe')  label = `🟢 余裕: +${tm?.toFixed(1)}分`;
    else if (status === 'tight') label = `🟡 余裕: +${tm?.toFixed(1)}分`;
    else                         label = '⚪ 時間余裕: 未判定';

    const detail = (tti != null && et != null)
        ? `<br><span style="font-size:10px;color:#757575;">⏱ 津波: ${tti.toFixed(1)}分 ／ 🚶 避難: ${et.toFixed(1)}分</span>`
        : '';

    return `<div style="margin-top:5px;padding-top:5px;border-top:1px solid #e0e0e0;font-size:11px;">
        <div style="font-weight:700;color:#546e7a;font-size:10px;text-transform:uppercase;letter-spacing:0.4px;">Time Margin</div>
        <span style="color:${color};font-weight:700;">${label}</span>${detail}
    </div>`;
}

// ── 避難先候補の地図表示 ──────────────────────────────────────────────────

function displayDestinations(dests, recommended) {
    dests.forEach((dest, index) => {
        const isRecommended = recommended
            && Math.abs(dest.lat - recommended.lat) < 1e-8
            && Math.abs(dest.lon - recommended.lon) < 1e-8;

        let color, fillColor, radius;
        if (isRecommended) {
            color = '#e65100'; fillColor = '#ffd600'; radius = 18;
        } else if (dest.hazard_safe === true) {
            color = '#2e7d32'; fillColor = '#4caf50'; radius = 13;
        } else if (dest.hazard_safe === false) {
            color = '#e65100'; fillColor = '#ff9800'; radius = 13;
        } else {
            color = '#546e7a'; fillColor = '#78909c'; radius = 14; // 後方互換: hazard_safe 不明
        }

        const baseStyle = {
            color,
            fillColor,
            fillOpacity: 0.85,
            radius,
            weight: isRecommended ? 3 : 2
        };
        const marker = L.circleMarker([dest.lat, dest.lon], {
            ...baseStyle,
            bubblingMouseEvents: false
        }).addTo(map);

        const hazardLabel = dest.hazard_safe === true ? '✅ 危険区域外'
            : dest.hazard_safe === false ? '⚠️ 危険区域内'
            : '❓ 安全性未判定';
        const hazardNote = (dest.hazard_safe == null)
            ? '<br><span style="font-size:11px;color:#546e7a;">ハザードデータが利用できないため安全性は未判定です</span>'
            : '';
        const nameLabel = dest.name ? `<strong>${dest.name}</strong>` : `<strong>避難先候補 #${index + 1}</strong>`;
        const recLabel = isRecommended ? '<br><span style="color:#e65100;font-weight:700;">⭐ 推奨避難先</span>' : '';

        marker.on('click', () => {
            // 左パネルを確実に表示してからカードを選択・スクロール
            const panel = document.getElementById('destinationsPanel');
            if (panel) panel.style.display = 'block';
            showDestInFloatCard(dest, index);
            showRoute(dest, index, { ensureCardVisible: true });
        });

        marker.bindTooltip(isRecommended ? '⭐' : String(index + 1), {
            permanent: true,
            direction: 'center',
            className: 'destination-number-label'
        });

        marker.bringToFront();
        destinationMarkers.push(marker);
        destinationMarkerBaseStyles.push(baseStyle);
    });

    // 地図の表示範囲を調整
    const bounds = L.latLngBounds(
        [currentLocation.lat, currentLocation.lon],
        dests.map(d => [d.lat, d.lon])
    );
    map.fitBounds(bounds, { padding: [50, 50] });
}

// ── 避難先リスト表示 ──────────────────────────────────────────────────────

function displayDestinationsList(dests, recommended) {
    const listContainer = document.getElementById('destinationsList');
    listContainer.innerHTML = '';

    dests.forEach((dest, index) => {
        const isRecommended = recommended
            && Math.abs(dest.lat - recommended.lat) < 1e-8
            && Math.abs(dest.lon - recommended.lon) < 1e-8;

        const card = document.createElement('div');
        let cardClass = 'destination-card';
        if (isRecommended) cardClass += ' is-recommended';
        else if (dest.hazard_safe === false) cardClass += ' hazard-unsafe';
        card.className = cardClass;
        card.dataset.index = index;

        const hazardBadge = dest.hazard_safe === true
            ? '<span class="hazard-safe-badge safe">危険区域外</span>'
            : dest.hazard_safe === false
                ? '<span class="hazard-safe-badge unsafe">⚠️ 危険区域内</span>'
                : '<span class="hazard-safe-badge unknown">❓ 安全性未判定</span>';
        const hazardReasonBlock = buildHazardReasonBlock(dest.hazard_assessment);
        const unknownNote = (dest.hazard_safe == null)
            ? '<p style="font-size:11px;color:#546e7a;margin:2px 0 0;">ハザードデータが利用できないため安全性は未判定です</p>'
            : '';
        const nameText = dest.name || `候補 #${index + 1}`;
        const typeBadge = dest.type === 'emergency_shelter'
            ? '<span class="dest-type-badge">指定避難所</span>'
            : dest.type === 'safe_high_ground_candidate'
                ? '<span class="dest-type-badge" style="background:#f3e5f5;color:#6a1b9a;">高台候補</span>'
                : '';
        const rankClass = isRecommended ? 'destination-rank is-recommended-rank' : 'destination-rank';
        const rankLabel = isRecommended ? '⭐' : String(index + 1);

        const guideBtnClass = dest.hazard_safe === false
            ? 'dest-guide-btn unsafe-dest'
            : 'dest-guide-btn';
        const guideBtnText = dest.hazard_safe === false ? '⚠️ 案内' : '案内';

        card.innerHTML = `
            <span class="${rankClass}">${rankLabel}</span>
            <div class="destination-info">
                <p class="dest-name">${nameText}${typeBadge}</p>
                <p>${hazardBadge}
                    <span class="safety-score">スコア ${dest.safety_score.toFixed(1)}</span>
                </p>
                ${hazardReasonBlock}
                <p>📏 ${dest.distance.toFixed(0)}m | ⏱️ ${dest.estimated_time_minutes.toFixed(0)}分</p>
                <p>⬆️ +${dest.elevation_gain.toFixed(1)}m（標高 ${dest.elevation.toFixed(1)}m）</p>
                ${renderTimeMarginBlock(dest)}
                ${unknownNote}
                ${renderHazardAssessmentBlock(dest.hazard_assessment)}
                <button class="${guideBtnClass}" data-dest-index="${index}">${guideBtnText}</button>
            </div>
            <div class="route-guidance" data-route-guidance></div>
        `;

        card.addEventListener('click', () => {
            showRoute(dest, index, { ensureCardVisible: false });
        });

        const guideBtn = card.querySelector('.dest-guide-btn');
        if (guideBtn) {
            guideBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                showRoute(dest, index, { ensureCardVisible: false });
            });
        }

        listContainer.appendChild(card);
    });
}

// ── 危険判定パネル ────────────────────────────────────────────────────────

function displayHazardStatus(hazardStatus) {
    const panel = document.getElementById('dangerStatusPanel');
    if (!panel) return;

    const hazards    = hazardStatus?.hazards || [];
    const isDanger   = hazardStatus?.is_danger === true;
    const assessment = hazardStatus?.assessment || {};

    panel.className = `danger-status-panel ${isDanger ? 'danger' : 'safe'}`;

    if (!isDanger || hazards.length === 0) {
        panel.innerHTML = `
            <div class="danger-title">✅ 現在地はハザード区域外です</div>
            <div style="font-size:12px;">念のため避難先を確認しておきましょう</div>
        `;
    } else {
        const labelMap = {
            flood: '洪水', tsunami: '津波', storm_surge: '高潮',
            inland_flood: '内水氾濫', landslide: '土砂災害', urban_flood: '内水氾濫'
        };

        const hazardTags = hazards
            .map(h => {
                const label    = labelMap[h] || h;
                const asmValue = assessment[h];
                // dict 形式は level から、string 'inside' は danger 相当でランク付け
                const level = (asmValue && typeof asmValue === 'object' && asmValue.status === 'inside')
                    ? (asmValue.level || 'danger')
                    : 'danger';
                return { h, label, asmValue, level, rank: getSeverityRank(level) };
            })
            .sort((a, b) => b.rank - a.rank)
            .map(({ label, asmValue, level }) => {
                if (asmValue && typeof asmValue === 'object' && asmValue.status === 'inside') {
                    const sev   = getSeverityInfo(level);
                    const extra = asmValue.depth_m != null
                        ? `${asmValue.depth_m}m`
                        : asmValue.zone_type === 'special' ? '特別警戒区域'
                        : asmValue.zone_type === 'warning'  ? '警戒区域'
                        : '';
                    const extraHtml = extra
                        ? `<span style="font-size:10px;margin-left:3px;">(${extra})</span>`
                        : '';
                    return `<span class="hazard-tag severity-${level}">${sev.icon} ${label}：${sev.text}${extraHtml}</span>`;
                }
                return `<span class="hazard-tag">${label}</span>`;
            })
            .join('');

        const activeLabels = hazards.map(h => labelMap[h] || h);
        const mainMessage  = `現在地は${activeLabels.join('・')}の危険区域内です`;

        panel.innerHTML = `
            <div class="danger-title">⚠️ ${mainMessage}</div>
            <div style="margin-top:4px;">${hazardTags}</div>
            <div style="margin-top:6px;font-size:12px;">直ちに避難先へ移動してください</div>
        `;
    }
    panel.style.display = 'block';
}

function hideDangerStatus() {
    const panel = document.getElementById('dangerStatusPanel');
    if (panel) panel.style.display = 'none';
}

// ── 危険理由ブロック（避難先カード用）────────────────────────────────────

/**
 * 避難先の hazard_assessment から危険理由ピルを生成する。
 * 危険区域内のハザードのみ表示。severity がある場合は色付き。
 *
 * @param {Object} assessment - dest.hazard_assessment
 * @returns {string} HTML文字列
 */
function buildHazardReasonBlock(assessment) {
    if (!assessment || typeof assessment !== 'object') {
        // assessment が null/undefined = データなし → 安全確定しない
        return `<div class="hazard-reason-block"><span class="hazard-reason-item is-unknown">${UNKNOWN_HAZARD_TEXT}</span></div>`;
    }

    const ranked = [];
    let hasUnknown = false;

    for (const [key, value] of Object.entries(assessment)) {
        if (typeof value === 'string') {
            if (value === 'inside') {
                ranked.push({
                    rank: getSeverityRank('danger'),
                    html: `<span class="hazard-reason-item is-danger">${getHazardLabel(key)}</span>`
                });
            } else if (value === 'unknown') {
                hasUnknown = true;
            }
        } else if (value && typeof value === 'object') {
            const status = value.status;
            if (status === 'inside') {
                const level    = value.level || 'danger';
                const cssClass = level === 'caution' ? 'is-caution' : 'is-danger';
                const sev      = getSeverityInfo(level);
                const extra    = value.depth_m != null ? `${value.depth_m}m`
                    : value.zone_type === 'special' ? '特別警戒'
                    : value.zone_type === 'warning'  ? '警戒区域'
                    : '';
                const label = extra ? `${getHazardLabel(key)}(${extra})` : getHazardLabel(key);
                ranked.push({
                    rank: getSeverityRank(level),
                    html: `<span class="hazard-reason-item ${cssClass}">${sev.icon} ${label}</span>`
                });
            } else if (status === 'unknown') {
                hasUnknown = true;
            }
        }
    }

    // severity 高い順にソート
    ranked.sort((a, b) => b.rank - a.rank);

    if (ranked.length > 0) {
        // inside があれば danger ピルを表示（unknownの有無は問わない）
        return `<div class="hazard-reason-block">${ranked.map(r => r.html).join('')}</div>`;
    }
    if (hasUnknown) {
        // inside は無いが unknown が1件以上 → 安全確定しない
        return `<div class="hazard-reason-block"><span class="hazard-reason-item is-unknown">${UNKNOWN_HAZARD_TEXT}</span></div>`;
    }
    // 全件 outside のみ → 安全
    return `<div class="hazard-reason-block"><span class="hazard-reason-item is-safe">${SAFE_HAZARD_TEXT}</span></div>`;
}

// ── 推奨理由セクション ────────────────────────────────────────────────────

function _buildRecommendSection(dest, rank) {
    const rows = [];

    // 🛡 ハザード安全判定
    if (dest.hazard_safe === true) {
        // hazard_assessment から「どのハザードが外か」を列挙
        const assessment = dest.hazard_assessment;
        let outsideLabels = [];
        if (assessment && typeof assessment === 'object') {
            for (const [key, val] of Object.entries(assessment)) {
                const status = typeof val === 'string' ? val : val?.status;
                if (status === 'outside') outsideLabels.push(getHazardLabel(key));
            }
        }
        const desc = outsideLabels.length > 0
            ? outsideLabels.join('・') + 'のリスクエリア外です'
            : '全ハザードエリア外です';
        rows.push(`
            <div class="recommend-row">
                <span class="recommend-icon">🛡</span>
                <div>
                    <div class="recommend-title">全ハザードエリア外</div>
                    <div class="recommend-desc">${dest.__escapeLabel ? dest.__escapeLabel + 'を含む全ハザードで' : ''}${desc}</div>
                </div>
            </div>`);
    } else if (dest.hazard_safe === false) {
        const assessment = dest.hazard_assessment;
        let insideLabels = [];
        if (assessment && typeof assessment === 'object') {
            for (const [key, val] of Object.entries(assessment)) {
                const status = typeof val === 'string' ? val : val?.status;
                if (status === 'inside') insideLabels.push(getHazardLabel(key));
            }
        }
        const desc = insideLabels.length > 0
            ? insideLabels.join('・') + 'のリスクあり'
            : 'ハザードエリア内の可能性あり';
        rows.push(`
            <div class="recommend-row">
                <span class="recommend-icon">⚠️</span>
                <div>
                    <div class="recommend-title is-warning">ハザードエリアを含む可能性あり</div>
                    <div class="recommend-desc">${desc}</div>
                </div>
            </div>`);
    }

    // 📈 高低差
    const gain = dest.elevation_gain != null ? Number(dest.elevation_gain) : null;
    const elev = dest.elevation     != null ? Number(dest.elevation)      : null;
    if (gain !== null && elev !== null) {
        const isPos     = gain >= 0;
        const gainStr   = (isPos ? '+' : '') + gain.toFixed(1) + 'm';
        const currentEl = elev - gain;
        const dirLabel  = isPos ? '高い' : '低い';
        rows.push(`
            <div class="recommend-row">
                <span class="recommend-icon">📈</span>
                <div>
                    <div class="recommend-title${isPos ? '' : ' is-negative'}">現在地より ${gainStr} ${dirLabel}</div>
                    <div class="recommend-desc">標高 ${elev.toFixed(1)}m（現在地 ${currentEl.toFixed(1)}m）</div>
                </div>
            </div>`);
    }

    // 🚶 最寄りの安全な場所（rank === 0 のみ）
    if (rank === 0) {
        rows.push(`
            <div class="recommend-row">
                <span class="recommend-icon">🚶</span>
                <div>
                    <div class="recommend-title">最寄りの安全な場所</div>
                    <div class="recommend-desc">検索範囲内で最も近い</div>
                </div>
            </div>`);
    }

    if (rows.length === 0) return '';
    return `<div class="recommend-section">
        <div class="recommend-header">── この避難所をすすめる理由 ──</div>
        ${rows.join('')}
    </div>`;
}

// ── 推奨避難先カード ──────────────────────────────────────────────────────

function displayRecommended(rec, meta) {
    const panel = document.getElementById('recommendedPanel');
    const card = document.getElementById('recommendedCard');
    if (!panel || !card || !rec) return;

    const hazardBadge = rec.hazard_safe === true
        ? '<span class="hazard-safe-badge safe">✅ 危険区域外</span>'
        : rec.hazard_safe === false
            ? '<span class="hazard-safe-badge unsafe">⚠️ 危険区域内</span>'
            : '<span class="hazard-safe-badge unknown">❓ 安全性未判定</span>';
    const unknownWarning = (rec.hazard_safe == null)
        ? `<div class="recommended-unknown-warning">⚠️ ハザードデータが利用できないため、この候補の安全性は未判定です。避難前に現地の状況を確認してください。</div>`
        : '';

    const typeLabel = rec.type === 'emergency_shelter' ? '指定緊急避難場所'
        : rec.type === 'safe_high_ground_candidate' ? '高台候補地点'
        : rec.type || '';

    let metaNote = '';
    if (meta) {
        const tierLabels = { safe: '安全候補から選定', unknown: '未判定候補から選定', unsafe: '危険区域内（fallback）' };
        const tierLabel = tierLabels[meta.selected_tier] || meta.selected_tier || '-';
        metaNote = `<div class="recommendation-meta-note">
            安全候補数: ${meta.safe_candidates_found} / ${meta.total_candidates_found} 件 ｜
            選定: ${tierLabel}
        </div>`;
    }

    const cardStateClass = rec.hazard_safe === true ? 'safe'
        : rec.hazard_safe === false ? 'unsafe'
        : 'unknown';
    const provisionalLabel = (rec.hazard_safe == null)
        ? '<span class="recommended-provisional-label">暫定推奨</span>'
        : '';

    const dangerWarningBanner = rec.time_margin_status === 'danger'
        ? `<div class="recommended-warning">🚨 津波到達前に避難が完了しない可能性があります</div>`
        : '';

    card.innerHTML = `
        <div class="recommended-card ${cardStateClass}">
            <div class="recommended-name">📍 ${rec.name}${provisionalLabel}</div>
            <div class="recommended-type">${typeLabel} ${hazardBadge}</div>
            ${dangerWarningBanner}
            <div class="recommended-stats">
                <span>⬆️ 標高差: +${rec.elevation_gain.toFixed(1)}m</span>
                <span>🏔️ 標高: ${rec.elevation.toFixed(1)}m</span>
                <span>📏 距離: ${rec.distance.toFixed(0)}m</span>
                <span>⏱️ 約${rec.estimated_time_minutes.toFixed(0)}分</span>
                <span>スコア: ${rec.safety_score.toFixed(1)}</span>
            </div>
            ${renderTimeMarginBlock(rec)}
            ${unknownWarning}
            ${renderHazardAssessmentBlock(rec.hazard_assessment)}
            ${rec.reason ? `<div class="recommended-reason">💬 ${rec.reason}</div>` : ''}
            <button class="recommended-btn ${cardStateClass}" id="recommendedRouteBtn">${cardStateClass === 'unsafe' ? '⚠️ 注意して案内' : '🚶 今すぐ案内'}</button>
        </div>
        ${metaNote}
    `;

    const btn = document.getElementById('recommendedRouteBtn');
    if (btn) {
        btn.addEventListener('click', () => {
            const idx = destinations.findIndex(d =>
                Math.abs(d.lat - rec.lat) < 1e-8 && Math.abs(d.lon - rec.lon) < 1e-8
            );
            if (idx >= 0) {
                showRoute(destinations[idx], idx, { ensureCardVisible: true });
            } else {
                drawRouteTo(rec.lat, rec.lon, {});
            }
        });
    }

    panel.style.display = 'block';
}

function hideRecommended() {
    const panel = document.getElementById('recommendedPanel');
    if (panel) panel.style.display = 'none';
}

// ── カード・ナビゲーション状態 ────────────────────────────────────────────

function setSelectedDestinationCard(index) {
    document.querySelectorAll('.destination-card').forEach((card, cardIndex) => {
        card.classList.toggle('selected', cardIndex === index);
    });
}

function updateNavigatingState(index) {
    activeNavigatingIndex = index;

    // 既存のナビ開始・停止・再ルートボタン（カード内）を全削除
    document.querySelectorAll('.nav-start-in-card, .nav-stop-in-card, .nav-reroute-same-in-card, .nav-reroute-new-in-card').forEach(el => el.remove());

    document.querySelectorAll('.destination-card').forEach((card, cardIndex) => {
        card.classList.toggle('navigating', cardIndex === index);
    });

    document.querySelectorAll('.dest-guide-btn').forEach((btn) => {
        const btnIndex = parseInt(btn.dataset.destIndex, 10);
        const dest = destinations[btnIndex];
        if (btnIndex === index) {
            btn.textContent = '✅ 案内中';
            btn.classList.add('navigating');
            _injectNavStopBtn(btn);
        } else {
            btn.textContent = (dest && dest.hazard_safe === false) ? '⚠️ 案内' : '案内';
            btn.classList.remove('navigating');
        }
    });

    const recBtn = document.getElementById('recommendedRouteBtn');
    if (recBtn && evacuationRecommended) {
        const dest = destinations[index];
        const isRecNavigating = dest
            && Math.abs(dest.lat - evacuationRecommended.lat) < 1e-8
            && Math.abs(dest.lon - evacuationRecommended.lon) < 1e-8;
        if (isRecNavigating) {
            recBtn.textContent = '✅ 案内中';
            recBtn.classList.add('navigating');
            _injectNavStopBtn(recBtn);
        } else {
            const recSafe = evacuationRecommended.hazard_safe;
            recBtn.classList.remove('navigating', 'safe', 'unsafe', 'unknown');
            if (recSafe === true) {
                recBtn.classList.add('safe');
                recBtn.textContent = '🚶 今すぐ案内';
            } else if (recSafe === false) {
                recBtn.classList.add('unsafe');
                recBtn.textContent = '⚠️ 注意して案内';
            } else {
                recBtn.classList.add('unknown');
                recBtn.textContent = '🚶 今すぐ案内';
            }
        }
    }
}

function _injectNavStopBtn(afterElement) {
    // ナビ開始ボタン
    const startBtn = document.createElement('button');
    startBtn.className = 'btn btn-primary nav-start-in-card';
    startBtn.textContent = '🚶 ナビ開始';
    startBtn.style.marginTop = '8px';
    startBtn.style.width = '100%';
    startBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (typeof startNavigation === 'function') startNavigation();
    });

    // ナビ停止ボタン
    const stopBtn = document.createElement('button');
    stopBtn.className = 'btn btn-danger nav-stop-in-card';
    stopBtn.textContent = '⏹ ナビ停止';
    stopBtn.style.display = 'none'; // _updateNavUI が制御
    stopBtn.style.marginTop = '8px';
    stopBtn.style.width = '100%';
    stopBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (typeof stopNavigation === 'function') stopNavigation();
    });

    // 同じ避難先へ再ルートボタン（逸脱時のみ表示・navigation.js が制御）
    const rerouteSameBtn = document.createElement('button');
    rerouteSameBtn.className = 'btn btn-secondary nav-reroute-same-in-card';
    rerouteSameBtn.textContent = '🔄 同じ避難先へ再ルート';
    rerouteSameBtn.style.display = 'none';
    rerouteSameBtn.style.marginTop = '4px';
    rerouteSameBtn.style.width = '100%';
    rerouteSameBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (typeof rerouteToSameDestination === 'function') rerouteToSameDestination();
    });

    // 避難先を再検索ボタン（逸脱時のみ表示）
    const rerouteNewBtn = document.createElement('button');
    rerouteNewBtn.className = 'btn btn-secondary nav-reroute-new-in-card';
    rerouteNewBtn.textContent = '🔍 避難先を再検索';
    rerouteNewBtn.style.display = 'none';
    rerouteNewBtn.style.marginTop = '4px';
    rerouteNewBtn.style.width = '100%';
    rerouteNewBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        if (typeof rerouteWithNewSearch === 'function') rerouteWithNewSearch();
    });

    afterElement.insertAdjacentElement('afterend', rerouteNewBtn);
    afterElement.insertAdjacentElement('afterend', rerouteSameBtn);
    afterElement.insertAdjacentElement('afterend', stopBtn);
    afterElement.insertAdjacentElement('afterend', startBtn);
}

// ── RSA（到達可能安全エリア） ─────────────────────────────────────────────

const RSA_STYLE = {
    color: '#2e7d32',
    weight: 2,
    opacity: 0.8,
    fillColor: '#66bb6a',
    fillOpacity: 0.25,
};

function clearRsaLayer() {
    if (reachableSafeAreaLayer) {
        map.removeLayer(reachableSafeAreaLayer);
        reachableSafeAreaLayer = null;
    }
}

function displayRsa(rsa) {
    const panel = document.getElementById('rsaPanel');
    const info  = document.getElementById('rsaInfo');

    clearRsaLayer();

    if (!rsa || !rsa.enabled || rsa.exists === null) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';

    const areaKm2 = rsa.area_m2 != null ? (rsa.area_m2 / 1_000_000).toFixed(2) : null;
    const existsBadge = rsa.exists
        ? '<span class="rsa-exists-badge yes">✅ 避難可能エリアあり</span>'
        : '<span class="rsa-exists-badge no">❌ 避難可能エリアなし</span>';

    const warningBlock = !rsa.exists
        ? `<div class="rsa-warning">
            🚨 現在地からの水平避難が難しい可能性があります。<br>
            近隣の高い建物への垂直避難も検討してください。
           </div>`
        : '';

    info.innerHTML = `
        ${existsBadge}
        <div class="rsa-stat"><span class="rsa-stat-label">到達可能半径</span><span class="rsa-stat-value">約${rsa.radius_m != null ? Math.round(rsa.radius_m) : '—'} m</span></div>
        <div class="rsa-stat"><span class="rsa-stat-label">津波到達まで</span><span class="rsa-stat-value">${rsa.time_to_impact_minutes != null ? rsa.time_to_impact_minutes.toFixed(1) : '—'} 分</span></div>
        <div class="rsa-stat"><span class="rsa-stat-label">歩行速度</span><span class="rsa-stat-value">${rsa.walking_speed_mps} m/s</span></div>
        ${areaKm2 != null ? `<div class="rsa-stat"><span class="rsa-stat-label">安全エリア面積</span><span class="rsa-stat-value">約${areaKm2} km²</span></div>` : ''}
        ${warningBlock}
    `;

    if (rsa.exists && rsa.geometry) {
        reachableSafeAreaLayer = L.geoJSON(rsa.geometry, { style: RSA_STYLE }).addTo(map);
        reachableSafeAreaLayer.bringToBack();
    }
}

// ── マーカー・検索結果のクリア ────────────────────────────────────────────

function clearDestinationMarkers() {
    destinationMarkers.forEach(marker => map.removeLayer(marker));
    destinationMarkers = [];
    destinationMarkerBaseStyles = [];
}

function clearSearchResults() {
    // ナビ中にクリアされた場合はナビを停止する
    if (typeof navigationMode !== 'undefined' && typeof stopNavigation === 'function' &&
        (navigationMode === 'navigation_active' || navigationMode === 'navigation_warning' ||
         navigationMode === 'navigation_paused')) {
        stopNavigation();
    }
    // 手動設定のゴールピン・ルートもクリア
    if (typeof clearUserDestination === 'function') clearUserDestination();
    clearDestinationMarkers();
    clearRsaLayer();
    document.getElementById('rsaPanel').style.display = 'none';

    if (routingControl) {
        map.removeControl(routingControl);
        routingControl = null;
    }
    clearSelectedRouteHighlight();
    clearRouteCandidateLayers();
    clearRouteStepFocusMarker();

    document.getElementById('destinationsPanel').style.display = 'none';
    destinations = [];
    evacuationRecommended = null;
    evacuationHazardStatus = null;
    evacuationMeta = null;
    activeNavigatingIndex = null;
    hasSearchedDestinations = false;
    hideSearchMessage();
    hideSelectedEmergencyShelter();
    hideDangerStatus();
    hideRecommended();

    // ナビバナー・音声案内バーの残存表示をクリア
    const navBanner = document.getElementById('navBanner');
    if (navBanner) navBanner.style.display = 'none';
    const announcementBar = document.getElementById('nav-announcement-bar');
    if (announcementBar) announcementBar.style.display = 'none';
}

// ── 指定緊急避難場所の選択情報 ───────────────────────────────────────────

function showSelectedEmergencyShelter(site) {
    const transportLabel = document.getElementById('transportMode').value === 'walking' ? '徒歩' : '車';

    // サイドパネル更新
    document.getElementById('selectedShelterName').textContent = site.name || '名称未設定';
    document.getElementById('selectedShelterDesignation').textContent = site.designation || '指定緊急避難場所';
    document.getElementById('selectedShelterAddress').textContent = site.address || '-';
    document.getElementById('selectedShelterLat').textContent = Number(site.lat).toFixed(6);
    document.getElementById('selectedShelterLon').textContent = Number(site.lon).toFixed(6);
    document.getElementById('selectedShelterTransport').textContent = transportLabel;
    document.getElementById('selectedShelterDistance').textContent = '計算中...';
    document.getElementById('selectedShelterDuration').textContent = '計算中...';
    clearSelectedEmergencyShelterRouteGuidance();
    document.getElementById('selectedShelterInfo').style.display = 'block';

    // 地図カード更新
    document.getElementById('shelter-card-name').textContent = site.name || '名称未設定';
    document.getElementById('shelter-card-designation').textContent = site.designation || '指定緊急避難場所';
    const addrEl = document.getElementById('shelter-card-address');
    if (site.address) {
        addrEl.textContent = '📍 ' + site.address;
        addrEl.style.display = 'block';
    } else {
        addrEl.style.display = 'none';
    }
    document.getElementById('shelter-card-transport').textContent = transportLabel;

    // 直線距離 → 暫定徒歩時間（距離m ÷ 80 = 分）
    let estimatedDist = null;
    if (typeof currentLocation !== 'undefined' && currentLocation) {
        const dlat = (site.lat - currentLocation.lat) * 111000;
        const dlon = (site.lon - currentLocation.lon) * 111000 * Math.cos(site.lat * Math.PI / 180);
        estimatedDist = Math.round(Math.sqrt(dlat * dlat + dlon * dlon));
    }
    if (estimatedDist !== null) {
        document.getElementById('shelter-card-distance').textContent =
            estimatedDist < 1000 ? `約 ${estimatedDist} m` : `約 ${(estimatedDist / 1000).toFixed(1)} km`;
        const estMin = Math.max(1, Math.round(estimatedDist / 80));
        document.getElementById('shelter-card-duration').textContent = `約 ${estMin} 分`;
    } else {
        document.getElementById('shelter-card-distance').textContent = '計算中...';
        document.getElementById('shelter-card-duration').textContent = '計算中...';
    }

    // 対応ハザードアイコンをカードに表示
    const hazardBlock = document.getElementById('shelter-card-hazard-block');
    if (hazardBlock) {
        const hazardTypes = Array.isArray(site.hazard_types) ? site.hazard_types : [];
        const HAZARD_ICON = {
            tsunami:     '🌊 津波',
            flood:       '🌧 洪水',
            storm_surge: '🌬 高潮',
            earthquake:  '🏚 地震',
            landslide:   '🏔 崖崩れ',
            fire:        '🔥 大規模火事',
            inland_flood:'💧 内水氾濫',
            volcano:     '🌋 火山',
        };
        if (hazardTypes.length > 0) {
            hazardBlock.innerHTML =
                '<div id="shelter-hazard-label" style="font-size:10px;color:#888;margin-bottom:2px;">対応ハザード</div>' +
                '<div>' +
                hazardTypes.map(h =>
                    `<span class="shelter-hazard-tag">${HAZARD_ICON[h] || h}</span>`
                ).join('') +
                '</div>';
        } else {
            hazardBlock.innerHTML = '<div style="font-size:11px;color:#aaa;">対応ハザード情報なし</div>';
        }
    }
    // elev-score は destination 候補で非表示にされることがあるためリセット
    const elevScoreEl2 = document.getElementById('shelter-card-elev-score');
    if (elevScoreEl2) elevScoreEl2.style.display = 'none';

    document.getElementById('shelter-card-dest-info').style.display = 'block';
    _showFloatCardCentered();
}

function _showFloatCardCentered() {
    // タブ自動遷移は行わない。ナビ開始ボタンへのアクセスを妨げないよう
    // 操作タブはユーザーの手動操作でのみ切り替える。
}

// ── 実ルート値フォーマット（カード表示用）───────────────────────────────────
function _formatCardDistance(meters) {
    const m = Number(meters) || 0;
    if (m < 1000) return `${Math.round(m)} m`;
    return `${(m / 1000).toFixed(1)} km`;
}
function _formatCardDuration(seconds) {
    const min = Math.floor((Number(seconds) || 0) / 60);
    return min <= 0 ? '1分未満' : `約${min}分`;
}

// フロートカードの距離・時間を実ルート値で上書き（候補・避難所共通）
function updateShelterCardRouteInfo(distanceMeters, durationSeconds) {
    document.getElementById('shelter-card-distance').textContent = _formatCardDistance(distanceMeters);
    document.getElementById('shelter-card-duration').textContent = _formatCardDuration(durationSeconds);
}

// フロートカードのルート危険度ブロックを更新（ルート取得後に呼ぶ）
function updateShelterCardRiskInfo(route) {
    const el = document.getElementById('shelter-card-route-risk');
    if (!el) return;
    el.innerHTML = '';
    el.style.display = 'none';
    if (!route) return;
    const riskSummary = route.__riskSummary;
    if (!riskSummary) return;
    const notes = riskSummary.risk_summary?.notes || [];
    const score = Math.round(riskSummary.safety_score ?? 100);
    if (notes.length === 0 && score >= 95) return;
    if (typeof _appendRouteRiskBlock === 'function') {
        _appendRouteRiskBlock(el, route);
    }
    el.style.display = '';
}

function updateSelectedEmergencyShelterRouteInfo(distanceMeters, durationSeconds, transportMode) {
    const transportLabel = transportMode === 'walking' ? '徒歩' : '車';
    const distText = _formatCardDistance(distanceMeters);
    const durText  = _formatCardDuration(durationSeconds);

    // サイドパネル更新
    document.getElementById('selectedShelterTransport').textContent = transportLabel;
    document.getElementById('selectedShelterDistance').textContent = distText;
    document.getElementById('selectedShelterDuration').textContent = durText;

    // 地図カード更新
    document.getElementById('shelter-card-transport').textContent = transportLabel;
    updateShelterCardRouteInfo(distanceMeters, durationSeconds);
}

// 番号付きピン（①②③）タップ時にフロートカードへ全情報を表示
function showDestInFloatCard(dest, rank = null) {
    try {
        const transportLabel = document.getElementById('transportMode').value === 'walking' ? '徒歩' : '車';

        document.getElementById('shelter-card-name').textContent = dest.name || '避難先候補';

        // designation 欄：安全バッジ＋スコア
        const hazardBadge = dest.hazard_safe === true
            ? '<span class="hazard-safe-badge safe">✅ 危険区域外</span>'
            : dest.hazard_safe === false
                ? '<span class="hazard-safe-badge unsafe">⚠️ 危険区域内</span>'
                : '<span class="hazard-safe-badge unknown">❓ 安全性未判定</span>';
        const score = dest.safety_score != null ? Number(dest.safety_score).toFixed(1) : '—';
        document.getElementById('shelter-card-designation').innerHTML =
            `${hazardBadge}&nbsp;<span class="safety-score">スコア ${score}</span>`;

        document.getElementById('shelter-card-address').style.display = 'none';

        document.getElementById('shelter-card-transport').textContent = transportLabel;
        document.getElementById('shelter-card-distance').textContent = '計算中...';
        document.getElementById('shelter-card-duration').textContent = '計算中...';

        // 推奨理由セクション＋ハザード詳細（従来の hazard-block を置き換え）
        const recommendHtml = _buildRecommendSection(dest, rank);
        const hazardDetailHtml = buildHazardReasonBlock(dest.hazard_assessment);
        document.getElementById('shelter-card-hazard-block').innerHTML =
            recommendHtml + hazardDetailHtml;

        // 標高行は推奨理由に統合したため非表示
        const elevScoreEl = document.getElementById('shelter-card-elev-score');
        if (elevScoreEl) elevScoreEl.style.display = 'none';

        // コメント
        const commentEl = document.getElementById('shelter-card-comment');
        if (dest.comment) {
            commentEl.textContent = '💬 ' + dest.comment;
            commentEl.style.display = 'block';
        } else {
            commentEl.style.display = 'none';
        }

        document.getElementById('shelter-card-dest-info').style.display = 'block';
        document.getElementById('shelter-card-route-guidance').innerHTML = '';
    } catch (e) {
        console.error('[showDestInFloatCard] error:', e);
    }

    _showFloatCardCentered();
}

// ゴールピンタップ時にフロートカードへルート案内を表示
function showUserDestInFloatCard() {
    if (!userDestination) return;
    const transportLabel = document.getElementById('transportMode').value === 'walking' ? '徒歩' : '車';

    document.getElementById('shelter-card-name').textContent = userDestination.name || '目的地';
    document.getElementById('shelter-card-designation').textContent = '手動設定の目的地';
    document.getElementById('shelter-card-address').style.display = 'none';
    document.getElementById('shelter-card-transport').textContent = transportLabel;

    // 距離・時間をサイドバーパネルから読み取って反映
    // （ルート案内本体は renderUserDestRouteGuidance が直接 shelter-card-route-guidance に描画済み）
    const srcPanel = document.getElementById('userDestRouteGuidance');
    if (srcPanel) {
        const summary = srcPanel.querySelector('.route-guidance-summary');
        if (summary) {
            const text = summary.textContent;
            const distMatch = text.match(/距離:\s*([^\s/]+(?:\s*(?:km|m))?)/);
            const durMatch  = text.match(/所要時間:\s*(.+)/);
            document.getElementById('shelter-card-distance').textContent = distMatch ? distMatch[1] : '-';
            document.getElementById('shelter-card-duration').textContent = durMatch  ? durMatch[1]  : '-';
        } else {
            document.getElementById('shelter-card-distance').textContent = '-';
            document.getElementById('shelter-card-duration').textContent = '-';
        }
    }

    document.getElementById('shelter-card-dest-info').style.display = 'none';

    // shelter-card-route-guidance を常に最新のルート案内で再描画する
    // （他用途でクリアされた後でも正しく表示されるよう毎回再描画）
    if (typeof rerenderUserDestFloatCard === 'function') {
        rerenderUserDestFloatCard();
    }

    _showFloatCardCentered();
}

function hideSelectedEmergencyShelter() {
    clearSelectedEmergencyShelterRouteGuidance();
    document.getElementById('selectedShelterInfo').style.display = 'none';
    // タブ自動遷移は行わない
    selectedEmergencyShelterSite   = null;
    selectedEmergencyShelterMarker = null;
}

// ── メッセージ・ステータステキスト ────────────────────────────────────────

function showSearchMessage(message, type = 'info') {
    const messageEl = document.getElementById('searchMessage');
    messageEl.textContent = message;
    messageEl.className = `search-message ${type}`;
    messageEl.style.display = 'block';
}

function hideSearchMessage() {
    const messageEl = document.getElementById('searchMessage');
    messageEl.textContent = '';
    messageEl.className = 'search-message';
    messageEl.style.display = 'none';
}

// ── 地図オーバーレイ トースト ────────────────────────────────────────────
let _mapToastTimer = null;

function showMapToast(message, { warn = false, durationMs = 6000 } = {}) {
    const el = document.getElementById('map-toast');
    if (!el) return;
    if (_mapToastTimer) { clearTimeout(_mapToastTimer); _mapToastTimer = null; }
    el.textContent = message;
    el.className = warn ? 'map-toast--warn' : '';
    el.style.display = 'block';
    _mapToastTimer = setTimeout(() => {
        el.style.display = 'none';
        _mapToastTimer = null;
    }, durationMs);
}

function hideMapToast() {
    if (_mapToastTimer) { clearTimeout(_mapToastTimer); _mapToastTimer = null; }
    const el = document.getElementById('map-toast');
    if (el) el.style.display = 'none';
}

function setShelterStatus(message) {
    document.getElementById('shelterStatus').textContent = message;
}

function setHazardStatus(message) {
    document.getElementById('hazardStatus').textContent = message;
}

function setFloodStatus(message) {
    const el = document.getElementById('floodStatus');
    if (el) el.textContent = message;
}

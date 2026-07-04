// /live/stream — 地図レンダラ (中央 & 各小窓で共用)
// 将来: Leaflet / 既存 /live 地図基盤へ差し替え可能なよう独立モジュールとして実装
// 座標系: SVG viewBox 0 0 1000 1300 (at:[x,y] はこの座標)
// 実本番では緯度経度 → SVG座標への投影変換を挟む

const MAP_PATHS = `
  <path d="M612,150 C648,108 742,104 800,146 C842,176 832,250 778,268 C726,285 648,272 618,228 C600,202 596,170 612,150 Z"/>
  <path d="M700,300 C724,322 724,352 720,388 C716,440 730,470 724,506 C720,532 700,548 668,560 C600,584 520,600 452,648 C392,690 332,726 268,758 C244,770 232,748 256,732 C320,694 388,660 446,620 C512,576 576,544 612,498 C646,454 656,398 662,352 C666,320 680,294 700,300 Z"/>
  <path d="M322,792 C360,784 404,794 408,824 C412,852 372,872 326,866 C292,861 276,834 290,812 C298,800 310,795 322,792 Z"/>
  <path d="M236,772 C272,764 300,790 300,828 C300,876 278,940 244,960 C220,974 198,956 200,916 C203,866 214,808 226,780 C229,776 232,773 236,772 Z"/>
  <circle cx="160" cy="1110" r="12"/><circle cx="138" cy="1156" r="9"/><circle cx="120" cy="1200" r="7"/>`;

let _gridStr = '';
for (let x = 100; x <= 900; x += 100) _gridStr += `<line x1="${x}" y1="60" x2="${x}" y2="1240"/>`;
for (let y = 100; y <= 1200; y += 100) _gridStr += `<line x1="60" y1="${y}" x2="940" y2="${y}"/>`;

function renderMap(el, {view = {zoom:1, cx:500, cy:650}, markers = [], rain = [], rail = [], graticule = false} = {}) {
  const z = view.zoom, cx = view.cx, cy = view.cy;
  const tf = `translate(500 650) scale(${z}) translate(${-cx} ${-cy})`;
  const grid = graticule
    ? `<g opacity="0.5" stroke="rgba(86,128,180,0.16)" stroke-width="1">${_gridStr}</g>`
    : '';
  const rainStr = rain.map(([x,y,r,o]) =>
    `<circle cx="${x}" cy="${y}" r="${r}" fill="var(--c-rain)" opacity="${o}"/>`
  ).join('');
  const railStr = rail.map(l =>
    `<polyline points="${l.points}" stroke="${l.color}" stroke-width="${l.w}" opacity="${l.o}" fill="none" stroke-linecap="round" stroke-linejoin="round"/>`
  ).join('');
  const mk = markers.map(m => {
    const r = m.r || 9, inv = 1 / z;
    const tid = m.testid ? ` data-testid="${m.testid}"` : '';
    // Stream Phase 5-A.1: 市区町村震度マーカー等、既存パルス(震源)マーカーと異なる見た目/属性を
    // 個別に指定したい呼び出し元向けの任意拡張点。未指定時は従来通りの震源パルス表示のまま。
    const cls = m.cls ? ` class="${m.cls}"` : '';
    const attrs = m.attrs || '';
    const ring = m.noRing ? '' : `<circle cx="0" cy="0" r="${r+4}" fill="none" stroke="${m.color}" stroke-width="2.5" style="transform-box:fill-box;transform-origin:center;animation:ring 2.4s ease-out infinite"/>`;
    return `<g transform="translate(${m.x} ${m.y}) scale(${inv})"${tid}${cls}${attrs}>
      ${ring}
      <circle cx="0" cy="0" r="${r}" fill="${m.color}" stroke="rgba(255,255,255,.9)" stroke-width="2" style="${m.noRing ? '' : 'animation:core 2.4s ease-in-out infinite'}"/>
      ${m.label ? `<text x="0" y="${-(r+8)}" text-anchor="middle" font-family="var(--mono)" font-size="${m.fs||16}" font-weight="700" fill="#fff">${m.label}</text>` : ''}
    </g>`;
  }).join('');
  el.innerHTML = `<svg viewBox="0 0 1000 1300" preserveAspectRatio="xMidYMid meet" style="width:100%;height:100%;display:block">
    <defs>
      <filter id="soft" x="-40%" y="-40%" width="180%" height="180%"><feGaussianBlur stdDeviation="13"/></filter>
      <radialGradient id="sea" cx="50%" cy="42%" r="75%"><stop offset="0%" stop-color="#0e1622"/><stop offset="100%" stop-color="#070a11"/></radialGradient>
    </defs>
    <rect width="1000" height="1300" fill="url(#sea)"/>
    <g transform="${tf}">
      ${grid}
      <g fill="#1c2735" stroke="rgba(125,172,228,0.42)" stroke-width="1.6" stroke-linejoin="round">${MAP_PATHS}</g>
      <g filter="url(#soft)">${rainStr}</g>
      <g>${railStr}</g>
      ${mk}
    </g>
  </svg>`;
}

// easeOutCubic — ズームアニメーション用
const EASE = x => 1 - Math.pow(1 - x, 3);

// 全国ビュー → 対象地点へ 900ms でズームアップ (rAF トゥイーン)
// el.__raf に進行中のハンドルを保持し、切替時に cancelAnimationFrame する
function zoomToTarget(el, toView, opts, dur = 900) {
  const from = {zoom:1, cx:500, cy:650};
  if (el.__raf) cancelAnimationFrame(el.__raf);
  const t0 = performance.now();
  function step(now) {
    const k = Math.min(1, (now - t0) / dur), e = EASE(k);
    const v = {
      zoom: from.zoom + (toView.zoom - from.zoom) * e,
      cx:   from.cx   + (toView.cx   - from.cx)   * e,
      cy:   from.cy   + (toView.cy   - from.cy)   * e,
    };
    renderMap(el, {...opts, view:v});
    if (k < 1) el.__raf = requestAnimationFrame(step);
    else        el.__raf = null;
  }
  el.__raf = requestAnimationFrame(step);
}

/**
 * 実潮位データカーブ SVG (時間別記録データから描画)
 * @param {HTMLElement} el    描画先
 * @param {object}      st    潮位ステーション (records:[{h,cm}], highData, lowData, alert)
 * @param {number}      curHF 現在時刻 (小数時間 e.g. 19.7 = 19:42)
 */
function renderTideFromRecords(el, st, curHF) {
  const allRec   = (st.records  || []).slice().sort((a, b) => a.h - b.h);
  const highData = st.highData || [];
  const lowData  = st.lowData  || [];
  const x0 = 30, x1 = 336, y0 = 10, y1 = 94;

  // ±12h ウィンドウ: 現在時刻を常に中央に固定。左=過去、右=未来。
  const halfW  = 12;
  const tStart = curHF - halfW;
  const tEnd   = curHF + halfW;
  const curX   = (x0 + x1) / 2; // 常に中央 = X(curHF)
  const X = h  => x0 + ((h - tStart) / (tEnd - tStart)) * (x1 - x0);

  // ウィンドウ内のレコード (1h バッファで曲線が端まで引けるようにする)
  const records = allRec.filter(r => r.h >= tStart - 1 && r.h <= tEnd + 1);

  if (records.length === 0) {
    el.innerHTML = `<svg viewBox="0 0 346 106" preserveAspectRatio="none" style="width:100%;height:100%;display:block"><rect width="346" height="106" fill="none"/><text x="173" y="57" text-anchor="middle" font-size="11" fill="rgba(148,163,184,.8)">データなし</text></svg>`;
    return;
  }

  // Y スケールはウィンドウ内のデータで決定
  const cms = records.map(r => r.cm);
  let cmMin = Math.min(...cms), cmMax = Math.max(...cms);
  const cmPad = Math.max(20, (cmMax - cmMin) * 0.12);
  cmMin -= cmPad; cmMax += cmPad;
  if (cmMax <= cmMin) { cmMin -= 10; cmMax += 10; }
  const Y = cm => y1 - ((cm - cmMin) / (cmMax - cmMin)) * (y1 - y0);

  let line = '';
  records.forEach((r, i) => {
    line += (i ? 'L' : 'M') + X(r.h).toFixed(1) + ' ' + Y(r.cm).toFixed(1) + ' ';
  });
  const area = line
    + `L${X(records[records.length - 1].h).toFixed(1)} ${y1}`
    + ` L${X(records[0].h).toFixed(1)} ${y1} Z`;

  // 現在潮位 — 全レコードから線形補間
  let curCm = allRec.length ? allRec[0].cm : 0;
  if (allRec.length && curHF >= allRec[allRec.length - 1].h) {
    curCm = allRec[allRec.length - 1].cm;
  } else {
    for (let i = 0; i < allRec.length - 1; i++) {
      const a = allRec[i], b = allRec[i + 1];
      if (a.h <= curHF && curHF <= b.h && b.h > a.h) {
        curCm = a.cm + (curHF - a.h) / (b.h - a.h) * (b.cm - a.cm);
        break;
      }
    }
  }

  // グリッド: ±3h, ±6h, ±9h (現在時刻中央基準)
  const vg = [curHF - 9, curHF - 6, curHF - 3, curHF + 3, curHF + 6, curHF + 9];
  const accent = st.alert ? '#e879f9' : 'var(--c-tide-2)';

  const hiDots = highData
    .filter(e => e.h >= tStart && e.h <= tEnd)
    .map(e => `<circle cx="${X(e.h).toFixed(1)}" cy="${Y(e.cm).toFixed(1)}" r="3.5" fill="none" stroke="${accent}" stroke-width="1.8"/>`)
    .join('');
  const loDots = lowData
    .filter(e => e.h >= tStart && e.h <= tEnd)
    .map(e => `<circle cx="${X(e.h).toFixed(1)}" cy="${Y(e.cm).toFixed(1)}" r="3.5" fill="none" stroke="rgba(120,200,255,.9)" stroke-width="1.8"/>`)
    .join('');

  el.innerHTML = `<svg viewBox="0 0 346 106" preserveAspectRatio="none" style="width:100%;height:100%;display:block">
    <g stroke="rgba(180,150,220,0.14)" stroke-width="1">
      <line x1="${x0}" y1="${y0}" x2="${x0}" y2="${y1}"/>
      <line x1="${x0}" y1="${y1}" x2="${x1}" y2="${y1}"/>
      ${vg.map(t => `<line x1="${X(t).toFixed(1)}" y1="${y0+4}" x2="${X(t).toFixed(1)}" y2="${y1}"/>`).join('')}
    </g>
    <path d="${area}" fill="rgba(170,80,210,0.14)"/>
    <path d="${line.trim()}" fill="none" stroke="${accent}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" data-testid="live-stream-tide-curve"/>
    <line x1="${curX.toFixed(1)}" y1="${y0}" x2="${curX.toFixed(1)}" y2="${y1}" stroke="${accent}" stroke-width="1.2" stroke-dasharray="3 3" opacity=".8"/>
    ${hiDots}${loDots}
    <circle cx="${curX.toFixed(1)}" cy="${Y(curCm).toFixed(1)}" r="4.5" fill="${accent}" stroke="#fff" stroke-width="1.8" data-testid="live-stream-tide-current-marker"/>
  </svg>`;
}

/**
 * 潮位カーブ SVG (正弦近似モデル)
 * @param {HTMLElement} el              描画先
 * @param {object}      st              潮位ステーション (base, amp, phase, alert)
 * @param {number}      currentHourFloat 現在時刻 (時間単位の小数 e.g. 19.7 = 19:42)
 *                                       LiveStreamClock.getCurrentHourFloat() から渡す
 */
function renderTide(el, st, currentHourFloat) {
  const base = st.base, amp = st.amp, phase = st.phase;
  const x0 = 30, x1 = 336, y0 = 10, y1 = 94;
  const cmMax = Math.max(220, base + amp + 20);
  const lvl = t => base + amp * Math.sin(2 * Math.PI * (t - phase) / 12.42);

  // ±12h ウィンドウ: 現在時刻を常に中央に固定。左=過去、右=未来。
  const cur    = currentHourFloat;
  const halfW  = 12;
  const tStart = cur - halfW;
  const tEnd   = cur + halfW;
  const curX   = (x0 + x1) / 2; // 常に中央 = X(cur)
  const X = t => x0 + ((t - tStart) / (tEnd - tStart)) * (x1 - x0);
  const Y = cm => y1 - (cm / cmMax) * (y1 - y0);

  let line = '';
  for (let i = 0; i <= 96; i++) {
    const t = tStart + (i / 96) * (tEnd - tStart);
    line += (i ? 'L' : 'M') + X(t).toFixed(1) + ' ' + Y(lvl(t)).toFixed(1) + ' ';
  }
  const area = line + `L${x1} ${y1} L${x0} ${y1} Z`;

  // ウィンドウ内の最高・最低潮位を探す
  let hiT = tStart, loT = tStart, hiV = -1e9, loV = 1e9;
  for (let t = tStart; t <= tEnd; t += 0.1) {
    const v = lvl(t);
    if (v > hiV) { hiV = v; hiT = t; }
    if (v < loV) { loV = v; loT = t; }
  }

  // グリッド: ±3h, ±6h, ±9h
  const vg = [cur - 9, cur - 6, cur - 3, cur + 3, cur + 6, cur + 9];
  const accent = st.alert ? '#e879f9' : 'var(--c-tide-2)';
  el.innerHTML = `<svg viewBox="0 0 346 106" preserveAspectRatio="none" style="width:100%;height:100%;display:block">
    <g stroke="rgba(180,150,220,0.14)" stroke-width="1">
      <line x1="${x0}" y1="${y0}" x2="${x0}" y2="${y1}"/>
      <line x1="${x0}" y1="${y1}" x2="${x1}" y2="${y1}"/>
      ${vg.map(t => `<line x1="${X(t).toFixed(1)}" y1="${y0+4}" x2="${X(t).toFixed(1)}" y2="${y1}"/>`).join('')}
    </g>
    <path d="${area}" fill="rgba(170,80,210,0.14)"/>
    <path d="${line.trim()}" fill="none" stroke="${accent}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round" data-testid="live-stream-tide-curve"/>
    <line x1="${curX.toFixed(1)}" y1="${y0}" x2="${curX.toFixed(1)}" y2="${y1}" stroke="${accent}" stroke-width="1.2" stroke-dasharray="3 3" opacity=".8"/>
    <circle cx="${X(hiT).toFixed(1)}" cy="${Y(hiV).toFixed(1)}" r="3.5" fill="none" stroke="${accent}" stroke-width="1.8"/>
    <circle cx="${X(loT).toFixed(1)}" cy="${Y(loV).toFixed(1)}" r="3.5" fill="none" stroke="rgba(120,200,255,.9)" stroke-width="1.8"/>
    <circle cx="${curX.toFixed(1)}" cy="${Y(lvl(cur)).toFixed(1)}" r="4.5" fill="${accent}" stroke="#fff" stroke-width="1.8" data-testid="live-stream-tide-current-marker"/>
  </svg>`;
}

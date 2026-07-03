// /live/stream — メイン描画 render(scene, tick)
// 時計は live-stream-clock.js で別 interval 管理。
// 毎秒フル再描画せず、モード変更 / 状態遷移 / 8秒サイクル進行時のみ再描画。
// 依存: renderMap, zoomToTarget, renderTide (live-stream-map.js)
//        RAIL_LINES_BASE, TICKER_TEXT (live-stream-scene.js)
//        LiveStreamClock (live-stream-clock.js)

const FULL_VIEW = {zoom:1, cx:500, cy:650};
const $s = id => document.getElementById(id);
let _lastTickerText = '';

// 潮位 正弦モデルで任意時刻の潮位(cm)を計算する (デモ用)
function _tideLvl(st, hourFloat) {
  return st.base + st.amp * Math.sin(2 * Math.PI * (hourFloat - st.phase) / 12.42);
}

// 実潮位記録 [{h, cm}] から時刻 h に対応する潮位を線形補間する
function _interpolateFromRecords(records, h) {
  if (!records || records.length === 0) return null;
  if (h <= records[0].h) return records[0].cm;
  if (h >= records[records.length - 1].h) return records[records.length - 1].cm;
  for (let i = 0; i < records.length - 1; i++) {
    const a = records[i], b = records[i + 1];
    if (a.h <= h && h <= b.h && b.h > a.h) {
      return Math.round(a.cm + (h - a.h) / (b.h - a.h) * (b.cm - a.cm));
    }
  }
  return records[records.length - 1].cm;
}

function render(scene, tick) {
  const eq   = scene.earthquake;
  const rain  = scene.rain;
  const rail  = scene.rail;
  const tide  = scene.tide;
  const tideAlerts = tide.stations.filter(s => s.alert);
  const eqOn   = eq.targets.length > 0;
  const rainOn  = rain.targets.length > 0;
  const railOn  = rail.affected.length > 0;
  const tideOn  = tideAlerts.length > 0;
  const calm    = !eqOn && !rainOn && !railOn && !tideOn;

  // 8秒サイクルで巡回するインデックス
  const cyc   = Math.floor(tick / 8);
  const eqI   = eqOn   ? cyc % eq.targets.length   : 0;
  const rainI  = rainOn  ? cyc % rain.targets.length : 0;
  const eqCur  = eq.targets[eqI];
  const rainCur = rain.targets[rainI];

  /* ---- ヘッダー件数 ---- */
  // statusCount: 実データ由来の件数。なければ targets.length で代替
  if (eq.status === 'error') {
    $s('ct-eq').textContent = '-';
  } else {
    $s('ct-eq').textContent = eq.statusCount != null ? eq.statusCount : eq.targets.length;
  }
  if (rain.status === 'error') {
    $s('ct-rain').textContent = '-';
  } else {
    $s('ct-rain').textContent = rainOn
      ? (rain.statusCount != null ? rain.statusCount : rain.alerts.length)
      : 0;
  }
  if (rail.status === 'error') {
    $s('ct-rail').textContent = '-';
  } else {
    $s('ct-rail').textContent = rail.affected.length;
  }
  if (tide.status === 'error') {
    $s('ct-tide').textContent = '-';
  } else {
    $s('ct-tide').textContent = tideAlerts.length;
  }

  /* ---- 中央マップ ---- */
  const cm = [], cr = [];
  if (eqOn)   cm.push({x:eqCur.at[0],   y:eqCur.at[1],   color:'var(--c-eq)',     r:(eqCur.r||12)-2, label:eqCur.s,   fs:16, testid:'live-stream-pulse-earthquake'});
  if (rainOn) {
    cm.push({x:rainCur.at[0], y:rainCur.at[1], color:'var(--c-rain-2)', r:9, label:'', testid:'live-stream-pulse-rain'});
    rainCur.cells.forEach(c => cr.push(c));
  }
  if (railOn) cm.push({x:545, y:476, color:'var(--c-rail)', r:8, label:'', testid:'live-stream-pulse-rail'});  // ポップアップ無し
  tideAlerts.forEach(s => cm.push({x:s.at[0], y:s.at[1], color:'var(--c-tide-2)', r:8, label:'', testid:'live-stream-pulse-tide'}));
  renderMap($s('center-map'), {view:FULL_VIEW, markers:cm, rain:cr, graticule:true});
  $s('center-overlay').innerHTML = calm
    ? `<div class="center-empty"><div class="ring"><div></div></div><div class="m">現在、表示対象なし</div><div class="s">ALL CLEAR · 全国の警戒情報を監視中</div></div>`
    : '';
  $s('level').dataset.lv    = calm ? 'calm' : 'high';
  $s('level-text').textContent = calm ? '平常 · 監視中' : '警戒レベル 高';

  /* ---- 地震小窓 ---- */
  if (eq.status === 'error') {
    $s('eq-meta').innerHTML = `<span class="quiet" data-testid="live-stream-earthquake-status">一時的に取得不可</span>`;
  } else if (eqOn) {
    $s('eq-meta').innerHTML = eq.targets.length > 1
      ? `<span data-testid="live-stream-earthquake-status">対象 ${eqI+1}/${eq.targets.length}</span><span class="cyc"></span><span class="cyc-note">8s切替</span>`
      : `<span data-testid="live-stream-earthquake-status">対象 1/1</span>`;
  } else {
    $s('eq-meta').innerHTML = `<span class="quiet" data-testid="live-stream-earthquake-status">監視中</span>`;
  }
  $s('eq-history').innerHTML = eq.history.map(e =>
    `<div class="row" data-testid="live-stream-earthquake-history-item"><span class="tm">${e.t}</span><span class="nm">${e.p}</span><span class="mag">${e.m}</span><span class="chip" style="background:${e.c}">${e.s}</span></div>`
  ).join('');
  if (eqOn) {
    zoomToTarget(
      $s('eq-map'),
      {zoom:3.2, cx:eqCur.at[0], cy:eqCur.at[1]},
      {markers:[{x:eqCur.at[0], y:eqCur.at[1], color:'var(--c-eq)', r:eqCur.r||15, label:eqCur.s, fs:19}]}
    );
    const depthLine = eqCur.depth ? `<div class="l">深さ ${eqCur.depth}</div>` : '';
    const tsunamiLine = eqCur.tsunami ? `<div class="l">津波: ${eqCur.tsunami}</div>` : '';
    $s('eq-overlay').innerHTML =
      `<div class="popup popup--eq zoomin" data-testid="live-stream-earthquake-popup">
        <div class="p" data-testid="live-stream-earthquake-active">${eqCur.p}</div>
        <div class="l">${eqCur.m} ・ 震度<b style="color:#fff;font-size:14px">${eqCur.s}</b> ・ ${eqCur.t}</div>
        ${depthLine}${tsunamiLine}
      </div>`;
  } else {
    const eqMapEl = $s('eq-map');
    if (eqMapEl.__raf) { cancelAnimationFrame(eqMapEl.__raf); eqMapEl.__raf = null; }
    renderMap(eqMapEl, {view:FULL_VIEW, graticule:true});
    $s('eq-overlay').innerHTML = `<div class="win-empty"><div class="m">現在 対象なし</div><div class="s">全国を監視中</div></div>`;
  }

  /* ---- 豪雨小窓 ---- */
  if (rain.status === 'error') {
    $s('rain-meta').innerHTML = `<span class="quiet" data-testid="live-stream-rain-status">一時的に取得不可</span>`;
  } else if (rainOn) {
    $s('rain-meta').innerHTML = rain.targets.length > 1
      ? `<span data-testid="live-stream-rain-status">対象 ${rainI+1}/${rain.targets.length}</span><span class="cyc"></span><span class="cyc-note">8s切替</span>`
      : `<span data-testid="live-stream-rain-status">対象 1/1</span>`;
  } else {
    $s('rain-meta').innerHTML = `<span class="quiet" data-testid="live-stream-rain-status">監視中</span>`;
  }
  $s('rain-alerts').innerHTML = rain.alerts.map(a =>
    `<div class="row" data-testid="live-stream-rain-list-item"><span class="sq" style="background:${a.cl}"></span><span class="nm">${a.r}</span><span class="lv" style="background:${a.cl}">${a.lv}</span></div>`
  ).join('') || `<div style="font:10px var(--mono);color:#5d6878;padding-top:8px">発表なし</div>`;
  if (rainOn) {
    zoomToTarget(
      $s('rain-map'),
      {zoom:3.1, cx:rainCur.at[0], cy:rainCur.at[1]},
      {rain:rainCur.cells}
    );
    const catLabel = rainCur.category ? rainCur.category + '災害' : '土砂災害';
    const amtPart  = rainCur.amt ? ` ・ ${rainCur.amt}` : '';
    $s('rain-overlay').innerHTML =
      `<div class="popup popup--rain zoomin" data-testid="live-stream-rain-popup">
        <div class="p" data-testid="live-stream-rain-active">${rainCur.r}</div>
        <div class="l">${catLabel} ・ <b style="color:${rainCur.lvColor}">${rainCur.lv}</b>${amtPart}</div>
      </div>`;
  } else {
    const rainMapEl = $s('rain-map');
    if (rainMapEl.__raf) { cancelAnimationFrame(rainMapEl.__raf); rainMapEl.__raf = null; }
    renderMap(rainMapEl, {view:FULL_VIEW, graticule:true});
    $s('rain-overlay').innerHTML = `<div class="win-empty"><div class="m">現在 対象なし</div><div class="s">全国を監視中</div></div>`;
  }

  /* ---- 鉄道小窓 (ポップアップなし・路線色カードのみ) ---- */
  {
    const affIds = new Set(rail.affected.map(a => a.mapId || a.id));
    const railGeom = RAIL_LINES_BASE.map(l => affIds.has(l.id)
      ? {points:l.points, color:l.color, w:l.id==='yamanote' ? 6 : 5, o:1}
      : {points:l.points, color:'#37445a', w:3, o:.55});
    renderMap($s('rail-map'), {view:{zoom:3.4, cx:552, cy:478}, rail:railGeom});

    if (rail.status === 'error') {
      $s('rail-meta').innerHTML = `<span class="quiet">一時的に取得不可</span>`;
      $s('rail-side').innerHTML = `<div class="rail-empty" data-testid="live-stream-rail-unavailable" style="color:#5d6878"><div class="m">一時的に取得不可</div><div class="s">鉄道情報を取得できません</div></div>`;
    } else if (railOn) {
      $s('rail-meta').innerHTML = `<span>影響 ${rail.affected.length}路線</span>`;
      $s('rail-side').innerHTML = rail.affected.map(c => {
        const mapId   = c.mapId || c.id;
        const geo     = RAIL_LINES_BASE.find(g => g.id === mapId) || {};
        const barClr  = c.lineColor || geo.color || '#7888a0';
        const updLine = c.updatedAt ? `<span class="upd" style="font:9px var(--mono);color:#5d6878;margin-left:auto">${c.updatedAt}</span>` : '';
        return `<div class="rail-card" data-testid="live-stream-rail-list-item">
           <span class="bar" style="background:${barClr}"></span>
           <div class="body">
             <div class="nm" data-testid="live-stream-rail-line-name">${c.name}</div>
             <div class="note" data-testid="live-stream-rail-section">${c.note}</div>
           </div>
           <span class="st" style="background:${c.stColor}" data-testid="live-stream-rail-status">${c.status}</span>
           ${updLine}
         </div>`;
      }).join('');
    } else {
      $s('rail-meta').innerHTML = `<span class="quiet" style="color:#7ee0a0">平常運転</span>`;
      $s('rail-side').innerHTML = `<div class="rail-empty" data-testid="live-stream-rail-empty"><i></i><div class="m">影響路線なし</div><div class="s">平常運転</div></div>`;
    }
  }

  /* ---- 潮位小窓 (2拠点を同時表示、8秒で次の2拠点へ巡回) ---- */
  {
    const N = tide.stations.length;
    if (tide.status === 'error') {
      $s('tide-meta').innerHTML = `<span class="quiet" data-testid="live-stream-tide-status">一時的に取得不可</span>`;
      $s('tide-body').innerHTML = `<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#5d6878;font:11px var(--mono)">一時的に取得不可</div>`;
    } else if (N === 0) {
      $s('tide-meta').innerHTML = `<span class="quiet" data-testid="live-stream-tide-status">監視中</span>`;
      $s('tide-body').innerHTML = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%"><div style="color:#5d6878;font:12px var(--mono)">現在、表示対象なし</div><div style="color:#3d4a5a;font:10px var(--mono);margin-top:4px">潮位データを監視中</div></div>`;
    } else {
      const pairStart = (Math.floor(tick / 8) * 2) % N;
      const shown = [0, 1].map(j => tide.stations[(pairStart + j) % N]).filter(Boolean);
      $s('tide-meta').innerHTML = N > 2
        ? `<span data-testid="live-stream-tide-status">拠点 ${(pairStart%N)+1}・${((pairStart+1)%N)+1}/${N}</span><span class="cyc"></span><span class="cyc-note">8s巡回</span>`
        : `<span data-testid="live-stream-tide-status">拠点 ${shown.length}/${N}</span>`;
      const curHF = LiveStreamClock.getCurrentHourFloat();
      $s('tide-body').innerHTML = shown.map((s, i) => {
        const isReal = !!s.source;
        const rawCm = isReal
          ? _interpolateFromRecords(s.records || [], curHF)
          : _tideLvl(s, curHF);
        const curCmStr = rawCm != null && isFinite(rawCm) ? String(Math.round(rawCm)) : '--';
        const devStr = s.dev != null ? `偏差${s.dev}` : '';
        return `<div class="tide-cell${s.alert ? ' alert' : ''}" data-testid="live-stream-tide-station">
           <div class="tide-info">
             <div class="tide-name" data-testid="live-stream-tide-station-name"><span class="dot"></span>${s.name}${s.alert ? '<span class="tide-flag">高潮警戒</span>' : ''}</div>
             <div class="tide-now" data-testid="live-stream-tide-current"><b>${curCmStr}</b><span>cm</span></div>
             <div class="tide-hl">
               <span class="hi" data-testid="live-stream-tide-high">▲${s.high}</span>
               <span class="lo" data-testid="live-stream-tide-low">▼${s.low}</span>
               ${devStr ? `<span class="dv" data-testid="live-stream-tide-deviation">${devStr}</span>` : ''}
             </div>
             ${isReal ? `<div class="tide-src" data-testid="live-stream-tide-source" style="font:9px var(--mono);color:#3d4a5a;margin-top:2px">気象庁潮位表</div>` : ''}
           </div>
           <div class="tide-chart" id="tide-chart-${i}"></div>
         </div>`;
      }).join('');
      shown.forEach((s, i) => {
        const el = $s('tide-chart-' + i);
        if (!el) return;
        if (s.source) {
          renderTideFromRecords(el, s, curHF);
        } else {
          renderTide(el, s, curHF);
        }
      });
    }
  }

  /* ---- テロップ (ticker本文が変わったときのみDOM更新してmarqueeをリセット) ---- */
  {
    const items = buildTickerItems(scene);
    const tickerText = buildTickerText(items);
    if (tickerText !== _lastTickerText) {
      _lastTickerText = tickerText;
      const a = $s('ticker-a'); if (a) a.textContent = tickerText;
      const b = $s('ticker-b'); if (b) b.textContent = tickerText;
    }
  }
}

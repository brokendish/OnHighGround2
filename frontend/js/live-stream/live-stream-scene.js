// /live/stream — SCENES & 描画用ビューモデル
// buildScene() は将来 /live 実データと差し替える差し替え口

const PT = {
  iwate:    [640, 360], miyagi:   [636, 418], fukushima: [628, 452], ibaraki:  [612, 486],
  shizuoka: [470, 582], aichi:    [428, 622], yamanashi: [500, 556], nagano:   [476, 540],
  gifu:     [430, 560], tokyo:    [582, 500], tokyoBay:  [586, 506],
};

// PT の各地点に対応する実緯度経度 — Leaflet 本番地図 (中央マップ) のパルス配置用
// PT (SVGモック座標) とは別に保持する。小窓地図は引き続き PT (SVG) を使用する。
const PT_LATLON = {
  iwate:    [39.2,  142.1], miyagi:   [38.4,  142.0], fukushima: [37.3,  141.7], ibaraki:  [36.4,  140.9],
  shizuoka: [34.9,  138.2], aichi:    [34.9,  137.3], yamanashi: [35.4,  138.6], nagano:   [35.9,  138.0],
  gifu:     [35.8,  136.9], tokyo:    [35.68, 139.77], tokyoBay: [35.55, 139.85],
};

// 鉄道パルス (中央マップ) — 首都圏を代表する固定地点。個別路線の緯度経度は持たないため中央付近に固定表示する。
const RAIL_PULSE_LATLON = PT_LATLON.tokyo;

const HISTORY_12H = [
  {t:'19:34', p:'宮城県沖',     m:'M4.2', s:'2',   c:'var(--c-eq-2)'},
  {t:'19:21', p:'岩手県沖',     m:'M6.1', s:'5弱', c:'var(--c-eq)'},
  {t:'17:55', p:'福島県沖',     m:'M3.8', s:'1',   c:'var(--c-eq-3)'},
  {t:'15:02', p:'茨城県北部',   m:'M3.1', s:'1',   c:'var(--c-eq-3)'},
  {t:'12:30', p:'青森県東方沖', m:'M4.0', s:'2',   c:'var(--c-eq-2)'},
  {t:'09:14', p:'十勝沖',       m:'M3.5', s:'1',   c:'var(--c-eq-3)'},
];

const RAIL_LINES_BASE = [
  {id:'chuo',     name:'中央線快速',  color:'#f15a22', points:'498,470 536,452 576,448 614,452'},
  {id:'yamanote', name:'山手線',      color:'#9acd32', points:'536,452 562,462 568,490 548,506 522,496 518,470 536,452'},
  {id:'keihin',   name:'京浜東北線', color:'#00a7e0', points:'512,432 540,490 560,534'},
  {id:'saikyo',   name:'埼京線',      color:'#00ac9b', points:'520,428 540,452 596,448 624,452'},
];

// 潮位観測点プール — 実装では /live の観測点ごとの潮位時系列に置き換える
// lat/lon: Leaflet 本番地図 (中央マップ) のパルス配置用実緯度経度
const TIDE_POOL = [
  {name:'東京',   at:[586, 506], lat:35.65, lon:139.77, base:106, amp:78, phase:2.4, dev:6},
  {name:'横浜',   at:[590, 516], lat:35.45, lon:139.65, base:110, amp:70, phase:2.9, dev:4},
  {name:'千葉',   at:[602, 494], lat:35.61, lon:140.10, base:100, amp:82, phase:2.1, dev:8},
  {name:'名古屋', at:[430, 566], lat:35.18, lon:136.91, base:96,  amp:66, phase:3.4, dev:5},
  {name:'清水',   at:[478, 590], lat:35.01, lon:138.49, base:112, amp:84, phase:2.6, dev:7},
  {name:'銚子',   at:[624, 472], lat:35.73, lon:140.83, base:118, amp:74, phase:1.8, dev:5},
];

function fmtHM(t) {
  const h = Math.floor(t) % 24, m = Math.round((t - Math.floor(t)) * 60) % 60;
  return String(h).padStart(2, '0') + ':' + String(m).padStart(2, '0');
}

/**
 * 潮位ステーションリストを生成する。
 * `current` (現在潮位) は render 時に LiveStreamClock.getCurrentHourFloat() で動的に計算するため
 * ここには含めない。代わりに base / amp / phase を保持し、描画側が任意の時刻で計算できる。
 *
 * @param {string[]} alertNames 高潮警戒扱いにする拠点名リスト
 */
function makeTide(alertNames) {
  const set = new Set(alertNames || []);
  return TIDE_POOL.map(s => {
    const alert = set.has(s.name);
    const amp = alert ? s.amp + 26 : s.amp, base = alert ? s.base + 34 : s.base;
    const lvl = t => base + amp * Math.sin(2 * Math.PI * (t - s.phase) / 12.42);
    let hiT = 0, loT = 0, hi = -1e9, lo = 1e9;
    for (let t = 0; t <= 24; t += 0.05) {
      const v = lvl(t);
      if (v > hi) { hi = v; hiT = t; }
      if (v < lo) { lo = v; loT = t; }
    }
    return {
      name: s.name, at: s.at, lat: s.lat, lon: s.lon, base, amp, phase: s.phase, alert,
      // current は render 時に LiveStreamClock.getCurrentHourFloat() から動的計算する
      high: fmtHM(hiT) + ' ' + Math.round(hi) + 'cm',
      low:  fmtHM(loT) + ' ' + Math.round(lo) + 'cm',
      dev: '+' + (alert ? s.dev + 22 : s.dev) + 'cm',
    };
  });
}

const SCENES = {
  /* ---- 平穏時 ---- */
  calm: {
    level: 'calm',
    earthquake: { targets: [], history: HISTORY_12H },
    rain:        { targets: [], alerts: [] },
    rail:        { affected: [] },
    tide:        { stations: makeTide([]) },
  },
  /* ---- 警戒時 ---- */
  alert: {
    level: 'high',
    earthquake: {
      targets: [
        {
          id:'eq-demo-iwate',  p:'岩手県沖', m:'M6.1', s:'5弱', t:'19:21', at:PT.iwate,  lat:PT_LATLON.iwate[0],  lon:PT_LATLON.iwate[1],  r:15,
          // Stream Phase 5-A.1 demo: 広域 (東北全体) の市区町村震度 — リスト自動スクロール・小地図巡回の両方を確認できる件数にする。
          // 末尾1件は座標辞書に存在しない架空地名 (missingCoordinateCount 検証用)。
          points: [
            {pref:'岩手県', addr:'盛岡市',       isArea:false, scale:45},
            {pref:'岩手県', addr:'宮古市',       isArea:false, scale:45},
            {pref:'岩手県', addr:'大船渡市',     isArea:false, scale:40},
            {pref:'岩手県', addr:'花巻市',       isArea:false, scale:40},
            {pref:'岩手県', addr:'北上市',       isArea:false, scale:30},
            {pref:'岩手県', addr:'久慈市',       isArea:false, scale:30},
            {pref:'宮城県', addr:'石巻市',       isArea:false, scale:40},
            {pref:'宮城県', addr:'仙台青葉区',   isArea:false, scale:30},
            {pref:'青森県', addr:'八戸市',       isArea:false, scale:30},
            {pref:'青森県', addr:'十和田市',     isArea:false, scale:20},
            {pref:'秋田県', addr:'秋田市',       isArea:false, scale:20},
            {pref:'福島県', addr:'福島市',       isArea:false, scale:20},
            {pref:'福島県', addr:'いわき市',     isArea:false, scale:10},
            {pref:'岩手県', addr:'西方村',       isArea:false, scale:30},
          ],
        },
        {
          id:'eq-demo-miyagi', p:'宮城県沖', m:'M4.2', s:'2',   t:'19:34', at:PT.miyagi, lat:PT_LATLON.miyagi[0], lon:PT_LATLON.miyagi[1], r:12,
          // 局所的な地震 — リストは自動スクロール不要・小地図も単一フレームで収まる件数にする。
          points: [
            {pref:'宮城県', addr:'石巻市',     isArea:false, scale:20},
            {pref:'宮城県', addr:'仙台若林区', isArea:false, scale:20},
          ],
        },
      ],
      history: HISTORY_12H,
    },
    rain: {
      targets: [
        {id:'kikikuru-静岡県 中部-land', r:'静岡県 中部', lv:'危険', lvColor:'#e879f9', level:'danger', rawType:'kikikuru', amt:'1h 62mm', at:PT.shizuoka, lat:PT_LATLON.shizuoka[0], lon:PT_LATLON.shizuoka[1],
         cells:[[470,582,50,.55],[430,620,36,.5],[500,600,26,.45],[452,560,22,.4]]},
        {id:'kikikuru-愛知県 東部-land', r:'愛知県 東部', lv:'警戒', lvColor:'#fb7185', level:'warning', rawType:'kikikuru', amt:'1h 44mm', at:PT.aichi, lat:PT_LATLON.aichi[0], lon:PT_LATLON.aichi[1],
         cells:[[428,622,46,.55],[400,600,30,.5],[452,640,22,.42]]},
      ],
      alerts: [
        {r:'静岡県 中部', lv:'危険', cl:'#a21caf'},
        {r:'山梨県 南部', lv:'警戒', cl:'#e11d48'},
        {r:'愛知県 東部', lv:'警戒', cl:'#e11d48'},
        {r:'長野県 南部', lv:'注意', cl:'#d4a017'},
        {r:'岐阜県 美濃', lv:'注意', cl:'#d4a017'},
      ],
    },
    rail: {
      affected: [
        {id:'chuo',     mapId:'chuo',     name:'中央線快速',  status:'見合わせ', statusCode:'suspended',          note:'三鷹〜東京 / 人身事故',  stColor:'var(--c-eq)'},
        {id:'yamanote', mapId:'yamanote', name:'山手線',       status:'遅延',     statusCode:'delay',              note:'内回り 最大20分',         stColor:'#d4a017'},
        {id:'keihin',   mapId:'keihin',   name:'京浜東北線',  status:'一部運休', statusCode:'partial_suspension', note:'大宮〜田端',               stColor:'var(--c-eq-2)'},
        {id:'saikyo',   mapId:'saikyo',   name:'埼京線',       status:'遅延',     statusCode:'delay',              note:'最大15分',                stColor:'#d4a017'},
      ],
    },
    tide: { stations: makeTide(['清水', '名古屋']) },
  },
};

const TICKER_TEXT = '【地震】19:21 岩手県沖 M6.1 最大震度5弱 — 津波の心配なし　／　【大雨】静岡県中部に土砂災害キキクル「危険」　／　【鉄道】中央線快速 三鷹〜東京で運転見合わせ　／　【潮位】東京 満潮 05:00 189cm　／　';

/**
 * railModel から scene.rail セクションを構築する。
 * error 時は { status:'error', affected:[] } を返す。
 */
function _buildRailSection(railModel, baseRail) {
  if (!railModel || railModel.status === 'unavailable') return baseRail;
  if (railModel.status === 'error') {
    return { status: 'error', affected: [] };
  }
  return {
    status:   'ok',
    affected: railModel.affected,
  };
}

/**
 * tideModel から scene.tide セクションを構築する。
 * error 時は { status:'error', stations:[], alertCount:0 } を返す。
 */
function _buildTideSection(tideModel, baseTide) {
  if (!tideModel || tideModel.status === 'unavailable') return baseTide;
  if (tideModel.status === 'error') {
    return { status: 'error', stations: [], alertCount: 0 };
  }
  return {
    status:     'ok',
    stations:   tideModel.stations,
    alertCount: tideModel.alertCount || 0,
  };
}

/* ================================================================
   ticker — scene から下部テロップ文言を生成する
   ================================================================ */

function _safeStr(v) {
  if (v === null || v === undefined) return null;
  if (typeof v === 'number' && !isFinite(v)) return null;
  const s = String(v);
  return (s === 'undefined' || s === 'null' || s === 'NaN') ? null : s;
}

function _eqTickerItem(eq) {
  if (!eq) return null;
  if (eq.status === 'error') {
    return { label: '地震', text: '情報を取得できません', priority: 5, category: 'earthquake' };
  }
  if (!eq.targets || eq.targets.length === 0) return null;
  const t = eq.targets[0];
  const time    = _safeStr(t.t) || '';
  const place   = _safeStr(t.p) || '地域不明';
  const mag     = _safeStr(t.m) ? ' ' + t.m : '';
  const shindo  = _safeStr(t.s) || '';
  const shindoPart = shindo ? ' 最大震度' + shindo : '';
  let text = (time ? time + ' ' : '') + place + mag + shindoPart;
  if (t.tsunami && _safeStr(t.tsunami)) text += ' - ' + t.tsunami;
  const isHigh = !!(shindo && (
    shindo.includes('5') || shindo.includes('6') || shindo.includes('7') || t.tsunami
  ));
  return { label: '地震', text: text.trim(), priority: isHigh ? 100 : 50, category: 'earthquake' };
}

function _rainTickerItem(rain) {
  if (!rain) return null;
  if (rain.status === 'error') {
    return { label: '大雨', text: '情報を取得できません', priority: 5, category: 'rain' };
  }
  const src = (rain.alerts  && rain.alerts.length  > 0) ? rain.alerts[0]
            : (rain.targets && rain.targets.length > 0) ? rain.targets[0]
            : null;
  if (!src) return null;
  const region = _safeStr(src.r)   || '地域不明';
  const lv     = _safeStr(src.lv)  || '';
  const cat    = _safeStr(src.cat) || '';
  const text   = lv
    ? (cat ? `${region} ${cat}キキクル「${lv}」` : `${region} キキクル「${lv}」`)
    : region;
  const isHigh = lv === '危険' || lv === '災害切迫';
  return { label: '大雨', text, priority: isHigh ? 90 : 60, category: 'rain' };
}

function _railTickerItem(rail) {
  if (!rail) return null;
  if (rail.status === 'error') {
    return { label: '鉄道', text: '運行情報を取得できません', priority: 5, category: 'rail' };
  }
  if (!rail.affected || rail.affected.length === 0) return null;
  const a      = rail.affected[0]; // severity 降順ソート済み
  const name   = _safeStr(a.name)   || '路線名不明';
  const status = _safeStr(a.status) || '';
  const note   = _safeStr(a.note)   || '';
  const detail = note || status;
  const text   = detail ? name + ' ' + detail : name;
  const isSuspended = status.includes('見合わせ') || status.includes('運休');
  return { label: '鉄道', text, priority: isSuspended ? 80 : 40, category: 'rail' };
}

function _tideTickerItem(tide) {
  if (!tide) return null;
  if (tide.status === 'error') {
    return { label: '潮位', text: '情報を取得できません', priority: 5, category: 'tide' };
  }
  if (!tide.stations || tide.stations.length === 0) return null;
  const s    = tide.stations[0];
  const name = _safeStr(s.name) || '不明';
  const high = _safeStr(s.high) || '--:-- --cm';
  const text = s.alert
    ? `${name} 高潮に注意 / 満潮${high}`
    : `${name} 満潮${high}`;
  return { label: '潮位', text, priority: s.alert ? 70 : 10, category: 'tide' };
}

/**
 * scene から下部テロップ用 item 配列を生成する。
 * calm シーンは常に空配列 (→ buildTickerText で監視中テロップになる)。
 *
 * @param {object} scene  buildScene() が返す scene オブジェクト
 * @returns {Array<{label, text, priority, category}>} priority 降順
 */
function buildTickerItems(scene) {
  if (!scene || scene.level === 'calm') return [];
  const items = [
    _eqTickerItem(scene.earthquake),
    _rainTickerItem(scene.rain),
    _railTickerItem(scene.rail),
    _tideTickerItem(scene.tide),
  ].filter(Boolean);
  items.sort((a, b) => b.priority - a.priority);
  return items;
}

/**
 * ticker item 配列をテロップ表示文字列に変換する。
 * items が空のとき (calm / 対象なし) は監視中テロップを返す。
 * dataState='unavailable' (全カテゴリ取得失敗) のときは取得待機メッセージを優先する
 * (Stream Phase 3-C: 取得失敗を平常と誤表示しないための区別)。
 *
 * @param {Array} items
 * @param {string} [dataState]  LiveStreamEventStore.getSummary().dataState
 * @returns {string}
 */
function buildTickerText(items, dataState) {
  if (dataState === 'unavailable') {
    return '【監視中】一部データの取得を確認中です。画面は最新取得済み情報をもとに監視を継続しています　／　';
  }
  if (!items || items.length === 0) {
    return '【監視中】全国の地震・豪雨・潮位・交通影響を監視中　／　';
  }
  return items.map(it => `【${it.label}】${it.text}`).join('　／　') + '　／　';
}

const _TICKER_LABEL_BY_TYPE = { earthquake: '地震', rain: '大雨', kikikuru: '大雨', railway: '鉄道', tide: '潮位', water: '水位' };
const _TICKER_PRIORITY_BY_SEVERITY = { critical: 100, high: 80, medium: 50, low: 20, info: 5 };

/**
 * StreamMapEvents.build() の正規化イベント配列から下部テロップ用 item 配列を生成する。
 * 中央マップと同じ配列を参照するため、地図とテロップの内容が食い違わない (Stream Phase 3-C)。
 * カテゴリごとに最優先の1件のみ採用する (events は呼び出し側で severity 降順ソート済み)。
 *
 * @param {Array} events  StreamMapEvents.build() の出力 (LiveStreamEventStore.getEvents() 等)
 * @returns {Array<{label, text, priority, category}>} priority 降順
 */
function buildTickerItemsFromEvents(events) {
  if (!events || events.length === 0) return [];
  const seenLabel = new Set();
  const items = [];
  for (const e of events) {
    const label = _TICKER_LABEL_BY_TYPE[e.type] || e.type;
    if (seenLabel.has(label)) continue;
    seenLabel.add(label);
    const title = _safeStr(e.title) || '不明';
    const subtitle = _safeStr(e.subtitle);
    items.push({
      label,
      text: subtitle ? `${title} ${subtitle}` : title,
      priority: _TICKER_PRIORITY_BY_SEVERITY[e.severity] || 10,
      category: e.type,
    });
  }
  items.sort((a, b) => b.priority - a.priority);
  return items;
}

/**
 * Stream Phase 4-A: 自動巡回で注目中の event を「注目」ラベルとしてテロップ先頭へ差し込む。
 * 同じカテゴリの通常項目と内容が重複して見えないよう、そのカテゴリの通常項目は取り除く。
 * demo/real いずれの ticker item 配列にも適用できる汎用関数 (focusEvent は正規化イベント形式)。
 *
 * @param {Array} items       buildTickerItems() / buildTickerItemsFromEvents() の出力
 * @param {object|null} focusEvent  LiveStreamFocusController.getState().activeEvent (focus中でなければ null)
 * @returns {Array}
 */
function mergeFocusIntoTickerItems(items, focusEvent) {
  if (!focusEvent) return items || [];
  const title = _safeStr(focusEvent.title) || '不明';
  const subtitle = _safeStr(focusEvent.subtitle);
  const focusItem = {
    label: '注目',
    text: subtitle ? `${title} ${subtitle}` : title,
    priority: 999,
    category: focusEvent.type,
  };
  const rest = (items || []).filter(it => it.category !== focusEvent.type);
  return [focusItem, ...rest];
}

/* ================================================================ */

/**
 * demo シーン (SCENES.alert / SCENES.calm) を StreamMapEvents.build() が期待する
 * { eqModel, rainModel, railModel, tideModel } 形式へ変換する。
 * これにより demo=1 も本番データと同じ正規化パイプラインを通せる
 * (Stream Phase 3-C: 「demo も同じ event source を使う」)。
 *
 * @param {object} scene  buildScene() が返す scene オブジェクト
 * @returns {{eqModel:object, rainModel:object, railModel:object, tideModel:object}}
 */
function buildDemoStreamModels(scene) {
  const eq = (scene && scene.earthquake) || { targets: [], history: [] };
  const rain = (scene && scene.rain) || { targets: [] };
  const rail = (scene && scene.rail) || { affected: [] };
  const tide = (scene && scene.tide) || { stations: [] };
  return {
    eqModel:   { status: 'ok', targets: eq.targets || [], mapEvents: eq.targets || [] },
    rainModel: { status: 'ok', targets: rain.targets || [] },
    railModel: { status: 'ok', affected: rail.affected || [] },
    tideModel: { status: 'ok', stations: tide.stations || [] },
  };
}

/**
 * rainModel から scene.rain セクションを構築する。
 * error 時は { status:'error', targets:[], alerts:[] } を返す。
 */
function _buildRainSection(rainModel, baseRain) {
  if (!rainModel || rainModel.status === 'unavailable') return baseRain;
  if (rainModel.status === 'error') {
    return { status: 'error', targets: [], alerts: [] };
  }
  return {
    status:      'ok',
    targets:     rainModel.targets,
    alerts:      rainModel.alerts,
    statusCount: rainModel.statusCount,
  };
}

/**
 * /live 差し替え口 — eq/rain adapter 出力を scene に変換する。
 *
 * @param {object|null} eqModel    EarthquakeStreamAdapter.build() の出力 (null = デモ使用)
 * @param {object}      [options]  { mode: 'calm'|'alert', useDemo: bool,
 *                                   rainModel: RainStreamAdapter.build() の出力,
 *                                   useRainDemo: bool }
 * @returns {object} scene
 *
 * useDemo=true または eqModel が null / status!='ok' の場合は静的デモシーンを返す。
 * state=calm は常に SCENES.calm を返す。
 */
function buildScene(eqModel, options) {
  const opts = options || {};
  const mode = opts.mode;
  const rainModel   = opts.rainModel  || null;
  const railModel   = opts.railModel  || null;
  const tideModel   = opts.tideModel  || null;
  // useXxxDemo: 明示的に false を渡した場合のみ実データ使用。未指定 / true → デモ
  const useRainDemo = opts.useRainDemo !== false;
  const useRailDemo = opts.useRailDemo !== false;
  const useTideDemo = opts.useTideDemo !== false;

  // state=calm: 実データに関わらず平穏シーン固定
  if (mode === 'calm') return SCENES.calm;

  const base = SCENES.alert;
  const rain = useRainDemo ? base.rain : _buildRainSection(rainModel, base.rain);
  const rail = useRailDemo ? base.rail : _buildRailSection(railModel, base.rail);
  const tide = useTideDemo ? base.tide : _buildTideSection(tideModel, base.tide);

  // demo=1 / データ未取得 → 静的デモシーン（status フィールドなし）
  if (opts.useDemo || !eqModel || eqModel.status === 'unavailable') {
    return { ...base, rain, rail, tide };
  }

  // 取得失敗: rain/rail/tide と同様に空状態を返す (status='error' でヘッダーは '-' になる)。
  // Stream Phase 3-C: 以前はここで base (デモ) の地震ターゲットを残していたため、
  // 取得失敗時に中央マップ (0件) とパネル/ポップアップ (デモ2件) の内容が食い違っていた。
  if (eqModel.status === 'error') {
    return { ...base, earthquake: { targets: [], history: [], status: 'error' }, rain, rail, tide };
  }

  // 実データあり: SCENES.alert をベースに地震部分だけ置換
  // history が空配列なのは「直近12hに地震なし」という正当な実データ状態であり、
  // demo (base.earthquake.history) へフォールバックしてはいけない。フォールバックすると
  // targets は実データの空のままなのに history だけ demo の架空地震が残り、
  // 一覧には地震が出ているのに地図がズームしない/詳細が出ない、という食い違いになる。
  const eq = {
    targets:     eqModel.targets,
    history:     eqModel.history,
    statusCount: eqModel.statusCount,
    status:      'ok',
  };

  return { ...base, earthquake: eq, rain, rail, tide };
}

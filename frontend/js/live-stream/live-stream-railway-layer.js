'use strict';
// /live/stream — 鉄道路線レイヤー (Stream Phase 4-C)
//
// protomaps-leaflet + 全国鉄道路線 PMTiles (/live 本体と同じ静的ファイルを「利用」する。
// /live 本体の live-train-pmtiles-layer.js は改変しない、独立した stream 専用実装)。
// 警報・遅延等のある路線 (LiveStreamEventStore の railway event) は太線・強調色で表示する。

const LiveStreamRailwayLayer = (function () {
  const PMTILES_URL = '/layers/railways/railways_japan.pmtiles';
  const MAX_DATA_ZOOM = 14;

  // Stream Phase 5-A bundle C: /live 側の公式/準公式路線カラー定義を移植したもの。
  // 出典: frontend/js/live/live-train-pmtiles-layer.js の _LINE_COLORS / _resolveRailColor
  // (/live 本体は改変せず、値のみをこの stream 専用ファイルへ複製している)。
  // 視聴者が自分の地域の路線色を認識しやすいよう、平常路線も含め常にこの色をベースに描画する
  // (障害路線は「別の色」ではなく width/opacity を上げて強調する — C-1/C-2 の要件)。
  const _LINE_COLORS = {
    '山手線':           '#9ACD32', '中央線': '#F15A22', '中央線快速': '#F15A22',
    '中央快速線':       '#F15A22', '中央本線': '#F15A22', '中央緩行線': '#FFD400',
    '京浜東北線':       '#00A7E3', '根岸線': '#00A7E3',
    '総武線':           '#FFD400', '総武線各駅停車': '#FFD400', '中央・総武線': '#FFD400', '総武緩行線': '#FFD400',
    '総武快速線':       '#006DB3', '総武本線': '#006DB3',
    '京葉線':           '#E85298',
    '埼京線':           '#00AC9A', '赤羽線': '#00AC9A', '川越線': '#00AC9A',
    '常磐線':           '#00B261', '常磐快速線': '#00B261', '常磐緩行線': '#00B261',
    '武蔵野線':         '#F68B1E', '横浜線': '#00A94F', '南武線': '#F5A200',
    '高崎線':           '#F15A22', '宇都宮線': '#F15A22', '東北本線': '#F15A22',
    '横須賀線':         '#006DB3', '青梅線': '#F15A22', '相模線': '#00A94F',
    '湘南新宿ライン':   '#F15A22', '内房線': '#0068B7', '外房線': '#0068B7',
    '成田線':           '#00B261', '日光線': '#F15A22',
    '銀座線':           '#F39700', '丸ノ内線': '#E60012', '日比谷線': '#9C9EA0', '東西線': '#00A7DB',
    '千代田線':         '#009944', '有楽町線': '#C1A03E', '半蔵門線': '#8F76D6', '南北線': '#00ACA5',
    '副都心線':         '#8B6239',
    '都営浅草線':       '#E4007F', '浅草線': '#E4007F',
    '都営三田線':       '#0079C2', '三田線': '#0079C2',
    '都営新宿線':       '#6CBB5A', '新宿線': '#6CBB5A',
    '都営大江戸線':     '#C84E00', '大江戸線': '#C84E00',
    '東京さくらトラム': '#E9546B', '都電荒川線': '#E9546B',
    '日暮里・舎人ライナー': '#CD8A00',
    '小田急線':         '#2288CC', '小田急小田原線': '#2288CC', '小田急電鉄小田原線': '#2288CC',
    '小田急江ノ島線':   '#2288CC', '小田急電鉄江ノ島線': '#2288CC',
    '小田急多摩線':     '#2288CC', '小田急電鉄多摩線': '#2288CC',
    '京王線':           '#DD0077', '京王電鉄京王線': '#DD0077',
    '京王相模原線':     '#DD0077', '京王電鉄相模原線': '#DD0077',
    '京王高尾線':       '#DD0077', '京王電鉄高尾線': '#DD0077',
    '井の頭線':         '#3994C3', '京王電鉄井の頭線': '#3994C3',
    '東急東横線':       '#DA0442', '東急田園都市線': '#20A288', '東急目黒線': '#00BB85',
    '東急大井町線':     '#EE86A7', '東急池上線': '#D9A700', '東急多摩川線': '#AE0378',
    '西武池袋線':       '#F39800',
    '西武新宿線':       '#00A6BF', '西武拝島線': '#00A6BF', '西武多摩湖線': '#00A6BF',
    '東武スカイツリーライン': '#F6873A', '東武伊勢崎線': '#F6873A', '伊勢崎線': '#F6873A',
    '東武東上線':       '#004098', '東武野田線': '#33A23D',
    '京急本線':         '#E5171F', '京浜急行電鉄本線': '#E5171F',
    '京急空港線':       '#E5171F', '京急久里浜線': '#E5171F', '京浜急行電鉄久里浜線': '#E5171F',
    '京成本線':         '#E85B11', '京成押上線': '#E85B11', '京成千葉線': '#E85B11', '京成成田空港線': '#E85B11',
    '北総線':           '#00A0E9', 'つくばエクスプレス': '#00B274', 'ゆりかもめ': '#00ADEE', 'りんかい線': '#00ABC4',
    '東京モノレール':   '#80CBC4', '多摩モノレール': '#009FE8',
    'ブルーライン':     '#0080CB', '横浜市営地下鉄ブルーライン': '#0080CB', '横浜市営1号線': '#0080CB', '横浜市営3号線': '#0080CB',
    'グリーンライン':   '#4CAF50', '横浜市営地下鉄グリーンライン': '#4CAF50',
    '東海道本線':       '#F15A22', '東海道新幹線': '#0068B7', '東北新幹線': '#009944',
    '上越新幹線':       '#E60012', '北陸新幹線': '#C1A03E',
  };
  const _FALLBACK_COLOR = '#8FA3B0';
  const _COLOR_KEYS_SORTED = Object.keys(_LINE_COLORS).sort((a, b) => b.length - a.length);

  function _resolveRailColor(props) {
    const candidates = [props.name, props['name:ja'], props['name:en'], props.ref, props.operator].filter(Boolean).map(String);
    for (const name of candidates) {
      if (_LINE_COLORS[name]) return _LINE_COLORS[name];
    }
    for (const name of candidates) {
      for (const key of _COLOR_KEYS_SORTED) {
        if (name.includes(key)) return _LINE_COLORS[key];
      }
    }
    return _FALLBACK_COLOR;
  }

  // Stream Phase 5-A.1 (railway calm map): 中央メイン地図に加え、鉄道子画面の小地図
  // (#rail-map) にも同じ路線レイヤーを載せられるよう、単一 _map/_layer ではなく
  // 複数インスタンスを管理する。affected 判定 (_affectedNames) は全インスタンスで共有し、
  // setAffectedEvents() 一回の呼び出しで両方の地図を再描画する。
  const _instances = []; // [{ key, map, layer }]
  let _affectedNames = new Set();
  let _lastError = null;

  function _isAffected(props) {
    if (_affectedNames.size === 0) return false;
    const candidates = [props.name, props['name:ja'], props['name:en'], props.ref].filter(Boolean);
    return candidates.some(c => _affectedNames.has(c));
  }

  // 平常路線は控えめ (細く/薄く)、障害路線は少し太く/明るく — 路線色自体は変えない (C-1/C-2)。
  function _widthFor(zoom, f) {
    const base = zoom <= 6 ? 0.5 : zoom <= 8 ? 0.8 : zoom <= 10 ? 1.2 : 1.8;
    return _isAffected(f.props) ? base * 2.2 : base;
  }
  function _opacityFor(zoom, f) {
    const base = zoom <= 6 ? 0.4 : zoom <= 8 ? 0.5 : 0.62;
    return _isAffected(f.props) ? 1 : base;
  }
  function _colorFor(zoom, f) {
    return _resolveRailColor(f.props);
  }

  // yard/siding 等の非旅客線・専用線は表示しない (live-train-pmtiles-layer.js と同じ方針)
  const _EXCLUDE_SERVICE = new Set(['yard', 'siding', 'spur', 'crossover']);
  function _isDisplayable(zoom, f) {
    const svc = f.props.service || '';
    const usage = f.props.usage || '';
    if (_EXCLUDE_SERVICE.has(svc)) return false;
    if (usage === 'industrial') return false;
    return true;
  }

  function _buildPaintRules(P) {
    return [{
      dataLayer: 'railways',
      filter: _isDisplayable,
      symbolizer: new P.LineSymbolizer({
        color:   _colorFor,
        width:   _widthFor,
        opacity: _opacityFor,
      }),
    }];
  }

  // Stream Phase 5-C: 中央地図・鉄道子画面小地図の2インスタンスが、それぞれ独立に
  // 同じ railways_japan.pmtiles へ fetch (Range リクエスト) していたため、同一ファイルへの
  // 重複ネットワーク要求が発生していた (soak検証で観測された断続的な "TypeError: Failed to
  // fetch" console error — protomaps-leaflet 内部が AbortError 以外の reject を console.error
  // する箇所があり、こちらからは抑制できない — の一因と考えられる)。
  // PmtilesSource の内部実体 (.p) だけを1つ作って全レイヤーで共有し、fetch/ヘッダキャッシュを
  // 再利用することで重複リクエストそのものを減らす (「不要な fetch を起動しない」方針)。
  // .p は protomaps-leaflet 4.1.1 の非公開実装詳細のため、取得できない場合は黙って
  // 文字列URL (従来どおり各レイヤーが独立にソースを作る) にフォールバックする。
  // 既知の残課題: protomaps-leaflet はズーム変更時、前ズームの進行中fetchをAbortControllerで
  // 中断するが、この中断は同ライブラリの sourceToViews() 内部で shouldCancelZooms=true 固定で
  // 生成される (leafletLayer() のオプションからは変更不可)。Chromiumの実装上まれに
  // DOMException("AbortError") ではなく素の "TypeError: Failed to fetch" として reject される
  // ことがあり、protomaps-leaflet は名前が "AbortError" の reject だけを無視して他は
  // console.error するため、この経路はアプリ側から抑制できない (soak検証で低頻度に残存を確認)。
  let _sharedPmtilesSource = null;
  function _getSharedSource(P) {
    if (_sharedPmtilesSource) return _sharedPmtilesSource;
    try {
      const probe = new P.PmtilesSource(PMTILES_URL, true);
      _sharedPmtilesSource = probe && probe.p ? probe.p : null;
    } catch (_) {
      _sharedPmtilesSource = null;
    }
    return _sharedPmtilesSource;
  }

  function _createLayer() {
    if (!window.protomapsL) {
      console.warn('[LiveStreamRailwayLayer] protomaps-leaflet が読み込まれていません');
      return null;
    }
    const P = window.protomapsL;
    try {
      return P.leafletLayer({
        url:         _getSharedSource(P) || PMTILES_URL,
        paintRules:  _buildPaintRules(P),
        maxDataZoom: MAX_DATA_ZOOM,
        levelDiff:   0,
        maxZoom:     20,
        attribution: '© OpenStreetMap contributors',
      });
    } catch (e) {
      console.warn('[LiveStreamRailwayLayer] レイヤー生成失敗:', e.message);
      return null;
    }
  }

  async function _probeFile() {
    try {
      const res = await fetch(PMTILES_URL, { method: 'HEAD' });
      return res.ok;
    } catch (e) {
      if (typeof LiveStreamRuntime !== 'undefined' && LiveStreamRuntime.recordFetchFailureDetail) {
        LiveStreamRuntime.recordFetchFailureDetail({
          category: 'railwayLayer', path: PMTILES_URL, mode: 'n/a',
          errorName: e && e.name, errorMessage: e && e.message,
        });
      }
      return false;
    }
  }

  // protomaps-leaflet は PMTiles を内部で fetch() の Range リクエストとして読む。ページ遷移で
  // その fetch が中断されると "TypeError: Failed to fetch" が未処理の Promise 拒否として
  // コンソールに出る (ページを閉じる/移動するだけの無害な中断で、実際の不具合ではない)。
  // ナビゲーション由来のこの特定パターンのみ抑制し、他の reject は握りつぶさない。
  let _abortGuardInstalled = false;
  function _installFetchAbortGuard() {
    if (_abortGuardInstalled || typeof window === 'undefined') return;
    _abortGuardInstalled = true;
    window.addEventListener('unhandledrejection', e => {
      const msg = e && e.reason ? String(e.reason.message || e.reason) : '';
      if (msg.includes('Failed to fetch')) e.preventDefault();
    });
  }

  function _pushDiagnostics() {
    if (typeof LiveStreamRuntime === 'undefined' || !LiveStreamRuntime.setRailwayLayerDiagnostics) return;
    const loadedInstances = _instances.filter(i => i.layer);
    LiveStreamRuntime.setRailwayLayerDiagnostics({
      loaded: loadedInstances.length > 0,
      layerCount: loadedInstances.length,
      // protomaps-leaflet はタイル単位のベクタ描画で個々のfeatureをJS側に保持しないため、
      // featureCount/coloredFeatureCount の正確な計上はできない (常に公式カラーで塗るため coloredFeatureCount は
      // 事実上 featureCount と同義になる想定だが、取得手段が無いため省略する)。
      highlightedFeatureCount: _affectedNames.size,
      lastError: _lastError,
    });
  }

  /**
   * @param {L.Map} map
   * @param {object} [opts]  { key: string }  同一 key で複数回 init しても二重追加しない。
   */
  async function init(map, opts) {
    const key = (opts && opts.key) || 'default';
    if (_instances.some(i => i.key === key)) return; // 同じ小窓の再init (多重起動) を防ぐ
    if (!window.protomapsL) {
      _lastError = 'protomaps-leaflet not loaded';
      _pushDiagnostics();
      return;
    }
    _installFetchAbortGuard();
    const exists = await _probeFile();
    if (!exists || !map) {
      if (!exists) {
        console.warn('[LiveStreamRailwayLayer] PMTilesファイルが見つかりません:', PMTILES_URL);
        _lastError = 'pmtiles not found';
      }
      _pushDiagnostics();
      return;
    }
    const layer = _createLayer();
    if (layer) {
      layer.addTo(map);
      _lastError = null;
    } else {
      _lastError = 'layer creation failed';
    }
    _instances.push({ key, map, layer });
    _pushDiagnostics();
  }

  /**
   * scene.rail.affected (= 鉄道カード一覧と同じ全件。座標の有無でフィルタされていない) から
   * 警報路線名の集合を更新する。Stream Phase 5-B: 以前は EventStore.getEventsByType('railway')
   * (地図にピンを置ける座標がある路線だけに絞り込まれた集合) を使っていたため、代表座標を
   * 持たない事業者の路線が「カードには出るのに太線にはならない」ことがあった。
   * main.js から毎フレーム呼ぶ想定。変化がなければ再描画しない (無駄な redraw を避ける)。
   * 登録済みの全インスタンス (中央地図・鉄道子画面小地図) をまとめて再描画する。
   * @param {Array} events  event.title が路線名 (例: '中央線快速') の配列
   */
  function setAffectedEvents(events) {
    const names = new Set();
    (events || []).forEach(e => { if (e.title) names.add(e.title); });
    const unchanged = names.size === _affectedNames.size && [..._affectedNames].every(n => names.has(n));
    if (unchanged) return;
    _affectedNames = names;
    _instances.forEach(inst => {
      if (inst.layer && typeof inst.layer.redraw === 'function') {
        try { inst.layer.redraw(); } catch (_) { /* noop */ }
      }
    });
    _pushDiagnostics();
  }

  // Stream Phase 5-A.1 (railway calm map): 鉄道子画面の diagnostics (railwayMiniMap) 用。
  // routeCount は実際に描画された feature 数ではなく、色定義表に登録済みの路線名数
  // (protomaps-leaflet はタイル単位描画のため実描画feature数を計上できないための代替指標)。
  function getKnownRouteCount() {
    return _COLOR_KEYS_SORTED.length;
  }

  function isInstanceLoaded(key) {
    const inst = _instances.find(i => i.key === key);
    return !!(inst && inst.layer);
  }

  return { init, setAffectedEvents, getKnownRouteCount, isInstanceLoaded };
})();

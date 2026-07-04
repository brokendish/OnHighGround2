// /live/stream — railway adapter
// /api/live/trains/summary レスポンス → stream 鉄道 ViewModel 変換。
// 純粋変換のみ。副作用・DOM アクセスなし。

const RailwayStreamAdapter = (function () {

  const _JST_OFFSET_MS = 9 * 60 * 60 * 1000;

  // stream ステータスチップ色 (live-stream-scene.js の demo 色に合わせる)
  const _ST_COLOR = {
    suspended:          'var(--c-eq)',
    partial_suspension: 'var(--c-eq-2)',
    delay:              '#d4a017',
    unknown:            '#5d6878',
  };

  // stream SVG 路線図への対応付け (RAIL_LINES_BASE のキー)
  const _LINE_MAP_ID = {
    '中央線快速': 'chuo',
    '中央線':     'chuo',
    '山手線':     'yamanote',
    '京浜東北線': 'keihin',
    '埼京線':     'saikyo',
  };

  // Stream Phase 5-A bundle C: /live 側の公式/準公式路線カラー定義を移植したもの。
  // 出典: frontend/js/live/live-train-pmtiles-layer.js の _LINE_COLORS
  // (/live 本体は改変せず、値のみをこの stream 専用ファイルへ複製している)。
  const _OFFICIAL_LINE_COLORS = {
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
  const _OFFICIAL_COLOR_KEYS_SORTED = Object.keys(_OFFICIAL_LINE_COLORS).sort((a, b) => b.length - a.length);

  // Stream Phase 5-B: backend の railway_name はローカル名称表 (_RAILWAY_NAMES) に無い路線だと
  // odpt:railway ID 末尾の英字がそのまま返る (例: 'odpt.Railway:MIR.TsukubaExpress' → 'TsukubaExpress')。
  // この英字名は PMTiles 側の OSM 名称 (日本語 name/name:ja) と一致しないため、鉄道子画面の
  // 太線強調 (LiveStreamRailwayLayer._isAffected) が効かなくなる。backend 側の
  // _RAILWAY_NAMES テーブルは改変不可 (CLAUDE.md ガードレール) なので、frontend 側だけで完結する
  // 補完テーブルとして持つ。出典: frontend/js/live/live-train-osm-layer.js の _ODPT_TO_OSM
  // (/live 本体は改変せず、値のみをこの stream 専用ファイルへ複製している。各エントリの
  // 先頭候補のみを採用)。キーは railway_id の "odpt.Railway:" 接頭辞を除いた部分。
  const _RAILWAY_ID_NAME_ALIAS = {
    'JR-East.Yamanote': '山手線', 'JR-East.ChuoRapid': '中央線快速',
    'JR-East.ChuoSobuLocal': '中央・総武線', 'JR-East.SobuLocal': '中央・総武線',
    'JR-East.KeihinTohokuNegishi': '京浜東北線', 'JR-East.Joban': '常磐線',
    'JR-East.JobanRapid': '常磐快速線', 'JR-East.JobanLocal': '常磐緩行線',
    'JR-East.Musashino': '武蔵野線', 'JR-East.Yokohama': '横浜線', 'JR-East.Nambu': '南武線',
    'JR-East.Saikyo': '埼京線', 'JR-East.SaikyoKawagoe': '埼京線', 'JR-East.Takasaki': '高崎線',
    'JR-East.Utsunomiya': '宇都宮線', 'JR-East.Keiyo': '京葉線',
    'JR-East.Shonan-Shinjuku': '湘南新宿ライン', 'JR-East.ShonanShinjuku': '湘南新宿ライン',
    'JR-East.SobuRapid': '総武快速線', 'JR-East.Uchibo': '内房線', 'JR-East.Sotobou': '外房線',
    'JR-East.Nikko': '日光線',
    'TokyoMetro.Ginza': '銀座線', 'TokyoMetro.Marunouchi': '丸ノ内線', 'TokyoMetro.Hibiya': '日比谷線',
    'TokyoMetro.Tozai': '東西線', 'TokyoMetro.Chiyoda': '千代田線', 'TokyoMetro.Yurakucho': '有楽町線',
    'TokyoMetro.Hanzomon': '半蔵門線', 'TokyoMetro.Namboku': '南北線', 'TokyoMetro.Fukutoshin': '副都心線',
    'Toei.Asakusa': '都営浅草線', 'Toei.Mita': '都営三田線', 'Toei.Shinjuku': '都営新宿線',
    'Toei.Oedo': '都営大江戸線', 'Toei.Arakawa': '東京さくらトラム', 'Toei.NipporiToneri': '日暮里・舎人ライナー',
    'Odakyu.Odawara': '小田急小田原線', 'Odakyu.Enoshima': '小田急江ノ島線', 'Odakyu.Tama': '小田急多摩線',
    'Keio.Keio': '京王線', 'Keio.Sagamihara': '京王相模原線', 'Keio.Takao': '京王高尾線',
    'Keio.Inokashira': '井の頭線',
    'Tokyu.Toyoko': '東急東横線', 'Tokyu.DenEnToshi': '東急田園都市線', 'Tokyu.Meguro': '東急目黒線',
    'Tokyu.Oimachi': '東急大井町線', 'Tokyu.Ikegami': '東急池上線',
    'Seibu.Ikebukuro': '西武池袋線', 'Seibu.Shinjuku': '西武新宿線',
    'Tobu.TobuSkytree': '東武スカイツリーライン', 'Tobu.TobuTojo': '東武東上線',
    'Keikyu.Main': '京急本線', 'Keikyu.Airport': '京急空港線',
    'Keisei.Main': '京成本線', 'Keisei.Oshiage': '京成押上線',
    'MIR.TX': 'つくばエクスプレス', 'MIR.TsukubaExpress': 'つくばエクスプレス',
    'Yurikamome.Yurikamome': 'ゆりかもめ', 'TWR.Rinkai': 'りんかい線',
    'TokyoMonorail.HanedaAirport': '東京モノレール', 'TamaMonorail.TamaMonorail': '多摩モノレール',
    'YokohamaMunicipal.Blue': 'ブルーライン', 'YokohamaMunicipal.Green': 'グリーンライン',
  };

  // Stream Phase 5-B: 事業者代表点 (backend の _operator_representative_latlng) が
  // 取得できない事業者の路線でも、鉄道子画面のズームイン (focusOn) が必ず発火するよう、
  // 最終手段として東京駅付近を汎用フォールバック地点として使う
  // (frontend/js/live-stream/live-stream-map-events.js の RAIL_GENERIC_FALLBACK_POINT と同じ値)。
  const _GENERIC_FALLBACK_LATLNG = { lat: 35.6812, lng: 139.7671 }; // 東京駅

  function _railwayKey(railwayId) {
    if (!railwayId) return '';
    const idx = railwayId.indexOf(':');
    return idx >= 0 ? railwayId.slice(idx + 1) : railwayId;
  }

  // 表示名・地図強調・色解決すべての起点となる正規化済み路線名。
  // backend の railway_name が既に公式路線カラー表で解決できる名前ならそのまま使う
  // (backend 側の正しい解決結果を尊重し、無駄な上書きをしない)。解決できない
  // (= ID 末尾の英字がそのまま返っている等) 場合のみ ID ベースの補完表を試す。
  function _resolvedName(item) {
    const raw = item.railway_name || '';
    if (raw && _resolveOfficialColor(raw)) return raw;
    return _RAILWAY_ID_NAME_ALIAS[_railwayKey(item.railway_id || '')] || raw || '路線名不明';
  }

  function _resolveOfficialColor(name) {
    if (!name) return null;
    if (_OFFICIAL_LINE_COLORS[name]) return _OFFICIAL_LINE_COLORS[name];
    for (const key of _OFFICIAL_COLOR_KEYS_SORTED) {
      if (name.includes(key)) return _OFFICIAL_LINE_COLORS[key];
    }
    return null;
  }

  // 路線バー色: まず /live と共有の公式路線名カラー表を試し、一致しなければ
  // ODPT railway_id パターン (Tokyo Metro/都営 等、名称が取れない場合の保険) にフォールバックする。
  function _lineColor(item, name) {
    const official = _resolveOfficialColor(name != null ? name : (item.railway_name || ''));
    if (official) return official;
    const id = item.railway_id || '';
    if (id.includes('Ginza'))        return '#f39700';
    if (id.includes('Marunouchi'))   return '#e60012';
    if (id.includes('Hibiya'))       return '#b5b5ac';
    if (id.includes('Tozai'))        return '#00a7d8';
    if (id.includes('Chiyoda'))      return '#00bb85';
    if (id.includes('Yurakucho'))    return '#c8a400';
    if (id.includes('Hanzomon'))     return '#8f76d6';
    if (id.includes('Namboku'))      return '#00ac9b';
    if (id.includes('Fukutoshin'))   return '#9c5e31';
    if (id.includes('TokyoMetro'))   return '#b5b5ac';
    if (id.includes('Toei.Asakusa')) return '#e85298';
    if (id.includes('Toei.Mita'))    return '#0079c2';
    if (id.includes('Toei.Shinjuku')) return '#6cbb5a';
    if (id.includes('Toei.Oedo'))    return '#b6007a';
    if (id.includes('JR-East'))      return '#f15a22';
    return '#7888a0';
  }

  function _fmtUpdated(isoStr) {
    if (!isoStr) return '';
    try {
      const d = new Date(isoStr);
      if (isNaN(d.getTime())) return '';
      const jst = new Date(d.getTime() + _JST_OFFSET_MS);
      return String(jst.getUTCHours()).padStart(2, '0') + ':' + String(jst.getUTCMinutes()).padStart(2, '0');
    } catch (_) { return ''; }
  }

  function _truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.slice(0, maxLen - 1) + '…' : str;
  }

  function _buildLine(item) {
    const name = _resolvedName(item);
    const mapId = _LINE_MAP_ID[name] || null;
    return {
      id:           item.railway_id || String(Math.random()),
      mapId,
      name,
      operator:     item.operator_name || '',
      status:       item.status_label || item.status || '状態不明',
      statusCode:   item.status || null,
      note:         _truncate(item.description || '', 40),
      // Stream Phase 5-A bundle: 鉄道子画面詳細化用 — 概要カードは note (truncate済み) のまま維持し、
      // 詳細表示 (#rail-overlay) 用に全文を別途保持する。backend の TrainInfoItem に
      // 影響区間/原因の個別フィールドは無いため、description の全文をそのまま表示する。
      description:  item.description || '',
      source:       item.source || '',
      updatedAt:    _fmtUpdated(item.updated_at),
      updatedAtRaw: item.updated_at || null,
      // 事業者が運行する都道府県の重心座標 (粗い代表点)。取得できない事業者は汎用フォールバック
      // (東京駅付近) を使う — 精度を主張するものではなく、子画面のズームインを常に発火させるため。
      lat:          item.lat != null ? item.lat : _GENERIC_FALLBACK_LATLNG.lat,
      lng:          item.lng != null ? item.lng : _GENERIC_FALLBACK_LATLNG.lng,
      stColor:      _ST_COLOR[item.status] || '#5d6878',
      lineColor:    _lineColor(item, name),
      severity:     Number(item.severity) || 0,
    };
  }

  /**
   * /api/live/trains/summary レスポンスを stream 鉄道 ViewModel に変換する。
   *
   * @param {object} raw  API レスポンス
   * @returns {{ status, affected, affectedCount }}
   *   status: 'ok' | 'unavailable' | 'error'
   */
  function build(raw) {
    if (!raw) return { status: 'unavailable', affected: [], affectedCount: 0 };

    // ODPT未設定や外部エラー → unavailable (デモ fallback なし: error として扱う)
    if (raw.status === 'unavailable') {
      return { status: 'error', affected: [], affectedCount: 0 };
    }

    const items = (raw.items || [])
      .filter(item => item && Number(item.severity) > 0)  // severity=0 = 平常 → 除外
      .sort((a, b) => (Number(b.severity) || 0) - (Number(a.severity) || 0))  // 重要度降順
      .slice(0, 6);  // 最大 6 件

    return {
      status:        'ok',
      affected:      items.map(_buildLine),
      affectedCount: items.length,
    };
  }

  return { build };
})();

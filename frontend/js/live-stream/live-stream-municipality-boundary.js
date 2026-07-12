'use strict';
// /live/stream — 小画面 (地震・キキクル/豪雨) 市区町村境界線・条件付きラベル (Phase 8-B / 8-B.1 / 8-B.2)
//
// データ: frontend/layers/administrative/municipality_boundaries/{block}.geojson (8地方ブロック)
//   scripts/download/download_municipality_boundaries_nationwide.py で全国47都道府県分の raw
//   データを取得し、scripts/derive/simplify_municipality_boundaries.py で地方ブロック単位
//   (北海道/東北/関東/中部/近畿/中国/四国/九州・沖縄) に統合・簡略化・代表点付与したもの。
//   全国1ファイルの一括ロードは避け、小画面の表示範囲 (bbox) に交差するブロックだけを
//   遅延ロード・キャッシュする (Phase 8-B.1 の「常時全国一括ロードしない」要件)。
//
// データソース: スマートニュース メディア研究所 japan-topography
//   (加工元は国土交通省 国土数値情報「行政区域」データ、https://nlftp.mlit.go.jp/ksj/)。
//   国土数値情報側の指定クレジットが必要なため、_installAttribution() で地図の attribution に
//   追加する (スマートニュースへのクレジット表記は README上不要と明記されている)。
//
// この module は eq-mini / rain-mini など複数の小地図インスタンスを key で束ねて扱う
// (LiveStreamRailwayLayer と同じ複数インスタンス管理パターン)。ブロックデータは
// module 全体で共有キャッシュする (同じブロックを複数の小地図が使っても再フェッチしない)。

const LiveStreamMunicipalityBoundary = (function () {
  const BLOCK_URL = (block) => `/layers/administrative/municipality_boundaries/${block}.geojson`;
  const ATTRIBUTION = '国土交通省 国土数値情報（行政区域データ）を加工して作成';

  // 各ブロックのおおまかな bbox (「どのブロックを読み込むか」を決める用途のみ。
  // 実際の境界線描画・point-in-polygon 判定は各 feature 自身の bbox/geometry で行うため、
  // ここでの精度はラフでよい。ただし東京都は南鳥島・小笠原諸島など遠方の離島まで行政区域に
  // 含むため、kanto の bbox をそれらまで含めて計算すると九州・沖縄と丸ごと重なってしまい、
  // 「どのブロックを取得するか」の選定が無意味になる — そのため kanto は本州側の実用範囲に
  // 絞ってある (離島自体の境界線データは kanto.geojson 内にちゃんと含まれている)。
  // このままだと伊豆諸島・小笠原諸島のイベントでブロック選定から漏れてしまうため、
  // Phase 8-B.2 で BLOCK_EXTRA_BBOXES による個別補正を追加している。
  const BLOCK_BBOXES = {
    hokkaido:       [139.30, 41.30, 148.90, 45.60],
    tohoku:         [139.00, 36.70, 142.20, 41.60],
    kanto:          [138.40, 34.50, 140.95, 37.20],
    chubu:          [135.40, 34.50, 139.95, 38.60],
    kinki:          [134.20, 33.40, 137.00, 35.80],
    chugoku:        [130.70, 33.70, 134.55, 36.40],
    shikoku:        [132.00, 32.65, 134.85, 34.60],
    kyushu_okinawa: [122.90, 24.00, 132.10, 34.80],
  };
  const BLOCK_NAMES = Object.keys(BLOCK_BBOXES);

  // Phase 8-B.2: 各ブロックの本土側 bbox から大きく外れる遠方離島用の追加 bbox。
  // kanto の bbox を意図的に本州側へ絞った副作用 (上のコメント参照) で、伊豆諸島・小笠原諸島
  // (南鳥島含む、小笠原村の行政区域内) がブロック選定から漏れていたため個別に補う。
  // 沖縄の遠方離島 (宮古・八重山・大東諸島・奄美群島) は kyushu_okinawa の本来の bbox に
  // 実際には収まっているが、境界付近の取りこぼしを避けるための保険として明示しておく。
  // 点/範囲がここに1つでも一致すれば、そのブロックをロード対象に含める (本来のbboxとのOR判定)。
  const BLOCK_EXTRA_BBOXES = {
    kanto: [
      [139.00, 32.30, 139.90, 34.85], // 伊豆諸島 (大島支庁〜八丈支庁・青ヶ島)
      [140.80, 24.10, 154.00, 27.80], // 小笠原諸島 (父島・母島・硫黄島・南鳥島を含む)
    ],
    kyushu_okinawa: [
      [128.00, 27.00, 130.50, 29.20], // 奄美群島
      [127.00, 25.70, 128.70, 27.00], // 沖縄本島周辺
      [122.80, 24.00, 125.60, 25.60], // 宮古・八重山
      [131.10, 24.40, 131.40, 26.00], // 大東諸島
    ],
  };

  // この zoom 未満 (=広域俯瞰) では描画しない。全国データとはいえ、低ズームで多数ブロック・
  // 大量polygonを毎回描画するのはコストが高く、小画面の用途 (対象1件への寄り) にも合わない。
  const MIN_ZOOM_TO_DRAW = 7;
  const LABEL_MIN_PIXEL_GAP = 24; // ラベル同士がこれより近ければ後勝ちを間引く (衝突回避)

  const _instances = new Map(); // key -> { map, boundaryLayer, labelLayer, ... }
  const _blockPromises = new Map(); // block name -> Promise<Feature[]> (module全体で共有キャッシュ)
  let _lastError = null;
  let _attributionInstalled = false;

  function _installAttribution(map) {
    if (_attributionInstalled || !map || !map.attributionControl) return;
    try {
      map.attributionControl.addAttribution(ATTRIBUTION);
    } catch (_) { /* noop */ }
    _attributionInstalled = true;
  }

  function _loadBlock(block) {
    if (_blockPromises.has(block)) return _blockPromises.get(block);
    const p = fetch(BLOCK_URL(block))
      .then(res => (res.ok ? res.json() : null))
      .then(data => {
        const features = (data && Array.isArray(data.features)) ? data.features : [];
        if (features.length === 0) _lastError = `empty or unavailable: ${block}`;
        return features;
      })
      .catch(e => {
        _lastError = `${block}: ${(e && e.message) || 'fetch failed'}`;
        return [];
      });
    _blockPromises.set(block, p);
    return p;
  }

  function _boundsIntersects(bbox, minx, miny, maxx, maxy) {
    return !(bbox[2] < minx || bbox[0] > maxx || bbox[3] < miny || bbox[1] > maxy);
  }

  function _pointInBbox(bbox, lat, lng) {
    return lng >= bbox[0] && lng <= bbox[2] && lat >= bbox[1] && lat <= bbox[3];
  }

  // 各ブロックの候補 bbox 一覧 (本来の bbox + Phase 8-B.2 の遠方離島用追加 bbox)。
  function _candidateBboxesForBlock(block) {
    const extras = BLOCK_EXTRA_BBOXES[block] || [];
    return [BLOCK_BBOXES[block], ...extras];
  }

  // 現在の表示範囲 (bbox) と交差するブロック名の一覧を返す (本来の bbox か、離島用追加 bbox の
  // どちらかが交差すれば対象に含める)。
  function _blocksForBounds(minx, miny, maxx, maxy) {
    return BLOCK_NAMES.filter(b => _candidateBboxesForBlock(b)
      .some(bbox => _boundsIntersects(bbox, minx, miny, maxx, maxy)));
  }

  // 点 (lat,lng) を含み得るブロック名の一覧 (通常1件、ブロック境界・離島付近では複数)。
  function _blocksForPoint(lat, lng) {
    return BLOCK_NAMES.filter(b => _candidateBboxesForBlock(b)
      .some(bbox => _pointInBbox(bbox, lat, lng)));
  }

  async function _loadBlocks(blockNames) {
    const lists = await Promise.all(blockNames.map(_loadBlock));
    return lists.flat();
  }

  // Ray casting (Polygon/MultiPolygon, 外環のみ判定。N03市区町村データに穴は基本無い想定)。
  function _pointInRing(lat, lng, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      const xi = ring[i][0], yi = ring[i][1];
      const xj = ring[j][0], yj = ring[j][1];
      const intersect = ((yi > lat) !== (yj > lat))
        && (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi);
      if (intersect) inside = !inside;
    }
    return inside;
  }

  function _pointInFeature(lat, lng, feature) {
    const geom = feature.geometry;
    if (!geom) return false;
    if (geom.type === 'Polygon') {
      return geom.coordinates.length > 0 && _pointInRing(lat, lng, geom.coordinates[0]);
    }
    if (geom.type === 'MultiPolygon') {
      return geom.coordinates.some(poly => poly.length > 0 && _pointInRing(lat, lng, poly[0]));
    }
    return false;
  }

  function init(map, opts) {
    const key = (opts && opts.key) || 'default';
    if (_instances.has(key) || !map || typeof L === 'undefined') return;
    const boundaryLayer = L.layerGroup().addTo(map);
    const labelLayer = L.layerGroup().addTo(map);
    const inst = {
      map, boundaryLayer, labelLayer, lastBoundsSig: null, visibleCount: 0, labelCount: 0,
      labelCandidates: [], labelOpts: null,
    };
    _instances.set(key, inst);
    _installAttribution(map);
    // 小地図の移動 (fitTo/focusOn 等) は flyTo/setView によるアニメーションを伴い非同期に完了するため、
    // setLabels() 呼び出し時点ではまだ最終的な view になっていないことがある (投影がズレて全ラベルが
    // ほぼ同じ1点に重なって間引かれてしまう不具合の原因だった)。moveend (アニメーション完了後に発火)
    // のたびに最後の候補リストで再配置することで、常に最終 view に対して正しく配置し直す。
    map.on('moveend', () => {
      _redrawBoundaries(key);
      _placeLabels(key);
    });
  }

  async function _redrawBoundaries(key) {
    const inst = _instances.get(key);
    if (!inst || !inst.map) return;
    const zoom = inst.map.getZoom();
    if (zoom == null || zoom < MIN_ZOOM_TO_DRAW) {
      if (inst.lastBoundsSig !== 'hidden') {
        inst.boundaryLayer.clearLayers();
        inst.lastBoundsSig = 'hidden';
        inst.visibleCount = 0;
      }
      return;
    }
    const bounds = inst.map.getBounds();
    const west = bounds.getWest(), south = bounds.getSouth(), east = bounds.getEast(), north = bounds.getNorth();
    const sig = `${zoom}:${west.toFixed(2)},${south.toFixed(2)},${east.toFixed(2)},${north.toFixed(2)}`;
    if (sig === inst.lastBoundsSig) return; // 範囲がほぼ変わっていなければ再描画しない
    inst.lastBoundsSig = sig;

    const blockNames = _blocksForBounds(west, south, east, north);
    if (blockNames.length === 0) {
      inst.boundaryLayer.clearLayers();
      inst.visibleCount = 0;
      return;
    }
    const features = await _loadBlocks(blockNames);
    // await 中に新しい moveend (別の bounds) が発生していたら、この結果は古いので破棄する。
    if (!_instances.has(key) || _instances.get(key) !== inst || inst.lastBoundsSig !== sig) return;
    if (!features.length) return;

    const visible = features.filter(f => f.properties && f.properties.bbox
      && _boundsIntersects(f.properties.bbox, west, south, east, north));
    inst.boundaryLayer.clearLayers();
    inst.visibleCount = visible.length;
    if (visible.length === 0) return;
    // 境界線は静的表示 (CSSアニメーション不要) のため、地図既定の Canvas renderer のまま描画する
    // (preferCanvas:true。多数の polygon を SVG DOM 化するより軽い — 選択路線ハイライトのような
    // 個別の blink 演出が要らないここでは renderer:L.svg() を強制しない)。
    L.geoJSON(visible, {
      interactive: false,
      style: () => ({
        color: 'rgba(255,255,255,0.22)',
        weight: 0.8,
        fill: false,
      }),
    }).addTo(inst.boundaryLayer);
  }

  /**
   * @param {string} key
   * @param {Array<{lat:number,lng:number,name:string,priority?:number}>} candidates
   * @param {{maxCount?:number}} [opts]
   */
  function setLabels(key, candidates, opts) {
    const inst = _instances.get(key);
    if (!inst) return;
    inst.labelCandidates = (candidates || [])
      .filter(c => c && c.lat != null && c.lng != null && isFinite(c.lat) && isFinite(c.lng) && c.name);
    inst.labelOpts = opts || null;
    _placeLabels(key);
  }

  // 現在の map view (最終的な view とは限らない — アニメーション中に呼ばれることもある) を基準に、
  // 直近の候補リストからラベルを配置し直す。moveend からも呼ばれるため、アニメーション完了後には
  // 必ず正しい view で再配置される。
  function _placeLabels(key) {
    const inst = _instances.get(key);
    if (!inst) return;
    inst.labelLayer.clearLayers();
    inst.labelCount = 0;
    const candidates = inst.labelCandidates;
    if (!candidates || candidates.length === 0) return;
    const maxCount = (inst.labelOpts && inst.labelOpts.maxCount) || 6;
    const list = candidates.slice().sort((a, b) => (b.priority || 0) - (a.priority || 0));

    const placedPoints = []; // 画面座標 (衝突回避用)
    let placedCount = 0;
    for (const c of list) {
      if (placedCount >= maxCount) break;
      let pt;
      try {
        pt = inst.map.latLngToContainerPoint([c.lat, c.lng]);
      } catch (_) {
        continue;
      }
      const tooClose = placedPoints.some(p => Math.hypot(p.x - pt.x, p.y - pt.y) < LABEL_MIN_PIXEL_GAP);
      if (tooClose) continue;
      placedPoints.push(pt);
      placedCount += 1;

      const esc = String(c.name).replace(/[&<>"']/g, ch => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]));
      const icon = L.divIcon({
        html: `<div class="live-muni-label" data-testid="live-stream-municipality-label">${esc}</div>`,
        className: 'live-muni-label-icon',
        iconSize: [0, 0],
      });
      L.marker([c.lat, c.lng], { icon, interactive: false, keyboard: false, zIndexOffset: 300 }).addTo(inst.labelLayer);
    }
    inst.labelCount = placedCount;
  }

  function clearLabels(key) {
    const inst = _instances.get(key);
    if (inst) {
      inst.labelCandidates = [];
      inst.labelLayer.clearLayers();
      inst.labelCount = 0;
    }
  }

  /**
   * 指定の緯度経度を含む市区町村を返す (キキクル/豪雨など、市区町村コードを持たない
   * イベントに対して代表点から市区町村名を逆引きするための補助)。全国どこでも動作する。
   * @returns {Promise<{name:string, code:string}|null>}
   */
  async function findMunicipalityAt(lat, lng) {
    if (lat == null || lng == null || !isFinite(lat) || !isFinite(lng)) return null;
    const blockNames = _blocksForPoint(lat, lng);
    if (blockNames.length === 0) return null;
    const features = await _loadBlocks(blockNames);
    for (const f of features) {
      const bbox = f.properties && f.properties.bbox;
      if (bbox && (lng < bbox[0] || lng > bbox[2] || lat < bbox[1] || lat > bbox[3])) continue;
      if (_pointInFeature(lat, lng, f)) {
        return { name: f.properties.name, code: f.properties.code };
      }
    }
    return null;
  }

  function getDiagnostics() {
    const instances = {};
    for (const [key, inst] of _instances) {
      instances[key] = { visibleCount: inst.visibleCount, labelCount: inst.labelCount, zoom: inst.map ? inst.map.getZoom() : null };
    }
    return {
      lastError: _lastError,
      instanceKeys: [..._instances.keys()],
      instances,
      loadedBlocks: [..._blockPromises.keys()],
    };
  }

  return { init, setLabels, clearLabels, findMunicipalityAt, getDiagnostics };
})();

if (typeof window !== 'undefined') window.LiveStreamMunicipalityBoundary = LiveStreamMunicipalityBoundary;

'use strict';
// /live/stream — 雨雲 (降水ナウキャスト) レイヤー (Stream Phase 4-C)
//
// /live 本体 (frontend/js/live/live-layers.js) と同じ気象庁タイルAPIを利用するが、
// /live 側のファイルは改変せず、stream 専用の独立実装として持つ。
// バックエンドは画像バイトを中継しない (JMAのタイルURLテンプレートを返すのみ) ため、
// Leaflet は気象庁サーバーへ直接タイルを取得しに行く。

const LiveStreamRainLayer = (function () {
  const TIMES_URL = '/api/weather/rain/tile/times';
  const REFRESH_MS = 5 * 60 * 1000; // JMAナウキャストは5分更新

  const TILE_OPTIONS = {
    attribution:   '気象庁 降水ナウキャスト',
    minZoom:       1,
    maxNativeZoom: 10,
    maxZoom:       19,
    tileSize:      256,
    zIndex:        450, // /live 本体 (live-layers.js) と同じ値 (基図タイルより手前)
  };

  // JMA 降水ナウキャスト色テーブル (/live 本体 live-layers.js の _RAIN_PIXEL_TABLE と同一)。
  // alphaScale: 元 alpha に乗算する係数。弱雨ほど低く、強雨ほど高く設定する。
  // 以前は「ほぼ白=透明、それ以外=不透明(1.0)」という簡易2値判定になっており、
  // 弱雨・並雨まで強雨と同じ濃さで描画されて地図が見えにくくなっていた。
  const _RAIN_PIXEL_TABLE = [
    { r: 160, g: 210, b: 255, s: 0.25 }, // weak 弱い雨（薄青）
    { r:  33, g: 140, b: 255, s: 0.25 }, // weak 弱い雨（青）
    { r:   0, g:  65, b: 255, s: 0.40 }, // moderate 雨（濃青）
    { r:   0, g: 200, b: 200, s: 0.40 }, // moderate 雨（シアン）
    { r:   0, g: 200, b:   0, s: 0.65 }, // strong 強い雨（緑）
    { r: 255, g: 215, b:   0, s: 0.65 }, // strong 強い雨（黄）
    { r: 255, g: 140, b:   0, s: 0.70 }, // severe 非常に激しい雨（橙）
    { r: 255, g:   0, b:   0, s: 0.82 }, // severe 非常に激しい雨（赤）
    { r: 180, g:   0, b: 180, s: 0.90 }, // severe 猛烈な雨（紫）
  ];
  const _RAIN_THRESHOLD_SQ = 1600; // 距離 40 の 2 乗 (バックエンド distance_threshold: 40 と同値)
  const _RAIN_BG_MIN       = 230;  // R/G/B がすべてこの値以上なら背景 (降水なし)
  const _RAIN_ALPHA_MIN    = 50;   // alpha がこの値未満なら透明ピクセル

  function _rainAlphaScale(r, g, b, a) {
    if (a < _RAIN_ALPHA_MIN) return 0;
    if (r >= _RAIN_BG_MIN && g >= _RAIN_BG_MIN && b >= _RAIN_BG_MIN) return 0;
    let bestScale = 0.25;
    let bestDist = Infinity;
    for (const c of _RAIN_PIXEL_TABLE) {
      const d = (r - c.r) * (r - c.r) + (g - c.g) * (g - c.g) + (b - c.b) * (b - c.b);
      if (d < bestDist) { bestDist = d; bestScale = c.s; }
    }
    return bestDist <= _RAIN_THRESHOLD_SQ ? bestScale : 0.35;
  }

  const _RainTileLayer = (typeof L !== 'undefined') ? L.TileLayer.extend({
    _clampZoom(zoom) {
      let z = L.TileLayer.prototype._clampZoom.call(this, zoom);
      if (z % 2 !== 0) z = Math.max(z - 1, 2); // JMA hrpns タイルは偶数ズームのみ
      return z;
    },
    createTile(coords, done) {
      const canvas = document.createElement('canvas');
      canvas.width = canvas.height = 256;
      const ctx = canvas.getContext('2d');
      const img = new Image();
      img.crossOrigin = 'anonymous';
      img.onload = function () {
        ctx.drawImage(img, 0, 0);
        try {
          const imageData = ctx.getImageData(0, 0, 256, 256);
          const data = imageData.data;
          for (let i = 0; i < data.length; i += 4) {
            data[i + 3] = Math.round(data[i + 3] * _rainAlphaScale(data[i], data[i + 1], data[i + 2], data[i + 3]));
          }
          ctx.putImageData(imageData, 0, 0);
        } catch (_) {
          // CORS でピクセル読み取り不可の場合は控えめな opacity で全体描画にフォールバック
          ctx.clearRect(0, 0, 256, 256);
          ctx.globalAlpha = 0.35;
          ctx.drawImage(img, 0, 0);
        }
        done(null, canvas);
      };
      img.onerror = e => done(e, canvas);
      img.src = this.getTileUrl(coords);
      return canvas;
    },
  }) : null;

  // Stream Phase 5-A.1 (rain mini map): 中央メイン地図に加え、キキクル・豪雨小画面の小地図
  // (#rain-map) にも同じ降水ナウキャストレイヤーを載せられるよう、単一 _map/_layer ではなく
  // 複数インスタンスを管理する。fetch (5分ごと) は共有し、取得した1つの tile_url_template を
  // 登録済みの全インスタンスへ適用する (小画面が増えても API呼び出しは増やさない)。
  const _instances = []; // [{ key, map, layer }]
  let _timer = null;

  async function _refresh() {
    if (!_RainTileLayer || _instances.length === 0) return;
    try {
      const res = await fetch(TIMES_URL);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const times = Array.isArray(data.times) ? data.times : [];
      const current = times.find(t => t.offset_minutes === 0) || times[0];
      if (!current || !current.tile_url_template) return;

      _instances.forEach(inst => {
        if (inst.layer) { inst.map.removeLayer(inst.layer); inst.layer = null; }
        inst.layer = new _RainTileLayer(current.tile_url_template, TILE_OPTIONS).addTo(inst.map);
      });
    } catch (e) {
      console.warn('[LiveStreamRainLayer] refresh failed:', e.message);
      // Stream Phase 5-C: この fetch は demo/calm/real いずれのモードでも起動する地図タイル用
      // asset fetch (対象外扱い) であり、app-level console error にはしない。診断用に記録のみ行う。
      if (typeof LiveStreamRuntime !== 'undefined' && LiveStreamRuntime.recordFetchFailureDetail) {
        LiveStreamRuntime.recordFetchFailureDetail({
          category: 'rainTile', path: TIMES_URL, mode: 'n/a',
          errorName: e && e.name, errorMessage: e && e.message,
        });
      }
    }
  }

  /**
   * @param {L.Map} map
   * @param {object} [opts]  { key: string }  同一 key で複数回 init しても二重登録しない。
   */
  function init(map, opts) {
    const key = (opts && opts.key) || 'default';
    if (_instances.some(i => i.key === key)) return; // 多重init防止
    if (!_RainTileLayer || !map) return;
    _instances.push({ key, map, layer: null });
    _refresh();
    if (!_timer) _timer = setInterval(_refresh, REFRESH_MS);
  }

  function destroy() {
    if (_timer) { clearInterval(_timer); _timer = null; }
    _instances.forEach(inst => { if (inst.layer) inst.map.removeLayer(inst.layer); });
    _instances.length = 0;
  }

  return { init, destroy };
})();

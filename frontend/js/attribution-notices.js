/**
 * attribution-notices.js — 第三者データ出典表示（Phase 2-D Round 2、P2D-UI-ATTRIBUTION対応）
 *
 * `/`, `/live`, `/live/stream` の3画面で共通して使う、Leaflet地図の
 * attributionControl（右下の常時確認できるコンパクトな出典導線）へ
 * 第三者データの出典を追加するヘルパー。
 *
 * 既存のLeaflet OSM attribution controlは削除・重複・非表示にせず、
 * 追加のattribution文字列を`addAttribution`/`removeAttribution`で
 * 出し入れする（`frontend/js/live-stream/live-stream-municipality-boundary.js`
 * が既に使っている安全なpatternを踏襲）。
 */
(function (global) {
  'use strict';

  var OSM_ATTRIBUTION =
    '<a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">' +
    '&copy; OpenStreetMap contributors</a> (<a href="https://opendatacommons.org/licenses/odbl/1-0/" ' +
    'target="_blank" rel="noopener">ODbL</a>)';

  var KSJ_BOUNDARY_ATTRIBUTION = '国土交通省 国土数値情報（行政区域データ）を加工して作成';

  var GSI_DEM_ATTRIBUTION =
    '<a href="https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html" target="_blank" rel="noopener">' +
    '出典：国土地理院ウェブサイト</a>（数値標高モデルを加工して作成）';

  var HAZARD_KSJ_ATTRIBUTION = '国土交通省 国土数値情報（津波・洪水・高潮・土砂災害の各ハザードデータ）';

  var GSI_SHELTER_ATTRIBUTION =
    '<a href="https://www.gsi.go.jp/bousaichiri/hinanbasho.html" target="_blank" rel="noopener">' +
    '出典：国土地理院「指定緊急避難場所・指定避難所データ」</a>（最新かつ詳細の状況は各市区町村へ確認してください）';

  var JMA_ATTRIBUTION =
    '<a href="https://www.jma.go.jp/jma/kishou/info/coment.html" target="_blank" rel="noopener">' +
    '出典：気象庁ホームページ</a>';

  var OPEN_METEO_ATTRIBUTION =
    '<a href="https://open-meteo.com/" target="_blank" rel="noopener">Weather data by Open-Meteo.com</a> (CC BY 4.0)';

  // MLIT交通量API機能利用規約 第5条1が要求する、サービス利用中は常時確認できる
  // 免責文言（文言を要約・改変しない）。
  var JARTIC_DISCLAIMER =
    'このサービスは、交通量API機能を使用していますが、サービスの内容は国土交通省によって保証されたものではありません。' +
    '（<a href="https://www.jartic-open-traffic.org/" target="_blank" rel="noopener">交通量API（国土交通省）</a>）';

  var ODPT_ATTRIBUTION =
    '鉄道運行情報: <a href="https://developer.odpt.org/terms" target="_blank" rel="noopener">ODPT</a>' +
    '（事業者ごとの個別licenseに基づき許可済み事業者のみ表示）';

  function _addOnce(map, key, text) {
    if (!map || !map.attributionControl) return;
    map.__ohg2AttributionInstalled = map.__ohg2AttributionInstalled || {};
    if (map.__ohg2AttributionInstalled[key]) return;
    try {
      map.attributionControl.addAttribution(text);
      map.__ohg2AttributionInstalled[key] = true;
    } catch (_e) { /* noop: attributionControl未初期化でも地図機能自体は継続させる */ }
  }

  function _remove(map, key, text) {
    if (!map || !map.attributionControl) return;
    if (!map.__ohg2AttributionInstalled || !map.__ohg2AttributionInstalled[key]) return;
    try {
      map.attributionControl.removeAttribution(text);
    } catch (_e) { /* noop */ }
    map.__ohg2AttributionInstalled[key] = false;
  }

  /** 地図の基本attribution（国土数値情報ハザード、GSI DEM、気象庁）を追加する。
   *  OSM基本地図のattributionは各画面のL.tileLayer(...)側で既に設定済みのため
   *  ここでは重複追加しない（ODbLへのlinkは各tileLayer呼び出し側の
   *  attribution文字列自体に含める）。ページ読み込み時に一度だけ呼べばよい（冪等）。 */
  function installBaseAttribution(map) {
    _addOnce(map, 'hazardKsj', HAZARD_KSJ_ATTRIBUTION);
    _addOnce(map, 'gsiDem', GSI_DEM_ATTRIBUTION);
    _addOnce(map, 'jma', JMA_ATTRIBUTION);
  }

  /** 行政区域（国土数値情報N03）境界レイヤーを表示する画面でのみ追加する。 */
  function installBoundaryAttribution(map) {
    _addOnce(map, 'ksjBoundary', KSJ_BOUNDARY_ATTRIBUTION);
  }

  /** 避難所マーカーを表示する画面でのみ追加する。 */
  function installShelterAttribution(map) {
    _addOnce(map, 'gsiShelter', GSI_SHELTER_ATTRIBUTION);
  }

  function installOpenMeteoAttribution(map) {
    _addOnce(map, 'openMeteo', OPEN_METEO_ATTRIBUTION);
  }

  function installOdptAttribution(map) {
    _addOnce(map, 'odpt', ODPT_ATTRIBUTION);
  }

  /** JARTIC道路交通量レイヤーがON中だけ常時表示する（layer OFFで自動的に消える）。 */
  function installJarticAttribution(map) {
    _addOnce(map, 'jartic', JARTIC_DISCLAIMER);
  }

  function removeJarticAttribution(map) {
    _remove(map, 'jartic', JARTIC_DISCLAIMER);
  }

  global.OHG2Attribution = {
    OSM_ATTRIBUTION: OSM_ATTRIBUTION,
    KSJ_BOUNDARY_ATTRIBUTION: KSJ_BOUNDARY_ATTRIBUTION,
    GSI_DEM_ATTRIBUTION: GSI_DEM_ATTRIBUTION,
    JMA_ATTRIBUTION: JMA_ATTRIBUTION,
    OPEN_METEO_ATTRIBUTION: OPEN_METEO_ATTRIBUTION,
    JARTIC_DISCLAIMER: JARTIC_DISCLAIMER,
    ODPT_ATTRIBUTION: ODPT_ATTRIBUTION,
    installBaseAttribution: installBaseAttribution,
    installBoundaryAttribution: installBoundaryAttribution,
    installShelterAttribution: installShelterAttribution,
    installOpenMeteoAttribution: installOpenMeteoAttribution,
    installOdptAttribution: installOdptAttribution,
    installJarticAttribution: installJarticAttribution,
    removeJarticAttribution: removeJarticAttribution,
  };
})(window);

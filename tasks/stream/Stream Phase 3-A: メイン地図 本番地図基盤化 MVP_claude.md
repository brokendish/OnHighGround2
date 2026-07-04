Claude用実装指示書
/live/stream Stream Phase 3-A: メイン地図 本番地図基盤化 MVP
目的

/live/stream 中央のモック日本地図を、配信用の本番地図基盤へ置き換える。

Phase 2-C までで、以下は実データ接続済み。

地震
キキクル・豪雨
潮位
鉄道
下部テロップ

今回の Phase 3-A では、中央メイン地図だけを対象にする。

対象:
  中央メイン地図

対象外:
  地震小窓地図
  キキクル・豪雨小窓地図
  潮位小窓
  鉄道小窓
  鉄道簡略路線図
基本方針

/live/stream の地図は、通常 /live のような操作地図ではない。

配信用の 見るだけ地図 として作る。

通常 /live:
  ユーザーが操作する地図
  レイヤー切替
  ポップアップ
  詳細確認
  現在地
  ズーム操作

/live/stream:
  配信用の見るだけ地図
  操作しない
  日本全土を表示
  軽量
  長時間表示で安定
  パルス/マーカーで注目地点を示す

通常 /live の地図処理を丸ごと流用しない。
タイル設定や地図基盤は共有してよいが、UI制御は /live/stream 専用にする。

1. 中央メイン地図を本番地図へ置き換える

現在の中央メイン地図は、簡略SVG/モック日本地図で表示されている。

これを Leaflet など既存プロジェクトで利用している地図基盤に置き換える。

対象DOM:

live-stream-center-map

既存 data-testid は維持する。

live-stream-center
live-stream-center-map
2. LiveStreamMapView ラッパーを作成する

/live/stream 専用の薄い地図ラッパーを作成する。

ファイル名候補:

frontend/js/live-stream/live-stream-map-view.js

または既存構成に合わせて、

frontend/js/live-stream/live-stream-map.js

へ統合してもよい。

役割
地図初期化
日本全土 fitBounds
操作無効化
パルス描画
マーカー描画
attribution 表示
リサイズ対応
再描画
破棄処理
APIイメージ
class LiveStreamMapView {
  constructor(options) {}

  initialize() {}

  fitJapan() {}

  setPulses(pulses) {}

  setMarkers(markers) {}

  clearPulses() {}

  clearMarkers() {}

  invalidateSize() {}

  destroy() {}
}

呼び出し側イメージ:

const centerMap = new LiveStreamMapView({
  containerId: "live-stream-center-map",
  mode: "center",
  interactive: false
});

centerMap.initialize();
centerMap.fitJapan();
centerMap.setPulses(scene.mapPulses);
centerMap.setMarkers(scene.mapMarkers);

実装は既存設計に合わせて調整してよい。

3. 配信用に操作を無効化する

中央メイン地図は操作させない。

Leafletを使う場合の例:

L.map(container, {
  zoomControl: false,
  attributionControl: true,
  dragging: false,
  scrollWheelZoom: false,
  doubleClickZoom: false,
  boxZoom: false,
  keyboard: false,
  tap: false,
  touchZoom: false
});

必須方針:

ズームボタンを出さない
ドラッグ操作できない
ホイールズームできない
ダブルクリックズームできない
キーボード操作できない
ポップアップを出さない
4. 日本全土が表示されるようにする

中央メイン地図は、初期表示で日本全土が収まるようにする。

基本 bounds:

const JAPAN_BOUNDS = [
  [24.0, 122.0],
  [46.0, 146.5]
];
map.fitBounds(JAPAN_BOUNDS, {
  padding: [8, 8],
  animate: false
});
補足

沖縄・北海道が入ることを優先する。
小笠原まで完全に入れるかは今回必須ではない。

受け入れ条件:

北海道が見える
本州・四国・九州が見える
沖縄本島周辺が見える
日本全体が画面中央の地図内に収まる
5. 既存パルスを本番地図上へ移植する

現在、中央地図には地震・豪雨などのパルスがモック地図上に表示されている。

これを本番地図上の緯度経度に基づく表示へ移植する。

対象
地震パルス
キキクル・豪雨パルス
潮位マーカー/パルスが既にある場合は維持
鉄道パルスは原則不要
表示方針
地震:
  赤〜オレンジ系

キキクル・豪雨:
  青〜水色系

潮位:
  紫系
  Phase 3-Aでは必須ではないが、既存表示があれば壊さない

鉄道:
  中央メイン地図には原則表示しない
pulses ViewModel

既存 scene のパルス情報を、可能なら以下のような構造へ整理する。

scene.mapPulses = [
  {
    id: "earthquake-xxx",
    category: "earthquake",
    lat: 39.2,
    lon: 142.1,
    label: "岩手県沖",
    severity: "high"
  },
  {
    id: "rain-xxx",
    category: "rain",
    lat: 35.1,
    lon: 138.6,
    label: "静岡県中部",
    severity: "warning"
  }
];

既存構造がある場合は、無理に大きく変えず adapter 側で変換する。

6. パルス描画方式

Leaflet の DivIcon、CircleMarker、または専用 pane を使ってよい。

推奨:

DivIcon + CSS animation

理由:

既存のパルス表現を移植しやすい
色・サイズ・アニメーションをCSS管理できる
E2EでDOM確認しやすい

data-testid 候補:

live-stream-map-pulse
live-stream-map-pulse-earthquake
live-stream-map-pulse-rain
live-stream-map-marker

ただし data-testid を Leaflet marker DOM に付けるのが難しい場合は、class名で検証できるようにする。

7. マーカー表示

Phase 3-Aでは、中央地図上のマーカーは最小限でよい。

優先:

地震パルス
豪雨パルス

潮位観測点マーカーは Phase 3-B 以降でもよい。
ただし既に scene 側に潮位 marker 情報があるなら、紫系マーカーとして表示してもよい。

今回の必須対象は 中央地図の本番地図化と既存パルス移植。

8. 地図タイル設定

既存 /live または本体で使っている地図タイル設定を優先する。

避けたいこと:

public OSM tile への新規大量直アクセス
/live/stream だけ別の外部タイルへ依存
外部フォント/外部地図に過剰依存

望ましいこと:

既存プロジェクトの地図タイル設定を再利用
既存キャッシュ/既存Caddy経由の設定があれば使う
通常 /live と出典表記を合わせる

ただし、MVPとして外部OSMタイルを一時利用する場合は、必ず notes に残す。

9. OSM attribution を明記する

本番地図にOSM由来タイルを使う場合、attributionを表示する。

表示例:

© OpenStreetMap contributors

Leaflet attributionControl を使ってもよい。
ただし配信画面なので、表示が大きすぎる場合はCSSで控えめにする。

禁止:

OSM地図を使っているのに attribution がない
10. 画面デザインへの配慮

中央地図が明るすぎると、周囲のダークUIと馴染まない可能性がある。

必要に応じてCSSで調整する。

地図全体を少し暗くする
彩度を抑える
コントラストを落とす
パルスは見やすくする

例:

.live-stream-center-map .leaflet-tile {
  filter: brightness(0.72) saturate(0.8) contrast(1.05);
}

ただし視認性が落ちすぎないようにする。

11. リサイズ対応

OBSやブラウザサイズ変更時に地図が崩れないようにする。

対応:

初期化後に invalidateSize()
画面レイアウト確定後に invalidateSize()
resize イベントで debounce して invalidateSize()

ただし毎秒呼ばない。

12. demo / calm / real の扱い
demo=1
/live/stream?state=alert&chrome=off&demo=1&demoNow=...

固定デモパルスが本番地図上に表示される。

期待:

地震デモ位置に赤系パルス
豪雨デモ位置に青系パルス
日本地図は本番地図
state=calm
/live/stream?state=calm&chrome=off&demoNow=...

本番地図は表示する。
ただし警戒パルスは出さない。

期待:

日本全土の本番地図
パルスなし
監視中文言
通常表示
/live/stream?chrome=off

実データ由来のパルスを表示する。
実データがない場合は、地図だけ表示し、パルスなし。

13. 既存モックSVGの扱い

中央地図のモックSVGは、本番地図化後は通常表示に使わない。

ただし以下の扱いは許容する。

fallback用としてコードに残す
demo専用として残す
削除する

推奨:

通常表示では Leaflet 地図
Leaflet 初期化失敗時のみ fallback として簡易表示

fallback 表示になった場合は、console.warn で分かるようにする。

14. 既存E2Eを壊さない

既存E2Eは維持する。

既存:

e2e/live-stream.spec.js
e2e/eq-mock-verify.spec.js
e2e/rain-mock-verify.spec.js
e2e/tide-mock-verify.spec.js
e2e/rail-mock-verify.spec.js

今回、地図本番化によりDOM構造が変わる可能性があるため、E2Eは必要に応じて更新する。
ただし、既存の data-testid はできるだけ維持する。

15. 追加E2E候補

可能であれば、以下を追加する。

e2e/live-stream-main-map.spec.js

確認内容:

中央地図がLeaflet/本番地図として初期化される
日本全土 bounds で表示される
demo=1 で地震/豪雨パルスが表示される
state=calm でパルスが表示されない
操作UIが表示されない
OSM attribution が表示される
console/page error がない
16. 今回やらないこと
地震小窓のOSM化
キキクル・豪雨小窓のOSM化
小窓リスト連動
地震市町村震度マーカー表示
潮位観測点マーカー本格対応
鉄道簡略路線図
鉄道小窓OSM化
地図クリック/ポップアップ
ユーザー操作

今回の範囲は 中央メイン地図の本番地図化MVP に限定する。

17. 受け入れ条件

以下を満たすこと。

/live/stream の中央メイン地図が本番地図基盤で表示される
日本全土が中央地図に収まる
地図操作UIが出ない
ドラッグ/ズーム操作が無効化されている
OSM attribution が表示される
demo=1 で既存デモパルスが本番地図上に表示される
state=calm で本番地図は表示されるが警戒パルスは出ない
通常表示で実データ由来パルスが表示される、または対象なしならパルスなし
既存の地震/豪雨/潮位/鉄道/テロップ表示が壊れない
undefined / null / NaN が画面に出ない
console error がない
/live が壊れない
/ が壊れない
実装後の報告

以下を報告する。

変更ファイル
追加ファイル
LiveStreamMapView の概要
利用した地図タイル設定
日本全土 bounds
パルス移植内容
操作無効化内容
OSM attribution 表示方法
既存E2E更新内容
追加E2E
未対応項目
次フェーズ候補
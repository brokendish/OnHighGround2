# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 5-A.1：地震情報 子画面詳細化 MVP

## 目的

`/live/stream` の左上「地震情報」子画面を、現在の震源中心表示から一段詳細化する。

現在メイン震源として表示している地震 1 件に対して、P2P で取得した市区町村別震度情報を下部に表示し、視聴者が「どこで、どのくらい揺れたのか」を配信画面上で把握できるようにする。

あわせて、地震情報子画面内の小地図に市区町村震度マーカーを配置する。

Phase 5-A までで `/live/stream` は配信用安定運用の土台が入っているため、この Phase 5-A.1 では既存の `EventStore` / `FocusController` / `Runtime` / diagnostics を壊さず、地震子画面の詳細表示を追加する。

---

## 前提

`/live/stream` は OBS / YouTube 配信用の「見るだけ」監視卓ビューである。

```text
/live
  通常操作用の全国災害ビューア

/live/stream
  配信用・監視卓表示専用ビュー
  16:9固定
  OBSブラウザソース想定
  操作不可
  自動巡回
  地図・小窓・パネル・テロップで全国状況を俯瞰
```

Phase 5-A.1 の対象は、左上の地震情報子画面である。

メイン地図、鉄道子画面、キキクル/豪雨子画面、潮位子画面の大改修は今回対象外。

---

## 重要方針

### 1. `/live` 本体を壊さない

通常 `/live` の既存UI、既存JS、既存API挙動を壊さないこと。

`/live/stream` 側の地震詳細表示は、可能な限り stream 専用JS/CSSに閉じる。

禁止:

```text
/live 側の地震表示ロジックを stream 都合で大きく変更する
既存APIレスポンス形式を破壊する
通常 /live の地震パネルや地図挙動を変える
```

---

### 2. P2P 市区町村震度データは既存取得経路を優先する

新しい外部API直叩きや新規スクレイピングはしない。

まず既存コードを調査し、P2P / JMA / 地震詳細 / 市区町村震度に関する取得経路があるか確認する。

確認対象例:

```text
frontend/js/live/
frontend/js/live-stream/
backend/
data_runtime/backend/
tasks/live/
e2e/*earthquake*
e2e/*eq*
```

既存 `/live` 側ですでに P2P の市区町村震度情報を取得・正規化している場合は、それを流用する。

既存 backend API に市区町村震度が含まれている場合は、それを利用する。

既存データに市区町村震度がない場合は、Phase 5-A.1 では以下のどちらかに留める。

```text
1. 既存データから取得可能な範囲のみ表示
2. stream 専用の安全な正規化層を追加し、既存データ形式を壊さない
```

---

### 3. demo fallback しない

通常 `/live/stream` で P2P 市区町村震度が取れない場合に、demo の市区町村震度を勝手に表示してはいけない。

```text
通常モード:
  本番データのみ

demo=1:
  demo データのみ

state=calm:
  市区町村震度表示なし
```

---

### 4. 配信画面として「読める」「邪魔しない」を優先する

地震子画面は小さいため、情報を詰め込みすぎない。

ただし、大規模地震で市区町村数が多い場合は、複数行リスト + 自動スクロールで全体を表示する。

重要:

```text
全スクロールの表示が終わるまで、地震子画面の表示対象を切り替えない
市区町村震度マーカーの全範囲を小地図で巡回表示し終わるまで、次の地震情報へ進まない
```

---

## 実装対象

### 対象

左上「地震情報」子画面。

既存表示を活かしつつ、以下を追加する。

```text
1. メイン震源 1 件の詳細カード
2. その下に P2P 市区町村震度リスト
3. 小地図に市区町村震度マーカー
4. 市区町村数が多い場合のリスト自動スクロール
5. 震度範囲が広い場合の小地図自動巡回
6. スクロール/巡回完了まで表示切替を待つ制御
```

---

## 推奨ファイル構成

既存構成を優先すること。

新規追加する場合の推奨例:

```text
frontend/js/live-stream/live-stream-earthquake-detail.js
frontend/js/live-stream/live-stream-earthquake-mini-map.js
frontend/js/live-stream/live-stream-panel-playback.js
frontend/css/live/live-stream.css
e2e/live-stream-earthquake-detail.spec.js
```

既存ファイルを拡張する場合の候補:

```text
frontend/js/live-stream/live-stream-earthquake-adapter.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-scene.js
frontend/js/live-stream/live-stream-focus-controller.js
frontend/js/live-stream/live-stream-runtime.js
frontend/js/live-stream/live-stream-event-store.js
```

ただし、既存の安定性対策を壊すような大改修は避ける。

---

## データ正規化

### 市区町村震度データの共通形式

P2P / 既存API / demo いずれの入力であっても、stream 内部では以下のような形式へ正規化する。

```js
{
  id: "eq-20260704-0921-iwate-morioka",
  eventId: "eq-20260704-0921",
  pref: "岩手県",
  city: "盛岡市",
  areaName: "岩手県盛岡市",
  intensity: "5弱",
  intensityRank: 50,
  lat: 39.7036,
  lng: 141.1527,
  source: "p2pquake"
}
```

必須:

```text
eventId
pref
city または areaName
intensity
intensityRank
```

任意:

```text
lat
lng
source
```

座標がない場合:

```text
リストには表示してよい
小地図マーカーにはしない
```

### 震度 rank

並び順・強調表示用に rank を持つ。

推奨:

```text
7    -> 70
6強  -> 65
6弱  -> 60
5強  -> 55
5弱  -> 50
4    -> 40
3    -> 30
2    -> 20
1    -> 10
不明 -> 0
```

既存に別の rank がある場合は、それを使ってよい。

---

## 表示仕様：市区町村震度リスト

### 配置

現在メイン震源として表示している 1 件の下に、市区町村震度リストを表示する。

構成イメージ:

```text
[メイン震源カード]
  岩手県沖
  M6.1 / 最大震度5弱 / 19:21

[市区町村震度]
  5弱 岩手県 盛岡市
  5弱 岩手県 宮古市
  4   青森県 八戸市
  4   岩手県 花巻市
  ...
```

### 並び順

推奨:

```text
1. 震度が高い順
2. 都道府県順
3. 市区町村名順
```

同じ震度の中では、都道府県ごとにまとまっていると視聴者が理解しやすい。

### 表示件数が多い場合

表示領域に収まらない場合は、自動スクロールする。

要件:

```text
複数行リスト表示
縦方向にゆっくり自動スクロール
全行が一度は表示される
スクロール完了まで地震表示対象を切り替えない
スクロール完了後に次の地震/次の focus へ進んでよい
```

推奨:

```text
visible rows: 5〜8行程度
scroll speed: 配信で読める速度
最小表示時間: 8秒程度
最大表示時間: 45〜60秒程度
```

大規模地震で市区町村が非常に多い場合は、長すぎる配信停滞を避けるため、最大表示時間の上限を設けてもよい。

ただし、上限を設ける場合は「全体を表示しきれない可能性がある」ことを diagnostics / notes で分かるようにする。

---

## 表示仕様：小地図の市区町村震度マーカー

### 目的

震源だけでなく、「どこでどの程度揺れたか」を視聴者に伝える。

### 表示対象

座標を持つ市区町村震度データを小地図へ表示する。

```text
lat/lng がある市区町村のみ marker 表示
lat/lng がない市区町村はリストのみ
不正座標は除外
```

日本周辺の簡易座標チェック例:

```text
lat: 20〜46
lng: 122〜154
```

### マーカー仕様

震度マーカーは地図を隠さない程度に小さくする。

推奨:

```text
直径 10〜16px 程度
震度数字または短い震度表記を表示
強震度ほど少し目立たせる
常時激しく点滅させない
```

CSS class 例:

```css
.stream-eq-intensity-marker
.stream-eq-intensity-marker--1
.stream-eq-intensity-marker--2
.stream-eq-intensity-marker--3
.stream-eq-intensity-marker--4
.stream-eq-intensity-marker--5-lower
.stream-eq-intensity-marker--5-upper
.stream-eq-intensity-marker--6-lower
.stream-eq-intensity-marker--6-upper
.stream-eq-intensity-marker--7
.stream-eq-intensity-marker--active
```

### 小地図の実装方式

既存の地震子画面内にある小地図表現を優先して活かす。

実装候補:

```text
1. 既存の小地図/装飾マップに marker overlay を追加
2. stream 専用の軽量 Leaflet mini map を 1 インスタンスだけ作る
3. SVG/Canvas の軽量 mini map として実装する
```

重要:

```text
地震カードごとに Leaflet map を増殖させない
小地図インスタンスは再利用する
更新時に marker が増殖しない
OBS長時間表示でメモリ/DOMが増え続けない
```

Leaflet mini map を使う場合:

```text
zoomControl: false
dragging: false
scrollWheelZoom: false
doubleClickZoom: false
keyboard: false
attributionControl: false または既存 attribution との整合を取る
```

---

## 小地図の範囲制御

### 通常

市区町村震度マーカーの bounds を計算し、小地図に収まるように表示する。

### 範囲が広い場合

震度範囲が広く、小地図に収めるとマーカーが潰れて何も伝わらない場合は、小地図を自動巡回する。

例:

```text
東北全体
関東〜東北
北海道〜東海
広域津波を伴う地震
```

要件:

```text
市区町村震度マーカー全体を表示対象にする
範囲を複数フレームに分ける
小地図をゆっくり pan / fit して各範囲を表示する
全範囲を巡回し終わるまで次の地震情報へ進まない
```

フレーム分割の例:

```text
都道府県単位
地域ブロック単位
震度上位地点優先 + 残り地域
緯度経度グリッド
```

MVPでは複雑な最適化は不要。

推奨:

```text
1. 高震度地点を優先
2. 都道府県または地域ブロックごとに group
3. 各 group の bounds を順番に表示
4. 最後に全体 bounds へ戻る
```

ただし、全体 bounds に戻すと見づらい場合は省略してよい。

### 小地図 frame 状態の露出

E2E検証しやすいよう、DOM属性または diagnostics に状態を出す。

例:

```text
data-eq-mini-map-frame-index="1"
data-eq-mini-map-frame-total="4"
data-eq-mini-map-mode="fit|tour|empty|unavailable"
```

---

## 表示切替ロック

### 背景

地震子画面の詳細リストや小地図巡回が終わる前に、次の focus / scene / 地震カードへ切り替わると、視聴者が情報を読み切れない。

### 要件

以下が完了するまで、地震子画面の対象を切り替えない。

```text
市区町村震度リストの自動スクロール
小地図の全フレーム巡回
```

可能なら、既存の `LiveStreamFocusController` に大きな変更を入れず、最小限の hold 機構を追加する。

推奨API例:

```js
window.LiveStreamFocusController.requestHold({
  source: "earthquake-detail",
  eventId,
  durationMs,
});
```

または:

```js
window.LiveStreamPanelPlayback.requestHold("earthquake-detail", eventId, durationMs);
```

要件:

```text
hold 中は focus event id を別の地震へ切り替えない
hold 中も Runtime refresh / data update は止めない
対象 event が消えた場合は hold を解除する
API失敗や空データ時に hold が残り続けない
hold は最大時間で必ず解除される
```

E2E検証用に状態を露出する。

例:

```text
body[data-stream-panel-hold="earthquake-detail"]
body[data-stream-panel-hold-event-id="eq-..."]
body[data-stream-panel-hold-until="..."]
```

---

## EventStore / FocusController との関係

既存 Phase 3-D / 4-A / 5-A の前提を壊さない。

```text
EventStore:
  正規化 event の集約元

FocusController:
  注目イベントの自動巡回

Runtime:
  fetch / in-flight / diagnostics / degraded/error 管理
```

Phase 5-A.1 では、地震詳細表示が EventStore の earthquake event と紐づくことが重要。

推奨:

```text
earthquake event に municipalIntensities を関連付ける
または event id で earthquake detail store を参照する
```

避けること:

```text
DOMから震源名を読んで P2P データを無理にマッチングする
現在表示テキストだけで event を推定する
focus と無関係な地震詳細を表示する
```

---

## データなし・取得失敗時

P2P 市区町村震度がない場合も画面を壊さない。

表示例:

```text
市区町村震度: 詳細取得中
市区町村震度: 詳細なし
市区町村震度: 一時的に取得不可
```

条件:

```text
通常モードで demo データを表示しない
JS pageerror を出さない
小地図 marker が残存しない
古い event の市区町村震度を別 event に誤表示しない
```

---

## demo mode

`demo=1` では、地震詳細表示のデモデータを用意してよい。

demo では以下を確認できるようにする。

```text
市区町村震度リストが複数行で表示される
自動スクロールする
小地図に震度マーカーが出る
広域震度の場合に小地図 tour が動く
hold 中に次へ切り替わらない
```

demo 用の query param 例:

```text
/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test
```

既存 demo パイプラインに合わせること。

---

## diagnostics

Phase 5-A の diagnostics 方針に合わせ、必要最小限の状態を `window.__LiveStreamDiagnostics.getSnapshot()` に追加する。

例:

```js
{
  earthquakeDetail: {
    activeEventId: "eq-...",
    municipalCount: 48,
    markerCount: 42,
    missingCoordinateCount: 6,
    scrollMode: "static|scrolling|empty|unavailable",
    scrollProgress: 0.42,
    miniMapMode: "fit|tour|empty|unavailable",
    miniMapFrameIndex: 1,
    miniMapFrameTotal: 4,
    holdActive: true
  }
}
```

E2Eで読めることを優先する。

---

## CSS / 視認性

### リスト

```text
小さすぎない
読みやすい行間
震度ラベルが一目で分かる
スクロール中でも文字がブレすぎない
```

### マーカー

```text
地図を隠さない
色・数字・サイズで震度差が分かる
密集時に完全に読めなくても、強い揺れの分布が分かる
```

### 動き

```text
スクロール速度は読める速度
点滅しすぎない
OBS配信でちらつきにくい
prefers-reduced-motion も可能なら考慮
```

---

## パフォーマンス

Phase 5-A の安定性対策を維持する。

注意:

```text
更新ごとに mini map instance を作り直さない
更新ごとに marker DOM が増殖しない
setInterval / setTimeout が多重起動しない
hold timer が残存しない
subscribe が増殖しない
```

---

## E2E追加

最低限、以下を追加または更新する。

```text
e2e/live-stream-earthquake-detail.spec.js
```

テスト観点:

```text
1. 地震 event に municipal intensity がある場合、メイン震源カード下に市区町村震度リストが出る
2. 市区町村震度は震度降順で表示される
3. 座標あり市区町村は小地図 marker になる
4. 座標なし市区町村はリストには出るが marker にはならない
5. 多数市区町村時にリストが自動スクロールする
6. リストスクロール完了まで表示対象が切り替わらない
7. 広域震度時に小地図が複数フレーム巡回する
8. 小地図巡回完了まで表示対象が切り替わらない
9. P2P 詳細取得失敗時に画面が壊れない
10. 空データ時に古い marker/list が残らない
11. demo=1 でも同じ detail pipeline を通る
12. state=calm では詳細表示・marker が出ない
13. Phase 5-A の stability E2E が回帰しない
14. 通常 /live に副作用がない
```

---

## 完了条件

Phase 5-A.1 の完了条件は以下。

```text
/live/stream 地震子画面で、現在対象の地震に紐づく市区町村震度リストが表示される
市区町村数が多い場合に自動スクロールし、全体を見せる設計になっている
スクロール完了まで地震子画面の対象が切り替わらない
小地図に市区町村震度マーカーが表示される
広域震度時に小地図が巡回表示される
小地図巡回完了まで次の地震情報へ進まない
P2P詳細なし/取得失敗/空データで画面破綻しない
demo fallback しない
marker / timer / subscriber が増殖しない
既存 Phase 3-D / 4-A / 5-A のE2Eが回帰しない
通常 /live に明確な副作用がない
```

---

## 注意

この Phase 5-A.1 は、見た目の派手さより「視聴者に揺れの分布が伝わること」を優先する。

特に重要:

```text
震源だけでなく、市区町村震度を伝える
大規模地震でも読める形で流す
表示し終える前に切り替えない
小地図で揺れの広がりを見せる
長時間配信で増殖しない
```

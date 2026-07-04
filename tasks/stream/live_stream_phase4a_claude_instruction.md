# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 4-A：自動巡回・注目地域フォーカス MVP

## 目的

`/live/stream` に、配信用監視卓としての **自動巡回・注目地域フォーカス** を追加する。

Phase 3-B / 3-C / 3-D で構築済みの以下を前提にする。

- 本番API由来 event marker 表示
- `LiveStreamEventStore` を中心にした event pipeline
- 地図 marker / 左右パネル / テロップ同期
- 全体ステータス・カテゴリバッジ・件数表示同期

Phase 4-A では、`LiveStreamEventStore` の active event / summary を利用して、配信画面が自動的に「今見るべき地域・カテゴリ」へ視線誘導する状態を作る。

通常 `/live` は操作用、`/live/stream` は配信用の「見るだけ」画面である。

```text
/live
  通常操作用の全国災害ビューア

/live/stream
  配信用・監視卓表示専用ビュー
  OBSブラウザソース想定
  16:9固定
  操作不可
  自動巡回
  注目地域フォーカス
  下部テロップ
  地図・小窓・パネルで状況把握
```

## 重要方針

### 1. `/live` を壊さない

通常 `/live` の既存UI、既存JS、既存API挙動を壊さないこと。

禁止事項:

- `/live` 側の通常地図・レイヤー・パネル挙動を変更する
- `/live` 側に stream 専用分岐を大量追加する
- 既存APIレスポンス形式を stream 都合で変更する
- `/live/stream` のために外部APIを新規直叩きする

Phase 4-A の実装は、原則として `frontend/js/live-stream/` と `frontend/css/live/live-stream.css` に閉じる。

### 2. EventStore を唯一の判断元にする

自動巡回・注目地域フォーカスは `LiveStreamEventStore` の normalized event / summary を利用する。

各パネルDOMをスクレイピングして巡回対象を作らない。

推奨:

- `LiveStreamEventStore.getEvents()`
- `LiveStreamEventStore.getHeadlineEvents()`
- `LiveStreamEventStore.getSummary()`
- `LiveStreamEventStore.subscribe()`

### 3. 見るだけ画面のままにする

地図のユーザー操作不可は維持する。

維持する仕様:

- ズームUIなし
- ドラッグ不可
- ホイールズーム不可
- ダブルクリックズーム不可
- キーボード操作不可

ただし、Phase 4-A では **プログラムによる地図移動・ズーム** は許可する。

つまり、ユーザー操作は不可だが、配信画面として自動的に日本全体表示と注目地点表示を切り替える。

### 4. OBS配信で破綻しないことを優先

派手な演出より安定性を優先する。

- 高速で切り替えすぎない
- map tile の読み込みが追いつかないほどズームしない
- 左右パネル・テロップを邪魔しない
- 取得失敗時に demo fallback しない
- イベントがない時は静かな全国監視表示に戻る

## MVPスコープ

Phase 4-A で実装するもの:

1. 自動巡回コントローラ
2. 注目 event の選定ロジック
3. 中央メイン地図の自動フォーカス
4. 地図 marker / パネル / テロップの active event 同期
5. calm / error / demo / real 各状態で破綻しない挙動
6. E2Eで検証可能な data attribute / test hook

Phase 4-A ではやらないもの:

- 新しい外部API追加
- `/live` 本体のUI変更
- 鉄道路線 polyline の自動追跡
- 潮位 alert 判定の本格実装
- 自動音声読み上げ
- YouTube API連携
- OBS制御
- 複雑なカメラワークや3D演出

## 推奨ファイル構成

既存構成に合わせること。新規追加する場合の推奨:

```text
frontend/js/live-stream/live-stream-focus-controller.js
frontend/js/live-stream/live-stream-focus-policy.js
```

既存ファイルを拡張する場合の候補:

```text
frontend/js/live-stream/live-stream-main.js
frontend/js/live-stream/live-stream-map-view.js
frontend/js/live-stream/live-stream-map-events.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-scene.js
frontend/css/live/live-stream.css
```

テスト候補:

```text
e2e/live-stream-auto-focus.spec.js
```

## 自動巡回の基本仕様

### モード

`/live/stream` は以下の巡回状態を持つ。

```text
overview
  日本全体を表示する監視状態

focus
  重要 event の地点へ自動フォーカスしている状態

returning
  overview へ戻る途中、または戻した直後の状態

paused/off
  query param またはテスト都合で自動巡回を停止した状態
```

MVPでは内部状態名は自由だが、E2Eで確認できるように body または root 要素へ data attribute を付ける。

推奨:

```html
<body data-stream-focus-mode="overview" data-stream-focus-event-id="">
<body data-stream-focus-mode="focus" data-stream-focus-event-id="eq-xxx">
```

または:

```html
<div id="live-stream-root" data-focus-mode="focus" data-focus-event-id="eq-xxx">
```

### デフォルト挙動

通常アクセス時:

```text
/live/stream
  自動巡回 ON
```

calm:

```text
/live/stream?state=calm
  event があっても強制 calm なので focus しない
  日本全体表示
```

demo:

```text
/live/stream?demo=1
  demo event も同じ focus pipeline で巡回対象にする
```

テスト・スクリーンショット用に自動巡回を止められる query param を追加してよい。

推奨:

```text
/live/stream?focus=off
/live/stream?autofocus=0
```

E2E高速化用に短い間隔を指定できる query param を追加してよい。

推奨:

```text
/live/stream?focusSpeed=test
```

ただし、通常運用のデフォルトを高速化しないこと。

## 巡回タイミング

OBS配信で見やすい程度にする。

推奨値:

```js
const OVERVIEW_DURATION_MS = 15000;
const FOCUS_DURATION_MS = 12000;
const RETURN_DURATION_MS = 3000;
const MIN_REBUILD_INTERVAL_MS = 5000;
```

MVPでは厳密でなくてよいが、以下は避ける。

- 1〜2秒ごとに頻繁に切り替わる
- event 更新のたびに即座にカメラが飛ぶ
- setInterval が多重起動する
- 画面遷移時に timer が残り続ける

`LiveStreamEventStore.subscribe()` で event 更新を受ける場合、既存 timer を必ず整理する。

## 注目 event 選定ロジック

### 基本方針

`LiveStreamEventStore` の normalized event から、配信上見せる価値のある event を選ぶ。

必須条件:

- lat/lng を持つ
- stale / invalid / filtered out ではない
- 表示対象カテゴリである
- `state=calm` では巡回対象にしない

対象カテゴリ:

```text
earthquake
rain
kikikuru
railway
tide
water
```

ただし tide/water は alert event 化されている場合のみ対象にする。通常の潮位パネル地点を巡回対象にしない。

### 優先順位

MVPの優先順位は以下を推奨する。

```text
1. critical severity
2. high severity
3. earthquake M5以上 / 最大震度5弱以上
4. kikikuru 危険 / 警戒
5. railway 運転見合わせ / 一部運休 / 見合わせ
6. rain 強雨・猛烈な雨・非常に激しい雨
7. tide/water alert event
8. medium severity
9. low/info は原則フォーカス対象外
```

同じ severity 内では、以下で並べる。

```text
rank が小さいもの
updatedAt が新しいもの
timeLabel が新しいもの
```

実装上すでに `getHeadlineEvents()` が優先度順を持つなら、それをベースにしてよい。

### 件数上限

巡回対象は絞る。

推奨:

```text
最大 5 event
```

理由:

全国配信画面で巡回対象が多すぎると、視聴者が追えない。

### カテゴリ偏りの抑制

MVPでは簡易でよい。

推奨:

- 最重要 event は必ず入れる
- 可能ならカテゴリごとに最大2件程度
- 地震だけで5件埋まる場合でも high/critical なら許容

## 地図フォーカス仕様

### overview

overview は Phase 3-A の日本全体表示を維持する。

```text
center: 日本全体が見える中心
zoom: 日本全体が入るズーム
```

既存の initial view / bounds がある場合はそれを使う。

### focus

注目 event の lat/lng へ中央メイン地図を自動移動する。

推奨ズーム:

```text
earthquake: 6〜7
rain/kikikuru: 7〜8
railway: 8〜10
tide/water: 8〜10
unknown: 7
```

ただし全国監視卓なので寄りすぎない。

市区町村や駅単位まで極端にズームしないこと。

### アニメーション

MVPでは、`flyTo` / `setView` / `panTo` のどれでもよい。

推奨:

- 通常運用は滑らかな `flyTo` または `setView` with animation
- E2Eではアニメーション完了を待ちやすいよう data attribute を更新する
- `prefers-reduced-motion` ではアニメーションを抑制できるとよい

### フォーカス表示

フォーカス中の event を視覚的に分かるようにする。

必須:

- 地図 marker に active class を付与
- 対応パネル項目に active class または data-active を付与
- テロップまたはヘッドラインに同じ event 内容が出る

推奨 class:

```css
.stream-map-event--active
.stream-panel-item--active
.stream-focus-card
```

推奨 data attribute:

```html
<div class="stream-map-event" data-event-id="eq-xxx" data-active="true"></div>
<div class="stream-panel-item" data-event-id="eq-xxx" data-active="true"></div>
```

### フォーカス中の簡易ラベル

可能なら中央地図上、または地図上部に小さな focus label を出す。

例:

```text
注目: 岩手県沖 M6.1 / 最大震度5弱
注目: 静岡県 中部 キキクル危険
注目: 中央線快速 運転見合わせ
```

ただし、既存UIを圧迫するなら必須ではない。

## パネル同期仕様

Phase 3-C の同期を維持しつつ、active focus event をパネル側でも示す。

- 地震 focus 中: 地震パネルの該当 card / item を active
- rain/kikikuru focus 中: キキクル・豪雨パネルの該当 card / item を active
- railway focus 中: 鉄道パネルの該当 item を active
- tide/water focus 中: 潮位・水位パネルの該当 item を active

パネルが複数項目をローテーション表示している場合、active event のカテゴリ・IDと矛盾しないようにする。

MVPでは、完全なスクロール制御までは不要。ただし、該当 event が表示範囲内にある場合は active 表示する。

## テロップ同期仕様

フォーカス中の event は、下部テロップにも反映する。

MVPでは以下のいずれかでよい。

方式A:

- フォーカス event を ticker の先頭に一時的に優先表示する

方式B:

- ticker は既存 priority のまま維持し、フォーカス event が headline 対象の場合は内容一致を保証する

推奨は方式A。

例:

```text
【注目】岩手県沖 M6.1 最大震度5弱 ／ 【大雨】静岡県 中部 キキクル「危険」 ／ ...
```

取得失敗時・空データ時は従来通り:

```text
【監視中】全国の地震・豪雨・潮位・交通影響を監視中
【監視中】一部データの取得を確認中です
```

## ステータス同期仕様

Phase 3-D の以下を壊さない。

- `LiveStreamEventStore.getSummary()`
- top category badge count
- category status
- overall status
- `data-stream-overall-status`
- `body[data-stream-status]`
- panel `data-count` / `data-status`

Phase 4-A で追加する focus 状態は、summary の上書きではなく追加情報として扱う。

推奨:

```js
LiveStreamFocusController.getState()
// または
window.LiveStreamFocusController
```

E2E向けに最低限参照可能にしてよい。

## エラー・空データ時の挙動

### 空データ

期待:

- focus 対象なし
- 日本全体 overview
- marker なし
- category badge 0
- panel calm
- ticker monitoring
- JS error なし

### API失敗

期待:

- focus 対象なし、または直前の有効 event が stale でなければ維持
- demo fallback なし
- map は壊れない
- ticker は「取得を確認中」
- data status は error / partial など既存方針に従う
- JS error / unhandledrejection なし

### event 更新で対象が消えた場合

期待:

- active event id を解除
- 次の対象があれば移る
- なければ overview へ戻る
- 古い active class が残らない

## demo / calm 仕様

### demo=1

- demo event も EventStore 経由で巡回対象にする
- 地図 marker / パネル / ticker / badge / focus が同じ event pipeline で同期する
- 本番 fetch と混ぜない

### state=calm

- calm では自動フォーカスしない
- event marker / pulse は出さない
- map は overview
- badge は 0
- panel/ticker は監視中表示

既存仕様通り、calm URL は `state=calm` を使う。

## CSS方針

既存デザインに合わせる。

追加候補:

```css
.stream-map-event--active
.stream-panel-item--active
.stream-focus-indicator
.stream-focus-label
.stream-root--focus
.stream-root--overview
```

演出は控えめにする。

- active marker は少し強調
- active panel item は枠線または発光程度
- 点滅しすぎない
- OBSで読みやすい
- ダークUIと調和する

`prefers-reduced-motion` も考慮できるとよい。

## E2E追加

新規または更新:

```text
e2e/live-stream-auto-focus.spec.js
```

テスト観点:

1. 本番データ mock で高優先 event が focus 対象になる
2. body/root に focus mode と focus event id が反映される
3. focus event id が map marker と panel item で一致する
4. focus event 内容が ticker に反映される
5. 複数 event がある場合、一定時間後に次の focus event へ巡回する
6. `state=calm` では focus せず overview のまま
7. `demo=1` でも同じ focus pipeline で巡回する
8. 空データでは focus せず overview のまま
9. API 500 / 不正JSON / timeout 相当で画面破綻なし、demo fallback なし
10. event 更新で active event が消えた場合、active class が解除される
11. 地図操作不可が維持される
12. `/live` 通常画面に副作用がない

E2E高速化のために `focusSpeed=test` などの query param を実装した場合は、それを使ってよい。

## 完了条件

Phase 4-A の完了条件:

- `/live/stream` が通常アクセスで自動巡回する
- 重要 event が注目対象として選ばれる
- 中央メイン地図が注目 event へ自動フォーカスする
- focus event id が地図 marker / パネル / テロップで同期する
- overview に戻れる、または巡回継続できる
- calm では focus しない
- demo でも同じ pipeline で巡回する
- 空データ / API失敗 / 不正JSON / timeout で画面破綻しない
- demo fallback しない
- 地図操作不可が維持される
- Phase 3-D のバッジ・件数・ステータス同期を壊さない
- 通常 `/live` に明確な副作用がない
- E2E が追加/更新され PASS

## 注意

Phase 4-A は「派手なカメラ演出」ではなく、監視卓としての視線誘導 MVP である。

最重要は以下。

```text
EventStore を単一の判断元にする
active event id を map / panel / ticker で一致させる
calm / error で破綻しない
/live 本体を壊さない
```

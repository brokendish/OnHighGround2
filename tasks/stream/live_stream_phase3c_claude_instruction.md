# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 3-C：メイン地図 event と左右パネル・テロップの同期 MVP

## 目的

OnHighGround2 内の `/live/stream` で、Phase 3-B により中央メイン地図へ表示できるようになった本番API由来 event marker を、左右パネルおよび下部テロップと同期させる。

`/live/stream` は OBS / YouTube 配信用の「見るだけ」監視卓ビューであり、通常 `/live` の操作画面とは役割が異なる。

```text
/live
  通常操作用の全国災害ビューア

/live/stream
  配信用・監視卓表示専用ビュー
  16:9固定
  OBSブラウザソース想定
  操作不可
  自動更新
  地図・小窓・パネル・テロップで全国状況を俯瞰
```

Phase 3-C のゴールは、以下を同じ event データから描画すること。

```text
中央メイン地図 event marker
左右パネルの注目情報
下部テロップ
全体ステータス表示
```

つまり、地図・パネル・テロップが別々の mock / demo / 独自状態を見るのではなく、同一の正規化 event list を参照する構造にする。

---

## 前提

Phase 3-B は PASS with notes 済み。

確認済み:

```text
通常 /live/stream で demo pulse ではなく本番API由来 event marker を表示
空データ / 500 / 404 / 不正JSON / timeout で画面破綻なし
不正座標除外・重複排除・件数上限・stale 表示/除外
地図操作不可を維持
OSM/CARTO/Leaflet attribution 表示
/live と / に明確な副作用なし
```

Phase 3-B の notes:

```text
calm URL は calm=1 ではなく既存仕様の state=calm
潮位の中央地図 event は alert 判定未接続のため実質後続フェーズ扱い
```

Phase 3-C でも、calm URL は既存仕様の `state=calm` を優先すること。

潮位 event は、alert 判定や注目判定が未接続なら無理に出さない。潮位パネルは「通常監視中」「注目情報なし」などの静穏表示でよい。

---

## 重要方針

### 1. `/live` を壊さない

通常 `/live` の既存UI、既存JS、既存API挙動を壊さないこと。

`/live/stream` 側で必要な処理は、可能な限り stream 専用JS/CSSに閉じる。

禁止事項:

```text
/live 側の表示ロジックへ stream 専用分岐を大量追加する
既存APIのレスポンス形式を stream 都合で変更する
通常 /live の地図・レイヤー・パネル挙動を変える
```

---

### 2. 同一 event source を使う

Phase 3-C の最重要ポイントは、地図・左右パネル・テロップの情報源を統一すること。

望ましい構造:

```text
既存API / static runtime data
  ↓
/live/stream 用 正規化 event list
  ↓
stream event store / state
  ↓
map renderer
panel renderer
ticker renderer
status renderer
```

避けるべき構造:

```text
map は本番API由来
panel は古い mock
ticker は demo 固定文言
status は別ロジック
```

これをやると、配信画面として情報の辻褄が合わなくなる。

---

### 3. demo / calm も同じ pipeline を通す

`/live/stream?demo=1` の demo event も、可能な限り本番 event と同じ正規化形式・同じ store・同じ renderer を通す。

`/live/stream?state=calm` は、event list が空の静穏状態として扱う。

通常アクセス `/live/stream` で本番API取得に失敗した場合、demo event に勝手に fallback してはいけない。

---

## 実装対象

### MVP対象

以下を Phase 3-C MVP の対象とする。

```text
1. stream event store の導入または整理
2. 中央メイン地図 marker と event store の同期
3. 左右パネルの注目情報を event store 由来にする
4. 下部テロップを event store 由来にする
5. 全体ステータスを event store 由来にする
6. event 更新時に marker / panel / ticker が同時に更新される
```

### 対象外

以下は Phase 3-C では対象外。

```text
地図の自動ズーム・自動巡回
地域フォーカス遷移
鉄道路線 polyline 描画
潮位 alert 判定の新規実装
新しい外部API追加
音声読み上げ
OBS 配信設定
通常 /live のUI改修
```

自動巡回や注目地域フォーカスは後続 Phase 4 以降で扱う。

---

## 推奨ファイル構成

既存構成を確認し、命名は既存に合わせること。

新規作成する場合の推奨例:

```text
frontend/js/live/stream/live-stream-event-store.js
frontend/js/live/stream/live-stream-panel-events.js
frontend/js/live/stream/live-stream-ticker-events.js
frontend/js/live/stream/live-stream-status.js
frontend/css/live/stream/live-stream-panels.css
frontend/css/live/stream/live-stream-ticker.css
```

既存で以下のようなファイルがある場合は、それを拡張する。

```text
live-stream.js
live-stream-main-map.js
live-stream-main-map-events.js
live-stream-data-source.js
live-stream.css
```

重要なのは、`/live/stream` 専用処理を `/live` 本体へ混ぜ込まないこと。

---

## 正規化 event 形式

Phase 3-B の正規化形式を継続し、必要なら panel / ticker 用フィールドを追加する。

基本形式:

```js
{
  id: "eq-20260703-1305-001",
  type: "earthquake", // earthquake | rain | kikikuru | railway | tide | water
  severity: "high",   // critical | high | medium | low | info
  lat: 38.2,
  lng: 142.1,
  title: "宮城県沖",
  subtitle: "M6.4 / 最大震度4",
  timeLabel: "13:05",
  updatedAt: "2026-07-03T13:05:00+09:00",
  source: "jma",
  rank: 1
}
```

Phase 3-C で追加してよい任意項目:

```js
{
  panelTitle: "地震: 宮城県沖",
  panelBody: "M6.4 / 最大震度4 / 13:05発表",
  tickerText: "【地震】宮城県沖 M6.4 最大震度4（13:05）",
  shortLabel: "M6.4",
  statusLabel: "警戒",
  stale: false
}
```

必須項目:

```text
id
type
severity
title
```

地図 marker に出す event は lat/lng 必須。

ただし、パネルやテロップでは座標なし event を扱ってよい場合がある。Phase 3-C では、混乱を避けるため原則として「地図に出る event とパネル/テロップの主な注目 event は同じもの」を優先する。

例外として、鉄道など代表座標が取れないが重要な情報がある場合は、パネルのみ表示してよい。その場合は地図非表示であることが分かるように実装・テストする。

---

## stream event store 仕様

### 目的

地図・パネル・テロップの状態を一元管理する。

### 推奨API例

実装形は既存に合わせてよいが、概念として以下を満たすこと。

```js
setEvents(events, meta)
getEvents()
getEventsByType(type)
getHeadlineEvents(limit)
getSummary()
subscribe(listener)
```

### summary 例

```js
{
  overallStatus: "alert", // critical | alert | watch | calm | unavailable
  total: 8,
  countsByType: {
    earthquake: 2,
    rain: 3,
    kikikuru: 1,
    railway: 2,
    tide: 0
  },
  countsBySeverity: {
    critical: 1,
    high: 3,
    medium: 4,
    low: 0,
    info: 0
  },
  headlineEvents: [...],
  updatedAt: "2026-07-03T13:05:00+09:00",
  dataState: "ok" // ok | partial | empty | stale | unavailable
}
```

### overallStatus 判定

簡易でよい。

```text
critical event あり → critical
high event あり → alert
medium event あり → watch
event なし & fetch ok → calm
fetch 失敗 & 有効cacheなし → unavailable
一部API失敗 → partial
```

既存に近いステータス表記がある場合は、それを優先してよい。

---

## event 並び順

地図・パネル・テロップで優先順が大きくズレないようにする。

推奨ソート:

```text
1. severity: critical > high > medium > low > info
2. rank が小さい順
3. updatedAt が新しい順
4. type 優先度: earthquake > kikikuru > rain > railway > tide > water
```

全国監視画面なので、全件表示ではなく「いま見るべきもの」を上位に出す。

---

## 中央メイン地図との同期

Phase 3-B で実装された event marker を、event store の内容から描画する。

要件:

```text
marker は event.id を data 属性などで保持する
marker の件数は store の地図表示対象 event と一致する
store 更新時に古い marker が残らない
同一 id の marker が重複しない
地図操作不可は維持する
```

推奨 DOM 属性:

```html
<div class="stream-map-event stream-map-event--earthquake" data-event-id="eq-001"></div>
```

### highlight 同期

MVPでは必須ではないが、可能なら下部テロップやパネルの先頭 event と地図 marker を同期して強調する。

例:

```text
headlineEvents[0] の event.id を activeEventId とする
該当 marker に .stream-map-event--active を付与
該当 panel row に .is-active を付与
```

自動巡回まではやらなくてよい。

---

## 左右パネル同期

既存の `/live/stream` レイアウトを維持し、左右パネルの中身だけを event store 由来にする。

### 表示方針

```text
表示件数は絞る
重要なものから順に出す
通常雨や平常鉄道などは出さない
データなしと取得失敗を混同しない
```

### パネル構成例

既存UIに合わせてよいが、概念として以下を推奨する。

```text
左パネル:
  全国ステータス
  地震
  豪雨・キキクル

右パネル:
  鉄道影響
  潮位・沿岸監視
  データ更新状態
```

### 各カテゴリ表示上限

```text
地震: 最大3件
豪雨・キキクル: 最大3件
鉄道: 最大3件
潮位・水位: 最大2件、ただし Phase 3-C では alert event 未接続なら静穏表示でよい
```

### 空データ表示

fetch 成功かつ event なし:

```text
現在、注目情報はありません
全国監視中
```

fetch 失敗:

```text
情報取得待機中
一部データ取得不可
```

古い情報:

```text
更新確認中
情報が古い可能性があります
```

「取得失敗」を「平常」と断定しないこと。

---

## 下部テロップ同期

下部テロップは event store の headlineEvents から生成する。

### 要件

```text
通常アクセス時に demo 固定文言を出さない
event がある場合は event 由来の文言を流す
複数 event がある場合は重要度順に連結またはローテーション
空データ時は静穏メッセージ
取得失敗時は取得待機メッセージ
```

### テロップ文言例

地震:

```text
【地震】宮城県沖 M6.4 最大震度4（13:05）
```

豪雨・キキクル:

```text
【大雨】鹿児島県付近 非常に激しい雨 / キキクル警戒
```

鉄道:

```text
【鉄道】JR東日本 山手線 遅延情報あり
```

静穏:

```text
全国の地震・気象・交通情報を監視中です
```

取得失敗:

```text
一部データの取得を確認中です。画面は最新取得済み情報をもとに監視を継続しています
```

### 注意

配信向けなので過度に煽らない。

```text
未確認情報を断定しない
「危険」「壊滅」など過激な語を増やさない
データソースにない避難指示風の文言を作らない
```

---

## 全体ステータス同期

画面上部または既存のステータス表示がある場合、event store summary から更新する。

例:

```text
CRITICAL: 重大情報あり
ALERT: 警戒情報あり
WATCH: 監視中
CALM: 全国監視中
PARTIAL: 一部データ取得待機中
UNAVAILABLE: データ取得確認中
```

既存デザインの表記に合わせてよい。

重要なのは、地図・パネル・テロップとステータスが矛盾しないこと。

---

## demo / state=calm 仕様

### 通常

```text
/live/stream
  本番APIから取得
  event store に本番 event を格納
  地図・パネル・テロップを同期
```

### demo

```text
/live/stream?demo=1
  demo event を event store に格納
  地図・パネル・テロップを同期
  demo 固有の別描画ではなく、できるだけ同じ renderer を通す
```

### calm

```text
/live/stream?state=calm
  event list は空
  地図 marker なし
  パネルは静穏表示
  テロップは監視中メッセージ
```

`calm=1` を新設しない。既存仕様の `state=calm` を優先する。

---

## 更新周期と差し替え

Phase 3-B の更新周期を維持する。

推奨:

```text
初回表示時に即時取得
以後 60〜120秒間隔で更新
```

store 更新時の注意:

```text
古い marker / panel row / ticker item が残らない
同一 event が重複しない
DOM が増殖しない
setInterval が多重起動しない
更新中に一瞬 demo 表示へ戻らない
```

---

## エラー・データなし時の挙動

以下で画面が崩れないこと。

```text
API失敗
データ空
一部データだけ不正
座標なし
timeout
不正JSON
```

期待挙動:

```text
地図は表示継続
パネルは取得待機または静穏表示
テロップは取得待機または監視中表示
demo marker / demo ticker に fallback しない
JS error / unhandledrejection を出さない
```

取得失敗時に有効な直近取得データがある場合は、短時間だけ維持してよい。
その場合は stale / updating / partial などが分かる class や文言を付ける。

---

## CSS方針

既存デザインに合わせる。

追加 class 例:

```css
.stream-panel-event
.stream-panel-event--earthquake
.stream-panel-event--rain
.stream-panel-event--kikikuru
.stream-panel-event--railway
.stream-panel-event--tide
.stream-panel-event--critical
.stream-panel-event--high
.stream-panel-event--medium
.stream-panel-event--stale
.stream-panel-event.is-active
.stream-ticker-event
.stream-status--critical
.stream-status--alert
.stream-status--watch
.stream-status--calm
.stream-status--partial
.stream-status--unavailable
```

演出は控えめにする。

```text
配信で読める
チカチカしすぎない
下部テロップが主張しすぎない
地図を邪魔しない
```

`prefers-reduced-motion` も考慮できるとよい。

---

## テスト追加

最低限、以下の E2E を追加または更新する。

```text
e2e/live-stream-event-sync.spec.js
```

既存の `e2e/live-stream-main-map-real-data.spec.js` に追記してもよいが、同期観点は別 spec に分けることを推奨する。

### テスト観点

```text
1. 本番データ相当の mock response で、同一 event id が地図・パネル・テロップに反映される
2. 地震 event が marker / 地震パネル / テロップに表示される
3. 豪雨・キキクル event が marker / 豪雨パネル / テロップに表示される
4. 鉄道 event が marker / 鉄道パネル / テロップに表示される
5. store 更新時に古い marker / panel row / ticker text が残らない
6. 空データ時に marker なし、パネル静穏、テロップ監視中になる
7. API 500 / 不正JSON / timeout で画面破綻せず、demo に fallback しない
8. state=calm で marker なし、パネル静穏、テロップ監視中になる
9. demo=1 では demo event が地図・パネル・テロップに同じ pipeline で反映される
10. 地図操作不可が維持される
11. `/live` 通常画面に影響がない
```

Playwright では API を route mock して deterministic に検証してよい。

### 推奨 event id

テストしやすいように mock event へ明示的な id を持たせる。

```text
eq-sync-001
rain-sync-001
rail-sync-001
```

DOMにも可能なら `data-event-id` を出す。

---

## 完了条件

Phase 3-C の完了条件は以下。

```text
/live/stream の中央メイン地図・左右パネル・下部テロップが同じ event store 由来で同期される
通常アクセス時に demo 表示へ fallback しない
地図上の event とパネル/テロップの内容が矛盾しない
空データ/取得失敗でも画面が破綻しない
state=calm が既存仕様通り動く
地図操作不可が維持される
通常 /live に副作用がない
E2E が追加/更新され PASS
検証レポート作成可能な状態
```

## 注意

Phase 3-C は派手な新機能追加ではなく、監視卓としての整合性を作るフェーズ。

特に重要なのは以下。

```text
地図・パネル・テロップが同じ情報を見ていること
取得失敗を平常と誤表示しないこと
通常アクセスで demo に逃げないこと
/live 本体を壊さないこと
```

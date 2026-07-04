# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 3-B：メイン地図 本番データ連動 MVP

## 目的

OnHighGround2 内の `/live/stream` の中央メイン地図に、現在の demo alert / mock 表示ではなく、既存 `/live` 系APIで取得できる本番データを反映する。

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

Phase 3-B では、まず中央メイン地図だけを本番データ連動させる。

左右パネル、テロップ、自動巡回の高度化は後続フェーズでよい。

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

### 2. 既存APIを流用する

新しいスクレイピング、新しい外部API直叩きはしない。

まず既存 `/live` が使っている backend API / static runtime data / JS fetch 処理を調査し、流用できるものを使う。

想定対象:

```text
地震情報
キキクル・豪雨リスク情報
鉄道運行影響情報
潮位・水位情報
```

ただし Phase 3-B MVP では、全部を無理に入れなくてよい。

座標を安定して取れるものから表示する。

---

### 3. demo / mock は本番表示の代替にしない

Phase 3-A までの demo alert / mock marker は、検証用として残してよい。

ただし、通常アクセス時の `/live/stream` では本番データを優先する。

推奨:

```text
/live/stream
  本番データモード

/live/stream?demo=1
  デモ表示モード

/live/stream?calm=1
  静穏テストモード
```

既存で別の query param がある場合は、それに合わせてよい。

通常アクセス時に、本番データ取得失敗の代替として demo marker を表示してはいけない。

---

## 実装対象

### MVP対象

中央メイン地図に以下の代表イベントを表示する。

```text
1. 地震
2. 豪雨・キキクル代表地点
3. 鉄道運行影響
4. 潮位・水位異常または注目地点
```

ただし、Phase 3-B では座標が安全に取れるものだけ表示する。

座標が取れない、または代表点の信頼性が低いデータは、無理に地図へ出さない。

その場合は debug ログに留め、画面破綻させない。

---

## 推奨ファイル構成

既存構成を確認し、命名は既存に合わせること。

新規作成する場合の推奨例:

```text
frontend/js/live/stream/live-stream-data-source.js
frontend/js/live/stream/live-stream-map-events.js
frontend/js/live/stream/live-stream-main-map-events.js
frontend/css/live/stream/live-stream-map-events.css
```

既存で以下のようなファイルがある場合は、それを拡張する。

```text
live-stream.js
live-stream-main-map.js
live-stream-map.js
live-stream.css
```

重要なのは、`/live/stream` 専用処理を `/live` 本体へ混ぜ込まないこと。

---

## 実装ステップ

### Step 1. 既存API調査

まず `/live` 側のデータ取得処理を確認する。

確認対象例:

```text
frontend/js/live/
backend 側 live API
data_runtime/backend/
tasks/live/ 過去レポート
e2e/live 系テスト
```

以下を把握する。

```text
地震情報をどのAPIから取得しているか
豪雨・キキクル情報をどのAPIから取得しているか
鉄道情報をどのAPIから取得しているか
潮位・水位情報をどのAPIから取得しているか
それぞれ座標情報を含むか
既存JS側に正規化済みデータがあるか
既存 backend 側に stream でも使える summary API があるか
```

この段階では、既存APIのレスポンス形式を変更しない。

---

### Step 2. stream用の正規化レイヤーを作る

各APIのレスポンス形式を直接 Leaflet 描画に渡さない。

`/live/stream` 用に、以下のような共通イベント形式へ正規化する。

```js
{
  id: "eq-20260703-1305-001",
  type: "earthquake", // earthquake | rain | kikikuru | railway | tide | water
  severity: "high",   // critical | high | medium | low | info
  lat: 38.2,
  lng: 142.1,
  title: "宮古島北西沖",
  subtitle: "M6.4 / 最大震度3",
  timeLabel: "13:05",
  updatedAt: "2026-07-03T13:05:00+09:00",
  source: "jma",
  rank: 1
}
```

必須項目:

```text
id
type
severity
lat
lng
title
```

任意項目:

```text
subtitle
timeLabel
updatedAt
source
rank
```

座標が不正なものは除外する。

除外条件:

```text
lat/lng が null
lat/lng が数値でない
日本周辺として明らかに異常な座標
同一 id が重複
```

日本周辺の簡易判定例:

```text
lat: 20〜46
lng: 122〜154
```

厳密でなくてよいが、明らかな異常座標で地図が壊れないようにする。

---

### Step 3. 地震イベント表示

既存 `/live` の地震情報から、震源座標を持つイベントを表示する。

MVP条件:

```text
直近数件のみ
M5以上、または最大震度3以上を優先
最大5件程度
震源位置にパルスマーカー
クリック操作なし
ポップアップ不要
```

表示イメージ:

```text
赤〜橙系の発光点
強い地震ほど少し目立つ
地図上に短いラベルを出してもよい
```

ラベル例:

```text
M6.4
震度3
```

ただし、ラベルが地図を汚す場合はマーカーのみでよい。

---

### Step 4. 豪雨・キキクル代表イベント表示

既存 `/live` の豪雨ランキング、キキクル危険地域、または注目地域データから代表地点を表示する。

MVP条件:

```text
危険度が高いもののみ
最大5件程度
代表座標があるものだけ表示
通常雨は表示しない
```

対象例:

```text
キキクル 危険
キキクル 警戒
猛烈な雨
非常に激しい雨
```

表示イメージ:

```text
青〜紫系の発光点
キキクル危険はやや強調
```

注意:

市区町村名や地域名だけで座標がない場合、Phase 3-B では無理にジオコーディングしない。

既存データ内に代表点・中心点・bbox がある場合のみ使う。

---

### Step 5. 鉄道運行影響イベント表示

既存 `/live` の鉄道運行影響データから、障害路線の代表地点を表示する。

MVP条件:

```text
平常路線は表示しない
遅延・運転見合わせ・一部運休など影響ありのみ
最大5件程度
代表座標があるものだけ表示
路線形状描画は今回対象外
```

表示イメージ:

```text
緑〜黄系の小さめマーカー
影響度が高い場合は発光
```

注意:

Phase 3-B では、鉄道路線の polyline 描画はやらない。

路線全体の描画は後続フェーズで検討する。

---

### Step 6. 潮位・水位イベント表示

既存 `/live` に潮位・水位の注目地点または異常値ランキングがある場合のみ表示する。

MVP条件:

```text
地点座標がある
注目・警戒・異常傾向がある
最大3件程度
通常値の全地点表示はしない
```

表示イメージ:

```text
紫系の小さな発光点
```

座標や異常判定が安定していない場合は、Phase 3-B ではスキップしてよい。

---

## 更新周期

OBS配信画面なので、過剰な fetch は避ける。

推奨:

```text
初回表示時に即時取得
以後 60〜120秒間隔で更新
```

実装例:

```js
const REFRESH_INTERVAL_MS = 60 * 1000;
const FETCH_TIMEOUT_MS = 5000;
```

fetch は `AbortController` で timeout する。

複数API取得は `Promise.allSettled()` を使い、一部失敗しても画面全体を壊さない。

setInterval の多重起動を避けること。

---

## エラー・データなし時の挙動

以下のケースで画面が崩れないこと。

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
既存マーカーは古すぎなければ維持してよい
完全に取得失敗した場合も JS error を出さない
demo marker へ勝手にフォールバックしない
```

表示上は静穏状態に寄せてよい。

```text
全国監視中
取得待機中
情報なし
```

などの表示が既存UIにある場合は利用する。

---

## stale 判定

古い情報を本番っぽく表示し続けるのは避ける。

MVPでは簡易でよい。

```text
地震: 24時間超なら表示対象外
豪雨・キキクル: 3時間超なら表示対象外
鉄道: 24時間超なら表示対象外、または取得時刻不明なら表示してよいが stale class を付ける
潮位・水位: 6時間超なら表示対象外
```

既存 `/live` 側に stale 判定がある場合は、それを優先して流用する。

---

## 地図描画仕様

Leaflet 地図は Phase 3-A の仕様を維持する。

```text
日本全体表示
16:9 OBS想定
操作不可
ズームUIなし
ドラッグ不可
ホイールズーム不可
ダブルクリックズーム不可
キーボード操作不可
OSM attribution 表示
```

今回追加するのは、メイン地図上の本番データ由来イベントマーカーのみ。

---

## Marker CSS方針

既存デザインに合わせる。

推奨 class:

```css
.stream-map-event
.stream-map-event--earthquake
.stream-map-event--rain
.stream-map-event--kikikuru
.stream-map-event--railway
.stream-map-event--tide
.stream-map-event--critical
.stream-map-event--high
.stream-map-event--medium
.stream-map-event--stale
```

演出は控えめにする。

```text
配信で見える
でも地図を汚さない
常時チカチカしすぎない
```

`prefers-reduced-motion` も考慮できるとよい。

---

## 表示上限

地図上の表示件数には必ず上限を設ける。

推奨:

```text
地震: 最大5
豪雨・キキクル: 最大5
鉄道: 最大5
潮位・水位: 最大3

合計最大20程度
```

全国地図なので、情報を増やしすぎると一気に見づらくなる。

監視卓は「全部出す」より「異常を見せる」が正解。

---

## demo / calm モード

既存E2Eやスクリーンショット用に demo / calm モードは残してよい。

ただし通常アクセスでは本番データ取得を行う。

推奨挙動:

```text
/live/stream
  本番APIから取得

/live/stream?demo=1
  demo marker を表示

/live/stream?calm=1
  本番取得せず静穏状態を表示
```

既存の query param がある場合は、それを優先。

通常モードで本番APIが失敗しても demo marker を表示して成功扱いにしないこと。

---

## テスト追加

最低限、以下の E2E を追加または更新する。

```text
e2e/live-stream-main-map-real-data.spec.js
```

テスト観点:

```text
1. 本番データ相当の mock response で地震マーカーが表示される
2. 豪雨・キキクル代表マーカーが表示される
3. 鉄道影響マーカーが表示される
4. 座標なしデータは表示されない
5. 空データ時にマーカーが出ず、画面が壊れない
6. API 500時に JS error にならない
7. demo=1 のときだけ demo marker が出る
8. 通常アクセス時に demo marker へ勝手に fallback しない
9. 地図操作不可が維持される
10. `/live` 通常画面に影響がない
```

Playwright では API を route mock して deterministic に検証してよい。

---

## 完了条件

Phase 3-B の完了条件は以下。

```text
/live/stream の中央メイン地図に本番データ由来のイベントが表示される
demo marker が通常表示の代替になっていない
地震・豪雨/キキクル・鉄道のうち、座標取得可能なものが表示される
データなし/取得失敗でも画面が破綻しない
地図操作不可が維持される
通常 /live に副作用がない
E2E が追加/更新され PASS
検証レポート作成可能な状態
```

## 注意

Phase 3-B は派手な見た目追加より、堅牢性を優先すること。

特に重要なのは以下。

```text
データ取得に失敗しても配信画面が落ちない
通常表示で demo marker に逃げない
マーカーが更新のたびに増殖しない
/live 本体を壊さない
```

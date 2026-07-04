# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 3-D：全体ステータス・カテゴリバッジ・件数表示の同期 MVP

## 目的

`/live/stream` の Phase 3-C で、中央メイン地図 event、左右パネル、下部テロップが同じ event pipeline / event id で同期された。

Phase 3-D では、その上位にある **全体ステータス・上部カテゴリバッジ・各パネルの件数表示** を `LiveStreamEventStore` / 正規化 event pipeline と同期させる。

これにより、配信画面全体で以下の情報が矛盾しない状態にする。

```text
中央メイン地図 marker
左右パネルの対象表示
下部テロップ
上部カテゴリバッジ件数
全体ステータス表示
各パネル右上の対象数/状態表示
```

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

Phase 3-D は、見た目の大改修ではなく、**状態・件数・表示文言の同期** を主目的とする。

---

## 背景

Phase 3-C の検証では以下が PASS with notes となっている。

```text
地図 marker / パネル / テロップは同じ event pipeline で同期済み
state=calm は既存仕様通り動作
取得失敗時に demo fallback なし
通常 /live への副作用なし
```

一方で notes として以下が残っている。

```text
全体ステータスバッジは既存の calm/high 表記維持で EventStore.overallStatus には未接続
潮位 event は alert 判定未接続のため後続扱い
```

Phase 3-D では、主に前者を回収する。

潮位 event の alert 判定接続は今回の主対象ではない。既に EventStore に tide/water event が入ってくる場合のみ、件数同期の対象に含める。

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

### 2. `LiveStreamEventStore` を状態表示の単一参照元にする

Phase 3-C で導入/整理された `LiveStreamEventStore` を、Phase 3-D でも中心に置く。

対象:

```text
全体ステータス
カテゴリ別件数
カテゴリ別状態
パネル右上の対象件数
テロップの状態文
ヘッダーのカテゴリバッジ表示
```

各UIが個別に API response を再解釈して件数や状態を計算しないこと。

許容:

```text
既存 scene section から UI 表示用の補助情報を取る
既存パネルの表示順や focus index を維持する
```

ただし、件数・状態の最終判断は EventStore summary または EventStore の normalized events から導出すること。

---

### 3. 見た目の大改修をしない

既存の監視卓デザインを維持する。

今回やること:

```text
件数を同期する
ステータス文言を同期する
data 属性を付与する
既存 class/data-lv を EventStore summary に合わせて更新する
取得失敗時に calm と誤表示しない
```

今回やらないこと:

```text
大幅なレイアウト変更
新しい大型パネル追加
地図演出の追加
カテゴリ体系の全面刷新
潮位 alert 判定の新規実装
```

---

## 対象ファイル候補

既存構成を確認し、実ファイル名に合わせて対応すること。

想定対象:

```text
frontend/live/stream.html
frontend/css/live/live-stream.css
frontend/js/live-stream/live-stream-event-store.js
frontend/js/live-stream/live-stream-main.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-scene.js
frontend/js/live-stream/live-stream-map-events.js
frontend/js/live-stream/live-stream-earthquake-adapter.js
frontend/js/live-stream/live-stream-rain-adapter.js
frontend/js/live-stream/live-stream-railway-adapter.js
frontend/js/live-stream/live-stream-tide-adapter.js
```

新規ファイルが必要な場合の例:

```text
frontend/js/live-stream/live-stream-status-view.js
frontend/js/live-stream/live-stream-category-badges.js
```

ただし、既存 `live-stream-main.js` や `live-stream-panels.js` に小さく収められるなら新規ファイルは必須ではない。

---

## 実装対象

### 1. EventStore summary の整理

`LiveStreamEventStore` に既に `getSummary()` がある場合は、それを拡張または安定化する。

最低限、以下のような情報を返せるようにする。

```js
{
  total: 7,
  activeTotal: 7,
  overallStatus: "high", // calm | watch | high | critical | error など。既存語彙を優先
  hasError: false,
  hasPartialError: false,
  updatedAt: "2026-07-03T13:05:00+09:00",
  byType: {
    earthquake: { count: 2, status: "high" },
    rain: { count: 5, status: "high" },
    kikikuru: { count: 2, status: "high" },
    railway: { count: 4, status: "watch" },
    tide: { count: 0, status: "calm" },
    water: { count: 0, status: "calm" }
  }
}
```

実際の event type が以下のように分かれている場合は、既存に合わせてよい。

```text
earthquake
rain
kikikuru
railway
tide
water
```

ヘッダー表示上は、`rain` と `kikikuru` を「豪雨」カテゴリとして合算してよい。

```text
豪雨カテゴリ = rain + kikikuru
潮位カテゴリ = tide + water
```

---

### 2. overallStatus の判定

既存 CSS / E2E で使われている status vocabulary をまず確認すること。

既存が `calm` / `high` のみなら、まずはその語彙を壊さずに接続する。

推奨優先順位:

```text
critical event あり
  -> critical または既存語彙に合わせて high

high event あり
  -> high

medium/watch event あり
  -> watch または既存語彙に合わせて high/calm の中間表現がなければ high

取得失敗/一部失敗あり、かつ有効 event なし
  -> error / checking / watch のいずれか
     ※ 少なくとも通常の calm と同じ見え方・文言にしない

有効 event なし、取得成功
  -> calm

state=calm
  -> calm を強制
```

重要:

```text
API 失敗や timeout を「平常/対象なし」と誤表示しないこと
```

UI文言例:

```text
平常監視
監視中
注意監視
警戒監視
一部取得確認中
取得確認中
```

既存文言がある場合は、それを優先する。

---

### 3. 上部カテゴリバッジの同期

画面右上のカテゴリバッジを EventStore summary と同期する。

対象例:

```text
地震
豪雨
鉄道
潮位
LIVE
```

同期する内容:

```text
カテゴリ別件数
カテゴリ別状態
data-count
data-status または data-lv
aria-label / title などの補助情報
```

例:

```html
<div class="stream-category-badge" data-category="earthquake" data-count="2" data-status="high">
  地震 2
</div>
```

既存 class 名を壊さないこと。

必要なら data 属性のみ追加する。

件数ルール:

```text
地震: earthquake event 件数
豪雨: rain + kikikuru event 件数
鉄道: railway event 件数
潮位: tide + water event 件数
```

Phase 3-D では、潮位 event が EventStore に入ってこない場合は 0 でよい。

潮位パネルに通常観測地点が表示されていても、中央 event として扱われていないなら上部 badge count に含めない。

---

### 4. 全体ステータス表示の同期

上部または画面内にある全体 status 表示を `LiveStreamEventStore.getSummary().overallStatus` と同期する。

対象候補:

```text
.level[data-lv]
ヘッダー右側の状態表示
LIVE 近傍の状態表示
監視卓タイトル横の状態表示
```

既存の `data-lv="calm"` / `data-lv="high"` などがある場合、それを EventStore summary から更新する。

実装上の注意:

```text
既存 CSS が未対応の status 値を急に入れて表示崩れさせない
critical/watch/error を追加する場合は CSS と E2E も最小限対応する
不安がある場合は statusRaw と statusView を分ける
```

例:

```js
const statusRaw = summary.overallStatus; // critical / high / watch / calm / error
const statusView = mapStatusToExistingViewLevel(statusRaw); // high / calm など
```

---

### 5. パネル右上の対象数/状態表示の同期

各パネル右上に表示される件数・状態を EventStore summary と同期する。

対象例:

```text
地震情報: 対象 1/2, 監視中, 取得確認中
キキクル・豪雨情報: 対象 1/5, 発表なし, 一時的に取得不可
鉄道情報: 影響 4路線, 平常運転, 一時的に取得不可
潮位・水位: 地点 1・2/6, 8巡回
```

方針:

```text
event として対象があるカテゴリは EventStore 件数を表示
event がないが取得成功しているカテゴリは 0 / 発表なし / 平常監視
取得失敗しているカテゴリは 0 とだけ出さず、取得確認中/一時的に取得不可を出す
```

注意:

潮位パネルは通常観測表示があるため、Phase 3-D では以下の扱いでよい。

```text
潮位パネル内の station 表示件数は既存維持
上部カテゴリバッジの潮位件数は tide/water event 件数
混同しないように data 属性や文言で分ける
```

---

### 6. 下部テロップの状態文との整合

Phase 3-C で ticker は event pipeline 由来になっている。

Phase 3-D では、以下の状態とバッジ/パネルが矛盾しないようにする。

```text
有効 event あり
  -> event headline を流す

event なし、取得成功
  -> 全国監視中 / 現在大きな発表なし

一部取得失敗
  -> 一部データの取得を確認中

全取得失敗に近い状態
  -> データ取得を確認中 / 最新取得済み情報で監視継続

state=calm
  -> 監視中 / 現在対象なし
```

ticker が既に適切に動作している場合、無理に大きく変更しない。

ただし、header badge や panel status と明らかに矛盾する場合は修正する。

---

### 7. demo / calm / real mode の扱い

#### 通常

```text
/live/stream
```

本番API由来の normalized events から summary を作り、badge/panel/status/ticker を同期する。

#### calm

```text
/live/stream?state=calm
```

既存仕様通り `state=calm` を正とする。

期待:

```text
marker なし
pulse なし
カテゴリ件数 0
overallStatus calm
パネルは監視中/対象なし
テロップは監視中
```

#### demo

```text
/live/stream?demo=1
```

demo event も real event と同じ EventStore pipeline に入れる。

期待:

```text
map marker
panel
ticker
category badge
overall status
```

が同じ demo event summary に基づいて同期する。

---

## data 属性 / テスト容易性

E2Eで安定確認できるように、主要要素に data 属性を付与する。

既存属性がある場合はそれを優先する。

推奨:

```html
<body data-stream-status="high">

<div data-stream-overall-status="high"></div>

<div data-stream-category="earthquake" data-count="2" data-status="high"></div>
<div data-stream-category="rain" data-count="5" data-status="high"></div>
<div data-stream-category="railway" data-count="4" data-status="watch"></div>
<div data-stream-category="tide" data-count="0" data-status="calm"></div>

<section data-panel="earthquake" data-count="2" data-status="high"></section>
<section data-panel="rain" data-count="5" data-status="high"></section>
<section data-panel="railway" data-count="4" data-status="watch"></section>
<section data-panel="tide" data-count="0" data-status="calm"></section>
```

class 名より data 属性のほうが E2E に向いている。

ただし、既存HTMLを大きく壊さないこと。

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
panel は既存レイアウト維持
ticker は取得確認中などを表示
category badge は 0 件でも status を checking/error/watch などにできる
通常の calm と API 失敗を誤同一視しない
JS error を出さない
demo marker へ勝手にフォールバックしない
```

---

## stale / invalid event の扱い

Phase 3-B/3-C の event 正規化で除外されたものは、Phase 3-D の件数にも含めない。

件数に含める対象:

```text
EventStore に入った valid event
表示対象として採用された event
```

件数に含めない対象:

```text
stale 除外された event
不正座標で除外された event
severity 不足で除外された event
通常雨などの対象外 event
API response 上はあるが stream event 化されていない通常観測値
```

---

## 更新周期 / subscription

既存の EventStore subscription がある場合はそれを使う。

実装例:

```js
LiveStreamEventStore.subscribe((events, summary) => {
  renderHeaderStatus(summary);
  renderCategoryBadges(summary);
  renderPanelMeta(summary);
});
```

注意:

```text
setInterval を増やさない
fetch を増やさない
EventStore 更新のたびにDOMが増殖しない
リスナーを多重登録しない
```

---

## テスト追加

最低限、以下の E2E を追加または更新する。

```text
e2e/live-stream-status-sync.spec.js
```

テスト観点:

```text
1. 地震 event 2件で、地震バッジ count が 2 になる
2. rain + kikikuru event 合算で、豪雨バッジ count が正しくなる
3. railway event 4件で、鉄道バッジ count が 4 になる
4. tide/water event がない場合、潮位バッジ count は 0 のまま
5. 地図 marker 件数と上部カテゴリ件数が一致する
6. パネル右上の対象件数と EventStore summary が一致する
7. overallStatus が high event に応じて high になる
8. event なし + 取得成功では calm/監視中になる
9. API 失敗時に通常 calm と誤表示しない
10. demo=1 でも badge/status/panel/ticker が同期する
11. state=calm では badge count 0、overallStatus calm、marker 0 になる
12. stale/invalid event は badge count に含まれない
13. 通常 /live に副作用がない
```

Playwright route mock を使って deterministic に検証してよい。

---

## 完了条件

Phase 3-D の完了条件は以下。

```text
/live/stream の全体ステータスが EventStore summary と同期している
上部カテゴリバッジの件数が EventStore の有効 event 件数と同期している
地震・豪雨・鉄道・潮位カテゴリの count/status が矛盾しない
各パネル右上の対象数/状態が EventStore summary と矛盾しない
下部テロップの状態文と header/panel 状態が矛盾しない
API失敗時に通常 calm と誤表示しない
state=calm が既存仕様通り維持される
demo=1 も同じ pipeline で同期する
地図操作不可と attribution が維持される
通常 /live に副作用がない
関連E2Eが PASS
検証レポート作成可能な状態
```

---

## 注意

今回の主眼は「情報の整合性」。

派手な演出追加は不要。

特に重要:

```text
画面上の数字が嘘をつかない
取得失敗を平常と誤認させない
地図・パネル・テロップ・バッジが別々の世界線に行かない
/live 本体を壊さない
```

監視卓は、見た目より数字の信頼性が命。


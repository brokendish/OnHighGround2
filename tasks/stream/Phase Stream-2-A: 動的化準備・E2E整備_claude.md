# Claude用実装指示書

## `/live/stream` Phase Stream-2-A: 動的化準備・E2E整備

## 目的

`/live/stream` Phase Stream-1 で作成した配信用監視卓ビューについて、次フェーズ以降の実データ接続に備え、以下を整備する。

* `/live/stream` 専用E2Eを追加しやすいDOM構造にする
* `data-testid` を追加する
* 時計・地図内時刻・潮位カーブの現在時刻を整理する
* `renderTide()` の固定現在時刻 `19.42` を廃止する
* テスト用に時刻を固定できる仕組みを追加する
* `buildScene()` の差し替え口を明確化する
* 通常 `/live` と `/` への影響を出さない
* 実データ接続はまだ行わない

今回の Phase Stream-2-A は **動的化の準備フェーズ** であり、JMA / キキクル / ODPT / 潮位などの実API接続は対象外とする。

---

## 前提

Phase Stream-1 は以下の状態で PASS with notes。

* `/live/stream` 表示済み
* `?state=calm`
* `?state=alert`
* `?chrome=off`
* 1920×1080レイアウト
* 1366×768 / 1280×720 縮小確認
* 時計更新確認
* テロップ確認
* 小窓4種確認
* `/live` と `/` の回帰確認
* console/page error なし

Notes:

* `renderTide()` の現在時刻位置が固定値 `cur = 19.42`
* Google Fonts は外部参照
* dedicated E2E は未追加

今回対応する主対象は、`renderTide()` の固定時刻解消と dedicated E2E 整備である。

---

## 今回やること

## 1. `renderTide()` の固定時刻を廃止する

現在、潮位・水位小窓の現在時刻位置が固定値になっている。

```js
cur = 19.42
```

これを廃止し、現在時刻から算出する。

### 仕様

JSTの現在時刻から、以下の値を算出する。

```text
currentHourFloat = hour + minute / 60 + second / 3600
```

例:

```text
19:42:00 → 19.7
06:30:00 → 6.5
```

`renderTide()` は固定値を内部に持たず、外部から渡された `currentHourFloat` を使う。

### 方針

時計表示、地図内時刻、潮位カーブの現在位置は、同じ時刻ソースから取得する。

```text
LiveStreamClock
  ↓
now
  ↓
header clock
center map clock
tide current marker
```

毎秒フル再描画しない。
時計は毎秒更新、潮位カーブの現在位置は最低でも1分単位で更新できればよい。

---

## 2. テスト用の固定時刻パラメータを追加する

E2Eとスクリーンショットの安定化のため、URLパラメータで時刻を固定できるようにする。

### 追加パラメータ

```text
?demoNow=2026-06-30T19:42:00+09:00
```

URL上では `+` が空白扱いになる場合があるため、E2Eでは以下のようにエンコードする。

```text
?demoNow=2026-06-30T19:42:00%2B09:00
```

### 仕様

`demoNow` が指定された場合:

* ヘッダー時計は `demoNow` の時刻を表示
* 中央地図内時刻も `demoNow` を表示
* 潮位カーブの現在位置も `demoNow` を使用
* デモ時刻は固定とし、毎秒進めない
* E2Eスクリーンショットが安定することを優先する

`demoNow` が指定されない場合:

* 実時刻を使用
* ヘッダー時計は毎秒更新
* 中央地図内時刻も更新
* 潮位カーブの現在時刻位置も実時刻に追従する

---

## 3. 時計処理を整理する

`live-stream-clock.js` を中心に、時刻取得処理を一元化する。

### 推奨構造

```js
const LiveStreamClock = {
  getNow(),
  getCurrentHourFloat(),
  formatHeaderTime(),
  formatDateLine(),
  formatMapTime(),
  isFixedDemoTime()
};
```

既存構成に合わせて調整してよい。

### 要件

* JST表示を維持する
* `demoNow` 指定時は固定時刻
* `demoNow` なしでは実時刻
* 時計更新とシーン再描画を分離する
* 毎秒DOM全体を再描画しない

---

## 4. `data-testid` を追加する

Codex / Playwright E2E で安定して検証できるよう、主要要素に `data-testid` を追加する。

### 必須

```text
live-stream-stage
live-stream-header
live-stream-clock
live-stream-date
live-stream-status-bar
live-stream-center
live-stream-center-map
live-stream-center-time
live-stream-alert-level
live-stream-panel-earthquake
live-stream-panel-rain
live-stream-panel-rail
live-stream-panel-tide
live-stream-ticker
live-stream-ticker-body
```

### 可能なら追加

```text
live-stream-dev-chrome
live-stream-earthquake-list
live-stream-rain-list
live-stream-rail-list
live-stream-tide-station-list
live-stream-tide-current-marker
live-stream-tide-curve
live-stream-pulse-earthquake
live-stream-pulse-rain
live-stream-pulse-rail
live-stream-pulse-tide
```

特に `live-stream-tide-current-marker` は、`demoNow=06:00` と `demoNow=18:00` で位置が変わることを検証するために使う。

SVG要素の場合でも、`data-testid` を付ける。

---

## 5. `?chrome=off` の対象を明確化する

`?chrome=off` では、配信用画面に不要な開発UIを非表示にする。

### 非表示対象

```text
開発用状態表示
デバッグUI
テスト切替UI
Claude Design由来の開発パネル
```

### 表示対象

```text
ヘッダー
中央全国モニタ
小窓4種
下部テロップ
LIVE表示
時計
```

`chrome=off` で本体レイアウトが崩れないこと。

`data-testid="live-stream-dev-chrome"` を付け、E2Eで非表示確認できるようにする。

---

## 6. `buildScene()` の責務を整理する

実データ接続は行わないが、次フェーズで `/live` 正規化済みデータを接続できるよう、`buildScene()` の入口を明確にする。

### 方針

```js
function buildScene(rawLiveData, options) {
  // Phase Stream-2-A では dummy scene を返す
  // 将来 rawLiveData に /live の正規化済みデータを渡す
}
```

### 返却するViewModelの概念

```text
scene.mode
scene.clock
scene.earthquake
scene.rain
scene.rail
scene.tide
scene.ticker
scene.statusCounts
scene.alertLevel
```

まだ型定義は厳密でなくてよいが、コメントで責務を明記する。

### 禁止

* このフェーズで `/live` 実APIに接続しない
* backend APIを新規追加しない
* data_runtime構造を変更しない
* DBを追加しない

---

## 7. 画面更新処理を安定化する

今後の実データ接続に備え、更新処理の分離を確認する。

### 望ましい分離

```text
時計更新:
  1秒周期

シーン巡回:
  8秒周期

デモ状態切替:
  無指定時のみ 16秒 calm / 48秒 alert / 64秒ループ

潮位現在位置:
  実時刻時は1分単位または必要時更新
  demoNow指定時は固定
```

### 注意

* 毎秒すべての小窓を作り直さない
* 時計更新だけでアニメーションがリセットされない
* `state=calm` / `state=alert` 固定時に勝手に切り替わらない
* 無指定デモモードのみ calm / alert を巡回する

---

## 8. E2E用にHTML構造を壊さない

E2E追加はCodex側で実施してもよいが、Claude側ではE2Eを書きやすいHTML構造を用意する。

### 重要

* 主要領域は `data-testid` で取得できる
* 状態文言は極端に変えない
* `state=calm` では「現在、表示対象なし」相当が残る
* `state=alert` では地震・豪雨・鉄道・潮位の各警戒表示が存在する
* `chrome=off` でも主要領域の `data-testid` は残る

---

## 今回やらないこと

Phase Stream-2-A では以下をやらない。

```text
/live 実データ接続
JMA API接続
キキクル実タイル連携
ODPT実データ連携
潮位実データ連携
JARTIC交通量表示
Leaflet / MapLibre への地図差し替え
YouTube API連携
音声読み上げ
DB追加
履歴保存
フォントセルフホスト化
通常 /live の大規模改修
```

Google Fontsのセルフホスト化は将来課題として残してよい。

---

## 受け入れ条件

以下を満たすこと。

```text
/live/stream が表示できる
/live/stream?state=calm&chrome=off が表示できる
/live/stream?state=alert&chrome=off が表示できる
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00 が表示できる
demoNow指定時に時計が固定される
demoNow未指定時に時計が毎秒更新される
renderTide() の固定値 19.42 が消えている
潮位現在位置が現在時刻から計算される
data-testid が主要領域に追加されている
chrome=off で開発UIが非表示になる
state=calm / state=alert の挙動がPhase Stream-1から壊れていない
console error がない
通常 /live に影響がない
通常 / に影響がない
```

---

## 実装後の報告

実装後、以下を報告する。

```text
追加ファイル
変更ファイル
renderTide() 固定時刻の修正内容
demoNow の仕様
追加した data-testid 一覧
E2E追加に向けた補足
未対応項目
Phase Stream-2-B で実施すべき項目
```

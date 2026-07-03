# Claude用実装指示書

## `/live/stream` Stream Phase 2-D: モック残存除去・実データ整合性修正

## 目的

`/live/stream` は Phase 2-C までで、地震・キキクル/豪雨・潮位・鉄道・下部テロップの実データ接続が完了している。

一方で、実画面確認により、モック/デモ状態の残存や、実データとの整合性に疑いのある表示が見えてきた。

次工程へ進む前に、以下を修正し、`/live/stream` を本番運用に近い状態へ整理する。

---

## 対象の問題

確認された問題は以下。

```text
1. 画面左上の「平穏時」「警戒時」「自動デモ」が本番用として不要
2. 潮位グラフの現在地縦線が右端に寄って表示される
3. 潮位グラフのカーブが OnHighGround2 本体の潮位カーブと異なるように見える
4. 現在潮位 cm が OnHighGround2 本体の値と異なるように見える
5. 子画面の巡回で同じ情報を繰り返し表示することがある
   例: 福島県会津市 → 福島県会津市 → 福島県会津市
6. 警戒/危険情報があるのに「現在、表示対象なし」が表示されることがある
7. モック状態・デモ状態がどこかに残っており、実データ表示へ混入している可能性がある
```

---

## 基本方針

今回の対応は新機能追加ではない。

目的は以下。

```text
本番用 /live/stream からモックUIを排除する
実データ表示とデモ表示の境界を明確にする
潮位表示を OnHighGround2 本体側の潮位ロジックと整合させる
巡回対象の重複を排除する
情報あり/なし判定の矛盾を解消する
既存E2Eを壊さない
```

---

## 1. 左上のモック操作UIを本番画面から削除する

### 現状

画面左上に以下のような開発/モック用UIが残っている。

```text
平穏時
警戒時
自動デモ
```

これは本番用 `/live/stream` では不要。

### 対応方針

本番画面から削除する。

```text
/live/stream
/live/stream?chrome=off
```

では表示しない。

### ただし

E2Eやデモ確認用のURLパラメータは残してよい。

```text
?state=calm
?state=alert
?demo=1
?demoNow=...
```

つまり、

```text
画面上の切替UIは削除
URLパラメータによるテスト/デモ制御は維持
```

とする。

### 注意

`?chrome=off` の有無に関係なく、通常の `/live/stream` ではモック操作UIを出さない。

開発時だけ必要な場合は、明示的なパラメータにする。

例:

```text
?devControls=1
```

ただし、今回のMVPでは `devControls=1` の新設は必須ではない。
削除または完全非表示でよい。

---

## 2. demo / mock / real の境界を明確化する

現在、モック状態が実データ表示に混入している可能性がある。

以下の状態を明確に分離する。

```text
real mode:
  通常の /live/stream
  実データを使う

demo mode:
  ?demo=1
  固定デモデータを使う

forced calm:
  ?state=calm
  強制的に平穏表示

forced alert:
  ?state=alert
  alert状態を強制
  ただし demo=1 がない場合は実データ優先
```

### 優先順位

表示モード判定は以下の順に整理する。

```text
1. state=calm
   → 強制平穏表示

2. demo=1
   → 固定デモデータ表示

3. 通常
   → 実データ表示

4. 実データ取得失敗
   → 取得不可表示
```

### 禁止

通常の `/live/stream` で、固定デモデータが混入しないこと。

---

## 3. 潮位グラフを OnHighGround2 本体の潮位ロジックへ寄せる

### 現状

以下の疑いがある。

```text
潮位グラフのカーブが OnHighGround2 本体と異なる
現在潮位 cm が OnHighGround2 本体と異なる
現在時刻縦線が右端に寄る
```

### 対応方針

`/live/stream` で独自の潮位カーブ生成や独自補間を持っている場合は、可能な限り OnHighGround2 本体側の潮位表示ロジックに揃える。

確認対象:

```text
OnHighGround2 本体の潮位API
/live 側の潮位API
潮位カーブ生成関数
現在潮位算出関数
満潮/干潮算出ロジック
demoNow適用方法
JST時刻処理
```

### 望ましい状態

```text
同じ地点
同じ時刻
同じAPIレスポンス
```

で比較した場合、

```text
OnHighGround2 本体の現在潮位
/live/stream の現在潮位
```

が一致、または丸め誤差程度に収まる。

### 潮位カーブ

`/live/stream` で簡易正弦波や仮カーブを使っている場合は廃止する。

```text
実データ hourly / timeline / curve points
  ↓
OnHighGround2 本体と同じ、または同等の変換
  ↓
SVG path
```

とする。

### 現在時刻縦線

現在時刻縦線は、グラフの横軸定義に基づいて配置する。

想定:

```text
24時間表示なら:
  x = (currentHourFloat / 24) * chartWidth
```

ただし、OnHighGround2 本体が「現在時刻の前後○時間」形式の場合は、その仕様に合わせる。

### 注意点

以下のズレに注意する。

```text
UTC/JSTの取り違え
日付跨ぎ
demoNow と実時刻の混在
hour 0-23 と index 0-24 のズレ
グラフ幅にpaddingを含める/含めないの違い
丸め処理
```

---

## 4. 潮位現在時刻縦線の右端寄りを修正する

### 現象

潮位グラフの現在地縦線が右側に寄って表示される。

### 調査観点

```text
currentHourFloat が 24 に近い値になっていないか
JST変換が二重適用されていないか
Date parsing で timezone が落ちていないか
demoNow が未指定時にUTCとして扱われていないか
chart x scale が 0-24 なのか 0-23 なのか
SVG viewBox と描画領域の padding 計算が一致しているか
```

### 期待

```text
現在時刻が 12:00 なら中央付近
06:00 なら左から1/4付近
18:00 なら左から3/4付近
```

となる。

E2Eで `demoNow=06:00`, `12:00`, `18:00` を確認できるようにする。

---

## 5. 子画面の巡回重複を排除する

### 現象

同じ対象が連続して表示されることがある。

例:

```text
福島県会津市
→ 福島県会津市
→ 福島県会津市
```

### 原因候補

```text
targets 配列に同一地域が重複している
ID生成が毎回変わって重複排除できていない
カテゴリ違いの同一地域を別対象として扱っている
巡回index計算が対象数と合っていない
filter後に同一対象だけが残っているのに巡回表示している
```

### 対応方針

各カテゴリの `targets` 生成時に重複排除する。

最低限、以下のキーで dedupe する。

```text
地震:
  eventId
  ない場合は occurredAt + hypocenter + magnitude

キキクル/豪雨:
  areaName + level + category
  または normalizedAreaCode があればそれを優先

鉄道:
  railwayId
  ない場合は operator + lineName + status

潮位:
  stationId
  ない場合は stationName
```

### 巡回ルール

```text
targets.length === 0:
  対象なし表示

targets.length === 1:
  1件を固定表示
  巡回インジケータは出さない、または 1/1

targets.length >= 2:
  8秒ごとに次の対象へ切り替える
  同じIDを連続表示しない
```

---

## 6. 情報ありなのに「現在、表示対象なし」になる問題を修正する

### 現象

警戒/危険情報があるのに、中央または小窓に

```text
現在、表示対象なし
```

が表示されることがある。

### 調査観点

```text
statusCount と targets.length がズレていないか
activeTarget が null のままになっていないか
targets はあるが座標なしで除外されていないか
小窓にはリストがあるが mapTarget がないため対象なし扱いになっていないか
centerMap の allClear 判定が一部カテゴリしか見ていないか
demo/calm 判定が real data より優先されていないか
```

### 期待

警戒/危険情報がある場合:

```text
中央:
  現在、表示対象なし を出さない

該当小窓:
  activeTarget を表示する

座標がない場合:
  地図パルスは出せなくても、リスト/カードは表示する
  「対象なし」ではなく「位置情報なし」またはカード表示のみ
```

### 中央の all clear 判定

中央地図の「現在、表示対象なし」は、以下すべてが0の場合のみ表示する。

```text
earthquake active targets = 0
rain/kikikuru active targets = 0
rail affected lines = 0
tide alert targets = 0
```

ただし、潮位は通常代表表示を持つため、平常潮位だけでは中央の all clear を解除しない。

---

## 7. 既存E2Eを維持しつつ追加テストする

既存E2Eは壊さない。

既存:

```text
live-stream.spec.js
eq-mock-verify.spec.js
rain-mock-verify.spec.js
tide-mock-verify.spec.js
rail-mock-verify.spec.js
```

必要に応じて以下を追加する。

```text
live-stream-production-cleanup.spec.js
```

または既存 `live-stream.spec.js` に追加してもよい。

---

## 8. 今回やらないこと

```text
新しい災害カテゴリ追加
OBS配信設定
YouTube連携
音声読み上げ
JARTIC表示
中央地図の本物地図化
潮位の新規警戒判定
河川水位の新規取得
```

今回は **修正・整合性確認フェーズ** とする。

---

## 受け入れ条件

以下を満たすこと。

```text
通常 /live/stream から「平穏時」「警戒時」「自動デモ」の画面UIが消えている
?state / ?demo / ?demoNow によるE2E制御は維持される
通常表示でデモデータが混入しない
潮位現在潮位が OnHighGround2 本体または /live の潮位値と整合する
潮位カーブが実データ由来で OnHighGround2 本体と同等になる
潮位現在時刻縦線が demoNow=06/12/18 で妥当な位置に出る
子画面巡回で同じ対象が連続重複表示されない
警戒/危険情報がある場合に「現在、表示対象なし」が出ない
取得失敗時に「なし」「平常」と断定しない
undefined / null / NaN が画面に出ない
既存E2EがPASSする
/live が壊れない
/ が壊れない
```

---

## 実装後の報告

以下を報告する。

```text
変更ファイル
削除/非表示にしたモックUI
demo/real/calm の判定整理内容
潮位カーブ・現在潮位の修正内容
潮位現在時刻縦線の修正内容
巡回重複排除ロジック
「現在、表示対象なし」判定の修正内容
追加/更新したE2E
未対応項目
```

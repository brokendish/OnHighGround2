# Claude用実装指示書

## `/live/stream` Phase Stream-1: 災害監視Live配信画面 MVP 実装

## 目的

OnHighGround2 に、通常の `/live` とは別ページとして **`/live/stream`** を追加する。

`/live/stream` は OBS / YouTube 配信用の「見るだけ」の監視卓画面であり、ユーザー操作を前提にしない。
まずは Claude Design が作成した `design_handoff_live_stream/` を基準に、OnHighGround2 の既存フロントエンド構成内でデザインを再現する。

今回の Phase Stream-1 では、実データ接続は必須ではない。
まずは以下を達成する。

* `/live/stream` が表示できる
* 1920×1080 固定レイアウトが再現される
* OBSブラウザソースで使える
* `?state=calm`
* `?state=alert`
* `?chrome=off`
* デモ表示
* 小窓4種
* 中央全国モニタ
* ヘッダー時計
* 下部速報テロップ
* 色ルール
* 巡回・ズームアニメーションの土台

## 参照資料

以下を実装リファレンスとして使用する。

```text
design_handoff_live_stream/
  README.md
  index.html
```

重要事項:

* `index.html` はデザインリファレンスであり、そのまま本番投入するコードではない
* OnHighGround2 の既存構成・命名・読み込み方式に合わせて再現する
* 簡略SVG地図は仮であり、将来的には既存 `/live` の地図基盤に置き換える
* Phase Stream-1 では、簡略SVG地図のままでもよい
* `/live` 本体の既存挙動を壊さないことを最優先にする

---

## 実装対象

新規ページ:

```text
/live/stream
```

想定ファイル構成例:

```text
frontend/
  live-stream.html

frontend/css/live/
  live-stream.css

frontend/js/live-stream/
  live-stream-main.js
  live-stream-scene.js
  live-stream-clock.js
  live-stream-ticker.js
  live-stream-panels.js
  live-stream-map.js
```

既存のプロジェクト構成に合わせて調整してよい。
ただし、通常 `/live` のファイルへ大きな改修を入れないこと。

---

## 基本設計方針

`/live/stream` は `/live` とは別ビューとして実装する。

```text
/live
  通常操作用の全国災害ビューア

/live/stream
  OBS/YouTube配信用の監視卓ビュー
```

ただし、将来的には `/live` の既存データ・正規化済み情報を加工して表示する。

Phase Stream-1 では、以下の構造を先に作る。

```text
dummy SCENES
  ↓
buildScene()
  ↓
render(scene)
  ↓
/live/stream 表示
```

将来フェーズで、`dummy SCENES` を `/live` の実データへ差し替える。

---

## 今回やること

### 1. `/live/stream` ページ追加

* `GET /live/stream` で画面を表示できるようにする
* 既存 frontend のルーティング方式に合わせる
* Docker / 開発環境で `http://127.0.0.1:8080/live/stream` 相当で確認できること
* 通常 `/live` は既存通り表示されること

---

### 2. 1920×1080 固定ステージ

Claude Design の指定を再現する。

基本サイズ:

```text
stage: 1920 × 1080
header: 1920 × 72
ticker: 1920 × 46
body: 1920 × 962
left column: 476
center column: 900
right column: 476
gap: 14
body padding: 16px 20px
small window height: 458
```

ブラウザサイズに応じて、`.stage` を以下の考え方で縮小フィットさせる。

```text
scale(min(vw / 1920, vh / 1080))
```

OBS の 1920×1080 では scale=1 となる想定。

---

### 3. ヘッダー実装

ヘッダーには以下を表示する。

左:

```text
全国災害監視ライブ
NATIONAL HAZARD WATCH · 監視卓
```

中央:

```text
HH:MM:SS
YYYY.MM.DD TUE · JST
```

右:

```text
地震 件数
豪雨 件数
鉄道 件数
潮位 件数
LIVE
```

時計は毎秒更新する。
Phase Stream-1 では実時刻でよい。

---

### 4. 中央全国モニタ

中央に全国モニタを表示する。

Phase Stream-1 では、design_handoff の簡略SVG地図を使用してよい。
ただし、将来的に Leaflet / MapLibre / 既存 `/live` 地図へ差し替えられるよう、地図描画処理を独立させる。

表示要素:

* 全国地図
* グリッド
* カテゴリ別パルスマーカー
* 左上タイトル
* 右上警戒レベルピル
* 左下時刻
* 右下凡例
* 平穏時の中央オーバーレイ

平穏時オーバーレイ:

```text
現在、表示対象なし
ALL CLEAR · 全国の警戒情報を監視中
```

---

### 5. 小窓4種

以下4つの小窓を実装する。

左上:

```text
地震情報
```

左下:

```text
キキクル・豪雨情報
```

右上:

```text
鉄道情報
```

右下:

```text
潮位・水位
```

各小窓はカテゴリ色の枠線を持つ。
小窓枠線色と中央地図パルス色を一致させる。

---

## 色ルール

Claude Design README の Design Tokens を優先する。

最低限、以下をCSS変数として定義する。

```css
--c-eq: #ff4d3d;
--c-eq-2: #ff9a3c;
--c-eq-3: #ffc266;

--c-rain: #2f7bff;
--c-rain-2: #34d6ff;

--c-rail: #2bd576;

--c-tide: #c64be0;
--c-tide-2: #d24be0;

--c-alert: #ff2d2d;
--c-safe: #2bd576;

--bg-0: #070a11;
--bg-1: #0b1019;
--bg-hdr: #0a0f19;

--ink: #e8edf5;
--ink-2: #c5cedd;
--ink-3: #8b97a9;
--ink-4: #6b7686;
```

カテゴリ対応:

```text
地震: 赤〜オレンジ
キキクル・豪雨: 青〜水色
鉄道: 緑
潮位・水位: 紫〜マゼンタ
```

---

## フォント

Claude Design の指定:

```text
和文: Zen Kaku Gothic New
数値・英字・時刻: Share Tech Mono
```

Phase Stream-1 では Google Fonts 読み込みでよい。
将来的には配信安定性のためセルフホスト化を検討する。

---

## URLパラメータ

以下を実装する。

### `?state=calm`

平穏時固定表示。

* 中央全国モニタに「現在、表示対象なし」
* 地震小窓は対象なし
* キキクル小窓は対象なし
* 鉄道小窓は影響路線なし
* 潮位は平常表示

### `?state=alert`

警戒時固定表示。

* ダミーの地震情報を表示
* ダミーのキキクル・豪雨情報を表示
* ダミーの鉄道影響を表示
* ダミーの潮位・水位情報を表示
* 8秒巡回を行う

### 無指定

デモモード。

* 16秒 平穏
* 48秒 警戒
* 64秒ループ

### `?chrome=off`

開発用UIを非表示にする。
OBS配信時はこのモードを使う。

---

## 地震小窓

### 表示内容

左パネル:

```text
過去12時間の履歴
時刻
地点
M
震度チップ
```

右地図:

* 現在選択中の地震イベントのみ表示
* 履歴の全地点を地図上に出さない
* 対象が複数ある場合は8秒ごとに巡回
* 対象切替時にズームアップアニメーション
* ポップアップ表示

平穏時:

```text
現在 対象なし
全国を監視中
```

---

## キキクル・豪雨小窓

### 表示内容

左パネル:

```text
警報・注意報リスト
地域
レベルバッジ
```

右地図:

* 対象地域の雨域を表示
* 雨域はぼかし円または簡略SVGでよい
* 対象が複数ある場合は8秒ごとに巡回
* 対象切替時にズームアップアニメーション
* ポップアップ表示

平穏時:

```text
現在 対象なし
全国を監視中
```

---

## 鉄道小窓

鉄道はごちゃつきやすいため、配信用に簡略化する。

### 方針

* 影響のある路線のみ太く表示
* 地図上ポップアップは出さない
* 左パネルに路線色付きカードを並べる
* 平常路線は細く・暗く表示
* 駅名は原則表示しない

左パネル:

```text
路線名
状態
区間/理由
路線色バー
```

右地図:

```text
影響あり路線: 太線・路線色
平常路線: 細線・低透明度
```

平穏時:

```text
影響路線なし
平常運転
```

---

## 潮位・水位小窓

### 表示内容

* 2拠点を上下に同時表示
* 8秒ごとに次の2拠点へ巡回
* 各セルに現在潮位、満潮、干潮、偏差、24時間潮位カーブを表示
* 高潮警戒の拠点はマゼンタ系で強調

Phase Stream-1 では、design_handoff のダミーデータと正弦近似SVGカーブを使用してよい。

---

## テロップ

下部に速報テロップを実装する。

構成:

```text
速報タグ
marquee本文
```

表示例:

```text
【地震】19:21 岩手県沖 M6.1 最大震度5弱 ／
【大雨】静岡県中部にキキクル「危険」 ／
【鉄道】中央線快速 三鷹〜東京で運転見合わせ ／
【潮位】東京 満潮 05:00 189cm
```

動作:

```text
marquee 34s ループ
```

---

## アニメーション

Claude Design の指定を再現する。

### ズームアップ

対象:

```text
地震小窓
キキクル・豪雨小窓
```

仕様:

```text
duration: 900ms
easing: easeOutCubic
```

easeOutCubic:

```js
1 - Math.pow(1 - x, 3)
```

対象切替時:

```text
全国ビュー
↓
対象地域へズームアップ
```

ポップアップ:

```text
popIn 0.5s
delay 0.4s
```

### 巡回

```text
8秒サイクル
```

対象:

```text
地震
キキクル・豪雨
潮位・水位
```

### 点滅

```text
LIVE: blink 1.4s
警戒レベルドット: blink 1.4s
パルスマーカー: ring/core 2.4s
巡回インジケータ: cyc 8s
```

---

## 状態管理

`render(scene, tick)` のような形に寄せる。

Phase Stream-1 では、以下の考え方でよい。

```text
mode:
  calm
  alert
  demo

tick:
  経過秒

scene:
  表示用ビューモデル

lastSig:
  mode / state / 8秒サイクルが変わった時のみ再描画

clock:
  毎秒更新
```

毎秒フル再描画しない。
時計更新とシーン再描画を分離する。

---

## buildScene() の将来差し替え口

今回の実装では、以下のような関数を用意する。

```js
function buildScene(rawLiveData) {
  // Phase Stream-1では dummy SCENES を返す
  // 将来 /live の正規化済みデータから stream 用 view model を作る
}
```

将来的に `/live` データから以下のビューモデルへ変換する。

```text
earthquake:
  targets
  history

rain:
  targets
  alerts

rail:
  affected

tide:
  stations
```

この差し替え口を作っておくことで、将来 `/live` の変更を `/live/stream` に反映しやすくする。

---

## 今回やらないこと

Phase Stream-1 では以下はやらない。

```text
/live 本体の大規模リファクタ
実データAPI接続
既存 /live 地図基盤への完全置き換え
JARTIC交通量表示
YouTube API連携
音声読み上げ
DB追加
履歴保存
管理画面追加
スマホ専用レイアウト
```

特に `/live` 本体の改修は最小限にする。

---

## 受け入れ条件

以下を満たすこと。

```text
/live/stream が表示できる
/live は既存通り表示できる
?state=calm が動作する
?state=alert が動作する
?chrome=off が動作する
無指定時にデモモードが動作する
1920×1080でレイアウトが崩れない
ヘッダー時計が毎秒更新される
下部テロップが表示される
小窓4種が表示される
小窓の枠線色がカテゴリ色と一致する
中央地図のパルス色がカテゴリ色と一致する
鉄道小窓に地図上ポップアップが出ない
console error がない
通常 /live に影響がない
```

---

## 実装後に残すメモ

実装後、以下を簡単に報告する。

```text
追加ファイル
変更ファイル
/live/stream の確認URL
未実装項目
Phase Stream-2で実施すべき項目
```

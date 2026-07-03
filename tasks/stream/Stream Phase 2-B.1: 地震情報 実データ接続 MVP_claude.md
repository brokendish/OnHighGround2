# Claude用実装指示書

## `/live/stream` Stream Phase 2-B.1: 地震情報 実データ接続 MVP

## 目的

`/live/stream` の地震情報だけを、既存 `/live` の地震データへ接続する。

Phase Stream-2-A までで整備した以下の土台を維持する。

* `/live/stream` 専用ページ
* `state=calm`
* `state=alert`
* `chrome=off`
* `demoNow`
* 1920×1080 固定レイアウト
* dedicated E2E
* `data-testid`
* `buildScene()` 差し替え口

今回の目的は、`/live/stream` の **地震小窓・中央地図の地震パルス・地震系ステータス** を、実データ由来で表示できるようにすること。

---

## 重要方針

`/live/stream` は通常 `/live` とは別ビューだが、データは `/live` の既存資源を利用する。

今回やること:

```text
既存 /live の地震データ取得・正規化済みデータ
  ↓
stream用 earthquake adapter
  ↓
buildScene()
  ↓
地震小窓 / 中央地図パルス / 地震ステータスへ反映
```

今回やらないこと:

```text
新規backend API追加
JMA等への新規直接アクセス
/live 本体の大規模改修
キキクル実データ接続
鉄道実データ接続
潮位実データ接続
テロップ全面動的化
Leaflet / MapLibre 地図差し替え
DB追加
履歴保存方式変更
```

---

## 実装対象

主な対象候補:

```text
frontend/js/live-stream/live-stream-scene.js
frontend/js/live-stream/live-stream-main.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-map.js
frontend/js/live-stream/live-stream-clock.js
frontend/live/stream.html
e2e/live-stream.spec.js
```

既存 `/live` 側の地震データ取得処理・API・正規化ロジックを調査し、必要最小限の共有利用に留める。

既存 `/live` の挙動を変えないこと。

---

## 1. 既存 `/live` 地震データ取得口の調査

まず、現在 `/live` が地震情報をどこから取得しているかを確認する。

調査対象例:

```text
frontend/js/live/
backendの /api/live/* 系
地震リストAPI
震度マーカーAPI
M5以上地震リスト
津波警報中の地震リスト展開処理
```

確認すること:

```text
取得URL
レスポンス形式
地震イベントID相当の項目
発生時刻
震源名
マグニチュード
最大震度
緯度経度
震度観測点または市区町村震度
更新時刻
津波有無
```

既存 `/live` がすでに正規化済みのJSONを受け取っている場合は、それを優先的に使う。

---

## 2. stream用 earthquake adapter を作る

`/live/stream` 側で、実データを直接DOMへ流し込まない。
必ず stream 用 ViewModel に変換する。

新規または既存ファイル内に以下のような責務を作る。

```js
function buildEarthquakeStreamModel(rawEarthquakeData, options) {
  // /live 由来の地震データを /live/stream 用に整形する
}
```

返却イメージ:

```js
{
  hasActiveEarthquake: true,
  activeTarget: {
    id: "eq-202606301921",
    time: "19:21",
    occurredAt: "2026-06-30T19:21:00+09:00",
    hypocenter: "岩手県沖",
    magnitude: "6.1",
    maxIntensity: "5弱",
    lat: 39.8,
    lon: 142.1,
    depth: "40km",
    tsunami: "調査中",
    summary: "岩手県沖 M6.1 最大震度5弱"
  },
  targets: [
    {
      id: "eq-202606301921",
      time: "19:21",
      hypocenter: "岩手県沖",
      magnitude: "6.1",
      maxIntensity: "5弱",
      lat: 39.8,
      lon: 142.1
    }
  ],
  history: [
    {
      id: "eq-202606301921",
      time: "19:21",
      hypocenter: "岩手県沖",
      magnitude: "6.1",
      maxIntensity: "5弱"
    }
  ],
  statusCount: 1
}
```

---

## 3. 表示対象の地震ルール

`/live/stream` は配信用画面なので、地図上へ全部を出さない。

### 地震小窓の右側地図

表示するのは **現在選択中の地震イベントのみ**。

```text
現在注目地震1件
震源または代表位置
最大震度情報
ポップアップ
```

履歴全件を右地図上には出さない。

### 地震小窓の左側リスト

過去12時間の地震履歴を表示する。

表示項目:

```text
時刻
震源名
M
最大震度
```

件数が多い場合は上位または直近から最大5〜8件程度に制限する。

### 中央地図

地震カテゴリの赤〜オレンジ系パルスを、現在注目中の地震位置へ表示する。

中央地図に全履歴を大量表示しない。

---

## 4. activeTarget 選択ルール

複数地震がある場合、以下の優先順位で注目対象を選ぶ。

```text
1. 最大震度が高い
2. マグニチュードが大きい
3. 発生時刻が新しい
```

ただし、Phase 2-B.1 では複雑にしすぎない。

まずは以下でも可。

```text
最大震度またはMが取れる場合:
  最大震度 → M → 発生時刻

取れない場合:
  発生時刻の新しい順
```

複数対象がある場合は、既存の8秒巡回の枠組みを使って切り替える。

---

## 5. 12時間表示ルール

地震履歴は原則として過去12時間分を対象にする。

`demoNow` が指定されている場合:

```text
demoNow を現在時刻として12時間判定
```

`demoNow` が指定されていない場合:

```text
実時刻を現在時刻として12時間判定
```

ただし、既存 `/live` API側ですでに表示対象を絞っている場合は、その仕様を尊重する。

---

## 6. 地震データなし時の挙動

実データ取得に成功し、表示対象地震が0件の場合:

```text
地震小窓:
  現在、表示対象なし
  全国を監視中

中央地図:
  地震パルスなし

ヘッダー地震件数:
  0

全体:
  calm相当の地震表示
```

重要:

```text
データ取得成功 + 件数0 = 正常
データ取得失敗 = unavailable / error
```

この2つを混同しない。

---

## 7. 地震データ取得失敗時の挙動

API取得失敗・パース失敗・ネットワークエラー時は、画面全体を壊さない。

表示例:

```text
地震情報
取得できません
前回データなし
```

または

```text
地震情報
一時的に取得不可
```

禁止:

```text
地震情報なし
```

取得失敗時に「なし」と断定しない。

console error は出さず、必要なら console.warn 程度にする。

---

## 8. state パラメータとの関係

既存の `state=calm` / `state=alert` は維持する。

### `state=calm`

強制的に平穏表示。
実データがあっても、E2E安定のため calm 表示を優先する。

```text
state=calm はデモ・検証用の固定状態
```

### `state=alert`

Phase 2-B.1 では、地震情報については実データを優先する。

ただし、実データが0件または取得不能の場合は、既存のalertダミーデータを fallback として残すか、`useDemo=1` のような別パラメータを用意してもよい。

推奨:

```text
state=alert:
  実データ取得を試みる
  取得成功・地震あり → 実データ表示
  取得成功・地震なし → 対象なし表示
  取得失敗 → 取得不可表示

demoNow:
  時刻判定や時計固定にのみ使う
```

ただし、既存E2Eが `state=alert` のダミー表示に依存している場合は、E2Eが不安定にならないようにテスト用mockまたは `demo=1` を併用する。

---

## 9. demoNow との関係

`demoNow` は継続使用する。

用途:

```text
時計固定
12時間判定の現在時刻
E2Eスクリーンショット安定化
```

地震実データの発生時刻と `demoNow` が大きくずれると、過去12時間判定で表示対象が0になる可能性がある。

E2Eでは mock データを使う、または `demo=1` を用意してダミーデータを固定する方法を優先してよい。

---

## 10. E2E安定化用 mock / demo モード

実データは時々刻々と変わるため、E2Eで実データ有無に依存しないようにする。

推奨パラメータ:

```text
?demo=1
```

または既存設計に合わせて:

```text
?source=demo
```

目的:

```text
state=alert&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

で、必ず地震ダミーデータが表示されるようにする。

実データ接続確認とE2E安定確認を分ける。

### 推奨整理

```text
通常:
  実データ接続

?demo=1:
  デモデータ固定

?state=calm:
  平穏表示固定

?state=alert&demo=1:
  警戒デモ固定
```

---

## 11. 中央地図パルス更新

地震実データがある場合、中央地図の地震パルス位置を実データ由来にする。

Phase 2-B.1 では、簡略SVG地図上の疑似座標変換でよい。

```text
lat/lon
  ↓
簡易日本地図SVG上の x/y
  ↓
地震パルス表示
```

厳密な地図座標変換は次フェーズ以降でよい。

ただし、北海道・東北・関東・近畿・九州など大まかな位置が大きくズレないようにする。

---

## 12. 地震小窓ポップアップ

地震小窓の現在注目イベントに、以下を表示する。

```text
震源名
M
最大震度
発生時刻
深さ
津波情報があれば津波情報
```

例:

```text
岩手県沖
M6.1 / 最大震度5弱
19:21 発生
深さ 40km
津波: 調査中
```

値が欠損する場合は `不明` または非表示にする。
`null`, `undefined`, `NaN` を表示しない。

---

## 13. ヘッダーステータス反映

ヘッダー右側の地震件数を実データ由来にする。

```text
地震 0
地震 1
地震 3
```

対象は過去12時間の表示対象件数。

取得失敗時は以下のいずれか。

```text
地震 -
地震 取得不可
```

---

## 14. テロップは最小対応

今回、テロップ全面動的化は対象外。

ただし地震実データがある場合、テロップの先頭に地震情報を1件反映してもよい。

例:

```text
【地震】19:21 岩手県沖 M6.1 最大震度5弱
```

やりすぎない。
テロップ全カテゴリの動的化は Phase 2-C 以降。

---

## 15. エラー耐性

以下で画面が壊れないこと。

```text
API 500
API timeout
空配列
緯度経度なし
Mなし
最大震度なし
時刻パース失敗
想定外フィールド名
```

表示は degraded mode でよい。

---

## 16. data-testid 追加・維持

Phase 2-A の testid を壊さない。

地震用に可能なら追加する。

```text
live-stream-earthquake-active
live-stream-earthquake-history
live-stream-earthquake-history-item
live-stream-earthquake-popup
live-stream-earthquake-status
live-stream-pulse-earthquake
```

既存 testid は名称変更しない。

---

## 17. 今回やらないこと

以下は対象外。

```text
地震以外の実データ接続
キキクル・豪雨の実データ接続
鉄道の実データ接続
潮位・水位の実データ接続
JARTIC表示
中央地図の本物地図化
震度マーカー全市区町村表示の完全再現
地震詳細クリック操作
音声読み上げ
YouTube連携
DB保存
```

---

## 18. 受け入れ条件

以下を満たすこと。

```text
/live/stream が表示できる
既存 dedicated E2E が壊れない
state=calm が維持される
state=alert&demo=1 で安定した地震デモ表示ができる
通常表示で既存 /live の地震データ取得口を利用する
地震実データがある場合、地震小窓へ反映される
地震実データがある場合、中央地図の地震パルスへ反映される
地震実データがある場合、ヘッダー地震件数へ反映される
地震データ0件時に「表示対象なし」になる
地震取得失敗時に「なし」と断定しない
console error がない
/live が壊れない
/ が壊れない
```

---

## 実装後の報告

以下を報告する。

```text
変更ファイル
追加ファイル
参照した既存 /live 地震データ取得口
stream用 earthquake adapter の概要
demo / mock モードの仕様
地震0件時の表示
取得失敗時の表示
未対応項目
次フェーズ候補
```

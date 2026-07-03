# Claude用実装指示書

## `/live/stream` Stream Phase 2-B.4: 鉄道情報 実データ接続 MVP

## 目的

`/live/stream` 右上の **「鉄道情報」小窓** を、既存 `/live` 側の鉄道運行影響データへ接続する。

Phase 2-B.1 では地震、Phase 2-B.2 ではキキクル・豪雨、Phase 2-B.3 では潮位情報の実データ接続が完了した。
今回の Phase 2-B.4 では、ODPTで取得できる範囲の鉄道運行影響を、配信用に簡潔に表示する。

今回の目的は以下。

```text
既存 /live の鉄道運行影響データ
  ↓
stream用 railway adapter
  ↓
buildScene()
  ↓
鉄道情報小窓
影響路線カード
簡略路線図
ヘッダー鉄道件数
必要に応じてテロップの鉄道項目
```

---

## 重要方針

今回の対象は **ODPTで取得できる範囲の鉄道運行影響** とする。

全国の全鉄道路線を完全監視するものではない。
ODPTの対応範囲に依存するため、表示文言やUI上でも過度な断定を避ける。

### 表示上の考え方

```text
対象:
  ODPT対応路線の運行影響

対象外:
  ODPT非対応路線
  JR全路線の完全網羅
  全国鉄道網の完全監視
  公式発表外の推定
```

### 配信用の見せ方

通常 `/live` のように地図上へ細かい路線・駅名・ポップアップを大量表示しない。

```text
影響あり路線だけを太く表示
影響内容は左側カードに集約
地図上ポップアップは表示しない
平常時は「影響路線なし」
取得失敗時は「取得できません」
```

---

## 1. 既存 `/live` の鉄道データ取得口を調査する

まず既存 `/live` がどのAPIや状態を使って鉄道情報を表示しているか確認する。

調査対象候補:

```text
frontend/js/live/
live-railway-layer.js
live-railway-labels.js
live-alert-panel.js
live-main.js
backend /api/live/railway* 系
data_runtime/backend/live/railway* 系
ODPT cache / normalized railway data
```

確認すること:

```text
取得URL
レスポンス形式
事業者名
路線名
路線ID
運行状態
説明文
影響区間
更新時刻
路線カラー
代表座標
路線ジオメトリの有無
平常/影響ありの判定方法
取得失敗時の表現
```

既存 `/live` がすでに正規化済みの鉄道運行情報を持っている場合、それを優先して使う。
`/live/stream` からODPTへ直接アクセスしない。

---

## 2. stream用 railway adapter を作る

実データを直接DOMへ流し込まず、`/live/stream` 用 ViewModel に変換する。

関数名例:

```js
function buildRailwayStreamModel(rawRailwayData, options) {
  // /live 由来の鉄道運行影響データを /live/stream 用に整形する
}
```

返却イメージ:

```js
{
  hasRailwayData: true,
  unavailable: false,
  affectedCount: 3,
  affectedLines: [
    {
      id: "odpt.Railway:TokyoMetro.Tozai",
      operator: "東京メトロ",
      lineName: "東西線",
      status: "delay",
      statusLabel: "遅延",
      section: "一部区間",
      reason: "混雑の影響",
      description: "混雑の影響で一部列車に遅れが出ています。",
      updatedTime: "20:35",
      lineColor: "#00A7DB",
      geometry: [],
      representativeLat: 35.69,
      representativeLon: 139.76
    }
  ],
  displayLines: [],
  statusCount: 3
}
```

---

## 3. 影響あり判定

鉄道パネルでは、原則として影響のある路線のみ表示する。

### 影響ありに含める状態例

```text
運転見合わせ
運休
一部運休
遅延
運転再開
ダイヤ乱れ
直通運転中止
運転変更
その他、平常ではない状態
```

### 影響なしに扱う状態例

```text
平常
平常運転
情報なし
通常運行
```

ただし、ODPTの表記ゆれがある可能性があるため、既存 `/live` 側の判定ロジックがある場合はそれを尊重する。

---

## 4. 鉄道小窓の表示

右上パネルは以下の構成を維持する。

```text
左側:
  影響路線カード一覧

右側:
  簡略路線図
```

### 左側カード

表示内容:

```text
路線名
状態
区間/理由
更新時刻
路線色バー
```

例:

```text
中央線快速
運転見合わせ
三鷹〜東京 / 人身事故
20:35
```

### 右側簡略路線図

表示方針:

```text
影響あり路線:
  太線
  路線色
  明るく表示

平常路線:
  原則表示しない
  表示する場合も細線・低透明度

駅名:
  原則非表示

地図上ポップアップ:
  表示しない
```

---

## 5. 表示件数

左側カードは最大4〜6件程度に制限する。

配信画面では細かく詰め込まない。

```text
影響路線が0件:
  影響路線なし
  平常運転

影響路線が1〜6件:
  すべて表示

影響路線が7件以上:
  重要度上位を表示
  残りは「ほか n 件」
```

---

## 6. 重要度順

複数影響路線がある場合は、以下の優先順位で表示する。

```text
1. 運転見合わせ / 運休
2. 一部運休 / 直通運転中止
3. 遅延
4. 運転変更 / ダイヤ乱れ
5. 更新時刻が新しいもの
```

既存 `/live` 側に優先順位がある場合は、それに合わせる。

---

## 7. 平常時表示

実データ取得に成功し、影響路線が0件の場合:

```text
鉄道情報小窓:
  影響路線なし
  平常運転

ヘッダー:
  鉄道 0

右側簡略路線図:
  控えめな背景線のみ
  または「影響路線なし」表示
```

重要:

```text
取得成功 + 影響0件 = 正常
取得失敗 = unavailable / error
```

この2つを混同しない。

---

## 8. 取得失敗時表示

API取得失敗・パース失敗・ネットワークエラー時は、画面全体を壊さない。

表示例:

```text
鉄道情報
取得できません
```

または

```text
鉄道情報
一時的に取得不可
```

禁止:

```text
影響路線なし
平常運転
```

取得失敗時に平常と断定しない。

console error は出さず、必要なら console.warn 程度にする。

---

## 9. ヘッダー鉄道件数

ヘッダー右上の `鉄道 n` は、影響路線数とする。

```text
影響あり:
  鉄道 4

影響なし:
  鉄道 0

取得失敗:
  鉄道 -
```

ODPT対応範囲内の影響件数であり、全国全鉄道の件数ではない。

---

## 10. 中央地図パルス

鉄道は地震・豪雨と異なり、基本的に中央地図パルス対象外とする。

理由:

```text
鉄道は線情報であり、点パルスにすると意味が曖昧になる
中央地図がうるさくなる
ODPT対応範囲が偏る
```

ただし、将来フェーズで必要になった場合に備えて `live-stream-pulse-rail` の testid は残してもよい。

Phase 2-B.4 では、中央地図への鉄道パルス表示は必須ではない。

---

## 11. テロップ最小対応

今回、テロップ全面動的化は対象外。

ただし鉄道影響がある場合、鉄道項目だけ最小限差し替えてもよい。

例:

```text
【鉄道】中央線快速 三鷹〜東京で運転見合わせ
```

影響なしの場合は、テロップに鉄道項目を出さない、または既存デモ文言のままでよい。

テロップ全体の統合は Phase 2-C で行う。

---

## 12. state / demo パラメータとの関係

### `state=calm`

強制平穏表示。
実データがあっても calm 表示を優先する。

```text
鉄道パネル:
  影響路線なし
  平常運転
```

### `state=alert&demo=1`

E2E安定用の警戒デモ表示。
鉄道のダミー影響路線を必ず表示する。

### 通常表示

実データ取得を試みる。

```text
取得成功・影響あり:
  実データ表示

取得成功・影響なし:
  影響路線なし

取得失敗:
  取得不可表示
```

---

## 13. demo=1

`demo=1` を地震・豪雨・潮位に加えて鉄道にも適用する。

例:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

このURLでは以下が保証されること。

```text
鉄道デモ影響路線が表示される
ヘッダー鉄道件数が1以上になる
鉄道小窓左側に路線カードが出る
右側に簡略路線図が出る
```

---

## 14. data-testid 追加・維持

既存 testid を壊さない。

追加推奨:

```text
live-stream-rail-active
live-stream-rail-list
live-stream-rail-list-item
live-stream-rail-line-name
live-stream-rail-status
live-stream-rail-section
live-stream-rail-map
live-stream-rail-route
live-stream-rail-empty
live-stream-rail-unavailable
```

既存必須testid:

```text
live-stream-panel-rail
live-stream-status-bar
live-stream-ticker
```

は名称変更しない。

---

## 15. 表示欠損対策

以下が画面に出ないこと。

```text
undefined
null
NaN
Invalid Date
[object Object]
```

値が欠損する場合:

```text
路線名なし:
  路線名不明

状態なし:
  状態不明

区間なし:
  区間情報なし

更新時刻なし:
  更新 --
```

ただし、配信画面なので欠損表示は最小限にする。

---

## 16. 今回やらないこと

```text
全国鉄道網の完全対応
ODPT非対応路線の推定表示
JR全路線対応
駅名表示
地図上ポップアップ
中央地図への鉄道パルス
鉄道詳細ページ
鉄道履歴保存
鉄道と道路/JARTICの連携
テロップ全面動的化
```

---

## 17. 受け入れ条件

以下を満たすこと。

```text
/live/stream が表示できる
既存 dedicated E2E が壊れない
state=calm が維持される
state=alert&demo=1 で鉄道デモ表示ができる
通常表示で既存 /live の鉄道データ取得口を利用する
影響あり時に鉄道小窓へ反映される
影響あり時にヘッダー鉄道件数へ反映される
影響なし時に「影響路線なし / 平常運転」になる
取得失敗時に平常と断定しない
地図上ポップアップが出ない
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
参照した既存 /live 鉄道データ取得口
stream用 railway adapter の概要
影響あり判定ロジック
demo / mock モードの仕様
影響0件時の表示
取得失敗時の表示
未対応項目
次フェーズ候補
```

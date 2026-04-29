# Magnitude Phase2-4 実装指示書（Claude Code）
## 震度フィルタ対応

## 目的

Magnitudeモードの地震リストと地図ピンに震度フィルタを追加する。

表示対象を震度条件で絞り込めるようにし、ユーザーが重要度の高い地震を把握しやすくする。

---

## 背景

Magnitude Phase2-3 までで、以下に対応済み。

```text
・地震ピン表示
・地震リスト表示
・現在地からの距離表示
・避難所レイヤー一時非表示
・新着地震の差分ハイライト
・新しい順 / 近い順ソート
```

次の段階では、震度が小さい地震を必要に応じて隠し、情報量を調整できるようにする。

---

## 実装スコープ

### やること

```text
・Magnitudeパネルに震度フィルタUIを追加
・全件 / 震度3以上 / 震度4以上 / 震度5弱以上 を切替可能にする
・フィルタ結果を地震リストに反映する
・フィルタ結果を地図ピンに反映する
・現在のソート状態と組み合わせて動作する
・NEWバッジ、新着件数、距離表示を維持する
・フィルタ条件に一致しない場合は空表示メッセージを出す
```

### やらないこと

```text
・WebSocketリアルタイム受信
・自動ポーリング
・避難誘導連動
・地域フィルタ
・期間フィルタ
```

---

## フィルタ仕様

### フィルタ種別

```text
all:
  全件

3:
  最大震度3以上

4:
  最大震度4以上

5-:
  最大震度5弱以上
```

UI表示:

```text
全件 | 震度3以上 | 震度4以上 | 震度5弱以上
```

初期値:

```text
all
```

---

## 震度の比較仕様

P2P/JMA系の震度表現には以下があり得る。

```text
1
2
3
4
5弱
5強
6弱
6強
7
不明
null
```

内部比較用に数値化する。

推奨マッピング:

```js
const INTENSITY_RANK = {
  '1': 10,
  '2': 20,
  '3': 30,
  '4': 40,
  '5弱': 50,
  '5-': 50,
  '5強': 55,
  '5+': 55,
  '6弱': 60,
  '6-': 60,
  '6強': 65,
  '6+': 65,
  '7': 70
};
```

注意:

```text
・max_intensity が数値の場合も扱う
・文字列前後の空白を除去する
・null / undefined / 不明 は比較不能として扱う
```

---

## フィルタ判定

疑似コード:

```js
function getIntensityRank(value) {
  if (value == null) return null;

  const s = String(value).trim();

  if (INTENSITY_RANK[s] != null) {
    return INTENSITY_RANK[s];
  }

  return null;
}

function passesIntensityFilter(item, filterMode) {
  if (filterMode === 'all') return true;

  const rank = getIntensityRank(item.max_intensity);
  if (rank == null) return false;

  if (filterMode === '3') return rank >= 30;
  if (filterMode === '4') return rank >= 40;
  if (filterMode === '5-') return rank >= 50;

  return true;
}
```

---

## 状態管理

Magnitude側に現在のフィルタ状態を持つ。

```js
let magnitudeIntensityFilter = 'all';
```

ページリロードでリセットしてよい。  
同一セッション内で Magnitude ON/OFF しても、可能なら最後の選択を維持してよい。

---

## 処理順序

地震データの表示処理は以下の順にする。

```text
1. APIから取得した全itemsを保持
2. 震度フィルタを適用
3. ソートを適用
4. リストを描画
5. ピンを描画
```

重要:

```text
・フィルタはリストとピンの両方に適用する
・ソートはフィルタ後のitemsに対して適用する
```

---

## 新着表示との関係

Phase2-2 の NEW 判定は、API取得結果の全件に対して行う。  
ただし表示はフィルタ結果に従う。

```text
・新着地震がフィルタ条件を満たす場合 → NEW表示
・新着地震がフィルタ条件を満たさない場合 → 表示しない
・直近の newEventIds に含まれる間は、フィルタ変更後もNEW表示してよい
```

新着件数表示は、フィルタ後に表示されている新着件数を推奨する。

---

## UI仕様

Magnitudeパネル上部、ソートUIの近くに震度フィルタを追加する。

表示例:

```text
表示: [全件] [震度3以上] [震度4以上] [震度5弱以上]
並び順: [新しい順] [近い順]
```

CSSクラス例:

```text
.mq-filter-tabs
.mq-filter-button
.mq-filter-button.active
```

スマホ幅でも折り返して見やすいようにする。

---

## 空表示

フィルタ条件に一致する地震がない場合は、リストにメッセージを表示する。

```text
条件に一致する地震情報はありません。
```

地図ピンも0件にする。

---

## API再取得時の挙動

```text
・現在の震度フィルタを維持する
・現在のソート状態を維持する
・新着判定後にフィルタを適用する
```

---

## Magnitude OFF時の挙動

```text
・フィルタ状態は維持してもリセットしてもよい
・ただしON/OFFでUIが壊れないこと
・地震ピンが残らないこと
```

推奨:

```text
同一セッション内ではフィルタ状態を維持する
```

---

## 実装対象の想定ファイル

```text
frontend/js/magnitude.js
frontend/js/magnitude-ui.js
frontend/js/magnitude-layer.js
frontend/index.html
```

既存構造を優先すること。

---

## エッジケース

```text
・max_intensity が null:
  全件では表示、震度条件付きでは非表示、JSエラーなし

・max_intensity が "5弱":
  震度5弱以上で表示

・max_intensity が "5強":
  震度5弱以上で表示

・max_intensity が "不明":
  全件では表示、震度条件付きでは非表示

・フィルタ後0件:
  空表示メッセージ、ピン0件、JSエラーなし
```

---

## 実装順序

1. 震度ランク変換関数を追加する
2. passesIntensityFilter を追加する
3. magnitudeIntensityFilter 状態を追加する
4. リスト描画前にフィルタを適用する
5. ピン描画にも同じフィルタ済みitemsを渡す
6. フィルタ切替UIを追加する
7. フィルタ後0件の空表示を追加する
8. ソート機能との組み合わせを確認する
9. NEW表示との組み合わせを確認する
10. ON/OFF連続操作で状態が壊れないことを確認する

---

## 完了条件

```text
・全件 / 震度3以上 / 震度4以上 / 震度5弱以上 を切り替えられる
・フィルタがリストとピンの両方に反映される
・震度5弱/5強/6弱/6強/7 を正しく比較できる
・max_intensity null/不明 でJSエラーにならない
・フィルタ後0件で空表示になる
・新しい順/近い順ソートが壊れない
・NEWバッジ、新着件数、ピン強調が壊れない
・避難所一時非表示が壊れない
・DOM/ピン/イベントが増殖しない
```

---

## 注意事項

このフェーズではリアルタイム更新は実装しない。  
リアルタイム更新は Phase3 で実施予定とする。

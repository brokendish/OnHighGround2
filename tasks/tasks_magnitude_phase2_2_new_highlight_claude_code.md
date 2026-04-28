# Magnitude Phase2-2 実装指示書（Claude Code）
## 新着地震の差分ハイライト対応

## 目的

Magnitudeモードで地震情報を再取得した際に、前回表示済みの地震と新規取得された地震を判別し、新着地震を視覚的に強調する。

リアルタイム WebSocket 実装前の段階として、手動更新または再取得時に「新しい地震が追加された」ことをユーザーがすぐ分かるようにする。

---

## 背景

Magnitude MVP では、指定日数分の地震情報を地図ピンとリストで表示できるようになった。  
Phase2-1 では Magnitudeモード中の避難所一時非表示により、地震情報の視認性を改善した。

次の段階では、地震情報が更新されたときに新着イベントを目立たせ、Magnitudeモードに「生きている情報画面」としての感触を追加する。

---

## 実装スコープ

### やること

```text
・前回取得済み event_id の保持
・再取得時に新規 event_id を差分判定
・新着地震のリスト項目に NEW バッジ表示
・新着地震ピンを一定時間だけ強調表示
・新着件数を Magnitudeパネル上部に表示
・連続更新時に状態が破綻しないようにする
```

### やらないこと

```text
・WebSocketリアルタイム受信
・自動ポーリング
・ブラウザ通知
・音声通知
・避難誘導連動
```

---

## 基本仕様

### 初回表示時

初回取得時は、全件を「既存データ」として扱う。

```text
Magnitudeモード初回ON:
  地震一覧取得
  event_id を既知リストに登録
  NEW表示はしない
```

理由:

```text
初回表示で全件NEWにするとノイズが大きい。
```

---

### 再取得時

再取得時に、前回までに存在しなかった `event_id` を新着として扱う。

```text
再取得:
  新しい items を取得
  knownEventIds に存在しない event_id を newEventIds として判定
  newEventIds を強調表示
  knownEventIds に追加
```

---

## 状態管理

Magnitude制御側に以下の状態を追加する。

推奨ファイル:

```text
frontend/js/magnitude.js
```

状態例:

```js
let knownMagnitudeEventIds = new Set();
let latestNewMagnitudeEventIds = new Set();
let magnitudeFirstLoadCompleted = false;
let magnitudeHighlightTimers = [];
```

---

## 差分判定ロジック

疑似コード:

```js
function detectNewEarthquakes(items) {
  const newIds = new Set();

  if (!magnitudeFirstLoadCompleted) {
    items.forEach(item => {
      if (item.event_id) knownMagnitudeEventIds.add(item.event_id);
    });
    magnitudeFirstLoadCompleted = true;
    latestNewMagnitudeEventIds = new Set();
    return latestNewMagnitudeEventIds;
  }

  items.forEach(item => {
    if (!item.event_id) return;

    if (!knownMagnitudeEventIds.has(item.event_id)) {
      newIds.add(item.event_id);
    }

    knownMagnitudeEventIds.add(item.event_id);
  });

  latestNewMagnitudeEventIds = newIds;
  return newIds;
}
```

---

## 新着表示仕様

### リスト表示

新着地震には `NEW` バッジを表示する。

表示例:

```text
NEW 12:34 相模湾 震度4 M4.8
現在地から 約32km
```

CSSクラス例:

```css
.mq-item-new
.mq-new-badge
```

CSS例:

```css
.mq-item-new {
  border-left: 4px solid #ff5a3c;
  background: rgba(255, 90, 60, 0.08);
}

.mq-new-badge {
  display: inline-block;
  font-size: 11px;
  font-weight: 700;
  padding: 2px 6px;
  border-radius: 999px;
  margin-right: 6px;
  background: #ff5a3c;
  color: #fff;
}
```

既存デザインに合わせて調整すること。

---

### ピン表示

新着地震ピンには追加クラスを付与する。

```text
magnitude-marker-new
```

挙動:

```text
・既存の時間帯色分けは維持
・新着の場合だけ外周リングまたはパルスを追加
・一定時間後に新着強調を解除して通常表示に戻す
```

推奨強調時間:

```text
60秒
```

CSS例:

```css
.magnitude-marker-new {
  animation: magnitude-new-pulse 1.2s ease-in-out infinite;
}

@keyframes magnitude-new-pulse {
  0% {
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(255, 90, 60, 0.6);
  }
  70% {
    transform: scale(1.18);
    box-shadow: 0 0 0 10px rgba(255, 90, 60, 0);
  }
  100% {
    transform: scale(1);
    box-shadow: 0 0 0 0 rgba(255, 90, 60, 0);
  }
}
```

---

## 新着件数表示

Magnitudeパネル上部に、新着件数を短時間表示する。

表示例:

```text
新着地震 2件
```

表示条件:

```text
・newEventIds.size > 0 の場合のみ表示
・一定時間後に非表示、または次回取得時に更新
```

推奨表示時間:

```text
10秒〜30秒
```

---

## 手動更新導線

既に更新ボタンがある場合:

```text
既存の更新ボタンに差分判定を組み込む
```

更新ボタンがない場合:

```text
Magnitudeパネルに「更新」ボタンを追加してよい
```

表示例:

```text
更新
```

動作:

```text
/api/earthquakes を再取得
差分判定
地図ピン再描画
リスト再描画
新着があれば強調
```

---

## 初期化・解除処理

MagnitudeモードOFF時:

```text
・新着表示タイマーをクリア
・最新の newEventIds をクリア
・ただし knownEventIds は維持してよい
```

推奨:

```text
同一セッション中は knownEventIds を維持する。
ページ再読み込みではリセットでよい。
```

理由:

```text
Magnitudeを一度閉じて再表示したときに、同じ地震を毎回NEW表示しないため。
```

ただし実装が複雑になる場合は、Magnitude OFF時に全リセットでも可。  
その場合でも初回表示ではNEWを出さない仕様にすること。

---

## 非同期競合対策

既存の Magnitude MVP で導入済みの取得トークン/ガードがある場合、それを使う。

要件:

```text
・古いAPIレスポンスが後から返っても、最新表示を上書きしない
・連続更新で newEventIds が壊れない
・Magnitude OFF後にレスポンスが返っても描画しない
```

---

## XSS対策

新着バッジ追加時も既存のエスケープ方針を維持する。

```text
・epicenter_name
・tsunami_info
・その他API由来文字列
```

は必ず安全に描画すること。

---

## 実装対象の想定ファイル

```text
frontend/js/magnitude.js
frontend/js/magnitude-layer.js
frontend/js/magnitude-ui.js
frontend/index.html
```

必要に応じて既存構造を優先すること。

---

## 実装順序

1. 現在の Magnitude 再取得処理を確認する
2. knownEventIds / newEventIds の状態管理を追加する
3. 初回表示ではNEWを出さない差分判定を実装する
4. 再取得時のみ新着判定する
5. リストに NEW バッジを表示する
6. ピンに新着強調クラスを付与する
7. 新着件数表示を追加する
8. 強調解除タイマーを追加する
9. Magnitude OFF時のタイマー/状態整理を実装する
10. 連続更新・連続ON/OFFで壊れないようにする

---

## 完了条件

以下を満たすこと。

```text
・初回表示時に全件NEWにならない
・再取得時に新規 event_id のみNEWになる
・新着地震のリスト項目にNEWバッジが表示される
・新着地震ピンが一定時間強調される
・新着件数が表示される
・連続更新でピン/DOM/イベントが増殖しない
・Magnitude OFF後にタイマーや表示が残らない
・地震API失敗時に状態が壊れない
・Phase2-1の避難所一時非表示が壊れない
```

---

## 注意事項

今回はリアルタイム実装ではない。  
「更新したら新着が分かる」状態まででよい。

このフェーズの目的は、Magnitudeモードにライブ感を出すための土台作りである。

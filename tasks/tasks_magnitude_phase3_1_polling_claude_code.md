# Magnitude Phase3-1 実装指示書（Claude Code）
## 定期更新ポーリング対応

## 目的

Magnitudeモードに定期更新ポーリングを追加し、地震情報を自動的に再取得できるようにする。

WebSocket/SSEによるリアルタイム化の前段階として、既存の `/api/earthquakes` を一定間隔で再取得し、新着差分ハイライト・震度フィルタ・ソート・地震タブUIと安全に連携させる。

---

## 背景

Magnitudeは以下に対応済み。

```text
・地震情報MVP
・避難所一時非表示
・新着差分ハイライト
・距離順ソート
・震度フィルタ
・地震タブUI
```

P2P地震情報は JSON API と WebSocket API を提供しており、WebSocket API は低遅延受信用とされている。  
ただし、最初からWebSocket常時接続に入ると状態管理・再接続・通知制御が重くなるため、Phase3-1では安全な定期更新から始める。

---

## 実装スコープ

### やること

```text
・MagnitudeモードON中だけ定期更新する
・既存 /api/earthquakes を一定間隔で再取得する
・新着差分ハイライトと連動する
・現在の震度フィルタ/ソート状態を維持する
・更新中表示、最終更新時刻、次回更新目安を表示する
・手動更新ボタンと競合しないようにする
・Magnitude OFF時にタイマーを確実に停止する
・API失敗時もUIを壊さず復帰可能にする
```

### やらないこと

```text
・WebSocket接続
・SSE接続
・プッシュ通知
・音声通知
・避難誘導連動
・バックグラウンド常時監視
```

---

## 基本仕様

### 更新間隔

初期値:

```text
60秒
```

将来Config化する前提で、定数として分離する。

```js
const MAGNITUDE_POLL_INTERVAL_MS = 60_000;
```

開発・検証しやすいように内部的に上書きしやすい構造にしてよい。

---

## 動作条件

```text
MagnitudeモードON:
  定期更新開始

MagnitudeモードOFF:
  定期更新停止

ページ非表示:
  可能なら更新停止または抑制

ページ再表示:
  MagnitudeモードONなら即時更新または次回更新を再開
```

`document.visibilityState` を利用してよい。

---

## ポーリング処理

### 基本フロー

```text
1. MagnitudeモードON
2. 初回地震情報取得
3. setTimeoutループ開始
4. intervalごとに /api/earthquakes を再取得
5. 差分判定
6. フィルタ/ソートを維持して再描画
7. 新着があればNEW表示
```

---

## 推奨実装

`setInterval` より `setTimeout` 再帰の方が安全。

理由:

```text
・API取得が遅い場合に多重実行を避けやすい
・失敗時のバックオフを入れやすい
・OFF時の停止が明確
```

疑似コード:

```js
let magnitudePollTimer = null;
let magnitudePolling = false;
let magnitudePollInFlight = false;

function startMagnitudePolling() {
  stopMagnitudePolling();
  magnitudePolling = true;
  scheduleNextMagnitudePoll();
}

function stopMagnitudePolling() {
  magnitudePolling = false;
  if (magnitudePollTimer) {
    clearTimeout(magnitudePollTimer);
    magnitudePollTimer = null;
  }
}

function scheduleNextMagnitudePoll(delayMs = MAGNITUDE_POLL_INTERVAL_MS) {
  if (!magnitudePolling) return;

  magnitudePollTimer = setTimeout(async () => {
    await runMagnitudePoll();
    scheduleNextMagnitudePoll();
  }, delayMs);
}

async function runMagnitudePoll() {
  if (!magnitudePolling) return;
  if (magnitudePollInFlight) return;
  if (document.visibilityState === 'hidden') return;

  magnitudePollInFlight = true;

  try {
    await refreshMagnitudeData({ reason: 'poll' });
  } finally {
    magnitudePollInFlight = false;
  }
}
```

---

## 手動更新との競合防止

既存の更新ボタンがある場合、手動更新とポーリングが同時に走らないようにする。

```text
・取得中は二重更新しない
・手動更新が先ならポーリングはスキップ
・ポーリング中に手動更新された場合は既存の取得ガードに従う
```

既存の fetch token / request id がある場合は必ず活用する。

---

## UI仕様

Magnitude地震タブ上部に更新状態を表示する。

表示例:

```text
最終更新: 23:41
自動更新: 60秒ごと
```

更新中:

```text
更新中...
```

失敗時:

```text
更新に失敗しました。次回自動更新で再試行します。
```

新着あり:

```text
新着地震 2件
```

既存の新着件数表示と競合しないようにする。

---

## 最終更新時刻

更新成功時に `lastUpdatedAt` を保存する。

```js
let magnitudeLastUpdatedAt = null;
```

表示はローカル時刻でよい。

```text
23:41
```

---

## エラー処理

API失敗時:

```text
・既存表示は基本的に維持する
・エラーメッセージを表示する
・次回ポーリングで再試行する
・連続失敗してもタイマーが増殖しない
```

必要なら連続失敗回数を保持する。

```js
let magnitudePollFailureCount = 0;
```

ただし初期実装ではバックオフ必須ではない。

---

## ページ非表示時の扱い

推奨:

```text
document.visibilityState === 'hidden' の間は取得しない
```

再表示時:

```text
MagnitudeモードONなら即時1回更新
```

疑似コード:

```js
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && isMagnitudeModeActive()) {
    refreshMagnitudeData({ reason: 'visibility' });
  }
});
```

---

## Config化の準備

今回はConfig管理画面への追加は必須ではない。  
ただし将来追加しやすいように定数名を明確にする。

将来候補:

```text
earthquake.auto_refresh_enabled
earthquake.refresh_interval_seconds
```

今回は固定値でよい。

---

## 既存機能との連携

### 新着差分ハイライト

```text
・ポーリング取得でも新規event_idのみNEW表示
・初回表示では全件NEWにしない
```

### 震度フィルタ

```text
・ポーリング後も現在のフィルタを維持
・フィルタ後のNEW件数表示を維持
```

### ソート

```text
・ポーリング後も現在のソートを維持
```

### 地震タブUI

```text
・地震タブ内で更新状態を表示
・スクロール干渉を再発させない
```

### 避難所一時非表示

```text
・Magnitude ON中は避難所非表示を維持
・ポーリングで避難所表示状態を壊さない
```

---

## 実装対象の想定ファイル

```text
frontend/js/magnitude.js
frontend/js/magnitude-ui.js
frontend/js/magnitude-layer.js
frontend/index.html
```

必要に応じて既存構造を優先すること。

---

## エッジケース

### 1. Magnitude ON/OFF連打

```text
・タイマーが増殖しない
・OFF後にAPIレスポンスが返っても描画しない
```

### 2. API遅延

```text
・次のポーリングが重ならない
・古いレスポンスで最新表示を上書きしない
```

### 3. API失敗

```text
・UIが壊れない
・次回更新で復帰できる
```

### 4. ページ非表示

```text
・非表示中は無駄な取得を抑制
・再表示時に更新できる
```

---

## 実装順序

1. 既存の地震情報取得関数を確認する
2. 手動更新と共通利用できる refreshMagnitudeData を整理する
3. ポーリング状態変数を追加する
4. startMagnitudePolling / stopMagnitudePolling を実装する
5. Magnitude ON/OFF と連動させる
6. 取得中/最終更新/失敗表示を追加する
7. visibilitychange 対応を追加する
8. 新着差分・フィルタ・ソートとの連携を確認する
9. ON/OFF連続操作でタイマー増殖がないことを確認する
10. e2eテストを追加する

---

## 完了条件

```text
・Magnitude ON中だけ自動更新される
・Magnitude OFFで自動更新が完全停止する
・更新中/最終更新時刻が表示される
・API失敗時もUIが壊れず次回更新で復帰できる
・ポーリングと手動更新が競合しない
・新着差分ハイライトがポーリングでも動く
・震度フィルタ/ソート状態が維持される
・地震タブUIのスクロール挙動が壊れない
・避難所一時非表示が壊れない
・タイマー/DOM/ピン/イベントが増殖しない
```

---

## 注意事項

このフェーズは WebSocket 実装ではない。  
あくまでリアルタイム化前の安全な自動更新である。

次フェーズで以下を検討する。

```text
Phase3-2:
  WebSocket または SSE による低遅延更新
```

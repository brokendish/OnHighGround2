# Magnitude Phase3-2C 実装指示書（Claude Code）
## 再接続・フォールバック・運用ログ強化

## 目的

Phase3-2Bで追加したP2P WebSocketリアルタイム受信を、実運用に耐えやすい形へ補強する。

主に以下を強化する。

```text
WebSocket再接続
指数バックオフ
SSE接続状態表示
ポーリングフォールバック制御
運用ログ
ヘルス確認
```

---

## 背景

Phase3-2AでSSE基盤、Phase3-2BでP2P WebSocket接続を追加済み。  
ただし、リアルタイム接続は切断・再接続・外部障害が普通に起こる。

Phase3-2Cでは、障害時にもOnHighGround2のMagnitude機能が破綻しないようにする。

---

## 実装スコープ

### やること

- P2P WebSocket切断時の再接続制御
- 指数バックオフ + 最大待機時間
- 接続状態をbackendで保持
- frontendにSSE状態を表示
- SSE切断時のポーリングフォールバック明示
- ヘルス/ステータスAPI追加
- 運用ログ追加

### やらないこと

- 通知/音声
- 避難誘導連動
- 複数外部ソース統合
- 永続DB保存

---

## Backend再接続仕様

### 状態

```text
disconnected
connecting
connected
reconnecting
failed
```

### バックオフ

```text
初回: 5秒
次回: 10秒
次回: 20秒
最大: 60秒
```

接続成功したらバックオフをリセットする。

疑似コード:

```python
delay = min(base_delay * (2 ** retry_count), max_delay)
```

---

## 再接続要件

- WebSocket切断時に自動再接続する
- 再接続中もbackendはhealthyを維持する
- 再接続ループが暴走しない
- shutdown時に再接続タスクを止める
- 接続成功時に状態をconnectedへ戻す

---

## ステータスAPI

追加候補:

```http
GET /api/earthquakes/realtime/status
```

レスポンス例:

```json
{
  "enabled": true,
  "state": "connected",
  "source": "p2p_ws",
  "last_connected_at": "2026-04-29T12:00:00+09:00",
  "last_event_at": "2026-04-29T12:34:56+09:00",
  "last_error": null,
  "retry_count": 0,
  "next_retry_at": null
}
```

---

## SSEステータスイベント

SSEで地震イベントだけでなく、状態イベントも流す。

```text
event: status
data: {"state":"connected","source":"p2p_ws"}
```

切断時:

```text
event: status
data: {"state":"reconnecting","source":"p2p_ws","next_retry_seconds":20}
```

---

## Frontend表示

地震タブにリアルタイム状態を表示する。

```text
リアルタイム: 接続中
リアルタイム: 再接続中（自動更新で継続）
リアルタイム: 切断中（60秒ごとに自動更新）
```

重要:

```text
SSE/WebSocketが切れてもMagnitude自体をエラー画面にしない。
ポーリングで継続していることを示す。
```

---

## ポーリングフォールバック制御

Ph3-1のポーリングは維持する。

推奨:

```text
SSE connected:
  60〜180秒ポーリング

SSE disconnected/reconnecting:
  30〜60秒ポーリング
```

初期実装では間隔変更は必須ではない。  
ただし、UI上は「自動更新で継続」と分かるようにする。

---

## 運用ログ

最低限以下をログに出す。

```text
P2P WS connect attempt
P2P WS connected
P2P WS disconnected
P2P WS reconnect scheduled delay=xx
P2P WS reconnect failed
P2P WS reconnect success
SSE client connected
SSE client disconnected
earthquake realtime event published
earthquake realtime duplicate skipped
```

ログレベル:

```text
INFO: 接続/切断/再接続
WARNING: 再接続失敗、連続失敗
ERROR: 想定外例外
DEBUG: イベント詳細、duplicate詳細
```

既存 `logging.level` 設定に従うこと。

---

## ヘルスの考え方

backend自体の `/health` は、P2P WebSocketが切れても原則healthyのままでよい。

理由:

```text
外部リアルタイム接続が切れても、ポーリングで地震情報機能は継続できるため。
```

詳細状態は `/api/earthquakes/realtime/status` で見る。

---

## エッジケース

- 起動時からP2Pに接続できない
- 接続後すぐ切断
- 何度も切断
- shutdown中に再接続待機中
- SSE clientが多数接続/切断
- frontendがスリープ復帰

すべてbackend/frontendが落ちないこと。

---

## 実装順序

1. realtime serviceに状態管理を追加
2. 再接続バックオフを実装
3. shutdown時のタスク停止を実装
4. status APIを追加
5. SSE status eventを追加
6. frontendにリアルタイム状態表示を追加
7. ポーリングフォールバック表示を追加
8. ログを整理
9. e2e/単体テストを追加
10. 接続失敗・復帰を検証

---

## 完了条件

- P2P WS切断時に再接続を試みる
- 指数バックオフが効く
- 再接続中もbackendが落ちない
- status APIで状態が見える
- SSE status eventがfrontendに届く
- frontendに接続状態が表示される
- 切断時もポーリングで継続する
- shutdown時にタスクが残らない
- ログで運用状況を追える
- Phase3-2A/B/Phase3-1に回帰なし

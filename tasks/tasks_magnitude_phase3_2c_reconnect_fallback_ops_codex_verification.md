# Magnitude Phase3-2C 検証指示書（CODEX）
## 再接続・フォールバック・運用ログ強化

## 目的

P2P WebSocket接続の切断・再接続・外部障害時にもMagnitudeが破綻せず、ポーリングフォールバックで継続できることを検証する。

---

## 検証対象

```text
WebSocket再接続
指数バックオフ
realtime status API
SSE status event
frontend接続状態表示
ポーリングフォールバック
運用ログ
```

---

# 1. 事前確認

```bash
docker compose ps
curl -s "http://localhost:8080/api/earthquakes?days=1" | python3 -m json.tool
curl -s "http://localhost:8080/api/earthquakes/realtime/status" | python3 -m json.tool
```

確認:
- backend healthy
- 既存API 200
- status API が返る

---

# 2. status API確認

確認項目:
- enabled
- state
- source
- last_connected_at
- last_event_at
- last_error
- retry_count
- next_retry_at

接続状態に応じて値が変化すること。

---

# 3. 正常接続ログ確認

backend logs:

```bash
docker compose logs -f backend
```

確認:
- connect attempt
- connected
- SSE client connected/disconnected
- event published

---

# 4. 切断・再接続確認

P2P WebSocketをモックできる場合、意図的に切断する。

確認:
- state が reconnecting になる
- reconnect scheduled ログが出る
- retry_count が増える
- next_retry_at が入る
- 再接続成功で connected に戻る
- retry_count がリセットされる

---

# 5. バックオフ確認

連続失敗を発生させる。

確認:
- 5秒→10秒→20秒→最大60秒程度に増える
- 無限高速リトライしない
- backend CPU/ログが暴走しない

---

# 6. frontend状態表示確認

手順:
1. Magnitude ON
2. 地震タブ表示
3. 接続状態を変化させる

確認:
- 接続中
- 再接続中（自動更新で継続）
- 切断中（自動更新で継続）

などが分かる。

---

# 7. SSE status event確認

curlでSSEを確認。

```bash
curl -N "http://localhost:8080/api/earthquakes/stream"
```

確認:
- `event: status` が流れる
- state変化が通知される
- `event: earthquake` と共存する

---

# 8. ポーリングフォールバック確認

WebSocket/SSEが切断またはreconnecting状態でも確認。

- `/api/earthquakes` のポーリングが継続
- 地震情報リストが使える
- 手動更新も使える
- UIがエラー画面にならない

---

# 9. 起動時接続不可

P2P接続先を一時的に不正にする、またはモックで接続失敗させる。

確認:
- backendは起動継続
- `/health` は原則healthy
- status API は disconnected/reconnecting
- Magnitude UI はポーリングで利用可能

---

# 10. shutdown確認

backend停止時に確認。

```bash
docker compose down
```

確認:
- 再接続タスクが残らない
- 例外ログが大量に出ない
- shutdownが遅延しすぎない

---

# 11. Phase3-2A/B回帰

確認:
- SSE earthquake eventが届く
- dev publishが動く
- P2P WS受信が動く
- 重複排除が動く

---

# 12. Phase3-1/Phase2回帰

確認:
- ポーリング
- 新着差分
- 震度フィルタ
- 距離ソート
- 地震タブスクロール
- 避難所一時非表示
- XSS対策

---

# 13. 合格条件

- 切断時に再接続する
- 指数バックオフが効く
- 高速リトライしない
- status APIで状態確認できる
- SSE status eventが流れる
- frontendで状態が分かる
- 切断中もポーリングで継続
- backendが落ちない
- shutdownが正常
- Phase3-2A/B/Phase3-1/Phase2に回帰なし

---

# 14. 検証結果報告フォーマット

```md
# Magnitude Phase3-2C 検証結果

## 結果
PASS / FAIL

## 確認内容
- status API:
- 正常接続ログ:
- 切断/再接続:
- バックオフ:
- frontend状態表示:
- SSE status:
- ポーリングフォールバック:
- 起動時接続不可:
- shutdown:
- Phase3-2A/B回帰:
- Phase3-1/Phase2回帰:

## 発見した問題
- なし / あり

## 修正内容
- なし / あり
```

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

---

# Magnitude Phase3-2C 検証結果

## 結果
PASS

## 確認内容
- status API: PASS（`/api/earthquakes/realtime/status` が `enabled/state/source/last_connected_at/last_event_at/last_error/retry_count/next_retry_at` を返す）
- 正常接続ログ: PASS（`P2P WS connect attempt`、`P2P WS connected`、`SSE client connected/disconnected`、dev publishログを確認）
- 切断/再接続: PASS（単体テストで切断後 `reconnecting`、再接続成功後 `connected` と `retry_count=0` を確認）
- バックオフ: PASS（単体テストで 5秒→10秒→20秒、`next_retry_at` が未来時刻、無限高速リトライなしを確認）
- frontend状態表示: PASS（SSE `status` eventで「接続中」「再接続中（自動更新で継続）」「切断中（自動更新）」へ更新）
- SSE status: PASS（curlで `event: status` と `event: earthquake` が同じstreamで共存することを確認）
- ポーリングフォールバック: PASS（status eventでreconnecting/disconnectedでもリスト・最終更新表示を維持し、e2eでポーリング回帰通過）
- 起動時接続不可: PASS（単体テストで接続失敗時も例外を外へ漏らさずreconnecting/backoffへ遷移。実backend `/health` はP2P接続中でもhealthy）
- shutdown: PASS（backend restart時に再接続/SSEタスク由来の大量例外なし。全サービス停止は避け、backend restartで停止/起動を確認）
- Phase3-2A/B回帰: PASS（SSE earthquake、dev publish、P2P正規化、重複排除テスト通過）
- Phase3-1/Phase2回帰: PASS（ポーリング、新着差分、震度フィルタ、距離ソート、XSS、ピン増殖防止のe2e通過）

## 発見した問題
- あり: 初回バックオフが仕様の5秒ではなく10秒から始まる計算になっていた。
- あり: `next_retry_at` が次回再試行予定時刻ではなく現在時刻になっていた。
- あり: 接続後に切断した場合、reconnecting中でも `retry_count` が0のままになりstatus APIで再接続試行中と分かりにくかった。
- あり: SSE新規接続直後に現在のrealtime状態が流れず、curl/frontend初期表示でP2P状態を即確認しづらかった。

## 修正内容
- あり: バックオフ計算を 5→10→20→最大60秒へ修正。
- あり: `next_retry_at` を現在時刻ではなく `now + delay` のJST ISO8601へ修正。
- あり: 切断/接続失敗後は初回retryとして `retry_count=1` にし、再接続成功時に0へリセット。
- あり: SSE接続開始時に現在のrealtime statusを `event: status` として即時送信。
- あり: frontend e2eにSSE status event表示とポーリングフォールバック表示の検証を追加。
- あり: backend単体テストに指数バックオフ、future `next_retry_at`、再接続成功reset、通常切断後retry、SSE status publishを追加。

## 実行コマンド
- `venv/bin/pytest tests/test_earthquake_source_p2p_ws.py tests/test_earthquake_realtime_service.py tests/test_earthquake_event_bus.py`: 15 passed
- `npx playwright test e2e/magnitude-sse.spec.js`: 6 passed
- `npx playwright test e2e/magnitude-polling.spec.js e2e/magnitude-intensity-filter.spec.js e2e/magnitude-sort.spec.js e2e/magnitude-sse.spec.js`: 25 passed
- `docker compose restart backend`: backend停止/起動を確認
- `docker compose ps`: backend healthy、frontend起動を確認
- `curl -i "http://127.0.0.1:8080/api/earthquakes/realtime/status"`: HTTP 200、status JSONを確認
- `curl -i -N --max-time 5 "http://127.0.0.1:8080/api/earthquakes/stream"`: `event: status` を確認
- `curl -s -X POST "http://127.0.0.1:8080/api/dev/earthquakes/publish" ...`: SSE上で `event: earthquake` 共存を確認

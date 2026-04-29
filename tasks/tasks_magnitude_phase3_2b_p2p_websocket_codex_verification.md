# Magnitude Phase3-2B 検証指示書（CODEX）
## P2P WebSocket接続 + 正規化 + 重複排除

## 目的

backendがP2P WebSocketから地震情報を受信し、既存EarthquakeEvent形式へ正規化してSSE経由でfrontendに届けられることを検証する。

---

## 検証対象

```text
P2P WebSocket接続
code=551受信
正規化
backend重複排除
SSE publish
frontend反映
```

---

# 1. 事前確認

```bash
docker compose ps
curl -s "http://localhost:8080/api/earthquakes?days=1" | python3 -m json.tool
curl -N "http://localhost:8080/api/earthquakes/stream"
```

確認:
- backend healthy
- 既存API 200
- SSE接続可能

---

# 2. WebSocketサービス起動確認

backendログを確認。

```bash
docker compose logs -f backend
```

確認:
- `P2P WS connecting`
- `connected` または接続試行ログ
- 接続失敗時もbackendが落ちない

---

# 3. モックWebSocket検証

可能であればP2P WebSocketをモックして、`code=551` 相当のイベントを流す。

確認:
- イベントを受信する
- EarthquakeEvent形式へ正規化される
- event_busへpublishされる
- SSEへ流れる
- frontendに表示される

---

# 4. 正規化確認

以下を含むデータで確認。

```text
震源名
発生時刻
緯度経度
深さ
マグニチュード
最大震度
津波情報
```

確認:
- `occurred_at` がJST ISO8601
- `magnitude` が数値またはnull
- `lat/lng` が数値またはnull
- `max_intensity` が既存UIで扱える形式
- `source` が `p2p_ws` 等で分かる

---

# 5. 座標なし確認

lat/lngなしイベントを流す。

確認:
- API/SSE処理が落ちない
- リストには表示可能
- ピンは出ない、または既存仕様どおり
- console errorなし

---

# 6. 重複排除確認

同じイベントを複数回流す。

確認:
- backendでduplicate skippedログ
- SSEへ重複publishされない、またはfrontendでupsertされる
- リスト/ピンが増殖しない
- NEW件数が増殖しない

---

# 7. ポーリング重複確認

同じ地震が `/api/earthquakes` とWebSocketの両方から来るケースを確認。

確認:
- event_id/fingerprintで重複しない
- リスト/ピンが1件のまま

---

# 8. 実P2P接続疎通

実接続可能な場合のみ確認。

確認:
- 接続が確立する
- 受信がない時間でも接続維持または再接続待機する
- backendが安定している

実地震が来ない場合、受信確認はモックで代替してよい。

---

# 9. frontend回帰

確認:
- SSEイベントがリスト/ピンに反映
- NEWバッジ
- 震度フィルタ
- 距離ソート
- 地震タブUI
- ポーリング

---

# 10. 異常系

```text
不正JSON
未知code
正規化不能
WebSocket切断
```

確認:
- backendが落ちない
- ログに残る
- ポーリングで機能継続

---

# 11. 合格条件

- P2P WSサービスが起動する
- `code=551` を正規化できる
- SSE経由でfrontendに届く
- 重複排除が効く
- 異常データで落ちない
- 接続失敗でもbackendが落ちない
- Phase3-2A/Phase3-1に回帰なし

---

# 12. 検証結果報告フォーマット

```md
# Magnitude Phase3-2B 検証結果

## 結果
PASS / FAIL

## 確認内容
- WSサービス起動:
- モック受信:
- 正規化:
- 座標なし:
- 重複排除:
- ポーリング重複:
- 実P2P疎通:
- frontend回帰:
- 異常系:

## 発見した問題
- なし / あり

## 修正内容
- なし / あり
```

---

# Magnitude Phase3-2B 検証結果

## 結果
PASS

## 確認内容
- WSサービス起動: PASS（backend startupで `EarthquakeRealtimeService started`、`P2P WS connecting`、`P2P WS connected` を確認）
- モック受信: PASS（`code=551` JSONを `P2PWebSocketClient._handle_message()` に流し、EarthquakeEvent形式のcallback呼び出しを確認）
- 正規化: PASS（震源名、発生時刻JST ISO8601、lat/lng、深さ、M、最大震度、津波情報、`source=p2p_ws` を単体テストで確認）
- 座標なし: PASS（P2Pの `latitude=-200` / `longitude=-200` は `lat/lng=null`、リスト表示可能なイベントとして正規化）
- 重複排除: PASS（backend realtime serviceが同じ `event_id` を2回目以降publishせず、`duplicate skipped` ログを出すことを確認）
- ポーリング重複: PASS（REST取得済みと同じ外部IDのWS/SSEイベントは同じ `event_id` でupsertされ、リスト/NEWが増殖しない）
- 実P2P疎通: PASS（`wss://api.p2pquake.net/v2/ws` へ接続成功。検証中に実地震受信はなかったため受信はモックで代替）
- frontend回帰: PASS（SSE反映、NEW、震度フィルタ、距離ソート、ポーリング回帰e2eが通過）
- 異常系: PASS（不正JSON、未知code、正規化不能をskipし、backendは継続）

## 発見した問題
- あり: WS側event_idが `p2p-ws-{外部ID}`、REST側event_idが `{外部ID}` になっており、同じP2P地震がポーリングとWSで重複表示される余地があった。
- あり: `duplicate skipped`、未知code、不正JSONのログがdebug中心で、通常ログレベルでは検証しづらかった。

## 修正内容
- あり: 外部IDがあるWSイベントはREST APIと同じ `event_id` を使うよう修正し、`source=p2p_ws` で由来を区別。
- あり: backend重複排除ログをINFOへ引き上げ、不正JSONはWARNING、未知code/受信ログはINFOで記録。
- あり: `tests/test_earthquake_source_p2p_ws.py` を追加し、正規化・座標なし・fingerprint・不正JSON・未知codeを検証。
- あり: `tests/test_earthquake_realtime_service.py` を追加し、publish、重複skip、300件seen cache、stopを検証。
- あり: `e2e/magnitude-sse.spec.js` にREST取得済みevent_idのSSE upsert回帰を追加。

## 実行コマンド
- `docker compose restart backend`: backend再起動、新規WSサービス反映
- `docker compose ps`: backend healthy、frontend起動を確認
- `docker logs --tail 160 evacuation-navi-backend`: `P2P WS connecting` / `P2P WS connected` を確認
- `curl -s "http://127.0.0.1:8080/api/earthquakes?days=1"`: HTTP 200、`items` 配列を確認
- `curl -i -N --max-time 3 "http://127.0.0.1:8080/api/earthquakes/stream"`: HTTP 200、`Content-Type: text/event-stream`、`: ping` を確認
- `venv/bin/pytest tests/test_earthquake_source_p2p_ws.py tests/test_earthquake_realtime_service.py tests/test_earthquake_event_bus.py`: 11 passed
- `npx playwright test e2e/magnitude-sse.spec.js`: 5 passed
- `npx playwright test e2e/magnitude-polling.spec.js e2e/magnitude-intensity-filter.spec.js e2e/magnitude-sort.spec.js e2e/magnitude-sse.spec.js`: 24 passed

## 参照
- P2P WebSocket APIの公開・`code=551` 地震情報の構造確認: https://p2pquake.hatenablog.jp/entry/2020/09/02/003546
- P2P JSON API v2 / WebSocket利用例確認: https://qiita.com/akikaki_san/items/d110ababd9687b7be6e7

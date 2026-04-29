# Magnitude Phase3-2A 検証指示書（CODEX）
## SSE基盤 + Frontend EventSource + ダミーイベント

## 目的
backend SSE基盤と frontend EventSource 接続が正しく動作し、ダミー地震イベントが Magnitude UI に反映されることを検証する。

このフェーズでは外部P2P WebSocket接続は検証対象外。

## 検証対象

```text
/api/earthquakes/stream SSE
dev publish endpoint
frontend EventSource購読
既存Magnitude UIへの反映
```

---

# 1. 事前確認

```bash
docker compose ps
curl -s "http://localhost:8080/api/earthquakes?days=1" | python3 -m json.tool
```

確認:
- backend healthy
- frontend起動
- 既存 `/api/earthquakes` が200

---

# 2. SSE接続確認

```bash
curl -N "http://localhost:8080/api/earthquakes/stream"
```

確認:
- 接続が維持される
- `Content-Type: text/event-stream`
- keepaliveが流れる
- 即切断されない

---

# 3. dev publish確認

別ターミナルからダミー地震をpublishする。

```bash
curl -X POST "http://localhost:8080/api/dev/earthquakes/publish" \
  -H "Content-Type: application/json" \
  -d '{
    "event_id": "dev-001",
    "occurred_at": "2026-04-29T12:34:56+09:00",
    "epicenter_name": "東京湾",
    "lat": 35.5,
    "lng": 139.8,
    "depth_km": 30,
    "magnitude": 4.8,
    "max_intensity": "4",
    "tsunami_info": "津波の心配なし",
    "source": "dev"
  }'
```

endpoint名が異なる場合は実装に合わせて読み替える。

確認:
- SSE側に `event: earthquake` が流れる
- `data` JSONが正しい
- 複数クライアントに届く

---

# 4. Frontend反映確認

手順:
1. ブラウザでMagnitudeモードON
2. 地震タブを表示
3. dev publishで新規event_idを送る

確認:
- リストに新規地震が追加される
- 地図ピンが追加される
- NEWバッジが表示される
- 新着件数が増える
- 接続状態が「接続中」になる

---

# 5. 重複排除確認

同じevent_idを複数回publishする。

確認:
- リストが重複しない
- ピンが重複しない
- NEWが増殖しない
- イベントハンドラが多重登録されない

---

# 6. フィルタ/ソート連携

手順:
1. 震度4以上を選択
2. `max_intensity=3` のイベントをpublish
3. `max_intensity=4` のイベントをpublish
4. 近い順を選択した状態でもpublish

確認:
- 震度条件外は表示されない
- 震度条件内は表示される
- 近い順が維持される
- 距離表示が壊れない

---

# 7. Magnitude OFF時確認

手順:
1. Magnitude ON
2. SSE接続を確認
3. Magnitude OFF
4. dev publish

確認:
- OFF後にUIへ反映されない
- EventSourceがcloseされる
- 地震ピンが残らない
- console errorがない

---

# 8. 不正データ確認

可能なら以下を送る。

```text
不正JSON
lat/lng null
max_intensity null
epicenter_name に <img src=x onerror=alert(1)>
```

確認:
- JSエラーなし
- XSS発火なし
- lat/lng null はリストのみ、または既存仕様どおり

---

# 9. ポーリング回帰

確認:
- Phase3-1の自動更新が継続
- SSE追加でポーリングが多重化しない
- 手動更新も動く

---

# 10. 連続操作・増殖確認

手順:
1. Magnitude ON/OFFを10回
2. dev publishを複数回
3. タブ切替、フィルタ、ソートを混ぜる

確認:
- EventSourceが増殖しない
- DOM/ピン/リストが増殖しない
- 選択状態は1件
- 通常系console errorなし

---

# 11. 合格条件

- SSE接続が維持される
- dev publishイベントがfrontendに届く
- リスト/ピン/NEWへ反映される
- 同じevent_idが重複しない
- Magnitude OFFでEventSourceが閉じる
- フィルタ/ソート/ポーリングに回帰なし
- XSS対策が維持される
- DOM/ピン/イベントが増殖しない

---

# 12. 検証結果報告フォーマット

```md
# Magnitude Phase3-2A 検証結果

## 結果
PASS / FAIL

## 確認内容
- SSE接続:
- dev publish:
- Frontend反映:
- 重複排除:
- フィルタ/ソート連携:
- OFF時close:
- 不正データ:
- ポーリング回帰:
- 連続操作:

## 発見した問題
- なし / あり

## 修正内容
- なし / あり
```

---

# Magnitude Phase3-2A 検証結果

## 結果
PASS

## 確認内容
- SSE接続: PASS（`/api/earthquakes/stream` が HTTP 200、`text/event-stream`、初回 `: ping`、接続維持）
- dev publish: PASS（`POST /api/dev/earthquakes/publish` が `{"published":true}` を返し、接続中SSEへ `event: earthquake` を配信）
- Frontend反映: PASS（EventSource受信でリスト追加、地図NEWリング、NEWバッジ、新着件数、接続状態表示をe2e確認）
- 重複排除: PASS（同じ `event_id` はupsertされ、リスト/NEWが増殖しない）
- フィルタ/ソート連携: PASS（震度4以上フィルタ、近い順、距離表示を維持）
- OFF時close: PASS（Magnitude OFFでEventSource close、リスト/ピン消去、OFF後/古い接続の遅延イベントを無視）
- 不正データ: PASS（不正JSONを無視、HTML文字列はescape、lat/lng nullはリスト表示のみでJSエラーなし）
- ポーリング回帰: PASS（Phase3-1ポーリング、手動更新、API失敗復帰、visibility制御の回帰テスト通過）
- 連続操作: PASS（ON/OFF連続時にEventSource/DOM/ピンの増殖なし）

## 発見した問題
- あり: close済みの古いEventSourceから遅延イベントが来た場合、再ON後のUIに混ざる余地があった。
- あり: 既存ポーリングe2eの `/api/earthquakes**` モックが新設SSE URLも拾い、RESTポーリング回数の検証を汚染していた。

## 修正内容
- あり: EventSourceのonopen/message/errorで現在の接続インスタンスとactive状態を確認し、古い接続からのイベントを無視。
- あり: `e2e/magnitude-sse.spec.js` を追加し、SSE受信、重複排除、フィルタ/ソート、OFF時close、不正データを検証。
- あり: `tests/test_earthquake_event_bus.py` を追加し、複数購読、unsubscribe、recent 100件保持を検証。
- あり: `e2e/magnitude-polling.spec.js` にSSE専用モックを追加し、RESTポーリング回帰テストの意図を維持。

## 実行コマンド
- `docker compose ps`: backend/frontend 起動を確認
- `curl -s "http://127.0.0.1:8080/api/earthquakes?days=1"`: HTTP 200、`items` 配列を確認
- `curl -i -N --max-time 3 "http://127.0.0.1:8080/api/earthquakes/stream"`: HTTP 200、`Content-Type: text/event-stream`、`: ping` を確認
- `curl -s -X POST "http://127.0.0.1:8080/api/dev/earthquakes/publish" ...`: `{"published":true,"event_id":"dev-002"}` とSSE `event: earthquake` を確認
- `venv/bin/pytest tests/test_earthquake_event_bus.py tests/test_config_change_notifier.py`: 7 passed
- `npx playwright test e2e/magnitude-polling.spec.js e2e/magnitude-intensity-filter.spec.js e2e/magnitude-sort.spec.js e2e/magnitude-sse.spec.js`: 23 passed

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

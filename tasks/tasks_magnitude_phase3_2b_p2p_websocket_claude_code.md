# Magnitude Phase3-2B 実装指示書（Claude Code）
## P2P WebSocket接続 + 正規化 + 重複排除

## 目的

backendからP2P地震情報 WebSocket に接続し、受信した地震情報を OnHighGround2 内部の EarthquakeEvent 形式へ正規化し、Phase3-2Aで作成したSSE基盤へpublishする。

---

## 背景

Phase3-2Aで、backend SSE基盤とfrontend EventSourceの経路は構築済み。  
Phase3-2Bでは、外部リアルタイムソースとしてP2P WebSocketを接続する。

P2P地震情報は JSON API / WebSocket API を提供しており、低遅延受信にはWebSocketが利用できる。

---

## 実装スコープ

### やること

- backendにP2P WebSocket購読サービスを追加
- 地震情報 `code=551` を中心に受信
- 受信JSONを既存EarthquakeEvent形式に正規化
- `event_id` / `fingerprint` による重複排除
- EarthquakeEventBusへpublish
- SSE経由でfrontendへ反映
- 起動/停止をbackendライフサイクルに統合
- 基本ログを出す

### やらないこと

- 本格的なバックオフ/監視
- 津波情報 `code=552` の本格連携
- 緊急地震速報の警告UI
- 避難誘導連動
- 通知/音声

---

## Backend追加構成案

```text
backend/app/services/earthquake_source_p2p_ws.py
backend/app/services/earthquake_realtime_service.py
```

既存構成に合わせてよい。

---

## P2P WebSocket接続

接続先・購読方法はP2P公式仕様に従う。実装時に現在の仕様を確認すること。

要件:

- User-Agent等が必要な場合は設定する
- 接続失敗時にbackend全体を落とさない
- 受信対象はまず地震情報 `code=551`
- 未知のcodeはログに出して無視してよい

---

## 正規化形式

既存 `/api/earthquakes` と同じ形式に揃える。

```json
{
  "event_id": "p2p-ws-xxxxx",
  "occurred_at": "2026-04-29T12:34:56+09:00",
  "epicenter_name": "東京湾",
  "lat": 35.5,
  "lng": 139.8,
  "depth_km": 30,
  "magnitude": 4.8,
  "max_intensity": "4",
  "tsunami_info": "津波の心配なし",
  "source": "p2p_ws",
  "raw": {}
}
```

### 座標がない場合

```text
lat/lng: null
リストには表示可能
ピンは既存仕様どおり表示しない
```

---

## event_id方針

外部データに安定IDがある場合:

```text
event_id = "p2p-ws-" + 外部ID
```

安定IDがない場合:

```text
event_id = fingerprintベース
```

fingerprint例:

```text
occurred_at + epicenter_name + magnitude + max_intensity
```

Python例:

```python
fingerprint = sha1(f"{occurred_at}|{epicenter_name}|{magnitude}|{max_intensity}".encode()).hexdigest()
event_id = f"p2p-ws-{fingerprint[:16]}"
```

---

## 重複排除

リアルタイム化では以下の重複が起きる。

- WebSocketで同じイベントを複数回受信
- WebSocketとポーリングで同じイベントを受信
- 再接続後に同じイベントを再受信

backend側で直近event_idを保持して重複publishを防ぐ。

保持件数:

```text
直近300件程度
```

frontend側にも既存のevent_id upsertがあるため、二重防御にする。

---

## ライフサイクル

FastAPI起動時にリアルタイムサービスを開始する。

```text
startup:
  start EarthquakeRealtimeService

shutdown:
  stop EarthquakeRealtimeService
```

既存のapp初期化方式に合わせること。

### 失敗時

- P2P WebSocket接続に失敗してもbackendは起動継続
- エラーログを出す
- Phase3-1ポーリングで機能継続

---

## ログ

最低限以下を出す。

```text
P2P WS connecting
P2P WS connected
P2P WS disconnected
P2P WS reconnect scheduled
earthquake event received
earthquake event published
duplicate skipped
normalize failed
```

ログレベルは既存 `logging.level` 設定に合わせる。

---

## SSE連携

```text
P2P WS receive
  ↓
normalize
  ↓
dedupe
  ↓
event_bus.publish
  ↓
SSE
  ↓
frontend
```

---

## エラー処理

- 不正JSONを受けてもサービス継続
- 想定外codeは無視
- 正規化失敗はログ出力してskip
- 接続切断はPhase3-2Cで本格化するが、最低限再接続してよい

---

## 実装順序

1. P2P WebSocket仕様を確認
2. `earthquake_source_p2p_ws.py` を追加
3. 正規化関数を実装
4. event_id/fingerprint生成を実装
5. backend側重複排除を実装
6. EarthquakeEventBusへpublish
7. FastAPI lifecycleへ組み込み
8. ログ追加
9. ダミー/モックWebSocketで検証
10. 実P2P WebSocketで疎通確認

---

## 完了条件

- backendがP2P WebSocketへ接続できる
- `code=551` 地震情報を受信できる
- 既存EarthquakeEvent形式へ正規化できる
- event_id/fingerprintで重複排除できる
- 受信イベントがSSE経由でfrontendに届く
- frontendでNEW/フィルタ/ソート/ピン表示が動く
- P2P接続失敗でもbackendが落ちない
- ポーリングフォールバックが壊れない

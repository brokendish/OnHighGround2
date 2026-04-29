# Magnitude Phase3-2A 実装指示書（Claude Code）
## SSE基盤 + Frontend EventSource + ダミーイベント

## 目的
OnHighGround2 backend 内に地震リアルタイム配信用のSSE基盤を追加し、frontend の Magnitude UI が `EventSource` でイベントを受信できる状態を作る。

このフェーズでは外部P2P WebSocketには接続しない。まずは OnHighGround2 内部のリアルタイム配信経路を固める。

## スコープ

### やること
- backendに地震イベントバスを追加
- `GET /api/earthquakes/stream` を追加
- 開発/検証用のダミー地震イベントpublish機構を追加
- frontendでEventSource購読を追加
- SSE受信イベントを既存Magnitudeデータへupsertする
- NEWバッジ、新着件数、震度フィルタ、距離ソート、ピン表示と連動する
- SSE切断時も既存ポーリングは維持する

### やらないこと
- P2P WebSocket接続
- 外部リアルタイムデータ正規化
- 本格的な再接続バックオフ
- 津波情報のリアルタイム連携
- 避難誘導連動
- 通知/音声

## Backend追加構成案

```text
backend/app/api/earthquakes_stream.py
backend/app/services/earthquake_event_bus.py
backend/app/services/earthquake_dev_publisher.py
```

既存構成に合わせて変更してよい。

## EarthquakeEventBus仕様

最小機能:

```text
publish(event)
subscribe()
unsubscribe()
recent events keep 100
```

VPSメモリを考慮し、無制限保持しないこと。

## SSE API

```http
GET /api/earthquakes/stream
```

ヘッダ:

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

イベント形式:

```text
event: earthquake
data: {"event_id":"dev-001","occurred_at":"2026-04-29T12:34:56+09:00","epicenter_name":"東京湾","lat":35.5,"lng":139.8,"depth_km":30,"magnitude":4.8,"max_intensity":"4","tsunami_info":"津波の心配なし","source":"dev"}
```

keepaliveとして `: ping` または `event: ping` を定期送信してよい。

## 開発用ダミーpublish

検証用に、ダミー地震イベントをpublishできる仕組みを追加する。

候補:

```http
POST /api/dev/earthquakes/publish
```

本番運用で危険にならないよう、環境変数や設定で無効化できること。

## Frontend実装

MagnitudeモードON時に接続開始、OFF時に切断する。

```js
let magnitudeEventSource = null;

function startMagnitudeStream() {
  stopMagnitudeStream();
  magnitudeEventSource = new EventSource('/api/earthquakes/stream');
  magnitudeEventSource.addEventListener('earthquake', (event) => {
    const item = JSON.parse(event.data);
    handleRealtimeEarthquake(item);
  });
  magnitudeEventSource.onerror = () => {
    // 状態表示のみ。ポーリングは継続。
  };
}

function stopMagnitudeStream() {
  if (magnitudeEventSource) {
    magnitudeEventSource.close();
    magnitudeEventSource = null;
  }
}
```

## SSE受信時の処理

```text
既存itemsへupsert
  ↓
event_idで重複排除
  ↓
newEventIdsへ追加
  ↓
現在の震度フィルタ適用
  ↓
現在のソート適用
  ↓
リスト/ピン再描画
```

重要:
- 同じevent_idは重複追加しない
- ポーリングで取得済みのevent_idがSSEで来ても増殖させない
- SSEで来たイベントがポーリングで後から来ても増殖させない

## UI表示

地震タブ内にSSE接続状態を表示する。

```text
リアルタイム: 接続中
リアルタイム: 再接続中
リアルタイム: 切断中（自動更新で継続）
```

Phase3-2Aでは再接続ロジックは最小でよい。ブラウザEventSourceの自動再接続に任せてよい。

## ポーリングとの関係

Phase3-1のポーリングは消さない。

```text
SSE接続中: ポーリングは保険として継続
SSE切断中: ポーリングで継続
```

## セキュリティ/XSS

SSEで受信した地震情報も外部由来として扱う。`epicenter_name`、`tsunami_info`、`source` は既存と同じエスケープ処理を通す。

## エッジケース

- SSE接続前にMagnitude OFF
- SSE接続中にOFF
- OFF後にイベントが来る
- 同じevent_idが複数回来る
- 不正JSONが来る
- lat/lng null
- max_intensity null/不明

すべてJSエラーなしで処理すること。

## 実装順序

1. backend EarthquakeEventBusを追加
2. `/api/earthquakes/stream` SSEを追加
3. dev publish endpointを追加
4. curlでSSE受信確認
5. frontend EventSource接続を追加
6. SSE受信イベントを既存Magnitude itemsへupsert
7. NEW/フィルタ/ソート/ピン再描画と連動
8. SSE接続状態表示を追加
9. Magnitude OFF時にEventSourceをclose
10. e2eテスト追加

## 完了条件

- `/api/earthquakes/stream` に接続できる
- dev publishした地震イベントがSSEでfrontendへ届く
- 受信イベントがリスト/ピンに反映される
- NEWバッジ/新着件数が動く
- 震度フィルタ/距離ソートが維持される
- 同じevent_idが重複しない
- Magnitude OFFでEventSourceがcloseされる
- ポーリング機能が壊れない
- DOM/ピン/イベントが増殖しない
- 通常系でconsole errorがない

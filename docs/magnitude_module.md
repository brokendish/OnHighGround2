# OnHighGround2 Magnitude モジュール開発成果まとめ

## 概要

OnHighGround2 において、地震情報の取得・可視化・リアルタイム更新を行う「Magnitude モジュール」を新規実装した。

本モジュールは以下の目的で構築された。

```text
・地震発生状況の可視化
・現在地からの距離把握
・新着地震の即時認識
・将来的な避難誘導連携の基盤構築
```

---

## 開発フェーズ

### Phase1: MVP

```text
・/api/earthquakes による地震情報取得
・地図へのピン表示
・地震リスト表示
```

---

### Phase2: UX強化

```text
Phase2-1: 避難所一時非表示
Phase2-2: 新着差分ハイライト
Phase2-3: 距離ソート
Phase2-4: 震度フィルタ
```

#### UI改善

```text
・地震ポップアップ → 地震タブへ移行
・スマホでも地図が常時見える構成へ改善
・スクロール干渉（地図が動く問題）を解消
```

---

### Phase3-1: 定期更新ポーリング

```text
・60秒間隔の自動更新
・visibilitychange対応
・手動更新との競合防止
・非同期競合防止（_loadInFlight）
```

---

### Phase3-2A: SSE基盤

```text
・EarthquakeEventBus 実装
・/api/earthquakes/stream (SSE)
・EventSource によるフロント接続
・ダミーイベントによる検証
```

---

### Phase3-2B: P2P WebSocket連携

```text
・P2P WebSocket接続
・code=551 地震情報受信
・EarthquakeEvent形式へ正規化
・event_id統一（RESTと一致）
・重複排除（backend + frontend）
```

---

### Phase3-2C: 再接続・運用強化

```text
・指数バックオフ（5→10→20→60秒）
・接続状態管理（connected / reconnecting）
・status API 実装
・SSE status event 配信
・ポーリングフォールバック維持
```

---

## アーキテクチャ

```text
P2P WebSocket
      ↓
Realtime Service（backend）
      ↓
Event Bus
      ↓
SSE (/api/earthquakes/stream)
      ↓
Frontend (EventSource)
      ↓
Magnitude UI
```

---

## 技術的ポイント

### 1. 重複排除戦略

```text
・event_id を REST / WS で統一
・backend: 直近イベントでフィルタ
・frontend: upsert方式
```

---

### 2. 非同期安全設計

```text
・_loadInFlight による多重取得防止
・古いSSEイベントの無視
・遅延レスポンス上書き防止
```

---

### 3. フォールバック設計

```text
SSE正常:
  低遅延更新

SSE切断:
  ポーリングで継続
```

---

### 4. UI設計

```text
・地震情報はタブUIへ統合
・地図を常に表示
・ポップアップは補助UI
```

---

## テスト

### 単体テスト

```text
・EventBus
・RealtimeService
・P2P正規化
```

### E2E

```text
・ポーリング
・SSE
・フィルタ
・ソート
・新着判定
・タブUI
```

---

## 現在の到達点

```text
・地震情報のリアルタイム表示
・新着即時反映
・スマホ対応UI
・外部接続耐障害設計
```

---

## 今後の拡張

```text
・津波情報（code=552）連携
・避難誘導（OnHighGround2コア）連動
・通知（音/プッシュ）
・履歴保存
・複数ソース統合（気象庁APIなど）
```

---

## 総括

Magnitude モジュールは、

```text
「見る」 → 「気づく」 → 「行動する」
```

のうち、

```text
見る・気づく
```

をリアルタイムで実現する基盤として完成した。

今後は OnHighGround2 の本来目的である

```text
危険 → 安全 → 避難
```

への連携を進めることで、実用的な防災システムへ発展させる。

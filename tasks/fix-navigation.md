# CLAUDE.md — OnHighGround ナビゲーションバグ修正タスク

## ⚠️ 重要：このファイルを最初に読むこと

このファイルはClaude Codeへの作業指示書です。
指示の範囲を厳守し、**ナビゲーション修正以外の改修は行わないこと**。

---

## プロジェクト概要

**OnHighGround** — 災害避難ナビゲーションシステム  
危険地点 → 安全な高台 → 避難ルート案内 を行うWebアプリ。

技術スタック: OpenStreetMap / OSRM routing / FastAPI / Web client / Docker

---

## 今回の作業スコープ

### 🔴 修正対象バグ（2件）

#### Bug #1: 目的地到着判定が機能しない
- 目的地を通過しても到着と判定されない
- フィールドテストで確認済み

#### Bug #2: 再ルート検索が機能しない
- ルートを外れても再ルートが発動しない
- 現状はルートを表示するだけでナビとして機能していない

### 📌 背景・重要情報

- **以前は正常に動作していた**（フィールドテスト済み）
- 「位置情報の精度対応」を実施した後から悪化した
- → 精度フィルタリング処理が到着判定・再ルート判定を阻害している可能性が高い

---

## 実装前に必ず行うこと（計画フェーズ）

コードを書く前に、以下を実施してCHECKLISTに回答すること。

### CHECKLIST

```
[ ] 1. git log で「精度対応」に関するコミットを特定した
[ ] 2. git diff でそのコミットの変更ファイルを確認した
[ ] 3. 位置情報を処理するメインファイルを特定した（例: navigation.js, location.js）
[ ] 4. watchPosition / getCurrentPosition のどちらを使っているか確認した
[ ] 5. 到着判定ロジックのコードを見つけた（距離閾値・条件式）
[ ] 6. 再ルート判定ロジックのコードを見つけた
[ ] 7. 精度フィルタ（accuracy条件）がどこに入っているか確認した
[ ] 8. 修正方針を日本語で箇条書きにまとめた（実装前に出力すること）
```

計画を出力してから修正に入ること。

---

## 修正方針（ガイドライン）

以下は修正の参考方針。コードの実態に合わせて適用すること。

### 原則

```
精度フィルタは「地図描画・軌跡表示」にのみ適用する。
到着判定・再ルート判定には精度条件を入れない。
```

### 到着判定の修正指針

```javascript
// ❌ 悪い例：精度条件が到着判定を妨げている
if (accuracy < THRESHOLD && distToDest < ARRIVAL_RADIUS) {
    triggerArrival();
}

// ✅ 良い例：到着判定は精度に依存しない
if (distToDest < ARRIVAL_RADIUS) {
    triggerArrival();
}
```

### 再ルート判定の修正指針

```javascript
// ❌ 悪い例：精度フィルタで位置更新がスキップされ再ルートが発動しない
const onPositionUpdate = (pos) => {
    if (pos.coords.accuracy > ACCURACY_THRESHOLD) return; // ← これが再ルートも止めている
    checkRerouting(pos);
};

// ✅ 良い例：ナビ判定は精度フィルタの外で実行
const onPositionUpdate = (pos) => {
    const { latitude, longitude, accuracy } = pos.coords;

    // 到着・再ルート判定は常に実行
    checkArrival(latitude, longitude);
    checkRerouting(latitude, longitude);

    // 精度が低い場合は地図描画のみスキップ
    if (accuracy > ACCURACY_THRESHOLD) return;
    updateMapDisplay(latitude, longitude);
};
```

### watchPosition の確認事項

```javascript
// maximumAge が大きすぎるとリアルタイム更新が止まる
navigator.geolocation.watchPosition(handler, errorHandler, {
    enableHighAccuracy: true,
    timeout: 10000,
    maximumAge: 0  // ← 精度対応でここを変更していたら 0 に戻す
});
```

---

## デバッグログの追加（修正と同時に実施）

修正箇所にログを追加し、フィールドテストで確認できるようにすること。

```javascript
// 到着判定にログを追加
console.log(`[NAV] dist_to_dest=${distToDest.toFixed(1)}m, accuracy=${accuracy.toFixed(1)}m`);
if (distToDest < ARRIVAL_RADIUS) {
    console.log(`[NAV] ✅ ARRIVAL DETECTED`);
}

// 再ルート判定にログを追加
console.log(`[NAV] off_route=${isOffRoute}, reroute_triggered=${rerouteTriggered}`);
```

---

## やってはいけないこと（DO NOT）

- ❌ UIデザインを変更しない
- ❌ ルーティングエンジン（OSRM連携）を変更しない
- ❌ ハザードレイヤーや標高表示の処理を変更しない
- ❌ バックエンド（FastAPI）を変更しない
- ❌ 精度対応の全削除はしない（UI表示への適用は残す）
- ❌ 無関係なリファクタリングをしない

---

## 完了条件

修正後、以下を満たしていることをコードレベルで確認・報告すること。

```
[ ] 到着判定ロジックに accuracy 条件が含まれていない
[ ] 再ルート判定ロジックに accuracy 条件が含まれていない
[ ] watchPosition の maximumAge が適切な値になっている
[ ] 主要な判定箇所にデバッグログが追加されている
[ ] 変更ファイルの一覧と変更内容のサマリーを日本語で出力した
```

---

## 作業完了時の報告フォーマット

```
## 修正完了レポート

### 特定した根本原因
（精度対応のどのコードが問題だったか）

### 変更したファイル
- ファイル名: 変更内容

### 未解決の懸念点
（あれば記載）

### フィールドテストで確認すべきこと
1. ...
2. ...
```

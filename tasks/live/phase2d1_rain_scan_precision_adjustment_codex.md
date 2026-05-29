# Phase 2-D.1 雨雲面スキャン精度調整 検証

## 目的

Phase 2-D.1 実装が期待どおり動作しているか検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証項目

### 1. 構文確認

実施:

- Python compile
- import check

確認:

- SyntaxErrorなし
- ImportErrorなし

---

### 2. Docker起動確認

実施:

```bash
docker compose up -d
```

確認:

- backend healthy
- frontend healthy

---

### 3. Candidate生成確認

雨雲面スキャンログを確認すること。

確認内容:

```text
rain_scan candidate
```

が出力されること。

特に千葉周辺を確認すること。

期待:

```text
prefecture=千葉県
```

を含む candidate が存在する。

---

### 4. 重心計算確認

ログから以下を確認すること。

期待:

- tile center固定ではない
- centroid座標が出力される
- 強雨域側へ寄っている

確認例:

```text
centroid=(35.xxxx,140.xxxx)
```

---

### 5. 都道府県判定確認

期待:

- centroidベース判定
- 千葉雨域 → 千葉県
- 沖縄雨域 → 沖縄県

誤判定がないこと。

---

### 6. 危険地域ランキング確認

API:

```text
/live
```

または

```text
/api/live/summary
```

相当の出力を確認。

期待:

千葉県付近がランキングへ出現する。

---

### 7. 回帰確認

確認対象:

- 危険地域カード
- 雨雲ランキング
- キキクルランキング

期待:

既存表示が壊れていない。

---

### 8. false-safe契約確認

確認:

threshold未満の領域が danger 扱いされていないこと。

期待:

- weakのみ → 非表示
- unknown → 非表示
- threshold未満 → 非表示

---

### 9. areas上限確認

期待:

```python
MAX_AREAS = 5
```

維持。

出力件数が5件以内であること。

---

### 10. rankingロジック回帰確認

確認:

- score算出変更なし
- ソート順変更なし

既存ランキングロジックが維持されていること。

---

## レポート

以下ファイルへまとめること。

tasks/live/live_phase2d1_rain_scan_precision_codex_verification.md

記載内容:

- 実施日時
- 検証環境
- candidate生成結果
- centroid確認結果
- 千葉検出結果
- 沖縄検出結果
- 回帰確認結果
- 最終判定

判定:

- PASS
- PASS with notes
- FAIL

のいずれかを明記すること。
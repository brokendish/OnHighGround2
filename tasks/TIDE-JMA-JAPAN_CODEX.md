---

# OnHighGround2 気象庁潮位表 年次データ管理対応 検証指示書（CODEX向け）

# 検証対象

気象庁潮位表データ管理機能。

対象:

- 全国一括DL
- 固定長パース
- normalize
- validate
- deploy
- runtime参照
- tide736撤去

---

# 検証項目

## 1. dataset定義

確認:

```
TIDE-JMA-JAPAN-2026-001
が管理画面に表示されること。
```

---

## 2. DL確認

管理画面から全国取得。

確認:

```
data_lake/raw/japan/tide/jma/2026/
```

に複数 txt が生成されること。

例:

```
hTK.txt
hOS.txt
hNG.txt
```

---

## 3. station master

確認:

```
station_master.json
```

存在。

必須項目:

- station_code
- station_name
- lat
- lon

---

## 4. パース検証

確認:

- 24時間取得
- 日付取得
- station取得
- 欠損処理
- 異常行スキップ

固定長崩れ時に **ERROR ログ出力**。

---

## 5. normalize

確認:

```
tide_hourly_2026.jsonl
tide_extremes_2026.jsonl
```

生成。

### hourly件数確認

期待:

```
365 * 24 * station数
または
366 * 24 * station数
```

---

## 6. validate

異常データ投入時:

- deploy不可
- ERRORログ出力

確認。

---

## 7. deploy

確認:

```
data_runtime/backend/tide/jma/2026/
```

へ配置。

manifest.json 存在。

---

## 8. tide_service

確認:

- 外部APIアクセス無し
- runtime読込のみ
- 最寄station解決
- 現在潮位取得
- 次回満潮干潮取得

---

## 9. tide736削除確認

確認:

- tide736 import無し
- tide736 service無し
- tide736 endpoint無し
- fallback無し
- 未使用config無し

grep推奨。

---

## 10. frontend回帰

確認:

- 潮汐UI表示
- JSエラー無し
- API 200
- 既存レイアウト維持

---

## 11. Docker回帰

確認:

```
docker compose up
```

正常。

backend restart loop 無し。

---

## 12. ログ確認

INFO:

- tide runtime loaded
- nearest tide station resolved

確認。

ERROR:

- invalid tide format

異常系で確認。

---

## 13. パフォーマンス

確認:

- runtimeロード過大メモリ無し
- 毎request全件読み込み禁止
- station index化確認

---

## 14. 最終判定

以下満たせば PASS:

- 全国潮位取得成功
- runtime参照成功
- tide736完全削除
- frontend/backend正常
- docker正常
- 回帰なし

---

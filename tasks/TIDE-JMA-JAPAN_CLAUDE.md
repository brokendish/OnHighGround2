---

# OnHighGround2 気象庁潮位表 年次データ管理対応 指示書（Claude Code向け）

## 目的

現在 tide736 API に依存している潮汐取得を廃止し、  
気象庁の公式潮位表テキストデータを OnHighGround2 のデータ管理基盤へ統合する。

最終的に：

- 管理画面から年次潮位データを取得
- normalize / validate / deploy 対応
- runtime データから潮位取得
- tide736 完全撤去

を実現する。

---

# 実装フェーズ

## Phase1
潮位データセット基盤追加

## Phase2
管理画面から全国一括DL

## Phase3
固定長パーサー

## Phase4
normalize / validate / deploy

## Phase5
tide_service runtime切替

## Phase6
tide736削除

---

# 実装要件

## 1. dataset 定義追加

追加:

```
dataset_id:
TIDE-JMA-JAPAN-2026-001
表示名:
潮位表（気象庁・全国・2026年）
想定属性:
{
  "category": "tide",
  "source": "jma",
  "region": "japan",
  "year": 2026
}
```

---

## 2. ディレクトリ構成

追加:

```
data_lake/raw/japan/tide/jma/2026/
data_lake/normalized/japan/tide/jma/2026/
data_lake/validated/japan/tide/jma/2026/

data_runtime/backend/tide/jma/2026/
```

---

# 3. 管理画面

## 3.1 全国一括DL専用

データ管理画面に以下を追加する。

- 年度選択
- 全国一括ダウンロード
- normalize
- validate
- deploy

都道府県単位の選択UIは作らない。

理由:  
潮位観測地点は都道府県境界と一対一対応しないため、  
都道府県別管理にすると将来的に複雑化する。

## 3.2 ダウンロード仕様

指定年度の気象庁潮位表テキストデータを、全国地点分まとめて取得する。

保存先:

```
data_lake/raw/japan/tide/jma/{year}/
```

ファイル名:

```
h{station_code}.txt
```

例:

```
hTK.txt
hYK.txt
hOS.txt
```

## 3.3 station master

station_master.json も全国単位で保持する。

都道府県属性は任意項目としてよいが、  
処理上の主キーにはしない。

主キーは station_code とする。

---

# 4. ダウンロード仕様

保存:

```
data_lake/raw/japan/tide/jma/2026/hTK.txt
```

形式:

```
h<station>.txt
```

---

# 5. 固定長パーサー

新規:

```
backend/app/services/tide_parser.py
```

実装:

```
TIDE_FORMAT = {
    "line_start": 6,
    "value_width": 3,
    "hourly_count": 24,
}
```

固定値ベタ書き禁止。

---

# 6. normalize

生成:

```
tide_hourly_2026.jsonl
tide_extremes_2026.jsonl
```

JSONL形式。

### hourly schema

```
{
  "station": "TK",
  "datetime": "2026-01-01T00:00:00+09:00",
  "tide_cm": 123
}
```

### extremes schema

```
{
  "station": "TK",
  "date": "2026-01-01",
  "high_tides": [],
  "low_tides": []
}
```

---

# 7. validate

validate 追加。

検証:

- 365/366日
- 24時間件数
- 欠損率
- station存在確認
- datetime重複禁止

validate失敗時は deploy不可。

---

# 8. deploy

deploy先:

```
data_runtime/backend/tide/jma/2026/
```

manifest.json 作成。

---

# 9. tide_service.py

変更:

Before  
tide736 API

After  
runtime JSONL

---

## 検索仕様

現在地から最寄station検索。  
距離計算: haversine可。

### 返却例

```
{
  "station": "TOKYO",
  "current_tide_cm": 132,
  "next_high_tide": {},
  "next_low_tide": {}
}
```

---

# 10. tide736 完全撤去

削除対象:

- tide736 service
- fallback処理
- 設定値
- ログ
- 不要APIコード
- 不要import

スパゲッティ化防止のため完全削除。

---

# 11. ログ

INFO:

- tide dataset download start
- tide dataset normalize completed
- tide runtime loaded
- nearest tide station resolved

ERROR:

- invalid tide format
- missing tide station
- normalize failed

---

# 12. 注意事項

- HTMLスクレイピング禁止
- フォーマット固定位置を定数化
- normalize/validate/deploy を既存dataset pipelineへ統合
- 将来2027年以降追加可能構造
- yearハードコード禁止
- runtime優先構造維持

---

# 13. 完了条件

- 管理画面から全国潮位表DL可能
- normalize/validate/deploy可能
- tide_service runtime参照
- 全国地点で潮位取得可能
- tide736コード完全削除
- frontend既存表示維持
- backend/frontend lint pass
- docker起動pass

---

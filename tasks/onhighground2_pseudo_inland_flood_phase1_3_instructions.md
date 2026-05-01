# OnHighGround2 独自内水氾濫想定区域 Phase 1〜3 実装指示書

対象：Claude Code（実装） / CODEX（検証・テスト）  
対象フェーズ：Phase 1〜3 のみ  
目的：DEMから推定した「低地・内水リスク」レイヤーを生成し、管理画面・地図表示まで統合する

---

## 0. 背景

現在の OnHighGround2 では、洪水浸水想定区域として A31 系データ、内水氾濫として A51 系データを扱っている。

しかし、A51 は東京都内でのカバーが薄く、ファイルサイズも小さいため、東京防災アプリのような「面として厚みのある水害リスク表示」にはならない。

そのため、既存 DEM から地形由来の低地・凹地・緩傾斜を抽出し、独自の推定内水リスクレイヤーを生成する。

---

## 1. 対応範囲

今回の対象は Phase 1〜3 のみ。

### Phase 1：DEMから推定内水リスクレイヤーを生成する

- DEMを読み込む
- 標高・傾斜・凹地からリスクスコアを計算する
- low / medium / high のポリゴンを生成する
- GeoJSON を出力する
- MBTiles を生成する

### Phase 2：管理画面へ統合する

- dataset_definitions.json に定義を追加する
- Admin UI の Datasets タブで状態確認できるようにする
- 生成・検証・デプロイの状態管理に接続する

### Phase 3：フロント地図へ表示する

- サイドパネルにレイヤー追加
- 右側ボタンまたは既存レイヤーUIに追加
- Martin / Vector Tile 経由で表示する
- low / medium / high を色分けする
- 「推定」である注記を表示する

---

## 2. 今回やらないこと

以下は今回の対象外。

- 避難所スコアへの反映
- ルートスコアへの反映
- ナビゲーション中の危険回避ロジックへの反映
- リアルタイム雨量との統合
- A31 / A51 の既存処理変更
- 既存 inland_flood レイヤーとの統合

今回作るレイヤーは、まず **表示専用の参考リスクレイヤー** とする。

---

## 3. レイヤー定義

### 内部レイヤー名

```txt
pseudo_inland_flood
```

### 表示名

```txt
低地・内水リスク（推定）
```

### UI注記

```txt
標高・地形から推定した参考リスクです。公式の内水氾濫想定区域ではありません。
```

### データ種別

```txt
category: hazard
layer_type: pseudo_inland_flood
source_type: generated
official: false
```

---

## 4. 出力パス方針

既存構成に合わせること。もし既存の data_lake / data_runtime 配置ルールが異なる場合は、既存実装に合わせて調整する。

### GeoJSON 出力例

```txt
data_lake/validated/tokyo/pseudo_inland_flood/pseudo_inland_flood.geojson
```

### MBTiles 出力例

```txt
data_lake/tiles/tokyo/pseudo_inland_flood/pseudo_inland_flood.mbtiles
```

### runtime 配置例

```txt
data_runtime/frontend/tiles/tokyo_pseudo_inland_flood.mbtiles
```

### Martin source layer 名

```txt
pseudo_inland_flood
```

---

## 5. Phase 1：DEM 由来レイヤー生成

### 5.1 入力データ

既存の東京都 DEM を使用する。

想定入力例：

```txt
data_lake/validated/tokyo/dem/
```

または既存実装で使用している DEM 読み込みパスに合わせる。

### 5.2 メッシュサイズ

初期実装は 50m メッシュを推奨する。

```txt
grid_size_m = 50
```

理由：

- スマホ表示で重くなりにくい
- VPS負荷を抑えられる
- 初期検証として十分な粒度

将来的に 25m へ高精細化できるよう、定数化すること。

---

## 6. リスクスコア計算

### 6.1 基本式

```txt
risk_score = elevation_score + slope_score + depression_score
```

### 6.2 elevation_score

標高が低いほど高リスクとする。

```txt
0m 以上 5m 未満      : +40
5m 以上 10m 未満     : +25
10m 以上 20m 未満    : +10
20m 以上             : +0
```

0m未満など異常値は、既存DEM処理の nodata / invalid 判定に従って除外する。

### 6.3 slope_score

傾斜が小さいほど、水が滞留しやすいとみなす。

```txt
0度 以上 1度 未満    : +25
1度 以上 3度 未満    : +15
3度 以上 5度 未満    : +5
5度 以上             : +0
```

傾斜は DEM 近傍セルから算出する。初期実装で厳密なGIS傾斜計算が難しい場合は、近傍平均との差分から近似してよい。

### 6.4 depression_score

周囲より低い場所を凹地として評価する。

```txt
周囲平均より -2.0m 以下   : +25
周囲平均より -1.0m 以下   : +15
周囲平均より -0.5m 以下   : +5
それ以外                 : +0
```

周囲平均は、対象セルを中心とした一定範囲の近傍セルから算出する。

初期値：

```txt
depression_window_m = 150
```

---

## 7. リスク分類

risk_score から risk_level を決定する。

```txt
score >= 70 : high
score >= 45 : medium
score >= 25 : low
score < 25  : none
```

`none` は GeoJSON に出力しない。

---

## 8. GeoJSON properties

各 feature には最低限以下を入れる。

```json
{
  "layer_type": "pseudo_inland_flood",
  "risk_level": "high",
  "risk_score": 82,
  "source": "dem_estimated",
  "official": false,
  "grid_size_m": 50
}
```

任意で以下も追加してよい。

```json
{
  "elevation_score": 40,
  "slope_score": 25,
  "depression_score": 17,
  "avg_elevation_m": 4.8,
  "slope_deg": 0.8,
  "depression_m": -1.2
}
```

---

## 9. ポリゴン生成

### 9.1 初期実装

50mメッシュの矩形ポリゴンとして生成してよい。

### 9.2 dissolve

可能であれば、同一 `risk_level` の隣接ポリゴンを結合する。

```txt
high 同士を結合
medium 同士を結合
low 同士を結合
```

難しい場合は初期実装では省略可。ただし、後で追加できる構造にすること。

### 9.3 buffer

表示の厚みを出すため、控えめな buffer をかける。

初期値：

```txt
low    : 5m
medium : 10m
high   : 15m
```

buffer はやりすぎないこと。過剰に広げると公式データのように見えてしまい、信頼性を損なう。

---

## 10. MBTiles 生成

tippecanoe を使用して MBTiles を生成する。

例：

```bash
tippecanoe \
  -o pseudo_inland_flood.mbtiles \
  -l pseudo_inland_flood \
  -zg \
  --drop-densest-as-needed \
  --extend-zooms-if-still-dropping \
  pseudo_inland_flood.geojson
```

既存プロジェクトに tippecanoe ラッパーや tiles 生成関数がある場合は、それを使用する。

---

## 11. Martin 配信

### 11.1 martin.yaml 追加

既存の Martin 設定に合わせて、以下相当の MBTiles を追加する。

```txt
data_runtime/frontend/tiles/tokyo_pseudo_inland_flood.mbtiles
```

### 11.2 /tiles/catalog 確認

`/tiles/catalog` に `pseudo_inland_flood` が出るようにする。

注意：

- 存在しないパスを martin.yaml に入れない
- 一時ファイル `.tmp.mbtiles` を catalog に出さない
- source layer 名とフロント側の layer 名を一致させる

---

# Phase 2：管理画面統合

## 12. dataset_definitions.json 追加

`data_lake/registry/dataset_definitions.json` に以下相当を追加する。

既存スキーマに合わせて必要項目を補完すること。

```json
{
  "dataset_id": "TOKYO-PSEUDO-INLAND-FLOOD-001",
  "region": "tokyo",
  "category": "hazard",
  "layer_type": "pseudo_inland_flood",
  "display_name": "低地・内水リスク（推定）",
  "description": "DEM標高・傾斜・凹地から推定した参考内水リスク。公式の内水氾濫想定区域ではありません。",
  "source_type": "generated",
  "official": false,
  "routing_profile": null
}
```

---

## 13. pipeline_service 連携

既存のデータセット処理に合わせて、推定レイヤー生成処理を追加する。

### 13.1 追加する処理名案

```txt
generate_pseudo_inland_flood
```

または既存の `normalize` / `validate` / `deploy` フローに自然に入る名前にする。

### 13.2 推奨ステータス

```txt
generated
validated
deployed
failed
```

既存の normalize_status / validation_status / deploy_status に合わせる場合は、以下の意味で扱う。

```txt
normalize_status = generated
validation_status = validated
deploy_status = deployed
```

### 13.3 Validate 条件

最低限以下を確認する。

- GeoJSON が存在する
- features が 1件以上ある
- risk_level が `low / medium / high` のいずれか
- risk_score が数値
- official が false
- geometry が Polygon または MultiPolygon

---

## 14. Admin UI 表示

Datasets タブで以下が確認できること。

```txt
低地・内水リスク（推定）
```

表示項目：

- dataset_id
- region
- category
- layer_type
- display_name
- generated / validated / deployed 状態
- ファイルサイズ
- 更新日時

### UI注記

詳細または説明欄に以下を出す。

```txt
このデータはDEMから推定した参考リスクです。公式の内水氾濫想定区域ではありません。
```

---

# Phase 3：フロント表示

## 15. レイヤーUI追加

既存のハザードレイヤーUIに以下を追加する。

```txt
低地・内水リスク
```

ラベルに「推定」を含めてもよい。

```txt
低地・内水リスク（推定）
```

---

## 16. フロントレイヤー定義

既存の `VECTOR_TILE_SOURCES` または同等のレイヤー定義に追加する。

例：

```js
pseudo_inland_flood: {
  id: 'pseudo_inland_flood',
  label: '低地・内水リスク（推定）',
  region: 'tokyo',
  sourceLayer: 'pseudo_inland_flood',
  type: 'vector',
  official: false
}
```

実際の定義形式は既存コードに合わせること。

---

## 17. 表示スタイル

risk_level で色分けする。

推奨：

```txt
low    : 水色系 / opacity 0.18
medium : 黄色系 / opacity 0.28
high   : 赤系   / opacity 0.38
```

最大 opacity は 0.45 を超えないこと。

道路名や避難所が読めなくなる表示は禁止。

---

## 18. 凡例追加

凡例に以下を追加する。

```txt
低地・内水リスク（推定）
  high   : 高
  medium : 中
  low    : 低
```

注記：

```txt
※標高・地形から推定した参考リスクです。公式の内水氾濫想定区域ではありません。
```

---

## 19. 表示条件

初期表示は OFF でよい。

理由：

- 推定レイヤーなので、公式ハザードと混同させない
- まずはユーザ操作で確認できるようにする

ただし、将来的に「災害モード」では ON にできるよう拡張しやすくすること。

---

## 20. 既存レイヤーとの関係

既存 `inland_flood` / A51 とは別レイヤーとして扱う。

```txt
inland_flood           = 公式または取得済み内水氾濫データ
pseudo_inland_flood    = DEMから推定した参考リスク
```

両者を混同しないこと。

UI上もできれば別名にする。

---

# Claude Code 向け作業指示

## 21. 実装方針

以下の順番で実装してください。

1. 既存の DEM 読み込み処理・タイル生成処理・dataset 管理処理を確認
2. `pseudo_inland_flood` の dataset 定義を追加
3. DEM から GeoJSON を生成する処理を追加
4. Validate 処理を追加
5. MBTiles 生成・runtime deploy 処理を追加
6. Martin catalog に出るように設定
7. フロントのレイヤー定義を追加
8. サイドパネル・凡例に表示
9. 注記を表示
10. 既存の flood / inland_flood / tsunami / storm_surge 表示を壊していないことを確認

---

## 22. 実装上の重要注意

- 公式データではないため、UI上に必ず「推定」「参考リスク」と表示する
- `official: false` を GeoJSON properties と dataset 定義に入れる
- A51 の `inland_flood` とは別物として実装する
- GeoJSON直読みではなく、Vector Tile / Martin 表示を優先する
- VPSメモリを圧迫しないよう、50mメッシュから開始する
- 生成処理は失敗しても既存ハザード表示を壊さない
- Martin 設定に存在しない MBTiles パスを入れない
- 一時ファイルを catalog に混ぜない
- フロント側で sourceLayer 名の不一致を起こさない

---

# CODEX 検証指示

## 23. データ生成検証

以下を確認してください。

```bash
# GeoJSON 存在確認
ls -lh data_lake/validated/tokyo/pseudo_inland_flood/

# feature 数確認
python3 - <<'PY'
import json
p='data_lake/validated/tokyo/pseudo_inland_flood/pseudo_inland_flood.geojson'
with open(p, encoding='utf-8') as f:
    data=json.load(f)
print('features=', len(data.get('features', [])))
print('first_props=', data['features'][0].get('properties', {}) if data.get('features') else None)
PY
```

期待：

```txt
features が 0 件ではない
risk_level が存在する
risk_score が存在する
official が false
```

---

## 24. risk_level 検証

```bash
python3 - <<'PY'
import json, collections
p='data_lake/validated/tokyo/pseudo_inland_flood/pseudo_inland_flood.geojson'
with open(p, encoding='utf-8') as f:
    data=json.load(f)
c=collections.Counter(feat['properties'].get('risk_level') for feat in data.get('features', []))
print(c)
PY
```

期待：

```txt
low / medium / high のいずれかが存在する
想定外の risk_level がない
```

---

## 25. MBTiles 検証

```bash
ls -lh data_lake/tiles/tokyo/pseudo_inland_flood/
ls -lh data_runtime/frontend/tiles/ | grep pseudo
```

期待：

```txt
pseudo_inland_flood.mbtiles が存在する
サイズが 0 ではない
異常に巨大でない
```

目安：

```txt
初期実装では数MB〜数十MB程度を期待
100MBを大きく超える場合は要確認
```

---

## 26. Martin catalog 検証

```bash
curl -s http://localhost:8080/tiles/catalog | python3 -m json.tool | grep -i pseudo
```

期待：

```txt
pseudo_inland_flood が catalog に表示される
source layer 名が pseudo_inland_flood と一致する
```

---

## 27. フロント表示検証

ブラウザで OnHighGround2 を開き、以下を確認してください。

```txt
低地・内水リスク（推定）のON/OFFができる
ONにすると地図上に low / medium / high の面が表示される
凡例に low / medium / high が表示される
注記に「公式ではない」「推定」が表示される
```

---

## 28. 狛江・多摩川周辺の表示確認

確認地点：

```txt
狛江駅周辺
和泉多摩川周辺
多摩川沿い
```

期待：

```txt
多摩川沿い低地に面としてリスク表示が出る
A31単体よりも表示の厚みが増える
道路名・避難所マーカーが読める
スマホ操作が重くならない
```

---

## 29. 既存機能の回帰確認

以下の既存レイヤーが壊れていないこと。

```txt
洪水
津波
高潮
土砂
避難所クラスタ
地震
雨量
現在地表示
```

最低限、既存レイヤーの ON/OFF と地図表示を確認する。

---

## 30. 受け入れ条件

### 最低ライン

```txt
pseudo_inland_flood GeoJSON が生成される
MBTiles が生成される
Martin catalog に出る
フロントで ON/OFF できる
低地・内水リスク（推定）が地図上に表示される
UIに「推定」「公式ではない」旨の注記がある
既存レイヤーを壊していない
```

### 合格ライン

```txt
狛江・多摩川周辺で、A31/A51だけよりも面の厚みが明確に増える
スマホ表示でも操作不能にならない
low / medium / high が視覚的に区別できる
管理画面から状態確認できる
```

---

## 31. 作業規模感

Phase 1〜3 は中規模対応。

目安：

```txt
1〜3日程度
```

ただし、既存 DEM 処理・タイル生成・Admin UI との接続状態によってはもう少し増える可能性がある。

今回の目的は「完全な水理モデル」ではなく、まずは OnHighGround2 に不足している水害リスク表示の面の厚みを補完すること。

---

## 32. 最終方針

今回の実装では、以下を最優先とする。

```txt
1. 軽く作る
2. 壊さない
3. 推定であることを明示する
4. まず表示する
5. スコアリング統合は次フェーズに回す
```


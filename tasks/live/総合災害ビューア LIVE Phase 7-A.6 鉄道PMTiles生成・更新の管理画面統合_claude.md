# Claude 実装指示書

## 総合災害ビューア LIVE Phase 7-A.6

## 鉄道PMTiles生成・更新の管理画面統合

# 目的

現在の鉄道PMTiles生成は以下の手動作業となっている。

```bash
curl -O https://download.geofabrik.de/asia/japan-latest.osm.pbf

bash scripts/tile_build/build_railway_pmtiles.sh \
  data/japan-latest.osm.pbf
```

これはエンジニア前提であり、

```text
非エンジニアでも運用可能
```

という OnHighGround2 / LIVE の運用思想と一致しない。

そのため管理画面から

```text
OSM取得
↓
PMTiles生成
↓
検証
↓
反映
```

まで実行できるようにする。

---

# 実装方針

## 重要

PMTiles生成中に本番ファイルを上書きしないこと。

必ず

```text
tmp生成
↓
検証成功
↓
atomic rename
```

とする。

---

# Phase 7-A.6-A

## backend ジョブ化

### 新規ジョブ

例:

```text
railway_pmtiles_update
```

処理:

```text
1. japan-latest.osm.pbf ダウンロード
2. build_railway_pmtiles.sh 実行
3. PMTiles存在確認
4. サイズ確認
5. 成功時のみ反映
```

---

## ダウンロード先

例:

```text
data_lake/raw/osm/
```

保存例:

```text
japan-latest.osm.pbf
```

---

## 一時生成先

例:

```text
data_runtime/tmp/railway_pmtiles/
```

生成例:

```text
railways_japan.pmtiles.tmp
```

---

## 本番配置先

既存構成を尊重。

例:

```text
frontend/layers/railways/railways_japan.pmtiles
```

---

## 反映

必ず atomic rename を利用。

例:

```text
railways_japan.pmtiles.tmp
↓
railways_japan.pmtiles
```

---

# Phase 7-A.6-B

## 管理画面統合

データ管理画面へ追加。

項目例:

```text
全国鉄道路線 PMTiles
```

---

## 表示項目

### 現在状態

```text
PMTiles有無
ファイルサイズ
最終更新日時
```

---

### 元データ

```text
OSM PBF取得日時
PBFサイズ
```

---

### ジョブ状態

```text
未実行
実行中
成功
失敗
```

---

### ログ表示

直近100行程度表示。

例:

```text
OSMダウンロード開始
OSMダウンロード完了
PMTiles生成開始
PMTiles生成完了
反映成功
```

---

# Phase 7-A.6-C

## ワンボタン更新

管理画面に

```text
鉄道路線データ更新
```

ボタンを追加。

内部的には

```text
OSM取得
↓
生成
↓
検証
↓
反映
```

を実施する。

---

# 検証処理

反映前に最低限以下を確認。

---

## ファイル存在

```text
railways_japan.pmtiles
```

生成済みであること。

---

## サイズチェック

異常なサイズを検出。

例:

```text
1MB未満
FAIL

5GB超
FAIL
```

閾値は適宜設定。

---

## PMTilesヘッダ

可能なら取得。

```text
bounds
minzoom
maxzoom
```

---

# エラー処理

失敗時は

```text
旧PMTilesを維持
```

すること。

絶対に

```text
失敗
↓
本番ファイル消失
```

にならないこと。

---

# LIVEへの影響

更新後にページ再起動不要。

次回アクセス時から利用可能でよい。

---

# 成果物

実装後に報告すること。

```text
追加API
追加画面
追加ジョブ
保存先
ログ保存先
更新手順
既知制約
```

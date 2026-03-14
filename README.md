# OnHighGround2
津波や高潮、洪水から身を守るために現在地よりも標高の高い場所への避難経路を地図上に表示し目的地までナビゲートする。地図、標高情報、ルート検索などGoogleのサービスに依存せずにオープンソースで実装する。 可能であればオフラインでも動作させたい。

# 避難ナビゲーションシステム

津波・高潮・洪水から身を守るための避難経路案内システム。基盤地図情報（数値標高モデル）を使用して、現在地よりも標高の高い安全な避難先を検索し、経路をナビゲートします。

## Docker起動の前提データ

`docker compose up -d osrm-driving osrm-walking backend frontend` を実行する前に、以下を配置してください。

- `data/elevation.tif`（標高GeoTIFF (convert_dem.pyにて複数のXMLからtifに変換したもの)）
- `data/kanto-260214.osm.pbf`（OSRM前処理用の道路データ）
- `国土地理院避難所データ` (緊急避難場所 または 指定避難所データ)

## 機能

- 📍 **現在地取得**: ユーザーのデバイスから現在地を取得
- 🗻 **標高データ参照**: 基盤地図情報（数値標高モデル）から標高を取得
- 🎯 **避難先検索**: 現在地から標高の高い安全な避難先を検索
- 🗺️ **経路表示**: OpenStreetMapを使用して避難経路をナビゲート
- 🏫 **指定緊急避難場所表示**: 国土地理院データを地図上に重ねて表示
- ⚡ **リアルタイム計算**: 距離、所要時間、安全スコアを計算
- 📱 **レスポンシブ対応**: PC・スマホどちらでも利用可能

## システム構成

```
evacuation-navi/
├── backend/              # Python FastAPI バックエンド
│   ├── main.py          # APIサーバー
│   ├── elevation_service.py  # 標高データ処理
│   └── requirements.txt # 依存パッケージ
├── frontend/            # Webフロントエンド
│   └── index.html       # メインHTML（Leaflet.js使用)
└── data_processing/     # データ処理スクリプト
    ├── convert_dem.py   # JPGIS → GeoTIFF変換
    └── convert_evacuation_sites.py # 自治体避難施設データ変換
```

## 東京版データ基盤 v1

東京版のハザードデータ統合基盤として、`data_lake/` と責務別スクリプト群を追加しています。
このフェーズでは、ハザード解析本体ではなく、取得・正規化・検証・配信に向けた骨格の整備を優先しています。
今後の正本は `data_lake/` に一本化し、`data/` は移行期間中の旧構造として残します。

### 対象データ

- DEM
- 河川洪水
- 津波
- 高潮
- 内水
- 避難所
- 行政界
- 道路ネットワーク（OSM）

### データレイク構造

```
data_lake/
  raw/
    tokyo/
      dem/
      flood/
      tsunami/
      storm_surge/
      urban_flood/
      shelter/
      boundary/
      osm/
  normalized/
  validated/
  tiles/
  registry/
  logs/
```

`raw` は元データ正本、`normalized` は内部処理正本、`validated` は backend 参照正本、`tiles` は frontend / 配信正本です。
空白を安全扱いしない前提で、coverage と validation を段階的に扱える構成にしています。

### 新旧構造の扱い

- `data_lake/raw/...` が元データ正本
- `data_lake/normalized/...` が内部処理正本
- `data_lake/validated/...` が backend 参照正本
- `data_lake/tiles/...` が frontend / 配信正本
- `data/`, `tiles/`, `frontend/hazard/` は移行期間中の legacy 互換置き場

旧構造はこのフェーズでは削除しません。互換確認が終わるまで残します。

### 東京版パイプラインの最小実行

```bash
./init_data_lake.sh
./init_scripts.sh
./scripts/run_tokyo_pipeline.sh
```

現時点の最小 E2E は以下です。

1. registry チェック
2. shelter データの取り込み
3. shelter の normalize
4. shelter の geometry validate

生成物は `data_lake/raw/`, `data_lake/normalized/`, `data_lake/validated/` に出力され、`.gitignore` で除外されています。
ただし `data_lake/registry/` は追跡対象です。

### 既存データの移行

既存の `data/`, `tiles/`, `frontend/hazard/` にある主要データを `data_lake/` へ集約するには、以下を実行します。

```bash
./scripts/migrate/migrate_to_data_lake.sh
```

このスクリプトは最初はコピー優先で動作し、既存ファイルは上書きしません。

## セットアップ手順

### 1. データの準備

#### 基盤地図情報のダウンロード

1. [国土地理院 基盤地図情報ダウンロードサービス](https://service.gsi.go.jp/kiban/)にアクセス
2. 対象エリアを選択
3. 「基盤地図情報 数値標高モデル」を選択
4. 5mメッシュまたは10mメッシュをダウンロード（ZIP形式）
5. ZIPファイルを解凍してXMLファイルを取得

#### データの変換

```bash
# 必要なPythonパッケージをインストール
pip install rasterio numpy GDAL

# 単一XMLファイルを変換
python data_processing/convert_dem.py input.xml output.tif

# 複数XMLファイルを結合して変換
python data_processing/convert_dem.py /path/to/xml/directory output.tif --merge
```

変換後のGeoTIFFファイル（`output.tif`）をバックエンドで使用します。

#### 国土地理院 緊急避難場所データ

東京版データ基盤の最小パイプラインでは、リポジトリ内の `国土地理院避難所データ/東京/13000_1/13000_1.geojson` を raw 取り込み元として使用します。
将来的には `scripts/download/download_shelter.sh` を正式な取得処理に置き換える想定です。


### 2. 起動方法（推奨: Docker Compose）

`frontend` / `backend` / `osrm-driving` / `osrm-walking` をまとめて起動します。
移行期間中は旧 `data/` 構造でも起動できますが、正本方針は `data_lake/` です。

1. `data/` 配下に必要データを配置  
標高GeoTIFF（legacy 例: `data/elevation.tif`、canonical 例: `data_lake/validated/tokyo/dem/elevation.tif`）  
OSM PBF（例: `data/kanto-260214.osm.pbf`）

2. 起動

```bash
# 基本サービス（標高・ルーティング・フロントエンド）
docker compose up -d osrm-driving osrm-walking backend frontend

# 津波タイル配信を有効にする場合は martin も追加
docker compose up -d osrm-driving osrm-walking backend frontend martin
```

3. アクセス  
フロントエンド: `http://localhost:8080`  
バックエンドヘルス: `http://localhost:8000/health`

4. 停止

```bash
# 停止（コンテナは残す）
docker compose stop

# 停止してコンテナ/ネットワークを削除
docker compose down
```

初回起動時は OSRM 前処理（`extract` / `partition` / `customize`）が走るため、しばらく時間がかかります。  
フロントエンドは以下の自前OSRMを自動利用します。

- 車: `http://<host>:5500/route/v1`
- 徒歩: `http://<host>:5501/route/v1`

### 3. ローカル個別起動（Dockerを使わない場合）

#### バックエンド

```bash
# ディレクトリに移動
cd backend

# 仮想環境を作成（推奨）
#python -m venv venv
#source venv/bin/activate  # Windowsの場合: venv\Scripts\activate

#地理系ライブラリは 3.11〜3.12が安定。3.14は正直まだ早いので3.12を使う
/opt/homebrew/bin/python3.12 -m venv venv
source venv/bin/activate

# 依存パッケージをインストール
pip install -r requirements.txt

# backend/app.properties を編集して環境依存値を設定
# 例:
# dem.path=../data_lake/validated/tokyo/dem/elevation.tif  # Canonical
# dem.path=data/elevation.tif  # Legacy fallback
# dem.path=/path/to/your/output.tif  # ローカル実行時の例
# evacuation.sites.path=shelter_data/東京/13000_2/13000_2.csv  # Docker推奨
# evacuation.sites.path=../国土地理院避難所データ/東京/13000_2/13000_2.csv  # ローカル実行時の例
# api.host=0.0.0.0
# api.port=8000

# サーバーを起動
python main.py
```

サーバーは `backend/app.properties` の `api.host` / `api.port` で起動します。
デフォルト値では `http://localhost:8000` です。

#### フロントエンド

```bash
# シンプルなHTTPサーバーを起動（Python 3の場合）
cd frontend
python -m http.server 8080
```

ブラウザで `http://localhost:8080` にアクセスします。

**注意 1**: Dockerの`frontend`コンテナを起動している場合、`8080`はすでに使用中です。  
その場合は `python -m http.server 8081` のように別ポートを使ってください。

**注意 2**: フロントエンドはAPI接続先を自動判定します（`/api` → `http://<現在のホスト名>:8000/api` → `http://localhost:8000/api` の順に試行）。
`Failed to fetch` が出る場合は、バックエンドが起動しているか（`http://localhost:8000/health`）を先に確認してください。

## 使い方

1. **現在地を取得**
   - 「現在地を取得」ボタンをクリック
   - ブラウザの位置情報許可を承認
   - 現在地の緯度・経度・標高が表示されます

2. **検索条件を設定**
   - 移動手段: 徒歩または車
   - 最大移動距離: 避難できる最大距離（メートル）
   - 必要な標高差: 安全と判断する最低標高差（メートル）

3. **避難先を検索**
   - 「避難先を検索」ボタンをクリック
   - 条件に合った避難先候補が地図とリストに表示されます

4. **ルートを表示**
   - リストまたは地図上のマーカーをクリック
   - 現在地から避難先までの経路が表示されます

5. **津波浸水想定（東京都）レイヤーを表示**
   - 左側パネルの「津波浸水想定（東京都）」をONにすると、浸水想定ポリゴンを地図に重ねて表示します
   - 現在の地図範囲にデータがない場合は、レイヤー範囲へ自動で地図移動します
   - OFFにするとレイヤーのみ非表示になります（データは再利用されるため再ONは高速）

## API仕様

### エンドポイント

#### `GET /api/elevation`
指定座標の標高を取得

**パラメータ:**
- `lat`: 緯度（必須）
- `lon`: 経度（必須）

**レスポンス例:**
```json
{
  "lat": 35.6762,
  "lon": 139.6503,
  "elevation": 12.5,
  "unit": "meters"
}
```

#### `POST /api/evacuation`
避難目的地を検索

**リクエストボディ:**
```json
{
  "lat": 35.6762,
  "lon": 139.6503,
  "transport_mode": "walking",
  "max_distance": 2000.0,
  "min_elevation_gain": 10.0
}
```

**レスポンス例:**
```json
{
  "current_location": {
    "lat": 35.6762,
    "lon": 139.6503,
    "elevation": 5.2
  },
  "destinations": [
    {
      "lat": 35.6800,
      "lon": 139.6550,
      "elevation": 18.5,
      "elevation_gain": 13.3,
      "distance": 850.0,
      "estimated_time_minutes": 12.5,
      "safety_score": 85.2
    }
  ]
}
```

#### `POST /api/elevation-profile`
2点間の標高プロファイルを取得

**リクエストボディ:**
```json
{
  "start_lat": 35.6762,
  "start_lon": 139.6503,
  "end_lat": 35.6800,
  "end_lon": 139.6550,
  "num_points": 50
}
```

#### `GET /api/emergency-shelters`
指定緊急避難場所を取得（bboxによる範囲絞り込み対応）

**パラメータ（任意）:**
- `south`, `west`, `north`, `east`: 表示範囲
- `limit`: 最大返却件数（デフォルト5000）

**レスポンス例:**
```json
{
  "count": 120,
  "total_count": 120,
  "data": [
    {
      "name": "増戸会館",
      "address": "東京都あきる野市伊奈1157-5",
      "lat": 35.72746011,
      "lon": 139.2476138,
      "designation": "指定緊急避難場所",
      "source_file": "国土地理院避難所データ/東京/13000_2/13000_2.csv"
    }
  ]
}
```

## カスタマイズ

### 避難先選定ロジックの調整

`elevation_service.py` の以下のメソッドを編集：

- `find_evacuation_destinations()`: 検索アルゴリズム
- `_calculate_safety_score()`: 安全スコアの計算式
- `grid_size`: 検索グリッドの密度

### UIのカスタマイズ

`frontend/index.html` のスタイルやレイアウトを編集できます。

## 本番環境への展開

### セキュリティ対策

1. **CORS設定を厳密化**
   ```python
   # main.py
   allow_origins=["https://yourdomain.com"]  # 特定ドメインのみ許可
   ```

2. **HTTPS化**
   - リバースプロキシ（Nginx等）を使用
   - Let's Encryptで証明書を取得

3. **レート制限**
   - API呼び出しに制限を設定

### パフォーマンス最適化

1. **データベース化**
   - 標高データをPostGIS等のデータベースに格納
   - 空間インデックスで高速化

2. **キャッシュ**
   - Redisを使用してAPIレスポンスをキャッシュ
   - CDNでフロントエンドを配信

3. **非同期処理**
   - 重い処理をバックグラウンドで実行

### PWA化（オフライン対応）

`frontend/index.html` をPWA化することで、オフラインでも動作するようにできます：

1. Service Workerを実装
2. マニフェストファイルを追加
3. 地図タイルをキャッシュ

## トラブルシューティング

### 標高データが読み込めない

- GeoTIFFファイルのパスが正しいか確認
- ファイルの権限を確認
- `rasterio` が正しくインストールされているか確認

### 位置情報が取得できない

- ブラウザの位置情報許可を確認
- HTTPSでアクセスしているか確認（HTTP接続では制限される場合あり）

### APIにアクセスできない

- バックエンドが起動しているか確認
- CORS設定を確認
- ファイアウォール設定を確認

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。

## データソース

- 基盤地図情報（数値標高モデル）: 国土地理院
- 地図データ: OpenStreetMap contributors
- ルーティング: OSRM (Open Source Routing Machine)

## 今後の拡張案

- [x] 津波浸水想定区域データとの連携（MBTiles + Martin + Leaflet.VectorGrid によるタイル配信・表示）
- [x] 洪水浸水想定区域データとの連携（東京都・想定最大規模、A31a-2024）
- [🔵(東京のみ)] 指定避難所データベースの統合
- [ ] 複数の避難経路の比較表示
- [ ] 標高プロファイルグラフの表示
- [ ] 音声ナビゲーション
- [ ] 多言語対応
- [ ] リアルタイム災害情報の連携

## 津波浸水想定データ（東京都・神奈川県・千葉県）

津波ハザードレイヤーは **MBTiles + Martin + Leaflet.VectorGrid** によるベクタータイル配信で表示します。
GeoJSON ファイル（`frontend/hazard/`）への直接読み込みはフォールバックとして残っています。
配信用正本は今後 `data_lake/tiles/` に寄せ、`frontend/hazard/` は互換用同期先として扱います。

### データフロー

```text
国土数値情報（A40 GML）
  └─ data/processed/hazard/*.geojson   ← 処理済み GeoJSON（正規ソース）
       └─ scripts/build_tiles.py        ← tippecanoe でタイル化
            └─ tiles/*.mbtiles          ← ベクタータイル
                 └─ Martin（Docker）    ← タイル配信（/tiles/...）
                      └─ Leaflet.VectorGrid  ← フロントエンド表示
```

### データ取得元

- 国土数値情報ダウンロードサービス（津波浸水想定 A40）
- <https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A40-2024.html>

### タイル生成

```bash
# GeoJSON を tiles/*.mbtiles に変換（要 tippecanoe）
python scripts/build_tiles.py

# 暫定: frontend/hazard/ の GeoJSON を使う場合
python scripts/build_tiles.py --input frontend/hazard
```

詳細は `scripts/README.md` を参照してください。

### タイル配信サービスの起動

```bash
docker compose up -d martin
```

Martin は `tiles/` ディレクトリの `.mbtiles` ファイルを自動検出します。

### 動作確認

```bash
# タイルセット一覧（Martin が起動していれば応答あり）
curl http://localhost:8080/tiles/catalog

# 東京タイルセットの TileJSON
curl http://localhost:8080/tiles/tokyo_tsunami_A40-23_13
```

### フロントエンドの動作

フロントエンドは起動時に Martin の可用性を自動確認します。

- **Martin が起動中**: ベクタータイル（MBTiles）で表示
- **Martin が停止中**: GeoJSON ファイル（`/hazard/*.geojson`）でフォールバック表示

チェックボックスの有効/無効もデータ有無に応じて自動で切り替わります。

### 現在のタイルセット

#### 津波浸水想定

| 都県 | タイルセット ID | MBTiles ファイル |
| --- | --- | --- |
| 東京都 | `tokyo_tsunami_A40-23_13` | `tiles/tokyo_tsunami_A40-23_13.mbtiles` |
| 神奈川県 (1) | `kanagawa_tsunami_A40-16_14` | `tiles/kanagawa_tsunami_A40-16_14.mbtiles` |
| 神奈川県 (2) | `kanagawa_tsunami_A40-20_14` | `tiles/kanagawa_tsunami_A40-20_14.mbtiles` |
| 千葉県 | `chiba_tsunami_A40-18_12` | `tiles/chiba_tsunami_A40-18_12.mbtiles` |

#### 洪水浸水想定（想定最大規模）

| 都県 | タイルセット ID | MBTiles ファイル |
| --- | --- | --- |
| 東京都 | `tokyo_flood_max` | `tiles/tokyo_flood_max.mbtiles` |

洪水データのソース: 国土地理院「洪水浸水想定区域（洪水予報河川）」A31a-2024
（`国土地理院洪水予報河川データ/A31a-24_13_10_GeoJSON/20_想定最大規模/`）

`scripts/merge_flood_geojson.py` で複数の河川別 GeoJSON を結合して
`data/processed/hazard/tokyo_flood_max.geojson` を生成します。

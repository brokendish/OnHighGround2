# 外部データ要件・格納場所の整理

このドキュメントでは、OnHighGround2プロジェクトで必要となる外部データの種類、格納場所、入手方法を整理しています。

## 概要

OnHighGround2は避難ナビゲーションシステムで、以下の3種類の外部データが必須です：

| データ種類 | 用途 | 格納場所 | 説明 |
|-----------|------|---------|------|
| 標高データ | 標高計算・避難先検索 | `data/elevation.tif` | GeoTIFF形式の数値標高モデル |
| 道路データ | ルート検索（運転・徒歩） | `data/kanto-260214.osm.pbf` | OpenStreetMapの PBF形式 |
| 避難施設データ | 避難先の表示・検索 | `backend/shelter_data/` | CSV形式の緊急避難場所リスト |
| 　避難施設データは、リポジトリ直下の 国土地理院避難所データ 配下にあります。主なCSVはここです。
| 　国土地理院避難所データ/東京/13000_2/13000_2.csv
| 　国土地理院避難所データ/東京/13000_1/13000_1.csv
| 　国土地理院避難所データ/全国/mergeFromCity_2/mergeFromCity_2.csv
| 　補足: docker-compose.yml ではこのフォルダをコンテナ内 /app/shelter_data にマウントしています。

東京版データ基盤 v1 では、上記に加えて `data_lake/` を導入しています。
これは配信データの保存場所ではなく、元データ・正規化データ・検証済みデータを責務分離して管理するための基盤です。
`data/` はこのフェーズでは削除せず、legacy 扱いで互換用に残します。

### 東京版データレイクの役割

| レイヤ | 役割 | Git管理 |
|--------|------|---------|
| `data_lake/registry/` | データ台帳、マッピング、メタ情報 | 管理対象 |
| `data_lake/raw/` | 取得直後の元データ | `.gitignore` |
| `data_lake/normalized/` | CRS・属性を揃えた標準化データ | `.gitignore` |
| `data_lake/validated/` | geometry・属性・coverage確認後のデータ | `.gitignore` |
| `data_lake/tiles/` | 配信向け成果物 | `.gitignore` |
| `data_lake/logs/` | ダウンロード・変換・検証ログ | `.gitignore` |

### 東京版で管理対象にしているデータ

- DEM
- 河川洪水
- 津波
- 高潮
- 内水
- 避難所
- 行政界
- 道路ネットワーク（OSM）

台帳本体は `data_lake/registry/tokyo_hazard_registry.csv` です。

### 新旧ディレクトリの対応方針

| 旧構造 | 新しい正本 |
|--------|------------|
| `data/elevation.tif` | `data_lake/validated/tokyo/dem/elevation.tif` |
| `data/hazard/` | `data_lake/raw/tokyo/tsunami/` |
| `data/processed/hazard/*flood*.geojson` | `data_lake/normalized/tokyo/flood/` |
| `data/processed/hazard/*tsunami*.geojson` | `data_lake/normalized/tokyo/tsunami/` |
| `data/kanto-260214.osm.pbf` | `data_lake/raw/tokyo/osm/` |
| `data/osrm/driving`, `data/osrm/walking` | `data_lake/validated/tokyo/osm/` |
| `tiles/` | `data_lake/tiles/tokyo/` |
| `frontend/hazard/` | 当面は互換用同期先、正本は `data_lake/tiles/tokyo/` |

---

## 1. 標高データ（数値標高モデル）

### 概要
- **用途**: 現在地と避難先の標高検索、高さの差を計算して避難先を決定
- **形式**: GeoTIFF（地理参照付きラスター形式）
- **解像度**: 5m メッシュまたは 10m メッシュ
- **格納場所**: `data/elevation.tif`
- **ファイルサイズ**: 地域により異なる（東京都全域で数百MB程度）
- **更新頻度**: 通常は1-2年ごと

### 入手方法

#### オンライン取得（推奨）
1. [国土地理院 基盤地図情報ダウンロードサービス](https://service.gsi.go.jp/kiban/) にアクセス
2. 対象エリアを選択（例：東京都全域、関東地方など）
3. 「基盤地図情報 数値標高モデル」を選択
4. メッシュサイズを選択（5m推奨）
5. ZIP形式でダウンロード → 解凍してXMLファイルを取得

#### ダウンロード別アプローチ
- [基盤地図情報 数値標高モデル（5m メッシュ）](https://fgd.gsi.go.jp/download/menu.php) - 直接ダウンロード
- [タイルサービス](https://maps.gsi.go.jp/) - 地図表示で確認可能

### データ変換方法

**1つのXMLファイルから変換:**
```bash
cd data_processing
python convert_dem.py /path/to/downloaded.xml ../data/elevation.tif
```

**複数XMLファイルを結合して変換:**
```bash
cd data_processing
python convert_dem.py /path/to/xml/directory ../data/elevation.tif --merge
```

### 変換に必要なパッケージ
```
rasterio==1.4.3
numpy>=1.26,<2
```

### 技術仕様
- **入力形式**: JPGIS（日本地理情報標準）XML形式
- **出力形式**: GeoTIFF
- **座標系**: JGD2000（緯度経度）
- **データ型**: Float32（標高値）
- **解析モジュール**: `data_processing/convert_dem.py`の`DEMConverter`クラス

---

## 2. 道路ネットワークデータ

### 概要
- **用途**: OSRM（Open Source Routing Machine）による最短ルート検索
- **形式**: OpenStreetMap PBF（Protocol Buffer Format）
- **対象地域**: 関東地方（現在は kanto-260214.osm.pbf に固定）
- **格納場所**: `data/kanto-260214.osm.pbf`
- **ファイルサイズ**: 数百MB～1GB 程度
- **更新頻度**: 月1回程度（OpenStreetMap更新時）

### 入手方法

#### 公式ダウンロード
- [Geofabrik - OpenStreetMap Download Server](https://download.geofabrik.de/) - 複数地域の選択可能
- [BBBike](http://extract.bbbike.org/) - 任意の矩形領域を指定
- [Overpass API](https://overpass-turbo.eu/) - カスタムクエリで取得可能（小規模データ向け）

#### 関東地方データの例
```
https://download.geofabrik.de/asia/japan/kanto-latest.osm.pbf
```

### ダウンロード後のセットアップ
```bash
# データをプロジェクト配下に配置
cp /path/to/kanto-*.osm.pbf data/kanto-260214.osm.pbf
```

### オンメモリプリプロセッシング
Docker起動時に自動的に実行されます：

**運転用ルート（driving）:**
```bash
osrm-extract -p /opt/car.lua data/kanto-260214.osm.pbf
osrm-partition data/kanto-260214.osrm
osrm-customize data/kanto-260214.osrm
```

**徒歩用ルート（walking）:**
```bash
osrm-extract -p /opt/foot.lua data/kanto-260214.osm.pbf
osrm-partition data/kanto-260214.osrm
osrm-customize data/kanto-260214.osrm
```

処理済みファイルは以下に保存されます：
- `data/osrm/driving/kanto-260214.osrm*`
- `data/osrm/walking/kanto-260214.osrm*`

### インタフェース
- **運転用 OSRM**: Docker内 ポート 5500 → コンテナ内 5000
- **徒歩用 OSRM**: Docker内 ポート 5501 → コンテナ内 5001

---

## 3. 避難施設データ

### 概要
- **用途**: 指定緊急避難場所の地図表示、検索対象
- **形式**: CSV（UTF-8、カンマ区切り）
- **格納場所**: `backend/shelter_data/` 以下（自治体・地域別に構成）
- **必須カラム**: `name,site_type,designation,lat,lon`
- **指定区分**: `緊急避難場所` または `指定避難所`
- **更新頻度**: 年1回程度（自治体発表時）

### ディレクトリ構造

```
backend/shelter_data/
├── 東京/
│   ├── 13000_2/              # 東京都特別区（千代田区など）
│   │   └── 13000_2.csv       # 避難施設データ
│   └── [他の区域ID]/
├── 神奈川/
│   ├── [区域ID]/
│   │   └── *.csv
│   └── [他の区域ID]/
├── 千葉/
│   └── ...
└── [他の都道府県]/
    └── ...
```

### 入手方法

#### 公開データポータル

1. **国土地理院 緊急避難場所データ**
   - [国土地理院 基盤情報 指定緊急避難場所](https://nlftp.mlit.go.jp/ksj/#FacilityData)
   - 都道府県単位でダウンロード可能

2. **各自治体のオープンデータ**
   - [Code for Japan - Rescue Map](https://rescue-map.code4japan.org/)
   - 各都道府県の公式オープンデータサイト

3. **東京都の例**
   - [東京都オープンデータ - 指定緊急避難場所](https://catalog.data.metro.tokyo.lg.jp/)
   - [東京都デジタルサービス推進部](https://www.digital.metro.tokyo.lg.jp/)

### サポートされる入力形式

#### CSV形式
```csv
名称,種別,指定区分,緯度,経度
```

#### GeoJSON形式
```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "properties": {
        "name": "避難所A",
        "site_type": "公園",
        "designation": "緊急避難場所",
        "lat": 35.6789,
        "lon": 139.7654
      }
    }
  ]
}
```

### 設定ファイルへの登録

変換済みCSVを使用する際は、[backend/app.properties](backend/app.properties) を編集：

```properties
# 複数地域の場合はカンマ区切り
evacuation.sites.path=shelter_data/東京/13000_2/13000_2.csv,shelter_data/神奈川/14000_2/14000_2.csv
```

### 東京版データ基盤での扱い

東京版 v1 の最小パイプラインでは、GeoJSON を以下のように処理します。

1. `scripts/download/download_shelter.sh` が raw 領域へ配置
2. `scripts/normalize/normalize_shelter.py` が標準化 GeoJSON を作成
3. `scripts/validate/validate_geometry.py` が validated 領域へ昇格

将来的には属性必須チェックと coverage 判定も `validate/` に追加していきます。

---

## 4. Docker起動前のチェックリスト

システムを起動する前に、以下のファイルが配置されていることを確認してください：

```bash
# 必須ファイル確認
ls -lh data/elevation.tif           # 標高GeoTIFF（数百MB以上）
ls -lh data/kanto-260214.osm.pbf    # 道路ネットワーク（数百MB～1GB）
ls -lh backend/shelter_data/*/      # 避難施設CSV（1ファイル以上）
```

### チェック項目

- [ ] `data/` ディレクトリ存在
- [ ] `data_lake/validated/tokyo/dem/elevation.tif` が存在、または移行期間中は `data/elevation.tif` が存在
- [ ] `data/kanto-260214.osm.pbf` が存在（整合性: 数百MB以上）
- [ ] `backend/shelter_data/` ディレクトリ構造が存在
- [ ] 少なくとも1つの避難施設CSV が配置されている
- [ ] `backend/app.properties` の `dem.path` が `data_lake/validated/tokyo/dem` を指している
- [ ] `backend/app.properties` の `evacuation.sites.path` が正しいパスを指している

### 起動コマンド

```bash
docker compose up -d osrm-driving osrm-walking backend frontend
```

---

## 5. 開発環境のセットアップ（Docker不使用）

### 必要なシステムツール

```bash
# macOS (Homebrew)
brew install gdal rasterio

# Ubuntu/Debian
sudo apt-get install gdal-bin python3-gdal python3-rasterio
```

### Python依存パッケージ

backend:
```
fastapi==0.104.1
uvicorn[standard]==0.24.0
rasterio==1.4.3
numpy>=1.26,<2
python-multipart==0.0.6
pydantic==2.5.0
```

data_processing:
```
rasterio==1.4.3
numpy>=1.26,<2
GDAL  # オプション
```

### パッケージインストール

```bash
# backend 環境
cd backend
pip install -r requirements.txt

# data_processing 環境
cd data_processing
pip install rasterio numpy
```

---

## 6. トラブルシューティング

### 「標高データが見つかりません」エラー

**原因確認:**
```bash
# 1. ファイルが存在するか確認
ls -lh data/elevation.tif
echo $DEM_FILE_PATH  # Docker環境
cat backend/app.properties | grep dem.path  # ローカル実行時

# 2. ファイルが有効なGeoTIFFか確認
gdalinfo data/elevation.tif

# 3. パーミッション確認
stat data/elevation.tif
```

**解決方法:**
1. XMLから再変換：`python data_processing/convert_dem.py ...`
2. ファイルパスを修正：`backend/app.properties` の `dem.path` を確認
3. Docker マウント確認：`docker-compose.yml` の volumes セクション

### OSRM のプリプロセッシングに時間がかかる

**進捗確認:**
```bash
# ログ確認
docker logs evacuation-navi-osrm-driving
docker logs evacuation-navi-osrm-walking
```

**キャッシュの再作成:**
```bash
# 処理済みファイルを削除して再実行
rm -rf data/osrm/
docker compose restart osrm-driving osrm-walking
```

### 避難施設データが表示されない

**確認事項:**
```bash
# 1. CSVファイルが存在するか
ls -lh backend/shelter_data/

# 2. CSVが正しい形式か
head -5 backend/shelter_data/*/***/*.csv

# 3. app.properties のパス設定
grep evacuation.sites.path backend/app.properties
```

---

## 参考リンク

### データソース
- [国土地理院 基盤地図情報](https://fgd.gsi.go.jp/)
- [国土地理院 数値標高モデル](https://www.gsi.go.jp/kankyou/kankyou62-2.html)
- [OpenStreetMap](https://www.openstreetmap.jp/)
- [Geofabrik Download Server](https://download.geofabrik.de/)

### 技術ドキュメント
- [OSRM - Open Source Routing Machine](http://project-osrm.org/)
- [GeoTIFF](https://www.osgeo.org/projects/geotiff/)
- [Rasterio Documentation](https://rasterio.readthedocs.io/)

### 日本独自フォーマット
- [JPGIS - 日本地理情報標準](https://www.gsi.go.jp/kankyou/kankyou62-1.html)
- [基盤地図情報 仕様書](https://nlftp.mlit.go.jp/ksj/#rel_kiban)

---

最終更新: 2026年2月15日

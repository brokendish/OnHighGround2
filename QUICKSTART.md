# クイックスタートガイド

このガイドでは、避難ナビゲーションシステムを最速で動かす方法を説明します。

## 前提条件

- Docker / Docker Compose
- Python 3.9以上（ローカル実行の場合）
- Webブラウザ（Chrome、Firefox、Safari等）

## Docker で起動する（推奨）

### 1. データの準備

以下のファイルを事前に用意してください。

| ファイル | 配置先 | 説明 |
| -------- | ------ | ---- |
| `elevation.tif` | `data_lake/validated/tokyo/dem/elevation.tif` | 国土地理院 5m DEM |
| `kanto-*.osm.pbf` | `data/kanto-260214.osm.pbf` | OpenStreetMap 関東版 |
| `tokyo_shelter.geojson` | `data_lake/normalized/tokyo/shelter/tokyo_shelter.geojson` | 指定緊急避難場所 |
| `tokyo_flood_max.geojson` | `data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson` | 洪水浸水想定（想定最大規模） |

洪水浸水想定データが存在しない場合もバックエンドは起動しますが、ハザード判定は行われません。

### 2. Docker Compose で起動

```bash
docker compose up -d
```

### 3. アクセス

ブラウザで `http://localhost:8080` にアクセス。

地図上で「現在地を設定」→「避難先を検索」を実行すると:

- 現在地の洪水ハザード判定結果（危険 / 安全）が表示される
- ハザード安全な避難先が推奨候補として表示される
- 色分けされたマーカーで候補地点が地図に表示される（金=推奨、緑=安全、橙=ハザード範囲内）

---

## ローカル実行（Docker 不使用）

### 1. バックエンドの起動

```bash
cd backend
pip install -r requirements.txt
python main.py
```

`backend/app.properties` でパスを確認・調整してください。

```properties
dem.path=../data_lake/validated/tokyo/dem
evacuation.sites.path=../data_lake/normalized/tokyo/shelter
hazard.flood.path=../data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson
```

動作確認:

```bash
curl http://localhost:8000/health
```

### 2. フロントエンドの起動

```bash
cd frontend
python -m http.server 8080
```

ブラウザで `http://localhost:8080` にアクセス。

---

## API 動作確認

### ヘルスチェック

```bash
curl http://localhost:8000/health
```

### 避難先検索（例: 新宿）

```bash
curl -X POST http://localhost:8000/api/evacuation \
  -H "Content-Type: application/json" \
  -d '{"lat": 35.6938, "lon": 139.7034, "transport_mode": "walking"}'
```

レスポンス例:

```json
{
  "hazard_status": {
    "is_danger": true,
    "hazards": ["flood"]
  },
  "recommended": {
    "name": "新宿中央公園",
    "distance_m": 850,
    "elevation_m": 45.2,
    "hazard_safe": true,
    "reason": "洪水ハザードエリア外で、最も安全スコアが高い避難先です。"
  },
  "destinations": [...]
}
```

---

## データ入手先

| データ | 入手先 |
| ------ | ------ |
| DEM（5m メッシュ） | [国土地理院 基盤地図情報](https://fgd.gsi.go.jp/download/menu.php) |
| OSM（関東） | [Geofabrik](https://download.geofabrik.de/asia/japan.html) |
| 指定緊急避難場所 | [国土地理院 指定緊急避難場所データ](https://www.gsi.go.jp/bousaichiri/hinanbasho.html) |
| 洪水浸水想定 | [国土交通省 重ねるハザードマップ / 各都道府県](https://disaportal.gsi.go.jp/) |

---

## 東京版データ基盤（data_lake パイプライン）

データ取得・正規化・検証のパイプラインを試す場合:

```bash
./init_data_lake.sh
./init_scripts.sh
./scripts/run_tokyo_pipeline.sh
```

成功すると以下が生成されます:

- `data_lake/raw/tokyo/shelter/tokyo_shelter.geojson`
- `data_lake/normalized/tokyo/shelter/tokyo_shelter.geojson`
- `data_lake/validated/tokyo/shelter/tokyo_shelter.geojson`

詳細は `scripts/README.md` を参照してください。

---

## トラブルシューティング

### 「標高データが見つかりません」

1. `data_lake/validated/tokyo/dem/elevation.tif` が存在するか確認
2. `backend/app.properties` の `dem.path` が正しいか確認

### 「APIにアクセスできません」

1. バックエンドが起動しているか確認: `curl http://localhost:8000/health`
2. CORS設定を確認
3. ブラウザのコンソールでエラーを確認

### ハザード判定が常に「安全」になる

`data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson` が存在するか確認してください。
ファイルがない場合はハザード判定をスキップして全候補を「安全」扱いにします。
バックエンドのログに `Hazard data not found` が出ている場合はパスを確認してください。

### 避難先が見つからない / 候補が0件

- 避難所 GeoJSON (`tokyo_shelter.geojson`) が存在するか確認
- バックエンドログに `Loaded N shelters` が表示されているか確認
- 避難所データがない場合は格子状グリッド検索にフォールバックします

### 「位置情報が取得できません」

1. ブラウザの位置情報許可を確認
2. HTTPSでアクセスしているか確認（ローカルでは `http://localhost` は許可されます）

---

詳細は `README.md` を参照してください。

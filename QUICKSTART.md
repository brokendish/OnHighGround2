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
| `tokyo_flood_max.geojson` | `data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson` | 洪水浸水想定（表示用・666K ポリゴン） |
| `tokyo_flood_check.geojsonl` | `data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl` | 洪水浸水想定（判定用 GeoJSONL・ストリーミング読み込み） |
| `tsunami_tokyo.geojson` | `data_lake/normalized/tokyo/tsunami/tsunami_tokyo.geojson` | 津波浸水想定（東京都） |

ハザードデータが存在しない場合もバックエンドは起動しますが、該当ハザードの判定は `unknown` 扱いになります。
tsunami は `app.properties` の `hazard.tsunami.targets=tokyo` で制御します（デフォルト: 東京のみ）。

### 2. Docker Compose で起動

```bash
docker compose up -d
```

### 3. アクセス

ブラウザで `http://localhost:8080` にアクセス。

地図上で「現在地を設定」→「避難先を検索」を実行すると:

- 現在地の洪水・津波ハザード判定結果（危険 / 安全 / 未判定）が表示される
- ハザード安全な避難先が推奨候補として表示される
- 色分けされたマーカーで候補地点が地図に表示される（金=推奨、緑=安全、橙=ハザード範囲内、グレー=未判定）
- 候補カードおよびポップアップにハザードごとの判定根拠（`hazard_assessment`）が表示される

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
hazard.flood.enabled=true
hazard.flood.check_path=../data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl
hazard.tsunami.dir=../data_lake/normalized/tokyo/tsunami
hazard.tsunami.targets=tokyo
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
    "hazards": ["flood", "tsunami"]
  },
  "recommended": {
    "name": "新宿中央公園",
    "distance": 850,
    "elevation": 45.2,
    "hazard_safe": true,
    "hazard_assessment": {
      "flood": "outside",
      "tsunami": "outside"
    },
    "reason": "危険区域外、現在地より24m高い、徒歩10分圏内、安全候補の中で最も安全性スコアが高い"
  },
  "destinations": [
    {
      "name": "新宿中央公園",
      "hazard_safe": true,
      "hazard_assessment": {
        "flood": "outside",
        "tsunami": "outside"
      }
    }
  ]
}
```

`hazard_safe` は `true`（安全）/ `false`（危険）/ `null`（データ未ロードで未判定）の3値を返します。
`hazard_assessment` には各ハザードの個別判定結果（`"inside"` / `"outside"` / `"unknown"`）が含まれます。

---

## データ入手先

| データ | 入手先 |
| ------ | ------ |
| DEM（5m メッシュ） | [国土地理院 基盤地図情報](https://fgd.gsi.go.jp/download/menu.php) |
| OSM（関東） | [Geofabrik](https://download.geofabrik.de/asia/japan.html) |
| 指定緊急避難場所 | [国土地理院 指定緊急避難場所データ](https://www.gsi.go.jp/bousaichiri/hinanbasho.html) |
| 洪水浸水想定 | [国土交通省 重ねるハザードマップ / 各都道府県](https://disaportal.gsi.go.jp/) |
| 津波浸水想定 | [国土数値情報（津波浸水想定 A40）](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A40-2024.html) |

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

### 候補がすべてグレー（安全性未判定）になる

ハザードデータがロードできていない可能性があります。まず `/health` で確認してください。

```bash
curl http://localhost:8000/health
```

`hazard_loaded` が `[]` なら flood/tsunami データが読み込めていません。
`hazard_polygon_counts` でポリゴン数が 0 の場合もパスを確認してください。

- flood（判定用）: `data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl` が存在するか
- flood（表示用）: `data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson` が存在するか
- tsunami: `data_lake/normalized/tokyo/tsunami/tsunami_tokyo.geojson` が存在するか
- `backend/app.properties` の `hazard.flood.enabled=true` / `hazard.flood.check_path` / `hazard.tsunami.dir` が正しいか

データが存在しない場合、バックエンドは起動しますが `hazard_safe: null`（未判定）を返します。
これは v1.2 以降の正しい挙動です（データなし = 安全扱いではなく未判定）。

### 避難先が見つからない / 候補が0件

- 避難所 GeoJSON (`tokyo_shelter.geojson`) が存在するか確認
- バックエンドログに `Loaded N shelters` が表示されているか確認
- 避難所データがない場合は格子状グリッド検索にフォールバックします

### 「位置情報が取得できません」

1. ブラウザの位置情報許可を確認
2. HTTPSでアクセスしているか確認（ローカルでは `http://localhost` は許可されます）

---

詳細は `README.md` を参照してください。

最終更新: 2026-03-15

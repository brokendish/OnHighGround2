# OnHighGround2
津波や高潮、洪水から身を守るために現在地よりも標高の高い場所への避難経路を地図上に表示し目的地までナビゲートする。地図、標高情報、ルート検索などGoogleのサービスに依存せずにオープンソースで実装する。 可能であればオフラインでも動作させたい。

# 避難ナビゲーションシステム

津波・高潮・洪水から身を守るための避難経路案内システム。基盤地図情報（数値標高モデル）を使用して、現在地よりも標高の高い安全な避難先を検索し、経路をナビゲートします。

## 機能

- 📍 **現在地取得**: ユーザーのデバイスから現在地を取得
- 🗻 **標高データ参照**: 基盤地図情報（数値標高モデル）から標高を取得
- 🎯 **避難先検索**: 現在地から標高の高い安全な避難先を検索
- 🗺️ **経路表示**: OpenStreetMapを使用して避難経路をナビゲート
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
    └── convert_dem.py   # JPGIS → GeoTIFF変換
```

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

### 2. バックエンドのセットアップ

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

# main.pyを編集してDEMファイルのパスを設定
# DEM_PATH = "/path/to/your/output.tif"

# サーバーを起動
python main.py
```

サーバーは `http://localhost:8000` で起動します。

### 3. フロントエンドの起動

```bash
# シンプルなHTTPサーバーを起動（Python 3の場合）
cd frontend
python -m http.server 8080
```

ブラウザで `http://localhost:8080` にアクセスします。

**注意**: フロントエンドの `index.html` でAPIのベースURLが正しく設定されているか確認してください：

```javascript
const API_BASE_URL = 'http://localhost:8000/api';
```

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

- [ ] 浸水想定区域データとの連携
- [ ] 指定避難所データベースの統合
- [ ] 複数の避難経路の比較表示
- [ ] 標高プロファイルグラフの表示
- [ ] 音声ナビゲーション
- [ ] 多言語対応
- [ ] リアルタイム災害情報の連携



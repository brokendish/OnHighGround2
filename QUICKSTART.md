# クイックスタートガイド

このガイドでは、避難ナビゲーションシステムを最速で動かす方法を説明します。

## 前提条件

- Python 3.9以上
- pip
- Webブラウザ（Chrome、Firefox、Safari等）

## 5分でスタート

## 東京版データ基盤を先に試す

今回追加した東京版 v1 のデータ基盤は、避難所データだけで最小 E2E を確認できます。

```bash
./init_data_lake.sh
./init_scripts.sh
./scripts/run_tokyo_pipeline.sh
```

成功すると以下が生成されます。

- `data_lake/raw/tokyo/shelter/tokyo_shelter.geojson`
- `data_lake/normalized/tokyo/shelter/tokyo_shelter.geojson`
- `data_lake/validated/tokyo/shelter/tokyo_shelter.geojson`

このステップでは、ダウンロード・正規化・検証の責務分離と、`registry` の整合確認が主目的です。

### 既存データを data_lake に寄せる

旧 `data/`, `tiles/`, `frontend/hazard/` を data_lake 中心に整理する場合は、以下を実行します。

```bash
./scripts/migrate/migrate_to_data_lake.sh
```

この移行はコピー優先で、旧構造はそのまま残ります。

### 1. データの準備（サンプル用）

開発・テスト用に小さな範囲のデータを準備します。

```bash
# 国土地理院からデータをダウンロード
# https://fgd.gsi.go.jp/download/menu.php

# 例: 東京都心部の5mメッシュ（任意の1メッシュ）
# ダウンロード → 解凍 → XMLファイルを取得
```

### 2. データの変換

```bash
# プロジェクトのルートディレクトリで
cd data_processing

# 必要なパッケージをインストール
pip install rasterio numpy

# XMLをGeoTIFFに変換
python convert_dem.py /path/to/downloaded.xml ../data/elevation.tif
```

### 3. バックエンドの起動

```bash
cd ../backend

# 依存パッケージをインストール
pip install -r requirements.txt

# main.pyを編集してDEMパスを設定
# DEM_PATH = "../data_lake/validated/tokyo/dem/elevation.tif" に変更

# サーバー起動
python main.py
```

別のターミナルで動作確認：
```bash
curl http://localhost:8000/health
```

### 4. フロントエンドの起動

```bash
cd ../frontend

# シンプルなHTTPサーバーを起動
python -m http.server 8080
```

### 5. アクセス

ブラウザで http://localhost:8080 にアクセス

## Docker を使う場合

もっと簡単に始めたい場合はDockerを使用：

```bash
# データディレクトリを作成
mkdir -p data

# 変換済みのGeoTIFFファイルをlegacy dataまたはcanonical data_lakeに配置
cp /path/to/elevation.tif data/
# または
cp /path/to/elevation.tif data_lake/validated/tokyo/dem/elevation.tif

# Docker Composeで起動
docker-compose up -d

# ログを確認
docker-compose logs -f

# アクセス
# ブラウザで http://localhost:8080
```

停止する場合：
```bash
docker-compose down
```

## トラブルシューティング

### "標高データが見つかりません"

1. GeoTIFFファイルが正しいパスにあるか確認
2. `main.py` の `DEM_PATH` が正しいか確認
3. ファイルの読み取り権限を確認

### "APIにアクセスできません"

1. バックエンドが起動しているか確認: `curl http://localhost:8000/health`
2. CORS設定を確認
3. ブラウザのコンソールでエラーを確認

### "位置情報が取得できません"

1. ブラウザの位置情報許可を確認
2. HTTPSでアクセスしているか確認（ローカルでは http://localhost は許可されます）

## 次のステップ

動作確認ができたら、以下を試してみてください：

1. より広い範囲のデータを追加
2. `scripts/download/` と `scripts/normalize/` を使って東京版データレイクを拡張
3. 避難施設データと連携
4. PWA化してオフライン対応
5. 浸水想定区域データの統合

詳細は `README.md` を参照してください。

## テストデータの入手先

- [国土地理院 基盤地図情報](https://fgd.gsi.go.jp/download/menu.php)
- [東京都 浸水予想区域図](https://www.toshiseibi.metro.tokyo.lg.jp/bosai/chousa_6/home.htm)
- [指定緊急避難場所データ](https://www.gsi.go.jp/bousaichiri/hinanbasho.html)

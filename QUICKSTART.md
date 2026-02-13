# クイックスタートガイド

このガイドでは、避難ナビゲーションシステムを最速で動かす方法を説明します。

## 前提条件

- Python 3.9以上
- pip
- Webブラウザ（Chrome、Firefox、Safari等）

## 5分でスタート

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
# DEM_PATH = "../data/elevation.tif" に変更

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

# 変換済みのGeoTIFFファイルをdataディレクトリに配置
cp /path/to/elevation.tif data/

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
2. 避難施設データと連携
3. PWA化してオフライン対応
4. 浸水想定区域データの統合

詳細は `README.md` を参照してください。

## テストデータの入手先

- [国土地理院 基盤地図情報](https://fgd.gsi.go.jp/download/menu.php)
- [東京都 浸水予想区域図](https://www.toshiseibi.metro.tokyo.lg.jp/bosai/chousa_6/home.htm)
- [指定緊急避難場所データ](https://www.gsi.go.jp/bousaichiri/hinanbasho.html)

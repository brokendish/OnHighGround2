# scripts/ — データ処理スクリプト

このディレクトリには、既存のタイル生成スクリプトに加えて、東京版ハザードデータ基盤 v1 の責務別スクリプト群が含まれています。

## 東京版データ基盤 v1

新しく追加したスクリプトは、以下の責務分離を前提にしています。

- `download` は変換しない
- `normalize` は検証しない
- `validate` は修正しない
- `derive` は正本を上書きしない
- `tile_build` は `validated/derived` のみを見る
- `publish` は frontend への同期だけ行う

### 主要ディレクトリ

```
scripts/
  common/
  registry/
  download/
  extract/
  normalize/
  validate/
  derive/
  tile_build/
  publish/
  run_tokyo_pipeline.sh
```

### 最小パイプラインの実行

```bash
./init_data_lake.sh
./init_scripts.sh
./scripts/run_tokyo_pipeline.sh
```

現在の最小 E2E は shelter データだけを対象にしています。
将来的に river flood, tsunami, storm surge, urban flood, boundary, road network を同じ責務分離で拡張する想定です。

---

## 前提条件

### tippecanoe のインストール

**macOS (Homebrew):**
```bash
brew install tippecanoe
```

**Ubuntu / Debian:**
```bash
sudo apt install tippecanoe
```

**ソースからビルド:**
```
https://github.com/felt/tippecanoe
```

インストール確認:
```bash
tippecanoe --version
```

---

## build_tiles.py

以下は既存のレガシー寄りタイル生成フローです。東京版 v1 の基盤スクリプトとは独立しており、移行期間中は両方が存在します。

入力ディレクトリ内のすべての `.geojson` ファイルを、tippecanoe を使って
`.mbtiles` ベクタータイルファイルに変換します。

### 基本的な使い方

```bash
python scripts/build_tiles.py
```

`data/processed/hazard/`（正規のソースディレクトリ）から GeoJSON ファイルを読み込み、
`.mbtiles` ファイルを `tiles/` に出力します。

### オプション

| オプション | デフォルト | 説明 |
| --------- | --------- | ---- |
| `--minzoom` | 5 | 最小ズームレベル |
| `--maxzoom` | 14 | 最大ズームレベル |
| `--input DIR` | `data/processed/hazard` | GeoJSON ファイルが置かれたディレクトリ |
| `--output DIR` | `tiles` | .mbtiles ファイルの出力ディレクトリ |
| `--dry-run` | — | コマンドを実行せずに表示のみ行う |

### 実行例

```bash
# デフォルト実行（data/processed/hazard/ から読み込み）
python scripts/build_tiles.py

# ズーム範囲をカスタム指定
python scripts/build_tiles.py --minzoom 8 --maxzoom 16

# 暫定: frontend/hazard/ を入力として使用（レガシーの場所）
python scripts/build_tiles.py --input frontend/hazard

# 実行せずにプレビューのみ
python scripts/build_tiles.py --dry-run
```

---

## 現在のディレクトリ構成

```
data/
  hazard/                  ← 生のソースデータ（GML、Shapefile）— 直接編集しないこと
    A40-16-14/
    A40-18-12/
    ...
  processed/
    hazard/                ← 正規の GeoJSON 置き場（タイル生成の入力元）
      tsunami_tokyo.geojson
      tsunami_kanagawa.geojson
      tsunami_chiba.geojson

frontend/hazard/           ← レガシー / 暫定: 現フロントエンドが使用する GeoJSON のコピー
                             長期的なソースの置き場としては使用しないこと。
                             --input frontend/hazard で引き続き使用可能。

tiles/                     ← 生成された .mbtiles 出力（gitignore 対象）
  tsunami_tokyo.mbtiles
  tsunami_kanagawa.mbtiles
  tsunami_chiba.mbtiles

scripts/
  build_tiles.py           ← このスクリプト
  README.md                ← このファイル
```

> **注意:** `data/` はこのリポジトリで gitignore されています。`data/processed/hazard/` 以下のファイルは
> ローカルにのみ存在し、手動で生成またはコピーする必要があります。これは意図的な設計です —
> ハザード GeoJSON ファイルはサイズが大きく、`data/hazard/` 以下の生のソースデータから生成されるものであるためです。

---

## 新しいハザードデータセットを追加する

1. 処理済みの GeoJSON ファイルを `data/processed/hazard/` に配置します:

   ```
   data/processed/hazard/flood_tokyo.geojson
   ```

2. タイル生成スクリプトを実行します:

   ```bash
   python scripts/build_tiles.py
   ```

   スクリプトは入力ディレクトリ内のすべての `.geojson` ファイルを自動的に検出します。
   コードの変更は不要です。

### 暫定: frontend/hazard/ を入力として使用する

GeoJSON ファイルを `data/processed/hazard/` に移行するまでの間は、
レガシーの場所を使用できます:

```bash
python scripts/build_tiles.py --input frontend/hazard
```

`frontend/hazard/` はフロントエンドの描画互換性のために残していますが、
今後はハザード GeoJSON ソースデータの**正規の保存場所としては使用しないでください**。

---

## 将来のディレクトリ構成（予定）

プロジェクトがより多くの地域・ハザード種別に対応するにつれ、推奨される長期的なレイアウトは以下の通りです:

```
data/
  raw/                     ← オリジナルのソースデータ（GML、Shapefile 等）
  processed/               ← クリーニング・正規化済みの GeoJSON

tiles/
  japan/
    tokyo/
      tsunami/
        tsunami_tokyo.mbtiles
      flood/
        flood_tokyo.mbtiles
    kanagawa/
      tsunami/
        tsunami_kanagawa.mbtiles

scripts/
  build_tiles.py           ← タイル生成（--input/--output パスを更新して使用）
```

現在のフラットなレイアウト（`tiles/{dataset}.mbtiles`）は、この段階でのシンプルさを優先した意図的な設計です。
データセット数が増えた時点で、地域対応レイアウトへの移行を段階的に行うことができます。

---

## 前提事項と制限

- tippecanoe はローカルにインストールする必要があります（Docker 環境には含まれません）。
- GeoJSON ファイルは EPSG:4326（WGS84）を使用していることを前提としています。これは日本の政府ハザードデータセットの標準形式です。
- `.mbtiles` 形式はローカルでの使用やテストに適しています。

---

## Martin タイルサーバー

`tiles/` に生成した `.mbtiles` ファイルは、Docker Compose に含まれる
[Martin](https://github.com/maplibre/martin) タイルサーバーで配信されます。

### 起動方法

```bash
docker compose up martin
```

または他のサービスと一括起動:

```bash
docker compose up
```

### MBTiles の自動検出

Martin は起動時に `/tiles` ディレクトリ（`docker-compose.yml` で `./tiles:/tiles:ro` にマウント）
内のすべての `.mbtiles` ファイルを自動検出します。
設定ファイルは不要です。コマンド引数にディレクトリを渡すだけで動作します。

### タイルエンドポイントの確認

Martin が起動したら、以下の URL で動作を確認できます（nginx プロキシ経由）:

```bash
# タイルセット一覧
curl http://localhost:8080/tiles/catalog

# 東京タイルセットの TileJSON
curl http://localhost:8080/tiles/tokyo_tsunami_A40-23_13

# タイルリクエストの例（ズームレベル 10、xy 座標指定）
curl http://localhost:8080/tiles/tokyo_tsunami_A40-23_13/10/909/403
```

### タイルセット ID と source-layer 名

MBTiles ファイル名の stem がタイルセット ID になります。
tippecanoe の `--layer` オプションで指定した名前が source-layer 名です
（`build_tiles.py` では `--layer dataset` で dataset = ファイル名 stem）。

#### 津波浸水想定

| 都県         | タイルセット ID                  | source-layer 名                  |
|--------------|----------------------------------|----------------------------------|
| 東京都       | `tokyo_tsunami_A40-23_13`        | `tokyo_tsunami_A40-23_13`        |
| 神奈川県 (1) | `kanagawa_tsunami_A40-16_14`     | `kanagawa_tsunami_A40-16_14`     |
| 神奈川県 (2) | `kanagawa_tsunami_A40-20_14`     | `kanagawa_tsunami_A40-20_14`     |
| 千葉県       | `chiba_tsunami_A40-18_12`        | `chiba_tsunami_A40-18_12`        |

#### 洪水浸水想定（想定最大規模）

| 都県   | タイルセット ID   | source-layer 名   |
|--------|-------------------|-------------------|
| 東京都 | `tokyo_flood_max` | `tokyo_flood_max` |

### フロントエンドでの使用

`frontend/index.html` の `VECTOR_TILE_SOURCES` に上記の ID と source-layer 名が定義されています。

フロントエンド起動時に `/tiles/catalog` へのリクエストで Martin の可用性を自動確認します。

- Martin が起動している場合: ベクタータイルを使用（`L.vectorGrid.protobuf`）
- Martin が起動していない場合: GeoJSON ファイルへフォールバック（`/hazard/*.geojson`）

### フロントエンドでのベクタータイル描画確認

1. `docker compose up` でサービスを起動する
2. ブラウザで `http://localhost:8080` を開く
3. ブラウザの DevTools コンソールで以下のログを確認する:

   ```text
   Martin タイルサーバー: 利用可能（ベクタータイル使用）
   ```

4. 津波ハザードレイヤーのチェックボックスを ON にしてタイルが描画されることを確認する

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

```text
scripts/
  common/
  registry/
  download/
  migrate/
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
将来的に flood, tsunami, storm_surge, urban_flood, boundary, osm を同じ責務分離で拡張する想定です。

### 洪水データ処理スクリプト

#### `scripts/normalize/normalize_flood.py`

GML（A31a: 中小河川、A31b: 国管理河川）から GeoJSON に変換するスクリプト。
iterparse 2パス方式で大容量 GML を低メモリで処理します。

- A31a: 中小河川（従来対応）
- A31b: 荒川・多摩川等の国管理河川（対応済み）

#### `scripts/normalize/filter_flood_hazard.py`

`tokyo_flood_max.geojson`（表示用・全ランク）から、バックエンド判定用の
GeoJSONL を生成するスクリプト。

```bash
python scripts/normalize/filter_flood_hazard.py
```

- 入力: `data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson`（925,958 フィーチャ）
- 出力: `data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl`（1行1Feature、GeoJSONL 形式）
- デフォルト: rank 1〜5 すべてを含む（`--min-rank 1`）

GeoJSONL はバックエンドが `load_geojsonl()` で1行ずつストリーミング読み込みするため、
666K ポリゴンでも OOM を起こしません。

### 移行スクリプト

旧 `data/`, `tiles/`, `frontend/hazard/` から `data_lake/` へ集約するための互換移行は以下で行います。

```bash
./scripts/migrate/migrate_to_data_lake.sh
```

このスクリプトはコピー優先で、旧構造を削除しません。

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

```text
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

`data_lake/validated/tokyo/` を標準入力として再帰的に GeoJSON を読み込み、
`.mbtiles` ファイルを `data_lake/tiles/tokyo/` に出力します。

### オプション

| オプション | デフォルト | 説明 |
| --------- | --------- | ---- |
| `--minzoom` | 5 | 最小ズームレベル |
| `--maxzoom` | 14 | 最大ズームレベル |
| `--input DIR` | `data_lake/validated/tokyo` | GeoJSON ファイルが置かれたディレクトリ |
| `--output DIR` | `data_lake/tiles/tokyo` | .mbtiles ファイルの出力ディレクトリ |
| `--dry-run` | — | コマンドを実行せずに表示のみ行う |

### 実行例

```bash
# デフォルト実行（data_lake/validated/tokyo/ から再帰読み込み）
python scripts/build_tiles.py

# ズーム範囲をカスタム指定
python scripts/build_tiles.py --minzoom 8 --maxzoom 16

# 旧処理済み GeoJSON を一時入力として使用
python scripts/build_tiles.py --input data/processed/hazard

# 実行せずにプレビューのみ
python scripts/build_tiles.py --dry-run
```

---

## 現在のディレクトリ構成

```text
data_lake/
  validated/
    tokyo/
      flood/
        tokyo_flood_max.geojson
      tsunami/
        tokyo_tsunami_A40-23_13.geojson
  tiles/
    tokyo/
      flood/
        tokyo_flood_max.mbtiles
      tsunami/
        tokyo_tsunami_A40-23_13.mbtiles

data/processed/hazard/     ← 旧処理済み GeoJSON 置き場（legacy）
frontend/hazard/           ← 旧フロント直読場所（legacy）
tiles/                     ← 旧 MBTiles 置き場（legacy）

scripts/
  build_tiles.py           ← このスクリプト
  README.md                ← このファイル
```

> **注意:** 正本は `data_lake/` です。`data/processed/hazard/`、`frontend/hazard/`、`tiles/` は
> 互換確認のために残している legacy 置き場です。移行は `./scripts/migrate/migrate_to_data_lake.sh` を使ってください。

---

## 新しいハザードデータセットを追加する

1. 検証済みの GeoJSON ファイルを `data_lake/validated/tokyo/<hazard>/` に配置します:

   ```text
   data_lake/validated/tokyo/flood/flood_tokyo.geojson
   ```

2. タイル生成スクリプトを実行します:

   ```bash
   python scripts/build_tiles.py
   ```

   スクリプトは入力ディレクトリ内のすべての `.geojson` ファイルを自動的に検出します。
   コードの変更は不要です。

### 旧構造を一時入力として使用する

```bash
python scripts/build_tiles.py --input data/processed/hazard
```

`frontend/hazard/` はフロントエンドの描画互換性のために残していますが、
今後は**正規の保存場所としては使用しないでください**。配信用正本は `data_lake/tiles/` です。

---

## 現在の推奨ディレクトリ構成

プロジェクトがより多くの地域・ハザード種別に対応するにつれ、推奨される長期的なレイアウトは以下の通りです:

```text
data_lake/
  raw/
    tokyo/
      tsunami/
      flood/
      osm/
  normalized/
    tokyo/
      tsunami/
      flood/
  validated/
    tokyo/
      tsunami/
      flood/
      shelter/
      dem/
  tiles/
    tokyo/
      tsunami/
      flood/

scripts/
  build_tiles.py           ← タイル生成（--input/--output パスを更新して使用）
```

repo 直下の `tiles/` は legacy です。正本は `data_lake/tiles/` に固定します。

---

## 前提事項と制限

- tippecanoe はローカルにインストールする必要があります（Docker 環境には含まれません）。
- GeoJSON ファイルは EPSG:4326（WGS84）を使用していることを前提としています。これは日本の政府ハザードデータセットの標準形式です。
- `.mbtiles` 形式はローカルでの使用やテストに適しています。

---

## Martin タイルサーバー

`data_lake/tiles/` に生成した `.mbtiles` ファイルが配信用正本です。Docker Compose に含まれる
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

Martin は起動時に `/tiles` ディレクトリを見ます。現在の Docker Compose では
`./data_lake/tiles:/tiles:ro` をマウントし、`/tiles/tokyo/flood` や `/tiles/tokyo/tsunami`
を公開対象として渡しています。設定ファイルは不要です。コマンド引数にディレクトリを
渡すだけで動作します。

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

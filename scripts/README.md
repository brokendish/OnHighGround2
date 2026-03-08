# scripts/ — タイル生成パイプライン

このディレクトリには、ハザード GeoJSON データをベクタータイルに変換するスクリプトが含まれています。

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
  本番環境でのタイル配信には、[PMTiles](https://protomaps.com/docs/pmtiles) への変換や、
  [Martin](https://github.com/maplibre/martin) などのタイルサーバーの利用を検討してください。

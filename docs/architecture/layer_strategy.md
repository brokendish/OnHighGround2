# レイヤー配信戦略: GeoJSON fallback vs Vector Tiles

**Phase 2.1 時点のポリシー**

---

## 概要

OnHighGround2 のフロントエンドは、ハザードデータを 2 種類の経路で配信・表示する。

| 経路 | エンドポイント | 形式 | 用途 |
|---|---|---|---|
| GeoJSON fallback | `/layers/` | GeoJSON | 軽量・限定範囲のレイヤー、検証用 |
| Vector Tiles | `/tiles/` | MBTiles (Martin) | 大規模・高密度データ |

frontend は起動時に Martin タイルの可用性を確認し、タイルが利用可能であればタイルを優先表示する。
タイルがない場合は `/layers/` の GeoJSON にフォールバックする。

---

## GeoJSON fallback (`/layers/`)

### 用途

- **軽量または限定範囲のレイヤー**に使用
- ブラウザが全件ロードしても許容できる規模のデータ向け
- タイルサーバーが不要な単純な配信が可能

### 現在の対象レイヤー

| レイヤー | ファイル | 規模感 |
|---|---|---|
| 東京高潮 | `tokyo_storm_surge.geojson` | 中規模 |
| 東京津波 | `tsunami_tokyo.geojson` | 中規模 |
| 神奈川津波 | `tsunami_kanagawa.geojson` | 中規模 |
| 千葉津波 | `tsunami_chiba.geojson` | 中規模 |

### 配備フロー

```
data_lake/validated/tokyo/hazard/...
  → deploy_to_runtime.sh
  → data_runtime/frontend/layers/
  → (rsync/cp) → frontend/layers/
  → nginx /layers/ で配信
```

### ルール

- `frontend/hazard/` は **legacy 扱い** — 新規データを追加しない
- 新規 GeoJSON は `frontend/layers/` に配置し、`deploy_to_runtime.sh` 経由で管理する
- 大規模データ（数十MB以上）は GeoJSON fallback に無理に持たない

---

## Vector Tiles (`/tiles/`)

### 用途

- **大規模・高密度データ**に使用
- ズームレベルに応じた間引き・クリップが必要なデータ向け
- Martin (MBTiles) + Leaflet.VectorGrid で表示

### 現在の対象レイヤー

| レイヤー | MBTiles ファイル | 規模感 |
|---|---|---|
| 東京洪水 | `tokyo_flood_max.mbtiles` | 大規模（数百MB） |
| 東京津波（広域） | `tokyo_tsunami.mbtiles` | 大規模 |
| 高潮（タイル版） | `tokyo_storm_surge.mbtiles` | 中〜大 |
| 内水氾濫 | `tokyo_urban_flood.mbtiles` | 中〜大 |

### 配備フロー

```
data_lake/tiles/tokyo/...
  → deploy_to_runtime.sh
  → data_runtime/frontend/tiles/
  → Martin コンテナがマウント
  → nginx /tiles/ プロキシで配信
```

### ルール

- タイルの正本は `data_lake/tiles/` に置く
- `data_runtime/frontend/tiles/` は deploy artifact — 直接編集しない
- Martin が参照する正規マウント先は `data_runtime/frontend/tiles/`
- `data_lake/tiles/` の直接マウント（`/tiles_legacy`）は fallback として残存中（削除条件は `legacy/README.md` を参照）

---

## frontend の挙動

`frontend/js/config.js` の `LAYER_BASE_PATH = '/layers'` が GeoJSON fallback の基準パスを定義する。

`initializeHazardToggles()` は起動時に次の順序でレイヤーの可用性を確認する:

1. Martin が起動中かつ該当タイルセットが存在 → タイル表示モードでチェックボックスを有効化
2. Martin が利用不可または該当タイルセットなし → `/layers/...` に HEAD リクエスト
3. HEAD が 404 → チェックボックスを非活性化（データ未配備）

---

## よくある質問

**Q. なぜ津波は GeoJSON と Vector Tiles の両方があるのか？**

A. 津波 GeoJSON (`/layers/`) は範囲が限定的で軽量なため fallback として維持。広域津波や高解像度タイルは MBTiles で管理。両方存在する場合、フロントエンドはタイルを優先表示する。

**Q. 洪水に `/layers/` ファイルがないのはなぜか？**

A. 洪水データは数百MB規模で GeoJSON での全件ブラウザ読み込みが現実的でないため、タイル専用として管理している。

**Q. `frontend/hazard/` はいつ削除するのか？**

A. Martin タイル配信が安定し、`/layers/` 経由で全ハザードレイヤーが表示できることが確認されてから削除する。削除条件の詳細は `legacy/README.md` を参照。

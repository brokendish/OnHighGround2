# レイヤー配信戦略: GeoJSON fallback vs Vector Tiles

> Phase 4.2 時点のポリシー

---

## 概要

OnHighGround2 のフロントエンドは、ハザードデータを 2 種類の経路で配信・表示する。

| 経路 | エンドポイント | 形式 | 用途 |
| --- | --- | --- | --- |
| GeoJSON fallback | `/layers/` | GeoJSON | 軽量・限定範囲のレイヤー、検証用 |
| Vector Tiles | `/tiles/` | MBTiles (Martin) | 大規模・高密度データ |

frontend は起動時に Martin タイルの可用性を確認し、タイルが利用可能であればタイルを優先表示する。
タイルがない場合は、`apiUrl` が定義されていれば API モードで有効化し、なければチェックボックスを非活性化する。

---

## GeoJSON fallback (`/layers/`)

### 用途（GeoJSON）

- **軽量または限定範囲のレイヤー**に使用
- ブラウザが全件ロードしても許容できる規模のデータ向け
- タイルサーバーが不要な単純な配信が可能

### 現在の対象レイヤー（GeoJSON）

| レイヤー | ファイル | 規模感 |
| --- | --- | --- |
| 東京津波 | `tokyo_tsunami_A40-23_13.geojson` | 中規模 |
| 神奈川津波 | `kanagawa_tsunami_A40-16_14.geojson` | 中規模 |
| 千葉津波 | `chiba_tsunami_A40-18_12.geojson` | 中規模 |

### 配備フロー（GeoJSON）

```text
data_lake/validated/tokyo/hazard/...
  → deploy_to_runtime.sh
  → data_runtime/frontend/layers/
  → (rsync/cp) → frontend/layers/
  → nginx /layers/ で配信
```

### ルール（GeoJSON）

- `frontend/hazard/` は **legacy 扱い** — 新規データを追加しない
- 新規 GeoJSON は `frontend/layers/` に配置し、`deploy_to_runtime.sh` 経由で管理する
- 大規模データ（数十MB以上）は GeoJSON fallback に無理に持たない

---

## Vector Tiles (`/tiles/`)

### 用途（Vector Tiles）

- **大規模・高密度データ**に使用
- ズームレベルに応じた間引き・クリップが必要なデータ向け
- Martin (MBTiles) + Leaflet.VectorGrid で表示

### 現在の対象レイヤー（Vector Tiles）

| レイヤー | MBTiles ファイル | 規模感 |
| --- | --- | --- |
| 東京洪水 | `tokyo_flood_max.mbtiles` | 大規模（数百MB） |
| 東京津波 | `tokyo_tsunami_A40-23_13.mbtiles` | 大規模 |
| 高潮 | `tokyo_storm_surge.mbtiles` | 中〜大 |

### 配備フロー（Vector Tiles）

```text
data_lake/tiles/tokyo/...
  → deploy_to_runtime.sh
  → data_runtime/frontend/tiles/
  → Martin コンテナがマウント
  → nginx /tiles/ プロキシで配信
```

### ルール（Vector Tiles）

- タイルの正本は `data_lake/tiles/` に置く
- `data_runtime/frontend/tiles/` は deploy artifact — 直接編集しない
- Martin が参照する正規マウント先は `data_runtime/frontend/tiles/`
- `data_lake/tiles/` の直接マウント（`/tiles_legacy`）は fallback として残存中（削除条件は `legacy/README.md` を参照）

---

## フォールバック戦略

`initializeHazardToggles()` は起動時に次の優先順位でレイヤーを有効化する:

1. **Vector Tile 優先** — Martin が起動中かつ該当タイルセットが存在する場合、タイル表示モードで有効化
2. **API fallback** — タイルが存在しないが `apiUrl` が定義されている場合、`_vectorTilesUnavailable = true` を設定し API モードで有効化
3. **無効化** — タイルも `apiUrl` も存在しない場合のみチェックボックスを非活性化

現状の各レイヤーの経路:

| layer | 主経路 | fallback |
| --- | --- | --- |
| flood | Vector Tile | API |
| storm_surge | Vector Tile | API |
| tsunami | Vector Tile | API |
| inland_flood | `/layers/` GeoJSON | — |
| landslide | `/layers/` GeoJSON | — |

---

## よくある質問

**Q. なぜ津波は GeoJSON と Vector Tiles の両方があるのか？**

A. 津波は MBTiles（`tokyo_tsunami_A40-23_13.mbtiles`）が主経路。MBTiles が存在しない場合は `_vectorTilesUnavailable = true` となり、`apiUrl`（バックエンド API）経由で GeoJSON 相当を表示する。`/layers/` の GeoJSON は deploy_to_runtime.sh で配備される開発・検証用 fallback として維持している。

**Q. 洪水に `/layers/` ファイルがないのはなぜか？**

A. 洪水データは数百MB規模で GeoJSON での全件ブラウザ読み込みが現実的でないため、タイル専用として管理している。

**Q. `frontend/hazard/` はいつ削除するのか？**

A. Martin タイル配信が安定し、`/layers/` 経由で全ハザードレイヤーが表示できることが確認されてから削除する。削除条件の詳細は `legacy/README.md` を参照。

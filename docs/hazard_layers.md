# Hazard Layers Overview

ハザードレイヤー一覧。詳細は [layer_strategy.md](architecture/layer_strategy.md) と [hazard_capability_matrix.md](architecture/hazard_capability_matrix.md) を参照。

runtime の実態（catalog 状態・fallback 可否）は管理UIで確認できる: `http://localhost:8080/admin/hazards`

| layer | 表示名 | tileset | 主経路 | fallback | severity | notes |
| --- | --- | --- | --- | --- | --- | --- |
| flood | 洪水浸水想定 | `tokyo_flood_max` | Vector Tile | API | ✅ 浸水深ランク | `drop-densest-as-needed` 適用 |
| storm_surge | 高潮浸水想定 | `tokyo_storm_surge` | Vector Tile | API | ✅ 浸水深ランク | `coalesce` + `drop` 適用 |
| tsunami | 津波浸水想定 | `tokyo_tsunami_A40-23_13` | Vector Tile | API | — | 複数都県対応（kanagawa / chiba） |
| inland_flood | 内水氾濫 | — | `/layers/` GeoJSON | — | ✅ zone_type | タイル化未実装 |
| landslide | 土砂災害 | — | `/layers/` GeoJSON | — | ✅ zone_type | タイル化未実装 |

## レイヤー追加手順

1. GeoJSON を `data_lake/normalized/tokyo/{type}/` に配置
2. `scripts/build_tiles.py` でタイル生成（大規模データのみ）
3. `deploy_to_runtime.sh` で `data_runtime/` へ配備
4. `frontend/js/hazard-layers.js` の `HAZARD_LAYERS` と `VECTOR_TILE_SOURCES` に定義を追加

> **注意**: `VECTOR_TILE_SOURCES` の初期化式で参照するカラー定数は、TDZ（Temporal Dead Zone）を避けるため
> `HAZARD_LAYERS` より前に宣言すること（[hazard-layers.js](../frontend/js/hazard-layers.js) 冒頭のコメント参照）。

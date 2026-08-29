# Hazard Layers Overview

ハザードレイヤー一覧。詳細は [layer_strategy.md](architecture/layer_strategy.md) と [hazard_capability_matrix.md](architecture/hazard_capability_matrix.md) を参照。

public構成では管理UIは公開しない。catalog状態・fallback可否の確認を含む
privileged operation は [operator setup](operator-setup.md) の別workflowに従う。

| layer | 表示名 | tileset | 主経路 | fallback | severity | notes |
| --- | --- | --- | --- | --- | --- | --- |
| flood | 洪水浸水想定 | `tokyo_flood_max` | Vector Tile | API | ✅ 浸水深ランク | `drop-densest-as-needed` 適用 |
| storm_surge | 高潮浸水想定 | `tokyo_storm_surge` | Vector Tile | API | ✅ 浸水深ランク | `coalesce` + `drop` 適用 |
| tsunami | 津波浸水想定 | `tokyo_tsunami_A40-23_13` | Vector Tile | API | — | 複数都県対応（kanagawa / chiba） |
| inland_flood | 内水氾濫 | — | API (`/api/hazards/inland_flood/tokyo`) | — | ✅ depth_min_m ランク | タイル化未実装 |
| landslide | 土砂災害警戒区域 | — | API (`/api/hazards/landslide/tokyo`) | — | ✅ zone_type / severity_level | タイル化未実装。データ: A33 |

## レイヤー追加手順

1. GeoJSON を `data_lake/normalized/tokyo/{type}/` に配置
2. `scripts/build_tiles.py` でタイル生成（大規模データのみ）
3. `deploy_to_runtime.sh` で `data_runtime/` へ配備
4. `frontend/js/hazard-layers.js` の `HAZARD_LAYERS` と `VECTOR_TILE_SOURCES` に定義を追加

> **注意**: `VECTOR_TILE_SOURCES` の初期化式で参照するカラー定数は、TDZ（Temporal Dead Zone）を避けるため
> `HAZARD_LAYERS` より前に宣言すること（[hazard-layers.js](../frontend/js/hazard-layers.js) 冒頭のコメント参照）。

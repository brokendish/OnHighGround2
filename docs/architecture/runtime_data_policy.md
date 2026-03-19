# データ参照ポリシー: data_lake と data_runtime の責務分離

**Phase 1 時点のポリシー（段階移行中）**

---

## 概要

OnHighGround2 では、データを **正本（data_lake）** と **配備用（data_runtime）** に分離する方針を採る。
バックエンド・フロントエンドが直接読むのは `data_runtime/` であり、`data_lake/` は正本置き場として参照を限定する。

今回（Phase 1）は **段階移行** であり、まだ `data_runtime/` にデータが置かれていない場合、
backend は `data_lake/` へのフォールバックで動作する。完全移行は Phase 2 以降。

---

## data_lake/ 各層の役割

### `data_lake/raw/`

- **役割**: ソース取得の生データ置き場
- 外部から取得したまま（GML, Shapefile, PBF など）
- 加工・変換は行わない
- **アプリからの直接参照: 禁止**
- パイプラインの最上流 (`scripts/download/`) のみが書き込む

### `data_lake/normalized/`

- **役割**: 正規化済みデータ
- `raw/` を正規化スクリプト (`scripts/normalize/`) で処理した成果物
- GeoJSON / GeoJSONL 形式に統一済み
- **アプリからの直接参照: 原則避ける**（validated が整備されるまでの暫定フォールバックは許容）

### `data_lake/validated/`

- **役割**: 検証済み正本データ
- `normalized/` をバリデーション (`scripts/validate/`) で確認した成果物
- OSRM インデックス、DEM GeoTIFF など、最終確認済みの形式
- **アプリからのフォールバック参照: 許容**（runtime が未整備の間）

### `data_lake/tiles/`

- **役割**: ベクタータイル生成の成果物（MBTiles）
- tippecanoe で生成した `.mbtiles` ファイル
- Martin タイルサーバーが直接マウントして配信
- **現状: Martin は data_lake/tiles を直接参照中**（Phase 2 で data_runtime/frontend/tiles へ移行予定）

---

## data_runtime/ 各層の役割

`data_runtime/` はアプリが **直接読む配備用データ** を置く場所。
`data_lake/` は正本であり、`data_runtime/` はそのコピー（deploy artifact）。

### `data_runtime/backend/`

- バックエンド (FastAPI) が読む実行時データ
- `scripts/publish/deploy_to_runtime.sh` が `data_lake/validated/` または `data_lake/normalized/` からコピーして生成する
- 内容例:
  - `hazard/flood/` — 洪水ハザード GeoJSONL
  - `hazard/storm_surge/` — 高潮ハザード GeoJSON
  - `hazard/tsunami/` — 津波ハザード GeoJSON
  - `shelters/` — 避難所 GeoJSON
  - `elevation/` — DEM GeoTIFF

### `data_runtime/frontend/`

- フロントエンドに配信するデータ
- `layers/` — フォールバック用 GeoJSON（`frontend/layers/` へコピー予定）
- `tiles/` — MBTiles（将来的に Martin のマウント先を変更）

### `data_runtime/manifests/`

- どのデータが runtime に配備されているかを記録する manifest ファイル置き場
- `deploy_to_runtime.sh` が実行ログや配備リストを残す

---

## 参照原則

```
[正本データの流れ]
data_lake/raw/
  → (normalize) → data_lake/normalized/
  → (validate)  → data_lake/validated/
  → (tile_build)→ data_lake/tiles/
  → (publish)   → data_runtime/

[アプリの参照先]
backend   → data_runtime/backend/  (フォールバック: data_lake/validated/)
frontend  → data_runtime/frontend/ (フォールバック: frontend/hazard/ ← legacy)
martin    → data_lake/tiles/       (Phase 2 以降: data_runtime/frontend/tiles/)
```

- `data_lake/raw/` はいかなるアプリからも直接参照しない
- `data_lake/normalized/` は暫定フォールバックとして許容するが、段階的に廃止する
- `data_runtime/` にデータがない間は、backend がログで警告を出しつつ `data_lake/` を参照する

---

## 段階移行の現状 (Phase 1)

| コンポーネント | 現在の参照先 | 目標 (Phase 2+) |
|---|---|---|
| backend DEM | `data_lake/validated/tokyo/dem/` (fallback) | `data_runtime/backend/elevation/` (primary) |
| backend flood | `data_lake/normalized/tokyo/flood/` (fallback) | `data_runtime/backend/hazard/flood/` (primary) |
| backend storm_surge | `data_lake/normalized/tokyo/storm_surge/` (fallback) | `data_runtime/backend/hazard/storm_surge/` (primary) |
| backend tsunami | `data_lake/validated/tokyo/tsunami/` (fallback) | `data_runtime/backend/hazard/tsunami/` (primary) |
| frontend layers | `frontend/hazard/` (legacy GeoJSON) | `frontend/layers/` → `data_runtime/frontend/layers/` |
| martin tiles | `data_lake/tiles/` (direct) | `data_runtime/frontend/tiles/` |

Phase 1 では `data_runtime/` ディレクトリと deploy スクリプトの基盤を作成し、
backend が `data_runtime/` を優先参照するコードを導入した（データが存在しない間は自動フォールバック）。

---

## publish / deploy フロー

`scripts/publish/deploy_to_runtime.sh` が配備スクリプト。

```bash
# Tokyo 向け runtime 配備の実行例
scripts/publish/deploy_to_runtime.sh --region tokyo
```

このスクリプトは:
1. `data_lake/validated/tokyo/` または `data_lake/normalized/tokyo/` から必要なファイルをコピー
2. `data_runtime/backend/` および `data_runtime/frontend/layers/` に配置
3. `data_runtime/manifests/` に配備ログを記録

---

## frontend/hazard/ の扱い

`frontend/hazard/` は旧来の GeoJSON 直接配信ディレクトリ（legacy 扱い）。

- 現在 nginx が `/hazard/` として配信しており、フロントエンドのフォールバックとして機能
- 今後は `frontend/layers/` を公式ディレクトリとし、`/layers/` として配信
- `frontend/hazard/` は互換維持のため残すが、新規データは追加しない
- vector tiles (Martin) が十分に整備された段階で廃止予定

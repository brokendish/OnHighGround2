# legacy/ — 移行期間一時退避ディレクトリ

このディレクトリは **移行期間中の互換置き場** です。

---

## ポリシー

- **新規実装ではここを参照しない**
- 完全移行後に削除予定
- 現時点では互換維持のため、一部旧データ・旧構成が残る可能性がある
- 旧ディレクトリ構成を確認する際の参照先として使用する

---

## サブディレクトリの意味

| ディレクトリ | 旧配置 | 移行先 |
|---|---|---|
| `data/` | `data/` (プロジェクトルート直下の旧データ置き場) | `data_lake/` または `data_runtime/` |
| `tiles/` | `tiles/` (プロジェクトルート直下の旧タイル置き場) | `data_lake/tiles/` → `data_runtime/frontend/tiles/` |
| `frontend_hazard/` | `frontend/hazard/` (フロントエンド直下の旧ハザードGeoJSON) | `data_runtime/frontend/layers/` → `frontend/layers/` |

---

## 現状の互換維持箇所

- `frontend/hazard/` — nginx で `/hazard/` として配信中。**deprecated** (Phase 2)。
  - Phase 2 で `/layers/` への切替完了。新規参照は `frontend/layers/` を使うこと。
  - Martin vector tiles が安定した Phase 3 時点で `/hazard/` location と `frontend/hazard/` を削除予定。
- `data/elevation.tif` — DEMデータの旧配置。`data_runtime/backend/elevation/elevation.tif` への移行後に不要。
- `国土地理院避難所データ/` — 避難所CSVの旧配置。`data_runtime/backend/shelters/` に配備完了後に削除予定。

---

## Phase 2 完了後の削除対象候補

Phase 2 で以下の移行が完了した。これらは Phase 3 で削除を検討する。

| 対象 | 状態 | 削除条件 |
| --- | --- | --- |
| `nginx.conf` の `/hazard/` location | deprecated | Martin tiles が安定し `/layers/` で完全代替できること |
| `frontend/hazard/*.geojson` | 後方互換維持中 | `/layers/` 経由で全レイヤーが表示できること |
| `docker-compose.yml` の `data_lake/tiles:/tiles_legacy` マウント | fallback 用 | `data_runtime/frontend/tiles/` に全タイルが配備されること |
| backend の `data_lake` fallback コード | 残存 | runtime が 1 か月以上安定稼働したこと |
| `国土地理院避難所データ/` Docker マウント | legacy shelter | `data_runtime/backend/shelters/` で全避難所が賄えること |

---

## 削除タイミング

Phase 3 以降、上記削除条件を確認してから段階的に削除する。
削除前に `runtime_cutover_checklist.md` ですべての確認項目がグリーンになっていること。

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
| --- | --- | --- |
| `data/` | `data/` (プロジェクトルート直下の旧データ置き場) | `data_lake/` または `data_runtime/` |
| `tiles/` | `tiles/` (プロジェクトルート直下の旧タイル置き場) | `data_lake/tiles/` → `data_runtime/frontend/tiles/` |
| `frontend_hazard/` | `frontend/hazard/` (フロントエンド直下の旧ハザードGeoJSON) | `data_runtime/frontend/layers/` → `frontend/layers/` |

---

## fallback 残存一覧と縮退計画

Phase 2 完了時点で残っている fallback の一覧。削除条件が揃い次第、Phase 3 で段階的に削除する。

| fallback | 場所 | 現在の目的 | 削除条件 | 想定フェーズ |
| --- | --- | --- | --- | --- |
| nginx `/hazard/` location | `nginx.conf` | `frontend/hazard/` の後方互換配信 | `/layers/` 経由で全レイヤーが表示できること + Martin タイルが安定稼働 | Phase 3 |
| `frontend/hazard/*.geojson` | `frontend/hazard/` | `/hazard/` 配信の実体ファイル | `/layers/` 経由で全レイヤーが表示できること | Phase 3 |
| Martin `data_lake/tiles` マウント | `docker-compose.yml` (`/tiles_legacy`) | `data_runtime/frontend/tiles/` が空の場合の fallback | `data_runtime/frontend/tiles/` に全タイルが配備され 1 ヶ月以上安定稼働 | Phase 3 |
| backend `data_lake` fallback コード | `backend/main.py` (`resolve_existing_path`) | `data_runtime/` 未整備時の自動フォールバック | runtime が 1 ヶ月以上安定稼働し WARNING ログが出ないこと | Phase 3 |
| 国土地理院 CSV fallback | `docker-compose.yml` (`/app/shelter_data`) + `backend/main.py` | legacy 避難所 CSV の読み込み | `data_runtime/backend/shelters/` で全避難所が賄えること | Phase 3 |
| `frontend/js/config.js` の `LAYER_BASE_PATH` fallback ロジック | `frontend/index.html` (`initializeHazardToggles`) | `/layers/` 404 時のチェックボックス非活性化 | `/layers/` への GeoJSON 配備が運用として定着すること | Phase 3 以降 |

### 削除条件の補足

- **Martin タイル fallback**: `data_lake/tiles:/tiles_legacy` マウントを削除するには、`data_runtime/frontend/tiles/` にすべての `.mbtiles` が配備され、`docker logs evacuation-navi-martin` で `/tiles_legacy` への参照が発生していないことを確認する。
- **backend data_lake fallback**: `docker logs evacuation-navi-backend | grep fallback` で出力が 0 件になること。
- **nginx /hazard/ location**: ブラウザ開発者ツールで `/hazard/...` へのリクエストが発生していないことを確認してから削除する。

---

## 現状の互換維持箇所

- `frontend/hazard/` — nginx で `/hazard/` として配信中。**deprecated** (Phase 2)。
  - Phase 2 で `/layers/` への切替完了。新規参照は `frontend/layers/` を使うこと。
  - Martin vector tiles が安定した Phase 3 時点で `/hazard/` location と `frontend/hazard/` を削除予定。
- `data/elevation.tif` — DEMデータの旧配置。`data_runtime/backend/elevation/elevation.tif` への移行後に不要。
- `国土地理院避難所データ/` — 避難所CSVの旧配置。`data_runtime/backend/shelters/` に配備完了後に削除予定。

---

## 削除タイミング

Phase 3 以降、上記削除条件を確認してから段階的に削除する。
削除前に `runtime_cutover_checklist.md` ですべての確認項目がグリーンになっていること。

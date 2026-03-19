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

- `frontend/hazard/` — nginx から `/hazard/` として配信中。GeoJSON フォールバックとして現役。
  - 将来的に `frontend/layers/` + vector tiles (Martin) へ完全移行後、削除予定。
- `data/elevation.tif` — DEMデータの旧配置。`data_lake/validated/tokyo/dem/elevation.tif` への移行が完了したら不要。
- `国土地理院避難所データ/` — 避難所CSVの旧配置。`data_lake/validated/tokyo/shelter/` への移行後に削除予定。

---

## 削除タイミング

Phase 2 以降、`data_runtime/` への配備が安定した時点で、
`legacy/` 配下のディレクトリおよびプロジェクトルート直下の旧配置を整理する。

削除前に、各サービスの参照先がすべて `data_runtime/` を向いていることを確認すること。

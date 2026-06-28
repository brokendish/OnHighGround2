# LIVE Phase 7-A.6 鉄道PMTiles生成・更新の管理画面統合 CODEX 検証レポート

## 判定

PASS with notes

管理画面から鉄道路線 PMTiles 更新ジョブを開始し、ログで進捗確認できる UI/API 統合を確認した。
実 PMTiles 生成は Japan OSM PBF（約 1GB）と osmium / tippecanoe / tile-join に依存するため、この検証では未実行。

## 確認環境

- 日時: 2026-06-27
- Docker:
  - backend: Up / healthy
  - frontend: Up
  - martin: Up / healthy
  - osrm-walking: Up

## 実装確認

- 追加データセット: `RAILWAY-PMTILES-JAPAN-001`
- 追加 API: `POST /api/admin/datasets/{dataset_id}/railway-pmtiles-update`
- 追加ジョブ種別: `railway_pmtiles_update`
- OSM PBF 保存先: `data_lake/raw/osm/japan-latest.osm.pbf`
- PMTiles 生成 staging: `frontend/layers/railways/.railway_pmtiles_staging/`
- 検証用 tmp: `frontend/layers/railways/railways_japan.pmtiles.tmp`
- 本番配置先: `frontend/layers/railways/railways_japan.pmtiles`
- ログ: 既存 JobManager のジョブログに開始、ダウンロード、生成、検証、反映、終了を出力

## 安全性確認

- OSM ダウンロードは `.tmp` に保存後 rename
- curl は `--fail` 付きで HTTP エラーを失敗扱い
- OSM PBF サイズ異常を検出
- PMTiles は staging 生成後、同一ディレクトリ内の `.tmp` を検証
- 反映は `Path.replace()` による atomic replace
- 生成・検証失敗時は既存 `railways_japan.pmtiles` を維持

## テスト結果

- `python3 -m compileall backend/app/api/admin_datasets.py backend/app/services/pipeline_service.py backend/app/services/dataset_state_service.py`: PASS
- `node --check frontend/admin/datasets.js`: PASS
- `node --check e2e/admin-railway-pmtiles.spec.js`: PASS
- `bash -n scripts/tile_build/build_railway_pmtiles.sh`: PASS
- `python3 -c 'import json; json.load(open("data_lake/registry/dataset_definitions.json")); print("dataset_definitions.json OK")'`: PASS
- `npx playwright test e2e/admin-railway-pmtiles.spec.js`: 19/19 PASS
- `npx playwright test e2e/admin-datasets.spec.js`: 61/61 PASS

## 未実施

- 実 OSM PBF ダウンロード
- 実 PMTiles 生成時間計測
- 生成後の `/live` 全国主要都市表示確認
- OSM URL 無効、tippecanoe 未存在、ディスク不足の実地失敗試験

## メモ

実運用での初回更新前に、backend 実行環境へ `osmium-tool`、`tippecanoe`、`tile-join` が入っていることを確認する。

# /live 鉄道運行情報 全国ODPT対応 Phase 7-A.5 CODEX検証

## 判定

PASS with notes

## 検証日

2026-07-08

## 確認結果

- ODPT取得対象: `challenge` / `contest` / `2026` / `limited` / `temporary` / `experimental` 相当の識別子除外を確認。日付フィールドの `2026` は誤除外しない。
- 正規化結果: `operator_name` / `railway_name` / `status` / `description` / `updated_at` / `source` / `matched_geojson` / 代表点 fallback を確認。
- GeoJSON一致路線: 京王線、東武東上線、有楽町線などが実ジオメトリ由来boundsに一致することを確認。
- GeoJSON未一致路線: 代表点を持つ関東外路線は fallback 点として統合boundsに含まれ、座標なし路線は東京駅固定に寄せないことを確認。
- 混在ケース: GeoJSON一致路線 + 未一致代表点路線の統合boundsが両方を含むことをE2Eで確認。
- 複数障害路線: 東西・南北に離れた複数路線が1路線だけにズームされず、統合boundsで収まることを確認。
- 路線名マッチング: 事業者接頭辞付きOSM名と裸の路線名の部分一致、短すぎる裸名の完全一致制限を確認。
- `/live`: HTTP 200 OK、全国・関東外鉄道データ表示、鉄道レイヤーON/OFFでクラッシュなし。
- `/live/stream`: HTTP 200 OK、鉄道小地図bounds、詳細カード巡回、東京駅固定fallback非再発を確認。

## 実行コマンド

```bash
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check frontend/js/live-stream/live-stream-panels.js
venv/bin/python -m pytest tests/test_live_train_service.py tests/test_live_train_api.py
curl -I http://127.0.0.1:8080/live
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
npx playwright test e2e/live-stream-railway-odpt-national.spec.js e2e/live-railway-odpt-national.spec.js
npx playwright test e2e/live-stream-railway-bounds-verification.spec.js e2e/live-stream-railway-phase5b.spec.js e2e/live-stream-railway-calm-map.spec.js e2e/live-stream-railway-color-layer.spec.js e2e/live-stream-railway-detail.spec.js e2e/rail-mock-verify.spec.js e2e/live-stream-railway-odpt-national.spec.js e2e/live-railway-odpt-national.spec.js
```

## 結果

- `node --check`: 2/2 PASS
- `pytest`: 75 passed
- `/live`: 200 OK
- `/live/stream?chrome=off`: 200 OK
- 全国ODPT専用E2E: 7 passed
- 鉄道関連E2E一式: 60 passed

## Notes

- ローカルの素の `python3` には `pytest` が無かったため、リポジトリの `venv/bin/python` で実行した。
- E2Eのテスト用静的サーバーではPMTiles Range配信に制約があるため、該当する既知の無害な `content-length header` / `Byte Serving` 系エラーは専用E2E内で除外している。
- 既存ナビ本体 (`index.html`, `navigation.js`, `nav-*.js`, `hazard-layers.js`, `location-info-panel.js`, reroute 関連) は変更していない。

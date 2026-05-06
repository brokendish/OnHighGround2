# OnHighGround2 ルート危険区間アウトライン表示 検証結果

## 実行日時

- 2026-05-06 17:25:19 JST

## 対象 commit

- `7cd8151`

## 対象差分

- `backend/main.py`
  - `/api/route-risk` のレスポンスに `sampled_points` を追加。
  - 既存の `safety_score` / `risk_level` / `risk_summary` は維持。
- `frontend/index.html`
  - `js/route-risk-outline.js` を `routing.js` より前に読み込み。
- `frontend/js/navigation.js`
  - route risk API 結果から `__riskSampledPoints` を route に保持。
- `frontend/js/routing.js`
  - 候補ルート再描画時に既存アウトラインをクリア。
  - 選択中ルートのみ危険区間アウトラインを描画。
- `frontend/js/route-risk-outline.js`
  - `sampled_points` から `caution` / `danger` セグメントを生成。
  - Leaflet pane でルート本体より下に黄/赤アウトラインを描画。

## 検証コマンド

```bash
git status --short
git diff --stat
git diff
docker compose ps
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8080/tiles/catalog
node --check frontend/js/route-risk-outline.js
node --check frontend/js/routing.js
node --check frontend/js/navigation.js
node --check frontend/js/ui.js
find frontend -name '*.js' -print0 | xargs -0 -n1 node --check
PYTHONPYCACHEPREFIX=.pycache-check python3 -m py_compile backend/main.py backend/app/services/route_risk_scoring.py
npx playwright test e2e/smoke.spec.js
npx playwright test e2e/evacuation-ui.spec.js e2e/clear-ui.spec.js
```

## API確認結果

- `docker compose restart backend` 後、`POST /api/route-risk` が 200 OK。
- レスポンスに以下が含まれることを確認。
  - `safety_score: 48.0`
  - `risk_level: "danger"`
  - `risk_summary.hazards`
  - `risk_summary.notes`
  - `sampled_points`
- `sampled_points` には各サンプル点の `lat` / `lon` / `hazards` が入り、`flood` / `storm_surge` / `lowland_poor_drainage` の `inside` 判定を確認。
- `safety_score` は 0-100 範囲内。

## UI確認結果

- Playwright で `frontend/` の静的配信を読み込み、以下を確認。
  - `buildRouteRiskSegments` がグローバル関数として利用可能。
  - `drawRouteRiskOutlines` がグローバル関数として利用可能。
  - `renderRouteCandidatesOnMap` が利用可能。
  - スマホ幅 `390x844` でページロード時の JS エラーなし。
- Node VM + Leaflet stub でアウトライン生成を直接確認。
  - セグメント状態: `["caution", "danger", "caution"]`
  - danger layer: `pane=routeRiskDanger`, `color=#ef4444`, `weight=17`
  - caution layer: `pane=routeRiskCaution`, `color=#facc15`, `weight=15`
- `routeRiskDanger` / `routeRiskCaution` pane は既存ルート本体より下の z-index で作成されるため、候補ルート色を維持する構成。
- `clearRouteCandidateLayers()` でアウトラインもクリアされるため、候補切替・再描画で古いアウトラインが残りにくい設計。
- route risk API 失敗時は `__riskSampledPoints` が設定されず、`drawRouteRiskOutlines` が呼ばれないため通常ルート描画は継続する設計。

## 回帰確認結果

- `node --check`:
  - `frontend/js/route-risk-outline.js`: PASS
  - `frontend/js/routing.js`: PASS
  - `frontend/js/navigation.js`: PASS
  - `frontend/js/ui.js`: PASS
  - `find frontend -name '*.js' ... node --check`: PASS
- Python compile:
  - `backend/main.py`: PASS
  - `backend/app/services/route_risk_scoring.py`: PASS
- Playwright:
  - `e2e/smoke.spec.js`: 7 passed
  - `e2e/evacuation-ui.spec.js` + `e2e/clear-ui.spec.js`: 10 passed

## 最終判定

PASS with notes

## Notes

- backend 再起動前は起動済みプロセスが古く、`sampled_points` が返らなかった。`docker compose restart backend` 後は期待どおり返った。
- 検証途中、ホストから `127.0.0.1:8080` への curl が一時的に connection refused になった。一方、既存 Playwright のローカル静的サーバ `127.0.0.1:8787` ではページロードと回帰テストが通った。
- 実地図上での目視確認は未実施。赤/黄アウトラインの視認性は実ハザードレイヤー ON/OFF とスマホ実機相当で追加目視するとより確実。

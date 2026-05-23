# キキクル Phase 3-B Codex 検証レポート

実施日: 2026-05-23

## 判定

PASS

Phase 3-B の「キキクルによるルート危険度のリアルタイム補正」について、固定ハザードを主判定にしたまま、キキクルは控えめな補正として扱われることを確認した。

## 確認した実装ポイント

- `/api/route-risk` が任意の `kikikuru` 入力を受け取り、`kikikuru_adjustment` を返す。
- キキクルなしでは既存の `safety_score` / `risk_level` / `sampled_points` 形式が維持される。
- キキクル単独の danger は `danger` 断定に直結しない。
- 固定ハザードとキキクルが重なる場合のみ補正を強める。
- penalty は上限付きで、score は 0 未満にならない。
- `unavailable` / `unknown` は penalty 0 で、`safe` にも `danger` にも倒さない。
- frontend は route-risk 用サンプリングを UI 表示用サンプリングと分離し、選択中ルートの補正だけをルートカードに表示する。
- 自動 reroute / route candidate 破棄には接続していない。

## API 確認

Docker backend: `http://127.0.0.1:8000`

### キキクルなし

- request: `/api/route-risk`
- coordinates: `[[35.6812,139.7671],[35.6850,139.7700]]`
- result:
  - `safety_score`: `31.0`
  - `risk_level`: `danger`
  - `kikikuru_adjustment.enabled`: `false`
  - `sampled_points`: 形式維持

### 固定洪水ハザード + 洪水キキクル danger

- request kikikuru:
  - `status`: `ok`
  - `flood`: `danger`
- result:
  - `safety_score`: `15.0`
  - `risk_level`: `danger`
  - `kikikuru_adjustment.penalty`: `16.0`
  - `kikikuru_adjustment.max_level`: `danger`
  - `matched_hazards`: `["flood","lowland_poor_drainage"]`
  - note: `キキクル補正（リアルタイム）: -16.0点 / 洪水キキクル危険（固定ハザード重複）`

### キキクル取得不可

- request kikikuru:
  - `status`: `unavailable`
- result:
  - `safety_score`: `31.0`
  - `risk_level`: `danger`
  - `kikikuru_adjustment.penalty`: `0.0`
  - note: `キキクル取得不可（補正なし）`

## JMA targetTimes 確認

2026-05-23 実行時点の先頭エントリ:

- `basetime`: `20260523014000`
- `validtime`: `20260523014000`
- `member`: `immed0`
- `elements`: `land`, `inund`, `flood_mesh`, `flood`, `designated_river`, `inland_flood`, `designated_river_nation`, `flood_riskline`

## 実ブラウザ確認

Docker frontend: `http://127.0.0.1:8080`

取得スクリーンショット:

- `tasks/screenshots/kikikuru_phase3b_adjustment_desktop.png`
- `tasks/screenshots/kikikuru_phase3b_adjustment_mobile.png`
- `tasks/screenshots/kikikuru_phase3b_unavailable.png`

Playwright probe 結果:

- desktop route text: `浸水:なし洪水:なし土砂:なし補正: −16pt 洪水キキクル危険（固定ハザード重複）`
- mobile route text: `浸水:なし洪水:なし土砂:なし補正: −16pt 洪水キキクル危険（固定ハザード重複）`
- unavailable route text: `浸水:なし洪水:なし土砂:なしキキクル取得不可（補正なし）`
- mobile overflow: `0`
- 25回 `map.fire('move')` 後の追加 request: `0`
- console error: `0`
- pageerror: `0`

## 実行コマンド

PASS:

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/navigation.js
python3 -m compileall backend/app backend/main.py
python3 -m unittest tests.test_route_risk_kikikuru
git diff --check
npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/info-tab-card-ui.spec.js e2e/hazard-state-consistency.spec.js
node /private/tmp/kikikuru_phase3b_docker_probe.js
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/api/route-risk ...
```

補足:

- `python3 -m unittest tests.test_route_risk_kikikuru`: 28 tests passed
- `npx playwright test e2e/kikikuru-layer.spec.js`: 33 passed
- 代表回帰: 18 passed

## 残リスク

- 実 JMA データで危険色が必ず出るとは限らないため、補正あり表示と取得不可表示は mock 中心で確認した。
- Phase 3-B では自動 reroute へ接続しない方針を維持した。reroute 接続は別 Phase で明示的に扱うのが安全。

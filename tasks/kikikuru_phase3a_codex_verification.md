# キキクル Phase 3-A Codex 検証レポート

検証日: 2026-05-22

## 判定

**PASS with notes**

- ルート未選択時はルート周辺要約を非表示にし、route preview では情報タブ内に `ルート周辺` 要約を表示できることを確認した。
- route change / route clear / `targetTimes.json` 更新失敗 / tile 取得失敗で古い safe 要約へ倒れないよう補強した。
- Phase 3-A のキキクル route summary は frontend 表示専用で、`/api/route-risk`、`safety_score`、`risk_level`、route ranking、reroute 判定へ接続していないことを確認した。
- 実 JMA データ確認時の代表ルートでは浸水・洪水・土砂が `なし` で、`注意` / `危険` の実データ目視は限定的。

## 実行コマンド

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/navigation.js
node --check frontend/js/destination.js
node --check frontend/js/map-overlay-ui.js
node --check e2e/kikikuru-layer.spec.js
python3 -m compileall backend/app backend/main.py
git diff --check
npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/info-tab-card-ui.spec.js e2e/hazard-state-consistency.spec.js
docker compose up -d --build
docker compose ps
curl -I http://127.0.0.1:8080
curl -s http://127.0.0.1:8000/health
curl -s https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json
curl -s -X POST http://127.0.0.1:8000/api/route-risk -H 'Content-Type: application/json' -d '...'
node /private/tmp/kikikuru_phase3a_docker_probe.js
```

## 実装確認

既存 Phase 3-A 実装は `frontend/js/kikikuru-layer.js` の route sampling にあり、ルート座標を最大 12 点へ間引いて浸水・洪水・土砂を aggregate する。map move には sampling hook を置かず、`onNavRouteSelected()` から route change hook を呼ぶ表示専用構成である。

今回の確認で以下を補強した。

- `targetTimes.json` 更新失敗時に route 要約も `取得不可` へ切り替え、古い `なし` を残さない。
- route null 選択と目的地 clear で `navActiveRoute` と route 要約を clear し、旧ルート再サンプリングを防ぐ。
- キキクルカードを `loc-info-nonnav` 内から情報タブ共通位置へ移し、route preview で親ごと非表示にならないようにした。
- route preview、route clear、tile failure、target time failure、map move、route-risk 非影響の E2E を追加した。

## Docker 実ブラウザ確認

Playwright で Docker frontend `http://127.0.0.1:8080/` を開いて確認した。

```text
route 作成前:
  route summary visible = false

route 作成後:
  status = 5/22 23:00 時点
  badge = 正常
  current = 浸水 なし / 洪水 なし / 土砂 なし
  destination = 浸水 なし / 洪水 なし / 土砂 なし
  route = 浸水 なし / 洪水 なし / 土砂 なし

route clear 後:
  route summary visible = false

未取得 entry で route sampling:
  route = 取得不可
```

- desktop と mobile viewport `390 x 844` で route preview のキキクルカードを確認した。
- mobile の情報タブ横 overflow は `0`。
- console error、page error は発生しなかった。

## スクリーンショット

- `tasks/screenshots/kikikuru_phase3a_route_summary_desktop.png`
- `tasks/screenshots/kikikuru_phase3a_route_summary_mobile.png`
- `tasks/screenshots/kikikuru_phase3a_route_summary_unavailable.png`

## ネットワーク確認

検証中の JMA `targetTimes.json` 最新確認例:

```text
basetime: 20260522135000
validtime: 20260522135000
member: immed0
elements: land, inund, flood_mesh, flood, ...
```

Docker probe では 3 種 ON と route summary 表示後に route 更新、25 回の `map.fire('move')` を実行した。

```text
map move 前: targetTimes.json 1 回 / risk tile 9 回
map move 後: targetTimes.json 1 回 / risk tile 9 回
```

- `targetTimes.json` の重複 fetch は観測しなかった。
- route 更新は route change hook でのみ実行され、map move 連続で sampling request は増えなかった。
- route 更新時は既存 tile cache が効く代表点では追加 tile request が不要だった。

## route-risk 非影響

実 API `POST /api/route-risk` のレスポンスを確認した。

```text
top-level keys:
  safety_score
  risk_level
  risk_summary
  sampled_points

sample:
  safety_score = 92.0
  risk_level = safe
```

- route-risk レスポンスにキキクル由来フィールドはない。
- E2E で route summary sampling 中に `/api/route-risk` request が発生しないことを確認した。
- E2E で route object の `safety_score`、`risk_level`、`risk_summary`、`__riskSummary` が sampling 前後で不変であることを確認した。
- 今回の変更は route ranking UI、route comparison API、navigation reroute 判定を変更していない。

## E2E

`e2e/kikikuru-layer.spec.js`:

- Phase 1 / Phase 2 のキキクル代表確認: PASS
- route 未選択 / route summary 表示 / route clear: PASS
- route preview でカードが見えること: PASS
- route change の async version guard: PASS
- route tile failure の `取得不可`: PASS
- route `targetTimes.json` 更新失敗後の古い `なし` 排除: PASS
- route-risk 非影響: PASS
- map move 25 回相当で sampling request が増えないこと: PASS
- route summary を含む mobile 幅: PASS
- 合計: 27/27 PASS

代表回帰:

- `e2e/weather-rain-radar-card.spec.js`: PASS
- `e2e/info-tab-card-ui.spec.js`: PASS
- `e2e/hazard-state-consistency.spec.js`: PASS
- 合計: 18/18 PASS

## Docker 状態

- `frontend`: `HTTP/1.1 200 OK`
- `backend`: `healthy`
- `martin`: healthy
- `osrm-walking`: running
- Docker build/up 直後は backend healthcheck 起動待ちがあり、起動完了後に health と route-risk API を再確認した。

## 残課題

- 実災害時でない代表ルートでは危険色の route summary を実データで目視できなかったため、キキクル分布が出ている地点で `注意` / `危険` aggregate を追加確認するとより確実。

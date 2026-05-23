# キキクル Phase 2 Codex 検証レポート

検証日: 2026-05-22

## 判定

**PASS with notes**

- 現在地周辺と目的地周辺の危険度要約を情報タブで確認した。
- 目的地要約は目的地設定時のみ表示され、目的地変更フックと clear 後の非表示を確認した。
- tile 取得失敗、未知の不透明色、`targetTimes.json` 更新失敗後の既存 `なし` 要約残留を safe 側へ倒さないよう修正・回帰化した。
- 実データ確認時の代表地点では 3 種とも `なし` だったため、危険色の目視確認は限定的。

## 実行コマンド

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/destination.js
node --check frontend/js/navigation.js
node --check e2e/kikikuru-layer.spec.js
python3 -m compileall backend/app backend/main.py
docker compose up -d --build
docker compose ps
curl -I http://127.0.0.1:8080
curl -s http://127.0.0.1:8000/health
curl -s https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json
npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/info-tab-card-ui.spec.js e2e/hazard-state-consistency.spec.js
node /private/tmp/kikikuru_phase2_docker_probe.js
```

Docker 実ブラウザ確認では Playwright で `http://127.0.0.1:8080/` を開き、実 JMA データ表示、未取得エントリ時の unavailable 表示、モバイル幅、map move 連続時の JMA request 数を確認した。

## 実行結果

- JS 構文チェック: PASS
- Python compileall: PASS
- Docker build/up: PASS
- `frontend` HTTP: `200 OK`
- `backend` health: `healthy`
- `martin`: healthy
- `osrm-walking`: running

## Docker 実ブラウザ確認

デスクトップで以下を確認した。

- 情報タブのキキクルカード内に現在地周辺要約が表示される。
- `userDestination` 設定後、目的地周辺要約が表示される。
- 実 JMA データ取得成功時、共通バッジは `正常`。
- 現在地、目的地とも浸水・洪水・土砂の 3 行が読める。
- 未取得エントリ経由の unavailable 状態では、現在地と目的地が `取得不可` になり `なし` 表示へ倒れない。
- page error、console error は発生しなかった。

実ブラウザ確認時の要約:

```text
status: 5/22 22:00 時点
badge: 正常
current: 浸水 なし / 洪水 なし / 土砂 なし
destination: 浸水 なし / 洪水 なし / 土砂 なし
unavailable current: 取得不可
unavailable destination: 取得不可
```

モバイル viewport `390 x 844` では以下を確認した。

- 情報タブの横 overflow: `0`
- 現在地周辺要約と目的地周辺要約が画面幅内に収まる。
- desktop と同じ要約文言を確認できる。

## スクリーンショット

- `tasks/screenshots/kikikuru_phase2_docker_desktop.png`
- `tasks/screenshots/kikikuru_phase2_mobile.png`
- `tasks/screenshots/kikikuru_phase2_unavailable.png`

## ネットワーク確認

検証時の `targetTimes.json` 最新エントリ:

```text
basetime: 20260522130000
validtime: 20260522130000
member: immed0
elements: land, inund, flood_mesh, flood, ...
```

Docker ブラウザで 3 種 ON、現在地/目的地サンプリング後に 25 回 `map.fire('move')` して確認した。

```text
move 前: targetTimes.json 1 回 / risk tile 6 回
move 後: targetTimes.json 1 回 / risk tile 6 回
```

- `targetTimes.json` の重複 fetch は観測しなかった。
- map move 連続で sampling 用 tile request は増えなかった。
- 実データ確認ページの JMA request で console error、page error は発生しなかった。

## E2E

`e2e/kikikuru-layer.spec.js`:

- Phase1 表示レイヤー代表確認: PASS
- 現在地/目的地セクション表示条件: PASS
- 目的地変更フックと clear 後の目的地要約非表示: PASS
- 透明 tile 時の `なし` 表示: PASS
- tile 取得失敗時の `取得不可`: PASS
- 未知の不透明色を `none` 扱いしない: PASS
- `targetTimes.json` 更新失敗後に既存 `なし` を残さない: PASS
- モバイル幅: PASS
- 合計: 17/17 PASS

代表回帰:

- `e2e/weather-rain-radar-card.spec.js`: PASS
- `e2e/info-tab-card-ui.spec.js`: PASS
- `e2e/hazard-state-consistency.spec.js`: PASS
- 合計: 18/18 PASS

## 修正内容

- JMA 危険度色として読めない不透明色を `none` ではなく `unavailable` にした。
- `targetTimes.json` 更新失敗時は現在地/目的地要約を `取得不可` に更新し、過去の `なし` 要約を残さないようにした。
- サンプリング結果に version を持たせ、失敗・clear 後に古い async 結果が要約を上書きしないようにした。
- `destination.js` の目的地適用/clear と `navigation.js` の route destination 選択から `kikikuruOnDestinationChange()` を呼び、目的地要約を実アプリ操作に接続した。
- 上記の safe 誤判定防止と目的地 clear を E2E に追加した。

## 残課題

- 実データ確認時の代表地点では危険色 tile を採れなかったため、危険度分布が出ている時刻/地点で `危険` / `注意` バッジの実データ目視を追加するとさらに確実。

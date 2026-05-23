# キキクル Phase 1-B / 1-C Codex 検証レポート

検証日: 2026-05-22

## 判定

**PASS with notes**

- 洪水キキクルは `flood_mesh` TileLayer として ON/OFF、実 JMA tile request を確認した。
- 土砂キキクルは `land` TileLayer として ON/OFF、実 JMA tile request を確認した。
- 浸水・洪水・土砂の 3 種同時 ON、個別状態表示、凡例表示、モバイル幅を確認した。
- 代表タイルは `HTTP/2 200` だが検証時点の代表座標では透明タイルで、危険度色の目視確認は限定的。

## 実行コマンド

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/map-overlay-ui.js
node --check e2e/kikikuru-layer.spec.js
python3 -m compileall backend/app backend/main.py
docker compose up -d --build
docker compose ps
curl -I http://127.0.0.1:8080
curl -s http://127.0.0.1:8000/health
curl -s https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json
curl -i https://www.jma.go.jp/bosai/jmatile/data/risk/20260522122000/immed0/20260522122000/surf/flood_mesh/10/909/403.png
curl -i https://www.jma.go.jp/bosai/jmatile/data/risk/20260522122000/immed0/20260522122000/surf/land/10/909/403.png
npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/hazard-state-consistency.spec.js e2e/info-tab-card-ui.spec.js
```

Docker 実ブラウザ確認では Playwright で `http://127.0.0.1:8080/` を開き、3 種同時 ON と凡例タブを確認した。

## 実行結果

- JS 構文チェック: PASS
- Python compileall: PASS
- Docker build/up: PASS
- `frontend` HTTP: `200 OK`
- `backend` health: `healthy`
  - Docker 再起動直後は healthcheck 起動待ちで curl が失敗し、起動完了後に healthy を確認した。
- `martin`: healthy
- `osrm-walking`: running
- `osrm-driving`: compose profile 未指定のため今回の起動対象外

## Docker 実ブラウザ確認

デスクトップで以下を確認した。

- 情報タブから浸水・洪水・土砂を個別に ON できる。
- 3 種同時 ON 時、共通バッジは `正常`。
- 種別状態は浸水・洪水・土砂の各ボタンで `正常`。
- 凡例タブに `キキクル（現在の危険度）` と `表示中: 浸水・洪水・土砂` が出る。
- `表示なし` と `取得不可` を区別する凡例補足が残っている。
- page error、console error、JMA risk request failure は発生しなかった。

実ブラウザ確認時の状態:

```text
status: 5/22 21:20 時点
badge: 正常
inund: .../surf/inund/{z}/{x}/{y}.png
flood: .../surf/flood_mesh/{z}/{x}/{y}.png
land: .../surf/land/{z}/{x}/{y}.png
kind states: 正常 / 正常 / 正常
```

モバイル viewport `390 x 844` では以下を確認した。

- 情報タブの横 overflow: `0`
- document body の横 overflow: `0`
- キキクルカード内の 3 種トグルが表示範囲を押し広げない。

## スクリーンショット

- `tasks/screenshots/kikikuru_phase1b_1c_docker_desktop.png`
- `tasks/screenshots/kikikuru_phase1b_1c_mobile.png`

## ネットワーク確認

検証時の `targetTimes.json` 最新エントリ:

```text
basetime: 20260522122000
validtime: 20260522122000
member: immed0
elements: land, inund, flood_mesh, flood, ...
```

Docker ブラウザの 3 種同時 ON で以下を確認した。

- `targetTimes.json` request: 1 回
- 浸水: `surf/inund/10/908/403.png` と隣接タイル
- 洪水: `surf/flood_mesh/10/908/403.png` と隣接タイル
- 土砂: `surf/land/10/908/403.png` と隣接タイル
- JMA risk request failure: なし
- CORS / mixed content による console error: なし

代表 curl 結果:

- `flood_mesh` tile: `HTTP/2 200`, `content-type: image/png`, `cache-control: max-age=86400`
- `land` tile: `HTTP/2 200`, `content-type: image/png`, `cache-control: max-age=86400`

## E2E

`e2e/kikikuru-layer.spec.js`:

- 浸水 ON/OFF と凡例/状態表示: PASS
- `targetTimes.json` 失敗時の `取得不可`: PASS
- 洪水 ON/OFF と `flood_mesh` tile request: PASS
- 土砂 ON/OFF と `land` tile request: PASS
- 3 種同時 ON と凡例表示: PASS
- 種別状態 `OFF` / `正常`: PASS
- モバイル幅: PASS
- 合計: 7/7 PASS

代表回帰:

- `e2e/hazard-state-consistency.spec.js`: PASS
- `e2e/info-tab-card-ui.spec.js`: PASS
- `e2e/weather-rain-radar-card.spec.js`: PASS
- 合計: 18/18 PASS

## 既存機能への影響

- キキクルはフロントエンド TileLayer 表示に留まり、ルート危険度スコア、現在地要約、目的地要約、ナビ警告には触れていない。
- 浸水キキクルの地図ショートカット active 同期は維持されている。
- 雨量カード、情報タブカード、hazard safe/unknown/unsafe 代表回帰は PASS。

## 修正内容

- 種別状態インジケーターを記号だけの表示から `OFF` / `確認中` / `正常` / `取得不可` の文言表示へ変更した。
- 洪水 E2E で `flood_mesh`、土砂 E2E で `land` の tile request 発生まで検証するようにした。
- 3 種を素早く ON にしたとき `targetTimes.json` の同時重複 fetch を共有 Promise で抑えた。
- 3 種同時 ON E2E で `targetTimes.json` request が 1 回で済むことを確認した。

## 残課題

- 検証時の代表タイルは透明で危険度色が薄いため、危険度分布が実際に出ている時刻/地点で固定ハザード、雨量、避難所、ルートとの重ね目視を追加するとより確実。

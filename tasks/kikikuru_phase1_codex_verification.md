# キキクル Phase 1 Codex 検証レポート

検証日: 2026-05-22

## 判定

**PASS with notes**

- 浸水キキクルは Docker 配信の実ブラウザで ON/OFF、時刻取得、JMA タイル取得、凡例表示を確認した。
- 時刻取得失敗時は `取得不可` を表示し、危険度なし扱いにはならないことを E2E で確認した。
- 検証中に、情報タブ内の専用 ON/OFF UI が初期状態で隠れる問題を修正した。
- 代表回帰で見つかった `e2e/info-tab-card-ui.spec.js` の旧表示名期待は、2026-05-21 の UX 手修正に合わせて更新した。

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
curl -i https://www.jma.go.jp/bosai/jmatile/data/risk/20260522113000/immed0/20260522113000/surf/inund/10/909/403.png
npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/info-tab-card-ui.spec.js e2e/hazard-state-consistency.spec.js
```

Docker 配信のブラウザ確認では Playwright で `http://127.0.0.1:8080/` を開き、情報タブで浸水キキクルを ON にして凡例タブのスクリーンショットを取得した。

## 実行結果

- JS 構文チェック: PASS
- Python compileall: PASS
  - 初回は sandbox 内の Python bytecode cache 書き込み制限で失敗し、許可後の再実行で PASS。
- Docker build/up: PASS
- `frontend` HTTP: `200 OK`
- `backend` health: `healthy`
- `martin`: healthy
- `osrm-walking`: running
- `osrm-driving`: compose profile 未指定のため今回の起動対象外

## ブラウザ確認結果

Docker 配信のデスクトップ実ブラウザで以下を確認した。

- 情報タブ内にキキクルカードと浸水/土砂/洪水トグルが表示される。
- 浸水キキクル ON で取得状態が `正常` になる。
- 状態テキストに JMA validtime が表示される。
- 凡例タブに `キキクル（現在の危険度）` 凡例が表示される。
- 画面初期化時と浸水キキクル ON 時に `pageerror`、console error は発生しなかった。
- モバイル幅 390px でキキクル UI が情報タブ幅からはみ出さないことを E2E で確認した。

実ブラウザ確認時の状態:

```text
status: 5/22 20:30 時点
badge: 正常
layerUrl: .../20260522113000/immed0/20260522113000/surf/inund/{z}/{x}/{y}.png
kikikuru request count: 3
pageErrors: []
consoleErrors: []
failed requests: []
```

## スクリーンショット

- `tasks/screenshots/kikikuru_phase1_docker_desktop.png`

## ネットワーク確認結果

- `targetTimes.json` の実レスポンス先頭で `20260522113000`、`member: immed0` を確認した。
- 実レスポンスの `elements` に `land`、`inund`、`flood_mesh`、`flood` が含まれる。
- Docker ブラウザから浸水タイル `surf/inund/10/909/403.png` と隣接タイル取得を確認した。
- タイル URL への `curl -i` は `HTTP/2 200`、`content-type: image/png`、`cache-control: max-age=86400` を返した。

## E2E

追加:

- `e2e/kikikuru-layer.spec.js`

確認内容:

- 情報タブから浸水キキクルを ON/OFF できる。
- 地図ショートカットボタン active 状態と情報タブの浸水トグルが同期する。
- 凡例タブで凡例を表示できる。
- `targetTimes.json` 取得失敗時に `取得不可` を表示し、レイヤーを作らない。
- モバイル幅で横スクロールを増やさない。

実行結果:

- `e2e/kikikuru-layer.spec.js`: 3/3 PASS
- `e2e/hazard-state-consistency.spec.js`: PASS
- `e2e/weather-rain-radar-card.spec.js`: PASS
- `e2e/info-tab-card-ui.spec.js`: PASS

`info-tab-card-ui` は旧表示名 `環境カード` を期待していたため、2026-05-21 の UX 手修正後の表示名 `日の出と月カード` に合わせて更新した。

## 既存機能への影響

- キキクルは固定ハザードレイヤーと別のフロントエンド TileLayer として追加されており、ルート危険度スコアやナビ判定には触れていない。
- 雨量カード代表 E2E と hazard safe/unknown/unsafe 代表 E2E は PASS。
- 凡例は既存凡例タブへ追加し、雨量凡例と同居する。

## 修正内容

- 情報タブ内のキキクル ON/OFF UI を初期状態でも操作可能にした。
- 情報タブの浸水トグルと地図上キキクルショートカットの active 状態を同期した。
- 凡例に、表示なしと取得不可を混同しないための補足文を追加した。
- キキクル専用 E2E を追加した。

## 残課題

- タイル表示の視認性は実データ状態に依存するため、強い危険度分布が出ている時刻で固定ハザード、雨量、避難所、ルートと重ねた目視確認を追加するとより確実。

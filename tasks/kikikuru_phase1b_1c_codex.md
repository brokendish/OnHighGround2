# OnHighGround2 キキクル Phase 1-B / 1-C CODEX 検証指示書

## 目的

Claude Code が実装したキキクル Phase 1-B / 1-C を検証する。

対象:

1. Phase 1-B: 洪水キキクル表示レイヤー追加
2. Phase 1-C: 土砂キキクル表示レイヤー追加

今回の検証範囲は **表示レイヤー、UI、取得状態、凡例、既存機能への影響** までとする。

ルート危険度スコア、現在地要約、目的地要約、ナビ警告への統合はまだ対象外。

## 前提

Phase 1では浸水キキクルが実装済みで、Docker実ブラウザで以下を確認済み。

- JMA `targetTimes.json` 取得
- 浸水タイル取得
- 情報タブON/OFF
- 地図ボタンとの active 同期
- 凡例表示
- `取得不可` と `表示なし` の区別
- モバイル幅での横はみ出し防止

Phase 1-B/1-Cでは、これを洪水・土砂へ横展開しているはず。

## 重要な確認観点

### 1. 浸水の退行確認

既存の浸水キキクルが壊れていないこと。

確認:

- 情報タブから浸水ON/OFFできる。
- 浸水ONでレイヤーが追加される。
- OFFでレイヤーが消える。
- 状態表示が `正常` / `OFF` / `取得不可` のいずれかとして破綻しない。
- pageerror / console error が出ない。

### 2. 洪水キキクル確認

確認:

- 情報タブから洪水ON/OFFできる。
- 洪水ONで JMA risk tile へのリクエストが発生する。
- URLに洪水系 element が含まれる。
  - 第一候補: `flood_mesh`
  - 実装方針により `flood` の場合もあり得る。
- OFFで洪水レイヤーだけ消える。
- 浸水ON/OFFには影響しない。

確認URL例:

```text
https://www.jma.go.jp/bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/flood_mesh/{z}/{x}/{y}.png
```

または:

```text
https://www.jma.go.jp/bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/flood/{z}/{x}/{y}.png
```

### 3. 土砂キキクル確認

確認:

- 情報タブから土砂ON/OFFできる。
- 土砂ONで JMA risk tile へのリクエストが発生する。
- URLに `land` が含まれる。
- OFFで土砂レイヤーだけ消える。
- 浸水・洪水ON/OFFには影響しない。

確認URL例:

```text
https://www.jma.go.jp/bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/land/{z}/{x}/{y}.png
```

### 4. 3種同時ON

確認:

- 浸水・洪水・土砂を同時にONできる。
- 3種の状態表示が破綻しない。
- OFF操作が個別に効く。
- 地図が操作不能にならない。
- console error / pageerror が出ない。

### 5. 取得不可と表示なしの区別

確認:

- `targetTimes.json` 取得失敗時に `取得不可` を表示する。
- 取得失敗時に「危険度なし」「表示なし」と誤表示しない。
- 1種の失敗で他の種別まで巻き込まない。
- 取得不可時にレイヤー作成を無理に行わない。

可能なら Playwright route mock で `targetTimes.json` を失敗させる。

### 6. 凡例確認

確認:

- 凡例タブに `キキクル（現在の危険度）` が表示される。
- 浸水・洪水・土砂に対応した説明がある。
- `表示なし` と `取得不可` の違いが説明されている。
- 雨量凡例や既存ハザード凡例が壊れていない。

### 7. モバイル確認

確認:

- viewport 390px 前後で情報タブが横にはみ出さない。
- キキクルトグル3種が押せる。
- 凡例表示が崩れない。
- bottom panel / map overlay controls の幅を押し広げない。

### 8. 既存機能への影響

最低限、以下を確認する。

- 雨量カード代表E2E
- hazard state consistency代表E2E
- frontend/backend Docker起動
- backend health
- JS構文チェック
- Python compileall

`info-tab-card-ui.spec.js` は Phase 1 の時点で既存UI文言ズレによる失敗が報告済み。今回も落ちた場合は、キキクル起因か既存ズレかを切り分ける。

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
npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/hazard-state-consistency.spec.js
```

必要に応じて `info-tab-card-ui.spec.js` も実行する。

```bash
npx playwright test e2e/info-tab-card-ui.spec.js
```

ただし失敗時は原因を必ず切り分ける。

## 実ブラウザ確認

Docker配信の画面を Playwright または手動で確認する。

URL:

```text
http://127.0.0.1:8080/
```

確認操作:

1. 情報タブを開く。
2. キキクルカードを確認する。
3. 浸水ON/OFF。
4. 洪水ON/OFF。
5. 土砂ON/OFF。
6. 3種同時ON。
7. 凡例タブを開く。
8. 取得状態表示を確認する。
9. モバイル幅で表示確認する。

スクリーンショットを保存する。

推奨:

```text
tasks/screenshots/kikikuru_phase1b_1c_docker_desktop.png
tasks/screenshots/kikikuru_phase1b_1c_mobile.png
```

## ネットワーク確認

ブラウザまたは Playwright で以下を確認する。

- `targetTimes.json` が取得されている。
- 洪水ON時に `flood_mesh` または `flood` のタイルリクエストがある。
- 土砂ON時に `land` のタイルリクエストがある。
- 失敗リクエストが大量発生していない。
- CORSやmixed contentの問題がない。

可能なら curl でも代表タイルを確認する。

```bash
curl -i "https://www.jma.go.jp/bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/flood_mesh/10/909/403.png"
curl -i "https://www.jma.go.jp/bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/land/10/909/403.png"
```

`{basetime}` `{member}` `{validtime}` は `targetTimes.json` から取得した値に置き換える。

## E2Eに追加・更新してほしい内容

既存 `e2e/kikikuru-layer.spec.js` を拡張する。

最低限:

- 浸水ON/OFFが退行していない。
- 洪水ON/OFFができる。
- 土砂ON/OFFができる。
- 3種同時ONができる。
- 洪水ON時に `flood_mesh` または `flood` URLへアクセスする。
- 土砂ON時に `land` URLへアクセスする。
- `targetTimes.json` 失敗時に `取得不可` を表示する。
- モバイル幅で横スクロールを増やさない。

## 判定基準

### PASS

以下をすべて満たす。

- 浸水・洪水・土砂のON/OFFが正常。
- 洪水・土砂のJMAタイル取得が確認できる。
- 取得状態が破綻しない。
- 凡例が3種対応。
- モバイルで横はみ出しなし。
- JS/Python/Docker/代表E2EがPASS。
- 既存の浸水キキクルが退行していない。

### PASS with notes

以下のような軽微な残課題があるが、Phase 1-B/1-C の目的は達成している。

- 実データの危険度分布が薄く、色の目視確認が限定的。
- `info-tab-card-ui.spec.js` など、キキクル外の既存テスト文言ズレが残る。
- 洪水が `flood_mesh` ではなく `flood` 実装になっているが、理由と動作確認が明確。

### FAIL

以下のいずれか。

- 洪水または土砂のON/OFFができない。
- 洪水または土砂のJMAタイル取得が確認できない。
- 取得不可を危険度なし扱いしている。
- 1種の失敗でキキクル全体が壊れる。
- JSエラーで既存UIが壊れる。
- 雨量カードや固定ハザードなど既存機能に明確な退行がある。

## 検証レポート

以下に作成する。

```text
tasks/kikikuru_phase1b_1c_codex_verification.md
```

レポートに含めること。

- 判定
- 実行コマンド
- 実行結果
- Docker実ブラウザ確認
- ネットワーク確認
- スクリーンショットパス
- E2E結果
- 既存機能への影響
- 修正した場合の内容
- 残課題

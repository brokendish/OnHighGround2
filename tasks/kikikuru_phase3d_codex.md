# キキクル Phase 3-D CODEX向け検証指示書

## 目的

Phase 3-D の「キキクル Simulation Mode」が、災害を待たずにキキクルのレイヤー表示・要約・route-risk 補正を再現できるか検証する。

対象:

```text
http://localhost:8080/admin/simulation
```

最重要:

- `/admin/simulation` で疑似キキクルレイヤーを表示できる
- 実 JMA データに依存せず、注意/危険/取得不可/unknown を再現できる
- 現在地・目的地・ルート周辺要約に反映される
- Phase 3-B のリアルタイム補正表示を再現できる
- 通常画面に mock が漏れない

---

## 必須検証

### 1. Simulation UI

確認:

- `/admin/simulation` にキキクル検証パネルがある
- シナリオを選択できる
- clear / なし に戻せる
- 操作時に console error / pageerror が出ない

最低限確認するシナリオ:

- なし
- 浸水 注意
- 浸水 危険
- 洪水 注意
- 洪水 危険
- 土砂 注意
- 土砂 危険
- 3種同時
- 取得不可
- unknown / 判定不可

---

### 2. 疑似レイヤー表示

確認:

- 地図上に疑似キキクルレイヤーが表示される
- 注意 / 危険 の見た目が凡例と一致する
- 浸水 / 洪水 / 土砂 の違いが分かる
- 既存固定ハザードと重ねて確認できる
- clear 後に疑似レイヤーが消える

スクリーンショット推奨:

- `tasks/screenshots/kikikuru_simulation_flood_danger.png`
- `tasks/screenshots/kikikuru_simulation_three_dangers.png`
- `tasks/screenshots/kikikuru_simulation_clear.png`

---

### 3. 要約反映

確認:

- 現在地周辺要約へ反映される
- 目的地周辺要約へ反映される
- ルート周辺要約へ反映される
- 取得不可は `なし` にならない
- unknown は `なし` にならない
- clear 後に古い要約が残らない

---

### 4. route-risk 補正表示

確認:

- 洪水危険 + 固定ハザード重複シナリオで `リアルタイム補正` が表示される
- 「洪水リスクが上昇しています」などの自然文が表示される
- 固定ハザードとキキクルが重なっている説明が出る
- penalty 表示が必要以上に前面に出ない
- 取得不可は `補正なし` になる

---

### 5. 本番通常画面への非漏洩

確認:

- `/` 通常画面では simulation panel が表示されない
- URL parameter なしの通常画面で mock layer が出ない
- localStorage 等に simulation state が残って通常画面へ漏れない
- JMA 実取得ロジックが通常画面で維持される

---

### 6. E2E / Playwright シナリオ指定

確認:

- URL parameter または `window.setKikikuruSimulationScenario()` でシナリオ指定できる
- deterministic に同じ結果が出る
- screenshot が安定して撮れる
- 実 JMA targetTimes / tile 通信に依存しない

---

### 7. mobile

確認:

- 390px viewport で横はみ出しなし
- simulation panel が操作可能
- 地図・凡例・情報タブが崩れない
- 重要文言が読める

スクリーンショット推奨:

- `tasks/screenshots/kikikuru_simulation_mobile.png`

---

### 8. 凡例

確認:

- キキクル凡例が見える
- 固定ハザード説明がある
- リアルタイム補正説明がある
- 取得不可説明がある
- 表示なしを安全確定と誤読しない

スクリーンショット推奨:

- `tasks/screenshots/kikikuru_simulation_legend.png`

---

## E2E 追加推奨

追加先候補:

- `e2e/simulation-mode.spec.js`
- `e2e/kikikuru-layer.spec.js`

追加テスト案:

1. `/admin/simulation` にキキクル検証パネルが表示される
2. 洪水危険シナリオで疑似レイヤーが表示される
3. 3種同時シナリオで凡例・要約が一致する
4. 取得不可シナリオで `なし` にならない
5. unknown シナリオで `なし` にならない
6. clear 後に疑似レイヤーと要約が消える
7. route-risk 補正表示が出る
8. 通常画面に simulation panel / mock layer が出ない
9. mobile overflow が 0
10. screenshot を保存する

---

## 実行コマンド例

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/display-labels.js
node --check frontend/js/map-overlay-ui.js
node --check frontend/js/navigation.js
node --check e2e/simulation-mode.spec.js
node --check e2e/kikikuru-layer.spec.js
python3 -m compileall backend/app backend/main.py
git diff --check

npx playwright test e2e/simulation-mode.spec.js
npx playwright test e2e/kikikuru-layer.spec.js
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/info-tab-card-ui.spec.js e2e/hazard-state-consistency.spec.js
```

Docker:

```bash
docker compose up -d --build
docker compose ps
curl -I http://127.0.0.1:8080/admin/simulation
curl -s http://127.0.0.1:8000/health
```

---

## Docker 実ブラウザ確認

必須:

- desktop
- mobile
- flood danger
- three danger
- unavailable
- unknown
- clear
- normal `/` non-leak

保存例:

- `tasks/screenshots/kikikuru_simulation_desktop.png`
- `tasks/screenshots/kikikuru_simulation_flood_danger.png`
- `tasks/screenshots/kikikuru_simulation_three_dangers.png`
- `tasks/screenshots/kikikuru_simulation_unavailable.png`
- `tasks/screenshots/kikikuru_simulation_mobile.png`
- `tasks/screenshots/kikikuru_simulation_legend.png`

---

## 判定基準

### PASS

- `/admin/simulation` でキキクルシナリオを操作できる
- 疑似レイヤーが地図に表示される
- 要約と route-risk 補正へ反映される
- 取得不可 / unknown を safe 扱いしない
- 通常画面に mock が漏れない
- E2E / 代表回帰 PASS
- console error / pageerror なし
- screenshot が保存される

### PASS with notes

許容:

- 疑似レイヤーのデザイン微調整余地
- 一部シナリオ名の文言調整余地
- pixel-level の厳密比較未実施

### FAIL

- 通常画面に mock が漏れる
- 取得不可が `なし` 表示になる
- unknown が `なし` 表示になる
- clear 後に疑似レイヤーが残る
- route-risk 補正が反映されない
- simulation 画面が mobile で操作不能
- request 暴走
- console error / pageerror

# キキクル Phase 3-D Claude Code向け実装指示書

## 目的

`/admin/simulation` にキキクル Simulation Mode を追加し、実災害や実 JMA データを待たずに、キキクルのレイヤー表示・要約・route-risk 補正・凡例を画面上で再現確認できるようにする。

狙い:

- 災害を待たずに注意/危険/取得不可/判定不可を再現する
- 疑似キキクルレイヤーを地図へ表示する
- 現在地・目的地・ルート周辺要約へ反映する
- Phase 3-B のリアルタイム補正表示へ反映する
- CODEX がスクリーンショット付き検証をしやすくする
- 通常画面・本番 JMA 取得ロジックへ影響させない

---

## 基本方針

Phase 3-D は次の併用で実装する。

### 案B: `/admin/simulation` の人間確認用 UI

人間が画面上でキキクルシナリオを選び、レイヤー・要約・補正・凡例を目視確認できるようにする。

### 案A: Playwright / E2E 用スタブ

E2E から同じシナリオを deterministic に指定できるようにする。

---

## 最重要制約

禁止:

- 通常画面 `/` で simulation mock が有効になること
- admin/simulation 以外で mock UI が表示されること
- 実 JMA targetTimes / tile 取得ロジックを壊すこと
- mock 状態を通常 route-risk に無条件混入すること
- 自動 reroute に接続すること
- 取得不可を `なし` / safe 扱いすること
- unknown を `なし` 扱いすること

許可:

- `/admin/simulation` のみ mock source を使う
- E2E のみ URL parameter / localStorage / window hook で mock scenario を注入する
- simulation 用 kikikuru payload を route-risk request に渡す
- mock layer を地図に重ねる

---

## 追加対象

```text
http://localhost:8080/admin/simulation
```

既存の災害シミュレーション画面に「キキクル検証」パネルを追加する。

---

## 追加 UI

### キキクル検証パネル

最低限のシナリオ:

- なし
- 浸水 注意
- 浸水 危険
- 洪水 注意
- 洪水 危険
- 土砂 注意
- 土砂 危険
- 3種同時 注意
- 3種同時 危険
- 取得不可
- 判定不可 / unknown

可能なら追加:

- 現在地のみ危険
- 目的地のみ危険
- ルート上のみ危険
- 固定ハザード重複

---

## 疑似レイヤー表示

`/admin/simulation` の地図上に、疑似キキクルレイヤーを表示する。

要件:

- 浸水・洪水・土砂を区別できる
- 注意・危険が視覚的に分かる
- 固定ハザードと重ねて見られる
- 凡例と一致する
- desktop / mobile で見やすい
- clear 後に消える

推奨実装:

まずは Leaflet の polygon / circle / rectangle / canvas overlay で疑似危険エリアを描画する。

必要になれば、後続で疑似 PNG tile endpoint を追加する。

---

## Simulation 状態注入

既存キキクルロジックへ simulation scenario を注入できるようにする。

例:

```js
window.setKikikuruSimulationScenario({
  enabled: true,
  scenario: 'flood_danger_overlap',
  values: {
    inund: 'none',
    flood: 'danger',
    land: 'none'
  },
  scope: 'route',
  unavailable: false
});
```

要件:

- `/admin/simulation` だけで使用
- 通常画面では無効
- E2E から呼び出せる
- scenario clear ができる
- localStorage を使う場合は通常画面へ漏れないようにする

---

## 要約への反映

simulation scenario を以下へ反映する。

- 現在地周辺要約
- 目的地周辺要約
- ルート周辺要約

例:

```text
ルート周辺
浸水: なし　洪水: 危険　土砂: なし
```

取得不可:

```text
ルート周辺
取得不可
```

判定不可:

```text
ルート周辺
判定不可
```

---

## route-risk 補正への反映

simulation scenario を使って、Phase 3-B の kikikuru payload / adjustment を再現する。

確認したい表示:

```text
リアルタイム補正
洪水リスクが上昇しています
固定ハザードとキキクルが重なっています
```

取得不可:

```text
キキクル取得不可（補正なし）
```

注意:

- simulation 用補正は検証用
- 本番 JMA 経路を壊さない
- 自動 reroute には接続しない

---

## 凡例

simulation 画面でも以下を確認できるようにする。

- 浸水キキクル
- 洪水キキクル
- 土砂キキクル
- 固定ハザード
- リアルタイム補正
- 取得不可
- 表示なしは安全確定ではない旨

---

## E2E 連携

E2E からシナリオ指定できるようにする。

例:

```js
await page.goto('/admin/simulation?kikikuruScenario=flood-danger-overlap');
```

または:

```js
await page.evaluate(() => {
  window.setKikikuruSimulationScenario({
    enabled: true,
    scenario: 'flood_danger_overlap'
  });
});
```

要件:

- deterministic に同じ画面が出る
- screenshot が撮れる
- scenario clear できる
- 実 JMA targetTimes / tile 通信に依存しない

---

## スクリーンショット保存想定

CODEX が保存しやすい状態を作る。

- `tasks/screenshots/kikikuru_simulation_none.png`
- `tasks/screenshots/kikikuru_simulation_flood_danger.png`
- `tasks/screenshots/kikikuru_simulation_three_dangers.png`
- `tasks/screenshots/kikikuru_simulation_unavailable.png`
- `tasks/screenshots/kikikuru_simulation_mobile.png`
- `tasks/screenshots/kikikuru_simulation_legend.png`

---

## 実装候補ファイル

- `frontend/admin/simulation*`
- `frontend/js/kikikuru-layer.js`
- `frontend/js/display-labels.js`
- `frontend/js/map-overlay-ui.js`
- `frontend/js/navigation.js`
- `frontend/index.html`
- `e2e/simulation-mode.spec.js`
- `e2e/kikikuru-layer.spec.js`
- route-risk 関連テスト

既存構造に合わせて最小変更にすること。

---

## 非対象

今回はやらない:

- 本番自動 reroute
- push 通知
- 音声案内
- 実 JMA データ仕様変更対応
- pixel diff の厳密画像比較
- AI 判断文生成

---

## 完了条件

- `/admin/simulation` にキキクル検証パネルがある
- シナリオ選択で疑似レイヤーが地図に表示される
- 浸水・洪水・土砂の注意/危険を再現できる
- 現在地・目的地・ルート周辺要約へ反映される
- route-risk のリアルタイム補正表示を再現できる
- 取得不可 / unknown を safe 扱いしない
- 凡例で意味を確認できる
- E2E から scenario 指定できる
- mobile で崩れない
- 通常画面に mock UI が出ない
- 既存回帰 PASS

# キキクル Phase 3-C Codex 検証レポート

実施日: 2026-05-23

## 判定

PASS

Phase 3-C の表示改善に対し、共通表示名レイヤーを一般 UI の fallback 経路にも適用し、凡例・取得不可配色・モバイル折返しを補修した。内部 ID を表示しないこと、自然文でリアルタイム補正を伝えること、390px 幅で表示が崩れないことを確認した。

## 実施した補修

- `frontend/js/display-labels.js` を追加し、固定ハザード・キキクル種別・状態名の表示辞書を共通化。
- キキクル補正、情報タブ、避難所カード、避難所 popup、ハザード状態表示、レイヤー状態表示の fallback を翻訳済み名称へ統一。
- 未登録 ID の fallback は `対象ハザード` とし、内部 ID をそのまま UI に出さない。
- 凡例に `固定ハザード`、`キキクル`、`リアルタイム補正`、`取得不可` の説明を追加。
- `取得不可` のバッジ／種別ステータスを neutral gray に変更し、危険色との混同を回避。
- 補正説明の折返しを `overflow-wrap` に変更し、モバイルでの不自然な文字分割を抑制。

## 公式用語確認

気象庁のキキクル案内と照合し、一般 UI の種別名が以下の公式表記であることを確認した。

- `浸水キキクル`
- `洪水キキクル`
- `土砂キキクル`

## E2E 確認

追加・強化した確認:

- 凡例が固定ハザード、リアルタイム補正、取得不可の意味を表示する。
- 取得不可 badge が neutral gray で表示される。
- 情報タブの対応ハザードが `lowland_poor_drainage` / `flood_mesh` / 未登録 ID を表示しない。
- 公式キキクル名称、説明文、mobile fit を維持する。

実行結果:

```bash
npx playwright test e2e/kikikuru-layer.spec.js e2e/weather-rain-radar-card.spec.js e2e/info-tab-card-ui.spec.js e2e/hazard-state-consistency.spec.js
```

- `57 passed`

## 静的確認

PASS:

```bash
node --check frontend/js/display-labels.js
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/navigation.js
node --check frontend/js/map-overlay-ui.js
node --check frontend/js/location-info-panel.js
node --check frontend/js/shelter-browse-layer.js
node --check frontend/js/shelters.js
node --check frontend/js/ui.js
node --check frontend/js/hazard-layers.js
node --check e2e/kikikuru-layer.spec.js
git diff --check
```

## Docker 実ブラウザ確認

確認環境:

- frontend: `http://127.0.0.1:8080`
- backend health: healthy

スクリーンショット:

- `tasks/screenshots/kikikuru_phase3c_desktop.png`
- `tasks/screenshots/kikikuru_phase3c_mobile.png`
- `tasks/screenshots/kikikuru_phase3c_legend.png`

確認結果:

- desktop: `リアルタイム補正`、`洪水リスクが上昇しています`、固定ハザード重複説明を表示。
- mobile 390px: `overflow = 0`。
- desktop/mobile の可視テキスト内で禁止内部 ID は `0` 件。
- 凡例は固定ハザード、キキクル、リアルタイム補正、取得不可説明を表示。
- console error: `0`。
- pageerror: `0`。

## 補足

- 危険状態の表示は再現性を確保するため mock 補正で確認した。
- Phase 3-C の対象外である reroute 判定ロジックは変更していない。

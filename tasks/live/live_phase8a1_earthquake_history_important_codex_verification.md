# Phase 8-A.1 地震履歴の重要地震固定表示・JMA fallback明示 検証結果

## 判定

PASS

過去3日分の地震履歴、重要地震の上部固定、JMA fallback 時の `JMA fallback / 市区町村震度なし` 明示、`unknown` 非表示、重要地震マーカー/ポップアップ、PC/モバイル表示を確認した。

## 実装・確認内容

- `/api/live/earthquakes/history?days=3` で各地震に `isImportant`、`importantReasons`、`municipalityIntensityAvailable` を付与。
- P2P 取得が例外または空の場合に JMA fallback へ移行。
- 重要地震条件を `M5以上` または `最大震度5弱以上` に統一。
- LIVE 警戒カード上部に `重要地震` セクションを固定表示。
- 履歴見出しは `地震 N件 (3日間)`、重要地震ありの場合は `M5以上/震度5弱 N件` として既存の `M5以上` 表示契約も維持。
- JMA fallback 時はカード、重要地震、履歴、マーカーポップアップに `JMA fallback / 市区町村震度なし` を表示。
- `unknown` は UI 表示で `不明` / `最大震度不明` に変換。
- 重要地震マーカーを通常履歴地震より後に描画し、半径・枠線を強調。

## 追加/更新した E2E

- `e2e/live-eq-important.spec.js`

追加ケース:

- 重要地震セクション表示
- M7.2 重要地震固定
- 最大震度5弱以上の重要地震判定
- 小規模地震が増えても重要地震が上部固定
- P2P 成功時に fallback 注意文が出ない
- JMA fallback 時の `JMA fallback / 市区町村震度なし`
- `unknown` 非表示
- 重要地震マーカー/ポップアップ
- モバイルボトムシート表示と横スクロールなし
- console error / page error なし

## 実行コマンド

```bash
python3 -m compileall backend/app/api/live_earthquakes.py
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-layers.js
node --check e2e/live-eq-important.spec.js
npx playwright test e2e/live-eq-important.spec.js
npx playwright test e2e/live-eq-list-tsunami.spec.js
npx playwright test e2e/live-basic.spec.js --grep "F:|地震1件|M5以上|津波警報カード|カードに津波"
docker compose ps
node /private/tmp/live_phase8a1_screenshots.js
```

## 結果

- backend compile: PASS
- frontend JS syntax: PASS
- Phase 8-A.1 E2E: 26 passed
- 津波警報中の地震リスト回帰: 14 passed
- live-basic 地震関連回帰: 10 passed
- Docker: backend / frontend / martin / osrm-walking が起動中、backend と martin は healthy

## 確認した画面

- `/live.html` デスクトップ幅
- `/live.html` モバイル幅 390x844、ボトムシート展開状態

## スクリーンショット

- PC: `tasks/live/live_phase8a1_desktop.png`
- Mobile: `tasks/live/live_phase8a1_mobile.png`

## 残課題

- なし。

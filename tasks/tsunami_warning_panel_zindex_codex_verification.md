# 津波警告バナー・情報パネル重なり順 CODEX検証レポート

## 判定

PASS

スマホ幅で津波警告バナー表示中に情報パネルを最大化しても、情報パネルのハンドル・タブ・スクロール操作が妨げられないことを確認した。

## 確認日時

2026-06-09 00:20:02 JST

## 確認環境

- リポジトリ: `/Users/hideki/Documents/GitHub/OnHighGround2`
- backend: `http://127.0.0.1:8000`
- frontend/e2e static server: `http://127.0.0.1:8787`
- viewport: 390 x 844
- Docker backend health: `healthy`

## 実行コマンド

```bash
python3 -m compileall backend
find frontend/js -name "*.js" -print0 | xargs -0 -n1 node --check
node --check e2e/tsunami-warning-panel-zindex.spec.js
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/live/summary
npx playwright test e2e/tsunami-warning-panel-zindex.spec.js
npx playwright test e2e/tsunami-warning.spec.js
npx playwright test e2e/live-basic.spec.js
npx playwright test e2e/live-storm-surge.spec.js
```

## 確認結果

- backend compile: PASS
- frontend JS syntax: PASS
- 新規E2E syntax: PASS
- health: PASS (`status: "healthy"`)
- 実 `/api/live/summary`: PASS。津波は `status: "ok"`, `summary.active: false`, `areas: []`
- `e2e/tsunami-warning-panel-zindex.spec.js`: PASS。3件すべて成功
- `e2e/tsunami-warning.spec.js`: PASS。10件すべて成功
- `e2e/live-basic.spec.js`: PASS。73件すべて成功
- `e2e/live-storm-surge.spec.js`: PASS。32件すべて成功

## スマホUI確認

- 津波警告 active mock で `#tsunami-warning-banner` が表示される。
- 390px幅で横スクロールなし。
- 情報パネルを情報タブに切り替え、`#map-bottom-handle` で最大化できる。
- 最大化時、`body.mbc-panel-info-expanded #map-ui-overlay` の `z-index` が `1300` になり、津波バナー `z-index: 1200` より前面に出る。
- 情報パネル最大化中、ハンドル操作で折りたたみ可能。
- 情報パネル最大化中、レイヤータブ・情報タブの切り替えが可能。
- 情報パネル内スクロールが可能。
- 情報パネル操作後も active 中の津波警告バナーは表示継続。

## スクリーンショット

- `test-results/tsunami-warning-panel-zindex-mobile.png`

## Notes

- 情報パネルには独立した `×` close button はなく、`#map-bottom-handle` が縮小・折りたたみ操作を担う。E2Eではこの実UIに合わせて、最大化から折りたたみ可能であることを確認した。
- 静的確認では、通常 `#map-ui-overlay` は `z-index: 900`、津波バナーは `z-index: 1200`。情報パネル最大化時のみ `body.mbc-panel-info-expanded #map-ui-overlay { z-index: 1300; }` に引き上げられる。
- `#map-ui-overlay` は `pointer-events: none`、子要素は `pointer-events: auto`。津波バナーは `pointer-events: auto`。乱用による操作不能は確認されなかった。
- `#map-bottom-controls` 自体は `transform: translateX(-50%)` による stacking context を作るが、親 overlay の最大化時 z-index が津波バナーより高いため、操作部は前面に出る。

## 修正が必要な点

なし。

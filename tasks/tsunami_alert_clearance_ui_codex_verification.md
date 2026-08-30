# 津波警報解除反映・UI改善 CODEX検証レポート

## 判定

PASS

Claude修正後、`status: "active"` のときのみ津波警告バナーが表示されることを確認した。
前回FAILだった `status: "stale"` は、警告色バナーとして表示されなくなった。

## 確認日時

2026-06-08 23:50:10 JST

## 確認環境

- リポジトリ: repository root
- backend: `http://127.0.0.1:8000`
- frontend: `http://127.0.0.1:8080`
- Playwright 静的テストサーバー: `http://127.0.0.1:8787`
- Docker: backend / frontend / martin / osrm-walking 起動済み

## 実行コマンド

```bash
python3 -m compileall backend
find frontend/js -name "*.js" -print0 | xargs -0 -n1 node --check
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/live/summary
npx playwright test e2e/tsunami-warning.spec.js
npx playwright test e2e/live-storm-surge.spec.js
npx playwright test e2e/live-basic.spec.js
```

## 確認結果

- backend compile: PASS
- frontend JS syntax: PASS
- Docker/backend health: PASS (`status: "healthy"`)
- 実 `/api/live/summary`: PASS。津波は `status: "ok"`, `summary.active: false`, `areas: []`
- 津波E2E: PASS。`e2e/tsunami-warning.spec.js` 9件すべて成功
- `/live` 高潮・津波回帰: PASS。`e2e/live-storm-surge.spec.js` 32件すべて成功
- `/live` 基本回帰: PASS。`e2e/live-basic.spec.js` 73件すべて成功

## 津波バナー詳細

- active: PASS。注意報・警報・大津波警報バナーが表示される
- active -> cleared: PASS。バナー非表示
- active -> unavailable/API 500: PASS。前回警告は残らない
- none: PASS。バナー非表示
- stale: PASS。警告バナー非表示
- mobile layout: 前回検証で PASS。390px幅で横スクロールなし、長い対象地域は3件 + `ほか` に省略

## スクリーンショット

前回検証で取得:

- `/private/tmp/tsunami-active-mobile-390.png`
- `/private/tmp/root-regression-mobile-390.png`
- `/private/tmp/live-regression-mobile-390.png`

## Notes

- `frontend/js/tsunami-warning.js` は `status !== "active"` で非表示に変更済み。
- コードコメントに stale 表示の古い説明が残っていたため、実装に合わせて更新した。
- `e2e/tsunami-warning.spec.js` の新規 stale / cleared / 500 モックは、特定API route が `/api/**` より優先されるよう登録順を修正した。これにより stale テストが false positive にならない。
- 一時 no-setup Playwright 実行は `127.0.0.1:8787` 未起動時に接続拒否になったため、正式確認は通常設定の `npx playwright test ...` で実施した。
- `live-basic` と `live-storm-surge` の並列実行ではテストサーバーの `EADDRINUSE` が出たため、最終確認は単独実行で行った。

## 修正が必要な点

なし。

# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 5-C：demo mode console error / diagnostics 状態整理 MVP 検証

## 目的

Claude実装後、Phase 5-B で残った notes が解消または整理されていることを検証する。

検証対象の中心は以下。

```text
1. demo=1 中の TypeError: Failed to fetch console error が解消されていること
2. demo=1 の diagnostics が loading のまま残らないこと
3. demo / real / calm の dataMode と runtimeState が区別できること
4. real API failure と demo mode が混同されないこと
5. Phase 5-B までの安定性・表示同期が回帰しないこと
```

Phase 5-C は UI追加フェーズではなく、配信用安定運用の仕上げとしての console / diagnostics 整理フェーズである。

---

## 事前確認

まず以下を確認する。

```bash
git diff --stat
git diff
```

必ず以下のガードレールを読む。

```text
docs/live/DEVELOPMENT_GUARDRAILS.md
```

Phase 5-B の検証レポートも確認する。

```text
tasks/live/live_stream_phase5b_obs_soak_codex_verification.md
```

Phase 5-B の重要 notes:

```text
demo 10分で TypeError: Failed to fetch console error が4件
runtimeState=loading のまま
画面破綻や pageerror はなし
```

---

## 静的確認

### JS構文確認

変更対象に応じて以下を実行する。

```bash
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-rain-layer.js
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check frontend/js/live-stream/live-stream-earthquake-detail.js
node --check frontend/js/live-stream/live-stream-panels.js
```

新規E2Eがある場合も確認する。

```bash
node --check e2e/live-stream-demo-diagnostics.spec.js
```

実際のファイル名に合わせて追加/読み替えする。

---

## 差分確認観点

以下を重点確認する。

```text
console.error を握りつぶしていないか
window.onerror / unhandledrejection を不自然に握りつぶしていないか
demo mode で不要な /api/live/* fetch が止まっているか
必要な fetch failure は catch され diagnostics に記録されるか
runtimeState / dataMode の区別ができるか
real API failure を demo と誤判定していないか
API failure 時に demo fallback していないか
通常 /live へ stream 専用分岐を入れていないか
```

---

## Docker / HTTP確認

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test"
curl -I "http://127.0.0.1:8080/live/stream?state=calm&chrome=off"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

すべて 200 OK を期待する。

---

## E2E実行

### Phase 5-C 追加E2E

新規/更新された demo diagnostics E2E を実行する。

```bash
npx playwright test e2e/live-stream-demo-diagnostics.spec.js
```

### 既存 scoped E2E

可能なら Phase 5-B と同等の scoped E2E を実行する。

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-stability.spec.js \
  e2e/live-stream-earthquake-detail.spec.js \
  e2e/live-stream-earthquake-detail-map-sync.spec.js \
  e2e/live-stream-railway-detail.spec.js \
  e2e/live-stream-railway-color-layer.spec.js \
  e2e/live-stream-railway-calm-map.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

全体 `e2e/` を無理に実行しない。
Stream Phase 5-C と無関係な navigation / reroute harness の既存失敗を混ぜないこと。

---

## 必須検証観点

## 1. demo mode の console error 解消

URL:

```text
http://127.0.0.1:8080/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
```

Playwright で以下を監視する。

```js
const pageErrors = [];
const consoleErrors = [];
const failedToFetchErrors = [];

page.on('pageerror', (err) => pageErrors.push(err.message));
page.on('console', (msg) => {
  if (msg.type() === 'error') {
    const text = msg.text();
    consoleErrors.push(text);
    if (text.includes('TypeError: Failed to fetch') || text.includes('Failed to fetch')) {
      failedToFetchErrors.push(text);
    }
  }
});
```

期待:

```text
pageErrors.length === 0
failedToFetchErrors.length === 0
app起因の重大 console error なし
```

タイル/PMTilesの `requestfailed` は別扱いでよいが、console error として出ていないことを確認する。

---

## 2. demo mode の live API fetch 抑制

`demo=1` で `/api/live/*` への不要な periodic fetch が走っていないか確認する。

```js
const liveApiRequests = [];
page.on('request', (request) => {
  if (request.url().includes('/api/live/')) {
    liveApiRequests.push(request.url());
  }
});
```

期待:

```text
原則 liveApiRequests.length === 0
```

もし設計上必要なAPIがある場合は、レポートに明記する。
その場合でも `TypeError: Failed to fetch` や unhandled rejection が出ないこと。

---

## 3. diagnostics の demo 状態確認

`window.__LiveStreamDiagnostics.getSnapshot()` を確認する。

期待例:

```js
const snapshot = await page.evaluate(() => window.__LiveStreamDiagnostics.getSnapshot());
```

確認:

```text
snapshot.dataMode === "demo"
snapshot.runtimeState !== "loading"
snapshot.runtimeState === "demo" または "synthetic" など明確なdemo状態
snapshot.isDemo === true
snapshot.refreshInFlight === false
snapshot.eventCount > 0
recentFetchFailures が空、または許容された静的asset失敗のみ
```

body attribute も確認する。

```js
await page.locator('body').getAttribute('data-stream-data-mode')
await page.locator('body').getAttribute('data-stream-runtime-state')
```

期待:

```text
data-stream-data-mode="demo"
data-stream-runtime-state="demo" または synthetic 等
```

---

## 4. demo表示回帰確認

以下が維持されること。

```text
map marker / pulse が表示される
panel が表示される
ticker が表示される
focus が動く
地震詳細子画面が表示される
鉄道小画面が表示される
鉄道路線カラーが表示される
```

Phase 5-C で diagnostics を直した結果、demo表示が壊れていたら FAIL。

---

## 5. real API failure との区別

Playwright route mock で `/api/live/*` を 500 にする。

URL:

```text
http://127.0.0.1:8080/live/stream?chrome=off&runtimeSpeed=test
```

期待:

```text
snapshot.dataMode === "real"
snapshot.runtimeState === "degraded" または "error"
body[data-stream-data-mode="real"]
body[data-stream-runtime-state="error" or "degraded"]
ticker は取得確認中
demo marker / demo panel へ fallback しない
pageerror なし
```

意図的な 500 による browser console の `Failed to load resource` は PASS with notes 可。
ただし `TypeError: Failed to fetch` の未処理例外は FAIL。

---

## 6. calm mode との区別

URL:

```text
http://127.0.0.1:8080/live/stream?state=calm&chrome=off
```

期待:

```text
snapshot.dataMode === "calm"
snapshot.isCalm === true
map markers 0
focus しない
ticker は監視中
demo表示なし
```

runtimeState は `calm` または既存互換で `healthy` でもよい。
ただし dataMode=calm が明示されていること。

---

## 7. 通常 real mode 回帰

URL:

```text
http://127.0.0.1:8080/live/stream?chrome=off
```

期待:

```text
snapshot.dataMode === "real"
runtimeState が healthy / degraded / error のいずれかとして自然
loading のまま固定されない
地図・パネル・tickerが表示される
pageerrorなし
```

---

## 8. `/live` と `/` 回帰

```bash
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

可能ならブラウザでも開く。

期待:

```text
HTTP 200
pageerrorなし
/live通常画面に明確な副作用なし
```

---

## short soak / probe

可能なら demo mode で 3〜5分程度の短時間 probe を行う。

URL:

```text
/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
```

確認:

```text
pageerror 0
TypeError: Failed to fetch 0
runtimeState が loading に戻らない
Leaflet containers が増殖しない
tickerTextNodes が増殖しない
focus が動く
```

30分や60分のsoakは Phase 5-C 必須ではない。

---

## スクリーンショット

以下を保存する。

```bash
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 "http://127.0.0.1:8080/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test" test-results/live-stream-phase5c-demo-diagnostics-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" test-results/live-stream-phase5c-calm-diagnostics-1920.png
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 "http://127.0.0.1:8080/live/stream?chrome=off" test-results/live-stream-phase5c-real-diagnostics-1920.png
```

---

## レポート作成

以下にレポートを作成する。

```text
tasks/live/live_stream_phase5c_demo_diagnostics_codex_verification.md
```

レポート構成:

```md
# live stream Phase 5-C demo diagnostics verification

## Result
PASS / FAIL / PASS with notes

## Summary

## Checked files

## Environment

## Commands

## Test results

## Demo console check

## Diagnostics check

## Real failure check

## Calm check

## Screenshots

## Findings

## Notes

## Final judgement
```

必ず以下を明記する。

```text
TypeError: Failed to fetch の原因
どう解消したか
/demo=1 の runtimeState / dataMode
real failure との区別
console error / pageerror の有無
scoped E2E の件数
残 notes
```

---

## PASS条件

以下を満たせば PASS。

```text
demo=1 で TypeError: Failed to fetch が出ない
demo=1 で runtimeState が loading のままにならない
diagnostics で dataMode=demo が確認できる
body data attribute で demo状態が確認できる
demo表示・focus・ticker・panel・map が維持される
real API failure は error/degraded として扱われ、demoとは区別される
API failure 時に demo fallback しない
calm は dataMode=calm として区別される
pageerror / unhandledrejection なし
scoped E2E PASS
/live と / に明確な副作用なし
検証レポート作成済み
```

---

## PASS with notes 条件

以下は PASS with notes 可。

```text
意図的な 500 テストの Failed to load resource が console に出る
タイル/PMTiles/CARTO の requestfailed が残るが画面破綻なし
runtimeState 名は demo ではなく synthetic だが dataMode=demo が明示される
calm runtimeState は healthy のままだが dataMode=calm が明示される
短時間probeのみで、10分以上のdemo soakは未実施
```

---

## FAIL条件

以下があれば FAIL。

```text
demo=1 で TypeError: Failed to fetch が再発する
demo=1 で runtimeState が loading のままになる
demo表示が壊れる
real API failure が calm / 平常扱いになる
real API failure で demo fallback する
pageerror / unhandledrejection が出る
/live が壊れる
console.error を握りつぶしているだけ
```

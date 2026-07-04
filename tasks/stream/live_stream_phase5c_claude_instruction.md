# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 5-C：demo mode console error / diagnostics 状態整理 MVP

## 目的

`/live/stream` の Phase 5-B soak 検証で確認された以下の notes を解消または整理する。

- `demo=1` 10分soak中に `TypeError: Failed to fetch` が 4件 console error として出た
- `demo=1` では本番API refreshを使わない想定だが、diagnostics の `runtimeState` が `loading` のままになっていた
- 配信用画面として、demo mode / synthetic data mode の runtime 状態を明確化したい

Phase 5-C の目的は、見た目の追加ではなく、**配信運用時の console noise 削減と diagnostics の状態整理**である。

Phase 5-B の結果では、通常30分soak、calm 10分、demo 10分、API失敗・復帰10分、scoped E2E 191 passed まで確認済み。今回の Phase 5-C は、その追加改善として扱う。

---

## 背景

Phase 5-B 検証では、通常モードでは30分soakで以下が確認済み。

```text
pageerror: 0
console error: 0
Leaflet containers: 4 -> 4
railwayLayer.layerCount: 2 -> 2
tickerTextNodes: 2 -> 2
runtimeState: healthy -> healthy
```

一方で demo mode では以下の notes が残った。

```text
demo=1 10分soak:
  pageerror: 0
  console error: 4
  console error 内容: TypeError: Failed to fetch
  runtimeState: loading -> loading
```

画面破綻はしていないため致命傷ではないが、OBS / YouTube 配信想定では console error の発生元を潰すか、少なくとも状態として正しく扱う必要がある。

---

## 重要方針

### 1. `/live` を壊さない

通常 `/live` の既存UI、既存JS、既存API挙動を変更しないこと。

`/live/stream` 専用JS/CSS内で完結させる。

禁止:

```text
/live 本体の fetch / 地図 / レイヤー挙動を stream 都合で変更する
既存 backend API のレスポンス形式を stream 都合で変更する
通常 /live の回帰確認なしに共通処理を変更する
```

---

### 2. console error を隠すのではなく原因を潰す

`console.error = () => {}` のような握りつぶしは禁止。

やるべきこと:

```text
発生元 fetch を特定する
不要な fetch なら demo mode では起動しない
必要な fetch なら catch / timeout / AbortError / network failure を正規の failure state として扱う
diagnostics にどの fetch が失敗したか分かる情報を出す
```

console を完全に無音化する目的で、本当の不具合を隠してはいけない。

---

### 3. demo mode は本番APIとは別状態として扱う

`demo=1` は synthetic event / demo event を表示するモードであり、通常の live API refresh と同じ `loading` 状態に置き続けるのは分かりにくい。

Phase 5-C では、demo mode の runtime state を明確化する。

推奨:

```text
body[data-stream-runtime-state="demo"]
body[data-stream-data-mode="demo"]
window.__LiveStreamDiagnostics.getSnapshot().runtimeState === "demo"
window.__LiveStreamDiagnostics.getSnapshot().dataMode === "demo"
```

既存CSS互換が必要な場合、表示上の status badge は既存表現を維持してよい。
ただし diagnostics と data attribute では demo / synthetic であることが分かるようにする。

---

### 4. API失敗モードとは区別する

`demo=1` の状態は `error` / `degraded` ではない。

区別すること:

```text
demo mode:
  本番APIを使わない synthetic 表示
  runtimeState は demo など
  console error なしを目指す

API failure:
  本番API取得に失敗
  runtimeState は degraded / error
  ticker は取得確認中
  console resource error はテスト内容次第で許容される場合あり
```

---

## 対象範囲

Phase 5-C の対象は以下。

```text
1. demo mode 中の TypeError: Failed to fetch の発生元特定
2. demo mode 中の不要な live fetch / periodic refresh の停止または適正化
3. demo mode diagnostics の runtimeState / dataMode 整理
4. requestfailed / console error の扱い整理
5. E2E / probe 追加
6. Phase 5-A / 5-B / 3-D / 4-A の回帰防止
```

対象外:

```text
60分OBS実機soak
UI大幅改修
Phase 4-B のフォーカス演出改善
潮位/water alert focus の追加
鉄道路線形状focusの追加
backend API の仕様変更
```

---

## 既存状態の確認

まず以下を確認する。

```text
frontend/js/live-stream/live-stream-runtime.js
frontend/js/live-stream/live-stream-main.js
frontend/js/live-stream/live-stream-event-store.js
frontend/js/live-stream/live-stream-focus-controller.js
frontend/js/live-stream/live-stream-map-view.js
frontend/js/live-stream/live-stream-map-events.js
frontend/js/live-stream/live-stream-rain-layer.js
frontend/js/live-stream/live-stream-railway-layer.js
frontend/js/live-stream/live-stream-earthquake-detail.js
frontend/js/live-stream/live-stream-railway-adapter.js
frontend/live/stream.html
frontend/css/live/live-stream.css
e2e/live-stream-stability.spec.js
```

あわせて Phase 5-B レポートを確認する。

```text
tasks/live/live_stream_phase5b_obs_soak_codex_verification.md
```

確認観点:

```text
?demo=1 判定がどこで行われているか
live API fetch interval が demo mode で起動していないか
runtimeState が loading のままになる原因
TypeError: Failed to fetch を出している fetch の呼び出し元
fetch failure が catch されず console error になっていないか
```

---

## 実装要件

## 1. demo mode の fetch 発生源を特定する

まず、`demo=1` で `TypeError: Failed to fetch` を出している処理を特定する。

必要に応じて一時的に以下のような diagnostics を追加してもよいが、最終実装では過剰ログを残さない。

```js
{
  category: "earthquake" | "rain" | "railway" | "tide" | "tile" | "unknown",
  url,
  mode: "real" | "demo" | "calm",
  phase: "initial" | "interval" | "manualRefresh" | "layerLoad",
  errorName,
  errorMessage,
  timestamp
}
```

最終的には `window.__LiveStreamDiagnostics.getSnapshot()` から、直近の fetch failure 概要を確認できるようにする。

推奨 diagnostics 項目:

```js
recentFetchFailures: [
  {
    category: "railwayLayer",
    url: "...",             // 必要なら path のみ。API key 等は出さない
    mode: "demo",
    errorName: "TypeError",
    errorMessage: "Failed to fetch",
    timestamp: "..."
  }
]
```

注意:

```text
API key / token / 個人情報 / 長いURL全文は diagnostics に出さない
最大件数を制限する
```

---

## 2. demo mode では不要な live fetch を起動しない

`demo=1` では demo event / synthetic event を表示する前提なので、通常の `/api/live/*` polling は原則不要。

期待挙動:

```text
/live/stream?demo=1
  live API periodic fetch を起動しない
  EventStore には demo event を投入
  FocusController は demo event を使って動く
  ticker / panels / map は demo event pipeline で同期
  runtimeState は loading のままにしない
```

ただし、地図タイル、PMTiles、静的GeoJSONなど、表示に必要な map/layer asset fetch は対象外でもよい。
その場合は、失敗時に pageerror や app-level console error へしない。

---

## 3. runtime diagnostics の状態を整理する

`window.__LiveStreamDiagnostics.getSnapshot()` に、demo mode が明確に分かる情報を追加/整理する。

推奨 snapshot:

```js
{
  runtimeState: "demo",       // loading / healthy / degraded / error / demo / calm など
  dataMode: "demo",           // real | demo | calm
  isDemo: true,
  isCalm: false,
  refreshInFlight: false,
  refreshCount: 0,
  successCount: 0,
  failureCount: 0,
  consecutiveFailures: 0,
  eventCount: 10,
  lastRefreshAt: null,
  lastDemoUpdateAt: "2026-07-04T...",
  recentFetchFailures: []
}
```

calm mode も整理できる場合は以下のようにする。

```js
{
  runtimeState: "calm" または "healthy",
  dataMode: "calm",
  eventCount: 0
}
```

互換性維持のため、既存E2EやCSSが `healthy` を期待している場合は無理に壊さない。
その場合でも `dataMode` は必ず追加する。

---

## 4. body data attribute を整理する

以下のような data attribute を body に付与する。

```html
<body
  data-stream-runtime-state="demo"
  data-stream-data-mode="demo"
>
```

real mode:

```html
<body
  data-stream-runtime-state="healthy"
  data-stream-data-mode="real"
>
```

calm mode:

```html
<body
  data-stream-runtime-state="calm"
  data-stream-data-mode="calm"
>
```

API failure:

```html
<body
  data-stream-runtime-state="error"
  data-stream-data-mode="real"
>
```

既存の `body[data-stream-status]` や `data-lv` がある場合は互換性を壊さない。
追加属性として扱う。

---

## 5. demo mode の console error を解消する

`demo=1` で発生している `TypeError: Failed to fetch` を解消する。

優先順位:

```text
1. 不要な fetch を起動しない
2. 必要な fetch なら Abort / timeout / network failure を catch して diagnostics に記録
3. 画面は demo event 表示を維持
4. app-level console error は出さない
```

ただし、ブラウザが出す tile / PMTiles の `requestfailed` や `net::ERR_ABORTED` は、画面破綻がなく app console error でなければ許容してよい。

---

## 6. LiveStreamRuntime の責務を整理する

`LiveStreamRuntime` は以下を担当する。

```text
current data mode の把握: real / demo / calm
overall runtime state の把握: loading / healthy / degraded / error / demo / calm
in-flight guard
refresh counts
failure counts
recent fetch failures
diagnostics snapshot
body data attributes 更新
```

やりすぎ禁止:

```text
LiveStreamRuntime に UI描画ロジックを持たせる
EventStore の正規化仕様を大きく変える
FocusController の巡回仕様を大きく変える
```

---

## 7. demo mode の表示は既存どおり維持する

Phase 5-C は状態整理が目的なので、demo表示そのものを壊さない。

維持すること:

```text
地震/豪雨/鉄道/潮位の demo event 表示
map marker / pulse
panel表示
ticker表示
FocusController の demo focus 巡回
地震詳細子画面
鉄道小画面
鉄道路線カラー表示
```

---

## 8. エラー時の文言を正しく保つ

real mode の API failure は、引き続き「取得確認中」系の文言を出す。

禁止:

```text
API失敗を calm / 平常 / なし と断定する
demo fallback する
console error を隠すために失敗状態を無かったことにする
```

---

## E2E追加/更新

以下の新規または既存拡張を推奨する。

```text
e2e/live-stream-demo-diagnostics.spec.js
```

最低限の検証観点:

```text
1. /live/stream?demo=1 で body[data-stream-data-mode="demo"] になる
2. demo mode で diagnostics.runtimeState が loading のままにならない
3. demo mode で diagnostics.dataMode === "demo" になる
4. demo mode で live API periodic fetch が起動しない、または不要fetchが無い
5. demo mode で TypeError: Failed to fetch console error が出ない
6. demo mode で map / panel / ticker / focus は従来どおり動く
7. demo mode で EventStore の demo event が維持される
8. real API 500 では runtimeState=error/degraded になり、demoとは区別される
9. API failure 時に demo fallback しない
10. calm mode は dataMode=calm になり、demoとは区別される
11. Phase 5-B scoped E2E が回帰しない
12. 通常 /live に副作用がない
```

console監視例:

```js
const consoleErrors = [];
page.on('console', (msg) => {
  if (msg.type() === 'error') {
    consoleErrors.push(msg.text());
  }
});

expect(consoleErrors.filter((text) => text.includes('TypeError: Failed to fetch'))).toHaveLength(0);
```

API fetch 起動確認例:

```js
const liveApiRequests = [];
page.on('request', (request) => {
  if (request.url().includes('/api/live/')) {
    liveApiRequests.push(request.url());
  }
});
```

注意:

```text
地図タイル / PMTiles / 静的asset の request は live API request と混同しない
```

---

## 手動確認

最低限、以下URLを確認する。

```text
http://127.0.0.1:8080/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
http://127.0.0.1:8080/live/stream?state=calm&chrome=off
http://127.0.0.1:8080/live/stream?chrome=off
```

確認観点:

```text
demo表示が維持される
console error が増えない
診断状態が demo / calm / real で区別できる
ticker / focus / map / panels が停止しない
```

---

## diagnostics 確認コマンド例

ブラウザ console または Playwright で以下を確認する。

```js
window.__LiveStreamDiagnostics.getSnapshot()
```

期待例 demo:

```json
{
  "runtimeState": "demo",
  "dataMode": "demo",
  "isDemo": true,
  "refreshInFlight": false,
  "eventCount": 10,
  "recentFetchFailures": []
}
```

期待例 real failure:

```json
{
  "runtimeState": "error",
  "dataMode": "real",
  "isDemo": false,
  "consecutiveFailures": 3,
  "recentFetchFailures": [ ... ]
}
```

---

## 完了条件

Phase 5-C の完了条件は以下。

```text
/demo=1 中の TypeError: Failed to fetch console error の発生元が特定され、解消または正規処理化されている
demo mode の runtimeState が loading のまま残らない
diagnostics で dataMode=demo / real / calm を区別できる
body data attributes で runtime state / data mode を確認できる
demo表示・focus・ticker・panel・map が維持される
real API failure は error/degraded として扱われ、demoとは区別される
API failure 時に demo fallback しない
Phase 5-B までの scoped E2E が回帰しない
通常 /live に明確な副作用がない
検証レポートを作成できる状態
```

---

## PASS with notes 許容

以下は PASS with notes 可。

```text
タイル/PMTiles由来の requestfailed が残るが、pageerror / app console error ではない
意図的な API 500 テストで browser console の Failed to load resource が出る
runtimeState の表現を demo ではなく synthetic としたが dataMode=demo は明示されている
calm の runtimeState は healthy のままだが dataMode=calm は明示されている
10分以上の demo soak は未実施だが、短時間E2Eとprobeで console error 解消を確認済み
```

---

## FAIL条件

以下は FAIL。

```text
demo=1 で TypeError: Failed to fetch が再現する
demo=1 で runtimeState が loading のままになる
demo=1 で map / panel / ticker / focus が壊れる
real API failure が calm / 平常扱いになる
real API failure で demo fallback する
pageerror / unhandledrejection が出る
/live が壊れる
```

---

## レポート作成

検証後、以下にレポートを作成できるようにする。

```text
tasks/live/live_stream_phase5c_demo_diagnostics_codex_verification.md
```

レポートで特に明記してほしいこと:

```text
TypeError: Failed to fetch の原因
どう解消したか
demo mode の runtimeState / dataMode
real failure との区別
console error / pageerror の有無
E2E結果
残 notes
```

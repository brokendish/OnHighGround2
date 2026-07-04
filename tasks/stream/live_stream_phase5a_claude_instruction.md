# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 5-A：配信用安定運用・長時間稼働対策 MVP

## 目的

OnHighGround2 内の `/live/stream` を、OBS / YouTube 配信用に長時間表示しても破綻しにくい監視卓ビューへ強化する。

Phase 3-B〜4-A で以下は成立している。

```text
Phase 3-B: 中央メイン地図の本番データ連動
Phase 3-C: 地図 event / 左右パネル / テロップ同期
Phase 3-D: 全体ステータス / カテゴリバッジ / 件数表示同期
Phase 4-A: 自動巡回・注目地域フォーカス MVP
```

Phase 4-B は CODEX 制限により一旦スキップ / 保留扱い。

Phase 5-A では、見た目の演出追加ではなく、配信運用で重要な以下を優先する。

```text
長時間表示で marker / DOM / timer / listener が増殖しない
fetch が重複・暴走しない
API失敗やtimeoutが続いても画面が落ちない
復旧時に通常表示へ戻る
OBSブラウザソースで数時間表示しても安定する
通常 /live へ副作用を出さない
```

---

## 重要方針

### 1. `/live/stream` 専用に閉じる

通常 `/live` を壊さないこと。

禁止事項:

```text
通常 /live の地図・パネル・レイヤー挙動を変える
既存 /live API レスポンス形式を stream 都合で変更する
stream 用の安定化処理を /live 本体JSへ大量混入する
```

必要な処理は `frontend/js/live-stream/` と `frontend/css/live/live-stream.css` など、既存の stream 専用領域に閉じる。

---

### 2. 見た目改善ではなく安定運用を優先

Phase 5-A は UI演出フェーズではない。

今回の主目的は以下。

```text
timer / interval 管理
fetch 多重起動防止
AbortController timeout
marker / layer / DOM cleanup
EventStore subscriber cleanup
focus controller の暴走防止
ticker DOM の増殖防止
長時間監視用 diagnostics
```

フォーカス演出やHUDの派手な見た目改善は Phase 4-B または後続へ回す。

---

### 3. 自動リロードを標準動作にしない

配信中の突然の reload は OBS 画面で一瞬ブラックアウトや再読み込み表示を起こす可能性がある。

そのため Phase 5-A では、標準動作として `location.reload()` に頼らない。

許容:

```text
明示 query param 付きの検証用 auto reload
例: /live/stream?autoReload=1
```

禁止:

```text
通常 /live/stream で一定時間ごとに自動 reload する
エラー時に即 reload で逃げる
```

---

## 実装対象

### MVP対象

以下を実装・整理する。

```text
1. Stream Runtime Scheduler の整理
2. fetch の多重起動防止と timeout
3. marker / layer / DOM の増殖防止
4. EventStore / FocusController / Ticker の subscriber / timer 管理
5. 失敗継続時の degraded 状態管理
6. 復旧時の healthy 復帰
7. E2E/手動検証用 diagnostics API
```

---

## 推奨ファイル構成

既存構成を優先する。

新規作成する場合の推奨例:

```text
frontend/js/live-stream/live-stream-runtime.js
frontend/js/live-stream/live-stream-diagnostics.js
frontend/js/live-stream/live-stream-scheduler.js
```

既存ファイルへ統合する場合は、以下のような責務分離を意識する。

```text
live-stream-main.js
  初期化と全体接続のみ

live-stream-event-store.js
  normalized event の保持・summary・subscribe

live-stream-focus-controller.js
  focus cycle 管理

live-stream-map-events.js
  marker layer の描画・cleanup

live-stream-panels.js
  panel DOM render

live-stream-scene.js
  scene / ticker model 組み立て

live-stream-runtime.js
  timer / fetch cadence / health / diagnostics
```

---

## Step 1. 現状の timer / interval / listener を棚卸しする

まず、`/live/stream` で使っている以下を確認する。

```text
setInterval
setTimeout
requestAnimationFrame
EventStore.subscribe
FocusController.subscribe 相当
window.addEventListener
document.addEventListener
Leaflet event listener
fetch loop
clock update
ticker update
focus cycle
map refresh
```

確認後、以下を満たすように整理する。

```text
同じ interval が多重起動しない
初期化関数を2回呼んでも timer が増えない
subscribe したら unsubscribe できる
画面更新ごとに listener が増えない
```

既存仕様上 unsubscribe が不要な単発初期化であっても、diagnostics で増殖していないことを確認できるとよい。

---

## Step 2. Stream Runtime Scheduler を導入または整理する

fetch / refresh / focus / ticker / clock の周期処理を、可能な限り明示的に管理する。

推奨する runtime 状態:

```js
{
  started: true,
  refreshTimerId: 123,
  clockTimerId: 456,
  focusTimerId: 789,
  refreshInFlight: false,
  refreshCount: 0,
  lastRefreshStartedAt: "2026-07-04T00:00:00+09:00",
  lastRefreshFinishedAt: "2026-07-04T00:00:03+09:00",
  lastSuccessAt: "2026-07-04T00:00:03+09:00",
  lastErrorAt: null,
  consecutiveFailures: 0,
  dataState: "healthy" // healthy | degraded | error | loading
}
```

外部公開する必要はないが、E2E確認用に snapshot を取れるようにする。

---

## Step 3. fetch の多重起動防止

API refresh が重複しないようにする。

必須仕様:

```text
refreshInFlight=true の間は次の refresh を開始しない
前回 refresh が timeout した場合は AbortController で中断する
一部API失敗でも Promise.allSettled() で全体処理を継続する
失敗時に demo fallback しない
復旧時には consecutiveFailures を 0 に戻す
```

推奨値:

```js
const STREAM_REFRESH_INTERVAL_MS = 60 * 1000;
const STREAM_FETCH_TIMEOUT_MS = 5 * 1000;
```

E2E用には query param で短縮できるとよい。

例:

```text
/live/stream?runtimeSpeed=test
/live/stream?refreshSpeed=test
```

既存の `focusSpeed=test` がある場合は、それと衝突しない命名にする。

通常運用では 60秒前後のままにする。

---

## Step 4. marker / Leaflet layer の増殖防止

地図 marker 更新で DOM / Leaflet layer が増殖しないようにする。

必須仕様:

```text
event 更新時に古い marker を確実に削除する
同一 event id の marker が重複しない
focus 更新だけで marker が増殖しない
calm / empty / failure で marker が残留しない
地図 tile layer を再追加しない
Leaflet map instance を再生成しない
```

推奨:

```js
const eventLayer = L.layerGroup().addTo(map);

function renderEvents(events) {
  eventLayer.clearLayers();
  // normalized events から必要数だけ marker を再描画
}
```

または event id -> marker の Map で差分更新してもよい。

ただし MVP では `clearLayers()` 方式で十分。

---

## Step 5. DOM の増殖防止

以下のDOMが更新ごとに増殖しないこと。

```text
ticker item
panel item
focus label / HUD
map event marker DOM
status badge
error / loading message
```

方針:

```text
render 時は既存コンテナの innerHTML を置換する
または keyed update で不要ノードを削除する
append-only にしない
```

特に ticker は長時間配信で増殖しやすいので注意する。

---

## Step 6. EventStore subscriber 管理

`LiveStreamEventStore.subscribe()` が存在する場合、以下を満たす。

```text
subscribe は unsubscribe 関数を返す
同じ初期化で duplicate subscribe しない
subscriber 数を diagnostics で確認できる
setEvents() のたびに subscriber が増えない
```

推奨 diagnostics:

```js
LiveStreamEventStore.getDiagnostics?.()
// { eventCount, subscriberCount, updateCount, lastUpdatedAt }
```

既存APIを壊さず、追加のみで対応する。

---

## Step 7. FocusController の安定化

Phase 4-A の自動巡回を長時間運用向けに整理する。

必須仕様:

```text
focus timer が多重起動しない
focus対象 event が消えたら active class を消す
focus対象がない場合は overview のまま
API失敗時に古い focus id を不自然に固定し続けない
focus中にEventStore更新が来てもJS errorを出さない
map pan / setView / flyTo が過剰に連続発火しない
```

推奨:

```text
同じ focus event id へ連続で pan しない
短時間に連続 refresh が来ても focus transition をdebounceする
focus state を body[data-stream-focus-mode] / body[data-stream-focus-event-id] へ維持
```

---

## Step 8. Runtime health / degraded 状態

長時間配信では、一時的なAPI失敗を画面破綻にしないことが重要。

以下の状態を管理する。

```text
loading
healthy
degraded
error
```

推奨定義:

```text
loading:
  初回取得中

healthy:
  直近refreshで少なくとも主要データの一部取得成功

degraded:
  連続失敗が一定回数未満、または一部API失敗

error:
  主要APIが連続3回以上失敗
```

表示は既存UIに合わせて控えめでよい。

重要:

```text
error でも画面を落とさない
error でも demo fallback しない
error から復旧したら healthy / degraded へ戻る
```

DOM属性として以下を付与すると検証しやすい。

```text
body[data-stream-runtime-state="healthy"]
body[data-stream-runtime-state="degraded"]
body[data-stream-runtime-state="error"]
```

既存の `body[data-stream-status]` と競合しないようにする。

---

## Step 9. diagnostics API を追加する

E2Eと手動検証用に、window 配下へ diagnostics を公開する。

通常UIには表示しない。

推奨:

```js
window.__LiveStreamDiagnostics = {
  getSnapshot() {
    return {
      runtimeState,
      refreshInFlight,
      refreshCount,
      successCount,
      failureCount,
      consecutiveFailures,
      eventCount,
      markerCount,
      tickerItemCount,
      panelItemCount,
      subscriberCount,
      focusMode,
      focusEventId,
      mapInitialized,
      tileLayerCount,
      lastSuccessAt,
      lastErrorAt
    };
  },
  forceRefresh() {},
  stop() {},
  start() {}
};
```

注意:

```text
本番UIに目立つ表示を出さない
diagnostics は読み取り中心
forceRefresh はテスト用途で、通常操作UIからは使わない
```

`?debug=1` または `?health=1` の時だけ小さな debug overlay を出してもよいが、MVPでは必須ではない。

---

## Step 10. メモリ計測は参考扱い

ブラウザのJS heapは環境差が大きく、E2Eで厳密判定しづらい。

Phase 5-A では、メモリ使用量そのものより以下を重視する。

```text
DOM件数が増え続けない
marker数が増え続けない
timer数相当が増え続けない
subscriber数が増え続けない
fetchが重複しない
```

`performance.memory` が使える場合のみ diagnostics に参考値を出してよい。

```js
performance.memory?.usedJSHeapSize
```

ただし PASS/FAIL の主判定にはしない。

---

## Step 11. テスト追加

最低限、以下のE2Eを追加する。

```text
e2e/live-stream-stability.spec.js
```

テスト観点:

```text
1. runtime diagnostics が取得できる
2. 連続 refresh しても marker 数が増殖しない
3. 連続 refresh しても ticker DOM が増殖しない
4. 連続 refresh しても panel DOM が増殖しない
5. refreshInFlight 中に追加 refresh が走らない
6. API 500 / 404 / timeout が続いても pageerror なし
7. 失敗継続時に runtimeState が degraded/error になる
8. 復旧時に runtimeState が healthy に戻る
9. focus cycle 中に event が消えても active class が残らない
10. calm / demo / real mode の既存挙動を壊さない
11. Phase 3-D badge/count/status 同期を壊さない
12. 通常 /live に副作用がない
```

E2Eでは query param で短周期化してよい。

例:

```text
/live/stream?runtimeSpeed=test
/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test
```

ただし本番URLでは短周期化しないこと。

---

## 手動確認ポイント

1920x1080 で以下を確認する。

```text
/live/stream
/live/stream?state=calm
/live/stream?demo=1&focusSpeed=test
/live/stream?runtimeSpeed=test
```

確認内容:

```text
画面が崩れない
マーカーが増え続けない
フォーカス表示が暴走しない
テロップが二重化しない
パネル項目が二重化しない
上部バッジが不自然に増えない
API失敗時に demo 表示へ逃げない
```

---

## 完了条件

Phase 5-A の完了条件は以下。

```text
/live/stream が通常表示できる
長時間運用向け diagnostics が取得できる
refresh / focus / ticker / clock の timer が多重起動しない
fetch が多重実行されない
API timeout / 500 / 404 / 不正JSONで画面破綻しない
失敗継続時に degraded/error 状態を表現できる
復旧時に healthy へ戻る
marker / DOM / subscriber が更新ごとに増殖しない
Phase 3-D の badge/count/status 同期が維持される
Phase 4-A の自動フォーカスが維持される
通常 /live に副作用がない
E2E が追加/更新され PASS
検証レポート作成可能な状態
```

---

## 注意

Phase 5-A は地味だが重要。

配信画面では、派手な演出より以下が重要。

```text
落ちない
増えない
詰まらない
壊れたデータで巻き込まれない
復旧できる
```

OBS / YouTube 配信用の監視卓として、長時間放置しても耐えられる土台を作ること。

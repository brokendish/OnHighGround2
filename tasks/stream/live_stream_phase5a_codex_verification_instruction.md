# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 5-A：配信用安定運用・長時間稼働対策 MVP 検証

## 目的

Claude実装後、`/live/stream` が OBS / YouTube 配信用に長時間表示しても破綻しにくい状態になっていることを検証する。

Phase 5-A では見た目の演出ではなく、以下を重点確認する。

```text
timer / interval が多重起動しない
fetch が重複しない
marker / DOM / subscriber が更新ごとに増殖しない
API失敗やtimeoutで画面が落ちない
失敗継続時に degraded/error を表現できる
復旧時に healthy へ戻る
Phase 3-D / 4-A の既存同期を壊していない
通常 /live に副作用がない
```

---

## 前提

Phase 4-B は CODEX制限により一旦スキップ / 保留扱い。

今回の検証対象は Phase 5-A。

Phase 4-A までの確認済み前提:

```text
Phase 3-B: 本番データ event marker
Phase 3-C: map / panel / ticker event同期
Phase 3-D: status / badge / count同期
Phase 4-A: 自動巡回・注目地域フォーカス
```

---

## 事前確認

まずガードレールと差分を確認する。

```bash
git diff --stat
git diff
```

確認対象例:

```text
docs/live/DEVELOPMENT_GUARDRAILS.md
frontend/live/stream.html
frontend/js/live-stream/
frontend/css/live/live-stream.css
e2e/live-stream-stability.spec.js
e2e/live-stream-auto-focus.spec.js
e2e/live-stream-status-sync.spec.js
```

重点確認:

```text
通常 /live へ stream 専用処理を混ぜ込んでいないか
標準動作で location.reload() に頼っていないか
demo fallback で失敗を隠していないか
setInterval / setTimeout / subscribe が増殖しそうな実装になっていないか
```

---

## 静的確認

### JS構文確認

変更されたJSと関連E2Eに対して `node --check` を実行する。

例:

```bash
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-focus-policy.js
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-diagnostics.js
node --check e2e/live-stream-stability.spec.js
node --check e2e/live-stream-auto-focus.spec.js
node --check e2e/live-stream-status-sync.spec.js
node --check e2e/live-stream-event-sync.spec.js
```

実際に存在するファイル名に合わせて読み替えること。

### Python構文確認

backend変更がある場合のみ実行する。

```bash
python -m compileall backend
```

backend変更がない場合は「not run, no backend changes」と記録する。

---

## Docker / HTTP確認

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?runtimeSpeed=test"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

すべて `200 OK` を期待する。

`runtimeSpeed=test` が未実装の場合は、実装された検証用 query param に読み替える。

---

## E2E実行

推奨実行:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-stability.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

既存ファイル名に合わせて調整する。

---

## 必須検証観点

### 1. diagnostics が取得できる

`window.__LiveStreamDiagnostics.getSnapshot()` のような diagnostics を確認する。

期待する情報例:

```json
{
  "runtimeState": "healthy",
  "refreshInFlight": false,
  "refreshCount": 3,
  "successCount": 3,
  "failureCount": 0,
  "consecutiveFailures": 0,
  "eventCount": 5,
  "markerCount": 5,
  "tickerItemCount": 4,
  "panelItemCount": 10,
  "subscriberCount": 3,
  "focusMode": "overview",
  "focusEventId": "",
  "mapInitialized": true,
  "tileLayerCount": 1
}
```

実装された項目名に合わせてよい。

ただし、以下は何らかの形で確認できること。

```text
runtime state
refresh count
in-flight状態
event count
marker count
focus state
subscriber または listener 増殖確認に使える値
```

---

### 2. refresh 多重起動防止

検証方法例:

```text
runtimeSpeed=test で短周期化
API response を意図的に遅延させる
その間に refresh が重複しないことを diagnostics で確認
```

期待:

```text
refreshInFlight が true の間、次の refresh が開始されない
in-flight 数が 1 を超えない
pageerror / unhandledrejection が出ない
```

---

### 3. marker 増殖防止

同じデータ、または更新ごとに少し変わるデータを複数回返す。

期待:

```text
marker数が event 上限を超えて増え続けない
同一 event id の marker が重複しない
calm / empty / failure 後に古い marker が残留しない
focus cycling だけで marker が増えない
```

DOM例:

```text
.stream-map-event
.stream-map-event--active
```

実装classに合わせて読み替える。

---

### 4. ticker / panel DOM 増殖防止

複数 refresh 後に、以下が増殖していないことを確認する。

```text
ticker item
panel item
focus label
status badge
error/loading message
```

期待:

```text
ticker が二重に流れない
panel item が同じ内容で積み上がらない
status badge が増えない
```

---

### 5. subscriber / listener 増殖防止

diagnostics で subscriberCount 等を確認する。

期待:

```text
refresh のたびに subscriberCount が増えない
focus cycle のたびに subscriberCount が増えない
再初期化相当の処理をしても interval が二重化しない
```

直接確認が難しい場合は、以下を代替確認する。

```text
同じイベントに対して panel/ticker/map 更新が二重発火していない
同じログやDOM更新が重複していない
```

---

### 6. API失敗継続時の安全動作

以下を route mock で検証する。

```text
500
404
不正JSON
timeout相当
全API失敗
一部API失敗
```

期待:

```text
pageerror なし
unhandledrejection なし
地図表示維持
demo fallback なし
runtimeState が degraded または error へ変化
テロップは取得確認中 / 一部取得不可などの非断定表示
```

---

### 7. 復旧時の healthy 復帰

失敗を数回返した後、正常データを返す。

期待:

```text
runtimeState が degraded/error から healthy へ戻る
consecutiveFailures が 0 に戻る
event marker / badge / panel / ticker が正常データで更新される
古い error 表示が残留しない
```

---

### 8. Phase 3-D 回帰確認

既存の badge/count/status 同期が壊れていないこと。

確認:

```text
カテゴリバッジの件数が EventStore summary と一致
地震/豪雨/鉄道/潮位の件数が期待通り
calm では 0
failure では ordinary calm と誤表示しない
```

既存 `e2e/live-stream-status-sync.spec.js` を必ず含める。

---

### 9. Phase 4-A 回帰確認

自動フォーカスが壊れていないこと。

確認:

```text
focus id が map / panel / ticker で同期
focus対象消滅時に active class が残らない
state=calm では focus しない
API失敗時に focus しない
demo=1 でも同じ focus pipeline を使う
```

既存 `e2e/live-stream-auto-focus.spec.js` を必ず含める。

---

### 10. 通常 `/live` への副作用確認

```bash
curl -I http://127.0.0.1:8080/live
```

可能なら既存 `/live` 代表E2Eも実行する。

最低限:

```text
/live が 200 OK
pageerror なし
通常地図が表示される
stream 用 diagnostics / body属性 / CSS が通常 /live に漏れていない
```

---

## 手動スクリーンショット確認

以下を保存する。

```bash
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 \
  http://127.0.0.1:8080/live/stream \
  test-results/live-stream-phase5a-stability-normal-1920.png

npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 \
  "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" \
  test-results/live-stream-phase5a-stability-calm-1920.png

npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 \
  "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test&chrome=off" \
  test-results/live-stream-phase5a-stability-demo-1920.png
```

検証用パラメータ名は実装に合わせて調整する。

確認:

```text
見た目が大きく崩れていない
テロップが二重化していない
パネル項目が二重化していない
marker が異常に増えていない
focus 表示が暴走していない
通常 /live/stream で demo fallback していない
```

---

## 任意: 短時間 soak test

時間が許せば、Playwright またはブラウザで 5〜15分程度の短時間 soak を行う。

確認:

```text
pageerror なし
console error なし、または既知の外部リソース失敗のみ
markerCount が増え続けない
tickerItemCount が増え続けない
subscriberCount が増え続けない
refreshCount が増える一方で inFlight が詰まらない
```

メモリ使用量は参考値として記録してよいが、環境差が大きいため主判定にしない。

---

## 検証レポート作成

以下に作成する。

```text
tasks/live/live_stream_phase5a_stream_stability_codex_verification.md
```

構成:

```md
# live stream Phase 5-A stream stability verification

## Result

PASS / FAIL / PASS with notes

## Summary

## Checked files

## Environment

## Commands

## Test results

## Diagnostics snapshot

## Failure / recovery checks

## Manual browser check

## Screenshots

## Findings

## Notes

## Final judgement
```

---

## PASS条件

以下を満たす場合 PASS。

```text
/live/stream が HTTP 200
通常 / calm / demo が表示できる
diagnostics が取得できる
fetch が重複しない
API timeout / 500 / 404 / 不正JSONで pageerror なし
失敗時に demo fallback しない
失敗継続時に degraded/error を表現できる
復旧時に healthy に戻る
marker / ticker / panel / subscriber が更新ごとに増殖しない
Phase 3-D badge/count/status 同期が維持される
Phase 4-A auto focus 同期が維持される
通常 /live に明確な副作用がない
関連E2Eが PASS
検証レポートが作成されている
```

---

## FAIL条件

以下のいずれかがあれば FAIL。

```text
/live/stream が表示できない
Leaflet map が初期化されない
refresh ごとに marker が増殖する
refresh ごとに ticker/panel DOM が増殖する
fetch が重複し続ける
timeout 後に inFlight が解除されない
API失敗時に pageerror / unhandledrejection が出る
API失敗時に demo fallback する
失敗後に復旧できない
focus timer が暴走する
通常 /live が壊れる
```

---

## PASS with notes 条件

以下は PASS with notes 可。

```text
performance.memory は環境依存のため参考記録のみ
runtime diagnostics の項目名が指示書例と異なるが同等情報を確認できる
一部外部タイル/リソースのconsole warningがあるがページ動作に影響しない
短時間soakは実施したが長時間実配信テストは未実施
潮位/water alert event が未接続で focus 対象外
鉄道 focus が代表点ベース
```

---

## 最終判断

最終的に以下を明記する。

```text
PASS
FAIL
PASS with notes
```

Phase 5-A で最も重要なのは、見た目ではなく以下。

```text
長時間表示で増殖しない
API失敗で落ちない
復旧できる
通常 /live を壊さない
```

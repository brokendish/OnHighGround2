# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 4-A：自動巡回・注目地域フォーカス MVP 検証

## 目的

Claude実装後、`/live/stream` に追加された **自動巡回・注目地域フォーカス MVP** を検証する。

Phase 4-A で確認すべきことは、単に地図が動くことではない。

以下を重点確認する。

```text
LiveStreamEventStore を判断元にしている
重要 event が自動で focus 対象になる
focus event id が地図 marker / パネル / テロップで同期する
calm / demo / failure / empty で破綻しない
Phase 3-D のステータス・バッジ・件数同期を壊していない
通常 /live に副作用がない
```

## 前提

Phase 3-D までで以下が完了している前提。

- 本番データ由来 event marker 表示
- map / panel / ticker の event 同期
- `LiveStreamEventStore.getSummary()` による全体ステータス・カテゴリバッジ・件数同期
- `state=calm` は既存 calm URL
- `demo=1` は demo event pipeline

Phase 4-A では、この EventStore / summary を利用して自動巡回・注目地域フォーカスを実装しているはずである。

## 事前確認

まず `/live` ガードレール、今回の実装差分、関連ファイルを確認する。

```bash
git diff --stat
git diff
```

確認対象例:

```text
docs/live/DEVELOPMENT_GUARDRAILS.md
frontend/live/stream.html
frontend/js/live-stream/live-stream-event-store.js
frontend/js/live-stream/live-stream-main.js
frontend/js/live-stream/live-stream-map-view.js
frontend/js/live-stream/live-stream-map-events.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-scene.js
frontend/js/live-stream/live-stream-focus-controller.js
frontend/js/live-stream/live-stream-focus-policy.js
frontend/css/live/live-stream.css
e2e/live-stream-auto-focus.spec.js
e2e/live-stream-status-sync.spec.js
e2e/live-stream-event-sync.spec.js
```

実際のファイル名に合わせて読み替えること。

## 静的確認

### JS構文確認

変更された JS / E2E に対して `node --check` を実行する。

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
node --check e2e/live-stream-auto-focus.spec.js
node --check e2e/live-stream-status-sync.spec.js
node --check e2e/live-stream-event-sync.spec.js
```

存在しないファイルはスキップし、実装された実ファイルに合わせること。

### Python構文確認

backend に変更がある場合のみ実施。

```bash
python -m compileall backend
```

backend 変更がない場合は、レポートに「backend changesなしのため未実施」と記録してよい。

## 差分確認ポイント

以下を重点確認する。

```text
/live 本体に stream 専用分岐を大量追加していないか
既存APIレスポンス形式を変更していないか
EventStore ではなく DOM スクレイピングで focus 対象を作っていないか
setInterval / setTimeout が多重起動しないか
subscribe の解除漏れがないか
focus event が消えた後も active class が残らないか
API失敗時に demo fallback していないか
Phase 3-D の badge/count/status 同期を壊していないか
```

## Docker / HTTP確認

```bash
docker compose ps
```

必要に応じて:

```bash
docker compose up -d
```

以下が HTTP 200 で返ること。

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

`focusSpeed=test` 等の query param が実装されていない場合は、その確認はスキップしてよい。

## E2E実行

推奨:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

既存テスト名に合わせて調整すること。

## 必須検証観点

### 1. 自動巡回 controller の存在

以下のいずれかの形で focus state が確認できること。

```text
body[data-stream-focus-mode]
body[data-stream-focus-event-id]
#live-stream-root[data-focus-mode]
#live-stream-root[data-focus-event-id]
window.LiveStreamFocusController.getState()
```

実装に合わせて確認する。

期待:

- 通常データあり: `focus` または巡回中状態になる
- calm: `overview` または focus なし
- empty: `overview` または focus なし
- API failure: 画面破綻なし、focus なしまたは安全状態

### 2. 注目 event の選定

本番相当 mock response で、複数カテゴリ・複数 severity の event を返す。

確認:

```text
critical/high event が優先される
low/info だけの event は基本 focus 対象にならない
座標なし event は focus 対象にならない
stale event は focus 対象にならない
```

可能なら以下を混ぜる。

```text
地震 high
キキクル critical/high
鉄道 suspended/high
雨 medium
潮位通常値のみ
座標なし event
stale event
```

### 3. focus event id の同期

focus 中の event id が、以下で一致すること。

```text
focus state の event id
地図 marker の data-event-id
地図 marker の active class / data-active
対応パネル item/card の data-event-id
対応パネル item/card の active class / data-active
ticker の内容
```

DOM class は実装に合わせて確認する。

例:

```text
.stream-map-event--active
.stream-panel-item--active
[data-active="true"]
```

### 4. 地図自動フォーカス

中央メイン地図が、注目 event の周辺へ自動移動すること。

確認:

```text
focus 前後で map center / zoom が変わる
focus event の lat/lng が map bounds 内に入る
過度にズームしすぎない
日本国外や異常座標に飛ばない
```

Leaflet map instance を E2E から参照できる場合は center/zoom を確認する。
参照できない場合は marker の表示位置や data attribute で確認する。

### 5. 複数 event の巡回

複数 event を mock し、一定時間後に次の event へ focus が移ることを確認する。

期待:

```text
focus event id が event A から event B へ変わる
active marker が A から B へ移る
active panel item が A から B へ移る
ticker が B を反映する、または B を含む
古い active class が残らない
```

E2E用に `focusSpeed=test` がある場合は利用する。
ない場合は実装の通常タイミングに合わせて待つ。ただしテストが過度に長くなる場合は PASS with notes で補足してよい。

### 6. overview へ戻る

巡回サイクルの途中または対象消滅時に、overview へ戻ることを確認する。

期待:

```text
focus 対象なしになったら overview
active event id が空になる
map が日本全体表示へ戻る、または戻る予定状態になる
```

MVPで「常に次の focus へ巡回し続け、明示的 overview 戻りが短い」実装の場合は、その仕様をレポートに記録する。

### 7. calm

URL:

```text
/live/stream?state=calm
```

期待:

```text
focus しない
marker / pulse なし
badge count 0
panel calm
ticker monitoring
map overview
JS error なし
```

mock data が存在しても calm が優先されること。

### 8. demo

URL:

```text
/live/stream?demo=1
```

期待:

```text
demo event も EventStore 経由で focus 対象になる
map / panel / ticker / badge / focus が同期する
本番 fetch と混ざらない
```

### 9. 空データ

API が空データを返すケース。

期待:

```text
focus なし
map overview
marker 0
badge 0
panel calm
ticker monitoring
JS error なし
demo fallback なし
```

### 10. API失敗 / 不正JSON / timeout相当

以下を検証する。

```text
500
404
不正JSON
timeout相当の遅延
```

期待:

```text
画面破綻なし
JS pageerror なし
unhandledrejection なし
demo fallback なし
map は表示維持
ticker は取得確認中などの failure-aware 表示
focus なし、または安全に overview
```

### 11. Phase 3-D 回帰

以下が維持されていること。

```text
LiveStreamEventStore.getSummary() が集計元
top category badge count が正しい
category status が正しい
overall status が正しい
data-stream-overall-status / body[data-stream-status] が維持される
panel data-count / data-status が維持される
```

特に focus 実装によって badge count が active event だけの件数に変わっていないこと。

badge は active event count ではなく category total count を表示する。

### 12. 地図操作不可の維持

Phase 3-A 以降の仕様を確認する。

```text
ズームUIがない
ドラッグで地図が動かない
ホイールでズームしない
ダブルクリックでズームしない
キーボード操作で動かない
```

プログラムによる自動移動は許容。

### 13. `/live` 通常画面への副作用

通常 `/live` を開いて確認する。

```text
ページエラーなし
地図表示あり
既存パネル表示あり
既存レイヤー操作が大きく壊れていない
```

可能なら既存代表E2Eも通す。

## 手動ブラウザ確認

以下URLでスクリーンショットを取得する。

```text
http://127.0.0.1:8080/live/stream
http://127.0.0.1:8080/live/stream?state=calm&chrome=off
http://127.0.0.1:8080/live/stream?state=alert&demo=1&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00
```

E2E用 query param がある場合:

```text
http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00
```

推奨 viewport:

```text
1920x1080
```

保存例:

```text
test-results/live-stream-phase4a-auto-focus-1920.png
test-results/live-stream-phase4a-calm-1920.png
test-results/live-stream-phase4a-demo-focus-1920.png
```

手動確認ポイント:

```text
地図が注目 event に自動フォーカスしている
active marker が分かる
対応パネル item が active になっている
テロップに同じ event が出る、または含まれる
切り替えが速すぎない
画面がチカチカしすぎない
左右パネル・テロップを邪魔していない
calm では落ち着いた全国監視表示になる
```

## 検証レポート作成

以下にレポートを作成する。

```text
tasks/live/live_stream_phase4a_auto_focus_codex_verification.md
```

レポート構成:

```md
# live stream Phase 4-A auto focus verification

## Result

PASS / FAIL / PASS with notes

## Summary

## Checked files

## Environment

## Commands

## Test results

## Manual browser check

## Screenshots

## Findings

## Notes

## Final judgement
```

## PASS条件

以下を満たす場合 PASS。

```text
/live/stream が HTTP 200
自動巡回 controller が動作する
重要 event が focus 対象になる
中央メイン地図が focus event へ自動移動する
focus event id が map marker / panel / ticker で同期する
複数 event の巡回が確認できる
calm では focus しない
empty/failure/invalid/timeout で破綻しない
demo fallback しない
Phase 3-D の badge/count/status 同期を壊していない
地図操作不可が維持される
通常 /live に明確な副作用がない
関連 E2E が PASS
検証レポートが作成されている
```

## FAIL条件

以下のいずれかがあれば FAIL。

```text
/live/stream が表示できない
Leaflet 地図が初期化されない
自動巡回で JS error / unhandledrejection が出る
focus event id が map / panel / ticker で不一致
API失敗時に demo marker / demo focus へ fallback する
calm なのに focus する
地図操作不可が解除されている
Phase 3-D の badge/count/status が壊れている
通常 /live が壊れている
setInterval 多重起動で巡回が加速する
active class が消えず古い event が残り続ける
```

## PASS with notes 条件

以下は PASS with notes 可。

```text
overview 戻りが短く、巡回中心の実装になっている
focusSpeed=test などのE2E補助 query param がないため巡回テストがやや長い
潮位/water は alert event 未接続のため focus 対象外
鉄道は代表点のみ focus で路線形状追跡なし
ticker は focus event を先頭固定ではなく headline priority に含める方式
map center/zoom の厳密値は未検証だが bounds 内表示は確認済み
```

## 最終判断

最後に以下を明記する。

```text
PASS
FAIL
PASS with notes
```

今回の検証で特に重視するのは以下。

```text
EventStore 起点の自動巡回であること
active focus event が map / panel / ticker で一致すること
calm / error で破綻しないこと
Phase 3-D の状態・件数同期を壊していないこと
/live 本体を壊していないこと
```

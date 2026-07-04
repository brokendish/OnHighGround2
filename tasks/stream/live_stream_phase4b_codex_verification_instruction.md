# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 4-B：自動巡回ビュー演出・フォーカス表示改善 MVP 検証

## 目的

Claude 実装後、`/live/stream` の Phase 4-B「自動巡回ビュー演出・フォーカス表示改善 MVP」を検証する。

Phase 4-A では自動巡回・focus id 同期が実装済みである。
Phase 4-B では、focus 中に視聴者が「今どこを見ているのか」を分かりやすく認識できるように、HUD / marker / panel / ticker / map transition の表示改善が行われていることを確認する。

重要なのは、見た目だけではない。

以下を確認する。

```text
focus 表示が EventStore / FocusController の状態と同期している
HUD / map / panel / ticker が同じ focus event id を示す
calm / empty / failure で古い focus 表示が残らない
Phase 3-D の badge/count/status 同期が壊れていない
地図操作不可が維持されている
通常 /live に副作用がない
```

---

## 事前確認

まず開発ガードレール、実装差分、関連ファイルを確認する。

確認例:

```bash
git diff --stat
git diff
```

確認対象例:

```text
docs/live/DEVELOPMENT_GUARDRAILS.md
tasks/stream/live_stream_phase4b_codex_verification_instruction.md
frontend/live/stream.html
frontend/css/live/live-stream.css
frontend/js/live-stream/live-stream-event-store.js
frontend/js/live-stream/live-stream-focus-policy.js
frontend/js/live-stream/live-stream-focus-controller.js
frontend/js/live-stream/live-stream-map-view.js
frontend/js/live-stream/live-stream-map-events.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-main.js
e2e/live-stream-focus-view.spec.js
e2e/live-stream-auto-focus.spec.js
e2e/live-stream-status-sync.spec.js
e2e/live-stream-event-sync.spec.js
```

重点確認:

```text
DOM スクレイピングで focus 対象を決めていないか
EventStore とは別の独自イベント配列を作っていないか
FocusController の状態と HUD / marker / panel / ticker が矛盾しないか
通常 /live 側へ stream 専用分岐を混ぜていないか
demo fallback が通常表示や failure 時に発生しないか
```

---

## 静的確認

### JS 構文確認

変更された JS / E2E ファイルに対して `node --check` を実行する。

例:

```bash
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-focus-policy.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-main.js
node --check e2e/live-stream-focus-view.spec.js
node --check e2e/live-stream-auto-focus.spec.js
node --check e2e/live-stream-status-sync.spec.js
```

実際の変更ファイルに合わせて実行すること。

### Python 構文確認

backend に変更がある場合のみ実行する。

```bash
python -m compileall backend
```

backend 変更がない場合は、未実施でよいがレポートに明記する。

---

## Docker / HTTP 確認

Docker 状態確認:

```bash
docker compose ps
```

必要なら起動:

```bash
docker compose up -d
```

HTTP 確認:

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

期待:

```text
すべて 200 OK
```

実際に存在しない URL がある場合は、既存仕様に合わせて判断し、レポートに記録する。

---

## E2E 検証

推奨実行:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-focus-view.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

`live-stream-focus-view.spec.js` が存在しない場合は、Phase 4-B の表示検証が `live-stream-auto-focus.spec.js` に含まれているか確認する。
不足している場合は FAIL または notes ではなく、追加検証を行う。

---

## 必須検証観点

### 1. Focus HUD 表示

focus 中に HUD / 注目ラベルが表示されること。

確認項目:

```text
HUD が存在する
HUD が focus mode を示す
HUD に focus event の title または要約が出る
HUD が地図・左右パネル・下部テロップを邪魔しない
```

推奨 selector:

```text
[data-testid="stream-focus-hud"]
.stream-focus-hud
```

期待 data 属性:

```text
data-focus-mode
data-focus-event-id
```

既存実装に合わせて読み替えること。

---

### 2. focus id 同期

focus 中の id が以下で一致すること。

```text
body[data-stream-focus-event-id]
HUD data-focus-event-id
active map marker data-event-id
active panel item data-event-id
ticker 注目 data-event-id
```

body 状態:

```text
body[data-stream-focus-mode="focus"]
body[data-stream-focus-event-id="..."]
```

不一致があれば FAIL。

---

### 3. marker 強調表示

focus 対象 marker が視覚的に分かること。

確認:

```text
active / focused class が付く
focus ring / glow / label のいずれかが出る
他の marker と区別できる
marker が増殖しない
```

想定 class 例:

```text
.stream-map-event--active
.stream-map-event--focused
.stream-focus-ring
```

実装 class 名に合わせる。

---

### 4. panel active 表示

focus 対象に対応する panel item が強調されること。

確認:

```text
active / focused class が付く
または data-focused="true" が付く
対応 data-event-id が focus id と一致する
active 残存がない
```

focus 対象が消滅した後、古い panel item が active のまま残る場合は FAIL。

---

### 5. ticker 注目表示

focus 中、ticker に focus event が「注目」として表示されること。

確認:

```text
ticker に 注目 表示がある
注目 event id が focus id と一致する
focus がない場合は古い 注目 が残らない
failure 時に古い 注目 が残らない
```

推奨 selector:

```text
[data-testid="stream-ticker-focus"]
[data-focus-event-id]
```

実装 DOM に合わせる。

---

### 6. overview / focus / returning の状態

`body[data-stream-focus-mode]` が以下の状態を持ち、表示が破綻しないこと。

```text
overview
focus
returning
```

確認:

```text
overview: 日本全体表示、古い active なし
focus: 対象周辺表示、HUD/marker/panel/ticker が同じ対象
returning: 全国表示へ戻る途中、古い active が残り続けない
```

returning が短く捕捉しづらい場合は notes 可。
ただし overview / focus の整合性は必須。

---

### 7. focusSpeed=test による巡回

`focusSpeed=test` を使って、複数 event が巡回することを確認する。

URL 例:

```text
http://127.0.0.1:8080/live/stream?state=alert&demo=1&focusSpeed=test&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00
```

確認:

```text
focus event id が時間経過で切り替わる
HUD が追随する
active marker が追随する
active panel item が追随する
ticker 注目が追随する
```

---

### 8. calm / empty / failure 安全動作

以下のケースを確認する。

```text
state=calm
API empty
API 500
API 404
invalid JSON
timeout 相当
```

期待:

```text
focus しない
marker / pulse なし、または対象なし
古い HUD focus 表示なし
古い panel active なし
古い ticker 注目なし
demo fallback なし
JS pageerror なし
unhandledrejection なし
```

failure を ordinary calm と誤表示しないこと。

---

### 9. reduced motion

`prefers-reduced-motion` 対応がある場合は確認する。

必須ではないが、CSS または JS で animation を抑制する配慮があるか確認し、レポートに記録する。

以下は PASS with notes 可:

```text
CSS 中心の簡易対応
E2E では厳密確認せず静的確認のみ
```

---

### 10. 地図操作不可の維持

Phase 3-A 以降の重要仕様を維持する。

確認:

```text
ズームUIがない
ドラッグで地図が動かない
ホイールでズームしない
ダブルクリックでズームしない
キーボード操作で動かない
```

focus 演出を入れたことで user interaction が有効化されていないこと。

---

### 11. Phase 3-D 回帰確認

badge/count/status 同期が壊れていないこと。

確認:

```text
地震 badge count
豪雨 badge count
鉄道 badge count
潮位 badge count
全体ステータス
panel data-count / data-status
body[data-stream-status]
data-stream-overall-status
```

既存 `live-stream-status-sync.spec.js` が PASS すること。

---

### 12. 通常 `/live` 副作用確認

通常 `/live` を開き、最低限以下を確認する。

```text
HTTP 200
pageerror なし
地図表示あり
既存パネル表示あり
既存レイヤー操作が大きく壊れていない
```

可能なら関連 live E2E も実行する。

---

## 手動スクリーンショット確認

以下を保存する。

```bash
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 \
  http://127.0.0.1:8080/live/stream \
  test-results/live-stream-phase4b-focus-view-1920.png

npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 \
  "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" \
  test-results/live-stream-phase4b-calm-1920.png

npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=2400 \
  "http://127.0.0.1:8080/live/stream?state=alert&demo=1&focusSpeed=test&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00" \
  test-results/live-stream-phase4b-demo-focus-1920.png
```

手動確認ポイント:

```text
focus 中に「何に注目しているか」一目で分かる
HUD が読みやすい
HUD がパネル/テロップを邪魔しない
地図が寄りすぎない
marker active が見やすい
panel active が見やすい
ticker 注目が読みやすい
calm で警戒演出が残らない
demo focus で HUD / marker / panel / ticker が同じ対象を示す
```

---

## 検証レポート作成

以下へレポートを作成する。

```text
tasks/live/live_stream_phase4b_focus_view_codex_verification.md
```

レポート構成:

```md
# live stream Phase 4-B focus view verification

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

---

## PASS 条件

以下を満たす場合 PASS。

```text
/live/stream が HTTP 200
focus 中の HUD / 注目ラベルが表示される
HUD focus id が body / marker / panel / ticker と一致する
focus marker が視覚的に強調される
focus panel item が視覚的に強調される
ticker 注目が focus event と同期する
overview / focus / returning で古い active 表示が残らない
calm / empty / failure で focus せず demo fallback しない
地図操作不可が維持される
Phase 3-D badge/count/status 回帰がない
通常 /live に明確な副作用がない
関連 E2E が PASS
検証レポートが作成されている
```

---

## FAIL 条件

以下のいずれかがあれば FAIL。

```text
/live/stream が表示できない
focus 中に HUD / 注目表示が出ない
HUD / marker / panel / ticker の focus id が不一致
focus 対象が変わっても古い active が残る
calm / empty / failure で古い focus 表示が残る
failure 時に demo fallback する
JS pageerror / unhandledrejection が出る
地図操作不可が解除される
Phase 3-D badge/count/status が壊れる
通常 /live が壊れる
```

---

## PASS with notes 可の条件

以下は PASS with notes 可。

```text
潮位/water alert event が未接続のため focus 対象外
鉄道 focus が代表点ベースで路線形状ではない
focus zoom の type 別チューニングが簡易
returning 表示が短くスクショで捕捉しづらい
prefers-reduced-motion は CSS 中心の簡易対応
404 などでブラウザ console に resource failure が出るが pageerror はない
```

---

## 最終判断

最後に以下を明記する。

```text
PASS
FAIL
PASS with notes
```

Phase 4-B で最も重視するのは以下。

```text
視聴者が今の注目対象を理解できること
同じ focus event id が地図・パネル・テロップ・HUDで一致すること
calm/error 時に古い注目表示が残らないこと
配信画面として落ちないこと
通常 /live を壊さないこと
```

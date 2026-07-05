# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 6-A：OBS実配信リハーサル・公開前最終確認 MVP 検証

## 目的

`/live/stream` が OBS / YouTube 配信用の実画面としてリハーサル可能な状態になっていることを検証する。

Phase 6-A は、実装機能の派手さではなく、公開前に安全確認できることを重視する。

検証対象URL:

```text
http://127.0.0.1:8080/live/stream?chrome=off
http://127.0.0.1:8080/live/stream?state=calm&chrome=off
http://127.0.0.1:8080/live/stream?demo=1&chrome=off
```

本番想定URLに `demo=1`、`focusSpeed=test`、`runtimeSpeed=test` が混入していないことを必ず確認する。

---

## 前提

以下は完了済みとして扱う。

```text
Phase 5-B: 30分soak / calm / demo / API復帰検証 PASS with notes
Phase 5-C: demo diagnostics 整理 PASS with notes
```

Phase 4-B は保留中であり、今回のFAIL条件に含めない。

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
tasks/live/live_stream_phase6a_obs_rehearsal_runbook.md
tasks/live/live_stream_phase6a_public_preflight_checklist.md
tools/live_stream_obs_rehearsal_probe.js
e2e/live-stream-obs-rehearsal.spec.js
frontend/live/stream.html
frontend/js/live-stream/
frontend/css/live/live-stream.css
```

重点確認:

```text
/live 本体に不要な変更が入っていないか
backend APIレスポンスを変更していないか
本番想定URLに demo/test 用挙動を混ぜていないか
Phase 5-B/5-C の安定性を壊していないか
```

---

## 静的確認

変更された JS / E2E / tools ファイルに対して `node --check` を実行する。

例:

```bash
node --check tools/live_stream_obs_rehearsal_probe.js
node --check e2e/live-stream-obs-rehearsal.spec.js
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-event-store.js
```

実際に存在するファイル名に合わせること。

backend 変更がある場合のみ Python compile を行う。

```bash
python -m compileall backend
```

---

## Docker / HTTP確認

```bash
docker compose ps
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?state=calm&chrome=off"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&chrome=off"
curl -I http://127.0.0.1:8080/live/stream
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

期待:

```text
すべて 200 OK
backend / martin は healthy
frontend は Up
```

---

## E2E検証

既存 scoped E2E に加えて、Phase 6-A の E2E を実行する。

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
  e2e/live-stream-obs-rehearsal.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

存在しない spec は除外し、実際のファイルに合わせること。

Phase 6-A固有の確認観点:

```text
/live/stream?chrome=off が表示される
本番想定URLで dataMode=real
本番想定URLで demo/test 表示が混入しない
主要UIが 1920x1080 に収まる
地図・小画面・ticker が存在する
window.__LiveStreamDiagnostics.getSnapshot() が取得できる
pageerror がない
通常 /live に回帰がない
```

---

## Runbook / checklist 確認

以下のファイルが存在し、内容が実用可能であることを確認する。

```text
tasks/live/live_stream_phase6a_obs_rehearsal_runbook.md
tasks/live/live_stream_phase6a_public_preflight_checklist.md
```

Runbook確認観点:

```text
OBS Browser Source URL が明記されている
1920x1080 / 16:9 前提が明記されている
リハーサル手順がある
異常時の停止・復旧手順がある
公開前チェック項目がある
notes / 既知制約がある
```

Checklist確認観点:

```text
画面確認
データ確認
安定性確認
OBS確認
YouTube等の公開範囲確認
異常時対応
```

---

## Rehearsal probe 確認

`tools/live_stream_obs_rehearsal_probe.js` が追加されている場合は実行する。

例:

```bash
node tools/live_stream_obs_rehearsal_probe.js \
  --url "http://127.0.0.1:8080/live/stream?chrome=off" \
  --minutes 10 \
  --interval 300 \
  --output test-results/live-stream-phase6a-rehearsal-probe.json \
  --screenshot-dir test-results
```

短時間probeで確認する項目:

```text
pageerror count
console error count
runtimeState
dataMode
Leaflet container count
ticker node count
railway layer count
marker count
bad token scan
screenshot保存
```

長時間確認は後続の manual / OBS soak で行ってよい。

---

## OBS実機確認

OBSが利用可能な環境では、必ず実機確認を行う。

確認手順:

```text
1. OBSを起動
2. Browser Source を追加
3. URL に http://127.0.0.1:8080/live/stream?chrome=off を指定
4. 幅 1920 / 高さ 1080
5. プレビューで表示確認
6. 10〜30分表示継続
7. 開始時 / 中間 / 終了時のスクリーンショットを保存
8. diagnostics snapshot を保存
```

確認観点:

```text
白画面化しない
文字が読める
ticker が読める
地図が表示される
小画面が表示される
focus が詰まらない
時計が進む
音声混入がない
OBS側でリサイズ崩れがない
```

OBS実機が使えない場合は、検証レポートで明記し、`PASS with notes` の候補とする。

---

## YouTube等の配信リハーサル確認

可能な場合のみ実施する。

重要:

```text
いきなり公開配信しない
限定公開 / 非公開 / テスト相当で確認
配信通知や公開範囲を事前確認
```

確認観点:

```text
視聴側で文字が読める
ticker が読める
地図と小画面が見える
遅延が許容範囲
停止手順を確認できた
```

実施できない場合は `未実施` と明記し、FAILにはしない。ただし「公開前最終確認」として残課題に記録する。

---

## 30分以上の通常soak

可能なら以下を実施する。

```text
URL: http://127.0.0.1:8080/live/stream?chrome=off
viewport: 1920x1080
duration: 30分以上
```

記録:

```text
0分 screenshot
15分 screenshot
30分 screenshot
diagnostics snapshot
console/pageerror/requestfailed summary
```

期待:

```text
pageerror 0
重大 console error なし
Leaflet container 増殖なし
ticker node 増殖なし
railway layer 増殖なし
marker 単調増加なし
runtimeState が妥当
```

60分以上できた場合はレポートに明記する。

---

## API失敗・復帰確認

可能なら、既存 Phase 5-B と同様に API failure / recovery を確認する。

確認観点:

```text
失敗中に平常扱いしない
取得確認中文言になる
pageerror が出ない
復帰後 healthy / ok に戻る
```

短時間でよい。

---

## スクリーンショット

以下を保存する。

```text
test-results/live-stream-phase6a-obs-rehearsal-normal-start-1920.png
test-results/live-stream-phase6a-obs-rehearsal-normal-mid-1920.png
test-results/live-stream-phase6a-obs-rehearsal-normal-end-1920.png
test-results/live-stream-phase6a-obs-rehearsal-calm-1920.png
test-results/live-stream-phase6a-obs-rehearsal-demo-1920.png
```

OBS実機を使った場合は、OBSプレビューのスクリーンショットも保存する。

---

## 検証レポート作成

以下にレポートを作成する。

```text
tasks/live/live_stream_phase6a_obs_rehearsal_codex_verification.md
```

構成:

```md
# live stream Phase 6-A OBS rehearsal verification

## Result
PASS / FAIL / PASS with notes

## Summary

## Checked files

## Environment

## Commands

## HTTP results

## E2E results

## Runbook / checklist review

## Rehearsal probe results

## OBS actual check

## YouTube / stream rehearsal check

## Soak results

## Diagnostics snapshot

## Screenshots

## Findings

## Notes

## Final judgement
```

---

## PASS条件

以下を満たす場合 PASS。

```text
/live/stream?chrome=off が表示できる
本番想定URLで dataMode=real
本番想定URLで demo/test state が混入しない
主要UIが1920x1080で表示される
Runbook と checklist が作成されている
scoped E2E がPASS
短時間または30分soakで pageerror なし
Leaflet/ticker/railway layer の明確な増殖なし
通常 /live と / に副作用なし
検証レポートが作成されている
```

OBS実機とYouTube限定配信まで確認できた場合は、レポートで強くPASSと判断してよい。

---

## PASS with notes 条件

以下は PASS with notes 可。

```text
OBS実機確認が未実施で、Chrome/Playwright soakのみ
YouTube配信確認が未実施
60分ではなく30分soakまで
サードパーティ由来の非致命 console error が少数残る
タイル/PMTiles requestfailed があるが画面破綻なし
```

ただし、本番想定URLが表示できない場合は PASS with notes ではなく FAIL。

---

## FAIL条件

以下のいずれかがあれば FAIL。

```text
/live/stream?chrome=off が表示できない
本番想定URLで demo/test mode になる
OBSプレビューで白画面になる
pageerror が出る
主要UIが画面外にはみ出す
Leaflet container が増殖する
railway layer が増殖する
ticker node が増殖する
API失敗を平常扱いする
runtime diagnostics が取れない
/live 本体が壊れる
```

---

## 最終判断

最終的に以下のいずれかを明記する。

```text
PASS
PASS with notes
FAIL
```

Phase 6-A では、実配信に向けて「何が確認済みで、何が未確認か」を明確にすることが最重要。

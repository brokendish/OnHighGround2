# Claude用実装・運用準備指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 6-A：OBS実配信リハーサル・公開前最終確認 MVP

## 目的

`/live/stream` を OBS / YouTube 配信用の実画面としてリハーサルできる状態にする。

Phase 6-A は新機能を大きく追加するフェーズではない。目的は、これまで実装してきた `/live/stream` を実運用前に安全に確認できるようにすることである。

対象は以下。

```text
/live/stream?chrome=off
  OBS Browser Source 用の本番想定URL

/live/stream?state=calm&chrome=off
  静穏状態確認用

/live/stream?demo=1&chrome=off
  デモ表示確認用
```

Phase 6-A では、OBS 実機または通常 Chrome / Playwright での長時間表示、YouTube限定公開または非公開相当の配信リハーサル、公開前チェックリスト、診断ログ収集を整備する。

---

## 前提

以下フェーズは完了済みとして扱う。

```text
Phase 3-B: メイン地図 本番データ連動 MVP
Phase 3-C: メイン地図 event と左右パネル・テロップ同期 MVP
Phase 3-D: 全体ステータス・カテゴリバッジ・件数表示同期 MVP
Phase 4-A: 自動巡回・注目地域フォーカス MVP
Phase 5-A: 配信用安定運用・長時間稼働対策 MVP
Phase 5-A.1: 地震情報 子画面詳細化 MVP
Phase 5-B: OBS配信想定 soak 検証
Phase 5-C: demo mode console error / diagnostics 状態整理 MVP
```

Phase 4-B は保留扱いであり、Phase 6-A の成否条件に含めない。

---

## 重要方針

### 1. 新規機能追加を最小化する

Phase 6-A は「実配信前のリハーサル・公開前確認」が目的。

禁止事項:

```text
大規模なUI変更
既存 EventStore / FocusController / Runtime の再設計
/live 本体への不要な変更
backend APIレスポンス形式の変更
OBS向けに /live/stream の通常挙動を壊す変更
```

必要な変更は、診断・チェックリスト・リハーサル補助に限定する。

---

### 2. `/live/stream?chrome=off` を本番想定URLにする

OBS Browser Source の基本URLは以下とする。

```text
http://127.0.0.1:8080/live/stream?chrome=off
```

本番公開時にドメイン経由で配信する場合は、同じ path / query を使う。

```text
https://<domain>/live/stream?chrome=off
```

`demo=1`、`focusSpeed=test`、`runtimeSpeed=test` は検証用であり、本番想定URLには含めない。

---

### 3. 実配信リハーサルは「失敗時に安全に止められる」ことを優先する

YouTube等で確認する場合は、いきなり公開配信にしない。

推奨:

```text
限定公開 / 非公開 / テスト配信相当
公開前に音声・個人情報・URL・通知設定を確認
配信停止手順を事前に確認
```

このプロジェクトの Phase 6-A では、公開運用の自動化までは対象外とする。

---

## 実装・整備対象

### A. OBSリハーサル用Runbook作成

以下のファイルを作成または更新する。

```text
tasks/live/live_stream_phase6a_obs_rehearsal_runbook.md
```

内容に以下を含める。

```text
1. 目的
2. 使用URL
3. OBS Browser Source 推奨設定
4. リハーサル手順
5. 監視ポイント
6. 異常時の停止・復旧手順
7. 公開前チェックリスト
8. 判定基準
9. 既知のnotes
```

OBS Browser Source 推奨設定には以下を含める。

```text
URL: /live/stream?chrome=off
幅: 1920
高さ: 1080
表示比率: 16:9
音声: 原則なし
CSS/HTMLをOBS側で無理に上書きしない
ページ権限やローカルURLの扱いを確認
```

OBSのバージョン依存設定やYouTubeの細かな推奨ビットレートなど、環境差が大きい情報は断定しない。

---

### B. 公開前チェックリスト作成

以下のファイルを作成または更新する。

```text
tasks/live/live_stream_phase6a_public_preflight_checklist.md
```

最低限、以下のチェック項目を含める。

```text
画面:
- /live/stream?chrome=off が表示できる
- 1920x1080 に収まる
- 文字が読める
- ticker が読める
- 地図が白画面になっていない
- 小画面が崩れていない
- demo/test用表示が混入していない

データ:
- dataMode が real である
- runtimeState が healthy / degraded / error のいずれかとして正しく出る
- 取得失敗時に「平常」と誤断定しない
- demo fallback しない

安定性:
- 30分以上表示して白画面化しない
- Leaflet container が増殖しない
- ticker node が増殖しない
- railway layer が増殖しない
- marker が単調増加し続けない

OBS:
- Browser Source のURLが本番想定URL
- 画面サイズが1920x1080
- 音声混入なし
- 個人情報や開発用URLが見えていない
- 配信開始/停止手順を確認済み

YouTube等:
- 最初は限定公開/非公開相当
- タイトル/説明/サムネ/公開範囲を確認
- 誤って公開配信しない
```

---

### C. OBS rehearsal probe の整備

既存 diagnostics を使い、OBSリハーサル前後の状態を保存できる Playwright または Node script を追加してよい。

推奨ファイル:

```text
tools/live_stream_obs_rehearsal_probe.js
```

既存のツール配置方針がある場合はそれに合わせる。

このスクリプトは、以下を環境変数または引数で指定できるようにする。

```text
URL
DURATION_MINUTES
SAMPLE_INTERVAL_SECONDS
OUTPUT_JSON
SCREENSHOT_DIR
```

例:

```bash
node tools/live_stream_obs_rehearsal_probe.js \
  --url "http://127.0.0.1:8080/live/stream?chrome=off" \
  --minutes 30 \
  --interval 300 \
  --output test-results/live-stream-phase6a-obs-rehearsal-diagnostics.json
```

記録対象:

```text
時刻
pageerror count
console error count
requestfailed summary
window.__LiveStreamDiagnostics.getSnapshot()
Leaflet container count
ticker node count
railway layer count
map marker count
body data attributes
bad token scan結果
スクリーンショットパス
```

注意:

```text
このprobeはOBS実機の完全な代替ではない
OBS実機確認ができない場合は PASS with notes にする
```

---

### D. Diagnostics の不足があれば最小限追加

既存 `window.__LiveStreamDiagnostics.getSnapshot()` で不足があれば、最小限追加する。

追加候補:

```text
dataMode
runtimeState
focusMode
focusEventId
eventCount
markerCount
tickerTextNodes
leafletContainerCount
railwayLayerCount
earthquakeDetail status
railwayMiniMap status
lastRefreshAt
consecutiveFailures
```

すでに取得できるものは再実装しない。

---

### E. `/live/stream` 本番想定URLのE2Eを追加

以下の E2E を追加または更新する。

```text
e2e/live-stream-obs-rehearsal.spec.js
```

確認観点:

```text
/live/stream?chrome=off が表示できる
body に demo/test state が混入しない
本番想定URLでは dataMode=real
1920x1080 に収まる
主要UIが存在する
地図が表示される
ticker が存在する
pageerror がない
runtime diagnostics が取れる
```

長時間soakそのものは Playwright標準E2Eに含めなくてもよい。長時間検証は probe / 手動リハーサルで行う。

---

## OBS実機リハーサル手順の推奨

Runbookには以下の手順を含める。

### 1. ローカル準備

```bash
docker compose ps
curl -I http://127.0.0.1:8080/live/stream?chrome=off
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

### 2. 通常ブラウザ確認

```text
Chromeで /live/stream?chrome=off を表示
1920x1080相当で確認
スクリーンショット保存
console / pageerror / diagnostics を確認
```

### 3. OBS Browser Source 確認

```text
Browser Source を追加
URL: /live/stream?chrome=off
幅: 1920
高さ: 1080
音声なし
OBSプレビューに収まることを確認
```

### 4. 30分以上のリハーサル

```text
開始時スクリーンショット
15分時点スクリーンショット
30分時点スクリーンショット
diagnostics snapshot 保存
CPU/メモリの目視確認
```

### 5. 限定公開/非公開相当の配信テスト

```text
公開範囲を必ず確認
通知が飛ばない設定を確認
数分配信
視聴側で文字・ticker・地図が読めることを確認
停止手順を確認
```

---

## 失敗時の扱い

以下は FAIL。

```text
/live/stream?chrome=off が表示できない
OBS Browser Source で白画面になる
pageerror が出る
通常30分で Leaflet container が増殖する
ticker node が増殖する
marker が単調増加し続ける
runtimeState が実態と合わない
取得失敗を平常扱いする
demo/test state が本番URLに混入する
/live 本体が壊れる
```

以下は PASS with notes 可。

```text
OBS実機が使えず Playwright/Chrome soak のみ
60分ではなく30分確認まで
サードパーティ由来の非致命 console error が少数残る
requestfailed にタイル abort が出るが画面破綻なし
YouTube実配信は未実施で、OBSプレビュー/録画のみ
```

---

## 完了条件

```text
Runbook が作成されている
公開前チェックリストが作成されている
本番想定URLのE2Eがある
必要なら rehearsal probe が追加されている
/live/stream?chrome=off が実運用前確認できる
/live と / に副作用がない
CODEXが検証レポートを作成できる状態
```

---

## 注意

Phase 6-A は「華やかな機能追加」ではない。

目的は、OBS実配信リハーサルを安全に行い、公開前に問題を見つけられる状態へ持っていくこと。

余計な演出改善やレイアウト大改修は後続フェーズへ回すこと。

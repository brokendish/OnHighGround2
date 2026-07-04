# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 3-D：全体ステータス・カテゴリバッジ・件数表示の同期 MVP 検証

## 目的

Claude実装後、`/live/stream` の以下が同じ EventStore / normalized event pipeline に基づいて同期していることを検証する。

```text
中央メイン地図 marker
左右パネル
下部テロップ
上部カテゴリバッジ
全体ステータス
各パネル右上の対象件数/状態
```

Phase 3-C では地図・パネル・テロップの event sync が PASS with notes だった。

Phase 3-D では、その notes のうち以下を重点検証する。

```text
全体ステータスバッジが EventStore summary と同期しているか
カテゴリ別件数が EventStore の有効 event 件数と一致しているか
API失敗を通常 calm と誤表示していないか
```

潮位 event の alert 判定未接続は、今回の主検証対象ではない。

ただし、EventStore に tide/water event が入る場合は、その件数同期は検証する。

---

## 事前確認

まず差分と関連ファイルを確認する。

```bash
git diff --stat
git diff
```

確認対象例:

```text
frontend/live/stream.html
frontend/css/live/live-stream.css
frontend/js/live-stream/live-stream-event-store.js
frontend/js/live-stream/live-stream-main.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-scene.js
frontend/js/live-stream/live-stream-map-events.js
frontend/js/live-stream/live-stream-map-view.js
frontend/js/live-stream/live-stream-earthquake-adapter.js
frontend/js/live-stream/live-stream-rain-adapter.js
frontend/js/live-stream/live-stream-railway-adapter.js
frontend/js/live-stream/live-stream-tide-adapter.js
e2e/live-stream-status-sync.spec.js
e2e/live-stream-event-sync.spec.js
e2e/live-stream-main-map-real-data.spec.js
```

重点確認:

```text
通常 /live へ stream 専用変更を混ぜていないか
既存APIレスポンス形式を壊していないか
EventStore 以外で別々に件数計算していないか
API失敗時に calm と誤表示していないか
demo fallback が通常表示に混ざっていないか
setInterval / subscribe が多重登録されていないか
DOM が更新ごとに増殖しないか
```

---

## 静的確認

### JS構文確認

変更された JS / E2E に対して `node --check` を実行する。

例:

```bash
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js
node --check frontend/js/live-stream/live-stream-rain-adapter.js
node --check frontend/js/live-stream/live-stream-railway-adapter.js
node --check frontend/js/live-stream/live-stream-tide-adapter.js
node --check e2e/live-stream-status-sync.spec.js
node --check e2e/live-stream-event-sync.spec.js
node --check e2e/live-stream-main-map-real-data.spec.js
node --check e2e/live-stream.spec.js
```

実際のファイル名に合わせて実行すること。

---

### Python構文確認

backend に変更がある場合のみ実施。

```bash
python -m compileall backend
```

backend に変更がない場合は not run と明記してよい。

---

## Docker起動確認

```bash
docker compose ps
```

必要に応じて:

```bash
docker compose up -d
```

主要サービスが Up / healthy であること。

---

## HTTP確認

以下が HTTP 200 で返ること。

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I 'http://127.0.0.1:8080/live/stream?state=calm'
curl -I 'http://127.0.0.1:8080/live/stream?demo=1'
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

`/live/stream` と `/live/stream.html` の扱いは既存仕様に合わせて確認する。

---

## E2E検証

推奨実行:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

既存の関連テストが増減している場合は、実装に合わせて読み替えること。

---

## 必須検証観点

### 1. EventStore summary と上部カテゴリバッジの同期

Playwright route mock で以下のような有効 event を返す。

```text
earthquake: 2件
rain: 3件
kikikuru: 2件
railway: 4件
tide/water: 0件
```

期待:

```text
地震バッジ count = 2
豪雨バッジ count = 5  または実装仕様通り rain/kikikuru 合算
鉄道バッジ count = 4
潮位バッジ count = 0
```

確認対象例:

```text
[data-stream-category="earthquake"]
[data-stream-category="rain"]
[data-stream-category="railway"]
[data-stream-category="tide"]
```

既存 class/data 属性に合わせて確認する。

DOM 表示テキストだけでなく、可能なら `data-count` / `data-status` も確認する。

---

### 2. 地図 marker 件数とカテゴリ件数の整合

地図 marker とカテゴリバッジが同じ EventStore の valid event を参照していることを確認する。

期待:

```text
地震 marker 件数 = earthquake count
豪雨/kikikuru marker 件数 = rain/kikikuru count
鉄道 marker 件数 = railway count
潮位 marker 件数 = tide/water event count
```

注意:

```text
表示上限がある場合は、summary count と rendered count の仕様差をレポートに明記する
例: summary count は 10、rendered marker は上限 5
```

Phase 3-D で重要なのは、仕様として矛盾していないこと。

---

### 3. パネル右上の対象数/状態表示との整合

各パネル右上の表示が EventStore summary と矛盾しないことを確認する。

対象例:

```text
地震情報: 対象 1/2, 監視中, 取得確認中
キキクル・豪雨情報: 対象 1/5, 発表なし, 一時的に取得不可
鉄道情報: 影響 4路線, 平常運転, 一時的に取得不可
潮位・水位: 地点 1・2/6, 8巡回
```

期待:

```text
event があるカテゴリは対象数/影響数が EventStore 件数と整合
event がない取得成功カテゴリは対象なし/発表なし/平常監視
event がない取得失敗カテゴリは取得確認中/一時的に取得不可であり、単なる平常扱いではない
```

潮位パネルは通常観測地点表示があるため、以下を確認する。

```text
潮位パネルの station 表示件数と、上部潮位 event badge count を混同していない
```

---

### 4. overallStatus の同期

有効 event の severity に応じて全体ステータスが更新されることを確認する。

ケース例:

```text
high earthquake あり -> overallStatus high または既存 view level high
critical event あり -> critical または既存互換の high
event なし + 取得成功 -> calm / 監視中
event なし + API失敗 -> checking/error/watch 等。通常 calm と誤表示しない
state=calm -> calm 強制
```

確認対象例:

```text
body[data-stream-status]
[data-stream-overall-status]
.level[data-lv]
ヘッダー状態文言
```

既存語彙が `calm/high` のみの場合は、`statusRaw` と `statusView` の関係をレポートに明記する。

---

### 5. API失敗時に calm と誤表示しない

以下を route mock で検証する。

```text
500
404
不正JSON
timeout相当
一部APIのみ失敗
全APIに近い失敗
```

期待:

```text
JS error なし
unhandledrejection なし
地図表示維持
demo fallback なし
ticker は取得確認中などの文言
category badge / panel status が通常の平常監視と誤認しない表示
```

重要:

```text
API失敗で event が 0 件になっただけなのに、完全な平常/発表なしと表示しないこと
```

---

### 6. 空データ時の calm 表示

API が正常に空データを返すケースを検証する。

期待:

```text
marker 0
badge count 0
パネルは対象なし/発表なし/平常監視
ticker は全国監視中/現在大きな発表なし
overallStatus calm
JS error なし
demo fallback なし
```

空データと API失敗を区別できていること。

---

### 7. stale / invalid event の件数除外

以下のデータを混ぜる。

```text
stale event
不正座標 event
severity 不足 event
通常雨など対象外 event
同一 id 重複 event
```

期待:

```text
地図 marker に出ない
category badge count に含まれない
panel 対象数に含まれない
EventStore summary の active count に含まれない
JS error なし
```

---

### 8. demo=1 の同期

```text
/live/stream?demo=1
```

期待:

```text
demo event が EventStore pipeline に入る
map marker / panel / ticker / badge / overallStatus が同期する
通常 API と混ざらない
```

確認例:

```text
地震 demo event があれば地震 badge count が増える
豪雨 demo event があれば豪雨 badge count が増える
鉄道 demo event があれば鉄道 badge count が増える
overallStatus が demo event severity に応じた状態になる
```

---

### 9. state=calm の維持

```text
/live/stream?state=calm
```

期待:

```text
marker 0
pulse 0
badge count 0
overallStatus calm
パネルは監視中/対象なし
テロップは監視中
mock data が存在しても表示されない
```

既存仕様通り、`calm=1` ではなく `state=calm` を正とする。

---

### 10. 地図操作不可と attribution 維持

Phase 3-A 以降の仕様が壊れていないこと。

確認:

```text
ズームUIがない
ドラッグで地図が動かない
ホイールでズームしない
ダブルクリックでズームしない
キーボード操作で動かない
OSM/CARTO/Leaflet attribution が表示される
```

---

### 11. 通常 `/live` への副作用確認

通常 `/live` を開いて最低限確認する。

```text
HTTP 200
ページエラーなし
地図表示あり
既存パネル表示あり
既存レイヤー操作が明確に壊れていない
```

可能なら代表回帰 E2E も実行する。

---

## 手動ブラウザ確認

以下URLを 1920x1080 で確認し、スクリーンショットを保存する。

```text
http://127.0.0.1:8080/live/stream
http://127.0.0.1:8080/live/stream?state=calm&chrome=off
http://127.0.0.1:8080/live/stream?state=alert&demo=1&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00
```

保存例:

```text
test-results/live-stream-phase3d-status-sync-1920.png
test-results/live-stream-phase3d-calm-1920.png
test-results/live-stream-phase3d-demo-1920.png
```

確認:

```text
上部カテゴリバッジの件数が画面内容と一致している
全体ステータスが画面内容と矛盾していない
取得失敗時に平常と誤認しない
左右パネルとテロップが読みやすい
地図 marker と badge count が大きく矛盾していない
```

---

## 検証レポート作成

以下にレポートを作成する。

```text
tasks/live/live_stream_phase3d_status_badge_count_sync_codex_verification.md
```

レポート構成:

```md
# live stream Phase 3-D status badge count sync verification

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

## PASS条件

以下をすべて満たす場合 PASS。

```text
/live/stream が HTTP 200
中央メイン地図が表示される
全体ステータスが EventStore summary と同期している
上部カテゴリバッジの件数が valid event 件数と同期している
パネル右上の対象数/状態が EventStore summary と矛盾しない
ticker の状態文が header/panel 状態と矛盾しない
空データと API失敗を区別できている
API失敗時に通常 calm と誤表示しない
demo=1 も badge/status/panel/ticker が同期する
state=calm が既存仕様通り維持される
stale/invalid event が件数に含まれない
地図操作不可と attribution が維持される
通常 /live に明確な副作用がない
関連E2Eが PASS
検証レポートが作成されている
```

---

## FAIL条件

以下のいずれかがあれば FAIL。

```text
/live/stream が表示できない
Leaflet 地図が初期化されない
全体ステータスが EventStore と無関係に固定表示されている
カテゴリバッジ件数が地図/パネル/event と明確に矛盾している
API失敗を平常/発表なしとして表示している
通常アクセス時に demo marker / demo count に fallback している
JS pageerror / unhandledrejection が出る
state=calm が壊れている
地図操作不可が解除されている
通常 /live が壊れている
更新のたびにDOMやlistenerが増殖する
```

---

## PASS with notes 条件

以下は PASS with notes 可。

```text
既存CSS互換のため statusRaw は critical/watch/error だが表示用 data-lv は high/calm に丸めている
潮位/water event は alert 判定未接続のため通常は count 0
summary count と rendered marker count に上限差があるが仕様として明記されている
一部パネルは既存 scene 表示を維持しており、data 属性で整合確認している
```

---

## 最終判断

検証完了後、以下を明記する。

```text
PASS
FAIL
PASS with notes
```

今回の検証で特に重視するのは以下。

```text
画面上の数字が嘘をつかないこと
API失敗を平常と誤認させないこと
地図・パネル・テロップ・バッジが同じ event pipeline を見ていること
通常 /live を壊していないこと
```

監視卓では、件数とステータスの信頼性が最重要。


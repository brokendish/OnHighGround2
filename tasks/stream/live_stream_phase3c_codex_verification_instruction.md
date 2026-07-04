# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 3-C：メイン地図 event と左右パネル・テロップの同期 MVP 検証

## 目的

Claude実装後、`/live/stream` の中央メイン地図 event、左右パネル、下部テロップが同一 event データに基づいて同期されていることを検証する。

Phase 3-C で重要なのは、単に表示が増えることではない。

以下を確認する。

```text
地図・パネル・テロップが同じ event source を見ている
通常アクセス時に demo 表示へ fallback していない
空データ/失敗時に表示が破綻しない
取得失敗を平常と誤断定しない
state=calm が既存仕様通り動く
通常 /live に副作用がない
```

---

## 前提

Phase 3-B は PASS with notes 済み。

確認済み:

```text
通常 /live/stream で demo pulse ではなく本番API由来 event marker を表示
空データ / 500 / 404 / 不正JSON / timeout で画面破綻なし
不正座標除外・重複排除・件数上限・stale 表示/除外
地図操作不可を維持
OSM/CARTO/Leaflet attribution 表示
/live と / に明確な副作用なし
```

Phase 3-B の notes:

```text
calm URL は calm=1 ではなく既存仕様の state=calm
潮位の中央地図 event は alert 判定未接続のため実質後続フェーズ扱い
```

Phase 3-C 検証でも、`state=calm` を正とする。

---

## 事前確認

まず `/live` ガードレール、今回の実装差分、関連ファイルを確認する。

確認例:

```bash
git diff --stat
git diff
```

関連ファイル例:

```text
frontend/js/live/stream/
frontend/css/live/stream/
frontend/live-stream.html
frontend/live/
backend/
e2e/live-stream*.spec.js
tasks/live/
```

既存構成に合わせて読み替えること。

---

## 静的確認

### 1. JS構文確認

変更された JS ファイルに対して構文チェックを行う。

例:

```bash
node --check frontend/js/live/stream/live-stream-event-store.js
node --check frontend/js/live/stream/live-stream-panel-events.js
node --check frontend/js/live/stream/live-stream-ticker-events.js
node --check frontend/js/live/stream/live-stream-main-map-events.js
node --check frontend/js/live/stream/live-stream-data-source.js
```

実際のファイル名に合わせて実行すること。

---

### 2. Python構文確認

backend に変更がある場合のみ実施。

```bash
python -m compileall backend
```

---

### 3. 差分確認

以下を重点確認する。

```text
通常 /live の既存処理に stream 専用分岐を大量追加していないか
既存APIレスポンスを破壊していないか
地図・パネル・テロップが別々の mock を見ていないか
demo data が通常表示の fallback になっていないか
fetch 失敗時に未捕捉例外が出ないか
setInterval が多重起動しないか
marker / panel row / ticker item が更新のたびに増殖しないか
state=calm ではなく calm=1 前提に置き換えていないか
```

---

## Docker起動確認

```bash
docker compose ps
```

必要に応じて:

```bash
docker compose up -d
```

主要サービスが healthy / Up であること。

---

## HTTP確認

以下が HTTP 200 で返ること。

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I http://127.0.0.1:8080/live/stream?state=calm
curl -I http://127.0.0.1:8080/live/stream?demo=1
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

`/live/stream.html` もサポートしている場合は合わせて確認する。

```bash
curl -I http://127.0.0.1:8080/live/stream.html
```

---

## E2E検証

### 推奨実行

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js
```

既存の関連テストがある場合は合わせて実行する。

例:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

---

## 必須検証観点

### 1. 同一 event id の同期

Playwright route mock を使い、既存APIに本番相当レスポンスを返す。

推奨 mock event id:

```text
eq-sync-001
rain-sync-001
rail-sync-001
```

確認:

```text
同一 event id が地図 marker に反映される
同一 event id または同じ title が左右パネルに反映される
同じ event の内容が下部テロップに反映される
地図だけ/パネルだけ/テロップだけに存在する不整合がない
```

DOM class / 属性例:

```text
.stream-map-event[data-event-id="eq-sync-001"]
.stream-panel-event[data-event-id="eq-sync-001"]
.stream-ticker-event[data-event-id="eq-sync-001"]
```

実装 class 名に合わせて確認すること。

`data-event-id` が実装されていない場合は、title / text / class の組み合わせで検証する。ただし、可能であれば `data-event-id` 追加を推奨する。

---

### 2. カテゴリ別同期

以下をそれぞれ確認する。

```text
地震 event:
  地図 marker 表示
  地震パネル表示
  テロップ表示

豪雨・キキクル event:
  地図 marker 表示
  豪雨/キキクルパネル表示
  テロップ表示

鉄道 event:
  地図 marker またはパネル表示
  鉄道パネル表示
  テロップ表示
```

鉄道 event で代表座標がない仕様の場合は、地図 marker なしでも PASS with notes 可。その場合、パネル・テロップに表示され、地図非表示が仕様として妥当か確認する。

潮位 event は Phase 3-B notes に従い、alert 判定未接続なら後続扱いでよい。

---

### 3. summary / status 同期

event の severity に応じて全体ステータスが更新されることを確認する。

例:

```text
critical event あり → critical / 重大情報あり 相当
high event あり → alert / 警戒情報あり 相当
medium event あり → watch / 監視中 相当
event なし & fetch ok → calm / 全国監視中 相当
fetch 失敗 & 有効cacheなし → unavailable / 取得確認中 相当
一部API失敗 → partial / 一部取得待機中 相当
```

既存デザインの表記に合わせて判定する。

重要なのは、地図・パネル・テロップ・ステータスが矛盾しないこと。

---

### 4. demo marker / demo ticker に逃げていないこと

通常アクセス:

```text
/live/stream
```

確認:

```text
demo 専用 marker が出ていない
demo 固定パネル文言が出ていない
demo 固定テロップだけで成功扱いしていない
本番API mock の内容に応じて地図・パネル・テロップが出る
API空レスポンス時に demo 表示へ fallback しない
API失敗時に demo 表示へ fallback しない
```

---

### 5. demo=1

URL:

```text
/live/stream?demo=1
```

確認:

```text
demo event が表示される
demo event が地図・パネル・テロップに同期される
本番 fetch と混ざらない
可能なら通常 event と同じ renderer / store を通っている
```

---

### 6. state=calm

URL:

```text
/live/stream?state=calm
```

確認:

```text
marker なし
パネルは静穏表示
テロップは監視中メッセージ
JS error なし
画面崩れなし
```

`calm=1` ではなく `state=calm` を正として確認する。

---

### 7. 空データ

API が空データを返すケースを検証する。

期待:

```text
JS error なし
メイン地図表示維持
marker 0件
パネル静穏表示
テロップ監視中表示
demo 表示への fallback なし
```

---

### 8. API失敗

以下を検証する。

```text
500
404
timeout相当
不正JSON
一部APIのみ失敗
```

期待:

```text
JS error なし
unhandledrejection なし
地図表示維持
パネルは取得待機または一部取得不可表示
テロップは取得待機または監視継続表示
demo 表示に fallback しない
取得失敗を平常と断定しない
```

Playwright で以下を監視する。

```js
page.on('pageerror', ...)
page.on('console', ...)
```

console error が実害あるものなら FAIL。

---

### 9. 更新時の差し替え

可能なら route mock またはテスト用 refresh hook を使い、初回と2回目で異なる event を返す。

初回:

```text
eq-sync-001
rain-sync-001
```

2回目:

```text
eq-sync-002
rail-sync-001
```

期待:

```text
古い marker が残らない
古い panel row が残らない
古い ticker text が残らない
新しい event が反映される
同一 id が重複しない
DOM が増殖しない
```

この検証が難しい場合は、E2Eでなくコード確認 + 可能な範囲の実ブラウザ確認でもよいが、レポートに明記する。

---

### 10. 表示件数上限

多数 event を返し、表示上限が守られることを確認する。

期待例:

```text
地図 event 合計が過剰にならない
カテゴリ別パネルは最大3件程度
テロップは headline event のみ
重要度順に上位が出る
```

実装仕様に合わせて確認し、上限値をレポートに記録する。

---

### 11. stale データ

古いデータを返す。

期待:

```text
仕様通り除外される
または stale class / 更新確認中 表示になる
テロップで古い情報を最新のように断定しない
```

どちらの仕様で実装されたかをレポートに明記する。

---

### 12. 地図操作不可の維持

Phase 3-A / 3-B の重要仕様が壊れていないこと。

確認:

```text
ズームUIがない
ドラッグで地図が動かない
ホイールでズームしない
ダブルクリックでズームしない
キーボード操作で動かない
```

---

### 13. attribution 表示

OSM / CARTO / Leaflet attribution が表示されていること。

確認:

```text
OpenStreetMap
CARTO
Leaflet
```

実際の表記に合わせる。

---

### 14. `/live` 通常画面への副作用確認

通常 `/live` を開き、最低限以下を確認する。

```text
ページエラーなし
地図表示あり
既存パネル表示あり
既存レイヤー操作が大きく壊れていない
```

可能なら既存代表E2Eも実行。

```bash
npx playwright test e2e/live*.spec.js
```

重すぎる場合は、関連する代表テストのみでよい。

---

## 手動ブラウザ確認

以下URLを開いてスクリーンショットを取得する。

```text
http://127.0.0.1:8080/live/stream
```

推奨 viewport:

```text
1920x1080
```

確認:

```text
中央地図の event と左右パネルの内容が一致している
下部テロップが event 由来の内容になっている
表示が多すぎない
左右パネルを邪魔しない
下部テロップが読みやすい
通常アクセス時に demo 表示ではない
```

スクリーンショット保存例:

```text
test-results/live-stream-phase3c-event-sync-1920.png
```

必要に応じて以下も取得する。

```text
test-results/live-stream-phase3c-calm-1920.png
test-results/live-stream-phase3c-demo-1920.png
```

---

## 検証レポート作成

以下にレポートを作成する。

```text
tasks/live/live_stream_phase3c_event_panel_ticker_sync_codex_verification.md
```

レポート構成:

```md
# live stream Phase 3-C event panel ticker sync verification

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
地図・左右パネル・下部テロップが同一 event source 由来で同期される
通常アクセス時に demo 表示へ fallback しない
空データ/失敗/不正JSON/timeout で JS error にならない
取得失敗を平常と誤断定しない
state=calm が既存仕様通り動く
地図操作不可が維持される
OSM/CARTO/Leaflet attribution が表示される
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
地図・パネル・テロップが別々の mock / demo を見ている
通常アクセス時に demo 表示だけで成功扱いしている
API失敗時に画面が破綻する
取得失敗を平常と断定する
JS pageerror / unhandledrejection が出る
地図操作不可が解除されている
通常 /live が壊れている
marker / panel row / ticker item が更新のたびに増殖する
state=calm が壊れている
```

---

## PASS with notes 条件

以下は PASS with notes 可。

```text
潮位・水位は alert 判定未接続のため静穏表示または後続扱い
鉄道は代表座標がない event はパネル/テロップのみ表示
highlight 同期は未実装だが、地図・パネル・テロップの内容同期はできている
更新差し替え検証がE2Eでは限定的で、コード確認と手動確認で補完
stale 判定が簡易実装
一部APIが未設定時 unavailable / partial だが画面破綻なし
```

---

## 最終判断

検証完了後、以下を明記する。

```text
PASS
FAIL
PASS with notes
```

PASS with notes の場合は、後続フェーズで対応すべき残課題を具体的に列挙すること。

今回の検証で特に重視するのは以下。

```text
地図・パネル・テロップが同じ event を見ていること
通常表示で demo に逃げていないこと
取得失敗を平常と誤表示しないこと
配信画面として落ちないこと
通常 /live を壊していないこと
```

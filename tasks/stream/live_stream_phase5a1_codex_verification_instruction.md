# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 5-A.1：地震情報 子画面詳細化 MVP 検証

## 目的

Claude実装後、`/live/stream` の左上「地震情報」子画面が、現在対象の地震に紐づく P2P 市区町村震度情報を表示できることを検証する。

今回の重点は以下。

```text
市区町村震度リストが表示される
多数市区町村時に自動スクロールする
スクロール完了まで表示対象が切り替わらない
小地図に市区町村震度マーカーが出る
広域震度時に小地図が巡回する
小地図巡回完了まで次の情報へ進まない
P2P詳細なし/失敗/空データで破綻しない
Phase 5-A の安定運用対策を壊していない
通常 /live に副作用がない
```

---

## 事前確認

まずガードレール、今回の実装差分、関連ファイルを確認する。

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
backend/
data_runtime/
e2e/live-stream-earthquake-detail.spec.js
e2e/live-stream-stability.spec.js
tasks/live/
```

特に以下を確認する。

```text
通常 /live 側に stream 専用の大きな分岐を入れていないか
既存APIレスポンスを破壊していないか
P2P詳細取得失敗時に demo fallback していないか
mini map / marker / timer / subscriber が増殖しない設計か
```

---

## 静的確認

### JS構文確認

変更された JS と E2E を `node --check` する。

例:

```bash
node --check frontend/js/live-stream/live-stream-earthquake-detail.js
node --check frontend/js/live-stream/live-stream-earthquake-mini-map.js
node --check frontend/js/live-stream/live-stream-panel-playback.js
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-runtime.js
node --check e2e/live-stream-earthquake-detail.spec.js
```

実際のファイル名に合わせて実行すること。

### Python構文確認

backend に変更がある場合のみ実施。

```bash
python -m compileall backend
```

backend 変更がない場合は、その旨をレポートに明記する。

---

## Docker / HTTP確認

```bash
docker compose ps
```

必要に応じて:

```bash
docker compose up -d
```

以下が `200 OK` で返ること。

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

---

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
  e2e/live-stream-stability.spec.js \
  e2e/live-stream-earthquake-detail.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

既存テスト構成に合わせて読み替えてよい。

---

## 必須検証観点

### 1. 市区町村震度リスト表示

Playwright route mock または既存 mock を使い、P2P 市区町村震度を持つ地震 event を返す。

確認:

```text
左上の地震子画面にメイン震源カードが表示される
その下に市区町村震度リストが表示される
リスト内容が対象 event id と一致する
別の地震 event の市区町村震度が混ざらない
```

DOM属性例:

```text
data-earthquake-detail-event-id
data-eq-intensity-list
data-eq-intensity-row
data-eq-intensity
data-pref
data-city
```

実装名に合わせて確認すること。

---

### 2. 並び順

震度が混在する mock を用意する。

期待:

```text
震度7
震度6強
震度6弱
震度5強
震度5弱
震度4
震度3
震度2
震度1
```

のように高震度順で表示される。

同震度内の都道府県・市区町村順は実装仕様に従い、レポートに明記する。

---

### 3. 座標あり/なしの扱い

mock に以下を混ぜる。

```text
座標あり市区町村
座標なし市区町村
lat null
lng null
不正座標
日本周辺外の座標
```

期待:

```text
座標あり市区町村は小地図 marker になる
座標なし市区町村はリストには出る
座標なし/不正座標は marker にならない
JS error なし
古い marker が残らない
```

---

### 4. 小地図震度マーカー

確認:

```text
小地図に市区町村震度 marker が表示される
marker が地図を隠しすぎない
marker の震度 class / label が確認できる
marker 数が座標あり市区町村数と整合する
```

DOM属性例:

```text
data-eq-intensity-marker
data-intensity
data-event-id
```

Leaflet の場合は DOM / diagnostics / marker count のいずれかで確認してよい。

---

### 5. 多数市区町村時の自動スクロール

多数の市区町村震度 mock を用意する。

期待:

```text
リストが複数行表示される
表示領域から溢れる場合に自動スクロールする
全行が一度は表示される設計になっている
scroll progress / scroll state が diagnostics または DOM で確認できる
```

DOM属性例:

```text
data-eq-intensity-scroll-mode="static|scrolling"
data-eq-intensity-scroll-progress
```

---

### 6. スクロール完了まで切替ロック

複数の地震 event を用意する。

期待:

```text
1件目の市区町村震度リストがスクロール中は、地震子画面の対象が2件目へ切り替わらない
スクロール完了後に次の地震/次の focus へ進める
対象 event が消えた場合は hold が解除される
hold が永久に残らない
```

確認属性例:

```text
body[data-stream-panel-hold="earthquake-detail"]
body[data-stream-panel-hold-event-id]
data-earthquake-detail-event-id
```

---

### 7. 広域震度時の小地図 tour

広域の市区町村震度 mock を用意する。

例:

```text
北海道
東北
関東
中部
関西
```

期待:

```text
小地図が単に全体縮小で潰れるだけにならない
複数 frame / tour で震度範囲を表示する
frame index / total が確認できる
全 frame 表示完了まで地震子画面対象が切り替わらない
```

確認属性例:

```text
data-eq-mini-map-mode="fit|tour"
data-eq-mini-map-frame-index
data-eq-mini-map-frame-total
```

---

### 8. P2P詳細なし

地震 event はあるが、市区町村震度詳細がないケース。

期待:

```text
地震子画面は破綻しない
「詳細取得中」「詳細なし」「一時的に取得不可」などの表示になる
小地図 marker は 0
古い市区町村震度リストが残らない
demo fallback しない
```

---

### 9. API失敗 / 不正JSON / timeout

以下を検証する。

```text
P2P詳細 API 500
P2P詳細 API 404
不正JSON
timeout相当
```

期待:

```text
JS pageerror なし
unhandledrejection なし
地震パネル表示維持
古い detail が別 event に誤表示されない
demo fallback しない
Runtime degraded/error の既存挙動を壊さない
```

---

### 10. state=calm

```text
/live/stream?state=calm
```

期待:

```text
市区町村震度リストなし
小地図震度 marker なし
hold なし
calm 表示維持
```

---

### 11. demo=1

```text
/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test
```

期待:

```text
demo 地震 event の市区町村震度リストが表示される
demo 小地図 marker が表示される
demo でも同じ detail pipeline を通る
hold / scroll / mini map tour が確認できる
本番 fetch と混ざらない
```

---

### 12. Phase 5-A stability 回帰

Phase 5-Aで確認した安定性が壊れていないこと。

確認:

```text
marker が更新ごとに増殖しない
ticker DOM が増殖しない
panel DOM が増殖しない
mini map marker が増殖しない
timer が多重起動しない
subscriber が増殖しない
in-flight guard が維持される
```

`window.__LiveStreamDiagnostics.getSnapshot()` がある場合は、以下も確認する。

```text
earthquakeDetail.activeEventId
earthquakeDetail.municipalCount
earthquakeDetail.markerCount
earthquakeDetail.missingCoordinateCount
earthquakeDetail.scrollMode
earthquakeDetail.miniMapMode
earthquakeDetail.miniMapFrameIndex
earthquakeDetail.miniMapFrameTotal
earthquakeDetail.holdActive
```

---

### 13. 地図操作不可の維持

メイン地図および小地図が操作不可であること。

確認:

```text
ズームUIなし
ドラッグ不可
ホイールズーム不可
ダブルクリックズーム不可
キーボード操作不可
```

小地図に Leaflet を使っている場合も同様。

---

### 14. `/live` 通常画面への副作用確認

通常 `/live` を開き、最低限以下を確認する。

```text
HTTP 200
pageerror なし
通常地図表示あり
既存パネル表示あり
既存レイヤー操作が大きく壊れていない
```

可能であれば既存代表E2Eも実行する。

---

## 手動ブラウザ確認

以下のスクリーンショットを取得する。

```bash
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 http://127.0.0.1:8080/live/stream test-results/live-stream-phase5a1-earthquake-detail-normal-1920.png

npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" test-results/live-stream-phase5a1-earthquake-detail-calm-1920.png

npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test&chrome=off" test-results/live-stream-phase5a1-earthquake-detail-demo-1920.png
```

必要なら、広域震度 tour 用の追加スクリーンショットを保存する。

```text
test-results/live-stream-phase5a1-earthquake-detail-wide-tour-1920.png
```

目視確認:

```text
市区町村震度リストが読める
震度ラベルが分かる
小地図 marker が小さく、地図を潰していない
広域時に小地図の巡回が分かる
スクロールが速すぎない
左右パネルやテロップを邪魔していない
```

---

## 検証レポート作成

以下に作成する。

```text
tasks/live/live_stream_phase5a1_earthquake_detail_codex_verification.md
```

構成例:

```md
# live stream Phase 5-A.1 earthquake detail verification

## Result

PASS / PASS with notes / FAIL

## Summary

## Checked files

## Environment

## Commands

## Test results

## Diagnostics snapshot

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
地震子画面に対象地震の市区町村震度リストが表示される
市区町村震度が対象 event id と紐づいている
小地図に市区町村震度 marker が表示される
座標なし/不正座標は marker 化されない
多数市区町村時に自動スクロールする
スクロール完了まで表示対象が切り替わらない
広域震度時に小地図 tour または同等の巡回表示がある
小地図巡回完了まで表示対象が切り替わらない
P2P詳細なし/失敗/timeoutで pageerror なし
通常モードで demo fallback しない
Phase 5-A の安定性対策が回帰していない
通常 /live に明確な副作用がない
関連E2Eが PASS
```

---

## PASS with notes 条件

以下は PASS with notes 可。

```text
市区町村震度の座標が一部欠落し、リストのみ表示される
広域 tour の分割が簡易実装
非常に多数の市区町村では最大表示時間の上限により全件完全表示ではなく代表巡回になる
小地図は既存装飾地図への overlay であり、詳細な地形/行政界は出ない
P2P詳細が存在しない地震では「詳細なし」表示になる
```

---

## FAIL条件

以下はいずれも FAIL。

```text
/live/stream が表示できない
地震子画面で JS pageerror が出る
市区町村震度が別の地震 event に誤表示される
詳細取得失敗時に demo データへ fallback する
スクロール中に表示対象が勝手に切り替わる
小地図 marker が更新のたびに増殖する
hold が永久に残る
state=calm で震度詳細や marker が出る
通常 /live が壊れる
```

---

## 最終判断

検証完了後、以下を明記する。

```text
PASS
PASS with notes
FAIL
```

PASS with notes の場合は、後続フェーズで対応すべき残課題を具体的に列挙すること。

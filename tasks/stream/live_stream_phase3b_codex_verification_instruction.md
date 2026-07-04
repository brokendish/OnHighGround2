# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 3-B：メイン地図 本番データ連動 MVP 検証

## 目的

Claude実装後、`/live/stream` の中央メイン地図が本番データ連動になっていることを検証する。

重要なのは、単にマーカーが出ることではない。

以下を確認する。

```text
本番API由来のデータで表示される
通常表示で demo marker に逃げていない
データなし/失敗時に破綻しない
地図操作不可が維持される
通常 /live に副作用がない
```

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
node --check frontend/js/live/stream/live-stream-data-source.js
node --check frontend/js/live/stream/live-stream-main-map-events.js
node --check frontend/js/live/stream/live-stream-main-map.js
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
demo data が通常表示の fallback になっていないか
fetch 失敗時に未捕捉例外が出ないか
setInterval が多重起動しないか
マーカーが更新のたびに増殖しないか
表示件数に上限があるか
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
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

実際に存在するURLに合わせて確認する。

`/live/stream` と `/live/stream.html` の両方をサポートしている場合は両方確認する。

---

## E2E検証

### 推奨実行

```bash
npx playwright test e2e/live-stream.spec.js e2e/live-stream-main-map.spec.js e2e/live-stream-main-map-real-data.spec.js
```

既存の関連テストがある場合は合わせて実行する。

例:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

---

## 必須検証観点

### 1. 本番データ相当でマーカー表示

Playwright route mock を使い、既存APIに本番相当レスポンスを返す。

確認:

```text
地震マーカーが表示される
豪雨/キキクル代表マーカーが表示される
鉄道影響マーカーが表示される
表示件数が上限内
```

DOM class 例:

```text
.stream-map-event--earthquake
.stream-map-event--rain
.stream-map-event--kikikuru
.stream-map-event--railway
```

実装 class 名に合わせて確認すること。

---

### 2. demo marker に逃げていないこと

通常アクセス:

```text
/live/stream
```

確認:

```text
demo 専用 marker が出ていない
本番API mock の内容に応じて marker が出る
API空レスポンス時に demo marker が勝手に出ない
API失敗時に demo marker が勝手に出ない
```

demo mode:

```text
/live/stream?demo=1
```

確認:

```text
demo marker が表示される
本番 fetch と混ざらない
```

calm mode:

```text
/live/stream?calm=1
```

確認:

```text
本番 marker も demo marker も出ない
画面は破綻しない
```

---

### 3. 空データ

API が空データを返すケースを検証する。

期待:

```text
JS error なし
メイン地図表示維持
マーカー 0件
画面崩れなし
demo marker への fallback なし
```

---

### 4. API失敗

以下を検証する。

```text
500
404
timeout相当
不正JSON
```

期待:

```text
JS error なし
unhandledrejection なし
地図表示維持
demo marker に fallback しない
```

Playwright で以下を監視する。

```js
page.on('pageerror', ...)
page.on('console', ...)
```

console error が実害あるものなら FAIL。

---

### 5. 座標不正データ

以下のようなデータを混ぜる。

```text
lat null
lng null
lat が文字列
lng が NaN
座標なし
日本周辺から大きく外れた座標
同一 id の重複
```

期待:

```text
該当データは marker 化されない
他の正常データは表示される
JS error なし
マーカーが重複しない
```

---

### 6. stale データ

古いデータを返す。

期待:

```text
仕様通り除外される
または stale class 付きで弱表示される
```

どちらの仕様で実装されたかをレポートに明記する。

---

### 7. 地図操作不可の維持

Phase 3-A の重要仕様が壊れていないこと。

確認:

```text
ズームUIがない
ドラッグで地図が動かない
ホイールでズームしない
ダブルクリックでズームしない
キーボード操作で動かない
```

---

### 8. attribution 表示

OSM / CARTO / Leaflet attribution が表示されていること。

確認:

```text
OpenStreetMap
CARTO
Leaflet
```

実際の表記に合わせる。

---

### 9. `/live` 通常画面への副作用確認

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
中央地図に本番データ由来 marker が表示される
表示が多すぎない
左右パネルを邪魔しない
下部テロップを邪魔しない
地図が暗すぎ/明るすぎで marker が見えない状態になっていない
通常アクセス時に demo marker ではない
```

スクリーンショット保存例:

```text
test-results/live-stream-phase3b-main-map-real-data-1920.png
```

---

## 検証レポート作成

以下にレポートを作成する。

```text
tasks/live/live_stream_phase3b_main_map_real_data_codex_verification.md
```

レポート構成:

```md
# live stream Phase 3-B main map real data verification

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
本番データ相当のAPIレスポンスで marker が表示される
通常アクセス時に demo marker へ fallback しない
空データ/失敗/不正座標で JS error にならない
地図操作不可が維持される
OSM attribution が表示される
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
通常アクセス時に demo marker だけで成功扱いしている
API失敗時に画面が破綻する
JS pageerror / unhandledrejection が出る
地図操作不可が解除されている
通常 /live が壊れている
marker が更新のたびに増殖する
マーカー表示数に上限がない
```

---

## PASS with notes 条件

以下は PASS with notes 可。

```text
潮位・水位は座標/異常判定不足で Phase 3-B 対象外
豪雨/キキクルは代表座標があるものだけ表示
鉄道は代表点のみで路線形状なし
一部APIが未設定時 unavailable だが画面破綻なし
stale 判定が簡易実装
```

---

## 最終判断

検証完了後、以下を明記する。

```text
PASS
FAIL
PASS with notes
```

また、PASS with notes の場合は、後続フェーズで対応すべき残課題を具体的に列挙すること。

今回の検証で特に重視するのは以下。

```text
本番データ連動になっていること
demo marker に逃げていないこと
配信画面として落ちないこと
通常 /live を壊していないこと
```

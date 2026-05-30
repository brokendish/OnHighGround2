# Phase 4-A 潮位観測点レイヤー MVP 検証

## 目的

Phase 4-A 実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

- /live
- 潮位観測点レイヤー
- 潮位API
- 潮位ポップアップ
- 潮位グラフ
- レイヤー切替

---

## 検証項目

### 1. 構文確認

実施:

python -m compileall backend/app

node --check frontend/js/live/*.js

確認:

- SyntaxErrorなし
- ImportErrorなし
- JS構文エラーなし

---

### 2. Docker起動確認

実施:

docker compose build

docker compose up -d

確認:

- backend healthy
- frontend healthy
- martin healthy

---

### 3. API確認

#### 観測点一覧

GET /api/live/tide/stations

確認:

- HTTP 200
- stations配列あり
- 観測点数取得可能

---

#### 観測点詳細

GET /api/live/tide/stations/{id}

確認:

- HTTP 200
- current_tide
- extremes
- series

取得可能

---

### 4. レイヤー表示確認

確認:

レイヤー一覧に

「潮位観測点」

が表示されること。

---

### 5. ON/OFF確認

確認:

- ONで表示
- OFFで非表示
- 再ONで復帰

---

### 6. マーカー確認

確認:

- 全国観測点表示
- 重複なし
- JSエラーなし

---

### 7. ポップアップ確認

確認:

- 観測点名
- 現在潮位
- 満潮
- 干潮

表示されること。

---

### 8. グラフ確認

確認:

- 描画成功
- 時系列表示
- Console Errorなし

---

### 9. 回帰確認

実施:

pytest

npx playwright test e2e/live-basic.spec.js

git diff --check

確認:

- pytest成功
- Playwright成功
- git diff --check OK

---

### 10. ナビ本体影響確認

確認:

- / 表示可能
- ナビ動作正常
- JSエラーなし

---

## レポート

作成先:

tasks/live/live_phase4a_tide_layer_mvp_codex_verification.md

記載内容:

- 実施日時
- Docker状態
- API確認結果
- 観測点数
- レイヤー確認
- ポップアップ確認
- グラフ確認
- 回帰確認
- ナビ本体影響確認
- スクリーンショット
- 最終判定

判定:

- PASS
- PASS with notes
- FAIL
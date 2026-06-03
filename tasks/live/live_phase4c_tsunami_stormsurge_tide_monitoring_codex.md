# Phase 4-C 津波・高潮・潮位監視表示 検証

## 目的

Phase 4-C 実装内容を検証する。

実装修正は禁止。

調査・検証・レポート作成のみ実施すること。

---

## 検証対象

- 津波レイヤー
- 高潮レイヤー
- 情報パネル
- dangerous_areas
- レイヤー切替
- 回帰影響

---

# 1. 構文確認

実施:

python3 -m compileall backend/app

node --check frontend/js/live/*.js

確認:

- SyntaxErrorなし
- ImportErrorなし
- JS構文エラーなし

---

# 2. Docker起動確認

実施:

docker compose build
docker compose up -d
docker compose ps

確認:

- backend healthy
- frontend Up
- martin healthy

---

# 3. 津波確認

確認対象:

/api/live/summary

確認:

- tsunami status
- tsunami areas

取得可能

---

## UI確認

確認:

- 津波レイヤー表示
- ON/OFF動作
- 海岸線表示

---

## 情報パネル

確認:

- 津波警報あり
- 津波注意報あり

表示可能

---

# 4. 高潮確認

確認対象:

/api/live/summary

確認:

- storm_surge status
- storm_surge areas

取得可能

---

## UI確認

確認:

- 高潮レイヤー表示
- ON/OFF動作

---

## 情報パネル

確認:

- 高潮警報あり
- 高潮注意報あり

表示可能

---

# 5. dangerous_areas確認

確認:

- 津波が反映される
- 高潮が反映される

優先順位確認:

津波 > 高潮 > キキクル > 雨雲

---

# 6. Console確認

確認:

- console errorなし
- page errorなし

---

# 7. 回帰確認

実施:

git diff --check

実施:

npx playwright test e2e/live-basic.spec.js
npx playwright test e2e/live-earthquake-layer.spec.js
npx playwright test e2e/live-sun-moon-card.spec.js
npx playwright test e2e/live-tide-layer.spec.js

追加E2Eがある場合は実施。

---

# 8. ナビ本体影響確認

URL:

http://127.0.0.1:8080/

確認:

- 正常表示
- console errorなし
- page errorなし

---

# レポート

作成先:

tasks/live/live_phase4c_tsunami_stormsurge_tide_monitoring_codex_verification.md

記載内容:

- 実施日時
- Docker状態
- 津波確認
- 高潮確認
- dangerous_areas確認
- Console確認
- 回帰確認
- ナビ本体影響確認
- スクリーンショット
- 最終判定

判定:

PASS
PASS with notes
FAIL
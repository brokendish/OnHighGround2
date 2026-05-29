# /live Phase 2-C 地域ブロック代表点 受入検証レポート

検証日: 2026-05-29 (JST)  
対象: 作業ツリー上の `/live Phase 2-C 地域ブロック代表点化`  
判定: **PASS with notes**

## 判定概要

- `LIVE_RAIN_SAMPLE_POINTS` は総数 76 件。
- `kind=prefecture_capital` は 47 件、`kind=regional` は 29 件。
- `kind` は全地点で `prefecture_capital` / `regional` のいずれか。
- `id` 重複なし、座標重複なし。
- 実 API `/api/live/summary` は `rain.summary.sample_count=76` を返した。
- false-safe 防止は期待通り。`unknown_count>=38` かつ warning/danger なしで `evaluated=false`、warning ありでは unknown が多数でも `evaluated=true`。
- `rain.areas` は最大 5 件、danger が warning より優先される。
- TTL は 120 秒、timeout は 30 秒、並列数は 8。
- `/live` E2E は **44 passed**、backend test は **41 passed** と **21 passed**、既存ナビ代表 E2E は **44 passed**。
- 禁止対象の既存ナビファイルに差分はなく、live から navigation/state/reroute/OSRM への依存追加はない。

## 実施方針

指示書に従い、実装修正は行わず検証とレポート作成のみ実施した。

## 実施コマンド

```bash
sed -n '1,240p' docs/live/DEVELOPMENT_GUARDRAILS.md
sed -n '1,560p' 'tasks/live/live Phase 2-C_雨雲サンプリング地域ブロック代表点化_CODEX .md'
git status --short
git diff --name-only HEAD
git ls-files --others --exclude-standard
git diff -- frontend/index.html frontend/js/navigation.js frontend/js/state.js frontend/js/hazard-layers.js frontend/js/location-info-panel.js
rg -n -i "navigation\.js|state\.js|location-info-panel|reroute|osrm|nav-[A-Za-z0-9_-]*\.js" frontend/js/live frontend/live.html frontend/css/live e2e/live-basic.spec.js backend/app/services/live_* backend/app/api/live_* nginx.conf
venv/bin/python -c "... LIVE_RAIN_SAMPLE_POINTS summary ..."
venv/bin/python -c "... false-safe and areas checks ..."
venv/bin/pytest tests/test_live_rain_summary_service.py
venv/bin/pytest tests/test_live_summary_api.py
npx playwright test e2e/live-basic.spec.js
npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
docker compose build
docker compose up -d
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/live.html
curl -s http://127.0.0.1:8000/api/live/summary
node /private/tmp/phase2c_screenshots.js
docker compose ps
git diff --check
```

## Sample Count 確認

確認コマンド結果:

```text
total 76
kind_counts {'prefecture_capital': 47, 'regional': 29}
missing_kind []
duplicate_coords 0
duplicate_ids 0
ttl 120.0
max_workers 8
timeout 30.0
max_areas 5
```

結果:

- 総数 76: PASS。
- 都道府県代表点 47: PASS。
- 地域ブロック代表点 29: PASS。
- `kind` 全地点あり: PASS。
- `kind` 値は `prefecture_capital` / `regional`: PASS。
- 重複座標なし: PASS。
- id 重複なし: PASS。
- 明らかな県外誤配置は、地点名・都道府県・緯度経度の目視確認範囲では検出なし。

## API 確認結果

実行:

```bash
curl -s http://127.0.0.1:8000/api/live/summary
```

rain レスポンス抜粋:

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_nowcast",
  "summary": {
    "strong_rain_detected": false,
    "warning_area_count": 0,
    "danger_area_count": 0,
    "sample_count": 76,
    "unknown_count": 0
  },
  "areas": []
}
```

結果:

- `rain.status`: `ok`
- `rain.evaluated`: `true`
- `rain.reason`: `sampled_nowcast`
- `rain.summary.sample_count`: `76`
- `rain.summary.unknown_count`: `0`

## False-Safe 確認

純粋ロジック確認:

```text
caseA unknown False too_many_unknown_samples {'strong_rain_detected': None, 'warning_area_count': None, 'danger_area_count': None, 'sample_count': 76, 'unknown_count': 38}
caseB ok True {'strong_rain_detected': True, 'warning_area_count': 1, 'danger_area_count': 0, 'sample_count': 76, 'unknown_count': 60} 1
```

結果:

- ケースA: warning/danger なし、`unknown_count=38` で `evaluated=false`: PASS。
- ケースB: warning あり、`unknown_count=60` でも `evaluated=true`: PASS。
- `evaluated=false` 時に `strong_rain_detected=false` としない: PASS。

## Areas 件数 / 優先順位

純粋ロジック確認:

```text
areas_case 5 ['danger', 'danger', 'danger', 'danger', 'danger'] {'strong_rain_detected': True, 'warning_area_count': 7, 'danger_area_count': 7, 'sample_count': 76, 'unknown_count': 0}
```

結果:

- `rain.areas` 最大 5 件: PASS。
- danger が warning より優先: PASS。
- summary の warning/danger count は areas 上限前の検出数を反映: PASS。

## Timeout / 並列数 / TTL

`backend/app/services/live_rain_summary_service.py` で確認:

- `_TOTAL_SAMPLING_TIMEOUT = 30.0`: PASS。
- `_MAX_WORKERS = 8`: PASS。
- `_CACHE_TTL = 120.0`: PASS。
- timeout 時は未完了地点を `unknown` として扱う: PASS。

## Backend Test

実行:

```bash
venv/bin/pytest tests/test_live_rain_summary_service.py
venv/bin/pytest tests/test_live_summary_api.py
```

結果:

- `tests/test_live_rain_summary_service.py`: **41 passed**
- `tests/test_live_summary_api.py`: **21 passed**

## E2E 結果

実行:

```bash
npx playwright test e2e/live-basic.spec.js
```

結果:

- `/live` E2E: **44 passed**

確認された内容:

- 地図表示。
- JS console error なし。
- カード表示。
- レイヤー切替動作。
- rain evaluated=false で `強雨域なし` を表示しない。
- rain offline で `雨雲情報: 取得失敗` を表示。
- API 503 時も map 操作継続、レイヤー切替継続、page error なし。

## 既存ナビ回帰

実行:

```bash
npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

結果:

- 既存ナビ代表 E2E: **44 passed**

## Docker / HTTP

実行:

```bash
docker compose build
docker compose up -d
docker compose ps
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/live.html
```

結果:

- backend healthy。
- frontend running。
- martin healthy。
- `/`: HTTP 200。
- `/live`: HTTP 200。
- `/live.html`: HTTP 200。

## 禁止事項確認

禁止ファイル差分:

- `frontend/index.html`: 差分なし。
- `frontend/js/navigation.js`: 差分なし。
- `frontend/js/state.js`: 差分なし。
- `frontend/js/hazard-layers.js`: 差分なし。
- `frontend/js/location-info-panel.js`: 差分なし。
- `frontend/js/nav-*`: 差分なし。

依存関係:

- live 側から `navigation.js` / `state.js` / `reroute` / OSRM への依存追加なし。
- `nginx.conf` の OSRM ヒットは既存 proxy 設定のみ。
- live JS のヒットは「依存しない」旨のコメント/README のみ。

## スクリーンショット

保存済み:

- `tasks/live/verification_screenshots/phase2c-live-normal.png`
- `tasks/live/verification_screenshots/phase2c-live-rain-warning.png`
- `tasks/live/verification_screenshots/phase2c-live-rain-offline.png`
- `tasks/live/verification_screenshots/phase2c-navigation-root.png`

通常画面と `/` は Docker 実配信で撮影。rain warning と rain offline は Playwright route mock で撮影した。

## 問題点 / Notes

- 実天候では強雨なしだったため、強雨ランキング表示は mock で確認した。
- Phase 2-C 指示書は「実装修正禁止」だったため、既存の作業ツリー差分を検証対象として扱い、実装ファイル・テストファイルの編集は行っていない。
- `e2e/live-basic.spec.js` 内の追加 describe 名は Phase 2-B のままだが、実 API と backend test では Phase 2-C の 76 地点契約を確認済み。

# /live Phase 2-B 雨雲サンプリング精度改善 受入検証レポート

検証日: 2026-05-29 (JST)  
対象: 作業ツリー上の `/live Phase 2-B 雨雲サンプリング精度改善`  
判定: **PASS with notes**

## 判定概要

- 雨雲サンプリング地点は 47 都道府県代表点になり、各地点に `id` / `label` / `prefecture` / `lat` / `lng` が定義されている。
- `/api/live/summary.rain.summary.sample_count` は実 API で `47` を返した。
- TTL は `120.0` 秒、並列数は `8`、取得詰まり防止の全体 sampling timeout と未完了地点の `unknown` 化を確認した。
- `unknown >= 50%` かつ warning/danger なしの場合は `evaluated=false`, `strong_rain_detected=null`, `reason=too_many_unknown_samples` になり、false-safe を避ける。
- `unknown` が多くても warning/danger がある場合は `evaluated=true`, `strong_rain_detected=true` を維持する。
- rain `areas` は最大 5 件で、`danger` が `warning` より優先される。
- backend test は **35 passed** と **21 passed**、`/live` E2E は **44 passed**、既存ナビ代表 E2E は **44 passed**。
- 禁止対象の既存ナビファイルに差分はなく、live から navigation/state/reroute/OSRM への依存追加はない。

## 実装確認

対象ファイル:

- `backend/app/services/live_rain_summary_service.py`
- `tests/test_live_rain_summary_service.py`
- `e2e/live-basic.spec.js`

`backend/app/services/live_rain_summary_service.py` で確認した内容:

- `LIVE_RAIN_SAMPLE_POINTS` は 47 件。
- 全地点に `id`, `label`, `prefecture`, `lat`, `lng` がある。
- `id` 重複なし。
- `_CACHE_TTL = 120.0`。
- `_MAX_WORKERS = 8`。
- `_TOTAL_SAMPLING_TIMEOUT = 24.0`。
- `_MAX_AREAS = 5`。
- `ThreadPoolExecutor(max_workers=_MAX_WORKERS)` で並列数を制限。
- `as_completed(..., timeout=_TOTAL_SAMPLING_TIMEOUT)` と `executor.shutdown(wait=False, cancel_futures=True)` により、未完了サンプルで処理全体が詰まり続けない。
- timeout / exception の地点は `intensity=unknown`, `rain_class=-1` として扱う。
- `severe -> danger`, `strong -> warning`, `moderate -> watch`。公開 `areas` に入るのは warning/danger のみ。
- `areas` は danger 優先で最大 5 件。
- source failure は `status=offline`, `evaluated=false`, `strong_rain_detected=null`, `sample_count=47`。

## 静的確認

実行:

```bash
git diff --name-only HEAD
git ls-files --others --exclude-standard
git diff -- frontend/index.html frontend/js/navigation.js frontend/js/state.js frontend/js/hazard-layers.js frontend/js/location-info-panel.js
rg -n -i "navigation\.js|state\.js|location-info-panel|reroute|osrm|nav-[A-Za-z0-9_-]*\.js" frontend/js/live frontend/live.html frontend/css/live e2e/live-basic.spec.js backend/app/services/live_* backend/app/api/live_* nginx.conf
git diff --check
```

結果:

- tracked 差分は `backend/app/services/live_rain_summary_service.py`, `tests/test_live_rain_summary_service.py`, `e2e/live-basic.spec.js` のみ。
- untracked は Phase 2-B 指示書 2 件と本レポートのみ。
- 禁止対象ファイルへの差分なし。
- 禁止依存検索の live 側ヒットは「依存しない」旨のコメント/README のみ。
- `nginx.conf` の OSRM ヒットは既存 proxy 設定のみ。
- `git diff --check` PASS。

## 構文チェック

実行:

```bash
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-main.js
node --check frontend/js/live/live-danger-summary.js
node --check e2e/live-basic.spec.js
```

結果: 全 PASS。

## Backend Test

実行:

```bash
venv/bin/pytest tests/test_live_rain_summary_service.py
venv/bin/pytest tests/test_live_summary_api.py
```

結果:

- `tests/test_live_rain_summary_service.py`: **35 passed**
- `tests/test_live_summary_api.py`: **21 passed**

指示書の想定は rain summary service **33 passed** だったが、今回 `max_workers` と per-sample timeout の確認を追加したため 35 件になった。

## Docker / HTTP 確認

実行:

```bash
docker compose build
docker compose up -d
docker compose ps
curl -s http://127.0.0.1:8000/health
curl -I http://127.0.0.1:8080/
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/live.html
curl -s http://127.0.0.1:8000/api/live/summary
```

結果:

- Docker build PASS。
- backend healthy。
- frontend running。
- martin healthy。
- `/`, `/live`, `/live.html` は HTTP 200。
- `/api/live/summary` は HTTP 200。

実 API の rain レスポンス抜粋:

```json
{
  "status": "ok",
  "evaluated": true,
  "reason": "sampled_nowcast",
  "summary": {
    "strong_rain_detected": false,
    "warning_area_count": 0,
    "danger_area_count": 0,
    "sample_count": 47,
    "unknown_count": 0
  },
  "areas": []
}
```

## False-Safe 確認

unit test で確認:

- `unknown >= 50%` かつ warning/danger なし: `evaluated=false`, `strong_rain_detected=null`, `reason=too_many_unknown_samples`。
- `unknown >= 50%` でも `strong` あり: `evaluated=true`, `strong_rain_detected=true`。
- `unknown >= 50%` でも `severe` あり: `evaluated=true`, `strong_rain_detected=true`。
- 空サンプル/source failure 相当: `status=offline`, `evaluated=false`, `strong_rain_detected=null`。
- `evaluated=false` のとき `strong_rain_detected=false` にならない。

frontend E2E で確認:

- rain `evaluated=false` で `強雨域なし` を表示しない。
- rain `offline` で `雨雲情報: 取得失敗` を表示する。
- rain `offline` で `安全` と断定しない。

## Level / Areas 確認

unit test と実装確認:

- `severe -> danger`。
- `strong -> warning`。
- `moderate -> watch` だが危険地域 `areas` には入らない。
- `weak` / `none` は `areas` に入らない。
- `areas` は最大 5 件。
- summary の `warning_area_count` / `danger_area_count` は、5 件上限適用前の全検出数を反映する。
- danger が warning より前に並ぶ。

`/live` E2E で確認:

- 複数 rain areas でもカード表示が崩れない。
- rain areas が複数地点出ても危険地域カードは 5 件以内に収まる。

## E2E 結果

実行:

```bash
npx playwright test e2e/live-basic.spec.js
npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

結果:

- `/live` E2E: **44 passed**
- 既存ナビ代表 E2E: **44 passed**

## スクリーンショット

保存済み:

- `tasks/live/verification_screenshots/phase2b-live-normal.png`
- `tasks/live/verification_screenshots/phase2b-live-rain-warning-multiple.png`
- `tasks/live/verification_screenshots/phase2b-live-rain-offline.png`
- `tasks/live/verification_screenshots/phase2b-navigation-root.png`

通常画面と `/` は Docker 実配信で撮影。rain warning 複数と rain offline は Playwright route mock で撮影した。

## 既存ナビへの影響

確認範囲では **影響なし**。

- `frontend/index.html`, `frontend/js/navigation.js`, `frontend/js/state.js`, `frontend/js/nav-*.js`, `frontend/js/hazard-layers.js`, `frontend/js/location-info-panel.js` に差分なし。
- 既存 reroute / bottom panel 関連への変更なし。
- live から navigation/state/reroute/OSRM への依存追加なし。
- `/` HTTP 200。
- 既存ナビ代表 E2E **44 passed**。

## Notes / 改善提案

- 実天候では強雨なしだったため、複数 warning/danger 表示は mock で確認した。
- 47 都道府県代表点は 11 地点より取り逃しを減らす軽量改善だが、狭い局地的強雨を必ず拾うものではない。
- 将来さらに精度を上げる場合も、全国メッシュ全解析ではなく、軽量性を維持できる追加代表点または地域別重点点の導入がよい。

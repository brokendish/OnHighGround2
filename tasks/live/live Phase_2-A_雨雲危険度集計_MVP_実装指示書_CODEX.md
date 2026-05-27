````md
# /live Phase 2-A 雨雲危険度集計 MVP 受入検証指示書（CODEX向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md
- tasks/live/live_phase1b_danger_cards_codex_verification.md
- tests/test_live_summary_api.py
- tests/test_live_rain_summary_service.py

今回の検証目的は、Phase 2-A で追加された雨雲危険度集計 MVP が、`/live` の summary 契約を壊さず、false-safe を起こさず、既存避難ナビに副作用を出していないことを確認することである。

---

# 検証対象

## 新規

- backend/app/services/live_rain_summary_service.py
- tests/test_live_rain_summary_service.py

## 変更

- backend/app/services/live_summary_service.py
- tests/test_live_summary_api.py
- e2e/live-basic.spec.js
- frontend/js/live/live-alert-panel.js
- 必要に応じて live 関連ファイル

---

# 絶対確認事項

以下が改変されていないこと。

- frontend/index.html
- frontend/js/navigation.js
- frontend/js/state.js
- frontend/js/nav-*.js
- frontend/js/hazard-layers.js
- frontend/js/location-info-panel.js
- 既存 reroute 関連
- 既存 bottom panel 関連

live から以下へ依存追加がないこと。

- navigation.js
- state.js
- reroute
- OSRM

---

# 1. 静的確認

## 差分範囲

```bash
git diff --name-only HEAD
git ls-files --others --exclude-standard
````

確認:

* live / backend live_summary / tests / e2e の範囲に収まっていること
* 禁止ファイルに差分がないこと

---

## 禁止依存チェック

```bash
rg -n -i "navigation\.js|state\.js|location-info-panel|reroute|osrm|nav-[A-Za-z0-9_-]*\.js" frontend/js/live frontend/live.html frontend/css/live e2e/live-basic.spec.js backend/app/services/live_* backend/app/api/live_* nginx.conf
```

期待:

* live 側・live summary 側に navigation/state/reroute/OSRM 依存なし
* nginx.conf の既存 OSRM proxy は既存差分なら notes 扱い

---

# 2. 構文チェック

```bash
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-main.js
node --check frontend/js/live/live-danger-summary.js
```

期待: 全 PASS。

---

# 3. backend test

```bash
pytest tests/test_live_rain_summary_service.py
pytest tests/test_live_summary_api.py
```

期待:

```text
test_live_rain_summary_service.py: 24 passed
test_live_summary_api.py: 21 passed
```

実件数が異なる場合は理由を記録する。

---

# 4. Docker / HTTP 確認

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

確認:

* backend healthy
* frontend running
* martin healthy
* `/`, `/live`, `/live.html` HTTP 200
* `/api/live/summary` が 200
* `rain` セクションが存在する
* `rain.evaluated` が boolean
* `rain.summary.strong_rain_detected` が契約通り

---

# 5. /api/live/summary 契約確認

`/api/live/summary` の rain セクションを確認する。

## 必須項目

```json
{
  "rain": {
    "status": "ok|offline|stale|unknown",
    "evaluated": true,
    "reason": "sampled_nowcast",
    "summary": {
      "strong_rain_detected": true,
      "warning_area_count": 1,
      "danger_area_count": 0,
      "sample_count": 11,
      "unknown_count": 0
    },
    "areas": []
  }
}
```

実際の天候により `evaluated=false` や `offline` になる可能性はあるため、以下を厳密に確認する。

## false-safe 防止

### evaluated=false の場合

* `strong_rain_detected` は `null`
* `強雨域なし` と断定しない
* reason があること

  * `too_many_unknown_samples`
  * `source_unavailable`
  * `tile_only`
  * その他妥当な理由

### status=offline の場合

* `evaluated=false`
* `strong_rain_detected=null`
* frontend は `雨雲情報: 取得失敗` 等を表示

### evaluated=true の場合

* `strong_rain_detected` は boolean
* `sample_count > 0`
* `unknown_count / sample_count < 0.5`
* areas の level は契約値内

  * `watch`
  * `warning`
  * `danger`
  * `normal`
  * `unknown`

---

# 6. 雨雲危険度集計ロジック確認

以下を確認する。

* 全国 11 地点サンプリングであること
* TTL 120秒キャッシュがあること
* `strong` → `warning`
* `severe` → `danger`
* `moderate` → `watch`
* `warning` / `danger` は dangerous_areas に追加
* `watch` は dangerous_areas に追加しない
* unknown が 50%以上なら `evaluated=false`
* JMA / source failure 時は `status=offline`
* 判定不能を `strong_rain_detected=false` にしない

---

# 7. /live E2E

```bash
npx playwright test e2e/live-basic.spec.js
```

期待:

```text
38 passed
```

確認観点:

* rain evaluated=true + false で `強雨域なし`
* rain evaluated=true + true で `強雨域あり`
* rain danger/warning area が危険地域ランキングに入る
* rain evaluated=false では `強雨域なし` を表示しない
* rain offline では取得失敗表示
* page error / unhandled rejection なし
* map 操作継続

---

# 8. 既存ナビ代表 E2E

```bash
npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

期待:

```text
44 passed
```

実件数が異なる場合は理由を記録する。

---

# 9. 実画面確認

スクリーンショットを保存する。

```text
tasks/live/verification_screenshots/phase2a-live-normal.png
tasks/live/verification_screenshots/phase2a-live-rain-warning.png
tasks/live/verification_screenshots/phase2a-live-rain-offline.png
tasks/live/verification_screenshots/phase2a-navigation-root.png
```

確認:

* 通常表示
* rain warning / danger mock
* rain offline
* 既存 `/` ナビ画面

---

# 10. 判定基準

## PASS

以下をすべて満たす。

* backend rain summary test PASS
* live summary API test PASS
* `/api/live/summary.rain` が契約を満たす
* evaluated=false / offline で false-safe しない
* strong/severe が warning/danger として扱われる
* dangerous_areas に rain warning/danger が入る
* `/live` E2E PASS
* 既存ナビ代表 E2E PASS
* 禁止ファイル未変更
* navigation/state/reroute/OSRM 依存追加なし

## PASS with notes

以下のような軽微な注記のみの場合。

* 実天候が強雨なしで、実配信画面では rain warning を mock のみで確認
* 11地点サンプリングは MVP のため網羅性に限界あり
* ブラウザ由来の failed resource console があるがアプリ page error はない

## FAIL

以下のいずれかがある場合。

* false-safe 表示が復活
* evaluated=false で `strong_rain_detected=false`
* source failure が `強雨域なし` になる
* `/live` E2E FAIL
* backend pytest FAIL
* 既存ナビ E2E FAIL
* 禁止ファイル差分あり
* navigation/state/reroute/OSRM 依存追加

---

# 11. 検証レポート

以下に作成すること。

```text
tasks/live/live_phase2a_rain_summary_codex_verification.md
```

記載内容:

* 判定
* 実行コマンド
* 結果
* `/api/live/summary.rain` 契約確認
* false-safe 確認
* 雨雲危険度集計ロジック確認
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 既存ナビへの影響有無
* スクリーンショット保存先
* notes / 改善提案

---

# 最重要メッセージ

今回の検証で最も重要なのは、強雨を検出できることだけではない。

最重要は以下。

```text
判定不能・取得失敗を「強雨なし」と表示しないこと
```

これが守られている限り、Phase 2-A は MVP として成立する。

```
```

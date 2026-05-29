もちろんです。CODEXにはこれで投げてください。

````md
# /live Phase 2-B 雨雲サンプリング精度改善 受入検証指示書（CODEX向け）

## 最重要

作業前に必ず以下を読むこと。

- AGENTS.md
- CLAUDE.md
- docs/live/DEVELOPMENT_GUARDRAILS.md
- frontend/js/live/README.md
- tasks/live/live_mvp_codex_verification.md
- tasks/live/live_phase1b_danger_cards_codex_verification.md
- tasks/live/live_phase2a_rain_summary_codex_verification.md
- tests/test_live_rain_summary_service.py
- tests/test_live_summary_api.py

今回の検証目的は、Phase 2-B で追加された雨雲サンプリング精度改善が、軽量性・契約・false-safe 防止・既存ナビ非干渉を満たしているか確認すること。

---

# 検証対象

## 主な変更対象

- backend/app/services/live_rain_summary_service.py
- tests/test_live_rain_summary_service.py
- e2e/live-basic.spec.js

必要に応じて以下も確認する。

- backend/app/services/live_summary_service.py
- tests/test_live_summary_api.py
- frontend/js/live/live-alert-panel.js
- frontend/js/live/live-danger-summary.js

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

* Phase 2-B の変更が live rain summary / live E2E / tests の範囲に収まっていること
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
test_live_rain_summary_service.py: 33 passed
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
* `rain.summary.sample_count` が原則 47
* `rain.evaluated` が boolean
* `rain.summary.strong_rain_detected` が契約通り

---

# 5. 雨雲サンプリング仕様確認

`backend/app/services/live_rain_summary_service.py` を確認する。

## 必須確認

* サンプル地点が 47都道府県分ある
* 各地点に以下がある

  * id
  * label
  * prefecture
  * lat
  * lng
* id が重複していない
* sample_count は原則 47
* TTL は 120秒
* 並列数制限がある

  * 例: max_workers=8
* timeout または外部取得詰まり防止がある
* areas 最大件数が 5件
* danger > warning の優先順で areas が制限される

---

# 6. false-safe 確認

以下を重点的に確認する。

## unknown 過多

```text
unknown >= 50%
かつ
warning/danger なし
```

期待:

```text
evaluated=false
strong_rain_detected=null
reason=too_many_unknown_samples
```

## unknown が混じるが warning/danger あり

期待:

```text
evaluated=true
strong_rain_detected=true
```

理由:

```text
一部 unknown でも危険検出は表示する
```

## source failure

期待:

```text
status=offline
evaluated=false
strong_rain_detected=null
sample_count=47
```

## prohibited

以下は禁止。

```text
unknown / failure を strong_rain_detected=false にする
取得失敗を 強雨域なし と表示する
```

---

# 7. level / areas 確認

確認:

* severe → danger
* strong → warning
* moderate → watch
* weak / none → normal 相当
* watch は dangerous_areas に入らない
* warning / danger のみ areas に入る
* areas は最大5件
* dangerous_areas への rain 追加も最大5件相当
* danger が warning より優先される

---

# 8. /live E2E

```bash
npx playwright test e2e/live-basic.spec.js
```

期待:

```text
44 passed
```

確認観点:

* rain warning mock で危険地域に雨雲が出る
* 複数 rain areas でもカードが崩れない
* areas 最大5件制限
* rain evaluated=false で `強雨域なし` を表示しない
* rain offline で `雨雲情報: 取得失敗`
* page error / unhandled rejection なし

---

# 9. 既存ナビ代表 E2E

```bash
npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js
```

期待:

```text
44 passed
```

実件数が異なる場合は理由を記録する。

---

# 10. 実画面確認

スクリーンショットを保存する。

```text
tasks/live/verification_screenshots/phase2b-live-normal.png
tasks/live/verification_screenshots/phase2b-live-rain-warning-multiple.png
tasks/live/verification_screenshots/phase2b-live-rain-offline.png
tasks/live/verification_screenshots/phase2b-navigation-root.png
```

確認:

* 通常表示
* rain warning 複数 mock
* rain offline
* 既存 `/` ナビ画面

---

# 11. 判定基準

## PASS

以下をすべて満たす。

* backend rain summary test PASS
* summary API test PASS
* `/api/live/summary.rain.summary.sample_count` が原則 47
* 47都道府県代表点が定義されている
* TTL 120秒
* 並列数制限 / timeout がある
* areas 最大5件
* danger > warning 優先
* unknown / failure で false-safe しない
* warning/danger 検出時は unknown 混在でも strong_rain_detected=true
* `/live` E2E PASS
* 既存ナビ代表 E2E PASS
* 禁止ファイル未変更
* navigation/state/reroute/OSRM 依存追加なし

## PASS with notes

以下のような軽微な注記のみの場合。

* 実天候では強雨なしで、複数 warning 表示は mock 確認
* 47地点代表点でも狭い局地的強雨は取り逃す可能性あり
* per-sample timeout が内部関数依存で明示値ではないが全体 timeout がある
* ブラウザ由来の failed resource console があるが page error はない

## FAIL

以下のいずれかがある場合。

* false-safe 表示が復活
* unknown / failure が `strong_rain_detected=false`
* source failure が `強雨域なし`
* sample_count が意図なく 47 未満
* areas 上限なし
* `/live` E2E FAIL
* backend pytest FAIL
* 既存ナビ E2E FAIL
* 禁止ファイル差分あり
* navigation/state/reroute/OSRM 依存追加

---

# 12. 検証レポート

以下に作成すること。

```text
tasks/live/live_phase2b_rain_sampling_codex_verification.md
```

記載内容:

* 判定
* 実行コマンド
* 結果
* 47地点サンプリング確認
* TTL / 並列数 / timeout 確認
* false-safe 確認
* areas 上限確認
* `/api/live/summary.rain` 契約確認
* `/live` E2E 結果
* 既存ナビ代表 E2E 結果
* 既存ナビへの影響有無
* スクリーンショット保存先
* notes / 改善提案

---

# 最重要メッセージ

Phase 2-B の目的は、重い全国解析ではない。

最重要は以下。

```text
軽量性を維持しつつ、11地点より取り逃しを減らすこと
```

そして、これまで同様に、

```text
判定不能・取得失敗を「強雨なし」と表示しないこと
```

を必ず守ること。

```
```

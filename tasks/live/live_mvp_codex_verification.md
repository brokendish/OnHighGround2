# /live MVP 回帰検証レポート

検証日: 2026-05-26 (JST)  
対象: 作業ツリー上の `/live` MVP 実装および `nginx.conf` 変更  
判定: **FAIL**

## 判定理由

- `/live` と `/live.html` は Docker frontend 経由で HTTP 200、`/` も HTTP 200 のまま維持された。
- 禁止対象の既存ナビファイルに作業ツリー差分はなく、live JS から `navigation.js` / `state.js` / reroute / OSRM への実依存も確認されなかった。
- 既存ナビ代表 E2E は 44 件すべて PASS した。
- ただし必須条件である `npx playwright test e2e/live-basic.spec.js` が 13 件中 2 件 FAIL した。
- API 503 を模擬した実画面 probe では画面操作は継続したが、雨雲・地震・津波の status dot がすべて正常色のままになった。

## 必須文書確認

確認済み:

- `AGENTS.md`
- `CLAUDE.md`
- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `frontend/js/live/README.md`

## 静的確認

### 差分範囲

`git diff --name-only HEAD` で tracked 差分は以下のみ:

- `e2e/live-basic.spec.js`
- `nginx.conf`

`git ls-files --others --exclude-standard` で実装対象の新規ファイルを確認:

- `frontend/live.html`
- `frontend/css/live/live.css`
- `frontend/js/live/live-map.js`
- `frontend/js/live/live-layers.js`
- `frontend/js/live/live-alert-panel.js`
- `frontend/js/live/live-ui.js`
- `frontend/js/live/live-main.js`

### 禁止ファイル未変更

以下に対する `git diff` は空であり、live 実装の混入は確認されなかった:

- `frontend/index.html`
- `frontend/js/navigation.js`
- `frontend/js/nav-*.js`
- `frontend/js/hazard-layers.js`
- `frontend/js/location-info-panel.js`
- 既存 reroute 関連
- 既存 bottom panel 関連

### 禁止依存チェック

実行:

```bash
rg -n -i "navigation\.js|state\.js|location-info-panel|reroute|osrm|nav-[A-Za-z0-9_-]*\.js" frontend/js/live frontend/live.html frontend/css/live e2e/live-basic.spec.js nginx.conf
```

結果:

- `frontend/js/live/` のヒットは「依存しない」旨のコメントおよび README のみ。
- `nginx.conf` の OSRM ヒットは既存ナビ向け既存 proxy ブロックのみ。
- live HTML がロードするアプリ JS は `/js/live/*.js` のみ。
- live のための OSRM / reroute / navigation state 依存追加なし。

### nginx 差分

`nginx.conf` の変更は `/live` を `live.html` に解決する `location /live` ブロック追加のみ。既存の `/`, `/api/`, `/osrm/walking/`, tile 関連 location に差分なし。

## 実行コマンドと結果

| 確認 | コマンド | 結果 |
| --- | --- | --- |
| JS 構文 | `node --check frontend/js/live/live-map.js` | PASS |
| JS 構文 | `node --check frontend/js/live/live-layers.js` | PASS |
| JS 構文 | `node --check frontend/js/live/live-alert-panel.js` | PASS |
| JS 構文 | `node --check frontend/js/live/live-ui.js` | PASS |
| JS 構文 | `node --check frontend/js/live/live-main.js` | PASS |
| Docker build | `docker compose build` | PASS |
| Docker 起動 | `docker compose up -d` | PASS |
| Docker 状態 | `docker compose ps` | PASS: backend healthy, frontend running, martin healthy, osrm-walking running |
| Backend health | `curl -s http://127.0.0.1:8000/health` | PASS: `"status":"healthy"` |
| 従来 root | `curl -I http://127.0.0.1:8080/` | PASS: HTTP 200 |
| live route | `curl -I http://127.0.0.1:8080/live` | PASS: HTTP 200 |
| live html | `curl -I http://127.0.0.1:8080/live.html` | PASS: HTTP 200 |
| live E2E | `npx playwright test e2e/live-basic.spec.js` | **FAIL: 11 passed, 2 failed** |
| 既存ナビ代表 E2E | `npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js` | PASS: 44 passed |
| 実画面 / 失敗耐性 probe | `node /private/tmp/live_mvp_visual_probe.js` | 部分 PASS: 通常時正常、API 503 時も map 操作継続。ただし status 表示不正確 |

指定された既存代表 spec は 4 件とも存在し、すべて実行した。存在しないためスキップした spec はない。

## /live 実画面確認

通常 API mock による Docker 配信画面の probe 結果:

- ダークテーマ、警戒カード、レイヤー UI、ステータスバーを表示。
- `#live-map` 自体に `leaflet-container` class が付き、Leaflet が初期化された。
- 初期地図中心は `lat=36.5`, `lng=137`, zoom `5` で、日本全体表示の設定を確認。
- rain / kikikuru / earthquake / tsunami toggle を ON/OFF 操作して page error / console error なし。

既存 `/` の Docker 配信画面も取得し、タイトルは `避難ナビゲーション OnHighGround - 津波・高潮・洪水対策`。既存 UI の機能回帰は代表 E2E 44 件 PASS で確認した。

## 失敗・注意点

### 1. `live-basic` が Leaflet 初期化を誤った selector で待機する

該当箇所:

- `e2e/live-basic.spec.js:110`
- `e2e/live-basic.spec.js:143`

現状は `#live-map .leaflet-container` を待機しているが、Leaflet は `#live-map` 要素自身へ `leaflet-container` class を付与する。実画面 probe では `#live-map.leaflet-container` を確認済みで、ページ初期化は動作している。

影響:

- `Leaflet マップが初期化されている` が FAIL。
- `地震トグル OFF でマーカーが非表示になる` は操作前の同一 wait で FAIL。
- PASS 条件の `live-basic E2E が通る` を満たさない。

修正提案:

- 両 locator を `#live-map.leaflet-container` に変更し、E2E を再実行する。
- 地震 OFF 検査は circle marker の実表示有無を直接確認できる assertion に補強する。

### 2. API 失敗時にも status dot が正常色になる

該当箇所:

- `frontend/js/live/live-main.js:13-22`
- `frontend/js/live/live-layers.js:23-50`
- `frontend/js/live/live-layers.js:185-220`

`rain.refresh()` / `earthquake.refresh()` / `tsunami.refresh()` は HTTP 非成功や取得例外を reject せず正常 return するため、`Promise.allSettled()` は失敗時も `fulfilled` と判定する。API を 503 にした probe で status dot の class は 3 件とも `live-status-dot` のままで、offline 表示にならなかった。

影響:

- API 失敗でも画面と map 操作は継続し、JS 例外による破綻はなかった。
- しかしデータ未取得を正常稼働として表示するため、災害ビューアの状態表示として誤解を招く。
- 意図的な 503 応答時はブラウザの resource load console error も記録された。

修正提案:

- 各 refresh が `{ ok, data }` 等の結果を返し、status は取得成否で描画する。
- または取得失敗を reject させ、カードの degraded 表示と status 判定を分離する。
- empty / none / stale / error を区別する E2E を追加する。

## スクリーンショット保存先

- `tasks/live/verification_screenshots/live-success.png`
- `tasks/live/verification_screenshots/live-api-failure.png`
- `tasks/live/verification_screenshots/navigation-root.png`

## 既存ナビへの影響

確認範囲では **影響なし**。

- 禁止ファイルへの差分なし。
- `/` の HTTP 200 を維持。
- 既存ナビ代表 E2E 44 件 PASS。
- `nginx.conf` の差分は `/live` 追加だけであり、既存 API / tiles / OSRM location の変更なし。

## 結論

`/live` ページそのものは Docker 配信で表示・操作でき、既存避難ナビ本体の回帰は検出されなかった。一方、必須 E2E が selector 不備で失敗しており、API 失敗表示にも改善が必要であるため、現時点の受入判定は **FAIL** とする。

---

## FAIL 修正後 再検証 (2026-05-26 JST)

再検証判定: **FAIL**

### 概要

前回指摘のうち、以下は修正を確認した。

- `e2e/live-basic.spec.js` の Leaflet locator は `#live-map.leaflet-container` に変更され、`13 passed` となった。
- API 503 初期表示時、雨雲・地震・津波の status dot はすべて `offline` class となった。

ただし、API 失敗状態で雨雲トグルを OFF から ON に戻すと、`[live-rain] HTTP 503` の未処理 page error が発生した。API 失敗時のレイヤートグル継続と error-free 条件を満たさないため、判定は **FAIL** とする。

### 再実行結果

| 確認 | コマンド | 結果 |
| --- | --- | --- |
| 必須文書 | `sed -n ... AGENTS.md CLAUDE.md docs/live/DEVELOPMENT_GUARDRAILS.md frontend/js/live/README.md` | PASS: 再確認済み |
| JS 構文 | `node --check frontend/js/live/live-map.js` ほか live JS 5 本 | PASS |
| 禁止依存 | `rg -n -i "navigation\\.js\|state\\.js\|location-info-panel\|reroute\|osrm\|nav-..." frontend/js/live frontend/live.html frontend/css/live e2e/live-basic.spec.js nginx.conf` | PASS: live 側は否定コメントのみ。OSRM は既存 nginx proxy のみ |
| 禁止ファイル差分 | `git diff -- frontend/index.html frontend/js/navigation.js frontend/js/nav-forward-warning.js frontend/js/nav-bottom-sheet.js frontend/js/hazard-layers.js frontend/js/location-info-panel.js 'frontend/js/*reroute*' 'frontend/js/*bottom*panel*' 'frontend/js/*bottom*sheet*'` | PASS: 差分なし |
| nginx 差分 | `git diff -- nginx.conf` | PASS: `/live` 配信用 location 追加のみ |
| Docker / HTTP | `docker compose ps`; `curl -I http://127.0.0.1:8080/`; `curl -I http://127.0.0.1:8080/live`; `curl -I http://127.0.0.1:8080/live.html` | PASS: backend healthy / frontend running / martin healthy / osrm-walking running、3 URL とも HTTP 200 |
| `/live` E2E | `npx playwright test e2e/live-basic.spec.js` | PASS: **13 passed** |
| 既存ナビ代表 E2E | `npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js` | PASS: **44 passed** |
| API 失敗時 probe | `node /private/tmp/live_mvp_visual_probe.js` | **FAIL**: offline 表示と map 継続は PASS、雨雲トグル再 ON で page error |

補足: 既存ナビ代表 E2E は最初に `/live` E2E と並列起動した際、両者の local test server が `127.0.0.1:8787` を使用して `EADDRINUSE` となったため、単独で再実行し `44 passed` を確認した。

### API 失敗時の確認結果

API 503 を返す probe で確認した内容:

- `#live-map.leaflet-container` は維持され、map の pan 操作は継続できた。
- status dot は `live-status-dot offline` が 3 件となり、前回の誤った正常色表示は解消した。
- `toggle-kikikuru` / `toggle-earthquake` / `toggle-tsunami` の操作後も画面は維持された。
- `toggle-rain` を OFF から ON に戻すと、page error に `[live-rain] HTTP 503` が記録された。
- 503 応答自体に伴うブラウザ console resource errors も記録された。

### 残存不具合

該当箇所:

- `frontend/js/live/live-layers.js:49-53`

`_rainSetVisible(true)` が `_rainRefresh()` の reject を await / catch せずに呼び出すため、雨雲 API が失敗している最中にトグルを再度 ON にすると未処理 rejection になる。初期ロードおよび定期更新の失敗処理は改善されているが、UI 操作経路が未処理のままである。

修正提案:

- `_rainSetVisible()` から呼ぶ `_rainRefresh()` に `.catch(...)` を付け、`liveUI.updateRainStatus(false)` と警告表示を行う。
- または toggle handler を async 化し、refresh 失敗を UI レイヤーで処理する。
- API failure 下で rain OFF/ON を操作し、page error / application console error が発生せず offline のままであることを E2E に追加する。

### 再検証スクリーンショット

以下を再取得済み:

- `tasks/live/verification_screenshots/live-success.png`
- `tasks/live/verification_screenshots/live-api-failure.png`
- `tasks/live/verification_screenshots/navigation-root.png`

### 既存ナビへの影響

再検証範囲では **影響なし**。

- 禁止ファイル差分なし。
- live から既存 navigation/state/reroute/OSRM 依存なし。
- `/` は HTTP 200。
- 既存ナビ代表 E2E は 44 passed。
- `nginx.conf` 差分は `/live` 配信追加のみ。

---

## 最終再検証 (2026-05-26 JST)

最終判定: **PASS with notes**

### 判定概要

雨雲トグル OFF→ON 経路の reject 処理修正後、要求された機能確認と既存ナビ回帰確認はすべて通過した。

- `/live` E2E は API 失敗耐性 3 件を含む **16 passed**。
- API 503 状態で rain OFF→ON を操作しても application page error は発生しない。
- API 503 状態で status dot は雨雲・地震・津波すべて `offline` のまま。
- API 503 状態でも map 操作は継続できる。
- 通常動作で application `console.error` は発生しない。
- 既存ナビ代表 E2E は **44 passed**。
- 禁止ファイル、禁止依存、nginx 差分の境界違反は確認されなかった。

注記: API failure probe で意図的に HTTP 503 を返したリクエストについては、Chromium が `Failed to load resource: the server responded with a status of 503` を console error 種別で記録する。アプリケーションコードによる `console.error` および未処理 rejection / page error は検出されなかったため、障害耐性の受入を妨げる実装不具合とは扱わず **PASS with notes** とした。

### 最終実行結果

| 確認 | コマンド | 結果 |
| --- | --- | --- |
| 必須文書 | `AGENTS.md`, `CLAUDE.md`, `docs/live/DEVELOPMENT_GUARDRAILS.md`, `frontend/js/live/README.md` を再読 | PASS |
| JS / E2E 構文 | `node --check frontend/js/live/live-map.js` ほか live JS 5 本および `e2e/live-basic.spec.js` | PASS |
| 禁止依存 | `rg -n -i "navigation\\.js\\|state\\.js\\|location-info-panel\\|reroute\\|osrm\\|nav-..." frontend/js/live frontend/live.html frontend/css/live e2e/live-basic.spec.js nginx.conf` | PASS: live 側のヒットは否定コメントのみ。OSRM は既存 nginx proxy のみ |
| 禁止ファイル差分 | `git diff -- frontend/index.html frontend/js/navigation.js frontend/js/nav-forward-warning.js frontend/js/nav-bottom-sheet.js frontend/js/hazard-layers.js frontend/js/location-info-panel.js 'frontend/js/*reroute*' 'frontend/js/*bottom*panel*' 'frontend/js/*bottom*sheet*'` | PASS: 差分なし |
| nginx 差分 | `git diff -- nginx.conf` | PASS: `/live` 配信用 `location /live` 追加のみ |
| Docker / HTTP | `docker compose ps`; `curl -I http://127.0.0.1:8080/`; `curl -I http://127.0.0.1:8080/live`; `curl -I http://127.0.0.1:8080/live.html`; `curl -s http://127.0.0.1:8000/health` | PASS: backend healthy / frontend running / martin healthy / osrm-walking running、3 URL HTTP 200 |
| `/live` E2E | `npx playwright test e2e/live-basic.spec.js` | PASS: **16 passed** |
| API failure 実配信 probe | `node /private/tmp/live_mvp_visual_probe.js` | PASS with notes: `pageErrors: []`, status dot 3 件 `offline`, map 継続。意図的 503 の browser resource messages あり |
| 既存ナビ代表 E2E | `npx playwright test e2e/info-tab-card-ui.spec.js e2e/weather-rain-radar-card.spec.js e2e/tide-sun-moon-timeline.spec.js e2e/simulation-mode.spec.js` | PASS: **44 passed** |

### 修正確認

前回残存していた `frontend/js/live/live-layers.js` の雨雲トグル経路は、`_rainRefresh()` の rejection を `.catch(...)` で処理し、失敗時に `liveUI.updateRainStatus(false)` を呼ぶ実装へ変更された。これにより API 503 中の rain OFF→ON で未処理 rejection が発生しないことを確認した。

`e2e/live-basic.spec.js` には以下の API failure テストが追加され、いずれも PASS した。

- rain OFF→ON で page error が発生しない。
- status dot が offline になる。
- map 操作が継続できる。

### 最終スクリーンショット

再取得済み:

- `tasks/live/verification_screenshots/live-success.png`
- `tasks/live/verification_screenshots/live-api-failure.png`
- `tasks/live/verification_screenshots/navigation-root.png`

### 既存避難ナビ本体への影響

最終再検証範囲では **影響なし**。

- 既存ナビ禁止ファイルへの差分なし。
- live の実装は既存 navigation/state/reroute/OSRM に依存しない。
- nginx の既存 `/`, `/api/`, tiles, OSRM 配信設定に変更なし。
- `/` 配信は HTTP 200。
- 既存ナビ代表 E2E は 44 passed。

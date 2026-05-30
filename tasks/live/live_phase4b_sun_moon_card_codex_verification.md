# Phase 4-B 日月情報カード 検証レポート

## 実施日時

- 2026-05-30 22:13-22:25 JST
- 再確認: 2026-05-30 22:33 JST

## 最終判定

**PASS with notes**（2026-05-30 22:33 JST 再確認後）

Claude 修正により、`live-basic.spec.js` に `/api/live/sun-moon` mock が追加され、初回 FAIL の原因だった 404 console error は解消した。

残る notes:

- 標準 Playwright config のままではローカルの既存 8787 番サーバーと競合し、開始前に `EADDRINUSE` で失敗する。この環境要因を避けるため、既存 8787 サーバーを利用する一時 config で同一 4 スイートを再実行した。
- API 503 失敗時テストでは、意図した 503 に対するブラウザ標準 resource error は console に出る。JS 例外や page error はない。

## 初回判定

**FAIL**

理由:

- 日月 API、実ブラウザでの日月情報カード表示、API 失敗時表示、ナビ本体への非干渉は確認できた。
- ただし指定回帰の `npx playwright test e2e/live-basic.spec.js` が失敗した。
- 失敗理由は `/live.html` に追加された `/api/live/sun-moon` 呼び出しが `live-basic.spec.js` 側で mock されておらず、静的 E2E サーバー上で 404 となり、複数の console error 監視テストが落ちるため。

## 1. 構文確認

実行:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-tide-layer.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-sun-moon-card.js
node --check frontend/js/live/live-danger-summary.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-main.js
node --check frontend/js/live/live-mobile.js
```

結果:

- PASS
- Python SyntaxError なし。
- JS 構文エラーなし。

## 2. Docker 状態

実行:

```bash
docker compose build
docker compose up -d
docker compose ps
```

結果:

- `backend`: Up / healthy
- `frontend`: Up
- `martin`: Up / healthy
- `osrm-walking`: Up

確認時の状態:

```text
evacuation-navi-backend   Up 3 minutes (healthy)  0.0.0.0:8000->8000/tcp
evacuation-navi-frontend  Up 38 minutes           0.0.0.0:8080->80/tcp
evacuation-navi-martin    Up 38 minutes (healthy)
evacuation-navi-osrm-walking Up 38 minutes        0.0.0.0:5501->5001/tcp
```

補足:

- frontend は compose 上で healthcheck 表示なしのため `healthy` ではなく `Up` として確認。

## 3. API 結果

実行:

```bash
curl -i http://127.0.0.1:8000/api/live/sun-moon
```

結果:

- PASS
- HTTP 200
- `sunrise`, `sunset`, `moonrise`, `moonset`, `moon_phase` あり。

レスポンス:

```json
{
  "location": "東京",
  "date": "2026-05-30",
  "sunrise": "04:27",
  "sunset": "18:49",
  "moonrise": "18:06",
  "moonset": "03:09",
  "moon_phase": 13.3,
  "moon_phase_name": "十三夜"
}
```

## 4. カード表示結果

実ブラウザ確認:

- URL: `http://127.0.0.1:8080/live.html`

結果:

- PASS
- `#live-sun-moon-card` 表示あり。
- `#live-sun-moon-body` 表示あり。
- レイアウト崩れは確認されず。

実測:

- card visible: true
- row count: 5
- body box: `x=1313, y=262, width=100, height=113`

## 5. 表示内容確認

確認結果:

- `日の出`: 表示あり、値 `04:27`
- `日の入り`: 表示あり、値 `18:49`
- `月の出`: 表示あり、値 `18:06`
- `月の入り`: 表示あり、値 `03:09`
- `月齢`: 表示あり、値 `13.3`
- 月相名: `十三夜`
- 空欄または `--` の値: なし

実ブラウザ text:

```text
日の出04:27日の入り18:49月の出18:06月の入り03:09月齢13.3十三夜
```

結果:

- PASS

## 6. API 失敗時確認

確認方法:

- Playwright route で `/api/live/sun-moon` に HTTP 503 を返す。

結果:

- `取得できません` 表示あり。
- page error なし。
- リクエスト回数: 1 回。
- 無限リトライなし。
- `live sun moon load failed: HTTP 503` の warning あり。

補足:

- ブラウザ標準の resource error として `Failed to load resource: the server responded with a status of 503` が console error に記録された。
- JS 例外は発生していない。

## 7. Console 確認

通常表示:

- console error: 0 件
- page error: 0 件
- log: `live sun moon loaded`

API 失敗時:

- page error: 0 件
- JS 例外なし。
- 503 によるブラウザ標準 resource error は 1 件。

結果:

- PASS with notes

## 8. 回帰確認結果

### git diff check

実行:

```bash
git diff --check
```

結果:

- PASS

### Playwright live-basic

指定コマンド:

```bash
npx playwright test e2e/live-basic.spec.js
```

結果:

- FAIL
- `Error: listen EADDRINUSE: address already in use 127.0.0.1:8787`

追加確認:

- 既存 8787 サーバーを利用する一時 config `/private/tmp/playwright-live-existing-server.config.js` で実行。

```bash
npx playwright test e2e/live-basic.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- FAIL
- 58 passed / 6 failed

失敗テスト:

- `/live Phase 1-B — 危険地域カード強化 › Phase 1-B: console.error / page error が発生しない`
- `/live Phase 2-A — 雨雲危険度集計 › Phase 2-A: console.error / page error が発生しない`
- `/live Phase 2-B — 雨雲サンプリング精度改善 › Phase 2-B: console.error / page error が発生しない`
- `/live Phase 3-A — キキクル危険度集計 › Phase 3-A: console.error / page error が発生しない`
- `/live Phase 3-B — キキクル複数種別 › Phase 3-B: console.error / page error が発生しない`
- `/live Phase 2-D — 雨雲面スキャン方式 › Phase 2-D: console.error / page error が発生しない`

共通エラー:

```text
Failed to load resource: the server responded with a status of 404 (Not Found)
```

原因メモ:

- `live-basic.spec.js` は `/api/live/sun-moon` を mock していない。
- `/live.html` 読み込み時に `live-sun-moon-card.js` が自動で `/api/live/sun-moon` を fetch する。
- 静的 E2E サーバーでは該当 API が存在しないため 404 になり、console error 監視テストが失敗している。

### Playwright live-tide-layer

実行:

```bash
npx playwright test e2e/live-tide-layer.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- PASS
- 13 passed

### Playwright live-sun-moon-card

追加確認:

```bash
npx playwright test e2e/live-sun-moon-card.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- PASS
- 15 passed

## 9. ナビ本体影響確認

実ブラウザ確認:

- URL: `http://127.0.0.1:8080/`

結果:

- PASS
- HTTP 200
- map visible: true
- `/api/live/sun-moon` 自動リクエスト: 0 件
- console error: 0 件
- page error: 0 件

## スクリーンショット

- `/private/tmp/live-phase4b-sun-moon-card.png`
  - `/live.html` で日月情報カード表示。
- `/private/tmp/live-phase4b-sun-moon-error.png`
  - `/api/live/sun-moon` 503 時に `取得できません` 表示。
- `/private/tmp/live-phase4b-nav-root.png`
  - `/` ナビ本体表示確認。

## 総括

Phase 4-B の実装機能としては、日月 API と `/live` カード表示は成立している。

ただし既存 `live-basic.spec.js` が新 API を mock しておらず、追加カードの自動 fetch が 404 console error を発生させるため、指定回帰確認を満たしていない。

したがって初回判定は **FAIL**。

---

## 再確認（Claude 修正後）

### 実施日時

- 2026-05-30 22:33 JST

### 修正内容の確認

確認:

- `e2e/live-basic.spec.js` に `SUN_MOON_RESPONSE` 定数が追加されている。
- `mockLiveTraffic()` に `/api/live/sun-moon` mock が追加されている。
- `mockLiveTrafficWith()` に `/api/live/sun-moon` mock が追加されている。
- `mockLiveTrafficWithSummary()` は `mockLiveTrafficWith()` 経由でカバーされる。

結果:

- PASS

### 構文・API・Docker 再確認

実行:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/live-sun-moon-card.js
node --check e2e/live-basic.spec.js
docker compose ps
curl -i http://127.0.0.1:8000/api/live/sun-moon
```

結果:

- compileall: PASS
- JS check: PASS
- E2E spec syntax: PASS
- backend: Up / healthy
- frontend: Up
- martin: Up / healthy
- `/api/live/sun-moon`: HTTP 200

API レスポンス:

```json
{
  "location": "東京",
  "date": "2026-05-30",
  "sunrise": "04:27",
  "sunset": "18:49",
  "moonrise": "18:06",
  "moonset": "03:09",
  "moon_phase": 13.3,
  "moon_phase_name": "十三夜"
}
```

### 実ブラウザ再確認

確認 URL:

- `http://127.0.0.1:8080/live.html`
- `http://127.0.0.1:8080/`

結果:

- 日月情報カード表示: PASS
- 表示項目: `日の出`, `日の入り`, `月の出`, `月の入り`, `月齢`
- 値の空欄なし。
- 通常表示の console error: 0 件
- 通常表示の page error: 0 件
- API 503 時: `取得できません` 表示、リクエスト 1 回、無限リトライなし、page error なし。
- `/` ナビ本体: HTTP 200、map visible、`/api/live/sun-moon` 自動リクエスト 0 件、console error 0 件。

実ブラウザ text:

```text
日の出04:27日の入り18:49月の出18:06月の入り03:09月齢13.3十三夜
```

### 回帰再確認

指定に近い標準コマンド:

```bash
npx playwright test e2e/live-basic.spec.js e2e/live-sun-moon-card.spec.js e2e/live-tide-layer.spec.js e2e/live-entry-button.spec.js
```

結果:

- FAIL
- `Error: listen EADDRINUSE: address already in use 127.0.0.1:8787`
- テスト実行前のローカル環境要因。

既存 8787 サーバー利用 config で再実行:

```bash
npx playwright test e2e/live-basic.spec.js e2e/live-sun-moon-card.spec.js e2e/live-tide-layer.spec.js e2e/live-entry-button.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- PASS
- 98 passed
- 内訳:
  - `live-basic`: 64 passed
  - `live-sun-moon-card`: 15 passed
  - `live-tide-layer`: 13 passed
  - `live-entry-button`: 6 passed

追加:

```bash
git diff --check
```

結果:

- PASS

### 再確認総括

初回 FAIL の原因だった `live-basic.spec.js` の `/api/live/sun-moon` 未 mock は解消済み。

機能本体、実ブラウザ、日月カード専用 E2E、既存 live 回帰 E2E の観点で Phase 4-B は成立している。

最終判定は **PASS with notes**。

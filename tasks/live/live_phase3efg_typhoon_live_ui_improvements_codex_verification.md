# Phase 3-EFG 台風時ライブ監視 UI 改善 検証レポート

## 実施日時

- 2026-06-02 00:37 JST
- 再確認: 2026-06-02 00:47 JST

## 最終判定

**PASS with notes**（Claude修正後再確認）

再確認結果:

- 前回 FAIL の原因だった「地震一覧項目クリック後に Leaflet popup が表示されない」問題は解消。
- 実ブラウザで地震一覧クリック後、地図フォーカスと `.leaflet-popup` 表示を確認。
- 追加 E2E を含む関連 Playwright 112 件は PASS。
- console error / page error、ナビ本体非干渉、雨雲 opacity、キキクル mock 表示も再確認済み。

初回判定（履歴）:

- E: キキクル危険地域カード整合、G: 雨雲レイヤー opacity、回帰 E2E、ナビ本体非干渉は確認できた。
- F: 地震一覧は表示され、一覧クリックで地図フォーカスもできた。
- ただし、タスク完了条件にある「地震一覧タップで地図フォーカスできる」に加え、検証項目の「ポップアップ表示」まで確認したところ、実ブラウザでは一覧クリック後に Leaflet popup が表示されなかった。
- 修正前 E2E は地図中心と zoom のみを確認しており、ポップアップ未表示を検出していなかった。

## 1. 構文確認

実行:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-layers.js
node --check e2e/live-basic.spec.js
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
evacuation-navi-backend   Up About a minute (healthy)  0.0.0.0:8000->8000/tcp
evacuation-navi-frontend  Up 2 days                    0.0.0.0:8080->80/tcp
evacuation-navi-martin    Up 2 days (healthy)
evacuation-navi-osrm-walking Up 2 days                 0.0.0.0:5501->5001/tcp
```

補足:

- frontend は compose 上で healthcheck 表示なしのため `healthy` ではなく `Up` として確認。

## 3. E: キキクル整合性確認

API:

```bash
curl -s http://127.0.0.1:8000/api/live/summary
```

実データ結果:

- `kikikuru.status`: `ok`
- `kikikuru.evaluated`: `true`
- `kikikuru.summary.danger_detected`: `false`
- `kikikuru.summary.watch_area_count`: 1
- `kikikuru.summary.warning_area_count`: 0
- `kikikuru.summary.danger_area_count`: 0
- `kikikuru.areas`: 0 件
- `dangerous_areas`: 5 件、すべて `type: rain`

判定:

- PASS with notes

Notes:

- 検証時点の実データでは、沖縄・奄美などのキキクル warning / danger は再現していない。
- `kikikuru.areas` が 0 件で、`dangerous_areas` に kikikuru が入っていないため、実データ上の不整合はなし。
- mock summary で `kikikuru.areas` と `dangerous_areas` に沖縄・奄美を入れたケースでは、カードに「キキクル危険地域あり」と危険地域リストが表示された。

mock UI 確認 text:

```text
キキクル危険地域あり
沖縄県付近
キキクル（土砂）
奄美付近
キキクル（浸水）
```

false-safe 確認:

- 実データでは unknown/unavailable は danger 扱いされていない。
- `watch_area_count=1` は dangerous_areas へ入っていない。

## 4. F: 地震一覧確認

実ブラウザ:

- URL: `http://127.0.0.1:8080/live.html`

結果:

- 地震件数表示: PASS
- 展開トグル: PASS
- 初期状態でリスト非表示: PASS
- タップでリスト展開: PASS
- 地震イベント一覧表示: PASS

実ブラウザ text 抜粋:

```text
地震 5件 (24h)
熊本県熊本地方
M2.7 / 震度1 06-01 12:40
新潟県上中越沖
M4.6 / 震度3 06-01 05:54
茨城県南部
M3.1 / 震度1 06-01 03:10
```

確認項目:

- 発生時刻: PASS
- 震源名: PASS
- M: PASS
- 最大震度: PASS

Notes:

- 初回検証時は DOM text で `震度106-01` のように震度と日時の間の空白が詰まって見える箇所があった。
- Claude 修正後の再確認では `M2.7 / 震度1 06-01 12:40` のようにスペース入りで表示されることを確認。

## 5. F: 地図フォーカス確認

地震一覧の先頭項目をクリック。

結果:

- 地図中心移動: PASS
- zoom: 5 → 8
- center: `[36.5, 137.0]` → approximately `[32.6, 130.7]`
- 対象地震: `熊本県熊本地方`

ポップアップ:

- 初回検証: FAIL（`popupVisible`: false）
- Claude 修正後再確認: PASS（`popupVisible`: true）
- 一覧クリック後に Leaflet popup が表示され、震源名 `熊本県熊本地方` が含まれることを確認。

## 6. G: 雨雲レイヤー視認性確認

実ブラウザ確認:

- 雨雲レイヤー表示あり。
- 雨雲 tile layer の `opacity`: 0.65
- log:

```text
[live-rain] live rain layer opacity: value=0.65
```

結果:

- PASS

Notes:

- 修正前スクリーンショットはこの検証時点では取得できないため、直接比較は未実施。
- 現在のスクリーンショットでは地図ベースレイヤーと雨雲が同時に視認可能。

## 7. Console 確認

実ブラウザ通常表示:

- console error: 0 件
- page error: 0 件

mock kikikuru ケース:

- console error: 0 件
- page error: 0 件

ナビ本体:

- console error: 0 件
- page error: 0 件

結果:

- PASS

## 8. 回帰確認

### git diff check

実行:

```bash
git diff --check
```

結果:

- PASS

### Playwright

実行:

```bash
npx playwright test e2e/live-basic.spec.js e2e/live-earthquake-layer.spec.js e2e/live-sun-moon-card.spec.js e2e/live-tide-layer.spec.js
```

結果:

- PASS
- 112 passed

内訳:

- `live-basic`: 72 passed
- `live-earthquake-layer`: 12 passed
- `live-sun-moon-card`: 15 passed
- `live-tide-layer`: 13 passed

Notes:

- 以前の検証で発生していた 8787 port 競合は、今回は標準 config の global setup が起動できたため発生しなかった。
- Claude 修正後は Phase 3-EFG E2E が地震一覧展開、地図フォーカス、ポップアップ表示まで確認している。

## 9. ナビ本体影響確認

実ブラウザ:

- URL: `http://127.0.0.1:8080/`

結果:

- PASS
- HTTP 200
- map visible: true
- console error: 0 件
- page error: 0 件

## スクリーンショット

- `/private/tmp/live-phase3efg-live.png`
  - 実データの `/live.html`、地震一覧・雨雲・危険地域カード確認。
- `/private/tmp/live-phase3efg-kikikuru-mock.png`
  - mock summary で沖縄・奄美のキキクル危険地域表示確認。
- `/private/tmp/live-phase3efg-nav-root.png`
  - `/` ナビ本体表示確認。

## 総括

E のキキクル整合性、G の雨雲 opacity、回帰 E2E、ナビ本体非干渉は確認できた。

F の地震一覧も表示・展開・地図フォーカス・ポップアップ表示まで成立している。

初回検証で検出した「一覧項目クリック後のポップアップ未表示」は、Claude 修正後の再確認で解消を確認した。最終判定は **PASS with notes**。

## 再確認（Claude修正後）

修正内容確認:

- `frontend/js/live/live-alert-panel.js`: 地震一覧 item に `data-name` / `data-detail` が追加されている。
- `frontend/js/live/live-alert-panel.js`: 一覧 item click で `L.popup().setLatLng(...).setContent(...).openOn(liveMap)` が呼ばれる。
- `frontend/js/live/live-alert-panel.js`: 震度と日時の間にスペースが入る表示に修正されている。
- `e2e/live-basic.spec.js`: `.leaflet-popup` 表示と震源名 text を確認する E2E が追加されている。

再実行:

```bash
node --check frontend/js/live/live-alert-panel.js
node --check e2e/live-basic.spec.js
python3 -m compileall backend/app
node /private/tmp/live_phase3efg_probe.js
git diff --check
npx playwright test e2e/live-basic.spec.js e2e/live-earthquake-layer.spec.js e2e/live-sun-moon-card.spec.js e2e/live-tide-layer.spec.js
```

結果:

- 構文確認: PASS
- Docker 状態: `backend` healthy / `frontend` Up / `martin` healthy / `osrm-walking` Up
- 実ブラウザ probe: PASS
- `git diff --check`: PASS
- Playwright: 112 passed

実ブラウザ再確認 detail:

- 地震トグル: `地震 5件 (24h) ▾`
- 地震リスト初期状態: 非表示
- 地震リスト展開: PASS
- 表示 text: `M2.7 / 震度1 06-01 12:40` など、震度と日時の間のスペースあり
- 一覧クリック後 focus: zoom 5 → 8、center `[36.5, 137.0]` → approximately `[32.6, 130.7]`
- ポップアップ: `popupVisible: true`
- 雨雲レイヤー: opacity 0.65、zIndex 450
- console error: 0 件
- page error: 0 件

キキクル mock 再確認:

- `キキクル危険地域あり`
- `沖縄県付近 キキクル（土砂）`
- `奄美付近 キキクル（浸水）`
- console error / page error: 0 件

ナビ本体再確認:

- URL: `http://127.0.0.1:8080/`
- HTTP 200
- map visible: true
- console error / page error: 0 件

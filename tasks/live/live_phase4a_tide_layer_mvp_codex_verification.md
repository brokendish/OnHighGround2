# Phase 4-A 潮位観測点レイヤー MVP 検証レポート

## 実施日時

- 2026-05-30 20:59-21:41 JST

## 最終判定

**PASS with notes**（2026-05-30 21:58 JST 再確認後）

初回確認時は **FAIL**。Claude 修正後の再確認で、観測点詳細 API の 404 は解消し、実ブラウザでもポップアップとグラフ描画を確認できた。

残る notes:

- `pytest` はローカル venv の `requests` 不足で collection error のまま。
- 指定どおりの `npx playwright test e2e/live-basic.spec.js` は 8787 ポート使用中で起動失敗のまま。ただし既存 8787 サーバーを使う一時 config では `live-basic` / `live-tide-layer` とも PASS。
- 東京湾周辺の近接マーカーはクリック対象が重なりやすい。実確認では詳細取得・ポップアップ・グラフ自体は正常。

## 初回判定

理由:

- 観測点一覧 API は成功したが、一覧に含まれる観測点 ID の詳細 API が 404 になった。
- 実ブラウザ確認でも、マーカークリック後の詳細取得が 404 になり、現在潮位・満潮・干潮・グラフが表示されなかった。
- 指定回帰の `pytest` はローカル環境依存で実行完了できなかった。
- 指定どおりの `npx playwright test e2e/live-basic.spec.js` は既存 8787 ポート使用中で起動に失敗した。

## 1. 構文確認

### Python

実行:

```bash
python3 -m compileall backend/app
```

結果:

- PASS
- `backend/app/api/live_tide.py` を含め SyntaxError なし。

### JavaScript

実行:

```bash
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-tide-layer.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-danger-summary.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-main.js
node --check frontend/js/live/live-mobile.js
```

結果:

- PASS
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
evacuation-navi-backend   Up 39 minutes (healthy)   0.0.0.0:8000->8000/tcp
evacuation-navi-frontend  Up 24 hours               0.0.0.0:8080->80/tcp
evacuation-navi-martin    Up 24 hours (healthy)
evacuation-navi-osrm-walking Up 24 hours            0.0.0.0:5501->5001/tcp
```

補足:

- frontend は compose 上で healthcheck 表示なしのため `healthy` ではなく `Up` として確認。

## 3. API 確認結果

### 観測点一覧

実行:

```bash
curl -i http://127.0.0.1:8000/api/live/tide/stations
```

結果:

- HTTP 200
- `stations` 配列あり
- 観測点数: 50

サンプル:

```json
{
  "count": 50,
  "stations": [
    { "id": "WN", "name": "稚内", "has_data": true },
    { "id": "TK", "name": "東京", "has_data": true },
    { "id": "QS", "name": "横浜", "has_data": true }
  ]
}
```

### 観測点詳細

実行:

```bash
curl -i http://127.0.0.1:8000/api/live/tide/stations/TK
curl -i http://127.0.0.1:8000/api/live/tide/stations/QS
```

結果:

- FAIL
- `TK`: HTTP 404 `{"detail":"station not found: TK"}`
- `QS`: HTTP 404 `{"detail":"station not found: QS"}`
- `current_tide` / `current_tide_cm`, `extremes`, `series` / `records` は取得できず。

参考メモ:

- 一覧 API が返す ID と詳細 API の検索対象に不整合がある可能性がある。
- 実装修正は禁止のため、調査メモに留めた。

## 4. レイヤー表示確認

実ブラウザ確認:

- URL: `http://127.0.0.1:8080/live.html`
- レイヤー一覧に「潮位観測点」表示あり。

結果:

- PASS

## 5. ON/OFF 確認

実ブラウザ確認結果:

- 初期状態: OFF
- ON: マーカー 50 件表示
- OFF: マーカー 0 件
- 再 ON: マーカー 50 件に復帰

結果:

- PASS

## 6. マーカー確認

実ブラウザ確認結果:

- 全国観測点: 50 件表示
- 重複 title: 0
- sample title: 稚内, 小樽, 函館, 室蘭, 江差, 釧路, 網走, 大間

結果:

- PASS with notes

Notes:

- 東京湾周辺など近接地点は視覚的に重なりやすく、通常クリックでは別マーカーが pointer event を受けるケースあり。

## 7. ポップアップ確認

実ブラウザ確認結果:

- マーカークリックでポップアップ自体は表示。
- 詳細 API が HTTP 404 のため、内容は `読み込み中...` から更新されなかった。
- Console warning:

```text
[live-tide] 詳細取得失敗: Error: HTTP 404
```

結果:

- FAIL

確認できなかった項目:

- 現在潮位
- 満潮
- 干潮

## 8. グラフ確認

実ブラウザ確認結果:

- 詳細 API が HTTP 404 のため `.live-tide-graph-canvas` は表示されなかった。

結果:

- FAIL

## 9. 回帰確認

### pytest

実行:

```bash
pytest
```

結果:

- FAIL
- `pytest: command not found`

追加確認:

```bash
venv/bin/pytest
```

結果:

- FAIL
- collection 中に `backend/test_api.py` で `ModuleNotFoundError: No module named 'requests'`

### Playwright live-basic

指定コマンド:

```bash
npx playwright test e2e/live-basic.spec.js
```

結果:

- FAIL
- `Error: listen EADDRINUSE: address already in use 127.0.0.1:8787`
- 既存の node process が 8787 を listen していた。

追加確認:

- 既存 8787 サーバーを利用する一時 config を `/private/tmp/playwright-live-existing-server.config.js` に作成して実行。

```bash
npx playwright test e2e/live-basic.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- PASS
- 64 passed

### Playwright live-tide-layer

追加確認:

```bash
npx playwright test e2e/live-tide-layer.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- PASS
- 13 passed
- この spec は API mock を使用するため、実 API の詳細 404 は検出しない。

### git diff check

実行:

```bash
git diff --check
```

結果:

- PASS

## 10. ナビ本体影響確認

実ブラウザ確認:

- URL: `http://127.0.0.1:8080/`
- HTTP 200
- map visible: true
- `/api/live/tide/` 自動リクエスト: 0 件
- console error: 0 件

結果:

- PASS

## スクリーンショット

- `/private/tmp/live-phase4a-tide-on.png`
  - `/live.html` で潮位観測点 ON、50 マーカー表示。
- `/private/tmp/live-phase4a-tide-popup.png`
  - マーカークリック後。詳細 API 404 のためポップアップは読み込み中表示。
- `/private/tmp/live-phase4a-nav-root.png`
  - `/` ナビ本体表示確認。

## 総括

レイヤー切替、マーカー表示、ON/OFF、ナビ本体への非干渉は確認できた。

一方で、実 API の観測点詳細が 404 になるため、Phase 4-A MVP の主要要件である潮位ポップアップと潮位グラフは実データでは成立していない。

したがって初回判定は **FAIL**。

---

## 再確認（Claude 修正後）

### 実施日時

- 2026-05-30 21:58 JST

### 修正内容の確認

確認:

- `backend/app/services/tide_service.py`
  - `get_station_meta(station_code)` 追加を確認。
  - `has_station_data(station_code)` 追加を確認。
- `backend/app/api/live_tide.py`
  - `_stations` / `_hourly_index` の直接インポート廃止を確認。
  - `get_station_meta()` / `has_station_data()` 経由に変更されていることを確認。

結果:

- PASS

### 構文確認

実行:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-tide-layer.js
```

結果:

- PASS

### Docker 状態

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

### API 再確認

#### 観測点一覧

実行:

```bash
curl -i http://127.0.0.1:8000/api/live/tide/stations
```

結果:

- HTTP 200
- 観測点数: 50
- `TK` / `QS` を含む `stations` 配列あり。

#### 観測点詳細: TK

実行:

```bash
curl -i http://127.0.0.1:8000/api/live/tide/stations/TK
```

結果:

- HTTP 200
- `station_id`: `TK`
- `name`: `東京`
- `current_tide_cm`: 123
- `records`: 72 件
- `extremes.high_tides`: 6 件
- `extremes.low_tides`: 4 件
- `next_high_tide` / `next_low_tide` あり。

#### 観測点詳細: QS

実行:

```bash
curl -i http://127.0.0.1:8000/api/live/tide/stations/QS
```

結果:

- HTTP 200
- `station_id`: `QS`
- `name`: `横浜`
- `current_tide_cm`: 118
- `records`: 72 件
- `extremes.high_tides`: 6 件
- `extremes.low_tides`: 4 件
- `next_high_tide` / `next_low_tide` あり。

### 実ブラウザ再確認

確認 URL:

- `http://127.0.0.1:8080/live.html`

結果:

- レイヤー一覧に「潮位観測点」あり。
- 初期状態: OFF
- ON: マーカー 50 件表示
- OFF: マーカー 0 件
- 再 ON: マーカー 50 件に復帰
- 重複 title: 0
- 詳細 API: HTTP 200
- ポップアップ表示: PASS
- 現在潮位表示: PASS
- 満潮・干潮表示: PASS
- グラフ canvas 表示: PASS
- canvas pixel 非空: PASS
- console error / page error: 0 件

実確認時のポップアップ例:

```text
油壺
現在潮位: 99 cm
満潮 03:00 140 cm
干潮 22:00 92 cm
```

Notes:

- 横浜付近の近接マーカークリックでは、重なりにより油壺側が選択された。詳細 API は 200 で、ポップアップ更新とグラフ描画は正常に確認。

### ナビ本体影響再確認

確認 URL:

- `http://127.0.0.1:8080/`

結果:

- HTTP 200
- map visible: true
- `/api/live/tide/` 自動リクエスト: 0 件
- console error: 0 件

### 回帰再確認

#### pytest

実行:

```bash
venv/bin/pytest
```

結果:

- FAIL
- `backend/test_api.py` collection 中に `ModuleNotFoundError: No module named 'requests'`
- 初回確認時と同じ環境要因。

#### Playwright live-basic

指定コマンド:

```bash
npx playwright test e2e/live-basic.spec.js
```

結果:

- FAIL
- `Error: listen EADDRINUSE: address already in use 127.0.0.1:8787`
- 初回確認時と同じ環境要因。

追加確認:

```bash
npx playwright test e2e/live-basic.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- PASS
- 64 passed

#### Playwright live-tide-layer

追加確認:

```bash
npx playwright test e2e/live-tide-layer.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- PASS
- 13 passed

#### git diff check

実行:

```bash
git diff --check
```

結果:

- PASS

### スクリーンショット（再確認）

- `/private/tmp/live-phase4a-recheck-tide-on.png`
  - `/live.html` で潮位観測点 ON、50 マーカー表示。
- `/private/tmp/live-phase4a-recheck-tide-popup.png`
  - マーカークリック後。詳細 200、現在潮位・満潮/干潮・グラフ表示。
- `/private/tmp/live-phase4a-recheck-nav-root.png`
  - `/` ナビ本体表示確認。

### 再確認総括

Claude 修正により、初回 FAIL の主因だった「一覧 ID と詳細 API の不整合」は解消済み。

実 API、実ブラウザ、mock E2E の各観点で潮位レイヤー MVP の主要機能は成立している。

最終判定は **PASS with notes**。

# OnHighGround2 気象カード Phase2-C Codex 検証結果

## 検証メタデータ

- 検証日時: 2026-05-17 10:57 JST
- 対象ブランチ: `main`
- 対象 commit: `e6cc2732fc3eb5fe1e1ca1cc992e0960a9148205`
- 対象:
  - `backend/app/api/weather.py`
  - `backend/app/services/weather_risk_context_service.py`
  - `frontend/js/weather-service.js`
  - `frontend/js/weather-card.js`
  - `frontend/js/weather-alert-ui.js`
  - `frontend/index.html`
- 最終判定: **PASS with notes**

## サマリー

Phase2-C の「気象 × ハザード統合」は、新 API `GET /api/weather/risk/context` と frontend の `combined` model で実装されている。backend は `lowland/flood/inland_flood/landslide` を対象に複合リスクを構築し、frontend は情報タブ「気象」カードと地図本体バナーに combined risk を反映する。

Docker 起動、API 回帰、mock 複合リスク判定、Playwright UI mock、既存 E2E、既存 pytest は通過した。route scoring / reroute への変更は確認されず、気温 UI 復活も確認されなかった。

notes として、平常時は `複合リスクなし` を明示表示せず、combined risk 欄を非表示にする設計だった。仕様例とは少し異なるが、平常時に静かな UI という方針には合っているため PASS with notes とする。

## 1. 静的確認

### PASS

- 気象 × ハザードの combined risk model が `weather_risk_context_service.py` にある。
- 新 API `GET /api/weather/risk/context?lat=&lon=` が `backend/app/api/weather.py` に追加されている。
- 対象 hazard:
  - `lowland`
  - `flood`
  - `inland_flood`
  - `landslide`
  - `tsunami` / `storm_surge` は hazards に含むが combined では参考情報扱い。
- backend は `HazardService.assess_candidate()` を再利用している。
- `weather warning + hazard unknown` で weather warning が消えない risk 計算になっている。
- `hazard unavailable` 時は empty assessment / unavailable response で API を落とさない構造。
- frontend は `_weatherRiskContextFetch()` で context API を取得し、`riskInfo.combined` / `riskInfo.hazards` として UI に渡す。
- 情報タブ「気象」カードは `.wc-combined-list` / `.wc-combined-row` で combined risk を表示する。
- 地図本体バナーは combined がある場合、combined headline を優先して表示する。
- `route_risk_scoring.py` / navigation / reroute 系への変更は確認されなかった。
- 気温 UI の復活は確認されなかった。

### Notes

- 平常時の `複合リスクなし` は明示表示されず、combined list は `display:none` になる。
- hazard unavailable 単独では UI に `ハザード情報を確認できません` を明示しない。騒がせすぎない方針としては許容だが、今後の改善余地あり。

## 2. Docker / 起動確認

### 実施コマンド

```bash
docker compose build backend frontend
docker compose up -d backend frontend martin osrm-walking
docker compose ps backend frontend martin osrm-walking
```

### 結果

- `docker compose build backend frontend`: PASS
  - compose 上は backend image の build が実行された。frontend は nginx volume serving 構成。
- `docker compose up -d backend frontend martin osrm-walking`: PASS
- `docker compose ps`:
  - backend: `healthy`
  - frontend: `up`
  - martin: `healthy`
  - osrm-walking: `up`

backend はハザードデータ読み込みのため healthy まで約 1 分かかったが、起動自体は正常。

## 3. API 確認

### 実施コマンド

```bash
curl -s 'http://127.0.0.1:8000/api/weather/risk/context?lat=35.681236&lon=139.767125'
```

### 実 API 結果

東京駅付近の実レスポンス:

```json
{
  "status": "ok",
  "risk_level": "none",
  "weather": {
    "alert_severity": "none",
    "precip_severity": "none",
    "current_intensity": "none",
    "forecast_max_intensity": "none",
    "forecast_max_minutes": 5
  },
  "hazards": {
    "lowland": true,
    "flood": true,
    "inland_flood": false,
    "landslide": false,
    "tsunami": false,
    "storm_surge": true,
    "data_available": true
  },
  "combined": []
}
```

判定: PASS

- HTTP 200。
- `risk_level` あり。
- `weather` あり。
- `hazards` あり。
- `combined` あり。
- 現在は降水なしのため、hazard が true でも combined は空で静か。

## 4. API 回帰

### 実施コマンド

```bash
curl -i 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/alerts/current?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/rain/tile/times'
curl -i 'http://127.0.0.1:8000/api/hazards/active'
```

### 結果

- precipitation summary API: HTTP 200
- weather alerts API: HTTP 200
- rain tile times API: HTTP 200
- hazard active API: HTTP 200
- API 500 は確認されなかった。

## 5. mock 複合リスク検証

backend container 内で `weather_risk_context_service` の `_build_combined_risks()` と `_compute_risk_level()` を直接検証した。

| Case | Expected risk_level | Actual risk_level | Expected combined | Actual combined | Result |
|---|---:|---:|---|---|---|
| weather none + precip none + hazards none | `none` | `none` | `[]` | `[]` | PASS |
| moderate rain + lowland | `advisory` | `advisory` | `rain_lowland` | `rain_lowland` | PASS |
| strong rain + flood | `warning` | `warning` | `rain_flood` | `rain_flood` | PASS |
| severe rain + landslide | `emergency` | `emergency` | `rain_landslide` | `rain_landslide` | PASS |
| weather warning + hazard unknown | `warning` | `warning` | `[]` | `[]` | PASS |
| unknown only | `unknown` | `unknown` | `[]` | `[]` | PASS |

判定: PASS

- unknown は none に倒れていない。
- weather warning は hazard unknown に潰されない。
- severe rain + landslide は emergency になる。

## 6. UI mock 確認

Playwright で `http://127.0.0.1:8080` を開き、`_weatherAlertUiUpdate()` と `_weatherCardRender()` に mock data を直接投入した。

### 平常時

結果:

```text
bannerDisplay: none
bannerText: ""
combinedDisplay: none
cardText: 気象 ... 警報・注意報なし 降水 現在: 降水なし
```

判定: PASS with notes

- 地図本体バナーなし。
- 平常時は静か。
- `複合リスクなし` の明示行は出ない。

### advisory combined

mock:

```text
precip: moderate
combined: rain_lowland / advisory
```

結果:

```text
bannerClass: weather-alert-banner wa-banner--advisory
bannerText: 雨域 + 低地・排水困難エリア
combinedText: 雨域 + 低地・排水困難エリア
```

判定: PASS

- 情報タブに複合リスク表示。
- 地図本体に小バナー。

### warning combined

mock:

```text
precip: strong
combined: rain_flood / warning
```

結果:

```text
bannerClass: weather-alert-banner wa-banner--warning
bannerText: 強雨域接近 + 洪水想定区域
combinedText: 強雨域接近 + 洪水想定区域
```

判定: PASS

- 情報タブに浸水リスク文言。
- 赤バナー。

### emergency combined

mock:

```text
precip: severe
combined: rain_landslide / emergency
```

結果:

```text
bannerClass: weather-alert-banner wa-banner--emergency
bannerText: 強雨 + 土砂災害警戒区域 — 命を守る行動を確認してください
combinedText: 強雨 + 土砂災害警戒区域
```

判定: PASS

- 最上位警告。
- 命を守る行動の文言あり。

## 7. バナー状態遷移

Playwright mock で以下を確認した。

```text
combined warning
↓
combined none
↓
hazard unavailable
↓
weather warning
↓
combined advisory
```

### 結果

- combined warning -> none:
  - `display:none`
  - `textContent: ""`
  - `innerHTML: ""`
- hazard unavailable:
  - `display:none`
  - 誤警告なし。
- weather warning + hazard unknown:
  - warning バナー維持。
  - `大雨警報 発表中 — 避難を検討してください`
- warning -> advisory:
  - advisory バナーに downgrade。
  - 古い warning 文言は残らない。

判定: PASS

## 8. 回帰確認

### 実施コマンド

```bash
npx playwright test e2e/info-tab-card-ui.spec.js --reporter=line
venv/bin/python -m pytest tests/test_weather_temperature.py -q
```

追加確認:

```bash
rg --files e2e | rg 'weather-card.*\.spec\.js$'
```

### 結果

- `e2e/info-tab-card-ui.spec.js`: 3 passed
- `tests/test_weather_temperature.py`: 34 passed
- `e2e/weather-card*.spec.js`: 該当ファイルなし
- 気温 UI 復活は確認されなかった。
- navigation / route scoring / reroute 関連ファイルへの変更は確認されなかった。

## 9. Notes

- 平常時に `複合リスクなし` を明示しない設計。仕様例に寄せるならカード内に静かな一行を追加してもよい。
- hazard unavailable 単独では `ハザード情報を確認できません` を UI に出さない。通常時に騒がせない設計としては妥当だが、debug/詳細表示では出せる余地あり。
- 実 API では東京駅付近が `lowland: true` / `flood: true` だったが、降水なしのため combined は空。雨天時の実地確認は継続推奨。
- route scoring / reroute には未統合で、Phase2-C の除外条件を守っている。

## 最終判定

**PASS with notes**

combined risk model/API、主要 hazard 対象、strong rain + flood warning、severe rain + landslide emergency、unknown の安全側処理、情報タブ表示、地図バナー反映、API/E2E 回帰はいずれも通過した。残りは平常時の `複合リスクなし` 明示や hazard unavailable 表示の細かな UX 調整。

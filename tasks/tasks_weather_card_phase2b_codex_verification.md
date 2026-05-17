# OnHighGround2 気象カード Phase2-B Codex 検証結果

## 検証メタデータ

- 検証日時: 2026-05-17 10:36 JST
- 対象ブランチ: `main`
- 対象 commit: `e6cc2732fc3eb5fe1e1ca1cc992e0960a9148205`
- 対象:
  - `frontend/js/weather-alert-ui.js`
  - `frontend/js/weather-card.js`
  - `frontend/js/weather-service.js`
  - `frontend/index.html`
  - backend weather API 回帰
- 最終判定: **PASS with notes**

## サマリー

Claude 修正後の再検証で、前回 FAIL の blocker は解消した。

- `precipitation severity: "unknown"` は `riskInfo.precipUnknown` として UI に渡される。
- unknown 時はカードに `降水予測を判定できません` と `現在: 判定不能` が表示され、none と同一表示にならない。
- warning -> none / warning -> unavailable 後に、地図バナーの `innerHTML` と `textContent` は空になる。
- 降水ドリブン advisory / warning の地図バナー文言は避難判断向けに修正された。

Docker 起動、API 回帰、既存 E2E、既存 pytest も通過したため、最終判定は **PASS with notes** とする。

notes として、UI 用 `riskLevel` 自体は unknown を `none` rank として扱う設計のままだが、`precipUnknown` により false-safe な表示は回避できている。また、カード内 future 表示は `30分後: 強い雨` 形式で、仕様例の `30分以内に強雨域接近` にはまだ改善余地がある。

## 1. 静的確認

### PASS

- current と future forecast は `weather-service.js::_buildPrecipInfo()` と `weather-card.js::_wcRenderPrecip()` で分離されている。
- severity 統合ロジックは `weather-service.js::_computeRiskLevel()` にある。
- `precipData.severity === "unknown"` の場合、`riskInfo.precipUnknown: true` が付与される。
- `weather-card.js` は `precipUnknown` 時に `降水予測を判定できません` を `.wc-precip-unknown` で表示する。
- `weather-alert-ui.js` は `riskLevel === "none"` / `!hasBannerAlert && !hasNotablePrecip` / `!text` の各 path で `banner.innerHTML = ''` を実行する。
- warning / emergency / advisory の CSS class は分離されている。
- emergency のみ pulse animation がある。常時点滅は見当たらない。
- 通常 UI に Phase2-A debug の `zoom`, `tile_url`, `rgb`, `distance_sq` は表示されない。

### Notes

- `weather-service.js::_WS_SEVERITY_RANK` は `unknown: 0` のまま。`riskLevel` だけを見ると none 相当だが、UI は `precipUnknown` を別軸で扱うため、表示上は none に倒れていない。
- future のカード文言は `<minutes>分後: <intensity label>` のまま。構造は正しいが、避難判断向け表現としては今後 `30分以内に強雨域接近` などに寄せる余地がある。

## 2. Docker / 起動確認

### 実施コマンド

```bash
docker compose build frontend backend
docker compose up -d backend frontend martin osrm-walking
docker compose ps backend frontend martin osrm-walking
```

### 結果

- `docker compose build frontend backend`: PASS
  - compose 上は backend image の build が実行された。frontend は nginx volume serving 構成。
- `docker compose up -d backend frontend martin osrm-walking`: PASS
- `docker compose ps`:
  - backend: `healthy`
  - frontend: `up`
  - martin: `healthy`
  - osrm-walking: `up`

backend はハザードデータ読み込みのため healthcheck が healthy になるまで約 1 分かかったが、起動自体は正常。

## 3. API 回帰

### 実施コマンド

```bash
curl -i 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/alerts/current?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/rain/tile/times'
curl -i 'http://127.0.0.1:8000/api/hazards/active'
```

### 結果

- precipitation summary API: HTTP 200
  - `status: "ok"`
  - `severity: "none"`
  - `current.intensity: "none"`
  - `forecast[]`: +5 から +30 分まで schema 通り
- weather alerts API: HTTP 200
  - `status: "ok"`
  - `severity: "none"`
  - `alerts: []`
  - `location.city: "千代田区"`
- rain tile times API: HTTP 200
- hazard active API: HTTP 200
- API schema 崩れや 500 は確認されなかった。

## 4. UI mock 確認

Playwright で `http://127.0.0.1:8080` を開き、`_weatherAlertUiUpdate()` と `_weatherCardRender()` に mock data を直接投入した。

### none

結果:

```text
bannerDisplay: none
bannerClass: weather-alert-banner
bannerText: ""
bannerHtml: ""
cardText: 気象 ... 警報・注意報なし 降水 現在: 降水なし
```

判定: PASS

- 地図本体バナーなし。
- 派手な色なし。
- 平常時は静か。

### advisory

#### 注意報ドリブン

mock:

```text
alerts: 大雨注意報
precip: current weak, forecast moderate
riskLevel: advisory
```

結果:

```text
bannerDisplay: flex
bannerClass: weather-alert-banner wa-banner--advisory
bannerText: 注意報: 大雨注意報×
cardText: ... 大雨注意報発表中 降水 現在: 弱い雨30分後: 雨 ...
```

判定: PASS

#### 降水ドリブン

mock:

```text
alerts: none
precip: current weak, forecast moderate
riskLevel: advisory
```

結果:

```text
bannerDisplay: flex
bannerClass: weather-alert-banner wa-banner--advisory
bannerText: 現在地周辺で雨域を検出×
cardText: ... 警報・注意報なし 降水 現在: 弱い雨30分後: 雨 ...
```

判定: PASS

- 黄色系の小バナーになる。
- 旧文言 `弱い雨が予測されています — 降水レーダーを確認してください` は出ない。
- current / future は分離されている。

### warning

#### 警報ドリブン

mock:

```text
alerts: 大雨警報
precip: forecast strong
riskLevel: warning
```

結果:

```text
bannerDisplay: flex
bannerClass: weather-alert-banner wa-banner--warning
bannerText: ⚠ 大雨警報 発表中 — 避難を検討してください×
cardText: ... 大雨警報発表中 降水 現在: 降水なし30分後: 強い雨 ...
```

判定: PASS

#### 降水ドリブン

mock:

```text
alerts: none
precip: forecast strong
riskLevel: warning
```

結果:

```text
bannerDisplay: flex
bannerClass: weather-alert-banner wa-banner--warning
bannerText: ⚠ 30分以内に強雨域接近 — 安全な場所への移動を検討してください×
cardText: ... 警報・注意報なし 降水 現在: 降水なし30分後: 強い雨 ...
```

判定: PASS

- 赤系バナー。
- 降水ドリブン文言が避難判断向けに修正されている。
- カード header class は `wc-header--warning`。

### emergency

mock:

```text
alerts: 大雨特別警報
precip: current severe, forecast severe
riskLevel: emergency
```

結果:

```text
bannerDisplay: flex
bannerClass: weather-alert-banner wa-banner--emergency
bannerText: ⚠ 大雨特別警報 発表中 — 命を守る行動を確認してください
cardText: ... 大雨特別警報発表中 降水 現在: 非常に激しい雨20分後: 非常に激しい雨 命を守る行動を今すぐとってください
```

判定: PASS

- 最上位強調。
- emergency のみ pulse animation。
- close button は emergency には出ない。

## 5. current / future 分離確認

確認結果:

- current は `現在: <label>` として表示される。
- forecast の最大強度は `<minutes>分後: <intensity label>` として表示される。
- warning mock では `現在: 降水なし` と `30分後: 強い雨` が分かれて表示された。
- emergency mock では `現在: 非常に激しい雨` と `20分後: 非常に激しい雨` が表示された。
- unknown mock では `降水予測を判定できません` と `現在: 判定不能` が表示された。

判定: PASS with notes

current / future の分離構造は通っている。future 表示は「接近中」ではなく「30分後: 強い雨」という表現なので、仕様例の `30分以内に強雨域接近` にはまだ改善余地がある。

## 6. unavailable / unknown

### unavailable

warning 表示後に unavailable を投入した。

結果:

```text
bannerDisplay: none
bannerClass: weather-alert-banner
bannerText: ""
bannerHtml: ""
cardText: ... 警報・注意報なし 降水 ナウキャスト取得不可 気象情報を取得できません
```

判定: PASS

- 表示上バナーが消える。
- DOM 内にも直前 warning 文言は残らない。
- unavailable は warning 扱いされない。

### unknown

mock:

```text
alerts: none
precip: severity unknown, current unknown, forecast unknown
```

結果:

```text
bannerDisplay: none
bannerClass: weather-alert-banner
bannerText: ""
bannerHtml: ""
cardText: ... 警報・注意報なし 降水 降水予測を判定できません現在: 判定不能
headerClass: wc-header--none
```

判定: PASS with notes

- `降水予測を判定できません` が表示される。
- none と同一表示ではない。
- emergency / warning 扱いにもならない。
- `riskLevel` は none のままだが、`precipUnknown` で UI 表現できているため false-safe 表示は回避できている。

## 7. バナー状態遷移

Playwright mock で以下を確認した。

```text
warning
↓
none
↓
unavailable
↓
warning
↓
advisory
```

### 結果

- warning -> none:
  - `display:none`
  - `className: weather-alert-banner`
  - `textContent: ""`
  - `innerHTML: ""`
- warning -> unavailable:
  - `display:none`
  - `className: weather-alert-banner`
  - `textContent: ""`
  - `innerHTML: ""`
- warning -> advisory:
  - `display:flex`
  - `className: weather-alert-banner wa-banner--advisory`
  - 文言も advisory に更新される。

判定: PASS

古い warning バナーは残らず、downgrade / clear / unavailable が正しく処理される。

## 8. 回帰確認

### 実施コマンド

```bash
npx playwright test e2e/info-tab-card-ui.spec.js --reporter=line
venv/bin/python -m pytest tests/test_weather_temperature.py -q
```

### 結果

- `e2e/info-tab-card-ui.spec.js`: 3 passed
- `tests/test_weather_temperature.py`: 34 passed
- 気温 UI 復活は確認されなかった。

### 追加回帰メモ

- backend/frontend/martin/osrm-walking: 起動中
- backend: healthy
- martin: healthy
- rain tile times API: HTTP 200
- hazard active API: HTTP 200
- weather alerts API: HTTP 200
- navigation / hazard overlay の深い操作確認は未実施。ただし既存 E2E 範囲では崩れなし。

## 9. Notes

- `riskLevel` は `none/advisory/warning/emergency` の 4 段階を維持し、unknown は `precipUnknown` で別軸表示する設計。UI 表示上は none に倒れていないため Phase2-B として許容。
- future のカード文言は「接近中」ではなく「30分後: 強い雨」。より避難判断向けにする余地あり。
- emergency の視認性、色味、pulse の強さは今後の調整余地あり。
- debug UI の混入は確認されなかった。

## 最終判定

**PASS with notes**

前回 blocker だった `unknown を none に倒さない` と `旧バナー状態を残さない` は解消した。Docker/API/E2E も通過しており、Phase2-B は実用判定として PASS。残るのは文言・視認性の微調整。

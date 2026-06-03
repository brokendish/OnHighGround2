# JMA r8 警報・注意報実装 Codex再検証

## 判定

PASS

`warning/data/r8/{pref_code}.json` への切替と、city → class20 code 優先フィルタが期待通り動作していることを確認した。前回FAILだった `class10Items` 混入は解消し、足立区は強風注意報のみ、調布市は警報・注意報なし、大島町は強風注意報 + 波浪警報を返す。

## 検証日時

2026-06-03

## 実装確認

コンテナ内の `jma_weather_adapter.py` で以下を確認した。

```text
_JMA_WARNING_BASE = https://www.jma.go.jp/bosai/warning/data/r8/{pref_code}.json
_JMA_WARNING_LEGACY_BASE = https://www.jma.go.jp/bosai/warning/data/warning/{pref_code}.json
_CITY_CLASS20_CODE あり
filter_alerts_for_city() は class20 code 既知なら area_code == class20_code のみ返す
```

## API確認

### 足立区

座標:

```text
lat=35.775
lng=139.804
```

`GET /api/weather/warnings`:

```json
{
  "ok": true,
  "area_name": "足立区",
  "has_warning": false,
  "max_level": "advisory",
  "items": [
    {
      "name": "強風注意報",
      "level": "注意報",
      "status": "継続"
    }
  ]
}
```

結果:

- 足立区 `1312100` の強風注意報を取得: PASS
- `波浪注意報` 混入なし: PASS

### 調布市

座標:

```text
lat=35.65
lng=139.54
```

`GET /api/weather/warnings`:

```json
{
  "ok": true,
  "area_name": "調布市",
  "has_warning": false,
  "max_level": "none",
  "items": []
}
```

結果:

- class20 code `1320800` に該当アクティブ項目なし: PASS
- `東京地方` の強風注意報/波浪注意報へフォールバックしない: PASS

### 大島町

座標:

```text
lat=34.75
lng=139.36
```

`GET /api/weather/warnings`:

```json
{
  "ok": true,
  "area_name": "大島町",
  "has_warning": true,
  "max_level": "warning",
  "items": [
    {
      "name": "強風注意報",
      "level": "注意報",
      "status": "警報から注意報"
    },
    {
      "name": "波浪警報",
      "level": "警報",
      "status": "継続"
    }
  ]
}
```

結果:

- 大島町 `1336100` の警報・注意報を取得: PASS
- `max_level=warning`: PASS

### 八丈町

座標:

```text
lat=33.10
lng=139.80
```

`GET /api/weather/warnings`:

```json
{
  "ok": true,
  "area_name": "八丈町",
  "has_warning": true,
  "max_level": "warning",
  "items": [
    {
      "name": "強風注意報",
      "level": "注意報",
      "status": "継続"
    },
    {
      "name": "波浪警報",
      "level": "警報",
      "status": "継続"
    }
  ]
}
```

結果:

- 八丈町の警報・注意報を取得: PASS

## 直接関数確認

`fetch_warnings_for_pref("130000", "東京都")` と `filter_alerts_for_city()` を直接確認。

```json
{
  "map_adachi": "1312100",
  "map_chofu": "1320800",
  "map_oshima": "1336100",
  "adachi": [
    {
      "area_code": "1312100",
      "kind": "強風注意報",
      "status": "継続"
    }
  ],
  "chofu": [],
  "oshima": [
    {
      "area_code": "1336100",
      "kind": "強風注意報",
      "status": "警報から注意報"
    },
    {
      "area_code": "1336100",
      "kind": "波浪警報",
      "status": "継続"
    }
  ]
}
```

結果:

- city → class20 code 解決: PASS
- class20 既知時に class10 へフォールバックしない: PASS

## UI確認

Playwrightプローブで情報タブを確認した。

```text
天気カード表示: PASS
警報・注意報欄表示: PASS
調布市表示: 警報・注意報なし
降水表示: 現在: 降水なし
標高表示: 36 m
レイヤー/凡例/地震タブ DOM 存在: PASS
console error / page error: なし
```

取得失敗時モック:

```text
警報・注意報：取得できません
気象情報を取得できません
```

取得失敗時に `警報・注意報なし` と断定しない表示を確認した。

スクリーンショット:

```text
tasks/weather_warning_info_tab.png
```

## 回帰確認

実行コマンド:

```bash
python3 -m compileall backend
node --check frontend/js/location-info-panel.js
node --check frontend/js/weather.js
node --check frontend/js/weather-card.js
docker compose restart backend
docker compose ps
curl -s http://127.0.0.1:8000/health
curl -s http://127.0.0.1:8000/api/live/summary
node /private/tmp/weather_warning_info_tab_probe.js
```

結果:

- backend compile: PASS
- JS syntax: PASS
- backend health: PASS
- Docker services: backend/frontend/martin/osrm 起動確認
- `/live` summary: PASS
- `/live` UI基本表示: PASS
- 情報タブ基本表示: PASS

補足:

- `frontend/js/jma-warning.js` は存在しないため対象外。

## 残メモ

`WeatherAlertItem.area_name` は class20 item でも `東京都` になるケースがある。ただし `/api/weather/warnings` の `area_name` は reverse geocode の city を優先しており、UI/API表示上の主問題ではない。将来的には `area_code_names` に class20 名も持たせると、内部ログや `/api/weather/alerts/current` の可読性が上がる。

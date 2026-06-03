# JMA r8 警報・注意報実装 Codex検証

## 判定

FAIL

`warning/data/r8/{pref_code}.json` への切替自体は成功しており、足立区 `1312100` の `強風注意報` は r8 データから抽出できている。しかし、現在地が市区町村まで判定できている場合でも、最終APIは `class20Items` ではなく `class10Items` 相当の `東京地方` を返している。そのため、足立区・調布市に `波浪注意報` が混入し、調布市でも強風注意報が表示される。

## 検証日時

2026-06-03

## 検証対象

- `backend/app/services/jma_weather_adapter.py`
- `backend/app/services/weather_alert_service.py`
- `GET /api/weather/alerts/current`
- `GET /api/weather/warnings`
- 情報タブ「天気」カード

## 実装確認

コンテナ内の `jma_weather_adapter.py` で以下を確認した。

```text
_JMA_WARNING_BASE = https://www.jma.go.jp/bosai/warning/data/r8/{pref_code}.json
_JMA_WARNING_LEGACY_BASE = https://www.jma.go.jp/bosai/warning/data/warning/{pref_code}.json
_parse_r8_payload() あり
fetch_warnings_for_pref() は r8 優先、失敗時 legacy fallback
```

backend 再起動後、r8 実装がHTTP APIに反映されていることを確認した。

## コマンド確認

```bash
python3 -m compileall backend
node --check frontend/js/location-info-panel.js
node --check frontend/js/weather.js
node --check frontend/js/weather-card.js
docker compose restart backend
curl -s http://127.0.0.1:8000/health
```

結果:

- backend compile: PASS
- JS syntax: PASS
- backend health: PASS
- Docker services: backend/frontend/martin/osrm 起動確認

補足:

- `frontend/js/jma-warning.js` は存在しない。

## 足立区API確認

座標:

```text
lat=35.775
lon=139.804
```

### `/api/weather/alerts/current`

```json
{
  "status": "ok",
  "severity": "advisory",
  "location": {
    "area_name": "東京都",
    "pref_code": "130000",
    "city": "足立区"
  },
  "alerts": [
    {
      "area_code": "130010",
      "area_name": "東京地方",
      "kind": "強風注意報",
      "status": "継続",
      "raw_code": "15"
    },
    {
      "area_code": "130010",
      "area_name": "東京地方",
      "kind": "波浪注意報",
      "status": "継続",
      "raw_code": "16"
    }
  ]
}
```

### `/api/weather/warnings`

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
    },
    {
      "name": "波浪注意報",
      "level": "注意報",
      "status": "継続"
    }
  ]
}
```

足立区の強風注意報は表示されるようになった。ただし、JMA画面では足立区の波浪は `---` であり、`波浪注意報` の混入は不適合。

## 調布市API確認

座標:

```text
lat=35.65
lon=139.54
```

### `/api/weather/warnings`

```json
{
  "ok": true,
  "area_name": "調布市",
  "has_warning": false,
  "max_level": "advisory",
  "items": [
    {
      "name": "強風注意報",
      "level": "注意報",
      "status": "継続"
    },
    {
      "name": "波浪注意報",
      "level": "注意報",
      "status": "継続"
    }
  ]
}
```

r8 抽出結果では調布市 `1320800` のアクティブ項目は空だった。にもかかわらず、APIは `東京地方` の `強風注意報` と `波浪注意報` を返している。

## r8抽出結果

`fetch_warnings_for_pref("130000", "東京都")` の直接確認:

```json
{
  "all_count": 53,
  "adachi_1312100": [
    {
      "area_code": "1312100",
      "area_name": "東京都",
      "kind": "強風注意報",
      "status": "継続",
      "raw_code": "15",
      "updated_at": "2026-06-03T18:13:00+09:00"
    }
  ],
  "chofu_1320800": [],
  "tokyo_130010": [
    {
      "area_code": "130010",
      "area_name": "東京地方",
      "kind": "強風注意報",
      "status": "継続",
      "raw_code": "15"
    },
    {
      "area_code": "130010",
      "area_name": "東京地方",
      "kind": "波浪注意報",
      "status": "継続",
      "raw_code": "16"
    }
  ]
}
```

重要点:

- r8 データから足立区 `1312100` の `強風注意報` は抽出できている。
- 調布市 `1320800` はアクティブ項目なしとして処理されている。
- `filter_alerts_for_city(items, "足立区")` と `filter_alerts_for_city(items, "調布市")` は、どちらも `東京地方` の class10 項目を返している。

## UI確認

Playwrightプローブで情報タブを確認した。

```text
天気カード表示: PASS
警報・注意報欄表示: PASS
取得失敗時の非断定表示: PASS
console error / page error: なし
```

ただし、調布市固定UIで以下が表示された。

```text
強風注意報継続
波浪注意報継続
```

r8 抽出上、調布市はアクティブ項目なしのため不一致。

スクリーンショット:

```text
tasks/weather_warning_info_tab.png
```

## 島しょ部確認

### 大島町

```json
{
  "area_name": "大島町",
  "has_warning": true,
  "max_level": "warning",
  "items": [
    {
      "name": "強風注意報",
      "status": "警報から注意報"
    },
    {
      "name": "波浪警報",
      "status": "継続"
    }
  ]
}
```

### 八丈町

```json
{
  "area_name": "八丈町",
  "has_warning": true,
  "max_level": "warning",
  "items": [
    {
      "name": "強風注意報",
      "status": "継続"
    },
    {
      "name": "波浪警報",
      "status": "継続"
    }
  ]
}
```

島しょ部の警報・注意報はr8の最新状況を返している。

## 原因

`_parse_r8_payload()` は `class10Items` と `class20Items` を両方 `WeatherAlertItem` に変換しているが、class20 の区域名が `_AREA_CODE_NAME` に存在しないため、足立区 `1312100` などの `area_name` が `東京都` になる。

一方、`filter_alerts_for_city()` は `city_name` から `area_city_keywords` を使って `東京地方` を特定し、`area_name == "東京地方"` の項目だけ返す。

結果:

```text
足立区 -> matched_areas=["東京地方"] -> class10Items(130010) を採用
調布市 -> matched_areas=["東京地方"] -> class10Items(130010) を採用
```

本来、市区町村が判定できている場合は `class20Items.areaCode` を優先すべきだが、現在は class20 の `areaCode` と city の対応を使っていない。

## PASSしている点

- 旧URLではなく `warning/data/r8/{pref_code}.json` を取得している。
- r8 root array をparseできている。
- 足立区 `1312100` の `強風注意報` を抽出できている。
- `解除` / `発表警報・注意報はなし` はアクティブ表示から除外されている。
- 取得失敗時UIは `警報・注意報：取得できません` となる。
- backend health、`/live` summary、既存UI基本表示は維持。

## FAIL要因

- 市区町村まで判定できているのに、`class20Items` ではなく `class10Items` を返している。
- 足立区に `波浪注意報` が混入している。
- 調布市に `強風注意報` / `波浪注意報` が混入している。

## 修正方針案

今回は検証のみで実装変更していない。修正する場合は以下が必要。

1. `common/const/area.json` またはローカル registry に class20 code/name 対応を追加する。
2. 逆ジオコードで得た city から class20 code を解決する。
3. 市区町村コードが解決できた場合は、`class20Items.areaCode == city_class20_code` の項目を優先して返す。
4. class20 が解決できない場合のみ class10 フォールバックする。
5. 波浪・高潮など、市区町村ごとの対象外判定は class20 側または `no_wave_tide.json` 相当で扱う。

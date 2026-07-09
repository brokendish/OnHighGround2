# Phase 8-A Open-Meteo JMA 全国気象ミニテロップ MVP 検証

## 判定

PASS with notes

主要要件は満たしている。Open-Meteo JMA は backend proxy 経由で利用され、frontend から `api.open-meteo.com` への直接アクセスはない。地点マスタ、表示順、天気コード正規化、flags、stale/unavailable 表示、専用 E2E は確認済み。

notes:

- 指示書の「対象画面」は `/live` と記載されているが、実装と専用 E2E の対象は `frontend/live/stream.html`、つまり `/live/stream`。`/live` は影響なしとして確認した。
- 実通信時点では Open-Meteo JMA の `precipitation_probability` が全地点で `null` だった。フィールド取得・レスポンス項目・flags 境界値は unit/E2E mock で確認済み。

## 検証日時

2026-07-10 00:24 JST

## 確認したファイル

- `docs/live/DEVELOPMENT_GUARDRAILS.md`
- `backend/main.py`
- `backend/app/api/live_weather_jma.py`
- `backend/app/services/live_weather_jma_service.py`
- `backend/app/data/weather_points_jma.json`
- `frontend/live/stream.html`
- `frontend/js/live-stream/live-stream-weather-widget.js`
- `frontend/css/live/live-weather-ticker.css`
- `e2e/live-stream-weather-ticker.spec.js`
- `tests/test_live_weather_jma_service.py`

## 対象差分

主な Phase 8-A 関連差分:

- `backend/app/api/live_weather_jma.py`: `GET /api/live/weather/jma/prefectures`
- `backend/app/services/live_weather_jma_service.py`: Open-Meteo `/v1/jma` 取得、正規化、cache/stale/unavailable
- `backend/app/data/weather_points_jma.json`: 都道府県代表地点 + 北海道複数地点
- `frontend/live/stream.html`: 右カラム上部に全国気象パネル追加
- `frontend/js/live-stream/live-stream-weather-widget.js`: backend API 取得、ページ送り、stale/unavailable 表示
- `frontend/css/live/live-weather-ticker.css`: 小型テロップ、天気バッジ、数値強調
- `e2e/live-stream-weather-ticker.spec.js`: 専用 Playwright 検証
- `tests/test_live_weather_jma_service.py`: 天気コード・flags・cache の unit test

作業ツリーには Phase 7-A.5/鉄道関連の既存未コミット差分も含まれているため、本検証では Phase 8-A 関連ファイルを中心に確認した。

## 実行コマンド

```bash
sed -n '1,240p' docs/live/DEVELOPMENT_GUARDRAILS.md
sed -n '1,620p' 'tasks/stream/Phase 8-A: Open-Meteo JMA 全国気象ミニテロップ MVP_CODEX.md'
git status --short
git diff --stat
git diff --name-only
rg -n "api\\.open-meteo\\.com|open-meteo\\.com" frontend backend
rg -n "OPEN_METEO_URL|/v1/jma|hourly=|timezone=Asia|precipitation_probability|temperature_2m|relative_humidity_2m|weather_code" backend/app/services/live_weather_jma_service.py
rg -n "include_router\\(live_weather_jma_router\\)|live_weather_jma" backend/main.py
jq 'length' backend/app/data/weather_points_jma.json
jq '[.[] | select(.pref_code=="01") | .point_name]' backend/app/data/weather_points_jma.json
jq '[.[:12][] | {point_name,display_order}], [.[-12:][] | {point_name,display_order}]' backend/app/data/weather_points_jma.json
python3 -m json.tool backend/app/data/weather_points_jma.json
venv/bin/python -c "import json; p=json.load(open('backend/app/data/weather_points_jma.json')); print({'count':len(p),'pref_codes':len({x['pref_code'] for x in p}),'hokkaido':[x['point_name'] for x in p if x['pref_code']=='01'],'dup_ids':sorted({x['id'] for x in p if [y['id'] for y in p].count(x['id'])>1}),'missing_required':sum(1 for x in p if not all(k in x for k in ['id','pref_code','pref_name','point_name','lat','lon','display_order'])),'display_order_numeric':all(isinstance(x.get('display_order'),(int,float)) for x in p),'sorted':all(p[i]['display_order']<=p[i+1]['display_order'] for i in range(len(p)-1))})"
node --check frontend/js/live-stream/live-stream-weather-widget.js
curl -s http://127.0.0.1:8000/api/live/weather/jma/prefectures
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/live/stream
venv/bin/python -m pytest tests/test_live_weather_jma_service.py
venv/bin/python -m pytest tests/test_live_train_service.py tests/test_live_weather_jma_service.py
npx playwright test e2e/live-stream-weather-ticker.spec.js
npx playwright test e2e/live-stream-railway-phase5b.spec.js e2e/live-stream.spec.js
date '+%Y-%m-%d %H:%M %Z'
```

## backend API確認

`GET /api/live/weather/jma/prefectures` は 200 OK で応答した。

実通信の概要:

- `status`: `ok`
- `source`: `Open-Meteo JMA`
- `forecast_time`: `2026-07-10T00:00:00+09:00`
- `fetched_at`: `2026-07-10T00:16:39.545237+09:00`
- `cache_status`: `fresh`
- `items`: 53件
- 先頭: 那覇 `display_order=10`
- 末尾: 稚内 `display_order=530`
- 北海道: 函館、帯広、釧路、札幌、旭川、網走、稚内

Open-Meteo 利用確認:

- backend service は `https://api.open-meteo.com/v1/jma` を使用。
- `hourly=weather_code,temperature_2m,relative_humidity_2m,precipitation_probability` を指定。
- `timezone=Asia%2FTokyo` を指定。
- `frontend` 配下に `api.open-meteo.com` 直接参照なし。
- `backend` 側の直接参照は `backend/app/services/live_weather_jma_service.py` のみ。

## 地点マスタ確認

`backend/app/data/weather_points_jma.json` を確認。

- 地点数: 53
- `pref_code` 種別: 47
- 46都府県は各1地点、北海道は7地点
- 北海道7地点: 函館、帯広、釧路、札幌、旭川、網走、稚内
- 必須キー欠落: 0
- `id` 重複: 0
- `display_order` は数値
- ファイル上の並びは `display_order` 昇順

表示順の代表確認:

- 先頭側: 那覇、鹿児島、宮崎、長崎、熊本、大分、佐賀、高知、福岡、松山、徳島、山口
- 末尾側: 山形、仙台、盛岡、秋田、青森、函館、帯広、釧路、札幌、旭川、網走、稚内

南から北の順序として妥当。

## 天気コード・flags確認

`tests/test_live_weather_jma_service.py` で以下を確認済み。

- `0,1,2 -> 晴`
- `3 -> 曇`
- `45,48 -> 霧`
- `51,53,55,56,57,61,63,65,66,67,80,81,82 -> 雨`
- `71,73,75,77,85,86 -> 雪`
- `95,96,99 -> 雷`
- 不明値、`None`、非数値 -> `不明`

flags 境界値も確認済み。

- 降水確率 `69=false`, `70=true`
- 気温 `34.9=false`, `35.0=true`
- 気温 `0.0=true`, `0.1=false`
- 湿度 `84=false`, `85=true`

## cache / stale / unavailable確認

unit test と E2E mock で確認。

- fresh: 正常取得時に `cache_status=fresh`
- stale: 取得失敗時に有効な前回 cache があれば `cache_status=stale`、UI に `更新遅延`
- unavailable: cache なし、または期限超過時に `cache_status=unavailable`、UI に `更新停止中`

frontend は backend 到達失敗時に初回のみ unavailable 表示へ落とし、既存データがある場合は前回状態を維持する。継続的な console error は専用 E2E では検出されなかった。

## UI確認結果

対象実装は `/live/stream`。

- `frontend/live/stream.html` の右カラム先頭に `data-panel="weather"` パネルあり。
- 鉄道 `data-panel="railway"`、潮位 `data-panel="tide"` より前に配置。
- ヘッダーは `全国気象` と `Open-Meteo JMA` 出典を表示。
- `forecast_time` / `fetched_at` は `HH:mm時点 / HH:mm取得` として表示。
- 9件単位、3列 x 3行で表示。
- `weatherSpeed=test` 時は 300ms、通常は 10秒でページ送り。
- 天気バッジ class は `sunny/cloudy/rain/snow/thunder/fog/unknown` で分岐。
- 数値強調 class は降水確率、高温、低温、高湿度に対応。

狭幅 2列については CSS に専用 media query は見当たらず、現状の検証は E2E の通常 viewport での 3列確認まで。`/live/stream` は配信用固定レイアウト色が強いため notes 扱い。

## E2E確認結果

```text
npx playwright test e2e/live-stream-weather-ticker.spec.js
11 passed
```

確認済み項目:

- `/live/stream` で全国気象パネル表示
- 右カラムで鉄道・潮位より前
- 出典表示
- JST `HH:mm時点 / HH:mm取得`
- 地点セル、天気バッジ、気温、湿度、降水確率
- 降水確率70%以上、高温、低温、高湿度の強調 class
- ページ送り
- 北海道地点のページング内表示
- stale 表示
- unavailable 表示
- frontend 直接 Open-Meteo 呼び出しなし
- `/live` への影響なし

## 回帰確認結果

```text
venv/bin/python -m pytest tests/test_live_weather_jma_service.py
23 passed

venv/bin/python -m pytest tests/test_live_train_service.py tests/test_live_weather_jma_service.py
82 passed

npx playwright test e2e/live-stream-railway-phase5b.spec.js e2e/live-stream.spec.js
53 passed
```

HTTP 確認:

- `curl -I http://127.0.0.1:8080/live`: 200 OK
- `curl -I http://127.0.0.1:8080/live/stream`: 200 OK

JS 構文確認:

- `node --check frontend/js/live-stream/live-stream-weather-widget.js`: PASS

## 問題・再現手順

致命的な問題は検出しなかった。

軽微な notes:

1. 指示書は `/live` 右パネルと書いているが、実装は `/live/stream` 右カラム。`/live` には全国気象 UI は追加されていない。
2. 実通信レスポンスでは `precipitation_probability_percent` が `null`。Open-Meteo JMA 側データに依存するため、この時点の実 API では降水確率の実値表示までは確認できなかった。
3. 狭幅時 2列表示の専用 CSS は未確認。専用 E2E も通常 viewport 中心。

## 総括

Phase 8-A の MVP としては利用可能。backend proxy、地点マスタ、南北順、時刻表示、badge/flags、stale/unavailable、既存 `/live/stream` 回帰はいずれも確認できた。上記 notes は仕様表記・実データ依存・狭幅表示の確認範囲に関するもの。

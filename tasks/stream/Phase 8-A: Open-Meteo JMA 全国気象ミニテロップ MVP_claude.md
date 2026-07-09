# Claude用実装指示書

## Phase 8-A: Open-Meteo JMA 全国気象ミニテロップ MVP

## 目的

`/live` 画面の右パネル上部に、Open-Meteo JMA API を利用した「全国気象」ミニテロップを追加する。

この機能は、全国災害ビューア LIVE における補助的な気象概況表示であり、警報・キキクル・地震・津波・鉄道・水位などの主役情報を妨げない小型表示とする。

## 基本方針

* Open-Meteo の `/v1/jma` を利用する。
* frontend から Open-Meteo を直接叩かず、backend proxy + cache 経由で取得する。
* 表示位置は `/live` 右パネル上部。
* 表示名は `全国気象`。
* 右パネル上部の小型カード、または小型テロップとして実装する。
* 鉄道情報、潮位・水位カードの高さを調整し、その上に配置する。
* 天気情報は災害判断の主情報ではなく、補助情報として扱う。
* JMA警報・注意報やキキクル等と混同しないよう、出典を `Open-Meteo JMA` と表示する。

## 表示する情報

各地点ごとに以下を表示する。

* 地点名
* 天気種別
* 気温
* 湿度
* 降水確率

表示例:

```text
全国気象 23:00時点 / 23:05取得

那覇   晴 30℃
湿88  雨30

鹿児島 雨 27℃
湿91  雨80

東京   曇 28℃
湿76  雨40
```

## 更新時刻表示

ヘッダーには以下の形式で表示する。

```text
全国気象 HH:mm時点 / HH:mm取得
```

意味:

* `HH:mm時点`: Open-Meteo hourly forecast の対象時刻
* `HH:mm取得`: backend が Open-Meteo から取得した時刻

例:

```text
全国気象 23:00時点 / 23:05取得
```

取得遅延時:

```text
全国気象 22:00時点 / 22:10取得  更新遅延
```

長時間取得不能時:

```text
全国気象 更新停止中 / 前回 21:40取得
```

## 取得地点

都道府県の代表地点を基本とする。
北海道は最初から複数地点を含める。

### 地点数

* 46都府県: 各1地点
* 北海道: 複数地点
* 合計: 約53地点

### 北海道の地点

北海道は以下の7地点を含める。

* 函館
* 札幌
* 旭川
* 帯広
* 釧路
* 網走
* 稚内

## 表示順

表示順は **南から北** に固定する。

目的:

* テロップ表示時の流れを安定させる
* 後から地点を追加しても表示タイミングが崩れにくくする
* 全国を南から北へスキャンするような視認性を作る

地点マスタには必ず `display_order` を持たせる。

例:

```json
{
  "id": "okinawa_naha",
  "pref_code": "47",
  "pref_name": "沖縄県",
  "point_name": "那覇",
  "lat": 26.2124,
  "lon": 127.6792,
  "region": "okinawa",
  "display_order": 10
}
```

北海道も同一 `pref_code: "01"` で複数地点を定義する。

例:

```json
{
  "id": "hokkaido_hakodate",
  "pref_code": "01",
  "pref_name": "北海道",
  "point_name": "函館",
  "lat": 41.7687,
  "lon": 140.7288,
  "region": "hokkaido",
  "display_order": 470
}
```

```json
{
  "id": "hokkaido_sapporo",
  "pref_code": "01",
  "pref_name": "北海道",
  "point_name": "札幌",
  "lat": 43.0618,
  "lon": 141.3545,
  "region": "hokkaido",
  "display_order": 480
}
```

## Open-Meteo取得項目

Open-Meteo `/v1/jma` から以下を取得する。

* `weather_code`
* `temperature_2m`
* `relative_humidity_2m`
* `precipitation_probability`

timezone は `Asia/Tokyo` とする。

取得URL例:

```text
https://api.open-meteo.com/v1/jma
  ?latitude=35.6895
  &longitude=139.6917
  &hourly=weather_code,temperature_2m,relative_humidity_2m,precipitation_probability
  &timezone=Asia/Tokyo
  &forecast_days=1
```

複数地点取得に対応できる場合は、緯度・経度をカンマ区切りでまとめて取得してよい。
ただし URL 長やレスポンス管理に問題が出る場合は、backend 側で 10〜15地点程度に分割取得してよい。

## backend API案

新規API例:

```text
GET /api/live/weather/jma/prefectures
```

レスポンス例:

```json
{
  "status": "ok",
  "source": "Open-Meteo JMA",
  "forecast_time": "2026-07-09T23:00:00+09:00",
  "fetched_at": "2026-07-09T23:05:12+09:00",
  "cache_status": "fresh",
  "items": [
    {
      "id": "okinawa_naha",
      "pref_code": "47",
      "pref_name": "沖縄県",
      "point_name": "那覇",
      "display_order": 10,
      "weather_code": 3,
      "weather_category": "cloudy",
      "weather_label": "曇",
      "temperature_c": 30.2,
      "humidity_percent": 88,
      "precipitation_probability_percent": 70,
      "flags": {
        "precipitation_high": true,
        "temperature_hot": false,
        "temperature_cold": false,
        "humidity_high": true
      }
    }
  ]
}
```

## キャッシュ仕様

backend 側でキャッシュする。

推奨:

* 通常キャッシュ: 20分
* 取得失敗時: stale cache を最大2時間利用
* 2時間を超える古いデータは更新停止扱い

cache_status の例:

```text
fresh
stale
unavailable
```

### fresh

通常表示。

```text
全国気象 23:00時点 / 23:05取得
```

### stale

前回データを表示し、更新遅延バッジを出す。

```text
全国気象 22:00時点 / 22:10取得  更新遅延
```

### unavailable

データ表示は抑制、または薄く表示し、更新停止中と表示する。

```text
全国気象 更新停止中 / 前回 21:40取得
```

取得不能を「なし」と誤表示しないこと。

## 天気コード正規化

Open-Meteo の `weather_code` を UI 用カテゴリへ正規化する。

MVPでは以下のカテゴリにまとめる。

* 晴
* 曇
* 雨
* 雪
* 雷
* 霧
* 不明

分類案:

```text
0:
  晴

1, 2:
  晴

3:
  曇

45, 48:
  霧

51, 53, 55, 56, 57:
  雨

61, 63, 65, 66, 67, 80, 81, 82:
  雨

71, 73, 75, 77, 85, 86:
  雪

95, 96, 99:
  雷

その他:
  不明
```

## 天気カラーバッジ

天気種別はカラーバッジとして表示する。
文字だけではなく、パッと見て天気が認識できることを重視する。

表示ラベル:

* 晴
* 曇
* 雨
* 雪
* 雷
* 霧
* 不明

色方針:

```text
晴  → 黄・橙系
曇  → グレー系
雨  → 青系
雪  → 水色・白系
雷  → 紫・黄系
霧  → 薄グレー系
不明 → 暗めグレー
```

注意:

* 色は強くしすぎない。
* キキクル、警報、津波、鉄道障害などの重要色と競合しないよう、彩度は控えめにする。
* 天気バッジは主役ではなく、補助情報として見える程度に抑える。

## 数値バッジ

以下の条件では数値を強調表示する。

```text
降水確率 70%以上 → 青系強調
気温 35℃以上 → 高温注意
気温 0℃以下 → 低温注意
湿度 85%以上 → 蒸し暑さ/不快感の補助
```

flag名案:

```text
precipitation_high
temperature_hot
temperature_cold
humidity_high
```

表示例:

```text
鹿児島 雨 27℃
湿91  雨80
```

この場合:

* `雨` 天気バッジ: 青系
* `湿91`: 高湿度強調
* `雨80`: 降水確率高強調

## frontend UI

### 配置

`/live` 右パネル最上部へ追加する。

構成イメージ:

```text
右パネル
├─ 全国気象 ミニテロップ
├─ 鉄道情報
├─ 潮位・水位
└─ その他
```

既存の鉄道情報、潮位・水位カードは高さを少し圧縮する。

ただし、災害・障害発生時の重要カードの視認性は損なわないこと。

### 表示形式

2列〜3列の縦テロップ表示とする。

デスクトップ右パネル:

```text
3列 × 3行 = 9地点 / ページ
```

狭幅またはモバイル:

```text
2列 × 4行 = 8地点 / ページ
```

地点数が約53地点のため、複数ページに分けて表示する。

### ページ送り

8〜10秒ごとに次ページへ切り替える。

推奨:

```text
10秒ごと
```

理由:

* YouTube配信でも読み取りやすい
* 速すぎると視認性が落ちる
* 災害情報画面として落ち着いた表示になる

ページ送りは `display_order` に従う。
最終ページまで表示したら先頭に戻る。

## 表示カード例

```text
全国気象 23:00時点 / 23:05取得

那覇   晴 30℃   鹿児島 雨 27℃   宮崎   曇 29℃
湿88  雨30      湿91  雨80      湿79  雨40

福岡   雷 26℃   高知   雨 28℃   大阪   晴 31℃
湿86  雨90      湿84  雨70      湿70  雨20

東京   曇 28℃   仙台   雨 23℃   函館   曇 20℃
湿76  雨40      湿82  雨70      湿74  雨30
```

## ファイル名案

既存構成に合わせて調整してよいが、以下のような分離を推奨する。

backend:

```text
backend/app/services/live_weather_jma_service.py
backend/app/api/live_weather_jma.py
backend/app/data/weather_points_jma.json
```

frontend:

```text
frontend/js/live/live-weather-ticker.js
frontend/css/live/live-weather-ticker.css
```

既存の `/live` モジュール構成により適切な場所へ配置すること。

## エラー時の扱い

以下を守ること。

* 取得不能を「天気なし」と表示しない。
* stale cache があれば stale として表示する。
* stale cache もない場合は「更新停止中」とする。
* console error を出し続けない。
* `/live` 全体の初期化を妨げない。
* Open-Meteo 側の障害で `/live` が落ちないようにする。

## 非目標

Phase 8-A では以下は対象外。

* 地図上への天気アイコン表示
* 市区町村単位の天気取得
* 1時間ごとの予報グラフ
* 週間予報
* JMA警報・注意報との統合判定
* キキクルとの危険度合成
* ユーザー任意地点の検索
* 現在地連動

## 受け入れ条件

* `/live` 右パネル上部に `全国気象` が表示される。
* Open-Meteo `/v1/jma` のデータを backend proxy 経由で取得している。
* frontend が Open-Meteo を直接叩いていない。
* 都道府県代表地点が表示される。
* 北海道は複数地点が表示される。
* 表示順が南から北で固定されている。
* `全国気象 HH:mm時点 / HH:mm取得` が表示される。
* 天気種別がカラーバッジで表示される。
* 降水確率70%以上、気温35℃以上、気温0℃以下、湿度85%以上が強調される。
* 2列〜3列の縦テロップとして表示される。
* 8〜10秒程度でページ送りされる。
* stale cache / 更新遅延 / 更新停止中の表示ができる。
* `/live` の既存主要機能、鉄道情報、潮位・水位、地震、キキクル、雨雲表示を壊さない。

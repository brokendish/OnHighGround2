# JMA警報・注意報ページ 最新データ取得元調査

## 判定

別URLへ切替推奨。

OnHighGround2 が現在参照している `https://www.jma.go.jp/bosai/warning/data/warning/130000.json` は、2026-06-03 時点で公式ページの表示と同期していない。JMA公式ページは実際には `https://www.jma.go.jp/bosai/warning/data/r8/130000.json` を Fetch しており、このレスポンスに 2026-06-03 の最新警報・注意報と足立区 `1312100` の強風注意報が含まれている。

## 調査対象

- `https://www.jma.go.jp/bosai/warning/#area_type=offices&area_code=130000&lang=ja&timeline_efilter=all&timeline_lfilter=all`
- `https://www.jma.go.jp/bosai/warning/#area_type=class20s&area_code=1312100&lang=ja&timeline_efilter=all&timeline_lfilter=all`

Playwright でページを開き、request / response / websocket を記録した。直接比較用に `curl -I` と no-cache 相当の直接 Fetch も実施した。

## ページが実際に読んでいるURL

主要通信:

```text
GET https://www.jma.go.jp/bosai/warning/
GET https://www.jma.go.jp/bosai/common/const/area.json
GET https://www.jma.go.jp/bosai/common/const/contents.json
GET https://www.jma.go.jp/bosai/warning/const/no_wave_tide.json
GET https://www.jma.go.jp/bosai/warning/const/with_tidal_area.json
GET https://www.jma.go.jp/bosai/flood/const/no_flood.json
GET https://www.jma.go.jp/bosai/warning/const/explain.html
GET https://www.jma.go.jp/bosai/warning_timeline/const/explain.html
GET https://www.jma.go.jp/bosai/probability/const/explain.txt
GET https://www.jma.go.jp/bosai/probability/const/week_area05.json
GET https://www.jma.go.jp/bosai/warning/data/r8/130000.json
GET https://www.jma.go.jp/bosai/warning_timeline/data/130000.json
GET https://www.jma.go.jp/bosai/flood/data/r8/flood_xml.json
GET https://www.jma.go.jp/bosai/probability/data/probability/r8/130000.json
GET https://www.jma.go.jp/bosai/timecard.txt
```

従来の `https://www.jma.go.jp/bosai/warning/data/warning/130000.json` は、公式ページ表示時のNetwork通信では読み込まれなかった。

## JSONレスポンス一覧

### `warning/data/r8/130000.json`

```text
status: 200
resourceType: fetch
content-type: application/json
last-modified: Wed, 03 Jun 2026 09:17:37 GMT
cache-control: max-age=60
root: array
length: 5
has 2026-06-03: true
has 18:16: true
has 1312100: true
has 強風/code 15: true
```

公式ページの警報・注意報表示の主データ。

### `warning_timeline/data/130000.json`

```text
status: 200
resourceType: fetch
content-type: application/json
last-modified: Wed, 03 Jun 2026 07:57:13 GMT
reportDatetime: 2026-06-03T17:00:00+09:00
targetDatetime: 2026-06-03T18:00:00+09:00
has 1312100: true
has code 15: true
```

時系列・早期注意情報寄りのデータ。現在発令中一覧の一次取得元としては `warning/data/r8/130000.json` の方が近い。

### `common/const/area.json`

```text
status: 200
resourceType: xhr
content-type: application/json
last-modified: Wed, 03 Jun 2026 02:45:19 GMT
has 足立区: true
has 1312100: true
```

地域名・区域コード解決用。

### その他

- `warning/const/no_wave_tide.json`: 波浪・高潮の対象外地域定義。`1312100` を含む。
- `warning/const/with_tidal_area.json`: 潮位関連区域定義。
- `flood/data/r8/flood_xml.json`: 洪水関連XMLメタデータ。
- `probability/data/probability/r8/130000.json`: 早期注意情報系。

## WebSocket / EventSource

なし。

Playwright の `websocket` イベントは発火せず、`resourceType=eventsource` のリクエストもなかった。公式ページは通常の Fetch / XHR でデータを取得している。

## 最新更新時刻を含むデータ

公式ページ本文では以下のシグナルを確認した。

```text
has 足立区: true
has 強風: true
has 2026年06月03日: true
has 18時16分: true
```

`warning/data/r8/130000.json` には以下が含まれる。

```text
reportDatetime: 2026-06-03T18:16:00+09:00
controlDatetime: 2026-06-03T09:16:34Z
dataTypeCode: VPWW56
```

また、足立区の強風注意報を含むレコードは以下。

```text
reportDatetime: 2026-06-03T18:13:00+09:00
controlDatetime: 2026-06-03T09:13:01Z
dataTypeCode: VPWW58
headlineText: 東京地方、伊豆諸島北部、伊豆諸島南部では、強風に注意してください。
```

## 足立区 `1312100` の強風注意報

`warning/data/r8/130000.json` の `reportDatetime=2026-06-03T18:13:00+09:00` レコードに含まれている。

抜粋:

```json
{
  "areaCode": "1312100",
  "kinds": [
    {
      "code": "15",
      "status": "継続",
      "properties": [
        {
          "type": "風危険度",
          "significancyPart": {
            "locals": [
              {
                "code": "20"
              }
            ]
          }
        },
        {
          "type": "風"
        }
      ]
    }
  ]
}
```

`code: "15"` は強風注意報、`status: "継続"`。

## 従来URLとの差分

### 旧URL

```text
URL: https://www.jma.go.jp/bosai/warning/data/warning/130000.json
last-modified: Thu, 28 May 2026 01:17:15 GMT
reportDatetime: 2026-05-28T10:16:00+09:00
bytes: 約12KB
```

足立区:

```json
{
  "code": "1312100",
  "warnings": [
    {
      "status": "発表警報・注意報はなし"
    }
  ]
}
```

### 公式ページが読む新URL

```text
URL: https://www.jma.go.jp/bosai/warning/data/r8/130000.json
last-modified: Wed, 03 Jun 2026 09:17:37 GMT
reportDatetime entries: 2026-06-03T16:10, 18:16, 18:13, 18:13, 16:08
bytes: 約25KB-31KB
```

足立区:

```json
{
  "areaCode": "1312100",
  "kinds": [
    {
      "code": "15",
      "status": "継続"
    }
  ]
}
```

## 採用可能な取得元候補

### 第一候補

```text
https://www.jma.go.jp/bosai/warning/data/r8/{office_code}.json
```

理由:

- JMA公式ページが実際にFetchしている。
- `2026-06-03` の最新データを含む。
- 足立区 `1312100` の強風注意報を含む。
- `common/const/area.json` と組み合わせれば区域名解決が可能。

### 補助候補

```text
https://www.jma.go.jp/bosai/common/const/area.json
```

区域コードと名称の解決に必要。

### 補助候補

```text
https://www.jma.go.jp/bosai/warning_timeline/data/{office_code}.json
```

時系列・今後の見通し用。現在発令中一覧の主ソースにはしない方がよい。

## 採用時のリスク

- `warning/data/r8/{office_code}.json` は公式ページ内部で利用されるJSONであり、API仕様として安定保証されているとは限らない。
- 旧 `warning/{office_code}.json` とは構造が異なる。
  - 旧: object root、`areaTypes[].areas[].warnings`
  - 新: array root、各レコードに `warning.class10Items` / `warning.class20Items`
- 複数レコードが返るため、単純に配列先頭または最新 `reportDatetime` のみを見ると取りこぼす可能性がある。
  - 足立区の強風注意報は `18:13` レコードにあり、同じ配列には `18:16` レコードも存在する。
- `status` は `継続`, `発表`, `警報から注意報`, `解除`, `発表警報・注意報はなし` などが混在するため、状態マージ規則が必要。
- `dataTypeCode` ごとに対象現象が分かれている可能性があるため、現象別に最新状態を合成する必要がある。

## 実装変更が必要な場合の方針案

今回の調査では実装変更しない。ただし採用するなら以下が必要。

1. `warning/data/r8/{pref_code}.json` を新取得元にする。
2. root array を走査し、`warning.class10Items` と `warning.class20Items` を両方読む。
3. 現在地が市区町村まで判定できる場合は `class20Items.areaCode` を優先する。
4. 市区町村判定ができない場合は `class10Items.areaCode` を使う。
5. 同一 `areaCode + warning code` について、`reportDatetime/controlDatetime` と `status` を使って最新状態を合成する。
6. `解除` と `発表警報・注意報はなし` はアクティブ表示から除外する。
7. `common/const/area.json` で `areaCode -> name` を補完する。
8. JMA内部JSON変更時に `ok:false` / `取得できません` へ倒す。

## 調査成果物

生ログ:

```text
/private/tmp/jma_warning_network_investigation_raw.json
```

補助スクリプト:

```text
/private/tmp/jma_warning_network_investigation.js
/private/tmp/jma_warning_direct_probe.js
```

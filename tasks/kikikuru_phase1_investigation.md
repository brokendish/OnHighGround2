# キキクル Phase1 調査結果

調査日: 2026-05-22

## タイルURL

```
https://www.jma.go.jp/bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/{elem}/{z}/{x}/{y}.png
```

- `basetime` = `validtime`（現状は同値）
- `member`: `immed0`（最新）、`immed1`（1時点前）、…
- `elem`:
  - `inund` — 浸水キキクル
  - `land`  — 土砂キキクル
  - `flood` — 洪水キキクル（流域単位）
  - `flood_mesh` — 洪水キキクル（メッシュ）

## 時刻管理ファイル

```
https://www.jma.go.jp/bosai/jmatile/data/risk/targetTimes.json
```

レスポンス例:
```json
[
  {
    "basetime": "20260522111000",
    "validtime": "20260522111000",
    "member": "immed0",
    "elements": ["land", "inund", "flood_mesh", "flood", ...]
  },
  ...
]
```

- 更新間隔: **10分**（…111000, 110000, 105000, …）
- 最新エントリが `immed0`、以降 `immed1`, `immed2`, …

## ズームレベル

| 項目 | 値 |
|------|-----|
| minZoom | 4 |
| maxZoom | 14 |
| maxNativeZoom | 11 |
| zoomUse | 偶数ズームのみデータあり |

雨量レーダー（hrpns）と同様に、奇数ズームでは偶数ズームのタイルをLeafletがCSS拡大して表示する。

## CORS / キャッシュ

| 項目 | 値 |
|------|-----|
| Access-Control-Allow-Origin | `*` → **フロントから直接参照可能** |
| Cache-Control | `max-age=86400` |
| X-Cache | CloudFront |

basetime がURLに含まれるため、10分ごとにURLが変わる。
ブラウザの古いキャッシュが残ることはない（URL自体が更新時刻でユニーク）。

## プロキシ方式の判断

CORS `*` かつ URL がタイムスタンプでユニークなため、**フロント直接参照で問題なし**。
バックエンドプロキシは不要。

## 実装方式

- Leaflet `TileLayer`（偶数ズーム clamp カスタム拡張）
- `targetTimes.json` を10分ごとにポーリングして最新 basetime/member を取得
- 取得失敗時は stale 状態を表示、レイヤー自体は残す

## 参照したプロパティファイル

```
https://www.jma.go.jp/bosai/risk/table/risk.properties__8d3b3a2f96d6ec2be4ea.xml
```

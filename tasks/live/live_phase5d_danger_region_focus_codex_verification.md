# Phase 5-D 危険地域フォーカス機能 検証レポート

## 実施日時

2026-06-03 10:28:38 JST

## Docker状態

`docker compose build`: PASS

`docker compose up -d`: PASS

`docker compose ps`: backend healthy / frontend Up / martin healthy / osrm-walking Up

`/health`: healthy

## 構文確認結果

`python3 -m compileall backend/app`: PASS

`node --check frontend/js/live/*.js`: PASS

`git diff --check`: PASS

## カード確認結果

PASS

- `/live` で危険地域カードが表示された。
- 危険地域アイテムに `lac-danger-clickable` が付与されていた。
- `data-lat`, `data-lng`, `data-label` が設定されていた。
- CSS cursor は `pointer`。

実画面プローブ:

```text
item: 埼玉県付近
class: lac-danger-item lac-danger-danger lac-danger-clickable
cursor: pointer
lat: 35.8569
lng: 139.6489
clickable count: 7
```

## フォーカス確認結果

PASS

- 危険地域クリックで地図中心が対象地域へ移動した。
- `live danger region focus:` の console log を確認した。
- page error / console error は発生しなかった。

実画面プローブ:

```text
before: lat=36.5, lng=137, zoom=5
after:  lat=35.8569, lng=139.6489, zoom=8
log: live danger region focus: label=埼玉県付近 lat=35.8569 lng=139.6489
```

## ズーム確認結果

PASS

- クリック後に zoom が `5` から `8` に変更された。
- 過度なズームアウトは発生していない。
- 実装上は `Math.max(liveMap.getZoom(), 8)` により、現在 zoom より小さくならない。

## 強調表示確認結果

PASS

- クリック後に Leaflet layer が増加した。
- `radius=28`, `color=#ff6b35` の `CircleMarker` を 1 件確認した。
- 強調 ring 表示として確認。

実画面プローブ:

```text
layers: 78 -> 80
circleMarkers: 1
```

## ポップアップ確認結果

PASS

- クリック後に `.leaflet-popup` が表示された。
- ポップアップに地域名とイベント一覧が表示された。

実画面プローブ:

```text
埼玉県付近
キキクル（浸水）
キキクル（洪水）
```

追加 E2E では指定例に近い以下も確認済み:

```text
高知県付近
キキクル（洪水）
雨雲
```

## false-safe確認結果

PASS

- クリックしても `/api/live/summary` の再取得なし。
- `dangerous_areas` / `integrated_dangerous_regions` のデータ変化なし。
- ランキング行数の変化なし。
- 集計値の再計算や API 追加呼び出しは検出されなかった。

実画面プローブ:

```text
summary requests: 1
integrated-specific requests: 0
```

追加 E2E:

- `クリックしても summary は再取得されない（集計変化なし）`: PASS
- `integrated_dangerous_regions のデータは変化しない`: PASS

## Console確認結果

実画面 `/live`: PASS

- console error: 0
- page error: 0

ナビ本体 `/`: PASS

- console error: 0
- page error: 0

## 回帰確認結果

`npx playwright test e2e/live-basic.spec.js e2e/live-earthquake-layer.spec.js e2e/live-sun-moon-card.spec.js e2e/live-tide-layer.spec.js e2e/live-storm-surge.spec.js e2e/live-integrated-regions.spec.js e2e/live-rain-timeline.spec.js e2e/live-danger-focus.spec.js`

結果: PASS

```text
169 passed
0 failed
```

追加 E2E:

- `e2e/live-danger-focus.spec.js`: PASS

## ナビ本体影響確認

PASS

- `http://127.0.0.1:8080/` は正常表示。
- console error / page error なし。
- `/api/live/summary` 自動呼び出しなし。
- `/api/live/*` 自動呼び出しなし。
- 既存ナビ本体ファイルは未変更。

## スクリーンショット

- `tasks/live/live_phase5d_card_before_focus.png`
- `tasks/live/live_phase5d_focus_popup.png`
- `tasks/live/live_phase5d_nav_home.png`

## 最終判定

PASS

理由:

- 危険地域カード、地図フォーカス、ズーム、強調 ring、ポップアップ、false-safe、Console、ナビ本体影響はいずれも PASS。
- 指定回帰 E2E と追加 Phase 5-D E2E を含む 169 件がすべて PASS。

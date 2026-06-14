# Phase 7-A.2 鉄道路線オーバーレイ強化 CODEX検証

## 判定

PASS with notes

## 検証環境

- date: 2026-06-14 23:30:08 JST
- branch: main
- commit: c87fb31
- docker compose:
  - backend: Up / healthy
  - frontend: Up
  - martin: Up / healthy
  - osrm-walking: Up

## 対応内容

- OSM鉄道路線ベースレイヤー `frontend/js/live/live-train-osm-layer.js` を確認。
- ODPT障害路線とOSM路線名の辞書マッチを確認。
- OSMマッチ済み障害路線は路線表示、未一致時は既存 CircleMarker へフォールバックすることを確認。
- 実環境で `https://overpass-api.de/api/interpreter` 直アクセスが `ERR_CONNECTION_REFUSED` になるため、backend proxy `/api/live/trains/osm` を追加。
- backend proxy でも Overpass 不通時は軽量な主要路線フォールバックを返すよう補強。
- 実ODPT Railway IDs に合わせて主要辞書を補正。
  - `MIR.TsukubaExpress`
  - `JR-East.ChuoSobuLocal`
  - `JR-East.SaikyoKawagoe`
  - `JR-East.ShonanShinjuku`
  - `Toei.Arakawa`
  - `Toei.NipporiToneri`
  - `YokohamaMunicipal.Blue/Green`
  - など

## 起動確認

- `python3 -m compileall backend`: PASS
- `docker compose ps`: backend/frontend/martin 起動確認、backend healthy

## 鉄道路線表示

E2E:

- `npx playwright test e2e/live-train-osm-layer.spec.js`: 12 passed

実画面:

- `/live.html` を Playwright で表示
- zoom 10 で鉄道レイヤーON
- `/api/live/trains/osm`: HTTP 200
- SVG path count: 5
- request failures: 0
- console errors: 0
- warnings: 0

スクリーンショット:

- `/private/tmp/live_phase7a2_railway_overlay.png`

## 通常路線表示

E2Eで DOM style を確認。

- stroke: `#888888`
- stroke-width: `1.5`
- stroke-opacity: `0.3`

期待どおり、薄グレー・低opacity・細線で、主張しすぎない表示。

## 障害路線強調

モックデータで状態別色を確認。

| status | expected | result |
|---|---|---|
| delay | `#FFD54F` | PASS |
| partial_suspension | `#FF9800` | PASS |
| suspended | `#F44336` | PASS |

強調線:

- stroke-width: `4`
- stroke-opacity: `0.9`

## 路線マッピング確認

確認済み:

```text
odpt.Railway:TokyoMetro.Ginza
↓
OSM name: 銀座線
```

E2Eでマッチ時は GeoJSON path として表示され、既存 CircleMarker が重複表示されないことを確認。

未一致/OSM取得失敗:

- CircleMarker fallback が表示されることを確認。

## ポップアップ

OSMマッチ路線の popup 表示を確認。

- 路線名
- 事業者
- 状態
- 説明
- 更新時刻
- 出典

`undefined` 表示なし。

## レイヤー順序

通常鉄道路線は細線・低opacity、障害路線のみ強調。

注意:

- 既存 `/live` は雨雲/キキクルがタイル、高潮などが vector で混在している。
- 完全な pane 階層制御は今後の共通レイヤー整理課題。
- 今回は線幅/opacity を抑え、災害レイヤーの視認性を壊さない範囲で確認。

## モバイル

既存 Phase 7-A E2E を再実行。

- `npx playwright test e2e/live-train-layer.spec.js`: 5 passed
- モバイル幅で横スクロールなし
- 交通カード・レイヤートグル操作可能

## パフォーマンス

E2E確認:

- zoom 7以下では `/api/live/trains/osm` を呼ばない
- zoom 8以上で表示範囲 bbox のみ取得
- bbox が大きすぎる場合は backend 側でも抑止
- pan/zoom は debounce 500ms

実画面:

- `/api/live/trains/osm` は fallback で 5路線返却
- 初期表示・zoom・toggle 操作に固まりなし

## 回帰確認

- `npx playwright test e2e/live-basic.spec.js`: 73 passed
- `npx playwright test e2e/live-train-layer.spec.js`: 5 passed
- `npx playwright test e2e/live-train-osm-layer.spec.js`: 12 passed

確認範囲:

- 地震一覧
- 津波警報UI
- 雨雲
- キキクル
- 潮位
- 日月
- 河川リンク
- 鉄道カード
- 鉄道レイヤーON/OFF

## 発見した問題

### Overpass直アクセスが実環境で失敗

最初の実 `/live` probe では、ブラウザから `https://overpass-api.de/api/interpreter` へ直接アクセスし、以下が発生。

```text
net::ERR_CONNECTION_REFUSED
```

このままだと「路線表示不能」になり得るため、backend proxy + fallback に変更した。

### 外部OSM取得に依存する路線網の網羅性

Overpass が利用できる環境では表示範囲の OSM 路線を取得する。
利用できない環境では主要路線の軽量フォールバックに退避するため、網羅性は限定的。

## 最終結論

鉄道運行影響レイヤーは、マーカー中心から路線中心の表示へ改善された。

通常路線は控えめに表示され、障害路線は状態別に強調される。OSMマッチしない場合やOSM取得失敗時も既存マーカーへ退避し、`/live` 全体の回帰は確認されなかった。

Overpass不通時は軽量フォールバックに退避するため、実運用上の安定性は確保できた。一方でフォールバック路線の網羅性は限定的なため、判定は PASS with notes とする。

# Phase 7-A.6: 鉄道障害路線 選択ハイライト改善 — Claude実装記録

## 実装日

2026-07-10

## 対象

`/live/stream` 鉄道情報パネル（`#rail-side` 障害路線リスト + `#rail-map` 鉄道子画面路線図）。
`/live` 本体側は対象外（指示書どおり `/live/stream` のみ対応）。

## 変更ファイル

- `frontend/js/live-stream/live-stream-railway-layer.js`
  - GeoJSON fetch を `_loadGeoData()` に共通化（bbox 用インデックスと feature インデックスで二重 fetch しない）
  - `_loadFeatureIndex()` / `getFeaturesForNames(names)` を追加（osm name → Feature[] の一度きりの構築、選択のたびに全 feature を走査しない）
  - `highlightSelectedRoute(map, routeInfo)` / `clearSelectedHighlight()` / `getSelectedRouteId()` を追加
    - `renderer: L.svg()` を明示指定（地図が `preferCanvas:true` のため、指定しないと選択ハイライトに CSS class/animation が効かない — Phase C 高潮沿岸ハイライトと同じ既知の制約）
    - 白縁取り (`live-railway-selected-outline`) + 公式カラー太線 (`live-railway-selected-core`) の2層を `L.layerGroup` で重ねる
    - 同一路線が複数 feature / MultiLineString に分かれる場合もまとめてハイライト
    - feature 未一致時は `matched:false` を返すのみ（console error は出さない）
    - 選択が別路線へ切り替わった後に古い問い合わせが解決した場合は結果を破棄する（race guard）
- `frontend/js/live-stream/live-stream-panels.js`
  - `#rail-side`（静的コンテナ）へ一度だけ click delegation を登録（リスト内容は `render()` のたびに `innerHTML` で作り直されるため）
  - 選択状態 (`_selectedRailEventId`) を保持し、再クリックでトグル解除、別路線クリックで差し替え
  - `render()` の鉄道小窓ブロックで、選択中路線が現在の障害路線一覧から消えたら自動的に選択解除（障害解消後にハイライトが残り続けない）
  - `setRailwayMiniMapDiagnostics()` に `selectedRailwayEventId` / `selectedRailwayMatched` を追加（E2E 検証用）
- `frontend/css/live/live-stream.css`
  - `.rail-card.is-selected`（背景+枠線強調、バー幅を太く。点滅なし）
  - `.live-railway-selected-outline` / `.live-railway-selected-core` + `@keyframes live-railway-selected-pulse`（1.4s、opacity 1↔0.4、drop-shadow グロー）
  - `prefers-reduced-motion: reduce` で `.live-railway-selected-core` の animation を無効化

## 非目標（指示書どおり据え置き）

- 障害路線すべての常時点滅、地図の自動 pan/fit 変更、複数選択UI、路線検索、`/live` 側対応は対象外。

## 動作確認

- 実データ（ODPT）で 千代田線・副都心線 が同時に障害中の状態で Playwright により手動確認：
  - クリックで選択 → 白縁取り+公式カラー(#009944)太線+点滅アニメーションが `#rail-map` 上に表示
  - 別路線クリックで差し替え（旧ハイライトは1件も残らない）
  - 再クリックで解除
  - console error / page error なし
- `prefers-reduced-motion: reduce` で `animationName` が `none` になることを確認
- 新規 E2E: `e2e/live-stream-railway-selected-highlight.spec.js`（7件 PASS）
- 既存回帰: `e2e/live-stream.spec.js`（53件）, `e2e/live-stream-railway-phase5b.spec.js`, `e2e/live-stream-railway-calm-map.spec.js`, `e2e/live-stream-railway-bounds-verification.spec.js` 含め計36件 追加実行、すべて PASS

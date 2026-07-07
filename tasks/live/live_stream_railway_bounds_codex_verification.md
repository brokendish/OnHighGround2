# live stream railway bounds verification

検証日: 2026-07-07  
対象: `/live/stream` 鉄道障害路線小地図 bounds / fallback / `/live` 回帰  
判定: **PASS**

## Summary

ユーザー指定の7観点を確認しました。検証中、GeoJSONで見つかる路線と見つからない路線が混在した場合に、未一致路線の代表点をboundsへ混ぜる保証が弱かったため、stream専用実装を補強しました。

変更後、専用E2E 7件と既存鉄道系E2E 53件が通過しています。

## Changed

- `frontend/js/live-stream/live-stream-railway-layer.js`
  - `getBoundsForNames()` の返却値に `matchedNames` を追加。
  - OSM路線名に事業者名接頭辞がある場合も、裸の路線名との部分一致を維持。

- `frontend/js/live-stream/live-stream-panels.js`
  - GeoJSON一致路線は実ジオメトリboundsを使い、GeoJSON未一致路線だけ代表点をboundsへ追加。
  - `railwayMiniMap` diagnostics に現在のLeaflet boundsを追加。

- `e2e/live-stream-railway-bounds-verification.spec.js`
  - 指定7観点を直接検証する専用E2Eを追加。

## Verification Points

1. 複数障害路線が東西・南北に離れている場合、全路線が画面内に収まること
   - `京王線` / `東武東上線` / `有楽町線` の複数路線で `fittedLineIds` 全件一致と広角fitを確認。

2. 1路線のみ障害時も、その路線全体が収まること
   - `東武東上線` 1件で、Leaflet表示boundsがGeoJSON路線boundsを含むことを確認。

3. OSM路線名に事業者名接頭辞がある場合も強調対象になること
   - `有楽町線` が `東京メトロ有楽町線` 相当のOSM名に部分一致し、GeoJSON boundsを取得できることを確認。

4. GeoJSONに見つからない路線のみ代表点フォールバックされること
   - `京王線` はGeoJSON bounds、`検証架空線` は代表点を使い、両方が同じ表示boundsへ含まれることを確認。

5. 代表点フォールバックが全件に効いて、東京西側へ偏る旧挙動に戻っていないこと
   - GeoJSON未一致の東西2路線について、両方の代表点が表示boundsに入ることを確認。

6. 8秒巡回ズームが残っていないこと
   - 複数路線時、9.2秒待っても `fittedLineIds` / zoom / center が変わらないことを確認。
   - なお詳細テキストカードの巡回は残っていますが、小地図のズーム対象は全件統合boundsで固定されます。

7. `/live` 本体と `/live/stream` の両方で破綻していないこと
   - 専用E2EとHTTP確認で `/live` / `/live/stream?chrome=off` の表示・疎通を確認。

## Commands

```bash
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check e2e/live-stream-railway-bounds-verification.spec.js
```

Result: all passed.

```bash
npx playwright test e2e/live-stream-railway-bounds-verification.spec.js
```

Result: **7 passed**

```bash
npx playwright test \
  e2e/live-stream-railway-bounds-verification.spec.js \
  e2e/live-stream-railway-phase5b.spec.js \
  e2e/live-stream-railway-calm-map.spec.js \
  e2e/live-stream-railway-color-layer.spec.js \
  e2e/live-stream-railway-detail.spec.js \
  e2e/rail-mock-verify.spec.js
```

Result: **53 passed**

```bash
curl -I http://127.0.0.1:8080/live
curl -I "http://127.0.0.1:8080/live/stream?chrome=off"
```

Result: both **200 OK**

## Notes

- 既存ナビ本体の `frontend/index.html`, `navigation.js`, `nav-*.js`, `hazard-layers.js`, `location-info-panel.js`, reroute系には触れていません。
- 追加したdiagnosticsの `railwayMiniMap.bounds` はE2E検証用で、配信UIには表示されません。

## Final Judgement

**PASS**

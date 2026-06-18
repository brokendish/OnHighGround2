# 総合災害ビューア全国監視 Phase 7-A.3 CODEX検証メモ

## 対応概要

- `frontend/js/live/live-train-osm-layer.js` で路線カラー辞書を拡張した。
- OSM の `name` / `name_ja` / `name_en` / `ref` / `line` / `route_name` / `operator` と、表示用にまとめた `_live_route_name` を色解決・ODPT照合に使うようにした。
- 無名線、貨物線、`railway=service|siding|yard|platform|station|spur`、`service=yard|siding|spur|crossover`、`usage=industrial` を抑制するフィルタを追加した。
- 表示範囲内の同一路線 feature を路線名キーで `MultiLineString` にまとめ、Leaflet 上では路線単位の path として描画するようにした。
- 障害状態でも路線本体色を維持し、線幅・破線・ハローで状態を表現する既存 Phase 7-A.3 差分を維持した。
- `e2e/live-train-osm-layer.spec.js` に、同一路線 feature の集約とノイズ線抑制の回帰テストを追加した。

## 実データ確認

対象:

```text
frontend/layers/railways/kanto_railways.geojson
```

確認結果:

```json
{
  "total": 20884,
  "keptSegments": 18956,
  "routeNames": 371,
  "unnamedExcluded": 1367,
  "freightExcluded": 561
}
```

表示時は `keptSegments` をそのまま個別 path にせず、表示範囲内で路線名単位に集約する。

## 検証結果

```bash
node --check frontend/js/live/live-train-osm-layer.js
```

PASS。

```bash
python3 -m compileall backend
```

PASS。

```bash
docker compose ps
```

- backend: Up / healthy
- frontend: Up
- martin: Up / healthy
- osrm-walking: Up

```bash
npx playwright test e2e/live-basic.spec.js
```

PASS: 73 passed。

```bash
npx playwright test e2e/live-train-osm-layer.spec.js
```

PASS: 15 passed。

```bash
npx playwright test e2e/live-train-layer.spec.js
```

PASS: 5 passed。

## 補足

Playwright を3本並列起動した初回実行では、各プロセスが同じ `127.0.0.1:8787` の test server を起動しようとして `EADDRINUSE` が発生した。順次実行では全て PASS。

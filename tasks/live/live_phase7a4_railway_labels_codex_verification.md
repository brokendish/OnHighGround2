# 総合災害ビューア全国監視 Phase 7-A.4 CODEX検証メモ

## 対応概要

- `frontend/js/live/live-train-label-layer.js` を追加し、鉄道運行影響レイヤーON時だけ路線名・駅名ラベルを表示するようにした。
- `frontend/css/live/live-train-label.css` を追加し、黒背景地図上でも読める小型ラベル、路線色枠、障害状態バッジを定義した。
- `frontend/live.html` にラベル用 CSS / JS を追加した。
- `frontend/js/live/live-train-osm-layer.js` から、表示範囲内で集約済みの路線 feature と障害情報をラベル層へ渡すようにした。
- `frontend/layers/railways/kanto_stations.geojson` を追加し、駅ラベル用の静的 GeoJSON として利用する。
- zoom ごとの表示上限を設定した。

## 表示上限

```text
zoom 8〜10:
  route labels max 20
  station labels 0

zoom 11〜12:
  route labels max 40
  station labels max 10

zoom 13〜14:
  route labels max 60
  station labels max 40

zoom 15以上:
  route labels max 80
  station labels max 80
```

## 優先表示

- 路線ラベルは障害路線を通常路線より先に表示する。
- 障害路線ラベルには `遅延` / `一部運休` / `見合わせ` の状態バッジを付ける。
- zoom 13〜14 の駅ラベルは、主要駅に加えて障害路線の近傍駅も表示対象にする。
- 駅候補は障害路線近傍、主要駅、`train=yes`、地下鉄系プロパティを加点して並べる。

## 駅GeoJSON確認

対象:

```text
frontend/layers/railways/kanto_stations.geojson
```

概要:

```json
{
  "features": 2016,
  "railway": {
    "station": 1999,
    "halt": 17
  }
}
```

`name` は全 feature に存在し、`railway=platform` / `public_transport=platform` の大量混入は確認されなかった。

HTTP確認:

```bash
curl -I http://127.0.0.1:8080/layers/railways/kanto_stations.geojson
```

結果:

```text
HTTP/1.1 200 OK
Content-Type: application/geo+json
Content-Length: 389505
Vary: Accept-Encoding
```

## 検証結果

```bash
node --check frontend/js/live/live-train-osm-layer.js
node --check frontend/js/live/live-train-label-layer.js
node --check e2e/live-train-label-layer.spec.js
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
npx playwright test e2e/live-train-label-layer.spec.js
```

PASS: 12 passed。

```bash
npx playwright test e2e/live-basic.spec.js
```

PASS: 73 passed。

```bash
npx playwright test e2e/live-train-layer.spec.js
```

PASS: 5 passed。

```bash
npx playwright test e2e/live-train-osm-layer.spec.js
```

PASS: 15 passed。

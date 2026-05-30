# Phase 3-D 地震 市区町村震度マーカー表示 検証レポート

## 実施日時

- 2026-05-31 00:13 JST

## 最終判定

**PASS with notes**

理由:

- `/live` 実画面で市区町村単位の震度数字マーカー表示、ON/OFF、再ON、ポップアップ表示を確認できた。
- points なしケースでは市区町村 divIcon が表示されず、フォールバック経路のログと JS エラーなしを確認できた。
- live 専用 E2E を含む回帰確認は、既存 8787 サーバー利用 config で 104 passed。
- ただし実 API の震度 point は `pref` / `addr` / `scale` 形式で、各 point に `municipality` / `intensity` / `lat` / `lng` という名前のフィールドは直接含まれない。UI 側で市区町村名・震度ラベルへ変換し、`/data/municipality_coords.json` で座標解決している。
- 代表地点フォールバックは `circleMarker` + `preferCanvas: true` のため DOM カウントでは直接確認しにくい。コード経路、ログ、E2E、画面破綻なしで確認した。

## 1. 構文確認

実行:

```bash
python3 -m compileall backend/app
node --check frontend/js/live/live-earthquake-layer.js
node --check frontend/js/live/live-layers.js
node --check frontend/js/live/live-ui.js
node --check frontend/js/live/live-tide-layer.js
node --check frontend/js/live/live-alert-panel.js
node --check frontend/js/live/live-sun-moon-card.js
node --check frontend/js/live/live-danger-summary.js
node --check frontend/js/live/live-map.js
node --check frontend/js/live/live-main.js
node --check frontend/js/live/live-mobile.js
node --check e2e/live-earthquake-layer.spec.js
node --check e2e/live-basic.spec.js
```

結果:

- PASS
- Python SyntaxError なし。
- JS 構文エラーなし。

## 2. Docker 状態

実行:

```bash
docker compose build
docker compose up -d
docker compose ps
```

結果:

- `backend`: Up / healthy
- `frontend`: Up
- `martin`: Up / healthy
- `osrm-walking`: Up

確認時の状態:

```text
evacuation-navi-backend   Up About a minute (healthy)  0.0.0.0:8000->8000/tcp
evacuation-navi-frontend  Up 2 hours                   0.0.0.0:8080->80/tcp
evacuation-navi-martin    Up 2 hours (healthy)
evacuation-navi-osrm-walking Up 2 hours                0.0.0.0:5501->5001/tcp
```

補足:

- frontend は compose 上で healthcheck 表示なしのため `healthy` ではなく `Up` として確認。

## 3. API 確認結果

確認 API:

```bash
curl -s 'http://127.0.0.1:8000/api/earthquakes?days=1'
```

結果:

- PASS with notes
- HTTP 200
- 地震イベント取得可能。
- `count`: 8
- 最新イベント:
  - `event_id`: `6a1af63be88ee598246bed6c`
  - `occurred_at`: `2026-05-30T23:34:00+09:00`
  - `epicenter_name`: `釧路地方中南部`
  - `magnitude`: 4.1
  - `max_intensity`: `2`
  - `points`: 31 件

市区町村別震度データ例:

```json
{
  "pref": "北海道",
  "addr": "芽室町東２条",
  "isArea": false,
  "scale": 20
}
```

確認できたこと:

- `pref` から都道府県を取得可能。
- `addr` から市区町村を抽出可能。
- `scale` から震度ラベルへ変換可能。
- イベント代表地点の `lat` / `lng` はあり。

Notes:

- task の確認項目にある `municipality`, `intensity`, 各 point の `lat/lng` は API レスポンスに直接は含まれない。
- Phase 3-D 実装では、`addr` を市区町村へ正規化し、`scale` を震度へ変換し、`/data/municipality_coords.json` で座標解決している。

## 4. 市区町村震度マーカー表示確認

実ブラウザ確認:

- URL: `http://127.0.0.1:8080/live.html`

結果:

- PASS
- 地震レイヤー ON で市区町村震度マーカーが表示された。
- 代表地点 1 つだけではなく複数マーカー表示。
- 震度数字が見える。
- OnHighGround2 本体と同じ `.earthquake-intensity-marker` クラスの divIcon 表示を確認。

実測:

- 市区町村震度マーカー数: 4
- 表示ラベル: `2`, `1`, `1`, `1`
- console log:

```text
live earthquake municipality markers: event_id=6a1af63be88ee598246bed6c count=4
```

## 5. レイヤー ON/OFF 確認

実ブラウザ確認結果:

- ON: 市区町村震度マーカー 4 件
- OFF: 市区町村震度マーカー 0 件
- 再 ON: 市区町村震度マーカー 4 件に復帰

結果:

- PASS

## 6. ポップアップ確認

市区町村震度マーカークリック結果:

- popup visible: true

ポップアップ text:

```text
北海道 釧路市
震度: 2
発表時刻: 23:34
震源: 釧路地方中南部
M4.1
 / 深さ100km
```

確認項目:

- 市区町村名: PASS
- 都道府県: PASS
- 震度: PASS
- 地震発生時刻: PASS
- 震源名: PASS
- マグニチュード: PASS

## 7. フォールバック確認

確認方法:

- Playwright route で `points: []` の地震イベントを返す。

結果:

- 市区町村震度マーカー: 0 件
- JS error: 0 件
- page error: 0 件
- フォールバックログあり。

ログ:

```text
live earthquake municipality markers unavailable, fallback to representative marker: event_id=fallback-001
```

Notes:

- 代表地点マーカーは `L.circleMarker` かつ `liveMap` が `preferCanvas: true` のため、`.leaflet-marker-icon` のような DOM 要素としては数えられない。
- E2E ではフォールバック時に市区町村 divIcon が出ないこと、画面が壊れないことを確認。

## 8. Console 確認

実ブラウザ確認:

- 市区町村震度マーカー表示時 console error: 0 件
- 市区町村震度マーカー表示時 page error: 0 件
- フォールバック確認時 console error: 0 件
- フォールバック確認時 page error: 0 件

結果:

- PASS

## 9. 回帰確認結果

### git diff check

実行:

```bash
git diff --check
```

結果:

- PASS

### Playwright

標準 config:

```bash
npx playwright test e2e/live-basic.spec.js e2e/live-tide-layer.spec.js e2e/live-sun-moon-card.spec.js e2e/live-earthquake-layer.spec.js
```

結果:

- FAIL
- `Error: listen EADDRINUSE: address already in use 127.0.0.1:8787`
- テスト実行前のローカル環境要因。

既存 8787 サーバー利用 config:

```bash
npx playwright test e2e/live-basic.spec.js e2e/live-tide-layer.spec.js e2e/live-sun-moon-card.spec.js e2e/live-earthquake-layer.spec.js --config=/private/tmp/playwright-live-existing-server.config.js
```

結果:

- PASS
- 104 passed

内訳:

- `live-basic`: 64 passed
- `live-earthquake-layer`: 12 passed
- `live-sun-moon-card`: 15 passed
- `live-tide-layer`: 13 passed

## 10. ナビ本体影響確認

実ブラウザ確認:

- URL: `http://127.0.0.1:8080/`

結果:

- PASS with notes
- HTTP 200
- map visible: true
- console error: 0 件
- page error: 0 件
- `/api/earthquakes` の自動呼び出し: 0 件
- `.earthquake-intensity-marker`: 0 件

Notes:

- `/data/municipality_coords.json` は 1 回読み込まれた。これは既存ナビ本体の `earthquake-intensity-layer.js` 由来で、Phase 3-D の `/live` 用 API 自動呼び出しではない。

## スクリーンショット

- `/private/tmp/live-phase3d-earthquake-actual-on.png`
  - `/live.html` で市区町村震度数字マーカー表示。
- `/private/tmp/live-phase3d-earthquake-actual-popup.png`
  - 市区町村震度マーカークリック後のポップアップ表示。
- `/private/tmp/live-phase3d-earthquake-fallback.png`
  - `points: []` フォールバック確認。
- `/private/tmp/live-phase3d-nav-root.png`
  - `/` ナビ本体表示確認。

## 総括

Phase 3-D の主目的である「代表地点 1 マーカー方式から、市区町村単位の震度数字マーカー表示へ改善」は、実 API・実ブラウザ・E2E の範囲で成立している。

API point のフィールド名と座標解決方式に注意点はあるが、表示機能・ON/OFF・ポップアップ・フォールバック・回帰は確認済み。

最終判定は **PASS with notes**。

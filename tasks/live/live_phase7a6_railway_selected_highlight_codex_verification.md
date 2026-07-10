# Phase 7-A.6 鉄道障害路線 選択ハイライト改善 検証

## 判定

PASS with notes

## 検証日時

2026-07-10 10:36 JST

## 対象差分

- `frontend/js/live-stream/live-stream-railway-layer.js`
  - GeoJSON 生データの共有 loader と feature index を追加
  - 選択路線専用の `L.geoJSON` ハイライトレイヤーを追加
  - 白縁取りレイヤーと公式カラー中心線レイヤーを分離
  - `renderer: L.svg()` を強制し、CSS class / animation が効くように対応
  - feature 未一致時は画面を壊さず `matched:false` を返す
- `frontend/js/live-stream/live-stream-panels.js`
  - 鉄道障害路線リストの click delegation を追加
  - 選択状態、再クリック解除、別路線選択時の差し替えを追加
  - E2E 用 diagnostics に選択状態を追加
- `frontend/css/live/live-stream.css`
  - `.rail-card.is-selected` のリスト側選択表示を追加
  - `.live-railway-selected-outline` / `.live-railway-selected-core` と pulse keyframes を追加
  - `prefers-reduced-motion: reduce` で点滅を無効化
- `e2e/live-stream-railway-selected-highlight.spec.js`
  - 選択、差し替え、解除、公式色、feature 未一致、reduced motion、回帰確認を追加

## 実行コマンド

```bash
git diff --stat
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-railway-layer.js
rg -n "railway-selected|prefers-reduced-motion|is-selected" frontend/css/live frontend/js/live-stream e2e/live-stream-railway-selected-highlight.spec.js
curl -I http://127.0.0.1:8080/live/stream
curl -I http://127.0.0.1:8080/live
docker compose ps
npx playwright test e2e/live-stream-railway-selected-highlight.spec.js
venv/bin/python -m pytest tests/test_live_train_service.py
npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/live-stream-railway-phase5b.spec.js
```

補足: `live-stream.spec.js` と `live-stream-railway-phase5b.spec.js` を同時起動した最初の試行では、Playwright の一時サーバ `127.0.0.1:8787` が競合して Phase 5B 側のみ `EADDRINUSE` で失敗した。単独再実行では PASS。

## UI確認

- `/live/stream` は `200 OK`。
- `/live` は `200 OK`。
- Docker compose 上で backend / frontend / martin / osrm-walking は起動中。
- 新規 E2E で鉄道情報カード、障害路線リスト、鉄道ミニマップ、他の stream パネルの表示を確認。

## ハイライト確認

- 太線: `stroke-width` で core と outline の線幅を検証し、outline が core より太いことを確認。
- 縁取り: `.live-railway-selected-outline` の出現を確認。
- 点滅: `.live-railway-selected-core` に animation class / keyframes が存在することを確認。
- 前面表示: 専用 `L.layerGroup` を追加し、outline / core に `bringToFront()` を呼ぶ実装を確認。
- 公式色: 千代田線の core stroke が `#009944` で、警戒色の赤点滅ではないことを E2E で確認。
- リスト選択状態: `.rail-card.is-selected` が選択項目に付与されることを E2E で確認。

## 切替確認

- 1本目選択後、2本目選択で `.rail-card.is-selected` が1件だけになることを確認。
- 旧カードから `is-selected` が外れ、新カードに付くことを確認。
- 選択済みカードの再クリックで selected class と highlight layer が消えることを確認。
- console error / page error は検出されなかった。

## feature未一致 / 複数feature確認

- feature 未一致:
  - `存在しない架空線` の mock で、リスト選択は維持され、地図ハイライトは出ず、画面が壊れないことを確認。
- 複数 feature / MultiLineString:
  - 実装は `Feature[]` を `L.geoJSON(features, ...)` に渡す構成で、同一路線に一致した複数 feature をまとめて描画する。
  - 自動テストでは複数 feature の実視覚差分までは個別検証していないため、今後の実データ確認余地として Notes に残す。

## reduced motion確認

- Playwright の `page.emulateMedia({ reducedMotion: 'reduce' })` で確認。
- `.live-railway-selected-core` は表示されたまま、computed style の `animationName` が `none` になることを確認。

## 回帰確認

- `npx playwright test e2e/live-stream-railway-selected-highlight.spec.js`: 7 passed
- `venv/bin/python -m pytest tests/test_live_train_service.py`: 59 passed
- `npx playwright test e2e/live-stream.spec.js`: 45 passed
- `npx playwright test e2e/live-stream-railway-phase5b.spec.js`: 8 passed

## Notes

- スクリーンショット `test-results/live-railway-selected-highlight.png` は未取得。代わりに E2E で DOM 出現、stroke color / width、selected class、reduced motion、feature 未一致時の挙動を確認した。
- 複数 feature / MultiLineString は実装上対応しているが、特定の実データ路線を使ったスクリーンショット目視までは未実施。
- `/live` 本体側は今回の対象外で、`/live/stream` のみ対応。

## 結論

主要な受け入れ条件は満たしている。選択路線はリスト選択と連動し、地図上で専用レイヤーにより太線・縁取り・グロー・点滅表示される。別路線選択、解除、feature 未一致、reduced motion、代表回帰も PASS。スクリーンショット目視と複数 feature の実データ確認だけ未実施のため、判定は `PASS with notes` とする。

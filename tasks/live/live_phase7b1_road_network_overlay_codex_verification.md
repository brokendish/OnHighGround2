# Phase 7-B.1 道路ネットワークオーバーレイ CODEX検証

## 判定

**PASS with notes**（2026-06-21 是正後再検証）

初回検証で FAIL とした SVG path 過多、モバイルラベル過密、ref単独ラベル、GeoJSONのGit管理外を是正した。実データ再検証では zoom 9 / 11 / 13 の path 数がそれぞれ 200 / 300 / 600、モバイル zoom 13 のラベルが6件となり、画面の判読性を確認した。

Phase 7-B.1 専用E2Eは追加した是正テストを含め18件すべてPASS。既存live全体E2Eには統合カード移行前のselectorを参照する失敗が残るため notes 扱いとする。

## 検証環境

- date: 2026-06-21 (Asia/Tokyo)
- branch: `main`
- commit: `3d763d1` (`refactor: /live 交通情報カードを「現在の状況」パネルに統合`)
- Docker:
  - backend: Up / healthy
  - frontend: Up
  - martin: Up / healthy
  - osrm-walking: Up
- Browser: Playwright Chromium / Desktop 1440x900 / Mobile 390x844
- URL: `http://127.0.0.1:8080/live.html`

## 実施コマンド

```bash
python3 -m compileall backend
node --check frontend/js/live/live-road-traffic-layer.js
node --check frontend/js/live/live-road-traffic-panel.js
node --check frontend/js/live/live-road-osm-layer.js
node --check frontend/js/live/live-road-label-layer.js
node --check frontend/js/live/live-legend.js
node --check frontend/js/live/live-layers.js
docker compose ps
curl -I http://127.0.0.1:8080/layers/roads/kanto_roads_main.geojson
curl -I -H 'Accept-Encoding: gzip' http://127.0.0.1:8080/layers/roads/kanto_roads_main.geojson
jq ... frontend/layers/roads/kanto_roads_main.geojson frontend/layers/roads/kanto_roads_tertiary.geojson
npx playwright test e2e/live-road-osm-layer.spec.js --config=/private/tmp/playwright-live-road.config.js
npx playwright test e2e/live-*.spec.js --config=/private/tmp/playwright-live-road.config.js
```

構文・compileall はすべて成功。標準 Playwright 設定は応答のない `127.0.0.1:8787` が `EADDRINUSE` となったため、リポジトリを変更せず一時設定で Docker frontend (`8080`) に接続した。

## GeoJSON確認

| ファイル | feature数 | 非圧縮サイズ | highway内訳 |
|---|---:|---:|---|
| `kanto_roads_main.geojson` | 4,461 | 18,584,047 bytes | motorway 172 / trunk 507 / primary 1,568 / secondary 2,214 |
| `kanto_roads_tertiary.geojson` | 4,502 | 4,462,335 bytes | tertiary 4,502 |

- HTTP 200
- `Content-Type: application/geo+json`
- `Accept-Encoding: gzip` に対し `Content-Encoding: gzip`
- residential / service / living_street / track / path / footway / cycleway は含まれない
- tertiary は全件名前付き。main は無名 66件
- `.gitignore` に道路ディレクトリと2ファイルの例外を追加し、Git追跡可能であることを `git status` で確認

## レイヤーON/OFF確認

- OFF初期状態: 道路 path 0、道路ラベル 0
- ON: main GeoJSON を初回のみ取得し道路とラベルを表示
- OFFへ復帰: 道路 path 0、道路ラベル 0
- zoom 7以下: GeoJSONを取得せず道路非表示
- 専用 E2E: PASS

## ズーム段階表示確認

- zoom 8〜10: motorway / trunk / primary
- zoom 11〜12: secondary を追加
- zoom 13以上: tertiary を追加し別ファイルを遅延取得
- residential / service はデータ自体に含まれない
- 専用 E2E の段階表示テスト: PASS

道路種別優先度（motorway > trunk > primary > secondary > tertiary）によるフィーチャーキャップを追加。実データの描画数は zoom 9 で200 path、zoom 11で300 path、zoom 13（狛江・世田谷周辺）で600 pathとなり、設定上限どおりであることを確認した。

## 道路名ラベル確認

- `_live_road_name` は生成時に `name` → `name_ja` → `official_name` → `alt_name` → `ref` の順で採用
- 同一道路名の重複抑止あり
- pan / zoom / OFF 時に古いラベルはクリアされる
- 実データで国道246号、環七通り、環八通り、青梅街道、多摩堤通り、世田谷通り、狛江通り、府中街道を確認
- `_isGoodLabel()` により `246`、`3`、`R16` 等の数字・英数字だけのラベルを除外
- デスクトップ上限は zoom 8〜10: 8件、11〜12: 15件、13以上: 25件
- モバイル上限は zoom 8〜10: 5件、11〜12: 8件、13以上: 12件
- 120pxグリッドの同一・8近傍セル衝突回避を確認
- 実データでは desktop zoom 13で19件、mobile zoom 13で6件となり過密を解消

## 細街路除外確認

- GeoJSON は motorway / trunk / primary / secondary / tertiary の5種のみ
- residential / service / private / parking aisle / driveway / footway / cycleway は表示対象外
- 狛江・世田谷周辺で世田谷通り、多摩堤通り、狛江通り、府中街道、環八通りを確認

## 色・線幅確認

- motorway: 緑 `#43A047`, 3.0
- trunk: 明るい緑 `#66BB6A`, 2.8
- primary: 青 `#1E88E5`, 2.5
- secondary: オレンジ `#FB8C00`, 2.0
- tertiary: 薄グレー `#B0BEC5`, 1.5
- 実画面で黒背景上の識別は可能
- motorway > trunk > primary > secondary > tertiary の線幅順を確認

## 交通量マーカー共存確認

- モック交通量1件を使った専用 E2E で道路 path と観測点マーカーの同時表示を確認
- OFFで両方非表示
- ポップアップ表示テスト PASS
- 実API実行時は観測点0件だったため、実データでのクリック確認は未実施

## パフォーマンス確認

- main / tertiary は Promise とメモリでキャッシュし、pan / zoomごとの再fetchなし
- moveend / zoomend は 300ms debounce
- 表示範囲フィルタあり
- ローカルDockerでONからmain取得・描画安定まで約3.3秒（再検証値）
- console error / page error は0件
- SVG path は zoom 9: 200、zoom 11: 300、zoom 13: 600に制限
- GeoJSON非圧縮合計は約23MBで、初回転送・parse負荷は今後の改善余地として残る

## モバイル確認

- 390x844で横スクロールなし (`scrollWidth == clientWidth == 390`)
- page error なし
- zoom 13の道路ラベルは6件（上限12件）
- 120pxグリッド衝突回避により地図判読性を確認
- 下部の現在状況パネルは表示維持

## 回帰確認

- Phase 7-B.1 専用 E2E: **18 passed**（キャップ・モバイル上限・ref除外の追加テストを含む）
- live 全 E2E: **252 passed / 41 failed (293 total)**

41 failures の多くは、commit `3d763d1` の交通情報カード統合後も旧 `#live-train-card` / `#live-road-traffic-card` を参照する既存テストによるもの。ほかに、危険地域のテストデータ干渉・strict locator違反が4件ある。Phase 7-B.1 専用テストは全件通過しており、今回の道路コードによる鉄道・災害レイヤー破壊を直接示す失敗は確認していない。

## 発見した問題

1. **解消:** モバイル道路ラベル過密（100件 → 6件）。
2. **解消:** zoom 9のSVG path過多（1,987 → 200）。
3. **解消:** 数字・英数字ref単独ラベル。
4. **解消:** 必須GeoJSONのgitignore対象化。
5. **継続note:** 統合カードUIに合わせて旧selector参照を更新する必要がある。
6. **継続note:** GeoJSON非圧縮約23MBの初回転送・parse負荷。

## 修正提案

1. 将来的にはGeoJSONを表示範囲単位に分割、または vector tile / Martin 配信へ移行し、初回転送量を抑える。
2. 統合交通カードに合わせて既存 train / road E2E のselectorを更新する。

## スクリーンショット

- [Desktop zoom 13](screenshots/live_phase7b1_desktop.png)
- [Mobile 390x844 zoom 13](screenshots/live_phase7b1_mobile.png)

## 最終結論

初回FAILの4項目はすべて是正され、実データ描画・モバイル表示・専用E2E 18件で再確認した。道路ネットワークMVPの受け入れ基準は満たすため **PASS with notes**。残件は既存live E2Eの旧selector更新と、約23MBのGeoJSON初回転送量の将来的な最適化である。

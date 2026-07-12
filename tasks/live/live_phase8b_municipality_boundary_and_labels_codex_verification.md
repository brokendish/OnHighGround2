# Phase 8-B 小画面 市区町村境界線・自治体名表示改善 検証

## 判定

PASS with notes

## 検証日時

2026-07-12 13:09 JST

## 対象差分

- `frontend/js/live-stream/live-stream-municipality-boundary.js`
  - 地震小画面 `eq-mini`、キキクル/豪雨小画面 `rain-mini` 用の市区町村境界・ラベル共通モジュールを追加。
  - 境界データを一度だけ fetch し、bbox と zoom 条件で小地図範囲内のみ描画。
  - ラベル候補を優先度順に最大件数へ制限し、画面座標で近接ラベルを間引く。
  - キキクル/豪雨用に代表点から市区町村を逆引きする `findMunicipalityAt()` を追加。
  - `getDiagnostics()` で Canvas 描画の境界線数をE2Eから検証できるようにしている。
- `frontend/js/live-stream/live-stream-map-view.js`
  - `eq-mini` / `rain-mini` だけで `LiveStreamMunicipalityBoundary.init()` を呼ぶ。
- `frontend/js/live-stream/live-stream-panels.js`
  - 地震小画面では表示中の震度マーカーをラベル候補化し、最大6件に制限。
  - キキクル/豪雨小画面では現在ターゲット代表点を市区町村逆引きし、最大5件に制限。
  - 対象なし/切替時にラベルを clear し、古い表示を残さない。
- `frontend/css/live/live-stream.css`
  - `.live-muni-label` を追加。白文字 + 黒縁取りで小画面上の可読性を確保。
- `frontend/live/stream.html`
  - `live-stream-municipality-boundary.js` を読み込み。
- `e2e/live-stream-mini-map-municipality-boundary.spec.js`
  - 境界線、ラベル件数、カバレッジ外、GeoJSON取得失敗、全国俯瞰、回帰を検証する6件を追加。
- `scripts/derive/simplify_municipality_boundaries.py`
  - 東京都・神奈川県の既存境界データを統合・簡略化し、代表点とbboxを付与する派生スクリプト。

## データ確認

- 使用データ: `frontend/layers/administrative/kanto_municipality_boundary_simplified.geojson`
- サイズ: 約234KB
- JSON妥当性: `python3 -m json.tool` で確認済み。
- feature数: 121
- 代表プロパティ: `code`, `name`, `pref`, `cx`, `cy`, `bbox`
- 配信確認: `http://127.0.0.1:8080/layers/administrative/kanto_municipality_boundary_simplified.geojson` は `200 OK`。

重要な注意:

- このGeoJSONは `.gitignore` の `frontend/layers/*/` により `git status` に出ない。ローカル配信は成功しているが、CI/他環境で再現するには、強制追加するか生成手順を明確にする必要がある。
- 境界線データの実カバレッジは東京都・神奈川県のみ。全国対応ではない。

## 実行コマンド

```bash
git diff --stat
git status --short --untracked-files=all
node --check frontend/js/live-stream/live-stream-municipality-boundary.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-panels.js
python3 -m compileall scripts/derive/simplify_municipality_boundaries.py
python3 -m json.tool frontend/layers/administrative/kanto_municipality_boundary_simplified.geojson
jq '{type, featureCount:(.features|length), firstProps:.features[0].properties}' frontend/layers/administrative/kanto_municipality_boundary_simplified.geojson
curl -I http://127.0.0.1:8080/live/stream
curl -I http://127.0.0.1:8080/layers/administrative/kanto_municipality_boundary_simplified.geojson
docker compose ps
docker stats --no-stream
npx playwright test e2e/live-stream-mini-map-municipality-boundary.spec.js
node /private/tmp/phase8b_screenshots.js
npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/live-stream-earthquake-detail.spec.js e2e/live-stream-rain-hazard-detail.spec.js
```

補足: `live-stream.spec.js` と地震/雨詳細回帰を並列実行した最初の試行では、Playwright の一時サーバ `127.0.0.1:8787` が競合して片方が `EADDRINUSE` になった。単独再実行では PASS。

## UI確認

- 地震小画面:
  - diagnostics: `visibleCount=96`, `labelCount=4`, `zoom=9`
  - スクリーンショット: `test-results/live-stream-earthquake-mini-map-boundary.png`
  - 市区町村境界線は薄く表示され、震度マーカーの視認性を大きく損なっていない。
  - ラベルは千代田区・大田区・世田谷区など表示中震度マーカー由来で、全自治体表示にはなっていない。
- キキクル/豪雨小画面:
  - diagnostics: `visibleCount=113`, `labelCount=1`, `zoom=8`
  - スクリーンショット: `test-results/live-stream-rain-mini-map-boundary.png`
  - 横浜市中区のラベルが代表点付近に表示され、境界線は雨/危険度情報を邪魔しない薄さ。
- 全国俯瞰:
  - calm時は低zoomのため `eq-mini` / `rain-mini` とも `visibleCount=0`。
  - 関東2都県だけが不自然に浮く表示は抑制されている。

## ラベル・境界線確認

- 全自治体名の常時表示はしていない。
- 地震小画面は表示中震度マーカーをラベル候補にし、`maxCount: 6`。
- キキクル/豪雨小画面は代表点から逆引きした自治体をラベル化し、`maxCount: 5`。
- ラベルは画面座標で24px未満の近接候補を間引く。
- ラベルは白文字 + 黒縁取りで、縮小表示でも読める。
- 地震スクリーンショットでは都心部ラベルがやや近いが、件数は4件で破綻なし。マーカー自体も読める。

## エラー耐性確認

- 境界GeoJSON取得失敗を404でmockしても、地震ポップアップと地震パネルは表示継続。
- 関東カバレッジ外の大阪/福岡mockでは境界線・豪雨ラベルは出ず、主機能は表示継続。
- E2E上の page error / console error 収集では継続エラーなし。

## パフォーマンス確認

- 境界データは約234KB、121 features。
- `MIN_ZOOM_TO_DRAW=7` 未満では描画しない。
- bboxで可視featureのみ描画し、同じbounds signatureでは再描画しない。
- 境界線は Canvas renderer のまま描画し、SVG DOMを大量生成しない。
- `docker stats --no-stream` 実行時:
  - frontend: CPU 0.00%, memory 9.777MiB
  - backend: CPU 0.20%, memory 2.118GiB
  - martin: CPU 0.12%, memory 34.78MiB
- E2E中に体感的な大きな遅延やレイヤー増殖は確認されなかった。

## 回帰確認

- `npx playwright test e2e/live-stream-mini-map-municipality-boundary.spec.js`: 6 passed
- `npx playwright test e2e/live-stream.spec.js`: 45 passed
- `npx playwright test e2e/live-stream-earthquake-detail.spec.js e2e/live-stream-rain-hazard-detail.spec.js`: 21 passed

## Notes

- 判定を `PASS with notes` にした主因は、境界データが東京都・神奈川県のみで、かつ `.gitignore` により未追跡扱いになっている点。
- `git diff --stat` には新規未追跡ファイルが出ないため、レビュー時は `git status --short --untracked-files=all` も確認すること。
- キキクル/豪雨ラベルは現状の小画面ターゲットが1代表点のため、実質1件表示。将来ランキングや複数危険自治体を同時表示する場合は、優先度選定の拡張余地がある。
- 地震小画面の都心部ではラベルが近接しやすい。現状は破綻なしだが、配信縮小で気になる場合は `LABEL_MIN_PIXEL_GAP` を少し広げる余地がある。

## 結論

Phase 8-B の主要受け入れ条件は満たしている。地震小画面とキキクル/豪雨小画面に市区町村境界線が追加され、ラベルは条件付き・件数制限付きで表示される。境界線は薄く、主情報を大きく邪魔していない。取得失敗・カバレッジ外・全国俯瞰でも画面は壊れず、代表E2Eと回帰も PASS。

ただし、境界データのカバレッジとGit追跡方法はリリース前に扱いを決める必要があるため、最終判定は `PASS with notes` とする。

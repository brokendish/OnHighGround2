# live stream Phase 5-A bundle verification

## Result

PASS with notes

## Summary

`/live/stream` を Phase 5-B (OBS実運用リハーサル) へ進む前提として、以下3本を一括実装した。

**A. 地震子画面 本番地図化・詳細表示同期**
- 地震子画面の小地図 (`#eq-map`) を、Phase 5-A.1 時点のSVGモックから Leaflet + CARTO タイルの本番地図へ移行 (`LiveStreamMapView` の2個目のインスタンスとして singleton 化、中央地図と同じ非操作設計)
- 市区町村震度マーカーを Leaflet divIcon で描画 (`setIntensityMarkers()`)、震源マーカーは既存の `ls-pulse` を再利用
- 震度マーカー範囲への fit / 広域時の都道府県単位 tour を Leaflet の実緯度経度ベースで実装 (SVG座標変換ロジックは不要になった)
- 概要ヘッダー・市区町村震度リスト・小地図が同一 `earthquakeEventId` を参照することを `data-earthquake-detail-id` で明示
- Leaflet 未初期化/失敗時は Phase 5-A.1 のSVGモック地図へ自動フォールバック

**B. 鉄道情報 子画面 詳細化**
- 自動巡回/focus 中の鉄道 event 1件について、路線名・事業者・状態・詳細本文(全文)・更新時刻・出典を表示する詳細カード (`#rail-overlay`) を追加
- 影響区間/原因の個別フィールドが backend に無いため、`description` 全文をそのまま表示し「詳細未取得」等の非断定表示で対応 (推測しない)
- 詳細本文が70文字を超える場合のみ自動スクロール、スクロール中は対象路線を hold

**C. メイン地図 鉄道路線カラー反映**
- `/live` の `live-train-pmtiles-layer.js` にある公式/準公式路線カラー表 (110路線超) を stream 専用ファイルへ値のみ移植し、メイン地図の鉄道路線レイヤーに常時適用 (平常路線も含め、路線色自体は変更しない)
- 障害路線は色を変えず、幅(約2.2倍)・不透明度(最大1.0)を上げて強調する設計に変更 (自分の地域の路線色認識を壊さないため)
- 鉄道カード (`.bar`) のアクセント色も同じ表で統一

**共通基盤の変更**: `LiveStreamFocusController` の hold 機構を、単一 `_hold` 変数から source ごとの `Map` (`_holds`) へ拡張した。地震詳細 (`earthquake-detail`) と鉄道詳細 (`railway-detail`) の hold が同時に存在しうるため、互いに上書き消去しないようにするための変更。`requestHold`/`releaseHold` の公開APIは変更していないが、特定 source の状態を読む `getHold(source)` を新設し、地震子画面ローカルの対象固定・鉄道詳細双方がこれを使う。

## Checked files

```text
frontend/js/live-stream/live-stream-map-view.js        (fitTo/setIntensityMarkers/clearIntensityMarkers 追加)
frontend/js/live-stream/live-stream-panels.js            (eq小地図Leaflet化、鉄道詳細overlay追加、diagnostics拡張)
frontend/js/live-stream/live-stream-focus-controller.js  (hold機構を単一→Map化、getHold追加)
frontend/js/live-stream/live-stream-runtime.js           (railwayDetail/railwayLayer diagnostics追加)
frontend/js/live-stream/live-stream-railway-adapter.js   (description/source passthrough、公式カラー表反映)
frontend/js/live-stream/live-stream-railway-layer.js     (公式カラー表・diagnostics追加)
frontend/css/live/live-stream.css                         (Leaflet震度マーカー・鉄道詳細overlay用CSS追加)
frontend/live/stream.html                                 (#rail-overlay追加、data-earthquake-detail-*/data-railway-detail-* 属性追加)
e2e/live-stream-earthquake-detail-map-sync.spec.js         (新規, 11テスト)
e2e/live-stream-railway-detail.spec.js                     (新規, 9テスト)
e2e/live-stream-railway-color-layer.spec.js                (新規, 8テスト)
```

backend / data_runtime に変更なし。`/live` 本体 (`frontend/js/live/`) は未変更 (公式路線カラー表・震度スケール表は値のみ stream 側へ複製し、参照元ファイルは一切編集していない)。

## Environment

```text
docker compose: evacuation-navi-backend / -osrm-walking / -frontend / -martin 稼働中
E2E: DOCKER_BASE=http://127.0.0.1:8080 (nginx経由), Playwright chromium, 1 worker
```

## Commands

```bash
node --check frontend/js/live-stream/live-stream-map-view.js            # OK
node --check frontend/js/live-stream/live-stream-panels.js                # OK
node --check frontend/js/live-stream/live-stream-focus-controller.js       # OK
node --check frontend/js/live-stream/live-stream-runtime.js                 # OK
node --check frontend/js/live-stream/live-stream-railway-adapter.js         # OK
node --check frontend/js/live-stream/live-stream-railway-layer.js           # OK
node --check e2e/live-stream-earthquake-detail-map-sync.spec.js             # OK
node --check e2e/live-stream-railway-detail.spec.js                        # OK
node --check e2e/live-stream-railway-color-layer.spec.js                   # OK

curl -I http://127.0.0.1:8080/live/stream                                        # 200
curl -I "http://127.0.0.1:8080/live/stream?state=calm"                            # 200
curl -I "http://127.0.0.1:8080/live/stream?demo=1"                                # 200
curl -I "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test" # 200
curl -I http://127.0.0.1:8080/live/stream.html                                    # 200
curl -I http://127.0.0.1:8080/live                                                # 200
curl -I http://127.0.0.1:8080/                                                    # 200

npx playwright test \
  e2e/live-stream.spec.js e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-focus-view.spec.js e2e/live-stream-stability.spec.js \
  e2e/live-stream-earthquake-detail.spec.js e2e/live-stream-earthquake-detail-map-sync.spec.js \
  e2e/live-stream-railway-detail.spec.js e2e/live-stream-railway-color-layer.spec.js \
  e2e/eq-mock-verify.spec.js e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js e2e/rail-mock-verify.spec.js
```

`e2e/` 全体を無理に実行すると `block-ahead-reroute-generated.spec.js` 等ナビ系ハーネスの既存不安定挙動 (本フェーズと無関係) に巻き込まれるため、指示書の注意書きどおり上記スコープのみで判定した。

## Test results

```text
190 passed (4.3分)
```

内訳:
- 既存回帰 (Phase 3-B/3-C/3-D/4-A/4-B/5-A/5-A.1 + adapter mock検証): 147件 PASS
- 新規 `live-stream-earthquake-detail-map-sync.spec.js`: 11件 PASS
- 新規 `live-stream-railway-detail.spec.js`: 9件 PASS
- 新規 `live-stream-railway-color-layer.spec.js`: 8件 PASS
- 新規 `live-stream-earthquake-detail.spec.js` (Phase 5-A.1既存分、Leaflet化後も無改修で継続PASS): 15件 PASS

実装中に発見しその場で修正した問題 (2件、いずれも最終実行では解消済み):

```text
1. eq小地図の震源マーカーに setPulses(pulses, eqCur.id) を渡していたため、常時 data-active=true になり
   Phase 4-B の既存回帰 (「overview復帰後にactive markupが残らない」) が一時的に破綻。
   震源マーカーは常時同じ強調のままでよいため、activeEventId に null を渡すよう修正。
2. FocusController の hold を単一変数のままにしていた場合、地震詳細のholdと鉄道詳細のholdが同時に
   要求されると後勝ちで前者を消してしまう設計欠陥に気づき、hold を source 別 Map に拡張した
   (実際に両者が同時稼働するE2Eではまだ再現していないが、実運用でいずれ発生しうるため先に修正)。
```

## Diagnostics snapshot

`?demo=1&focusSpeed=test&runtimeSpeed=test&focus=off` にて:

```json
{
  "earthquakeDetail": {
    "activeEventId": "eq-demo-iwate", "municipalCount": 14, "markerCount": 13, "missingCoordinateCount": 1,
    "scrollMode": "scrolling", "miniMapMode": "tour", "miniMapFrameIndex": 1, "miniMapFrameTotal": 5,
    "truncated": false, "holdActive": true,
    "detailStatus": "ready", "listScrollState": "running", "mapTourState": "running", "holdReason": "earthquake-detail-tour"
  },
  "railwayDetail": {
    "activeRailwayEventId": null, "detailStatus": "empty", "hasScrollableDetail": false,
    "scrollState": "idle", "holdActive": false, "holdReason": null
  },
  "railwayLayer": { "loaded": true, "layerCount": 1, "highlightedFeatureCount": 4, "lastError": null }
}
```

(`focus=off` のため railwayDetail は対象なし。実際に鉄道路線に focus が当たった状態での動作は E2E `live-stream-railway-detail.spec.js` の 7 番、およびスクリーンショットで確認済み。)

`featureCount` / `coloredFeatureCount` は指示書の diagnostics 例に含まれていたが、protomaps-leaflet がタイル単位のベクタ描画で個々の feature を JS 側に保持しないため正確な計上手段がなく、今回は省略した (`loaded`/`layerCount`/`highlightedFeatureCount`/`lastError` のみ実装)。

## Manual browser check

```text
test-results/live-stream-phase5a-bundle-earthquake-map-1920.png       (通常表示・実データ0件)
test-results/live-stream-phase5a-bundle-calm-1920.png                  (state=calm)
test-results/live-stream-phase5a-bundle-demo-1920.png                  (demo=1、地震小地図Leaflet化+メイン地図鉄道カラー確認)
test-results/live-stream-phase5a-bundle-earthquake-wide-tour-1920.png (広域地震の市区町村震度リスト+小地図tour)
test-results/live-stream-phase5a-bundle-railway-detail-1920.png       (鉄道詳細overlay: 中央線快速 運転見合わせ)
test-results/live-stream-phase5a-bundle-railway-color-layer-1920.png  (メイン地図 鉄道路線カラー)
```

目視確認結果:

```text
地震子画面の小地図が実際のOSM/CARTOタイル地図として表示され、"Leaflet | © OpenStreetMap contributors © CARTO" の attribution が小さく表示されている
市区町村震度マーカーが小地図上に小さいバッジとして表示され、地図を覆い隠していない
広域地震で小地図の表示範囲が地震ごとに切り替わる (tour) ことを frame index/total のDOM属性でも確認
鉄道詳細overlayに路線名・状態チップ・事業者・更新時刻・詳細本文・出典が表示され、長文は自動スクロールしている
メイン地図の鉄道路線が単色ではなく、オレンジ(中央線系統)・緑(山手線)・水色(京浜東北線)等、路線ごとに異なる公式カラーで表示されている
影響路線 (中央線快速) が他の路線より太く/明るく強調されている一方、路線自体の色は変わっていない
左右パネル・下部テロップのレイアウトは崩れていない
```

補足: state=calm のスクリーンショットで地震子画面に固定デモ履歴 (HISTORY_12H) が表示されるのは Phase 5-A.1 以前からの既存挙動であり、本フェーズの変更対象外。

## Findings

なし (FAIL相当の不具合は検出されなかった)。

## Notes

以下はPASS with notes相当の既知の設計上の制約であり、後続フェーズでの改善候補とする。

```text
1. 鉄道詳細 (description) には backend 側に「影響区間」「原因」の個別フィールドが無いため、
   これらは常に description 全文の中に埋め込まれた自由文として表示している。ODPT側のデータが
   将来構造化されれば、個別欄への分割表示を検討できる。
2. メイン地図の鉄道路線カラーは protomaps-leaflet のタイル単位ベクタ描画のため、featureCount/
   coloredFeatureCount 等の詳細な diagnostics 計上ができない (loaded/layerCount/
   highlightedFeatureCount/lastError のみ)。
3. 地震子画面の小地図 tour は Phase 5-A.1 と同じ「都道府県単位・最大6グループ」のシンプルな
   フレーム分割のままであり、C-3で言及されている「地域ブロック単位」等の高度な分割は未実装。
4. 鉄道詳細の hold 判定は「現在 focus 中の鉄道 event が1件のみ」を前提にした設計であり、
   将来的に複数路線を同時に detail 表示する要件が生じた場合は再設計が必要。
```

## Final judgement

PASS with notes

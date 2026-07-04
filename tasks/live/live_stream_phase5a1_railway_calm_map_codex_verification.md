# live stream Phase 5-A.1 railway calm map verification

## 判定

PASS

## 検証日時

2026-07-04

## 対象ブランチ/コミット

main (作業ツリー、未コミット)

## Summary

`/live/stream` 鉄道情報小画面について、障害・運行影響が発生していない平常時 (`state=calm` 含む) でも、右側の地図が空白/背景のみ/文字だけにならず、首都圏のODPT対応路線が収まる範囲で路線図を表示することをCodex担当分として検証した。

- 鉄道子画面の小地図 (`#rail-map`) を、4路線のみの手描きSVGモックから、中央メイン地図と同じ Leaflet + PMTiles (全国鉄道路線データ、既存の公式カラー表を共有) の本番地図へ移行
- `LiveStreamRailwayLayer` を単一インスタンス前提から複数インスタンス対応 (`_instances` 配列, key別管理) へ拡張し、中央地図・鉄道子画面小地図の両方に同じ affected-highlight ロジックを適用できるようにした
- 小地図は初期化時に一度だけ固定 bounds (`STREAM_RAILWAY_DEFAULT_BOUNDS = [[35.50,139.45],[35.90,140.05]]`) を適用し、以後 pan/zoom し直さない (「路線図を表示するか」と「影響路線を強調するか」を分離)
- 路線レイヤーの初期化条件を「影響路線の有無」から完全に切り離した (影響0件でも layer は常に初期化される)
- キャプションを「首都圏路線図 · 影響路線のみ強調」→「首都圏路線図 · ODPT対応路線のみ監視」に変更し、「全国鉄道」「首都圏全路線」のような誤解を招く表現を避けた
- API失敗時は「一時的に取得不可」を表示し、「平常運転」「影響路線なし」と断定しない (既存ロジックのまま維持、地図背景も影響なく表示され続ける)

## 変更ファイル

```text
frontend/js/live-stream/live-stream-railway-layer.js  (単一instance→複数instance対応、getKnownRouteCount/isInstanceLoaded追加)
frontend/js/live-stream/live-stream-map-view.js        (rail-mini mode追加、鉄道レイヤーをcenter/rail-mini両方で初期化)
frontend/js/live-stream/live-stream-panels.js          (rail-miniマップsingleton初期化、鉄道小窓のマップ描画をLeaflet化+SVGフォールバック維持、railwayMiniMap diagnostics追加)
frontend/js/live-stream/live-stream-runtime.js         (railwayMiniMap diagnostics追加)
frontend/live/stream.html                              (#rail-mapへtestid追加、ODPT対応路線のみラベルへ変更)
```

## 追加ファイル

```text
e2e/live-stream-railway-calm-map.spec.js  (新規, 14テスト)
```

既存ファイル `e2e/live-stream-railway-color-layer.spec.js` の1テスト (`layerCount`期待値) を、鉄道子画面小地図も同じレイヤーを共有するようになった仕様変更に合わせて更新した (期待値 1→2、「増殖しない」ことの検証は維持)。

backend / data_runtime に変更なし。`/live` 本体は未変更。

## 静的確認

```bash
node --check frontend/js/live-stream/live-stream-runtime.js            # OK
node --check frontend/js/live-stream/live-stream-main.js                # OK
node --check frontend/js/live-stream/live-stream-panels.js              # OK
node --check frontend/js/live-stream/live-stream-railway-adapter.js     # OK
node --check frontend/js/live-stream/live-stream-railway-layer.js       # OK
node --check frontend/js/live-stream/live-stream-map-view.js            # OK
node --check frontend/js/live-stream/live-stream-focus-policy.js        # OK
node --check frontend/js/live-stream/live-stream-focus-controller.js    # OK
node --check e2e/live-stream.spec.js                                     # OK
node --check e2e/live-stream-railway-detail.spec.js                      # OK
node --check e2e/live-stream-railway-color-layer.spec.js                 # OK
node --check e2e/rail-mock-verify.spec.js                                # OK
node --check e2e/live-stream-railway-calm-map.spec.js                    # OK
```

作業ツリーには過去フェーズ由来の未コミット差分も含まれるが、今回の確認対象は `/live/stream` 鉄道小画面関連ファイル (上記) + 新規E2E。スコープ外領域 (地震小画面、キキクル/豪雨、潮位、メイン地図PMTiles再設計、backend) への追加変更はなし。

## Docker状態

```text
evacuation-navi-backend        Up (healthy)
evacuation-navi-frontend       Up
evacuation-navi-martin         Up (healthy)
evacuation-navi-osrm-walking   Up
```

## HTTP確認

```text
200  /live/stream
200  /live/stream?chrome=off
200  /live/stream?state=calm&chrome=off
200  /live/stream?demo=1&chrome=off
200  /live/stream?demo=1&focusSpeed=test&runtimeSpeed=test
200  /live
200  /
```

## calm / 平常時 鉄道小画面確認

`?state=calm&chrome=off` にて確認:

```text
鉄道小画面が表示される ✓
左側: 「影響路線なし」「平常運転」が表示される ✓
右側: 首都圏ODPT対応路線図が表示される (Leaflet+CARTOタイル + PMTiles路線、多数の色分けされた路線が見える) ✓
路線図が空白にならない ✓
路線が小画面内に収まっている (fixed bounds 適用済み) ✓
「首都圏路線図 · ODPT対応路線のみ監視」ラベルが表示され、既存ラベルと重ならない ✓
```

Diagnostics (`window.__LiveStreamDiagnostics.getSnapshot().railwayMiniMap`):

```json
{ "loaded": true, "defaultBoundsApplied": true, "routeCount": 111, "affectedCount": 0, "highlightedCount": 0, "lastError": null }
```

(`routeCount` は実描画feature数ではなく、公式カラー表に登録済みの路線名数。理由はNotes参照)

## 実データ影響0件 / mock確認

実データで影響路線0件の状態は、Playwright route mock (`/api/live/trains/summary` → `{items:[]}`) で確認した。

```text
右側に首都圏ODPT対応路線図が表示される ✓
左側「影響路線なし・平常運転」が表示される ✓
ヘッダー鉄道件数は既存仕様通り (件数0) ✓
デモ路線の混入なし (実データパイプラインとdemo=1は完全に分離済み、既存仕様のまま) ✓
```

## demo / 影響あり確認

`?demo=1&focusSpeed=test&runtimeSpeed=test&chrome=off` および mock (`live-stream-railway-detail.spec.js`, `live-stream-railway-calm-map.spec.js` の影響ありケース) で確認:

```text
影響路線カードが表示される ✓
右側路線図が表示される ✓
影響路線が強調される (highlightedCount が affectedCount と一致) ✓
既存の鉄道詳細overlay (#rail-overlay)・detail hold・auto-scrollは無改修で継続動作 ✓
```

## API失敗時確認

`/api/live/trains/summary` を 500 にして確認:

```text
左側: 「一時的に取得不可」「鉄道情報を取得できません」表示 ✓
「平常運転」「影響路線なし」と断定しない ✓ (テキストにこれらの文言が含まれないことを確認)
右側路線図の背景は維持される (レイヤーの初期化がfetch成否と独立しているため) ✓
console/page error なし ✓
```

## ODPT対応路線のみ表示ラベル確認

```text
「首都圏路線図 · ODPT対応路線のみ監視」がmap-cap位置に表示 ✓
文字サイズは既存map-capと同じ(10px)で読める ✓
既存の「平常監視」「影響 n路線」表示とは別要素で重ならない ✓
「全国鉄道」「首都圏全路線」等の誤解を招く文言は使用していない ✓
```

## 路線図表示範囲確認

目視確認 (スクリーンショット参照): 首都圏 (東京・埼玉・神奈川・千葉の一部) のODPT対応路線 (JR各線・東京メトロ・都営地下鉄等、色分け済み) が小画面内に収まっており、日本全国表示になって路線が豆粒になる、海だけになる、路線が画面外に出る、といったFAIL例には該当しない。

## E2E結果

```text
追加E2E単体: 14 passed (14.2s)
統合E2E（追加E2E込み）: 191 passed (4.5m)
```

対象:
- 新規 `e2e/live-stream-railway-calm-map.spec.js`: 14件 PASS
- 既存回帰 + 新規E2Eを含む `/live/stream` scoped suite: 191件 PASS

## スクリーンショット保存先

```text
test-results/live-stream-phase5a1-railway-calm-1920.png
test-results/live-stream-phase5a1-railway-normal-1920.png
test-results/live-stream-phase5a1-railway-demo-1920.png
test-results/live-stream-phase5a1-railway-failure-1920.png
```

failure スクリーンショットも取得済み (右側路線図の背景が取得失敗時も維持されていることを視覚的に確認できる)。

## `/live` 回帰確認

```text
HTTP 200 ✓
console/page error なし ✓
地図・地震・キキクル/豪雨・潮位・鉄道の各表示に副作用なし (frontend/js/live/ 配下は無変更) ✓
```

## `/` 回帰確認

```text
HTTP 200 ✓
console/page error なし ✓
基本地図表示に影響なし ✓
/live/stream CSS/JS の漏れなし ✓
```

## Notes

1. `live-stream-railway-color-layer.spec.js` の「4: repeated refresh does not accumulate railway layers/instances」は、以前は `layerCount === 1` (中央地図のみ) を期待していたが、今回の修正で鉄道子画面小地図にも同じレイヤーを載せるようになったため `layerCount === 2` (center + rail-mini) が正しい値になった。テストの意図 (「増殖しない」こと) は変えず、期待値のみ更新した。これは既存E2Eの破壊ではなく、仕様拡張に伴う正当な追随。
2. `routeCount` diagnostics は実際にビューポート内に描画されているfeature数ではなく、公式カラー表 (`_LINE_COLORS`) に登録済みの路線名の総数 (111件) を返す。protomaps-leaflet がタイル単位のベクタ描画で個々のfeatureをJS側に保持しないため、Phase 5-A bundle Part C と同様に正確な描画feature数は計上できない制約がある。
3. 固定bounds (`STREAM_RAILWAY_DEFAULT_BOUNDS`) は指示書の候補値をそのまま採用した。実際の画面での見え方は目視確認済みで首都圏路線が概ね収まっているが、将来的に微調整の余地はある。
4. 影響ありの状態でも小地図は同じ固定boundsのまま変化しない設計にした (Phase 5-A時点のSVGモックも影響有無でzoom/panを変えていなかったため、既存挙動を踏襲)。特定路線へズームインする要求は今回の指示書に含まれていないため未実装。

## 未対応項目

- 鉄道小画面の駅名ラベル表示 (対象外として明記されていたため未実装)
- ODPT期間限定路線対応 (対象外)
- 固定bounds以外の動的bounds算出 (指示書が固定boundsを推奨していたためこちらを採用)

## 次フェーズ候補

- Phase 5-B: OBS soak / 長時間安定性確認 へ進行可能

## 最終判断

PASS

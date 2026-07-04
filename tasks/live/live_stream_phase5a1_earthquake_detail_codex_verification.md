# live stream Phase 5-A.1 earthquake detail verification

## Result

PASS with notes

## Summary

`/live/stream` 左上「地震情報」子画面に、現在対象の地震に紐づく P2P 市区町村震度情報を追加した。

- メイン震源カードの下に市区町村震度リストを表示 (`#eq-muni` / `data-testid="live-stream-earthquake-municipal-panel"`)
- 多数市区町村時は縦マーキーで自動スクロール (`data-eq-muni-scroll-mode="scrolling"`)、少数時は静的表示 (`"static"`)
- 小地図 (`#eq-map`、既存SVG小窓を流用・新規Leafletインスタンスなし) に市区町村震度マーカーを描画、広域震度時は都道府県グループ単位で複数フレームを巡回 (`data-eq-mini-map-mode="tour"`)
- スクロール中/巡回中は `LiveStreamFocusController.requestHold()` で対象地震の切替をロック。ロックは「現在 focus 中の対象が hold 対象と一致する場合のみ」次への遷移を止めるよう限定し、無関係カテゴリの自動巡回は妨げない
- P2P詳細なし/取得失敗/空データでは「詳細取得中」「詳細なし」表示に留め、demo fallback しない
- `window.__LiveStreamDiagnostics.getSnapshot().earthquakeDetail` に状態を追加

## Checked files

```text
frontend/js/live-stream/live-stream-earthquake-detail.js   (新規, 正規化のみ)
frontend/js/live-stream/live-stream-earthquake-adapter.js  (points[] passthrough追加)
frontend/js/live-stream/live-stream-scene.js                (demo target に points 追加)
frontend/js/live-stream/live-stream-panels.js               (list/mini-map描画・hold連携・diagnostics)
frontend/js/live-stream/live-stream-focus-controller.js     (requestHold/releaseHold追加、getState()のhold自己失効化)
frontend/js/live-stream/live-stream-runtime.js               (earthquakeDetail diagnostics追加)
frontend/js/live-stream/live-stream-map.js                   (marker描画にcls/attrs/noRing拡張、後方互換)
frontend/css/live/live-stream.css                             (市区町村リスト/マーカー用CSS追加)
frontend/live/stream.html                                     (#eq-muni DOM追加、新規script読み込み)
e2e/live-stream-earthquake-detail.spec.js                      (新規, 15テスト)
```

backend / data_runtime に変更なし (P2P市区町村震度は既存 `backend/app/services/earthquake_source_p2p.py` の `points` フィールドをそのまま利用、正規化は stream 側で完結)。

`/live` 本体 (`frontend/js/live/`, `navigation.js` 等) は未変更。

## Environment

```text
docker compose: evacuation-navi-backend / -osrm-walking / -frontend / -martin 稼働中
E2E: DOCKER_BASE=http://127.0.0.1:8080 (nginx経由), Playwright chromium, 1 worker
```

## Commands

```bash
node --check frontend/js/live-stream/live-stream-earthquake-detail.js   # OK
node --check frontend/js/live-stream/live-stream-earthquake-adapter.js # OK
node --check frontend/js/live-stream/live-stream-panels.js              # OK
node --check frontend/js/live-stream/live-stream-scene.js                # OK
node --check frontend/js/live-stream/live-stream-focus-controller.js     # OK
node --check frontend/js/live-stream/live-stream-runtime.js               # OK
node --check frontend/js/live-stream/live-stream-map.js                   # OK
node --check e2e/live-stream-earthquake-detail.spec.js                     # OK

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
  e2e/live-stream-earthquake-detail.spec.js \
  e2e/eq-mock-verify.spec.js e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js e2e/rail-mock-verify.spec.js
```

backend に変更がないため `python -m compileall backend` は未実施 (対象なし)。

## Test results

```text
162 passed (3.3m)  ※上記コマンドの全13ファイル合算 (新規 e2e/live-stream-earthquake-detail.spec.js の15件を含む)
```

新規 `e2e/live-stream-earthquake-detail.spec.js` 内訳 (15件、指示書の14観点+静止リスト用の補助テスト1件):

```text
1: 市区町村震度リストがメイン震源カード下に表示される — PASS
2: 震度降順ソート — PASS
3: 座標ありは小地図markerになる — PASS
4: 座標なしはリストのみ・marker化されない — PASS
5: 多数市区町村で自動スクロール — PASS
5b: 少数市区町村は静的表示・小地図fit (補助) — PASS
6: スクロール中は対象地震が切り替わらない (hold) — PASS
7: 広域震度で小地図が複数frame巡回 — PASS
8: frame進行中も対象地震は切り替わらない — PASS
9: P2P/震源取得失敗で破綻しない — PASS
10: 対象消失で古いmarker/リストが残らない — PASS
11: demo=1 で同一detailパイプラインを通る — PASS
12: state=calmで詳細・marker非表示 — PASS
13: 繰り返しrefreshでmarker/row DOMが増殖しない — PASS
14: 通常/liveへの副作用なし — PASS
```

既存回帰 (147件 → 新規15件を除く既存分) もすべてPASS。実装途中で以下2件の回帰を検出しその場で修正済み (最終実行では両方PASS):

```text
- live-stream-focus-view.spec.js の "10b" (複数demo focus対象がactive markerを持つ回帰): 新設した
  requestHold が「現在focus中でない対象」まで巻き込んでグローバル自動巡回全体を止めてしまっていた。
  _advance() のhold判定を「現在focus中のeventが、hold対象と一致する場合のみ」に限定して修正。
- 座標辞書ロード完了前に地震eventのidが確定すると、その地震が対象である間ずっと「詳細取得中」に
  固まる不具合を自己テストで検出。_eqDetailTick (1秒毎) が辞書ロード完了後に再同期するよう修正。
```

## Diagnostics snapshot

`?demo=1&focusSpeed=test&runtimeSpeed=test&focus=off` にて `window.__LiveStreamDiagnostics.getSnapshot().earthquakeDetail`:

```json
{
  "activeEventId": "eq-demo-iwate",
  "municipalCount": 14,
  "markerCount": 13,
  "missingCoordinateCount": 1,
  "scrollMode": "scrolling",
  "scrollProgress": 0.0000595,
  "miniMapMode": "tour",
  "miniMapFrameIndex": 1,
  "miniMapFrameTotal": 5,
  "truncated": false,
  "holdActive": true
}
```

`byCategory` (fetch in-flight/成功/失敗カウント)・`dom` (marker/panel DOM件数)・`focusSubscribers` 等、既存 Phase 5-A diagnostics も正常に取得できることを確認。

## Manual browser check

```text
test-results/live-stream-phase5a1-earthquake-detail-normal-1920.png
test-results/live-stream-phase5a1-earthquake-detail-calm-1920.png
test-results/live-stream-phase5a1-earthquake-detail-demo-1920.png
test-results/live-stream-phase5a1-earthquake-detail-wide-tour-1920.png
```

目視確認結果:

```text
市区町村震度リストは読める文字サイズ・行間で表示されている
震度ラベル (5弱/3/2 等) が一目で分かる
小地図markerは小さく (直径約14px相当)、地図/震源markerを覆い隠していない
広域tour時、小地図の表示範囲が地震ごとの都道府県グループに応じて切り替わることを確認 (frame index/totalのDOM属性でも確認)
スクロールは実測 約1.2秒/行相当で、読める速度
左右パネル・下部テロップのレイアウトは崩れていない
state=calm では市区町村リスト・小地図markerとも非表示、既存の「現在、表示対象なし」表示は維持
```

補足: state=calm のスクリーンショットで地震子画面の「過去12時間の履歴」に固定デモ履歴 (HISTORY_12H) が表示されるのは Phase 5-A.1 以前からの既存挙動であり、本フェーズの変更対象外。

## Findings

なし (FAIL相当の不具合は検出されなかった)。

## Notes

以下はPASS with notes相当の既知の設計上の制約であり、後続フェーズでの改善候補とする。

```text
1. 小地図のtourフレーム分割は「都道府県単位・最大6グループ」のシンプルな実装であり、
   同一都道府県内でも震度分布が広い場合の細分割は行っていない (MVP範囲)。
2. 非常に多数の市区町村 (スクロール+tour合計の理想時間が60秒を超える場合) は
   MAX_HOLD_MS(60秒)で打ち切られ、全件を必ず一巡させる保証はない。この場合
   diagnostics.truncated=true が立つ設計になっているが、今回の検証データでは
   truncated=trueとなるケースは意図的には作成していない (実運用の巨大地震で発生しうる)。
3. 小地図は既存SVG簡易地図への座標変換ベースの overlay であり、Leafletのような
   正確な地形/行政界表示ではない (既存 /live の詳細市区町村マーカー機能とは表示方式が異なる)。
4. 座標辞書 (municipality_coords.json) に存在しない市区町村はリストのみに表示される。
   政令指定都市の区表記など住所解析パターンは /live 側の既存ロジックをそのまま移植したものを
   使用しており、新規のエッジケース対応は追加していない。
```

## Final judgement

PASS with notes

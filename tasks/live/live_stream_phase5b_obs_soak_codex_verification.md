# live stream Phase 5-B OBS soak verification

## 判定

PASS with notes

## 検証日時

2026-07-04 18:35 JST

## 対象ブランチ/コミット

main / c6d451c (作業ツリー、未コミット差分あり)

## Summary

`/live/stream` のOBS配信想定 `chrome=off` 表示について、Playwright Chromium 1920x1080 で通常30分soak、calm 10分、demo 10分、API失敗・復帰10分を実施した。

通常30分soakでは画面の白画面化、pageerror、重大なconsole error、ticker停止、時計停止、focus/hold詰まり、Leaflet instance増殖は確認されなかった。API失敗・復帰では、前半に `/api/live/*` 500 を注入して `runtimeState=error` と取得確認中文言になり、後半に通常APIへ戻すと `runtimeState=healthy` / 各カテゴリ `status=ok` へ復帰した。

60分soakとOBS実機確認は未実施。demo 10分中に `TypeError: Failed to fetch` が4件console errorとして出たが、pageerrorはなく、画面・ticker・focus・小画面・地図表示は継続したため notes 付きPASSとする。

## 変更ファイル

Phase 5-Bとしての実装修正はなし。

作成/更新:

```text
tasks/live/live_stream_phase5b_obs_soak_codex_verification.md
test-results/live-stream-phase5b-diagnostics.json
test-results/live-stream-phase5b-console.log
test-results/live-stream-phase5b-obs-soak-start-1920.png
test-results/live-stream-phase5b-obs-soak-15min-1920.png
test-results/live-stream-phase5b-obs-soak-30min-1920.png
test-results/live-stream-phase5b-obs-soak-calm-1920.png
test-results/live-stream-phase5b-obs-soak-demo-1920.png
```

検証用Playwrightプローブは `/private/tmp/live_phase5b_obs_soak_probe.js` に一時作成して実行した。リポジトリ配下には追加していない。

## 静的確認

以下すべて `node --check` OK。

```text
frontend/js/live-stream/live-stream-runtime.js
frontend/js/live-stream/live-stream-main.js
frontend/js/live-stream/live-stream-map-view.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-focus-policy.js
frontend/js/live-stream/live-stream-focus-controller.js
frontend/js/live-stream/live-stream-earthquake-adapter.js
frontend/js/live-stream/live-stream-earthquake-detail.js
frontend/js/live-stream/live-stream-railway-adapter.js
frontend/js/live-stream/live-stream-railway-layer.js
e2e/live-stream.spec.js
e2e/live-stream-main-map.spec.js
e2e/live-stream-main-map-real-data.spec.js
e2e/live-stream-event-sync.spec.js
e2e/live-stream-status-sync.spec.js
e2e/live-stream-auto-focus.spec.js
e2e/live-stream-stability.spec.js
e2e/live-stream-earthquake-detail.spec.js
e2e/live-stream-earthquake-detail-map-sync.spec.js
e2e/live-stream-railway-detail.spec.js
e2e/live-stream-railway-color-layer.spec.js
e2e/live-stream-railway-calm-map.spec.js
e2e/eq-mock-verify.spec.js
e2e/rain-mock-verify.spec.js
e2e/tide-mock-verify.spec.js
e2e/rail-mock-verify.spec.js
```

## Docker状態

```text
evacuation-navi-backend        Up (healthy)
evacuation-navi-frontend       Up
evacuation-navi-martin         Up (healthy)
evacuation-navi-osrm-walking   Up
```

backend health: `healthy`

## HTTP確認

soak前に以下すべて 200 OK。

```text
/live/stream
/live/stream?chrome=off
/live/stream?state=calm&chrome=off
/live/stream?demo=1&chrome=off
/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
/live
/
```

soak後:

```text
200  /live
200  /
```

## 既存E2E結果

```text
191 passed (4.5m)
```

対象:

```text
e2e/live-stream.spec.js
e2e/live-stream-main-map.spec.js
e2e/live-stream-main-map-real-data.spec.js
e2e/live-stream-event-sync.spec.js
e2e/live-stream-status-sync.spec.js
e2e/live-stream-auto-focus.spec.js
e2e/live-stream-stability.spec.js
e2e/live-stream-earthquake-detail.spec.js
e2e/live-stream-earthquake-detail-map-sync.spec.js
e2e/live-stream-railway-detail.spec.js
e2e/live-stream-railway-color-layer.spec.js
e2e/live-stream-railway-calm-map.spec.js
e2e/eq-mock-verify.spec.js
e2e/rain-mock-verify.spec.js
e2e/tide-mock-verify.spec.js
e2e/rail-mock-verify.spec.js
```

## 通常30分soak

URL:

```text
/live/stream?chrome=off
```

結果:

```text
pageerror: 0
console error: 0
runtimeState: healthy -> healthy
clock: 17:23:04 -> 17:53:04
Leaflet containers: 4 -> 4
railwayLayer.layerCount: 2 -> 2
tickerTextNodes: 2 -> 2
badTokens(undefined/null/NaN/Invalid Date/[object Object]): 0
```

diagnostics 抜粋:

```text
0分:  markers=5, focus=overview, railCards=0, railwayMiniMap loaded=true affected=0
5分:  markers=5, focus=rain-愛知県付近-, tickerNodes=2
10分: markers=6, focus=overview, tickerNodes=2
15分: markers=6, focus=earthquake, earthquakeDetail.markerCount=1
30分: markers=8, focus=odpt.Railway:MIR.TsukubaExpress, railCards=1, railwayMiniMap affected=1 highlighted=1
```

所見:

- 画面全体は白画面化せず、1920x1080内にヘッダー・中央地図・小画面・tickerが収まった
- 時計は30分進行した
- tickerは表示継続し、DOMノード数は増殖しなかった
- focusは overview / rain / earthquake / railway へ遷移し、詰まりなし
- 中央地図と小地図はいずれも表示維持
- 鉄道小画面の首都圏ODPT対応路線図は30分後も表示維持
- requestfailed は PMTiles の range/HEAD/GET abort のみで、pageerror/console error にはならなかった

## 60分soak

未実施。

理由: 30分通常soak + calm/demo/API復帰soakを優先した。指示書の PASS with notes 条件に該当。

## calm 10分soak

URL:

```text
/live/stream?state=calm&chrome=off
```

結果:

```text
pageerror: 0
console error: 0
runtimeState: healthy -> healthy
clock: 17:53:38 -> 18:03:38
map markers: 0 -> 0
Leaflet containers: 4 -> 4
railwayLayer.layerCount: 2 -> 2
railwayMiniMap routeCount: 111, affected=0, highlighted=0
badTokens: 0
```

所見:

- calm状態が維持された
- tickerは「監視中」表示を維持
- デモ警戒データの混入なし
- 鉄道小画面に首都圏ODPT対応路線図が表示された
- 地図・小画面の崩れなし

## demo 10分soak

URL:

```text
/live/stream?demo=1&chrome=off&focusSpeed=test&runtimeSpeed=test
```

結果:

```text
pageerror: 0
console error: 4
runtimeState: loading -> loading
clock: 18:03:51 -> 18:13:51
Leaflet containers: 4 -> 4
railwayLayer.layerCount: 2 -> 2
railCards: 4 -> 4
earthquakeDetail.markerCount: 13 -> 13
railwayMiniMap affected=4 highlighted=4
badTokens: 0
```

所見:

- demo表示は維持された
- 地震・豪雨・鉄道・潮位のデモ表示は継続
- focusは `kikikuru-静岡県 中部-land` から `eq-demo-iwate` へ遷移
- 地震詳細ミニ地図、鉄道小画面、tickerはいずれも表示継続
- console error `TypeError: Failed to fetch` が4件発生したが、pageerrorはなく画面破綻なし
- `runtimeState=loading` のままなのは demo モードで本番API refreshを走らせないためと見られる。実表示・focus・tickerは継続している

## API失敗・復帰確認

URL:

```text
/live/stream?chrome=off
```

方法:

- 0〜5分: `/api/live/earthquakes/history`, `/api/live/summary`, `/api/live/trains/summary`, `/api/live/tide/stations` を 500
- 5分以降: route を通常APIへ戻し、`window.__LiveStreamDiagnostics.forceRefresh()` を実行

結果:

```text
pageerror: 0
runtimeState: error -> healthy
consecutiveFailures: 3 -> 0
clock: 18:24:43 -> 18:34:49
Leaflet containers: 4 -> 4
tickerTextNodes: 2 -> 2
badTokens: 0
```

0分時点:

```text
runtimeState=error
eventCount=0
ticker=一部データの取得を確認中
map markers=0
各カテゴリ status=error
```

10分時点:

```text
runtimeState=healthy
eventCount=9
focusMode=focus
各カテゴリ status=ok
railwayMiniMap loaded=true affected=1 highlighted=1
```

所見:

- API 500 注入時も画面全体は壊れなかった
- 取得失敗を「平常」「なし」と断定せず、取得確認中文言になった
- API復帰後に healthy / ok へ戻った
- console error は意図的な 500 応答による browser console の `Failed to load resource` 20件

## diagnostics snapshot

保存先:

```text
test-results/live-stream-phase5b-diagnostics.json
```

比較結果:

```text
normal-30min:
  records=5
  pageerrors=0
  consoleErrors=0
  Leaflet containers 4 -> 4
  ticker nodes 2 -> 2
  railway layerCount 2 -> 2

calm-10min:
  records=3
  pageerrors=0
  consoleErrors=0
  markers 0 -> 0
  Leaflet containers 4 -> 4

demo-10min:
  records=3
  pageerrors=0
  consoleErrors=4
  Leaflet containers 4 -> 4
  railway layerCount 2 -> 2
  railway highlighted 4 -> 4

api-failure-recovery-10min:
  records=5
  pageerrors=0
  runtimeState error -> healthy
  consecutiveFailures 3 -> 0
```

## marker / layer / map instance 増殖

```text
Leaflet containers:
  normal: 4 -> 4
  calm:   4 -> 4
  demo:   4 -> 4
  api:    4 -> 4

railwayLayer.layerCount:
  normal: 2 -> 2
  calm:   2 -> 2
  demo:   2 -> 2
  api:    2 -> 2

tickerTextNodes:
  normal: 2 -> 2
  calm:   2 -> 2
  demo:   2 -> 2
  api:    2 -> 2
```

実データの変化により map marker 数や railCards は増減したが、EventStore/DOM更新に伴う単調増加ではなく、表示対象イベント数に応じた変化と判断した。

## console / pageerror

```text
normal-30min: pageerror=0, console error=0
calm-10min:   pageerror=0, console error=0
demo-10min:   pageerror=0, console error=4
api-recovery: pageerror=0, console error=20 (意図的な500)
```

requestfailed:

- PMTiles `railways_japan.pmtiles` の `net::ERR_ABORTED`
- 一部 CARTO tile の `net::ERR_ABORTED`
- API失敗シナリオ中の意図的な `/api/live/*` abort/500

いずれもページクラッシュ・pageerror・白画面化にはつながらなかった。

## メモリ/パフォーマンス所見

`window.__LiveStreamDiagnostics.getSnapshot().memory.usedJSHeapSize` の範囲:

```text
normal: 53.5MB -> 60.3MB
calm:   56.8MB -> 56.8MB
demo:   103MB -> 103MB
api:    42.1MB -> 42.1MB
```

Chrome DevTools の厳密な長時間プロファイルではなく diagnostics ベースの傾向確認。30分通常soakで急増し続ける兆候は確認されなかった。

## スクリーンショット

```text
test-results/live-stream-phase5b-obs-soak-start-1920.png
test-results/live-stream-phase5b-obs-soak-15min-1920.png
test-results/live-stream-phase5b-obs-soak-30min-1920.png
test-results/live-stream-phase5b-obs-soak-calm-1920.png
test-results/live-stream-phase5b-obs-soak-demo-1920.png
```

目視確認:

- start/15min/30min で主要UIが収まり、白画面化なし
- 30min で中央地図・小地図・ticker・鉄道小地図が表示維持
- calm で監視中表示、警戒デモ混入なし、鉄道路線図あり
- demo で各カテゴリのデモ表示、地震詳細/鉄道小画面/tickerが表示維持

## `/live` 回帰

soak後:

```text
HTTP 200
```

既存E2E内でも `/live` regression はPASS済み。

## `/` 回帰

soak後:

```text
HTTP 200
```

既存E2E内でも `/` regression はPASS済み。

## Notes

1. 60分soakとOBS実機確認は未実施。Playwright Chromium による 30分通常soak + 補助soakで代替したため PASS with notes。
2. demo 10分で `TypeError: Failed to fetch` console error が4件発生した。pageerrorはなく、UIは維持されたが、配信用の完全無音consoleを目指すなら別途調査対象。
3. requestfailed の多くは PMTiles/CARTO tile の `net::ERR_ABORTED`。地図表示は維持されており、Leafletのタイル/rangeリクエストキャンセル由来と見られる。
4. API失敗・復帰確認では、意図的に500を出したため browser console の `Failed to load resource` が出る。復帰後は `runtimeState=healthy` まで戻った。
5. demoモードでは diagnostics の `runtimeState` が `loading` のままだが、本番API refreshを使わない demo 表示のためと見られる。表示・focus・tickerは継続。

## 修正推奨事項

- demoモード中の `TypeError: Failed to fetch` の発生元を別途特定する
- demoモードの diagnostics `runtimeState=loading` が仕様として妥当か、必要なら `demo` / `synthetic` など別状態として表現する
- OBS実機または通常Chrome表示で60分以上のsoakを追加実施する

## 次フェーズ候補

- Phase 5-C: OBS実機/配信環境での60分以上soak
- Phase 5-C: console error / requestfailed のノイズ削減

## 最終判断

PASS with notes

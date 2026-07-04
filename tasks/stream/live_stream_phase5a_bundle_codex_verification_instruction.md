# CODEX用検証指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 5-A 統合対応：地震子画面本番地図化・鉄道子画面詳細化・メイン地図鉄道路線カラー反映 MVP 検証

## 目的

Claude実装後、`/live/stream` の Phase 5-A 統合対応が期待どおりに動作していることを検証する。

今回の検証対象は以下の3本。

```text
1. 地震情報 子画面 本番地図化・詳細表示同期
2. 鉄道情報 子画面 詳細化
3. メイン地図 鉄道路線カラー反映
```

Phase 5-B の実OBS soak検証へ進む前に、配信用画面として必要な情報伝達力と安定性を確認する。

---

## 前提

以下は完了済みとして回帰確認対象に含める。

```text
Phase 3-B: メイン地図 本番データ連動
Phase 3-C: event とパネル・テロップ同期
Phase 3-D: 全体ステータス・カテゴリバッジ・件数同期
Phase 4-A: 自動巡回・注目地域フォーカス
Phase 5-A: 配信用安定運用・長時間稼働対策
Phase 5-A.1: 地震情報 子画面詳細化
```

Phase 4-B は保留中のため、未実装であることを失敗条件にしない。

---

## 重要検証方針

単に画面に何かが出るだけではPASSにしない。

以下を重視する。

```text
地震概要・震度リスト・小地図が同じ地震idで同期している
地震子画面の小地図がモックではなく本番地図である
自動スクロール/小地図tour中に対象が勝手に切り替わらない
鉄道詳細がfocus中の障害路線と同期している
鉄道詳細スクロール中に対象が勝手に切り替わらない
メイン地図の鉄道路線に /live と同等の路線色が反映されている
marker / layer / ticker / panel / subscriber / timer が増殖しない
API失敗時にdemo fallbackしない
通常 /live に副作用がない
```

---

## 事前確認

まずガードレールと差分を確認する。

```bash
git diff --stat
git diff
```

確認対象例:

```text
docs/live/DEVELOPMENT_GUARDRAILS.md
tasks/stream/live_stream_phase5a_bundle_claude_instruction.md
frontend/live/stream.html
frontend/js/live-stream/
frontend/css/live/live-stream.css
e2e/live-stream*.spec.js
tasks/live/
```

特に以下を確認する。

```text
/live 本体にstream専用処理を混ぜすぎていないか
backend/data_runtimeを不要に変更していないか
既存APIレスポンス形式を破壊していないか
地図インスタンスやtimerを更新ごとに作り直していないか
demo fallbackで成功扱いしていないか
```

---

## 静的チェック

変更されたJS/E2Eに対して `node --check` を実行する。

例:

```bash
node --check frontend/js/live-stream/live-stream-runtime.js
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-event-store.js
node --check frontend/js/live-stream/live-stream-focus-controller.js
node --check frontend/js/live-stream/live-stream-map-view.js
node --check frontend/js/live-stream/live-stream-map-events.js
node --check frontend/js/live-stream/live-stream-earthquake-detail.js
node --check frontend/js/live-stream/live-stream-earthquake-detail-map.js
node --check frontend/js/live-stream/live-stream-railway-detail.js
node --check frontend/js/live-stream/live-stream-railway-layer.js
node --check e2e/live-stream-earthquake-detail.spec.js
node --check e2e/live-stream-earthquake-detail-map-sync.spec.js
node --check e2e/live-stream-railway-detail.spec.js
node --check e2e/live-stream-railway-color-layer.spec.js
```

実際のファイル名に合わせて読み替えること。

backend変更がある場合のみ:

```bash
python -m compileall backend
```

---

## Docker / HTTP確認

```bash
docker compose ps
```

必要に応じて:

```bash
docker compose up -d
```

以下が HTTP 200 であること。

```bash
curl -I http://127.0.0.1:8080/live/stream
curl -I "http://127.0.0.1:8080/live/stream?state=calm"
curl -I "http://127.0.0.1:8080/live/stream?demo=1"
curl -I "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test"
curl -I http://127.0.0.1:8080/live/stream.html
curl -I http://127.0.0.1:8080/live
curl -I http://127.0.0.1:8080/
```

---

## E2E実行

推奨実行範囲:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-stability.spec.js \
  e2e/live-stream-earthquake-detail.spec.js \
  e2e/live-stream-earthquake-detail-map-sync.spec.js \
  e2e/live-stream-railway-detail.spec.js \
  e2e/live-stream-railway-color-layer.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

存在しない新規spec名は、実装されたファイル名に合わせて変更すること。

注意:

```text
全 e2e/ を無理に実行してナビゲーション系の既存harness失敗で判定を濁さない。
block-ahead-reroute-generated.spec.js 等のナビ系ハーネスは今回の判定対象外。
```

---

# 検証観点 A：地震子画面 本番地図化

## A-1. 小地図が本番地図であること

確認:

```text
地震子画面の小地図がLeafletで初期化される
CARTO/OSMタイルが表示される
モック/SVGのみの地図ではない
ズームUIなし
ドラッグ不可
ホイールズーム不可
ダブルクリックズーム不可
キーボード操作不可
```

DOM / diagnostics / screenshot で確認する。

---

## A-2. 市区町村震度マーカー

P2P市区町村震度データをmockし、以下を確認する。

```text
市区町村ごとの震度マーカーが表示される
震度数字が表示される
震度マーカーが小さく地図を隠さない
対象地震idの震度データだけが表示される
地震切替時に前の地震の震度マーカーが残らない
marker数が更新ごとに増殖しない
```

震度種別を混ぜる。

```text
震度1
震度2
震度3
震度4
震度5弱
震度5強
震度6弱
震度6強
震度7
```

---

## A-3. 地震概要ヘッダー同期

確認:

```text
ヘッダーに発生時刻・震源・M・最大震度が表示される
ヘッダーの earthquake id がリスト・小地図と一致する
市区町村震度リストがどの地震の詳細か分かる
```

可能なら以下のような `data-*` を確認する。

```text
data-earthquake-detail-id
data-earthquake-intensity-list-id
data-earthquake-intensity-map-id
```

実装名に合わせて読み替える。

---

## A-4. リストスクロール完了まで切替hold

市区町村数が多い地震データをmockする。

確認:

```text
震度リストが自動スクロールする
スクロール中に次の地震へ切り替わらない
スクロール完了後に次の地震へ進む
hold release漏れがない
```

`focusSpeed=test` / `detailSpeed=test` 等のテスト短縮パラメータがある場合は利用してよい。

---

## A-5. 小地図tour完了まで切替hold

広域震度データをmockする。

確認:

```text
小地図が複数フレームを巡回する
巡回中に次の地震へ切り替わらない
全フレーム表示後に次の地震へ進む
巨大地震データでも無限に止まらない
```

都道府県単位分割など簡易実装の場合は PASS with notes 可。

---

## A-6. 座標辞書ロード遅延

座標辞書ロード前に地震idが確定するケースを作る。

確認:

```text
「詳細取得中」のまま固まらない
座標辞書ロード後に再同期する
期限超過時は詳細なし/座標なしとして表示し、pageerrorを出さない
```

---

## A-7. 失敗系

以下を確認する。

```text
P2P詳細空データ
P2P詳細 500
P2P詳細 404
P2P詳細 不正JSON
P2P詳細 timeout相当
座標なし市区町村
```

期待:

```text
pageerrorなし
地震概要は表示継続
demo fallbackなし
詳細取得中/詳細なし表示
小地図は壊れない
```

---

# 検証観点 B：鉄道子画面 詳細化

## B-1. 障害路線詳細表示

鉄道障害eventをmockする。

確認:

```text
路線名が表示される
事業者名が表示される
状態が表示される
影響区間が表示される、または未取得として非断定表示される
原因が表示される、または未取得として非断定表示される
詳細本文が表示される
更新時刻が表示される
出典が表示される、または既存仕様に従う
```

無い情報を推測していないこと。

---

## B-2. 詳細スクロール

長い詳細本文をmockする。

確認:

```text
詳細本文が長い場合に自動スクロールする
固定ヘッダーは残る
スクロール中に対象路線が切り替わらない
スクロール完了後に次へ進む
hold release漏れがない
```

---

## B-3. 失敗系

以下を確認する。

```text
鉄道詳細なし
鉄道詳細 500
鉄道詳細 404
鉄道詳細 不正JSON
鉄道詳細 timeout相当
```

期待:

```text
pageerrorなし
路線概要は表示継続
demo fallbackなし
詳細取得中/詳細なし表示
focusが永久停止しない
```

---

## B-4. 無関係カテゴリhold回帰

地震詳細や鉄道詳細のhold中に、無関係カテゴリの巡回が永久停止しないことを確認する。

確認:

```text
hold対象と現在focus対象が一致する場合のみholdが効く
別カテゴリに切り替わった後も古いholdが残らない
```

---

# 検証観点 C：メイン地図 鉄道路線カラー反映

## C-1. 路線色表示

確認:

```text
メイン地図に鉄道路線レイヤーが表示される
/live と同等の路線色が適用される
主要路線の色が識別できる
障害路線が平常路線より視認しやすい
```

首都圏代表例が使える場合:

```text
山手線: 黄緑系
中央線快速: オレンジ系
京浜東北線: 水色系
総武線: 黄色系
```

厳密なhex一致でなくても、既存 `/live` の色定義を流用していることを差分確認する。

---

## C-2. 表示密度

確認:

```text
路線色は分かる
地図を塗りつぶしていない
線幅が配信用として過剰でない
ラベルや駅名が邪魔になっていない
```

視認性に問題がある場合は PASS with notes または FAIL 判断する。

---

## C-3. レイヤー増殖なし

繰り返し更新またはfocus巡回を行い、以下を確認する。

```text
GeoJSON layer が増殖しない
path要素が更新ごとに増え続けない
marker count / layer count が安定する
pageerrorなし
```

Diagnostics に railwayLayer がある場合は利用する。

---

## C-4. 失敗系

鉄道路線GeoJSON取得失敗をmockする。

期待:

```text
メイン地図は表示継続
pageerrorなし
既存表示維持または路線レイヤーなし
データ取得確認中/error状態を適切に表現
demo fallbackなし
```

---

# 検証観点 D：安定性・diagnostics

`window.__LiveStreamDiagnostics.getSnapshot()` を確認する。

期待する代表項目:

```js
{
  earthquakeDetail: {
    activeEarthquakeId,
    detailStatus,
    intensityCount,
    markerCount,
    listScrollState,
    mapTourState,
    mapTourFrameIndex,
    mapTourFrameCount,
    holdActive
  },
  railwayDetail: {
    activeRailwayEventId,
    detailStatus,
    hasScrollableDetail,
    scrollState,
    holdActive
  },
  railwayLayer: {
    loaded,
    featureCount,
    coloredFeatureCount,
    highlightedFeatureCount,
    layerCount,
    lastError
  }
}
```

実装により名前が異なる場合は、同等情報が取得できればよい。

確認:

```text
normal / calm / demo / failure でsnapshotが取れる
pageerrorなし
subscriberCount / focusSubscribers が増え続けない
markerCount / layerCount が増え続けない
runtimeState が healthy / degraded / error へ妥当に遷移する
```

---

# 手動ブラウザ確認

以下のスクリーンショットを保存する。

```bash
npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=7000 \
  http://127.0.0.1:8080/live/stream \
  test-results/live-stream-phase5a-bundle-normal-1920.png

npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 \
  "http://127.0.0.1:8080/live/stream?state=calm&chrome=off" \
  test-results/live-stream-phase5a-bundle-calm-1920.png

npx playwright screenshot --viewport-size=1920,1080 --wait-for-timeout=5000 \
  "http://127.0.0.1:8080/live/stream?demo=1&focusSpeed=test&runtimeSpeed=test&chrome=off" \
  test-results/live-stream-phase5a-bundle-demo-1920.png
```

可能なら追加で以下を保存する。

```text
test-results/live-stream-phase5a-bundle-earthquake-map-1920.png
test-results/live-stream-phase5a-bundle-earthquake-wide-tour-1920.png
test-results/live-stream-phase5a-bundle-railway-detail-1920.png
test-results/live-stream-phase5a-bundle-railway-color-layer-1920.png
```

目視確認:

```text
地震子画面で小地図が実地図として認識できる
震度マーカーが小さく読みやすい
地震ヘッダーにより、どの地震の詳細か分かる
鉄道詳細が読みやすい
路線色が視聴者の認識に近い
地図・パネル・テロップを邪魔していない
重複描画やチラつきがない
```

---

# 検証レポート作成

以下にレポートを作成する。

```text
tasks/live/live_stream_phase5a_bundle_detail_and_railway_codex_verification.md
```

レポート構成:

```md
# live stream Phase 5-A bundle detail and railway verification

## Result

PASS / FAIL / PASS with notes

## Summary

## Checked files

## Environment

## Commands

## Test results

## Earthquake detail map verification

## Railway detail verification

## Railway color layer verification

## Diagnostics snapshot

## Failure / recovery checks

## Manual browser check

## Screenshots

## Findings

## Notes

## Final judgement
```

---

# PASS条件

以下を満たす場合 PASS。

```text
/live/stream が HTTP 200
地震子画面の小地図が本番地図化されている
市区町村震度マーカーが対象地震idと同期して表示される
地震概要ヘッダー・震度リスト・小地図が同じ地震idで同期する
リストスクロール/小地図tour中に対象が勝手に切り替わらない
鉄道子画面に障害路線の詳細が表示される
鉄道詳細スクロール中に対象が勝手に切り替わらない
メイン地図の鉄道路線に /live と同等の路線色が反映される
marker / layer / ticker / panel / subscriber / timer が増殖しない
API失敗・空データ・不正JSON・timeoutでpageerrorなし
demo fallbackなし
state=calm / demo=1 / 通常表示が維持される
地図操作不可が維持される
Phase 3-D / 4-A / 5-A / 5-A.1 の回帰がない
通常 /live に明確な副作用がない
関連E2EがPASS
検証レポートが作成されている
```

---

# FAIL条件

以下があれば FAIL。

```text
/live/stream が表示できない
地震子画面の小地図が壊れる
震度リストと小地図が別の地震idを表示する
リストスクロール中に対象が勝手に切り替わる
小地図tour中に対象が勝手に切り替わる
hold release漏れで巡回が止まる
鉄道詳細が別路線の情報を表示する
鉄道詳細スクロール中に対象が勝手に切り替わる
鉄道路線レイヤーが更新ごとに増殖する
marker / DOM / subscriber / timer が増殖する
API失敗でpageerror/unhandledrejectionが出る
通常表示でdemo fallbackしている
地図操作不可が解除されている
通常 /live が壊れている
```

---

# PASS with notes 条件

以下は PASS with notes 可。

```text
小地図tourが都道府県単位など簡易分割
巨大地震では表示フレーム数上限により一部打ち切り
鉄道詳細の一部項目がデータソース不足で未取得表示
路線色が完全な公式hex一致ではないが /live と同等の色定義を流用
GeoJSON失敗時は路線非表示だが画面は維持
5〜15分OBS soakは未実施
```

---

# 最終判断

検証完了後、以下を明記する。

```text
PASS
FAIL
PASS with notes
```

PASS with notes の場合は、後続フェーズで対応すべき制約を具体的に列挙すること。

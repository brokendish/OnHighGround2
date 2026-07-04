# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 5-A 統合対応：地震子画面本番地図化・鉄道子画面詳細化・メイン地図鉄道路線カラー反映 MVP

## 目的

OnHighGround2 内の `/live/stream` について、Stream Phase 5-B（OBS実運用リハーサル・長時間soak検証）へ進む前に、配信用画面として不足している情報伝達力をまとめて改善する。

今回の対象は以下の3本を一括で扱う。

```text
1. 地震情報 子画面 本番地図化・詳細表示同期
2. 鉄道情報 子画面 詳細化
3. メイン地図 鉄道路線カラー反映
```

既に完了済みの Phase 5-A / 5-A.1 の安定運用基盤・地震詳細基盤を壊さず、視聴者が「どの災害情報を見ているのか」「どこで起きているのか」「どの程度影響があるのか」を配信画面だけで理解できる状態にする。

---

## 既存完了フェーズの前提

以下は完了済みとして扱い、回帰させないこと。

```text
Stream Phase 3-B:
  メイン地図 本番データ連動 MVP

Stream Phase 3-C:
  メイン地図 event と左右パネル・テロップ同期 MVP

Stream Phase 3-D:
  全体ステータス・カテゴリバッジ・件数表示同期 MVP

Stream Phase 4-A:
  自動巡回・注目地域フォーカス MVP

Stream Phase 4-B:
  CODEX制限により保留。今回の前提にしない。

Stream Phase 5-A:
  配信用安定運用・長時間稼働対策 MVP

Stream Phase 5-A.1:
  地震情報 子画面詳細化 MVP
```

特に Phase 5-A の以下の安定運用要件は必ず維持する。

```text
fetch 多重起動防止
in-flight guard
marker / ticker / panel / subscriber 増殖防止
API 500 / 404 / timeout / 不正JSON で pageerror なし
継続失敗時 degraded / error
復旧時 healthy
diagnostics snapshot
通常 /live への副作用なし
```

---

## 重要方針

### 1. `/live` 本体を壊さない

通常 `/live` の既存UI、既存JS、既存API挙動を壊さないこと。

`/live/stream` 用の処理は原則として以下に閉じる。

```text
frontend/live/stream.html
frontend/js/live-stream/
frontend/css/live/live-stream.css
frontend/css/live/stream系ファイルがある場合はそれ
```

禁止:

```text
/live 本体の地図・パネル・レイヤー挙動を stream 都合で変更する
既存APIレスポンス形式を stream 都合で破壊する
通常 /live の鉄道表示や地震表示に副作用を出す
```

---

### 2. EventStore / FocusController / Runtime を壊さない

既存の `/live/stream` は以下を中心に同期している。

```text
LiveStreamEventStore
LiveStreamFocusPolicy
LiveStreamFocusController
LiveStreamRuntime
LiveStreamDiagnostics
```

今回の追加もこの流れに乗せる。

特に以下を守る。

```text
DOMスクレイピングを主データ源にしない
同じ正規化 event id を地図・パネル・テロップ・詳細子画面で共有する
focus中のeventと詳細表示中のeventがズレないようにする
自動スクロール/小地図巡回中は必要な範囲で hold する
hold が無関係カテゴリの巡回まで止めないようにする
```

---

### 3. demo fallback 禁止

本番データ取得失敗時に demo 表示へ勝手に fallback してはいけない。

期待挙動:

```text
P2P詳細なし:
  詳細取得中 / 詳細なし を表示

鉄道詳細なし:
  詳細取得中 / 詳細なし / 公式情報未取得 を表示

路線色データなし:
  デフォルト線色または既存スタイルにフォールバック

API失敗:
  画面は維持
  pageerrorなし
  demo dataへ逃げない
```

---

### 4. 配信用画面として読みやすさ優先

OBS / YouTube 配信用の「見るだけ」画面なので、操作UIは増やさない。

```text
クリック前提にしない
ホバー前提にしない
スクロールバーを見せすぎない
文字は1920x1080配信で読めるサイズを維持
地図をマーカーや路線で汚しすぎない
```

---

# 実装対象 A：地震情報 子画面 本番地図化・詳細表示同期 MVP

## 背景

Phase 5-A.1 で地震子画面に P2P 市区町村震度リストと小地図マーカーを追加した。

ただし現状の小地図がモック/SVG風で、視聴者が「どこの震度情報なのか」を直感的に把握しにくい。

また、市区町村震度スクロールリストが「何時に発生したどの地震に対する情報なのか」分かりにくい。

今回、地震子画面を以下の状態にする。

```text
対象地震の概要ヘッダー
同じ地震idの市区町村震度スクロールリスト
同じ地震idの市区町村震度マーカー付き本番小地図
リスト/地図巡回が完了するまで次の地震へ切り替えない
完了後に次の地震詳細へ進む
```

---

## A-1. 小地図を本番地図化

地震子画面の小地図を、CARTO/OSM/Leaflet など Phase 3-A のメイン地図と同等の本番地図基盤にする。

要件:

```text
Leaflet地図を使用
CARTO/OSMタイルを使用
小地図は操作不可
ズームUIなし
ドラッグ不可
ホイールズーム不可
ダブルクリックズーム不可
キーボード操作不可
attributionは小さく表示、または既存メイン地図のattribution設計と衝突しない形で表示
```

重要:

```text
地震切替ごとに Leaflet インスタンスを作り直さない
小地図 Leaflet は singleton 的に再利用する
marker layer / label layer だけ差し替える
tile layer を増殖させない
長時間表示でDOMやmarkerが増殖しない
```

推奨ファイル:

```text
frontend/js/live-stream/live-stream-earthquake-detail-map.js
frontend/js/live-stream/live-stream-earthquake-detail.js 既存拡張
frontend/css/live/live-stream.css 既存拡張
```

既存ファイル名が異なる場合は既存構成に合わせる。

---

## A-2. 震度マーカー仕様

P2P市区町村震度データに座標がある場合、小地図に震度マーカーを表示する。

要件:

```text
市区町村ごとに震度マーカーを配置
震度数字を表示
マーカーは小さく、地図を隠さない
震度が高いほど少し目立たせる
最大震度地点はやや強調してもよい
```

震度表記例:

```text
1
2
3
4
5-
5+
6-
6+
7
```

CSS class 例:

```css
.stream-eq-intensity-marker
.stream-eq-intensity-marker--1
.stream-eq-intensity-marker--2
.stream-eq-intensity-marker--3
.stream-eq-intensity-marker--4
.stream-eq-intensity-marker--5-lower
.stream-eq-intensity-marker--5-upper
.stream-eq-intensity-marker--6-lower
.stream-eq-intensity-marker--6-upper
.stream-eq-intensity-marker--7
.stream-eq-intensity-marker--active
```

注意:

```text
マーカーが多い場合でも地図を塗りつぶさない
全市区町村名を地図上へ常時表示しない
数字中心の小型マーカーにする
詳細名はリスト側に任せる
```

---

## A-3. 小地図のfit/tour制御

震度マーカー範囲に応じて小地図を自動調整する。

基本:

```text
震度マーカーが少数/狭域:
  全震度マーカーが収まるboundsへfit

震度マーカーが広域:
  都道府県単位、地域単位、またはbounds分割で複数フレーム巡回

震度マーカーが全国規模:
  代表フレーム数に上限を設けて巡回
```

重要:

```text
全範囲の巡回が終わるまで次の地震情報へ切り替えない
ただし巨大地震で無限に長くならないよう上限を設ける
上限で打ち切った場合は diagnostics / notes に残す
```

推奨上限:

```text
小地図tourフレーム: 最大8〜12程度
1フレーム表示: 3〜5秒程度
E2E用には mapTourSpeed=test 等の短縮パラメータを許容
```

既に Phase 5-A.1 の都道府県単位巡回がある場合は、それを本番Leaflet小地図へ接続する。

---

## A-4. 地震概要ヘッダーとリスト同期

市区町村震度リストの上部に、対象地震の概要を固定表示する。

表示例:

```text
19:21　岩手県沖　M6.1　最大震度5弱
市区町村震度詳細
```

または既存UIに合わせて以下を表示する。

```text
発生時刻
震源地名
マグニチュード
最大震度
深さ
津波有無がある場合は簡潔に
```

要件:

```text
概要ヘッダーはスクロールしない
市区町村震度リストのみスクロールする
ヘッダー、リスト、小地図は必ず同じ earthquakeEventId / earthquakeId を参照する
```

DOM属性例:

```html
<section data-earthquake-detail-id="eq-xxx">
  <div data-earthquake-detail-header></div>
  <div data-earthquake-intensity-list></div>
  <div data-earthquake-intensity-map></div>
</section>
```

---

## A-5. 詳細表示シーケンス制御

複数地震がある場合、対象地震ごとに以下を完了してから次へ進む。

```text
1. 対象地震の概要ヘッダー表示
2. 対象地震の市区町村震度リスト表示
3. 必要ならリストを自動スクロール
4. 小地図に対象地震の震度マーカー表示
5. 必要なら小地図tourを実行
6. リストスクロールと小地図tourの両方が完了
7. hold解除
8. 次の地震詳細へ進む
```

切替条件:

```text
リストスクロール未完了なら次へ進まない
小地図tour未完了なら次へ進まない
詳細取得中の場合は短時間待つ
取得失敗/詳細なしの場合は一定時間表示して次へ進む
```

重要:

```text
FocusController.requestHold/releaseHold を使用する場合、hold対象が現在focus中の地震eventと一致する場合のみ巡回を止める
無関係のカテゴリ、例えば鉄道focusまで永久停止させない
release漏れで巡回が止まらないよう timeout fallback を持つ
```

---

## A-6. diagnostics

`window.__LiveStreamDiagnostics.getSnapshot()` に地震詳細関連の状態を追加または拡張する。

例:

```js
{
  earthquakeDetail: {
    activeEarthquakeId: "eq-xxx",
    detailStatus: "ready", // loading | ready | empty | error
    intensityCount: 84,
    markerCount: 84,
    listScrollState: "running", // idle | running | done
    mapTourState: "running",    // idle | running | done
    mapTourFrameIndex: 2,
    mapTourFrameCount: 6,
    holdActive: true,
    holdReason: "earthquake-detail-tour"
  }
}
```

必須ではないが、E2Eで検証しやすいようにする。

---

# 実装対象 B：鉄道情報 子画面 詳細化 MVP

## 背景

現在の鉄道子画面は、障害路線の概要表示が中心。

配信画面としては、視聴者に以下が分かる必要がある。

```text
どの路線で
どの区間に
どのような影響があり
原因は何で
更新時刻はいつか
```

---

## B-1. 障害路線1件の詳細表示

自動巡回/focus中の鉄道eventに対応する子画面で、詳細情報を表示する。

表示候補:

```text
路線名
事業者名
状態: 遅延 / 運転見合わせ / 一部運休 / 直通中止 / 平常ではない状態
影響区間
原因
詳細本文
更新時刻
出典
```

既存ODPT/JARTIC/鉄道adapterにある情報のみ使う。

無い情報は無理に推測しない。

```text
影響区間不明
原因未取得
詳細未取得
```

のように非断定表示にする。

---

## B-2. 詳細リストの自動スクロール

鉄道詳細が長い場合、子画面内で自動スクロールして全体を表示する。

要件:

```text
詳細本文が短い場合はスクロールしない
長い場合のみ自動スクロール
スクロール完了まで同じ鉄道eventを表示
スクロール完了後に次のfocus/sceneへ進む
```

実装方針:

```text
スクロール領域と固定ヘッダーを分ける
路線名/状態/更新時刻は固定表示
詳細本文だけスクロール
```

DOM属性例:

```html
<section data-railway-detail-id="rail-xxx">
  <div data-railway-detail-header></div>
  <div data-railway-detail-scroll></div>
</section>
```

---

## B-3. hold制御

鉄道詳細の自動スクロール中は、対象切替をholdする。

要件:

```text
hold対象は現在focus中の鉄道eventに限定
無関係カテゴリの巡回まで止めない
スクロール完了でrelease
取得失敗/詳細なしの場合は短時間表示してrelease
release漏れ防止のtimeout fallbackを持つ
```

---

## B-4. diagnostics

`window.__LiveStreamDiagnostics.getSnapshot()` に鉄道詳細状態を追加する。

例:

```js
{
  railwayDetail: {
    activeRailwayEventId: "rail-xxx",
    detailStatus: "ready", // loading | ready | empty | error
    hasScrollableDetail: true,
    scrollState: "running", // idle | running | done
    holdActive: true,
    holdReason: "railway-detail-scroll"
  }
}
```

---

# 実装対象 C：メイン地図 鉄道路線カラー反映 MVP

## 背景

`/live/stream` のメイン地図に鉄道路線レイヤーが表示されているが、路線色が `/live` と同じ公式/準公式カラーになっていない。

視聴者は自分の地域の鉄道路線色を強く認識しているため、路線色があると理解速度が上がる。

例:

```text
山手線: 黄緑
中央線快速: オレンジ
京浜東北線: 水色
総武線: 黄色
```

---

## C-1. `/live` と同じ鉄道路線色を流用

通常 `/live` 側で実装済みの鉄道路線カラー定義・表記ゆれ対応・公式カラー対応がある場合は、それを流用する。

確認対象例:

```text
frontend/js/live/railway系
frontend/js/live/live-railway-layer系
frontend/js/live/stream/live-stream-railway-layer.js
frontend/css/live/railway系
```

要件:

```text
/live と同じ色定義をできるだけ共有
stream側で重複定義する場合も出典/理由を明記
表記ゆれに対応
障害路線は通常路線より強調
平常路線は控えめ
```

---

## C-2. stream用の描画密度調整

`/live/stream` は配信用であり、操作用ではない。

そのため `/live` よりもやや控えめな表示にする。

要件:

```text
路線色は分かる
ただし地図を塗りつぶさない
線幅は控えめ
障害路線は少し太く/明るく
平常路線は細く/薄く
駅名・ラベルが邪魔なら出さない、または既存stream仕様を維持
```

推奨:

```text
通常路線: 1.0〜1.5px 程度
障害路線: 2.0〜3.0px 程度
不透明度: stream背景に合わせて調整
```

既存実装と合わない場合は、見やすさ優先で調整する。

---

## C-3. パフォーマンスと安定性

鉄道路線レイヤーは重くなりやすい。

Phase 5-A の安定運用を壊さないこと。

要件:

```text
レイヤーを更新ごとに増殖させない
GeoJSON layer を重複追加しない
style再適用で済むなら再作成しない
データ取得失敗時にpageerrorを出さない
表示件数/描画量に上限またはズーム制御を持つ
```

---

# 共通テスト要件

E2E を追加または更新する。

推奨追加ファイル:

```text
e2e/live-stream-earthquake-detail-map-sync.spec.js
e2e/live-stream-railway-detail.spec.js
e2e/live-stream-railway-color-layer.spec.js
```

既存 `e2e/live-stream-earthquake-detail.spec.js` がある場合は拡張してよい。

---

## E2E観点 A：地震子画面

必須確認:

```text
1. 地震子画面の小地図が Leaflet/CARTO/OSM タイルで表示される
2. 小地図に市区町村震度マーカーが表示される
3. 震度マーカーは対象地震idに紐づくデータのみ表示される
4. 地震概要ヘッダーに発生時刻・震源・M・最大震度が表示される
5. ヘッダー、リスト、小地図が同じ earthquake id を参照する
6. リストスクロール完了まで次の地震へ切り替わらない
7. 小地図tour完了まで次の地震へ切り替わらない
8. 詳細なし/空データ/失敗時にdemo fallbackしない
9. 小地図Leafletインスタンスやmarkerが更新で増殖しない
10. diagnostics.earthquakeDetail が妥当な値を返す
```

---

## E2E観点 B：鉄道子画面

必須確認:

```text
1. 障害路線1件の詳細が表示される
2. 路線名・事業者・状態・影響区間・原因・更新時刻が表示される、または未取得時に非断定表示される
3. 詳細本文が長い場合に自動スクロールする
4. スクロール完了まで対象路線が切り替わらない
5. 詳細なし/空データ/失敗時にdemo fallbackしない
6. diagnostics.railwayDetail が妥当な値を返す
7. 無関係カテゴリのfocusまでholdし続けない
```

---

## E2E観点 C：鉄道路線カラー

必須確認:

```text
1. メイン地図に鉄道路線レイヤーが表示される
2. `/live` と同等の路線色が適用される
3. 障害路線が平常路線より視認しやすい
4. 路線レイヤーが更新ごとに増殖しない
5. GeoJSON取得失敗時にpageerrorが出ない
6. 地図操作不可が維持される
7. attribution が維持される
```

---

## E2E観点 D：既存回帰

既存の関連テストを実行する。

推奨:

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

全 `e2e/` を無理に実行して、ナビゲーション系の既存harness失敗で混乱しないこと。

`block-ahead-reroute-generated.spec.js` 等のナビ系ハーネスは今回の判定対象外。

---

# エラー・空データ時の期待挙動

```text
P2P震度詳細取得失敗:
  地震概要は表示継続
  市区町村震度欄は「詳細取得中」または「詳細なし」
  小地図は震源周辺または全国overview
  demo fallbackなし

P2P震度座標辞書未ロード:
  固まらず、ロード後に再同期
  期限超過時は詳細なし扱い

鉄道詳細取得失敗:
  路線概要は表示継続
  詳細欄は「詳細取得中」または「詳細なし」
  demo fallbackなし

鉄道路線GeoJSON取得失敗:
  メイン地図は表示継続
  路線レイヤーなし、または既存表示維持
  pageerrorなし
```

---

# diagnostics 要件

既存 `window.__LiveStreamDiagnostics.getSnapshot()` を拡張する。

少なくとも以下が確認できるとよい。

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

既存snapshot構造に合わせてよい。

---

# スクリーンショット確認

以下を保存できる状態にする。

```text
test-results/live-stream-phase5a-bundle-earthquake-map-1920.png
test-results/live-stream-phase5a-bundle-earthquake-wide-tour-1920.png
test-results/live-stream-phase5a-bundle-railway-detail-1920.png
test-results/live-stream-phase5a-bundle-railway-color-layer-1920.png
test-results/live-stream-phase5a-bundle-calm-1920.png
test-results/live-stream-phase5a-bundle-demo-1920.png
```

---

# 完了条件

以下を満たしたら完了。

```text
地震子画面の小地図が本番地図化される
市区町村震度マーカーが小地図に表示される
地震概要ヘッダー・震度リスト・小地図が同じ地震idで同期する
リストスクロール/小地図tour完了まで次の地震へ切り替わらない
鉄道子画面に障害路線の詳細が表示される
鉄道詳細が長い場合は自動スクロールし、完了まで切替をholdする
メイン地図の鉄道路線に /live と同等の路線色が反映される
marker / layer / ticker / panel / subscriber / timer が増殖しない
API失敗・空データ・不正JSON・timeoutでpageerrorなし
demo fallbackなし
state=calm / demo=1 / 通常表示が維持される
地図操作不可が維持される
Phase 3-D / 4-A / 5-A / 5-A.1 の回帰がない
通常 /live に明確な副作用がない
関連E2EがPASS
検証レポート作成可能な状態
```

---

# 注意

今回の範囲は Phase 5-B の実OBS soak検証ではない。

Phase 5-B に進む前の配信用情報表示強化である。

また、Phase 4-B は保留中のため、Phase 4-B の演出改善が未実装であることを失敗条件にしない。

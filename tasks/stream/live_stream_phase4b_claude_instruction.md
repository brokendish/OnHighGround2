# Claude用実装指示書
# 総合災害ビューア全国監視 / `/live/stream`
# Stream Phase 4-B：自動巡回ビュー演出・フォーカス表示改善 MVP

## 目的

`/live/stream` の Phase 4-A で実装された自動巡回・注目地域フォーカスを、OBS / YouTube 配信用の監視卓ビューとして見やすく改善する。

Phase 4-A では以下が完了している。

- `LiveStreamEventStore` の正規化 event を起点に focus 候補を選定
- `LiveStreamFocusPolicy.selectCandidates(events)` による DOM 非依存の候補選定
- `LiveStreamFocusController` による `overview` / `focus` / `returning` 状態管理
- `body[data-stream-focus-mode]`
- `body[data-stream-focus-event-id]`
- 地図 marker / panel item / ticker 「注目」の focus id 同期
- calm / empty / failure 時に focus しない安全挙動

Phase 4-B では、機能追加を広げすぎず、以下に絞る。

```text
自動巡回中に、いま何を見ているのか配信視聴者に分かりやすくする
overview → focus → returning の画面遷移を自然にする
focus 対象のラベル・強調・地図表示を見やすくする
既存 EventStore / FocusController / Phase 3-D 同期を壊さない
```

---

## 重要方針

### 1. Phase 4-A の状態管理を壊さない

Phase 4-B は演出・表示改善フェーズであり、focus の根本ロジックを作り直さない。

維持するもの:

```text
LiveStreamEventStore
LiveStreamFocusPolicy
LiveStreamFocusController
body[data-stream-focus-mode]
body[data-stream-focus-event-id]
地図 marker / panel item / ticker の focus id 同期
Phase 3-D の badge/count/status 同期
```

禁止:

```text
DOM スクレイピングで focus 対象を再判定する
panel 表示から逆算して focus 対象を作る
EventStore とは別の独自イベント配列を作る
FocusController を無視して地図だけ勝手に移動する
/live 本体へ stream 専用分岐を混ぜる
```

---

### 2. 配信用として控えめな演出にする

OBS / YouTube 配信画面なので、派手すぎるアニメーションは避ける。

目標:

```text
視聴者が「今どこを見ているか」分かる
文字が読みやすい
地図・パネル・テロップを邪魔しない
長時間表示しても疲れない
点滅しすぎない
```

禁止寄り:

```text
強い点滅
激しいズームイン/ズームアウト
画面全体を覆う演出
テロップを隠す
左右パネルを隠す
常時大きなモーダル表示
```

---

### 3. `/live` 通常画面に副作用を出さない

`/live/stream` 専用の JS / CSS に閉じること。

通常 `/live` の既存 UI、既存地図、既存レイヤー、既存パネルを変更しない。

---

## 実装対象

Phase 4-B の MVP 対象は以下。

```text
1. Focus HUD / 注目ラベルの改善
2. 地図 focus 表示の改善
3. パネル active 表示の改善
4. テロップ「注目」表示の改善
5. overview / focus / returning の視覚状態整理
6. calm / error / empty 時の安全表示維持
7. prefers-reduced-motion 対応
```

---

## 推奨ファイル構成

既存構成を優先する。

既存ファイル例:

```text
frontend/live/stream.html
frontend/css/live/live-stream.css
frontend/js/live-stream/live-stream-focus-controller.js
frontend/js/live-stream/live-stream-map-view.js
frontend/js/live-stream/live-stream-map-events.js
frontend/js/live-stream/live-stream-panels.js
frontend/js/live-stream/live-stream-main.js
```

必要に応じて、演出専用 helper を追加してもよい。

追加する場合の例:

```text
frontend/js/live-stream/live-stream-focus-view.js
```

ただし、ファイルを増やしすぎない。
MVP では既存の focus-controller / map-view / panels / CSS への最小差分でよい。

---

## 実装要件

## 1. Focus HUD / 注目ラベル改善

中央地図上に、現在の focus 状態を示す小さな HUD を表示する。

表示位置の推奨:

```text
中央地図の上部中央、または左上寄り
左右パネルや下部テロップを隠さない位置
```

表示内容:

### overview 時

```text
全国モニタ
監視中
```

または既存表示を維持してよい。

### focus 時

```text
注目：中央線快速　見合わせ
鉄道 / high
```

または、event の情報から以下を表示する。

```text
title
subtitle
category label
severity label
```

例:

```text
注目：岩手県沖
M6.1 / 最大震度5弱
```

```text
注目：静岡県 中部
キキクル「危険」
```

```text
注目：中央線快速
見合わせ / 人身事故
```

### returning 時

```text
全国表示へ戻ります
```

ただし、returning が短い場合は表示しなくてもよい。

---

## 2. HUD の DOM 属性

E2E で安定検証できるよう、HUD には data 属性を付与する。

推奨:

```html
<div class="stream-focus-hud"
     data-testid="stream-focus-hud"
     data-focus-mode="focus"
     data-focus-event-id="rail-sync-001"
     data-focus-type="railway"
     data-focus-severity="high">
</div>
```

最低限:

```text
data-testid="stream-focus-hud"
data-focus-mode
data-focus-event-id
```

`body[data-stream-focus-mode]` / `body[data-stream-focus-event-id]` と矛盾しないこと。

---

## 3. 地図 focus 表示の改善

focus 中の marker を視覚的に分かりやすくする。

既存 active class がある場合は活用する。

推奨 class:

```text
.stream-map-event--active
.stream-map-event--focused
.stream-focus-ring
```

表示方針:

```text
focus 対象 marker の周囲にリング
軽い glow
短い category label
```

ただし、地図を汚さない。

地図表示の方針:

```text
overview: 日本全体表示
focus: 対象 event 周辺へ寄る
returning: 日本全体表示へ戻る
```

ズーム値は既存 Phase 4-A の設定を尊重し、極端に寄りすぎない。

推奨:

```text
地震: やや広域
豪雨/キキクル: 都道府県〜地方レベル
鉄道: 首都圏/地域レベル、代表点中心
潮位/water: 地点周辺。ただし alert event 未接続なら対象外でよい
```

MVP では event type ごとの厳密な zoom チューニングは必須ではない。
ただし、首都圏などで寄りすぎて地名や context が失われないようにする。

---

## 4. 地図遷移の自然化

Leaflet の pan/zoom 遷移が唐突すぎる場合、軽いアニメーションを使う。

推奨:

```js
map.flyTo(latlng, zoom, {
  animate: true,
  duration: 1.0,
  easeLinearity: 0.25
});
```

ただし、既存 map 初期化設定や非操作設定を壊さない。

以下は維持する。

```text
ズームUIなし
ドラッグ不可
ホイールズーム不可
ダブルクリックズーム不可
キーボード操作不可
```

`prefers-reduced-motion: reduce` の場合は、アニメーション時間を 0 または短くする。

---

## 5. パネル active 表示の改善

focus event に対応する panel item を、現在より分かりやすく強調する。

推奨:

```text
左/右パネル内の該当 item に active class
枠線または淡い背景
小さな「注目」ラベル
```

推奨 class:

```text
.stream-panel-item--active
.stream-panel-item--focused
```

推奨 data 属性:

```text
data-event-id="..."
data-focused="true"
```

注意:

```text
パネル全体を大きく揺らさない
active 以外の項目を読めなくしない
スクロールや overflow を発生させない
```

Phase 4-A で active class が既にある場合は、それを強化するだけでよい。

---

## 6. テロップ「注目」表示の改善

focus 中は、ticker の先頭または目立つ位置に focus event を表示する。

既存 Phase 4-A で `注目` が入っている場合は、それを維持しつつ視認性を上げる。

表示例:

```text
【注目】中央線快速　見合わせ　／　【地震】19:21 岩手県沖 M6.1 最大震度5弱　／　...
```

条件:

```text
focus 中の event id と ticker の 注目 event が一致する
focus がない場合は 注目 を無理に出さない
empty / calm / error 時に古い 注目 が残らない
```

E2E で確認しやすいよう、ticker の注目要素に属性を付ける。

推奨:

```html
<span data-testid="stream-ticker-focus" data-event-id="rail-sync-001">...</span>
```

既存 DOM 構造上 span 化が難しい場合は、ticker container に以下を付けるだけでもよい。

```text
data-focus-event-id="..."
```

---

## 7. overview / focus / returning の視覚状態整理

`body[data-stream-focus-mode]` に応じて CSS を切り替える。

状態:

```text
overview
focus
returning
```

期待表示:

### overview

```text
日本全体表示
HUD は「全国モニタ / 監視中」程度
active marker なし
active panel item なし
```

### focus

```text
地図が対象周辺へ寄る
HUD が注目 event を表示
対象 marker が強調される
該当 panel item が強調される
ticker に注目 event が出る
```

### returning

```text
全国表示へ戻る途中
必要なら HUD に「全国表示へ戻ります」
古い active 表示が残り続けない
```

---

## 8. calm / empty / error 時の挙動

Phase 4-A の安全挙動を維持する。

### calm

```text
focus しない
marker / pulse なし
HUD は「全国モニタ / 監視中」または「現在、表示対象なし」
ticker は監視中表示
```

### empty

```text
focus しない
marker なし
古い active 表示なし
```

### API failure / timeout / invalid JSON

```text
focus しない
demo fallback しない
古い focus が残らない
ticker は「取得を確認中」系
HUD も error / checking を邪魔にならない形で表示してよい
```

Failure を ordinary calm と誤表示しないこと。

---

## 9. accessibility / reduced motion

最低限、以下を考慮する。

```css
@media (prefers-reduced-motion: reduce) {
  ...
}
```

対応例:

```text
pulse animation を弱める
focus ring animation を止める
map transition duration を短くする、または無効化する
```

OBS では直接関係しないが、E2E や将来表示で安定する。

---

## 10. query param

既存 Phase 4-A の検証用 param を維持する。

```text
state=calm
demo=1
focusSpeed=test
chrome=off
demoNow=...
```

新規 param は原則追加しない。
必要な場合も後方互換を壊さないこと。

---

## E2E 追加・更新

以下の E2E を追加または更新する。

```text
e2e/live-stream-focus-view.spec.js
```

既存 `e2e/live-stream-auto-focus.spec.js` に追記でもよいが、Phase 4-B の表示検証は分けた方が望ましい。

テスト観点:

```text
1. focus 中に HUD が表示される
2. HUD の data-focus-event-id が body[data-stream-focus-event-id] と一致する
3. focus event id が active marker と一致する
4. focus event id が active panel item と一致する
5. ticker の 注目 event id が focus event id と一致する
6. overview 時に古い active 表示が残らない
7. returning 後に active 表示が残り続けない
8. calm では focus HUD が警戒表示にならず、marker/pulse なし
9. API failure / timeout / invalid JSON で demo fallback せず、古い focus 表示なし
10. focusSpeed=test で複数 event が巡回し、HUD / marker / panel / ticker が追随する
11. 地図操作不可が維持される
12. Phase 3-D の badge/count/status 同期が壊れていない
13. 通常 `/live` に明確な副作用がない
```

既存の関連テストも通すこと。

推奨実行:

```bash
npx playwright test \
  e2e/live-stream.spec.js \
  e2e/live-stream-main-map.spec.js \
  e2e/live-stream-main-map-real-data.spec.js \
  e2e/live-stream-event-sync.spec.js \
  e2e/live-stream-status-sync.spec.js \
  e2e/live-stream-auto-focus.spec.js \
  e2e/live-stream-focus-view.spec.js \
  e2e/eq-mock-verify.spec.js \
  e2e/rain-mock-verify.spec.js \
  e2e/tide-mock-verify.spec.js \
  e2e/rail-mock-verify.spec.js
```

---

## スクリーンショット確認

以下を保存できるようにする。

```text
test-results/live-stream-phase4b-focus-view-1920.png
test-results/live-stream-phase4b-calm-1920.png
test-results/live-stream-phase4b-demo-focus-1920.png
```

推奨 URL:

```text
http://127.0.0.1:8080/live/stream
http://127.0.0.1:8080/live/stream?state=calm&chrome=off
http://127.0.0.1:8080/live/stream?state=alert&demo=1&focusSpeed=test&chrome=off&demoNow=2026-07-03T13:05:00%2B09:00
```

確認ポイント:

```text
focus 中に「何に注目しているか」一目で分かる
地図が寄りすぎない
HUD がパネル/テロップを邪魔しない
active panel item が見やすい
テロップの注目 event が読みやすい
calm で警戒演出が残らない
```

---

## 完了条件

Phase 4-B の完了条件:

```text
focus 中の HUD / 注目ラベルが表示される
HUD の focus event id が body / map / panel / ticker と一致する
focus marker と panel item が視覚的に分かりやすく強調される
ticker の 注目 event が focus event と同期する
overview / focus / returning の視覚状態が破綻しない
calm / empty / failure で古い focus 表示が残らない
地図操作不可が維持される
Phase 3-D badge/count/status 同期が壊れていない
通常 /live に明確な副作用がない
関連 E2E が PASS
検証レポートを作成できる状態
```

---

## PASS with notes 可の条件

以下は Phase 4-B では notes 扱いでよい。

```text
潮位/water alert event が未接続のため focus 対象外
鉄道 focus が代表点ベースで路線形状ではない
focus zoom の type 別チューニングが簡易
returning 表示が短くスクショで捕捉しづらい
prefers-reduced-motion は CSS 中心の簡易対応
```

---

## 注意

Phase 4-B は「演出追加」だが、配信画面ではやりすぎると逆効果。

最優先は以下。

```text
今どこを見ているか分かる
地図・パネル・テロップが同じ対象を指す
長時間見ても疲れない
データ失敗時に落ちない
通常 /live を壊さない
```

派手さより、監視卓としての読みやすさを優先すること。

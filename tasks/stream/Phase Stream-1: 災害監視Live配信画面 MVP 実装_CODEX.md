# CODEX用検証指示書

## `/live/stream` Phase Stream-1 検証

## 目的

Claude Code が実装した `/live/stream` Phase Stream-1 について、以下を検証する。

* `/live/stream` が正しく表示される
* 1920×1080 配信用レイアウトが崩れていない
* URLパラメータが動作する
* 小窓・中央地図・テロップ・時計が表示される
* console error / page error がない
* 通常 `/live` に影響がない
* Docker / 既存開発環境で再現できる
* 必要に応じてE2Eを追加する

検証結果は Markdown レポートとして保存する。

---

## 前提

参照デザイン:

```text
design_handoff_live_stream/
  README.md
  index.html
```

対象ページ:

```text
/live/stream
```

通常ページ回帰:

```text
/live
/
```

今回の Phase Stream-1 では実データ接続は必須ではない。
ダミーデータ表示でよい。
検証では「設計通りの画面が再現されているか」を重視する。

---

## 検証観点

## 1. 静的確認

以下を確認する。

```text
追加ファイル一覧
変更ファイル一覧
/live 本体への影響範囲
既存 live-main.js などへの過剰な変更がないか
design_handoff/index.html を丸ごと本番投入していないか
```

確認ポイント:

* `/live/stream` 用のファイルが通常 `/live` と分離されていること
* `/live` の既存挙動に不要な副作用が出ない構成であること
* buildScene() または将来の `/live` データ差し替え口が存在すること
* 地図描画処理が将来的に Leaflet / MapLibre / 既存地図へ差し替えやすいこと

---

## 2. 構文チェック

該当するファイルに対して構文確認を行う。

例:

```bash
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-clock.js
node --check frontend/js/live-stream/live-stream-ticker.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-map.js
```

実際のファイル構成に合わせて対象を調整する。

CSS/HTMLについても、明らかな閉じタグ漏れ、読み込みパス誤り、存在しないファイル参照がないか確認する。

---

## 3. Docker / 開発環境起動確認

既存のOnHighGround2検証手順に従い、Docker環境を起動する。

確認例:

```bash
docker compose ps
```

必要に応じて以下を確認する。

```text
frontend 起動
backend 起動
martin 起動
その他既存サービスのヘルス
```

今回 `/live/stream` は基本フロントエンド表示なので、backend改修がない場合でも既存環境が壊れていないことを確認する。

---

## 4. HTTP確認

以下がHTTP 200で返ることを確認する。

```text
/live/stream
/live/stream?state=calm
/live/stream?state=alert
/live/stream?chrome=off
/live
/
```

`/live/stream` が 404 にならないこと。
`/live` と `/` が既存通り表示されること。

---

## 5. Playwright実画面確認

Playwrightで以下のURLを開く。

```text
http://127.0.0.1:8080/live/stream
http://127.0.0.1:8080/live/stream?state=calm
http://127.0.0.1:8080/live/stream?state=alert
http://127.0.0.1:8080/live/stream?state=alert&chrome=off
```

各画面で以下を確認する。

```text
page error がない
console error がない
画面が真っ白でない
1920×1080前提のstageが存在する
ヘッダーが表示される
中央全国モニタが表示される
地震小窓が表示される
キキクル・豪雨小窓が表示される
鉄道小窓が表示される
潮位・水位小窓が表示される
下部速報テロップが表示される
```

---

## 6. 1920×1080レイアウト検証

viewportを 1920×1080 に設定してスクリーンショットを撮る。

対象:

```text
/live/stream?state=calm&chrome=off
/live/stream?state=alert&chrome=off
```

確認項目:

```text
stage が画面内に収まっている
横スクロールが出ない
縦スクロールが出ない
ヘッダー高さが概ね72px
テロップ高さが概ね46px
左カラム・中央・右カラムの配置が崩れていない
小窓4つが上下左右に整列している
小窓同士が重なっていない
中央全国モニタが主役として表示されている
```

スクリーンショット保存例:

```text
test-results/live-stream-calm-1920.png
test-results/live-stream-alert-1920.png
```

---

## 7. 縮小フィット確認

viewportを以下に変えて確認する。

```text
1366×768
1280×720
```

確認項目:

```text
stage が縮小フィットする
画面から大きくはみ出さない
レイアウトが組み替わらない
小窓が極端に重ならない
操作UI前提の表示になっていない
```

スマホ専用レイアウトは今回対象外。
ただし、縮小時にも全体の意味が分かることを確認する。

---

## 8. URLパラメータ検証

### `?state=calm`

確認項目:

```text
平穏時表示になる
中央全国モニタに「現在、表示対象なし」相当が出る
地震小窓が対象なし表示になる
キキクル・豪雨小窓が対象なし表示になる
鉄道小窓が平常運転表示になる
潮位・水位が平常表示になる
警戒レベルが平常系になる
```

### `?state=alert`

確認項目:

```text
警戒時表示になる
地震情報が表示される
キキクル・豪雨情報が表示される
鉄道影響情報が表示される
潮位・水位情報が表示される
中央地図にカテゴリ別パルスが表示される
警戒レベルが警戒系になる
```

### 無指定

確認項目:

```text
デモモードとして表示される
一定時間で平穏→警戒へ遷移する
画面が毎秒フル再描画されて不自然にちらつかない
```

### `?chrome=off`

確認項目:

```text
開発用UIが非表示になる
配信用画面だけが残る
```

---

## 9. 時計検証

確認項目:

```text
ヘッダー中央のHH:MM:SSが表示される
1秒ごとに更新される
中央地図左下のHH:MMが表示される
日付表示が存在する
```

Playwrightで2秒程度待機し、時計文字列が変化することを確認する。

---

## 10. テロップ検証

確認項目:

```text
下部に速報タグが表示される
テロップ本文が表示される
marqueeが動作する
テロップが小窓や中央地図に重ならない
```

本文例:

```text
【地震】
【大雨】
【鉄道】
【潮位】
```

のようなカテゴリ情報が含まれていること。

---

## 11. 色ルール検証

小窓枠線とカテゴリ色が一致しているか確認する。

期待:

```text
地震: 赤〜オレンジ系
キキクル・豪雨: 青〜水色系
鉄道: 緑系
潮位・水位: 紫〜マゼンタ系
```

可能なら computed style を確認する。

期待hex:

```text
地震: #ff4d3d
豪雨: #2f7bff / #34d6ff
鉄道: #2bd576
潮位: #c64be0 / #d24be0
```

中央地図上のパルス色もカテゴリ色と対応していることを確認する。

---

## 12. 地震小窓検証

`?state=alert` で確認する。

確認項目:

```text
地震小窓が表示される
左パネルに過去12時間の履歴が表示される
履歴には時刻・地点・M・震度チップがある
右地図には現在選択中イベントのみが表示される
複数イベントがある場合、8秒程度で対象が切り替わる
対象切替時にズームアップ相当の動きがある
地震ポップアップが表示される
```

`?state=calm` で確認する。

```text
対象なし表示になる
履歴表示の扱いが破綻しない
```

---

## 13. キキクル・豪雨小窓検証

`?state=alert` で確認する。

確認項目:

```text
キキクル・豪雨小窓が表示される
左パネルに警報・注意報リストが表示される
レベルバッジが表示される
右地図に雨域相当の表示がある
複数地点がある場合、8秒程度で対象が切り替わる
対象切替時にズームアップ相当の動きがある
ポップアップが表示される
```

`?state=calm` で確認する。

```text
対象なし表示になる
```

---

## 14. 鉄道小窓検証

`?state=alert` で確認する。

確認項目:

```text
鉄道小窓が表示される
左パネルに影響路線カードが表示される
影響路線カードに路線色バーがある
路線名・状態・区間/理由が表示される
右地図で影響路線が太く表示される
非影響路線が細く控えめに表示される
地図上ポップアップが表示されない
```

`?state=calm` で確認する。

```text
影響路線なし
平常運転
```

---

## 15. 潮位・水位小窓検証

確認項目:

```text
潮位・水位小窓が表示される
2拠点が上下に表示される
現在潮位が表示される
満潮/干潮/偏差が表示される
24時間潮位カーブが表示される
8秒程度で次の2拠点へ巡回する
警戒拠点がある場合はマゼンタ系で強調される
```

---

## 16. アニメーション負荷・ちらつき確認

確認項目:

```text
時計更新で画面全体がちらつかない
8秒巡回時のみ対象表示が切り替わる
ズームアニメーションが約900msで終わる
ポップアップが遅延表示される
連続切替でアニメーションが破綻しない
```

可能なら、DevTools/Playwright上で以下も確認する。

```text
頻繁なDOM全再構築が起きていない
consoleにrequestAnimationFrame関連エラーがない
```

---

## 17. `/live` 回帰確認

通常 `/live` を開いて確認する。

確認項目:

```text
/live が表示される
console error がない
既存の地図表示が壊れていない
既存のレイヤーUIが壊れていない
/live/stream 用CSSが /live に漏れていない
/live/stream 用JSが /live で不要実行されていない
```

CSS漏れは特に確認すること。
`.stage`, `.win`, `.ticker` など汎用名が既存画面へ影響していないか注意する。

---

## 18. `/` 回帰確認

ナビ本体 `/` を開いて確認する。

確認項目:

```text
/ が表示される
console error がない
既存の地図・UIが壊れていない
/live/stream 用CSSが本体に漏れていない
```

---

## 19. E2E追加候補

可能であれば、以下のE2Eを追加する。

ファイル名候補:

```text
e2e/live-stream.spec.js
```

テスト案:

```text
1. /live/stream?state=calm&chrome=off が表示される
2. /live/stream?state=alert&chrome=off が表示される
3. header / center / 4 panels / ticker が存在する
4. state=calm で「表示対象なし」相当が表示される
5. state=alert で地震・豪雨・鉄道・潮位の警戒表示が出る
6. chrome=off で開発UIが非表示になる
7. 1920×1080 screenshot を保存する
8. /live の基本表示が壊れていない
```

セレクタは実装に合わせる。
可能なら、`data-testid` を追加してテストを安定させる。

推奨 data-testid:

```text
live-stream-stage
live-stream-header
live-stream-clock
live-stream-center
live-stream-panel-earthquake
live-stream-panel-rain
live-stream-panel-rail
live-stream-panel-tide
live-stream-ticker
```

---

## 20. レポート作成

検証結果を Markdown で保存する。

保存先候補:

```text
tasks/live/live_stream_phase1_codex_verification.md
```

レポートには以下を含める。

```text
判定: PASS / PASS with notes / FAIL
検証日時
対象ブランチ/コミット
追加・変更ファイル
Docker状態
HTTP確認結果
構文チェック結果
Playwright確認結果
スクリーンショット保存先
console error / page error 有無
/live 回帰結果
/ 回帰結果
E2E追加有無
Notes
修正推奨事項
```

---

## PASS条件

以下を満たせば PASS。

```text
/live/stream が表示できる
?state=calm が動作する
?state=alert が動作する
?chrome=off が動作する
1920×1080でレイアウト崩れがない
小窓4種が表示される
中央全国モニタが表示される
ヘッダー時計が更新される
下部テロップが表示される
console error がない
page error がない
/live が壊れていない
/ が壊れていない
```

---

## PASS with notes条件

以下の場合は PASS with notes とする。

```text
軽微な文字詰まりがある
一部アニメーションがデザイン指定と完全一致しない
縮小viewportで文字がやや読みにくい
実地図差し替えが未実装
実データ接続が未実装
```

ただし、Phase Stream-1では実地図差し替え・実データ接続は必須ではないため、それだけを理由にFAILにしない。

---

## FAIL条件

以下の場合は FAIL。

```text
/live/stream が404
画面が真っ白
重大なconsole errorがある
1920×1080で主要領域が重なる
小窓が表示されない
時計やテロップが表示されない
/live が壊れる
/ が壊れる
chrome=off が効かない
state=calm / state=alert が切り替わらない
```

---

## 最終コメント方針

検証後、結論を明確に書く。

例:

```text
判定: PASS

/live/stream Phase Stream-1 は、1920×1080配信用監視卓レイアウトとして表示できています。
state=calm / state=alert / chrome=off は動作し、console error / page error はありません。
通常 /live および / の回帰も問題ありません。
実地図差し替えと /live 実データ接続は次フェーズ対象です。
```

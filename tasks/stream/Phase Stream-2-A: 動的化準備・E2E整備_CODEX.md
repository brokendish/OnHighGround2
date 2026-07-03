# CODEX用検証指示書

## `/live/stream` Phase Stream-2-A 検証

### 動的化準備・E2E整備

## 目的

Claude Code が実装した `/live/stream` Phase Stream-2-A について、以下を検証する。

* Phase Stream-1 の表示が壊れていない
* `renderTide()` の固定現在時刻 `19.42` が廃止されている
* 潮位カーブの現在位置が時刻から計算されている
* `demoNow` により時刻固定ができる
* `demoNow` なしでは時計が実時刻で更新される
* `data-testid` が追加されている
* dedicated E2E が追加され、安定して実行できる
* `/live` と `/` に影響がない
* console/page error がない

検証結果は Markdown レポートとして保存する。

---

## 対象ページ

```text
/live/stream
/live/stream?state=calm
/live/stream?state=alert
/live/stream?state=alert&chrome=off
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
/live
/
```

---

## 1. 静的確認

### 変更ファイル確認

以下を確認する。

```text
追加・変更ファイル一覧
既存 /live 本体への影響範囲
既存 / 本体への影響範囲
/live/stream 専用CSS/JSの分離状態
```

### 重要確認

```text
renderTide() 内に固定値 cur = 19.42 が残っていない
19.42 相当の固定現在時刻が別名で残っていない
demoNow パラメータ処理が存在する
data-testid が主要DOMへ追加されている
buildScene() の差し替え口が維持されている
```

検索例:

```bash
grep -R "19.42" frontend/js/live-stream frontend/css/live frontend/live || true
grep -R "data-testid" frontend/live frontend/js/live-stream frontend/css/live || true
grep -R "demoNow" frontend/live frontend/js/live-stream || true
```

`19.42` がドキュメントやコメント以外に残っている場合は要確認。

---

## 2. 構文チェック

実装ファイルに対して `node --check` を実行する。

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

---

## 3. Docker / 開発環境確認

Docker環境を起動し、以下を確認する。

```bash
docker compose ps
```

確認対象:

```text
frontend
backend
martin
osrm-walking
```

既存サービスが起動していること。

---

## 4. HTTP確認

以下がHTTP 200で返ることを確認する。

```text
/live/stream
/live/stream?state=calm
/live/stream?state=alert
/live/stream?chrome=off
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
/live
/
```

---

## 5. Playwright専用E2E追加確認

可能であれば、専用E2Eを追加する。

推奨ファイル名:

```text
e2e/live-stream.spec.js
```

### テスト対象URL

Docker frontend の nginx 経由で確認する。

```text
http://127.0.0.1:8080/live/stream
```

既存Playwright設定が直接 `frontend/` を配信する前提で `/live/stream` 解決が難しい場合は、以下のどちらかを選ぶ。

```text
A. Docker frontend 8080 を前提にした dedicated test にする
B. 既存E2E設定に影響しない形で live-stream 用 baseURL を追加する
```

既存E2E全体を壊すような大きな設定変更は避ける。

---

## 6. E2Eで確認する data-testid

以下が取得できること。

```text
live-stream-stage
live-stream-header
live-stream-clock
live-stream-date
live-stream-status-bar
live-stream-center
live-stream-center-map
live-stream-center-time
live-stream-alert-level
live-stream-panel-earthquake
live-stream-panel-rain
live-stream-panel-rail
live-stream-panel-tide
live-stream-ticker
live-stream-ticker-body
```

可能なら以下も確認する。

```text
live-stream-dev-chrome
live-stream-tide-current-marker
live-stream-pulse-earthquake
live-stream-pulse-rain
live-stream-pulse-rail
live-stream-pulse-tide
```

---

## 7. `demoNow` 検証

### URL

```text
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

### 確認項目

```text
ヘッダー時計が 19:42:00 相当になる
中央地図内時刻が 19:42 相当になる
2秒待っても時計が進まない
潮位現在位置が 19時台の位置になる
console/page error がない
```

### 追加確認

時刻を変えて表示する。

```text
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T06:00:00%2B09:00
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T18:00:00%2B09:00
```

確認:

```text
06:00 と 18:00 で潮位現在マーカーの位置が変わる
```

`live-stream-tide-current-marker` の SVG属性、bounding box、transform など、実装に合わせて比較する。

---

## 8. 実時刻時計更新検証

### URL

```text
/live/stream?state=alert&chrome=off
```

### 確認項目

```text
ヘッダー時計が現在時刻を表示する
2秒待つと HH:MM:SS が変わる
中央地図内時刻も現在時刻系の表示になる
console/page error がない
```

`demoNow` 指定時は固定、未指定時は更新、という違いを明確に確認する。

---

## 9. `state=calm` 回帰確認

### URL

```text
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

```text
中央全国モニタに「現在、表示対象なし」相当が表示される
地震小窓が対象なし表示
キキクル・豪雨小窓が対象なし表示
鉄道小窓が平常運転表示
潮位・水位が平常表示
小窓4種が消えない
テロップが表示される
```

---

## 10. `state=alert` 回帰確認

### URL

```text
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

```text
地震情報が表示される
キキクル・豪雨情報が表示される
鉄道情報が表示される
潮位・水位情報が表示される
中央地図にカテゴリ別パルスが表示される
下部テロップが表示される
小窓枠線色がカテゴリ色と一致する
```

---

## 11. `chrome=off` 検証

確認項目:

```text
開発用UIが非表示
配信用画面だけが表示
ヘッダー、小窓、中央地図、テロップは表示
レイアウト崩れなし
```

`live-stream-dev-chrome` が存在する場合:

```text
display: none
visibility: hidden
またはDOM上存在しない
```

のいずれかを確認する。

---

## 12. 1920×1080スクリーンショット

以下を撮影する。

```text
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

保存先例:

```text
test-results/live-stream-phase2a-calm-1920.png
test-results/live-stream-phase2a-alert-1920.png
```

確認項目:

```text
stageが1920×1080で収まる
横スクロールなし
縦スクロールなし
ヘッダーが崩れない
中央地図が主役として表示される
小窓4種が整列する
テロップが下部に表示される
```

---

## 13. 縮小フィット確認

以下で確認する。

```text
1366×768
1280×720
```

対象:

```text
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

```text
stage が viewport 内に縮小フィット
横スクロールなし
縦スクロールなし
小窓の大きな重なりなし
```

---

## 14. `/live` 回帰確認

通常 `/live` を開く。

確認項目:

```text
HTTP 200
console/page error なし
通常の /live 地図が表示される
既存UIが壊れていない
/live/stream 用CSSが漏れていない
/live/stream 用JSが /live で実行されていない
```

特に以下のような汎用クラス漏れに注意する。

```text
.stage
.win
.row
.legend
.ticker
```

---

## 15. `/` 回帰確認

ナビ本体 `/` を開く。

確認項目:

```text
HTTP 200
console/page error なし
地図・UIが表示される
/live/stream 用CSSが漏れていない
```

---

## 16. E2Eテスト案

可能であれば `e2e/live-stream.spec.js` に以下を追加する。

### Test 1: calm 表示

```text
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

期待:

```text
stage/header/center/4 panels/ticker が存在
「現在、表示対象なし」相当が表示
```

### Test 2: alert 表示

```text
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

期待:

```text
地震・豪雨・鉄道・潮位の警戒表示が存在
カテゴリ別パルスが存在
```

### Test 3: demoNow 固定

```text
/live/stream?state=alert&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

期待:

```text
時計が19:42:00相当
2秒待っても変わらない
```

### Test 4: 実時刻更新

```text
/live/stream?state=alert&chrome=off
```

期待:

```text
2秒待つと時計が変わる
```

### Test 5: tide current marker

```text
demoNow=06:00
demoNow=18:00
```

期待:

```text
潮位現在マーカー位置が変わる
```

### Test 6: chrome off

期待:

```text
開発UIが非表示
```

### Test 7: `/live` 回帰

期待:

```text
/live が表示され console/page error なし
```

### Test 8: `/` 回帰

期待:

```text
/ が表示され console/page error なし
```

---

## 17. レポート作成

検証結果を Markdown で保存する。

保存先候補:

```text
tasks/live/live_stream_phase2a_codex_verification.md
```

レポートには以下を含める。

```text
判定: PASS / PASS with notes / FAIL
検証日時
対象ブランチ/コミット
追加・変更ファイル
構文チェック結果
Docker状態
HTTP確認結果
Playwright確認結果
E2E追加結果
スクリーンショット保存先
demoNow検証結果
renderTide固定時刻廃止確認
data-testid確認結果
/live 回帰結果
/ 回帰結果
Notes
修正推奨事項
```

---

## PASS条件

以下を満たせば PASS。

```text
/live/stream が表示できる
state=calm が動作する
state=alert が動作する
chrome=off が動作する
demoNow で時刻固定できる
demoNow なしで時計が更新される
renderTide() の固定値 19.42 が廃止されている
潮位現在マーカーが時刻に応じて変わる
主要 data-testid が存在する
dedicated E2E が追加され、対象テストがPASSする
1920×1080でレイアウト崩れなし
console/page error なし
/live が壊れていない
/ が壊れていない
```

---

## PASS with notes条件

以下は PASS with notes とする。

```text
軽微な文字詰まりがある
縮小viewportで一部文字が読みにくい
E2Eは追加済みだが既存環境都合でDocker 8080前提
潮位マーカーの比較が属性値比較ではなくスクリーンショット確認
Google Fonts外部参照が残っている
```

Google Fonts外部参照は今回のFAIL条件にしない。

---

## FAIL条件

以下の場合は FAIL。

```text
/live/stream が404
画面が真っ白
重大なconsole/page error
state=calm / state=alert が壊れている
chrome=off が効かない
demoNow が効かない
demoNowなしで時計が更新されない
renderTide() に固定時刻 19.42 が残っている
潮位現在マーカーが時刻で変わらない
主要小窓が表示されない
1920×1080で大きく崩れる
/live が壊れる
/ が壊れる
```

---

## 最終コメント例

```text
判定: PASS

/live/stream Phase Stream-2-A は、Phase Stream-1 の表示を維持したまま、demoNow による時刻固定、実時刻時計更新、renderTide() の固定時刻廃止、主要 data-testid 追加、dedicated E2E を確認できました。
通常 /live および / の回帰も問題ありません。
次フェーズでは buildScene() を /live 正規化済みデータへ接続する Phase Stream-2-B に進めます。
```

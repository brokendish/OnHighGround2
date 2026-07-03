# CODEX用検証指示書

## `/live/stream` Stream Phase 2-C: 下部テロップ統合・実データ化 検証

## 目的

Claude Code が実装した `/live/stream` の下部テロップ統合を検証する。

確認すること:

```text
既存E2Eが壊れていない
下部テロップが4カテゴリの scene / ViewModel から動的生成される
demo=1 で地震・大雨・鉄道・潮位がすべてテロップに出る
state=calm で監視中テロップになる
通常表示で実データ由来のテロップが生成される
取得失敗時に「なし」と断定しない
undefined / null / NaN が出ない
通常 /live と / に影響がない
console/page error がない
```

検証結果を Markdown レポートとして保存する。

---

## レポート保存先

```text
tasks/live/live_stream_phase2c_ticker_codex_verification.md
```

---

## 1. 静的確認

変更ファイルを確認する。

```bash
git status --short
git diff --stat
```

確認観点:

```text
/live/stream 専用ファイル中心の変更である
通常 /live への影響が最小限である
通常 / への影響がない
ticker生成関数がある
地震・大雨・鉄道・潮位のViewModelを利用している
毎秒ticker全体を再生成するような構造になっていない
```

---

## 2. スコープ逸脱確認

以下を確認する。

```text
音声読み上げまで広げていない
YouTube API連携まで広げていない
DB追加していない
テロップ編集UIを作っていない
/live 本体を大規模改修していない
```

今回の対象は `/live/stream` 下部テロップ統合のみ。

---

## 3. 構文チェック

対象JSに `node --check` を実行する。

例:

```bash
node --check frontend/js/live-stream/live-stream-main.js
node --check frontend/js/live-stream/live-stream-scene.js
node --check frontend/js/live-stream/live-stream-clock.js
node --check frontend/js/live-stream/live-stream-ticker.js
node --check frontend/js/live-stream/live-stream-panels.js
node --check frontend/js/live-stream/live-stream-map.js
node --check e2e/live-stream.spec.js
node --check e2e/eq-mock-verify.spec.js
node --check e2e/rain-mock-verify.spec.js
node --check e2e/tide-mock-verify.spec.js
node --check e2e/rail-mock-verify.spec.js
```

ticker用E2Eが追加された場合は、それも対象にする。

```bash
node --check e2e/ticker-mock-verify.spec.js
```

---

## 4. Docker状態確認

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

既存の起動状態を壊していないこと。

---

## 5. HTTP確認

以下が 200 で返ること。

```text
/live/stream
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?chrome=off
/live
/
```

---

## 6. 既存E2E実行

既存E2Eを実行する。

```bash
npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/eq-mock-verify.spec.js
npx playwright test e2e/rain-mock-verify.spec.js
npx playwright test e2e/tide-mock-verify.spec.js
npx playwright test e2e/rail-mock-verify.spec.js
```

期待:

```text
全テスト PASS
```

地震・豪雨・潮位・鉄道の既存接続が壊れていないこと。

---

## 7. ticker用E2E追加

可能であれば、ticker用E2Eを追加する。

候補:

```text
e2e/ticker-mock-verify.spec.js
```

対象URL:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

```text
live-stream-ticker が表示される
live-stream-ticker-body が表示される
テロップ本文に 【地震】 が含まれる
テロップ本文に 【大雨】 が含まれる
テロップ本文に 【鉄道】 が含まれる
テロップ本文に 【潮位】 が含まれる
区切り文字 ／ が含まれる
undefined / null / NaN が含まれない
console/page error がない
```

---

## 8. state=calm テロップ確認

対象URL:

```text
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

期待:

```text
live-stream-ticker-body が表示される
「監視中」または同等の文言が表示される
地震・大雨・鉄道の警戒デモ文言が出ない
undefined / null / NaN が出ない
```

例:

```text
【監視中】現在、表示対象となる警戒情報はありません
```

---

## 9. demo=1 テロップ確認

対象URL:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

期待例:

```text
【地震】19:21 岩手県沖 M6.1 最大震度5弱 ／ 【大雨】静岡県中部 土砂災害キキクル「危険」 ／ 【鉄道】中央線快速 三鷹〜東京で運転見合わせ ／ 【潮位】東京 現在155cm / 満潮 05:38 184cm
```

完全一致でなくてよい。
ただし4カテゴリが含まれること。

---

## 10. 通常表示テロップ確認

対象URL:

```text
/live/stream?chrome=off
```

確認項目:

```text
実データ由来のticker本文が生成される
表示対象がなければ監視中文言になる
潮位代表地点を出す仕様なら潮位テロップが表示される
取得失敗カテゴリがある場合、なしと断定しない
undefined / null / NaN が出ない
```

検証時点で実データが少なくても FAIL にしない。

---

## 11. 取得失敗時確認

可能であれば、各カテゴリのAPI失敗をmockして確認する。

最低限、ticker生成関数が取得失敗カテゴリを安全に扱うことを確認する。

期待:

```text
取得失敗カテゴリを「なし」と断定しない
画面全体が壊れない
ticker本文に undefined / null / NaN が出ない
console/page error がない
```

取得失敗mockが困難な場合は Notes に書く。

---

## 12. ticker更新・marquee確認

確認項目:

```text
テロップ本文が表示される
横スクロールが動作する
時計更新だけでtickerが不自然にリセットされない
demoNow指定時はticker本文が安定する
```

可能なら2〜3秒待機して、ticker DOM が不要に再生成されていないことを確認する。
厳密なパフォーマンス検証は不要。

---

## 13. 表示欠損確認

以下がテロップ本文に含まれないこと。

```text
undefined
null
NaN
Invalid Date
[object Object]
```

---

## 14. スクリーンショット

以下を保存する。

```text
test-results/live-stream-phase2c-ticker-demo-1920.png
test-results/live-stream-phase2c-ticker-calm-1920.png
test-results/live-stream-phase2c-ticker-live-1920.png
```

対象例:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?chrome=off
```

---

## 15. `/live` 回帰確認

通常 `/live` を開く。

確認項目:

```text
HTTP 200
console/page error なし
地図表示が壊れていない
地震表示が壊れていない
キキクル・豪雨表示が壊れていない
潮位表示が壊れていない
鉄道表示が壊れていない
既存レイヤーUIが壊れていない
```

---

## 16. `/` 回帰確認

ナビ本体 `/` を開く。

確認項目:

```text
HTTP 200
console/page error なし
基本地図表示が壊れていない
/live/stream CSS/JS が漏れていない
```

---

## 17. レポート作成

保存先:

```text
tasks/live/live_stream_phase2c_ticker_codex_verification.md
```

レポートに含める内容:

```text
判定: PASS / PASS with notes / FAIL
検証日時
対象ブランチ/コミット
変更ファイル
構文チェック結果
Docker状態
HTTP確認結果
E2E結果
demo=1 テロップ確認
state=calm テロップ確認
通常表示テロップ確認
取得失敗時の扱い
marquee確認
表示欠損確認
スクリーンショット保存先
/live 回帰
/ 回帰
Notes
修正推奨事項
```

---

## PASS条件

以下を満たせば PASS。

```text
/live/stream が表示できる
既存E2EがPASS
ticker用E2EがPASS
demo=1 で地震・大雨・鉄道・潮位がテロップに出る
state=calm で監視中文言になる
通常表示で実データ由来または監視中文言になる
undefined / null / NaN が出ない
取得失敗時に「なし」と断定しない
console/page error なし
/live が壊れていない
/ が壊れていない
```

---

## PASS with notes条件

以下は PASS with notes とする。

```text
通常表示時に実データ対象が少なく監視中表示になった
取得失敗mockまでは未実施
優先順位が簡易実装
ticker itemが各カテゴリ最大1件
marqueeリセットの厳密検証は未実施
```

Phase 2-C では上記のみを理由に FAIL にしない。

---

## FAIL条件

以下の場合は FAIL。

```text
/live/stream が404
画面が真っ白
重大なconsole/page error
既存E2Eが壊れる
tickerが表示されない
demo=1 で4カテゴリが出ない
state=calm で警戒デモ文言が出る
undefined / null / NaN がテロップに出る
取得失敗時に「なし」と断定する
/live が壊れる
/ が壊れる
```

---

## 最終コメント例

```text
判定: PASS

/live/stream Phase 2-C 下部テロップ統合は、地震・大雨・鉄道・潮位の各ViewModelからテロップ本文を生成し、demo=1 では4カテゴリ、state=calm では監視中文言を表示できることを確認しました。
既存E2E、通常 /live、/ への回帰影響はありません。
次フェーズではOBS配信用の運用安定化、または自動注目/巡回ロジック改善へ進めます。
```

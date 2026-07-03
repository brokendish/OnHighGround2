# CODEX用検証指示書

## `/live/stream` Stream Phase 2-B.2: キキクル・豪雨情報 実データ接続 MVP 検証

## 目的

Claude Code が実装した `/live/stream` のキキクル・豪雨情報実データ接続を検証する。

確認すること:

```text
Phase 2-A / 2-B.1 の既存E2Eが壊れていない
キキクル・豪雨小窓が実データ接続に対応している
キキクル・豪雨デモ表示がE2Eで安定している
対象0件時と取得失敗時を区別できる
中央地図の豪雨パルスがデータ由来になる
ヘッダー豪雨件数がデータ由来になる
通常 /live と / に影響がない
console/page error がない
```

検証結果を Markdown レポートとして保存する。

---

## レポート保存先

```text
tasks/live/live_stream_phase2b2_rain_codex_verification.md
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
既存 dedicated E2E が残っている
地震実データ接続が壊れていない
rain/kikikuru adapter 相当の処理がある
demo / mock モードがキキクル・豪雨にも対応している
```

---

## 2. スコープ逸脱確認

以下を確認する。

```text
backend APIを不用意に追加していない
DBを追加していない
/live 本体を大規模リファクタしていない
キキクルタイル完全描画まで広げていない
洪水/浸水/土砂の分割UIまで広げていない
鉄道・潮位の実データ接続まで広げていない
```

今回の対象はキキクル・豪雨のみ。

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
```

追加E2Eがある場合はそれも対象にする。

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

Phase 2-A / 2-B.1 の既存E2Eを実行する。

```bash
npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/eq-mock-verify.spec.js
```

期待:

```text
全テスト PASS
```

既存の地震接続が今回の雨接続で壊れていないこと。

---

## 7. キキクル・豪雨デモ表示E2E追加

可能であれば `e2e/live-stream.spec.js` にキキクル・豪雨デモ用テストを追加する。

対象URL:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

```text
live-stream-panel-rain が表示される
live-stream-rain-active が表示される
live-stream-rain-list が表示される
live-stream-rain-list-item が1件以上ある
live-stream-rain-popup が表示される
live-stream-pulse-rain が表示される
ヘッダー豪雨件数が1以上になる
console/page error がない
```

実装上 testid が異なる場合は、実装に合わせる。
ただし、安定したセレクタで検証すること。

---

## 8. 実データ接続確認

通常モードで `/live/stream` を開く。

```text
/live/stream?chrome=off
```

確認項目:

```text
キキクル・豪雨データ取得処理が実行される
既存 /live のデータ取得口を利用している
API失敗時に画面が壊れない
対象0件時に「表示対象なし」相当になる
対象あり時はキキクル・豪雨小窓に反映される
対象あり時は中央地図に豪雨パルスが出る
```

検証時点で対象データがない場合は、0件正常表示として扱う。
対象あり前提でFAILにしない。

---

## 9. `/live` データ取得口確認

ブラウザNetworkまたはコード静的確認で、`/live/stream` が既存 `/live` のキキクル・豪雨系データ取得口を利用しているか確認する。

確認内容:

```text
新規にJMA等へ直接アクセスしていない
既存backend/APIまたは正規化済みデータを使っている
既存 /live とデータ解釈が大きくズレていない
```

完全に同一JS共有でなくても、既存API/正規化済みデータを利用していれば可。

---

## 10. 対象0件表示確認

対象0件になる状況を作れる場合は確認する。

方法例:

```text
Playwright route でキキクル・豪雨APIを空配列にmock
または demo/mock パラメータで empty を指定できるなら使用
```

期待:

```text
キキクル・豪雨小窓: 現在、表示対象なし
中央地図: 豪雨パルスなし
ヘッダー: 豪雨 0
console/page error なし
```

禁止:

```text
取得失敗扱いになる
undefined / null / NaN が表示される
```

---

## 11. 取得失敗表示確認

API失敗をmockできる場合は確認する。

方法例:

```text
Playwright route でキキクル・豪雨APIを500にする
不正JSONを返す
timeout相当
```

期待:

```text
キキクル・豪雨小窓: 取得できません / 一時的に取得不可
中央地図: 豪雨パルスなし、または前回表示なし
ヘッダー: 豪雨 - / 取得不可
console error なし
page error なし
```

禁止:

```text
キキクル・豪雨情報なしと断定
画面全体が真っ白
Unhandled promise rejection
```

取得失敗テストが実装困難な場合は Notes に書く。

---

## 12. activeTarget 優先順位確認

可能であれば mock で確認する。

確認観点:

```text
危険度が高い地域が優先される
同じ危険度なら雨雲/雨量強度が高い地域が優先される
それも同じなら更新時刻が新しい地域が優先される
```

完全実装がまだの場合は、現状の選択ルールをレポートに明記する。

---

## 13. 8秒巡回確認

複数対象があるデモまたはmockで確認する。

期待:

```text
8秒程度でキキクル・豪雨小窓の対象が切り替わる
中央地図の豪雨パルス位置も切り替わる
時計更新で巡回がリセットされない
```

---

## 14. 中央地図パルス確認

確認項目:

```text
対象ありで live-stream-pulse-rain が表示される
対象0件で豪雨パルスが表示されない
豪雨パルス色が #2f7bff / #34d6ff 系である
```

位置確認:

```text
静岡データなら東海付近
関東データなら関東付近
九州データなら九州付近
```

簡略SVG地図なので厳密な座標一致は求めない。

---

## 15. キキクル・豪雨小窓表示確認

表示項目:

```text
地域名
カテゴリ
危険度/警戒度
更新時刻
ポップアップ
```

欠損値確認:

```text
undefined が出ない
null が出ない
NaN が出ない
空欄が不自然に残らない
```

---

## 16. ヘッダー豪雨件数確認

確認項目:

```text
対象あり → 豪雨件数が1以上
対象0件 → 豪雨 0
取得失敗 → 豪雨 - または取得不可
```

実装仕様に合わせて確認する。

---

## 17. スクリーンショット

以下を保存する。

```text
test-results/live-stream-phase2b2-rain-demo-1920.png
test-results/live-stream-phase2b2-rain-calm-1920.png
```

対象例:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

可能なら実データ表示スクリーンショットも保存する。

```text
test-results/live-stream-phase2b2-rain-live-1920.png
```

---

## 18. `/live` 回帰確認

通常 `/live` を開く。

確認項目:

```text
HTTP 200
console/page error なし
地図表示が壊れていない
雨雲/キキクル系表示が壊れていない
地震表示が壊れていない
既存レイヤーUIが壊れていない
```

可能なら関連E2Eを実行する。

---

## 19. `/` 回帰確認

ナビ本体 `/` を開く。

確認項目:

```text
HTTP 200
console/page error なし
基本地図表示が壊れていない
/live/stream CSS/JS が漏れていない
```

---

## 20. レポート作成

保存先:

```text
tasks/live/live_stream_phase2b2_rain_codex_verification.md
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
実データ接続確認結果
demo/mock確認結果
対象0件表示確認
取得失敗表示確認
activeTarget選択ルール確認
8秒巡回確認
中央地図パルス確認
ヘッダー豪雨件数確認
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
既存 dedicated E2E がPASS
地震E2EがPASS
キキクル・豪雨デモ表示E2EがPASS
既存 /live のキキクル・豪雨系データ取得口を利用している
対象あり時にキキクル・豪雨小窓へ反映される
対象あり時に中央地図パルスへ反映される
豪雨件数がヘッダーへ反映される
対象0件時に正常な対象なし表示になる
取得失敗時に「なし」と断定しない
console/page error なし
/live が壊れていない
/ が壊れていない
```

---

## PASS with notes条件

以下は PASS with notes とする。

```text
検証時点で実データの対象が0件だった
取得失敗mockまでは未実施
activeTarget優先順位が簡易実装
中央地図の位置が簡略SVG上の概算
雨域表現が簡略SVG/ぼかし円
テロップ動的化が最小対応または未対応
```

Phase 2-B.2 では上記のみを理由にFAILにしない。

---

## FAIL条件

以下の場合は FAIL。

```text
/live/stream が404
画面が真っ白
重大なconsole/page error
既存 dedicated E2E が壊れる
地震表示が壊れる
キキクル・豪雨小窓が表示されない
対象0件と取得失敗を混同する
取得失敗時に「豪雨なし」と断定する
undefined / null / NaN が画面に出る
/live が壊れる
/ が壊れる
```

---

## 最終コメント例

```text
判定: PASS

/live/stream Phase 2-B.2 キキクル・豪雨情報実データ接続は、既存 /live のキキクル・豪雨系データ取得口を利用し、キキクル・豪雨小窓・中央地図パルス・ヘッダー豪雨件数へ反映できることを確認しました。
demo=1 による安定E2Eも追加済みで、地震表示、通常 /live、/ への回帰影響はありません。
次フェーズでは鉄道情報または潮位・水位情報の実データ接続へ進めます。
```

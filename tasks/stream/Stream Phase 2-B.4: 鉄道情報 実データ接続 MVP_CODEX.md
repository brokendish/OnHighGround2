# CODEX用検証指示書

## `/live/stream` Stream Phase 2-B.4: 鉄道情報 実データ接続 MVP 検証

## 目的

Claude Code が実装した `/live/stream` の鉄道情報実データ接続を検証する。

確認すること:

```text
Phase 2-A / 2-B.1 / 2-B.2 / 2-B.3 の既存E2Eが壊れていない
鉄道情報小窓が実データ接続に対応している
ODPTで取得できる範囲の交通影響を表示している
鉄道デモ表示がE2Eで安定している
影響あり/影響なし/取得失敗を区別できる
ヘッダー鉄道件数が影響路線数として反映される
地図上ポップアップが表示されない
通常 /live と / に影響がない
console/page error がない
```

検証結果を Markdown レポートとして保存する。

---

## レポート保存先

```text
tasks/live/live_stream_phase2b4_railway_codex_verification.md
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
地震・豪雨・潮位接続が壊れていない
railway adapter 相当の処理がある
demo / mock モードが鉄道にも対応している
```

---

## 2. スコープ逸脱確認

以下を確認する。

```text
全国鉄道網の完全対応まで広げていない
ODPT非対応路線を推定表示していない
JR全路線対応のような未確認範囲へ広げていない
駅名表示を大量に追加していない
地図上ポップアップを追加していない
鉄道履歴保存やDB追加をしていない
テロップ全面動的化まで広げていない
JARTIC連携まで広げていない
```

今回の対象はODPTで取得できる範囲の鉄道運行影響表示のみ。

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
```

鉄道用E2Eが追加された場合は、それも対象にする。

```bash
node --check e2e/rail-mock-verify.spec.js
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
```

期待:

```text
全テスト PASS
```

地震・豪雨・潮位の既存接続が今回の鉄道接続で壊れていないこと。

---

## 7. 鉄道デモ表示E2E追加

可能であれば、鉄道用E2Eを追加する。

候補:

```text
e2e/rail-mock-verify.spec.js
```

対象URL:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

```text
live-stream-panel-rail が表示される
live-stream-rail-active が表示される
live-stream-rail-list が表示される
live-stream-rail-list-item が1件以上ある
live-stream-rail-line-name が表示される
live-stream-rail-status が表示される
live-stream-rail-map が表示される
live-stream-rail-route が表示される
ヘッダー鉄道件数が1以上になる
地図上ポップアップが0件である
console/page error がない
```

---

## 8. 実データ接続確認

通常モードで `/live/stream` を開く。

```text
/live/stream?chrome=off
```

確認項目:

```text
鉄道データ取得処理が実行される
既存 /live の鉄道データ取得口を利用している
ODPT由来の運行影響データを使っている
API失敗時に画面が壊れない
影響あり時は鉄道小窓に反映される
影響なし時は「影響路線なし / 平常運転」になる
ヘッダー鉄道件数が影響路線数になる
```

検証時点で影響路線がない場合は、影響0件正常表示として扱う。
影響あり前提でFAILにしない。

---

## 9. `/live` 鉄道データ取得口確認

ブラウザNetworkまたはコード静的確認で、`/live/stream` が既存 `/live` の鉄道データ取得口を利用しているか確認する。

確認内容:

```text
既存backend/APIまたは正規化済みデータを使っている
/live/stream からODPTへ直接アクセスしていない
既存 /live とデータ解釈が大きくズレていない
```

---

## 10. 影響あり表示確認

デモまたはmockで影響あり状態を確認する。

期待:

```text
鉄道小窓に影響路線カードが表示される
路線名が表示される
状態が表示される
区間/理由が表示される
更新時刻が表示される
路線色バーが表示される
右側簡略路線図に影響路線が太く表示される
```

欠損表示確認:

```text
undefined
null
NaN
Invalid Date
[object Object]
```

が出ていないこと。

---

## 11. 影響なし表示確認

影響0件になる状況を作れる場合は確認する。

方法例:

```text
Playwright route で鉄道APIを影響0件にmock
または demo/mock パラメータで empty を指定できるなら使用
```

期待:

```text
鉄道小窓: 影響路線なし / 平常運転
ヘッダー: 鉄道 0
右側簡略路線図が控えめ表示
console/page error なし
```

禁止:

```text
取得失敗扱いになる
undefined / null / NaN が表示される
```

---

## 12. 取得失敗表示確認

API失敗をmockできる場合は確認する。

方法例:

```text
Playwright route で鉄道APIを500にする
不正JSONを返す
timeout相当
```

期待:

```text
鉄道小窓: 取得できません / 一時的に取得不可
ヘッダー: 鉄道 - または取得不可
console error なし
page error なし
```

禁止:

```text
平常運転と断定
影響路線なしと断定
画面全体が真っ白
Unhandled promise rejection
```

取得失敗テストが実装困難な場合は Notes に書く。

---

## 13. 地図上ポップアップ非表示確認

配信用鉄道小窓では、地図上ポップアップを表示しないこと。

確認:

```text
鉄道小窓内に地図ポップアップがない
地図上に路線名ラベルが大量表示されない
駅名が大量表示されない
```

左側カードに情報が集約されていること。

---

## 14. ヘッダー鉄道件数確認

確認項目:

```text
影響あり → 鉄道件数が1以上
影響なし → 鉄道 0
取得失敗 → 鉄道 - または取得不可
```

件数はODPT対応範囲内の影響路線数でよい。

---

## 15. 中央地図パルス確認

Phase 2-B.4 では鉄道パルスは必須ではない。

確認観点:

```text
鉄道情報によって中央地図が過剰にうるさくなっていない
地震・豪雨・潮位の既存パルスが壊れていない
```

もし `live-stream-pulse-rail` を実装している場合は、仕様をNotesに記載する。

---

## 16. スクリーンショット

以下を保存する。

```text
test-results/live-stream-phase2b4-rail-demo-1920.png
test-results/live-stream-phase2b4-rail-calm-1920.png
test-results/live-stream-phase2b4-rail-live-1920.png
```

対象例:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?chrome=off
```

---

## 17. `/live` 回帰確認

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

可能なら鉄道関連E2Eまたは代表的な `/live` E2Eを実行する。

---

## 18. `/` 回帰確認

ナビ本体 `/` を開く。

確認項目:

```text
HTTP 200
console/page error なし
基本地図表示が壊れていない
/live/stream CSS/JS が漏れていない
```

---

## 19. レポート作成

保存先:

```text
tasks/live/live_stream_phase2b4_railway_codex_verification.md
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
影響あり表示確認
影響なし表示確認
取得失敗表示確認
地図上ポップアップ非表示確認
ヘッダー鉄道件数確認
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
豪雨E2EがPASS
潮位E2EがPASS
鉄道デモ表示E2EがPASS
既存 /live の鉄道データ取得口を利用している
影響あり時に鉄道小窓へ反映される
影響なし時に平常表示になる
ヘッダー鉄道件数が仕様通り表示される
地図上ポップアップが表示されない
取得失敗時に平常と断定しない
console/page error なし
/live が壊れていない
/ が壊れていない
```

---

## PASS with notes条件

以下は PASS with notes とする。

```text
検証時点で実データの影響路線が0件だった
取得失敗mockまでは未実施
ODPT対応範囲が限定的
路線ジオメトリが簡略表示
鉄道パルス未実装
テロップ動的化が最小対応または未対応
```

Phase 2-B.4 では上記のみを理由に FAIL にしない。

---

## FAIL条件

以下の場合は FAIL。

```text
/live/stream が404
画面が真っ白
重大なconsole/page error
既存 dedicated E2E が壊れる
地震表示が壊れる
豪雨表示が壊れる
潮位表示が壊れる
鉄道小窓が表示されない
影響0件と取得失敗を混同する
取得失敗時に平常運転と断定する
地図上ポップアップが出る
undefined / null / NaN が画面に出る
/live が壊れる
/ が壊れる
```

---

## 最終コメント例

```text
判定: PASS

/live/stream Phase 2-B.4 鉄道情報実データ接続は、既存 /live のODPT由来鉄道データ取得口を利用し、ODPTで取得できる範囲の運行影響を鉄道小窓・ヘッダー件数へ反映できることを確認しました。
地図上ポップアップは表示されず、配信用に簡潔なカード表示へ集約されています。
地震・豪雨・潮位E2E、通常 /live、/ への回帰影響はありません。
次フェーズでは下部テロップの実データ統合へ進めます。
```

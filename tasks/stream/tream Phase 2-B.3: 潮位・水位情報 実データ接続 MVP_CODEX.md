# CODEX用検証指示書

## `/live/stream` Stream Phase 2-B.3: 潮位・水位情報 実データ接続 MVP 検証

## 目的

Claude Code が実装した `/live/stream` の潮位・水位情報実データ接続を検証する。

確認すること:

```text
Phase 2-A / 2-B.1 / 2-B.2 の既存E2Eが壊れていない
潮位・水位小窓が実潮位データ接続に対応している
潮位デモ表示がE2Eで安定している
2地点表示が維持されている
複数地点巡回が動作する
潮位カーブが実データ由来になる
現在時刻マーカーが demoNow / 実時刻に連動する
ヘッダー潮位件数が警戒対象数として反映される
取得成功0件と取得失敗を区別できる
通常 /live と / に影響がない
console/page error がない
```

検証結果を Markdown レポートとして保存する。

---

## レポート保存先

```text
tasks/live/live_stream_phase2b3_tide_codex_verification.md
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
キキクル・豪雨実データ接続が壊れていない
tide adapter 相当の処理がある
demo / mock モードが潮位にも対応している
```

---

## 2. スコープ逸脱確認

以下を確認する。

```text
DBを追加していない
潮位データ生成処理を作り直していない
/live 本体を大規模リファクタしていない
河川水位の新規取得まで広げていない
鉄道実データ接続まで広げていない
JARTIC交通量表示まで広げていない
```

今回の対象は右下パネルの潮位実データ接続を中心とする。

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
```

潮位用E2Eが追加された場合は、それも対象にする。

```bash
node --check e2e/tide-mock-verify.spec.js
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

Phase 2-A / 2-B.1 / 2-B.2 の既存E2Eを実行する。

```bash
npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/eq-mock-verify.spec.js
npx playwright test e2e/rain-mock-verify.spec.js
```

期待:

```text
全テスト PASS
```

既存の地震・豪雨接続が今回の潮位接続で壊れていないこと。

---

## 7. 潮位デモ表示E2E追加

可能であれば、潮位用E2Eを追加する。

候補:

```text
e2e/tide-mock-verify.spec.js
```

対象URL:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

```text
live-stream-panel-tide が表示される
live-stream-tide-station が2件表示される
live-stream-tide-station-name が表示される
live-stream-tide-current が表示される
live-stream-tide-high が表示される
live-stream-tide-low が表示される
live-stream-tide-curve が表示される
live-stream-tide-current-marker が表示される
ヘッダー潮位件数が仕様通りになる
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
潮位データ取得処理が実行される
既存 /live の潮位データ取得口を利用している
API失敗時に画面が壊れない
潮位データあり時は潮位・水位小窓に反映される
2地点表示される
現在潮位が表示される
満潮/干潮が表示される
潮位カーブが表示される
```

実データがあるはずなので、可能な範囲で実値表示を確認する。
ただし、警戒対象が0件でも FAIL にしない。

---

## 9. `/live` 潮位データ取得口確認

ブラウザNetworkまたはコード静的確認で、`/live/stream` が既存 `/live` の潮位データ取得口を利用しているか確認する。

確認内容:

```text
既存backend/APIまたは正規化済みデータを使っている
フロントから直接 data_runtime の内部ファイルへ依存していない
潮位データ生成処理を重複実装していない
既存 /live とデータ解釈が大きくズレていない
```

---

## 10. 潮位カーブ確認

確認項目:

```text
デモデータではなく実データ由来の点列からカーブが作られている
現在時刻マーカーが表示される
demoNow=06:00 と demoNow=18:00 でマーカー位置が変わる
demoNowに応じて現在潮位も変化する、または最寄り時刻の値になる
```

確認URL例:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T06:00:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T18:00:00%2B09:00
```

可能なら通常実データモードでも同様に確認する。

---

## 11. 複数地点巡回確認

複数地点があるデモまたは実データで確認する。

期待:

```text
2地点ずつ表示される
8秒程度で次の2地点へ切り替わる
時計更新で巡回がリセットされない
潮位カーブも地点に応じて変わる
```

E2Eでは、地点名の変化を確認できるとよい。

---

## 12. 取得成功0件表示確認

地点0件になる状況を作れる場合は確認する。

方法例:

```text
Playwright route で潮位APIを空配列にmock
または demo/mock パラメータで empty を指定できるなら使用
```

期待:

```text
潮位・水位小窓: 現在、表示対象なし
ヘッダー: 潮位 0
console/page error なし
```

禁止:

```text
取得失敗扱いになる
undefined / null / NaN が表示される
```

---

## 13. 取得失敗表示確認

API失敗をmockできる場合は確認する。

方法例:

```text
Playwright route で潮位APIを500にする
不正JSONを返す
timeout相当
```

期待:

```text
潮位・水位小窓: 取得できません / 一時的に取得不可
ヘッダー: 潮位 - または取得不可
console error なし
page error なし
```

禁止:

```text
平常と断定
画面全体が真っ白
Unhandled promise rejection
```

取得失敗テストが実装困難な場合は Notes に書く。

---

## 14. ヘッダー潮位件数確認

確認項目:

```text
警戒対象あり → 潮位件数が1以上
警戒対象なし → 潮位 0
取得失敗 → 潮位 - または取得不可
```

重要:

```text
潮位 0 は地点データ0件ではなく、警戒対象0件の意味でよい
```

右下パネルに東京/横浜などの実潮位が表示されていても、ヘッダーが `潮位 0` なのは仕様として許容する。

---

## 15. 表示欠損確認

以下が画面に出ていないこと。

```text
undefined
null
NaN
Invalid Date
--undefined
```

満潮/干潮/偏差が欠損する場合は、仕様通り `--` 表示または項目非表示になっていること。

---

## 16. スクリーンショット

以下を保存する。

```text
test-results/live-stream-phase2b3-tide-demo-1920.png
test-results/live-stream-phase2b3-tide-calm-1920.png
test-results/live-stream-phase2b3-tide-live-1920.png
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
既存レイヤーUIが壊れていない
```

可能なら関連E2Eを実行する。

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
tasks/live/live_stream_phase2b3_tide_codex_verification.md
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
潮位カーブ確認
現在時刻マーカー確認
複数地点巡回確認
地点0件表示確認
取得失敗表示確認
ヘッダー潮位件数確認
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
潮位デモ表示E2EがPASS
既存 /live の潮位データ取得口を利用している
潮位データあり時に潮位・水位小窓へ反映される
2地点表示が維持される
潮位カーブが実データ由来になる
現在時刻マーカーが demoNow / 実時刻に連動する
ヘッダー潮位件数が仕様通り表示される
取得失敗時に平常と断定しない
console/page error なし
/live が壊れていない
/ が壊れていない
```

---

## PASS with notes条件

以下は PASS with notes とする。

```text
河川水位は未接続
警戒対象が検証時点で0件
取得失敗mockまでは未実施
高潮/警戒判定が簡易または未実装
中央地図の潮位パルスが未実装
テロップ動的化が最小対応または未対応
```

Phase 2-B.3 では上記のみを理由に FAIL にしない。

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
潮位・水位小窓が表示されない
潮位実データが表示されない
潮位カーブが壊れる
demoNowで現在時刻マーカーが動かない
取得失敗時に平常と断定する
undefined / null / NaN が画面に出る
/live が壊れる
/ が壊れる
```

---

## 最終コメント例

```text
判定: PASS

/live/stream Phase 2-B.3 潮位・水位情報実データ接続は、既存 /live の潮位データ取得口を利用し、潮位・水位小窓の現在潮位、満潮/干潮、潮位カーブ、現在時刻マーカーへ反映できることを確認しました。
地震・豪雨E2E、通常 /live、/ への回帰影響はありません。
河川水位と高度な警戒判定は次フェーズ以降の対象です。
```

# CODEX用検証指示書

## `/live/stream` Stream Phase 2-B.1: 地震情報 実データ接続 MVP 検証

## 目的

Claude Code が実装した `/live/stream` の地震情報実データ接続を検証する。

確認すること:

* Phase 2-A の既存E2Eが壊れていない
* `/live/stream` が引き続き表示できる
* 地震小窓が実データ接続に対応している
* 地震デモ表示がE2Eで安定している
* 地震0件時と取得失敗時を区別できる
* 中央地図の地震パルスが地震データ由来になる
* ヘッダー地震件数が地震データ由来になる
* 通常 `/live` と `/` に影響がない
* console/page error がない

検証結果を Markdown レポートとして保存する。

---

## 想定レポート保存先

```text
tasks/live/live_stream_phase2b1_earthquake_codex_verification.md
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
buildScene() の差し替え口が維持されている
地震 adapter 相当の処理がある
demo / mock モードがある場合、仕様が分かる
```

---

## 2. 不要な大改修確認

以下を確認する。

```text
backend APIを不用意に追加していない
DBを追加していない
/live 本体の大規模リファクタをしていない
キキクル・鉄道・潮位の実データ接続まで広げていない
```

今回の対象は地震のみ。
スコープが広がっている場合は Notes に書く。

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
```

追加ファイルがある場合はそれも対象にする。

```bash
node --check e2e/live-stream.spec.js
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

実装が `demo=1` ではなく別パラメータ名の場合は、実装仕様に合わせて読み替える。

---

## 6. 既存 dedicated E2E 実行

Phase 2-A で追加済みの E2E を実行する。

```bash
npx playwright test e2e/live-stream.spec.js
```

期待:

```text
全テスト PASS
```

既存テストが実データ接続の影響で不安定化していないこと。

---

## 7. 地震デモ表示E2E追加

可能であれば、`e2e/live-stream.spec.js` に地震デモ用テストを追加する。

対象URL例:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

確認項目:

```text
live-stream-panel-earthquake が表示される
live-stream-earthquake-active が表示される
live-stream-earthquake-history が表示される
live-stream-earthquake-history-item が1件以上ある
live-stream-earthquake-popup が表示される
live-stream-pulse-earthquake が表示される
ヘッダー地震件数が1以上になる
時計がdemoNowで固定される
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
地震データ取得処理が実行される
API失敗時に画面が壊れない
地震0件時に「表示対象なし」相当になる
地震がある場合は地震小窓に反映される
地震がある場合は中央地図に地震パルスが出る
```

実際に地震データがない時間帯の場合は、0件正常表示として扱う。
地震がある前提でFAILにしない。

---

## 9. `/live` 地震データ取得口の確認

ブラウザNetworkまたはコード静的確認で、`/live/stream` が既存 `/live` の地震データ取得口を利用しているか確認する。

確認内容:

```text
新規にJMA等へ直接アクセスしていないか
既存backend/APIを使っているか
既存正規化済みデータを使っているか
```

完全に同一のJSを共有できていなくても、既存APIを利用していれば Phase 2-B.1 としては可。

---

## 10. 0件表示確認

実データが0件になる状況を作れる場合は確認する。

方法例:

```text
Playwright route で地震APIを空配列にmock
または demo/mock パラメータで empty を指定できるなら使用
```

期待:

```text
地震小窓: 現在、表示対象なし
中央地図: 地震パルスなし
ヘッダー: 地震 0
console error なし
```

禁止:

```text
取得失敗扱いになる
地震情報なしと取得失敗が混同される
undefined / null / NaN が表示される
```

---

## 11. 取得失敗表示確認

API失敗をmockできる場合は確認する。

方法例:

```text
Playwright route で地震APIを500にする
Playwright route でtimeout相当
不正JSONを返す
```

期待:

```text
地震小窓: 取得できません / 一時的に取得不可
中央地図: 地震パルスなし、または前回表示なし
ヘッダー: 地震 - / 取得不可
console error なし
page error なし
```

禁止:

```text
地震情報なしと断定
画面全体が真っ白
Unhandled promise rejection
```

取得失敗テストが実装困難な場合は、静的確認と手動検証に留め、Notes に書く。

---

## 12. 12時間フィルタ確認

可能であれば mock で確認する。

データ例:

```text
demoNow = 2026-06-30T19:42:00+09:00

A: 2026-06-30T19:21:00+09:00 → 表示対象
B: 2026-06-30T08:00:00+09:00 → 表示対象
C: 2026-06-30T06:00:00+09:00 → 対象外
```

期待:

```text
A/B は履歴に出る
C は履歴から除外される
```

実装が既存 `/live` API側の絞り込みに依存する場合は、その仕様を確認し Notes に残す。

---

## 13. activeTarget 優先順位確認

可能であれば mock で確認する。

確認観点:

```text
最大震度が高い地震が優先される
最大震度が同じならMが大きい地震が優先される
それも同じなら新しい地震が優先される
```

完全実装がまだの場合は、現状の選択ルールをレポートに明記する。

---

## 14. 中央地図パルス確認

確認項目:

```text
地震データありで live-stream-pulse-earthquake が表示される
地震データなしで地震パルスが表示されない
地震パルス色が地震カテゴリ色 #ff4d3d 系である
```

可能なら位置も確認する。

```text
東北地震データなら中央地図の東北付近
関東地震データなら関東付近
九州地震データなら九州付近
```

簡略SVG地図なので、厳密な座標一致は求めない。

---

## 15. 地震小窓表示確認

確認項目:

```text
震源名
M
最大震度
発生時刻
深さ
津波情報があれば津波情報
```

欠損値確認:

```text
undefined が出ない
null が出ない
NaN が出ない
空欄が不自然に残らない
```

---

## 16. ヘッダー地震件数確認

確認項目:

```text
地震データあり → 地震件数が1以上
地震0件 → 地震 0
取得失敗 → 地震 - または取得不可
```

実装仕様に合わせて確認する。

---

## 17. スクリーンショット

以下を保存する。

```text
test-results/live-stream-phase2b1-earthquake-demo-1920.png
test-results/live-stream-phase2b1-earthquake-calm-1920.png
```

対象例:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

可能なら実データ表示スクリーンショットも保存する。

```text
test-results/live-stream-phase2b1-earthquake-live-1920.png
```

---

## 18. `/live` 回帰確認

通常 `/live` を開く。

確認項目:

```text
HTTP 200
console/page error なし
地図表示が壊れていない
地震リストが壊れていない
地震マーカー表示が壊れていない
津波警報中の地震リスト展開に影響していない
```

可能なら既存の関連E2Eを実行する。

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
tasks/live/live_stream_phase2b1_earthquake_codex_verification.md
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
0件表示確認
取得失敗表示確認
12時間フィルタ確認
activeTarget選択ルール確認
中央地図パルス確認
ヘッダー地震件数確認
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
地震デモ表示E2EがPASS
地震実データ取得口が既存 /live 資源を利用している
地震データあり時に地震小窓へ反映される
地震データあり時に中央地図パルスへ反映される
地震件数がヘッダーへ反映される
地震0件時に正常な対象なし表示になる
取得失敗時に「なし」と断定しない
console/page error なし
/live が壊れていない
/ が壊れていない
```

---

## PASS with notes条件

以下は PASS with notes とする。

```text
実データの地震が検証時点で0件だった
取得失敗mockまでは未実施
12時間フィルタの一部が既存API依存
activeTarget優先順位が簡易実装
中央地図の位置が簡略SVG上の概算
テロップ動的化が最小対応または未対応
```

Phase 2-B.1 では上記のみを理由にFAILにしない。

---

## FAIL条件

以下の場合は FAIL。

```text
/live/stream が404
画面が真っ白
重大なconsole/page error
既存 dedicated E2E が壊れる
地震小窓が表示されない
地震データ0件と取得失敗を混同する
取得失敗時に「地震なし」と断定する
undefined / null / NaN が画面に出る
/live が壊れる
/ が壊れる
```

---

## 最終コメント例

```text
判定: PASS

/live/stream Phase 2-B.1 地震情報実データ接続は、既存 /live の地震データ取得口を利用し、地震小窓・中央地図パルス・ヘッダー件数へ反映できることを確認しました。
demo=1 による安定E2Eも追加済みで、通常 /live と / への回帰影響はありません。
次フェーズではキキクル・豪雨情報の実データ接続へ進めます。
```

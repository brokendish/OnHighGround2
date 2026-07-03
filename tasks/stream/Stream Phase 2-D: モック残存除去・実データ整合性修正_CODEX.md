# CODEX用検証指示書

## `/live/stream` Stream Phase 2-D: モック残存除去・実データ整合性修正 検証

## 目的

Claude Code が対応した `/live/stream` の本番化前修正を検証する。

主な検証対象:

```text
モック操作UIの削除
demo / real / calm の分離
潮位グラフと現在潮位の整合性
潮位現在時刻縦線の位置
子画面巡回の重複排除
情報あり時の「現在、表示対象なし」誤表示解消
既存E2E回帰
/live と / の回帰
```

検証結果を Markdown レポートとして保存する。

---

## レポート保存先

```text
tasks/live/live_stream_phase2d_cleanup_codex_verification.md
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
/live/stream 関連ファイル中心の変更である
通常 /live への影響が最小限である
通常 / への影響がない
モックUI削除/非表示の変更がある
潮位描画ロジックの修正がある
巡回重複排除ロジックがある
all clear 判定修正がある
```

---

## 2. 構文チェック

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

追加E2Eがある場合はそれも対象にする。

---

## 3. Docker状態確認

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

既存サービスが壊れていないこと。

---

## 4. HTTP確認

以下が 200 で返ること。

```text
/live/stream
/live/stream?chrome=off
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
/live
/
```

---

## 5. モック操作UI削除確認

通常表示で以下のUIが表示されないことを確認する。

対象URL:

```text
/live/stream
/live/stream?chrome=off
```

表示されてはいけない文言:

```text
平穏時
警戒時
自動デモ
自動でも
```

確認方法:

```text
Playwright text locator
スクリーンショット
DOM確認
```

ただし、URLパラメータによる制御は維持されていること。

```text
?state=calm
?state=alert
?demo=1
?demoNow=...
```

---

## 6. demo / real 分離確認

### 通常表示

対象URL:

```text
/live/stream?chrome=off
```

確認:

```text
固定デモ地震「岩手県沖 M6.1」などが無条件で混入していないこと
固定デモ大雨「静岡県中部」などが無条件で混入していないこと
固定デモ鉄道「中央線快速」などが無条件で混入していないこと
固定デモ潮位値が無条件で混入していないこと
```

実データに同名情報がある場合は、APIレスポンスと照合する。

### demo表示

対象URL:

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T19:42:00%2B09:00
```

確認:

```text
デモ表示は維持される
地震・大雨・鉄道・潮位のデモテロップが出る
```

### calm表示

対象URL:

```text
/live/stream?state=calm&chrome=off&demoNow=2026-06-30T19:42:00%2B09:00
```

確認:

```text
強制平穏表示になる
警戒デモ文言が出ない
```

---

## 7. 潮位現在時刻縦線の位置確認

以下の3パターンを確認する。

```text
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T06:00:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T12:00:00%2B09:00
/live/stream?state=alert&chrome=off&demo=1&demoNow=2026-06-30T18:00:00%2B09:00
```

期待:

```text
06:00 → グラフ左から約1/4
12:00 → グラフ中央付近
18:00 → グラフ左から約3/4
```

確認対象:

```text
live-stream-tide-current-marker
SVG cx / x / transform
スクリーンショット
```

FAIL条件:

```text
06/12/18 のすべてで右端付近
demoNowに関係なく同じ位置
NaN/undefinedで位置が壊れる
```

---

## 8. 潮位値の OnHighGround2 整合確認

同じ地点・同じ時刻で、以下を比較する。

```text
OnHighGround2 本体または /live の潮位APIの値
/live/stream の表示値
```

対象地点例:

```text
東京
横浜
```

確認項目:

```text
現在潮位 cm
満潮時刻/潮位
干潮時刻/潮位
潮位カーブの形
```

許容:

```text
丸め差 ±1cm 程度
表示桁の差
```

要注意:

```text
数十cm単位でズレる
カーブの山谷が本体と明らかに違う
現在潮位だけ別ソース/デモ値になっている
```

---

## 9. 潮位カーブの実データ由来確認

確認観点:

```text
簡易正弦波や固定ダミーカーブが通常表示で使われていない
実データ点列からpathが生成されている
demo=1 のときだけデモカーブを使っている
```

可能ならコード静的確認とスクリーンショット比較を行う。

---

## 10. 巡回重複排除確認

キキクル/豪雨で確認する。

方法:

```text
複数対象を返す mock を使う
同一 areaName の重複を含める
8秒巡回を確認する
```

期待:

```text
福島県会津市 → 福島県会津市 のような連続重複が起きない
重複対象は1件にまとめられる
targets.length=1 の場合は固定表示になる
```

確認対象:

```text
小窓の active 表示
live-stream-rain-active
巡回インジケータ
```

可能であれば、専用E2Eを追加する。

---

## 11. 情報あり時の「現在、表示対象なし」誤表示確認

mockまたはdemoで、情報あり状態を作る。

確認対象:

```text
地震あり
豪雨あり
鉄道影響あり
潮位警戒あり
```

期待:

```text
中央に「現在、表示対象なし」が出ない
該当小窓に activeTarget またはカードが表示される
座標なしでもリスト/カードは表示される
```

特に豪雨で以下を確認する。

```text
リストには危険情報がある
しかしactiveTargetがnull
→ この場合に「現在、表示対象なし」にならないこと
```

---

## 12. 取得失敗時の扱い

可能であればAPI失敗mockを確認する。

期待:

```text
取得できません / 一時的に取得不可
```

禁止:

```text
平常
影響なし
現在、表示対象なし
```

取得失敗と対象なしを混同しないこと。

---

## 13. 既存E2E実行

既存E2Eをすべて実行する。

```bash
npx playwright test e2e/live-stream.spec.js
npx playwright test e2e/eq-mock-verify.spec.js
npx playwright test e2e/rain-mock-verify.spec.js
npx playwright test e2e/tide-mock-verify.spec.js
npx playwright test e2e/rail-mock-verify.spec.js
```

追加E2Eがある場合は実行する。

期待:

```text
全テスト PASS
```

---

## 14. スクリーンショット保存

以下を保存する。

```text
test-results/live-stream-phase2d-cleanup-real-1920.png
test-results/live-stream-phase2d-cleanup-demo-1920.png
test-results/live-stream-phase2d-cleanup-calm-1920.png
test-results/live-stream-phase2d-tide-0600.png
test-results/live-stream-phase2d-tide-1200.png
test-results/live-stream-phase2d-tide-1800.png
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

## レポートに含める内容

```text
判定: PASS / PASS with notes / FAIL
検証日時
対象ブランチ/コミット
変更ファイル
構文チェック結果
Docker状態
HTTP確認結果
モックUI削除確認
demo/real分離確認
潮位縦線位置確認
潮位値整合確認
潮位カーブ確認
巡回重複排除確認
情報あり時の対象なし誤表示確認
取得失敗時表示確認
E2E結果
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
モック操作UIが通常画面から消えている
URLパラメータ制御は維持されている
通常表示にデモデータが混入しない
潮位現在時刻縦線が demoNow に応じて妥当な位置に出る
潮位値が OnHighGround2 本体または /live API と整合する
潮位カーブが実データ由来である
巡回で同一対象が連続重複表示されない
情報あり時に「現在、表示対象なし」が出ない
既存E2EがPASS
console/page error なし
/live が壊れていない
/ が壊れていない
```

---

## PASS with notes条件

以下は PASS with notes とする。

```text
潮位カーブ比較が目視中心
取得失敗mockの一部未実施
巡回重複の確認が一部カテゴリのみ
OnHighGround2本体との潮位比較が代表地点のみ
```

---

## FAIL条件

以下の場合は FAIL。

```text
モック操作UIが通常画面に残っている
通常表示に固定デモデータが混入する
潮位縦線が常に右端に出る
潮位値が本体と大きくズレる
巡回で同一対象が連続重複する
情報ありなのに「現在、表示対象なし」が出る
undefined / null / NaN が表示される
既存E2Eが壊れる
/live が壊れる
/ が壊れる
```

---

## 最終コメント例

```text
判定: PASS

/live/stream Phase 2-D は、モック操作UIを通常画面から除去し、demo/real/calm の分離、潮位グラフと現在潮位の整合、巡回重複排除、情報あり時の対象なし誤表示解消を確認しました。
既存E2E、通常 /live、/ への回帰影響はありません。
これにより、次工程のOBS/配信運用安定化へ進めます。
```

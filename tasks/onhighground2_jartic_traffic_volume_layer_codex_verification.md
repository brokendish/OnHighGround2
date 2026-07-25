# OnHighGround2 Phase 7-B.3 JARTIC 道路交通量・色分けマーカーレイヤー CODEX検証指示書

## 1. 検証目的

Claudeが実装した OnHighGround2 通常画面向け JARTIC 道路交通量レイヤーの色分け対応について、実装内容・実データ・PC/モバイル画面・回帰影響を独立検証する。

本検証の主眼は、単なるテスト成功確認ではなく、以下を実画面とコードの両面から確認することである。

- 通常画面の青一色マーカーが、LIVE側と同じ意味・閾値・色に基づいて分類されていること
- 通常画面側で独自の閾値やカテゴリが新設されていないこと
- 実JARTICデータで複数カテゴリの色分けが成立していること
- 低ズーム停止、BBOX取得、デバウンス、キャンセル処理が実際に機能すること
- モバイルで凡例・ポップアップ・情報パネル・警告UIが干渉しないこと
- `/live` および `/live/stream.html` 側へ回帰がないこと

実装修正は原則として行わず、まず検証と報告を行うこと。

重大な不具合、明確な要件逸脱、テストのfalse positive、または軽微かつ安全に直せる検証コード上の問題を発見した場合のみ、必要最小限の修正を行ってよい。その場合は、修正理由・変更ファイル・再検証結果を明示すること。

---

## 2. 対象リポジトリ・画面

対象プロジェクト：OnHighGround2

主対象画面：

```text
/
```

回帰確認対象：

```text
/live
/live/stream.html
```

主な変更対象として報告されているファイル：

```text
backend/app/services/jartic_traffic_service.py
tests/test_jartic_traffic_service.py
frontend/js/jartic-traffic-layer.js
frontend/js/map-overlay-ui.js
frontend/index.html
e2e/jartic-traffic-layer.spec.js
```

参照すべきLIVE側実装：

```text
backend/app/services/live_road_traffic_service.py
backend/app/models/live_road_traffic.py
frontend/js/live/live-road-traffic-layer.js
```

実際のリポジトリ構成に合わせてパスを確認すること。

---

## 3. Claude実装報告の前提

Claude報告では以下が実装済みとされている。

### 3.1 共通化

- `classify_volume()` をLIVE側サービスからimport
- `STATUS_LABEL` / `SEVERITY` をLIVE側モデルからimport
- JS側の色コードとカテゴリ文言はLIVE側から1:1で転記
- 免責文言をLIVE側と統一

免責文言：

```text
交通量APIの値から推定した表示であり、通行止め・規制を断定するものではありません。
```

### 3.2 色分類

| status | 条件 | 色 | 表示ラベル |
|---|---:|---|---|
| very_high | 5分値 150以上 | `#dc2626` | 交通量非常に多い |
| high | 80以上 | `#d97706` | 交通量多い |
| normal | 上記・下記以外 | `#22c55e` | 通常 |
| low | 15以下 | `#1f6feb` | 交通量少ない |
| very_low | 3以下 | `#7c3aed` | 交通量極端に少ない |
| unknown | データなし | `#9ca3af` | 状態不明 |

閾値境界の優先順により分類が変わらないか、実装をコードで確認すること。

### 3.3 通常画面固有の仕様

- 1観測点＝1マーカー
- 上り・下りのうち `severity` が高い側をマーカー色として採用
- severity同値時は上り優先
- ポップアップでは上り・下り双方の状態を表示
- zoom 11未満では取得停止
- moveend / zoomend は250msデバウンス
- AbortControllerとトークン方式で古いリクエスト・レスポンスを破棄
- 凡例はレイヤーON時のみ表示
- 通常画面はLIVE側より広い観測点セットを取得する可能性がある

---

## 4. 検証時のガードレール

以下を厳守すること。

- `/live`、`/live/stream.html` のUI・挙動を意図的に変更しない
- LIVE側の分類閾値を変更しない
- 通常画面独自の分類閾値を追加しない
- 「渋滞」「通行止め」「規制中」と断定する文言へ変更しない
- APIキー、秘密情報、YouTube Stream Key等をログ・レポートへ記載しない
- JARTIC CQLフィルターで日本語フィールド名をダブルクォートしない
- 実データ取得失敗を「交通量なし」と誤表示しない
- テストを通すためだけのproductionコード変更を行わない

---

## 5. 事前調査

最初にコード差分と関連実装を確認し、検証レポートに簡潔にまとめること。

### 5.1 Git差分

以下を確認する。

```bash
git status --short
git diff -- backend/app/services/jartic_traffic_service.py
git diff -- tests/test_jartic_traffic_service.py
git diff -- frontend/js/jartic-traffic-layer.js
git diff -- frontend/js/map-overlay-ui.js
git diff -- frontend/index.html
git diff -- e2e/jartic-traffic-layer.spec.js
```

コミット済みの場合は適切な比較元を使うこと。

### 5.2 共通化実態

以下をコードで確認する。

- Python側がLIVE側の関数・定数を本当にimportしているか
- import先が循環依存を起こさない構造か
- 通常画面側に同等の閾値ロジックが重複定義されていないか
- JS側の色・ラベルがLIVE側と一致するか
- 「LIVE側と同一値」のコメントだけでなく、実値が一致しているか
- `unknown` を含む全カテゴリが欠落なく扱われているか

可能であれば、比較用の小さな検証スクリプトまたはテストで、LIVE側と通常画面側のカテゴリ名・色・ラベルの一致を自動確認すること。

---

## 6. 静的検証

### 6.1 Python構文・import

```bash
python -m compileall backend/app/services/jartic_traffic_service.py
```

プロジェクトのvenvを使用する場合は実環境に合わせること。

以下も確認する。

- import errorなし
- 循環importなし
- typingや未使用importによる致命的問題なし

### 6.2 JavaScript構文

```bash
node --check frontend/js/jartic-traffic-layer.js
node --check frontend/js/map-overlay-ui.js
```

### 6.3 HTML/CSS

- `frontend/index.html` のタグ崩れがない
- 凡例CSSが既存スタイルを不必要に上書きしていない
- グローバルすぎるセレクタを追加していない
- `z-index` を過剰に引き上げていない
- モバイル専用の固定幅により横スクロールを発生させない

---

## 7. Python単体テスト

### 7.1 JARTIC専用テスト

```bash
pytest -q tests/test_jartic_traffic_service.py
```

最低限、以下の境界値を明示的に確認すること。

- `None` / 欠損 → unknown
- 0 → very_low
- 3 → very_low
- 4 → low
- 15 → low
- 16 → normal
- 79 → normal
- 80 → high
- 149 → high
- 150 → very_high

LIVE側の `classify_volume()` が境界順序を含めて正しく動作しているか検証する。

### 7.2 上下方向統合

通常画面の1観測点1マーカー仕様について、少なくとも以下を確認する。

- 上りvery_high、下りnormal → very_high
- 上りlow、下りhigh → high
- 上りnormal、下りnormal → normal
- 上りunknown、下りnormal → normalまたは仕様どおりの結果
- 上りunknown、下りunknown → unknown
- severity同値時に上り優先となること

「重い方」の比較が、文字列順や辞書順ではなく `SEVERITY` に基づいていることを確認する。

### 7.3 APIレスポンス

レスポンスに以下が期待どおり含まれること。

- `status_up`
- `status_down`
- 総合status相当の値
- 上り・下り交通量
- 合計、小型、大型
- 観測時刻
- 観測点コード

欠損値で500にならず、unknownへ安全にフォールバックすること。

---

## 8. E2Eテスト精査

```bash
npx playwright test e2e/jartic-traffic-layer.spec.js
```

既存21件の結果だけでなく、各テストが実際に対象機能を検証しているかコードを読むこと。

特に以下のfalse positiveを確認する。

- route mockの登録順により意図しないhandlerが応答していないか
- 色の検証が要素存在だけで終わっていないか
- CSS計算後の色ではなく未使用属性だけを見ていないか
- レイヤーOFF後も非表示DOMを数えてPASSしていないか
- 低ズーム時に、以前のマーカーが残存したままでもPASSしないか
- デバウンス試験がAPI呼び出し発生前に終了していないか
- AbortController試験が古いレスポンスの破棄まで見ているか
- ポップアップの免責文言を部分一致しすぎていないか

問題があれば、productionコードではなくE2E側を必要最小限で修正し、再実行すること。

---

## 9. 実API・実データ検証

モックだけで完了にしないこと。Dockerまたはローカル実環境で実JARTICデータを使用して確認する。

### 9.1 起動確認

プロジェクト標準手順で必要サービスを起動する。

例：

```bash
docker compose ps
```

必要に応じてbuild/upを行うが、既存データや秘密情報を破壊しないこと。

### 9.2 API確認

実際の通常画面向けJARTIC APIへBBOX付きでアクセスし、HTTP 200とレスポンス内容を確認する。

確認事項：

- CQLフィルターが400にならない
- 日本語フィールド名のダブルクォート問題が再発していない
- BBOXが現在表示範囲に対応している
- 実データにstatusが付与されている
- 全件unknownまたは全件同色になっていない
- 0件時と取得失敗時を区別している

### 9.3 複数色確認

可能な表示範囲・時刻を選び、少なくとも2カテゴリ以上のマーカー色が実画面で表示されることを確認する。

理想は以下のうち3カテゴリ以上。

- 赤
- 黄
- 緑
- 青
- 紫
- グレー

実データ都合でカテゴリが揃わない場合は、その事実を明示し、APIレスポンス上の分類分布を集計して示すこと。

例：

```text
very_high: N件
high: N件
normal: N件
low: N件
very_low: N件
unknown: N件
```

---

## 10. PC実画面検証

Chromium 1440×900程度で通常画面 `/` を確認する。

### 10.1 レイヤートグル

- 「道路交通量」または実装された統一文言で表示される
- 初期状態OFF
- ONで取得・描画開始
- OFFでマーカー消去
- OFFで凡例非表示
- OFF後の地図移動で不要なAPI通信が発生しない
- 再ONで正常復帰

### 10.2 ズーム制御

- zoom 11未満では新規取得しない
- 低ズーム案内が分かりやすい
- zoom 11未満へ移動した際、既存マーカーが残って誤解を招かない
- zoom 11以上へ戻すと取得・表示が再開する

低ズーム時の既存マーカー残存については、仕様が明確でなければUX上の問題として評価すること。

### 10.3 色と凡例

- マーカー色が分類結果と一致
- 凡例6カテゴリの色・ラベルが一致
- 凡例順が「多い→少ない→不明」で分かりやすい
- 紫を最混雑と誤解しないよう凡例が常に確認可能
- レイヤーON時のみ表示

### 10.4 ポップアップ

実データのマーカーをクリックし、以下を確認する。

- 観測点コード
- 上り交通量・状態
- 下り交通量・状態
- 総合状態
- 合計・小型・大型
- 観測時刻
- 集計単位・データ種別
- 出典
- 免責文言

数値欠損時に `undefined`、`null`、`NaN` が表示されないこと。

### 10.5 地図操作

- パン・ズームが重くなりすぎない
- マーカークリック後も地図操作可能
- 他レイヤーと同時ONで操作不能にならない
- 避難経路・現在地・避難所マーカーを過度に隠さない

---

## 11. モバイル実画面検証

Claude報告で未実施のため、本検証では必須とする。

代表ビューポート：

```text
390 × 844
```

可能なら以下も確認する。

```text
375 × 667
430 × 932
```

### 11.1 基本表示

- 道路交通量トグルが操作可能
- 凡例が画面外へはみ出さない
- 凡例の長い日本語が不自然に切れない
- 横スクロールが発生しない
- マーカーがタップ可能
- ポップアップが左右にはみ出さない
- ポップアップ内を必要に応じてスクロールできる

### 11.2 情報パネル干渉

以下の状態で確認する。

- 情報パネル閉
- 情報パネル通常表示
- 情報パネル最大化

確認事項：

- 最大化した情報パネルより凡例・マーカー・ポップアップが前面に残らない
- 情報パネルの閉じる操作を妨げない
- 右側コントロール、LIVEボタン、交通量凡例が重ならない
- レイヤーON/OFF操作後も画面操作が継続できる

### 11.3 警告UI干渉

可能なモックまたは既存E2E手法を使って、津波警告・警戒ボトムシート等が表示された状態を再現する。

- 警告表示が交通量凡例に隠れない
- 情報パネル最大化時に操作不能にならない
- 交通量ポップアップが警告UIより不適切に前面へ出ない

---

## 12. 通信・競合・パフォーマンス検証

### 12.1 デバウンス

連続パンを行い、moveend/zoomendの発生数に対してAPI呼び出しが過剰にならないことを確認する。

Claude報告の「連続パン5回で増分2回以内」を再現するだけでなく、ブラウザのNetworkまたはPlaywright計測で根拠を示すこと。

### 12.2 リクエストキャンセル

応答を意図的に遅延させたモックを使い、以下を確認する。

1. BBOX Aを要求
2. 直後にBBOX Bへ移動
3. Bのレスポンスが先に到着
4. 遅れてAが到着
5. 最終表示がBのデータのままである

AbortControllerだけに依存せず、トークンによる古いレスポンス破棄が実際に効いていること。

### 12.3 ON/OFF反復

10回程度ON/OFFを繰り返し、以下を確認する。

- イベントリスナーが重複登録されない
- API呼び出しが回数に比例して増殖しない
- マーカーレイヤーが重複しない
- コンソールエラーが出ない
- OFF中の通信が止まる

### 12.4 エラー時

500、タイムアウト、ネットワーク切断を再現し、以下を確認する。

- 「交通量なし」と誤断定しない
- 既存マーカーをどう扱うかが一貫している
- コンソールログが連続スパムにならない
- 復旧後に自動または再操作で正常表示へ戻れる

---

## 13. LIVE側との一致・回帰確認

### 13.1 分類一致

同一の数値を通常画面側とLIVE側の分類関数へ入力し、同一statusになることを確認する。

代表値：

```text
0, 3, 4, 15, 16, 79, 80, 149, 150, null
```

### 13.2 色・文言一致

通常画面とLIVE側で以下が一致すること。

- status名
- 色コード
- 表示ラベル
- 免責文言

### 13.3 対象点差の確認

通常画面とLIVE側では取得対象が異なる可能性があるため、以下を区別して評価する。

- 同一観測点・同一方向・同一交通量値なら分類は一致すること
- 表示観測点総数が異なること自体は即FAILにしない
- 通常画面が高速道路等を含む既存仕様を維持していることを記録する

### 13.4 回帰

最低限、以下を実行する。

```bash
npx playwright test e2e/live-road-traffic-layer.spec.js
```

ベースライン失敗がある場合は、今回差分あり／なしで比較し、本変更起因かを確認する。

`/live` と `/live/stream.html` を実画面でも開き、以下を確認する。

- ページ初期化エラーなし
- コンソールエラーなし
- レイアウト崩れなし
- LIVE側交通量表示の色・凡例・ポップアップに変化なし

---

## 14. 通常画面の代表回帰テスト

最低限、以下を実行する。

```bash
npx playwright test e2e/smoke.spec.js
npx playwright test e2e/hazard-state-consistency.spec.js
npx playwright test e2e/evacuation-ui.spec.js
npx playwright test e2e/shelter-marker-image.spec.js
```

失敗がある場合：

- 変更前ベースラインでも同一失敗か確認
- 今回差分との因果関係をコード・再現手順で判断
- 単に「既存失敗」とせず、根拠をレポートする

可能なら対象テストだけでなく、主要frontend E2Eの代表セットも実行する。

---

## 15. 総合判定基準

### PASS

以下をすべて満たす。

- Python側分類がLIVE側ロジックを真に共通利用
- 色・ラベル・免責文言がLIVE側と一致
- 実APIで正常取得
- 実画面で色分け表示
- PC・モバイルとも重大な表示崩れなし
- 情報パネル・警告UIと干渉なし
- OFF時通信停止
- デバウンス・古いレスポンス破棄が機能
- 通常画面とLIVE側に新規回帰なし

### PASS with notes

主要要件は満たすが、以下のような限定的な注意点が残る場合。

- 実データの都合で一部カテゴリを目視できないが、レスポンス分布・モックで裏付け済み
- 軽微な凡例折返しや文言改善余地
- 対象観測点セットや方向別マーカー方式がLIVE側と異なるが、意図された既存仕様
- 定量的な長時間メモリ測定のみ未実施

### FAIL

以下のいずれかがある。

- 通常画面独自の閾値が残る
- LIVE側と同じ数値で分類結果が異なる
- 実API取得が400/500になる
- 全マーカーが固定色またはunknownになる
- 低ズームでも大量通信・描画が続く
- OFF中も通信する
- 古いレスポンスで表示範囲が巻き戻る
- モバイルで操作不能、閉じるボタンを塞ぐ、横スクロールが発生
- 「渋滞」「通行止め」と誤断定
- `/live` または `/live/stream.html` に新規回帰
- E2Eがfalse positiveで主要要件を実際には検証していない

---

## 16. 検証成果物

以下のレポートを作成すること。

```text
tasks/onhighground2_jartic_traffic_volume_layer_codex_verification.md
```

リポジトリの既存命名規則により、より適切な `tasks/` 配下へ配置してよい。

### レポート必須項目

1. 総合判定：PASS / PASS with notes / FAIL
2. 検証日時・環境
3. Git差分概要
4. 共通化実態の確認結果
5. 分類境界値テスト結果
6. API実データ確認結果
7. 実データのカテゴリ別件数
8. PC画面確認結果
9. モバイル画面確認結果
10. 情報パネル・警告UIとの干渉確認
11. デバウンス・Abort・古いレスポンス破棄確認
12. ON/OFF反復確認
13. LIVE側一致確認
14. 実行テスト一覧と結果
15. ベースライン失敗との比較
16. 発見した問題と重要度
17. 修正を行った場合の変更内容
18. 残課題・注意点

### スクリーンショット

可能なら以下を保存する。

```text
test-results/jartic-traffic-desktop.png
test-results/jartic-traffic-mobile.png
test-results/jartic-traffic-mobile-panel-max.png
test-results/jartic-traffic-popup.png
```

実際のプロジェクト規則に合わせて保存先を変更してよい。

---

## 17. 最終報告形式

完了時は、チャット上で以下を簡潔に報告すること。

- 判定
- 検証レポートのパス
- 実行した主要テストと結果
- 実データで確認できた色カテゴリ
- PC・モバイルの確認結果
- LIVE側への回帰有無
- 発見した問題またはnotes
- 修正した場合は変更ファイル一覧

「テストが通ったためPASS」だけで終わらず、実画面・実API・モバイル・競合制御を確認した根拠を必ず示すこと。

---

# CODEX 独立検証結果

## 総合判定

**FAIL**

検証日時は2026-07-25 12:00〜12:15 JST、HEADは`d27970b`。macOS、
Playwright Chromium（1440×900、390×844）、Docker Composeのbackend/frontend、
実JARTIC WFSを使用した。

分類共通化、実APIでのstatus付与、BBOX取得、低ズーム停止、基本的な
PC/モバイル描画は成立した。一方、免責文言がLIVEと完全一致せず、既存E2Eには
色・デバウンスのfalse positiveがあり、Abort競合、10回ON/OFF、モバイル情報パネル
最大化、警告UI干渉の必須検証が欠落しているためPASS条件を満たさない。

## Git差分概要

検証開始時の対象差分は次の6ファイル。

- `backend/app/services/jartic_traffic_service.py`: LIVE分類関数・定数をimportし、
  方向別statusと総合statusを追加
- `tests/test_jartic_traffic_service.py`: status、unknown、mock分類テストを追加
- `frontend/js/jartic-traffic-layer.js`: 6色、凡例、方向別状態、低ズーム停止、
  250msデバウンス、AbortController＋tokenを追加
- `frontend/js/map-overlay-ui.js`: トグル、status、凡例スロットを追加
- `frontend/index.html`: 凡例CSSを追加
- `e2e/jartic-traffic-layer.spec.js`: 対象E2Eを21件へ拡張

既存の未コミット差分を保全し、productionコードおよびE2Eコードは修正していない。

## 共通化とLIVE一致

- Pythonは`live_road_traffic_service.classify_volume`を直接importしており、
  通常画面独自の閾値関数はない。
- `SEVERITY`、`STATUS_LABEL`もLIVEモデルから直接import。循環importなし。
- 総合statusは`SEVERITY`の数値比較、同値時は`>=`により上り優先。
- 色は6カテゴリすべて一致:
  `very_high #dc2626`、`high #d97706`、`normal #22c55e`、
  `low #1f6feb`、`very_low #7c3aed`、`unknown #9ca3af`。
- 6カテゴリの表示ラベルも一致。
- 免責文言は不一致。
  - 通常: `交通量APIの値から推定した表示であり、通行止め・規制を断定するものではありません。`
  - LIVE: `交通量APIの値から推定した交通影響であり、通行止め・規制を断定するものではありません。`

## 分類境界値

LIVEの`classify_volume()`を直接実行し、次の10件はすべて期待値と一致した。

```text
None=unknown
0=very_low, 3=very_low
4=low, 15=low
16=normal, 79=normal
80=high, 149=high
150=very_high
```

上下統合はコードと単体テストで`SEVERITY`比較、unknown fallback、同値時上り優先を
確認した。ただし指示書記載の全組合せを独立test caseとしては網羅していない。

## 実API・実データ

backend再起動後に次を確認した。

```text
GET /api/jartic/traffic?bbox=139.55,35.50,139.95,35.85
HTTP 200 / status=ok / items=23
observed_at=2026-07-25T11:45:00+09:00
```

CQLは400にならず、日本語フィールド名のダブルクォート問題なし。指定BBOX内だけを返し、
`status`、`status_up`、`status_down`、各labelを実データで確認した。0台は
`very_low`となり、欠損と区別された。

カテゴリ分布:

```text
very_high: 3
high:      16
normal:    2
low:       0
very_low:  2
unknown:   0
```

実APIで4カテゴリが成立した。実画面の初期表示範囲はhighのみ
（desktop 3点、mobile 2点）だったため、複数色同時表示はモックE2E、
実データの複数カテゴリはAPI集計で確認した。

## PC・モバイル実画面

PC 1440×900:

- 初期OFF、ONでBBOX取得、OFFでmarker/凡例消去を確認
- zoom 11未満でmarkerをclearし、新規取得せず案内を表示
- 実画面のhigh marker計算済みfillは`rgb(217, 119, 6)`（`#d97706`）
- 凡例6カテゴリの色、ラベル、順序を確認
- popup必須項目はE2Eとコードで確認
- page error 0

Mobile 390×844:

- 実データ2 marker描画
- document横スクロールなし
- page error 0

保存したスクリーンショット:

- `test-results/jartic-traffic-desktop.png`
- `test-results/jartic-traffic-mobile.png`

375×667、430×932、popup端部/内部スクロールは未実施。情報パネル最大化および
津波警告・警戒ボトムシートの再現は未実施で、
`jartic-traffic-mobile-panel-max.png`は未作成。この必須項目に証跡がない。

## 通信・競合・反復

productionコードには250msデバウンス、取得前abort、単調増加tokenによる古い成功応答・
OFF後応答の破棄がある。

しかし対象E2Eの連続pan試験は追加呼び出し数`<= 2`だけを検証し、0回でもPASSする。
Aを遅延、Bを先着させて最終表示がBであることを確認する試験もない。単発ON/OFFは確認したが、
10回反復時のlistener/API/layer増殖、OFF中通信、console spamは未確認。

## E2E精査で確認したfalse positive

1. 色テストは`.jartic-traffic-status-*`クラスの存在だけを確認し、
   SVGの計算済み`fill`を検証しない。色コードが誤っていてもPASSし得る。
2. デバウンステストにAPI呼び出し数の下限がなく、0回でもPASSする。
3. Abort＋token、10回反復、mobile panel/warning干渉のtest caseがない。
4. routeは広い`/api/**`の後にJARTIC専用routeを登録しており、今回の実行では
   専用handlerが応答した。登録順による誤応答は再現しなかった。
5. OFFと低ズームはDOM marker数0まで確認しており、非表示DOM残存型の
   false positiveは認めなかった。

## 実行テストと結果

| 検証 | 結果 |
|---|---:|
| Python compileall（pycacheを`/private/tmp`へ指定） | PASS |
| JS `node --check` 2ファイル | PASS |
| `pytest -q tests/test_jartic_traffic_service.py` | 22 passed |
| 境界値直接検証 | 10/10 passed |
| `e2e/jartic-traffic-layer.spec.js` | 21 passed |
| `e2e/live-road-traffic-layer.spec.js` | 2 passed / 8 failed |
| `e2e/smoke.spec.js` | 7 passed |
| `e2e/hazard-state-consistency.spec.js` | 13 passed |
| `e2e/evacuation-ui.spec.js` | 6 passed |
| `e2e/shelter-marker-image.spec.js` | 1 passed / 1 failed |

代表回帰セット合計は30 passed / 9 failed。

## ベースライン失敗との比較

LIVE 8失敗は`#live-road-traffic-card`および`#live-train-card`が現行DOMに存在しない
旧selector待ち。失敗スナップショットでは現行LIVE画面自体は描画されている。今回差分に
`frontend/live.html`、`frontend/js/live/`、LIVE API/model/serviceの変更はないため、
今回変更起因ではない。実画面の`/live`と`/live/stream.html`はtitle、初期化、
page error 0を確認した。

shelter marker 1失敗は期待SVG 7件に対し4件。今回差分に`shelters.js`やmarker assetの
変更はなく、今回変更起因ではない。

未コミットのユーザー差分を保全するためbaseline checkoutは行わず、差分対象、失敗selector、
画面スナップショットから因果判定した。

## 発見した問題

- **High**: Abort順逆転、10回反復、情報パネル最大化、警告UI干渉の必須検証欠落
- **Medium**: E2Eの色検証が実色を見ないfalse positive
- **Medium**: E2Eのデバウンス検証が0回でも通るfalse positive
- **Medium**: 免責文言がLIVEと不一致
- **Low**: LIVE回帰E2Eのselectorが現行DOMから陳腐化

## 修正内容・残課題

検証レポート追記とスクリーンショット作成以外の修正は行っていない。

残課題:

1. 通常/LIVEどちらを正とするか決め、免責文言を完全一致させる。
2. API statusとSVG計算済みfill RGBを対応付けるE2Eを追加する。
3. デバウンス呼び出しを下限込み（例: ちょうど1回）で検証する。
4. 遅延A/先着Bで最終marker/popupがBのままであることを検証する。
5. 10回ON/OFF後のlistener、API数、marker数、console errorを計測する。
6. mobile panel閉/通常/最大化と警告UIでz-index、閉じる操作、popup、凡例を確認する。
7. LIVE回帰E2Eを現行DOMへ追随させる。

---

# CODEX 再検証結果（2026-07-25）

## 再検証判定

**PASS with notes**

前回FAILとした5項目への修正を、差分、E2E assertion、独立実行結果、
生成スクリーンショットの目視で再検証した。すべて解消を確認した。

notesは本タスク起因ではない既知の回帰E2E 9失敗、および実データの時刻依存で
全6カテゴリが同時には出現しなかった点。

## FAIL指摘への対応確認

| 前回指摘 | 再検証結果 |
|---|---|
| 通常/LIVE免責文言不一致 | `推定した交通影響であり...`で完全一致 |
| 色E2Eがクラス名だけを検証 | SVG pathの実`fill`をstatusごとに検証し、3色以上もassert |
| デバウンスが0回でもPASS | 5回pan後の追加APIを`toBe(1)`で検証 |
| Abort/古い応答破棄が未検証 | 遅延A・先着B後、popupがBのみ、Aなし、marker 1件を検証 |
| 反復・mobile panel・警告干渉が未検証 | 10回反復とmobile 3シナリオを追加し全PASS |

旧`#layer-toggle-btn` / `#legend-toggle-btn`も、現行UIの
`#mbc-tab-btn-layer` / `#mbc-tab-btn-legend`へ修正済み。凡例は実タブを開いた状態で
`toBeVisible()`、OFF時は`toBeHidden()`を検証するため、前回の非表示DOM型
false positiveも解消した。

## 独立実行結果

```text
Python compileall: PASS
node --check jartic-traffic-layer.js: PASS
node --check map-overlay-ui.js: PASS
pytest tests/test_jartic_traffic_service.py: 22 passed
Playwright e2e/jartic-traffic-layer.spec.js: 27 passed
```

27件には次の強化検証が含まれ、個別に全PASSした。

- statusとSVG実fillの1:1一致、3カテゴリ同時描画
- デバウンス後の追加APIちょうど1回
- Abort＋tokenによる後着Aの破棄
- 10回ON/OFF後のOFF中通信停止、marker非重複、listener非増殖、
  JARTIC console error/page errorなし
- 津波警告中のtoggle・凡例操作と横スクロールなし
- 情報パネル最大化時の凡例排他非表示、ハンドル操作、横スクロールなし
- popup paneが津波警告バナーより低いz-index

## 画像目視結果

次を再生成・目視確認した。

- `test-results/jartic-traffic-desktop-off.png`
- `test-results/jartic-traffic-desktop.png`
- `test-results/jartic-traffic-mobile.png`
- `test-results/jartic-traffic-mobile-panel-max.png`
- `test-results/jartic-traffic-popup.png`

390×844の最大化画像では、津波警報バナーが上端に可視、情報パネルのhandleとタブが
操作可能な位置にあり、交通量凡例は情報タブと排他で非表示、横はみ出しなし。
popup画像ではpopupが津波警告および下部UIより不適切に前面へ出ていない。

## 実API再確認

```text
GET /api/jartic/traffic?bbox=139.55,35.50,139.95,35.85
status=ok
items=23
updated_at=2026-07-25T12:43:47.058438+09:00
```

再検証時点の分類分布:

```text
very_high: 2
high:      17
normal:    2
low:       0
very_low:  2
unknown:   0
```

実データで4カテゴリ、方向別status/labelを再確認した。時刻により前回分布
（very_high 3 / high 16）から変動したが、分類動作は正常。

## 回帰再確認

指定代表セットを再実行し、前回と完全に同じ結果。

```text
30 passed / 9 failed
```

- `smoke.spec.js`: 7 passed
- `hazard-state-consistency.spec.js`: 13 passed
- `evacuation-ui.spec.js`: 6 passed
- `live-road-traffic-layer.spec.js`: 2 passed / 8 failed
- `shelter-marker-image.spec.js`: 1 passed / 1 failed

LIVE 8失敗は現行DOMにない`#live-road-traffic-card` /
`#live-train-card`を参照する既知の陳腐化selector、shelter 1失敗は期待SVG 7件に対し
4件の既知失敗。失敗内容・件数は前回と一致し、今回修正ファイルは
`frontend/js/jartic-traffic-layer.js`と`e2e/jartic-traffic-layer.spec.js`だけなので、
新規回帰ではない。

## 再検証時の変更

CODEXによるproduction/E2E修正なし。本節を検証レポートへ追記したのみ。

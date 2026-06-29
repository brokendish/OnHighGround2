# CODEX用検証指示書

## 検証対象

Phase 7-B.2
JARTIC交通量観測点レイヤー MVP

Claude実装後の検証を行う。

目的は、OnHighGround2本体の詳細地図上でJARTIC交通量観測点が適切に表示されることを確認すること。

今回のMVPでは、道路交通レイヤーの完成や渋滞判定は行わない。
JARTIC交通量APIは道路線データではなく、交通量観測点の点データとして扱う。

## 最重要確認事項

JARTICへの問い合わせにより、以下が確認済み。

```text
交通量API仕様書には x-api-key 認証方式の記載がある
しかし現時点では利用者ごとのAPIキー発行・配布の仕組みはない
APIキー取得手続きや申請は不要
本APIは一般公開型のオープンデータAPIとして提供されている
```

そのため、今回の検証では以下を最重要項目とする。

```text
JARTIC_API_KEY 未設定でも取得処理が実行されること
APIキー未設定を理由に unavailable にならないこと
取得失敗時のみ unavailable / error になること
```

既存コードに以下が残っていないか確認する。

```text
JARTIC_API_KEY が必須
JARTIC_API_KEY 未設定時に即 unavailable
x-api-key ヘッダが必須
APIキー未設定時にJARTIC取得処理をスキップ
```

## 検証方針

原則として検証を主目的とする。
明らかな軽微不具合がある場合のみ、最小限の修正を行ってよい。

ただし、以下のような仕様変更は行わない。

```text
DB追加
PostgreSQL追加
履歴保存追加
変化率算出追加
道路名推定追加
OSM最近傍マッチング追加
/live 本格表示追加
ランキング追加
渋滞・混雑判定追加
```

## 今回確認するべき仕様

### Backend

以下を確認する。

```text
APIキーなしでJARTIC交通量APIを取得しようとする
取得成功時 status: ok を返す
取得失敗時 status: unavailable または error を返す
正規化JSONを返す
座標のないデータは除外される
0台は欠損扱いされない
欠損値は null として扱われる
最新スナップショットのみ保存される
履歴ファイルが増えない
DBを使用していない
```

想定キャッシュ先:

```text
data_runtime/backend/jartic/latest_traffic.json
data_runtime/backend/jartic/manifest.json
```

実装上のパスが異なる場合は、既存設計との整合性を確認する。

### Frontend

OnHighGround2本体側で以下を確認する。

```text
交通量観測点トグルが存在する
初期状態はOFF
ONにすると観測点マーカーが表示される
OFFにすると観測点マーカーが消える
現在の地図表示範囲BBOX内の観測点のみ表示される
BBOX外の観測点は表示されない
マーカークリックでポップアップが表示される
ポップアップに交通量情報が表示される
```

### ポップアップ表示

以下の項目が表示されること。

```text
交通量観測点

上り: xxx台
下り: xxx台
合計: xxx台

小型: xxx台
大型: xxx台
観測時刻: yyyy-mm-dd hh:mm
観測点コード: xxxx
出典: JARTIC / 国土交通省交通量API
```

取得データ上で判別できる場合のみ、以下が表示されていてもよい。

```text
集計単位
データ種別
```

欠損値は `不明` または `-` 表示でよい。
ただし、`0` は `0台` と表示されること。

## 表示文言の検証

今回のMVPでは、以下の文言を使っていないことを確認する。

```text
渋滞
混雑
通行止め
規制
事故
異常
危険
```

JARTIC交通量APIは交通量観測点データであり、渋滞・規制・事故情報ではない。
UI、ポップアップ、ログ、APIレスポンスのユーザー向け文言にこれらの断定表現がないか確認する。

## `/live` 側への影響確認

今回の本格表示対象は OnHighGround2 本体側であり、`/live` ではない。

以下を確認する。

```text
/live 側に不要な交通量観測点UIが追加されていない
/live の既存レイヤーが壊れていない
/live の鉄道・道路・地震・雨雲・キキクル表示に影響がない
```

## 既存機能への回帰確認

最低限、以下に影響がないことを確認する。

```text
OnHighGround2本体の初期表示
現在地表示
避難ルート表示
安全地点表示
情報パネル
津波警告UI
気象カード
既存レイヤートグル
/live 初期表示
```

## 推奨検証手順

### 1. 静的確認

```bash
grep -R "JARTIC_API_KEY" -n .
grep -R "x-api-key" -n .
grep -R "渋滞\|混雑\|通行止め\|規制\|事故\|異常\|危険" -n frontend backend
```

確認ポイント:

```text
JARTIC_API_KEY 未設定で即 unavailable になっていないか
x-api-key 必須実装になっていないか
交通量データを渋滞・規制として表示していないか
```

### 2. Backend構文・単体確認

既存プロジェクトの手順に合わせて実行する。

例:

```bash
python -m py_compile backend/*.py
pytest
```

または既存テスト構成に合わせる。

確認ポイント:

```text
Backendが起動する
JARTIC交通量APIエンドポイントがHTTP 200を返す
APIキー未設定でも取得処理が走る
status が ok / unavailable のいずれかで返る
レスポンス形式がfrontend想定と一致する
```

### 3. APIキー未設定テスト

明示的に `JARTIC_API_KEY` を未設定にした状態で確認する。

```bash
unset JARTIC_API_KEY
```

Docker compose または backend 起動環境でも、環境変数を渡していない状態を確認する。

期待結果:

```text
APIキー未設定を理由に unavailable にならない
JARTIC API取得が試行される
通信またはAPI側の問題がなければ status: ok
通信失敗時のみ status: unavailable / error
```

### 4. キャッシュ確認

以下を確認する。

```text
latest_traffic.json が作成または更新される
manifest.json が作成または更新される
日付別・時刻別の履歴ファイルが大量作成されない
DBファイルやPostgreSQL依存が追加されていない
```

確認例:

```bash
find data_runtime/backend/jartic -maxdepth 2 -type f -print
```

期待結果:

```text
最新スナップショット中心の構成
履歴保存なし
```

### 5. Docker起動確認

既存の手順に合わせて確認する。

例:

```bash
docker compose build
docker compose up -d
docker compose ps
```

確認ポイント:

```text
backend healthy
frontend 起動
martin 等の既存サービスに悪影響なし
新規DBコンテナが追加されていない
```

### 6. Frontend表示確認

OnHighGround2本体をブラウザで開く。

確認項目:

```text
交通量観測点トグルが表示される
初期状態はOFF
ONでマーカー表示
OFFでマーカー非表示
地図移動後、表示範囲に応じてマーカー表示が変わる
マーカークリックでポップアップ表示
```

ポップアップ確認:

```text
交通量観測点
上り
下り
合計
小型
大型
観測時刻
観測点コード
出典: JARTIC / 国土交通省交通量API
```

### 7. BBOX表示確認

テストデータまたは実データで、以下を確認する。

```text
表示範囲内の観測点は表示される
表示範囲外の観測点は表示されない
地図を移動すると表示対象が更新される
全国全件が一度に大量表示されない
```

### 8. E2Eテスト

可能であれば、専用E2Eを追加する。

候補ファイル:

```text
e2e/jartic-traffic-observation-layer.spec.js
```

テスト項目:

```text
初期状態で交通量観測点マーカーが表示されない
トグルONでBBOX内マーカーが表示される
トグルOFFでマーカーが消える
マーカークリックでポップアップが出る
ポップアップに基本項目が表示される
0台が0台として表示される
欠損値が不明または-として表示される
BBOX外の観測点が表示されない
/live に交通量観測点UIが出ない
```

## PASS条件

以下をすべて満たせば PASS。

```text
JARTIC_API_KEY 未設定でも取得処理が実行される
APIキー未設定を理由に unavailable にならない
取得成功時 status: ok
取得失敗時のみ unavailable / error
正規化JSONが返る
0台が欠損扱いされない
座標不正データが除外される
最新スナップショットのみ保存される
DB・履歴・変化率が追加されていない
OnHighGround2本体に交通量観測点トグルがある
初期状態OFF
ONでBBOX内マーカー表示
OFFでマーカー非表示
ポップアップに交通量情報が表示される
表示文言が交通量に留まっている
渋滞・規制・通行止め等と断定していない
/live に不要な影響がない
既存主要機能が壊れていない
```

## FAIL条件

以下のいずれかがあれば FAIL。

```text
JARTIC_API_KEY 未設定で unavailable になる
APIキーがないと取得処理を実行しない
x-api-key 必須実装になっている
DBやPostgreSQLが追加されている
履歴ファイルを保存している
変化率や通常比を算出している
道路名推定をしている
OSM最近傍マッチングをしている
交通量を渋滞・混雑・規制・通行止めとして表示している
全国全件マーカーを常時大量表示している
BBOX外の観測点が表示される
ポップアップに必要項目が出ない
/live 側の既存表示が壊れている
OnHighGround2本体の既存主要機能が壊れている
```

## 検証レポート作成先

以下に検証レポートを作成する。

```text
tasks/jartic_traffic_observation_layer_mvp_codex_verification.md
```

## レポートに記載する内容

```text
判定: PASS / PASS with notes / FAIL
検証日時
検証環境
対象ブランチ / コミット
変更ファイル一覧
APIキー不要対応の確認結果
Backend API確認結果
キャッシュ確認結果
Frontend表示確認結果
BBOX表示確認結果
ポップアップ確認結果
/live 影響確認結果
既存機能回帰確認結果
実行したコマンド
テスト結果
スクリーンショット保存先
発見した問題
必要な修正
次に確認すべきこと
```

## 注意事項

今回のMVPは「交通量観測点が地図上でどう見えるか」を確認するための薄い実装である。

過剰に作り込まないこと。
特に、道路名推定・履歴保存・通常比・ランキング化は今回の対象外。

まずは実物を見て、OnHighGround2本体に残す価値があるか、`/live` に展開する価値があるかを判断できる状態にする。

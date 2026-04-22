# Claude Code Instructions — Pre-Field-Test Parameter Tuning Suite for OnHighGround

> このドキュメントは **Claude Code** に渡すための指示書です。
> 目的:**フィールドテスト前に、navigation パラメータの妥当範囲を机上で絞り込む**ことで、貴重なフィールドテスト機会を「探索」ではなく「最終確認・微調整」に使えるようにする。

---

## How to use this file with Claude Code

1. このファイルをプロジェクトルートに **`CLAUDE_testing.md`** として配置する
   - **既存の `CLAUDE.md`(tile pipeline 用)は上書きしない**。共存させる
2. Claude Code セッション開始時の最初のプロンプト例:
   > `CLAUDE_testing.md` の指示に従ってタスクを進めてください。まず "Pre-implementation planning step" を実行し、プランを提示してから承認を待ってください。
3. Plan が提示されたら内容を確認・承認してから実装に進ませる
4. 実装は Implementation order に沿ってセクションごとにコミットを分ける
5. セッションを跨ぐ場合は、新セッションでもこのファイルを再参照させることでコンテキストを復元できる
6. 既存の `CLAUDE.md`(tile pipeline)に書かれた原則(スコープ遵守・Do NOT 尊重・Pre-implementation planning)は本指示書にも適用される

---

## Background / なぜやるか

OnHighGround は災害避難ナビゲーションシステム。フィールドテストは出勤時のみ可能で、1日1回しかチャンスがない。

本日のフィールドテストで観測された現象:
- 目的地に到達しても arrival イベントが発火しない(目的地スルー)
- 経路から逸脱しても再ルートが走らない

**重要な気づき:** これらは「バグ」ではなく、以下2つのパラメータが**まだ妥当な値に決まっていない**ことの症状である。

- `arrival_radius` — 目的地到着判定の半径
- `reroute_threshold` — 再ルート発火のための逸脱距離閾値

つまり本来必要なのは:
1. 合成 GPS トレースによるパラメータスイープで**候補値の範囲を絞り込む**(机上)
2. 絞り込まれた候補を**実地で微調整する**(フィールド)

本指示書はこの「1. 机上での絞り込み」の環境を構築するためのもの。

---

## Goal

以下が達成された状態を目指す:

- `pytest tests/navigation/` 実行 → パラメータスイープレポートが自動生成される
- レポートを見ると `arrival_radius` と `reroute_threshold` の **安全域・危険域・ノイズ感度域** が一目で分かる
- フィールドテスト当日にすべきことが「狭い範囲の検証」にまで絞られている

---

## Scope

### Do
- GPS トレースリプレイハーネスの新規実装
- 合成トレース生成ユーティリティ(直線接近・通過・逸脱・周回)
- GPS ノイズシミュレーション(Gaussian ノイズ注入)
- パラメータスイープ実行フレームワーク
- 閾値推奨レポート自動生成
- 過去・今後のフィールドテスト記録を regression fixture として保存する仕組み
- フィールドテスト当日の計測プロトコル文書

### Do NOT
- UI の再設計や新機能追加
- OSRM プロファイルや routing アルゴリズムの変更
- safe location 選定ロジックの変更
- 「目的地スルー」や「再ルート不可」を**コードのバグとして修正しようとすること**(これらはパラメータ次第で消える症状である)
- パラメータのハードコード値を勝手に変更すること(本タスクの成果物はあくまで「推奨範囲」であり、決定ではない)

---

## Pre-implementation planning step(必須)

実装に入る前に以下を調査し、プランを出力してユーザーの承認を得る。

1. **対象モジュールの特定**
   - navigation state machine の場所(ファイルパス・関数名)
   - arrival 判定ロジック — 現在の判定基準と閾値、ハードコードか設定可能か
   - reroute トリガ — 発火条件、現在の閾値
   - OSRM client ラッパーの場所
2. **既存テストの棚卸し**
   - `pytest --collect-only` で既存テストを確認
   - navigation 周りに既存テストがあれば構造を流用
3. **GPS 入力の現状**
   - 本番コードが GPS をどこから受け取るか(WebSocket / HTTP / ブラウザ Geolocation など)
   - テスト注入点として最も影響の少ない箇所
4. **パラメータ設定の現状**
   - `arrival_radius` / `reroute_threshold` が定数なのか、設定ファイルなのか、環境変数なのか
   - テスト実行時に動的に差し替える方法

プラン出力フォーマット:

```
## Plan
### Target modules
- <path>:<function> — 役割と現在の閾値
### Existing tests
- <path> — 概要
### GPS injection point
- <候補>:<理由>
### Parameter injection mechanism
- 現状: <定数/config/env>
- テスト時の差し替え方法: <案>
### Implementation order
1. ...
```

---

## Pre-checks

実装開始前に確認:
- [ ] `pytest` が使える(なければ `pip install pytest pytest-asyncio numpy` を `requirements-dev.txt` に追加)
- [ ] `docker-compose up` で OSRM コンテナが起動する
- [ ] `data/test_fixtures/` が存在(なければ作成)
- [ ] レポート出力先 `reports/parameter_sweep/` を作成

---

## Test categories

### 1. GPS trace replay harness(最優先・基盤)

**目的:** 外部 GPS の代わりに記録 or 合成したトレースを navigation engine に流し込めるようにする。全てのテストの基盤。

**要件:**
- 入力: GeoJSON LineString(時間情報付き)or CSV(`timestamp, lat, lon, accuracy, speed`)
- 出力: navigation state の時系列イベントログ(arrival / deviation / reroute / error / route_update)
- pytest から呼べる interface: `replay_trace(engine, trace, params) -> EventLog`
- 仮想時間で高速実行(実時間待ち禁止)
- パラメータ(`arrival_radius`, `reroute_threshold` 等)をテスト実行時に差し替え可能

**非要件:**
- UI 連携
- リアルタイム再生

---

### 2. Synthetic trace generators(スイープの弾薬)

`tests/navigation/fixtures/trace_generators.py` に以下を実装:

| 関数 | 用途 |
|------|------|
| `straight_approach(start, dest, speed, step_sec)` | 直線で目的地に近づくトレース |
| `overshoot(start, dest, overshoot_m, speed, step_sec)` | 目的地を指定距離通り過ぎるトレース |
| `circle_around(center, radius_m, duration_sec)` | 目的地周辺を周回(到着判定の重複発火チェック用) |
| `deviate_from_route(route, deviation_m, return_to_route: bool)` | 経路から指定距離逸脱、復帰有無を選択可 |
| `add_gaussian_noise(trace, sigma_m, accuracy_field=True)` | 既存トレースに Gaussian ノイズを乗せる。accuracy 値も対応して更新 |
| `add_gps_loss(trace, start_sec, duration_sec)` | GPS 信号喪失を再現(トンネル想定) |

**ノイズ注入の注意点:**
- σ は GPS accuracy の分布を反映すべき。都市部の典型: 5〜15m。オフィス街や地下近傍: 20〜30m
- 同じ seed で再現可能にする(`numpy.random.default_rng(seed)`)

---

### 3. Parameter sweep — arrival_radius

`tests/navigation/test_arrival_sweep.py`

**固定トレース(複数):**
- T1: 目的地に正確に到達して停止
- T2: 目的地を 10m 通過
- T3: 目的地を 30m 通過(今日発生した現象の再現)
- T4: 目的地手前 5m で停止
- T5: 目的地周辺を周回

**スイープ軸:**
- `arrival_radius` ∈ {5, 8, 10, 12, 15, 20, 25, 30, 40, 50} m
- ノイズ σ ∈ {0, 5, 10, 15, 20} m(各 σ で 10 試行)

**記録項目(各組み合わせごと):**
- arrival が発火したか(Y/N)
- 発火時点の目的地からの距離
- 重複発火の有無(周回ケース)
- 誤発火の有無(目的地接近前に発火)

**出力:** `reports/parameter_sweep/arrival.md`(下記レポート仕様参照)

---

### 4. Parameter sweep — reroute_threshold

`tests/navigation/test_reroute_sweep.py`

**固定トレース:**
- T1: 経路通りに走行(false positive 検出用)
- T2: 経路から 20m 逸脱して復帰
- T3: 経路から 40m 逸脱して復帰
- T4: 経路から 75m 逸脱して離脱
- T5: 経路から 150m 逸脱して離脱
- T6: 経路上をジッター走行(accuracy σ=10m、実際には逸脱なし)
- T7: GPS ロスト後、経路から 50m 離れた位置に復帰

**スイープ軸:**
- `reroute_threshold` ∈ {15, 20, 25, 30, 40, 50, 75, 100, 150} m
- ノイズ σ ∈ {0, 5, 10, 15, 20} m(各 10 試行)

**記録項目:**
- reroute 発火タイミング(経路逸脱後、何秒・何メートルで発火したか)
- ジッターケースでの false positive 率
- 連続発火(デバウンス不備)の検出
- OSRM 再問い合わせが成功/失敗したか

**出力:** `reports/parameter_sweep/reroute.md`

---

### 5. Interaction check — パラメータ間の依存関係

`tests/navigation/test_interaction.py`

特に確認したい相互作用:
- `reroute_threshold ≤ arrival_radius` の状況 → 目的地接近時に逸脱判定が暴発する可能性
- 両パラメータを同時スイープした 2D マトリクスを生成
- 「両方安全」「片方だけ安全」「両方危険」のゾーニング

**出力:** `reports/parameter_sweep/interaction.md`(2D ヒートマップ or テーブル)

---

### 6. Threshold recommendation report(最終成果物)

全スイープ結果を統合した推奨レポートを `reports/parameter_sweep/RECOMMENDATION.md` に自動生成。

**必要な章:**
1. **Safe zone** — ノイズ σ=15m までの全試行で期待動作する閾値範囲
2. **Risk zone: false negative** — 検出漏れ(arrival / reroute が発火しない)が起きる範囲
3. **Risk zone: false positive** — 誤発火が起きる範囲
4. **Sensitive zone** — ノイズ量で挙動が変わる範囲(フィールドで要検証)
5. **Recommended starting values** — フィールドテストで試す初期値の提案(1〜3パターン)
6. **What field test must answer** — 机上で決められなかった項目のリスト

この章6が次セクション(7)の入力になる。

---

### 7. Field test day protocol(文書)

`docs/field_test_protocol.md` を作成。内容:

- **当日の計測項目**
  - GPS accuracy の1秒ごとの記録
  - 目的地周辺 50m 圏内での実測誤差
  - 逸脱発生地点の座標と復帰までの軌跡
- **事前に設定すべき値**
  - (6) のレポートから、当日試す `arrival_radius` / `reroute_threshold` の候補
  - 試行順序(1回の通勤で複数パターン試す場合)
- **記録フォーマット**
  - GPS トレースを JSONL or CSV で保存するスキーマ
  - 発生したイベント(到着・逸脱・reroute・失敗)のタイムスタンプ付きログ
- **帰宅後のルーティン**
  - 記録したトレースを `data/test_fixtures/gps_traces/field_tests/YYYY-MM-DD/` に保存
  - メタデータ YAML を添付(次セクション参照)
  - regression テスト(8)が自動的にそのトレースを拾うこと

---

### 8. Regression fixture — 過去のフィールドテスト

実地で発生した挙動を二度と現場で繰り返さないためのセーフティネット。

**構造:**
```
data/test_fixtures/gps_traces/field_tests/
  2026-04-21/
    trace.geojson
    meta.yaml
```

**meta.yaml の例:**
```yaml
date: 2026-04-21
route: home_to_station
params_tested:
  arrival_radius: 10
  reroute_threshold: 30
observed:
  - destination_overshoot
  - reroute_not_fired
notes: |
  目的地半径と再ルート閾値の妥当性を見るテスト。
  現在の値では両方発火せず。
```

**`tests/navigation/test_regression.py`** で `field_tests/*/` を全走査し、replay 結果が meta.yaml の期待と一致するか検証(期待値は手動で埋める運用)。

---

## Implementation order

1. GPS trace replay harness
2. 合成トレース生成ユーティリティ
3. arrival_radius スイープ
4. reroute_threshold スイープ
5. 相互作用マトリクス
6. 推奨レポート自動生成
7. field_test_protocol.md の起草
8. regression fixture 機構(空でも仕組みだけ)
9. `README.md` or `docs/testing.md` に実行手順追記

各ステップごとにコミットを分ける。

---

## Success criteria

- [ ] `pytest tests/navigation/` で全スイープが実行される(仮想時間で高速実行、実機 GPS 不要)
- [ ] `reports/parameter_sweep/RECOMMENDATION.md` が生成される
- [ ] レポートを見て `arrival_radius` の推奨範囲が具体的な数値で示されている
- [ ] レポートを見て `reroute_threshold` の推奨範囲が具体的な数値で示されている
- [ ] `docs/field_test_protocol.md` を見れば、次回フィールドテスト当日に何をすればいいかが明確
- [ ] 次回のフィールドテスト結果を fixture として保存する手順が明文化されている

---

## Out of scope(今回やらないこと)

- パラメータの最終決定(これはフィールドテストの結果で決める)
- UI のスナップショットテスト
- tile pipeline のテスト
- パフォーマンステスト
- 実機ブラウザでの end-to-end テスト
- 経路探索アルゴリズムの変更

---

## Reporting

実装完了後、以下を報告:
1. 追加・変更したファイル一覧
2. `RECOMMENDATION.md` の内容サマリ
3. 推奨閾値レンジ(現在のデフォルト値と比較)
4. 実装中に気づいた潜在的な問題点(本タスクでは直さず記録)
5. 次回フィールドテストで検証すべき項目のリスト

---

## Notes for Claude Code

- スイープのパラメータ範囲は指示書内の値を**初期値**として使い、実装後にユーザーと調整する余地を残す(レンジを config ファイル化して簡単に変更できるように)
- ノイズ seed は固定して結果を再現可能にする
- レポート生成は失敗しても他のテストを止めないこと(`pytest` hook か post-run スクリプトで)
- 現在のハードコード値(`arrival_radius` / `reroute_threshold` の今の値)は**勝手に変更しない**。スイープはあくまで「候補値」を調べるだけ
- 不明点・判断迷いが出たらユーザーに確認する(特にモジュール配置・命名規約・既存テスト構造との整合)
- 各フェーズの実装後、必ず `pytest` が通ることを確認してからコミットする(壊れたままコミットしない)
- 既存 `CLAUDE.md`(tile pipeline 用)と本指示書は独立したタスク。ファイル・ディレクトリが競合しないよう配置に注意

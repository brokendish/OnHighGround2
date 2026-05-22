# OnHighGround2 キキクル Phase 1-B / 1-C Claude Code 実装指示書

## 目的

Phase 1で実装済みの「浸水キキクル」表示基盤を拡張し、以下を順番に追加する。

1. Phase 1-B: 洪水キキクル表示レイヤー追加
2. Phase 1-C: 土砂キキクル表示レイヤー追加

今回は **表示レイヤー追加まで** とし、現在地要約、目的地要約、ルート危険度スコア、ナビ警告にはまだ組み込まない。

## 前提

既存の Phase 1 実装では、以下が完了している。

- `frontend/js/kikikuru-layer.js` に浸水キキクルの取得・表示・状態管理がある。
- JMA `targetTimes.json` を取得し、最新 validtime/member を使ってタイル URL を構築している。
- 情報タブ内にキキクルカードがあり、浸水/洪水/土砂のトグル枠が存在する。
- 浸水トグルと地図ショートカットボタンの active 状態が同期している。
- 凡例タブにキキクル凡例が追加されている。
- `取得不可` と `表示なし` を混同しない設計になっている。
- `e2e/kikikuru-layer.spec.js` が追加済み。

## 実装方針

既存の浸水キキクル実装をベースに、設定駆動で以下3種を扱える構造へ整理する。

- `inund`: 浸水キキクル
- `flood`: 洪水キキクル
- `land`: 土砂キキクル

既存コードが浸水専用の分岐や固定 DOM ID に寄りすぎている場合は、最小限のリファクタリングで共通化する。

ただし、今回の主目的は洪水・土砂の追加であり、過剰な全面改修は避ける。

## JMAタイル種別

Phase 1 の検証で `targetTimes.json` の `elements` に以下が含まれることを確認済み。

- `inund`
- `flood_mesh`
- `flood`
- `land`

実装では以下の優先で扱う。

### 浸水

既存どおり `surf/inund` を使う。

### 洪水

まず `flood_mesh` を第一候補にする。

ただし、環境によって `flood_mesh` が利用できない場合に備え、内部設定として `flood` へフォールバックできる余地を残す。

最初から複雑な自動フォールバックを作る必要はないが、設定値を1か所で変更できるようにする。

### 土砂

`land` を使う。

## タイル URL 方針

既存の浸水キキクルと同じ構築ルールを踏襲する。

```text
https://www.jma.go.jp/bosai/jmatile/data/risk/{basetime}/{member}/{validtime}/surf/{element}/{z}/{x}/{y}.png
```

実装時は既存 Phase 1 の URL 生成ロジックを流用し、`element` 部分だけをレイヤー種別ごとに差し替える。

## UI要件

### 情報タブ

キキクルカードに以下3トグルを並べる。

- 浸水
- 洪水
- 土砂

すでに枠がある場合は、洪水・土砂のトグルを有効化する。

各トグルの状態は個別に保持する。

### 地図ショートカット

既存の地図上キキクルショートカットが浸水専用の場合は、以下のどちらかで対応する。

推奨:
- 情報タブの3トグルを主操作にする。
- 地図ショートカットは「キキクルカードを開く/注目させる」または「浸水キキクルON/OFF」の既存挙動を維持する。

避けること:
- 地図上にボタンを増やしすぎてUIを重くする。
- 既存の雨量・ハザード・避難所ボタンと競合する。

今回は、無理に地図ショートカットを3種類に増やさなくてよい。

### 取得状態表示

キキクルカード内で3種それぞれの状態が分かるようにする。

```text
浸水: 正常 / 取得不可 / OFF
洪水: 正常 / 取得不可 / OFF
土砂: 正常 / 取得不可 / OFF
```

可能であれば validtime は共通表示にまとめる。

```text
更新: 5/22 20:30 時点
```

ただし、種別ごとに取得失敗があり得るため、状態は個別に出す。

### 凡例

凡例タブの `キキクル（現在の危険度）` を3種対応にする。

- 浸水キキクル
- 洪水キキクル
- 土砂キキクル

重要:
- `表示なし` は「危険度が表示されていない/タイル上に色がない」状態。
- `取得不可` は「JMA時刻またはタイル取得に失敗した」状態。
- この2つを混同しない。

## レイヤー制御要件

3種の TileLayer を独立して管理する。

- 浸水 ON: inund TileLayer 追加
- 洪水 ON: flood/flood_mesh TileLayer 追加
- 土砂 ON: land TileLayer 追加

OFF時は対象レイヤーだけ削除する。

複数ONを許可する。

レイヤーの重なり順は以下を推奨する。

1. 固定ハザードレイヤー
2. キキクルレイヤー
3. ルート線
4. 現在地・目的地・避難所マーカー

キキクルがルート線やマーカーを潰さないよう、opacity を調整する。

推奨初期値:

```js
opacity: 0.60
```

視認性が強すぎる場合は `0.45〜0.55` 程度に落としてよい。

## エラー処理

以下を守る。

- `targetTimes.json` 取得失敗時は `取得不可` 表示。
- 取得不可を危険度なしとして扱わない。
- 失敗時に既存表示済みレイヤーが stale になる場合は、状態表示に `更新失敗` または `取得不可` を出す。
- console error / pageerror を出さない。
- 1種の取得失敗で他のキキクルレイヤーまで巻き込まない。

## キャッシュ・更新

Phase 1 の設計を踏襲する。

- 同一 validtime の再取得を無駄に繰り返さない。
- トグルON時に最新 targetTimes を確認する。
- 更新時刻が変わった場合は対象レイヤーのURLを更新する。
- 取得できない場合は stale 表示を検討するが、今回は最低限 `取得不可` が出ればよい。

## 既存機能に触れない範囲

今回は以下には組み込まない。

- `/api/route-risk`
- `navigation.js` の reroute 判定
- ルート危険度スコア
- 現在地周辺リスク要約
- 目的地周辺リスク要約
- ナビ中の迂回提案

固定ハザード、雨量カード、避難所、地震、潮位、月齢UIを壊さないこと。

## 実装候補ファイル

主対象:

- `frontend/js/kikikuru-layer.js`
- `frontend/index.html`
- `frontend/js/map-overlay-ui.js`
- `e2e/kikikuru-layer.spec.js`

必要に応じてのみ:

- `frontend/js/location-info-panel.js`
- `frontend/js/hazard-layers.js`

## 期待する完成状態

- 情報タブで浸水・洪水・土砂キキクルを個別にON/OFFできる。
- 洪水ONで JMA risk tile の洪水系タイルが表示される。
- 土砂ONで JMA risk tile の土砂系タイルが表示される。
- 3種同時ONでもJSエラーが出ない。
- 取得状態が種別ごとに分かる。
- 凡例が3種対応になっている。
- モバイル幅で横スクロールやレイアウト崩れが起きない。
- 既存の浸水キキクル動作が退行しない。

## 実装後に実行する確認

```bash
node --check frontend/js/kikikuru-layer.js
node --check frontend/js/map-overlay-ui.js
node --check e2e/kikikuru-layer.spec.js
python3 -m compileall backend/app backend/main.py
docker compose up -d --build
curl -I http://127.0.0.1:8080
curl -s http://127.0.0.1:8000/health
npx playwright test e2e/kikikuru-layer.spec.js
```

可能なら代表回帰:

```bash
npx playwright test e2e/weather-rain-radar-card.spec.js e2e/hazard-state-consistency.spec.js
```

`e2e/info-tab-card-ui.spec.js` は既存の文言ズレが報告済みのため、今回修正対象に含めるかは判断する。キキクルと無関係な失敗であれば notes に切り分ける。

## 成果物

以下を作成または更新する。

- 実装コード
- E2E
- 必要であれば `tasks/kikikuru_phase1b_1c_implementation_notes.md`

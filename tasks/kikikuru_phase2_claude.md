# キキクル Phase 2 実装指示書

## 目的

キキクル Phase1 で実装済みの

- 浸水 (`inund`)
- 洪水 (`flood_mesh`)
- 土砂 (`land`)

のリアルタイム TileLayer を利用し、

- 現在地周辺
- 目的地周辺

の危険度要約を情報タブへ表示する。

目的は「現在どこが危険か」をユーザーへ即時伝達することであり、
ルート危険度スコアやナビ制御にはまだ反映しない。

---

# 実装方針

## 最重要

絶対にやってはいけないこと:

- unknown を safe 扱い
- 取得失敗を危険度なし扱い
- JMA fetch 失敗で stale 情報を残す
- ルート危険度スコアへ混入
- ナビ reroute へ影響

Phase2 は「要約表示のみ」。

---

# 実装内容

## 1. 現在地危険度要約

情報タブへ追加。

例:

- 現在地周辺:
  - 浸水: 注意
  - 洪水: 危険
  - 土砂: なし

または短縮:

- 現在地周辺: 洪水危険

---

## 2. 目的地危険度要約

目的地設定済みの場合のみ表示。

例:

- 目的地周辺: 危険度なし
- 目的地周辺: 土砂注意

---

## 3. サンプリング

現在地/目的地周辺を少半径で確認。

推奨:

- 半径: 100〜250m
- center + 周辺数点

Tile の pixel color を確認して判定。

---

## 4. 危険度ルール

最低限:

- なし
- 注意
- 危険
- 取得不可
- 確認中

JMA 色と完全一致しない unknown は
必ず取得不可寄り扱い。

---

## 5. UI

情報タブへカード追加。

例:

- キキクル現在地
- キキクル目的地

既存 weather/rain card と競合しないこと。

---

## 6. 更新

既存キキクル更新に同期。

追加 fetch を乱発しない。

targetTimes.json の共有 Promise を維持。

---

## 7. 状態管理

必須:

- stale timeout
- loading
- unavailable
- no-data

を分離。

---

## 8. パフォーマンス

禁止:

- 毎 frame 判定
- move イベント連続 fetch

推奨:

- throttle
- debounce
- map idle 後更新

---

## 9. ログ

debug 有効時のみ:

- sampled tile
- sampled color
- resolved status

を console 出力。

---

## 10. 非対象

今回やらない:

- reroute
- route score
- push alert
- auto warning
- SSE
- backend API
- DB保存

フロント完結。

---

# 完了条件

- 現在地要約表示
- 目的地要約表示
- 浸水/洪水/土砂対応
- 取得不可を safe 扱いしない
- モバイル崩れなし
- console error なし
- 既存回帰 PASS
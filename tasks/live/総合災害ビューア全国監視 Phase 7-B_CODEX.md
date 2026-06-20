# CODEX用検証指示書

# 総合災害ビューア全国監視 Phase 7-B

# 道路交通影響レイヤー MVP 検証

## 検証目的

Phase 7-B 道路交通影響レイヤー MVP を検証する。

今回の重点は以下。

* 国土交通省交通量API（JARTIC提供）から実データまたはモックデータを取得できること
* 交通量データを道路交通影響として正規化できること
* 交通量を通行止め・規制と断定していないこと
* 取得不可と交通影響なしを誤判定しないこと
* `/live` の既存災害・鉄道レイヤーを壊していないこと

---

## 対象

```text
/live
```

対象API:

```text
/api/live/road-traffic/summary
```

対象UI:

```text
🚗 道路交通影響
道路交通影響レイヤー
```

成果物:

```text
tasks/live/live_phase7b_road_traffic_impact_codex_verification.md
```

---

## 1. 起動確認

```bash
python3 -m compileall backend
docker compose ps
```

追加JSがある場合:

```bash
node --check frontend/js/live/live-road-traffic-layer.js
node --check frontend/js/live/live-road-traffic-panel.js
```

期待:

* backend healthy
* frontend up
* martin healthy
* 構文エラーなし

---

## 2. API疎通確認

```bash
curl -s "http://127.0.0.1:8000/api/live/road-traffic/summary" | jq .
```

期待:

* HTTP 200
* `status` が存在
* `items` が配列
* 取得不可時もアプリ例外なし

---

## 3. scope確認

以下を確認する。

```bash
curl -s "http://127.0.0.1:8000/api/live/road-traffic/summary?prefecture=東京都" | jq .
curl -s "http://127.0.0.1:8000/api/live/road-traffic/summary?prefecture=大阪府" | jq .
curl -s "http://127.0.0.1:8000/api/live/road-traffic/summary?lat=35.681236&lng=139.767125" | jq .
```

bbox対応がある場合:

```bash
curl -s "http://127.0.0.1:8000/api/live/road-traffic/summary?bbox=139.5,35.5,140.0,35.9" | jq .
```

期待:

* HTTP 200
* scope が保持される
* 東京都固定になっていない
* データなしと取得不可が分離される

---

## 4. 実データ取得確認

交通量API設定済みの場合、実データ取得を確認する。

記録:

```text
取得件数
観測地点数
道路名数
取得時間
最新観測時刻
```

注意:

5分値は観測から遅延して取得可能になるため、最新時刻が現在時刻と完全一致しなくてもよい。

---

## 5. 正規化確認

モックまたは実データで以下を確認する。

### normal

期待:

```text
status=normal
severity=0
```

### high

期待:

```text
status=high
status_label=交通量多い
severity=2
```

### very_high

期待:

```text
status=very_high
status_label=交通量非常に多い
severity=3
```

### low

期待:

```text
status=low
status_label=交通量少ない
severity=2
```

### very_low

期待:

```text
status=very_low
status_label=交通量極端に少ない
severity=3
```

### unavailable

期待:

```text
status=unavailable
items=[]
```

重要:

取得不可を「目立った交通影響なし」と表示してはいけない。

---

## 6. UIカード確認

`/live` を開く。

期待:

* 「🚗 道路交通影響」カードが表示される
* high / very_high / low / very_low が表示される
* normal は原則ランキング対象外
* 取得不可時は「道路交通量情報を取得できません」
* データなし時は「現在地周辺の道路交通量情報はありません」
* 交通量情報を通行止めと断定していない

---

## 7. 地図レイヤー確認

レイヤーパネルで「道路交通影響」をON/OFFする。

期待:

* ONで観測点マーカーが表示される
* OFFで消える
* 他レイヤーに影響しない

状態別:

```text
normal      緑/薄グレー
high        黄
very_high   赤
low         青
very_low    紫/濃青
unknown     グレー
```

重要:

凡例またはポップアップで、赤が「通行止め」ではなく「交通量非常に多い」と分かること。

---

## 8. ポップアップ確認

観測点をクリックする。

期待表示:

```text
道路名
方向
5分交通量
1時間交通量
状態
観測時刻
出典
注意書き
```

注意書き例:

```text
交通量APIの値から推定した交通影響であり、通行止め・規制を断定するものではありません。
```

`undefined` / `null` が表示されないこと。

---

## 9. キャッシュ確認

同一APIを連続実行する。

```bash
time curl -s "http://127.0.0.1:8000/api/live/road-traffic/summary?prefecture=東京都" > /tmp/road1.json
time curl -s "http://127.0.0.1:8000/api/live/road-traffic/summary?prefecture=東京都" > /tmp/road2.json
```

期待:

* 2回目が高速
* 毎回外部APIへフルアクセスしない
* TTLが効く

---

## 10. 障害時確認

APIキー無効、base URL不正、通信失敗などを模擬する。

期待:

* backend が落ちない
* APIが安全に応答
* `status=unavailable`
* stale cache がある場合は `stale=true`
* UIが「交通影響なし」と誤表示しない

---

## 11. モバイル確認

スマホ幅で確認。

期待:

* カードが崩れない
* レイヤー操作可能
* ポップアップが画面を破壊しない
* 横スクロールなし
* z-index競合なし

---

## 12. 既存回帰確認

最低限確認:

* `/live` 初期表示
* 地震一覧
* 津波警報UI
* 雨雲レイヤー
* キキクルレイヤー
* 高潮/潮位
* 日月カード
* 危険地域ランキング
* 河川情報リンク
* 鉄道運行影響カード
* 鉄道路線オーバーレイ
* 鉄道路線名・駅名ラベル
* レイヤーON/OFF全般

---

## 13. E2E追加推奨

追加候補:

```text
e2e/live-road-traffic-layer.spec.js
```

最低限:

```text
1. 道路交通影響カードが表示される
2. 取得不可とデータなしを分離する
3. high / very_high / low / very_low が表示される
4. レイヤーON/OFFできる
5. 観測点ポップアップが表示される
6. 通行止めと断定しない注意書きが出る
7. モバイルで横スクロールが出ない
```

---

## 14. 判定基準

### PASS

* APIが正常応答
* 交通量データを正規化できる
* 取得不可・データなし・交通影響なしを区別
* UIカード表示
* 地図レイヤーON/OFF
* 観測点マーカー表示
* ポップアップに注意書き表示
* 通行止め断定なし
* 既存 `/live` 回帰なし

### PASS with notes

* 実データ取得範囲が限定的
* 閾値が暫定
* 一部観測点に道路名不足
* 基準交通量比較は未実装
* 5分値の取得遅延あり

### FAIL

* `/live` が起動しない
* backendが落ちる
* 取得不可を交通影響なしと誤表示
* 交通量から通行止めと断定
* レイヤー操作で既存機能破壊
* モバイル操作不能

---

## 15. レポート作成

以下に作成する。

```text
tasks/live/live_phase7b_road_traffic_impact_codex_verification.md
```

記載内容:

```text
# Phase 7-B 道路交通影響レイヤー MVP CODEX検証

## 判定
PASS / PASS with notes / FAIL

## 検証環境
- date
- branch
- commit
- docker compose status

## 実施コマンド

## API確認

## 実データ取得確認

## 正規化確認

## UIカード確認

## 地図レイヤー確認

## ポップアップ確認

## キャッシュ確認

## モバイル確認

## 回帰確認

## 発見した問題

## 修正提案

## スクリーンショット

## 最終結論
```

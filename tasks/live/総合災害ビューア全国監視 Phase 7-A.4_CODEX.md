# CODEX用検証指示書

# 総合災害ビューア全国監視 Phase 7-A.4

# 鉄道路線名・駅名ラベル表示

## 検証目的

Phase 7-A.4 の鉄道路線名・駅名ラベル表示を検証する。

重点は以下。

* 鉄道運行影響レイヤーON時のみラベルが表示されること
* ズームレベルに応じて段階表示されること
* 障害路線・障害路線周辺駅が優先表示されること
* ラベル過多で地図が読めなくならないこと
* 既存の鉄道路線色・障害表現を壊していないこと
* 災害レイヤーの視認性を壊していないこと

---

## 対象

```text
/live
```

対象レイヤー:

```text
鉄道運行影響
```

対象データ候補:

```text
frontend/layers/railways/kanto_railways.geojson
frontend/layers/railways/kanto_stations.geojson
```

対象ファイル候補:

```text
frontend/js/live/live-train-osm-layer.js
frontend/js/live/live-train-label-layer.js
frontend/css/live/live-train.css
```

成果物:

```text
tasks/live/live_phase7a4_railway_labels_codex_verification.md
```

---

## 1. 起動確認

```bash
node --check frontend/js/live/live-train-osm-layer.js
python3 -m compileall backend
docker compose ps
```

追加JSがある場合:

```bash
node --check frontend/js/live/live-train-label-layer.js
```

期待:

* JS構文PASS
* backend compile PASS
* backend healthy
* frontend up
* martin healthy

---

## 2. E2E実行

```bash
npx playwright test e2e/live-basic.spec.js
npx playwright test e2e/live-train-layer.spec.js
npx playwright test e2e/live-train-osm-layer.spec.js
```

追加テストがある場合:

```bash
npx playwright test e2e/live-train-label-layer.spec.js
```

期待:

全PASS。

---

## 3. レイヤーON/OFF確認

### 鉄道レイヤーOFF

期待:

* 路線名ラベルなし
* 駅名ラベルなし
* 駅GeoJSONを不要にfetchしない

### 鉄道レイヤーON

期待:

* 路線名ラベルが表示される
* zoom条件を満たす場合のみ駅名ラベルが表示される
* OFFに戻すとラベルが消える

---

## 4. ズーム段階表示確認

以下のズームで確認する。

### zoom 8〜10

期待:

* 主要路線名のみ
* 駅名なし
* ラベル数が少ない

### zoom 11〜12

期待:

* 路線名が増える
* 障害路線名が優先表示される
* 駅名は原則なし、または主要駅のみ少数

### zoom 13〜14

期待:

* 路線名表示
* 主要駅名表示
* 障害路線周辺駅を優先

### zoom 15以上

期待:

* 駅名が増える
* ただし表示上限以内
* 地図が読める

---

## 5. ラベル数制御確認

確認:

* DOM要素が増えすぎない
* 表示範囲外のラベルが出ない
* 同一路線名が過剰に重複しない
* pan/zoomで古いラベルが残らない

目安:

```text
zoom 8〜10:
  route labels max 20
  station labels 0

zoom 11〜12:
  route labels max 40
  station labels max 10

zoom 13〜14:
  route labels max 60
  station labels max 40

zoom 15以上:
  route labels max 80
  station labels max 80
```

実装側で異なる上限を採用した場合は、レポートに記録する。

---

## 6. 障害路線優先確認

モックで障害路線を投入する。

例:

```text
中央線快速 delay
京王線 suspended
```

期待:

* 障害路線名ラベルが優先表示される
* ラベルに状態が分かる表示がある
* 例: 中央線快速 遅延
* 例: 京王線 見合わせ
* 障害路線が画面内にある場合、通常路線より優先される

---

## 7. 障害路線周辺駅優先確認

モック障害路線の近くで確認する。

期待:

* 障害路線近傍の駅名が優先表示される
* 遠い通常駅より優先される
* zoom 13以上で確認できる

厳密なトポロジ一致までは求めない。

---

## 8. 駅GeoJSON確認

```bash
curl -I http://127.0.0.1:8080/layers/railways/kanto_stations.geojson
```

期待:

* HTTP 200
* gzip有効ならなお良い
* JSONとして妥当
* 駅名プロパティがある
* platformのみの大量データではない

---

## 9. 表示品質確認

実画面で確認する。

確認地点例:

```text
新宿
東京
渋谷
池袋
品川
横浜
大宮
千葉
立川
調布
```

期待:

* 路線名が読める
* 駅名が読める
* 文字が小さすぎない
* ラベル背景が地図に馴染む
* 災害情報を邪魔しない
* クリック操作を過剰に阻害しない

---

## 10. モバイル確認

スマホ幅で確認。

期待:

* 横スクロールなし
* ラベルが画面を埋め尽くさない
* レイヤーパネル操作可能
* 交通カードが崩れない
* z-index競合なし

---

## 11. パフォーマンス確認

確認:

* 鉄道レイヤーOFF時に駅GeoJSONをfetchしない
* ON後に初回fetch
* 以後メモリキャッシュ
* pan/zoomで毎回fetchしない
* debounceが効く
* 操作が重くならない
* console errorなし
* request failureなし

---

## 12. 既存回帰確認

最低限確認:

* 地震一覧展開
* 地震項目クリックで地図フォーカス
* 津波警報UI
* 雨雲レイヤー
* キキクルレイヤー
* 高潮レイヤー
* 潮位観測点
* 日月カード
* 危険地域ランキング
* 河川情報リンク
* 鉄道カード
* 鉄道路線色
* 鉄道障害表現
* 鉄道レイヤーON/OFF

---

## 13. 判定基準

### PASS

以下をすべて満たす。

* 鉄道レイヤーON時のみ路線名・駅名が表示される
* OFF時はラベルが消える
* ズームレベルで段階表示される
* 障害路線名が優先表示される
* 障害路線周辺駅が優先表示される
* ラベル数が制御されている
* 地図がラベルで潰れない
* モバイルで破綻しない
* 既存鉄道路線色・障害表現を壊さない
* 既存 `/live` の回帰がない

### PASS with notes

以下のような軽微な課題がある場合。

* 一部駅名が取得できない
* 一部路線名が表示名として不自然
* 主要駅判定に改善余地あり
* ラベル配置に重なりが一部残る
* モバイルではやや情報量が多い

### FAIL

以下のいずれか。

* 鉄道レイヤーOFFでもラベルが表示される
* zoom段階表示が効かない
* ラベルが多すぎて地図が読めない
* 駅GeoJSONを常時fetchする
* pan/zoomでUIが重い
* モバイルで操作不能
* 既存災害レイヤーを壊す
* 既存鉄道レイヤーを壊す

---

## 14. レポート作成

以下に作成する。

```text
tasks/live/live_phase7a4_railway_labels_codex_verification.md
```

記載内容:

```text
# Phase 7-A.4 鉄道路線名・駅名ラベル表示 CODEX検証

## 判定
PASS / PASS with notes / FAIL

## 検証環境
- date
- branch
- commit
- docker compose status

## 実施コマンド
- node --check
- backend compile
- Playwright

## レイヤーON/OFF確認

## ズーム段階表示確認

## 路線名ラベル確認

## 駅名ラベル確認

## 障害路線優先確認

## 障害路線周辺駅優先確認

## ラベル数制御確認

## パフォーマンス確認

## モバイル確認

## 回帰確認

## 発見した問題

## 修正提案

## スクリーンショット

## 最終結論
```

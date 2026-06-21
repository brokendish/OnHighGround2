# CODEX用検証指示書

# 総合災害ビューア全国監視 Phase 7-B.1

# 道路ネットワークオーバーレイ・道路名ラベル MVP 検証

## 検証目的

Phase 7-B.1 の道路ネットワークオーバーレイと道路名ラベル表示を検証する。

重点:

* 道路交通影響レイヤーON時だけ道路ネットワークが表示されること
* ズームレベルに応じて大きい道から細い道へ段階表示されること
* 高速・国道だけでなく主要地方道も表示されること
* 住宅街の細街路を表示しないこと
* 道路名ラベルが分かりやすく表示されること
* 既存の交通量観測点マーカー、鉄道、災害レイヤーを壊さないこと

---

## 対象

画面:

```text
/live
```

対象レイヤー:

```text
道路交通影響
```

データ候補:

```text
frontend/layers/roads/kanto_major_roads.geojson
```

ファイル候補:

```text
frontend/js/live/live-road-network-layer.js
frontend/js/live/live-road-traffic-layer.js
frontend/js/live/live-road-traffic-panel.js
frontend/css/live/live-road-network.css
```

成果物:

```text
tasks/live/live_phase7b1_road_network_overlay_codex_verification.md
```

---

## 1. 構文・起動確認

```bash
python3 -m compileall backend
node --check frontend/js/live/live-road-traffic-layer.js
node --check frontend/js/live/live-road-traffic-panel.js
```

追加JSがある場合:

```bash
node --check frontend/js/live/live-road-network-layer.js
```

Docker:

```bash
docker compose ps
```

期待:

* backend healthy
* frontend up
* martin healthy
* JS構文エラーなし

---

## 2. GeoJSON確認

```bash
curl -I http://127.0.0.1:8080/layers/roads/kanto_major_roads.geojson
```

期待:

* HTTP 200
* Content-Type が GeoJSON/JSON
* gzip または圧縮配信が望ましい
* サイズが過大でないこと

中身確認:

```bash
python3 - <<'PY'
import json
p='frontend/layers/roads/kanto_major_roads.geojson'
with open(p) as f:
    d=json.load(f)
print(len(d.get('features', [])))
from collections import Counter
print(Counter(f.get('properties', {}).get('highway') for f in d.get('features', [])))
PY
```

期待:

含まれる:

```text
motorway
trunk
primary
secondary
tertiary
```

含まれない、または極少:

```text
residential
service
living_street
track
path
footway
cycleway
```

---

## 3. レイヤーON/OFF確認

### OFF時

期待:

* 道路ネットワーク非表示
* 道路名ラベル非表示
* 不要な道路GeoJSON fetch が発生しないことが望ましい

### ON時

期待:

* 主要道路が表示される
* 道路名ラベルが表示される
* 交通量観測点マーカーも維持される

OFFへ戻す:

* 道路線・道路ラベル・道路マーカーが消える

---

## 4. ズーム段階表示確認

### zoom 8〜10

期待:

表示:

```text
motorway
trunk
primary
```

非表示:

```text
secondary
tertiary
residential
service
```

確認例:

* 東名高速
* 中央道
* 圏央道
* 国道20号
* 国道246号

---

### zoom 11〜12

期待:

追加表示:

```text
secondary
```

確認例:

* 環七通り
* 環八通り
* 世田谷通り
* 青梅街道
* 府中街道
* 多摩堤通り

---

### zoom 13以上

期待:

追加表示:

```text
tertiary
```

ただし表示数制御あり。

住宅街の細街路は表示しない。

---

## 5. 道路名ラベル確認

確認:

* `name` 優先
* `ref` は代替
* 「都道3号」より「世田谷通り」等の通称が出る
* 同一道路名が過剰に重複しない
* 表示範囲外のラベルが残らない
* pan/zoomで古いラベルが残らない

確認例:

```text
東名高速
中央道
圏央道
国道20号
国道246号
世田谷通り
環七通り
環八通り
多摩堤通り
府中街道
```

---

## 6. 細街路除外確認

狛江市・世田谷区周辺で確認する。

期待:

表示される可能性あり:

```text
世田谷通り
多摩堤通り
狛江通り
府中街道
環八通り
国道20号
```

表示されない:

```text
住宅街の細い生活道路
private/service道路
駐車場内通路
歩道
自転車道
```

---

## 7. 色・線幅確認

期待:

```text
motorway   緑
trunk      明るい緑
primary    青
secondary  オレンジ
tertiary   薄グレー
```

線幅:

```text
motorway > trunk > primary > secondary > tertiary
```

確認:

* 黒背景で読める
* 鉄道路線色と混同しすぎない
* 災害レイヤーを潰さない
* 道路が主張しすぎない

---

## 8. 交通量マーカー共存確認

Phase 7-B の観測点マーカーが壊れていないこと。

確認:

* 道路交通影響レイヤーONでマーカー表示
* マーカークリックでポップアップ
* 道路ネットワークとマーカーが同時表示
* OFFで両方消える

---

## 9. パフォーマンス確認

確認:

* 初回 fetch 後はメモリキャッシュ
* pan/zoomで再fetchしない
* 表示範囲フィルタあり
* debounceあり
* DOM/SVG pathが増えすぎない
* 操作が重くならない
* console errorなし

---

## 10. モバイル確認

スマホ幅で確認。

期待:

* 横スクロールなし
* 道路ラベルが画面を埋め尽くさない
* レイヤーパネル操作可能
* 交通カードが崩れない
* ポップアップが画面を破壊しない
* 鉄道ラベルと競合して操作不能にならない

---

## 11. 回帰確認

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
* 道路交通影響カード
* 道路交通量マーカー
* レイヤーON/OFF全般

---

## 12. E2E追加推奨

追加候補:

```text
e2e/live-road-network-layer.spec.js
```

最低限:

```text
1. 道路交通影響レイヤーONで道路ネットワーク表示
2. OFFで道路ネットワーク非表示
3. zoom 8〜10 で motorway/trunk/primary のみ
4. zoom 11〜12 で secondary 追加
5. zoom 13以上で tertiary 追加
6. residential/service が表示されない
7. 道路名ラベルが表示される
8. 道路交通量マーカーと共存する
9. モバイルで横スクロールなし
```

---

## 13. 判定基準

### PASS

* 道路交通影響レイヤーON時だけ道路ネットワーク表示
* OFF時に消える
* zoom段階表示が機能する
* 高速・国道・主要地方道が表示される
* 住宅街の細街路は表示されない
* 道路名ラベルが表示される
* ラベルが多すぎない
* 交通量マーカーと共存
* 既存 `/live` 回帰なし
* モバイル破綻なし

### PASS with notes

* 一部道路名が ref 表示になる
* 一部主要道路のタグ分類に改善余地
* tertiary 表示がやや多い
* ラベル重なりが一部残る
* 色味・線幅に微調整余地

### FAIL

* 道路が表示されない
* レイヤーOFFでも道路が残る
* residential/service が大量表示される
* ラベル過多で地図が読めない
* pan/zoomで重くなる
* 既存災害・鉄道レイヤーを壊す
* モバイル操作不能

---

## 14. レポート作成

以下に作成する。

```text
tasks/live/live_phase7b1_road_network_overlay_codex_verification.md
```

記載内容:

```text
# Phase 7-B.1 道路ネットワークオーバーレイ CODEX検証

## 判定
PASS / PASS with notes / FAIL

## 検証環境
- date
- branch
- commit
- docker compose status

## 実施コマンド

## GeoJSON確認

## レイヤーON/OFF確認

## ズーム段階表示確認

## 道路名ラベル確認

## 細街路除外確認

## 色・線幅確認

## 交通量マーカー共存確認

## パフォーマンス確認

## モバイル確認

## 回帰確認

## 発見した問題

## 修正提案

## スクリーンショット

## 最終結論
```

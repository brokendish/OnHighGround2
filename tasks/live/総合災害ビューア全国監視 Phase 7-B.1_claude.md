# Claude用実装指示書

# 総合災害ビューア全国監視 Phase 7-B.1

# 道路ネットワークオーバーレイ・道路名ラベル MVP

## 背景

Phase 7-B では、国土交通省交通量API（JARTIC提供）を前提とした道路交通影響レイヤーMVPを実装した。

ただし、JARTIC APIキー取得待ちのため、現時点では実交通量データを地図上で十分に観察できない。

一方で、鉄道レイヤーでは以下の改善により、情報伝達力が大きく向上した。

* 路線オーバーレイ
* 路線ごとの色分け
* 路線名ラベル
* 駅名ラベル
* ズーム段階表示

道路交通影響レイヤーでも、交通量データを重ねる前に、道路ネットワークそのものを見えるようにする。

---

## 目的

`/live` の「道路交通影響」レイヤーON時に、主要道路ネットワークと道路名ラベルを表示する。

将来 JARTIC 交通量データが取得できた際に、観測点や交通量状態を道路ネットワーク上に重ねられる土台とする。

---

## 基本方針

道路ナビではなく、災害時の道路交通影響把握を目的とする。

そのため、生活道路や住宅街の細街路は表示しない。

既存の背景地図を拡大すれば細街路は確認できるため、`/live` の道路交通影響レイヤーでは主要道路に限定する。

---

## 表示対象道路

OSM PBF から主要道路を抽出し、静的 GeoJSON として配信する。

対象タグ:

```text
highway=motorway
highway=trunk
highway=primary
highway=secondary
highway=tertiary
```

ただし `tertiary` はズーム高めで限定表示する。

---

## 除外対象

以下は表示しない。

```text
highway=residential
highway=service
highway=living_street
highway=unclassified
highway=track
highway=path
highway=footway
highway=cycleway
highway=pedestrian
highway=steps
highway=construction
```

また以下も除外する。

```text
service=parking_aisle
service=driveway
access=private
```

---

## データ生成

既存の `data/kanto-260214.osm.pbf` を利用する。

鉄道で実施した方式と同様に、osmium 等で道路 GeoJSON を事前抽出する。

出力候補:

```text
frontend/layers/roads/kanto_major_roads.geojson
```

プロパティ例:

```json
{
  "highway": "secondary",
  "name": "世田谷通り",
  "ref": "都道3号",
  "operator": null,
  "oneway": "yes",
  "_live_road_name": "世田谷通り",
  "_live_road_class": "secondary"
}
```

---

## 道路名決定ルール

表示名は `name` を優先する。

優先順:

```text
name
name_ja
official_name
alt_name
ref
```

理由:

利用者には「都道3号」より「世田谷通り」「環八通り」「国道20号」の方が分かりやすい。

ただし、`ref` しかない場合は `ref` を使う。

例:

```text
国道20号
国道246号
世田谷通り
環七通り
環八通り
多摩堤通り
府中街道
青梅街道
甲州街道
```

---

## 道路クラス

内部的には以下へ正規化する。

```text
motorway   高速道路
trunk      自動車専用道・主要幹線
primary    国道級
secondary  主要地方道級
tertiary   地域主要道路
unknown    不明
```

---

## ズーム段階表示

鉄道レイヤーと同様に、ズームレベルで表示道路を変える。

### zoom 8〜10

広域監視。

表示:

```text
motorway
trunk
primary
```

目的:

高速道路・広域幹線・主要国道を見る。

例:

```text
東名高速
中央道
圏央道
関越道
国道1号
国道16号
国道20号
国道246号
```

---

### zoom 11〜12

都市監視。

追加表示:

```text
secondary
```

目的:

都市部の主要地方道を見る。

例:

```text
環七通り
環八通り
世田谷通り
目黒通り
青梅街道
府中街道
鎌倉街道
多摩堤通り
```

---

### zoom 13以上

地域監視。

追加表示:

```text
tertiary
```

ただし表示数制限を行う。

目的:

生活道路ではない地域主要道路を見る。

---

## 道路色

道路種別ごとに固定色を使う。

推奨:

```text
motorway   #43A047  緑
trunk      #66BB6A  明るい緑
primary    #1E88E5  青
secondary  #FB8C00  オレンジ
tertiary   #B0BEC5  薄いグレー
unknown    #78909C  グレー
```

背景地図が黒系のため、視認性を確認すること。

---

## 線幅

```text
motorway   3.0
trunk      2.8
primary    2.5
secondary  2.0
tertiary   1.5
```

opacity:

```text
0.65〜0.85
```

災害レイヤーを邪魔しないこと。

---

## 道路ラベル

道路交通影響レイヤーON時のみ表示する。

### zoom 8〜10

```text
motorway / trunk / primary の主要道路名のみ
最大 30 件
```

### zoom 11〜12

```text
secondary まで道路名表示
最大 60 件
```

### zoom 13以上

```text
tertiary まで道路名表示
最大 100 件
```

ただし、ラベル過多を避ける。

---

## ラベル表示方針

MVPでは道路に沿った文字でなくてよい。

以下でよい。

```text
表示範囲内 geometry の代表点
または bounds center
```

同一路線名は過剰に重複表示しない。

1道路名につき表示範囲内で1〜2個程度に抑える。

---

## ラベル見た目

鉄道路線ラベルと似たトーンでよい。

推奨:

```text
文字色: #ffffff
背景: rgba(0,0,0,0.55)
枠線: 道路種別色
角丸
小さめ
```

道路名ラベル例:

```text
東名高速
国道20号
世田谷通り
環八通り
```

---

## 道路 feature 集約

鉄道と同様に、同一道路名・ref の複数 feature をまとめる。

キー候補:

```text
_live_road_name
name
ref
highway
```

目的:

細切れ feature が大量に描画されることを防ぐ。

---

## 表示範囲フィルタ

全件を一度にLeaflet描画しない。

必ず表示範囲内のみ描画する。

鉄道と同様に以下を行う。

* 初回 fetch
* メモリキャッシュ
* 表示範囲フィルタ
* pan/zoom debounce
* zoom段階フィルタ

---

## 道路交通量マーカーとの関係

Phase 7-B の観測点マーカーは維持する。

レイヤーON時には以下が同時に表示される。

```text
道路ネットワーク
道路名ラベル
交通量観測点マーカー
```

JARTIC実データ取得後は、観測点の状態に応じて近傍道路を強調できるようにする。

ただし Phase 7-B.1 では、交通量による道路線強調は対象外。

---

## 凡例

道路交通影響レイヤーON時に凡例へ追加する。

例:

```text
道路:
緑 高速道路
青 国道級
橙 主要地方道
灰 地域主要道路

交通量:
赤 交通量非常に多い
青 交通量少ない
```

通行止めと誤認しない文言を維持する。

---

## MVP対象外

以下は実装しない。

```text
住宅街の細街路表示
全道路網表示
経路探索
渋滞距離表示
所要時間表示
通行止め断定
交通量による道路線強調
IC名・交差点名ラベル
```

---

## 完了条件

* 道路交通影響レイヤーON時に主要道路が表示される
* OFF時は道路ネットワークと道路名ラベルが消える
* zoom 8〜10 では motorway/trunk/primary のみ表示
* zoom 11〜12 では secondary が追加表示
* zoom 13以上では tertiary が限定表示
* residential/service/living_street 等は表示されない
* 道路名ラベルが表示される
* ラベルが多すぎない
* 交通量観測点マーカーと共存する
* 鉄道レイヤーと競合しない
* 既存災害レイヤーを邪魔しない
* モバイルで破綻しない

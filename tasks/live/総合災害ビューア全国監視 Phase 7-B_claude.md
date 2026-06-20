# Claude用実装指示書

# 総合災害ビューア全国監視 Phase 7-B

# 道路交通影響レイヤー MVP

## 目的

`/live` に「道路交通影響レイヤー」を追加する。

目的は道路ナビや渋滞アプリを作ることではない。

災害時に、

* 交通量が多い
* 交通量が極端に少ない
* 迂回集中の可能性がある
* 通行止め・規制・冠水等の可能性がある

といった道路交通影響を把握し、行動判断を支援する。

---

## データソース

第一候補:

```text
国土交通省 交通量API
JARTIC提供 常時観測交通量データ
```

取得対象:

```text
5分値
1時間値
観測地点情報
```

注意:

このAPIは交通量APIであり、通行止めAPIではない。

そのため UI 上で「通行止め」と断定しない。

表現は以下を基本とする。

```text
交通量多い
交通量少ない
交通量急増
交通量急減
交通影響の可能性
```

---

## 重要方針

以下を必ず分離する。

```text
交通影響なし
交通量データなし
取得不可
状態不明
```

取得不可を「交通影響なし」と誤表示しない。

---

## APIキー・利用条件

JARTIC/交通量APIの利用条件を確認し、必要な認証・規約同意を前提とする。

設定値は環境変数で管理する。

例:

```env
ROAD_TRAFFIC_API_BASE_URL=...
ROAD_TRAFFIC_API_KEY=...
```

APIキー不要の場合でも、base URL は環境変数化してよい。

---

## バックエンド追加候補

```text
backend/app/services/live_road_traffic_service.py
backend/app/routers/live_road_traffic.py
backend/app/models/live_road_traffic.py
```

既存構成に合わせること。

---

## 正規化モデル

生データをそのままフロントへ返さない。

正規化例:

```json
{
  "station_id": "xxxx",
  "road_name": "国道20号",
  "direction": "上り",
  "lat": 35.6812,
  "lng": 139.7671,
  "volume_5min": 120,
  "volume_1h": 1320,
  "baseline_volume_1h": null,
  "status": "high",
  "status_label": "交通量多い",
  "severity": 2,
  "observed_at": "2026-06-18T21:40:00+09:00",
  "source": "国土交通省 交通量API（JARTIC提供）"
}
```

---

## status分類

MVPでは以下に正規化する。

```text
normal       通常
high         交通量多い
very_high    交通量非常に多い
low          交通量少ない
very_low     交通量極端に少ない
unknown      状態不明
unavailable 取得不可
```

### severity

```text
0 normal
1 unknown
2 high / low
3 very_high / very_low
9 unavailable
```

---

## 判定ロジック MVP

最初から高度な平常時比較は不要。

MVPでは以下の順で実装する。

### 1. 絶対値ベース

5分値または1時間値から、交通量の多寡を簡易判定。

ただし閾値は固定値でよいが、必ず `MVP provisional` とコメントする。

### 2. 方向別

同一観測地点で方向別データがある場合、方向を保持する。

### 3. 将来拡張

平常時平均との差分、前週同曜日比較、直近平均との差分は Phase 7-B.1 以降候補とする。

---

## API

追加API案:

```text
GET /api/live/road-traffic/summary
```

クエリ:

```text
lat
lng
prefecture
bbox
```

優先:

```text
bbox > prefecture > lat/lng
```

レスポンス例:

```json
{
  "status": "ok",
  "scope": {
    "mode": "prefecture",
    "prefecture": "東京都"
  },
  "updated_at": "2026-06-18T21:45:00+09:00",
  "items": [
    {
      "station_id": "xxx",
      "road_name": "国道20号",
      "direction": "上り",
      "lat": 35.68,
      "lng": 139.76,
      "status": "very_high",
      "status_label": "交通量非常に多い",
      "severity": 3,
      "volume_5min": 180,
      "volume_1h": 2100,
      "observed_at": "2026-06-18T21:25:00+09:00",
      "source": "国土交通省 交通量API（JARTIC提供）"
    }
  ]
}
```

取得不可:

```json
{
  "status": "unavailable",
  "message": "道路交通量情報を取得できません",
  "items": []
}
```

データなし:

```json
{
  "status": "ok",
  "items": [],
  "message": "現在地周辺の道路交通量情報はありません"
}
```

---

## キャッシュ

交通量APIへの過剰アクセスを避ける。

MVP:

```text
TTL 5分
```

失敗時、stale cache がある場合:

```json
{
  "status": "ok",
  "stale": true,
  "message": "最新の道路交通量情報を取得できません。前回取得情報を表示しています"
}
```

---

## 情報カード

既存の交通系カードを拡張する。

候補:

```text
🚗 道路交通影響
```

表示例:

```text
国道20号 上り　交通量非常に多い
国道246号 下り　交通量少ない
国道16号 外回り　交通量急増の可能性
```

障害なしではなく、データがあるが異常なしの場合:

```text
現在地周辺で目立った道路交通影響は確認されていません
```

データなし:

```text
現在地周辺の道路交通量情報はありません
```

取得不可:

```text
道路交通量情報を取得できません
```

---

## 地図レイヤー

レイヤーパネルに追加:

```text
道路交通影響
```

MVPでは観測点マーカー表示から開始する。

理由:

交通量APIは観測点データであり、道路全線の規制情報ではないため。

---

## マーカー色

```text
normal      緑または薄グレー
high        黄
very_high   赤
low         青
very_low    紫または濃青
unknown     グレー
```

ただし「赤=通行止め」と誤解されないよう、凡例で明示する。

```text
赤: 交通量が非常に多い
青: 交通量が少ない
```

---

## ポップアップ

観測点クリック時に表示:

```text
道路名
方向
交通量 5分値
交通量 1時間値
状態
観測時刻
出典
注意書き
```

注意書き:

```text
交通量APIの値から推定した交通影響であり、通行止め・規制を断定するものではありません。
```

---

## ランキング

道路交通影響カードでは、severity 降順で上位を表示する。

表示件数:

```text
最大5件
```

将来、最大10件を検討。

---

## MVP対象外

実施しない。

```text
通行止め断定
事故情報
渋滞距離
所要時間
経路探索
迂回ルート案内
全道路網オーバーレイ
道路規制情報との統合
```

---

## テスト

追加候補:

```text
tests/test_live_road_traffic_service.py
tests/test_live_road_traffic_api.py
e2e/live-road-traffic-layer.spec.js
```

確認:

* 交通量APIレスポンス正規化
* high / very_high / low / very_low 判定
* 取得不可とデータなしの分離
* stale cache
* prefecture / bbox scope
* カード表示
* マーカー表示
* ポップアップ
* レイヤーON/OFF
* モバイル表示

---

## 完了条件

* `/api/live/road-traffic/summary` が追加される
* 交通量APIデータを正規化できる
* 取得不可・データなし・異常なしを分離できる
* `/live` に「🚗 道路交通影響」カードが表示される
* 道路交通影響レイヤーをON/OFFできる
* 観測点マーカーが状態別に表示される
* ポップアップに交通量・観測時刻・出典・注意書きが出る
* 交通量を通行止めと断定しない
* 既存の鉄道レイヤー、災害レイヤーを壊さない

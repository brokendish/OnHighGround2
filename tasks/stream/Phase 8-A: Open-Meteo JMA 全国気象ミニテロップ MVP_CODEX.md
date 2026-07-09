# CODEX用検証指示書

## Phase 8-A: Open-Meteo JMA 全国気象ミニテロップ MVP 検証

## 検証目的

Claude実装後の `Phase 8-A: Open-Meteo JMA 全国気象ミニテロップ MVP` について、仕様通りに実装されているかを検証する。

対象は `/live` 右パネル上部に追加される `全国気象` ミニテロップである。

特に以下を重点確認する。

* Open-Meteo `/v1/jma` を backend proxy 経由で利用していること
* frontend から Open-Meteo を直接叩いていないこと
* 都道府県代表地点 + 北海道複数地点が取得・表示されること
* 表示順が南から北で固定されていること
* 更新時刻表示が正しいこと
* 天気カラーバッジ・数値強調が機能すること
* stale / unavailable 時に誤表示しないこと
* 既存 `/live` 機能を壊していないこと

## 前提

対象画面:

```text
/live
```

対象機能名:

```text
全国気象
```

想定API:

```text
GET /api/live/weather/jma/prefectures
```

実際の実装でパスが異なる場合は、実装差分を確認して該当APIを特定すること。

## 検証成果物

検証結果を以下に作成する。

```text
tasks/live/live_phase8a_open_meteo_jma_weather_ticker_codex_verification.md
```

レポートには以下を含める。

* 判定: PASS / PASS with notes / FAIL
* 確認したファイル
* 実行したコマンド
* API確認結果
* UI確認結果
* E2E確認結果
* 回帰確認結果
* 問題があれば再現手順と原因推定
* notes があれば明記

## 1. 実装差分確認

以下を確認する。

* backend に Open-Meteo JMA 用 service / API が追加されているか
* frontend に live weather ticker 用 JS/CSS が追加されているか
* `/live` HTML または既存 live 初期化処理に組み込まれているか
* 代表地点マスタが追加されているか
* 既存の鉄道情報、潮位・水位カードの高さ調整が過剰でないか
* 既存 `/live` 機能に不要な影響が出ていないか

確認例:

```bash
git diff --stat
git diff
```

## 2. backend API確認

### 2.1 API存在確認

以下相当のAPIが存在すること。

```text
GET /api/live/weather/jma/prefectures
```

確認例:

```bash
curl -sS http://127.0.0.1:8000/api/live/weather/jma/prefectures | jq .
```

docker環境のポートに合わせて適宜変更すること。

### 2.2 レスポンス構造確認

レスポンスに以下が含まれること。

```json
{
  "status": "ok",
  "source": "Open-Meteo JMA",
  "forecast_time": "...",
  "fetched_at": "...",
  "cache_status": "fresh",
  "items": []
}
```

各 item に以下が含まれること。

```json
{
  "id": "...",
  "pref_code": "...",
  "pref_name": "...",
  "point_name": "...",
  "display_order": 10,
  "weather_code": 3,
  "weather_category": "cloudy",
  "weather_label": "曇",
  "temperature_c": 28.0,
  "humidity_percent": 76,
  "precipitation_probability_percent": 40,
  "flags": {
    "precipitation_high": false,
    "temperature_hot": false,
    "temperature_cold": false,
    "humidity_high": false
  }
}
```

### 2.3 Open-Meteo /v1/jma 利用確認

backend 側が Open-Meteo の `/v1/jma` を利用していることを確認する。

確認観点:

* `/v1/forecast` ではなく `/v1/jma` を利用していること
* `hourly` に以下が含まれること

  * `weather_code`
  * `temperature_2m`
  * `relative_humidity_2m`
  * `precipitation_probability`
* `timezone=Asia/Tokyo` が指定されていること
* frontend から Open-Meteo を直接叩いていないこと

frontend JS 内に以下のような直接アクセスがないか確認する。

```bash
grep -R "api.open-meteo.com" frontend backend -n
```

期待:

* backend 側には存在してよい
* frontend 側には存在しないこと

## 3. 地点マスタ確認

### 3.1 都道府県代表地点

代表地点マスタが存在すること。

例:

```text
weather_points_jma.json
```

または同等ファイル。

確認項目:

* 46都府県が各1地点以上あること
* 北海道が複数地点あること
* 各地点に `id`, `pref_code`, `pref_name`, `point_name`, `lat`, `lon`, `display_order` があること
* `display_order` が数値であること
* `id` が重複していないこと

### 3.2 北海道複数地点

北海道として以下の7地点が含まれること。

* 函館
* 札幌
* 旭川
* 帯広
* 釧路
* 網走
* 稚内

確認例:

```bash
cat <地点マスタ> | jq '.[] | select(.pref_code=="01") | .point_name'
```

### 3.3 表示順

表示順が南から北になっていること。

最低限、以下の順序関係を確認する。

```text
那覇 < 鹿児島 < 福岡 < 高知/松山/高松等 < 大阪 < 名古屋 < 東京 < 仙台 < 青森 < 函館 < 札幌 < 旭川/帯広/釧路/網走 < 稚内
```

厳密な全地点順は実装マスタに依存してよいが、北海道が先頭側に来たり、那覇が末尾側に来たりしないこと。

APIレスポンスの `items` が `display_order` 昇順で返ることを確認する。

## 4. 天気コード正規化確認

Open-Meteo `weather_code` が UI 用カテゴリへ正規化されていること。

期待カテゴリ:

```text
sunny
cloudy
rain
snow
thunder
fog
unknown
```

または同等のカテゴリ。

表示ラベル:

```text
晴
曇
雨
雪
雷
霧
不明
```

分類確認:

```text
0 → 晴
1,2 → 晴
3 → 曇
45,48 → 霧
51,53,55,56,57 → 雨
61,63,65,66,67,80,81,82 → 雨
71,73,75,77,85,86 → 雪
95,96,99 → 雷
その他 → 不明
```

単体テストがある場合は実行する。
ない場合は追加を検討する。

## 5. flags確認

以下の条件で flags が true になること。

```text
precipitation_probability_percent >= 70
  → precipitation_high = true

temperature_c >= 35
  → temperature_hot = true

temperature_c <= 0
  → temperature_cold = true

humidity_percent >= 85
  → humidity_high = true
```

境界値を確認する。

* 降水確率 69 → false
* 降水確率 70 → true
* 気温 34.9 → false
* 気温 35.0 → true
* 気温 0.0 → true
* 気温 0.1 → false
* 湿度 84 → false
* 湿度 85 → true

## 6. cache / stale確認

### 6.1 fresh

正常取得時:

```json
"cache_status": "fresh"
```

UI表示:

```text
全国気象 HH:mm時点 / HH:mm取得
```

### 6.2 stale

Open-Meteo 取得失敗時に stale cache がある場合:

```json
"cache_status": "stale"
```

UI表示:

```text
全国気象 HH:mm時点 / HH:mm取得  更新遅延
```

確認観点:

* 前回データを表示する
* 更新遅延が分かる
* 「なし」と誤表示しない
* `/live` が落ちない

### 6.3 unavailable

stale cache もない場合、または有効期限超過時:

```json
"cache_status": "unavailable"
```

UI表示:

```text
全国気象 更新停止中
```

または:

```text
全国気象 更新停止中 / 前回 HH:mm取得
```

確認観点:

* データなしを天気なしと誤解させない
* console error を出し続けない
* `/live` 全体の描画を妨げない

## 7. frontend UI確認

### 7.1 表示位置

`/live` 右パネル上部に `全国気象` が表示されること。

期待構成:

```text
右パネル
├─ 全国気象
├─ 鉄道情報
├─ 潮位・水位
└─ その他
```

確認項目:

* 鉄道情報より上に表示される
* 潮位・水位より上に表示される
* 右パネルからはみ出さない
* 他カードと重ならない
* 既存カードの高さ圧縮が過剰でない

### 7.2 ヘッダー表示

以下形式で表示されること。

```text
全国気象 HH:mm時点 / HH:mm取得
```

例:

```text
全国気象 23:00時点 / 23:05取得
```

確認項目:

* forecast_time 由来の時刻が `HH:mm時点`
* fetched_at 由来の時刻が `HH:mm取得`
* JST表示になっている
* undefined / null / Invalid Date が表示されない

### 7.3 2列〜3列表示

デスクトップ右パネルでは 3列表示、狭幅では 2列表示になること。

確認項目:

* 3列 × 3行程度で表示される
* 狭幅では2列表示に崩れる
* 横スクロールが発生しない
* 地点名、天気バッジ、気温、湿度、降水確率が読める

### 7.4 ページ送り

全地点を一度に固定表示せず、ページングまたはテロップ切替されること。

確認項目:

* 約8〜10秒で次ページに切り替わる
* `display_order` 順に切り替わる
* 最終ページの後に先頭へ戻る
* 北海道の複数地点も表示対象に含まれる
* 切替時に画面が大きく跳ねない
* `/live/stream` でも見苦しくない

### 7.5 天気カラーバッジ

天気種別がカラーバッジで表示されること。

対象:

* 晴
* 曇
* 雨
* 雪
* 雷
* 霧
* 不明

確認項目:

* 天気が文字だけでなくバッジ化されている
* 晴/雨/雪/雷などが視覚的に区別できる
* 色が強すぎず、災害警戒色と競合しない
* ダークUI上で読める
* コントラストが不足していない

### 7.6 数値強調

以下が視覚的に強調されること。

```text
降水確率 70%以上
気温 35℃以上
気温 0℃以下
湿度 85%以上
```

確認項目:

* 降水確率70%以上が青系強調される
* 気温35℃以上が高温注意として強調される
* 気温0℃以下が低温注意として強調される
* 湿度85%以上が高湿度として強調される
* 複数条件が同時に true の場合も表示が破綻しない

## 8. E2Eテスト確認

可能であれば Playwright 等で専用E2Eを追加・実行する。

推奨テストファイル名:

```text
e2e/live-weather-ticker.spec.js
```

テスト観点:

1. `/live` で全国気象カードが表示される
2. ヘッダーに `全国気象` と `HH:mm時点 / HH:mm取得` が表示される
3. 地点が複数表示される
4. 天気バッジが表示される
5. 降水確率70%以上などの強調classが付与される
6. ページ送りで表示地点が変わる
7. 北海道の複数地点がページング内に含まれる
8. stale時に `更新遅延` が表示される
9. unavailable時に `更新停止中` が表示される
10. console error / page error がない

## 9. 回帰確認

既存 `/live` 機能に影響がないことを確認する。

最低限確認:

* `/live` が 200 OK
* `/live/stream` が 200 OK
* 雨雲レイヤー表示
* キキクル表示
* 地震リスト表示
* 鉄道情報表示
* 潮位・水位表示
* レイヤー切替
* 右パネル表示崩れなし
* モバイル表示崩れなし

可能であれば既存テストを実行する。

例:

```bash
node --check frontend/js/live/*.js
```

```bash
venv/bin/python -m pytest
```

または既存の scoped test があればそれを優先する。

## 10. `/live/stream` 確認

YouTube配信向け画面でも表示が破綻しないことを確認する。

確認URL例:

```text
/live/stream?chrome=off
```

確認項目:

* 全国気象が表示される
* 文字が小さすぎない
* 10秒程度のページ送りが見やすい
* 地点切替時に画面が跳ねない
* 既存 ticker や警戒表示と競合しない
* 右パネル内で収まる

## 11. 失敗時の確認

Open-Meteo 側への接続失敗を mock / route / 環境変数等で再現できる場合、以下を確認する。

* backend が 500 を返し続けない
* stale cache があれば stale として返す
* stale cache がなければ unavailable として返す
* frontend は更新停止中表示にする
* `/live` 全体は正常表示される
* console error を大量出力しない

## 12. 判定基準

### PASS

以下をすべて満たす場合。

* `/live` 右パネル上部に全国気象が表示される
* Open-Meteo `/v1/jma` を backend proxy 経由で利用している
* frontend 直接アクセスがない
* 都道府県代表地点 + 北海道複数地点が表示される
* 表示順が南から北
* 更新時刻表示が正しい
* 天気カラーバッジが機能する
* 数値強調が機能する
* stale / unavailable が非断定表示になる
* `/live` 既存機能に破壊的影響がない

### PASS with notes

主要機能は満たすが、以下のような軽微な課題がある場合。

* 表示順に一部改善余地あり
* 右パネル内の余白調整余地あり
* 色味やコントラストに軽微な改善余地あり
* テストカバレッジに追加余地あり
* Open-Meteo実通信に依存するため一部検証が限定的

### FAIL

以下がある場合。

* `/live` が表示不能
* backend API が機能しない
* frontend が Open-Meteo を直接叩いている
* 北海道複数地点が含まれていない
* 表示順が明らかに南→北でない
* stale / unavailable で誤表示する
* 既存の鉄道・潮位・水位・地震・雨雲等を壊している
* console error / page error が継続発生する

## 13. レポート出力形式

レポートは以下の形式でまとめる。

````markdown
# Phase 8-A Open-Meteo JMA 全国気象ミニテロップ MVP 検証

## 判定

PASS / PASS with notes / FAIL

## 検証日時

YYYY-MM-DD HH:mm JST

## 対象差分

- 変更ファイル一覧
- 主要実装概要

## 実行コマンド

```bash
...
````

## backend API確認

結果を記載。

## 地点マスタ確認

結果を記載。

## UI確認

結果を記載。

## stale / unavailable確認

結果を記載。

## E2E確認

結果を記載。

## 回帰確認

結果を記載。

## Notes

改善余地や制約を記載。

## 結論

最終判断を記載。

```
```

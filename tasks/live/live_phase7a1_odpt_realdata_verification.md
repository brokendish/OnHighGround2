# Phase 7-A.1 ODPT実データ取得検証

## 判定

PASS with notes

## 取得日時

- 2026-06-14 21:02:48 JST

## 検証環境

- backend: `evacuation-navi-backend` healthy
- frontend: `evacuation-navi-frontend` up
- martin: healthy
- ODPT_API_KEY: 設定あり（64文字、値は非記録）
- backend コンテナ: `.env` 反映済み（再作成後に確認）

## ODPT直接取得

実装参照エンドポイント:

- `https://api.odpt.org/api/v4/odpt:TrainInformation?acl:consumerKey=...`
- `https://api.odpt.org/api/v4/odpt:Railway?acl:consumerKey=...`

結果:

| 種別 | HTTP | 件数 | サイズ | 取得時間 |
|---|---:|---:|---:|---:|
| TrainInformation | 200 | 21 | 9,979 bytes | 0.103 s |
| Railway | 200 | 94 | 121,522 bytes | 0.113 s |

認証成功。JSON取得成功。

## 実件数確認

TrainInformation 生データ:

- 運行情報件数: 21
- 事業者数: 6
- 路線数: 21
- 事業者例:
  - TokyoMetro
  - Toei
  - TWR
  - MIR
  - TamaMonorail
  - YokohamaMunicipal

Railway 生データ:

- 路線情報件数: 94
- 事業者数: 25
- JR-East / JR-Central などを含む

## Backend API確認

`/api/live/trains/summary`

| run | HTTP | status | stale | items | operators | railways | 応答時間 |
|---:|---:|---|---|---:|---:|---:|---:|
| 1 | 200 | ok | false | 0 | 0 | 0 | 0.089 s |
| 2 | 200 | ok | false | 0 | 0 | 0 | 0.004 s |
| 3 | 200 | ok | false | 0 | 0 | 0 | 0.006 s |

補足:

- ODPT 生データは 21件取得できている。
- 実データ 21件はすべて平常系テキストだった。
- Phase 7-A の仕様どおり、backend は平常路線をカード対象外として `items=[]` に正規化している。

## 全国性確認

| prefecture | HTTP | status | scope | items | 応答時間 |
|---|---:|---|---|---:|---:|
| 東京都 | 200 | ok | 東京都 | 0 | 0.005 s |
| 大阪府 | 200 | ok | 大阪府 | 0 | 0.005 s |
| 愛知県 | 200 | ok | 愛知県 | 0 | 0.005 s |
| 福岡県 | 200 | ok | 福岡県 | 0 | 0.003 s |
| 北海道 | 200 | ok | 北海道 | 0 | 0.004 s |

確認:

- エラーなし。
- 東京都固定ではなく、指定都道府県 scope を保持。
- 現在の実データは全件平常のため、全都道府県でカード対象障害は 0件。

## 状態分類確認

実データの `odpt:trainInformationStatus` は全21件が `null`。

実データ本文例:

- `現在、平常どおり運転しています。`
- `現在、１５分以上の遅延はありません。`
- `平常通り運転しています。`
- `平常運行`

判定:

- 実データ上で `delay` / `partial_suspension` / `suspended` は観測されなかった。
- 全件が normal 相当であり、backend がカード対象から除外する挙動は妥当。
- 非平常分類は Phase 7-A のユニットテストで確認済み。

## 実際の障害路線確認

今回取得時点では ODPT 生データに実障害路線なし。

整合性:

```text
ODPT実データ: 全件平常系
backend正規化: items=[]
UI表示: 現在地周辺で運行障害は確認されていません
```

## キャッシュ確認

- 初回 backend 応答: 0.089 s
- 2回目: 0.004 s
- 3回目: 0.006 s

2回目以降は明確に高速化。ODPTへ毎回フルアクセスしていないと判断できる。

## ODPT停止模擬

無効キー:

- `status=unavailable`
- `stale=false`
- `items=0`
- アプリ例外なし

通信失敗 + 既存キャッシュあり:

- `status=ok`
- `stale=true`
- `items=1`
- `scope={mode: prefecture, prefecture: 東京都}`

障害なしとの誤判定はない。

## UI確認

実 `/live` を Playwright で確認。

- 交通影響カード: 表示あり
- 都道府県選択: 表示あり
- 鉄道運行影響トグル: 表示あり
- console/page error: 0
- 現在の実データは障害なしのため、レイヤーON時の鉄道 marker/path は 0

実表示:

```text
現在地周辺で運行障害は確認されていません
```

スクリーンショット:

- `/private/tmp/live_phase7a1_real.png`

## パフォーマンス確認

| 対象 | 時間 |
|---|---:|
| ODPT TrainInformation 直接取得 | 0.103 s |
| ODPT Railway 直接取得 | 0.113 s |
| Backend 初回 | 0.089 s |
| Backend cache 2回目 | 0.004 s |
| Backend cache 3回目 | 0.006 s |

目安:

- 初回 3秒以内: PASS
- キャッシュ 1秒以内: PASS

## ログ確認

backendログ確認:

- トークン漏洩なし
- `consumerKey` 出力なし
- `ODPT_API_KEY` 出力なし
- stacktraceなし
- エラースパムなし

確認された live train ログ:

```text
live train summary: items=0
live train summary: ok items=0
```

## 発見した注意点

- ODPT `TrainInformation` の実取得件数は 21件で、今回時点では首都圏・周辺事業者中心だった。
- `Railway` は 94件・25事業者だが、現在の実装は `TrainInformation` を主データとしているため、障害情報の実カバレッジは ODPT 側の `TrainInformation` 掲載状況に依存する。
- 実障害が発生していないタイミングだったため、実データで `delay` / `partial_suspension` / `suspended` は観測できなかった。

## 最終結論

ODPTアクセストークン設定後の実データ取得は成功。backend API は実データ状態で安定応答し、キャッシュも正常に機能した。現在の実データは全件平常系のため、UIは「運行障害なし」と表示し、障害なしと取得失敗を誤判定していない。

全国 scope 指定は API として維持されているが、実際に取得できる運行情報の事業者範囲は ODPT `TrainInformation` の掲載状況に依存するため、判定は PASS with notes とする。

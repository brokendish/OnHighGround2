# データ準備

これは正式なデータ準備ガイドです。ホストの前提条件と public-core の smoke
パスについては、まず [インストール](installation.md) を参照してください。
大きなソースデータと生成物は意図的に Git にコミットしていません。

## データフローとディレクトリ

```text
data_lake/raw/<region>/        ダウンロードまたは手動取り込みしたソースデータ
data_lake/normalized/<region>/ 正規化した GeoJSON/GeoJSONL と派生データ
data_lake/validated/<region>/  検証済みの DEM・避難所・OSRM 入力
data_lake/tiles/<region>/      Martin 用に生成した MBTiles
data_runtime/current/          アトミックに publish された runtime バージョン
```

`data_runtime/current/` は runtime のソースです。ここへ直接データをコピー
しないでください。`scripts/publish/deploy_to_runtime.sh --dry-run` はマッピングを
プレビューします。実際の publish には privileged な operator ワークフローから
`scripts/publish/deploy_to_runtime_atomic.sh --region tokyo` を使います。
dry-run でない直接の publish スクリプトは、staging 環境が無いと fail-closed で
停止します。

## コアデータセット

| データセット | 分類 | 取得・準備 | 必要な出力 / 利用先 | 更新頻度 |
| --- | --- | --- | --- | --- |
| Driving OSM PBF | driving OSRM のコア | `scripts/download/download_osm.sh kanto` で Geofabrik から取得し、下記の検証済みパスへコピー/前処理する | `data_lake/validated/tokyo/osm/driving/kanto-260214.osm.pbf`; `osrm-driving` | 定期的に更新 |
| Walking OSM PBF | walking ルーティングのコア | Geofabrik がソース。下記の正確なパス向けに walking extract を準備する | `data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf`; `osrm-walking` | 定期的に更新 |
| DEM | 標高を考慮した結果のコア | 国土地理院の数値標高データを取得し、プロジェクトのデータ処理で変換・検証する | `data_lake/validated/tokyo/dem/elevation.tif`; publish 後の backend | 静的ソース。必要に応じて更新 |
| Flood hazard | 設定済み洪水判定のコア | KSJ A31 ZIP を手動取得し、`scripts/download/download_river_flood.sh` と正規化/フィルタを実行する | `data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl`; publish 後の backend | 定期的に更新 |
| Shelters | 避難所結果のコア | `scripts/download/download_emergency_shelter.sh` または `download_shelter.sh` で 国土地理院 GeoJSON を取得し、正規化/検証する | `data_lake/validated/tokyo/shelter/*.geojson` または `.csv`; publish 後の backend | 定期的に更新 |

OSM ダウンローダは `kanto` と `japan` のソース region に対応しています
（`--list-regions` で URL を表示）。指定した出力パスへ PBF と manifest を
書き出します。Compose ファイルは上記の固定バージョン名を使います。OSRM を
起動する前に、準備済みの入力を上記の正確なパスに配置してください。

### OSRM の前処理

Compose サービスは MLD 前処理を使います。

```text
PBF → osrm-extract → osrm-partition → osrm-customize → .osrm* artifacts
```

`osrm-driving` は `/opt/car.lua` と `kanto-260214` プレフィックスを使います。
`osrm-walking` は `osrm/foot.lua` と `tokyo-kanagawa-260214` プレフィックスを
使います。各サービスのコマンドは、対応する検証済みディレクトリに生成物が
無ければそれを生成します。前処理は CPU・メモリ・ディスク・時間を多く使う
場合があり、正確なホスト最小要件は定めていません。ルーティングサービスに
依存する前に、PBF が存在し、想定される `.osrm`・`.osrm.partition`・
`.osrm.mldgr`・`.osrm.cells`・`.osrm.fileIndex`・`.osrm.ramIndex` の各ファイルが
空でないことを確認してください。

### DEM

backend は publish 済みファイルを
`data_runtime/current/backend/elevation/elevation.tif`
（`/data_runtime/backend/elevation/elevation.tif` としてマウント）に期待します。
publish の入力は `data_lake/validated/tokyo/dem/elevation.tif` です。DEM ソースの
帰属は [国土地理院](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html)
です。[ATTRIBUTIONS.md](../ATTRIBUTIONS.md) を参照してください。

### 洪水およびその他のハザード

KSJ の洪水 A31 配布は手動ダウンロードのフローです。安定した直接ダウンロード
URL が確認できていないためです。ZIP を
[公式 A31 ページ](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html)
からダウンロードし、次を実行します。

```bash
scripts/download/download_river_flood.sh /path/to/A31.zip 13
```

このスクリプトはソースデータを検証し、既定で `data_lake/raw/tokyo/flood` へ
取り込みます。リポジトリの洪水正規化/フィルタのワークフローを実行して、
runtime 入力 `tokyo_flood_check.geojsonl` を作成してください。津波・高潮・
内水氾濫・土砂災害・低地排水の各パスは、`scripts/publish/deploy_to_runtime.sh`
によって normalized/validated のレイアウトから取り込まれます。設定済みの津波
ターゲットは `tokyo,kanagawa` です。ターゲットデータが欠けている場合は、
安全であるという主張ではなく、利用不可/不明の capability を返します。

## タイルと Martin

Martin はコンテナ化された MBTiles サーバーです。現在の Compose 構成には
PostGIS サービス・外部データベース接続・スキーマ・マイグレーション・seed
コマンドは宣言されていません。Martin は `data_runtime/current/frontend/tiles` を
`/tiles` として読み、`config/martin.yaml` がスキャンする MBTiles ディレクトリを
宣言します。`.mbtiles` を `data_lake/tiles/<region>/<hazard>/` の下に生成または
配置し、アトミックに publish してください。ディレクトリが無い場合、Martin は
警告を出して継続し、対応するレイヤーは利用不可になります。

## runtime の API データと任意サービス

JMA・Open-Meteo・JARTIC・ODPT は runtime のサービスであり、インストール時の
データセットではありません。ODPT は任意の鉄道情報機能に `ODPT_API_KEY` が
必要です。JARTIC と道路交通の設定は任意です。[設定](configuration.md) を
参照してください。これらのレスポンスはリポジトリにコミットされません。
Streamer のデータ/設定は任意で、個別に secret を持ちます。

## publish と検証

1. マッピングをプレビュー: `scripts/publish/deploy_to_runtime.sh --region tokyo --dry-run`。
2. 認可された operator ワークフローで、アトミックに publish:
   `scripts/publish/deploy_to_runtime_atomic.sh --region tokyo`。
3. `data_runtime/current/` が解決でき、想定される runtime ファイルを含むことを
   確認する。`data_runtime/manifests/` の下に生成される manifest を確認する。
4. 入力が存在するサービスのみを起動する。walking/driving の PBF が欠けていると
   対応する OSRM サービスはファイルチェックに失敗する。backend のデータセットが
   無いと degraded/不明な結果になる。

## 帰属と更新方針

ダウンロードスクリプトが生成するプロバイダー条件・ソース URL・取得時刻・
ハッシュを保持してください。OSM の帰属は ODbL の下で © OpenStreetMap
contributors です。国土地理院と KSJ の帰属/条件は
[ATTRIBUTIONS.md](../ATTRIBUTIONS.md) に記載しています。定期的なソース更新の
前に、毎回プロバイダーの条件を確認してください。ライセンスとリリース分類が
明示的にレビューされていない限り、raw の大規模データセット・生成された OSRM
生成物・runtime バージョン・ダウンロードした API レスポンスを決して
コミットしないでください。

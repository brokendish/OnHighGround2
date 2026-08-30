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

このガイドで扱う実データの準備・配備は、`docker compose up` でスタックを
起動できる状態にすることとは別工程です。データ未配備でも backend は degraded
起動します（fresh-start degraded ≠ full-data environment）。macOS Docker Desktop
向けの local runtime profile（`/data_runtime` を named volume 化）を使う場合、
named volume は初回は空で、本ガイドの配備手順を別途実施する必要があります
（[設定](configuration.md) の「local runtime profile」節）。

## コアデータセット

| データセット | 分類 | 取得・準備 | 必要な出力 / 利用先 | 更新頻度 |
| --- | --- | --- | --- | --- |
| Driving OSM PBF | driving OSRM のコア | `scripts/download/download_osm.sh kanto` で Geofabrik から取得し、下記の検証済みパスへコピー/前処理する | `data_lake/validated/tokyo/osm/driving/kanto-260214.osm.pbf`; `osrm-driving` | 定期的に更新 |
| Walking OSM PBF | walking ルーティングのコア | Geofabrik がソース。下記の正確なパス向けに walking extract を準備する | `data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf`; `osrm-walking` | 定期的に更新 |
| DEM | 標高を考慮した結果のコア | 国土地理院の数値標高データを取得し、プロジェクトのデータ処理で変換・検証する | `data_lake/validated/tokyo/dem/elevation.tif`; publish 後の backend | 静的ソース。必要に応じて更新 |
| Flood hazard | 設定済み洪水判定のコア | KSJ A31 ZIP を手動取得し、`scripts/download/download_river_flood.sh` と正規化/フィルタを実行する | `data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl`; publish 後の backend | 定期的に更新 |
| Shelters | 避難所結果のコア | `scripts/download/download_emergency_shelter.sh` または `download_shelter.sh` で 国土地理院 GeoJSON を取得し、正規化/検証する | `data_lake/validated/tokyo/shelter/*.geojson` または `.csv`; publish 後の backend | 定期的に更新 |

### 東京の指定緊急避難場所 GeoJSON

`data_runtime/backend/shelters/tokyo_emergency_evacuation_sites.geojson` は、
国土地理院の指定緊急避難場所データから再生成できる runtime 生成物です。Git
では管理しません。東京都の都道府県コードは `13000`、指定緊急避難場所の
カテゴリは `2`、取得するソースファイルは `13000_2.geojson` です。取得 URL は
`scripts/download/download_shelter_gsi_prefecture.sh` が国土地理院の公開配布先から
決定的に組み立てます。

前提条件は `bash`、`curl`、`python3`、`shasum`、および network access です。
必要な環境変数はありません。既存の GeoJSON を入力として使わず、空の作業場所で
次の2段階を実行します。

1. 国土地理院ソースを取得する。
2. OnHighGround2 の runtime 形式へ normalize する。

```bash
mkdir -p /tmp/ohg2-shelter/raw
scripts/download/download_shelter_gsi_prefecture.sh 13000 2 /tmp/ohg2-shelter/raw
python3 scripts/normalize/normalize_shelter_gsi_prefecture.py \
  --input /tmp/ohg2-shelter/raw/13000_2.geojson \
  --output data_runtime/backend/shelters/tokyo_emergency_evacuation_sites.geojson
```

生成後は、出力が `FeatureCollection` であり空でないこと、先頭featureの
propertiesに `NO`、`施設・場所名`、`住所`、`洪水`、`高潮`、`地震`、`津波` が
すべて存在することを確認してください。国土地理院データの利用条件と帰属は
[ATTRIBUTIONS.md](../ATTRIBUTIONS.md) を参照してください。

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
使います。OSRM の生成物にはformat互換性があります。`osrm-extract`、
`osrm-partition`、`osrm-customize` と `osrm-routed` は、Composeで固定された同一の
canonical OSRM versionを使用してください。OSRM image versionを変更した場合、旧版で
生成された `.osrm*` 一式を再利用せず、PBFから再生成します。

各生成物prefixには、成功した前処理の後に
`<prefix>.osrm.provenance.json` が生成されます。ここにはOSRM version、profile、入力
PBF名だけを記録します。起動時はこのmetadataと実行中のOSRM binary versionを照合し、
metadataの欠落・破損・不一致時はroutingを開始せず、明示的な再生成を要求します。
既存の大容量成果物を起動時に削除して自動再生成することはありません。

owner/local環境の既存成果物を安全に再生成するには、まずPBFが次の正確な入力pathに
存在することを確認し、repository rootで実行します。スクリプトは両profileの
`*.osrm*` を完全inventoryして一時backupへ退避してから、現行Composeのdigest固定
imageで `extract → partition → customize` を実行します。PBFは変更しません。

```bash
scripts/rebuild_osrm_artifacts.sh
```

backup先を明示する場合は次を使います。新成果物のroute検証が完了するまで、backupは
削除しないでください。

```bash
scripts/rebuild_osrm_artifacts.sh --backup-root /tmp/ohg2-osrm-backup
```

前処理はCPU・メモリ・ディスク・時間を多く使う場合があり、正確なホスト最小要件は
定めていません。ルーティングサービスに依存する前に、PBF、provenance metadata、
および `.osrm`・`.osrm.partition`・`.osrm.mldgr`・`.osrm.cells`・
`.osrm.fileIndex`・`.osrm.ramIndex` が空でないことを確認してください。これらの
generated artifactsとprovenance metadataはGit管理対象ではありません。

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

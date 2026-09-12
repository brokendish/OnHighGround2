# インストール

これは公開版 OnHighGround2 構成の正式なインストールガイドです。README は
方向付けのみを提供します。古いガイドを 2 つ目のインストール手順として
使わないでください。

## サポートされる実行モデルと前提条件

ドキュメント化されているデプロイモデルは、Linux Docker ホスト上の
Docker Compose です。macOS の Docker Desktop は想定される開発パスですが、
クリーンインストールのリリースターゲットとしては検証されていません。
Docker Desktop のファイルシステムとファイル所有権の挙動は Linux と
異なる場合があります。

Compose 構成には `linux/amd64` 向けに宣言された OSRM サービスが含まれます。
ネイティブ arm64 での動作、Windows ネイティブのデプロイ、非 Docker のデプロイ、
Kubernetes のデプロイは本ガイドでは検証していません。Docker や Compose の
最小バージョンは定めていません。現行の Docker Engine もしくは Compose v2
プラグイン付きの Docker Desktop をインストールし、`docker compose` コマンドを
使ってください。

以下をインストールまたは用意してください。

- Git（リポジトリの取得用）
- Docker Engine または Docker Desktop
- Docker Compose v2（`docker compose version`）
- 公開 UI 用のサポートされた Web ブラウザ

地理データの完全な準備と OSRM の前処理には、多くのディスク・メモリ・CPU を
必要とする場合があります。正確なホストリソースの最小要件は定めていません。
以下のデータ無し公開 smoke パスは、フルデータのデプロイを表すものでは
ありません。

## 1. クローンと公開構成の準備

```bash
git clone https://github.com/brokendish/OnHighGround2.git
cd OnHighGround2
cp .env.example .env
```

`.env` は Compose にとって任意ですが、値が必要な場合の公開構成ファイルです。
ローカル限定であり、コミットしないでください。API キーなどの値を追加する前に
[設定](configuration.md) を参照してください。

public-core のパスでは `.env.operator` を作成しないでください。operator は
任意かつ privileged なコンポーネントであり、手順は
[Operator セットアップ](operator-setup.md) に分離されています。

## 2. runtime ディレクトリの準備

公開サービスはデプロイ済みの runtime データを読み込みます。既存の publish
スクリプトで runtime ディレクトリを準備してください。

```bash
scripts/publish/deploy_to_runtime.sh --region tokyo --dry-run
scripts/publish/deploy_to_runtime.sh --region tokyo
```

地理データを準備していない場合、アプリケーションは degraded な状態で起動する
ことがあります。これは smoke 確認にのみ有用で、標高・ハザード・ルーティング・
地図コンテンツは完全ではありません。正式なデータセット一覧・取得・準備・
アトミックな publish フローは [データ準備](data-setup.md) に従ってください。

## 3. public-core の smoke パスの起動

```bash
docker compose build backend-public
docker compose up -d backend-public frontend
```

`runtime-init` は `backend-public` の前に自動で起動されます。このコマンドは
任意の operator profile や streamer profile を起動しません。

hazard 判定（HazardEngine）は `runtime-init` が初期化する atomic runtime
lease機構が前提であり、それが未導入の環境向けの legacy flat fallback は
サポートされないデプロイモードとして廃止済みです。

公開エンドポイントを確認します。

```bash
curl -fsS http://localhost:8080/health
```

ブラウザで <http://localhost:8080/> を開きます。利用可能なデータに応じて、
health ステータスが `ok` または `degraded` になるのは想定内です。

## 4. 準備済みデータを使うコンポーネント

必要な地理データと生成物が揃ったら、必要なコンポーネントを明示的に
起動します。

```bash
docker compose up -d osrm-walking backend-public frontend martin
docker compose --profile driving up -d osrm-driving
```

OSRM には対応する準備済み PBF と派生生成物が必要です。Martin には準備済みの
タイルデータが必要です。サービスコンテナが起動するというだけで、これらが
任意になるわけではありません。今後提供されるフルデータガイドを完了してから
使ってください。

OSRM や Martin へ loopback で直接アクセスする必要があるローカル開発では、
既定のデプロイコマンドではなく、明示的な開発用オーバーライドを使ってください。

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d martin
```

## 5. 任意のコンポーネント

以下はいずれも public-core の初回起動コマンドに追加しないでください。

- **Operator:** privileged かつ既定で無効です。
  [Operator セットアップ](operator-setup.md) を参照してください。
- **Streamer:** 任意でリソースを多く消費し、個別の設定と secret が必要で、
  `--profile streamer` を指定したときのみ有効になります。

Playwright / npm は開発・テスト用の依存であり、公開 runtime の前提条件では
ありません。

`/live` と `/live/stream` の背景地図は CARTO Basemaps の API キー（任意の
`CARTO_BASEMAP_API_KEY`）を使います。未設定でもアプリは起動し、背景地図は
キー不要の OpenStreetMap タイルへフォールバックします。設定する場合は `.env`
に1行追加するだけです（詳細は [設定](configuration.md) §8）。

```bash
cp .env.example .env   # 未作成の場合
vi .env                # CARTO_BASEMAP_API_KEY=your_key_here を設定
docker compose up -d frontend
```

## 6. local runtime profile（macOS Docker Desktop 向け・任意）

macOS の Docker Desktop では host bind mount の所有権正規化・I/O 性能に難が
あるため、`/data_runtime` を Docker 管理の named volume へ切り替える opt-in
プロファイルを用意しています。Linux Docker ホストでは不要です。

`docker-compose.override.example.yml` の「B: local runtime profile」ブロックが
`runtime-init` / `backend-public` / `martin` の `/data_runtime` を named volume
（`data-runtime` / `data-runtime-logs` / `data-runtime-cache`）へ差し替えます。
新規 named volume の root は `root:root` で作られ backend-public（UID 10001）が
`logs` / `cache` へ書き込めないため、**`up` の前に一度だけ** bootstrap helper を
実行して所有権（`10001:10001`）と nested mountpoint を用意します。

```bash
cp docker-compose.override.example.yml docker-compose.override.yml
scripts/local/bootstrap_runtime_volumes.sh          # named volume + 所有権 + mountpoint
docker compose up -d backend-public frontend        # runtime-init は自動で先行実行される
```

- helper は idempotent（何度実行してもよい）で、`.publish.lock` / `.staging` /
  `versions` は作りません（それらは `runtime-init` の責務）。
- Martin は `config/martin-local.yaml`（`config/martin.yaml` のタイル参照ルートを
  `/data_runtime/frontend/tiles` へ付け替えただけのもの）を使います。helper が
  参照先ディレクトリを空で事前作成するため、タイル未配備でも Martin は
  起動します（当該レイヤーが catalog に出ないだけ）。
- named volume は初回は空です。DEM・ハザード・タイルの実データ配備は別手順
  （[データ準備](data-setup.md)）。データ無しでも backend は degraded 起動します。

## サービスの停止

```bash
docker compose down
```

これはコンテナと network を削除しますが、名前付き volume は保持します。
`docker compose down -v` を通常のシャットダウンとして使わないでください。
名前付き volume を削除し、ローカルに保持している状態を失う可能性があります。

## よくある初期確認

| 症状 | 確認 |
| --- | --- |
| `frontend` に到達できない | `docker compose ps` を実行し、`docker compose logs frontend` を確認する。 |
| health が `degraded` | runtime データがデプロイされたか確認する。フルデータの準備は依然必要。 |
| OSRM が終了する | 起動前に、必要な準備済み PBF / 生成物が存在するか確認する。 |
| 公開側の `/admin` URL が使えない | 想定内。operator アクセスは [Operator セットアップ](operator-setup.md) に従う。 |

次に [設定](configuration.md) を確認し、privileged な管理が実際に必要な場合のみ
[Operator セットアップ](operator-setup.md) を使ってください。

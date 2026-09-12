# 設定・環境変数の扱い

このドキュメントは、現在の Compose 構成で使う設定ファイルについて説明します。
インストールの順序については、まず [インストール](installation.md) を参照して
ください。

## 1. example env ファイル一覧

| ファイル | 対象 | コピー先 | 参照元 |
|---|---|---|---|
| `.env.example`（リポジトリroot） | public backend（backend-public） + browser-visible 公開設定 | リポジトリroot直下の`.env` | `docker-compose.yml`の`backend-public.env_file`（`path: .env`, `required: false`）、および`frontend`の`environment`（`CARTO_BASEMAP_API_KEY`） |
| `.env.operator.example` | operator backend（backend-operator） | リポジトリroot直下の`.env.operator` | `docker-compose.yml`の`backend-operator.env_file`（`path: .env.operator`, `required: false`） |
| `.env.stream.example` | streamer（`--profile streamer`、既定非起動） | リポジトリroot直下の`.env.stream` | `docker-compose.yml`の`streamer.env_file`（`path: .env.stream`, `required: false`） |

いずれも`required: false`のため、ファイルが存在しなくてもcompose自体は起動する（各serviceの起動時検証がfail-closedで必要な秘密の欠如を検出する設計、後述4節）。

`.env.example`（リポジトリroot） は canonical な単一のテンプレートです
（`cp .env.example .env`）。旧 `backend/.env.example` は internal な
責務調査の結果、これとは別の standalone contract を持たないことを確認した
ため、内容をここへ統合し、`backend/.env.example` 自体は deprecated stub
（参照リダイレクトのみ）にしました（後述 7.1 節）。

`.env` に置く値のうち `ODPT_API_KEY` 等は server-side secret ですが、
`CARTO_BASEMAP_API_KEY` はブラウザから参照可能な公開設定です（後述 7・8 節）。
同じファイルに同居しますが扱いが異なるため混同しないでください。

## 2. 環境変数の分類（public backendが実際に参照するもの）

`app_public.py`とそこからimportされる各`app/api/*.py`・`app/services/*.py`を対象に、実コードのgrep（`os.environ.get`/`os.getenv`）で洗い出した。

| 変数 | 分類 | secret | 既定値未設定時の挙動 |
|---|---|---|---|
| `ODPT_API_KEY` | public-optional | secret | 鉄道運行情報機能が無効化される（fail-closedで起動停止はしない） |
| `ODPT_API_BASE_URL` | public-optional | non-secret | 既定URLを使用 |
| `ODPT_EXCLUDE_KEYWORDS` | public-optional | non-secret | フィルタなし |
| `JARTIC_TRAFFIC_BASE_URL` | public-optional | non-secret | 既定URLを使用 |
| `JARTIC_TRAFFIC_USE_MOCK` | development-only | non-secret | false（実API呼び出し） |
| `ROAD_TRAFFIC_API_BASE_URL` | public-optional | non-secret | 既定URLを使用 |
| `ROAD_TRAFFIC_USE_MOCK` | development-only | non-secret | false |
| `MARTIN_INTERNAL_URL` | public-optional | non-secret | 既定URLを使用 |
| `OHG2_DATA_RUNTIME_ROOT` | public-optional | non-secret | `data_runtime/`を使用 |
| `APP_PROPERTIES_FILE` | public-optional | non-secret | `backend/app.properties`を使用 |
| `OHG2_DEV_MODE` | development-only | non-secret | 未設定（開発docsは無効のまま） |
| `OHG2_DEV_DOCS_ENABLED` | development-only | non-secret | 同上 |
| `DEV_EARTHQUAKE_PUBLISH` | development-only | non-secret | 未設定（デバッグ公開なし） |
| `DEM_FILE_PATH` | public-required | non-secret | `docker-compose.yml`の`environment:`で`/data_runtime/backend/elevation/elevation.tif`に固定設定（`.env`側での上書きは通常不要） |
| `API_HOST` / `API_PORT` | public-required | non-secret | 同上、compose側で固定設定済み |
| `OHG2_LEASE_TTL_SECONDS` | public-optional | non-secret | compose側で既定30秒 |

`OPERATOR_AUTH_SECRET`・`SIMULATION_REPORT_DIR`・`SIMULATION_SCENARIOS_DIR`・`OHG2_LEASES_GID`等はoperator専用（`backend-operator`・`runtime-init`のみが参照）であり、public backendの起動には関与しない。詳細は[docs/operator-setup.md](operator-setup.md)を参照。

CORS設定（`cors.allow_origins`等）は環境変数ではなく`backend/app.properties`のkey-value形式で設定する（exact-origin allowlist、fail-closed。詳細はコメント参照）。

## 3. example値の方針

- 実秘密は一切使用しない（`ODPT_API_KEY=`は空、コメントで取得方法のみ案内）。
- wildcard origin（`cors.allow_origins=*`等）はexample・既定値のいずれにも含めない。
- production hostname・実VPS IP・private registry credentialは一切記載しない。
- operator secretに弱い固定defaultは置かない（`.env.operator.example`の`OPERATOR_AUTH_SECRET=`は空、`openssl rand -hex 32`等での生成を案内）。
- APIキーが不要なsource（気象庁・国土数値情報等）には、不要なキー欄を設けない。

## 4. missing secret時のfail-closed動作

- `backend-operator`は`OPERATOR_AUTH_SECRET`が未設定・空文字・空白のみの場合、起動時検証で非0 exit codeとなり起動しない（`backend/app_operator.py`）。
- `backend-public`のCORS設定（`cors.allow_origins`）は、値が1件でも構文違反（wildcard・path付き・空白付き等）を含む場合、起動時にfail-closedで停止する（`backend/app_config_properties.py::parse_cors_origins`）。
- `ODPT_API_KEY`未設定は起動停止を伴わない機能単位のoptional欠如として扱われる（上記2節参照）。

## 5. ローカルでの secret の扱い

`.env`・`.env.operator`・`.env.stream` は、それぞれの任意の値が必要になった
ときにのみローカルで作成してください。Git の管理外に置き、ホストの通常の
secret 取り扱い方針に従ってローカルファイルへのアクセスを制限してください。
リポジトリは実際の secret 値や production ホストの設定を提供しません。

## 6. コンテナイメージの pin 更新方針

リリースに影響するイメージ参照は、Compose ファイルと backend Dockerfile 内で、
明示的なバージョンと OCI manifest-list digest に pin されています。更新する
際は、レビュー済みの upstream バージョンを選び、対応アーキテクチャ向けの
manifest-list digest を取得し、バージョンと digest を同時に更新し、merge の
前に `docker compose config` と該当する build/test チェックを実行してください。
pin を `latest` や `alpine` のような浮動タグに置き換えないでください。

## 7. ランタイム設定の分離（browser-visible 公開設定 / server-side secret）

OnHighGround2 の設定は 2 系統に分かれます。混在させないでください。

| 種別 | 保存場所 | Git 管理 | ブラウザから参照可能 | 例 |
|---|---|---|---|---|
| ランタイム公開設定（browser-visible） | `.env`（`CARTO_BASEMAP_API_KEY`） | 対象外 | Yes | `CARTO_BASEMAP_API_KEY` |
| backend secret | `.env`（`ODPT_API_KEY` 等） | 対象外 | No | `ODPT_API_KEY` |
| operator secret | `.env.operator` | 対象外 | No | `OPERATOR_AUTH_SECRET` |
| stream secret | `.env.stream` | 対象外 | No | YouTube ストリームキー等 |

「ランタイム公開設定」は、最終的にブラウザへ配信されても許容される値だけを
置きます。CARTO タイルはブラウザが直接取得するため、`CARTO_BASEMAP_API_KEY`
はここに該当します（サーバー側で秘匿できる secret ではありません）。ただし
backend secret（`ODPT_API_KEY` 等）と同じ `.env` ファイルに書きますが、扱いは
別物です。backend secret はサーバー側にとどまりますが、`CARTO_BASEMAP_API_KEY`
はブラウザへそのまま配信されます。混同しないでください。

### 7.1 単一の設定入口（`.env`）と生成の仕組み

利用者が編集する場所は `.env` の `CARTO_BASEMAP_API_KEY` だけです。

```text
1. .env の CARTO_BASEMAP_API_KEY          … 利用者が編集する唯一の入口
2. docker-compose.yml の frontend.environment  … .env の値を container へ渡す
3. config/runtime-config.template.js（tracked）… envsubst 用テンプレート
4. scripts/frontend/generate_runtime_config.sh … frontend 起動時（docker-entrypoint.d）に
                                                   1 を検証・埋め込み、
                                                   /run/ohg2/runtime-config.js を生成
5. nginx.conf の `location = /js/shared/runtime-config.js`
                                                … 4 の生成物へ alias 配信
6. ランタイムコード（frontend/js/shared/basemap.js 等）
                                                … window.OHG2_RUNTIME_CONFIG のみ参照（無変更）
```

frontend root（`./frontend`）は read-only bind mount のため、生成物はその外側
（コンテナ自身の書き込み可能な `/run/ohg2/`）に書き、nginx が exact-match
location でそこへ配信します。`frontend/js/shared/runtime-config.js`（tracked
default）は書き換えません。

`.env` が無い・`CARTO_BASEMAP_API_KEY` が空文字の場合は空文字を埋め込み、
フロント側の既存ロジック（`frontend/js/shared/basemap.js`）が OpenStreetMap
フォールバックを判定します（§8.2）。

生成スクリプトは、値をそのまま JS 文字列へ埋め込む前に文字種
（英数字・`.`・`_`・`-`）を検証し、想定外の文字が含まれる値は安全側で
「未設定」として扱います（injection 対策。詳細はスクリプト内コメント参照）。

#### レガシー経路（`config/runtime-config.local.js` + `docker-compose.override.yml`）

以前からの `config/runtime-config.local.js` + `docker-compose.override.yml`
（§8.4 旧版）による設定は、後方互換のフォールバックとして今も機能します。
`.env` の `CARTO_BASEMAP_API_KEY` が空の場合のみ、生成スクリプトが
`frontend/js/shared/runtime-config.js`（override.yml が実ファイルを bind mount
している場合はその内容）から値を読み取って使います。新規セットアップでは
この経路を使う必要はありません。

## 8. 背景地図の API キー（`CARTO_BASEMAP_API_KEY`）

### 8.1 何に使うか

`/live`（全国災害ビューア）と `/live/stream`（配信画面）の背景地図には、
CARTO Basemaps の `dark_all` ラスタタイルを使います。CARTO Basemaps は
2026-08 に API キーが必須化されたため、キーを設定しないと地図に
「API KEY REQUIRED」のウォーターマークが表示されます。

トップ画面 `/` は OpenStreetMap のラスタタイルを直接使うため、この設定は
不要です（`CARTO_BASEMAP_API_KEY` は任意設定です）。

### 8.2 未設定時の挙動（フォールバック）

`CARTO_BASEMAP_API_KEY` が未設定・空・プレースホルダー（`YOUR_KEY` 等）の
場合、`/live`・`/live/stream` の背景地図はキー不要の OpenStreetMap ラスタ
タイル（`/` と同じプロバイダー）へ自動的にフォールバックします。CARTO へは
一切リクエストを送りません（`?key=` 空のリクエストも送りません）。

フォールバック時も地図・災害オーバーレイ・ナビゲーション UI はすべて動作
します。CARTO 固有の暗色スタイルではなくなりますが、操作不能にはなりません。
アプリケーションの起動が CARTO の可用性に依存することはありません。

### 8.3 キーの取得

各利用者が自分自身で CARTO 公式ページから取得します。公開リポジトリは
実キーを提供しません。

- 取得先: <https://carto.com/basemaps/apikey/>

### 8.4 設定方法

このキーはブラウザから参照可能な公開設定値です（§7 参照。詳細は
[SECURITY.md](../SECURITY.md)）。他人のキーを配布しないため、また課金の
観点から、実キーはリポジトリへコミットしないでください。

1. `.env` を用意する（まだ無ければ。`.env` は `.gitignore` 済み）。

   ```bash
   cp .env.example .env
   ```

2. `.env` を編集して `CARTO_BASEMAP_API_KEY` に自分のキーを設定する。

   ```bash
   CARTO_BASEMAP_API_KEY=your_key_here
   ```

3. frontend を再作成する。

   ```bash
   docker compose up -d frontend
   ```

これだけで完了します。Compose override（`docker-compose.override.yml`）の作成
やコピー手順は不要です。

Docker を使わず静的配信する場合は、`frontend/js/shared/runtime-config.js`
（tracked default）と同じ形の JS を、配信ルートの `js/shared/runtime-config.js`
として自分で用意してください（tracked ファイル自体は書き換えてコミットしない）。

### 8.5 設定できたことの確認

- `/live` と `/live/stream` の背景地図に「API KEY REQUIRED」ウォーター
  マークが表示されない。
- ブラウザの開発者ツール（Network タブ）で `basemaps.cartocdn.com` への
  タイルリクエストに `key=` パラメータが付いており、HTTP エラーが出ない。
- 地図右下の出典表示に OpenStreetMap（ODbL）と CARTO が表示されている。

### 8.6 CARTO Basemaps 利用規約について

CARTO Basemaps の利用規約には、車両向けのリアルタイム turn-by-turn
ナビゲーションや移動中の車両・航空機での地図表示に関する制限があります。
OnHighGround2 は徒歩避難ナビゲーションを主用途とし、`/live`・`/live/stream`
での CARTO の用途は「見るための全国状況モニター地図の背景」に限られます。
本キー対応でアプリケーションの機能や用途は変更していません。

## 9. local runtime profile（macOS Docker Desktop 向け・任意）

`docker-compose.override.yml`（`docker-compose.override.example.yml` から作成、
Git 管理外）は `/data_runtime` を host bind mount から named volume へ
切り替える local runtime profile 専用です（CARTO 等のランタイム公開設定は
§7.1 のとおり `.env` だけで完結するため、この override は不要になりました）。

### 9.1 行う差し替え

| mount | base（Linux 想定） | local runtime profile |
|---|---|---|
| `/data_runtime`（親） | host bind `./data_runtime`（backend は `:ro`） | named volume `data-runtime`（backend は `:ro`） |
| `/data_runtime/logs` | host bind（rw） | 専用 named volume `data-runtime-logs`（rw） |
| `/data_runtime/cache` | host bind（rw） | 専用 named volume `data-runtime-cache`（rw） |
| Martin タイル参照 | `./data_runtime/frontend/tiles` → `/tiles`、`config/martin.yaml` | `data-runtime` を `/data_runtime:ro`、`config/martin-local.yaml` |

named volume 名は `${COMPOSE_PROJECT_NAME}` を前置します。plain な
`docker compose` ではプロジェクトディレクトリ名（`onhighground2`）が既定値、
`-p <名前>` で名前空間を分離できます（CODEX の disposable qualification 用）。

### 9.2 bootstrap helper が必要な理由

Docker が新規作成する named volume の root は `root:root` です。
`/data_runtime/logs` と `/data_runtime/cache` を専用 child named volume にすると、
backend-public（UID/GID `10001:10001`）が書き込めません。`runtime-init`
（root, one-shot）は `.staging` / `versions` / `.publish.lock` だけを扱い
logs/cache には関与しないため、`scripts/local/bootstrap_runtime_volumes.sh` が
opt-in の前処理として次を行います（idempotent・非破壊）。

1. 対象 named volume を作成（既存なら no-op）
2. 共有 runtime volume 内へ nested mountpoint を作成
   （`logs` / `cache` / `backend` / `frontend/tiles/<region>/<hazard>` 一式。
   最後のものは `config/martin-local.yaml` から動的に導出）
3. `logs` / `cache` child volume の root を `10001:10001` / mode `0750` に設定

helper は `.publish.lock` / `.staging` / `versions` を作りません（`runtime-init`
の責務を奪わない）。実行順は helper → `docker compose up`（`runtime-init` →
`backend-public`）。

### 9.3 Martin local config（`config/martin-local.yaml`）

`config/martin.yaml` との差分はタイル参照ルートの付け替えのみ
（`/tiles/<region>/<hazard>` → `/data_runtime/frontend/tiles/<region>/<hazard>`）。
`listen_addresses`・スキャン方式・その他の datasource semantics は無変更で、
`mbtiles.paths` の各エントリは production config と 1:1 で一致します。

Martin 1.14.0 は `mbtiles.paths` に列挙した path がディスク上に存在しないと
fatal 終了します（存在すれば空でも起動継続）。そのため bootstrap helper が
参照先ディレクトリを空で事前作成し、タイル未配備でも Martin が起動できる
ようにしています。`config/martin.yaml`（production）自体は変更していません。

### 9.4 データ配備は別手順

named volume は初回は空です。DEM・ハザード・タイル・避難所の実データ配備は
[データ準備](data-setup.md) の手順であり、この profile の範囲外です。
データ無しでも backend は degraded 起動します（fresh-start degraded ≠ full-data）。

## 10. 関連ドキュメント

- [docs/installation.md](installation.md) — clean clone からの起動手順
- [docs/operator-setup.md](operator-setup.md) — operator 構成の信頼境界
- [SECURITY.md](../SECURITY.md) — セキュリティ報告の状況と境界の要約
- [ATTRIBUTIONS.md](../ATTRIBUTIONS.md) — 外部 API キーが関連する第三者サービスの利用条件

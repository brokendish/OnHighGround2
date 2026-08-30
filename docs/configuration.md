# 設定・環境変数の扱い

このドキュメントは、現在の Compose 構成で使う設定ファイルについて説明します。
インストールの順序については、まず [インストール](installation.md) を参照して
ください。

## 1. example env ファイル一覧

| ファイル | 対象 | コピー先 | 参照元 |
|---|---|---|---|
| `backend/.env.example` | public backend（backend-public） | リポジトリroot直下の`.env` | `docker-compose.yml`の`backend-public.env_file`（`path: .env`, `required: false`） |
| `.env.operator.example` | operator backend（backend-operator） | リポジトリroot直下の`.env.operator` | `docker-compose.yml`の`backend-operator.env_file`（`path: .env.operator`, `required: false`） |
| `.env.stream.example` | streamer（`--profile streamer`、既定非起動） | リポジトリroot直下の`.env.stream` | `docker-compose.yml`の`streamer.env_file`（`path: .env.stream`, `required: false`） |

いずれも`required: false`のため、ファイルが存在しなくてもcompose自体は起動する（各serviceの起動時検証がfail-closedで必要な秘密の欠如を検出する設計、後述4節）。

上記はいずれも server-side secret 用です。ブラウザから参照可能なランタイム
公開設定（`CARTO_BASEMAP_API_KEY` 等）は別系統で、`config/runtime-config.example.js`
を `config/runtime-config.local.js` へコピーして設定します（後述 7・8 節）。

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
| ランタイム公開設定（browser-visible） | `config/runtime-config.local.js` | 対象外 | Yes | `CARTO_BASEMAP_API_KEY` |
| backend secret | `.env` | 対象外 | No | `ODPT_API_KEY` |
| operator secret | `.env.operator` | 対象外 | No | `OPERATOR_AUTH_SECRET` |
| stream secret | `.env.stream` | 対象外 | No | YouTube ストリームキー等 |

「ランタイム公開設定」は、最終的にブラウザへ配信されても許容される値だけを
置きます。CARTO タイルはブラウザが直接取得するため、`CARTO_BASEMAP_API_KEY`
はここに該当します（サーバー側で秘匿できる secret ではありません）。backend /
operator / stream の secret はこの経路へ入れないでください。

### 7.1 3 層構成

```text
1. tracked default / 配信ターゲット : frontend/js/shared/runtime-config.js（空値。直接編集しない）
2. Git 管理外のローカル設定          : config/runtime-config.local.js（実値。example をコピーして作成）
3. ランタイムコード                  : frontend/js/shared/basemap.js 等（window.OHG2_RUNTIME_CONFIG のみ参照）
```

利用者が編集するのは 2 の `config/runtime-config.local.js` だけです。1 の
`frontend/js/shared/runtime-config.js` は「デフォルト値の保持」と「ローカル設定の
配信先（bind-mount のマウント先）」に役割を限定しており、直接編集しません。

優先順位: `tracked default（空値）` < `config/runtime-config.local.js`。
これは `.env` 系の server-side 設定とは別系統です。

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

1. example をコピーしてローカル設定ファイルを作る（`config/runtime-config.local.js`
   は `.gitignore` 済み）。

   ```bash
   cp config/runtime-config.example.js config/runtime-config.local.js
   ```

   `config/runtime-config.local.js` を編集して自分のキーを設定する。

   ```javascript
   window.OHG2_RUNTIME_CONFIG = {
     CARTO_BASEMAP_API_KEY: '<自分のCARTOキー>',
   };
   ```

2. Compose の override を用意する（`docker-compose.override.yml` は `.gitignore`
   済み。`docker compose` が自動でマージします）。

   ```bash
   cp docker-compose.override.example.yml docker-compose.override.yml
   ```

   この override は `config/runtime-config.local.js` を frontend コンテナの
   `/usr/share/nginx/html/js/shared/runtime-config.js` へ read-only mount します。

3. frontend を再作成する。

   ```bash
   docker compose up -d frontend
   ```

Docker を使わず静的配信する場合は、`config/runtime-config.local.js` の内容を
配信ルートの `js/shared/runtime-config.js` へ配置してください（tracked ファイルを
直接書き換えてコミットしないよう注意）。

#### 旧方式からの移行

以前 `frontend/js/shared/runtime-config.local.js` を使っていた場合は、内容を
`config/runtime-config.local.js` へ移し、`docker-compose.override.yml` の
マウント元を `./config/runtime-config.local.js` に変更してください。旧パスは
不要なら削除して構いません（設定経路は 1 本に保ちます）。

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
Git 管理外）は 2 つの独立した用途を担います。片方だけ使う場合は不要な側の
ブロックを削除して構いません。

| ブロック | 目的 | 対象 service |
|---|---|---|
| A | CARTO 等のランタイム公開設定を frontend へ差し込む（§8） | `frontend` |
| B | `/data_runtime` を host bind mount から named volume へ切り替える | `runtime-init` / `backend-public` / `martin` |

### 9.1 B が行う差し替え

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
